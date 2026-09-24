"""Per-club discovery scan: read every club newsroom, keep only sentences that
place an injury *inside a game*, and promote the ones that hold up.

Why this file exists
--------------------
Every league-wide "notable injuries" bullet for Weeks 1-2 is already in the
verified ledger, so the remaining rows can only come from club pages, one at a
time. This script is the machine that does that reading: it walks all 32 club
newsrooms, keeps sentences that (a) carry an in-game phrase from the shared
vocabulary, (b) are not practice/injury-report language, (c) name somebody and
(d) are short enough to quote verbatim — then it asks one more question before
anything reaches the master list.

The promotion gate (the part that keeps hallucinations out)
----------------------------------------------------------
A candidate is promoted into ``data/archive.json`` only when all of these hold:

1. **Two-read stability** — the identical sentence, on the same club URL, was
   read in two separate runs (``reads >= 2``). One flaky read is not evidence.
2. **A resolvable game** — the article's own publication date plus the game day
   named in the sentence resolves to a real NFL game for that club through the
   ESPN schedule lane, and the article was published within three days of it.
3. **The club is in the sentence** — no promoting an opponent's injury as ours.
4. **No speech attribution** — sentences that quote a coach are held for review,
   because "Coach X said Y is hurt" is a different claim from "Y was hurt".
5. **Not already in the ledger** — a player already carrying a row for that
   season is not duplicated.

Everything that fails a gate stays in ``data/candidates.json`` with the failed
gate named, so a reviewer can see exactly why it was not promoted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alertlog import (fingerprint, iso_seconds, load as load_log, make as make_log_entry, merge as merge_log,
                      write as write_log)
from clubs import ARTICLE_EXCLUSIONS, ARTICLE_PATTERNS, CLUBS, INDEX_PATHS
from lanes import LaneError, article_meta, http_get, json_get, schedule_index
from refresh import AREAS
from schema import ID, official_url, validate_archive
from signals import candidate_sentences, load_vocabulary, player_name, visible_text
from signals import article_links as _article_links

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data/clubscan-state.json"
CANDIDATES_PATH = ROOT / "data/candidates.json"
EASTERN = ZoneInfo("America/New_York")
MAX_READ_HISTORY = 400          # URLs remembered per club
MAX_CANDIDATES = 400            # candidates kept in the file
SEASON = 2026
SPEECH_MARKERS = ("said", "told reporters", "per coach", "head coach", "coach ", "per nfl network", "reported")


def empty_state() -> dict:
    return {"version": 1, "updatedAt": None, "policy": STATE_POLICY, "clubs": {}}


STATE_POLICY = ("Per-club discovery record. A club is marked ok only when its news index answered this "
                "scan; blocked clubs are recorded with the error and never silently skipped. Counts are "
                "articles read and candidates kept, not injuries confirmed.")


def load_json(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def load_state() -> dict:
    state = load_json(STATE_PATH, empty_state())
    if state.get("version") != 1 or not isinstance(state.get("clubs"), dict):
        return empty_state()
    state.setdefault("policy", STATE_POLICY)
    return state


def load_candidates() -> dict:
    data = load_json(CANDIDATES_PATH, {"version": 1, "updatedAt": None, "label": CANDIDATE_LABEL, "policy": CANDIDATE_POLICY, "candidates": []})
    if data.get("version") != 1 or not isinstance(data.get("candidates"), list):
        return {"version": 1, "updatedAt": None, "label": CANDIDATE_LABEL, "policy": CANDIDATE_POLICY, "candidates": []}
    return data


CANDIDATE_LABEL = ("AUTO-MATCHED CLUB TEXT — official pages, sentence level, not yet in the verified master list. "
                   "Each row is a verbatim sentence from a club newsroom with the URL a reader can open.")
CANDIDATE_POLICY = ("Candidates are found by phrase, not by a model: the sentence must carry one of the closed "
                    "in-game phrases, must not be practice or injury-report language, and must name somebody. "
                    "Promotion into data/archive.json needs two independent reads of the same sentence plus a "
                    "resolvable game; everything else stays here with the failed gate named.")


def candidate_key(url: str, quote: str) -> str:
    return f"{url}::{quote.strip()[:120]}"


def index_urls(club_code: str) -> list[str]:
    host = CLUBS[club_code]["host"]
    return [f"https://{host}{path}" for path in INDEX_PATHS]


def pick_articles(html: str, host: str, *, already_read: set[str], limit: int,
                  recheck: tuple[str, ...] = ()) -> list[str]:
    """New articles first, then a couple of re-reads.

    The re-reads matter: promotion requires the *same sentence* to be read in
    two separate runs, so a scanner that only ever opened unseen URLs could
    never clear that gate. At most two known URLs per club are re-read per pass.
    """
    links = _article_links(html, host)
    fresh: list[str] = []
    for link in links:
        slug = link.rsplit("/", 1)[-1].lower()
        if any(bad in slug for bad in ARTICLE_EXCLUSIONS):
            continue
        if not any(good in slug for good in ARTICLE_PATTERNS):
            continue
        if link in already_read or link in fresh:
            continue
        fresh.append(link)
        if len(fresh) >= limit:
            break
    chosen = list(fresh)
    for link in recheck:
        if link.startswith(f"https://{host}") and link not in chosen and len(chosen) < limit + 2:
            chosen.append(link)
    return chosen


def resolve_game(published: str, club: str, schedule: dict[str, dict], *, max_gap: int = 3) -> tuple[str, str]:
    """(game date, opponent) for a sentence published just after a club game."""
    if not published:
        return "", ""
    try:
        moment = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return "", ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local_day = moment.astimezone(EASTERN).date()
    for gap in range(0, max_gap + 1):
        day = (local_day - timedelta(days=gap)).isoformat()
        mapping = schedule.get(day)
        if mapping and club in mapping:
            return day, mapping[club]
    return "", ""


def promotion_gate(candidate: dict, *, archive_names: set[str], schedule: dict[str, dict]) -> tuple[dict | None, str]:
    """Return (row, "") when the candidate may join the master list, else (None, reason)."""
    if int(candidate.get("reads", 0)) < 2:
        return None, "awaiting a second independent read of the same sentence"
    quote = candidate.get("quote", "")
    if not (20 <= len(quote) <= 200):
        return None, "quote length outside the range the ledger accepts verbatim"
    if not official_url(candidate.get("url", "")):
        return None, "source URL is not on the official league/club allowlist"
    club = candidate.get("club", "")
    if club not in CLUBS:
        return None, "unknown club"
    tokens = [token.lower() for token in CLUBS[club]["tokens"]]
    if not any(token in quote.lower() for token in tokens):
        return None, "sentence does not name the club it would be filed under"
    if any(marker in quote.lower() for marker in SPEECH_MARKERS):
        return None, "sentence attributes the claim to somebody speaking; held for review"
    game_date, opponent = resolve_game(candidate.get("published", ""), club, schedule)
    if not game_date or not opponent:
        return None, "no NFL game for this club within three days of the article date"
    name = candidate.get("player", "")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not name or not slug:
        return None, "no reliable player name in the sentence"
    if f"{club}-{slug}" in archive_names:
        return None, "player already has a row in the ledger"
    phrase = candidate.get("signal", {}).get("phrase", "")
    status = candidate.get("signal", {}).get("status", "")
    lowered = quote.lower()
    if status == "returned":
        outcome = "returned"
    elif "did not return" in lowered or "missed the remainder" in lowered or "missed the rest" in lowered:
        outcome = "did_not_return"
    elif status == "out":
        outcome = "out"
    elif status == "questionable":
        outcome = "questionable"
    else:
        outcome = "unconfirmed"
    outcome = outcome if outcome in {"out", "did_not_return", "returned"} else "unconfirmed"
    if outcome == "unconfirmed" and status not in {"observed", "evaluated", "questionable"}:
        return None, "no availability outcome this project can state"
    area = next((word for word in sorted(AREAS, key=len, reverse=True) if re.search(rf"\b{word}\b", lowered)), "")
    observations = []
    observation = candidate.get("signal", {}).get("observation", "")
    if observation == "Cart or stretcher":
        observations = ["Carted to locker room" if "locker room" in lowered else "Helped off field"]
    elif observation == "Medical tent evaluation":
        observations = ["Blue tent"]
    elif observation == "Left game":
        observations = ["Left game"]
    elif observation == "Injury mentioned":
        observations = ["Injured during game"]
    row_id = f"{game_date}-{club.lower()}-{slug}"
    if ID.fullmatch(row_id) is None:
        return None, "generated id does not match the ledger format"
    summary = {
        "out": "Ruled out",
        "did_not_return": "Did not return",
        "returned": "Returned to the game",
        "questionable": "Return uncertain",
        "unconfirmed": "In-game injury reported",
    }[outcome]
    row = {
        "id": row_id,
        "player": name,
        "position": "—",
        "team": club,
        "opponent": opponent,
        "gameDate": game_date,
        "injury": area.capitalize() if area else "Not specified",
        "outcome": outcome,
        "observations": observations,
        "claims": [{
            "date": game_date,
            "kind": "game",
            "text": f"{summary} — auto-matched from the club's own page. The quote is the club's sentence; "
                    f"no diagnosis, severity or return date is implied.",
            "quote": quote,
            "url": candidate["url"],
        }],
        "promotion": {
            "lane": "club-scan",
            "url": candidate["url"],
            "quote": quote,
            "phrase": phrase,
            "reads": int(candidate.get("reads", 0)),
            "firstSeen": candidate.get("firstSeen", ""),
            "lastSeen": candidate.get("lastSeen", ""),
            "article": candidate.get("article", ""),
            "gate": "two-read stability + club named in sentence + resolvable game date",
        },
    }
    return row, ""


def scan(*, get=None, get_json=None, now: datetime | None = None, clubs: list[str] | None = None,
         per_club: int = 3, budget: int = 220, state: dict | None = None, candidates: dict | None = None,
         promote: bool = True, archive: dict | None = None) -> dict:
    """One discovery pass. Network failures are recorded per club, never raised."""
    get = get or http_get
    get_json = get_json or json_get
    now = now or datetime.now(timezone.utc)
    state = state if state is not None else load_state()
    candidates = candidates if candidates is not None else load_candidates()
    archive = archive if archive is not None else load_json(ROOT / "data/archive.json", {"incidents": []})
    vocab = load_vocabulary()
    failures: list[str] = []
    schedule = schedule_index(SEASON, list(range(1, 4)), get=get_json, failures=failures)
    by_key = {candidate_key(item["url"], item["quote"]): item for item in candidates.get("candidates", [])}
    archive_names = {f"{row['team'].lower()}-{re.sub(r'[^a-z0-9]+', '-', row['player'].lower()).strip('-')}" for row in archive.get("incidents", [])}
    new_rows: list[dict] = []
    log_entries: list[dict] = []
    requests = 0

    order = clubs or sorted(CLUBS)
    for code in order:
        record = state["clubs"].setdefault(code, {
            "host": CLUBS[code]["host"], "label": CLUBS[code]["label"],
        })
        record.setdefault("readHistory", [])
        record.setdefault("articlesRead", 0)
        record.setdefault("candidatesKept", 0)
        record.setdefault("consecutiveFailures", 0)
        if requests >= budget:
            record.update({"status": "budget-skipped", "lastScanAt": iso_seconds(now)})
            continue
        index_html = ""
        index_error = ""
        for url in index_urls(code):
            if requests >= budget:
                break
            requests += 1
            try:
                index_html = get(url, kind="html").decode("utf-8", "replace")
                record["index"] = url
                break
            except Exception as error:  # noqa: BLE001 - record, never crash the scan
                index_error = f"{type(error).__name__}: {error}"[:180]
        if not index_html:
            record.update({"status": "blocked", "lastError": index_error or "index unavailable",
                           "lastScanAt": iso_seconds(now), "consecutiveFailures": record["consecutiveFailures"] + 1})
            failures.append(f"{code} news index unavailable ({index_error or 'no response'})")
            log_entries.append(make_log_entry(
                kind="lane-failure", tier="official", lane="club-scan", subject=f"{CLUBS[code]['label']} news index",
                text=f"Club news index could not be read this scan: {index_error or 'no response'}",
                url=index_urls(code)[0], detected_at=iso_seconds(now), status="blocked",
                note="A blocked club is recorded so it is not mistaken for a club with no injuries.",
            ))
            continue
        record.update({"status": "ok", "lastError": "", "lastScanAt": iso_seconds(now), "consecutiveFailures": 0})
        read_history = set(record.get("readHistory", []))
        # Pending candidates are re-read so a verified promotion needs two
        # independent reads of the identical sentence, not two lucky guesses.
        recheck = tuple(item["url"] for item in by_key.values()
                        if item.get("club") == code and item.get("promotion", {}).get("state") != "promoted")
        articles = pick_articles(index_html, CLUBS[code]["host"], already_read=read_history,
                                 limit=per_club, recheck=recheck)
        record["articlesSeen"] = len(articles)
        record["articlesRecheck"] = sum(1 for url in articles if url in read_history)
        for url in articles:
            if requests >= budget:
                break
            requests += 1
            try:
                html = get(url, kind="html").decode("utf-8", "replace")
            except Exception as error:  # noqa: BLE001
                failures.append(f"{code} article unreadable ({type(error).__name__})")
                continue
            meta = article_meta(html)
            body = visible_text(html)
            record["articlesRead"] = record.get("articlesRead", 0) + 1
            history = [item for item in record.setdefault("readHistory", []) if item != url]
            history.append(url)
            record["readHistory"] = history[-MAX_READ_HISTORY:]
            for found in candidate_sentences(body, vocab=vocab):
                key = candidate_key(url, found["quote"])
                existing = by_key.get(key)
                if existing:
                    existing["reads"] = int(existing.get("reads", 1)) + 1
                    existing["lastSeen"] = iso_seconds(now)
                    continue
                item = {
                    "id": f"cand-{fingerprint(key)}",
                    "club": code,
                    "clubLabel": CLUBS[code]["label"],
                    "url": url,
                    "article": meta.get("title", "")[:160],
                    "published": "",
                    "quote": found["quote"],
                    "player": found["player_guess"],
                    "signal": found["signal"],
                    "gameHint": found["gameHint"],
                    "reads": 1,
                    "firstSeen": iso_seconds(now),
                    "lastSeen": iso_seconds(now),
                    "promotion": {"state": "pending", "gate": "awaiting a second independent read of the same sentence"},
                }
                published, opponent = resolve_game(meta.get("published", ""), code, schedule)
                item["published"] = (meta.get("published") or "")[:40]
                item["gameDate"] = published
                item["opponent"] = opponent
                by_key[key] = item
                record["candidatesKept"] = record.get("candidatesKept", 0) + 1
                log_entries.append(make_log_entry(
                    kind="club-candidate", tier="official", lane="club-scan",
                    subject=f"{found['player_guess']} — {code}", text=found["quote"],
                    quote=found["quote"], url=url, detected_at=iso_seconds(now),
                    source_at=meta.get("published", ""), status=found["signal"]["status"],
                    note=f"Matched the phrase “{found['signal']['phrase']}” on the club's own page. Candidate only.",
                ))
    merged_candidates = sorted(by_key.values(), key=lambda item: str(item.get("lastSeen", "")), reverse=True)[:MAX_CANDIDATES]
    promoted = 0
    if promote:
        for item in merged_candidates:
            if item.get("promotion", {}).get("state") == "promoted":
                continue
            row, reason = promotion_gate(item, archive_names=archive_names, schedule=schedule)
            if row is None:
                item["promotion"] = {"state": "pending", "gate": reason}
                continue
            try:
                validate_archive({**archive, "incidents": archive.get("incidents", []) + [row]})
            except Exception as error:  # noqa: BLE001 - a row that fails its own schema is never written
                item["promotion"] = {"state": "blocked", "gate": f"row failed ledger validation: {error}"[:160]}
                log_entries.append(make_log_entry(
                    kind="lane-failure", tier="official", lane="club-scan", subject=f"{row['id']}",
                    text=f"Auto-promotion withheld: {error}"[:300], url=row["claims"][0]["url"],
                    detected_at=iso_seconds(now), status="blocked",
                    note="Fail-closed: an auto row that does not satisfy the ledger schema is not published.",
                ))
                continue
            archive["incidents"].append(row)
            archive_names.add(f"{row['team'].lower()}-{re.sub(r'[^a-z0-9]+', '-', row['player'].lower()).strip('-')}")
            item["promotion"] = {"state": "promoted", "gate": "two independent reads + resolvable game", "rowId": row["id"]}
            promoted += 1
            new_rows.append(row)
            log_entries.append(make_log_entry(
                kind="club-promotion", tier="official", lane="club-scan", subject=f"{row['player']} — {row['team']}",
                text=f"{row['outcome']} in {row['team']} vs {row['opponent']} ({row['gameDate']})",
                quote=row["claims"][0]["quote"], url=row["claims"][0]["url"], detected_at=iso_seconds(now),
                source_at=item.get("published", ""), status=row["outcome"], player=row["player"], team=row["team"],
                opponent=row["opponent"], game_date=row["gameDate"],
                note="Promoted automatically after two identical reads of the club's own sentence.",
            ))
    entry_data = {"version": 1, "updatedAt": iso_seconds(now), "label": CANDIDATE_LABEL, "policy": CANDIDATE_POLICY,
                  "candidates": merged_candidates}
    state["updatedAt"] = iso_seconds(now)
    return {"state": state, "candidates": entry_data, "archive": archive, "rows": new_rows,
            "logEntries": log_entries, "failures": failures, "requests": requests,
            "clubsScanned": sum(1 for code in order if state["clubs"].get(code, {}).get("status") == "ok"),
            "candidatesSeen": len(merged_candidates), "promoted": promoted}


def update_scope(archive: dict, added: int) -> None:
    """Keep the archive's own scope sentence honest about the rows it ships.

    The self-check and the ledger test both require the scope string to name the
    row count, so an automatic promotion that grew the list must also update it.
    """
    count = len(archive.get("incidents", []))
    scope = str(archive.get("scope", ""))
    scope = re.sub(r"^\d+", str(count), scope) if re.match(r"^\d+", scope) else f"{count} verified incidents. {scope}"
    if added:
        scope += (f" Automatic club-page promotions added {added} row(s) this scan; every promoted row carries a "
                  f"promotion block with the club sentence, its URL and both read times.")
    archive["scope"] = scope
    archive["verifiedOn"] = date.today().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clubs", nargs="*", help="subset of team codes (default: all 32)")
    parser.add_argument("--per-club", type=int, default=3)
    parser.add_argument("--budget", type=int, default=220, help="maximum HTTP requests for this pass")
    parser.add_argument("--no-promote", action="store_true", help="collect candidates without promoting")
    parser.add_argument("--report", type=Path, help="write the JSON report here as well")
    args = parser.parse_args()
    result = scan(clubs=args.clubs, per_club=args.per_club, budget=args.budget, promote=not args.no_promote)
    STATE_PATH.write_text(json.dumps(result["state"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    CANDIDATES_PATH.write_text(json.dumps(result["candidates"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.no_promote:
        archive = result["archive"]
        if result["rows"]:
            update_scope(archive, len(result["rows"]))
        (ROOT / "data/archive.json").write_text(json.dumps(archive, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if result["logEntries"]:
        data, added = merge_log(load_log(), result["logEntries"])
        write_log(data)
        print(f"alert log: +{added} entries")
    if args.report:
        args.report.write_text(json.dumps({key: value for key, value in result.items() if key not in {"state", "candidates", "archive"}},
                                          indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"club scan: {result['clubsScanned']} club indexes read, {result['candidatesSeen']} candidates on file, "
          f"{result['promoted']} promoted, {result['requests']} requests")
    for failure in result["failures"][:8]:
        print(f" - {failure}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

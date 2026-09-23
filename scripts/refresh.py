"""Collect scores separately from cautiously parsed NFL.com in-game news.

Run in GitHub Actions; nothing is committed or sent to a browser API. If either
provider is unavailable, output says so and never invents a player/status.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from schema import TEAMS, official_url, validate_incidents

ROOT = Path(__file__).resolve().parents[1]
NFL_INDEX = (
    "https://www.nfl.com/news/series/nfl-news-roundup",
    "https://www.nfl.com/news",
)
SCORE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
EASTERN = ZoneInfo("America/New_York")
MAX_HTML = 3_000_000
MAX_JSON = 6_000_000
# Automatic reporting never interprets diagnoses, prognosis or medical severity.
AREAS = frozenset({
    "ankle", "back", "calf", "chest", "concussion", "elbow", "foot", "groin",
    "hamstring", "hand", "hip", "knee", "neck", "quad", "shoulder", "stinger", "thigh", "toe", "wrist",
})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return result.astimezone(timezone.utc)


def fetch(url: str, *, kind: str) -> bytes:
    """Allowlisted HTTPS only; bound response size, timeout and redirect origin."""
    host = "site.api.espn.com" if kind == "scores" else "www.nfl.com"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.password:
        raise ValueError("untrusted fetch URL")
    request = Request(url, headers={"User-Agent": "InjuryAlerTNFL/1.0 (+https://github.com/buffedlizard55-lab/InjuryAlerTNFL; public news monitor)", "Accept": "application/json" if kind == "scores" else "text/html"})
    with urlopen(request, timeout=12) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != host:
            raise ValueError("cross-origin redirect refused")
        content_type = response.headers.get_content_type()
        expected = "application/json" if kind == "scores" else "text/html"
        if content_type != expected:
            raise ValueError(f"unexpected {kind} content-type: {content_type}")
        limit = MAX_JSON if kind == "scores" else MAX_HTML
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("oversized provider response")
        return payload


class NewsHTML(HTMLParser):
    """Extract only index links, article date/title and list items with player links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.items: list[dict] = []
        self.stack: list[dict] = []
        self.current_link: dict | None = None
        self.script: list[str] | None = None
        self.ld_json: list[str] = []
        self.meta_date: str | None = None
        self.title: str = ""
        self.in_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "li":
            self.stack.append({"parts": [], "players": []})
        elif tag == "a":
            self.current_link = {"url": attr.get("href") or "", "parts": [], "item": self.stack[-1] if self.stack else None}
        elif tag == "script" and (attr.get("type") or "").lower() == "application/ld+json":
            self.script = []
        elif tag == "meta" and (attr.get("property") in ("article:published_time", "article:published") or attr.get("itemprop") == "datePublished"):
            self.meta_date = attr.get("content") or self.meta_date
        elif tag == "h1":
            self.in_h1 = True

    def handle_data(self, data: str) -> None:
        if self.script is not None:
            self.script.append(data)
        if self.current_link is not None:
            self.current_link["parts"].append(data)
        if self.in_h1:
            self.title += data
        for item in self.stack:
            item["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_link is not None:
            link = self.current_link
            name = " ".join(" ".join(link["parts"]).split())
            self.links.append((link["url"], name))
            if link["item"] is not None and "/players/" in link["url"]:
                link["item"]["players"].append((link["url"], name))
            self.current_link = None
        elif tag == "li" and self.stack:
            item = self.stack.pop()
            item["text"] = " ".join(" ".join(item["parts"]).split())
            self.items.append(item)
        elif tag == "script" and self.script is not None:
            self.ld_json.append("".join(self.script))
            self.script = None
        elif tag == "h1":
            self.in_h1 = False

    @property
    def published(self) -> datetime | None:
        def find_date(obj: object) -> str | None:
            if isinstance(obj, list):
                for item in obj:
                    value = find_date(item)
                    if value:
                        return value
            if isinstance(obj, dict):
                if obj.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle") and obj.get("datePublished"):
                    return str(obj["datePublished"])
                for value in obj.values():
                    result = find_date(value)
                    if result:
                        return result
            return None

        for raw in self.ld_json:
            try:
                found = find_date(json.loads(raw))
                if found:
                    return parse_time(found)
            except (ValueError, TypeError):
                continue
        if self.meta_date:
            try:
                return parse_time(self.meta_date)
            except ValueError:
                pass
        return None


def parse_news(html: bytes) -> NewsHTML:
    page = NewsHTML()
    page.feed(html.decode("utf-8", errors="replace"))
    page.close()
    return page


def discover_links(pages: list[NewsHTML]) -> list[str]:
    found: list[str] = []
    for page in pages:
        for href, _ in page.links:
            url = urljoin("https://www.nfl.com", href).split("?", 1)[0]
            if urlparse(url).hostname == "www.nfl.com" and official_url(url) and "notable-injuries" in url and url not in found:
                found.append(url)
    return found[:8]


def normal_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def valid_player_link(name: str, href: str) -> bool:
    url = urljoin("https://www.nfl.com", href)
    if not official_url(url, player_page=True) or not urlparse(url).path.startswith("/players/"):
        return False
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    expected = normal_slug(name)
    return slug == expected or bool(re.fullmatch(re.escape(expected) + r"-\d+", slug))


def split_sentences(text: str, names: list[str]) -> list[str]:
    # Protect A.J., P.J., Jr. in linked names from punctuation splitting.
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, name.replace(".", "{dot}"))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.replace("{dot}", ".").strip() for p in parts if p.strip()]


def game_for(team: str, published: datetime, games: list[dict], now: datetime) -> dict | None:
    day = published.astimezone(EASTERN).date()
    matches = [
        game for game in games
        if team in (game["home"], game["away"])
        and abs((datetime.fromisoformat(game["date"].replace("Z", "+00:00")).astimezone(EASTERN).date() - day).days) <= 1
        and game["phase"] in ("live", "final")
        and parse_time(game["date"]) <= now
    ]
    return matches[0] if len(matches) == 1 else None


def outcome_in_sentence(sentence: str, player: str) -> str | None:
    rest = sentence.split(player, 1)[-1].lower()
    # Overlapping/conflicting verbs or a future/pre-game 'out for' => never publish.
    matched = []
    if re.search(r"\b(?:was |is )?ruled out (?:of|in)\b", rest):
        matched.append("out")
    if "did not return" in rest or "didn't return" in rest:
        matched.append("did_not_return")
    if re.search(r"\breturned (?:to|after|in|during)\b", rest):
        matched.append("returned")
    return matched[0] if len(matched) == 1 else None


def extract_roundup(page: NewsHTML, url: str, published: datetime, games: list[dict], now: datetime, held: set[str]) -> tuple[list[dict], list[dict]]:
    accepted: list[dict] = []
    flagged: list[dict] = []
    team_names = {g["homeName"]: g["home"] for g in games} | {g["awayName"]: g["away"] for g in games}
    for item in page.items:
        text = item["text"]
        if not item["players"] or not text or len(text) > 1250:
            continue
        team_name = next((n for n in sorted(team_names, key=len, reverse=True) if text.startswith(n + " ")), None)
        if team_name is None:
            continue
        team = team_names[team_name]
        game = game_for(team, published, games, now)
        if not game:
            continue
        other = game["away"] if game["home"] == team else game["home"]
        event_date = parse_time(game["date"]).astimezone(EASTERN).date().isoformat()
        names = [name for _, name in item["players"] if name]
        for href, name in item["players"]:
            if not name or name not in text:
                continue
            key = f"{event_date}-{team.lower()}-{normal_slug(name)}"
            if key in held:
                continue  # an unresolved source irregularity cannot auto-promote
            if not valid_player_link(name, href):
                flagged.append({"subject": name, "reason": "NFL player hyperlink/name mismatch; withheld", "url": url})
                continue
            sentences = [s for s in split_sentences(text, names) if name in s]
            if len(sentences) != 1:
                continue
            sentence = sentences[0]
            # A shared status ('A and B did not return') is not player-specific enough.
            if sum(other_name in sentence for other_name in names) != 1:
                continue
            outcome = outcome_in_sentence(sentence, name)
            if not outcome or len(sentence) > 220:
                continue
            # The roundup must say something about THIS game, not next week's practice.
            context = sentence.lower()
            if not re.search(r"\b(?:game|win|loss|halftime|against)\b|\bvs\.", context):
                continue
            # Parentheses immediately following the linked player's name, not a guessed diagnosis.
            after = sentence.split(name, 1)[1]
            area_match = re.match(r"\s*\(([^)]{2,30})\)", after)
            injury = area_match.group(1).title() if area_match and area_match.group(1).lower() in AREAS else "Not specified"
            summary = {"out": "Ruled out of that game.", "did_not_return": "Did not return to that game.", "returned": "Returned to that game."}[outcome]
            observations = ["Blue tent"] if "blue tent" in sentence.lower() else []
            if "carted" in sentence.lower():
                observations.append("Carted to locker room" if "locker room" in sentence.lower() else "Left game")
            if not observations:
                observations = ["Returned after halftime"] if outcome == "returned" and "after halftime" in sentence.lower() else ["Left game"]
            row = {
                "id": key, "player": name, "position": "—", "team": team, "opponent": other,
                "gameDate": event_date, "gameStart": game["date"], "injury": injury, "outcome": outcome,
                "observations": observations, "automatic": True, "capturedAt": iso(now),
                "claims": [{"date": published.astimezone(EASTERN).date().isoformat(), "kind": "game", "text": summary + " (NFL.com in-game roundup; no later availability implied.)", "quote": sentence, "url": url}],
            }
            try:
                validate_incidents([row], automatic=True)
            except (ValueError, KeyError):
                flagged.append({"subject": name, "reason": "Source/metadata validation failed; withheld", "url": url})
                continue
            accepted.append(row)
    return accepted, flagged


def parse_scores(raw: bytes) -> list[dict]:
    payload = json.loads(raw)
    if not isinstance(payload.get("events"), list):
        raise ValueError("ESPN response lacks events array")
    games: list[dict] = []
    for event in payload["events"]:
        try:
            code = str(event["id"])
            if not code.isdigit():
                continue
            competition = event["competitions"][0]
            sides = {side["homeAway"]: side for side in competition["competitors"]}
            home, away = sides["home"], sides["away"]
            hteam, ateam = home["team"], away["team"]
            habbr, aabbr = hteam["abbreviation"], ateam["abbreviation"]
            if habbr not in TEAMS or aabbr not in TEAMS or habbr == aabbr:
                continue
            when = iso(parse_time(event["date"]))
            state = event["status"]["type"]["state"]
            phase = {"in": "live", "post": "final", "pre": "scheduled"}.get(state)
            if not phase:
                continue
            label = str(event["status"]["type"].get("shortDetail") or event["status"]["type"].get("description") or "")[:36]
            hscore = str(home.get("score", "0")) if phase != "scheduled" else None
            ascore = str(away.get("score", "0")) if phase != "scheduled" else None
            if any(score is not None and not re.fullmatch(r"\d{1,3}", score) for score in (hscore, ascore)):
                continue
            games.append({"id": code, "date": when, "home": habbr, "away": aabbr,
                          "homeName": hteam["displayName"], "awayName": ateam["displayName"],
                          "homeScore": hscore, "awayScore": ascore, "phase": phase, "detail": label,
                          "url": f"https://www.espn.com/nfl/game/_/gameId/{code}"})
        except (KeyError, IndexError, ValueError, TypeError):
            continue  # never fabricate an incomplete game
    return games


def collect_scores(now: datetime, get=fetch) -> dict:
    games: dict[str, dict] = {}
    failures: list[str] = []
    urls = [SCORE_URL + "?limit=50"]
    # At a week boundary, the default ESPN endpoint drops earlier games.
    for days_ago in (1, 2):
        day = (now - timedelta(days=days_ago)).strftime("%Y%m%d")
        urls.append(SCORE_URL + f"?dates={day}&limit=50")
    for url in urls:
        try:
            for game in parse_scores(get(url, kind="scores")):
                games[game["id"]] = game
        except (OSError, ValueError, KeyError) as exc:
            failures.append(f"ESPN scoreboard unavailable ({type(exc).__name__})")
    return {"version": 1, "checkedAt": iso(now),
            "status": "unavailable" if len(failures) == len(urls) else "partial" if failures else "ok",
            "provider": "ESPN public scoreboard; scores are not injury verification",
            "games": sorted(games.values(), key=lambda game: game["date"]),
            "warnings": sorted(set(failures))}


def collect_news(now: datetime, games: list[dict], held: set[str], get=fetch, *, score_status: str = "ok") -> dict:
    problems: list[str] = []
    if score_status != "ok":
        problems.append("Scoreboard check limited; game matching may be incomplete")
    indexes = []
    for url in NFL_INDEX:
        try:
            indexes.append(parse_news(get(url, kind="html")))
        except (OSError, ValueError) as exc:
            problems.append(f"NFL.com news index unavailable ({type(exc).__name__})")
    articles = discover_links(indexes)
    incidents: dict[str, dict] = {}
    flags: list[dict] = []
    examined = 0
    for url in articles:
        try:
            page = parse_news(get(url, kind="html"))
            published = page.published
            if not published:
                flags.append({"subject": "Article metadata", "reason": "Publication date missing; no automatic claims", "url": url})
                continue
            if published > now + timedelta(minutes=5) or now - published > timedelta(hours=72):
                continue
            if "notable injuries" not in page.title.lower() or "games" not in page.title.lower():
                continue
            examined += 1
            if not any(item["players"] for item in page.items):
                problems.append("NFL.com roundup has no readable player bullets; format may have changed")
                flags.append({"subject": "Roundup parser", "reason": "Could not locate player-linked bullets; no automatic claims", "url": url})
                continue
            found, review = extract_roundup(page, url, published, games, now, held)
            for row in found:
                incidents.setdefault(row["id"], row)
            flags.extend(review)
        except (OSError, ValueError) as exc:
            problems.append(f"NFL.com article fetch failed ({type(exc).__name__})")
    status = "unavailable" if not indexes else "partial" if problems else "waiting" if examined == 0 else "ok"
    return {"version": 1, "checkedAt": iso(now), "status": status,
            "coverage": "NFL.com in-game roundups only; an empty list does not mean no injuries",
            "discovery": {"links": len(articles), "recentRoundups": examined, "accepted": len(incidents)},
            "incidents": list(incidents.values()), "flags": flags[:24], "warnings": sorted(set(problems))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--scoreboard", type=Path, required=True)
    args = parser.parse_args()
    now = utc_now()
    # A review flag has its own unique reason ID, distinct from the actual
    # incident ID. Never depend on free-text reasons or suffix stripping.
    held = {flag["incidentId"] for flag in json.loads((ROOT / "data/review.json").read_text())["flags"] if flag["disposition"] == "held"}
    scores = collect_scores(now)
    news = collect_news(now, scores["games"], held, score_status=scores["status"])
    validate_incidents(news["incidents"], automatic=True)
    for path, data in ((args.live, news), (args.scoreboard, scores)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"NFL.com: {news['status']}, {news['discovery']['accepted']} source-matched incidents; ESPN: {scores['status']}, {len(scores['games'])} games")
    if news["warnings"] or scores["warnings"]:
        print("Warnings: " + "; ".join(news["warnings"] + scores["warnings"]), file=sys.stderr)
    return 0  # degraded feeds are explicit, not silently published as fresh data


if __name__ == "__main__":
    raise SystemExit(main())

"""The append-only alert log.

Every update this project records — an official roundup match, a club-page
candidate, a promotion, a partner in-game wording, a lane failure — is written
here with **second-precision UTC timestamps** and the source it came from. The
log is the answer to "was this seen before the page was refreshed?": it is a
file in the repository, so refreshing the browser cannot lose it, and the
browser keeps its own session log on top of it.

Design rules, all enforced by ``schema.validate_alert_log``:

* ``detectedAt`` is when *this project* saw the text, to the second. It is never
  presented as the moment of injury.
* ``sourceAt`` is the provider's own timestamp when the lane publishes one, also
  truncated to the second (no invented sub-second precision).
* ``latencySeconds`` is only stored when a provider timestamp exists; otherwise
  it stays ``null`` rather than being guessed.
* Entries are immutable once written: the same event deduplicated by ``id``
  never changes its ``detectedAt``.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "data/alert-log.json"
MAX_ENTRIES = 1200
KINDS = frozenset({"roundup-match", "club-candidate", "club-promotion", "live-signal", "lane-status", "lane-failure", "roster-followup"})
TIERS = frozenset({"official", "partner", "unofficial"})
SECONDS_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def iso_seconds(moment: datetime) -> str:
    """UTC ISO-8601 truncated to whole seconds (never more precision than we have)."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_seconds() -> str:
    return iso_seconds(datetime.now(timezone.utc))


def truncate_seconds(value: str | None) -> str | None:
    """Provider timestamps often carry fractional seconds or an offset; normalise."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return iso_seconds(moment)


def fingerprint(*parts: str) -> str:
    """A stable short digest. Python's built-in hash() is salted per process, so a
    log written by one run could never be deduplicated by the next one."""
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]


def entry_id(kind: str, subject: str, url: str, key: str) -> str:
    """Identity is the *event*, not the moment we saw it: the same lane, subject,
    wording and provider timestamp produce one entry however often it is polled."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{subject}".lower()).strip("-")[:60]
    return f"log-{kind}-{slug}-{fingerprint(kind, subject, url, key)}"


def load(path: Path | None = None) -> dict:
    target = path or LOG_PATH
    if not target.exists():
        return {"version": 1, "updatedAt": None, "policy": POLICY, "entries": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "updatedAt": None, "policy": POLICY, "entries": []}
    if data.get("version") != 1 or not isinstance(data.get("entries"), list):
        return {"version": 1, "updatedAt": None, "policy": POLICY, "entries": []}
    data.setdefault("policy", POLICY)
    return data


POLICY = ("Append-only, newest first. Every entry carries a second-precision UTC detection time, "
          "the lane it came from, its tier label and the URL a reader can open. A detection time is "
          "when this project saw the text, never the moment of injury; absence of an entry is not "
          "evidence that nothing happened.")


def make(*, kind: str, tier: str, lane: str, subject: str, text: str, url: str,
         detected_at: str | None = None, source_at: str | None = None,
         status: str = "", quote: str = "", note: str = "",
         player: str = "", team: str = "", opponent: str = "", game_date: str = "",
         id_key: str = "", extra: dict | None = None) -> dict:
    """Build one log entry. Callers pass what they know; nothing is inferred."""
    if kind not in KINDS:
        raise ValueError(f"unknown log kind: {kind}")
    if tier not in TIERS:
        raise ValueError(f"log entry needs a real tier: {tier}")
    when = truncate_seconds(detected_at) or now_seconds()
    provider = truncate_seconds(source_at)
    # Dedupe key: an explicit key wins (heartbeats, incident ids); otherwise the
    # provider's own timestamp, then the wording itself.
    identity = truncate_seconds(id_key) or id_key or provider or f"{subject}\x1f{text}"
    latency = None
    if provider:
        latency = max(0, int((datetime.fromisoformat(when.replace("Z", "+00:00"))
                              - datetime.fromisoformat(provider.replace("Z", "+00:00"))).total_seconds()))
    entry = {
        "id": entry_id(kind, subject or lane, url, identity),
        "at": when,
        "detectedAt": when,
        "sourceAt": provider,
        "latencySeconds": latency,
        "kind": kind,
        "tier": tier,
        "lane": lane,
        "subject": subject[:120],
        "text": text[:400],
        "quote": quote[:300],
        "status": status[:32],
        "evidence": url,
        "player": player[:80],
        "team": team[:4],
        "opponent": opponent[:4],
        "gameDate": game_date[:10],
        "note": note[:300],
    }
    if extra:
        for key, value in extra.items():
            if key not in entry:
                entry[key] = value
    return entry


def merge(existing: dict, additions: list[dict], *, cap: int = MAX_ENTRIES) -> tuple[dict, int]:
    """Append newest-first, deduplicate by id, keep the first detection time."""
    entries = [entry for entry in existing.get("entries", []) if isinstance(entry, dict)]
    known = {entry.get("id") for entry in entries}
    added = 0
    fresh: list[dict] = []
    for entry in additions:
        if entry.get("id") in known:
            continue
        known.add(entry.get("id"))
        fresh.append(entry)
        added += 1
    fresh.sort(key=lambda item: str(item.get("detectedAt") or ""), reverse=True)
    merged = fresh + entries
    merged = merged[:cap]
    return {"version": 1, "updatedAt": fresh[0]["detectedAt"] if fresh else existing.get("updatedAt"),
            "policy": existing.get("policy", POLICY), "entries": merged}, added


def write(data: dict, path: Path | None = None) -> Path:
    target = path or LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return target

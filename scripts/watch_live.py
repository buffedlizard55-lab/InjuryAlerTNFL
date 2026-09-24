"""Game-window watcher: the lowest-latency lane this project can run for free.

A GitHub Actions cron entry is throttled to hours, which is useless during a
football game. A *running job*, by contrast, can poll every few seconds — so
this script is started inside a game window and stays alive for a few hours,
polling the free ESPN lanes and writing what it sees, with second-precision
timestamps, into ``data/watch.json`` and ``data/alert-log.json``.

What it can and cannot do is stated in the output itself:

* the **header** lane proves a game is live and gives the clock;
* the **summary** lane can carry an ``injuries`` section (status plus a provider
  note) — that is a league-partner feed, so it is labelled PARTNER, never
  official;
* the **plays** lane (ESPN core API) carries each play's own ``wallclock``
  timestamp to the second, which is the closest a free feed gets to "when";
* none of these lanes publishes a club statement. Club text arrives through
  ``clubscan.py`` (server-side) and the browser lane, and always with its tier.

The watcher never infers an injury from a play that does not say so.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from alertlog import (fingerprint, iso_seconds, load as load_log, make as make_log_entry, merge as merge_log,
                      truncate_seconds, write as write_log)
from lanes import HEADER, LaneError, json_get, play_records, plays_url, injury_records, parse_games, summary
from signals import classify, classify_all, load_vocabulary

ROOT = Path(__file__).resolve().parents[1]
WATCH_PATH = ROOT / "data/watch.json"
POLICY = ("Server-side game-window poll. Every signal carries the lane it came from, that lane's tier and a "
          "second-precision detection time; a lane that fails says so instead of going quiet. Nothing here is "
          "a diagnosis, a severity score, or a club statement.")

HEARTBEAT_SECONDS = 600  # one lane-status line per lane per ten minutes, no more


def empty_watch() -> dict:
    return {"version": 1, "checkedAt": None, "status": "not_started", "season": None, "week": None,
            "lanes": {}, "liveGames": [], "signals": [], "warnings": [], "policy": POLICY,
            "startedAt": None, "cycles": 0}


def load_watch() -> dict:
    try:
        data = json.loads(WATCH_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_watch()
    if data.get("version") != 1:
        return empty_watch()
    data.setdefault("policy", POLICY)
    return data


def signal_id(kind: str, text: str, source_at: str = "") -> str:
    """Stable across processes: the same wording in the same lane keeps one id, so
    a 20-second poll loop cannot write the same signal into the log 500 times."""
    return f"sig-{kind}-{fingerprint(kind, text, source_at)}"


def lane_probe(url: str, *, get) -> tuple[dict, str]:
    try:
        payload = get(url)
        return payload, ""
    except Exception as error:  # noqa: BLE001 - a lane failure is recorded, never raised
        return {}, f"{type(error).__name__}: {error}"[:160]


def cycle(*, get=None, now: datetime | None = None, watch: dict | None = None,
          log_entries: list[dict] | None = None, previous: dict | None = None) -> dict:
    """One poll of every lane. Pure enough to unit-test with an injected getter."""
    get = get or json_get
    now = now or datetime.now(timezone.utc)
    stamp = iso_seconds(now)
    watch = dict(watch or empty_watch())
    previous = previous or {}
    vocab = load_vocabulary()
    log_entries = log_entries if log_entries is not None else []
    lanes = dict(watch.get("lanes") or {})
    warnings: list[str] = []

    # 1. Header lane: is anything live, and what is the clock?
    header, header_error = lane_probe(HEADER, get=get)
    games = parse_games(header) if header else []
    lanes["header"] = {"status": "ok" if games else ("blocked" if header_error else "empty"),
                       "checkedAt": stamp, "error": header_error, "games": len(games)}
    live = [game for game in games if game["phase"] == "live"]
    if header_error:
        warnings.append(f"ESPN header lane unavailable ({header_error})")

    # 2. Per-live-game lanes: injuries section and play-by-play.
    signals: list[dict] = []
    for game in live:
        event_id = game["id"]
        payload, error = lane_probe(summary(event_id), get=get)
        lanes["summary"] = {"status": "ok" if payload else "blocked", "checkedAt": stamp, "error": error, "event": event_id}
        if error:
            warnings.append(f"ESPN summary lane unavailable for {event_id} ({error})")
        for record in injury_records(payload):
            text = f"{record['athlete']} — {record['status']}. {record['detail']}".strip()
            matches = classify_all(text, vocab)
            if not matches:
                continue
            provider_stamp = truncate_seconds(record.get("date")) or ""
            signal = {
                "id": signal_id("summary", text, provider_stamp),
                "lane": "ESPN summary injuries section",
                "tier": "partner",
                "game": event_id,
                "team": record.get("teamAbbreviation", ""),
                "player": record["athlete"],
                "status": matches[0]["status"],
                "phrase": matches[0]["phrase"],
                "label": matches[0]["label"],
                "text": text[:400],
                "sourceAt": provider_stamp or None,
                "detectedAt": stamp,
            }
            signals.append(signal)
            log_entries.append(make_log_entry(
                kind="live-signal", tier="partner", lane=signal["lane"], subject=f"{signal['player']} — {game['away']}/{game['home']}",
                text=text, quote=record.get("detail", ""), url=game["url"], detected_at=stamp,
                source_at=record.get("date", ""), status=matches[0]["status"], player=record["athlete"],
                id_key=f"summary|{record['athlete']}|{provider_stamp}|{text}",
                note="Partner feed wording during a live game. Not a league or club statement.",
            ))
        plays_payload, plays_error = lane_probe(plays_url(event_id, event_id), get=get)
        lanes["plays"] = {"status": "ok" if plays_payload else "blocked", "checkedAt": stamp, "error": plays_error, "event": event_id}
        if plays_error:
            warnings.append(f"ESPN play lane unavailable for {event_id} ({plays_error})")
        plays = play_records(plays_payload)
        for play in plays:
            signal = classify(play["text"], vocab)
            if not signal:
                continue
            stamp_play = play.get("wallclock") or ""
            item = {
                "id": signal_id("play", play["text"], stamp_play),
                "lane": "ESPN play-by-play (wallclock timestamp)",
                "tier": "partner",
                "game": event_id,
                "team": "",
                "player": "",
                "status": signal["status"],
                "phrase": signal["phrase"],
                "label": signal["label"],
                "text": play["text"][:400],
                "sourceAt": stamp_play,
                "detectedAt": stamp,
            }
            signals.append(item)
            log_entries.append(make_log_entry(
                kind="live-signal", tier="partner", lane=item["lane"], subject=f"{game['away']} @ {game['home']} play",
                text=play["text"], url=f"https://www.espn.com/nfl/game/_/gameId/{event_id}",
                detected_at=stamp, source_at=stamp_play, status=signal["status"],
                note="Play-by-play text that itself carries an availability phrase; no inference from the play call.",
            ))

    # 3. Heartbeats and game-state transitions, so the log proves the lane ran.
    game_state = {game["id"]: game["phase"] for game in games}
    for event_id, phase in game_state.items():
        before = (previous.get("game_state") or {}).get(event_id)
        if before == phase:
            continue
        summary_line = next((f"{game['away']} @ {game['home']} — {phase} ({game['detail']})" for game in games if game["id"] == event_id), event_id)
        log_entries.append(make_log_entry(
            kind="lane-status", tier="partner", lane="ESPN header", subject=summary_line,
            text=f"Game state moved to {phase} at {stamp}.", url=f"https://www.espn.com/nfl/game/_/gameId/{event_id}",
            detected_at=stamp, status=phase, note="State transition recorded from the partner header lane.",
        ))
    for lane in ("header", "summary", "plays"):
        record = lanes.get(lane, {})
        if record.get("status") != "blocked":
            continue
        last = (previous.get("heartbeats") or {}).get(lane)
        if last and (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < HEARTBEAT_SECONDS:
            continue
        log_entries.append(make_log_entry(
            kind="lane-failure", tier="partner", lane=lane, subject=f"{lane} lane blocked",
            text=f"The {lane} lane did not answer this cycle: {record.get('error') or 'no response'}",
            url=HEADER, detected_at=stamp, status="blocked",
            note="Lane failures are logged so an empty feed is never read as an all-clear.",
        ))
        previous.setdefault("heartbeats", {})[lane] = stamp

    known = {item.get("id") for item in (watch.get("signals") or [])}
    fresh_signals = [item for item in signals if item["id"] not in known]
    watch.update({
        "version": 1,
        "checkedAt": stamp,
        "status": "live" if live else ("watching" if games else "unavailable" if warnings else "idle"),
        "lanes": lanes,
        "liveGames": live,
        "signals": (fresh_signals + (watch.get("signals") or []))[:200],
        "warnings": sorted(set(warnings))[:12],
        "cycles": int(watch.get("cycles") or 0) + 1,
        "game_state": game_state,
        "policy": POLICY,
    })
    watch.setdefault("startedAt", stamp)
    return {"watch": watch, "logEntries": log_entries, "newSignals": fresh_signals, "live": len(live)}


def run(*, minutes: float, interval: float, get=None, once: bool = False, idle_exit: float | None = 45) -> int:
    started = time.monotonic()
    watch = load_watch()
    previous = {"game_state": watch.get("game_state") or {}, "heartbeats": {}}
    seen_live = False
    idle_since: float | None = None
    while True:
        try:
            result = cycle(get=get, watch=watch, previous=previous)
        except KeyboardInterrupt:  # pragma: no cover - operator stop
            break
        watch = result["watch"]
        previous["game_state"] = watch.get("game_state") or {}
        if result["logEntries"]:
            log_data, added = merge_log(load_log(), result["logEntries"])
            write_log(log_data)
            print(f"[{watch['checkedAt']}] log +{added} entries, {result['live']} live game(s)", flush=True)
        else:
            print(f"[{watch['checkedAt']}] {result['live']} live game(s), no new entries", flush=True)
        WATCH_PATH.write_text(json.dumps(watch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        if result["live"]:
            seen_live = True
            idle_since = None
        elif seen_live and idle_exit is not None:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since > idle_exit:
                print("no live game for a while; stopping the watcher", flush=True)
                break
        if once or time.monotonic() - started >= minutes * 60:
            break
        time.sleep(max(5.0, interval))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=300, help="how long to keep polling (job limit friendly)")
    parser.add_argument("--interval", type=float, default=20, help="seconds between cycles")
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument("--no-idle-exit", action="store_true", help="keep polling even when no game is live")
    args = parser.parse_args()
    if args.once:
        result = cycle()
        watch = result["watch"]
        WATCH_PATH.write_text(json.dumps(watch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        if result["logEntries"]:
            data, added = merge_log(load_log(), result["logEntries"])
            write_log(data)
            print(f"watch: one cycle, log +{added} entries, {result['live']} live game(s)")
        else:
            print(f"watch: one cycle, {result['live']} live game(s), nothing matched")
        return 0
    return run(minutes=args.minutes, interval=args.interval, idle_exit=None if args.no_idle_exit else 45)


if __name__ == "__main__":
    sys.exit(main())

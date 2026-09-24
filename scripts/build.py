"""Assemble a Pages artifact. The collector never needs to push to main."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from schema import (InvalidData, validate_alert_log, validate_archive, validate_candidates, validate_incidents,
                    validate_leads, validate_review, validate_sources, validate_watch)

ROOT = Path(__file__).resolve().parents[1]
# Machine-written artefacts shipped with the site. They are data, not code: the
# page reads them, so a malformed one is a build failure, not a warning.
DATA_FILES = (
    "archive.json", "review.json", "sources.json", "leads.json",
    "alert-log.json", "candidates.json", "watch.json", "clubscan-state.json", "vocabulary.json",
)
STATIC_ASSETS = ("app.js", "domain.mjs", "vocabulary.mjs", "styles.css")


def rss(live: dict, log: dict | None = None) -> str:
    header = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<rss version="2.0"><channel><title>Sideline Signal — source-backed in-game reports</title>'
              '<link>https://buffedlizard55-lab.github.io/InjuryAlerTNFL/</link>'
              '<description>Only automatically matched NFL.com game reports. Game status is not a medical prognosis; an empty feed does not mean no injuries.</description>')
    items = []
    for row in live.get("incidents", []):
        url = row["claims"][0]["url"]
        summary = {"out": "ruled out", "did_not_return": "did not return", "returned": "returned"}[row["outcome"]]
        title = f"{row['player']} ({row['team']}): {summary} vs {row['opponent']} — {row['gameDate']}"
        captured = datetime.fromisoformat(row["capturedAt"].replace("Z", "+00:00")).astimezone(timezone.utc)
        description = f"{row['claims'][0]['quote']} Source: NFL.com. Captured at {row['capturedAt']}; not the time of injury."
        items.append('<item><title>' + escape(title) + '</title><link>' + escape(url) + '</link>'
                     + '<guid isPermaLink="false">' + escape(row["id"]) + '</guid>'
                     + '<pubDate>' + format_datetime(captured, usegmt=True) + '</pubDate>'
                     + '<description>' + escape(description) + '</description></item>')
    # The alert log is the second feed: everything the project saw, timestamped
    # to the second, each item linked to the page it came from.
    for entry in (log or {}).get("entries", [])[:40]:
        if entry.get("kind") not in {"club-promotion", "live-signal", "roundup-match"}:
            continue
        stamp = datetime.fromisoformat(entry["detectedAt"].replace("Z", "+00:00")).astimezone(timezone.utc)
        title = f"[{entry['tier'].upper()}] {entry['subject']}"
        items.append('<item><title>' + escape(title) + '</title><link>' + escape(entry["evidence"]) + '</link>'
                     + '<guid isPermaLink="false">' + escape(entry["id"]) + '</guid>'
                     + '<pubDate>' + format_datetime(stamp, usegmt=True) + '</pubDate>'
                     + '<description>' + escape(f"{entry['text']} (seen {entry['detectedAt']}, {entry['kind']}, {entry['lane']})")
                     + '</description></item>')
    return header + "".join(items) + '</channel></rss>\n'


def assemble(output: Path, live_path: Path, score_path: Path) -> None:
    archive = json.loads((ROOT / "data/archive.json").read_text(encoding="utf-8"))
    review = json.loads((ROOT / "data/review.json").read_text(encoding="utf-8"))
    sources = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))
    leads = json.loads((ROOT / "data/leads.json").read_text(encoding="utf-8"))
    alert_log = json.loads((ROOT / "data/alert-log.json").read_text(encoding="utf-8"))
    candidates = json.loads((ROOT / "data/candidates.json").read_text(encoding="utf-8"))
    watch = json.loads((ROOT / "data/watch.json").read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    scores = json.loads(score_path.read_text(encoding="utf-8"))
    validate_archive(archive)
    validate_review(review)
    # The provenance files are part of the public contract: a page that shows a
    # source tier must ship the registry that justifies it, and a lead list must
    # never contain an official row.
    validate_sources(sources)
    validate_leads(leads)
    validate_alert_log(alert_log)
    validate_candidates(candidates)
    validate_watch(watch)
    validate_incidents(live["incidents"], automatic=True)
    held = {flag["incidentId"] for flag in review["flags"] if flag["disposition"] == "held"}
    if any(row["id"] in held for row in archive["incidents"] + live["incidents"]):
        raise InvalidData("a held source issue cannot be published as verified")
    if live.get("version") != 1 or scores.get("version") != 1 or not isinstance(scores.get("games"), list):
        raise ValueError("unsupported live/scoreboard schema")
    if not (ROOT / "assets/vocabulary.mjs").exists():
        raise InvalidData("assets/vocabulary.mjs is missing: run python scripts/gen_vocabulary.py --write")
    if output.resolve() == ROOT:
        raise ValueError("refusing to overwrite repository root")
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    for file in ("index.html", ".nojekyll"):
        shutil.copy2(ROOT / file, output / file)
    for file in STATIC_ASSETS:
        shutil.copy2(ROOT / "assets" / file, output / "assets" / file)
    for file in DATA_FILES:
        shutil.copy2(ROOT / "data" / file, output / "data" / file)
    shutil.copy2(live_path, output / "data/live.json")
    shutil.copy2(score_path, output / "data/scoreboard.json")
    (output / "feed.xml").write_text(rss(live, alert_log), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--live", type=Path, default=ROOT / "data/live.json")
    parser.add_argument("--scoreboard", type=Path, default=ROOT / "data/scoreboard.json")
    args = parser.parse_args()
    assemble(args.output, args.live, args.scoreboard)
    print(f"Site assembled at {args.output}")


if __name__ == "__main__":
    main()

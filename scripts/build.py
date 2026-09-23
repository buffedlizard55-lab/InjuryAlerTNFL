"""Assemble a Pages artifact. The collector never needs to push to main."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from schema import validate_archive, validate_incidents, validate_review

ROOT = Path(__file__).resolve().parents[1]


def rss(live: dict) -> str:
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
    return header + "".join(items) + '</channel></rss>\n'


def assemble(output: Path, live_path: Path, score_path: Path) -> None:
    archive = json.loads((ROOT / "data/archive.json").read_text(encoding="utf-8"))
    review = json.loads((ROOT / "data/review.json").read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    scores = json.loads(score_path.read_text(encoding="utf-8"))
    validate_archive(archive)
    validate_review(review)
    validate_incidents(live["incidents"], automatic=True)
    if live.get("version") != 1 or scores.get("version") != 1 or not isinstance(scores.get("games"), list):
        raise ValueError("unsupported live/scoreboard schema")
    if output.resolve() == ROOT:
        raise ValueError("refusing to overwrite repository root")
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    for file in ("index.html", ".nojekyll"):
        shutil.copy2(ROOT / file, output / file)
    for file in ("app.js", "domain.mjs", "styles.css"):
        shutil.copy2(ROOT / "assets" / file, output / "assets" / file)
    for file in ("archive.json", "review.json"):
        shutil.copy2(ROOT / "data" / file, output / "data" / file)
    shutil.copy2(live_path, output / "data/live.json")
    shutil.copy2(score_path, output / "data/scoreboard.json")
    (output / "feed.xml").write_text(rss(live), encoding="utf-8")


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

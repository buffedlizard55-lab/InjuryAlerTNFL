#!/usr/bin/env python3
"""One-command self-audit: does the shipped site match the story it tells?

Run before a release or a review pass:

    python scripts/selfcheck.py

It is deliberately independent of the unit tests. The tests check behaviour;
this checks the *published artefacts* against the rules the project states out
loud, and prints the counts a reviewer can compare with README.md and
docs/source-audit.md. Exit code 1 means something a reader could be misled by.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from schema import (official_url, validate_alert_log, validate_archive, validate_candidates,  # noqa: E402
                    validate_leads, validate_review, validate_sources, validate_watch)

OFFICIAL_HOSTS = ("nfl.com", ".com")  # refined below by official_url itself


def load(name: str) -> dict:
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def main() -> int:
    archive, review, sources, leads = (load("archive.json"), load("review.json"),
                                       load("sources.json"), load("leads.json"))
    problems: list[str] = []

    # 1. Every file must still satisfy its own fail-closed schema.
    for name, data, validator in (
        ("archive.json", archive, validate_archive),
        ("review.json", review, validate_review),
        ("sources.json", sources, validate_sources),
        ("leads.json", leads, validate_leads),
        ("alert-log.json", load("alert-log.json"), validate_alert_log),
        ("candidates.json", load("candidates.json"), validate_candidates),
        ("watch.json", load("watch.json"), validate_watch),
    ):
        try:
            validator(data)
        except Exception as error:  # noqa: BLE001 - report, do not crash the audit
            problems.append(f"{name} fails its own validation: {error}")

    claims = [claim for row in archive["incidents"] for claim in row["claims"]]
    urls = {claim["url"] for claim in claims}
    hosts = {urlparse(url).hostname for url in urls}
    lanes = sources["sources"]

    # 2. The verified ledger may only cite league or club newsrooms.
    bad = sorted(url for url in urls if not official_url(url))
    if bad:
        problems.append(f"{len(bad)} archive url(s) are not on an allowed official host: {bad[:3]}")

    # 3. Every registry lane must say how it was checked and what it can prove.
    for lane in lanes:
        check = lane.get("verification", {})
        if len(check.get("method", "")) < 20:
            problems.append(f"{lane['id']}: probe method is too thin to trust")
        if not check.get("evidence"):
            problems.append(f"{lane['id']}: no evidence URL")
        if lane["tier"] != "official" and lane["autoPublish"]:
            problems.append(f"{lane['id']}: a non-official lane claims auto-publish")

    # 4. No lead may sit on an official-looking tier, and every lead must say
    #    what the next check is.
    for lead in leads["leads"]:
        if lead["source"]["tier"] == "official":
            problems.append(f"{lead['id']}: a lead may never cite an official source as a lead")
        if len(lead.get("verifyNext", "")) < 20:
            problems.append(f"{lead['id']}: next check is missing")

    # 5. The archive must not silently contain a pregame designation as an
    #    in-game event: every row needs at least one game-kind claim.
    for row in archive["incidents"]:
        if not any(claim["kind"] == "game" for claim in row["claims"]):
            problems.append(f"{row['id']}: no in-game claim")

    # 6. The page must load every artefact it needs, and its CSP must not open
    #    the browser to anything except the two ESPN hosts it polls.
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    front_end = index + "\n" + "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "assets").glob("*"))
        if path.suffix in {".js", ".mjs", ".css"})
    for artifact in ("archive.json", "review.json", "sources.json", "leads.json",
                     "alert-log.json", "candidates.json", "watch.json"):
        if artifact not in front_end:
            problems.append(f"the front end never loads {artifact}")
    csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', index)
    if csp:
        connect = re.search(r"connect-src([^;]+);", csp.group(1))
        allowed = (connect.group(1) if connect else "").split()
        unexpected = [item for item in allowed if not item.startswith("'self'")
                      and not item.startswith("https://site.api.espn.com")
                      and not item.startswith("https://site.web.api.espn.com")
                      and not item.startswith("https://sports.core.api.espn.com")]
        if unexpected:
            problems.append(f"connect-src opens the browser to {unexpected}")
    else:
        problems.append("index.html has no Content-Security-Policy")

    # 7. The registry has to name the boundary lanes, otherwise the taxonomy is
    #    incomplete by omission rather than by judgement.
    lane_ids = {lane["id"] for lane in lanes}
    for required in ("nfl-gamecenter-json", "espn-scoreboard", "espn-summary-plays", "x-twitter", "reddit-json"):
        if required not in lane_ids:
            problems.append(f"registry is missing the boundary lane {required}")

    # 8. The archive must describe the row count it actually ships.
    if str(len(archive["incidents"])) not in archive.get("scope", ""):
        problems.append("archive scope string does not name the row count it ships")

    official = sum(1 for lane in lanes if lane["tier"] == "official")
    partner = sum(1 for lane in lanes if lane["tier"] == "partner")
    unofficial = sum(1 for lane in lanes if lane["tier"] == "unofficial")
    print(f"archive: {len(archive['incidents'])} incidents / {len(claims)} claims / {len(urls)} official URLs "
          f"({', '.join(sorted(h for h in hosts if h))})")
    print(f"review:  {len(review['flags'])} flags "
          f"({sum(1 for f in review['flags'] if f['disposition'] == 'held')} held, "
          f"{sum(1 for f in review['flags'] if f['disposition'] == 'annotated')} annotated)")
    print(f"sources: {len(lanes)} lanes ({official} official / {partner} partner / {unofficial} unofficial)")
    print(f"leads:   {len(leads['leads'])} unofficial leads")
    log = load("alert-log.json")
    watch = load("watch.json")
    print(f"log:     {len(log['entries'])} entries (append-only, second-precision); "
          f"watch: {watch['status']} / {len(watch['signals'])} signal(s)")
    if problems:
        print("\nFAIL")
        for problem in problems:
            print(f" - {problem}")
        return 1
    print("\nOK — the published artefacts match the rules the project states.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

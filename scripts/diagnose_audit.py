"""Print the served source text around any excerpt the online audit cannot ground.

Run after verify_sources.py --strict writes its report. For every
"excerpt not found" line it re-fetches the cited page, measures the longest
matched prefix of the stored quote, and prints both sides of the mismatch so a
wording change, CDN variant, or parser artifact is visible without guesswork.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_sources import normalize, source_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def longest_prefix(text: str, quote: str) -> tuple[int, int]:
    """Return (matched chars, position in text) for the longest prefix of quote."""
    lo, hi = 0, len(quote)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text.find(quote[:mid]) >= 0:
            lo = mid
        else:
            hi = mid - 1
    pos = text.find(quote[:lo]) if lo else 0
    return lo, pos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path("/tmp/source-audit.txt"))
    args = parser.parse_args()
    report = args.audit.read_text(encoding="utf-8", errors="replace")
    rows = json.loads((ROOT / "data/archive.json").read_text(encoding="utf-8"))["incidents"]
    findings = re.findall(r"REVIEW: (\S+) claim (\d+): excerpt not found at (\S+)", report)
    if not findings:
        findings = re.findall(r"REVIEW: (\S+) claim (\d+): unavailable (\S+)", report)
        for iid, index, url in findings:
            print(f"diagnostic: {iid} claim {index}: source unreachable {url}")
        return 0
    for iid, index, url in findings:
        row = next((r for r in rows if r["id"] == iid), None)
        claim = row["claims"][int(index) - 1] if row else None
        if claim is None:
            print(f"diagnostic: {iid} claim {index}: row not found in ledger")
            continue
        try:
            served = source_text(url)
        except Exception as exc:  # noqa: BLE001 — diagnostics must never raise
            print(f"diagnostic: {iid} claim {index}: unreachable {url} ({type(exc).__name__})")
            continue
        quote = normalize(claim["quote"])
        matched, pos = longest_prefix(served, quote)
        print(f"diagnostic: {iid} claim {index}: matched {matched}/{len(quote)} chars of the normalized quote")
        if matched:
            print(f"  quote tail after last match: {quote[matched:matched + 90]!r}")
            print(f"  served text at match point : ...{served[max(0, pos - 90):pos + 240]}...")
        else:
            print(f"  served text start          : ...{served[:330]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

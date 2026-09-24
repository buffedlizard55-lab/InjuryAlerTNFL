"""Generate ``assets/vocabulary.mjs`` from ``data/vocabulary.json``.

The browser and the collectors must agree on what an in-game phrase is, so the
phrase list has exactly one home and the module is generated from it. A test
asserts the checked-in module matches the vocabulary file byte for byte; run
``python scripts/gen_vocabulary.py --write`` after editing the JSON.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = """// GENERATED FILE — do not edit by hand.
// Source: data/vocabulary.json · regenerate with: python scripts/gen_vocabulary.py --write
// This module is the browser half of the shared in-game vocabulary. It classifies
// text a provider actually wrote; it never creates a diagnosis, a severity or a cause.
"""


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(vocabulary: dict) -> str:
    rules = []
    for rule in vocabulary["rules"]:
        rules.append({
            "status": rule["status"],
            "observation": rule.get("observation", ""),
            "label": rule["label"],
            "weight": int(rule.get("weight", 1)),
            "source": [re.compile(pattern, re.IGNORECASE).pattern for pattern in rule["patterns"]],
        })
    lines = [HEADER, f"export const VOCABULARY_VERSION = {int(vocabulary['version'])};\n"]
    lines.append("export const IN_GAME_RULES = Object.freeze([\n")
    for rule in rules:
        patterns = ", ".join(f"/{pattern}/i" for pattern in rule["source"])
        lines.append("  Object.freeze({ status: %s, observation: %s, label: %s, weight: %d, patterns: Object.freeze([%s]) }),\n"
                     % (_js(rule["status"]), _js(rule["observation"]), _js(rule["label"]), rule["weight"], patterns))
    lines.append("]);\n\n")
    contexts = vocabulary["contexts"]
    lines.append("export const CONTEXTS = Object.freeze({\n")
    lines.append("  inGame: Object.freeze(%s),\n" % _js(contexts["inGame"]))
    lines.append("  practiceExclusion: Object.freeze(%s),\n" % _js(contexts["practiceExclusion"]))
    lines.append("  gameDateHint: Object.freeze(%s),\n" % _js(contexts["gameDateHint"]))
    lines.append("});\n")
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the module (default: report drift only)")
    args = parser.parse_args()
    vocabulary = json.loads((ROOT / "data/vocabulary.json").read_text(encoding="utf-8"))
    rendered = render(vocabulary)
    current = (ROOT / "assets/vocabulary.mjs").read_text(encoding="utf-8") if (ROOT / "assets/vocabulary.mjs").exists() else ""
    if args.write:
        (ROOT / "assets/vocabulary.mjs").write_text(rendered, encoding="utf-8")
        print("wrote assets/vocabulary.mjs")
        return 0
    if current != rendered:
        print("assets/vocabulary.mjs is out of sync with data/vocabulary.json", flush=True)
        return 1
    print("vocabulary module in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

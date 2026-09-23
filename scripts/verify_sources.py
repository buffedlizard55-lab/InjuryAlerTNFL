"""Optional online re-check of every short archive excerpt against its source.

Network outages are reported as failures, never transformed into confirmations.
Use --strict in a network-capable environment to require all quotes to match.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from schema import official_url, validate_archive

ROOT = Path(__file__).resolve().parents[1]


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "\u00a0": " ", "–": "-", "—": "-"}))
    return " ".join(text.split()).casefold()


def source_text(url: str) -> str:
    if not official_url(url):
        raise ValueError("URL not an approved official newsroom")
    request = Request(url, headers={"User-Agent": "InjuryAlerTNFL/1.0 (+https://github.com/buffedlizard55-lab/InjuryAlerTNFL; citation audit)", "Accept": "text/html"})
    with urlopen(request, timeout=15) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != urlparse(url).hostname or response.headers.get_content_type() != "text/html":
            raise ValueError("source redirected or did not serve HTML")
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError("oversize article")
    page = VisibleText()
    page.feed(raw.decode("utf-8", errors="replace"))
    return normalize(" ".join(page.parts))


def verify(data: dict, reader=source_text) -> list[str]:
    validate_archive(data)
    cache: dict[str, str] = {}
    issues: list[str] = []
    for row in data["incidents"]:
        for index, claim in enumerate(row["claims"], 1):
            url = claim["url"]
            if url not in cache:
                try:
                    cache[url] = reader(url)
                except (OSError, ValueError) as exc:
                    cache[url] = ""
                    issues.append(f"{row['id']} claim {index}: unavailable {url} ({type(exc).__name__})")
            if cache[url] and normalize(claim["quote"]) not in cache[url]:
                issues.append(f"{row['id']} claim {index}: excerpt not found at {url}")
    print(f"Checked {sum(len(row['claims']) for row in data['incidents'])} claims across {len(cache)} official article URLs; {len(issues)} issue(s)")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero on any missing source/quote")
    args = parser.parse_args()
    archive = json.loads((ROOT / "data/archive.json").read_text(encoding="utf-8"))
    issues = verify(archive)
    for issue in issues:
        print("REVIEW: " + issue, file=sys.stderr)
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())

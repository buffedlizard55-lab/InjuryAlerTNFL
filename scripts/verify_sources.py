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
    # Fold typographic punctuation to the ASCII forms used in stored excerpts:
    # curly quotes, the dash family (including the non-breaking hyphen some
    # articles use inside compound words), and soft hyphens are the same
    # characters to a reader.
    text = text.translate(str.maketrans({
        "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " ",
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
        "\u00ad": "", "\u2212": "-",
    }))
    return " ".join(text.split()).casefold()


def nearest_live_text(text: str, quote: str, limit: int = 300) -> str:
    """Return the sentence on the page that holds the longest run of the excerpt.

    Newsroom roundups are edited after publication, so a missing excerpt is usually
    a reword rather than a fabrication. Printing the live sentence next to the
    stored one lets a reviewer tell those two apart without opening the page, and
    keeps the CI report actionable when it cannot be reproduced locally.
    """
    needle = normalize(quote)
    best_length, best_pos = 0, -1
    for start in range(len(needle)):
        low, high = best_length + 1, len(needle) - start
        while low <= high:
            middle = (low + high) // 2
            position = text.find(needle[start:start + middle])
            if position == -1:
                high = middle - 1
            else:
                if middle > best_length:
                    best_length, best_pos = middle, position
                low = middle + 1
        if best_length >= len(needle):
            break
    if best_pos == -1:
        return ""
    left = text.rfind(". ", 0, best_pos)
    left = 0 if left == -1 else left + 2
    right = text.find(". ", best_pos + best_length)
    right = len(text) if right == -1 else right + 1
    snippet = text[left:right]
    return snippet[: limit - 1] + "…" if len(snippet) > limit else snippet


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
                hint = nearest_live_text(cache[url], claim["quote"])
                # Keep the URL as the last field diagnose_audit.py greps for; the
                # live-sentence hint goes after it so a reviewer sees both sides.
                detail = f" — nearest live text: {hint!r}" if hint else ""
                issues.append(f"{row['id']} claim {index}: excerpt not found at {url}{detail}")
    print(f"Checked {sum(len(row['claims']) for row in data['incidents'])} claims across {len(cache)} official article URLs; {len(issues)} issue(s)", flush=True)
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

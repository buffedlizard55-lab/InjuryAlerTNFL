"""Shared in-game vocabulary and candidate gates (Python side).

One list of phrases decides what this project is allowed to call an in-game
availability signal. The list lives in ``data/vocabulary.json`` and the browser
reads a generated copy of it (``assets/vocabulary.mjs``), so the page and the
collectors can never drift into disagreeing about what a phrase means.

Nothing in here diagnoses anything. A matched phrase is an observation or an
availability phrase written by somebody else, quoted with its source.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOCAB_PATH = ROOT / "data" / "vocabulary.json"
GENERATED_JS = ROOT / "assets" / "vocabulary.mjs"

# Words that mark a sentence as a practice/roster status rather than a moment in
# a game. The exclusion list is blunt on purpose: a practice report may prove a
# player is limited today, but it can never prove when the injury happened.
_PRACTICE_WORDS = None  # filled from the vocabulary on load

_NAME = re.compile(r"\b([A-Z][a-zA-Z'’.\-]+(?:\s+[A-Z][a-zA-Z'’.\-]+){1,2})\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"])")
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class VocabularyError(ValueError):
    pass


def load_vocabulary(path: Path | None = None) -> dict:
    data = json.loads((path or VOCAB_PATH).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise VocabularyError("unsupported vocabulary version")
    rules = data.get("rules")
    if not isinstance(rules, list) or len(rules) < 5:
        raise VocabularyError("vocabulary needs its closed rule list")
    for rule in rules:
        if rule.get("status") not in {"out", "questionable", "evaluated", "returned", "observed"}:
            raise VocabularyError(f"unknown status in vocabulary: {rule.get('status')}")
        if not isinstance(rule.get("patterns"), list) or not rule["patterns"]:
            raise VocabularyError(f"rule without patterns: {rule.get('label')}")
        for pattern in rule["patterns"]:
            re.compile(pattern)  # fail at load, not at scan time
    contexts = data.get("contexts")
    if not isinstance(contexts, dict) or not contexts.get("practiceExclusion"):
        raise VocabularyError("vocabulary must carry context gates")
    return data


def compiled_rules(vocab: dict) -> list[dict]:
    rules = []
    for rule in vocab["rules"]:
        rules.append({
            "status": rule["status"],
            "observation": rule.get("observation", ""),
            "label": rule["label"],
            "weight": int(rule.get("weight", 1)),
            "regexes": [re.compile(pattern, re.IGNORECASE) for pattern in rule["patterns"]],
        })
    return rules


def classify_all(text: str, vocab: dict | None = None) -> list[dict]:
    """Every distinct in-game phrase the text carries, strongest first.

    Returns ``[]`` — never a guess — when the text says nothing about
    availability, so play-by-play chatter stays silent.
    """
    value = str(text or "")
    if len(value) < 12 or len(value) > 4000:
        return []
    vocab = vocab or load_vocabulary()
    found: list[dict] = []
    for rule in compiled_rules(vocab):
        for regex in rule["regexes"]:
            match = regex.search(value)
            if match:
                found.append({
                    "status": rule["status"],
                    "observation": rule["observation"],
                    "label": rule["label"],
                    "weight": rule["weight"],
                    "phrase": match.group(0).strip(),
                    "matchedAt": match.start(),
                })
                break
    found.sort(key=lambda item: (-item["weight"], item["matchedAt"]))
    return found


def classify(text: str, vocab: dict | None = None) -> dict | None:
    """The single strongest signal in the text, or ``None``."""
    found = classify_all(text, vocab)
    return found[0] if found else None


def practice_language(sentence: str, vocab: dict | None = None) -> bool:
    """True when the sentence reads like a practice/injury-report status."""
    vocab = vocab or load_vocabulary()
    lowered = sentence.lower()
    return any(word.lower() in lowered for word in vocab["contexts"]["practiceExclusion"])


def in_game_language(sentence: str, vocab: dict | None = None) -> bool:
    vocab = vocab or load_vocabulary()
    lowered = sentence.lower()
    return any(word.lower() in lowered for word in vocab["contexts"]["inGame"])


def has_game_date_hint(sentence: str, vocab: dict | None = None) -> bool:
    vocab = vocab or load_vocabulary()
    lowered = sentence.lower()
    return any(word.lower() in lowered for word in vocab["contexts"]["gameDateHint"])


def player_name(sentence: str) -> str | None:
    """A conservative player-name guess used for review text, never for matching.

    Two capitalised words (optionally three) that are not the start of a
    sentence-only phrase. The extracted name is stored with the candidate for a
    human to confirm; it is not used to build an archive id.
    """
    for match in _NAME.finditer(sentence or ""):
        candidate = match.group(1).strip(" .,'’")
        parts = candidate.split()
        if len(parts) < 2 or len(parts) > 3:
            continue
        if any(part.lower() in {"The", "Sunday", "Monday", "Thursday", "Saturday", "Week", "Nfl", "Head", "Coach"} for part in parts):
            continue
        if any(part.isupper() and len(part) > 1 for part in parts):
            continue
        return candidate
    return None


def sentences(text: str) -> list[str]:
    """Plain-text sentences from an already de-tagged page body."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(clean) if part.strip()]


def visible_text(html: str) -> str:
    """Crude, dependency-free tag strip: scripts and styles removed first."""
    without_scripts = _HTML_SCRIPT.sub(" ", html or "")
    text = _HTML_TAG.sub(" ", without_scripts)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
                .replace("&apos;", "'").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"[ \t\u00a0]+", " ", text)


def candidate_sentences(text: str, *, vocab: dict | None = None, max_length: int = 400) -> list[dict]:
    """Sentences that could describe an in-game event.

    Four gates, all required, all checkable by a reviewer:

    1. the sentence carries one of the closed in-game phrases;
    2. it is not a practice/injury-report sentence (those describe a status,
       never a moment in a game);
    3. it names somebody (a capitalised name token) so a reader knows who;
    4. it is short enough to quote verbatim and long enough to mean something.
    """
    vocab = vocab or load_vocabulary()
    out: list[dict] = []
    for sentence in sentences(text):
        if not (30 <= len(sentence) <= max_length):
            continue
        signal = classify(sentence, vocab)
        if not signal:
            continue
        if practice_language(sentence, vocab):
            continue
        if not in_game_language(sentence, vocab):
            continue
        name = player_name(sentence)
        if not name:
            continue
        out.append({
            "quote": sentence,
            "player_guess": name,
            "signal": {key: signal[key] for key in ("status", "observation", "label", "phrase", "weight")},
            "gameHint": has_game_date_hint(sentence, vocab),
            "dateHint": next((word for word in ("Sunday", "Monday", "Thursday", "Saturday", "tonight") if word.lower() in sentence.lower()), ""),
        })
    return out


def article_links(html: str, base_host: str, patterns: tuple[str, ...] = ()) -> list[str]:
    """Same-host article links on a club index page, newest-first order preserved."""
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="([^"#?]+)"', html or ""):
        href = match.group(1)
        if not href.startswith("/"):
            continue
        if not href.startswith("/news/") and not href.startswith("/game-day/"):
            continue
        if href in seen:
            continue
        if patterns and not any(pattern in href for pattern in patterns):
            continue
        seen.add(href)
        links.append(f"https://{base_host}{href}")
    return links

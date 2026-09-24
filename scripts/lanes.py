"""Network lanes used by the CI collectors (club pages and ESPN public feeds).

Everything here is read-only, host-allowlisted, size-bounded and fails closed:
an unreachable lane returns an error the caller must record, it never returns
invented data. Parsing is deliberately defensive — this project would rather
show nothing than show a name it did not read.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from clubs import CLUBS

USER_AGENT = "InjuryAlerTNFL/1.0 (+https://buffedlizard55-lab.github.io/InjuryAlerTNFL/; public injury monitor)"
ESPN_HOSTS = frozenset({"site.api.espn.com", "site.web.api.espn.com", "sports.core.api.espn.com"})
CLUB_HOSTS = frozenset(club["host"] for club in CLUBS.values())
MAX_BYTES = 3_000_000
MAX_JSON_BYTES = 8_000_000

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
HEADER = "https://site.web.api.espn.com/apis/v2/scoreboard/header?sport=football&league=nfl"
NEWS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"
INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"


def summary(event_id: str) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={event_id}"


def plays_url(event_id: str, competition_id: str, limit: int = 1000) -> str:
    return (f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{event_id}"
            f"/competitions/{competition_id}/plays?limit={limit}")


def week_scoreboard_url(season: int, week: int) -> str:
    return f"{SCOREBOARD}?seasontype=2&week={week}&year={season}&limit=20"


def date_scoreboard_url(day: str) -> str:
    return f"{SCOREBOARD}?dates={day}&limit=50"


class LaneError(RuntimeError):
    pass


def http_get(url: str, *, kind: str = "html", timeout: int = 14, allowed: frozenset[str] | None = None) -> bytes:
    parsed = urlparse(url)
    hosts = allowed if allowed is not None else (ESPN_HOSTS | CLUB_HOSTS)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise LaneError(f"refusing to fetch {url!r}: host is not on the allowlist")
    accept = "application/json" if kind == "json" else "text/html"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.8"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlisted hosts only
        final = urlparse(response.geturl())
        if final.hostname not in hosts:
            raise LaneError(f"redirect left the allowlist: {final.hostname}")
        limit = MAX_JSON_BYTES if kind == "json" else MAX_BYTES
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise LaneError(f"response exceeded {limit} bytes")
    return raw


def json_get(url: str, *, timeout: int = 14, allowed: frozenset[str] | None = None) -> dict:
    raw = http_get(url, kind="json", timeout=timeout, allowed=allowed)
    try:
        return json.loads(raw)
    except ValueError as error:
        raise LaneError(f"lane did not return JSON: {error}") from error


# --------------------------------------------------------------------------- #
# ESPN scoreboard / header
# --------------------------------------------------------------------------- #
PHASES = {"in": "live", "post": "final", "pre": "scheduled"}


def parse_games(payload: dict | None) -> list[dict]:
    """Games from a site.api scoreboard payload. Unknown shapes yield no games."""
    games: list[dict] = []
    for event in (payload or {}).get("events", []) or []:
        try:
            code = str(event["id"])
            competition = (event.get("competitions") or [{}])[0]
            sides = {side.get("homeAway"): side for side in competition.get("competitors", [])}
            home, away = sides.get("home"), sides.get("away")
            habbr = home["team"]["abbreviation"]
            aabbr = away["team"]["abbreviation"]
            if habbr not in CLUBS or aabbr not in CLUBS or habbr == aabbr:
                continue
            phase = PHASES.get(event.get("status", {}).get("type", {}).get("state", ""))
            if not phase:
                continue
            detail = str(event["status"]["type"].get("shortDetail") or event["status"]["type"].get("description") or "")[:40]
            games.append({
                "id": code,
                "date": str(event.get("date") or ""),
                "home": habbr,
                "away": aabbr,
                "homeScore": None if phase == "scheduled" else _score(home),
                "awayScore": None if phase == "scheduled" else _score(away),
                "phase": phase,
                "detail": detail,
                "venue": ((competition.get("venue") or {}) or {}).get("fullName", ""),
                "url": f"https://www.espn.com/nfl/game/_/gameId/{code}",
            })
        except (KeyError, IndexError, TypeError, AttributeError):
            continue
    # The header lane (site.web.api) nests events differently; normalise both.
    if not games:
        for sport in (payload or {}).get("sports", []) or []:
            for league in sport.get("leagues", []) or []:
                for event in league.get("events", []) or []:
                    try:
                        sides = {side.get("homeAway"): side for side in event.get("competitors", [])}
                        habbr = sides["home"].get("abbreviation") or sides["home"]["team"]["abbreviation"]
                        aabbr = sides["away"].get("abbreviation") or sides["away"]["team"]["abbreviation"]
                        if habbr not in CLUBS or aabbr not in CLUBS:
                            continue
                        full = event.get("fullStatus") or {}
                        kind = (full.get("type") or {}).get("state", "")
                        phase = PHASES.get(kind)
                        if not phase:
                            continue
                        games.append({
                            "id": str(event.get("id") or ""),
                            "date": str(event.get("date") or ""),
                            "home": habbr,
                            "away": aabbr,
                            "homeScore": None if phase == "scheduled" else str(sides["home"].get("score", "")),
                            "awayScore": None if phase == "scheduled" else str(sides["away"].get("score", "")),
                            "phase": phase,
                            "detail": str(full.get("type", {}).get("shortDetail") or full.get("displayClock") or "")[:40],
                            "venue": "",
                            "url": f"https://www.espn.com/nfl/game/_/gameId/{event.get('id')}",
                        })
                    except (KeyError, IndexError, TypeError, AttributeError):
                        continue
    return [game for game in games if game["id"].isdigit()]


def _score(side: dict) -> str | None:
    value = str(side.get("score", "")).strip()
    return value if re.fullmatch(r"\d{1,3}", value) else None


def week_games(season: int, week: int, *, get=json_get) -> list[dict]:
    return parse_games(get(week_scoreboard_url(season, week)))


def day_games(day: str, *, get=json_get) -> list[dict]:
    return parse_games(get(date_scoreboard_url(day)))


def schedule_index(season: int, weeks: list[int], *, get=json_get, failures: list[str] | None = None) -> dict[str, dict]:
    """``{"YYYY-MM-DD": {TLA: opponent}}`` for the weeks asked for.

    It exists so a club sentence can be tied to the game it describes without
    anyone typing an opponent in by hand. A week that fails to load is recorded
    as a lane failure and simply contributes no dates.
    """
    index: dict[str, dict] = {}
    for week in weeks:
        try:
            games = week_games(season, week, get=get)
        except Exception as error:  # noqa: BLE001 - a lane failure is data, not a crash
            if failures is not None:
                failures.append(f"ESPN week {week} schedule unavailable ({type(error).__name__})")
            continue
        for game in games:
            day = str(game.get("date") or "")[:10]
            if len(day) != 10:
                continue
            mapping = index.setdefault(day, {})
            mapping[game["home"]] = game["away"]
            mapping[game["away"]] = game["home"]
    return index


# --------------------------------------------------------------------------- #
# Play-by-play and injury sections
# --------------------------------------------------------------------------- #
def walk(node, depth: int = 0):
    """Yield every dict/str in a JSON tree, bounded, with no exposure to cycles."""
    if depth > 12:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value, depth + 1)


def injury_records(payload: dict) -> list[dict]:
    """Any ``injuries`` array inside a payload, normalised and deduplicated.

    ESPN has moved this section around between endpoints, so the reader walks
    the tree instead of hard-coding a path. A record without an athlete name or
    status is dropped: it cannot be shown to a reader.
    """
    records: list[dict] = []
    seen: set[tuple] = set()

    def collect(node, depth: int = 0):
        if depth > 8:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "injuries" and isinstance(value, list):
                    for item in value:
                        collect_injury(item, node, depth)
                else:
                    collect(value, depth + 1)
        elif isinstance(node, list):
            for item in node:
                collect(item, depth + 1)

    def collect_injury(item, parent, depth):
        if not isinstance(item, dict):
            return
        nested = item.get("injuries")
        if isinstance(nested, list):  # team wrapper: descend with the team attached
            team = item.get("team") or item
            for inner in nested:
                collect_injury(inner, team, depth + 1)
            return
        athlete = item.get("athlete") or {}
        name = athlete.get("displayName") or athlete.get("fullName") or ""
        status = item.get("status") or item.get("type", {}).get("description", "")
        if not name or not status:
            return
        team_abbr = ""
        team = item.get("team") or parent.get("team") or parent
        if isinstance(team, dict):
            team_abbr = str(team.get("abbreviation") or "")
        key = (name, str(status), str(item.get("date") or ""))
        if key in seen:
            return
        seen.add(key)
        records.append({
            "athlete": str(name),
            "status": str(status),
            "detail": str(item.get("detail") or item.get("longComment") or item.get("shortComment") or "")[:300],
            "date": str(item.get("date") or ""),
            "teamAbbreviation": team_abbr,
            "side": str(item.get("side") or ""),
        })

    collect(payload or {})
    return records


def play_records(payload: dict, *, limit: int = 1200) -> list[dict]:
    """Play objects with their own clock and wall-clock timestamp.

    The core API dates each play to the second (``wallclock``), which is the
    closest thing a free feed gives us to "when in the game did this happen".
    """
    plays: list[dict] = []
    for node in walk(payload or {}):
        if not isinstance(node, dict):
            continue
        text = node.get("text") or node.get("shortText")
        if not isinstance(text, str) or not text.strip():
            continue
        if "clock" not in node and "wallclock" not in node:
            continue
        plays.append({
            "text": text.strip()[:400],
            "wallclock": str(node.get("wallclock") or ""),
            "period": (node.get("period") or {}).get("number") if isinstance(node.get("period"), dict) else node.get("period"),
            "clock": (node.get("clock") or {}).get("displayValue") if isinstance(node.get("clock"), dict) else None,
            "type": (node.get("type") or {}).get("text") if isinstance(node.get("type"), dict) else None,
        })
        if len(plays) >= limit:
            break
    return plays


# --------------------------------------------------------------------------- #
# Club article metadata
# --------------------------------------------------------------------------- #
class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key and attributes.get("content"):
                self.meta.setdefault(key, attributes["content"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()


def article_meta(html: str) -> dict:
    parser = _MetaParser()
    try:
        parser.feed(html[:400_000])
    except Exception:  # noqa: BLE001 - malformed markup must never raise
        pass
    published = (parser.meta.get("article:published_time")
                 or parser.meta.get("datepublished")
                 or parser.meta.get("published_time")
                 or "")
    if not published:
        match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html or "")
        published = match.group(1) if match else ""
    return {"title": parser.title or parser.meta.get("og:title", ""), "published": published.strip()}

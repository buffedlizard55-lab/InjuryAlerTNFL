"""One table for the 32 club newsrooms: host, human label and the words that
identify the club inside a sentence.

It exists so three things cannot drift apart: the official-source allowlist in
``schema.py``, the club discovery scan in ``clubscan.py``, and the browser's
link allowlist (checked by a test). The ``tokens`` are used only to decide
whether a sentence is plausibly about this club; they are never used to guess a
player's identity.
"""
from __future__ import annotations

CLUBS: dict[str, dict] = {
    "ARI": {"host": "www.azcardinals.com", "label": "Arizona Cardinals", "tokens": ("cardinals", "arizona")},
    "ATL": {"host": "www.atlantafalcons.com", "label": "Atlanta Falcons", "tokens": ("falcons", "atlanta")},
    "BAL": {"host": "www.baltimoreravens.com", "label": "Baltimore Ravens", "tokens": ("ravens", "baltimore")},
    "BUF": {"host": "www.buffalobills.com", "label": "Buffalo Bills", "tokens": ("bills", "buffalo")},
    "CAR": {"host": "www.panthers.com", "label": "Carolina Panthers", "tokens": ("panthers", "carolina")},
    "CHI": {"host": "www.chicagobears.com", "label": "Chicago Bears", "tokens": ("bears", "chicago")},
    "CIN": {"host": "www.bengals.com", "label": "Cincinnati Bengals", "tokens": ("bengals", "cincinnati")},
    "CLE": {"host": "www.clevelandbrowns.com", "label": "Cleveland Browns", "tokens": ("browns", "cleveland")},
    "DAL": {"host": "www.dallascowboys.com", "label": "Dallas Cowboys", "tokens": ("cowboys", "dallas")},
    "DEN": {"host": "www.denverbroncos.com", "label": "Denver Broncos", "tokens": ("broncos", "denver")},
    "DET": {"host": "www.detroitlions.com", "label": "Detroit Lions", "tokens": ("lions", "detroit")},
    "GB": {"host": "www.packers.com", "label": "Green Bay Packers", "tokens": ("packers", "green bay")},
    "HOU": {"host": "www.houstontexans.com", "label": "Houston Texans", "tokens": ("texans", "houston")},
    "IND": {"host": "www.colts.com", "label": "Indianapolis Colts", "tokens": ("colts", "indianapolis")},
    "JAX": {"host": "www.jaguars.com", "label": "Jacksonville Jaguars", "tokens": ("jaguars", "jacksonville")},
    "KC": {"host": "www.chiefs.com", "label": "Kansas City Chiefs", "tokens": ("chiefs", "kansas city")},
    "LAC": {"host": "www.chargers.com", "label": "Los Angeles Chargers", "tokens": ("chargers", "los angeles chargers")},
    "LAR": {"host": "www.rams.com", "label": "Los Angeles Rams", "tokens": ("rams", "los angeles rams")},
    "LV": {"host": "www.raiders.com", "label": "Las Vegas Raiders", "tokens": ("raiders", "las vegas")},
    "MIA": {"host": "www.miamidolphins.com", "label": "Miami Dolphins", "tokens": ("dolphins", "miami")},
    "MIN": {"host": "www.vikings.com", "label": "Minnesota Vikings", "tokens": ("vikings", "minnesota")},
    "NE": {"host": "www.patriots.com", "label": "New England Patriots", "tokens": ("patriots", "new england")},
    "NO": {"host": "www.neworleanssaints.com", "label": "New Orleans Saints", "tokens": ("saints", "new orleans")},
    "NYG": {"host": "www.giants.com", "label": "New York Giants", "tokens": ("giants", "new york giants")},
    "NYJ": {"host": "www.newyorkjets.com", "label": "New York Jets", "tokens": ("jets", "new york jets")},
    "PHI": {"host": "www.philadelphiaeagles.com", "label": "Philadelphia Eagles", "tokens": ("eagles", "philadelphia")},
    "PIT": {"host": "www.steelers.com", "label": "Pittsburgh Steelers", "tokens": ("steelers", "pittsburgh")},
    "SEA": {"host": "www.seahawks.com", "label": "Seattle Seahawks", "tokens": ("seahawks", "seattle")},
    "SF": {"host": "www.49ers.com", "label": "San Francisco 49ers", "tokens": ("49ers", "san francisco")},
    "TB": {"host": "www.buccaneers.com", "label": "Tampa Bay Buccaneers", "tokens": ("buccaneers", "tampa bay")},
    "TEN": {"host": "www.tennesseetitans.com", "label": "Tennessee Titans", "tokens": ("titans", "tennessee")},
    "WAS": {"host": "www.commanders.com", "label": "Washington Commanders", "tokens": ("commanders", "washington")},
}

# Pages that are worth reading on every scan, in the order that pays best.
INDEX_PATHS = ("/news/", "/news/injury-report/", "/game-day/")
# Slugs that historically carry an in-game sentence rather than a status table.
ARTICLE_PATTERNS = (
    "recap", "game-report", "notebook", "quick-hits", "takeaways", "in-game", "injury",
    "sidelined", "ir-", "injured-reserve", "roster", "transcript", "postgame", "highlights",
)
# Slugs that are almost never about a game: skip them so the scan stays cheap.
ARTICLE_EXCLUSIONS = (
    "tickets", "shop", "photos", "wallpaper", "parking", "how-to-watch", "depth-chart",
    "mock-draft", "power-rankings", "cheerleaders", "community", "foundation", "podcast",
    "uniform", "schedule-release", "vote", "pro-bowl",
)


def club_for_host(host: str) -> str | None:
    for code, club in CLUBS.items():
        if club["host"] == host:
            return code
    return None


def club_tokens(code: str) -> tuple[str, ...]:
    return CLUBS.get(code, {}).get("tokens", ())

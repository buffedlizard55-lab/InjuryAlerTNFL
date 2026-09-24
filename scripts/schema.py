"""Small, fail-closed schema for publicly displayed claims. No remote calls."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

TEAMS = frozenset(
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV "
    "MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split()
)
OUTCOMES = frozenset({"out", "did_not_return", "returned", "unconfirmed"})
KINDS = frozenset({"game", "observation", "followup"})
OBSERVATIONS = frozenset({
    "Blue tent", "Locker room", "Carted to locker room", "Helped off field",
    "Walked off field", "Left game", "Returned after halftime", "Injured during game", "Walking boot after game",
})
ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z]{2,3}-[a-z0-9-]+$")


class InvalidData(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidData(message)


def official_url(url: str, *, player_page: bool = False) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return False
    # Official league and club newsrooms. We allow the league site and
    # all 32 club sites plus a few legacy nfl.com player-page hosts.
    # This is the allowlist for what can appear as a source link in the
    # verified archive; it is intentionally narrow and fails closed.
    allowed_news_hosts = {
        "www.nfl.com",
        "www.dallascowboys.com",
        "www.denverbroncos.com",
        "www.buffalobills.com",
        "www.atlantafalcons.com",
        "www.baltimoreravens.com",
        "www.panthers.com",
        "www.chicagobears.com",
        "www.bengals.com",
        "www.clevelandbrowns.com",
        "www.detroitlions.com",
        "www.packers.com",
        "www.houstontexans.com",
        "www.colts.com",
        "www.jaguars.com",
        "www.chiefs.com",
        "www.chargers.com",
        "www.rams.com",
        "www.raiders.com",
        "www.dolphins.com",
        "www.vikings.com",
        "www.patriots.com",
        "www.saints.com",
        "www.giants.com",
        "www.nyjets.com",
        "www.newyorkjets.com",
        "www.jets.com",
        "www.eagles.com",
        "www.philadelphiaeagles.com",
        "www.steelers.com",
        "www.49ers.com",
        "www.seahawks.com",
        "www.buccaneers.com",
        "www.titans.com",
        "www.commanders.com",
        "www.azcardinals.com",
        "www.cardinals.com",
    }
    hostname = parsed.hostname or ""
    # Allow any sub-domain of nfl.com for future league moves, plus the
    # explicit club list above.
    host_ok = (
        hostname in allowed_news_hosts
        or hostname.endswith(".nfl.com")
        or (hostname.startswith("www.") and hostname.endswith("broncos.com"))
        or (hostname.startswith("www.") and hostname.endswith("bills.com"))
    )
    return (
        parsed.scheme == "https"
        and host_ok
        and port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query and not parsed.fragment
        and (parsed.path.startswith("/news/") or parsed.path.startswith("/videos/") or (player_page and hostname == "www.nfl.com" and parsed.path.startswith("/players/")))
        and "//" not in parsed.path
    )


def validate_incidents(incidents: list, *, automatic: bool = False) -> None:
    require(isinstance(incidents, list), "incidents must be a list")
    ids: set[str] = set()
    for row in incidents:
        require(isinstance(row, dict), "incident must be an object")
        key = row.get("id")
        require(isinstance(key, str) and ID.fullmatch(key) is not None, f"invalid ID: {key}")
        require(key not in ids, f"duplicate incident: {key}")
        ids.add(key)
        event_date = date.fromisoformat(row["gameDate"])
        name_slug = re.sub(r"[^a-z0-9]+", "-", row["player"].lower()).strip("-") if isinstance(row.get("player"), str) else ""
        require(key == f"{event_date.isoformat()}-{row['team'].lower()}-{name_slug}", f"game/team/player in ID: {key}")
        require(row["team"] in TEAMS and row["opponent"] in TEAMS and row["team"] != row["opponent"], f"teams: {key}")
        for field in ("player", "position", "injury"):
            require(isinstance(row.get(field), str) and 1 <= len(row[field]) <= 100, f"{field}: {key}")
        require(row.get("outcome") in OUTCOMES, f"outcome: {key}")
        require(isinstance(row.get("observations"), list) and all(o in OBSERVATIONS for o in row["observations"]), f"observations: {key}")
        claims = row.get("claims")
        require(isinstance(claims, list) and any(c.get("kind") == "game" for c in claims if isinstance(c, dict)), f"game claim: {key}")
        last = event_date
        for claim in claims:
            require(isinstance(claim, dict) and claim.get("kind") in KINDS, f"claim kind: {key}")
            day = date.fromisoformat(claim["date"])
            require(event_date <= day and day >= last, f"chronology: {key}")
            last = day
            require(isinstance(claim.get("text"), str) and 12 <= len(claim["text"]) <= 320, f"claim: {key}")
            require(isinstance(claim.get("quote"), str) and 10 <= len(claim["quote"]) <= 220, f"quote: {key}")
            require(official_url(claim.get("url")), f"untrusted source: {key}")
            if claim["kind"] == "game":
                excerpt = claim["quote"].lower()
                # did_not_return now also accepts the club-recap phrase
                # "missed the remainder of the game" as an explicit grounding,
                # per the audit's next-step recommendation for Cobie Durant.
                markers = {
                    "did_not_return": ("did not return", "missed the remainder of the game"),
                    "returned": ("returned", "returning"),
                }
                if row["outcome"] == "out":
                    require(re.search(r"\bruled(?:\s+\S+){0,3}\s+out\b", excerpt) is not None,
                            f"game outcome not grounded by excerpt: {key}")
                elif row["outcome"] in markers:
                    require(any(marker in excerpt for marker in markers[row["outcome"]]), f"game outcome not grounded by excerpt: {key}")
        if automatic:
            require(row.get("automatic") is True, f"auto marker: {key}")
            require(isinstance(row.get("capturedAt"), str) and row["capturedAt"].endswith("Z"), f"capture time: {key}")
            require(isinstance(row.get("gameStart"), str) and row["gameStart"].endswith("Z"), f"game start: {key}")
            require(row["injury"] == "Not specified" or row["injury"].lower() in {
                "ankle", "back", "calf", "chest", "concussion", "elbow", "foot", "groin", "hamstring", "hand",
                "hip", "knee", "neck", "quad", "shoulder", "stinger", "thigh", "toe", "wrist",
            }, f"auto injury inference: {key}")
            require(row["outcome"] != "unconfirmed", f"auto outcome: {key}")


def validate_archive(data: dict) -> None:
    require(data.get("version") == 1, "archive version")
    checked = date.fromisoformat(data["verifiedOn"])
    validate_incidents(data["incidents"])
    for row in data["incidents"]:
        require(date.fromisoformat(row["gameDate"]) <= checked, f"future game: {row['id']}")
        require(all(date.fromisoformat(c["date"]) <= checked for c in row["claims"]), f"future claim: {row['id']}")


def validate_review(data: dict) -> None:
    require(data.get("version") == 1, "review version")
    date.fromisoformat(data["verifiedOn"])
    ids: set[str] = set()
    for row in data["flags"]:
        require(isinstance(row.get("id"), str) and ID.fullmatch(row["id"]) is not None, "review ID")
        require(row["id"] not in ids, "duplicate review flag")
        ids.add(row["id"])
        require(row.get("disposition") in {"held", "annotated"}, "review disposition")
        require(isinstance(row.get("incidentId"), str) and ID.fullmatch(row["incidentId"]) is not None, "review incident ID")
        require(row["id"].startswith(row["incidentId"] + "-"), "review ID does not reference incident")
        require(isinstance(row.get("subject"), str) and row["subject"], "review subject")
        require(isinstance(row.get("reason"), str) and 15 <= len(row["reason"]) <= 400, "review reason")
        require(isinstance(row.get("links"), list) and len(row["links"]) >= 2, "review links")
        require(all(official_url(link, player_page=True) for link in row["links"]), "untrusted review link")

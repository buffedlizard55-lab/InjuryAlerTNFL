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
# Second-precision UTC only: this project may not print precision it does not have.
SECONDS_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
LOG_KINDS = frozenset({"roundup-match", "club-candidate", "club-promotion", "live-signal", "lane-status", "lane-failure", "roster-followup"})
LOG_KINDS_LANES = frozenset({"club-scan", "club-page", "browser-lane", "espn-plays", "espn-summary", "espn-header", "nfl-roundup", "roundup", "watch", "social-search"})


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
    "www.49ers.com",
    "www.atlantafalcons.com",
    "www.azcardinals.com",
    "www.baltimoreravens.com",
    "www.bengals.com",
    "www.buccaneers.com",
    "www.buffalobills.com",
    "www.chargers.com",
    "www.chicagobears.com",
    "www.chiefs.com",
    "www.clevelandbrowns.com",
    "www.colts.com",
    "www.commanders.com",
    "www.dallascowboys.com",
    "www.denverbroncos.com",
    "www.detroitlions.com",
    "www.giants.com",
    "www.houstontexans.com",
    "www.jaguars.com",
    "www.miamidolphins.com",
    "www.neworleanssaints.com",
    "www.newyorkjets.com",
    "www.nfl.com",
    "www.packers.com",
    "www.panthers.com",
    "www.patriots.com",
    "www.philadelphiaeagles.com",
    "www.raiders.com",
    "www.rams.com",
    "www.seahawks.com",
    "www.steelers.com",
    "www.tennesseetitans.com",
    "www.vikings.com",
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
        and (
            parsed.path.startswith("/news/")
            or parsed.path.startswith("/videos/")
            # Club game-day recap pages (e.g. .../game-day/2026/reg-week2/ravens-vs-saints/recap)
            # are club-authored and state in-game injuries; the Saints' Week 2 recap is the
            # worked example that put Martin Emerson Jr. in the ledger.
            or parsed.path.startswith("/game-day/")
            or (player_page and hostname == "www.nfl.com" and parsed.path.startswith("/players/"))
        )
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
        # One source sentence is one claim: repeating the same excerpt under the same
        # URL adds no evidence and inflates the claim ledger a reviewer counts on.
        require(len({(str(c.get("url")), str(c.get("quote"))) for c in claims}) == len(claims),
                f"duplicate claim in {key}")
        # An automatically promoted row must carry the sentence it was promoted
        # from, its URL and both read times, so a reader can audit the machine's
        # reasoning without trusting it. A promoted row may never be edited by
        # hand without dropping the block.
        promotion = row.get("promotion")
        if promotion is not None:
            require(isinstance(promotion, dict), f"promotion block: {key}")
            require(isinstance(promotion.get("quote"), str) and promotion["quote"].strip(), f"promotion quote: {key}")
            require(official_url(promotion.get("url", "")), f"promotion url: {key}")
            require(promotion["quote"].strip() in {c["quote"].strip() for c in claims},
                    f"promotion quote must be one of the row's claims: {key}")
            require(promotion["url"] in {c["url"] for c in claims}, f"promotion url must be one of the row's sources: {key}")
            require(int(promotion.get("reads", 0)) >= 2, f"promotion needs two independent reads: {key}")
            for field in ("firstSeen", "lastSeen"):
                require(SECONDS_UTC.fullmatch(str(promotion.get(field, ""))) is not None,
                        f"promotion {field} needs a second-precision UTC stamp: {key}")
            require(promotion.get("lane") in LOG_KINDS_LANES, f"promotion lane: {key}")
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


TIERS = frozenset({"official", "partner", "unofficial"})
SOURCE_STATUS = frozenset({"verified", "verified-exists", "verified-endpoint", "blocked", "link-out-only", "pending-reprobe"})
SOURCE_ROLES = frozenset({
    "in-game-signal", "in-game-discovery", "followup-signal", "pregame-status", "official-play-by-play",
    "club-in-game-and-followup", "postgame-signal", "scores-only", "live-game-state", "news-lead",
    "status-context", "play-by-play-unverified", "game-enumeration", "social-lead",
    "play-by-play", "club-scan-index", "injury-aggregator", "social-video-lead",
})
SOURCE_CATEGORIES = frozenset({
    "official-league", "official-club", "official-club-game-page", "official-protocol",
    "partner-espn", "partner-other",
    "unofficial-social", "unofficial-aggregator", "unofficial-beat", "unofficial-video",
})
LATENCY_CLASSES = frozenset({"seconds", "minutes", "hours", "daily", "weekly", "blocked", "link-out"})
TIMESTAMP_PRECISION = frozenset({"second", "minute", "quarter", "day", "none"})
SOURCE_ACCESS = frozenset({"keyless-json", "html", "auth-required", "blocked", "link-out", "rss"})
LEAD_STATUS = frozenset({"unverified"})


def https_url(url: str) -> bool:
    """Any well-formed public https URL. Used only for non-evidence tiers."""
    if not isinstance(url, str) or len(url) > 400:
        return False
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and "." in (parsed.hostname or "")
        and parsed.username is None
        and parsed.password is None
    )


def validate_sources(data: dict) -> None:
    """The registry must fail closed: a bad tier, role or missing probe record is an error.

    The point of the file is that every row states how it was checked and what it can
    and cannot prove. An entry that only claims to be trustworthy cannot pass.
    """
    require(data.get("version") == 1, "sources version")
    date.fromisoformat(data["verifiedOn"])
    policy = data.get("policy")
    require(isinstance(policy, dict) and set(policy) >= {"official", "partner", "unofficial", "rule"},
            "sources policy block")
    sources = data.get("sources")
    require(isinstance(sources, list) and len(sources) >= 8, "sources list")
    ids: set[str] = set()
    for entry in sources:
        require(isinstance(entry, dict), "source entry")
        key = entry.get("id")
        require(isinstance(key, str) and key and key not in ids, f"source id: {key}")
        ids.add(key)
        require(entry.get("tier") in TIERS, f"source tier: {key}")
        require(entry.get("role") in SOURCE_ROLES, f"source role: {key}")
        # Organisation, not decoration: a reader filters the registry by these,
        # so a lane without them cannot be presented as organised.
        require(entry.get("category") in SOURCE_CATEGORIES, f"source category: {key}")
        require(entry.get("latencyClass") in LATENCY_CLASSES, f"source latency class: {key}")
        require(entry.get("timestampPrecision") in TIMESTAMP_PRECISION, f"source timestamp precision: {key}")
        require(entry.get("access") in SOURCE_ACCESS, f"source access: {key}")
        # Tier and category may not contradict each other.
        if entry["tier"] == "official":
            require(entry["category"].startswith("official"), f"official lane with a non-official category: {key}")
        elif entry["tier"] == "partner":
            require(entry["category"].startswith("partner"), f"partner lane with a non-partner category: {key}")
        else:
            require(entry["category"].startswith("unofficial"), f"unofficial lane with a non-unofficial category: {key}")
        if entry["access"] == "link-out":
            require(entry["latencyClass"] == "link-out", f"a link-out lane cannot claim a measured latency: {key}")
        for field in ("name", "org", "what", "proves", "notes"):
            require(isinstance(entry.get(field), str) and entry[field], f"source {field}: {key}")
        require(isinstance(entry.get("latency"), str) and entry["latency"], f"source latency: {key}")
        require(isinstance(entry.get("inGame"), bool), f"source inGame flag: {key}")
        require(isinstance(entry.get("autoPublish"), bool), f"source autoPublish flag: {key}")
        require(https_url(entry.get("url", "")), f"source url: {key}")
        # Only a league/club row may auto-publish into the verified ledger.
        if entry["autoPublish"]:
            require(entry["tier"] == "official", f"only official sources may auto-publish: {key}")
        # An unofficial lane may report in-game chatter, but it can never be an evidence lane,
        # and it must be labelled as a lead wherever it is shown.
        if entry["tier"] != "official":
            require(not entry["autoPublish"], f"non-official source cannot auto-publish: {key}")
        if entry["tier"] == "unofficial":
            # Unofficial material may only ever be a lead: a social post, a beat
            # note, an aggregator row, a clip somebody watched, or an open-data
            # play-by-play dump. None of these may ground a verified row.
            require(entry["role"] in {"social-lead", "news-lead", "injury-aggregator", "social-video-lead",
                                      "play-by-play-unverified"},
                    f"unofficial source must be a lead role: {key}")
        check = entry.get("verification")
        require(isinstance(check, dict), f"source verification: {key}")
        require(check.get("status") in SOURCE_STATUS, f"source verification status: {key}")
        require(isinstance(check.get("method"), str) and len(check["method"]) >= 20, f"source probe method: {key}")
        require(isinstance(check.get("evidence"), str) and https_url(check["evidence"]), f"source evidence url: {key}")
        if check["status"] == "pending-reprobe":
            require(check.get("checkedOn") is None, f"pending source cannot claim a re-check date: {key}")
        else:
            date.fromisoformat(check["checkedOn"])
    # The registry must always carry the boundary sources a reader would ask about.
    required_lanes = {"nfl-gamecenter-json", "espn-scoreboard", "espn-summary-plays", "x-twitter", "reddit-json"}
    require(required_lanes <= ids, "registry is missing a boundary source (auth-gated NFL JSON, ESPN lanes, X, Reddit)")


def validate_leads(data: dict) -> None:
    """Unofficial leads are structurally checkable but never evidence: no archive claims allowed."""
    require(data.get("version") == 1, "leads version")
    date.fromisoformat(data["capturedOn"])
    require(isinstance(data.get("label"), str) and "UNOFFICIAL" in data["label"].upper(), "leads label")
    leads = data.get("leads")
    require(isinstance(leads, list) and leads, "leads list")
    ids: set[str] = set()
    for lead in leads:
        require(isinstance(lead, dict), "lead entry")
        key = lead.get("id")
        require(isinstance(key, str) and key.startswith("lead-") and key not in ids, f"lead id: {key}")
        ids.add(key)
        require(isinstance(lead.get("subject"), str) and lead["subject"], f"lead subject: {key}")
        require(lead.get("team") in TEAMS, f"lead team: {key}")
        require(isinstance(lead.get("text"), str) and 15 <= len(lead["text"]) <= 400, f"lead text: {key}")
        require(isinstance(lead.get("capturedOn"), str), f"lead capture date: {key}")
        date.fromisoformat(lead["capturedOn"])
        require(isinstance(lead.get("verifyNext"), str) and len(lead["verifyNext"]) >= 20, f"lead next step: {key}")
        require(isinstance(lead.get("notes"), str) and lead["notes"], f"lead notes: {key}")
        source = lead.get("source")
        require(isinstance(source, dict), f"lead source: {key}")
        require(source.get("tier") in TIERS, f"lead source tier: {key}")
        # A lead is by definition unverified: a league/club row must never sit in this file.
        require(source["tier"] != "official", f"official material belongs in the archive, not the leads file: {key}")
        require(https_url(source.get("url", "")), f"lead source url: {key}")
        require(isinstance(source.get("name"), str) and source["name"], f"lead source name: {key}")
        if "gameDate" in lead and lead["gameDate"] is not None:
            date.fromisoformat(lead["gameDate"])
        # A lead may intentionally shadow an archived incident when its whole purpose
        # is to re-check that incident for newer dated claims. It has to say so.
        if lead.get("duplicateOf") is not None:
            require(isinstance(lead["duplicateOf"], str) and ID.fullmatch(lead["duplicateOf"]) is not None,
                    f"lead duplicate marker: {key}")


# --------------------------------------------------------------------------- #
# Machine-written artefacts: the alert log, the club-scan candidates and the
# server-side game-window watch. These are validated with the same fail-closed
# rules as the hand-checked files, because the page shows them next to it.
# --------------------------------------------------------------------------- #
def validate_alert_log(data: dict) -> None:
    """Append-only, second-precision, tier-labelled, always with a source URL."""
    require(data.get("version") == 1, "alert log version")
    require(isinstance(data.get("policy"), str) and len(data["policy"]) >= 40, "alert log policy")
    entries = data.get("entries")
    require(isinstance(entries, list), "alert log entries")
    require(len(entries) <= 1200, "alert log is capped at 1200 entries")
    ids: set[str] = set()
    last = "9999-12-31T23:59:59Z"
    for entry in entries:
        require(isinstance(entry, dict), "alert log entry")
        key = entry.get("id")
        require(isinstance(key, str) and key.startswith("log-") and key not in ids, f"alert log id: {key}")
        ids.add(key)
        for field in ("at", "detectedAt"):
            require(SECONDS_UTC.fullmatch(str(entry.get(field, ""))) is not None,
                    f"alert log {field} must be UTC to the second: {key}")
        require(str(entry["at"]) <= last, f"alert log must be newest-first: {key}")
        last = str(entry["at"])
        require(entry.get("kind") in LOG_KINDS, f"alert log kind: {key}")
        require(entry.get("tier") in TIERS, f"alert log tier: {key}")
        require(isinstance(entry.get("lane"), str) and entry["lane"], f"alert log lane: {key}")
        require(isinstance(entry.get("subject"), str) and entry["subject"], f"alert log subject: {key}")
        require(isinstance(entry.get("text"), str) and 5 <= len(entry["text"]) <= 400, f"alert log text: {key}")
        require(https_url(entry.get("evidence", "")), f"alert log evidence url: {key}")
        source_at = entry.get("sourceAt")
        if source_at is not None:
            require(SECONDS_UTC.fullmatch(str(source_at)) is not None,
                    f"alert log sourceAt must be UTC to the second when present: {key}")
        latency = entry.get("latencySeconds")
        if latency is not None:
            require(isinstance(latency, int) and latency >= 0, f"alert log latency: {key}")
            require(source_at is not None, f"alert log latency without a provider timestamp: {key}")
        if entry["tier"] == "unofficial":
            require(entry["kind"] in {"live-signal", "lane-status", "club-candidate"},
                    f"an unofficial tier may only carry leads/observations in the log: {key}")


def validate_candidates(data: dict) -> None:
    """Auto-matched club sentences: quoted, official, and honest about their gate."""
    require(data.get("version") == 1, "candidates version")
    require(isinstance(data.get("label"), str) and "NOT" in data["label"].upper(), "candidates must be labelled as not verified")
    require(isinstance(data.get("policy"), str) and len(data["policy"]) >= 40, "candidates policy")
    rows = data.get("candidates")
    require(isinstance(rows, list) and len(rows) <= 400, "candidates list")
    seen: set[str] = set()
    for row in rows:
        require(isinstance(row, dict), "candidate entry")
        key = row.get("id")
        require(isinstance(key, str) and key.startswith("cand-") and key not in seen, f"candidate id: {key}")
        seen.add(key)
        require(row.get("club") in TEAMS, f"candidate club: {key}")
        require(official_url(row.get("url", "")), f"candidate must cite an official club page: {key}")
        require(isinstance(row.get("quote"), str) and 30 <= len(row["quote"]) <= 400, f"candidate quote: {key}")
        require(isinstance(row.get("player"), str) and row["player"], f"candidate player: {key}")
        signal = row.get("signal")
        require(isinstance(signal, dict) and signal.get("phrase") and signal.get("status"), f"candidate signal: {key}")
        require(isinstance(signal.get("phrase"), str) and signal["phrase"].strip().lower() in row["quote"].lower(),
                f"candidate phrase must appear in its own quote: {key}")
        for field in ("firstSeen", "lastSeen"):
            require(SECONDS_UTC.fullmatch(str(row.get(field, ""))) is not None,
                    f"candidate {field} needs a second-precision UTC stamp: {key}")
        require(isinstance(row.get("reads"), int) and row["reads"] >= 1, f"candidate reads: {key}")
        promotion = row.get("promotion")
        require(isinstance(promotion, dict) and promotion.get("state") in {"pending", "promoted", "blocked"},
                f"candidate promotion state: {key}")
        require(isinstance(promotion.get("gate"), str) and len(promotion["gate"]) >= 15,
                f"candidate must name the gate it passed or failed: {key}")
        if promotion["state"] == "promoted":
            require(isinstance(promotion.get("rowId"), str) and ID.fullmatch(promotion["rowId"]) is not None,
                    f"promoted candidate must name its ledger row: {key}")


def validate_watch(data: dict) -> None:
    """The server-side game-window watch: lane states plus timestamped signals."""
    require(data.get("version") == 1, "watch version")
    require(isinstance(data.get("policy"), str) and len(data["policy"]) >= 40, "watch policy")
    require(data.get("checkedAt") is None or SECONDS_UTC.fullmatch(str(data["checkedAt"])) is not None,
            "watch checkedAt must be UTC to the second")
    require(isinstance(data.get("liveGames"), list), "watch live games")
    require(isinstance(data.get("signals"), list) and len(data["signals"]) <= 200, "watch signals")
    require(isinstance(data.get("warnings"), list), "watch warnings")
    for name, lane in (data.get("lanes") or {}).items():
        require(isinstance(lane, dict), f"watch lane: {name}")
        require(lane.get("status") in {"ok", "empty", "blocked", "idle", "not_started"}, f"watch lane status: {name}")
        if lane.get("checkedAt") is not None:
            require(SECONDS_UTC.fullmatch(str(lane["checkedAt"])) is not None, f"watch lane stamp: {name}")
    for signal in data["signals"]:
        require(isinstance(signal, dict), "watch signal")
        require(signal.get("tier") in TIERS, "watch signal tier")
        require(isinstance(signal.get("text"), str) and signal["text"], "watch signal text")
        for field in ("detectedAt",):
            require(SECONDS_UTC.fullmatch(str(signal.get(field, ""))) is not None,
                    f"watch signal {field} must be UTC to the second")
        if signal.get("sourceAt"):
            require(SECONDS_UTC.fullmatch(str(signal["sourceAt"])) is not None,
                    "watch signal sourceAt must be UTC to the second when present")

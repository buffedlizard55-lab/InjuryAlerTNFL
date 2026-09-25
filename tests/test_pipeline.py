"""Offline contract tests. Fixtures are synthetic markup, not factual game records."""
from __future__ import annotations

import json
import re
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build import assemble, rss  # noqa: E402
from refresh import (collect_news, collect_scores, discover_links, extract_roundup, game_for,
                     normal_slug, parse_news, parse_scores, valid_player_link)  # noqa: E402
from schema import (InvalidData, official_url, validate_archive, validate_incidents,  # noqa: E402
                    validate_leads, validate_review, validate_sources)
from verify_sources import normalize, verify  # noqa: E402
from wait_for_legacy_pages import legacy_run, wait_for_legacy  # noqa: E402

FIXTURE = ROOT / "tests/fixtures"
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)
URL = "https://www.nfl.com/news/notable-injuries-news-from-sunday-s-week-2-games"


class SourceLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = json.loads((ROOT / "data/archive.json").read_text())
        cls.review = json.loads((ROOT / "data/review.json").read_text())

    def test_all_sixty_entries_are_unique_with_individual_official_evidence(self):
        validate_archive(self.archive)
        self.assertEqual(105, len(self.archive["incidents"]))
        self.assertIn(str(len(self.archive["incidents"])), self.archive["scope"],
                      "scope should describe the row count it ships with")
        self.assertEqual(105, len({row["id"] for row in self.archive["incidents"]}))
        self.assertEqual("2026-09-24", self.archive["verifiedOn"])
        claims = [claim for row in self.archive["incidents"] for claim in row["claims"]]
        self.assertEqual(279, len(claims))
        self.assertEqual(53, len({claim["url"] for claim in claims}))
        self.assertEqual(
            len(claims),
            len({(row["id"], claim["url"], claim["quote"]) for row in self.archive["incidents"] for claim in row["claims"]}),
        )
        for row in self.archive["incidents"]:
            with self.subTest(row=row["id"]):
                self.assertTrue(any(claim["kind"] == "game" for claim in row["claims"]))
                self.assertTrue(all(official_url(claim["url"]) for claim in row["claims"]))
                self.assertTrue(all(claim["quote"] for claim in row["claims"]))
                self.assertNotIn("severe (inferred)", row["injury"].lower())

    def test_all_excerpts_can_be_rechecked_line_by_line_without_guessing(self):
        pages = {}
        for row in self.archive["incidents"]:
            for claim in row["claims"]:
                pages.setdefault(claim["url"], []).append(claim["quote"])
        def reader(url):
            return normalize(" ".join(pages[url]))
        self.assertEqual([], verify(self.archive, reader))
        missing = next(iter(pages))
        del pages[missing]
        def unavailable(url):
            if url == missing:
                raise OSError("source down")
            return reader(url)
        self.assertTrue(any("unavailable" in issue for issue in verify(self.archive, unavailable)))

    def test_every_official_host_the_schema_trusts_is_clickable_in_the_ui(self):
        """The UI keeps its own allowlist; if it drifts, archived links silently stop linking.

        This is the bug that hid the Saints recap that grounds Martin Emerson Jr.: the
        schema accepted neworleanssaints.com before assets/app.js did.
        """
        schema_src = (ROOT / "scripts" / "schema.py").read_text()
        block = schema_src.split("allowed_news_hosts = {", 1)[1].split("}", 1)[0]
        schema_hosts = set(re.findall(r'"([a-z0-9.-]+)"', block))
        app_src = (ROOT / "assets" / "app.js").read_text()
        trusted = app_src.split("function trustedLink", 1)[1].split("];", 1)[0]
        app_hosts = set(re.findall(r"'([a-z0-9.-]+)'", trusted))
        from clubs import CLUBS
        club_hosts = {club["host"] for club in CLUBS.values()}
        self.assertTrue(schema_hosts, "schema allowlist should be parsed, not empty")
        self.assertEqual(set(), schema_hosts - app_hosts, "app.js trustedLink is missing official hosts")
        # The club table the collectors use and the host set the schema trusts are
        # the same 32 newsrooms: a new club may not appear in one and not the other.
        self.assertEqual(club_hosts, schema_hosts - {"www.nfl.com"})

    def test_line_by_line_outcomes_checked_against_sourced_master_list(self):
        expected = {
            "a-j-brown": "out",
            "a-j-terrell": "out",
            "aaron-banks": "out",
            "alec-pierce": "out",
            "andrew-thomas": "did_not_return",
            "anthony-campbell": "did_not_return",
            "arian-smith": "unconfirmed",
            "avonte-maddox": "out",
            "bj-green-ii": "did_not_return",
            "bo-melton": "unconfirmed",
            "brandon-pili": "out",
            "brian-burns": "did_not_return",
            "brian-thomas-jr": "returned",
            "caleb-williams": "unconfirmed",
            "charlie-kolar": "unconfirmed",
            "charvarius-ward": "unconfirmed",
            "chigoziem-okonkwo": "did_not_return",
            "chris-lindstrom": "out",
            "christian-mahogany": "did_not_return",
            "cobie-durant": "did_not_return",
            "cooper-mcdonald": "out",
            "da-shawn-hand": "out",
            "dallas-goedert": "did_not_return",
            "david-njoku": "out",
            "david-onyemata": "out",
            "davis-allen": "unconfirmed",
            "davon-hamilton": "returned",
            "de-zhaun-stribling": "out",
            "dee-winters": "unconfirmed",
            "dell-pettus": "did_not_return",
            "demarcus-robinson": "out",
            "demarvion-overshown": "unconfirmed",
            "derwin-james": "unconfirmed",
            "dj-moore": "out",
            "donovan-jennings": "unconfirmed",
            "dre-mont-jones": "did_not_return",
            "dylan-sampson": "out",
            "ed-oliver": "unconfirmed",
            "eli-raridon": "out",
            "elijah-molden": "did_not_return",
            "frankie-luvu": "did_not_return",
            "george-holani": "unconfirmed",
            "ja-kobi-lane": "unconfirmed",
            "jacob-parrish": "out",
            "jadarian-price": "did_not_return",
            "jaishawn-barham": "unconfirmed",
            "jake-hummel": "out",
            "jake-tonges": "unconfirmed",
            "jalen-coker": "unconfirmed",
            "james-thompson-jr": "unconfirmed",
            "jarvis-brownlee-jr": "returned",
            "jaxson-dart": "out",
            "jayden-daniels": "out",
            "jayden-reed": "out",
            "jaylen-wright": "did_not_return",
            "jonah-coleman": "unconfirmed",
            "jonathon-brooks": "unconfirmed",
            "jordan-love": "unconfirmed",
            "josiah-trotter": "unconfirmed",
            "keandre-lambert-smith": "did_not_return",
            "kelvin-banks-jr": "unconfirmed",
            "kitan-crawford": "unconfirmed",
            "kyle-louis": "out",
            "kyler-murray": "did_not_return",
            "ladd-mcconkey": "did_not_return",
            "mack-wilson-sr": "returned",
            "malik-hooker": "unconfirmed",
            "malik-nabers": "returned",
            "mansoor-delane": "out",
            "marcelino-mccrary-ball": "did_not_return",
            "max-melton": "out",
            "micheal-clemons": "unconfirmed",
            "mike-evans": "did_not_return",
            "mike-onwenu": "out",
            "miles-killebrew": "unconfirmed",
            "minkah-fitzpatrick": "did_not_return",
            "nick-cross": "unconfirmed",
            "nick-scott": "out",
            "omar-cooper-jr": "out",
            "p-j-locke": "did_not_return",
            "rico-dowdle": "returned",
            "robert-beal-jr": "did_not_return",
            "ronnie-rivers": "out",
            "ronnie-stanley": "did_not_return",
            "sam-darnold": "out",
            "samson-ebukam": "out",
            "saquon-barkley": "returned",
            "t-j-tampa": "out",
            "tyler-owens": "did_not_return",
            "tyrion-ingram-dawkins": "did_not_return",
            "tyrique-stevenson": "did_not_return",
            "will-johnson": "unconfirmed",
            "zay-flowers": "out",
        }
        # Pass 5 added a second A.J. Terrell incident (Week 1 shoulder, graded
        # unconfirmed), so the ledger is compared as (player slug, outcome) pairs
        # rather than a slug-keyed dict.
        pairs = {tuple(item) for item in expected.items()} | {("a-j-terrell", "unconfirmed")}
        pairs |= {
            ("zion-johnson", "unconfirmed"), ("cooper-dejean", "unconfirmed"), ("jalen-carter", "unconfirmed"),
            ("tyson-bagent", "unconfirmed"), ("kiko-mauigoa", "did_not_return"), ("mason-taylor", "unconfirmed"),
            ("romello-height", "unconfirmed"),
            ("martin-emerson-jr", "unconfirmed"),
            ("brett-thorson", "unconfirmed"),
            # Pass 7: the Packers' own in-game file resolves the roundup's
            # mismatched display-name link for the carted-off tackle.
            ("zach-bako-bewele", "out"),
            # Pass 7: vikings.com places a Week 1 thumb injury in the game.
            ("jordan-mason", "unconfirmed"),
        }
        self.assertEqual(pairs, {(row["id"].split("-", 4)[-1], row["outcome"]) for row in self.archive["incidents"]})

    def test_session_two_entries_carry_dated_followups_and_observation_labels(self):
        by_id = {row["id"]: row for row in self.archive["incidents"]}
        for entry, min_claims in (("2026-09-17-buf-dj-moore", 3), ("2026-09-21-nyg-brian-burns", 2),
                                  ("2026-09-20-no-kelvin-banks-jr", 3), ("2026-09-13-dal-malik-hooker", 4)):
            self.assertGreaterEqual(len(by_id[entry]["claims"]), min_claims, entry)
        self.assertEqual(["Walked off field", "Locker room"], by_id["2026-09-17-buf-dj-moore"]["observations"])
        self.assertEqual(["Carted to locker room"], by_id["2026-09-10-lar-davis-allen"]["observations"])
        for entry, min_claims in (("2026-09-13-bal-t-j-tampa", 2), ("2026-09-20-gb-aaron-banks", 2),
                                  ("2026-09-20-ne-dell-pettus", 2), ("2026-09-20-sf-james-thompson-jr", 2),
                                  ("2026-09-13-mia-kyle-louis", 2), ("2026-09-21-nyg-andrew-thomas", 2),
                                  ("2026-09-20-nyj-david-onyemata", 2)):
            self.assertGreaterEqual(len(by_id[entry]["claims"]), min_claims, entry)
        self.assertEqual("2026-09-23", by_id["2026-09-21-nyg-andrew-thomas"]["claims"][-1]["date"])

    def test_source_registry_states_what_each_lane_can_and_cannot_prove(self):
        sources = json.loads((ROOT / "data/sources.json").read_text())
        validate_sources(sources)
        by_id = {entry["id"]: entry for entry in sources["sources"]}
        # The boundary lanes a reader would ask about must always be listed with
        # their true status, including the ones that refuse unauthenticated reads.
        self.assertEqual("blocked", by_id["nfl-gamecenter-json"]["verification"]["status"])
        self.assertEqual("official", by_id["nfl-gamecenter-json"]["tier"])
        self.assertFalse(by_id["nfl-gamecenter-json"]["autoPublish"])
        self.assertEqual("link-out-only", by_id["x-twitter"]["verification"]["status"])
        self.assertEqual("blocked", by_id["reddit-json"]["verification"]["status"])
        # No partner or unofficial lane may auto-publish, and every lane records a probe.
        for entry in sources["sources"]:
            with self.subTest(source=entry["id"]):
                if entry["tier"] != "official":
                    self.assertFalse(entry["autoPublish"])
                self.assertTrue(entry["verification"]["method"])
                self.assertIn(entry["verification"]["status"],
                              {"verified", "verified-exists", "verified-endpoint", "blocked", "link-out-only", "pending-reprobe"})
        # Pass 8: the league's weekly injury report was re-probed (it sat as
        # pending-reprobe) and the Yahoo mirror is registered as unofficial.
        self.assertNotIn("pending-reprobe", [entry["verification"]["status"] for entry in sources["sources"]])
        self.assertEqual("verified", by_id["nfl-injury-report"]["verification"]["status"])
        self.assertEqual("unofficial", by_id["yahoo-nfl-injuries"]["tier"])
        self.assertFalse(by_id["yahoo-nfl-injuries"]["autoPublish"])
        # Browser reachability is recorded on every lane and takes only honest
        # values: what the page's own browser is known to reach, what refused a
        # measured read, what is never fetched, and what was not measured.
        allowed_states = {"allowed", "blocked", "not-applicable", "not-tested"}
        for entry in sources["sources"]:
            self.assertIn(entry["browserProbe"]["status"], allowed_states)
        self.assertEqual(
            {"espn-scoreboard", "espn-scoreboard-header", "espn-summary-plays", "espn-plays-core",
             "espn-news", "espn-injuries", "espn-core-events", "espn-summary-injuries"},
            {entry["id"] for entry in sources["sources"] if entry["browserProbe"]["status"] == "allowed"})
        self.assertEqual(
            {"nfl-gamecenter-json", "reddit-json", "bluesky-search"},
            {entry["id"] for entry in sources["sources"] if entry["browserProbe"]["status"] == "blocked"})
        self.assertEqual(
            {"x-twitter", "x-insider-accounts", "instagram-facebook-tiktok",
             "tiktok-search", "reddit-search-live", "youtube-nfl"},
            {entry["id"] for entry in sources["sources"] if entry["browserProbe"]["status"] == "not-applicable"})

    def test_unofficial_leads_never_carry_official_evidence_or_missing_next_steps(self):
        leads = json.loads((ROOT / "data/leads.json").read_text())
        validate_leads(leads)
        published = {(row["player"].lower(), row["team"], row["gameDate"]) for row in self.archive["incidents"]}
        for lead in leads["leads"]:
            with self.subTest(lead=lead["id"]):
                self.assertNotEqual("official", lead["source"]["tier"])
                self.assertGreaterEqual(len(lead["verifyNext"]), 20)
                # An unofficial lead is a candidate, never a quiet duplicate of an
                # archived row. Partner-tier entries are allowed to sit alongside an
                # archived row when they exist to document what the partner feed adds.
                if lead.get("gameDate") and lead["source"]["tier"] == "unofficial" and not lead.get("duplicateOf"):
                    # Same player, same club, same game date would be an archived row
                    # wearing an unofficial label: that is the one thing a lead may not be.
                    self.assertNotIn((lead["subject"].lower(), lead["team"], lead["gameDate"]), published)

    def test_review_flags_and_blocked_people_are_not_in_verified_archive(self):
        validate_review(self.review)
        # 36 after Pass 8: the league's own Week 3 injury report displays
        # Bako-Bewele but links to /players/zach-tom/ — an annotated irregularity
        # on an official page, not a held identity case.
        self.assertEqual(36, len(self.review["flags"]))
        self.assertEqual(2, sum(flag["disposition"] == "held" for flag in self.review["flags"]))
        published = {row["id"] for row in self.archive["incidents"]}
        for flag in self.review["flags"]:
            with self.subTest(flag=flag["id"]):
                if flag["disposition"] == "held":
                    self.assertNotIn(flag["incidentId"], published)
                else:
                    self.assertIn(flag["incidentId"], published)
                self.assertGreaterEqual(len(flag["links"]), 2)

    def test_untrusted_sources_cannot_enter_a_verified_record(self):
        self.assertFalse(official_url("https://www.nfl.com.attacker.test/news/claim"))
        self.assertFalse(official_url("http://www.nfl.com/news/claim"))
        self.assertFalse(official_url("https://www.nfl.com/news/claim?redirect=evil"))
        self.assertFalse(official_url("javascript:alert(1)"))
        tampered = json.loads(json.dumps(self.archive))
        tampered["incidents"][0]["claims"][0]["url"] = "https://example.com/news/claim"
        with self.assertRaises(InvalidData):
            validate_archive(tampered)
        tampered = json.loads(json.dumps(self.archive))
        tampered["incidents"][0]["player"] = "Unrelated Player"
        with self.assertRaises(InvalidData):
            validate_archive(tampered)
        tampered = json.loads(json.dumps(self.archive))
        tampered["incidents"][0]["claims"][0]["quote"] = "Unknown event reported in the game."
        with self.assertRaises(InvalidData):
            validate_archive(tampered)

    def test_league_injury_report_page_can_link_but_never_ground_a_game_row(self):
        # Pass 8 allows nfl.com/injuries/ as an official URL (it is the league's
        # own pregame page, used for review links and followup claims), but its
        # table wording ("Game Status: Out") must never ground an in-game
        # outcome: the outcome grounding regex demands the actual phrase.
        self.assertTrue(official_url("https://www.nfl.com/injuries/"))
        row = json.loads(json.dumps(self.archive["incidents"][0]))
        row["claims"][0]["url"] = "https://www.nfl.com/injuries/"
        row["claims"][0]["quote"] = "Reed, Neck, Did Not Participate In Practice, Out"
        with self.assertRaises(InvalidData):
            validate_incidents([row])

    def test_duplicate_and_future_rows_are_rejected(self):
        tampered = json.loads(json.dumps(self.archive))
        tampered["incidents"].append(tampered["incidents"][0])
        with self.assertRaises(InvalidData):
            validate_archive(tampered)
        tampered = json.loads(json.dumps(self.archive))
        row = tampered["incidents"][0]
        row["claims"].append(dict(row["claims"][0]))
        with self.assertRaises(InvalidData):
            validate_archive(tampered)
        tampered = json.loads(json.dumps(self.archive))
        tampered["verifiedOn"] = "2026-09-01"
        with self.assertRaises(InvalidData):
            validate_archive(tampered)


class PagesPublisherTests(unittest.TestCase):
    def test_wait_targets_only_legacy_build_for_this_commit(self):
        wanted = {"name": "pages build and deployment", "event": "dynamic", "head_sha": "abc",
                  "status": "completed", "conclusion": "success"}
        payload = {"workflow_runs": [dict(wanted, head_sha="old"),
                                     dict(wanted, name="Publish source-checked injury board"), wanted]}
        self.assertIs(wanted, legacy_run(payload, "abc"))
        self.assertIsNone(legacy_run(payload, "other"))
        with patch.dict(os.environ, {"GH_TOKEN": "test"}), \
                patch("wait_for_legacy_pages.api_json", side_effect=[{"build_type": "legacy"}, payload]) as api, \
                patch("wait_for_legacy_pages.time.sleep") as sleep:
            wait_for_legacy("abc", "test/repo", timeout=2)
            self.assertEqual(2, api.call_count)
            sleep.assert_called_once_with(12)

    def test_actions_only_pages_does_not_wait_for_missing_legacy_build(self):
        with patch.dict(os.environ, {"GH_TOKEN": "test"}), \
                patch("wait_for_legacy_pages.api_json", return_value={"build_type": "workflow"}) as api, \
                patch("wait_for_legacy_pages.time.sleep") as sleep:
            wait_for_legacy("abc", "test/repo", timeout=2)
            api.assert_called_once_with("repos/test/repo/pages")
            sleep.assert_not_called()


class FeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = parse_news((FIXTURE / "roundup.html").read_bytes())
        cls.games = parse_scores((FIXTURE / "scoreboard.json").read_bytes())

    def test_discovery_only_follows_allowlisted_official_links(self):
        index = parse_news((FIXTURE / "index.html").read_bytes())
        self.assertEqual([URL], discover_links([index]))
        self.assertEqual(datetime(2026, 9, 20, 18, tzinfo=timezone.utc), self.page.published)

    def test_parse_espn_scores_for_context_only(self):
        self.assertEqual(6, len(self.games))
        self.assertEqual("Philadelphia Eagles", self.games[0]["homeName"])
        self.assertEqual("final", self.games[0]["phase"])
        self.assertEqual("TEN", self.games[0]["away"])
        self.assertEqual("https://www.espn.com/nfl/game/_/gameId/4011", self.games[0]["url"])
        self.assertEqual([], parse_scores(b'{"events": []}'))
        with self.assertRaises(ValueError):
            parse_scores(b'{"notEvents": []}')

    def test_player_link_mismatch_and_nearby_games_fail_closed(self):
        self.assertEqual("a-j-brown", normal_slug("A.J. Brown"))
        self.assertTrue(valid_player_link("A.J. Brown", "/players/a-j-brown/"))
        self.assertFalse(valid_player_link("Zach Bako-Bewele", "/players/zach-tom/"))
        self.assertIsNone(game_for("PHI", NOW + __import__('datetime').timedelta(days=10), self.games, NOW))

    def test_explicit_single_player_status_is_required(self):
        accepted, flags = extract_roundup(self.page, URL, self.page.published, self.games, NOW, set())
        got = {row["player"]: row for row in accepted}
        self.assertEqual({"Dallas Goedert", "Mike Onwenu", "Jadarian Price"}, set(got))
        self.assertEqual("did_not_return", got["Dallas Goedert"]["outcome"])
        self.assertEqual("Knee", got["Dallas Goedert"]["injury"])
        self.assertEqual("out", got["Mike Onwenu"]["outcome"])
        self.assertEqual("Ankle", got["Mike Onwenu"]["injury"])
        # Shared 'A and B did not return' isn't attributable to one player.
        self.assertNotIn("Jaylen Wright", got)
        self.assertNotIn("Robert Beal Jr.", got)
        # 'Ruled out for Sunday's game' could be a pre-game inactive.
        self.assertNotIn("Ted Danger", got)
        self.assertIn("Zach Bako-Bewele", [item["subject"] for item in flags])
        validate_incidents(accepted, automatic=True)

    def test_held_issue_does_not_auto_publish(self):
        review = json.loads((ROOT / "data/review.json").read_text())
        held = {flag["incidentId"] for flag in review["flags"] if flag["disposition"] == "held"}
        # Pass 5 promoted Kiko Mauigoa (the Jets' own recap grounds the exit and the
        # club links the name to its roster page); Pass 7 promoted Zach Bako-Bewele
        # because the Packers' own in-game file names him independently of the
        # league roundup's mismatched player link. What stays held: Kam Curl's
        # name/URL mismatch and the withdrawn Puka Nacua row.
        self.assertIn("2026-09-10-lar-kam-curl", held)
        self.assertIn("2026-09-21-lar-puka-nacua", held)
        self.assertNotIn("2026-09-20-gb-zach-bako-bewele", held)
        archive = json.loads((ROOT / "data/archive.json").read_text())
        self.assertIn("Zach Bako-Bewele", [row["player"] for row in archive["incidents"]],
                      "the resolved identity case should now stand as a row")
        self.assertNotIn("2026-09-20-nyj-kiko-mauigoa", held)
        annotated = {flag["incidentId"] for flag in review["flags"] if flag["disposition"] == "annotated"}
        self.assertIn("2026-09-20-nyj-kiko-mauigoa", annotated)
        self.assertNotIn("2026-09-20-sea-jadarian-price", held)
        # The synthetic fixture contains Jadarian Price as a valid single-player
        # bullet, so without the held set it would be accepted; with the held set
        # from the previous session it was blocked. Now that it is annotated and
        # published, the collector must still respect the remaining held set.
        accepted, _ = extract_roundup(self.page, URL, self.page.published, self.games, NOW, held)
        # The fixture's Jadarian Price should now be accepted because it is no
        # longer in the held set (promoted to annotated with both sources).
        self.assertIn("Jadarian Price", [row["player"] for row in accepted])
        # The collector still refuses the roundup bullet automatically: its display
        # name resolves to /players/zach-tom/, and that mismatch is exactly what the
        # archived row had to be grounded *around* using the club's own page.
        self.assertNotIn("Zach Bako-Bewele", [row["player"] for row in accepted])

    def test_network_outage_is_explicit_and_does_not_publish_injuries(self):
        def offline(*_args, **_kwargs):
            raise OSError("offline")
        scores = collect_scores(NOW, offline)
        news = collect_news(NOW, [], set(), offline)
        self.assertEqual("unavailable", scores["status"])
        self.assertEqual("unavailable", news["status"])
        self.assertEqual([], scores["games"])
        self.assertEqual([], news["incidents"])

    def test_build_refuses_a_held_case_even_if_collector_regresses(self):
        # Two cases remain held after Pass 7: Kam Curl's name/URL mismatch and the
        # withdrawn Puka Nacua row. The synthetic fixture does not contain Kam Curl,
        # but the build must still refuse any held ID, even if a collector regresses
        # and emits it.
        review = json.loads((ROOT / "data/review.json").read_text())
        held_ids = {flag["incidentId"] for flag in review["flags"] if flag["disposition"] == "held"}
        self.assertIn("2026-09-10-lar-kam-curl", held_ids)
        # Construct a minimal valid incident that uses a held ID to ensure
        # the publisher fails closed.
        held_row = {
            "id": "2026-09-10-lar-kam-curl",
            "player": "Kam Curl",
            "position": "S",
            "team": "LAR",
            "opponent": "SF",
            "gameDate": "2026-09-10",
            "gameStart": "2026-09-10T20:00:00Z",
            "injury": "Ankle",
            "outcome": "unconfirmed",
            "observations": ["Left game"],
            "automatic": True,
            "capturedAt": "2026-09-10T21:00:00Z",
            "claims": [{"date": "2026-09-10", "kind": "game", "text": "Suffered ankle injury in Thursday's game per report.", "quote": "suffered an ankle injury in Thursday's game", "url": "https://www.nfl.com/news/nfl-news-roundup-latest-league-updates-from-thursday-sept-10"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            live = json.loads((ROOT / "data/live.json").read_text())
            live["incidents"] = [held_row]
            live_path = Path(tmp) / "live.json"
            live_path.write_text(json.dumps(live))
            with self.assertRaises(InvalidData):
                assemble(Path(tmp) / "site", live_path, ROOT / "data/scoreboard.json")

    def test_build_keeps_offline_fallback_and_never_rss_alerts_from_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "public"
            assemble(dest, ROOT / "data/live.json", ROOT / "data/scoreboard.json")
            self.assertTrue((dest / "index.html").is_file())
            self.assertTrue((dest / "assets/domain.mjs").is_file())
            self.assertEqual([], json.loads((dest / "data/live.json").read_text())["incidents"])
            self.assertNotIn("<item>", (dest / "feed.xml").read_text())
            self.assertEqual(105, len(json.loads((dest / "data/archive.json").read_text())["incidents"]))
            # Provenance must ship with the page: the source registry and the
            # unofficial lead list are reader-facing, so a build that omits them
            # would leave the site claiming more than it can show.
            sources = json.loads((dest / "data/sources.json").read_text())
            leads = json.loads((dest / "data/leads.json").read_text())
            self.assertGreaterEqual(len(sources["sources"]), 40)
            self.assertTrue(all(entry["tier"] in {"official", "partner", "unofficial"} for entry in sources["sources"]))
            self.assertTrue(all(lead["source"]["tier"] != "official" for lead in leads["leads"]))


if __name__ == "__main__":
    unittest.main()


class UnblockDeploymentPolicy(unittest.TestCase):
    """The stale-deployment closer must only touch old, unsettled deployments."""

    def test_only_stale_states_and_old_enough(self):
        from unblock_deployments import STALE_STATES, should_close
        for state in ("waiting", "in_progress", "queued", "pending"):
            self.assertTrue(should_close(state, 3600))
            self.assertFalse(should_close(state, 60))  # too young: maybe live
        for state in ("success", "failure", "error", "inactive", "unknown"):
            self.assertFalse(should_close(state, 86400))


if __name__ == "__main__":
    unittest.main()

"""Offline contract tests. Fixtures are synthetic markup, not factual game records."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build import assemble, rss  # noqa: E402
from refresh import (collect_news, collect_scores, discover_links, extract_roundup, game_for,
                     normal_slug, parse_news, parse_scores, valid_player_link)  # noqa: E402
from schema import InvalidData, official_url, validate_archive, validate_incidents, validate_review  # noqa: E402
from verify_sources import normalize, verify  # noqa: E402

FIXTURE = ROOT / "tests/fixtures"
NOW = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)
URL = "https://www.nfl.com/news/notable-injuries-news-from-sunday-s-week-2-games"


class SourceLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = json.loads((ROOT / "data/archive.json").read_text())
        cls.review = json.loads((ROOT / "data/review.json").read_text())

    def test_all_twenty_new_entries_are_unique_with_individual_official_evidence(self):
        validate_archive(self.archive)
        self.assertEqual(20, len(self.archive["incidents"]))
        self.assertEqual(20, len({row["id"] for row in self.archive["incidents"]}))
        self.assertEqual("2026-09-23", self.archive["verifiedOn"])
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

    def test_line_by_line_outcomes_checked_against_sourced_master_list(self):
        expected = {
            "sam-darnold": "out", "a-j-brown": "out", "de-zhaun-stribling": "out",
            "kyler-murray": "did_not_return", "zay-flowers": "out", "ja-kobi-lane": "unconfirmed",
            "caleb-williams": "unconfirmed", "jayden-daniels": "out", "alec-pierce": "out",
            "jaxson-dart": "out", "saquon-barkley": "returned", "rico-dowdle": "returned",
            "ronnie-stanley": "did_not_return", "jaylen-wright": "did_not_return",
            "dallas-goedert": "did_not_return", "demarcus-robinson": "out",
            "p-j-locke": "did_not_return", "mike-onwenu": "out",
            "a-j-terrell": "out", "robert-beal-jr": "did_not_return",
        }
        self.assertEqual(expected, {row["id"].split("-", 4)[-1]: row["outcome"] for row in self.archive["incidents"]})

    def test_review_flags_and_blocked_people_are_not_in_verified_archive(self):
        validate_review(self.review)
        self.assertEqual(8, len(self.review["flags"]))
        self.assertEqual(6, sum(flag["disposition"] == "held" for flag in self.review["flags"]))
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

    def test_duplicate_and_future_rows_are_rejected(self):
        tampered = json.loads(json.dumps(self.archive))
        tampered["incidents"].append(tampered["incidents"][0])
        with self.assertRaises(InvalidData):
            validate_archive(tampered)
        tampered = json.loads(json.dumps(self.archive))
        tampered["verifiedOn"] = "2026-09-01"
        with self.assertRaises(InvalidData):
            validate_archive(tampered)


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
        self.assertIn("2026-09-20-sea-jadarian-price", held)
        accepted, _ = extract_roundup(self.page, URL, self.page.published, self.games, NOW, held)
        self.assertNotIn("Jadarian Price", [row["player"] for row in accepted])

    def test_network_outage_is_explicit_and_does_not_publish_injuries(self):
        def offline(*_args, **_kwargs):
            raise OSError("offline")
        scores = collect_scores(NOW, offline)
        news = collect_news(NOW, [], set(), offline)
        self.assertEqual("unavailable", scores["status"])
        self.assertEqual("unavailable", news["status"])
        self.assertEqual([], scores["games"])
        self.assertEqual([], news["incidents"])

    def test_build_keeps_offline_fallback_and_never_rss_alerts_from_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "public"
            assemble(dest, ROOT / "data/live.json", ROOT / "data/scoreboard.json")
            self.assertTrue((dest / "index.html").is_file())
            self.assertTrue((dest / "assets/domain.mjs").is_file())
            self.assertEqual([], json.loads((dest / "data/live.json").read_text())["incidents"])
            self.assertNotIn("<item>", (dest / "feed.xml").read_text())
            self.assertEqual(20, len(json.loads((dest / "data/archive.json").read_text())["incidents"]))


if __name__ == "__main__":
    unittest.main()

"""Offline tests for the alerting layer: log contract, watcher, club scanner, build.

Everything here runs without a network. The collectors take an injected getter,
which is exactly how these tests drive them: the point is the *contract* (what is
written, what is deduplicated, what fails closed), not today's provider data.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import alertlog  # noqa: E402
import clubscan  # noqa: E402
import watch_live  # noqa: E402
from clubs import ARTICLE_PATTERNS, CLUBS  # noqa: E402
from schema import (validate_alert_log, validate_archive, validate_candidates,  # noqa: E402
                    validate_sources, validate_watch)
from signals import candidate_sentences  # noqa: E402

NOW = datetime(2026, 9, 24, 20, 30, 5, tzinfo=timezone.utc)
HEADER_PAYLOAD = {
    "sports": [{"leagues": [{"events": [{
        "id": "401872948", "date": "2026-09-25T00:15Z",
        "competitors": [
            {"homeAway": "home", "abbreviation": "GB", "score": "17"},
            {"homeAway": "away", "abbreviation": "ATL", "score": "20"},
        ],
        "fullStatus": {"type": {"state": "in", "shortDetail": "4Q 2:00"}, "displayClock": "2:00"},
    }]}]}]
}
SUMMARY_PAYLOAD = {"injuries": [{"team": {"abbreviation": "ATL"}, "injuries": [{
    "athlete": {"displayName": "A.J. Terrell"}, "status": "Did not return", "detail": "Ankle",
    "date": "2026-09-25T01:02:03Z",
}]}]}
PLAYS_PAYLOAD = {"items": [{
    "text": "Terrell carted off the field after the tackle.",
    "clock": {"displayValue": "2:00"}, "period": {"number": 4}, "wallclock": "2026-09-25T01:02:05Z",
}]}


class AlertLogTests(unittest.TestCase):
    def test_the_same_event_keeps_one_id_however_often_it_is_polled(self):
        first = alertlog.make(kind="live-signal", tier="partner", lane="summary", subject="A.J. Terrell",
                              text="Terrell — Out. Ankle", url="https://www.espn.com/nfl/game/_/gameId/1",
                              detected_at="2026-09-25T01:02:10Z", source_at="2026-09-25T01:02:03Z")
        later = alertlog.make(kind="live-signal", tier="partner", lane="summary", subject="A.J. Terrell",
                              text="Terrell — Out. Ankle", url="https://www.espn.com/nfl/game/_/gameId/1",
                              detected_at="2026-09-25T01:02:30Z", source_at="2026-09-25T01:02:03Z")
        self.assertEqual(first["id"], later["id"])
        self.assertEqual(first["detectedAt"], "2026-09-25T01:02:10Z")
        # A log written once and re-fed is idempotent; the first detection time wins.
        merged, added = alertlog.merge({"version": 1, "entries": [first]}, [later])
        self.assertEqual(0, added)
        self.assertEqual(1, len(merged["entries"]))
        self.assertEqual("2026-09-25T01:02:10Z", merged["entries"][0]["detectedAt"])

    def test_heartbeats_can_repeat_while_events_cannot(self):
        one = alertlog.make(kind="lane-failure", tier="partner", lane="plays", subject="plays lane blocked",
                            text="no response", url="https://site.web.api.espn.com/apis/v2/scoreboard/header",
                            detected_at="2026-09-25T01:00:00Z", source_at="2026-09-25T01:00:00Z",
                            id_key="heartbeat|plays|2026-09-25T01:00:00Z")
        two = alertlog.make(kind="lane-failure", tier="partner", lane="plays", subject="plays lane blocked",
                            text="no response", url="https://site.web.api.espn.com/apis/v2/scoreboard/header",
                            detected_at="2026-09-25T01:10:00Z", source_at="2026-09-25T01:10:00Z",
                            id_key="heartbeat|plays|2026-09-25T01:10:00Z")
        self.assertNotEqual(one["id"], two["id"])

    def test_latency_is_only_stored_when_a_provider_timestamp_exists(self):
        with_source = alertlog.make(kind="live-signal", tier="partner", lane="plays", subject="x",
                                    text="text", url="https://www.espn.com/nfl/game/_/gameId/1",
                                    detected_at="2026-09-25T01:00:30Z", source_at="2026-09-25T01:00:00Z")
        without = alertlog.make(kind="live-signal", tier="partner", lane="plays", subject="x",
                                text="text", url="https://www.espn.com/nfl/game/_/gameId/1",
                                detected_at="2026-09-25T01:00:30Z")
        self.assertEqual(30, with_source["latencySeconds"])
        self.assertIsNone(without["latencySeconds"])

    def test_the_log_it_writes_satisfies_its_own_contract(self):
        entries = [
            alertlog.make(kind="roundup-match", tier="official", lane="NFL.com in-game roundup",
                          subject="Alec Pierce (IND)", text="Ruled out. (NFL.com in-game roundup.)",
                          url="https://www.nfl.com/news/notable-injuries-news-from-sunday-s-week-2-games",
                          detected_at="2026-09-24T20:30:05Z", quote="Alec Pierce was ruled out.",
                          status="out", player="Alec Pierce", team="IND", opponent="KC",
                          game_date="2026-09-20"),
            alertlog.make(kind="lane-failure", tier="official", lane="NFL.com news index",
                          subject="news index degraded", text="index unavailable",
                          url="https://www.nfl.com/news/series/nfl-news-roundup",
                          detected_at="2026-09-24T20:30:05Z"),
        ]
        data, added = alertlog.merge({"version": 1, "entries": []}, entries)
        self.assertEqual(2, added)
        validate_alert_log(data)
        self.assertEqual({entry["id"] for entry in entries}, {entry["id"] for entry in data["entries"]})

    def test_cap_and_ordering(self):
        entries = [alertlog.make(kind="lane-status", tier="partner", lane="espn", subject=f"game {index}",
                                 text="state", url=f"https://www.espn.com/nfl/game/_/gameId/{index}",
                                 detected_at=f"2026-09-25T01:00:{index:02d}Z", id_key=str(index))
                   for index in range(5)]
        merged, _ = alertlog.merge({"version": 1, "entries": []}, entries, cap=3)
        self.assertEqual(3, len(merged["entries"]))
        self.assertEqual("2026-09-25T01:00:04Z", merged["entries"][0]["detectedAt"])


class WatchLiveTests(unittest.TestCase):
    def cycle(self, now, watch=None, previous=None):
        def get(url):
            if "scoreboard/header" in url:
                return HEADER_PAYLOAD
            if "summary" in url:
                return SUMMARY_PAYLOAD
            return PLAYS_PAYLOAD
        return watch_live.cycle(get=get, now=now, watch=watch, previous=previous or {})

    def test_a_poll_writes_tiered_second_precision_signals_and_logs_them(self):
        result = self.cycle(NOW)
        watch = result["watch"]
        validate_watch(watch)
        self.assertEqual("live", watch["status"])
        self.assertEqual("ok", watch["lanes"]["header"]["status"])
        self.assertTrue(watch["signals"])
        for signal in watch["signals"]:
            self.assertEqual("partner", signal["tier"])  # never labelled official
            self.assertRegex(signal["detectedAt"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        kinds = {entry["kind"] for entry in result["logEntries"]}
        self.assertIn("live-signal", kinds)
        validate_alert_log(alertlog.merge({"version": 1, "entries": []}, result["logEntries"])[0])

    def test_polling_the_same_game_twice_does_not_duplicate_the_log(self):
        first = self.cycle(NOW)
        watch, previous = first["watch"], {}
        previous["game_state"] = watch.get("game_state") or {}
        second = self.cycle(datetime(2026, 9, 24, 20, 30, 25, tzinfo=timezone.utc), watch=watch, previous=previous)
        # The cycle re-offers the same lines (it has no memory of the file); the
        # append-only merge is what collapses them, so a 20-second loop stays flat.
        log, added_first = alertlog.merge({"version": 1, "entries": []}, first["logEntries"])
        self.assertEqual(len(first["logEntries"]), added_first)
        log, added_second = alertlog.merge(log, second["logEntries"])
        self.assertEqual(0, added_second)
        self.assertEqual([], second["newSignals"])
        # The same wording in the same lane keeps the same id: that is what makes
        # the 20-second poll loop safe to run for hours.
        self.assertEqual({signal["id"] for signal in first["watch"]["signals"]},
                         {signal["id"] for signal in second["watch"]["signals"]})

    def test_a_blocked_lane_is_logged_instead_of_going_quiet(self):
        def failing(url):
            raise OSError("connection refused")
        result = watch_live.cycle(get=failing, now=NOW, previous={})
        self.assertEqual("blocked", result["watch"]["lanes"]["header"]["status"])
        self.assertEqual("unavailable", result["watch"]["status"])
        self.assertTrue(any(entry["kind"] == "lane-failure" for entry in result["logEntries"]))
        self.assertTrue(any("header lane unavailable" in warning for warning in result["watch"]["warnings"]))


class ClubScanTests(unittest.TestCase):
    HOST = CLUBS["CAR"]["host"]
    SLUG = f"/news/panthers-{ARTICLE_PATTERNS[0]}-week-2-2026"
    ARTICLE = ("<html><head><title>Panthers recap</title>"
               "<meta property=\"article:published_time\" content=\"2026-09-20T21:00:00Z\"></head>"
               "<body><p>Carolina Panthers safety Nick Scott was ruled out of Sunday's win over the "
               "Falcons with an abdomen injury.</p></body></html>")

    def getters(self):
        def get(url, kind="html"):
            if url.rstrip("/").endswith("/news"):
                return (f'<html><body><a href="{self.SLUG}">Recap</a></body></html>').encode()
            return self.ARTICLE.encode()
        def get_json(url):
            return {"events": []}  # no schedule this pass: promotion must fail closed
        return get, get_json

    def scan(self, state, candidates):
        get, get_json = self.getters()
        return clubscan.scan(get=get, get_json=get_json, now=NOW, clubs=["CAR"], per_club=2,
                             state=state, candidates=candidates, promote=True,
                             archive={"incidents": []})

    def test_a_club_sentence_is_kept_as_a_candidate_with_its_quote(self):
        state = {"clubs": {}}
        result = self.scan(state, {"candidates": []})
        rows = result["candidates"]["candidates"]
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("CAR", row["club"])
        self.assertEqual(1, row["reads"])
        self.assertIn("Nick Scott", row["quote"])
        self.assertEqual("pending", row["promotion"]["state"])
        validate_candidates(result["candidates"])
        self.assertTrue(any(entry["kind"] == "club-candidate" for entry in result["logEntries"]))
        self.assertEqual(0, result["promoted"])

    def test_two_reads_are_required_before_anything_can_be_promoted(self):
        state = {"clubs": {}}
        first = self.scan(state, {"candidates": []})
        second = self.scan(first["state"], first["candidates"])
        row = second["candidates"]["candidates"][0]
        self.assertEqual(2, row["reads"])
        # The schedule lane failed this pass, so the gate still refuses the row.
        self.assertEqual("pending", row["promotion"]["state"])
        self.assertIn("game", row["promotion"]["gate"])
        self.assertEqual(0, second["promoted"])

    def test_the_promotion_gate_rejects_a_sentence_that_does_not_name_its_club(self):
        candidate = {
            "club": "CAR", "url": f"https://{self.HOST}{self.SLUG}", "reads": 2,
            "quote": "The backup safety was ruled out of Sunday's win over the Falcons with an abdomen injury.",
            "player": "Nick Scott", "signal": {"status": "out", "observation": "", "phrase": "ruled out"},
            "published": "2026-09-20T21:00:00Z",
        }
        schedule = {"2026-09-20": {"CAR": "ATL", "ATL": "CAR"}}
        row, reason = clubscan.promotion_gate(candidate, archive_names=set(), schedule=schedule)
        self.assertIsNone(row)
        self.assertIn("club", reason)
        named = dict(candidate, quote="Carolina Panthers safety Nick Scott was ruled out of Sunday's win "
                                      "over the Falcons with an abdomen injury.")
        row, reason = clubscan.promotion_gate(named, archive_names=set(), schedule=schedule)
        self.assertEqual("", reason)
        self.assertEqual("CAR", row["team"])
        self.assertEqual("ATL", row["opponent"])
        self.assertEqual("out", row["outcome"])


class VocabularySyncTests(unittest.TestCase):
    def test_the_generated_browser_vocabulary_matches_its_source(self):
        """data/vocabulary.json is the only source; assets/vocabulary.mjs is derived.

        A drifted file would let the page and the collectors disagree about what a
        phrase means, which is the one thing the shared vocabulary exists to stop.
        """
        import gen_vocabulary
        vocabulary = json.loads((ROOT / "data/vocabulary.json").read_text(encoding="utf-8"))
        rendered = gen_vocabulary.render(vocabulary)
        shipped = (ROOT / "assets/vocabulary.mjs").read_text(encoding="utf-8")
        self.assertEqual(rendered, shipped, "run python scripts/gen_vocabulary.py --write")
        self.assertIn("export const IN_GAME_RULES", shipped)
        self.assertIn("export const CONTEXTS", shipped)

    def test_the_generator_exits_non_zero_on_drift(self):
        drifted = ROOT / "assets/vocabulary.mjs"
        original = drifted.read_text(encoding="utf-8")
        try:
            drifted.write_text(original + "\n// drift\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/gen_vocabulary.py")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(1, result.returncode)
        finally:
            drifted.write_text(original, encoding="utf-8")


class BuildContractTests(unittest.TestCase):
    def test_the_site_ships_every_artefact_a_reader_can_see(self):
        from build import assemble
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "site"
            assemble(dest, ROOT / "data/live.json", ROOT / "data/scoreboard.json")
            for name in ("archive.json", "review.json", "sources.json", "leads.json",
                         "alert-log.json", "candidates.json", "watch.json", "vocabulary.json"):
                self.assertTrue((dest / "data" / name).is_file(), name)
            self.assertTrue((dest / "assets/vocabulary.mjs").is_file())
            sources = json.loads((dest / "data/sources.json").read_text())
            validate_sources(sources)
            # The registry a reader sees must be organised, not a flat dump.
            self.assertTrue(all(lane["category"] and lane["latencyClass"] and lane["timestampPrecision"]
                                and lane["access"] for lane in sources["sources"]))
            self.assertGreaterEqual(len(sources["sources"]), 60)
            for lane in sources["sources"]:
                if lane["tier"] != "official":
                    self.assertFalse(lane["autoPublish"], lane["id"])

    def test_the_feed_carries_logged_alerts_with_their_tiers(self):
        from build import rss
        live = json.loads((ROOT / "data/live.json").read_text(encoding="utf-8"))
        log = {"entries": [{
            "id": "log-club-promotion-x-0000000000", "at": "2026-09-24T20:30:05Z",
            "detectedAt": "2026-09-24T20:30:05Z", "kind": "club-promotion", "tier": "official",
            "lane": "club-scan", "subject": "Nick Scott — CAR", "text": "out in CAR vs ATL (2026-09-20)",
            "evidence": "https://www.panthers.com/news/panthers-recap-week-2-2026",
        }]}
        feed = rss(live, log)
        self.assertIn("[OFFICIAL] Nick Scott", feed)
        self.assertIn("2026-09-24T20:30:05Z", feed)
        # An archive-only item is never turned into a feed entry on its own.
        self.assertEqual(1, feed.count("<item>"))

    def test_a_held_flag_still_stops_the_build(self):
        from build import assemble
        from schema import InvalidData
        live = json.loads((ROOT / "data/live.json").read_text(encoding="utf-8"))
        # The published fallback is empty; a synthetic incident proves the guard.
        live["incidents"] = [{
            "id": "2026-09-10-lar-kam-curl", "player": "Kam Curl", "position": "S", "team": "LAR",
            "opponent": "SF", "gameDate": "2026-09-10", "gameStart": "2026-09-11T00:15:00Z",
            "injury": "Ankle", "outcome": "out", "observations": ["Left game"], "automatic": True,
            "capturedAt": "2026-09-24T20:30:05Z",
            "claims": [{"date": "2026-09-11", "kind": "game", "text": "Ruled out of that game.",
                        "quote": "Kam Curl was ruled out.", "url": "https://www.nfl.com/news/nfl-news-roundup-latest-league-updates-from-thursday-sept-10"}],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            live_path = Path(tmp) / "live.json"
            live_path.write_text(json.dumps(live), encoding="utf-8")
            with self.assertRaises(InvalidData):
                assemble(Path(tmp) / "site", live_path, ROOT / "data/scoreboard.json")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.cli import main
from sports_briefing.demo import load_demo_scheffler_candidates, load_demo_texans_candidates
from sports_briefing.football_data import normalize_matches
from sports_briefing.news.evidence import normalize_batch
from sports_briefing.news.storage import persist_reviewed_batch
from sports_briefing.nfl.sportradar import normalize_injuries, normalize_schedule
from sports_briefing.nfl.storage import initialize_nfl_database, persist_texans_fetch
from sports_briefing.source_policy import PUBLIC_MODE_ENV, public_mode_from_env
from sports_briefing.storage import initialize_database, persist_successful_fetch
from sports_briefing.timeline import TimelineCandidate, TimelineTier, build_home_timeline, rank_candidates


FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-09-23T12:00:00Z"


def provider_candidate(entity_id: str, provider: str) -> TimelineCandidate:
    return TimelineCandidate(
        stable_id=f"{entity_id}:provider-item", entity_id=entity_id, entity_name=entity_id,
        sport="test", item_type="match", event_state="PRE_GAME", tier=TimelineTier.IMMINENT,
        title="Provider item", summary="Provider item", event_time="2026-09-23T15:00:00Z",
        change_time=None, competition=None, source_provider=provider, source_attribution=provider,
        source_generated_at=AS_OF, source_observed_at=AS_OF, source_record_id="provider-item",
    )


class PublicModeConfigTests(unittest.TestCase):
    def test_public_mode_is_explicit_and_rejects_ambiguous_values(self) -> None:
        self.assertFalse(public_mode_from_env({}))
        self.assertFalse(public_mode_from_env({PUBLIC_MODE_ENV: "false"}))
        self.assertTrue(public_mode_from_env({PUBLIC_MODE_ENV: "true"}))
        for value in ("1", "True", "yes", "on"):
            with self.assertRaises(ValueError):
                public_mode_from_env({PUBLIC_MODE_ENV: value})

    def test_invalid_server_setting_fails_app_creation(self) -> None:
        with patch.dict(os.environ, {PUBLIC_MODE_ENV: "yes"}):
            with self.assertRaises(ValueError):
                create_app(Path("unused.sqlite3"))


class PublicTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "sports.sqlite3"

    def seed_arsenal(self) -> None:
        payload = json.loads((FIXTURES / "arsenal_matches.json").read_text(encoding="utf-8"))
        fixtures, ignored = normalize_matches(payload)
        initialize_database(self.database)
        persist_successful_fetch(
            self.database, request_url="https://api.football-data.org/v4/teams/57/matches",
            date_from="2026-09-01", date_to="2026-10-01", started_at="2026-09-23T11:59:00Z",
            completed_at=AS_OF, http_status=200, raw_response=json.dumps(payload),
            received_count=len(payload["matches"]), fixtures=fixtures, filtered_unsupported_count=ignored,
        )

    def seed_texans(self) -> None:
        schedule_payload = json.loads((FIXTURES / "texans_schedule.json").read_text(encoding="utf-8"))
        injury_payload = json.loads((FIXTURES / "texans_injuries_limited.json").read_text(encoding="utf-8"))
        injury_payload["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-23T00:00:00Z"
        initialize_nfl_database(self.database)
        persist_texans_fetch(
            self.database, schedule=normalize_schedule(schedule_payload),
            injuries=normalize_injuries(injury_payload), schedule_url="https://example.test/schedule",
            injuries_url="https://example.test/injuries", schedule_generated_at="2026-09-23T11:30:00Z",
            injuries_generated_at="2026-09-23T11:30:00Z", schedule_raw=json.dumps(schedule_payload),
            injuries_raw=json.dumps(injury_payload), started_at="2026-09-23T11:44:00Z",
            completed_at="2026-09-23T11:45:00Z",
        )

    def import_synthetic_news(self) -> None:
        value = json.loads((FIXTURES / "news" / "synthetic-placement.json").read_text(encoding="utf-8"))
        persist_reviewed_batch(self.database, normalize_batch(value), observed_at="2026-09-25T11:00:00Z")

    def test_public_mode_excludes_persisted_football_data_and_sportradar_items(self) -> None:
        self.seed_arsenal()
        self.seed_texans()
        dev = build_home_timeline(self.database, as_of=AS_OF)
        self.assertEqual({item["source"]["provider"] for item in dev["items"]}, {"football-data.org", "sportradar"})

        public = build_home_timeline(self.database, as_of=AS_OF, public_mode=True)

        self.assertTrue(public["items"])
        self.assertEqual({item["source"]["provider"] for item in public["items"]}, {"synthetic-demo"})
        self.assertTrue(all(item["data_mode"] == "demo" for item in public["items"]))
        self.assertEqual(public["unavailable_entities"], ["arsenal"])

    def test_public_mode_never_calls_restricted_provider_loaders(self) -> None:
        loaders = {
            "sports_briefing.arsenal_timeline.load_arsenal_timeline_candidates": provider_candidate("arsenal", "football-data.org"),
            "sports_briefing.nfl.timeline.load_texans_timeline_candidates": provider_candidate("texans", "sportradar"),
            "sports_briefing.golf.timeline.load_golf_timeline_candidates": provider_candidate("scheffler", "sportradar"),
        }
        patches = {target: patch(target, return_value=[item]) for target, item in loaders.items()}
        mocks = {target: patcher.start() for target, patcher in patches.items()}
        for patcher in patches.values():
            self.addCleanup(patcher.stop)

        dev_ids = {item["id"] for item in build_home_timeline(self.database, as_of=AS_OF)["items"]}
        self.assertEqual(dev_ids, {item.stable_id for item in loaders.values()})
        for mock in mocks.values():
            mock.reset_mock()

        public = build_home_timeline(self.database, as_of=AS_OF, public_mode=True)

        for mock in mocks.values():
            mock.assert_not_called()
        self.assertFalse({item["id"] for item in public["items"]} & dev_ids)
        self.assertNotIn("arsenal", {item["entity"]["id"] for item in public["items"]})

    def test_public_mode_keeps_synthetic_news_and_drops_reviewed_news(self) -> None:
        synthetic = replace(provider_candidate("texans", "houston-texans-official:synthetic"),
                            stable_id="news:synthetic", data_mode="demo", tier=TimelineTier.MEANINGFUL_CHANGE,
                            change_time="2026-09-23T11:00:00Z")
        reviewed = replace(synthetic, stable_id="news:reviewed", data_mode="provider",
                           source_provider="houston-texans-official:reviewed")
        with patch("sports_briefing.news.timeline.load_news_timeline_candidates", return_value=[synthetic, reviewed]):
            ids = [item["id"] for item in build_home_timeline(self.database, as_of=AS_OF, public_mode=True)["items"]]
        self.assertIn("news:synthetic", ids)
        self.assertNotIn("news:reviewed", ids)

    def test_synthetic_texans_and_scottie_demo_items_are_labelled(self) -> None:
        public = build_home_timeline(self.database, as_of=AS_OF, public_mode=True)
        by_entity: dict[str, list[dict]] = {}
        for item in public["items"]:
            by_entity.setdefault(item["entity"]["id"], []).append(item)

        self.assertEqual(set(by_entity), {"texans", "scheffler"})
        for item in public["items"]:
            self.assertEqual(item["data_mode"], "demo")
            self.assertEqual(item["source"]["provider"], "synthetic-demo")
            self.assertIn("synthetic", item["source"]["attribution"])
            self.assertTrue(item["title"].endswith("(demo)"))
            self.assertTrue(item["summary"].startswith("Demo data: "))
            self.assertTrue(item["source"]["record_id"].startswith("synthetic-demo-"))
        self.assertFalse(self.database.exists(), "demo mode must not seed the database")

    def test_demo_items_obey_existing_freshness_and_are_stable_within_a_day(self) -> None:
        morning = build_home_timeline(self.database, as_of="2026-09-23T01:00:00Z", public_mode=True)
        evening = build_home_timeline(self.database, as_of="2026-09-23T23:00:00Z", public_mode=True)
        self.assertEqual([item["id"] for item in morning["items"]], [item["id"] for item in evening["items"]])
        # The demo Scottie result is observed at 18:00 the previous day, so the
        # unchanged 36-hour recent-result window still applies to the input state.
        as_of = datetime(2026, 9, 23, 23, tzinfo=timezone.utc)
        result = next(item for item in load_demo_scheffler_candidates(as_of, hide_results=True)
                      if item.tier is TimelineTier.RECENT_RESULT)
        self.assertEqual(result.event_time, "2026-09-22T18:00:00Z")

    def test_demo_status_survives_api_projection(self) -> None:
        response = TestClient(create_app(self.database, public_mode=True)).get(f"/timeline?as_of={AS_OF}")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertTrue(items)
        self.assertTrue(all(item["data_mode"] == "demo" for item in items))

    def test_ranking_ignores_data_mode_and_keeps_order(self) -> None:
        as_of = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
        demo = (load_demo_texans_candidates(as_of, hide_results=True)
                + load_demo_scheffler_candidates(as_of, hide_results=True))
        # Mixed modes would reorder the result if data_mode leaked into the ranking key.
        mixed = [replace(item, data_mode="provider") if index % 2 else item for index, item in enumerate(demo)]
        as_provider = [replace(item, data_mode="provider") for item in demo]
        ranked = [item.stable_id for item in rank_candidates(as_provider, as_of=as_of)]
        self.assertEqual(ranked, [item.stable_id for item in rank_candidates(demo, as_of=as_of)])
        self.assertEqual(ranked, [item.stable_id for item in rank_candidates(mixed, as_of=as_of)])
        public = build_home_timeline(self.database, as_of=AS_OF, public_mode=True)
        self.assertEqual([item["id"] for item in public["items"]], ranked)
        self.assertEqual([item["reason"] for item in public["items"]],
                         ["meaningful_status_change", "recent_result", "upcoming_context", "upcoming_context"])

    def test_per_entity_cap_still_applies_to_demo_and_synthetic_news(self) -> None:
        self.import_synthetic_news()
        as_of = "2026-09-25T11:30:00Z"
        public = build_home_timeline(self.database, as_of=as_of, public_mode=True)
        texans = [item["id"] for item in public["items"] if item["entity"]["id"] == "texans"]

        self.assertEqual(len(texans), 2)
        self.assertTrue(texans[0].startswith("news:"))
        self.assertTrue(texans[1].startswith("texans:availability:"))
        self.assertNotIn("texans:game:synthetic-demo-texans-game", texans)
        news = next(item for item in public["items"] if item["id"] == texans[0])
        self.assertEqual(news["data_mode"], "demo")

    def test_hide_and_show_results_apply_to_demo_results(self) -> None:
        def result_item(hide: bool) -> dict:
            timeline = build_home_timeline(self.database, as_of=AS_OF, hide_results=hide, public_mode=True)
            return next(item for item in timeline["items"] if item["reason"] == "recent_result")

        hidden = result_item(True)
        self.assertTrue(hidden["result_hidden"])
        self.assertNotIn("finished", hidden["summary"])
        self.assertNotIn("-12", hidden["summary"])
        revealed = result_item(False)
        self.assertNotIn("result_hidden", revealed)
        self.assertIn("finished position 3 at -12", revealed["summary"])

    def test_public_api_blocks_restricted_briefings_and_reports_meta(self) -> None:
        self.seed_arsenal()
        self.seed_texans()
        client = TestClient(create_app(self.database, public_mode=True))
        for path in ("/briefings/arsenal", "/briefings/texans"):
            response = client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertIn("public mode", response.json()["detail"])
        self.assertEqual(client.get("/meta").json(), {
            "public_mode": True, "version": "0.2.0",
            "entities": {"arsenal": "unavailable", "texans": "demo", "scheffler": "demo"},
        })

    def test_public_mode_uses_no_network(self) -> None:
        with patch("socket.socket.connect", side_effect=AssertionError("network used")), \
                patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            response = TestClient(create_app(self.database, public_mode=True)).get(f"/timeline?as_of={AS_OF}")
        self.assertEqual(response.status_code, 200)


class DevelopmentModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "sports.sqlite3"

    def test_default_behavior_is_unchanged_without_the_setting(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app(self.database))
            timeline = client.get(f"/timeline?as_of={AS_OF}").json()
            self.assertEqual(timeline["items"], [])
            self.assertEqual(timeline["unavailable_entities"], ["arsenal", "texans", "scheffler"])
            self.assertIn("Run ingestion first", client.get("/briefings/arsenal").json()["detail"])
            self.assertEqual(client.get("/meta").json()["public_mode"], False)

    def test_provider_items_carry_no_demo_marker(self) -> None:
        candidate = provider_candidate("arsenal", "football-data.org")
        with patch("sports_briefing.arsenal_timeline.load_arsenal_timeline_candidates", return_value=[candidate]):
            items = build_home_timeline(self.database, as_of=AS_OF)["items"]
        self.assertEqual([item["id"] for item in items], [candidate.stable_id])
        self.assertNotIn("data_mode", items[0])


class IngestionGuardTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            code = main(list(args))
        return code, stderr.getvalue()

    def test_sportradar_ingestion_fails_clearly_in_public_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {PUBLIC_MODE_ENV: "true", "SPORTRADAR_API_KEY": "unused-test-value"}), \
                patch("sports_briefing.cli.fetch_schedule") as fetch_schedule, \
                patch("sports_briefing.cli.retrieve_scottie") as retrieve_scottie:
            database = Path(directory) / "sports.sqlite3"
            for entity in ("texans", "scheffler"):
                code, stderr = self.run_cli("ingest", entity, "--db", str(database))
                self.assertEqual(code, 1)
                self.assertIn("Sportradar ingestion is disabled when SPORTS_BRIEFING_PUBLIC_MODE=true", stderr)
            fetch_schedule.assert_not_called()
            retrieve_scottie.assert_not_called()
            self.assertFalse(database.exists())

    def test_cli_timeline_honours_public_mode(self) -> None:
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {PUBLIC_MODE_ENV: "true"}), \
                redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = main(["timeline", "--db", str(Path(directory) / "none.sqlite3"), "--as-of", AS_OF])
        self.assertEqual(code, 0)
        items = json.loads(stdout.getvalue())["items"]
        self.assertTrue(items)
        self.assertTrue(all(item["data_mode"] == "demo" for item in items))


if __name__ == "__main__":
    unittest.main()

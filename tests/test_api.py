from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.briefing import build_arsenal_briefing
from sports_briefing.football_data import normalize_matches
from sports_briefing.storage import initialize_database, persist_successful_fetch


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "arsenal_matches.json"


class ArsenalAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "briefing.sqlite3"

    def client(self) -> TestClient:
        return TestClient(create_app(self.database))

    def seed_database(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        fixtures, ignored = normalize_matches(payload)
        initialize_database(self.database)
        persist_successful_fetch(
            self.database,
            request_url="https://api.football-data.org/v4/teams/57/matches",
            date_from="2026-09-01",
            date_to="2026-10-01",
            started_at="2026-09-20T11:59:58Z",
            completed_at="2026-09-20T12:00:00Z",
            http_status=200,
            raw_response=json.dumps(payload),
            received_count=3,
            fixtures=fixtures,
            filtered_unsupported_count=ignored,
        )

    def test_health_succeeds_without_a_database(self) -> None:
        response = self.client().get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_briefing_projects_persisted_deterministic_state_without_writing_or_fetching(self) -> None:
        self.seed_database()
        expected = build_arsenal_briefing(self.database, hide_results=False)
        before = self.database.read_bytes()

        with patch(
            "sports_briefing.football_data.urlopen",
            side_effect=AssertionError("the read API must not contact the provider"),
        ):
            response = self.client().get("/briefings/arsenal?hide_results=false")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["entity"], {"id": "arsenal", "name": "Arsenal"})
        self.assertEqual(body["as_of"], expected["as_of"])
        self.assertEqual(body["next_match"]["kickoff_utc"], expected["next_match"]["kickoff_utc"])
        self.assertEqual(
            body["latest_completed_match"]["result"],
            {"duration": "REGULAR", "full_time": {"away": 0, "home": 3}, "winner": "HOME_TEAM"},
        )
        self.assertEqual(body["source"]["checked_at"], "2026-09-20T12:00:00Z")
        self.assertEqual(self.database.read_bytes(), before)

    def test_hidden_briefing_omits_result_fields_at_every_depth(self) -> None:
        self.seed_database()

        with patch(
            "sports_briefing.api.build_arsenal_briefing",
            wraps=build_arsenal_briefing,
        ) as briefing_builder:
            response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 200)
        briefing_builder.assert_called_once_with(self.database, hide_results=True)
        body = response.json()
        self.assertEqual(body["spoiler"], {"results_hidden": True})
        self.assertTrue(body["latest_completed_match"]["result_hidden"])
        serialized = json.dumps(body).lower()
        for forbidden in ('"result"', '"winner"', '"score"', '"duration"'):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("3–0", serialized)

    def test_missing_briefing_state_returns_controlled_not_found(self) -> None:
        response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing is not available. Run ingestion first."},
        )

    def test_database_without_successful_ingestion_returns_controlled_not_found(self) -> None:
        initialize_database(self.database)

        response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing is not available. Run ingestion first."},
        )

    def test_successful_empty_ingestion_returns_controlled_not_found(self) -> None:
        initialize_database(self.database)
        persist_successful_fetch(
            self.database,
            request_url="https://api.football-data.org/v4/teams/57/matches",
            date_from="2026-09-01",
            date_to="2026-10-01",
            started_at="2026-09-20T11:59:58Z",
            completed_at="2026-09-20T12:00:00Z",
            http_status=200,
            raw_response='{"matches":[]}',
            received_count=0,
            fixtures=[],
            filtered_unsupported_count=0,
        )

        response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing is not available. Run ingestion first."},
        )

    def test_unreadable_database_returns_controlled_service_error(self) -> None:
        self.database.write_text("not a sqlite database", encoding="utf-8")

        response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing could not be read."},
        )

    def test_malformed_persisted_fixture_returns_controlled_service_error(self) -> None:
        self.seed_database()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE football_fixtures SET kickoff_utc = 'not-a-timestamp' WHERE provider_match_id = '5002'"
            )

        response = self.client().get("/briefings/arsenal")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing could not be read."},
        )

    def test_malformed_persisted_score_returns_controlled_service_error(self) -> None:
        self.seed_database()
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE football_fixtures SET score_json = 'not-json' WHERE provider_match_id = '5001'"
            )

        response = self.client().get("/briefings/arsenal?hide_results=false")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "Arsenal briefing could not be read."},
        )

    def test_non_object_persisted_score_returns_controlled_service_error(self) -> None:
        self.seed_database()
        for score_json in ("[]", "null"):
            with self.subTest(score_json=score_json):
                with sqlite3.connect(self.database) as connection:
                    connection.execute(
                        "UPDATE football_fixtures SET score_json = ? WHERE provider_match_id = '5001'",
                        (score_json,),
                    )

                response = self.client().get("/briefings/arsenal?hide_results=false")

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(),
                    {"detail": "Arsenal briefing could not be read."},
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from sports_briefing.cli import main
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "arsenal_matches.json"


def load_response() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FakeHTTPResponse:
    status = 200

    def __init__(self, payload: dict[str, object]):
        self.body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class MilestoneOneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "briefing.sqlite3"

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def ingest_args(self) -> tuple[str, ...]:
        return (
            "ingest",
            "arsenal",
            "--from",
            "2026-09-01",
            "--to",
            "2026-10-01",
            "--db",
            str(self.db_path),
        )

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_first_ingestion_inserts_supported_matches(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())

        code, output, _ = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["outcomes"], {"inserted": 2, "no_change": 0, "updated": 0})

        code, output, _ = self.run_cli("inspect", "arsenal", "--db", str(self.db_path))
        inspected = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual([item["provider_match_id"] for item in inspected["fixtures"]], ["5001", "5002"])
        self.assertEqual(inspected["latest_fetch"]["filtered_unsupported_count"], 1)

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_identical_second_ingestion_creates_no_duplicates(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        code, output, _ = self.run_cli(*self.ingest_args())

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["outcomes"], {"inserted": 0, "no_change": 2, "updated": 0})
        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        self.assertEqual(len(inspected["fixtures"]), 2)

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_changed_provider_state_updates_matching_record(self, fetch) -> None:
        initial = load_response()
        changed = load_response()
        changed_match = changed["matches"][1]
        changed_match["status"] = "FINISHED"
        changed_match["lastUpdated"] = "2026-09-23T21:05:00Z"
        changed_match["score"] = {
            "winner": "AWAY_TEAM",
            "duration": "REGULAR",
            "fullTime": {"home": 1, "away": 2},
            "halfTime": {"home": 1, "away": 1},
        }
        fetch.side_effect = [FakeHTTPResponse(initial), FakeHTTPResponse(changed)]

        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        code, output, _ = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["outcomes"], {"inserted": 0, "no_change": 1, "updated": 1})

        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        by_id = {fixture["provider_match_id"]: fixture for fixture in inspected["fixtures"]}
        self.assertEqual(by_id["5002"]["status"], "FINISHED")
        self.assertEqual(by_id["5002"]["score_full_time"], {"away": 2, "home": 1})

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_persisted_state_survives_a_new_process(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sports_briefing",
                "briefing",
                "arsenal",
                "--db",
                str(self.db_path),
                "--as-of",
                "2026-09-20T12:00:00Z",
            ],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["next_match"]["provider_match_id"], "5002")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_reserved_characters_in_database_path_survive_process_restart(self, fetch) -> None:
        self.db_path = Path(self.temp_dir.name) / "briefing #1?.sqlite3"
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "sports_briefing",
                "briefing",
                "arsenal",
                "--db",
                str(self.db_path),
                "--as-of",
                "2026-09-20T12:00:00Z",
            ],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["next_match"]["provider_match_id"], "5002")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_network_failure_preserves_existing_fixtures(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        before = self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1]
        fetch.side_effect = urllib.error.URLError("temporary outage")

        code, _, error = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 1)
        self.assertIn("provider", error.lower())
        after = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        self.assertEqual(json.loads(before)["fixtures"], after["fixtures"])
        self.assertEqual(after["latest_attempt"]["outcome"], "provider_failure")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_malformed_payload_fails_clearly_without_partial_writes(self, fetch) -> None:
        malformed = load_response()
        malformed["matches"][1].pop("utcDate")
        fetch.return_value = FakeHTTPResponse(malformed)

        code, _, error = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 1)
        self.assertIn("normalization", error.lower())
        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        self.assertEqual(inspected["fixtures"], [])
        self.assertEqual(inspected["latest_attempt"]["outcome"], "normalization_failure")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_briefing_is_deterministic_for_same_state_and_as_of(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        args = (
            "briefing",
            "arsenal",
            "--db",
            str(self.db_path),
            "--as-of",
            "2026-09-20T12:00:00Z",
        )

        first = self.run_cli(*args)[1]
        second = self.run_cli(*args)[1]
        self.assertEqual(first, second)
        briefing = json.loads(first)
        self.assertEqual(briefing["latest_completed_match"]["score"], {"away": 0, "home": 3})
        self.assertEqual(briefing["next_match"]["competition_code"], "CL")
        self.assertEqual(
            briefing["source"]["attribution"],
            "Football data provided by the Football-Data.org API",
        )

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_spoiler_mode_omits_all_result_fields_and_raw_payload(self, fetch) -> None:
        fetch.return_value = FakeHTTPResponse(load_response())
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)

        code, output, _ = self.run_cli(
            "briefing",
            "arsenal",
            "--db",
            str(self.db_path),
            "--as-of",
            "2026-09-20T12:00:00Z",
            "--hide-results",
        )
        self.assertEqual(code, 0)
        lowered = output.lower()
        self.assertNotIn('"score"', lowered)
        self.assertNotIn('"winner"', lowered)
        self.assertNotIn("raw", lowered)
        briefing = json.loads(output)
        self.assertTrue(briefing["latest_completed_match"]["result_hidden"])
        self.assertEqual(briefing["latest_completed_match"]["status"], "FINISHED")
        self.assertEqual(
            briefing["source"]["attribution"],
            "Football data provided by the Football-Data.org API",
        )

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_briefing_orders_fractional_kickoffs_chronologically(self, fetch) -> None:
        payload = load_response()
        fractional = json.loads(json.dumps(payload["matches"][0]))
        fractional["id"] = 5003
        fractional["utcDate"] = "2026-09-13T15:30:00.100000Z"
        fractional["lastUpdated"] = "2026-09-13T17:41:00Z"
        payload["matches"].append(fractional)
        payload["resultSet"]["count"] = 4
        fetch.return_value = FakeHTTPResponse(payload)
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)

        briefing = json.loads(
            self.run_cli(
                "briefing",
                "arsenal",
                "--db",
                str(self.db_path),
                "--as-of",
                "2026-09-20T12:00:00Z",
            )[1]
        )
        self.assertEqual(briefing["latest_completed_match"]["provider_match_id"], "5003")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_older_provider_revision_cannot_regress_fixture(self, fetch) -> None:
        initial = load_response()
        newer = load_response()
        newer_match = newer["matches"][1]
        newer_match["status"] = "FINISHED"
        newer_match["lastUpdated"] = "2026-09-23T21:05:00.100000Z"
        newer_match["score"] = {
            "winner": "AWAY_TEAM",
            "duration": "REGULAR",
            "fullTime": {"home": 1, "away": 2},
            "halfTime": {"home": 1, "away": 1},
        }
        fetch.side_effect = [
            FakeHTTPResponse(initial),
            FakeHTTPResponse(newer),
            FakeHTTPResponse(initial),
        ]
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        accepted = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        accepted_match = next(
            item for item in accepted["fixtures"] if item["provider_match_id"] == "5002"
        )

        code, output, _ = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["outcomes"]["no_change"], 2)
        after = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        after_match = next(item for item in after["fixtures"] if item["provider_match_id"] == "5002")
        self.assertEqual(after_match["status"], "FINISHED")
        self.assertEqual(after_match["score_full_time"], {"away": 2, "home": 1})
        self.assertEqual(after_match["last_seen_at"], accepted_match["last_seen_at"])

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_persistence_failure_rolls_back_entire_batch(self, fetch) -> None:
        initial = load_response()
        changed = load_response()
        changed["matches"][0]["status"] = "AWARDED"
        changed["matches"][0]["lastUpdated"] = "2026-09-14T10:00:00Z"
        changed["matches"][1]["status"] = "POSTPONED"
        changed["matches"][1]["lastUpdated"] = "2026-09-20T10:00:00Z"
        fetch.side_effect = [FakeHTTPResponse(initial), FakeHTTPResponse(changed)]
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_second_fixture_update
                BEFORE UPDATE ON football_fixtures
                WHEN OLD.provider_match_id = '5002'
                BEGIN
                    SELECT RAISE(ABORT, 'simulated write failure');
                END
                """
            )

        code, _, error = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 1)
        self.assertIn("persistence failure", error.lower())
        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        by_id = {item["provider_match_id"]: item for item in inspected["fixtures"]}
        self.assertEqual(by_id["5001"]["status"], "FINISHED")
        self.assertEqual(by_id["5002"]["status"], "TIMED")

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_raw_response_diagnostic_is_bounded(self, fetch) -> None:
        payload = load_response()
        payload["diagnosticPadding"] = "x" * (300 * 1024)
        fetch.return_value = FakeHTTPResponse(payload)

        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        self.assertEqual(inspected["latest_fetch"]["raw_response_truncated"], 1)
        with sqlite3.connect(self.db_path) as connection:
            raw_length = connection.execute(
                "SELECT length(CAST(raw_response AS BLOB)) FROM provider_fetches ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        self.assertLessEqual(raw_length, 256 * 1024)

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_bounded_failure_history_retains_last_success_for_briefing(self, fetch) -> None:
        fetch.side_effect = [FakeHTTPResponse(load_response())] + [
            urllib.error.URLError("temporary outage") for _ in range(21)
        ]
        self.assertEqual(self.run_cli(*self.ingest_args())[0], 0)
        for _ in range(21):
            self.assertEqual(self.run_cli(*self.ingest_args())[0], 1)

        code, output, _ = self.run_cli(
            "briefing",
            "arsenal",
            "--db",
            str(self.db_path),
            "--as-of",
            "2026-09-20T12:00:00Z",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["next_match"]["provider_match_id"], "5002")
        with sqlite3.connect(self.db_path) as connection:
            fetch_count = connection.execute("SELECT count(*) FROM provider_fetches").fetchone()[0]
        self.assertEqual(fetch_count, 21)

    @patch.dict(os.environ, {"FOOTBALL_DATA_API_KEY": "test-key"})
    @patch("sports_briefing.football_data.urlopen")
    def test_duplicate_supported_provider_id_rejects_whole_response(self, fetch) -> None:
        duplicate = load_response()
        duplicate_record = json.loads(json.dumps(duplicate["matches"][0]))
        duplicate["matches"].append(duplicate_record)
        duplicate["resultSet"]["count"] = 4
        fetch.return_value = FakeHTTPResponse(duplicate)

        code, _, error = self.run_cli(*self.ingest_args())
        self.assertEqual(code, 1)
        self.assertIn("duplicate provider match id", error)
        inspected = json.loads(self.run_cli("inspect", "arsenal", "--db", str(self.db_path))[1])
        self.assertEqual(inspected["fixtures"], [])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from email.message import Message
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
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.cli import main
from sports_briefing.nfl.briefing import build_texans_briefing
from sports_briefing.nfl.sportradar import (
    MAX_RESPONSE_BYTES,
    NormalizationError,
    ProviderError,
    fetch_schedule,
    normalize_injuries,
    normalize_schedule,
)
from sports_briefing.nfl.storage import initialize_nfl_database, inspect_texans_state
from sports_briefing.storage import initialize_database


FIXTURES = Path(__file__).parent / "fixtures"
TEXANS_ID = "82d2d380-3834-4938-835f-aec541e5ece7"


class FixtureDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixture_time = cls(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        return fixture_time if tz is None else fixture_time.astimezone(tz)


def load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload: object, generated: str) -> None:
        self._body = json.dumps(payload).encode()
        self.status = 200
        self.headers = Message()
        self.headers["x-generated-date"] = generated

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            return self._body
        result, self._body = self._body[:amount], self._body[amount:]
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class TexansMilestoneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "sports.sqlite3"
        clock = patch("sports_briefing.cli.datetime", FixtureDateTime)
        clock.start()
        self.addCleanup(clock.stop)
        self.schedule = load("texans_schedule.json")
        self.limited = load("texans_injuries_limited.json")
        self.dnp = load("texans_injuries_dnp.json")

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        from contextlib import redirect_stderr, redirect_stdout

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def ingest(
        self,
        injuries: dict[str, object],
        generated: str,
        *,
        schedule: dict[str, object] | None = None,
        week: int = 3,
        season: int = 2026,
        season_type: str = "REG",
    ) -> tuple[int, str, str]:
        responses = [
            FakeResponse(deepcopy(schedule or self.schedule), generated),
            FakeResponse(injuries, generated),
        ]
        with patch.dict(os.environ, {"SPORTRADAR_API_KEY": "secret"}), patch(
            "sports_briefing.nfl.sportradar.urlopen", side_effect=responses
        ), patch("sports_briefing.cli.time.sleep"):
            return self.run_cli(
                "ingest", "texans", "--db", str(self.database), "--season", str(season),
                "--season-type", season_type, "--week", str(week)
            )

    def test_initial_ingestion_persists_game_status_and_new_report(self) -> None:
        code, output, error = self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")

        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["outcomes"]["changes"], 1)
        state = inspect_texans_state(self.database)
        self.assertEqual(state["games"][0]["provider_game_id"], "game-texans-jaguars")
        self.assertEqual(state["availability"][0]["practice_status"], "LIMITED")
        self.assertEqual(state["changes"][0]["change_type"], "NEW_REPORT")

    def test_identical_rerun_is_idempotent(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        code, output, error = self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")

        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["outcomes"]["changes"], 0)
        self.assertEqual(len(inspect_texans_state(self.database)["changes"]), 1)

    def test_limited_to_dnp_and_dnp_to_limited_are_distinct_changes(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        self.assertEqual(self.ingest(self.dnp, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        recovered = deepcopy(self.limited)
        recovered["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-27T00:00:00Z"
        code, _, error = self.ingest(recovered, "Sun, 27 Sep 2026 01:00:00 GMT")

        self.assertEqual(code, 0, error)
        changes = inspect_texans_state(self.database)["changes"]
        self.assertEqual([row["change_type"] for row in changes], [
            "NEW_REPORT", "PRACTICE_STATUS_CHANGED", "GAME_STATUS_CHANGED",
            "PRACTICE_STATUS_CHANGED", "GAME_STATUS_CHANGED",
        ])
        self.assertEqual(changes[1]["old_value"], "LIMITED")
        self.assertEqual(changes[1]["new_value"], "DNP")
        self.assertEqual(changes[3]["old_value"], "DNP")
        self.assertEqual(changes[3]["new_value"], "LIMITED")

        final_dnp = deepcopy(self.dnp)
        final_dnp["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-28T00:00:00Z"
        self.assertEqual(self.ingest(final_dnp, "Mon, 28 Sep 2026 01:00:00 GMT")[0], 0)
        final_changes = inspect_texans_state(self.database)["changes"]
        self.assertEqual(final_changes[-2]["change_type"], "PRACTICE_STATUS_CHANGED")
        self.assertEqual((final_changes[-2]["old_value"], final_changes[-2]["new_value"]), ("LIMITED", "DNP"))

    def test_game_designation_change_is_detected(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        updated = deepcopy(self.limited)
        updated["teams"][0]["players"][0]["injuries"][0]["status"] = "Out"

        self.assertEqual(self.ingest(updated, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        changes = inspect_texans_state(self.database)["changes"]
        self.assertEqual(changes[-1]["change_type"], "GAME_STATUS_CHANGED")
        self.assertEqual((changes[-1]["old_value"], changes[-1]["new_value"]), ("QUESTIONABLE", "OUT"))

    def test_new_player_is_new_report(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        updated = deepcopy(self.limited)
        player = deepcopy(updated["teams"][0]["players"][0])
        player.update({"id": "player-anderson", "name": "Will Anderson Jr.", "sr_id": "sr:player:anderson"})
        updated["teams"][0]["players"].append(player)

        self.assertEqual(self.ingest(updated, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        changes = inspect_texans_state(self.database)["changes"]
        self.assertEqual(changes[-1]["change_type"], "NEW_REPORT")
        self.assertEqual(changes[-1]["player_name"], "Will Anderson Jr.")

    def test_stale_revision_and_equal_revision_conflict_cannot_overwrite(self) -> None:
        self.assertEqual(self.ingest(self.dnp, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        for revision in ("Sat, 26 Sep 2026 12:00:00 GMT", "Sat, 26 Sep 2026 13:00:00 GMT"):
            code, _, error = self.ingest(self.limited, revision)
            self.assertEqual(code, 1)
            self.assertIn("revision", error.lower())
        self.assertEqual(inspect_texans_state(self.database)["availability"][0]["practice_status"], "DNP")

    def test_transaction_failure_does_not_partially_replace_state_or_changes(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        with sqlite3.connect(self.database) as connection:
            connection.execute("""
                CREATE TRIGGER reject_nfl_change BEFORE INSERT ON nfl_availability_changes
                BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """)

        changed_schedule = deepcopy(self.schedule)
        changed_schedule["weeks"][0]["games"][0]["status"] = "flex-schedule"
        code, _, error = self.ingest(
            self.dnp,
            "Sat, 26 Sep 2026 13:00:00 GMT",
            schedule=changed_schedule,
        )

        self.assertEqual(code, 1)
        self.assertIn("persistence", error.lower())
        state = inspect_texans_state(self.database)
        self.assertEqual(state["games"][0]["status"], "scheduled")
        self.assertEqual(state["availability"][0]["practice_status"], "LIMITED")
        self.assertEqual(len(state["changes"]), 1)

    def test_network_failure_preserves_last_accepted_state(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        before = inspect_texans_state(self.database)
        with patch.dict(os.environ, {"SPORTRADAR_API_KEY": "secret"}), patch(
            "sports_briefing.nfl.sportradar.urlopen", side_effect=URLError("offline")
        ):
            code, _, error = self.run_cli(
                "ingest", "texans", "--db", str(self.database), "--season", "2026",
                "--season-type", "REG", "--week", "3"
            )
        self.assertEqual(code, 1)
        self.assertIn("provider", error.lower())
        after = inspect_texans_state(self.database)
        self.assertEqual(after["games"], before["games"])
        self.assertEqual(after["availability"], before["availability"])
        self.assertEqual(after["changes"], before["changes"])

    def test_persisted_texans_state_survives_process_restart(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        completed = subprocess.run(
            [sys.executable, "-m", "sports_briefing", "briefing", "texans", "--db", str(self.database), "--as-of", "2026-09-26T12:30:00Z"],
            cwd=Path(__file__).parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["availability"][0]["practice_status"], "LIMITED")

    def test_report_unavailable_and_verified_empty_are_distinct(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        future = build_texans_briefing(self.database, as_of="2026-09-28T00:00:00Z")
        self.assertFalse(future["availability_report"]["available"])
        self.assertEqual(future["availability"], [])

        empty = deepcopy(self.limited)
        empty["teams"][0]["players"] = []
        self.assertEqual(self.ingest(empty, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        current = build_texans_briefing(self.database, as_of="2026-09-26T12:30:00Z")
        self.assertTrue(current["availability_report"]["available"])
        self.assertIsNone(current["availability_report"]["report_date"])
        self.assertEqual(current["availability"], [])
        self.assertEqual(current["changes"][0]["change_type"], "REMOVED_FROM_REPORT")

    def test_equal_revision_ignores_provider_array_order_only(self) -> None:
        two_players = deepcopy(self.limited)
        player = deepcopy(two_players["teams"][0]["players"][0])
        player.update({"id": "player-anderson", "name": "Will Anderson Jr.", "sr_id": "sr:player:anderson"})
        two_players["teams"][0]["players"].append(player)
        self.assertEqual(self.ingest(two_players, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        reordered = deepcopy(two_players)
        reordered["teams"][0]["players"].reverse()

        code, output, error = self.ingest(reordered, "Sat, 26 Sep 2026 12:00:00 GMT")

        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["outcomes"]["changes"], 0)

    def test_deleted_game_is_not_selected_as_next_game(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        deleted = deepcopy(self.schedule)
        deleted["weeks"][0]["games"] = []
        deleted["deleted_games"] = [{"id": "game-texans-jaguars"}]
        week_four = deepcopy(self.limited)
        week_four["week"] = {"id": "week-4", "sequence": 4, "title": "4"}
        self.assertEqual(
            self.ingest(
                week_four,
                "Sat, 26 Sep 2026 13:00:00 GMT",
                schedule=deleted,
                week=4,
            )[0],
            0,
        )

        briefing = build_texans_briefing(self.database, as_of="2026-09-26T12:30:00Z")

        self.assertEqual(briefing["next_game"]["provider_game_id"], "game-titans-texans")
        self.assertTrue(briefing["availability_report"]["available"])

    def test_missing_optional_status_fields_remain_unknown(self) -> None:
        unknown = deepcopy(self.limited)
        injury = unknown["teams"][0]["players"][0]["injuries"][0]
        injury.pop("status")
        injury.pop("practice")
        injury["primary"] = None

        normalized = normalize_injuries(unknown)

        self.assertIsNone(normalized.players[0].practice_status)
        self.assertIsNone(normalized.players[0].game_status)
        self.assertIsNone(normalized.players[0].injury)

    def test_no_change_refreshes_status_date_before_later_regression_check(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        refreshed = deepcopy(self.limited)
        refreshed["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-26T00:00:00Z"
        self.assertEqual(self.ingest(refreshed, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        code, _, error = self.ingest(self.limited, "Sat, 26 Sep 2026 14:00:00 GMT")
        self.assertEqual(code, 1)
        self.assertIn("status date regressed", error.lower())

    def test_newer_report_can_remove_latest_dated_player_without_rejecting_remaining_player(self) -> None:
        initial = deepcopy(self.limited)
        latest = initial["teams"][0]["players"][0]
        latest["id"] = "player-latest"
        latest["name"] = "Latest Dated Player"
        latest["injuries"][0]["status_date"] = "2026-09-26T00:00:00Z"
        remaining = deepcopy(latest)
        remaining["id"] = "player-remaining"
        remaining["name"] = "Remaining Player"
        remaining["injuries"][0]["status_date"] = "2026-09-25T00:00:00Z"
        initial["teams"][0]["players"] = [latest, remaining]
        self.assertEqual(self.ingest(initial, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)

        newer = deepcopy(initial)
        newer["teams"][0]["players"] = [deepcopy(remaining)]
        code, _, error = self.ingest(newer, "Sat, 26 Sep 2026 13:00:00 GMT")
        self.assertEqual(code, 0, error)
        state = inspect_texans_state(self.database)
        by_player = {row["player_id"]: row for row in state["availability"]}
        self.assertEqual(by_player["player-latest"]["is_present"], 0)
        self.assertEqual(by_player["player-remaining"]["is_present"], 1)

        returned = deepcopy(initial)
        returned["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-27T00:00:00Z"
        code, _, error = self.ingest(returned, "Sun, 27 Sep 2026 01:00:00 GMT")
        self.assertEqual(code, 0, error)
        latest_changes = inspect_texans_state(self.database)["changes"]
        self.assertEqual(latest_changes[-1]["change_type"], "NEW_REPORT")
        self.assertEqual(latest_changes[-1]["player_id"], "player-latest")

    def test_change_report_date_comes_from_changed_player(self) -> None:
        initial = deepcopy(self.limited)
        first = initial["teams"][0]["players"][0]
        first["injuries"][0]["status_date"] = "2026-09-26T00:00:00Z"
        second = deepcopy(first)
        second["id"] = "player-second"
        second["name"] = "Second Player"
        second["injuries"][0]["status_date"] = "2026-09-25T00:00:00Z"
        initial["teams"][0]["players"] = [first, second]
        self.assertEqual(self.ingest(initial, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)

        changed = deepcopy(initial)
        for player in changed["teams"][0]["players"]:
            player["injuries"][0]["practice"]["status"] = "Did Not Participate In Practice"
        self.assertEqual(self.ingest(changed, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)

        practice_changes = [
            row for row in inspect_texans_state(self.database)["changes"]
            if row["change_type"] == "PRACTICE_STATUS_CHANGED"
        ]
        by_player = {row["player_id"]: row["report_date"] for row in practice_changes}
        self.assertEqual(by_player["player-collins"], "2026-09-26T00:00:00Z")
        self.assertEqual(by_player["player-second"], "2026-09-25T00:00:00Z")

    def test_cross_season_game_id_reuse_and_deletion_roll_back_whole_batch(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 13:00:00 GMT")[0], 0)
        prior = inspect_texans_state(self.database)
        prior_changes = len(prior["changes"])

        reused = deepcopy(self.schedule)
        reused.update({"id": "season-2025-reg", "year": 2025})
        injuries_2025 = deepcopy(self.limited)
        injuries_2025["season"].update({"id": "season-2025-reg", "year": 2025})
        code, _, error = self.ingest(
            injuries_2025,
            "Sat, 26 Sep 2026 12:00:00 GMT",
            schedule=reused,
            season=2025,
        )
        self.assertEqual(code, 1)
        self.assertIn("season scope", error.lower())

        deleted = deepcopy(reused)
        deleted["weeks"][0]["games"][0]["id"] = "game-2025-other"
        deleted["weeks"][1]["games"][0]["id"] = "game-2025-other-week-4"
        deleted["deleted_games"] = [{"id": "game-texans-jaguars"}]
        code, _, error = self.ingest(
            injuries_2025,
            "Sat, 26 Sep 2026 14:00:00 GMT",
            schedule=deleted,
            season=2025,
        )
        self.assertEqual(code, 1)
        self.assertIn("another season scope", error.lower())
        after = inspect_texans_state(self.database)
        self.assertEqual(after["games"], prior["games"])
        self.assertEqual(len(after["changes"]), prior_changes)
        self.assertFalse(any(row["season_year"] == 2025 for row in after["availability"]))

    def test_cli_and_briefing_share_upcoming_game_status_policy(self) -> None:
        schedule = deepcopy(self.schedule)
        schedule["weeks"][0]["games"][0]["status"] = "postponed"
        injuries = deepcopy(self.limited)
        injuries["week"] = {"id": "week-4", "sequence": 4, "title": "4"}
        responses = [
            FakeResponse(schedule, "Sat, 26 Sep 2026 12:00:00 GMT"),
            FakeResponse(injuries, "Sat, 26 Sep 2026 12:00:02 GMT"),
        ]
        with patch.dict(os.environ, {"SPORTRADAR_API_KEY": "secret"}), patch(
            "sports_briefing.nfl.sportradar.urlopen", side_effect=responses
        ), patch("sports_briefing.cli.time.sleep"):
            code, output, error = self.run_cli(
                "ingest", "texans", "--db", str(self.database)
            )
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["scope"]["week"], 4)
        briefing = build_texans_briefing(self.database, as_of="2026-09-26T12:30:00Z")
        self.assertEqual(briefing["next_game"]["provider_game_id"], "game-titans-texans")

    def test_malformed_or_ambiguous_payload_fails_clearly(self) -> None:
        malformed = deepcopy(self.limited)
        malformed["teams"][0]["players"][0]["injuries"].append(
            deepcopy(malformed["teams"][0]["players"][0]["injuries"][0])
        )
        with self.assertRaises(NormalizationError):
            normalize_injuries(malformed)
        missing_team = deepcopy(self.limited)
        missing_team["teams"] = []
        with self.assertRaises(NormalizationError):
            normalize_injuries(missing_team)

    def test_explicit_schedule_scope_mismatch_fails_before_injury_fetch(self) -> None:
        wrong = deepcopy(self.schedule)
        wrong["year"] = 2025
        with patch.dict(os.environ, {"SPORTRADAR_API_KEY": "secret"}), patch(
            "sports_briefing.nfl.sportradar.urlopen",
            return_value=FakeResponse(wrong, "Sat, 26 Sep 2026 12:00:00 GMT"),
        ) as open_url:
            code, _, error = self.run_cli(
                "ingest", "texans", "--db", str(self.database), "--season", "2026",
                "--season-type", "REG", "--week", "3"
            )

        self.assertEqual(code, 1)
        self.assertIn("normalization", error.lower())
        self.assertEqual(open_url.call_count, 1)

    def test_week_rollover_does_not_compare_player_to_prior_week(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        schedule = deepcopy(self.schedule)
        schedule["weeks"] = [schedule["weeks"][1]]
        injuries = deepcopy(self.dnp)
        injuries["week"] = {"id": "week-4", "sequence": 4, "title": "4"}
        responses = [FakeResponse(schedule, "Sat, 3 Oct 2026 12:00:00 GMT"), FakeResponse(injuries, "Sat, 3 Oct 2026 12:00:00 GMT")]
        with patch.dict(os.environ, {"SPORTRADAR_API_KEY": "secret"}), patch(
            "sports_briefing.nfl.sportradar.urlopen", side_effect=responses
        ), patch("sports_briefing.cli.time.sleep"):
            code, _, error = self.run_cli("ingest", "texans", "--db", str(self.database), "--season", "2026", "--season-type", "REG", "--week", "4")
        self.assertEqual(code, 0, error)
        week_four = [c for c in inspect_texans_state(self.database)["changes"] if c["week"] == 4]
        self.assertEqual([c["change_type"] for c in week_four], ["NEW_REPORT"])

    def test_briefing_is_deterministic_and_uses_matching_week(self) -> None:
        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        first = build_texans_briefing(self.database, as_of="2026-09-26T12:30:00Z")
        second = build_texans_briefing(self.database, as_of="2026-09-26T12:30:00Z")

        self.assertEqual(first, second)
        self.assertEqual(first["next_game"]["provider_game_id"], "game-texans-jaguars")
        self.assertEqual(first["availability"][0]["practice_status"], "LIMITED")
        self.assertEqual(first["changes"][0]["change_type"], "NEW_REPORT")

    def test_texans_api_projects_existing_briefing_and_missing_state(self) -> None:
        missing = TestClient(create_app(self.database)).get("/briefings/texans")
        self.assertEqual(missing.status_code, 404)

        self.assertEqual(self.ingest(self.limited, "Sat, 26 Sep 2026 12:00:00 GMT")[0], 0)
        response = TestClient(create_app(self.database)).get("/briefings/texans")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["entity"], {"id": "texans", "name": "Houston Texans"})
        self.assertEqual(body["availability"][0]["practice_status"], "LIMITED")
        self.assertTrue(body["availability_report"]["available"])
        self.assertNotIn("raw", json.dumps(body).lower())

    def test_existing_arsenal_database_reports_texans_as_not_ingested(self) -> None:
        initialize_database(self.database)

        response = TestClient(create_app(self.database)).get("/briefings/texans")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Texans briefing is not available. Run ingestion first."},
        )

    @patch("sports_briefing.nfl.sportradar.urlopen")
    def test_http_adapter_uses_header_auth_requires_generated_date_and_bounds_errors(self, open_url) -> None:
        open_url.return_value = FakeResponse(self.schedule, "Sat, 26 Sep 2026 12:00:00 GMT")
        response = fetch_schedule("token", season_year=2026, season_type="REG", timeout=4)
        request = open_url.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "token")
        self.assertNotIn("token", request.full_url)
        self.assertEqual(response.generated_at, "2026-09-26T12:00:00Z")

        missing = FakeResponse(self.schedule, "Sat, 26 Sep 2026 12:00:00 GMT")
        del missing.headers["x-generated-date"]
        open_url.return_value = missing
        with self.assertRaises(ProviderError):
            fetch_schedule("token", season_year=2026, season_type="REG")

        open_url.side_effect = HTTPError("url", 429, "quota", {}, io.BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1)))
        with self.assertRaises(ProviderError) as raised:
            fetch_schedule("token", season_year=2026, season_type="REG")
        self.assertEqual(raised.exception.status, 429)
        self.assertLessEqual(len(raised.exception.body.encode()), MAX_RESPONSE_BYTES)


if __name__ == "__main__":
    unittest.main()

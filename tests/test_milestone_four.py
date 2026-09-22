from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.arsenal_timeline import derive_arsenal_candidates
from sports_briefing.cli import main
from sports_briefing.football_data import normalize_matches
from sports_briefing.nfl.sportradar import normalize_injuries, normalize_schedule
from sports_briefing.nfl.storage import initialize_nfl_database, persist_texans_fetch
from sports_briefing.nfl.timeline import derive_texans_candidates
from sports_briefing.storage import persist_successful_fetch
from sports_briefing.timeline import TimelineCandidate, TimelineTier, rank_candidates
from sports_briefing.timeline import build_home_timeline


AS_OF = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"


def candidate(
    stable_id: str,
    entity_id: str,
    tier: TimelineTier,
    *,
    event_time: str | None = None,
    change_time: str | None = None,
) -> TimelineCandidate:
    return TimelineCandidate(
        stable_id=stable_id,
        entity_id=entity_id,
        entity_name="Arsenal" if entity_id == "arsenal" else "Houston Texans",
        sport="football" if entity_id == "arsenal" else "nfl",
        item_type="game" if event_time else "availability_change",
        event_state="live" if tier is TimelineTier.LIVE else "context",
        tier=tier,
        title=stable_id,
        summary="Synthetic scenario",
        event_time=event_time,
        change_time=change_time,
        competition=None,
        source_provider="synthetic",
        source_attribution="Synthetic test data",
        source_generated_at=change_time or event_time or "2026-09-23T12:00:00Z",
        source_observed_at="2026-09-23T12:00:00Z",
        source_record_id=stable_id,
    )


class TimelineRankingTests(unittest.TestCase):
    def test_live_always_beats_imminent_or_recent(self) -> None:
        live_arsenal = candidate(
            "arsenal-live", "arsenal", TimelineTier.LIVE, event_time="2026-09-23T11:00:00Z"
        )
        imminent_texans = candidate(
            "texans-soon", "texans", TimelineTier.IMMINENT, event_time="2026-09-23T12:30:00Z"
        )
        recent_texans = candidate(
            "texans-recent", "texans", TimelineTier.RECENT_RESULT, event_time="2026-09-23T10:00:00Z"
        )

        ranked = rank_candidates([imminent_texans, recent_texans, live_arsenal], as_of=AS_OF)

        self.assertEqual([item.stable_id for item in ranked], [
            "arsenal-live", "texans-soon", "texans-recent"
        ])

    def test_explicit_precedence_applies_across_both_sports(self) -> None:
        candidates = [
            candidate("arsenal-routine", "arsenal", TimelineTier.ROUTINE, event_time="2026-09-27T12:00:00Z"),
            candidate("texans-change", "texans", TimelineTier.MEANINGFUL_CHANGE, change_time="2026-09-23T11:00:00Z"),
            candidate("arsenal-result", "arsenal", TimelineTier.RECENT_RESULT, event_time="2026-09-23T09:00:00Z"),
            candidate("texans-live", "texans", TimelineTier.LIVE, event_time="2026-09-23T10:00:00Z"),
            candidate("arsenal-soon", "arsenal", TimelineTier.IMMINENT, event_time="2026-09-23T14:00:00Z"),
        ]

        ranked = rank_candidates(candidates, as_of=AS_OF)

        self.assertEqual([item.stable_id for item in ranked], [
            "texans-live", "arsenal-soon", "texans-change", "arsenal-result"
        ])

    def test_same_tier_uses_time_then_stable_identity(self) -> None:
        tied_a = candidate("a", "texans", TimelineTier.IMMINENT, event_time="2026-09-23T14:00:00Z")
        tied_b = candidate("b", "arsenal", TimelineTier.IMMINENT, event_time="2026-09-23T14:00:00Z")
        nearer = candidate("nearer", "arsenal", TimelineTier.IMMINENT, event_time="2026-09-23T13:00:00Z")

        ranked = rank_candidates([tied_a, tied_b, nearer], as_of=AS_OF)

        self.assertEqual([item.stable_id for item in ranked], ["nearer", "b", "a"])

    def test_per_entity_limit_is_enforced_without_forcing_an_entity(self) -> None:
        ranked = rank_candidates(
            [
                candidate("a1", "arsenal", TimelineTier.LIVE, event_time="2026-09-23T11:00:00Z"),
                candidate("a2", "arsenal", TimelineTier.IMMINENT, event_time="2026-09-23T13:00:00Z"),
                candidate("a3", "arsenal", TimelineTier.ROUTINE, event_time="2026-09-25T12:00:00Z"),
            ],
            as_of=AS_OF,
        )

        self.assertEqual([item.stable_id for item in ranked], ["a1", "a2"])
        self.assertFalse(any(item.entity_id == "texans" for item in ranked))

    def test_imminent_texans_beats_routine_arsenal(self) -> None:
        ranked = rank_candidates(
            [
                candidate("arsenal-week", "arsenal", TimelineTier.ROUTINE, event_time="2026-09-28T12:00:00Z"),
                candidate("texans-soon", "texans", TimelineTier.IMMINENT, event_time="2026-09-23T16:00:00Z"),
            ],
            as_of=AS_OF,
        )

        self.assertEqual([item.stable_id for item in ranked], ["texans-soon", "arsenal-week"])

    def test_duplicate_identity_is_selected_once(self) -> None:
        duplicate = candidate("same", "arsenal", TimelineTier.IMMINENT, event_time="2026-09-23T14:00:00Z")

        ranked = rank_candidates([duplicate, duplicate], as_of=AS_OF)

        self.assertEqual([item.stable_id for item in ranked], ["same"])


class CandidateDerivationTests(unittest.TestCase):
    def arsenal_row(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "provider": "football-data.org",
            "provider_match_id": "match-1",
            "competition_code": "PL",
            "competition_name": "Premier League",
            "kickoff_utc": "2026-09-23T11:00:00Z",
            "status": "IN_PLAY",
            "home_team_name": "Arsenal FC",
            "away_team_name": "Example FC",
            "provider_updated_at": "2026-09-23T11:50:00Z",
            "last_seen_at": "2026-09-23T11:50:00Z",
            "score_json": '{"fullTime":{"home":2,"away":1}}',
            "winner": "HOME_TEAM",
            "score_duration": "REGULAR",
        }
        row.update(overrides)
        return row

    def texans_game(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "provider_game_id": "game-1",
            "season_year": 2026,
            "season_type": "REG",
            "week": 3,
            "scheduled_utc": "2026-09-23T11:00:00Z",
            "status": "inprogress",
            "home_team_name": "Houston Texans",
            "away_team_name": "Example Team",
            "provider_generated_at": "2026-09-23T11:50:00Z",
            "last_seen_at": "2026-09-23T11:50:00Z",
            "source_url": "https://example.test/schedule",
        }
        row.update(overrides)
        return row

    def change(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "change_key": "change-1",
            "season_year": 2026,
            "season_type": "REG",
            "week": 3,
            "player_id": "player-1",
            "player_name": "Player One",
            "change_type": "PRACTICE_STATUS_CHANGED",
            "old_value": "LIMITED",
            "new_value": "DNP",
            "provider_generated_at": "2026-09-23T11:30:00Z",
            "report_date": "2026-09-23T00:00:00Z",
            "observed_at": "2026-09-23T11:45:00Z",
            "source_url": "https://example.test/injuries",
        }
        row.update(overrides)
        return row

    def test_live_status_requires_plausible_kickoff_and_fresh_observation(self) -> None:
        arsenal = derive_arsenal_candidates(
            [self.arsenal_row()], as_of=AS_OF, hide_results=True
        )
        texans = derive_texans_candidates(
            [self.texans_game()], [], {"provider": "sportradar"}, as_of=AS_OF
        )
        stale = derive_texans_candidates(
            [self.texans_game(last_seen_at="2026-09-23T10:00:00Z")],
            [],
            {"provider": "sportradar"},
            as_of=AS_OF,
        )

        self.assertEqual(arsenal[0].reason, "live")
        self.assertEqual(texans[0].reason, "live")
        self.assertEqual(stale, [])

    def test_only_fixed_time_games_can_be_imminent(self) -> None:
        arsenal = derive_arsenal_candidates(
            [
                self.arsenal_row(provider_match_id="timed", status="TIMED", kickoff_utc="2026-09-23T13:00:00Z"),
                self.arsenal_row(provider_match_id="postponed", status="POSTPONED", kickoff_utc="2026-09-23T12:30:00Z"),
            ],
            as_of=AS_OF,
            hide_results=True,
        )
        texans = derive_texans_candidates(
            [
                self.texans_game(provider_game_id="scheduled", status="scheduled", scheduled_utc="2026-09-23T14:00:00Z"),
                self.texans_game(provider_game_id="flex", status="flex-schedule", scheduled_utc="2026-09-23T12:30:00Z"),
                self.texans_game(provider_game_id="delayed", status="delayed", scheduled_utc="2026-09-23T11:30:00Z"),
            ],
            [],
            {"provider": "sportradar"},
            as_of=AS_OF,
        )

        self.assertEqual([item.stable_id for item in arsenal], ["arsenal:match:timed"])
        self.assertEqual([item.stable_id for item in texans], ["texans:game:scheduled"])
        self.assertEqual(arsenal[0].reason, "starts_soon")
        self.assertEqual(texans[0].reason, "starts_soon")

    def test_recent_result_hides_or_reveals_structured_result(self) -> None:
        row = self.arsenal_row(status="FINISHED", kickoff_utc="2026-09-22T19:00:00Z")

        hidden = derive_arsenal_candidates([row], as_of=AS_OF, hide_results=True)[0]
        shown = derive_arsenal_candidates([row], as_of=AS_OF, hide_results=False)[0]

        self.assertTrue(hidden.result_hidden)
        self.assertIsNone(hidden.result)
        self.assertEqual(shown.result["winner"], "HOME_TEAM")
        self.assertEqual(shown.reason, "recent_result")

    def test_latest_availability_transition_wins_and_ancient_provider_data_is_suppressed(self) -> None:
        game = self.texans_game(status="scheduled", scheduled_utc="2026-09-27T17:00:00Z")
        newest = self.change()
        older = self.change(
            change_key="change-older",
            old_value="FULL",
            new_value="LIMITED",
            provider_generated_at="2026-09-23T10:00:00Z",
            observed_at="2026-09-23T10:05:00Z",
        )
        ancient = self.change(
            change_key="change-ancient",
            player_id="player-2",
            player_name="Player Two",
            provider_generated_at="2026-09-01T10:00:00Z",
            observed_at="2026-09-23T11:50:00Z",
            report_date="2026-09-01T00:00:00Z",
        )

        items = derive_texans_candidates(
            [game], [older, ancient, newest], {"provider": "sportradar"}, as_of=AS_OF
        )
        change_item = next(item for item in items if item.item_type == "availability_change")

        self.assertEqual(change_item.summary, "Player One: LIMITED → DNP")
        self.assertEqual(change_item.source_record_id, "change-1")

    def test_availability_is_scoped_to_nearest_relevant_game(self) -> None:
        next_game = self.texans_game(status="scheduled", scheduled_utc="2026-09-27T17:00:00Z")
        later_game = self.texans_game(
            provider_game_id="game-2", week=4, status="scheduled", scheduled_utc="2026-09-29T17:00:00Z"
        )
        later_change = self.change(change_key="week-4", week=4)

        items = derive_texans_candidates(
            [later_game, next_game], [later_change], {"provider": "sportradar"}, as_of=AS_OF
        )

        self.assertFalse(any(item.item_type == "availability_change" for item in items))
        self.assertEqual(
            [item.stable_id for item in items if item.item_type == "game"],
            ["texans:game:game-1"],
        )

    def test_ineligible_reappearance_still_supersedes_older_removal(self) -> None:
        game = self.texans_game(status="scheduled", scheduled_utc="2026-09-27T17:00:00Z")
        removal = self.change(
            change_key="removal",
            change_type="REMOVED_FROM_REPORT",
            old_value='{"practice_status":"LIMITED"}',
            new_value=None,
            provider_generated_at="2026-09-23T11:00:00Z",
            report_date=None,
            observed_at="2026-09-23T11:05:00Z",
        )
        reappearance = self.change(
            change_key="reappearance",
            change_type="NEW_REPORT",
            old_value=None,
            new_value='{"practice_status":"LIMITED"}',
            provider_generated_at="2026-09-23T11:30:00Z",
            report_date="2026-09-20T00:00:00Z",
            observed_at="2026-09-23T11:45:00Z",
        )

        items = derive_texans_candidates(
            [game], [removal, reappearance], {"provider": "sportradar"}, as_of=AS_OF
        )

        self.assertFalse(any(item.item_type == "availability_change" for item in items))

    def test_reappearance_blocks_all_older_availability_fields_but_keeps_newer_fields(self) -> None:
        game = self.texans_game(status="scheduled", scheduled_utc="2026-09-27T17:00:00Z")
        older_practice = self.change(
            change_key="older-practice",
            change_type="PRACTICE_STATUS_CHANGED",
            old_value="LIMITED",
            new_value="DNP",
            provider_generated_at="2026-09-23T10:00:00Z",
            report_date=None,
            observed_at="2026-09-23T10:05:00Z",
        )
        removal = self.change(
            change_key="removal",
            change_type="REMOVED_FROM_REPORT",
            old_value='{"practice_status":"DNP"}',
            new_value=None,
            provider_generated_at="2026-09-23T11:00:00Z",
            report_date=None,
            observed_at="2026-09-23T11:05:00Z",
        )
        reappearance = self.change(
            change_key="reappearance",
            change_type="NEW_REPORT",
            old_value=None,
            new_value='{"practice_status":"FULL"}',
            provider_generated_at="2026-09-23T11:30:00Z",
            report_date="2026-09-20T00:00:00Z",
            observed_at="2026-09-23T11:45:00Z",
        )

        without_newer_field = derive_texans_candidates(
            [game],
            [older_practice, removal, reappearance],
            {"provider": "sportradar"},
            as_of=AS_OF,
        )

        self.assertFalse(
            any(item.item_type == "availability_change" for item in without_newer_field)
        )

        newer_practice = self.change(
            change_key="newer-practice",
            change_type="PRACTICE_STATUS_CHANGED",
            old_value="FULL",
            new_value="LIMITED",
            provider_generated_at="2026-09-23T11:50:00Z",
            report_date="2026-09-23T00:00:00Z",
            observed_at="2026-09-23T11:55:00Z",
        )
        with_newer_field = derive_texans_candidates(
            [game],
            [older_practice, removal, reappearance, newer_practice],
            {"provider": "sportradar"},
            as_of=AS_OF,
        )
        change_item = next(
            item for item in with_newer_field if item.item_type == "availability_change"
        )

        self.assertEqual(change_item.summary, "Player One: FULL → LIMITED")
        self.assertEqual(change_item.source_record_id, "newer-practice")


class PersistedTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "sports.sqlite3"

    def seed_arsenal(self, *, completed_at: str = "2026-09-23T12:00:00Z") -> None:
        payload = json.loads((FIXTURES / "arsenal_matches.json").read_text(encoding="utf-8"))
        fixtures, ignored = normalize_matches(payload)
        from sports_briefing.storage import initialize_database

        initialize_database(self.database)
        persist_successful_fetch(
            self.database,
            request_url="https://api.football-data.org/v4/teams/57/matches",
            date_from="2026-09-01",
            date_to="2026-10-01",
            started_at="2026-09-23T11:59:00Z",
            completed_at=completed_at,
            http_status=200,
            raw_response=json.dumps(payload),
            received_count=len(payload["matches"]),
            fixtures=fixtures,
            filtered_unsupported_count=ignored,
        )

    def seed_texans(self, *, generated: str = "2026-09-23T11:30:00Z", observed: str = "2026-09-23T11:45:00Z") -> None:
        schedule_payload = json.loads((FIXTURES / "texans_schedule.json").read_text(encoding="utf-8"))
        injury_payload = json.loads((FIXTURES / "texans_injuries_limited.json").read_text(encoding="utf-8"))
        injury_payload["teams"][0]["players"][0]["injuries"][0]["status_date"] = "2026-09-23T00:00:00Z"
        schedule = normalize_schedule(schedule_payload)
        injuries = normalize_injuries(injury_payload)
        initialize_nfl_database(self.database)
        persist_texans_fetch(
            self.database,
            schedule=schedule,
            injuries=injuries,
            schedule_url="https://example.test/schedule",
            injuries_url="https://example.test/injuries",
            schedule_generated_at=generated,
            injuries_generated_at=generated,
            schedule_raw=json.dumps(schedule_payload),
            injuries_raw=json.dumps(injury_payload),
            started_at="2026-09-23T11:44:00Z",
            completed_at=observed,
        )

    def test_mixed_persisted_state_ranks_imminent_arsenal_before_texans_change(self) -> None:
        self.seed_arsenal()
        self.seed_texans()

        timeline = build_home_timeline(
            self.database,
            as_of="2026-09-23T12:00:00Z",
            hide_results=True,
        )

        self.assertEqual(timeline["items"][0]["entity"]["id"], "arsenal")
        self.assertEqual(timeline["items"][0]["reason"], "starts_soon")
        self.assertEqual(timeline["items"][1]["entity"]["id"], "texans")
        self.assertEqual(timeline["items"][1]["reason"], "meaningful_status_change")
        self.assertEqual(timeline["unavailable_entities"], [])

    def test_old_or_unchanged_context_does_not_fill_the_timeline(self) -> None:
        self.seed_texans(generated="2026-09-01T10:00:00Z", observed="2026-09-01T10:05:00Z")

        timeline = build_home_timeline(
            self.database,
            as_of="2026-10-20T12:00:00Z",
        )

        self.assertEqual(timeline["items"], [])
        self.assertEqual(timeline["unavailable_entities"], ["arsenal"])

    def test_missing_texans_is_reported_separately_from_a_quiet_entity(self) -> None:
        self.seed_arsenal()

        timeline = build_home_timeline(
            self.database,
            as_of="2026-09-23T12:00:00Z",
        )

        self.assertEqual(timeline["unavailable_entities"], ["texans"])

    def test_api_is_spoiler_safe_and_excludes_raw_provider_payloads(self) -> None:
        self.seed_arsenal(completed_at="2026-09-14T12:00:00Z")

        response = TestClient(create_app(self.database)).get(
            "/timeline?as_of=2026-09-14T12:00:00Z"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        serialized = json.dumps(body).lower()
        self.assertNotIn("raw", serialized)
        for forbidden in ('"score"', '"winner"', '"result"'):
            self.assertNotIn(forbidden, serialized)
        recent = next(item for item in body["items"] if item["reason"] == "recent_result")
        self.assertTrue(recent["result_hidden"])

    def test_api_can_explicitly_reveal_supported_arsenal_result(self) -> None:
        self.seed_arsenal(completed_at="2026-09-14T12:00:00Z")

        response = TestClient(create_app(self.database)).get(
            "/timeline?as_of=2026-09-14T12:00:00Z&hide_results=false"
        )

        self.assertEqual(response.status_code, 200)
        recent = next(item for item in response.json()["items"] if item["reason"] == "recent_result")
        self.assertEqual(recent["result"]["winner"], "HOME_TEAM")
        self.assertEqual(recent["result"]["full_time"], {"home": 3, "away": 0})

    def test_identical_texans_refresh_does_not_create_fresh_change(self) -> None:
        self.seed_texans()
        self.seed_texans(observed="2026-09-26T12:00:00Z")

        timeline = build_home_timeline(self.database, as_of="2026-09-26T12:00:00Z")

        self.assertNotIn("meaningful_status_change", [item["reason"] for item in timeline["items"]])

    def test_malformed_api_as_of_is_a_client_error(self) -> None:
        response = TestClient(create_app(self.database)).get("/timeline?as_of=not-a-timestamp")

        self.assertEqual(response.status_code, 422)

    def test_cli_labels_invalid_timeline_evaluation_as_timeline_failure(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["timeline", "--db", str(self.database), "--as-of", "not-a-timestamp"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("timeline failure:", stderr.getvalue())

    def test_cli_returns_the_same_persisted_timeline_contract(self) -> None:
        self.seed_arsenal()
        stdout, stderr = io.StringIO(), io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "timeline", "--db", str(self.database), "--as-of", "2026-09-23T12:00:00Z"
            ])

        self.assertEqual(code, 0, stderr.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["items"][0]["reason"], "starts_soon")
        self.assertEqual(output["unavailable_entities"], ["texans"])


if __name__ == "__main__":
    unittest.main()

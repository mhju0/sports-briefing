from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sports_briefing.arsenal_timeline import load_arsenal_timeline_candidates
from sports_briefing.football_data import normalize_matches
from sports_briefing.storage import initialize_database, persist_successful_fetch
from sports_briefing.synthesis import (
    SynthesisError,
    SynthesisInput,
    SynthesisProfile,
    apply_cached_summaries,
    build_synthesis_input,
    generate_cached_summary,
    verify_synthesis,
)
from sports_briefing.timeline import TimelineCandidate, TimelineTier, _parse_timestamp, build_home_timeline


FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-09-14T12:00:00Z"
PROFILE = SynthesisProfile(model_id="fake-model-1", prompt_version="summary-v1")
CREATED_AT = "2026-09-14T11:00:00Z"


def output(*sentences: tuple[str, list[str]]) -> str:
    return json.dumps({"sentences": [{"text": text, "evidence_ids": ids} for text, ids in sentences]})


class FakeModel:
    def __init__(self, raw: str | None = None, *, error: Exception | None = None) -> None:
        self.raw = raw
        self.error = error
        self.inputs: list[SynthesisInput] = []

    def generate(self, synthesis_input: SynthesisInput) -> str:
        self.inputs.append(synthesis_input)
        if self.error is not None:
            raise self.error
        assert self.raw is not None
        return self.raw


def texans_game(**changes: object) -> TimelineCandidate:
    base = TimelineCandidate(
        stable_id="texans:game:g1",
        entity_id="texans",
        entity_name="Houston Texans",
        sport="nfl",
        item_type="game",
        event_state="PRE_GAME",
        tier=TimelineTier.IMMINENT,
        title="Texans' next game",
        summary="Houston Texans at Jacksonville Jaguars",
        event_time="2026-09-14T17:00:00Z",
        change_time=None,
        competition=None,
        source_provider="sportradar",
        source_attribution="Sportradar NFL",
        source_generated_at="2026-09-14T10:00:00Z",
        source_observed_at="2026-09-14T10:05:00Z",
        source_record_id="g1",
    )
    return replace(base, **changes)


def news_topic(summary: str) -> TimelineCandidate:
    return texans_game(
        stable_id="news:texans:placed_on_ir:p1",
        item_type="official_development",
        event_state="ROSTER_CHANGE",
        tier=TimelineTier.MEANINGFUL_CHANGE,
        title="Texans roster development",
        summary=summary,
        event_time=None,
        change_time="2026-09-14T09:00:00Z",
    )


GAME_OUTPUT = output(("The Texans visit the Jaguars next.", ["baseline_summary", "entity_name"]))


class SynthesisDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "sports.sqlite3"

    def seed_arsenal(self) -> None:
        payload = json.loads((FIXTURES / "arsenal_matches.json").read_text(encoding="utf-8"))
        fixtures, ignored = normalize_matches(payload)
        initialize_database(self.database)
        persist_successful_fetch(
            self.database,
            request_url="https://api.football-data.org/v4/teams/57/matches",
            date_from="2026-09-01",
            date_to="2026-10-01",
            started_at="2026-09-23T11:59:00Z",
            completed_at="2026-09-23T12:00:00Z",
            http_status=200,
            raw_response=json.dumps(payload),
            received_count=len(payload["matches"]),
            fixtures=fixtures,
            filtered_unsupported_count=ignored,
        )

    def generate(
        self,
        candidate: TimelineCandidate,
        raw: str = GAME_OUTPUT,
        *,
        hide_results: bool = True,
        profile: SynthesisProfile = PROFILE,
    ) -> str | None:
        return generate_cached_summary(
            self.database,
            candidate,
            hide_results=hide_results,
            profile=profile,
            model=FakeModel(raw),
            created_at=CREATED_AT,
        )

    def summaries(
        self,
        *candidates: TimelineCandidate,
        hide_results: bool = True,
        profile: SynthesisProfile = PROFILE,
    ) -> list[str]:
        applied = apply_cached_summaries(
            self.database, candidates, hide_results=hide_results, profile=profile
        )
        return [item.summary for item in applied]

    def rows(self) -> int:
        with sqlite3.connect(self.database) as connection:
            return connection.execute("SELECT COUNT(*) FROM summary_syntheses").fetchone()[0]


class RequestPathTests(SynthesisDatabaseTest):
    def test_cache_miss_and_missing_cache_table_keep_template(self) -> None:
        self.seed_arsenal()
        template = build_home_timeline(self.database, as_of=AS_OF)

        self.assertEqual(build_home_timeline(self.database, as_of=AS_OF, synthesis=PROFILE), template)
        self.assertEqual(self.summaries(texans_game()), ["Houston Texans at Jacksonville Jaguars"])
        missing = Path(self.temp.name) / "absent.sqlite3"
        self.assertEqual(
            apply_cached_summaries(missing, [texans_game()], hide_results=True, profile=PROFILE),
            [texans_game()],
        )

    def test_valid_cached_summary_replaces_only_the_summary(self) -> None:
        self.seed_arsenal()
        for hide_results in (True, False):
            template = build_home_timeline(self.database, as_of=AS_OF, hide_results=hide_results)
            candidate_id = template["items"][0]["id"]
            candidate = next(
                item
                for item in load_arsenal_timeline_candidates(
                    self.database, _parse_timestamp(AS_OF, "as of"), hide_results=hide_results
                )
                if item.stable_id == candidate_id
            )
            prose = "Arsenal hosted Nottingham Forest in the Premier League."
            accepted = self.generate(
                candidate,
                output((prose, ["baseline_summary", "competition"])),
                hide_results=hide_results,
            )
            self.assertEqual(accepted, prose)

            generated = build_home_timeline(
                self.database, as_of=AS_OF, hide_results=hide_results, synthesis=PROFILE
            )

            self.assertEqual(generated["items"][0]["summary"], prose)
            for before, after in zip(template["items"], generated["items"], strict=True):
                self.assertEqual({**before, "summary": None}, {**after, "summary": None})
            self.assertEqual(
                [(item["id"], item["tier"]) for item in generated["items"]],
                [(item["id"], item["tier"]) for item in template["items"]],
            )
            # Without a profile the serving path ignores the cache entirely.
            self.assertEqual(
                build_home_timeline(self.database, as_of=AS_OF, hide_results=hide_results), template
            )

    def test_cached_prose_cannot_change_selection_or_per_entity_cap(self) -> None:
        candidates = [
            texans_game(stable_id=f"texans:game:g{index}", source_record_id=f"g{index}")
            for index in range(3)
        ]
        for candidate in candidates:
            self.generate(candidate)

        applied = apply_cached_summaries(
            self.database, candidates[:2], hide_results=True, profile=PROFILE
        )

        self.assertEqual([item.stable_id for item in applied], ["texans:game:g0", "texans:game:g1"])
        self.assertEqual(
            [replace(item, summary="") for item in applied],
            [replace(item, summary="") for item in candidates[:2]],
        )

    def test_corrupt_entry_falls_back_for_that_candidate_only(self) -> None:
        first = texans_game(stable_id="texans:game:a", source_record_id="a")
        second = texans_game(stable_id="texans:game:b", source_record_id="b")
        self.generate(first)
        self.generate(second)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "UPDATE summary_syntheses SET output_json = ? WHERE stable_id = ?",
                ('{"sentences": "not a list"}', "texans:game:a"),
            )

        self.assertEqual(
            self.summaries(first, second),
            ["Houston Texans at Jacksonville Jaguars", "The Texans visit the Jaguars next."],
        )


class GenerationTests(SynthesisDatabaseTest):
    def test_rejected_outputs_write_nothing_and_keep_existing_entry(self) -> None:
        candidate = texans_game()
        self.generate(candidate)
        rejected = {
            "not json": "The Texans play.",
            "wrong shape": json.dumps({"text": "The Texans play.", "evidence_ids": ["title"]}),
            "extra field": json.dumps({"sentences": [], "importance": "high"}),
            "unknown evidence": output(("The Texans play.", ["injury_report"])),
            "no evidence": output(("The Texans play.", [])),
            "empty text": output(("  ", ["title"])),
            "three sentences": output(*[("The Texans play.", ["title"])] * 3),
            "too long": output(("word " * 80, ["title"])),
            "invented number": output(("The Texans play at 3pm.", ["event_time"])),
        }
        for label, raw in rejected.items():
            with self.subTest(label):
                self.assertIsNone(self.generate(candidate, raw))

        self.assertEqual(self.rows(), 1)
        self.assertEqual(self.summaries(candidate), ["The Texans visit the Jaguars next."])

    def test_model_failure_is_isolated_and_leaves_template(self) -> None:
        with self.assertLogs("sports_briefing.synthesis", "ERROR"):
            accepted = generate_cached_summary(
                self.database,
                texans_game(),
                hide_results=True,
                profile=PROFILE,
                model=FakeModel(error=TimeoutError("model timed out")),
                created_at=CREATED_AT,
            )
        self.assertIsNone(accepted)
        self.assertFalse(self.database.exists())
        self.assertEqual(self.summaries(texans_game()), ["Houston Texans at Jacksonville Jaguars"])

    def test_synthetic_news_disclosure_must_be_kept(self) -> None:
        candidate = news_topic("Synthetic example: Pat Doe was placed on Reserve/Injured on 2026-09-13.")

        dropped = output(("Pat Doe went on injured reserve on 2026-09-13.", ["baseline_summary"]))
        kept = output(("Synthetic example: Pat Doe went on injured reserve on 2026-09-13.", ["baseline_summary"]))

        self.assertIsNone(self.generate(candidate, dropped))
        self.assertIsNotNone(self.generate(candidate, kept))


class SpoilerTests(SynthesisDatabaseTest):
    def arsenal_result(self, *, hide_results: bool) -> TimelineCandidate:
        return TimelineCandidate(
            stable_id="arsenal:match:5001",
            entity_id="arsenal",
            entity_name="Arsenal",
            sport="football",
            item_type="match",
            event_state="POST_GAME",
            tier=TimelineTier.RECENT_RESULT,
            title="Arsenal's recent result",
            summary="Arsenal FC vs Nottingham Forest FC" + (". Result hidden." if hide_results else ""),
            event_time="2026-09-13T15:30:00Z",
            change_time=None,
            competition={"code": "PL", "name": "Premier League"},
            source_provider="football-data.org",
            source_attribution="Football-Data.org",
            source_generated_at="2026-09-13T17:40:00Z",
            source_observed_at="2026-09-14T10:00:00Z",
            source_record_id="5001",
            result_hidden=hide_results,
            result=None if hide_results else {
                "full_time": {"home": 3, "away": 0}, "winner": "HOME_TEAM", "duration": "REGULAR"
            },
        )

    def test_hidden_mode_model_input_excludes_result_evidence(self) -> None:
        shown = build_synthesis_input(self.arsenal_result(hide_results=False), hide_results=False, language="en")
        hidden = build_synthesis_input(self.arsenal_result(hide_results=True), hide_results=True, language="en")
        # Even a candidate that still carries a result is filtered in hidden mode.
        leaky = build_synthesis_input(self.arsenal_result(hide_results=False), hide_results=True, language="en")

        self.assertIn("result", dict(shown.evidence))
        for synthesis_input in (hidden, leaky):
            evidence = dict(synthesis_input.evidence)
            self.assertNotIn("result", evidence)
            self.assertNotIn("HOME_TEAM", json.dumps(evidence))
            self.assertEqual(synthesis_input.spoiler_mode, "hide_results")

        model = FakeModel(GAME_OUTPUT)
        generate_cached_summary(
            self.database,
            self.arsenal_result(hide_results=True),
            hide_results=True,
            profile=PROFILE,
            model=model,
            created_at=CREATED_AT,
        )
        self.assertNotIn("result", dict(model.inputs[0].evidence))

    def test_hidden_result_leakage_is_rejected(self) -> None:
        hidden = build_synthesis_input(self.arsenal_result(hide_results=True), hide_results=True, language="en")
        shown = build_synthesis_input(self.arsenal_result(hide_results=False), hide_results=False, language="en")
        leaks = [
            "Arsenal won 3-0 against Nottingham Forest.",
            "Arsenal beat Nottingham Forest in the Premier League.",
            "Arsenal FC vs Nottingham Forest FC ended in a draw.",
        ]
        for text in leaks:
            with self.subTest(text):
                with self.assertRaises(SynthesisError):
                    verify_synthesis(output((text, ["baseline_summary"])), hidden)

        self.assertEqual(
            verify_synthesis(output((leaks[0], ["result"])), shown),
            "Arsenal won 3-0 against Nottingham Forest.",
        )
        self.assertEqual(
            verify_synthesis(output(("Arsenal hosted Nottingham Forest; result hidden.", ["baseline_summary"])), hidden),
            "Arsenal hosted Nottingham Forest; result hidden.",
        )

    def test_hide_and_show_modes_never_share_entries(self) -> None:
        # Identical visible evidence in both modes: only the spoiler key separates them.
        candidate = texans_game()
        self.generate(candidate, hide_results=False)

        self.assertEqual(self.summaries(candidate, hide_results=True), [candidate.summary])
        self.assertEqual(
            self.summaries(candidate, hide_results=False), ["The Texans visit the Jaguars next."]
        )


class CacheIdentityTests(SynthesisDatabaseTest):
    def test_changed_synthesis_evidence_invalidates_entry(self) -> None:
        before = news_topic("Pat Doe was placed on Reserve/Injured on 2026-09-13.")
        after = news_topic(
            "Pat Doe was placed on Reserve/Injured on 2026-09-13. The placement was designated for return."
        )
        self.generate(before, output(("Pat Doe went on injured reserve on 2026-09-13.", ["baseline_summary"])))

        self.assertEqual(self.summaries(before), ["Pat Doe went on injured reserve on 2026-09-13."])
        self.assertEqual(self.summaries(after), [after.summary])
        self.assertEqual(self.summaries(texans_game()), [texans_game().summary])
        moved = texans_game(event_time="2026-09-15T17:00:00Z")
        self.generate(texans_game())
        self.assertEqual(self.summaries(moved), [moved.summary])

    def test_refetch_metadata_does_not_invalidate_entry(self) -> None:
        self.generate(texans_game())
        refetched = texans_game(
            source_observed_at="2026-09-14T11:55:00Z",
            source_generated_at="2026-09-14T11:50:00Z",
        )

        self.assertEqual(self.summaries(refetched), ["The Texans visit the Jaguars next."])

    def test_prompt_model_and_language_changes_invalidate_entry(self) -> None:
        candidate = texans_game()
        self.generate(candidate)
        variants = {
            "prompt": SynthesisProfile(model_id="fake-model-1", prompt_version="summary-v2"),
            "model": SynthesisProfile(model_id="fake-model-2", prompt_version="summary-v1"),
            "language": SynthesisProfile(model_id="fake-model-1", prompt_version="summary-v1", language="ko"),
        }
        for label, profile in variants.items():
            with self.subTest(label):
                self.assertEqual(self.summaries(candidate, profile=profile), [candidate.summary])
        self.assertEqual(self.summaries(candidate), ["The Texans visit the Jaguars next."])


if __name__ == "__main__":
    unittest.main()

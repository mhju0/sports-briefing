from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.cli import main
from sports_briefing.news.evidence import EvidenceError, load_batch, normalize_batch
from sports_briefing.news.storage import (
    inspect_news_state, initialize_news_database, load_news_topics, persist_reviewed_batch,
)
from sports_briefing.news.timeline import derive_news_candidates
from sports_briefing.nfl.storage import initialize_nfl_database
from sports_briefing.storage import StorageError
from sports_briefing.timeline import TimelineTier, build_home_timeline, rank_candidates


FIXTURES = Path(__file__).parent / "fixtures" / "news"
T1 = "2026-09-25T11:00:00Z"
T2 = "2026-09-25T13:00:00Z"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ReviewedTexansEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "news.sqlite3"

    def import_value(self, value: dict, at: str = T1) -> dict[str, int]:
        return persist_reviewed_batch(self.db, normalize_batch(value), observed_at=at)

    def test_two_documents_one_topic_exact_content_duplicate_and_noop_rerun(self) -> None:
        value = fixture("synthetic-placement.json")
        first = self.import_value(value)
        state = inspect_news_state(self.db)
        self.assertEqual(first, {
            "documents_inserted": 2, "documents_no_change": 0, "exact_content_duplicates": 1,
            "topics_inserted": 1, "topics_updated": 0, "topics_no_change": 1,
            "evidence_links_inserted": 2,
        })
        self.assertEqual((state["source_count"], state["document_count"], state["topic_count"], state["evidence_link_count"]), (1, 2, 1, 2))
        self.assertEqual(state["sources"][0]["name"], "Synthetic Texans evidence")
        self.assertEqual(state["documents"][0]["published_at"], "2026-09-25T09:00:00Z")
        self.assertEqual(state["documents"][0]["first_observed_at"], T1)
        self.assertEqual(state["documents"][1]["duplicate_of_document_id"], state["documents"][0]["id"])
        self.assertEqual(state["topics"][0]["revision"], 1)
        self.assertEqual(state["topics"][0]["meaningful_changed_at"], T1)
        self.assertEqual(state["topics"][0]["material_published_at"], "2026-09-25T09:00:00Z")
        self.assertEqual(self.import_value(value, T2)["documents_no_change"], 2)
        self.assertEqual(inspect_news_state(self.db), state)

    def test_reversed_batch_order_has_same_topic_identity_and_revision(self) -> None:
        value = fixture("synthetic-placement.json")
        self.import_value(value)
        original = inspect_news_state(self.db)
        second_db = Path(self.directory.name) / "reversed.sqlite3"
        persist_reviewed_batch(second_db, normalize_batch({**value, "documents": list(reversed(value["documents"]))}), observed_at=T1)
        reversed_state = inspect_news_state(second_db)
        self.assertEqual(reversed_state["topics"], original["topics"])
        self.assertEqual(reversed_state["documents"], original["documents"])

    def test_reversed_first_and_followup_batch_has_one_topic_and_one_revision_change(self) -> None:
        base = fixture("synthetic-placement.json")["documents"][0]
        followup = fixture("synthetic-followup.json")["documents"][0]
        combined = {"evidence_mode": "synthetic", "documents": [followup, base]}
        outcomes = self.import_value(combined, T2)
        self.assertEqual((outcomes["topics_inserted"], outcomes["topics_updated"]), (1, 1))
        self.assertEqual(inspect_news_state(self.db)["topics"][0]["revision"], 2)

    def test_followup_changes_topic_once_and_repeat_does_not_freshen_it(self) -> None:
        self.import_value(fixture("synthetic-placement.json"))
        followup = fixture("synthetic-followup.json")
        outcome = self.import_value(followup, T2)
        self.assertEqual(outcome["topics_updated"], 1)
        topic = inspect_news_state(self.db)["topics"][0]
        self.assertEqual((topic["revision"], topic["meaningful_changed_at"], topic["material_published_at"]),
                         (2, T2, "2026-09-25T12:00:00Z"))
        self.assertEqual(topic["placement_qualifier"], "designated_for_return")
        links = inspect_news_state(self.db)["evidence_links"]
        self.assertEqual(sum(link["contributed_placement"] for link in links), 1)
        self.assertEqual(sum(link["contributed_qualifier"] for link in links), 1)
        self.assertEqual(self.import_value(followup, "2026-09-25T14:00:00Z")["topics_updated"], 0)
        self.assertEqual(inspect_news_state(self.db)["topics"][0], topic)
        self.assertEqual(len(load_news_topics(self.db)), 1)

    def test_later_repeating_publication_does_not_reopen_freshness(self) -> None:
        self.import_value(fixture("synthetic-placement.json"))
        repeat = deepcopy(fixture("synthetic-placement.json"))
        repeat["documents"] = [repeat["documents"][1]]
        repeat["documents"][0]["canonical_url"] = "https://example.test/news/later-repeat"
        repeat["documents"][0]["external_id"] = "synthetic-later-repeat"
        repeat["documents"][0]["published_at"] = "2026-09-27T10:00:00Z"
        self.import_value(repeat, "2026-09-27T11:00:00Z")
        topic = inspect_news_state(self.db)["topics"][0]
        self.assertEqual(topic["meaningful_changed_at"], T1)
        self.assertEqual(topic["material_published_at"], "2026-09-25T09:00:00Z")
        self.assertEqual(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 27, 12, tzinfo=timezone.utc)), [])

    def test_old_discovered_today_or_missing_publication_has_no_candidate(self) -> None:
        self.import_value(fixture("synthetic-historical.json"))
        topic = inspect_news_state(self.db)["topics"][0]
        self.assertEqual(topic["first_observed_at"], T1)
        self.assertEqual(topic["material_published_at"], "2026-08-01T09:00:00Z")
        self.assertEqual(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 25, 12, tzinfo=timezone.utc)), [])
        undated = deepcopy(fixture("synthetic-placement.json"))
        undated["documents"] = [undated["documents"][0]]
        undated["documents"][0]["published_at"] = None
        undated["documents"][0]["canonical_url"] = "https://example.test/news/undated"
        undated["documents"][0]["external_id"] = "undated"
        undated["documents"][0]["subject_key"] = "player:undated"
        undated["documents"][0]["subject_name"] = "Undated Sample"
        self.import_value(undated)
        self.assertEqual(len(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 25, 12, tzinfo=timezone.utc))), 0)

    def test_changed_existing_url_and_conflicting_duplicate_fail_atomically(self) -> None:
        self.import_value(fixture("synthetic-placement.json"))
        before = inspect_news_state(self.db)
        altered = fixture("synthetic-placement.json")
        altered["documents"][0]["text"] += " Updated copy."
        with self.assertRaisesRegex(StorageError, "changed or conflicting"):
            self.import_value(altered, T2)
        self.assertEqual(inspect_news_state(self.db), before)
        conflicting = deepcopy(fixture("synthetic-placement.json"))
        conflicting["documents"] = [conflicting["documents"][0]]
        conflicting["documents"][0]["canonical_url"] = "https://example.test/news/conflicting-fact"
        conflicting["documents"][0]["external_id"] = "conflicting-fact"
        conflicting["documents"][0]["placement_qualifier"] = "designated_for_return"
        with self.assertRaisesRegex(StorageError, "identical content"):
            self.import_value(conflicting, T2)
        self.assertEqual(inspect_news_state(self.db), before)

    def test_future_publication_or_observation_rollback_and_recovery(self) -> None:
        self.import_value(fixture("synthetic-placement.json"))
        before = inspect_news_state(self.db)
        followup = fixture("synthetic-followup.json")
        with self.assertRaisesRegex(StorageError, "publication time"):
            self.import_value(followup, T1)
        self.assertEqual(inspect_news_state(self.db), before)
        earlier = deepcopy(followup)
        earlier["documents"][0]["published_at"] = "2026-09-25T10:00:00Z"
        with self.assertRaisesRegex(StorageError, "out-of-order"):
            self.import_value(earlier, "2026-09-25T10:30:00Z")
        self.assertEqual(inspect_news_state(self.db), before)
        self.assertEqual(self.import_value(followup, T2)["topics_updated"], 1)

    def test_strict_identity_authorization_and_bounded_input(self) -> None:
        value = fixture("synthetic-placement.json")
        bad = deepcopy(value)
        bad["documents"][0]["canonical_url"] += "?story=other"
        with self.assertRaises(EvidenceError):
            normalize_batch(bad)
        bad = deepcopy(value)
        bad["documents"][0]["action"] = "released"
        with self.assertRaises(EvidenceError):
            normalize_batch(bad)
        bad = deepcopy(value)
        bad["evidence_mode"] = "reviewed"
        with self.assertRaisesRegex(EvidenceError, "source_use_authorized"):
            normalize_batch(bad)
        bad["source_use_authorized"] = True
        with self.assertRaises(EvidenceError):
            normalize_batch(bad)
        huge = Path(self.directory.name) / "huge.json"
        huge.write_bytes(b" " * (512 * 1024 + 1))
        with self.assertRaises(EvidenceError):
            load_batch(str(huge))

    def test_news_does_not_mutate_structured_nfl_state(self) -> None:
        initialize_nfl_database(self.db)
        with sqlite3.connect(self.db) as connection:
            connection.execute("""INSERT INTO nfl_source_revisions
                (provider, endpoint_key, provider_generated_at, semantic_hash, report_date, accepted_at, source_url)
                VALUES ('sportradar', 'test', '2026-09-25T08:00:00Z', 'hash', NULL,
                    '2026-09-25T08:00:00Z', 'https://example.test/structured')""")
            before = {name: connection.execute(f"SELECT * FROM {name}").fetchall()
                      for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'nfl_%'")}
        self.import_value(fixture("synthetic-placement.json"))
        self.import_value(fixture("synthetic-followup.json"), T2)
        with sqlite3.connect(self.db) as connection:
            after = {name: connection.execute(f"SELECT * FROM {name}").fetchall() for name in before}
        self.assertEqual(after, before)

    def test_timeline_is_sparse_stable_and_uses_existing_ranker(self) -> None:
        empty = build_home_timeline(self.db, as_of="2026-09-25T11:30:00Z")
        self.assertEqual(empty["items"], [])
        self.import_value(fixture("synthetic-placement.json"))
        first = build_home_timeline(self.db, as_of="2026-09-25T11:30:00Z")
        self.assertEqual(first, build_home_timeline(self.db, as_of="2026-09-25T11:30:00Z"))
        self.assertEqual(len(first["items"]), 1)
        item = first["items"][0]
        self.assertEqual((item["entity"]["id"], item["tier"], item["change_time"]), ("texans", "meaningful_change", T1))
        self.assertEqual(item["source"]["generated_at"], "2026-09-25T09:00:00Z")
        self.assertEqual(item["source"]["observed_at"], T1)
        self.assertIn("synthetic", item["title"])
        self.assertNotIn("texans", first["unavailable_entities"])
        self.assertEqual(build_home_timeline(self.db, as_of="2026-09-27T12:00:00Z")["items"], [])
        self.assertEqual(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc))[0].tier, TimelineTier.MEANINGFUL_CHANGE)

    def test_one_news_candidate_even_with_multiple_topics(self) -> None:
        value = fixture("synthetic-placement.json")
        second = deepcopy(value["documents"][0])
        second.update(canonical_url="https://example.test/news/other-player", external_id="other-player",
                      text="Other Player was placed on Reserve/Injured.", subject_key="player:other-player",
                      subject_name="Other Player", published_at="2026-09-25T10:00:00Z")
        value["documents"].append(second)
        self.import_value(value)
        self.assertEqual(inspect_news_state(self.db)["topic_count"], 2)
        self.assertEqual(len(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc))), 1)

    def test_news_candidate_uses_existing_cross_sport_precedence(self) -> None:
        self.import_value(fixture("synthetic-placement.json"))
        as_of = datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc)
        news = derive_news_candidates(load_news_topics(self.db), as_of=as_of)[0]
        live = replace(news, stable_id="arsenal:live", entity_id="arsenal", tier=TimelineTier.LIVE,
                       event_time="2026-09-25T11:00:00Z", change_time=None)
        imminent = replace(news, stable_id="arsenal:imminent", entity_id="arsenal", tier=TimelineTier.IMMINENT,
                           event_time="2026-09-25T12:00:00Z", change_time=None)
        recent = replace(news, stable_id="texans:recent", tier=TimelineTier.RECENT_RESULT,
                         event_time="2026-09-25T10:00:00Z", change_time=None)
        self.assertEqual([item.stable_id for item in rank_candidates([recent, news, imminent, live], as_of=as_of)],
                         ["arsenal:live", "arsenal:imminent", news.stable_id, "texans:recent"])

    def test_cli_http_and_separate_process_readback(self) -> None:
        output = io.StringIO()
        with patch("sports_briefing.cli._now", return_value=T1), redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = main(["import-news", "texans", "--input", str(FIXTURES / "synthetic-placement.json"), "--db", str(self.db)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["outcomes"]["documents_inserted"], 2)
        read = subprocess.run(
            [sys.executable, "-m", "sports_briefing", "inspect", "texans-news", "--db", str(self.db)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(read.stdout)["evidence_link_count"], 2)
        response = TestClient(create_app(self.db)).get("/timeline?as_of=2026-09-25T11:30:00Z")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["result"] if "result" in response.json()["items"][0] else None, None)


if __name__ == "__main__":
    unittest.main()

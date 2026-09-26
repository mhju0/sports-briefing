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
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from urllib.error import HTTPError

from sports_briefing.cli import main
from sports_briefing.news.evidence import EvidenceBatch, EvidenceError
from sports_briefing.news.storage import NEWS_SCHEMA, initialize_news_database, inspect_news_state, load_news_topics, persist_reviewed_batch
from sports_briefing.news.timeline import derive_news_candidates
from sports_briefing.news.wikinews import API_URL, BACKGROUND_SHA256, MAIN_SHA256, fetch_article, normalize_article
from sports_briefing.nfl.storage import initialize_nfl_database
from sports_briefing.storage import StorageError


FIXTURE = Path(__file__).parent / "fixtures/news/wikinews-xhaka-2790899.json"
BACKGROUND_FIXTURE = Path(__file__).parent / "fixtures/news/wikinews-background-2793763.json"
OBSERVED = "2026-09-26T10:00:00Z"


def payload() -> dict:
    first = json.loads(FIXTURE.read_text(encoding="utf-8"))
    second = json.loads(BACKGROUND_FIXTURE.read_text(encoding="utf-8"))
    first["query"]["pages"].extend(second["query"]["pages"])
    return first


def legacy_schema() -> str:
    schema = NEWS_SCHEMA.replace("    published_date TEXT,\n    source_metadata_json TEXT,\n", "")
    schema = schema.replace("entity_id TEXT NOT NULL,", "entity_id TEXT NOT NULL CHECK(entity_id = 'texans'),")
    schema = schema.replace("action TEXT NOT NULL,", "action TEXT NOT NULL CHECK(action = 'placed_on_ir'),")
    return schema.replace("    evidence_mode TEXT NOT NULL,\n    CHECK((entity_id = 'texans' AND action = 'placed_on_ir') OR\n          (entity_id = 'arsenal' AND action = 'signing_announced'))", "    evidence_mode TEXT NOT NULL")


class WikinewsProofTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "proof.sqlite3"

    def test_reviewed_binding_and_date_only(self) -> None:
        batch = normalize_article(payload())
        self.assertEqual(len(batch.documents), 2)
        document = batch.documents[0]
        self.assertEqual((batch.source, batch.mode, document.entity_id, document.action),
                         ("wikinews", "live-reviewed", "arsenal", "signing_announced"))
        self.assertEqual((document.published_at, document.published_date, document.effective_date),
                         (None, "2016-05-25", "2016-05-25"))
        metadata = json.loads(document.source_metadata_json)
        self.assertEqual((metadata["page_id"], metadata["revision_id"], metadata["main_slot_sha256"]),
                         (2790899, 5024729, MAIN_SHA256))
        self.assertEqual(metadata["license"], "CC BY 2.5")
        self.assertIn("oldid=5024729", metadata["revision_url"])
        background = batch.documents[1]
        self.assertEqual((background.published_at, background.published_date, background.effective_date),
                         (None, "2016-07-06", "2016-05-25"))
        self.assertEqual(background.topic_key, document.topic_key)
        self.assertNotEqual(background.content_hash, document.content_hash)
        background_metadata = json.loads(background.source_metadata_json)
        self.assertEqual((background_metadata["page_id"], background_metadata["revision_id"],
                          background_metadata["main_slot_sha256"]), (2793763, 4813539, BACKGROUND_SHA256))
        self.assertEqual(background_metadata["normalization_scope"], "background_confirmation_of_existing_xhaka_signing")
        self.assertIn("this page does not establish the announcement date", background_metadata["event_date_basis"])

    def test_identity_revision_hash_publication_and_license_mismatches_fail(self) -> None:
        paths = [
            ("pageid", lambda p: p.update(pageid=1)),
            ("revision", lambda p: p["revisions"][0].update(revid=1)),
            ("title", lambda p: p.update(title="Another title")),
            ("canonical", lambda p: p.update(canonicalurl="https://en.wikinews.org/wiki/Other")),
            ("timestamp", lambda p: p["revisions"][0].update(timestamp="garbageZ")),
            ("hash", lambda p: p["revisions"][0]["slots"]["main"].update(content="changed")),
        ]
        for name, mutate in paths:
            with self.subTest(name=name):
                changed = payload()
                mutate(changed["query"]["pages"][0])
                with self.assertRaisesRegex(EvidenceError, "mismatch"):
                    normalize_article(changed)
        two_pages = payload()
        two_pages["query"]["pages"].append(deepcopy(two_pages["query"]["pages"][0]))
        with self.assertRaises(EvidenceError):
            normalize_article(two_pages)
        for name, change in [
            ("background revision", lambda p: p["revisions"][0].update(revid=1)),
            ("background hash", lambda p: p["revisions"][0]["slots"]["main"].update(content="changed")),
            ("background title", lambda p: p.update(title="Other")),
            ("background license", lambda p: p["revisions"][0]["slots"]["main"].update(content="{{date|July 6, 2016}}")),
        ]:
            with self.subTest(name=name):
                changed = payload()
                change(changed["query"]["pages"][1])
                with self.assertRaises(EvidenceError):
                    normalize_article(changed)
        missing = payload()
        missing["query"]["pages"].pop()
        with self.assertRaises(EvidenceError):
            normalize_article(missing)

    def test_bounded_http_and_cli_persistence_rerun_restart(self) -> None:
        raw = json.dumps(payload(), ensure_ascii=False).encode("utf-8")

        class Response:
            status = 200

            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, size): return raw[:size]

        with patch("sports_briefing.news.wikinews.urlopen", return_value=Response()) as opened:
            batch = fetch_article(timeout=3.0)
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, opened.call_args.kwargs["timeout"]), (API_URL, 3.0))
        self.assertEqual(request.get_header("User-agent") is not None, True)
        first = persist_reviewed_batch(self.db, batch, observed_at=OBSERVED)
        self.assertEqual((first["documents_inserted"], first["topics_inserted"], first["evidence_links_inserted"]), (2, 1, 2))
        state = inspect_news_state(self.db)
        self.assertEqual((state["document_count"], state["topic_count"], state["evidence_link_count"]), (2, 1, 2))
        self.assertEqual(state["sources"][0]["source_kind"], "community_reporting")
        self.assertEqual((state["documents"][0]["published_at"], state["documents"][0]["published_date"]),
                         (None, "2016-05-25"))
        self.assertEqual((state["topics"][0]["entity_id"], state["topics"][0]["action"]),
                         ("arsenal", "signing_announced"))
        self.assertEqual(persist_reviewed_batch(self.db, batch, observed_at=OBSERVED)["documents_no_change"], 2)
        self.assertEqual(inspect_news_state(self.db), state)
        self.assertEqual(load_news_topics(self.db)[0]["source_kind"], "community_reporting")
        self.assertEqual(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 26, tzinfo=timezone.utc)), [])

    def test_http_errors_and_oversize_fail_before_database(self) -> None:
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self, size): return b"x" * size

        with patch("sports_briefing.news.wikinews.urlopen", return_value=Response()):
            with self.assertRaisesRegex(EvidenceError, "64 KiB"):
                fetch_article()
        with patch("sports_briefing.news.wikinews.urlopen", side_effect=HTTPError(API_URL, 503, "Unavailable", {}, None)):
            with self.assertRaisesRegex(EvidenceError, "HTTP Error 503"):
                fetch_article()
        self.assertFalse(self.db.exists())

    def test_atomic_persistence_failure_and_future_date(self) -> None:
        batch = normalize_article(payload())
        with self.assertRaisesRegex(StorageError, "publication date"):
            persist_reviewed_batch(self.db, batch, observed_at="2016-05-24T23:59:59Z")
        self.assertEqual(inspect_news_state(self.db)["document_count"], 0)
        persist_reviewed_batch(self.db, batch, observed_at=OBSERVED)
        before = inspect_news_state(self.db)
        altered = deepcopy(batch.documents[0])
        changed = replace(altered, source_metadata_json="{}")
        with self.assertRaisesRegex(StorageError, "changed or conflicting"):
            persist_reviewed_batch(self.db, replace(batch, documents=(changed,)), observed_at=OBSERVED)
        self.assertEqual(inspect_news_state(self.db), before)

    def test_original_then_background_adds_only_evidence_link_and_survives_restart(self) -> None:
        batch = normalize_article(payload())
        original = EvidenceBatch(batch.mode, batch.documents[:1], batch.source)
        background = EvidenceBatch(batch.mode, batch.documents[1:], batch.source)
        first = persist_reviewed_batch(self.db, original, observed_at=OBSERVED)
        self.assertEqual((first["documents_inserted"], first["topics_inserted"]), (1, 1))
        initial = inspect_news_state(self.db)["topics"][0]
        second = persist_reviewed_batch(self.db, background, observed_at="2026-09-26T11:00:00Z")
        self.assertEqual((second["documents_inserted"], second["topics_no_change"], second["evidence_links_inserted"]),
                         (1, 1, 1))
        state = inspect_news_state(self.db)
        self.assertEqual((state["document_count"], state["topic_count"], state["evidence_link_count"]), (2, 1, 2))
        topic = state["topics"][0]
        for field in ("topic_key", "revision", "meaningful_changed_at", "material_document_id", "material_published_at"):
            self.assertEqual(topic[field], initial[field])
        self.assertEqual(topic["last_evidence_observed_at"], "2026-09-26T11:00:00Z")
        self.assertEqual([row["contributed_placement"] for row in state["evidence_links"]], [1, 0])
        self.assertEqual(persist_reviewed_batch(self.db, batch, observed_at="2026-09-26T11:00:00Z")["documents_no_change"], 2)
        self.assertEqual(inspect_news_state(self.db), state)
        restarted = subprocess.run(
            [sys.executable, "-m", "sports_briefing", "inspect", "news", "--db", str(self.db)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(restarted.stdout), state)
        self.assertEqual(derive_news_candidates(load_news_topics(self.db), as_of=datetime(2026, 9, 26, tzinfo=timezone.utc)), [])

    def test_reversed_api_pair_still_selects_original_as_material(self) -> None:
        reversed_payload = payload()
        reversed_payload["query"]["pages"].reverse()
        batch = normalize_article(reversed_payload)
        reversed_batch = replace(batch, documents=tuple(reversed(batch.documents)))
        persist_reviewed_batch(self.db, reversed_batch, observed_at=OBSERVED)
        state = inspect_news_state(self.db)
        self.assertEqual(state["topics"][0]["material_document_id"], state["documents"][0]["id"])
        self.assertEqual(state["documents"][0]["published_date"], "2016-05-25")
        self.assertEqual(state["topics"][0]["revision"], 1)

    def test_second_page_mismatch_rejects_whole_response_without_partial_write(self) -> None:
        changed = payload()
        changed["query"]["pages"][1]["revisions"][0]["slots"]["main"]["content"] = "changed"
        with self.assertRaises(EvidenceError):
            persist_reviewed_batch(self.db, normalize_article(changed), observed_at=OBSERVED)
        self.assertFalse(self.db.exists())

    def test_cli_and_structured_tables_remain_separate(self) -> None:
        initialize_nfl_database(self.db)
        with sqlite3.connect(self.db) as connection:
            connection.execute("""INSERT INTO nfl_source_revisions
                (provider, endpoint_key, provider_generated_at, semantic_hash, report_date, accepted_at, source_url)
                VALUES ('sportradar', 'test', '2026-09-25T08:00:00Z', 'hash', NULL,
                    '2026-09-25T08:00:00Z', 'https://example.test/structured')""")
            before = {name: connection.execute(f"SELECT * FROM {name}").fetchall()
                      for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'nfl_%'")}
        output = io.StringIO()
        with patch("sports_briefing.cli.fetch_article", return_value=normalize_article(payload())), \
             patch("sports_briefing.cli._now", return_value=OBSERVED), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["ingest-news", "wikinews-arsenal", "--db", str(self.db)]), 0)
        self.assertEqual(json.loads(output.getvalue())["outcomes"]["documents_inserted"], 2)
        with sqlite3.connect(self.db) as connection:
            after = {name: connection.execute(f"SELECT * FROM {name}").fetchall() for name in before}
        self.assertEqual(after, before)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["inspect", "news", "--db", str(self.db)]), 0)
        self.assertEqual(json.loads(output.getvalue())["document_count"], 2)

    def test_legacy_schema_migrates_without_losing_ids_links_or_qualifier(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.executescript(legacy_schema())
            connection.execute("INSERT INTO news_sources VALUES (7, 'houston-texans-official:synthetic', 'Synthetic Texans evidence', 'https://example.test', 'official', 'synthetic')")
            document = (7, "https://example.test/news/one", "one", "Sample", None, "2026-09-25T09:00:00Z", OBSERVED,
                        "hash", None, "texans:placed_on_ir:player:one:2026-09-25", "player:one", "One", "2026-09-25", "designated_for_return")
            connection.execute("INSERT INTO news_documents VALUES (11, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", document)
            connection.execute("INSERT INTO news_documents VALUES (12, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (7, "https://example.test/news/two", "two", "Sample two", None, "2026-09-25T10:00:00Z", OBSERVED,
                                "hash", 11, "texans:placed_on_ir:player:one:2026-09-25", "player:one", "One", "2026-09-25", "designated_for_return"))
            connection.execute("INSERT INTO news_topics VALUES (9, ?, 'texans', 'player:one', 'One', 'placed_on_ir', '2026-09-25', 'designated_for_return', ?, ?, ?, ?, 11, 2, 'synthetic')",
                               ("texans:placed_on_ir:player:one:2026-09-25", OBSERVED, OBSERVED, OBSERVED, "2026-09-25T09:00:00Z"))
            connection.execute("INSERT INTO news_topic_documents VALUES (9, 11, 1, 1)")
            connection.execute("INSERT INTO news_topic_documents VALUES (9, 12, 0, 0)")
        initialize_news_database(self.db)
        initialize_news_database(self.db)
        state = inspect_news_state(self.db)
        self.assertEqual([row["id"] for row in state["documents"]], [11, 12])
        self.assertEqual(state["documents"][1]["duplicate_of_document_id"], 11)
        self.assertEqual((state["topics"][0]["id"], state["topics"][0]["revision"], state["topics"][0]["placement_qualifier"]),
                         (9, 2, "designated_for_return"))
        self.assertEqual([row["document_id"] for row in state["evidence_links"]], [11, 12])
        self.assertIsNone(state["documents"][0]["published_date"])
        with sqlite3.connect(self.db) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        persist_reviewed_batch(self.db, normalize_article(payload()), observed_at=OBSERVED)
        self.assertEqual(inspect_news_state(self.db)["topic_count"], 2)

    def test_invalid_legacy_foreign_key_rolls_back_news_migration(self) -> None:
        with sqlite3.connect(self.db) as connection:
            connection.executescript(legacy_schema())
            connection.execute("INSERT INTO news_topic_documents VALUES (404, 405, 1, 0)")
        with self.assertRaisesRegex(StorageError, "foreign key check"):
            initialize_news_database(self.db)
        with sqlite3.connect(self.db) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(news_documents)")}
            topic_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'news_topics'").fetchone()[0]
            links = connection.execute("SELECT * FROM news_topic_documents").fetchall()
        self.assertNotIn("published_date", columns)
        self.assertNotIn("signing_announced", topic_sql)
        self.assertEqual(links, [(404, 405, 1, 0)])


if __name__ == "__main__":
    unittest.main()

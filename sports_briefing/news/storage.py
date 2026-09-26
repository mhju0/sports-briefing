from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from ..storage import StorageError, initialize_database
from .evidence import EvidenceBatch, ReviewedDocument


NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS news_sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    evidence_mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES news_sources(id),
    canonical_url TEXT NOT NULL UNIQUE,
    external_id TEXT,
    title TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    first_observed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    duplicate_of_document_id INTEGER REFERENCES news_documents(id),
    topic_key TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    placement_qualifier TEXT
);
CREATE TABLE IF NOT EXISTS news_topics (
    id INTEGER PRIMARY KEY,
    topic_key TEXT NOT NULL UNIQUE,
    entity_id TEXT NOT NULL CHECK(entity_id = 'texans'),
    subject_key TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action = 'placed_on_ir'),
    effective_date TEXT NOT NULL,
    placement_qualifier TEXT,
    first_observed_at TEXT NOT NULL,
    last_evidence_observed_at TEXT NOT NULL,
    meaningful_changed_at TEXT NOT NULL,
    material_published_at TEXT,
    material_document_id INTEGER NOT NULL REFERENCES news_documents(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    evidence_mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_topic_documents (
    topic_id INTEGER NOT NULL REFERENCES news_topics(id),
    document_id INTEGER NOT NULL UNIQUE REFERENCES news_documents(id),
    contributed_placement INTEGER NOT NULL CHECK(contributed_placement IN (0, 1)),
    contributed_qualifier INTEGER NOT NULL CHECK(contributed_qualifier IN (0, 1)),
    PRIMARY KEY(topic_id, document_id)
);
CREATE INDEX IF NOT EXISTS news_topics_entity_changed_idx
    ON news_topics(entity_id, meaningful_changed_at);
CREATE INDEX IF NOT EXISTS news_documents_hash_idx
    ON news_documents(source_id, content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS news_documents_external_id_idx
    ON news_documents(source_id, external_id) WHERE external_id IS NOT NULL;
"""


def initialize_news_database(path: Path) -> None:
    initialize_database(path)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(NEWS_SCHEMA)


def persist_reviewed_batch(path: Path, batch: EvidenceBatch, *, observed_at: str) -> dict[str, int]:
    observation = _parse_timestamp(observed_at, "news observation")
    stamp = _format_timestamp(observation)
    counts = {"documents_inserted": 0, "documents_no_change": 0, "exact_content_duplicates": 0,
              "topics_inserted": 0, "topics_updated": 0, "topics_no_change": 0,
              "evidence_links_inserted": 0}
    initialize_news_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            source_id = _source(connection, batch.mode)
            for document in sorted(batch.documents, key=lambda item: (item.published_at or "", item.canonical_url)):
                if document.published_at is not None and _parse_timestamp(document.published_at, "news publication") > observation:
                    raise StorageError("publication time cannot follow evidence observation")
                existing = connection.execute(
                    "SELECT * FROM news_documents WHERE canonical_url = ?", (document.canonical_url,)
                ).fetchone()
                if existing is not None:
                    _check_existing_document(existing, source_id, document, observation)
                    counts["documents_no_change"] += 1
                    continue
                duplicate = connection.execute(
                    "SELECT id FROM news_documents WHERE source_id = ? AND content_hash = ? ORDER BY id LIMIT 1",
                    (source_id, document.content_hash),
                ).fetchone()
                duplicate_id = duplicate["id"] if duplicate is not None else None
                if duplicate_id is not None:
                    original = connection.execute(
                        "SELECT topic_key, placement_qualifier FROM news_documents WHERE id = ?", (duplicate_id,)
                    ).fetchone()
                    if (original["topic_key"], original["placement_qualifier"]) != (
                        document.topic_key, document.placement_qualifier
                    ):
                        raise StorageError("identical content cannot assert conflicting normalized facts")
                cursor = connection.execute(
                    """INSERT INTO news_documents (
                        source_id, canonical_url, external_id, title, author, published_at,
                        first_observed_at, content_hash, duplicate_of_document_id, topic_key,
                        subject_key, subject_name, effective_date, placement_qualifier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (source_id, document.canonical_url, document.external_id, document.title,
                     document.author, document.published_at, stamp, document.content_hash,
                     duplicate_id, document.topic_key, document.subject_key,
                     document.subject_name, document.effective_date, document.placement_qualifier),
                )
                document_id = cursor.lastrowid
                counts["documents_inserted"] += 1
                if duplicate_id is not None:
                    counts["exact_content_duplicates"] += 1
                _apply_document(connection, document, document_id, batch.mode, stamp, counts)
    return counts


def _source(connection: sqlite3.Connection, mode: str) -> int:
    key = f"houston-texans-official:{mode}"
    name = "Synthetic Texans evidence" if mode == "synthetic" else "Houston Texans"
    connection.execute(
        "INSERT OR IGNORE INTO news_sources (source_key, name, base_url, source_kind, evidence_mode) "
        "VALUES (?, ?, ?, 'official', ?)",
        (key, name, "https://example.test" if mode == "synthetic" else "https://www.houstontexans.com", mode),
    )
    return connection.execute("SELECT id FROM news_sources WHERE source_key = ?", (key,)).fetchone()[0]


def _check_existing_document(
    existing: sqlite3.Row, source_id: int, document: ReviewedDocument, observation: datetime
) -> None:
    expected = {
        "source_id": source_id,
        "external_id": document.external_id,
        "title": document.title,
        "author": document.author,
        "published_at": document.published_at,
        "content_hash": document.content_hash,
        "topic_key": document.topic_key,
        "subject_key": document.subject_key,
        "subject_name": document.subject_name,
        "effective_date": document.effective_date,
        "placement_qualifier": document.placement_qualifier,
    }
    if any(existing[key] != value for key, value in expected.items()):
        raise StorageError(f"changed or conflicting evidence at existing URL: {document.canonical_url}")
    if observation < _parse_timestamp(existing["first_observed_at"], "stored observation"):
        raise StorageError("an older observation cannot replace stored document state")


def _apply_document(
    connection: sqlite3.Connection, document: ReviewedDocument, document_id: int,
    mode: str, observed_at: str, counts: dict[str, int],
) -> None:
    topic = connection.execute("SELECT * FROM news_topics WHERE topic_key = ?", (document.topic_key,)).fetchone()
    if topic is None:
        cursor = connection.execute(
            """INSERT INTO news_topics (
                topic_key, entity_id, subject_key, subject_name, action, effective_date,
                placement_qualifier, first_observed_at, last_evidence_observed_at,
                meaningful_changed_at, material_published_at, material_document_id, revision, evidence_mode
            ) VALUES (?, 'texans', ?, ?, 'placed_on_ir', ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (document.topic_key, document.subject_key, document.subject_name,
             document.effective_date, document.placement_qualifier, observed_at, observed_at,
             observed_at, document.published_at, document_id, mode),
        )
        topic_id = cursor.lastrowid
        counts["topics_inserted"] += 1
        contributed_placement, contributed_qualifier = 1, int(document.placement_qualifier is not None)
    else:
        if topic["evidence_mode"] != mode or topic["subject_name"] != document.subject_name:
            raise StorageError("conflicting topic identity or evidence mode")
        if _parse_timestamp(observed_at, "news observation") < _parse_timestamp(topic["last_evidence_observed_at"], "stored observation"):
            raise StorageError("out-of-order evidence observation is unsupported")
        if topic["placement_qualifier"] is not None and document.placement_qualifier not in (None, topic["placement_qualifier"]):
            raise StorageError("conflicting placement qualifier")
        topic_id = topic["id"]
        contributed_placement = 0
        contributed_qualifier = int(topic["placement_qualifier"] is None and document.placement_qualifier is not None)
        if contributed_qualifier:
            connection.execute(
                """UPDATE news_topics SET placement_qualifier = ?, last_evidence_observed_at = ?,
                    meaningful_changed_at = ?, material_published_at = ?, material_document_id = ?,
                    revision = revision + 1 WHERE id = ?""",
                (document.placement_qualifier, observed_at, observed_at, document.published_at, document_id, topic_id),
            )
            counts["topics_updated"] += 1
        else:
            connection.execute(
                "UPDATE news_topics SET last_evidence_observed_at = ? WHERE id = ?",
                (observed_at, topic_id),
            )
            counts["topics_no_change"] += 1
    connection.execute(
        "INSERT INTO news_topic_documents (topic_id, document_id, contributed_placement, contributed_qualifier) "
        "VALUES (?, ?, ?, ?)",
        (topic_id, document_id, contributed_placement, contributed_qualifier),
    )
    counts["evidence_links_inserted"] += 1


def load_news_topics(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT t.*, d.canonical_url AS material_url, d.published_at AS source_published_at,
                    d.first_observed_at AS source_observed_at, s.name AS source_name,
                    s.source_key, s.source_kind
                FROM news_topics t JOIN news_documents d ON d.id = t.material_document_id
                JOIN news_sources s ON s.id = d.source_id ORDER BY t.topic_key"""
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: news_topics" in str(exc):
                return []
            raise
        return [dict(row) for row in rows]


def inspect_news_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise StorageError(f"database does not exist: {path}")
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            sources = [dict(row) for row in connection.execute("SELECT * FROM news_sources ORDER BY id")]
            documents = [dict(row) for row in connection.execute("SELECT * FROM news_documents ORDER BY id")]
            topics = [dict(row) for row in connection.execute("SELECT * FROM news_topics ORDER BY id")]
            links = [dict(row) for row in connection.execute("SELECT * FROM news_topic_documents ORDER BY topic_id, document_id")]
        except sqlite3.OperationalError as exc:
            if "no such table: news_sources" in str(exc):
                raise StorageError("database contains no reviewed Texans evidence") from exc
            raise
    return {"source_count": len(sources), "document_count": len(documents),
            "topic_count": len(topics), "evidence_link_count": len(links),
            "sources": sources, "documents": documents, "topics": topics, "evidence_links": links}


def _parse_timestamp(raw: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise StorageError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

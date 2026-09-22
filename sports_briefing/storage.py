from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .football_data import FootballFixture, PROVIDER


RAW_DIAGNOSTIC_LIMIT_BYTES = 256 * 1024
FETCH_HISTORY_LIMIT = 20
SEMANTIC_COLUMNS = (
    "competition_id",
    "competition_code",
    "competition_name",
    "season_id",
    "kickoff_utc",
    "status",
    "matchday",
    "stage",
    "group_name",
    "home_team_id",
    "home_team_name",
    "away_team_id",
    "away_team_name",
    "winner",
    "score_duration",
    "score_json",
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_fetches (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    entity TEXT NOT NULL,
    request_url TEXT NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    http_status INTEGER,
    outcome TEXT NOT NULL,
    error_stage TEXT,
    error_message TEXT,
    raw_response TEXT,
    raw_response_truncated INTEGER NOT NULL CHECK (raw_response_truncated IN (0, 1)),
    received_count INTEGER,
    supported_count INTEGER,
    filtered_unsupported_count INTEGER,
    inserted_count INTEGER,
    updated_count INTEGER,
    no_change_count INTEGER
);

CREATE TABLE IF NOT EXISTS football_fixtures (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_match_id TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    competition_code TEXT NOT NULL,
    competition_name TEXT NOT NULL,
    season_id TEXT NOT NULL,
    kickoff_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    matchday INTEGER,
    stage TEXT,
    group_name TEXT,
    home_team_id TEXT NOT NULL,
    home_team_name TEXT NOT NULL,
    away_team_id TEXT NOT NULL,
    away_team_name TEXT NOT NULL,
    winner TEXT,
    score_duration TEXT,
    score_json TEXT NOT NULL,
    provider_updated_at TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (provider, provider_match_id)
);

CREATE INDEX IF NOT EXISTS football_fixtures_kickoff_idx
    ON football_fixtures (kickoff_utc, provider_match_id);
"""


class StorageError(Exception):
    pass


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA)


def record_failed_fetch(
    path: Path,
    *,
    request_url: str,
    date_from: str,
    date_to: str,
    started_at: str,
    completed_at: str,
    http_status: int | None,
    outcome: str,
    error_stage: str,
    error_message: str,
    raw_response: str | None,
) -> None:
    raw, truncated = _bounded_raw(raw_response)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO provider_fetches (
                    provider, entity, request_url, date_from, date_to, started_at, completed_at,
                    http_status, outcome, error_stage, error_message, raw_response,
                    raw_response_truncated
                ) VALUES (?, 'arsenal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROVIDER,
                    request_url,
                    date_from,
                    date_to,
                    started_at,
                    completed_at,
                    http_status,
                    outcome,
                    error_stage,
                    error_message,
                    raw,
                    int(truncated),
                ),
            )
            _prune_fetches(connection)


def persist_successful_fetch(
    path: Path,
    *,
    request_url: str,
    date_from: str,
    date_to: str,
    started_at: str,
    completed_at: str,
    http_status: int,
    raw_response: str,
    received_count: int,
    fixtures: Iterable[FootballFixture],
    filtered_unsupported_count: int,
) -> dict[str, int]:
    fixture_list = list(fixtures)
    raw, truncated = _bounded_raw(raw_response)
    counts = {"inserted": 0, "updated": 0, "no_change": 0}
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            for fixture in fixture_list:
                outcome = _upsert_fixture(
                    connection,
                    fixture,
                    source_url=request_url,
                    fetched_at=completed_at,
                )
                counts[outcome] += 1
            connection.execute(
                """
                INSERT INTO provider_fetches (
                    provider, entity, request_url, date_from, date_to, started_at, completed_at,
                    http_status, outcome, raw_response, raw_response_truncated, received_count,
                    supported_count, filtered_unsupported_count, inserted_count, updated_count,
                    no_change_count
                ) VALUES (?, 'arsenal', ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROVIDER,
                    request_url,
                    date_from,
                    date_to,
                    started_at,
                    completed_at,
                    http_status,
                    raw,
                    int(truncated),
                    received_count,
                    len(fixture_list),
                    filtered_unsupported_count,
                    counts["inserted"],
                    counts["updated"],
                    counts["no_change"],
                ),
            )
            _prune_fetches(connection)
    return counts


def inspect_state(path: Path) -> dict[str, Any]:
    with closing(_read_only(path)) as connection:
        connection.row_factory = sqlite3.Row
        fixtures = connection.execute(
            "SELECT * FROM football_fixtures ORDER BY kickoff_utc, provider_match_id"
        ).fetchall()
        latest_attempt = connection.execute(
            "SELECT * FROM provider_fetches ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest_fetch = connection.execute(
            "SELECT * FROM provider_fetches WHERE outcome = 'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "entity": "arsenal",
        "fixtures": [_fixture_projection(row) for row in fixtures],
        "latest_attempt": _fetch_projection(latest_attempt),
        "latest_fetch": _fetch_projection(latest_fetch),
    }


def load_briefing_state(path: Path, as_of: str | None) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    with closing(_read_only(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        latest = connection.execute(
            "SELECT * FROM provider_fetches WHERE outcome = 'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            raise StorageError("database contains no successful Arsenal ingestion")
        effective_as_of = as_of or latest["completed_at"]
        rows = connection.execute(
            "SELECT * FROM football_fixtures ORDER BY kickoff_utc, provider_match_id"
        ).fetchall()
    return [dict(row) for row in rows], effective_as_of, _fetch_projection(latest)


def _upsert_fixture(
    connection: sqlite3.Connection,
    fixture: FootballFixture,
    *,
    source_url: str,
    fetched_at: str,
) -> str:
    current = connection.execute(
        "SELECT * FROM football_fixtures WHERE provider = ? AND provider_match_id = ?",
        (PROVIDER, fixture.provider_match_id),
    ).fetchone()
    values = asdict(fixture)
    if current is None:
        connection.execute(
            """
            INSERT INTO football_fixtures (
                provider, provider_match_id, competition_id, competition_code, competition_name,
                season_id, kickoff_utc, status, matchday, stage, group_name, home_team_id,
                home_team_name, away_team_id, away_team_name, winner, score_duration, score_json,
                provider_updated_at, raw_record_json, source_url, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PROVIDER,
                *values.values(),
                source_url,
                fetched_at,
                fetched_at,
            ),
        )
        return "inserted"

    incoming_revision = _provider_revision(fixture.provider_updated_at)
    current_revision = _provider_revision(current["provider_updated_at"])
    if incoming_revision < current_revision:
        return "no_change"
    changed = any(current[column] != values[column] for column in SEMANTIC_COLUMNS)
    if changed:
        assignments = ", ".join(f"{column} = ?" for column in values)
        connection.execute(
            f"""
            UPDATE football_fixtures
            SET {assignments}, source_url = ?, last_seen_at = ?
            WHERE provider = ? AND provider_match_id = ?
            """,
            (
                *values.values(),
                source_url,
                fetched_at,
                PROVIDER,
                fixture.provider_match_id,
            ),
        )
        return "updated"

    connection.execute(
        """
        UPDATE football_fixtures
        SET provider_updated_at = ?, raw_record_json = ?, source_url = ?, last_seen_at = ?
        WHERE provider = ? AND provider_match_id = ?
        """,
        (
            fixture.provider_updated_at,
            fixture.raw_record_json,
            source_url,
            fetched_at,
            PROVIDER,
            fixture.provider_match_id,
        ),
    )
    return "no_change"


def _fixture_projection(row: sqlite3.Row) -> dict[str, Any]:
    import json

    score = json.loads(row["score_json"])
    return {
        "provider": row["provider"],
        "provider_match_id": row["provider_match_id"],
        "competition_code": row["competition_code"],
        "competition_name": row["competition_name"],
        "kickoff_utc": row["kickoff_utc"],
        "status": row["status"],
        "home_team": {"id": row["home_team_id"], "name": row["home_team_name"]},
        "away_team": {"id": row["away_team_id"], "name": row["away_team_name"]},
        "winner": row["winner"],
        "score_duration": row["score_duration"],
        "score_full_time": score.get("fullTime"),
        "provider_updated_at": row["provider_updated_at"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "source_url": row["source_url"],
    }


def _fetch_projection(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = (
        "provider",
        "request_url",
        "date_from",
        "date_to",
        "started_at",
        "completed_at",
        "http_status",
        "outcome",
        "error_stage",
        "error_message",
        "raw_response_truncated",
        "received_count",
        "supported_count",
        "filtered_unsupported_count",
        "inserted_count",
        "updated_count",
        "no_change_count",
    )
    return {key: row[key] for key in keys}


def _bounded_raw(raw: str | None) -> tuple[str | None, bool]:
    if raw is None:
        return None, False
    encoded = raw.encode("utf-8")
    if len(encoded) <= RAW_DIAGNOSTIC_LIMIT_BYTES:
        return raw, False
    bounded = encoded[:RAW_DIAGNOSTIC_LIMIT_BYTES].decode("utf-8", errors="ignore")
    return bounded, True


def _prune_fetches(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM provider_fetches
        WHERE id NOT IN (
            SELECT id FROM provider_fetches ORDER BY id DESC LIMIT ?
        )
        AND id != COALESCE(
            (SELECT MAX(id) FROM provider_fetches WHERE outcome = 'success'),
            -1
        )
        """,
        (FETCH_HISTORY_LIMIT,),
    )


def _provider_revision(value: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise StorageError(f"database does not exist: {path}")
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise StorageError(f"could not open database: {exc}") from exc

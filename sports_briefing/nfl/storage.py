from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from ..storage import RAW_DIAGNOSTIC_LIMIT_BYTES, StorageError, initialize_database
from .sportradar import InjurySnapshot, NFLGame, PROVIDER, ScheduleSnapshot


NFL_FETCH_HISTORY_LIMIT = 20
NFL_SCHEMA = """
CREATE TABLE IF NOT EXISTS nfl_games (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_game_id TEXT NOT NULL,
    season_id TEXT NOT NULL,
    season_year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    week_id TEXT NOT NULL,
    week INTEGER NOT NULL,
    scheduled_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    home_team_id TEXT NOT NULL,
    home_team_name TEXT NOT NULL,
    home_team_alias TEXT NOT NULL,
    away_team_id TEXT NOT NULL,
    away_team_name TEXT NOT NULL,
    away_team_alias TEXT NOT NULL,
    provider_generated_at TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (provider, provider_game_id)
);

CREATE TABLE IF NOT EXISTS nfl_availability_current (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    season_year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    week INTEGER NOT NULL,
    week_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    position TEXT,
    jersey TEXT,
    sr_id TEXT,
    practice_status TEXT,
    game_status TEXT,
    injury TEXT,
    status_date TEXT,
    is_present INTEGER NOT NULL CHECK (is_present IN (0, 1)),
    provider_generated_at TEXT NOT NULL,
    raw_record_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (provider, season_year, season_type, week, team_id, player_id)
);

CREATE TABLE IF NOT EXISTS nfl_availability_changes (
    id INTEGER PRIMARY KEY,
    change_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    season_year INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    week INTEGER NOT NULL,
    week_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    player_name TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    provider_generated_at TEXT NOT NULL,
    report_date TEXT,
    observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nfl_source_revisions (
    provider TEXT NOT NULL,
    endpoint_key TEXT NOT NULL,
    provider_generated_at TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    report_date TEXT,
    accepted_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (provider, endpoint_key)
);

CREATE TABLE IF NOT EXISTS nfl_fetches (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    entity TEXT NOT NULL,
    schedule_url TEXT NOT NULL,
    injuries_url TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    schedule_generated_at TEXT,
    injuries_generated_at TEXT,
    http_status INTEGER,
    outcome TEXT NOT NULL,
    error_stage TEXT,
    error_message TEXT,
    schedule_raw TEXT,
    injuries_raw TEXT,
    raw_response_truncated INTEGER NOT NULL CHECK (raw_response_truncated IN (0, 1)),
    games_count INTEGER,
    availability_count INTEGER,
    change_count INTEGER
);

CREATE INDEX IF NOT EXISTS nfl_games_schedule_idx
    ON nfl_games (scheduled_utc, provider_game_id);
CREATE INDEX IF NOT EXISTS nfl_availability_scope_idx
    ON nfl_availability_current (season_year, season_type, week, is_present, player_id);
CREATE INDEX IF NOT EXISTS nfl_changes_scope_idx
    ON nfl_availability_changes (season_year, season_type, week, observed_at, id);
"""


def initialize_nfl_database(path: Path) -> None:
    initialize_database(path)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(NFL_SCHEMA)


def persist_texans_fetch(
    path: Path,
    *,
    schedule: ScheduleSnapshot,
    injuries: InjurySnapshot,
    schedule_url: str,
    injuries_url: str,
    schedule_generated_at: str,
    injuries_generated_at: str,
    schedule_raw: str,
    injuries_raw: str,
    started_at: str,
    completed_at: str,
    http_status: int = 200,
) -> dict[str, int]:
    _validate_matching_scope(schedule, injuries)
    schedule_key = f"schedule:{schedule.season_year}:{schedule.season_type}"
    injuries_key = f"injuries:{injuries.season_year}:{injuries.season_type}:{injuries.week}"
    schedule_hash = _semantic_hash(schedule)
    injuries_hash = _semantic_hash(injuries)
    schedule_bounded, schedule_truncated = _bounded_raw(schedule_raw)
    injuries_bounded, injuries_truncated = _bounded_raw(injuries_raw)
    counts = {"games_inserted": 0, "games_updated": 0, "games_no_change": 0, "availability_inserted": 0, "availability_updated": 0, "availability_no_change": 0, "changes": 0}

    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            schedule_state = _revision_state(
                connection, schedule_key, schedule_generated_at, schedule_hash
            )
            injuries_state = _revision_state(
                connection,
                injuries_key,
                injuries_generated_at,
                injuries_hash,
            )
            if schedule_state == "new":
                for game in schedule.games:
                    outcome = _upsert_game(
                        connection,
                        game,
                        generated_at=schedule_generated_at,
                        source_url=schedule_url,
                        observed_at=completed_at,
                    )
                    counts[f"games_{outcome}"] += 1
                for provider_game_id in schedule.deleted_game_ids:
                    changed = _mark_deleted_game(
                        connection,
                        schedule,
                        provider_game_id,
                        generated_at=schedule_generated_at,
                        source_url=schedule_url,
                        observed_at=completed_at,
                    )
                    counts["games_updated"] += changed
            else:
                counts["games_no_change"] = len(schedule.games)
            if injuries_state == "new":
                injury_counts = _apply_injury_snapshot(
                    connection,
                    injuries,
                    generated_at=injuries_generated_at,
                    source_url=injuries_url,
                    observed_at=completed_at,
                )
                for key, value in injury_counts.items():
                    counts[key] += value
            else:
                counts["availability_no_change"] = len(injuries.players)
            if schedule_state == "new":
                _save_revision(connection, schedule_key, schedule_generated_at, schedule_hash, None, completed_at, schedule_url)
            if injuries_state == "new":
                _save_revision(connection, injuries_key, injuries_generated_at, injuries_hash, injuries.report_date, completed_at, injuries_url)
            connection.execute(
                """
                INSERT INTO nfl_fetches (
                    provider, entity, schedule_url, injuries_url, started_at, completed_at,
                    schedule_generated_at, injuries_generated_at, http_status, outcome,
                    schedule_raw, injuries_raw, raw_response_truncated, games_count,
                    availability_count, change_count
                ) VALUES (?, 'texans', ?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROVIDER,
                    schedule_url,
                    injuries_url,
                    started_at,
                    completed_at,
                    schedule_generated_at,
                    injuries_generated_at,
                    http_status,
                    schedule_bounded,
                    injuries_bounded,
                    int(schedule_truncated or injuries_truncated),
                    len(schedule.games),
                    len(injuries.players),
                    counts["changes"],
                ),
            )
            _prune_fetches(connection)
    return counts


def record_failed_texans_fetch(
    path: Path,
    *,
    schedule_url: str,
    injuries_url: str | None,
    started_at: str,
    completed_at: str,
    outcome: str,
    error_stage: str,
    error_message: str,
    http_status: int | None = None,
    schedule_generated_at: str | None = None,
    injuries_generated_at: str | None = None,
    schedule_raw: str | None = None,
    injuries_raw: str | None = None,
) -> None:
    schedule_bounded, schedule_truncated = _bounded_raw(schedule_raw)
    injuries_bounded, injuries_truncated = _bounded_raw(injuries_raw)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO nfl_fetches (
                    provider, entity, schedule_url, injuries_url, started_at, completed_at,
                    schedule_generated_at, injuries_generated_at, http_status, outcome,
                    error_stage, error_message, schedule_raw, injuries_raw,
                    raw_response_truncated
                ) VALUES (?, 'texans', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    PROVIDER,
                    schedule_url,
                    injuries_url,
                    started_at,
                    completed_at,
                    schedule_generated_at,
                    injuries_generated_at,
                    http_status,
                    outcome,
                    error_stage,
                    error_message,
                    schedule_bounded,
                    injuries_bounded,
                    int(schedule_truncated or injuries_truncated),
                ),
            )
            _prune_fetches(connection)


def inspect_texans_state(path: Path) -> dict[str, Any]:
    with closing(_read_only(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        games = connection.execute("SELECT * FROM nfl_games ORDER BY scheduled_utc, provider_game_id").fetchall()
        availability = connection.execute(
            "SELECT * FROM nfl_availability_current ORDER BY season_year, season_type, week, player_id"
        ).fetchall()
        changes = connection.execute(
            "SELECT * FROM nfl_availability_changes ORDER BY observed_at, id"
        ).fetchall()
        latest = connection.execute("SELECT * FROM nfl_fetches ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "entity": "texans",
        "games": [_game_projection(row) for row in games],
        "availability": [_availability_projection(row) for row in availability],
        "changes": [_change_projection(row) for row in changes],
        "latest_attempt": _fetch_projection(latest),
    }


def load_texans_briefing_state(path: Path, as_of: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], str, dict[str, Any]]:
    with closing(_read_only(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        latest = connection.execute(
            "SELECT * FROM nfl_fetches WHERE outcome = 'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            raise StorageError("database contains no successful Texans ingestion")
        games = [dict(row) for row in connection.execute("SELECT * FROM nfl_games ORDER BY scheduled_utc, provider_game_id")]
        availability = [dict(row) for row in connection.execute("SELECT * FROM nfl_availability_current ORDER BY player_name, player_id")]
        changes = [dict(row) for row in connection.execute("SELECT * FROM nfl_availability_changes ORDER BY observed_at DESC, id DESC")]
        revisions = {
            row["endpoint_key"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM nfl_source_revisions WHERE endpoint_key LIKE 'injuries:%'"
            )
        }
        effective_as_of = as_of or latest["completed_at"]
    return games, availability, changes, revisions, effective_as_of, _fetch_projection(latest)


def _validate_matching_scope(schedule: ScheduleSnapshot, injuries: InjurySnapshot) -> None:
    if (schedule.season_year, schedule.season_type) != (injuries.season_year, injuries.season_type):
        raise StorageError("schedule and injury report season scopes do not match")
    matching = [game for game in schedule.games if game.week == injuries.week]
    if not matching:
        raise StorageError("injury report week has no Houston Texans game in the fetched schedule")
    if any(game.week_id != injuries.week_id for game in matching):
        raise StorageError("schedule and injury report week identities do not match")


def _revision_state(
    connection: sqlite3.Connection,
    endpoint_key: str,
    generated_at: str,
    semantic_hash: str,
) -> str:
    incoming = _parse_timestamp(generated_at, "provider revision")
    current = connection.execute(
        "SELECT * FROM nfl_source_revisions WHERE provider = ? AND endpoint_key = ?",
        (PROVIDER, endpoint_key),
    ).fetchone()
    if current is None:
        return "new"
    stored = _parse_timestamp(current["provider_generated_at"], "stored provider revision")
    if incoming < stored:
        raise StorageError(f"stale provider revision for {endpoint_key}")
    if incoming == stored:
        if current["semantic_hash"] != semantic_hash:
            raise StorageError(f"conflicting payload for equal provider revision: {endpoint_key}")
        return "identical"
    return "new"


def _save_revision(connection: sqlite3.Connection, endpoint_key: str, generated_at: str, semantic_hash: str, report_date: str | None, accepted_at: str, source_url: str) -> None:
    connection.execute(
        """
        INSERT INTO nfl_source_revisions (
            provider, endpoint_key, provider_generated_at, semantic_hash, report_date,
            accepted_at, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, endpoint_key) DO UPDATE SET
            provider_generated_at = excluded.provider_generated_at,
            semantic_hash = excluded.semantic_hash,
            report_date = excluded.report_date,
            accepted_at = excluded.accepted_at,
            source_url = excluded.source_url
        """,
        (
            PROVIDER,
            endpoint_key,
            generated_at,
            semantic_hash,
            report_date,
            accepted_at,
            source_url,
        ),
    )


def _upsert_game(connection: sqlite3.Connection, game: NFLGame, *, generated_at: str, source_url: str, observed_at: str) -> str:
    current = connection.execute(
        "SELECT * FROM nfl_games WHERE provider = ? AND provider_game_id = ?",
        (PROVIDER, game.provider_game_id),
    ).fetchone()
    values = asdict(game)
    if current is None:
        connection.execute(
            """
            INSERT INTO nfl_games (
                provider, provider_game_id, season_id, season_year, season_type, week_id,
                week, scheduled_utc, status, home_team_id, home_team_name, home_team_alias,
                away_team_id, away_team_name, away_team_alias, provider_generated_at,
                raw_record_json, source_url, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                PROVIDER,
                game.provider_game_id,
                game.season_id,
                game.season_year,
                game.season_type,
                game.week_id,
                game.week,
                game.scheduled_utc,
                game.status,
                game.home_team_id,
                game.home_team_name,
                game.home_team_alias,
                game.away_team_id,
                game.away_team_name,
                game.away_team_alias,
                generated_at,
                game.raw_record_json,
                source_url,
                observed_at,
                observed_at,
            ),
        )
        return "inserted"
    current_scope = (
        current["season_id"],
        current["season_year"],
        current["season_type"],
    )
    incoming_scope = (game.season_id, game.season_year, game.season_type)
    if current_scope != incoming_scope:
        raise StorageError(
            f"provider game {game.provider_game_id} was reused across season scopes"
        )
    incoming_revision = _parse_timestamp(generated_at, "game provider revision")
    current_revision = _parse_timestamp(
        current["provider_generated_at"], "stored game provider revision"
    )
    if incoming_revision < current_revision:
        raise StorageError(f"stale provider revision for game {game.provider_game_id}")
    semantic = tuple(values[key] for key in values if key != "raw_record_json")
    current_semantic = tuple(current[key] for key in values if key != "raw_record_json")
    if incoming_revision == current_revision and semantic != current_semantic:
        raise StorageError(
            f"conflicting payload for equal game revision: {game.provider_game_id}"
        )
    if semantic == current_semantic:
        connection.execute(
            "UPDATE nfl_games SET provider_generated_at=?, raw_record_json=?, source_url=?, last_seen_at=? WHERE id=?",
            (generated_at, game.raw_record_json, source_url, observed_at, current["id"]),
        )
        return "no_change"
    assignments = ", ".join(f"{key}=?" for key in values)
    connection.execute(
        f"UPDATE nfl_games SET {assignments}, provider_generated_at=?, source_url=?, last_seen_at=? WHERE id=?",
        (*values.values(), generated_at, source_url, observed_at, current["id"]),
    )
    return "updated"


def _mark_deleted_game(
    connection: sqlite3.Connection,
    schedule: ScheduleSnapshot,
    provider_game_id: str,
    *,
    generated_at: str,
    source_url: str,
    observed_at: str,
) -> int:
    current = connection.execute(
        "SELECT * FROM nfl_games WHERE provider=? AND provider_game_id=?",
        (PROVIDER, provider_game_id),
    ).fetchone()
    if current is None:
        return 0
    current_scope = (
        current["season_id"],
        current["season_year"],
        current["season_type"],
    )
    incoming_scope = (schedule.season_id, schedule.season_year, schedule.season_type)
    if current_scope != incoming_scope:
        raise StorageError(
            f"deleted provider game {provider_game_id} belongs to another season scope"
        )
    incoming_revision = _parse_timestamp(generated_at, "deleted game provider revision")
    current_revision = _parse_timestamp(
        current["provider_generated_at"], "stored game provider revision"
    )
    if incoming_revision < current_revision:
        raise StorageError(f"stale provider revision for deleted game {provider_game_id}")
    if incoming_revision == current_revision and current["status"] != "deleted":
        raise StorageError(
            f"conflicting deletion for equal game revision: {provider_game_id}"
        )
    if current["status"] == "deleted":
        return 0
    connection.execute(
        """
        UPDATE nfl_games
        SET status='deleted', provider_generated_at=?, source_url=?, last_seen_at=?
        WHERE id=?
        """,
        (generated_at, source_url, observed_at, current["id"]),
    )
    return 1


def _apply_injury_snapshot(connection: sqlite3.Connection, snapshot: InjurySnapshot, *, generated_at: str, source_url: str, observed_at: str) -> dict[str, int]:
    counts = {"availability_inserted": 0, "availability_updated": 0, "availability_no_change": 0, "changes": 0}
    scope = (PROVIDER, snapshot.season_year, snapshot.season_type, snapshot.week, snapshot.team_id)
    existing = {
        row["player_id"]: row
        for row in connection.execute(
            """
            SELECT * FROM nfl_availability_current
            WHERE provider=? AND season_year=? AND season_type=? AND week=? AND team_id=?
            """,
            scope,
        ).fetchall()
    }
    incoming_ids = {player.player_id for player in snapshot.players}
    for player in snapshot.players:
        current = existing.get(player.player_id)
        if current is not None:
            _guard_player_report_date(current["status_date"], player.status_date, player.player_id)
        if current is None or not current["is_present"]:
            _upsert_availability(connection, snapshot, player, generated_at, source_url, observed_at)
            counts["availability_inserted"] += 1
            _insert_change(
                connection,
                snapshot,
                player.player_id,
                player.player_name,
                "NEW_REPORT",
                None,
                _state_summary(player),
                player.status_date,
                generated_at,
                observed_at,
                source_url,
            )
            counts["changes"] += 1
            continue
        changes = _player_changes(current, player)
        if changes:
            _upsert_availability(connection, snapshot, player, generated_at, source_url, observed_at)
            counts["availability_updated"] += 1
            for change_type, old_value, new_value in changes:
                _insert_change(
                    connection,
                    snapshot,
                    player.player_id,
                    player.player_name,
                    change_type,
                    old_value,
                    new_value,
                    player.status_date,
                    generated_at,
                    observed_at,
                    source_url,
                )
                counts["changes"] += 1
        else:
            _upsert_availability(
                connection, snapshot, player, generated_at, source_url, observed_at
            )
            counts["availability_no_change"] += 1
    for player_id, current in existing.items():
        if player_id in incoming_ids or not current["is_present"]:
            continue
        connection.execute(
            "UPDATE nfl_availability_current SET is_present=0, provider_generated_at=?, source_url=?, last_seen_at=? WHERE id=?",
            (generated_at, source_url, observed_at, current["id"]),
        )
        counts["availability_updated"] += 1
        _insert_change(
            connection,
            snapshot,
            player_id,
            current["player_name"],
            "REMOVED_FROM_REPORT",
            _row_state_summary(current),
            None,
            None,
            generated_at,
            observed_at,
            source_url,
        )
        counts["changes"] += 1
    return counts


def _upsert_availability(connection: sqlite3.Connection, snapshot: InjurySnapshot, player: Any, generated_at: str, source_url: str, observed_at: str) -> None:
    connection.execute(
        """
        INSERT INTO nfl_availability_current (
            provider, season_year, season_type, week, week_id, team_id, player_id,
            player_name, position, jersey, sr_id, practice_status, game_status, injury,
            status_date, is_present, provider_generated_at, raw_record_json, source_url,
            first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, season_year, season_type, week, team_id, player_id) DO UPDATE SET
            week_id=excluded.week_id, player_name=excluded.player_name,
            position=excluded.position, jersey=excluded.jersey, sr_id=excluded.sr_id,
            practice_status=excluded.practice_status, game_status=excluded.game_status,
            injury=excluded.injury, status_date=excluded.status_date, is_present=1,
            provider_generated_at=excluded.provider_generated_at,
            raw_record_json=excluded.raw_record_json, source_url=excluded.source_url,
            last_seen_at=excluded.last_seen_at
        """,
        (
            PROVIDER, snapshot.season_year, snapshot.season_type, snapshot.week,
            snapshot.week_id, snapshot.team_id, player.player_id, player.player_name,
            player.position, player.jersey, player.sr_id, player.practice_status,
            player.game_status, player.injury, player.status_date, generated_at,
            player.raw_record_json, source_url, observed_at, observed_at,
        ),
    )


def _player_changes(current: sqlite3.Row, player: Any) -> list[tuple[str, str | None, str | None]]:
    changes: list[tuple[str, str | None, str | None]] = []
    fields = (
        ("PRACTICE_STATUS_CHANGED", "practice_status", player.practice_status),
        ("GAME_STATUS_CHANGED", "game_status", player.game_status),
        ("INJURY_CHANGED", "injury", player.injury),
    )
    for change_type, column, new_value in fields:
        if current[column] != new_value:
            changes.append((change_type, current[column], new_value))
    return changes


def _guard_player_report_date(current: str | None, incoming: str | None, player_id: str) -> None:
    if current is not None and incoming is None:
        raise StorageError(f"status date regressed to unknown for player {player_id}")
    if current is not None and incoming is not None:
        if _parse_timestamp(incoming, "player status date") < _parse_timestamp(current, "stored player status date"):
            raise StorageError(f"status date regressed for player {player_id}")


def _insert_change(
    connection: sqlite3.Connection,
    snapshot: InjurySnapshot,
    player_id: str,
    player_name: str,
    change_type: str,
    old_value: str | None,
    new_value: str | None,
    report_date: str | None,
    generated_at: str,
    observed_at: str,
    source_url: str,
) -> None:
    identity = "|".join((str(snapshot.season_year), snapshot.season_type, str(snapshot.week), player_id, change_type, old_value or "<null>", new_value or "<null>", generated_at))
    change_key = hashlib.sha256(identity.encode()).hexdigest()
    connection.execute(
        """
        INSERT INTO nfl_availability_changes (
            change_key, provider, season_year, season_type, week, week_id, team_id,
            player_id, player_name, change_type, old_value, new_value,
            provider_generated_at, report_date, observed_at, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (change_key, PROVIDER, snapshot.season_year, snapshot.season_type, snapshot.week, snapshot.week_id, snapshot.team_id, player_id, player_name, change_type, old_value, new_value, generated_at, report_date, observed_at, source_url),
    )


def _state_summary(player: Any) -> str:
    return json.dumps({"practice_status": player.practice_status, "game_status": player.game_status, "injury": player.injury}, separators=(",", ":"), sort_keys=True)


def _row_state_summary(row: sqlite3.Row) -> str:
    return json.dumps({"practice_status": row["practice_status"], "game_status": row["game_status"], "injury": row["injury"]}, separators=(",", ":"), sort_keys=True)


def _semantic_hash(snapshot: object) -> str:
    value = asdict(snapshot)
    if isinstance(snapshot, ScheduleSnapshot):
        value["games"] = list(value["games"])
        for game in value["games"]:
            game.pop("raw_record_json", None)
        value["games"].sort(key=lambda game: game["provider_game_id"])
        value["deleted_game_ids"] = sorted(value["deleted_game_ids"])
    elif isinstance(snapshot, InjurySnapshot):
        value["players"] = list(value["players"])
        for player in value["players"]:
            player.pop("raw_record_json", None)
        value["players"].sort(key=lambda player: player["player_id"])
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _game_projection(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in ("provider_game_id", "season_year", "season_type", "week", "scheduled_utc", "status", "home_team_name", "away_team_name", "provider_generated_at", "last_seen_at", "source_url")}


def _availability_projection(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in ("season_year", "season_type", "week", "player_id", "player_name", "position", "practice_status", "game_status", "injury", "status_date", "is_present", "provider_generated_at", "last_seen_at", "source_url")}


def _change_projection(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in ("season_year", "season_type", "week", "player_id", "player_name", "change_type", "old_value", "new_value", "provider_generated_at", "report_date", "observed_at", "source_url")}


def _fetch_projection(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = ("provider", "schedule_url", "injuries_url", "started_at", "completed_at", "schedule_generated_at", "injuries_generated_at", "http_status", "outcome", "error_stage", "error_message", "raw_response_truncated", "games_count", "availability_count", "change_count")
    return {key: row[key] for key in keys}


def _bounded_raw(raw: str | None) -> tuple[str | None, bool]:
    if raw is None:
        return None, False
    encoded = raw.encode("utf-8")
    if len(encoded) <= RAW_DIAGNOSTIC_LIMIT_BYTES:
        return raw, False
    return encoded[:RAW_DIAGNOSTIC_LIMIT_BYTES].decode("utf-8", errors="ignore"), True


def _prune_fetches(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM nfl_fetches
        WHERE id NOT IN (SELECT id FROM nfl_fetches ORDER BY id DESC LIMIT ?)
        AND id != COALESCE((SELECT MAX(id) FROM nfl_fetches WHERE outcome='success'), -1)
        """,
        (NFL_FETCH_HISTORY_LIMIT,),
    )
    connection.execute(
        """
        UPDATE nfl_fetches
        SET schedule_raw=NULL, injuries_raw=NULL
        WHERE id != COALESCE((SELECT MAX(id) FROM nfl_fetches), -1)
        """
    )


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise StorageError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise StorageError(f"database does not exist: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)

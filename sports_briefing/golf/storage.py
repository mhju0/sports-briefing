"""Atomic Scottie state and endpoint provenance in the existing SQLite file."""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..storage import RAW_DIAGNOSTIC_LIMIT_BYTES, StorageError, initialize_database
from .sportradar import PROVIDER, SCOTTIE_ID, Response

SCHEMA = """
CREATE TABLE IF NOT EXISTS golf_tournaments (
 provider TEXT NOT NULL, tournament_id TEXT NOT NULL, name TEXT NOT NULL,
 tour_id TEXT NOT NULL, tour_alias TEXT NOT NULL, season_id TEXT NOT NULL,
 season_year INTEGER NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 course_timezone TEXT NOT NULL, event_type TEXT NOT NULL, status TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_changed_at TEXT NOT NULL,
 PRIMARY KEY(provider,tournament_id)
);
CREATE TABLE IF NOT EXISTS golf_entries (
 provider TEXT NOT NULL, tournament_id TEXT NOT NULL, player_id TEXT NOT NULL,
 display_name TEXT NOT NULL, field_confirmed INTEGER NOT NULL CHECK(field_confirmed=1),
 participation_source TEXT NOT NULL, position INTEGER, tied INTEGER, score INTEGER,
 strokes INTEGER, status TEXT, result_finalized_observed_at TEXT,
 first_seen_at TEXT NOT NULL, last_changed_at TEXT NOT NULL,
 PRIMARY KEY(provider,tournament_id,player_id)
);
CREATE TABLE IF NOT EXISTS golf_player_rounds (
 provider TEXT NOT NULL, tournament_id TEXT NOT NULL, player_id TEXT NOT NULL,
 round_id TEXT NOT NULL, number INTEGER NOT NULL, status TEXT NOT NULL,
 tee_time TEXT, score INTEGER, strokes INTEGER, thru INTEGER,
 scorecard_created_at TEXT, scorecard_updated_at TEXT,
 first_seen_at TEXT NOT NULL, last_changed_at TEXT NOT NULL,
 PRIMARY KEY(provider,tournament_id,player_id,round_id),
 UNIQUE(provider,tournament_id,player_id,number)
);
CREATE TABLE IF NOT EXISTS golf_sources (
 provider TEXT NOT NULL, endpoint_key TEXT NOT NULL, url TEXT NOT NULL,
 generated_raw TEXT NOT NULL, generated_at TEXT NOT NULL,
 last_modified TEXT, etag TEXT, semantic_hash TEXT NOT NULL,
 accepted_at TEXT NOT NULL, last_fetched_at TEXT NOT NULL,
 raw_response TEXT NOT NULL, raw_truncated INTEGER NOT NULL CHECK(raw_truncated IN(0,1)),
 PRIMARY KEY(provider,endpoint_key)
);
CREATE TABLE IF NOT EXISTS golf_fetches (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, entity TEXT NOT NULL,
 started_at TEXT NOT NULL, completed_at TEXT NOT NULL, outcome TEXT NOT NULL,
 tournament_id TEXT, endpoints_count INTEGER NOT NULL,
 inserted_count INTEGER NOT NULL, updated_count INTEGER NOT NULL,
 no_change_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS golf_rounds_time_idx ON golf_player_rounds(tee_time);
"""
ENTITY = "scheffler"
FETCH_LIMIT = 20
TOURNAMENT_FIELDS = ("name","tour_id","tour_alias","season_id","season_year","start_date","end_date","course_timezone","event_type","status")
ENTRY_FIELDS = ("display_name","field_confirmed","participation_source","position","tied","score","strokes","status")
ROUND_FIELDS = ("number","status","tee_time","score","strokes","thru","scorecard_created_at","scorecard_updated_at")


def initialize_golf_database(path: Path) -> None:
    initialize_database(path)
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(golf_entries)")}
            if "result_finalized_observed_at" not in columns:
                conn.execute("ALTER TABLE golf_entries ADD COLUMN result_finalized_observed_at TEXT")


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _bounded(value: str) -> tuple[str, int]:
    encoded = value.encode("utf-8")
    if len(encoded) <= RAW_DIAGNOSTIC_LIMIT_BYTES:
        return value, 0
    return encoded[:RAW_DIAGNOSTIC_LIMIT_BYTES].decode("utf-8", errors="ignore"), 1


def _source_content(bundle: dict[str, Any], key: str) -> object:
    try:
        return bundle["source_semantics"][key]
    except KeyError as exc:
        raise StorageError(f"missing normalized Golf source semantics: {key}") from exc


def _terminal_scottie_result(tournament: dict[str, Any], entry: dict[str, Any], rounds: list[dict[str, Any]]) -> bool:
    """A complete stroke-play result, excluding exceptions and partial rounds."""
    return (
        tournament["event_type"] == "stroke"
        and tournament["status"] == "closed"
        and entry["player_id"] == SCOTTIE_ID
        and entry["field_confirmed"] == 1
        and entry["status"] is None
        and isinstance(entry["position"], int) and entry["position"] > 0
        and isinstance(entry["score"], int)
        and isinstance(entry["strokes"], int) and entry["strokes"] > 0
        and bool(rounds)
        and all(r["status"] == "closed" and r["thru"] == 18
                and isinstance(r["score"], int) and isinstance(r["strokes"], int) and r["strokes"] > 0
                for r in rounds)
    )


def _plausible_finalization_date(tournament: dict[str, Any], observed_at: str) -> bool:
    """Bound observation to the event's local final date or following day."""
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("timezone missing")
        local_day = observed.astimezone(ZoneInfo(tournament["course_timezone"])).date()
        start = date.fromisoformat(tournament["start_date"])
        end = date.fromisoformat(tournament["end_date"])
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise StorageError("invalid Golf observation time or course timezone") from exc
    return start <= end and end <= local_day <= end + timedelta(days=1)


def persist_golf_fetch(path: Path, bundle: dict[str, Any], responses: dict[str, Response], *, started_at: str, completed_at: str) -> dict[str, int]:
    if set(responses) not in ({"schedule","summary","leaderboard"}, {"schedule","summary","leaderboard","tees","scores"}):
        raise StorageError("Golf response bundle is incomplete")
    if (bundle["selected_round"] is None) != ("tees" not in responses):
        raise StorageError("Golf round response scope mismatch")
    if any(response.generated_at is None or response.generated_raw is None for response in responses.values()):
        raise StorageError("accepted Golf source lacks x-generated-date")
    scopes = {key: (f"schedule:{bundle['tournament']['season_year']}:{bundle['tournament']['id']}" if key == "schedule" else f"{key}:{bundle['tournament']['id']}:{bundle['selected_round']}" if key in ("tees","scores") else f"{key}:{bundle['tournament']['id']}") for key in responses}
    hashes = {key: _hash(_source_content(bundle, key)) for key in responses}
    counts = {"inserted":0,"updated":0,"no_change":0,"sources_accepted":0,"sources_no_change":0}
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            # Check every endpoint before touching any accepted state.
            prior = {}
            for key, response in responses.items():
                current = conn.execute("SELECT * FROM golf_sources WHERE provider=? AND endpoint_key=?", (PROVIDER,scopes[key])).fetchone()
                prior[key] = current
                if current is None:
                    continue
                old = datetime.fromisoformat(current["generated_at"].replace("Z","+00:00"))
                new = datetime.fromisoformat(response.generated_at.replace("Z","+00:00"))
                if new < old:
                    raise StorageError(f"older Golf source generation for {scopes[key]}")
                if new == old and hashes[key] != current["semantic_hash"]:
                    raise StorageError(f"conflicting Golf content at equal generation for {scopes[key]}")
            tournament = bundle["tournament"]
            tid = tournament["id"]
            entry = bundle["entry"]
            previous_tournament = conn.execute("SELECT status FROM golf_tournaments WHERE provider=? AND tournament_id=?", (PROVIDER,tid)).fetchone()
            previous_entry = conn.execute("SELECT field_confirmed,status,result_finalized_observed_at FROM golf_entries WHERE provider=? AND tournament_id=? AND player_id=?", (PROVIDER,tid,entry["player_id"])).fetchone()
            observe_finalization = (
                previous_tournament is not None
                and previous_tournament["status"] in ("scheduled", "inprogress")
                and previous_entry is not None
                and previous_entry["field_confirmed"] == 1
                and previous_entry["status"] is None
                and previous_entry["result_finalized_observed_at"] is None
                and _terminal_scottie_result(tournament, entry, bundle["rounds"])
                and _plausible_finalization_date(tournament, completed_at)
            )
            existing_round_ids = {r[0] for r in conn.execute("SELECT round_id FROM golf_player_rounds WHERE provider=? AND tournament_id=? AND player_id=?",(PROVIDER,tid,bundle["entry"]["player_id"]))}
            incoming_round_ids = {r["round_id"] for r in bundle["rounds"]}
            if not existing_round_ids.issubset(incoming_round_ids):
                raise StorageError("newer Golf round list omits a previously accepted round; retirement semantics unverified")
            _upsert(conn, "golf_tournaments", {"provider":PROVIDER,"tournament_id":tid,**{k:tournament[k] for k in TOURNAMENT_FIELDS}}, ("provider","tournament_id"), TOURNAMENT_FIELDS, completed_at, counts)
            _upsert(conn, "golf_entries", {"provider":PROVIDER,"tournament_id":tid,"player_id":entry["player_id"],**{k:int(entry[k]) if k in ("field_confirmed","tied") and entry[k] is not None else entry[k] for k in ENTRY_FIELDS}}, ("provider","tournament_id","player_id"), ENTRY_FIELDS, completed_at, counts)
            for round_state in bundle["rounds"]:
                record={"provider":PROVIDER,"tournament_id":tid,"player_id":entry["player_id"],"round_id":round_state["round_id"],**{k:round_state["created_at"] if k=="scorecard_created_at" else round_state["updated_at"] if k=="scorecard_updated_at" else round_state[k] for k in ROUND_FIELDS}}
                if round_state["number"] != bundle["selected_round"]:
                    previous = conn.execute("SELECT tee_time,score,strokes,thru,scorecard_created_at,scorecard_updated_at FROM golf_player_rounds WHERE provider=? AND tournament_id=? AND player_id=? AND round_id=?",(PROVIDER,tid,entry["player_id"],round_state["round_id"])).fetchone()
                    if previous is not None:
                        for field in ("tee_time","score","strokes","thru","scorecard_created_at","scorecard_updated_at"):
                            if record[field] is None:
                                record[field] = previous[field]
                _upsert(conn, "golf_player_rounds", record, ("provider","tournament_id","player_id","round_id"), ROUND_FIELDS, completed_at, counts)
            if observe_finalization:
                conn.execute("UPDATE golf_entries SET result_finalized_observed_at=? WHERE provider=? AND tournament_id=? AND player_id=? AND result_finalized_observed_at IS NULL", (completed_at,PROVIDER,tid,entry["player_id"]))
            for key, response in responses.items():
                current = prior[key]
                changed = current is None or current["semantic_hash"] != hashes[key]
                # A changed representation with newer generation is accepted. A newer
                # header over identical Scottie data updates provenance only.
                raw, truncated = _bounded(response.body)
                if changed:
                    conn.execute("""INSERT INTO golf_sources(provider,endpoint_key,url,generated_raw,generated_at,last_modified,etag,semantic_hash,accepted_at,last_fetched_at,raw_response,raw_truncated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,endpoint_key) DO UPDATE SET
                    url=excluded.url,generated_raw=excluded.generated_raw,generated_at=excluded.generated_at,last_modified=excluded.last_modified,etag=excluded.etag,semantic_hash=excluded.semantic_hash,accepted_at=excluded.accepted_at,last_fetched_at=excluded.last_fetched_at,raw_response=excluded.raw_response,raw_truncated=excluded.raw_truncated""",
                    (PROVIDER,scopes[key],response.url,response.generated_raw,response.generated_at,response.last_modified,response.etag,hashes[key],completed_at,completed_at,raw,truncated))
                    counts["sources_accepted"] += 1
                else:
                    conn.execute("""UPDATE golf_sources SET generated_raw=?,generated_at=?,last_fetched_at=?,last_modified=?,etag=?,raw_response=?,raw_truncated=? WHERE provider=? AND endpoint_key=?""",(response.generated_raw,response.generated_at,completed_at,response.last_modified,response.etag,raw,truncated,PROVIDER,scopes[key]))
                    counts["sources_no_change"] += 1
            conn.execute("INSERT INTO golf_fetches(provider,entity,started_at,completed_at,outcome,tournament_id,endpoints_count,inserted_count,updated_count,no_change_count) VALUES(?,?,?,?,?,?,?,?,?,?)",(PROVIDER,ENTITY,started_at,completed_at,"success",tid,len(responses),counts["inserted"],counts["updated"],counts["no_change"]))
            conn.execute("DELETE FROM golf_fetches WHERE id NOT IN (SELECT id FROM golf_fetches ORDER BY id DESC LIMIT ?)",(FETCH_LIMIT,))
    return counts


def _upsert(conn: sqlite3.Connection, table: str, record: dict[str, Any], keys: tuple[str,...], fields: tuple[str,...], now: str, counts: dict[str,int]) -> None:
    where=" AND ".join(f"{k}=?" for k in keys)
    existing=conn.execute(f"SELECT * FROM {table} WHERE {where}",tuple(record[k] for k in keys)).fetchone()
    if existing is None:
        columns=list(record)+["first_seen_at","last_changed_at"]
        conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",tuple(record.values())+(now,now))
        counts["inserted"]+=1
    elif any(existing[field] != record[field] for field in fields):
        assignments=",".join(f"{field}=?" for field in fields)+",last_changed_at=?"
        conn.execute(f"UPDATE {table} SET {assignments} WHERE {where}",tuple(record[field] for field in fields)+(now,)+tuple(record[k] for k in keys))
        counts["updated"]+=1
    else:
        counts["no_change"]+=1


def load_golf_state(path: Path) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    if not path.exists():
        raise StorageError(f"database does not exist: {path}")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro",uri=True)) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("BEGIN")
        latest=conn.execute("SELECT * FROM golf_fetches WHERE outcome='success' ORDER BY id DESC LIMIT 1").fetchone()
        if latest is None:
            raise StorageError("database contains no successful Scottie ingestion")
        tournaments=[dict(r) for r in conn.execute("SELECT * FROM golf_tournaments WHERE provider=? ORDER BY start_date,tournament_id",(PROVIDER,))]
        for tournament in tournaments:
            tid=tournament["tournament_id"]
            entry=conn.execute("SELECT * FROM golf_entries WHERE provider=? AND tournament_id=?",(PROVIDER,tid)).fetchone()
            tournament["entry"]=dict(entry) if entry is not None else None
            if tournament["entry"] is not None:
                # Read-only clients may inspect a pre-migration database.
                tournament["entry"].setdefault("result_finalized_observed_at", None)
            tournament["rounds"]=[dict(r) for r in conn.execute("SELECT * FROM golf_player_rounds WHERE provider=? AND tournament_id=? ORDER BY number",(PROVIDER,tid))]
            sources=conn.execute("SELECT endpoint_key,url,generated_at,accepted_at,last_fetched_at FROM golf_sources WHERE provider=? AND (endpoint_key=? OR endpoint_key=? OR endpoint_key LIKE ?)",(PROVIDER,f"summary:{tid}",f"leaderboard:{tid}",f"tees:{tid}:%")).fetchall()
            tournament["sources"]={r["endpoint_key"]:dict(r) for r in sources}
        conn.rollback()
    return tournaments,dict(latest)


def inspect_golf_state(path: Path) -> dict[str,Any]:
    tournaments,latest=load_golf_state(path)
    return {"entity":ENTITY,"provider":PROVIDER,"tournaments":tournaments,"latest_fetch":latest}

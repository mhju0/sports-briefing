from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
from typing import Sequence
import sqlite3
import time

from .briefing import BriefingError, build_arsenal_briefing
from .football_data import (
    NormalizationError,
    ProviderError,
    fetch_arsenal_matches,
    normalize_matches,
)
from .storage import (
    StorageError,
    initialize_database,
    inspect_state,
    persist_successful_fetch,
    record_failed_fetch,
)
from .nfl.briefing import build_texans_briefing
from .nfl.game_policy import is_upcoming_game_status
from .nfl.sportradar import (
    NormalizationError as NFLNormalizationError,
    ProviderError as NFLProviderError,
    fetch_schedule,
    fetch_weekly_injuries,
    injuries_url,
    normalize_injuries,
    normalize_schedule,
    NFLGame,
    schedule_url,
)
from .nfl.storage import (
    initialize_nfl_database,
    inspect_texans_state,
    persist_texans_fetch,
    record_failed_texans_fetch,
)


LOGGER = logging.getLogger("sports_briefing")
DEFAULT_DATABASE = Path("data/sports_briefing.sqlite3")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        if args.command == "ingest":
            result = _ingest_arsenal(args) if args.entity == "arsenal" else _ingest_texans(args)
        elif args.command == "briefing":
            if args.entity == "arsenal":
                result = build_arsenal_briefing(
                    args.db, as_of=args.as_of, hide_results=args.hide_results
                )
            else:
                result = build_texans_briefing(args.db, as_of=args.as_of)
            LOGGER.info(
                "briefing_generated entity=%s as_of=%s",
                args.entity,
                result["as_of"],
            )
        else:
            result = inspect_state(args.db) if args.entity == "arsenal" else inspect_texans_state(args.db)
    except (
        ProviderError,
        NFLProviderError,
        NormalizationError,
        NFLNormalizationError,
        StorageError,
        BriefingError,
        ValueError,
        sqlite3.Error,
        OSError,
    ) as exc:
        LOGGER.error("command_failed stage=%s error=%s", _stage(exc), exc)
        print(f"{_stage(exc)} failure: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _ingest_arsenal(args: argparse.Namespace) -> dict[str, object]:
    if any(value is not None for value in (args.season, args.season_type, args.week)):
        raise ValueError("--season, --season-type, and --week apply only to Texans ingestion")
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    if not api_key:
        raise ValueError("FOOTBALL_DATA_API_KEY is required")
    date_from, date_to = _date_window(args.date_from, args.date_to)
    initialize_database(args.db)
    started_at = _now()
    expected_url = (
        f"https://api.football-data.org/v4/teams/57/matches?"
        f"dateFrom={date_from}&dateTo={date_to}&limit=500"
    )
    LOGGER.info(
        "fetch_start provider=football-data.org entity=arsenal from=%s to_exclusive=%s",
        date_from,
        date_to,
    )
    try:
        response = fetch_arsenal_matches(api_key, date_from, date_to, timeout=args.timeout)
    except ProviderError as exc:
        completed_at = _now()
        LOGGER.error("provider_failure entity=arsenal status=%s error=%s", exc.status, exc)
        record_failed_fetch(
            args.db,
            request_url=expected_url,
            date_from=date_from,
            date_to=date_to,
            started_at=started_at,
            completed_at=completed_at,
            http_status=exc.status,
            outcome="provider_failure",
            error_stage="provider",
            error_message=str(exc),
            raw_response=exc.body,
        )
        raise
    completed_at = _now()
    LOGGER.info(
        "fetch_end provider=football-data.org entity=arsenal status=%s bytes=%s",
        response.status,
        len(response.body.encode("utf-8")),
    )
    try:
        fixtures, ignored = normalize_matches(response.payload)
    except NormalizationError as exc:
        LOGGER.error("normalization_failure entity=arsenal error=%s", exc)
        record_failed_fetch(
            args.db,
            request_url=response.url,
            date_from=date_from,
            date_to=date_to,
            started_at=started_at,
            completed_at=completed_at,
            http_status=response.status,
            outcome="normalization_failure",
            error_stage="normalization",
            error_message=str(exc),
            raw_response=response.body,
        )
        raise
    counts = persist_successful_fetch(
        args.db,
        request_url=response.url,
        date_from=date_from,
        date_to=date_to,
        started_at=started_at,
        completed_at=completed_at,
        http_status=response.status,
        raw_response=response.body,
        received_count=len(response.payload["matches"]),
        fixtures=fixtures,
        filtered_unsupported_count=ignored,
    )
    LOGGER.info(
        "persistence_complete entity=arsenal inserted=%s updated=%s no_change=%s filtered=%s",
        counts["inserted"],
        counts["updated"],
        counts["no_change"],
        ignored,
    )
    return {
        "entity": "arsenal",
        "provider": "football-data.org",
        "window": {"from": date_from, "to_exclusive": date_to},
        "received": len(response.payload["matches"]),
        "supported": len(fixtures),
        "filtered_unsupported": ignored,
        "outcomes": counts,
        "fetched_at": completed_at,
    }


def _ingest_texans(args: argparse.Namespace) -> dict[str, object]:
    api_key = os.environ.get("SPORTRADAR_API_KEY")
    if not api_key:
        raise ValueError("SPORTRADAR_API_KEY is required")
    explicit = (args.season, args.season_type, args.week)
    if any(value is not None for value in explicit) and not all(value is not None for value in explicit):
        raise ValueError("--season, --season-type, and --week must be provided together")
    if args.date_from is not None or args.date_to is not None:
        raise ValueError("--from and --to apply only to Arsenal ingestion")
    initialize_nfl_database(args.db)
    started_at = _now()
    schedule_request_url = schedule_url(args.season, args.season_type)
    injuries_request_url: str | None = None
    schedule_response = None
    injury_response = None
    LOGGER.info("fetch_start provider=sportradar entity=texans source=schedule")
    schedule_started = time.monotonic()
    try:
        schedule_response = fetch_schedule(
            api_key,
            season_year=args.season,
            season_type=args.season_type,
            timeout=args.timeout,
        )
        schedule = normalize_schedule(schedule_response.payload)
        if args.season is not None and (
            schedule.season_year,
            schedule.season_type,
        ) != (args.season, args.season_type):
            raise NFLNormalizationError(
                "schedule response season does not match the requested season"
            )
        target_game = _target_texans_game(
            schedule.games, schedule.deleted_game_ids, args.week
        )
        injuries_request_url = injuries_url(
            schedule.season_year, schedule.season_type, target_game.week
        )
        LOGGER.info(
            "fetch_end provider=sportradar entity=texans source=schedule status=%s bytes=%s revision=%s",
            schedule_response.status,
            len(schedule_response.body.encode("utf-8")),
            schedule_response.generated_at,
        )
        wait = 1.05 - (time.monotonic() - schedule_started)
        if wait > 0:
            time.sleep(wait)
        LOGGER.info(
            "fetch_start provider=sportradar entity=texans source=weekly_injuries season=%s type=%s week=%s",
            schedule.season_year,
            schedule.season_type,
            target_game.week,
        )
        injury_response = fetch_weekly_injuries(
            api_key,
            season_year=schedule.season_year,
            season_type=schedule.season_type,
            week=target_game.week,
            timeout=args.timeout,
        )
        injuries = normalize_injuries(injury_response.payload)
        if (
            injuries.season_year,
            injuries.season_type,
            injuries.week,
            injuries.week_id,
        ) != (
            schedule.season_year,
            schedule.season_type,
            target_game.week,
            target_game.week_id,
        ):
            raise NFLNormalizationError(
                "weekly injury response scope does not match the requested Texans game"
            )
        LOGGER.info(
            "fetch_end provider=sportradar entity=texans source=weekly_injuries status=%s bytes=%s revision=%s",
            injury_response.status,
            len(injury_response.body.encode("utf-8")),
            injury_response.generated_at,
        )
    except (NFLProviderError, NFLNormalizationError) as exc:
        completed_at = _now()
        stage = "provider" if isinstance(exc, NFLProviderError) else "normalization"
        LOGGER.error("%s_failure entity=texans error=%s", stage, exc)
        record_failed_texans_fetch(
            args.db,
            schedule_url=schedule_request_url,
            injuries_url=injuries_request_url,
            started_at=started_at,
            completed_at=completed_at,
            outcome=f"{stage}_failure",
            error_stage=stage,
            error_message=str(exc),
            http_status=getattr(exc, "status", None),
            schedule_generated_at=getattr(schedule_response, "generated_at", None),
            schedule_raw=(
                getattr(schedule_response, "body", None)
                if schedule_response is not None
                else getattr(exc, "body", None)
            ),
            injuries_raw=(
                getattr(injury_response, "body", None)
                if injury_response is not None
                else getattr(exc, "body", None) if schedule_response is not None else None
            ),
        )
        raise
    completed_at = _now()
    try:
        counts = persist_texans_fetch(
            args.db,
            schedule=schedule,
            injuries=injuries,
            schedule_url=schedule_response.url,
            injuries_url=injury_response.url,
            schedule_generated_at=schedule_response.generated_at,
            injuries_generated_at=injury_response.generated_at,
            schedule_raw=schedule_response.body,
            injuries_raw=injury_response.body,
            started_at=started_at,
            completed_at=completed_at,
            http_status=injury_response.status,
        )
    except (StorageError, sqlite3.Error) as exc:
        LOGGER.error("persistence_failure entity=texans error=%s", exc)
        record_failed_texans_fetch(
            args.db,
            schedule_url=schedule_response.url,
            injuries_url=injury_response.url,
            started_at=started_at,
            completed_at=completed_at,
            outcome="persistence_failure",
            error_stage="persistence",
            error_message=str(exc),
            http_status=injury_response.status,
            schedule_generated_at=schedule_response.generated_at,
            injuries_generated_at=injury_response.generated_at,
            schedule_raw=schedule_response.body,
            injuries_raw=injury_response.body,
        )
        raise
    LOGGER.info(
        "persistence_complete entity=texans games_inserted=%s games_updated=%s availability_inserted=%s availability_updated=%s changes=%s",
        counts["games_inserted"], counts["games_updated"], counts["availability_inserted"],
        counts["availability_updated"], counts["changes"],
    )
    return {
        "entity": "texans",
        "provider": "sportradar",
        "scope": {"season": injuries.season_year, "type": injuries.season_type, "week": injuries.week},
        "outcomes": counts,
        "fetched_at": completed_at,
        "provider_revisions": {
            "schedule": schedule_response.generated_at,
            "injuries": injury_response.generated_at,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sports_briefing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="fetch and persist provider data")
    ingest.add_argument("entity", choices=("arsenal", "texans"))
    ingest.add_argument("--from", dest="date_from", type=_iso_date)
    ingest.add_argument("--to", dest="date_to", type=_iso_date, help="exclusive end date")
    ingest.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    ingest.add_argument("--timeout", type=_positive_float, default=15.0)
    ingest.add_argument("--season", type=int)
    ingest.add_argument("--season-type", choices=("PRE", "REG", "PST"))
    ingest.add_argument("--week", type=_positive_int)

    briefing = subparsers.add_parser("briefing", help="derive a deterministic briefing")
    briefing.add_argument("entity", choices=("arsenal", "texans"))
    briefing.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    briefing.add_argument("--as-of", help="ISO-8601 timestamp; defaults to the last successful fetch")
    briefing.add_argument("--hide-results", action="store_true")

    inspect = subparsers.add_parser("inspect", help="inspect normalized persisted state")
    inspect.add_argument("entity", choices=("arsenal", "texans"))
    inspect.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    return parser


def _date_window(date_from: date | None, date_to: date | None) -> tuple[str, str]:
    if (date_from is None) != (date_to is None):
        raise ValueError("--from and --to must be provided together")
    if date_from is None:
        today = datetime.now(timezone.utc).date()
        date_from = today - timedelta(days=30)
        date_to = today + timedelta(days=90)
    assert date_to is not None
    if date_from >= date_to:
        raise ValueError("--from must be earlier than exclusive --to")
    return date_from.isoformat(), date_to.isoformat()


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _target_texans_game(
    games: Sequence[NFLGame],
    deleted_game_ids: Sequence[str],
    requested_week: int | None,
) -> NFLGame:
    available = [game for game in games if game.provider_game_id not in deleted_game_ids]
    if requested_week is not None:
        matching = [game for game in available if game.week == requested_week]
        if len(matching) != 1:
            raise NFLNormalizationError(
                f"schedule must contain exactly one Texans game for week {requested_week}"
            )
        return matching[0]
    now = datetime.now(timezone.utc)
    upcoming = [
        game
        for game in available
        if datetime.fromisoformat(game.scheduled_utc.replace("Z", "+00:00")) >= now
        and is_upcoming_game_status(game.status)
    ]
    if not upcoming:
        raise NFLNormalizationError("schedule contains no upcoming Houston Texans game")
    return min(
        upcoming,
        key=lambda game: (
            datetime.fromisoformat(game.scheduled_utc.replace("Z", "+00:00")),
            game.provider_game_id,
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stage(exc: Exception) -> str:
    if isinstance(exc, (ProviderError, NFLProviderError)):
        return "provider"
    if isinstance(exc, (NormalizationError, NFLNormalizationError)):
        return "normalization"
    if isinstance(exc, StorageError):
        return "persistence"
    if isinstance(exc, BriefingError):
        return "briefing"
    if isinstance(exc, (sqlite3.Error, OSError)):
        return "persistence"
    return "configuration"

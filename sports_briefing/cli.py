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


LOGGER = logging.getLogger("sports_briefing")
DEFAULT_DATABASE = Path("data/sports_briefing.sqlite3")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        if args.command == "ingest":
            result = _ingest(args)
        elif args.command == "briefing":
            result = build_arsenal_briefing(
                args.db, as_of=args.as_of, hide_results=args.hide_results
            )
            LOGGER.info(
                "briefing_generated entity=arsenal as_of=%s spoiler_mode=%s",
                result["as_of"],
                result["spoiler_mode"],
            )
        else:
            result = inspect_state(args.db)
    except (
        ProviderError,
        NormalizationError,
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


def _ingest(args: argparse.Namespace) -> dict[str, object]:
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sports_briefing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="fetch and persist provider data")
    ingest.add_argument("entity", choices=("arsenal",))
    ingest.add_argument("--from", dest="date_from", type=_iso_date)
    ingest.add_argument("--to", dest="date_to", type=_iso_date, help="exclusive end date")
    ingest.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    ingest.add_argument("--timeout", type=_positive_float, default=15.0)

    briefing = subparsers.add_parser("briefing", help="derive a deterministic briefing")
    briefing.add_argument("entity", choices=("arsenal",))
    briefing.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    briefing.add_argument("--as-of", help="ISO-8601 timestamp; defaults to the last successful fetch")
    briefing.add_argument("--hide-results", action="store_true")

    inspect = subparsers.add_parser("inspect", help="inspect normalized persisted state")
    inspect.add_argument("entity", choices=("arsenal",))
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stage(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return "provider"
    if isinstance(exc, NormalizationError):
        return "normalization"
    if isinstance(exc, StorageError):
        return "persistence"
    if isinstance(exc, BriefingError):
        return "briefing"
    if isinstance(exc, (sqlite3.Error, OSError)):
        return "persistence"
    return "configuration"

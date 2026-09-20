from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..briefing import BriefingError
from .storage import load_texans_briefing_state


SPORTRADAR_ATTRIBUTION = "NFL data provided by Sportradar"
UPCOMING_STATUSES = frozenset({"scheduled", "created", "time-tbd", "flex-schedule"})


def build_texans_briefing(database: Path, *, as_of: str | None = None) -> dict[str, Any]:
    normalized_as_of = _timestamp(as_of, "--as-of") if as_of else None
    games, availability, changes, revisions, effective_as_of, fetch = load_texans_briefing_state(
        database, normalized_as_of
    )
    as_of_time = _parse_timestamp(effective_as_of, "briefing as-of time")
    upcoming = [
        game
        for game in games
        if game["status"].lower() in UPCOMING_STATUSES
        and _parse_timestamp(game["scheduled_utc"], "game scheduled time") >= as_of_time
    ]
    next_game = min(upcoming, key=_game_key, default=None)
    if next_game is None:
        scoped_availability: list[dict[str, Any]] = []
        scoped_changes: list[dict[str, Any]] = []
        report = {"available": False, "scope": None, "provider_generated_at": None, "report_date": None}
    else:
        scope = (next_game["season_year"], next_game["season_type"], next_game["week"])
        revision_key = f"injuries:{scope[0]}:{scope[1]}:{scope[2]}"
        revision = revisions.get(revision_key)
        scoped_availability = [
            _availability(item)
            for item in availability
            if revision is not None
            and (item["season_year"], item["season_type"], item["week"]) == scope
            and item["is_present"]
        ]
        scoped_changes = [
            _change(item)
            for item in changes
            if revision is not None
            and (item["season_year"], item["season_type"], item["week"]) == scope
        ][:20]
        report = {
            "available": revision is not None,
            "scope": {"season": scope[0], "type": scope[1], "week": scope[2]},
            "provider_generated_at": revision["provider_generated_at"] if revision else None,
            "report_date": revision["report_date"] if revision else None,
        }
    return {
        "entity": "Houston Texans",
        "as_of": effective_as_of,
        "next_game": _game(next_game),
        "availability": scoped_availability,
        "changes": scoped_changes,
        "availability_report": report,
        "source": {
            "provider": fetch["provider"],
            "attribution": SPORTRADAR_ATTRIBUTION,
            "fetched_at": fetch["completed_at"],
            "schedule_generated_at": fetch["schedule_generated_at"],
            "injuries_generated_at": report["provider_generated_at"],
        },
    }


def _game(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "provider_game_id": row["provider_game_id"],
        "season_year": row["season_year"],
        "season_type": row["season_type"],
        "week": row["week"],
        "scheduled_utc": row["scheduled_utc"],
        "status": row["status"],
        "home_team": row["home_team_name"],
        "away_team": row["away_team_name"],
        "provider_generated_at": row["provider_generated_at"],
    }


def _availability(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row["player_id"],
        "player_name": row["player_name"],
        "position": row["position"],
        "practice_status": row["practice_status"],
        "game_status": row["game_status"],
        "injury": row["injury"],
        "status_date": row["status_date"],
        "provider_generated_at": row["provider_generated_at"],
    }


def _change(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "player_id": row["player_id"],
        "player_name": row["player_name"],
        "change_type": row["change_type"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "provider_generated_at": row["provider_generated_at"],
        "report_date": row["report_date"],
    }


def _game_key(row: dict[str, Any]) -> tuple[datetime, str]:
    return _parse_timestamp(row["scheduled_utc"], "game scheduled time"), row["provider_game_id"]


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BriefingError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise BriefingError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: str, label: str) -> str:
    return _parse_timestamp(value, label).isoformat().replace("+00:00", "Z")

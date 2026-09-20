from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .storage import load_briefing_state


COMPLETED_STATUSES = frozenset({"FINISHED", "AWARDED"})
UPCOMING_STATUSES = frozenset({"SCHEDULED", "TIMED", "POSTPONED", "SUSPENDED"})


class BriefingError(Exception):
    pass


def build_arsenal_briefing(
    database: Path,
    *,
    as_of: str | None = None,
    hide_results: bool = False,
) -> dict[str, Any]:
    normalized_as_of = _timestamp(as_of, "--as-of") if as_of else None
    fixtures, effective_as_of, fetch = load_briefing_state(database, normalized_as_of)
    as_of_dt = _parse_timestamp(effective_as_of, "briefing as-of time")

    completed = [
        row
        for row in fixtures
        if row["status"] in COMPLETED_STATUSES
        and _parse_timestamp(row["kickoff_utc"], "fixture kickoff") <= as_of_dt
    ]
    upcoming = [
        row
        for row in fixtures
        if row["status"] in UPCOMING_STATUSES
        and _parse_timestamp(row["kickoff_utc"], "fixture kickoff") >= as_of_dt
    ]
    latest = max(completed, key=lambda row: (row["kickoff_utc"], row["provider_match_id"]), default=None)
    next_match = min(upcoming, key=lambda row: (row["kickoff_utc"], row["provider_match_id"]), default=None)

    return {
        "entity": "Arsenal",
        "as_of": effective_as_of,
        "spoiler_mode": "hide_results" if hide_results else "show_results",
        "next_match": _match_projection(next_match, include_result=False),
        "latest_completed_match": _completed_projection(latest, hide_results),
        "source": {
            "provider": fetch["provider"],
            "fetched_at": fetch["completed_at"],
            "window": {"from": fetch["date_from"], "to_exclusive": fetch["date_to"]},
        },
    }


def _match_projection(row: dict[str, Any] | None, *, include_result: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    result = {
        "provider_match_id": row["provider_match_id"],
        "competition_code": row["competition_code"],
        "competition_name": row["competition_name"],
        "kickoff_utc": row["kickoff_utc"],
        "status": row["status"],
        "home_team": row["home_team_name"],
        "away_team": row["away_team_name"],
        "provider_updated_at": row["provider_updated_at"],
        "source": {
            "provider": row["provider"],
            "fetched_at": row["last_seen_at"],
            "url": row["source_url"],
        },
    }
    if include_result:
        try:
            score = json.loads(row["score_json"])
        except json.JSONDecodeError as exc:
            raise BriefingError(
                f"stored score is invalid for provider match {row['provider_match_id']}"
            ) from exc
        result["score"] = score.get("fullTime")
        result["score_duration"] = row["score_duration"]
        result["winner"] = row["winner"]
    return result


def _completed_projection(row: dict[str, Any] | None, hide_results: bool) -> dict[str, Any] | None:
    projected = _match_projection(row, include_result=not hide_results)
    if projected is not None and hide_results:
        projected["result_hidden"] = True
    return projected


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

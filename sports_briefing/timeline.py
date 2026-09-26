from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .storage import StorageError


class TimelineError(Exception):
    pass


class TimelineTier(IntEnum):
    LIVE = 0
    IMMINENT = 1
    MEANINGFUL_CHANGE = 2
    RECENT_RESULT = 3
    ROUTINE = 4

    @property
    def reason(self) -> str:
        return {
            self.LIVE: "live",
            self.IMMINENT: "starts_soon",
            self.MEANINGFUL_CHANGE: "meaningful_status_change",
            self.RECENT_RESULT: "recent_result",
            self.ROUTINE: "upcoming_context",
        }[self]


@dataclass(frozen=True)
class TimelineCandidate:
    stable_id: str
    entity_id: str
    entity_name: str
    sport: str
    item_type: str
    event_state: str
    tier: TimelineTier
    title: str
    summary: str
    event_time: str | None
    change_time: str | None
    competition: dict[str, str] | None
    source_provider: str
    source_attribution: str
    source_generated_at: str
    source_observed_at: str
    source_record_id: str
    result_hidden: bool = False
    result: dict[str, Any] | None = None

    @property
    def reason(self) -> str:
        return self.tier.reason


def rank_candidates(
    candidates: Iterable[TimelineCandidate],
    *,
    as_of: datetime,
    limit_per_entity: int = 2,
) -> list[TimelineCandidate]:
    if as_of.tzinfo is None:
        raise TimelineError("timeline as-of time must include a timezone")
    if not 0 <= limit_per_entity <= 2:
        raise TimelineError("per-entity limit must be between 0 and 2")
    normalized_as_of = as_of.astimezone(timezone.utc)
    unique: dict[str, TimelineCandidate] = {}
    for item in candidates:
        if item.stable_id in unique and unique[item.stable_id] != item:
            raise TimelineError(f"conflicting timeline candidate identity: {item.stable_id}")
        unique[item.stable_id] = item
    ranked = sorted(unique.values(), key=lambda item: _ranking_key(item, normalized_as_of))
    selected: list[TimelineCandidate] = []
    counts: dict[str, int] = {}
    for item in ranked:
        count = counts.get(item.entity_id, 0)
        if count >= limit_per_entity:
            continue
        selected.append(item)
        counts[item.entity_id] = count + 1
    return selected


def build_home_timeline(
    database: Path,
    *,
    as_of: str | None = None,
    hide_results: bool = True,
    limit_per_entity: int = 2,
) -> dict[str, Any]:
    evaluation_time = (
        _parse_timestamp(as_of, "timeline as-of time")
        if as_of is not None
        else datetime.now(timezone.utc)
    )
    from .arsenal_timeline import load_arsenal_timeline_candidates
    from .nfl.timeline import load_texans_timeline_candidates
    from .golf.timeline import load_golf_timeline_candidates
    from .news.timeline import load_news_timeline_candidates

    candidates: list[TimelineCandidate] = []
    unavailable: list[str] = []
    for entity_id, loader in (
        ("arsenal", load_arsenal_timeline_candidates),
        ("texans", load_texans_timeline_candidates),
        ("scheffler", load_golf_timeline_candidates),
    ):
        try:
            candidates.extend(loader(database, evaluation_time, hide_results=hide_results))
        except (StorageError, sqlite3.Error, OSError) as exc:
            if _is_missing_state(entity_id, exc):
                unavailable.append(entity_id)
                continue
            raise
    candidates.extend(load_news_timeline_candidates(database, evaluation_time, hide_results=hide_results))
    if any(item.entity_id == "texans" for item in candidates) and "texans" in unavailable:
        unavailable.remove("texans")
    ranked = rank_candidates(
        candidates,
        as_of=evaluation_time,
        limit_per_entity=limit_per_entity,
    )
    return {
        "as_of": _format_timestamp(evaluation_time),
        "spoiler_mode": "hide_results" if hide_results else "show_results",
        "items": [_project_candidate(item) for item in ranked],
        "unavailable_entities": unavailable,
    }


def _project_candidate(candidate: TimelineCandidate) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "id": candidate.stable_id,
        "entity": {"id": candidate.entity_id, "name": candidate.entity_name},
        "sport": candidate.sport,
        "type": candidate.item_type,
        "state": candidate.event_state,
        "tier": candidate.tier.name.lower(),
        "reason": candidate.reason,
        "title": candidate.title,
        "summary": candidate.summary,
        "event_time": candidate.event_time,
        "change_time": candidate.change_time,
        "competition": candidate.competition,
        "source": {
            "provider": candidate.source_provider,
            "attribution": candidate.source_attribution,
            "generated_at": candidate.source_generated_at,
            "observed_at": candidate.source_observed_at,
            "record_id": candidate.source_record_id,
        },
    }
    if candidate.result_hidden:
        projected["result_hidden"] = True
    if candidate.result is not None:
        projected["result"] = candidate.result
    return projected


def _ranking_key(candidate: TimelineCandidate, as_of: datetime) -> tuple[object, ...]:
    reference = candidate.change_time or candidate.event_time
    if reference is None:
        raise TimelineError(f"timeline candidate {candidate.stable_id} has no ranking time")
    instant = _parse_timestamp(reference, f"timeline candidate {candidate.stable_id} time")
    if candidate.tier in (TimelineTier.LIVE, TimelineTier.IMMINENT, TimelineTier.ROUTINE):
        temporal = abs((instant - as_of).total_seconds())
    else:
        temporal = max(0.0, (as_of - instant).total_seconds())
    return (
        int(candidate.tier),
        temporal,
        candidate.entity_id,
        candidate.stable_id,
    )


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise TimelineError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise TimelineError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_missing_state(entity_id: str, error: Exception) -> bool:
    message = str(error)
    if message.startswith("database does not exist:"):
        return True
    if entity_id == "arsenal":
        return message in {
            "database contains no successful Arsenal ingestion",
            "no such table: provider_fetches",
        }
    if entity_id == "texans":
        return message in {
            "database contains no successful Texans ingestion",
            "no such table: nfl_fetches",
        }
    return message in {
        "database contains no successful Scottie ingestion",
        "no such table: golf_fetches",
    }

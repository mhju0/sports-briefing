from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any

from .briefing import COMPLETED_STATUSES, FOOTBALL_DATA_ATTRIBUTION
from .storage import load_briefing_state
from .timeline import TimelineCandidate, TimelineError, TimelineTier, _format_timestamp, _parse_timestamp


LIVE_STATUSES = frozenset({"IN_PLAY", "PAUSED"})
FIXED_UPCOMING_STATUSES = frozenset({"SCHEDULED", "TIMED"})
LIVE_KICKOFF_AGE = timedelta(hours=3)
LIVE_OBSERVATION_AGE = timedelta(minutes=30)
START_TOLERANCE = timedelta(minutes=15)
IMMINENT_WINDOW = timedelta(hours=24)
RECENT_RESULT_WINDOW = timedelta(hours=36)
ROUTINE_WINDOW = timedelta(days=7)


def load_arsenal_timeline_candidates(
    database: Path,
    as_of: datetime,
    *,
    hide_results: bool,
) -> list[TimelineCandidate]:
    fixtures, _, _ = load_briefing_state(database, _format_timestamp(as_of))
    return derive_arsenal_candidates(fixtures, as_of=as_of, hide_results=hide_results)


def derive_arsenal_candidates(
    fixtures: list[dict[str, Any]],
    *,
    as_of: datetime,
    hide_results: bool,
) -> list[TimelineCandidate]:
    candidates: list[TimelineCandidate] = []
    for fixture in fixtures:
        kickoff = _parse_timestamp(fixture["kickoff_utc"], "Arsenal fixture kickoff")
        observed = _parse_timestamp(fixture["last_seen_at"], "Arsenal fixture observation")
        until = kickoff - as_of
        status = fixture["status"]
        tier: TimelineTier | None = None
        state = "context"
        if (
            status in LIVE_STATUSES
            and -LIVE_KICKOFF_AGE <= until <= START_TOLERANCE
            and timedelta(0) <= as_of - observed <= LIVE_OBSERVATION_AGE
        ):
            tier, state = TimelineTier.LIVE, "LIVE"
        elif status in FIXED_UPCOMING_STATUSES and timedelta(0) <= until <= IMMINENT_WINDOW:
            tier, state = TimelineTier.IMMINENT, "PRE_GAME"
        elif (
            status in COMPLETED_STATUSES
            and timedelta(0) <= as_of - kickoff <= RECENT_RESULT_WINDOW
        ):
            tier, state = TimelineTier.RECENT_RESULT, "POST_GAME"
        elif status in FIXED_UPCOMING_STATUSES and timedelta(0) <= until <= ROUTINE_WINDOW:
            tier, state = TimelineTier.ROUTINE, "PRE_GAME"
        if tier is None:
            continue
        home, away = fixture["home_team_name"], fixture["away_team_name"]
        result = None
        result_hidden = tier is TimelineTier.RECENT_RESULT and hide_results
        if tier is TimelineTier.RECENT_RESULT and not hide_results:
            try:
                score = json.loads(fixture["score_json"])
            except json.JSONDecodeError as exc:
                raise TimelineError("stored Arsenal result is invalid JSON") from exc
            if not isinstance(score, dict):
                raise TimelineError("stored Arsenal result must be an object")
            result = {
                "full_time": score.get("fullTime"),
                "winner": fixture["winner"],
                "duration": fixture["score_duration"],
            }
        summary = f"{home} vs {away}"
        if tier is TimelineTier.LIVE:
            title = "Arsenal match is live"
        elif tier in (TimelineTier.IMMINENT, TimelineTier.ROUTINE):
            title = "Arsenal's next match"
        else:
            title = "Arsenal's recent result"
            if result_hidden:
                summary = f"{summary}. Result hidden."
        candidates.append(
            TimelineCandidate(
                stable_id=f"arsenal:match:{fixture['provider_match_id']}",
                entity_id="arsenal",
                entity_name="Arsenal",
                sport="football",
                item_type="match",
                event_state=state,
                tier=tier,
                title=title,
                summary=summary,
                event_time=_format_timestamp(kickoff),
                change_time=None,
                competition={
                    "code": fixture["competition_code"],
                    "name": fixture["competition_name"],
                },
                source_provider=fixture["provider"],
                source_attribution=FOOTBALL_DATA_ATTRIBUTION,
                source_generated_at=fixture["provider_updated_at"],
                source_observed_at=fixture["last_seen_at"],
                source_record_id=fixture["provider_match_id"],
                result_hidden=result_hidden,
                result=result,
                summary_facts=(("home_team", home), ("away_team", away)),
            )
        )
    live = [item for item in candidates if item.tier is TimelineTier.LIVE]
    upcoming = [
        item for item in candidates if item.tier in (TimelineTier.IMMINENT, TimelineTier.ROUTINE)
    ]
    recent = [item for item in candidates if item.tier is TimelineTier.RECENT_RESULT]
    selected: list[TimelineCandidate] = []
    if live:
        selected.append(
            min(
                live,
                key=lambda item: (
                    abs((_parse_timestamp(item.event_time or "", "live match time") - as_of).total_seconds()),
                    item.stable_id,
                ),
            )
        )
    if upcoming:
        selected.append(min(upcoming, key=lambda item: (item.event_time or "", item.stable_id)))
    if recent:
        selected.append(max(recent, key=lambda item: (item.event_time or "", item.stable_id)))
    return selected

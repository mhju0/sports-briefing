from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .briefing import SPORTRADAR_ATTRIBUTION
from .storage import load_texans_briefing_state
from ..timeline import TimelineCandidate, TimelineTier, _format_timestamp, _parse_timestamp


LIVE_STATUSES = frozenset({"inprogress", "halftime"})
FIXED_UPCOMING_STATUSES = frozenset({"scheduled", "created"})
COMPLETED_STATUSES = frozenset({"complete", "closed"})
LIVE_KICKOFF_AGE = timedelta(hours=6)
LIVE_OBSERVATION_AGE = timedelta(minutes=30)
START_TOLERANCE = timedelta(minutes=15)
IMMINENT_WINDOW = timedelta(hours=24)
CHANGE_WINDOW = timedelta(hours=48)
RECENT_RESULT_WINDOW = timedelta(hours=36)
ROUTINE_WINDOW = timedelta(days=7)
REPORT_MEMBERSHIP_CHANGES = frozenset({"NEW_REPORT", "REMOVED_FROM_REPORT"})


def load_texans_timeline_candidates(
    database: Path,
    as_of: datetime,
    *,
    hide_results: bool,
) -> list[TimelineCandidate]:
    del hide_results
    games, _, changes, _, _, fetch = load_texans_briefing_state(
        database, _format_timestamp(as_of)
    )
    return derive_texans_candidates(games, changes, fetch, as_of=as_of)


def derive_texans_candidates(
    games: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    fetch: dict[str, Any],
    *,
    as_of: datetime,
) -> list[TimelineCandidate]:
    candidates: list[TimelineCandidate] = []
    scoped_live_games: list[dict[str, Any]] = []
    scoped_upcoming_games: list[dict[str, Any]] = []
    for game in games:
        kickoff = _parse_timestamp(game["scheduled_utc"], "Texans game kickoff")
        observed = _parse_timestamp(game["last_seen_at"], "Texans game observation")
        until = kickoff - as_of
        status = game["status"].lower()
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
        elif status in COMPLETED_STATUSES and timedelta(0) <= as_of - kickoff <= RECENT_RESULT_WINDOW:
            tier, state = TimelineTier.RECENT_RESULT, "POST_GAME"
        elif status in FIXED_UPCOMING_STATUSES and timedelta(0) <= until <= ROUTINE_WINDOW:
            tier, state = TimelineTier.ROUTINE, "PRE_GAME"
        if (
            status in LIVE_STATUSES
            and -LIVE_KICKOFF_AGE <= until <= START_TOLERANCE
            and timedelta(0) <= as_of - observed <= LIVE_OBSERVATION_AGE
        ):
            scoped_live_games.append(game)
        elif status in FIXED_UPCOMING_STATUSES and timedelta(0) <= until <= ROUTINE_WINDOW:
            scoped_upcoming_games.append(game)
        if tier is None:
            continue
        home, away = game["home_team_name"], game["away_team_name"]
        if tier is TimelineTier.LIVE:
            title = "Texans game is live"
        elif tier in (TimelineTier.IMMINENT, TimelineTier.ROUTINE):
            title = "Texans' next game"
        else:
            title = "Texans' recent game"
        candidates.append(
            TimelineCandidate(
                stable_id=f"texans:game:{game['provider_game_id']}",
                entity_id="texans",
                entity_name="Houston Texans",
                sport="nfl",
                item_type="game",
                event_state=state,
                tier=tier,
                title=title,
                summary=f"{away} at {home}",
                event_time=_format_timestamp(kickoff),
                change_time=None,
                competition=None,
                source_provider=fetch["provider"],
                source_attribution=SPORTRADAR_ATTRIBUTION,
                source_generated_at=game["provider_generated_at"],
                source_observed_at=game["last_seen_at"],
                source_record_id=game["provider_game_id"],
                summary_facts=(("home_team", home), ("away_team", away)),
            )
        )

    live_games = [item for item in candidates if item.tier is TimelineTier.LIVE]
    upcoming_games = [
        item for item in candidates if item.tier in (TimelineTier.IMMINENT, TimelineTier.ROUTINE)
    ]
    recent_games = [item for item in candidates if item.tier is TimelineTier.RECENT_RESULT]
    selected_games: list[TimelineCandidate] = []
    if live_games:
        selected_games.append(
            min(
                live_games,
                key=lambda item: (
                    abs((_parse_timestamp(item.event_time or "", "live game time") - as_of).total_seconds()),
                    item.stable_id,
                ),
            )
        )
    if upcoming_games:
        selected_games.append(min(upcoming_games, key=lambda item: (item.event_time or "", item.stable_id)))
    if recent_games:
        selected_games.append(max(recent_games, key=lambda item: (item.event_time or "", item.stable_id)))

    relevant_game = None
    if scoped_live_games:
        relevant_game = min(scoped_live_games, key=lambda game: (game["scheduled_utc"], game["provider_game_id"]))
    elif scoped_upcoming_games:
        relevant_game = min(scoped_upcoming_games, key=lambda game: (game["scheduled_utc"], game["provider_game_id"]))
    relevant_scope = None
    if relevant_game is not None:
        relevant_scope = (
            relevant_game["season_year"], relevant_game["season_type"], relevant_game["week"]
        )

    by_scope: dict[tuple[int, str, int], list[dict[str, Any]]] = {}
    latest_fields: set[tuple[int, str, int, str, str]] = set()
    membership_boundaries: set[tuple[int, str, int, str]] = set()
    ordered_changes = sorted(
        changes,
        key=lambda row: (
            row["observed_at"], row["provider_generated_at"], row["player_id"], row["change_type"]
        ),
        reverse=True,
    )
    for change in ordered_changes:
        scope = (change["season_year"], change["season_type"], change["week"])
        if scope != relevant_scope:
            continue
        player_scope = (scope[0], scope[1], scope[2], change["player_id"])
        if player_scope in membership_boundaries:
            continue
        if change["change_type"] in REPORT_MEMBERSHIP_CHANGES:
            membership_boundaries.add(player_scope)
        field = (
            scope[0],
            scope[1],
            scope[2],
            change["player_id"],
            _change_field(change["change_type"]),
        )
        if field in latest_fields:
            continue
        latest_fields.add(field)
        observed = _parse_timestamp(change["observed_at"], "Texans change observation")
        generated = _parse_timestamp(change["provider_generated_at"], "Texans change provider time")
        if not (
            timedelta(0) <= as_of - observed <= CHANGE_WINDOW
            and timedelta(0) <= as_of - generated <= CHANGE_WINDOW
        ):
            continue
        if change["report_date"] is not None:
            report_date = _parse_timestamp(change["report_date"], "Texans change report date")
            if not timedelta(0) <= as_of - report_date <= CHANGE_WINDOW:
                continue
        by_scope.setdefault(scope, []).append(change)

    for scope, scoped_changes in by_scope.items():
        scoped_changes.sort(key=lambda row: (row["observed_at"], row["provider_generated_at"], row["player_id"], row["change_type"]), reverse=True)
        newest = scoped_changes[0]
        other_count = len(scoped_changes) - 1
        summary = _change_summary(newest)
        if other_count:
            summary = f"{summary}; {other_count} additional recent transition(s)"
        candidates.append(
            TimelineCandidate(
                stable_id=f"texans:availability:{scope[0]}:{scope[1]}:{scope[2]}:{newest['provider_generated_at']}",
                entity_id="texans",
                entity_name="Houston Texans",
                sport="nfl",
                item_type="availability_change",
                event_state="AVAILABILITY_CHANGE",
                tier=TimelineTier.MEANINGFUL_CHANGE,
                title="Texans availability changed",
                summary=summary,
                event_time=relevant_game["scheduled_utc"],
                change_time=newest["observed_at"],
                competition=None,
                source_provider=fetch["provider"],
                source_attribution=SPORTRADAR_ATTRIBUTION,
                source_generated_at=newest["provider_generated_at"],
                source_observed_at=newest["observed_at"],
                source_record_id=newest["change_key"],
                summary_facts=_change_facts(newest),
            )
        )
    return selected_games + [item for item in candidates if item.item_type == "availability_change"]


def _change_summary(change: dict[str, Any]) -> str:
    if change["change_type"] == "NEW_REPORT":
        return f"{change['player_name']}: newly on the injury report"
    if change["change_type"] == "REMOVED_FROM_REPORT":
        return f"{change['player_name']}: no longer listed in the latest report"
    old_value = change["old_value"] if change["old_value"] is not None else "unknown"
    new_value = change["new_value"] if change["new_value"] is not None else "unknown"
    return f"{change['player_name']}: {old_value} → {new_value}"


def _change_facts(change: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    facts = [("player", change["player_name"])]
    status_type = {
        "PRACTICE_STATUS_CHANGED": "practice_status",
        "GAME_STATUS_CHANGED": "game_status",
    }.get(change["change_type"])
    if status_type is not None:
        facts.append(("status_type", status_type))
        if change["old_value"] is not None:
            facts.append(("previous_status", change["old_value"]))
        if change["new_value"] is not None:
            facts.append(("new_status", change["new_value"]))
    return tuple(facts)


def _change_field(change_type: str) -> str:
    if change_type in REPORT_MEMBERSHIP_CHANGES:
        return "REPORT_MEMBERSHIP"
    return change_type

"""Labelled synthetic demo candidates for public mode.

Demo state is generated in code relative to the UTC day of the evaluation time,
so nothing is seeded into SQLite and no provider row can collide with it. The
synthetic state passes through the unchanged Texans and Golf derivation rules,
so demo items obey the same freshness windows as provider items; only their
provenance is replaced.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from .golf.sportradar import SCOTTIE_ID
from .golf.timeline import derive_golf_candidates
from .nfl.timeline import derive_texans_candidates
from .timeline import TimelineCandidate, _format_timestamp


DEMO_PROVIDER = "synthetic-demo"
DEMO_ATTRIBUTION = "Demo data: synthetic, not from a sports-data provider"


def load_demo_texans_candidates(as_of: datetime, *, hide_results: bool) -> list[TimelineCandidate]:
    del hide_results
    anchor = _anchor(as_of)
    stamp = _format_timestamp(anchor - timedelta(hours=2))
    scope = {"season_year": anchor.year, "season_type": "REG", "week": 1}
    game = {
        **scope,
        "provider_game_id": "synthetic-demo-texans-game",
        "scheduled_utc": _format_timestamp(anchor + timedelta(days=3, hours=18)),
        "status": "scheduled",
        "home_team_name": "Houston Texans",
        "away_team_name": "Sample Opponent",
        "provider_generated_at": stamp,
        "last_seen_at": stamp,
    }
    change = {
        **scope,
        "player_id": "synthetic-demo-player",
        "player_name": "Sample Player",
        "change_type": "GAME_STATUS_CHANGED",
        "old_value": "Questionable",
        "new_value": "Out",
        "observed_at": stamp,
        "provider_generated_at": stamp,
        "report_date": None,
        "change_key": "synthetic-demo-texans-change",
    }
    candidates = derive_texans_candidates([game], [change], {"provider": DEMO_PROVIDER}, as_of=as_of)
    return [_label(item) for item in candidates]


def load_demo_scheffler_candidates(as_of: datetime, *, hide_results: bool) -> list[TimelineCandidate]:
    anchor = _anchor(as_of)
    stamp = _format_timestamp(anchor - timedelta(hours=6))
    completed_rounds = [
        {"round_id": f"synthetic-demo-completed-round-{number}", "number": number, "status": "closed",
         "thru": 18, "score": -3, "strokes": 69, "tee_time": None}
        for number in range(1, 5)
    ]
    completed = {
        "tournament_id": "synthetic-demo-completed-tournament",
        "name": "Sample Invitational",
        "status": "closed",
        "event_type": "stroke",
        "entry": {
            "player_id": SCOTTIE_ID, "field_confirmed": 1, "status": None,
            "position": 3, "tied": 0, "score": -12, "strokes": 276,
            "result_finalized_observed_at": stamp,
        },
        "rounds": completed_rounds,
        "sources": {"leaderboard:synthetic-demo-completed-tournament": {"generated_at": stamp, "accepted_at": stamp}},
    }
    upcoming = {
        "tournament_id": "synthetic-demo-upcoming-tournament",
        "name": "Sample Classic",
        "status": "scheduled",
        "event_type": "stroke",
        "entry": {
            "player_id": SCOTTIE_ID, "field_confirmed": 1, "status": None,
            "result_finalized_observed_at": None,
        },
        "rounds": [{
            "round_id": "synthetic-demo-upcoming-round-1", "number": 1, "status": "scheduled",
            "thru": 0, "score": 0, "strokes": 0,
            "tee_time": _format_timestamp(anchor + timedelta(days=2, hours=13)),
        }],
        "sources": {"tees:synthetic-demo-upcoming-tournament:1": {"generated_at": stamp, "accepted_at": stamp}},
    }
    candidates = derive_golf_candidates([completed, upcoming], as_of=as_of, hide_results=hide_results)
    return [_label(item) for item in candidates]


def _anchor(as_of: datetime) -> datetime:
    # Day-anchored times keep demo identities and timestamps stable within a UTC day.
    return as_of.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _label(candidate: TimelineCandidate) -> TimelineCandidate:
    return replace(
        candidate,
        title=f"{candidate.title} (demo)",
        summary=f"Demo data: {candidate.summary}",
        source_provider=DEMO_PROVIDER,
        source_attribution=DEMO_ATTRIBUTION,
        data_mode="demo",
    )

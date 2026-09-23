"""Conservative Scottie tee-time candidates from accepted structured state."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..timeline import TimelineCandidate, TimelineTier, _format_timestamp, _parse_timestamp
from .storage import _terminal_scottie_result, load_golf_state

IMMINENT = timedelta(hours=24)
ROUTINE = timedelta(days=7)
RECENT_RESULT = timedelta(hours=36)


def derive_golf_candidates(tournaments: list[dict[str,Any]], *, as_of: datetime, hide_results: bool) -> list[TimelineCandidate]:
    tee_candidates=[]
    recent_candidates=[]
    for tournament in tournaments:
        entry=tournament.get("entry")
        if not entry or entry["field_confirmed"] != 1 or entry["player_id"] != "6db3e736-d86d-4181-aa3b-651b8c1bfdc1":
            continue
        observed = entry.get("result_finalized_observed_at")
        if observed is not None and _terminal_scottie_result(tournament, entry, tournament["rounds"]):
            observed_time = _parse_timestamp(observed, "Scottie result observation")
            if timedelta(0) <= as_of - observed_time <= RECENT_RESULT:
                source = tournament.get("sources", {}).get(f"leaderboard:{tournament['tournament_id']}")
                if source is not None:
                    position = f"tied for position {entry['position']}" if entry["tied"] else f"position {entry['position']}"
                    summary = (
                        f"Final result available for {tournament['name']}."
                        if hide_results else
                        f"Scottie Scheffler finished {position} at {entry['score']:+d} "
                        f"({entry['strokes']} strokes) in {tournament['name']}."
                    )
                    recent_candidates.append(TimelineCandidate(
                        stable_id=f"scheffler:tournament:{tournament['tournament_id']}",entity_id="scheffler",entity_name="Scottie Scheffler",sport="golf",item_type="result",event_state="POST_TOURNAMENT",tier=TimelineTier.RECENT_RESULT,
                        title="Scottie Scheffler tournament result",summary=summary,
                        event_time=_format_timestamp(observed_time),change_time=None,competition={"code":"PGA","name":"PGA Tour"},
                        source_provider="sportradar",source_attribution="Sportradar Golf",source_generated_at=source["generated_at"],source_observed_at=source["accepted_at"],source_record_id=tournament["tournament_id"],result_hidden=hide_results,result=None,
                    ))
            continue
        if entry["status"] is not None or tournament["status"] != "scheduled":
            continue
        for round_state in tournament["rounds"]:
            if round_state["status"] != "scheduled" or round_state["tee_time"] is None:
                continue
            if (round_state["thru"] or 0)>0 or (round_state["strokes"] or 0)>0 or (round_state["score"] or 0)!=0:
                continue
            tee=_parse_timestamp(round_state["tee_time"],"Scottie tee time")
            remaining=tee-as_of
            if not timedelta(0)<=remaining<=ROUTINE:
                continue
            tier=TimelineTier.IMMINENT if remaining<=IMMINENT else TimelineTier.ROUTINE
            sources=tournament.get("sources",{})
            source=sources.get(f"tees:{tournament['tournament_id']}:{round_state['number']}")
            if source is None:
                continue
            tee_candidates.append(TimelineCandidate(
                stable_id=f"scheffler:tournament:{tournament['tournament_id']}",entity_id="scheffler",entity_name="Scottie Scheffler",sport="golf",item_type="tee_time",event_state="PRE_ROUND",tier=tier,
                title="Scottie Scheffler's next round",summary=f"Confirmed field entry for {tournament['name']}; round {round_state['number']} tee time.",
                event_time=_format_timestamp(tee),change_time=None,competition={"code":"PGA","name":"PGA Tour"},
                source_provider="sportradar",source_attribution="Sportradar Golf",source_generated_at=source["generated_at"],source_observed_at=source["accepted_at"],source_record_id=round_state["round_id"],result_hidden=False,result=None,
            ))
    next_tee = min(tee_candidates,key=lambda item:(item.event_time or "",item.stable_id)) if tee_candidates else None
    return recent_candidates + ([next_tee] if next_tee is not None else [])


def load_golf_timeline_candidates(database: Path, as_of: datetime, *, hide_results: bool) -> list[TimelineCandidate]:
    tournaments,_=load_golf_state(database)
    return derive_golf_candidates(tournaments,as_of=as_of,hide_results=hide_results)

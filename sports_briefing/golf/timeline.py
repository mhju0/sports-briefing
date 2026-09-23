"""Conservative Scottie tee-time candidates from accepted structured state."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..timeline import TimelineCandidate, TimelineTier, _format_timestamp, _parse_timestamp
from .storage import load_golf_state

IMMINENT = timedelta(hours=24)
ROUTINE = timedelta(days=7)


def derive_golf_candidates(tournaments: list[dict[str,Any]], *, as_of: datetime, hide_results: bool) -> list[TimelineCandidate]:
    candidates=[]
    for tournament in tournaments:
        entry=tournament.get("entry")
        if not entry or entry["field_confirmed"] != 1 or entry["player_id"] != "6db3e736-d86d-4181-aa3b-651b8c1bfdc1":
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
            candidates.append(TimelineCandidate(
                stable_id=f"scheffler:tournament:{tournament['tournament_id']}",entity_id="scheffler",entity_name="Scottie Scheffler",sport="golf",item_type="tee_time",event_state="PRE_ROUND",tier=tier,
                title="Scottie Scheffler's next round",summary=f"Confirmed field entry for {tournament['name']}; round {round_state['number']} tee time.",
                event_time=_format_timestamp(tee),change_time=None,competition={"code":"PGA","name":"PGA Tour"},
                source_provider="sportradar",source_attribution="Sportradar Golf",source_generated_at=source["generated_at"],source_observed_at=source["accepted_at"],source_record_id=round_state["round_id"],result_hidden=False,result=None,
            ))
    if not candidates:
        return []
    return [min(candidates,key=lambda item:(item.event_time or "",item.stable_id))]


def load_golf_timeline_candidates(database: Path, as_of: datetime, *, hide_results: bool) -> list[TimelineCandidate]:
    tournaments,_=load_golf_state(database)
    return derive_golf_candidates(tournaments,as_of=as_of,hide_results=hide_results)

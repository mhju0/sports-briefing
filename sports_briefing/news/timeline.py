"""Deterministic candidates from reviewed Texans development topics."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..timeline import TimelineCandidate, TimelineTier, _parse_timestamp
from .storage import load_news_topics


CHANGE_WINDOW = timedelta(hours=48)


def derive_news_candidates(topics: list[dict[str, Any]], *, as_of: datetime) -> list[TimelineCandidate]:
    eligible: list[TimelineCandidate] = []
    for topic in topics:
        published = topic["material_published_at"]
        if published is None:
            continue
        changed_at = _parse_timestamp(topic["meaningful_changed_at"], "news meaningful change")
        published_at = _parse_timestamp(published, "news material publication")
        if not (
            timedelta(0) <= as_of - changed_at <= CHANGE_WINDOW
            and timedelta(0) <= as_of - published_at <= CHANGE_WINDOW
        ):
            continue
        if topic["action"] != "placed_on_ir" or topic["entity_id"] != "texans":
            continue
        # An old dated transaction discovered through a newly published repeat is
        # historical context, even if an optional qualifier was newly reviewed.
        if not timedelta(0) <= (as_of.date() - date.fromisoformat(topic["effective_date"])) <= timedelta(days=7):
            continue
        qualifier = topic["placement_qualifier"]
        summary = f"{topic['subject_name']} was placed on Reserve/Injured on {topic['effective_date']}."
        if qualifier == "designated_for_return":
            summary += " The placement was designated for return."
        synthetic = topic["evidence_mode"] == "synthetic"
        eligible.append(TimelineCandidate(
            stable_id=f"news:{topic['topic_key']}",
            entity_id="texans", entity_name="Houston Texans", sport="nfl",
            item_type="official_development", event_state="ROSTER_CHANGE",
            tier=TimelineTier.MEANINGFUL_CHANGE,
            title="Texans roster development (synthetic)" if synthetic else "Texans roster development",
            summary=("Synthetic example: " if synthetic else "") + summary,
            event_time=None, change_time=topic["meaningful_changed_at"], competition=None,
            source_provider=topic["source_key"], source_attribution=topic["source_name"],
            source_generated_at=published, source_observed_at=topic["source_observed_at"],
            source_record_id=topic["material_url"], result=None,
        ))
    # A single latest development keeps news from filling both Texans slots.
    return sorted(eligible, key=lambda item: (item.change_time or "", item.stable_id), reverse=True)[:1]


def load_news_timeline_candidates(database: Path, as_of: datetime, *, hide_results: bool) -> list[TimelineCandidate]:
    del hide_results
    return derive_news_candidates(load_news_topics(database), as_of=as_of)

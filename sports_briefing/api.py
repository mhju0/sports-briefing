from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .briefing import BriefingError, build_arsenal_briefing
from .cli import default_database
from .storage import StorageError
from .nfl.briefing import build_texans_briefing
from .source_policy import entity_sources, public_mode_from_env
from .timeline import TimelineError, build_home_timeline


LOGGER = logging.getLogger("sports_briefing.api")


class HealthResponse(BaseModel):
    status: str


class MetaResponse(BaseModel):
    public_mode: bool
    version: str
    entities: dict[str, str]


class EntityResponse(BaseModel):
    id: str
    name: str


class CompetitionResponse(BaseModel):
    code: str
    name: str


class MatchProvenanceResponse(BaseModel):
    provider_updated_at: str
    observed_at: str


class MatchResponse(BaseModel):
    competition: CompetitionResponse
    kickoff_utc: str
    status: str
    home_team: str
    away_team: str
    provenance: MatchProvenanceResponse


class FullTimeResponse(BaseModel):
    home: int | None
    away: int | None


class ResultResponse(BaseModel):
    full_time: FullTimeResponse
    winner: str | None
    duration: str | None


class CompletedMatchResponse(MatchResponse):
    result_hidden: bool
    result: ResultResponse | None = None


class SpoilerResponse(BaseModel):
    results_hidden: bool


class SourceResponse(BaseModel):
    provider: str
    attribution: str
    checked_at: str


class ArsenalBriefingResponse(BaseModel):
    entity: EntityResponse
    headline: str
    summary: str
    reason_shown: str
    as_of: str
    spoiler: SpoilerResponse
    next_match: MatchResponse | None
    latest_completed_match: CompletedMatchResponse | None
    source: SourceResponse


class TexansGameResponse(BaseModel):
    provider_game_id: str
    season_year: int
    season_type: str
    week: int
    scheduled_utc: str
    status: str
    home_team: str
    away_team: str
    provider_generated_at: str


class TexansAvailabilityResponse(BaseModel):
    player_id: str
    player_name: str
    position: str | None
    practice_status: str | None
    game_status: str | None
    injury: str | None
    status_date: str | None
    provider_generated_at: str


class TexansChangeResponse(BaseModel):
    player_id: str
    player_name: str
    change_type: str
    old_value: str | None
    new_value: str | None
    provider_generated_at: str
    report_date: str | None


class AvailabilityScopeResponse(BaseModel):
    season: int
    type: str
    week: int


class AvailabilityReportResponse(BaseModel):
    available: bool
    scope: AvailabilityScopeResponse | None
    provider_generated_at: str | None
    report_date: str | None


class TexansSourceResponse(BaseModel):
    provider: str
    attribution: str
    checked_at: str
    schedule_generated_at: str
    injuries_generated_at: str | None


class TexansBriefingResponse(BaseModel):
    entity: EntityResponse
    headline: str
    summary: str
    reason_shown: str
    as_of: str
    next_game: TexansGameResponse | None
    availability_report: AvailabilityReportResponse
    availability: list[TexansAvailabilityResponse]
    changes: list[TexansChangeResponse]
    source: TexansSourceResponse


class TimelineSourceResponse(BaseModel):
    provider: str
    attribution: str
    generated_at: str
    observed_at: str
    record_id: str


class TimelineItemResponse(BaseModel):
    id: str
    entity: EntityResponse
    sport: str
    type: str
    state: str
    tier: str
    reason: str
    title: str
    summary: str
    event_time: str | None
    change_time: str | None
    competition: CompetitionResponse | None
    source: TimelineSourceResponse
    result_hidden: bool | None = None
    result: ResultResponse | None = None
    data_mode: str | None = None


class TimelineResponse(BaseModel):
    as_of: str
    spoiler_mode: str
    items: list[TimelineItemResponse]
    unavailable_entities: list[str]


def create_app(database: Path | None = None, *, public_mode: bool | None = None) -> FastAPI:
    database = default_database() if database is None else database
    public = public_mode_from_env() if public_mode is None else public_mode
    app = FastAPI(title="Sports Briefing", version="0.2.0")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/meta", response_model=MetaResponse)
    def meta() -> MetaResponse:
        return MetaResponse(public_mode=public, version=app.version, entities=entity_sources(public))

    @app.get(
        "/briefings/arsenal",
        response_model=ArsenalBriefingResponse,
        response_model_exclude_unset=True,
    )
    def arsenal_briefing(
        hide_results: bool = Query(default=True),
    ) -> ArsenalBriefingResponse:
        if public:
            raise HTTPException(status_code=404, detail="Arsenal briefing is not available in public mode.")
        try:
            briefing = build_arsenal_briefing(database, hide_results=hide_results)
            return _project_briefing(briefing, hide_results=hide_results)
        except StorageError as exc:
            if _is_missing_state(exc):
                LOGGER.info("briefing_unavailable entity=arsenal")
                raise HTTPException(
                    status_code=404,
                    detail="Arsenal briefing is not available. Run ingestion first.",
                ) from exc
            LOGGER.exception("briefing_read_failed entity=arsenal stage=persistence")
            raise HTTPException(
                status_code=503,
                detail="Arsenal briefing could not be read.",
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            LOGGER.exception("briefing_read_failed entity=arsenal stage=persistence")
            raise HTTPException(
                status_code=503,
                detail="Arsenal briefing could not be read.",
            ) from exc
        except (BriefingError, ValueError, TypeError, KeyError, AttributeError) as exc:
            LOGGER.exception("briefing_read_failed entity=arsenal stage=projection")
            raise HTTPException(
                status_code=503,
                detail="Arsenal briefing could not be read.",
            ) from exc

    @app.get("/briefings/texans", response_model=TexansBriefingResponse)
    def texans_briefing() -> TexansBriefingResponse:
        if public:
            raise HTTPException(status_code=404, detail="Texans briefing is not available in public mode.")
        try:
            return _project_texans_briefing(build_texans_briefing(database))
        except StorageError as exc:
            if _is_missing_texans_state(exc):
                LOGGER.info("briefing_unavailable entity=texans")
                raise HTTPException(
                    status_code=404,
                    detail="Texans briefing is not available. Run ingestion first.",
                ) from exc
            LOGGER.exception("briefing_read_failed entity=texans stage=persistence")
            raise HTTPException(
                status_code=503,
                detail="Texans briefing could not be read.",
            ) from exc
        except (sqlite3.Error, OSError) as exc:
            if _is_missing_texans_state(exc):
                LOGGER.info("briefing_unavailable entity=texans")
                raise HTTPException(
                    status_code=404,
                    detail="Texans briefing is not available. Run ingestion first.",
                ) from exc
            LOGGER.exception("briefing_read_failed entity=texans stage=persistence")
            raise HTTPException(
                status_code=503,
                detail="Texans briefing could not be read.",
            ) from exc
        except (BriefingError, ValueError, TypeError, KeyError) as exc:
            LOGGER.exception("briefing_read_failed entity=texans stage=projection")
            raise HTTPException(
                status_code=503,
                detail="Texans briefing could not be read.",
            ) from exc

    @app.get(
        "/timeline",
        response_model=TimelineResponse,
        response_model_exclude_none=True,
    )
    def home_timeline(
        hide_results: bool = Query(default=True),
        as_of: datetime | None = Query(default=None),
    ) -> TimelineResponse:
        normalized_as_of = None
        if as_of is not None:
            if as_of.tzinfo is None:
                raise HTTPException(status_code=422, detail="Timeline as_of must include a timezone.")
            normalized_as_of = as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            return TimelineResponse.model_validate(
                build_home_timeline(
                    database, as_of=normalized_as_of, hide_results=hide_results, public_mode=public
                )
            )
        except (sqlite3.Error, OSError, StorageError) as exc:
            LOGGER.exception("timeline_read_failed stage=persistence")
            raise HTTPException(status_code=503, detail="Home timeline could not be read.") from exc
        except (TimelineError, BriefingError, ValueError, TypeError, KeyError, AttributeError) as exc:
            LOGGER.exception("timeline_read_failed stage=projection")
            raise HTTPException(status_code=503, detail="Home timeline could not be read.") from exc

    return app


def _project_briefing(
    briefing: dict[str, object],
    *,
    hide_results: bool,
) -> ArsenalBriefingResponse:
    next_match = _match(briefing.get("next_match"))
    latest = _completed_match(briefing.get("latest_completed_match"), hide_results)
    if next_match is not None:
        headline = f"{next_match.home_team} vs {next_match.away_team}"
        summary = f"Next fixture in {next_match.competition.name}."
        reason = "Next fixture in saved data"
    elif latest is not None:
        headline = f"{latest.home_team} vs {latest.away_team}"
        summary = "Latest completed match."
        if hide_results:
            summary += " Result hidden."
        reason = "Latest completed match"
    else:
        raise HTTPException(
            status_code=404,
            detail="Arsenal briefing is not available. Run ingestion first.",
        )

    source = _mapping(briefing["source"], "source")
    return ArsenalBriefingResponse(
        entity=EntityResponse(id="arsenal", name=str(briefing["entity"])),
        headline=headline,
        summary=summary,
        reason_shown=reason,
        as_of=str(briefing["as_of"]),
        spoiler=SpoilerResponse(results_hidden=hide_results),
        next_match=next_match,
        latest_completed_match=latest,
        source=SourceResponse(
            provider=str(source["provider"]),
            attribution=str(source["attribution"]),
            checked_at=str(source["fetched_at"]),
        ),
    )


def _match(value: object) -> MatchResponse | None:
    if value is None:
        return None
    match = _mapping(value, "match")
    source = _mapping(match["source"], "match source")
    return MatchResponse(
        competition=CompetitionResponse(
            code=str(match["competition_code"]),
            name=str(match["competition_name"]),
        ),
        kickoff_utc=str(match["kickoff_utc"]),
        status=str(match["status"]),
        home_team=str(match["home_team"]),
        away_team=str(match["away_team"]),
        provenance=MatchProvenanceResponse(
            provider_updated_at=str(match["provider_updated_at"]),
            observed_at=str(source["fetched_at"]),
        ),
    )


def _completed_match(value: object, hide_results: bool) -> CompletedMatchResponse | None:
    if value is None:
        return None
    match = _mapping(value, "completed match")
    projected = _match(match)
    assert projected is not None
    result = None
    if not hide_results:
        score = _mapping(match["score"], "full-time score")
        result = ResultResponse(
            full_time=FullTimeResponse(home=score.get("home"), away=score.get("away")),
            winner=match.get("winner"),
            duration=match.get("score_duration"),
        )
    if hide_results:
        return CompletedMatchResponse(
            **projected.model_dump(),
            result_hidden=True,
        )
    return CompletedMatchResponse(
        **projected.model_dump(),
        result_hidden=False,
        result=result,
    )


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BriefingError(f"{label} must be an object")
    return value


def _project_texans_briefing(briefing: dict[str, object]) -> TexansBriefingResponse:
    next_value = briefing.get("next_game")
    next_game = TexansGameResponse(**_mapping(next_value, "next game")) if next_value else None
    report = AvailabilityReportResponse(
        **_mapping(briefing["availability_report"], "availability report")
    )
    availability = [
        TexansAvailabilityResponse(**_mapping(value, "availability"))
        for value in _sequence(briefing["availability"], "availability")
    ]
    changes = [
        TexansChangeResponse(**_mapping(value, "change"))
        for value in _sequence(briefing["changes"], "changes")
    ]
    if next_game is None:
        headline = "No upcoming Texans game in saved schedule"
        summary = "No current availability report is attached to an upcoming game."
        reason = "No upcoming game in persisted schedule"
    else:
        headline = f"{next_game.home_team} vs {next_game.away_team}"
        if not report.available:
            summary = "Next game found; its injury report has not been ingested."
            reason = "Next game with report unavailable"
        elif changes:
            summary = f"{len(changes)} meaningful availability change(s) in the saved report."
            reason = "Recent practice or game-status change"
        else:
            summary = f"{len(availability)} player(s) in the current saved injury report."
            reason = "Current report for next game"
    source = _mapping(briefing["source"], "source")
    return TexansBriefingResponse(
        entity=EntityResponse(id="texans", name=str(briefing["entity"])),
        headline=headline,
        summary=summary,
        reason_shown=reason,
        as_of=str(briefing["as_of"]),
        next_game=next_game,
        availability_report=report,
        availability=availability,
        changes=changes,
        source=TexansSourceResponse(
            provider=str(source["provider"]),
            attribution=str(source["attribution"]),
            checked_at=str(source["fetched_at"]),
            schedule_generated_at=str(source["schedule_generated_at"]),
            injuries_generated_at=(
                str(source["injuries_generated_at"])
                if source["injuries_generated_at"] is not None
                else None
            ),
        ),
    )


def _sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise BriefingError(f"{label} must be an array")
    return value


def _is_missing_state(error: StorageError) -> bool:
    message = str(error)
    return message.startswith("database does not exist:") or message == (
        "database contains no successful Arsenal ingestion"
    )


def _is_missing_texans_state(error: Exception) -> bool:
    message = str(error)
    return (
        message.startswith("database does not exist:")
        or message == "database contains no successful Texans ingestion"
        or message == "no such table: nfl_fetches"
    )


app = create_app()

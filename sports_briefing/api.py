from __future__ import annotations

import logging
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .briefing import BriefingError, build_arsenal_briefing
from .cli import DEFAULT_DATABASE
from .storage import StorageError


LOGGER = logging.getLogger("sports_briefing.api")


class HealthResponse(BaseModel):
    status: str


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


def create_app(database: Path = DEFAULT_DATABASE) -> FastAPI:
    app = FastAPI(title="Sports Briefing", version="0.2.0")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/briefings/arsenal",
        response_model=ArsenalBriefingResponse,
        response_model_exclude_unset=True,
    )
    def arsenal_briefing(
        hide_results: bool = Query(default=True),
    ) -> ArsenalBriefingResponse:
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


def _is_missing_state(error: StorageError) -> bool:
    message = str(error)
    return message.startswith("database does not exist:") or message == (
        "database contains no successful Arsenal ingestion"
    )


app = create_app()

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROVIDER = "sportradar"
BASE_URL = "https://api.sportradar.com/nfl/official/trial/v7/en"
TEXANS_ID = "82d2d380-3834-4938-835f-aec541e5ece7"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class NormalizationError(Exception):
    pass


@dataclass(frozen=True)
class ProviderResponse:
    payload: dict[str, Any]
    body: str
    url: str
    status: int
    generated_at: str


@dataclass(frozen=True)
class NFLGame:
    provider_game_id: str
    season_id: str
    season_year: int
    season_type: str
    week_id: str
    week: int
    scheduled_utc: str
    status: str
    home_team_id: str
    home_team_name: str
    home_team_alias: str
    away_team_id: str
    away_team_name: str
    away_team_alias: str
    raw_record_json: str


@dataclass(frozen=True)
class ScheduleSnapshot:
    season_id: str
    season_year: int
    season_type: str
    games: tuple[NFLGame, ...]
    deleted_game_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlayerAvailability:
    player_id: str
    player_name: str
    position: str | None
    jersey: str | None
    sr_id: str | None
    practice_status: str | None
    game_status: str | None
    injury: str | None
    status_date: str | None
    raw_record_json: str


@dataclass(frozen=True)
class InjurySnapshot:
    season_id: str
    season_year: int
    season_type: str
    week_id: str
    week: int
    team_id: str
    report_date: str | None
    players: tuple[PlayerAvailability, ...]


def schedule_url(season_year: int | None = None, season_type: str | None = None) -> str:
    if season_year is None and season_type is None:
        return f"{BASE_URL}/games/current_season/schedule.json"
    if season_year is None or season_type is None:
        raise ValueError("season year and type must be provided together")
    return f"{BASE_URL}/games/{season_year}/{season_type}/schedule.json"


def injuries_url(season_year: int, season_type: str, week: int) -> str:
    return f"{BASE_URL}/seasons/{season_year}/{season_type}/{week}/injuries.json"


def fetch_schedule(
    api_key: str,
    *,
    season_year: int | None = None,
    season_type: str | None = None,
    timeout: float = 15.0,
) -> ProviderResponse:
    return _fetch(schedule_url(season_year, season_type), api_key, timeout)


def fetch_weekly_injuries(
    api_key: str,
    *,
    season_year: int,
    season_type: str,
    week: int,
    timeout: float = 15.0,
) -> ProviderResponse:
    return _fetch(injuries_url(season_year, season_type, week), api_key, timeout)


def normalize_schedule(payload: dict[str, Any]) -> ScheduleSnapshot:
    root = _object(payload, "schedule")
    season = _object(root.get("season"), "schedule.season")
    season_id = _text(season.get("id"), "schedule.season.id")
    season_year = _integer(season.get("year"), "schedule.season.year")
    season_type = _text(season.get("type"), "schedule.season.type")
    weeks = _list(root.get("weeks"), "schedule.weeks")
    games: list[NFLGame] = []
    seen: set[str] = set()
    for week_index, week_value in enumerate(weeks):
        week = _object(week_value, f"schedule.weeks[{week_index}]")
        week_id = _text(week.get("id"), f"schedule.weeks[{week_index}].id")
        sequence = _integer(week.get("sequence"), f"schedule.weeks[{week_index}].sequence")
        for game_index, game_value in enumerate(_list(week.get("games"), "week.games")):
            game = _object(game_value, f"week.games[{game_index}]")
            home = _team(game.get("home"), "game.home")
            away = _team(game.get("away"), "game.away")
            if TEXANS_ID not in {home[0], away[0]}:
                continue
            provider_game_id = _text(game.get("id"), "game.id")
            if provider_game_id in seen:
                raise NormalizationError(f"duplicate provider game id: {provider_game_id}")
            seen.add(provider_game_id)
            games.append(
                NFLGame(
                    provider_game_id=provider_game_id,
                    season_id=season_id,
                    season_year=season_year,
                    season_type=season_type,
                    week_id=week_id,
                    week=sequence,
                    scheduled_utc=_timestamp(game.get("scheduled"), "game.scheduled"),
                    status=_text(game.get("status"), "game.status"),
                    home_team_id=home[0],
                    home_team_name=home[1],
                    home_team_alias=home[2],
                    away_team_id=away[0],
                    away_team_name=away[1],
                    away_team_alias=away[2],
                    raw_record_json=_canonical(game),
                )
            )
    deleted_game_ids: list[str] = []
    for index, value in enumerate(_list(root.get("deleted_games", []), "schedule.deleted_games")):
        if isinstance(value, str):
            deleted_game_ids.append(_text(value, f"deleted_games[{index}]"))
        else:
            deleted = _object(value, f"deleted_games[{index}]")
            deleted_game_ids.append(_text(deleted.get("id"), f"deleted_games[{index}].id"))
    if len(deleted_game_ids) != len(set(deleted_game_ids)):
        raise NormalizationError("schedule.deleted_games contains duplicate ids")
    overlap = seen.intersection(deleted_game_ids)
    if overlap:
        raise NormalizationError(
            f"schedule lists game as both active and deleted: {min(overlap)}"
        )
    return ScheduleSnapshot(
        season_id,
        season_year,
        season_type,
        tuple(games),
        tuple(sorted(deleted_game_ids)),
    )


def normalize_injuries(payload: dict[str, Any]) -> InjurySnapshot:
    root = _object(payload, "injury report")
    season = _object(root.get("season"), "injury report.season")
    week = _object(root.get("week"), "injury report.week")
    season_id = _text(season.get("id"), "season.id")
    season_year = _integer(season.get("year"), "season.year")
    season_type = _text(season.get("type"), "season.type")
    week_id = _text(week.get("id"), "week.id")
    week_number = _integer(week.get("sequence"), "week.sequence")
    teams = _list(root.get("teams"), "injury report.teams")
    texans = [
        _object(team, "injury report team")
        for team in teams
        if isinstance(team, dict) and team.get("id") == TEXANS_ID
    ]
    if len(texans) != 1:
        raise NormalizationError("injury report must contain exactly one Houston Texans team")
    team = texans[0]
    players: list[PlayerAvailability] = []
    seen: set[str] = set()
    report_dates: list[str] = []
    for index, player_value in enumerate(_list(team.get("players"), "Texans players")):
        player = _object(player_value, f"Texans players[{index}]")
        player_id = _text(player.get("id"), "player.id")
        if player_id in seen:
            raise NormalizationError(f"duplicate provider player id: {player_id}")
        seen.add(player_id)
        injuries = _list(player.get("injuries"), f"player {player_id}.injuries")
        if len(injuries) != 1:
            raise NormalizationError(
                f"player {player_id} has {len(injuries)} injury rows; cannot select one safely"
            )
        injury = _object(injuries[0], f"player {player_id}.injuries[0]")
        practice_value = injury.get("practice")
        practice = None
        if practice_value is not None:
            practice = _object(practice_value, f"player {player_id}.practice")
        status_date = _optional_timestamp(injury.get("status_date"), "injury.status_date")
        if status_date is not None:
            report_dates.append(status_date)
        players.append(
            PlayerAvailability(
                player_id=player_id,
                player_name=_text(player.get("name"), "player.name"),
                position=_optional_text(player.get("position"), "player.position"),
                jersey=_optional_text(player.get("jersey"), "player.jersey"),
                sr_id=_optional_text(player.get("sr_id"), "player.sr_id"),
                practice_status=_practice_status(
                    practice.get("status") if practice is not None else None
                ),
                game_status=_game_status(injury.get("status")),
                injury=_optional_text(injury.get("primary"), "injury.primary"),
                status_date=status_date,
                raw_record_json=_canonical(player),
            )
        )
    return InjurySnapshot(
        season_id=season_id,
        season_year=season_year,
        season_type=season_type,
        week_id=week_id,
        week=week_number,
        team_id=TEXANS_ID,
        report_date=max(report_dates, default=None),
        players=tuple(players),
    )


def _fetch(url: str, api_key: str, timeout: float) -> ProviderResponse:
    request = Request(url, headers={"x-api-key": api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            body = _read_bounded(response)
            generated = response.headers.get("x-generated-date")
    except HTTPError as exc:
        body = _read_error(exc)
        raise ProviderError(
            f"Sportradar returned HTTP {exc.code}", status=exc.code, body=body
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Sportradar request failed: {exc}") from exc
    if not generated:
        raise ProviderError("Sportradar response is missing required x-generated-date header", status=status, body=body)
    try:
        generated_at = parsedate_to_datetime(generated)
    except (TypeError, ValueError) as exc:
        raise ProviderError("Sportradar x-generated-date is not a valid HTTP date", status=status, body=body) from exc
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderError("Sportradar response is not valid JSON", status=status, body=body) from exc
    if not isinstance(decoded, dict):
        raise ProviderError("Sportradar response must be a JSON object", status=status, body=body)
    return ProviderResponse(
        payload=decoded,
        body=body,
        url=url,
        status=status,
        generated_at=generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _read_bounded(response: Any) -> str:
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ProviderError("Sportradar response exceeded 2 MiB", body=data[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace"))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderError("Sportradar response is not UTF-8", body=data[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")) from exc


def _read_error(error: HTTPError) -> str:
    return error.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")


def _team(value: object, label: str) -> tuple[str, str, str]:
    team = _object(value, label)
    team_id = _text(team.get("id"), f"{label}.id")
    market = _optional_text(team.get("market"), f"{label}.market")
    name = _text(team.get("name"), f"{label}.name")
    display = f"{market} {name}" if market else name
    return team_id, display, _text(team.get("alias"), f"{label}.alias")


def _practice_status(value: object) -> str | None:
    status = _optional_text(value, "practice.status")
    return {
        "Did Not Participate In Practice": "DNP",
        "Limited Participation In Practice": "LIMITED",
        "Full Participation In Practice": "FULL",
    }.get(status, status)


def _game_status(value: object) -> str | None:
    status = _optional_text(value, "injury.status")
    return status.upper().replace(" ", "_") if status is not None else None


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NormalizationError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise NormalizationError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(f"{label} must be a non-empty string")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{label} must be an integer")
    return value


def _timestamp(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise NormalizationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_timestamp(value: object, label: str) -> str | None:
    return None if value is None else _timestamp(value, label)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROVIDER = "football-data.org"
ARSENAL_TEAM_ID = 57
SUPPORTED_COMPETITIONS = frozenset({"PL", "CL"})
ALLOWED_STATUSES = frozenset(
    {
        "SCHEDULED",
        "TIMED",
        "IN_PLAY",
        "PAUSED",
        "FINISHED",
        "SUSPENDED",
        "POSTPONED",
        "CANCELLED",
        "AWARDED",
    }
)
ALLOWED_WINNERS = frozenset({"HOME_TEAM", "AWAY_TEAM", "DRAW"})
ALLOWED_DURATIONS = frozenset({"REGULAR", "EXTRA_TIME", "PENALTY_SHOOTOUT"})
MAX_MATCHES = 500
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class NormalizationError(Exception):
    pass


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    body: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class FootballFixture:
    provider_match_id: str
    competition_id: str
    competition_code: str
    competition_name: str
    season_id: str
    kickoff_utc: str
    status: str
    matchday: int | None
    stage: str | None
    group_name: str | None
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    winner: str | None
    score_duration: str | None
    score_json: str
    provider_updated_at: str
    raw_record_json: str


def fetch_arsenal_matches(
    api_key: str,
    date_from: str,
    date_to: str,
    *,
    timeout: float = 15.0,
) -> FetchResponse:
    query = urlencode({"dateFrom": date_from, "dateTo": date_to, "limit": MAX_MATCHES})
    url = f"https://api.football-data.org/v4/teams/{ARSENAL_TEAM_ID}/matches?{query}"
    request = Request(
        url,
        headers={"X-Auth-Token": api_key, "Accept": "application/json", "User-Agent": "sports-briefing/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_RESPONSE_BYTES:
                bounded = response_bytes[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
                raise ProviderError(
                    f"provider response exceeds {MAX_RESPONSE_BYTES} bytes",
                    status=status,
                    body=bounded,
                )
            body = response_bytes.decode("utf-8")
    except ProviderError:
        raise
    except Exception as exc:
        status = getattr(exc, "code", None)
        error_body: str | None = None
        if hasattr(exc, "read"):
            try:
                error_body = exc.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES].decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                error_body = None
        raise ProviderError(f"provider request failed: {exc}", status=status, body=error_body) from exc

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProviderError("provider returned invalid JSON", status=status, body=body) from exc
    if not isinstance(payload, dict):
        raise ProviderError("provider response must be a JSON object", status=status, body=body)
    return FetchResponse(url=url, status=status, body=body, payload=payload)


def normalize_matches(payload: dict[str, Any]) -> tuple[list[FootballFixture], int]:
    matches = _required(payload, "matches", list, "response")
    result_set = _required(payload, "resultSet", dict, "response")
    declared_count = _required_int(result_set, "count", "response.resultSet")
    if declared_count != len(matches):
        raise NormalizationError(
            f"response.resultSet.count is {declared_count}, but response contains {len(matches)} matches"
        )
    if len(matches) >= MAX_MATCHES:
        raise NormalizationError(
            f"response reached the configured {MAX_MATCHES}-match limit; use a smaller date window"
        )

    fixtures: list[FootballFixture] = []
    ignored = 0
    seen_ids: set[str] = set()
    for index, record in enumerate(matches):
        path = f"matches[{index}]"
        if not isinstance(record, dict):
            raise NormalizationError(f"{path} must be an object")
        competition = _required(record, "competition", dict, path)
        code = _required_str(competition, "code", f"{path}.competition")
        if code not in SUPPORTED_COMPETITIONS:
            ignored += 1
            continue
        fixture = _normalize_fixture(record, path, competition, code)
        if fixture.provider_match_id in seen_ids:
            raise NormalizationError(
                f"duplicate provider match id {fixture.provider_match_id!r} in supported response"
            )
        seen_ids.add(fixture.provider_match_id)
        fixtures.append(fixture)
    return fixtures, ignored


def _normalize_fixture(
    record: dict[str, Any], path: str, competition: dict[str, Any], code: str
) -> FootballFixture:
    match_id = str(_required_int(record, "id", path))
    status = _required_str(record, "status", path)
    if status not in ALLOWED_STATUSES:
        raise NormalizationError(f"{path}.status has unsupported value {status!r}")

    kickoff = _utc_timestamp(_required_str(record, "utcDate", path), f"{path}.utcDate")
    provider_updated = _utc_timestamp(
        _required_str(record, "lastUpdated", path), f"{path}.lastUpdated"
    )
    season = _required(record, "season", dict, path)
    home = _normalize_team(_required(record, "homeTeam", dict, path), f"{path}.homeTeam")
    away = _normalize_team(_required(record, "awayTeam", dict, path), f"{path}.awayTeam")
    if ARSENAL_TEAM_ID not in {int(home[0]), int(away[0])}:
        raise NormalizationError(f"{path} does not contain Arsenal team id {ARSENAL_TEAM_ID}")

    score = _required(record, "score", dict, path)
    winner = _optional_enum(score, "winner", ALLOWED_WINNERS, f"{path}.score")
    duration = _optional_enum(score, "duration", ALLOWED_DURATIONS, f"{path}.score")
    normalized_score: dict[str, dict[str, int | None] | str | None] = {
        "winner": winner,
        "duration": duration,
    }
    for component in ("fullTime", "halfTime", "regularTime", "extraTime", "penalties"):
        if component in score and score[component] is not None:
            value = score[component]
            if not isinstance(value, dict):
                raise NormalizationError(f"{path}.score.{component} must be an object or null")
            home_score = _nullable_score(value, "home", f"{path}.score.{component}")
            away_score = _nullable_score(value, "away", f"{path}.score.{component}")
            if (home_score is None) != (away_score is None):
                raise NormalizationError(
                    f"{path}.score.{component} must contain both scores or neither"
                )
            normalized_score[component] = {"home": home_score, "away": away_score}
    if "fullTime" not in normalized_score:
        raise NormalizationError(f"{path}.score.fullTime is required")

    matchday = _nullable_int(record, "matchday", path)
    stage = _nullable_str(record, "stage", path)
    group_name = _nullable_str(record, "group", path)
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return FootballFixture(
        provider_match_id=match_id,
        competition_id=str(_required_int(competition, "id", f"{path}.competition")),
        competition_code=code,
        competition_name=_required_str(competition, "name", f"{path}.competition"),
        season_id=str(_required_int(season, "id", f"{path}.season")),
        kickoff_utc=kickoff,
        status=status,
        matchday=matchday,
        stage=stage,
        group_name=group_name,
        home_team_id=home[0],
        home_team_name=home[1],
        away_team_id=away[0],
        away_team_name=away[1],
        winner=winner,
        score_duration=duration,
        score_json=json.dumps(normalized_score, separators=(",", ":"), sort_keys=True),
        provider_updated_at=provider_updated,
        raw_record_json=raw,
    )


def _normalize_team(team: dict[str, Any], path: str) -> tuple[str, str]:
    return str(_required_int(team, "id", path)), _required_str(team, "name", path)


def _required(container: dict[str, Any], key: str, expected: type, path: str) -> Any:
    if key not in container:
        raise NormalizationError(f"{path}.{key} is required")
    value = container[key]
    if not isinstance(value, expected):
        raise NormalizationError(f"{path}.{key} must be {expected.__name__}")
    return value


def _required_str(container: dict[str, Any], key: str, path: str) -> str:
    value = _required(container, key, str, path)
    if not value:
        raise NormalizationError(f"{path}.{key} must not be empty")
    return value


def _required_int(container: dict[str, Any], key: str, path: str) -> int:
    if key not in container:
        raise NormalizationError(f"{path}.{key} is required")
    value = container[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{path}.{key} must be an integer")
    return value


def _nullable_int(container: dict[str, Any], key: str, path: str) -> int | None:
    value = container.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{path}.{key} must be an integer or null")
    return value


def _nullable_score(container: dict[str, Any], key: str, path: str) -> int | None:
    if key not in container:
        raise NormalizationError(f"{path}.{key} is required")
    value = container[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NormalizationError(f"{path}.{key} must be a non-negative integer or null")
    return value


def _nullable_str(container: dict[str, Any], key: str, path: str) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"{path}.{key} must be a string or null")
    return value


def _optional_enum(
    container: dict[str, Any], key: str, allowed: frozenset[str], path: str
) -> str | None:
    value = container.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise NormalizationError(f"{path}.{key} has unsupported value {value!r}")
    return value


def _utc_timestamp(value: str, path: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise NormalizationError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

"""Sportradar Golf REST input, kept separate from timeline policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROVIDER = "sportradar"
BASE = "https://api.sportradar.com/golf/trial"
SCOTTIE_ID = "6db3e736-d86d-4181-aa3b-651b8c1bfdc1"
MAX_BYTES = 2 * 1024 * 1024
LOGGER = logging.getLogger("sports_briefing.golf.sportradar")


class ProviderError(Exception):
    pass


class NormalizationError(Exception):
    pass


@dataclass(frozen=True)
class Response:
    url: str
    payload: dict[str, Any]
    body: str
    generated_raw: str | None
    generated_at: str | None
    last_modified: str | None
    etag: str | None
    status: int = 200


def schedule_url(year: int) -> str:
    return f"{BASE}/pga/v3/en/{year}/tournaments/schedule.json"


def tournament_url(year: int, tournament_id: str, suffix: str) -> str:
    return f"{BASE}/pga/v3/en/{year}/tournaments/{tournament_id}/{suffix}.json"


def round_url(year: int, tournament_id: str, number: int, suffix: str) -> str:
    return tournament_url(year, tournament_id, f"rounds/{number}/{suffix}")


def fetch(url: str, api_key: str, timeout: float = 15.0) -> Response:
    request = Request(url, headers={"x-api-key": api_key, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as reply:
            raw = reply.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ProviderError("Golf response exceeds 2 MiB")
            headers = reply.headers
            status = int(getattr(reply, "status", 200))
    except HTTPError as exc:
        raise ProviderError(f"Golf HTTP {exc.code} at {url}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Golf request failed at {url}: {exc}") from exc
    try:
        body = raw.decode("utf-8")
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Golf response is not UTF-8 JSON at {url}") from exc
    if not isinstance(payload, dict):
        raise ProviderError(f"Golf response root must be an object at {url}")
    generated_raw = headers.get("x-generated-date")
    generated_at = None
    if generated_raw:
        try:
            generated = parsedate_to_datetime(generated_raw)
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"Golf response has invalid x-generated-date at {url}") from exc
        if generated.tzinfo is None:
            raise ProviderError(f"Golf response has timezone-less x-generated-date at {url}")
        generated_at = utc(generated)
    return Response(url, payload, body, generated_raw, generated_at, headers.get("Last-Modified"), headers.get("ETag"), status)


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def obj(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NormalizationError(f"{label} must be an object")
    return value


def arr(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise NormalizationError(f"{label} must be an array")
    return value


def string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError(f"{label} must be a non-empty string")
    return value


def optional_string(value: object, label: str) -> str | None:
    return None if value is None else string(value, label)


def integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NormalizationError(f"{label} must be an integer")
    return value


def optional_integer(value: object, label: str) -> int | None:
    return None if value is None else integer(value, label)


def timestamp(value: object, label: str) -> str:
    raw = string(value, label)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise NormalizationError(f"{label} must include timezone")
    return utc(parsed)


def optional_timestamp(value: object, label: str) -> str | None:
    return None if value is None else timestamp(value, label)


def day(value: object, label: str) -> str:
    raw = string(value, label)
    try:
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError(raw)
    except ValueError as exc:
        raise NormalizationError(f"{label} must be a date without time") from exc
    return raw


def normalize_schedule(response: Response) -> list[dict[str, Any]]:
    root = response.payload
    tour = obj(root.get("tour"), "schedule.tour")
    season = obj(root.get("season"), "schedule.season")
    tour_id = string(tour.get("id"), "tour.id")
    tour_alias = string(tour.get("alias"), "tour.alias")
    if tour_alias != "pga":
        raise NormalizationError("schedule tour is not pga")
    season_id = string(season.get("id"), "season.id")
    year = integer(season.get("year"), "season.year")
    result = []
    seen: set[str] = set()
    for value in arr(root.get("tournaments"), "schedule.tournaments"):
        item = obj(value, "schedule tournament")
        provider_id = string(item.get("id"), "tournament.id")
        if provider_id in seen:
            raise NormalizationError(f"duplicate tournament {provider_id}")
        seen.add(provider_id)
        start, end = day(item.get("start_date"), "tournament.start_date"), day(item.get("end_date"), "tournament.end_date")
        if start > end:
            raise NormalizationError("tournament start is after end")
        result.append({"id": provider_id, "name": string(item.get("name"), "tournament.name"), "tour_id": tour_id, "tour_alias": tour_alias, "season_id": season_id, "season_year": year, "start_date": start, "end_date": end, "course_timezone": string(item.get("course_timezone"), "tournament.course_timezone"), "event_type": string(item.get("event_type"), "tournament.event_type"), "status": string(item.get("status"), "tournament.status")})
    return result


def discovery_order(tournaments: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    stroke = [t for t in tournaments if t["event_type"] == "stroke"]
    current = sorted((t for t in stroke if t["start_date"] <= today.isoformat() <= t["end_date"]), key=lambda t: (t["start_date"], t["id"]))
    upcoming = sorted((t for t in stroke if today.isoformat() < t["start_date"] <= (today+timedelta(days=60)).isoformat()), key=lambda t: (t["start_date"], t["id"]))[:3]
    recent = sorted((t for t in stroke if (today-timedelta(days=60)).isoformat() <= t["end_date"] < today.isoformat()), key=lambda t: (t["end_date"], t["id"]), reverse=True)[:3]
    return current[:2] + upcoming + recent


def field_contains(summary: Response, tournament_id: str) -> bool:
    root = summary.payload
    if string(root.get("id"), "summary.id") != tournament_id:
        raise NormalizationError("summary tournament identity mismatch")
    # Pre-field upcoming summaries can omit field, status, and rounds entirely.
    # This establishes no participation or withdrawal state.
    if "field" not in root:
        return False
    entries = arr(root.get("field"), "summary.field")
    ids = [string(obj(x, "field entry").get("id"), "field player id") for x in entries]
    if len(ids) != len(set(ids)):
        raise NormalizationError("summary.field has duplicate player IDs")
    return SCOTTIE_ID in ids


def normalize_bundle(tournament: dict[str, Any], responses: dict[str, Response]) -> dict[str, Any]:
    summary, board = responses["summary"].payload, responses["leaderboard"].payload
    tid = tournament["id"]
    for label, root in (("summary", summary), ("leaderboard", board)):
        if string(root.get("id"), f"{label}.id") != tid:
            raise NormalizationError(f"{label} tournament identity mismatch")
        for key in ("start_date", "end_date", "course_timezone", "event_type", "status"):
            if root.get(key) != tournament[key]:
                raise NormalizationError(f"{label}.{key} conflicts with schedule")
    if not field_contains(responses["summary"], tid):
        raise NormalizationError("Scottie not in confirmed field")
    seasons = arr(summary.get("seasons"), "summary.seasons")
    if not any(obj(s, "summary season").get("id") == tournament["season_id"] and obj(s.get("tour"), "summary season tour").get("id") == tournament["tour_id"] for s in seasons):
        raise NormalizationError("summary season/tour identity mismatch")
    field = next(x for x in summary["field"] if x["id"] == SCOTTIE_ID)
    display = f"{string(field.get('first_name'), 'Scottie first_name')} {string(field.get('last_name'), 'Scottie last_name')}"
    if display != "Scottie Scheffler":
        raise NormalizationError("Scottie identity name mismatch")
    summary_rounds = arr(summary.get("rounds"), "summary.rounds")
    if not summary_rounds:
        raise NormalizationError("summary has no rounds")
    board_rounds = arr(board.get("rounds"), "leaderboard.rounds")
    round_map = {integer(obj(r, "round").get("number"), "round.number"): r for r in summary_rounds}
    if len(round_map) != len(summary_rounds):
        raise NormalizationError("duplicate round number")
    round_ids = [string(obj(r,"round").get("id"),"round.id") for r in summary_rounds]
    if len(round_ids) != len(set(round_ids)):
        raise NormalizationError("duplicate round ID")
    if {(x.get("id"), x.get("number"), x.get("status")) for x in board_rounds} != {(x.get("id"), x.get("number"), x.get("status")) for x in summary_rounds}:
        raise NormalizationError("summary and leaderboard rounds conflict")
    players = arr(board.get("leaderboard"), "leaderboard.leaderboard")
    matches = [obj(p, "leaderboard player") for p in players if isinstance(p, dict) and p.get("id") == SCOTTIE_ID]
    if len(matches) > 1:
        raise NormalizationError("duplicate Scottie leaderboard entry")
    player = matches[0] if matches else None
    status = optional_string(player.get("status"), "player.status") if player else None
    tied = player.get("tied") if player else None
    if tied is not None and not isinstance(tied, bool):
        raise NormalizationError("player.tied must be boolean")
    board_player_rounds = {}
    if player:
        for value in arr(player.get("rounds"), "player.rounds"):
            r = obj(value, "player round")
            number = integer(r.get("sequence"), "player round sequence")
            if number in board_player_rounds or number not in round_map:
                raise NormalizationError("invalid player round sequence")
            board_player_rounds[number] = r
    rounds = []
    for number, raw in sorted(round_map.items()):
        rid = string(raw.get("id"), "round.id")
        rr = {"round_id": rid, "number": number, "status": string(raw.get("status"), "round.status"), "tee_time": None, "score": None, "strokes": None, "thru": None, "created_at": None, "updated_at": None}
        if number in board_player_rounds:
            pr = board_player_rounds[number]
            rr.update(score=optional_integer(pr.get("score"), "player round score"), strokes=optional_integer(pr.get("strokes"), "player round strokes"), thru=optional_integer(pr.get("thru"), "player round thru"))
        rounds.append(rr)
    leaderboard_rounds = [
        {key: r[key] for key in ("round_id", "number", "status", "score", "strokes", "thru")}
        for r in rounds
    ]
    selected = select_round(rounds, tournament["status"])
    tee_projection = None
    scorecard_projection = None
    if selected is not None:
        number = selected["number"]
        for key in ("tees", "scores"):
            if key not in responses:
                raise NormalizationError(f"missing {key} response")
            root = responses[key].payload
            if string(root.get("id"), f"{key}.id") != tid:
                raise NormalizationError(f"{key} tournament identity mismatch")
            actual_round = obj(root.get("round"), f"{key}.round")
            if (actual_round.get("id"), actual_round.get("number"), actual_round.get("status")) != (selected["round_id"], number, selected["status"]):
                raise NormalizationError(f"{key} round identity/status mismatch")
        tee_round = responses["tees"].payload["round"]
        pairings = [obj(p, "pairing") for course in arr(tee_round.get("courses"), "round.courses") for p in arr(obj(course, "course").get("pairings"), "course.pairings")]
        own_pairings = [p for p in pairings if any(obj(q, "paired player").get("id") == SCOTTIE_ID for q in arr(p.get("players"), "pairing.players"))]
        if len(own_pairings) > 1:
            raise NormalizationError("Scottie has duplicate pairing")
        if own_pairings:
            selected["tee_time"] = optional_timestamp(own_pairings[0].get("tee_time"), "pairing.tee_time")
        tee_projection = {"tournament_id": tid, "round_id": selected["round_id"], "number": number, "status": selected["status"], "tee_time": selected["tee_time"]}
        scores = [obj(p, "round score player") for p in arr(responses["scores"].payload["round"].get("players"), "round.players") if isinstance(p, dict) and p.get("id") == SCOTTIE_ID]
        if len(scores) > 1:
            raise NormalizationError("duplicate Scottie scorecard")
        if scores:
            score = scores[0]
            for field_name in ("score", "strokes", "thru"):
                score_value = optional_integer(score.get(field_name), f"scorecard.{field_name}")
                if selected[field_name] is not None and score_value != selected[field_name]:
                    raise NormalizationError(f"scorecard.{field_name} conflicts with leaderboard")
                selected[field_name] = score_value
            selected["created_at"] = optional_timestamp(score.get("created_at"), "scorecard.created_at")
            selected["updated_at"] = optional_timestamp(score.get("updated_at"), "scorecard.updated_at")
        scorecard_projection = {"tournament_id": tid, "round_id": selected["round_id"], "number": number, "status": selected["status"], "player": {key: selected[key] for key in ("score", "strokes", "thru", "created_at", "updated_at")} if scores else None}
    entry = {"player_id": SCOTTIE_ID, "display_name": display, "field_confirmed": True, "participation_source": responses["summary"].url, "position": optional_integer(player.get("position"), "player.position") if player else None, "tied": tied, "score": optional_integer(player.get("score"), "player.score") if player else None, "strokes": optional_integer(player.get("strokes"), "player.strokes") if player else None, "status": status}
    metadata = {key: tournament[key] for key in ("start_date", "end_date", "course_timezone", "event_type", "status")}
    semantics = {
        "schedule": {key: tournament[key] for key in ("id", "name", "tour_id", "tour_alias", "season_id", "season_year", "start_date", "end_date", "course_timezone", "event_type", "status")},
        "summary": {"tournament_id": tid, **metadata, "season_id": tournament["season_id"], "tour_id": tournament["tour_id"], "field": {"player_id": SCOTTIE_ID, "display_name": display}, "rounds": [{key: r[key] for key in ("round_id", "number", "status")} for r in rounds]},
        "leaderboard": {"tournament_id": tid, **metadata, "rounds": leaderboard_rounds, "player": {key: entry[key] for key in ("position", "tied", "score", "strokes", "status")} if player else None},
    }
    if tee_projection is not None:
        semantics["tees"] = tee_projection
        semantics["scores"] = scorecard_projection
    return {"tournament": tournament, "entry": entry, "rounds": rounds, "selected_round": selected["number"] if selected else None, "source_semantics": semantics}


def retrieve_scottie(api_key: str, *, year: int, today: date, timeout: float = 15.0, transport: Callable[[str, str, float], Response] = fetch) -> tuple[dict[str, Any], dict[str, Response]]:
    responses: dict[str, Response] = {}
    last_call = 0.0
    request_count = 0
    def get(url: str) -> Response:
        nonlocal last_call, request_count
        remaining = 1.05 - (time.monotonic() - last_call)
        if last_call and remaining > 0:
            time.sleep(remaining)
        LOGGER.info("fetch_start provider=sportradar source=golf url=%s",url)
        request_count += 1
        try:
            response = transport(url, api_key, timeout)
        except ProviderError:
            LOGGER.exception("fetch_failure provider=sportradar source=golf url=%s",url)
            raise
        last_call = time.monotonic()
        LOGGER.info("fetch_end provider=sportradar source=golf url=%s status=%s generated_raw=%s generated_at=%s",url,response.status,response.generated_raw,response.generated_at)
        return response
    responses["schedule"] = get(schedule_url(year))
    options = discovery_order(normalize_schedule(responses["schedule"]), today)
    if any(option["season_year"] != year for option in options):
        raise NormalizationError("Golf schedule season does not match requested year")
    if not options:
        raise NormalizationError("no stroke-play tournament in bounded discovery window")
    chosen = None
    for tournament in options:
        summary = get(tournament_url(year, tournament["id"], "summary"))
        if field_contains(summary, tournament["id"]):
            chosen = tournament
            responses["summary"] = summary
            break
    if chosen is None:
        raise NormalizationError("no confirmed Scottie field entry in bounded discovery window")
    tid = chosen["id"]
    responses["leaderboard"] = get(tournament_url(year, tid, "leaderboard"))
    rounds = arr(responses["summary"].payload.get("rounds"), "summary.rounds")
    selected = select_round(rounds, chosen["status"])
    if selected is not None:
        number = integer(selected.get("number"), "round.number")
        responses["tees"] = get(round_url(year, tid, number, "teetimes"))
        responses["scores"] = get(round_url(year, tid, number, "scores"))
    for key,response in responses.items():
        if response.generated_at is None:
            raise NormalizationError(f"selected Golf {key} source has no x-generated-date")
    bundle = normalize_bundle(chosen, responses)
    bundle["request_count"] = request_count
    return bundle, responses


def select_round(rounds: list[dict[str,Any]], tournament_status: str) -> dict[str,Any] | None:
    if not rounds:
        raise NormalizationError("summary has no rounds")
    numbers = [integer(obj(r,"round").get("number"),"round.number") for r in rounds]
    ids = [string(r.get("id", r.get("round_id")),"round.id") for r in rounds]
    if len(numbers) != len(set(numbers)) or len(ids) != len(set(ids)):
        raise NormalizationError("duplicate round identity")
    if tournament_status == "closed":
        return max(rounds,key=lambda r:r["number"])
    remaining=[r for r in rounds if r.get("status") != "closed"]
    return min(remaining,key=lambda r:r["number"]) if remaining else None

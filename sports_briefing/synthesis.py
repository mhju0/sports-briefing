"""Optional cached summary prose over already-ranked timeline candidates.

The model only paraphrases a bounded set of candidate fields. It never selects,
ranks or adds items; an absent, stale or unverifiable entry keeps the template.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterable, Protocol

from .timeline import TimelineCandidate


LOGGER = logging.getLogger("sports_briefing.synthesis")

OUTPUT_SCHEMA_VERSION = 1
MAX_SENTENCES = 2
MAX_SUMMARY_CHARS = 280
# News candidates built from synthetic evidence must keep their disclosure.
SYNTHETIC_PREFIX = "Synthetic example: "

SCHEMA = """
CREATE TABLE IF NOT EXISTS summary_syntheses (
    stable_id TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    spoiler_mode TEXT NOT NULL CHECK (spoiler_mode IN ('hide_results', 'show_results')),
    language TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (
        stable_id, evidence_fingerprint, spoiler_mode, language,
        prompt_version, model_id, schema_version
    )
);
"""

_DIGITS = re.compile(r"\d+")
_WORDS = re.compile(r"[a-z]+")
_SCORE = re.compile(r"\d+\s*[-–—]\s*\d+")
# Heuristic only: outcome vocabulary that should not appear in hidden-result
# prose unless the visible evidence itself already uses the word.
_RESULT_WORDS = frozenset({
    "beat", "beaten", "beats", "defeat", "defeated", "defeats", "draw", "drawn",
    "drew", "finished", "lead", "leading", "leads", "led", "lose", "loses",
    "losing", "lost", "score", "scored", "scores", "tied", "trailing",
    "victory", "win", "winner", "winning", "wins", "won",
})


class SynthesisError(Exception):
    pass


@dataclass(frozen=True)
class SynthesisProfile:
    model_id: str
    prompt_version: str
    language: str = "en"


@dataclass(frozen=True)
class SynthesisInput:
    stable_id: str
    spoiler_mode: str
    language: str
    evidence: tuple[tuple[str, str], ...]

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            [OUTPUT_SCHEMA_VERSION, [list(atom) for atom in self.evidence]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SummaryModel(Protocol):
    def generate(self, synthesis_input: SynthesisInput) -> str:
        """Return JSON text shaped as {"sentences": [{"text", "evidence_ids"}]}."""


def build_synthesis_input(
    candidate: TimelineCandidate,
    *,
    hide_results: bool,
    language: str,
) -> SynthesisInput:
    # Provenance, tier and observation times are deliberately not evidence: they
    # are not prose facts, and refetch metadata must not invalidate cached text.
    evidence: list[tuple[str, str]] = [
        ("entity_name", candidate.entity_name),
        ("title", candidate.title),
        ("baseline_summary", candidate.summary),
        ("event_state", candidate.event_state),
    ]
    if candidate.competition is not None:
        evidence.append(("competition", candidate.competition["name"]))
    if candidate.event_time is not None:
        evidence.append(("event_time", candidate.event_time))
    if candidate.change_time is not None:
        evidence.append(("change_time", candidate.change_time))
    if not hide_results and not candidate.result_hidden and candidate.result is not None:
        evidence.append(("result", json.dumps(candidate.result, sort_keys=True, separators=(",", ":"))))
    return SynthesisInput(
        stable_id=candidate.stable_id,
        spoiler_mode="hide_results" if hide_results else "show_results",
        language=language,
        evidence=tuple(evidence),
    )


def verify_synthesis(raw: str, synthesis_input: SynthesisInput) -> str:
    """Return the accepted summary, or raise SynthesisError.

    Checks are structural and lexical. They cannot prove that prose is entailed
    by its cited evidence; the reviewed evaluation set covers that gap.
    """
    try:
        output = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SynthesisError("output is not JSON") from exc
    if not isinstance(output, dict) or set(output) != {"sentences"}:
        raise SynthesisError("output must contain only sentences")
    sentences = output["sentences"]
    if not isinstance(sentences, list) or not 1 <= len(sentences) <= MAX_SENTENCES:
        raise SynthesisError("sentence count out of range")
    known_ids = {evidence_id for evidence_id, _ in synthesis_input.evidence}
    texts: list[str] = []
    for sentence in sentences:
        if not isinstance(sentence, dict) or set(sentence) != {"text", "evidence_ids"}:
            raise SynthesisError("sentence must contain only text and evidence_ids")
        text, evidence_ids = sentence["text"], sentence["evidence_ids"]
        if not isinstance(text, str) or not text.strip():
            raise SynthesisError("sentence text is empty")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise SynthesisError("sentence cites no evidence")
        if any(not isinstance(item, str) or item not in known_ids for item in evidence_ids):
            raise SynthesisError("sentence cites unknown evidence")
        texts.append(" ".join(text.split()))
    summary = " ".join(texts)
    if len(summary) > MAX_SUMMARY_CHARS:
        raise SynthesisError("summary too long")

    evidence_text = " ".join(value for _, value in synthesis_input.evidence)
    evidence_digits = set(_DIGITS.findall(evidence_text))
    evidence_digits |= {digits.lstrip("0") or "0" for digits in evidence_digits}
    if any(digits not in evidence_digits for digits in _DIGITS.findall(summary)):
        raise SynthesisError("summary contains a number absent from evidence")
    baseline = dict(synthesis_input.evidence)["baseline_summary"]
    if baseline.startswith(SYNTHETIC_PREFIX) and not summary.startswith(SYNTHETIC_PREFIX):
        raise SynthesisError("synthetic disclosure dropped")
    if synthesis_input.spoiler_mode == "hide_results":
        # Dates such as 2026-09-13 look like scores; only unseen pairs are rejected.
        if any(pair not in evidence_text for pair in _SCORE.findall(summary)):
            raise SynthesisError("hidden-result summary contains a score")
        visible_words = set(_WORDS.findall(evidence_text.lower()))
        if (set(_WORDS.findall(summary.lower())) & _RESULT_WORDS) - visible_words:
            raise SynthesisError("hidden-result summary contains outcome wording")
    return summary


def initialize_synthesis_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA)


def generate_cached_summary(
    database: Path,
    candidate: TimelineCandidate,
    *,
    hide_results: bool,
    profile: SynthesisProfile,
    model: SummaryModel,
    created_at: str,
) -> str | None:
    """Generate, verify and cache one summary; None leaves cache and template as they were."""
    synthesis_input = build_synthesis_input(candidate, hide_results=hide_results, language=profile.language)
    try:
        raw = model.generate(synthesis_input)
    except Exception:
        # Adapter failures of any kind are isolated to this candidate.
        LOGGER.exception("synthesis_model_failed id=%s", candidate.stable_id)
        return None
    try:
        summary = verify_synthesis(raw, synthesis_input)
    except SynthesisError as exc:
        LOGGER.info("synthesis_rejected id=%s reason=%s", candidate.stable_id, exc)
        return None
    initialize_synthesis_database(database)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO summary_syntheses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    synthesis_input.stable_id,
                    synthesis_input.fingerprint,
                    synthesis_input.spoiler_mode,
                    synthesis_input.language,
                    profile.prompt_version,
                    profile.model_id,
                    OUTPUT_SCHEMA_VERSION,
                    raw,
                    created_at,
                ),
            )
    return summary


def apply_cached_summaries(
    database: Path,
    candidates: Iterable[TimelineCandidate],
    *,
    hide_results: bool,
    profile: SynthesisProfile,
) -> list[TimelineCandidate]:
    """Swap in verified cached summaries; never calls a model and never raises for cache state."""
    candidates = list(candidates)
    if not database.is_file():
        return candidates
    try:
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return candidates
    applied: list[TimelineCandidate] = []
    with closing(connection):
        for candidate in candidates:
            try:
                applied.append(_cached(connection, candidate, hide_results=hide_results, profile=profile))
            except (sqlite3.Error, SynthesisError) as exc:
                LOGGER.debug("synthesis_cache_unused id=%s reason=%s", candidate.stable_id, exc)
                applied.append(candidate)
    return applied


def _cached(
    connection: sqlite3.Connection,
    candidate: TimelineCandidate,
    *,
    hide_results: bool,
    profile: SynthesisProfile,
) -> TimelineCandidate:
    synthesis_input = build_synthesis_input(candidate, hide_results=hide_results, language=profile.language)
    row = connection.execute(
        """
        SELECT output_json FROM summary_syntheses
        WHERE stable_id = ? AND evidence_fingerprint = ? AND spoiler_mode = ? AND language = ?
          AND prompt_version = ? AND model_id = ? AND schema_version = ?
        """,
        (
            synthesis_input.stable_id,
            synthesis_input.fingerprint,
            synthesis_input.spoiler_mode,
            synthesis_input.language,
            profile.prompt_version,
            profile.model_id,
            OUTPUT_SCHEMA_VERSION,
        ),
    ).fetchone()
    if row is None:
        return candidate
    # Re-verify on read so a corrupted or hand-edited row cannot bypass the checks.
    return replace(candidate, summary=verify_synthesis(row[0], synthesis_input))

"""Offline M7 evaluation report: deterministic gates plus side-by-side text for human review.

Run: python -m sports_briefing.synthesis_eval tests/fixtures/synthesis/summary_eval_cases.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .synthesis import PROMPT_VERSION, SynthesisError, build_synthesis_input, verify_synthesis
from .timeline import TimelineCandidate, TimelineTier


SPOILER_MODES = frozenset({"hide_results", "show_results"})
VERIFIER_OUTCOMES = frozenset({"accept", "reject"})
HARD_GATE_OUTCOMES = frozenset({"pass", "fail"})
# Only these candidate fields can reach the model; the rest are placeholders.
EVIDENCE_FIELDS = frozenset({
    "stable_id", "entity_name", "event_state", "title", "summary",
    "competition", "event_time", "change_time", "result_hidden", "result",
})


class EvaluationError(Exception):
    pass


def load_cases(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"could not read evaluation cases: {exc}") from exc
    if document.get("prompt_version") != PROMPT_VERSION:
        raise EvaluationError(
            f"cases target prompt {document.get('prompt_version')!r}, current is {PROMPT_VERSION!r}"
        )
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("evaluation file must contain a non-empty cases list")
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise EvaluationError(f"case id must be a unique non-empty string: {case_id!r}")
        seen.add(case_id)
        expected = case.get("expected", {})
        if (
            not isinstance(case.get("description"), str)
            or case.get("spoiler_mode") not in SPOILER_MODES
            or not isinstance(case.get("candidate"), dict)
            or set(case["candidate"]) - EVIDENCE_FIELDS
            or "generated" not in case
            or expected.get("verifier") not in VERIFIER_OUTCOMES
            or expected.get("hard_gates") not in HARD_GATE_OUTCOMES
            or (expected["verifier"] == "reject" and expected["hard_gates"] != "fail")
        ):
            raise EvaluationError(f"case {case_id} is malformed")
    return cases


def case_candidate(case: dict[str, Any]) -> TimelineCandidate:
    fields = case["candidate"]
    return TimelineCandidate(
        stable_id=fields["stable_id"],
        entity_id="evaluation",
        entity_name=fields["entity_name"],
        sport="evaluation",
        item_type="evaluation",
        event_state=fields["event_state"],
        tier=TimelineTier.ROUTINE,
        title=fields["title"],
        summary=fields["summary"],
        event_time=fields.get("event_time"),
        change_time=fields.get("change_time"),
        competition=fields.get("competition"),
        source_provider="evaluation",
        source_attribution="evaluation",
        source_generated_at="1970-01-01T00:00:00Z",
        source_observed_at="1970-01-01T00:00:00Z",
        source_record_id="evaluation",
        result_hidden=fields.get("result_hidden", False),
        result=fields.get("result"),
    )


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    candidate = case_candidate(case)
    synthesis_input = build_synthesis_input(
        candidate, hide_results=case["spoiler_mode"] == "hide_results", language="en"
    )
    try:
        accepted: str | None = verify_synthesis(json.dumps(case["generated"]), synthesis_input)
        verifier, reason = "accept", None
    except SynthesisError as exc:
        accepted, verifier, reason = None, "reject", str(exc)
    expected = case["expected"]
    matches = verifier == expected["verifier"] and (
        verifier == "accept" or expected.get("rejection", "") in (reason or "")
    )
    return {
        "id": case["id"],
        "spoiler_mode": case["spoiler_mode"],
        "template": candidate.summary,
        "generated": _generated_text(case["generated"]),
        "accepted_summary": accepted,
        "verifier": verifier,
        "reason": reason,
        "expected": expected,
        "matches_expectation": matches,
        "review": case.get("review"),
    }


def render_report(results: list[dict[str, Any]]) -> str:
    lines = [f"M7 summary evaluation ({PROMPT_VERSION}): {len(results)} cases"]
    for result in results:
        expected = result["expected"]
        status = "ok" if result["matches_expectation"] else "UNEXPECTED"
        lines += [
            "",
            f"[{status}] {result['id']} ({result['spoiler_mode']})",
            f"  template:  {result['template']}",
            f"  generated: {result['generated']}",
            f"  verifier:  {result['verifier']}" + (f" ({result['reason']})" if result["reason"] else "")
            + f"; expected {expected['verifier']}",
            f"  hard gates (expected): {expected['hard_gates']}"
            + (f" — {expected['hard_gate_note']}" if expected.get("hard_gate_note") else ""),
            f"  review: {json.dumps(result['review']) if result['review'] else 'not yet reviewed'}",
        ]
    verifier_accepts = sum(result["verifier"] == "accept" for result in results)
    missed = sum(
        result["verifier"] == "accept" and result["expected"]["hard_gates"] == "fail" for result in results
    )
    unexpected = sum(not result["matches_expectation"] for result in results)
    lines += [
        "",
        f"verifier accepted {verifier_accepts}; of those, {missed} are expected to fail a hard gate "
        "(verifier blind spots that need human review)",
        f"expectation mismatches: {unexpected}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sports_briefing.synthesis_eval")
    parser.add_argument("cases", type=Path, help="evaluation cases JSON file")
    args = parser.parse_args(argv)
    try:
        results = [evaluate_case(case) for case in load_cases(args.cases)]
    except EvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_report(results))
    return 0 if all(result["matches_expectation"] for result in results) else 1


def _generated_text(generated: object) -> str:
    if isinstance(generated, dict) and isinstance(generated.get("sentences"), list):
        return " ".join(
            f"{sentence.get('text')} {sentence.get('evidence_ids')}"
            for sentence in generated["sentences"]
            if isinstance(sentence, dict)
        )
    return json.dumps(generated)


if __name__ == "__main__":
    raise SystemExit(main())

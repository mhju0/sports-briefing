# Milestone 7: bounded summary synthesis

M7 asks whether generated prose improves the timeline enough to justify a model, and does it without ever letting a model decide facts or ranking.

- **Slice 1** built the provider-independent boundary: an optional, verified, cached replacement for one field (`summary`) on candidates that ranking has already selected.
- **Slice 2** adds a versioned prompt contract and an offline evaluation set, so a real model can be judged before it is enabled.

## Built

- **Deterministic selection first.** `SQLite → candidates → rank_candidates → apply_cached_summaries (optional) → JSON projection`. Titles, identity, state, tier, order, the 2-per-entity cap, times, competition, provenance and result fields never change.
- **Verified cache with template fallback.**
  - `apply_cached_summaries` only reads and never calls a model. A missing database, table or row, or a corrupt or incompatible row, keeps that candidate's template. Other candidates are unaffected.
  - `/timeline` and the CLI pass no synthesis profile, so their output is exactly the template output.
- **Prompt contract.** `PROMPT_VERSION = "summary-en-v1"` and `SUMMARY_INSTRUCTIONS` in `sports_briefing/synthesis.py` are the one English contract.
  - `build_prompt_request` returns a provider-neutral request in which evidence stays a separate data list and is never spliced into the instructions.
  - `SynthesisProfile.prompt_version` defaults to this version.
  - Changing the instructions requires a new version, which also invalidates cached prose.
- **Evaluation set and runner.**
  - Cases: `tests/fixtures/synthesis/summary_eval_cases.json`.
  - Report: `python -m sports_briefing.synthesis_eval tests/fixtures/synthesis/summary_eval_cases.json`.
- **Generation seam.** `generate_cached_summary(database, candidate, …, model)` builds input → model → verify → `INSERT OR REPLACE`. A model exception or a rejected output writes nothing. The only model is the tests' fake.

## Not built

- a real LLM integration, SDK or credentials, or any provider/model choice;
- transmission of any source data outside the process;
- automated or request-time generation, a scheduler, or retries;
- runtime configuration of a synthesis profile, deployment, or an API marker for generated text;
- bilingual output;
- cache pruning.

## Model-facing evidence

`build_synthesis_input` derives local evidence IDs from the candidate: `entity_name`, `title`, `baseline_summary`, `event_state`, plus `competition` (name), `event_time` and `change_time` when present. `result` (canonical JSON) is included only in `show_results` mode.

Candidates are already spoiler-filtered by their loaders, and the builder drops `result` in `hide_results` mode even if a candidate still carries one. Provenance, tier and observation times are not evidence, so a refetch cannot invalidate prose. No article text or raw provider payload reaches the model.

## Output and deterministic verification

The output is JSON `{"sentences": [{"text", "evidence_ids"}]}` with 1–2 sentences, joined into at most 280 characters. `verify_synthesis` rejects, and the template is kept, when:

- **Structure:** the output is not strict JSON or has the wrong shape; a sentence is empty; the summary is too long.
- **Citations:** a sentence cites nothing, or cites an ID absent from the input.
- **Numbers:** a digit run is not in the evidence.
- **Disclosure:** the `Synthetic example: ` label is dropped.
- **Hidden-result mode:**
  - a score-like pair does not appear verbatim in the evidence;
  - outcome vocabulary appears that the evidence does not use. This check is a heuristic.

Entries are verified on write and on read.

## Cache identity

The `summary_syntheses` table is created on first write. It is keyed by `stable_id`, the evidence fingerprint (SHA-256 of schema version plus ordered evidence), spoiler mode, language, prompt version, model ID and schema version.

## Evaluation

**Hard gates come before preference.** A generated summary fails outright if it does any of the following:
- adds an unsupported fact;
- contradicts deterministic evidence;
- leaks a hidden result;
- drops a material qualifier;
- drops the synthetic label;
- cites nonexistent evidence;
- breaks the output schema.

The verifier enforces only the lexical and structural subset. Entailment, contradiction and qualifier preservation remain **human-review and model-quality concerns**; no NLP library or second model is used. Each case therefore records both the expected verifier outcome and the expected hard-gate outcome. The report lists "verifier blind spots": cases the verifier accepts but that fail a hard gate.

**Case format.** Each case has:
- `id` and `description`;
- `spoiler_mode`;
- `candidate`: only fields that can reach the model. The runner fills placeholders for the rest, and the template is `candidate.summary`;
- `generated`: the structured output with evidence citations;
- `expected`: `verifier` accept/reject, `rejection` reason substring, `hard_gates` pass/fail and `hard_gate_note`;
- optional `review`: `{"outcome": "better|same|worse", "reviewer", "comments"}`.

The file pins `prompt_version`, and the runner refuses cases for any other version. The runner exits non-zero when any verifier outcome differs from its expectation.

**Current set (22 cases).** The generated texts are **hand-authored exemplars, not model output**. They pin the gates and document blind spots; they are not evidence that a model is useful. Candidate text follows current loader templates, with names taken from the repository fixtures. Coverage:
- **Arsenal:** upcoming, live, hidden and shown results.
- **Texans:** upcoming game, game-status change with a `Questionable` qualifier, and a recent game in show mode.
- **Scottie:** tee time, hidden and shown results.
- **News:** a synthetic item with `designated for return`.
- **Adversarial:**
  - invented number, invented venue;
  - significance language;
  - home-team inference;
  - instruction-like evidence;
  - score leak and wording leak;
  - unknown evidence ID and schema violation;
  - dropped label, dropped qualifiers.

Limits found or inherited:

- No Scottie LIVE candidate exists (the M5 gate is open), and Texans recent games carry no result evidence. Those cases use the nearest real shapes.
- Arsenal's evidence has `winner: HOME_TEAM` but no separate home/away atoms. A summary that names the winner relies on the unstated "home vs away" order. Add explicit team atoms before show-mode result prose is enabled.
- Lexical checks allow tokens already in evidence. Instruction-like provider text can therefore pass the verifier, although the template would display the same text.
- "Reported" and "expected" qualifiers do not occur in current candidate evidence and are not covered.

**Review workflow once a model exists:**
1. Generate outputs for these cases under a fixed profile.
2. Replace `generated` with the real outputs.
3. Run the report.
4. For verifier-accepted outputs, a reviewer records hard gates first, then `review.outcome` versus the template. The review judges clarity, concision, information density and usefulness for "what should I know right now?". Verbosity and style are not rewarded.

Enable prose only if hard-gate failures are rare enough, and the prose is consistently better than the short templates, to justify model cost, generation latency, operational complexity, rights obligations and a new failure surface. No automated quality score or LLM judge is used.

## Source-rights gate (pre-integration)

External LLM transmission permission is **unresolved unless explicitly verified per source**. This applies independently to:
- football-data.org;
- Sportradar NFL;
- Sportradar Golf;
- Wikinews CC BY 2.5, whose attribution and share-alike obligations would apply to derived prose;
- operator-reviewed news evidence (the Texans site terms prohibit database storage without consent).

The synthesis boundary's technical support is not permission. A source without verified permission must keep its template.

## Deferred decisions before a real model

- LLM vendor and model;
- budget;
- credentials;
- retries and timeouts;
- generation trigger (offline job or CLI, never request time);
- server profile configuration;
- retention and logging policy;
- generated-summary API marker;
- Korean output and its prompt version;
- cache cleanup;
- explicit home/away evidence atoms;
- per-source transmission permission;
- a human review pass over real model outputs.

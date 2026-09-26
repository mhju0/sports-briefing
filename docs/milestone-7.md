# Milestone 7: bounded summary synthesis

M7's first slice adds an optional, cached replacement for one field, `summary`, on candidates that deterministic ranking has already selected. There is no model provider, SDK, credential, network call, prompt text or generation trigger. Tests use a fake model. Without a profile the timeline is byte-for-byte the template output. The HTTP API and CLI pass no profile, so they are unchanged.

## Boundary

`SQLite → candidates → rank_candidates → apply_cached_summaries (optional) → JSON projection`

- Titles, identity, state, tier, order, the 2-per-entity cap, times, competition, provenance and result fields remain deterministic. A cached entry can only swap `summary` on an item that is already selected.
- `apply_cached_summaries` only reads (read-only connection) and never calls a model. A missing database, table or row, or a corrupt or incompatible row, keeps that candidate's template. Other candidates are unaffected.
- `generate_cached_summary` is the only write path: build input → model → verify → `INSERT OR REPLACE`. A model exception or a rejected output writes nothing, and an existing entry survives. Nothing calls it yet; there is no scheduler.

## Model-facing evidence

`build_synthesis_input` derives local evidence IDs from the candidate: `entity_name`, `title`, `baseline_summary`, `event_state`, plus `competition` (name), `event_time` and `change_time` when present. `result` (canonical JSON) is included only in `show_results` mode. Candidates are already spoiler-filtered by their loaders, and the input builder drops `result` in `hide_results` mode even if a candidate still carries one.

Provenance, tier and observation/generation timestamps are not evidence. The model receives no article text or raw provider payloads.

## Output and verification

The output is JSON `{"sentences": [{"text", "evidence_ids"}]}` with 1–2 sentences, joined into at most 280 characters. The deterministic verifier rejects, and the template is kept, when:

- **Structure:**
  - the output is not JSON, or has extra or missing keys;
  - the sentence count is out of range;
  - a sentence is empty;
  - the summary is too long.
- **Citations:** a sentence cites no evidence, or cites an ID absent from the input.
- **Numbers:** a digit run is absent from the evidence (this blocks invented scores, times and counts).
- **Disclosure:** the `Synthetic example: ` prefix of a synthetic news summary is dropped.
- **Hidden-result mode:**
  - a `n-n` score-like pair does not appear verbatim in the evidence;
  - outcome vocabulary (won, beat, draw, finished, …) appears that the visible evidence does not use. This check is a heuristic.

Entries are verified on write and again on read. The verifier cannot prove semantic entailment or that reported qualifiers were preserved (for example, "designated for return"). The reviewed evaluation set must cover those.

## Cache identity

The `summary_syntheses` table is created on first write with `CREATE TABLE IF NOT EXISTS`, following the repository convention. It is keyed by:

- `stable_id`
- `evidence_fingerprint`: SHA-256 of the output schema version plus the ordered evidence atoms
- `spoiler_mode`
- `language`
- `prompt_version`
- `model_id`
- `schema_version`

A refetch that changes only observation or generation metadata keeps prose valid. Any change in synthesis-visible evidence misses the cache and falls back. Superseded rows are not pruned.

## Evaluation fixture (proposed, not implemented)

One JSON object per reviewed case:

```json
{"stable_id": "...", "spoiler_mode": "hide_results", "language": "en",
 "evidence": [["baseline_summary", "..."]], "template": "...",
 "generated": {"sentences": [{"text": "...", "evidence_ids": ["..."]}]},
 "verifier": "accepted", "review": {"outcome": "better|same|worse|unsafe", "comments": "..."}}
```

It will be added with the first real-model slice, when there are generated outputs to review.

## Before enabling a real model

- **Provider decisions:** choose the provider/model, budget, and retention/logging settings.
- **Source rights:** confirm per-source rights to send data to an external LLM. None is established for:
  - football-data.org;
  - Sportradar NFL;
  - Sportradar Golf;
  - Wikinews CC BY 2.5 (attribution and share-alike obligations for derived prose);
  - operator-reviewed news evidence (whose Texans source terms prohibit database storage without consent).
- **Prompt:** write the prompt text and its version constraining output to paraphrase or compression of the supplied evidence.
- **Generation trigger:** decide what calls `generate_cached_summary` and when (offline job or CLI; never `/timeline`).
- **Enablement:** decide how the serving path gets its profile (currently only a `build_home_timeline` argument).
- **Labelling:** decide whether the API should mark generated summaries.
- **Evaluation:** build a reviewed evaluation set against templates before any user-facing enablement. Current templates are short (for example, "Arsenal FC vs Nottingham Forest FC"), so the added value of prose is unproven.

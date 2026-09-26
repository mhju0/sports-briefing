# Sports Briefing — canonical project roadmap

This is the shared current-state record for humans and coding agents. Read it before substantial work and update it when milestone acceptance, scope, architecture, or external blockers change. Detailed evidence stays in `docs/milestone-N.md` and existing `.scratch/milestone-N/spec.md` records; no external tracker is configured.

## Project goal

A continuously updated personal sports timeline for Arsenal, Houston Texans, and Scottie Scheffler. Surface meaningful developments, with at most two items per entity. Quiet entities may produce zero items. This is not a general sports feed.

## Architecture

`SQLite → domain-specific normalized candidates → deterministic shared ranking → CLI / HTTP`

Provider normalization stays in provider/domain modules. Structured providers remain authoritative for schedules, results, and availability. Ranking uses explicit LIVE, IMMINENT, MEANINGFUL_CHANGE, RECENT_RESULT, ROUTINE precedence with deterministic tie-breaking. Provenance is inspectable; unchanged refetches cannot create freshness. The SwiftUI proof remains Arsenal-only.

## Milestone status

| Milestone | Status | Completed / evidence | Remaining acceptance / next action |
| --- | --- | --- | --- |
| M1 — Arsenal ingestion | DONE | Python/SQLite fixture/result ingestion, restart/idempotency, spoiler-safe deterministic briefing; `c6359fe`, live verification `05fd86b`, [record](../milestone-1.md) | None; PL/UCL coverage only |
| M2 — API + SwiftUI | DONE | Thin FastAPI read boundary and iPhone Arsenal slice; [record](../milestone-2.md), verification `211a4c9` | None within bounded slice |
| M3 — Texans schedule + injury/practice | IMPLEMENTATION COMPLETE — ACCEPTANCE OPEN | NFL-specific state/change detection; authenticated schedule and prior-week injury shape; [record](../milestone-3.md), implementation `460418d`, shape fix `33fed3d` | Current target report returned `teams: []`; complete current-target authenticated persistence and second-ingest idempotency when upstream data permits |
| M4 — ranked Arsenal + Texans timeline | DONE | Deterministic sparse shared ranking, CLI/HTTP and offline scenarios; `594fb04`, [record](../milestone-4.md) | Does not close M3 live gate |
| M5 — Scottie Golf | IMPLEMENTATION COMPLETE — ACCEPTANCE OPEN | Stable identity, confirmed field, rounds, tee times, atomic persistence, live unchanged-refetch proof, IMMINENT/ROUTINE and accepted product-observed RECENT_RESULT; `b0016f1`, [record](../milestone-5.md) | Real Scottie-specific supported individual stroke-play LIVE evidence and implementation/acceptance; no synthetic substitute |
| M6 — unstructured/news layer | IN PROGRESS | Offline reviewed-evidence P1 foundation implemented; [record](../milestone-6.md) | Obtain source permission and validate a bounded live adapter/real grouping before full P1 acceptance |
| M7 — bounded LLM synthesis | PLANNED | No implementation | Begin only after explicit scope; synthesis consumes selected evidence, never determines factual state/ranking |

## Current active milestone

**M6 — Unstructured / News Layer.** Chosen narrow proof: Houston Texans IR-placement developments. Live inspection found usable article metadata and separate transaction archive representations, but Texans terms prohibit systematic database retrieval without written consent. The bounded Arsenal alternative did not establish a clearer permitted path. The offline reviewed evidence import and clearly labeled synthetic proof are implemented; no crawler or automatic HTML extraction. Live P1 acceptance remains open. No dependency on closing M5.

Core invariant: multiple source documents can resolve into one provenance-preserving development whose timeline freshness changes only when underlying information meaningfully changes.

P1 acceptance: source traceability; separate publication, observation and meaningful-change clocks; same-document and same-development idempotency; repeated information versus genuine follow-up; atomic isolated news persistence; deterministic sparse candidates through unchanged shared ranking; offline tests and bounded live-source proof. Every article is not a timeline item.

Offline foundation: four news tables, fixed IR-placement topic identity, exact-content/document grouping, one optional placement qualifier follow-up, atomic writes, CLI import/inspect, and one news candidate through existing CLI/HTTP timeline. Both material publication and accepted change must be within 48 hours; date-only effective-date eligibility is bounded to seven days. Next concrete step: obtain permitted source access, then validate bounded source extraction and real same-development grouping. No broader news or M7 implementation is authorized by this slice.

## Durable decisions

- M4: deterministic precedence and stable identity; no numerical relevance weights or LLM ranking.
- M5: `result_finalized_observed_at` is product observation of an accepted known nonterminal-to-final transition, never provider completion time. Historical closed imports do not bootstrap recency.
- M6: `published_at != first_observed_at != meaningful_changed_at`. Historical discovery cannot become fresh news merely because it was fetched today.
- M6: official statements/reported evidence remain separate from structured sport-domain truth; news ingestion must not mutate structured tables.
- M6: use bounded evidence-backed topic identity, not an ontology, claims graph, embeddings, or LLM extraction.

- M6 (2026-09-26): source permission gates automated ingestion. Public access and robots allowance do not establish database/redistribution rights. Offline reviewed input is not live-source acceptance.

## Known external blockers

- M3: current-target Sportradar Texans report availability; last recorded Week 3 response was empty. No fallback to a different week as acceptance.
- M5: await observable Scottie active play in supported individual stroke-play. Do not use cup/team events or another golfer as acceptance.

- M6: permission for systematic official-source retrieval/storage and an authorized live adapter remain unresolved. No external message or sales request has been sent.

## Deferred scope

Broad crawling/news aggregation, social/reporters, LLM synthesis/ranking, vector clustering, new followed entities, personalization, notifications, scheduled/background refresh, deployment/production, and UI expansion. M7 is planned; other later work remains unnumbered.

## Verification snapshot

M6 starting point (2026-09-26): `main`, clean at `b0016f1f79aa7af62ad89dc1937453308b0285c9`. Baseline complete offline suite rerun: **118 passing**. Prior focused Golf snapshot: 37 passing. No prior milestone history rewritten. M3/M5 acceptance gates remain open.

M6 offline verification: **18 focused / 136 complete tests passing**; compile and whitespace checks passed. A temporary copy of the actual database retained exact contents of all 12 original tables. Two synthetic documents produced one topic/two links; identical import changed no rows. One qualifier follow-up produced revision 2/three links exactly once. Separate-process CLI was deterministic; loopback HTTP returned 200 for both spoiler modes. Main application data was untouched. This is synthetic/offline acceptance only, not permission or live-source ingestion proof. Final implementation commit is the commit recording this snapshot; see Git history.

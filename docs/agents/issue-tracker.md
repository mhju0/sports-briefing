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
| M6 — unstructured/news layer | SOURCE-INDEPENDENT IMPLEMENTATION COMPLETE — ACCEPTANCE BLOCKED EXTERNALLY | Offline reviewed-evidence P1 foundation; P2 licensed Wikinews archival adapter live-verified; P3 real two-publication grouping/idempotency verified; [record](../milestone-6.md) | Permitted real current/recent qualifying news candidate. Blocked on source access/rights; source-specific mapping follows real payload evidence. Does not block M7 engineering |
| M7 — bounded LLM synthesis | IN PROGRESS — SLICE 3 AWAITING REVIEW | S1: provider-independent cached summary replacement after ranking (evidence atoms, deterministic verifier, SQLite cache, fake-model tests; inert without a profile). S2: versioned prompt contract, offline evaluation set and report runner. S3: structured `summary_facts` (home/away, status transitions, designation), winner/qualifier checks, prompt `summary-en-v2`; 24 cases, verifier blind spots 7 → 3; [record](../milestone-7.md) | Review slice 3. Real inference needs provider/budget/retention, per-source LLM transmission permission, generation trigger, and human review of real model outputs |

## Current active milestone

**M7** slices 1–3 (cached summary synthesis boundary; prompt contract and offline evaluation set; structured evidence hardening) are implemented and await review; no real model is integrated ([record](../milestone-7.md)). **M6** is blocked externally (see *M6 status and reopen trigger* below); its record follows.

**M6 — Unstructured / News Layer.** P3 extends the permitted Wikinews archive proof with a second real publication repeating the same Xhaka signing fact. Both documents are pinned/reviewed, separately attributed and date-only; unrelated transfers are not normalized. Live verification shows two publications, one topic, two links, revision 1 and no meaningful-freshness refresh. This is same-publisher repetition, not independent corroboration.

The current-candidate gate remains open: Wikinews is read-only and both publications are historical; commercial news access is not configured/confirmed. Existing candidate code supports Texans IR placements, not Arsenal news. Choose the smallest rights-cleared current source before adding any necessary mapping. M3/M5 gates remain unchanged; M7 is planned only.
Core invariant: multiple source documents can resolve into one provenance-preserving development whose timeline freshness changes only when underlying information meaningfully changes.

P1 acceptance: source traceability; separate publication, observation and meaningful-change clocks; same-document and same-development idempotency; repeated information versus genuine follow-up; atomic isolated news persistence; deterministic sparse candidates through unchanged shared ranking; offline tests and bounded live-source proof. Every article is not a timeline item.

Offline foundation: four news tables, fixed IR-placement topic identity, exact-content/document grouping, one optional placement qualifier follow-up, atomic writes, CLI import/inspect, and one news candidate through existing CLI/HTTP timeline. Both material publication and accepted change must be within 48 hours; date-only effective-date eligibility is bounded to seven days. Next concrete step: obtain rights-cleared non-scrambled current Texans news with precise publication metadata, then verify the required source normalization and existing qualifying candidate path. Real grouping is accepted; current candidate emission is not. No broader news or M7 implementation is authorized by this slice.

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

- Public deployment (2026-09-27 rights check; [canonical matrix](../feasibility.md#public-deployment-rights-checked-2026-09-27)):
  - Sportradar trial data may not be displayed publicly.
  - Sportradar §7.4 requires destroying data, derivatives and extracts within 30 days after termination or expiration. The trial dates are not recorded, and the remediation decision is pending with the owner.
  - football-data.org public display and LLM processing await provider confirmation.
  - Scottie is demo-only until a suitable licensed source exists.

- M6: permitted current/recent news source access. Official Texans permission and current commercial news entitlements remain unavailable. The licensed Wikinews archival pair has proved grouping, but not current eligibility. Current-source access remains unavailable; source-specific normalization/candidate work depends on that evidence. No external message or sales request has been sent.

## Deferred scope

Broad crawling/news aggregation, social/reporters, LLM synthesis/ranking, vector clustering, new followed entities, personalization, notifications, scheduled/background refresh, deployment/production, and UI expansion. M7 covers only cached summary replacement and its evaluation; other later work remains unnumbered.

## Verification snapshot

M6 starting point (2026-09-26): `main`, clean at `b0016f1f79aa7af62ad89dc1937453308b0285c9`. Baseline complete offline suite rerun: **118 passing**. Prior focused Golf snapshot: 37 passing. No prior milestone history rewritten. M3/M5 acceptance gates remain open.

M6 offline verification: **18 focused / 136 complete tests passing**; compile and whitespace checks passed. A temporary copy of the actual database retained exact contents of all 12 original tables. Two synthetic documents produced one topic/two links; identical import changed no rows. One qualifier follow-up produced revision 2/three links exactly once. Separate-process CLI was deterministic; loopback HTTP returned 200 for both spoiler modes. Main application data was untouched. This is synthetic/offline acceptance only, not permission or live-source ingestion proof. Final implementation commit is the commit recording this snapshot; see Git history.


P2 verification (2026-09-26; baseline `8b90305`): **8 P2 / 26 combined M6 / 144 complete tests passing**; compile/whitespace checks passed. One licensed Wikinews article fetched twice: 1 document/topic/link at revision 1; second run changed no news rows. Date-only 2016 publication was not replaced by its 2026 edit time or current observation. All 12 existing structured tables remained equal in a copied DB; original DB untouched. CLI repeated output deterministic, loopback HTTP 200 in both spoiler modes, zero historical news items. Real multi-document grouping and eligible source-backed candidate remain open; synthetic P1 scenarios are not relabeled live. The commit containing this snapshot records the bounded P2 implementation; M3/M5 remain acceptance-open and M7 planned.

- M6-P2: licensed archival evidence is valid source proof but not a continuing news feed. Pinned reviewed normalization must fail closed when source content changes. Date-only publication remains date-only; provider edit time is never a substitute.


P3 verification (2026-09-26; starting HEAD `10c6ed444863bb6ebb30803ec7459f379b611bd2`): **11 source-adapter / 29 combined M6 / 147 complete tests passing**, compile/whitespace clean. Real pages 2790899 and 2793763 formed one signing topic/two links; B repeated background information and left revision/meaningful time/material contributor unchanged. A second actual pair fetch left every news row equal. Twelve structured tables were unchanged in the proof copy and original DB. Current timeline remained empty. Date-only batch ordering was corrected without creating timestamps. P3 implementation is recorded by the commit containing this snapshot; see Git history for its HEAD. Independent review is required before integration.

**M6 REMAINS OPEN — permitted real current/recent news-candidate acceptance.** Grouping is now accepted. No configured SportsDataIO access or changed Editorial entitlement evidence was found; prior Editorial 403 was not retried. Current-source access is external; a narrow source-specific mapping may still be needed after payload validation. No new provider framework, candidate tier or eligibility relaxation is authorized.

## M6 status and reopen trigger (2026-09-26 audit)

Audit at `5415575`, clean, 147 tests passing. **Engineering independent of source access is complete:** four-table persistence, three separate clocks, idempotency, grouping, repeat-versus-follow-up, structured isolation, the Texans IR `MEANINGFUL_CHANGE` adapter through the unchanged ranker, and the licensed archival adapter are implemented and tested. The only remaining engineering is **source-specific** (provider normalization, attribution and, if the observed development is not a Texans IR placement, a bounded candidate mapping). It cannot be designed honestly before a real payload exists, so M6 is not labeled fully implementation-complete. No generic or speculative M6 work is justified; M6 is paused, not abandoned.

Reopen M6 acceptance only when one of these exists: permitted real current/recent source access with adequate retention/processing/display rights and precise publication metadata; new entitlement evidence for an already-investigated provider (Sportradar Editorial, Guardian); or another source meeting the same provenance and rights requirements. SportsDataIO NFL News-by-Team (RotoBaller) is the leading candidate, not a required vendor. Its unresolved prerequisites: real non-scrambled access, a configured credential, confirmed retention, normalization/processing and local display rights, attribution obligations, post-license retention/deletion terms, and inspection of a real payload before any adapter. Then prove: real source → persisted current development → deterministic qualifying `MEANINGFUL_CHANGE` candidate → CLI/HTTP timeline → idempotent rerun.

**M7 dependency: none blocking.** M7 consumes the stable `TimelineCandidate` interface after `rank_candidates`; every tier, including news, already reaches it through structured, synthetic and archival evidence. A future source may add candidates of a supported action; it does not change that interface or M7's position after ranking.

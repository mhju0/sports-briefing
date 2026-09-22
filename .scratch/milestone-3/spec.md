# Milestone 3: Texans availability changes

Status: in-progress

Authorized 2026-09-20. Baseline: `211a4c9`. Implementation and authenticated provider verification are separate gates.

## Scope and acceptance

Houston Texans schedule/next game, injury description, practice participation and game designation. Add NFL-specific SQLite state and deterministic meaningful-change history, CLI ingestion/inspection/briefing, and a small read-only HTTP endpoint if straightforward. Preserve Arsenal M1/M2 and all SwiftUI files.

Test the user-requested boundaries: initial ingestion; identical rerun; Limited → DNP and reverse; game designation change; new player; stale rejection; transaction rollback; malformed payload; deterministic briefing; existing Arsenal regression suite. Also test equal-revision conflicts, recurring transitions, week isolation and absence/unknown semantics. Use synthetic documentation-shaped provider fixtures and temporary real SQLite databases; no live dependency in the core suite.

Do not add other NFL entities, opponent injury reports, roster/stat databases, news, reporters, odds, notifications, scheduling, golf, universal ranking, LLMs or client changes.

## Provider gate

Only football-data.org credentials were present at initial inspection. The user was asked to configure any available NFL credential without posting it in chat, then confirmed that the NFL APIs are not ready yet. No account creation, subscription or paid access is assumed.

Sportradar NFL v7 is the provisional single-provider implementation choice. Its official examples separate practice participation, game designation and status date. API-NFL does not document practice fidelity; SportsDataIO's current schema marks its practice fields deprecated. Full research and current source links are in `docs/milestone-3.md`.

Until authenticated Texans responses establish actual field/header availability, M3 remains **awaiting provider verification**, even if all offline tests pass. Documentation examples are not real authenticated Texans captures.

## Integrity decisions

Class 3: new persistent current/previous availability state and atomic change detection. Independent Astra planning review completed before implementation; exact frozen-code review is required before integration.

- NFL-only tables; no Arsenal schema migration or universal event/player framework.
- Stable provider game/player IDs; availability identity includes season, season type and week.
- Upstream `x-generated-date` orders snapshots within a feed scope. `Last-Modified` describes file rebuilding; local fetch time describes receipt. Neither substitutes for missing upstream revision evidence.
- Older snapshots and equal-revision conflicts preserve accepted state. Report dates add a regression guard; a newer snapshot can carry a same-day practice change.
- Compare with immediately current semantic state. Repeats create no change; A → B → A remains a real sequence.
- Missing information is not healthy. Report membership disappearance must never become recovery/cleared, and one week's availability must not be attached to another week's game.
- Fetch/normalize first, then atomically persist accepted state, changes, watermarks and success diagnostics. Bounded failure diagnostics follow rollback.

## Verification record

Implementation complete — awaiting authenticated provider verification.

- 56 offline Python tests pass, including all 31 existing Arsenal M1/M2 tests. New tests cover initial ingestion, identical rerun, recurring participation transitions, game designation, new players, old/equal-conflicting revisions, date regression after a no-op, week isolation, report absence, nulls, deleted games, rollback, network failure, process restart, deterministic briefing, HTTP projection and missing state.
- Independent smoke: a temporary SQLite backup of the real Arsenal DB accepted synthetic Limited → identical Limited → DNP responses (change counts 1, 0, 2). Separate CLI processes retained state and returned deterministic briefings. Actual loopback Uvicorn requests returned 200 for Texans and Arsenal; the Arsenal domain output was unchanged. The original database was not used for synthetic writes.
- `git diff --check` and Python compile checks pass. No SwiftUI files or existing Arsenal test files changed.
- Authenticated access later became available. Post-fix schedule responses normalize successfully; a populated prior-week Texans injury response also matches the implemented player/practice model. The current next-game report returned HTTP 200 with `teams: []`, so no atomic batch or NFL domain state was accepted.
- First frozen candidate `460418d` did not pass independent review. Corrections add per-game revision/scope guards (including deletions), remove the invalid monotonic guard on the team-wide maximum player date, attribute changes to each player's own date, and align CLI/briefing upcoming-status policy. New regression cases reproduce the identified defects.
- Corrected production candidate `85e427e` passed Standards review. Final candidate `3775c761eb3628d6e6cc0467220c76a2005572ac` passed independent Class-3 Spec/integrity review with no blocking findings. The last correction freezes M3 test clocks; both previously clock-dependent cases also passed with an outer January 1, 2027 clock.
- Root reran all 56 tests and compile/diff checks on the final candidate. Actual loopback HTTP/CLI smoke passed against the corrected production code. Existing Arsenal implementation modules, schema, tests and SwiftUI files remain unchanged; only shared CLI/API entry points gained explicit Texans branches.
- Completion remains local implementation/offline verification plus partial authenticated shape validation. No paid subscription, push, deployment or client extension occurred. M3 remains `in-progress`: **Implementation complete — awaiting a populated current-week report and live persisted idempotency verification**.

### 2026-09-22 authenticated schedule regression

- The first entitled current-season schedule request returned successfully with normalized `x-generated-date` value `[redacted]`, then failed normalization with `schedule.id must be a non-empty string`; no NFL domain rows were written.
- The bounded saved response prefix proves the live payload nests `id`, `year`, `type` and `name` inside top-level `season`, with `weeks` remaining top-level. The full raw body and response headers were not retained.
- The normalizer now reads only the nested `season` identity. A sanitized live-shape fixture and regressions verify nested identity, reject a missing `season`, ignore conflicting legacy root metadata, and exercise the same structure through existing CLI/persistence tests.
- All 59 offline tests passed after the schedule regression fix. At that checkpoint a post-fix authenticated rerun was unavailable; the later authenticated evidence is recorded below and supersedes that access limitation.

### 2026-09-22 post-fix authenticated validation

- Current-season schedule: HTTP 200; top-level `season`, `weeks`, `_comment`; season identity nested under `season`; raw `x-generated-date: [redacted]`, normalized to `[redacted]`.
- Current week 3 injuries: first attempt HTTP 429 with [redacted]; controlled retry HTTP 200 with top-level `season`, `week`, `teams`, `_comment`, raw `x-generated-date: [redacted]`, and `teams: []`. The missing report was not converted into an empty/healthy report.
- Read-only week 2 diagnostic: HTTP 200; raw `x-generated-date: [redacted]`; [redacted] teams and [redacted] Texans players. Each Texans player had exactly one injury object with the expected status/status-date/practice/primary structure, and the current normalizer accepted all [redacted].
- No NFL games, availability, changes, or source revisions were persisted because schedule and current-week availability commit atomically. Final inspect therefore reports empty domain state and the latest controlled normalization failure; briefing reports no successful Texans ingestion.
- Stale-revision semantics required no change. Live persisted idempotency could not be tested without a populated current-week response. M3 remains `in-progress`.

### 2026-09-23 KST current-week recheck

- One authenticated week 3 injury read returned HTTP 200 with `teams: []` again. Raw `x-generated-date` remained `[redacted]`; the response `Date` was `[redacted]` (September 23 KST).
- Earlier stored schedule revisions `[redacted]` and later raw/normalized `[redacted]` values came from separate requests. The older raw header was not retained, so only its normalized database value is known.
- No new ingest was run because the current-week Texans report remained absent. NFL domain and revision row counts remain zero; M3 is still awaiting a populated current-week response and live persisted idempotency verification.

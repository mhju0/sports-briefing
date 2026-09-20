# Milestone 3: Texans availability changes

Status: in-progress

Authorized 2026-09-20. Baseline: `211a4c9`. Implementation and authenticated provider verification are separate gates.

## Scope and acceptance

Houston Texans schedule/next game, injury description, practice participation and game designation. Add NFL-specific SQLite state and deterministic meaningful-change history, CLI ingestion/inspection/briefing, and a small read-only HTTP endpoint if straightforward. Preserve Arsenal M1/M2 and all SwiftUI files.

Test the user-requested boundaries: initial ingestion; identical rerun; Limited → DNP and reverse; game designation change; new player; stale rejection; transaction rollback; malformed payload; deterministic briefing; existing Arsenal regression suite. Also test equal-revision conflicts, recurring transitions, week isolation and absence/unknown semantics. Use synthetic documentation-shaped provider fixtures and temporary real SQLite databases; no live dependency in the core suite.

Do not add other NFL entities, opponent injury reports, roster/stat databases, news, reporters, odds, notifications, scheduling, golf, universal ranking, LLMs or client changes.

## Provider gate

Only football-data.org credentials were present at initial inspection. The user was asked to configure any available NFL credential without posting it in chat. No account creation, subscription or paid access is assumed.

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

- 52 offline Python tests pass, including all 31 existing Arsenal M1/M2 tests. New tests cover initial ingestion, identical rerun, recurring participation transitions, game designation, new players, old/equal-conflicting revisions, date regression after a no-op, week isolation, report absence, nulls, deleted games, rollback, network failure, process restart, deterministic briefing, HTTP projection and missing state.
- Independent smoke: a temporary SQLite backup of the real Arsenal DB accepted synthetic Limited → identical Limited → DNP responses (change counts 1, 0, 2). Separate CLI processes retained state and returned deterministic briefings. Actual loopback Uvicorn requests returned 200 for Texans and Arsenal; the Arsenal domain output was unchanged. The original database was not used for synthetic writes.
- `git diff --check` and Python compile checks pass. No SwiftUI files or existing Arsenal test files changed.
- Credentials rechecked: only `FOOTBALL_DATA_API_KEY` is present in local `.env`; no NFL credential was available. No authenticated Texans records, live header semantics, quota/errors or practice fidelity have been verified.
- Frozen candidate independent review pending. M3 remains in-progress solely for the provider verification gate after implementation review is resolved.

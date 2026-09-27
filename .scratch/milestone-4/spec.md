# Milestone 4: Arsenal + Texans ranked home timeline

Status: complete

Authorized 2026-09-23. Baseline: `43e23ee`.

## Scope

Add a deterministic read-only cross-sport timeline over existing normalized Arsenal and Texans state. Preserve M1–M3 ingestion, persistence, briefings, API routes, and the open M3 live-provider gate. No schema, provider, scheduler, UI, golf, news, reporter, LLM, notification, or personalization work.

## Acceptance

- Sport adapters derive bounded meaningful candidates without reading raw provider payloads.
- Explicit precedence is live, imminent, meaningful change, recent result, routine context.
- Deterministic temporal and stable-identity tie breaks are inspectable.
- Duplicate events, unchanged reports, stale evidence and forced entity presence do not fill the surface.
- At most two items per entity survive selection.
- CLI and spoiler-safe HTTP output preserve provider attribution and source clocks.
- Full offline M1–M4 suite passes.

## Verification

- M4 scenario and integration tests cover both sports, persisted SQLite, CLI and HTTP without network access.
- Root verification on the first frozen candidate passed all 78 tests. Loopback HTTP returned 200 for the expected three-item mixed timeline; separate repeated CLI output matched apart from API null omission. All seven actual-database table counts and content hashes were unchanged by timeline reads.
- Missing-database HTTP returned 200 with both entities unavailable without creating a file; corrupt SQLite returned 503. Frozen review's membership and pre-reappearance field-supersession regressions are fixed, genuinely newer fields remain eligible, and the corrected full suite passes 81 tests.
- M3 remains `in-progress` for authenticated current-week Texans persistence/idempotency. M4 completion does not alter that gate.

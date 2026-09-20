# Milestone 1: Arsenal fixture/result ingestion

Status: complete

Authorized 2026-09-20 by the user's Milestone 1 request. Review baseline: `986ed4afde17ad7e04757b13273e011bec663179`.

## Scope

Python, SQLite and CLI only. Fetch Arsenal's football-data.org fixtures/results for Premier League (PL) and UEFA Champions League (CL), normalize football-specific records, persist and update by provider identity, and render a deterministic briefing from saved state. No second provider.

Exclude FA Cup, League/EFL Cup, every other competition, injuries, news, press conferences and reporters/X. No iOS/frontend, server framework, containers, CI, scheduler/worker, queue, LLM, agents, RAG, authentication or future-sport framework.

## Acceptance boundaries

The user explicitly requested tests at these boundaries:

1. Ingestion to persisted readback: first insert; identical rerun with no duplicates; changed record updates the same identity.
2. Real SQLite/process boundary: state survives closure and a new process; failures preserve existing data and batch atomicity.
3. Provider boundary: deterministic mocked responses; network/access and malformed/unexpected data fail clearly without depending on a live API.
4. Briefing boundary: same persisted state produces the same representation; hidden-result mode contains no score/winner/result and does not mutate storage.

Retain provider/record IDs, source and fetch times, and bounded raw diagnostics. Log fetch, normalization, persistence and briefing failures distinctly. Credentials belong in environment configuration, never repository files or logs.

## Delivery evidence

Completed 2026-09-20. Implementation commits: `c6359fe` and `3a1aa81`.

- All 21 offline tests pass (`python3 -m unittest discover -s tests -v`), including real SQLite rollback, subprocess restart/readback, reserved-character filenames, HTTP errors, idempotency, updates, deterministic output and spoiler-safe projection.
- `python3 -m compileall -q sports_briefing tests` and `git diff --check` pass.
- Manual mocked-transport CLI ingestion in separate processes inserted two supported fixtures, then reported two no-ops. Persisted readback and shown/hidden briefings succeeded; repeated hidden output was identical.
- Independent Standards review found no blocking violations. Removed inert unittest configuration; retained the small, justified failure-handler duplication and documented field-order coupling as nonblocking review observations.
- Independent Spec review of frozen implementation `3a1aa81ed6394cdabb0b735ac496ccb96fafbbb7` passed after fixing encoded SQLite paths, provider attribution and datetime ordering. Explicit connection closure preserves transaction commit/rollback.

Live provider verification completed 2026-09-20 using the user's locally configured credential. All three requested CLI commands exited 0. HTTP 200 returned 22 supported records (PL 16, CL 6); a second ingestion reported 0 inserts, 0 updates and 22 no-ops. Separate-process inspection retained 22 fixtures, and repeated hidden briefings were identical with no result fields. Status: Done for M1, with the observation limits below.

Observed window: 2026-08-21 inclusive to 2026-12-19 exclusive. Statuses: FINISHED 6, TIMED 16. All durations REGULAR; `group` null in all records and fullTime home/away null for the 16 upcoming fixtures. Scores contained duration, fullTime, halfTime and winner. Kickoff and lastUpdated used UTC Z timestamps.

Provider `lastUpdated` ranged 2026-09-20T10:20:29Z–10:20:31Z, later than local fetch completion at 09:51:55Z / 09:52:31Z. The cause of this clock discrepancy is unknown. Stale protection compares provider lastUpdated against the previously stored provider lastUpdated, not against fetch time; equal revisions may still update changed normalized fields. Fetch time records receipt/freshness only. No timestamp was rewritten to conceal this discrepancy.

One separate invalid-token request (without touching fixture storage) returned HTTP 400 with JSON `{"message":"Your API token is invalid.","errorCode":400}`. Live 403/429/5xx, extra time, penalties, postponed and cancelled fixtures were not observed; these are not claimed as live-verified. No normalization defect was observed, so no application change or regression fixture was necessary. `.env` and the SQLite database are Git-ignored; credentials were loaded into subprocess environment without printing or shell-executing the file.

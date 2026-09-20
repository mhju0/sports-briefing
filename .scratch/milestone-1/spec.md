# Milestone 1: Arsenal fixture/result ingestion

Status: in-progress

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

Pending implementation and review. Live provider operation must be labeled separately from deterministic fixture-based verification. A missing credential does not prevent offline test completion.

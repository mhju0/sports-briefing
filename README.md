# Sports Briefing

A continuously updated personal sports timeline for Houston Texans, Arsenal, and Scottie Scheffler. It answers: **What is the most important thing I should know about this team or player right now?**

Meaningful, source-backed changes take priority over volume. A followed entity can disappear from home when nothing meaningful has happened.

## Status

Milestone 1 is complete and live-verified: a **Python/SQLite Arsenal fixture/result pipeline** and deterministic CLI briefing. Milestone 2 adds a local FastAPI read endpoint and a minimal SwiftUI iPhone screen; see its [setup and verification](docs/milestone-2.md). Arsenal coverage supports only Premier League and UEFA Champions League. FA Cup, EFL Cup, other Arsenal competitions, Arsenal injuries, news and reporter material remain unsupported.

Milestone 3 adds a separate Texans schedule and practice/status-change pipeline. Its Sportradar integration is provisional and **awaiting authenticated provider verification**; see [M3 setup and limitations](docs/milestone-3.md). The iPhone app remains Arsenal-only.

Milestone 4 adds a deterministic, read-only Arsenal + Texans home timeline with explicit cross-sport precedence, sparse per-entity selection, explainable reasons, and CLI/HTTP output. M4 is offline-complete; it does not close M3's separate authenticated current-week persistence/idempotency gate. See [M4 behavior and ranking rules](docs/milestone-4.md).

Milestone 5 adds bounded Scottie Scheffler PGA stroke-play ingestion, conservative tee-time candidates, and product-observed recent-result eligibility after a known finalization transition. Authenticated ingestion, persisted readback, and unchanged rerun are verified; Scottie-specific live-state evidence remains open. See [M5 setup and evidence](docs/milestone-5.md).

Milestone 6 is active. Its first proof accepts **manually reviewed, explicitly authorized Texans transaction evidence** from JSON and groups documents into one provenance-preserving development. Automated official-source retrieval remains gated by source-use terms. The offline proof and its limits are in [M6 development evidence](docs/milestone-6.md).

## Run Milestone 1

Use Python 3.11+ from this directory. Export your football-data.org token as `FOOTBALL_DATA_API_KEY`; see [setup and behavior](docs/milestone-1.md) for safe credential entry, data limits and debugging.

```sh
python3 -m sports_briefing ingest arsenal --from 2026-09-01 --to 2026-11-01
python3 -m sports_briefing inspect arsenal
python3 -m sports_briefing briefing arsenal --hide-results
python3 -m sports_briefing timeline
python3 -m unittest discover -s tests -v
```

M1 ingestion/CLI use only the Python standard library. For the complete test suite and M2 server, install the dependencies in the [M2 setup](docs/milestone-2.md). Tests run offline with synthetic responses and temporary SQLite files. `inspect` exposes stored results for debugging; use `briefing --hide-results` for spoiler-safe output.

## Read next

- [Product specification](docs/product-spec.md): agreed scope, behavior, and exclusions
- [Feasibility](docs/feasibility.md): dated source research, licensing and coverage gaps
- [Decisions and proposed architecture](docs/decisions.md): trade-offs, domain boundaries, first milestone
- [Milestone 1 setup](docs/milestone-1.md): commands, schema, failure behavior and verification
- [Milestone 2 setup](docs/milestone-2.md): local API, iPhone client, contract and limitations
- [Milestone 3 setup](docs/milestone-3.md): Texans ingestion, change history and provider-verification gate
- [Milestone 4 setup](docs/milestone-4.md): cross-sport candidates, ranking, timeline CLI/API and limits
- [Milestone 5 setup](docs/milestone-5.md): Scottie Golf ingestion, source clocks, tee-time and observed-result candidates, and the remaining LIVE gate
- [Milestone 6 development evidence](docs/milestone-6.md): narrow Texans reviewed-document import, topic grouping, freshness, and open source-access gate

This is a separate repository from FullCourt. No FullCourt code is copied.

Matt Pocock's existing user-level skills are available; no new skills were installed. Milestone tracking uses local Markdown under `.scratch/`, with the convention in [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md). No external tracker is configured.

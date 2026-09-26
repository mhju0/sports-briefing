# Sports Briefing

A continuously updated personal sports timeline for Houston Texans, Arsenal, and Scottie Scheffler. It answers: **What is the most important thing I should know about this team or player right now?**

Meaningful, source-backed changes take priority over volume. A followed entity can disappear from home when nothing meaningful has happened.

## Project goals & engineering principles

Sports Briefing is a real personal product, deliberately built to portfolio-grade engineering standards. The aim is to demonstrate sound engineering judgment, not a list of technologies, and it is not tailored to any one employer or role.

- **Smallest defensible design.** Every architectural or technology choice has to be justified by a product need, and its tradeoffs have to be explainable. Complexity added only to show off a tool is treated as a defect.
- **Deterministic core.** Structured providers and explicit domain rules decide facts, freshness and ranking. Generated language is optional and always has a template fallback.
- **Evidence and provenance first.** Every item traces to its source and observation time. Source permissions are checked before data is stored or sent anywhere.
- **Degrade, don't break.** One provider's failure or a missing model must not take down other entities' items.
- **Offline, reproducible tests** with synthetic fixtures. Each milestone records what is verified live and what is still open.

## Status

Milestone 1 is complete and live-verified: a **Python/SQLite Arsenal fixture/result pipeline** and deterministic CLI briefing. Milestone 2 adds a local FastAPI read endpoint and a minimal SwiftUI iPhone screen; see its [setup and verification](docs/milestone-2.md). Arsenal coverage supports only Premier League and UEFA Champions League. FA Cup, EFL Cup, other Arsenal competitions, Arsenal injuries and current news/reporter feeds remain unsupported; M6 has a separate archival news proof.

Milestone 3 adds a separate Texans schedule and practice/status-change pipeline. Its Sportradar integration is provisional and **awaiting authenticated provider verification**; see [M3 setup and limitations](docs/milestone-3.md). The iPhone app remains Arsenal-only.

Milestone 4 adds a deterministic, read-only Arsenal + Texans home timeline with explicit cross-sport precedence, sparse per-entity selection, explainable reasons, and CLI/HTTP output. M4 is offline-complete; it does not close M3's separate authenticated current-week persistence/idempotency gate. See [M4 behavior and ranking rules](docs/milestone-4.md).

Milestone 5 adds bounded Scottie Scheffler PGA stroke-play ingestion, conservative tee-time candidates, and product-observed recent-result eligibility after a known finalization transition. Authenticated ingestion, persisted readback, and unchanged rerun are verified; Scottie-specific live-state evidence remains open. See [M5 setup and evidence](docs/milestone-5.md).

Milestone 6's source-independent implementation is complete; its current-news acceptance is blocked on external source access and does not block M7. The offline Texans evidence proof groups reviewed publications into developments. P2/P3 add a bounded licensed Wikinews archival retrieval proof for two Arsenal reports about the same signing, with normalization pinned to reviewed source content. Historical, date-only evidence remains quiet on home. Real grouping is supported by a pinned archival pair; qualifying current news-candidate acceptance remains open; official Texans retrieval permission is unresolved. See [M6 evidence and source limits](docs/milestone-6.md).

Milestone 7 adds optional, verified summary prose after deterministic ranking. It includes a spoiler-aware evidence boundary, a cache keyed by evidence, prompt and model, a versioned prompt contract, and an offline evaluation set. No LLM provider is integrated; the timeline always falls back to its templates. See [M7 synthesis boundary and evaluation](docs/milestone-7.md).

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
- [Milestone 6 development evidence](docs/milestone-6.md): Texans reviewed import, Wikinews archival proof, provenance, freshness, and remaining acceptance
- [Milestone 7 synthesis](docs/milestone-7.md): bounded summary synthesis, verifier, cache identity, prompt contract and evaluation workflow

This is a separate repository from FullCourt. No FullCourt code is copied.

The canonical current roadmap is [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md); detailed historical records also exist under `.scratch/`. No external tracker is configured.

# Sports Briefing

A continuously updated personal sports timeline for Houston Texans, Arsenal, and Scottie Scheffler. It answers: **What is the most important thing I should know about this team or player right now?**

Meaningful, source-backed changes take priority over volume. A followed entity can disappear from home when nothing meaningful has happened.

## Status

Milestone 1 implements a local **Python/SQLite Arsenal fixture/result pipeline** and deterministic CLI briefing. Only Premier League and UEFA Champions League are supported. FA Cup, EFL Cup, other competitions, injuries, news and reporter material are unsupported. The iPhone application and broader architecture remain unimplemented.

## Run Milestone 1

Use Python 3.11+ from this directory. Export your football-data.org token as `FOOTBALL_DATA_API_KEY`; see [setup and behavior](docs/milestone-1.md) for safe credential entry, data limits and debugging.

```sh
python3 -m sports_briefing ingest arsenal --from 2026-09-01 --to 2026-11-01
python3 -m sports_briefing inspect arsenal
python3 -m sports_briefing briefing arsenal --hide-results
python3 -m unittest discover -s tests -v
```

Tests run offline with synthetic provider responses and real temporary SQLite files. `inspect` exposes raw stored results for debugging; use `briefing --hide-results` for spoiler-safe output. No Python dependencies need installing.

## Read next

- [Product specification](docs/product-spec.md): agreed scope, behavior, and exclusions
- [Feasibility](docs/feasibility.md): dated source research, licensing and coverage gaps
- [Decisions and proposed architecture](docs/decisions.md): trade-offs, domain boundaries, first milestone
- [Milestone 1 setup](docs/milestone-1.md): commands, schema, failure behavior and verification

This is a separate repository from FullCourt. No FullCourt code is copied.

Matt Pocock's existing user-level skills are available; no new skills were installed. Milestone tracking uses [local Markdown](.scratch/milestone-1/spec.md), with the convention in [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md). No external tracker is configured.

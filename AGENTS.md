# Agent guidance

Durable rules for coding agents in this repository. Architecture lives in `docs/`, current milestone state lives in the tracker, and project intent lives in the README. Don't copy them here.

## Before you start
- Read `docs/agents/issue-tracker.md` before any milestone work. Treat it and the repository as authoritative over pasted handoffs, and report discrepancies instead of silently adapting.
- Engineering choices follow the README's "Project goals & engineering principles". Prefer the smallest design whose tradeoffs you can defend, and don't add technologies without a product need.

## Invariants
- Structured providers and deterministic domain logic are the source of truth. An LLM never decides factual state, freshness, eligibility, ranking, item selection or ordering; it may only phrase text for already-selected items, with a template fallback.
- Spoiler-safe output (`hide_results`) is the default everywhere, including generated text.
- Never weaken evidence or eligibility rules just to make live validation pass. Record the open gate instead.
- Respect provider and source-rights boundaries (see `docs/feasibility.md` and the milestone records). Don't bypass site terms. Don't retry access that was denied for entitlement reasons without new entitlement evidence. Technical ability to send data to a model is not permission to send it.
- Never print or commit credential values. `.env` stays local, and `.env.example` holds names only.

## Checks
```sh
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q sports_briefing tests
git diff --check
```
Tests stay offline, using synthetic or pinned fixtures and temporary SQLite files. Authenticated or live checks run only when a task explicitly calls for them, and never against the default database with synthetic data.

## Records and commits
- Update `docs/agents/issue-tracker.md` only when project state materially changes (milestone status, scope, architecture, external blockers). Evidence details belong in `docs/milestone-N.md`.
- Commit messages use this repository's sentence-case imperative style, for example "Add provider-independent cached summary synthesis after ranking", with no type prefix.
- Keep per-slice status and temporary task instructions out of this file.

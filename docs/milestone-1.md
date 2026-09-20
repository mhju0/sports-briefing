# Milestone 1: Arsenal data pipeline

This milestone is a local Python/SQLite CLI, not the full product. It supports **Premier League (PL)** and **UEFA Champions League (CL)** only, using football-data.org v4. FA Cup, League Cup/EFL Cup, all other competitions, injuries, team news, press conferences and reporter/X information are unsupported.

## Setup and commands

Use Python 3.11 or newer from the repository root. M1 runtime and its tests use the Python standard library; no service or live API is needed for those tests. The complete suite now includes M2 HTTP tests, which require the dependencies in [M2 setup](milestone-2.md).

Get a football-data.org credential for your own account/application. Export it as `FOOTBALL_DATA_API_KEY`; `.env.example` documents configuration, but the application does not automatically load `.env`. For an interactive bash/zsh shell, enter the key without echoing it or putting its value in shell history:

```sh
read -r -s FOOTBALL_DATA_API_KEY
export FOOTBALL_DATA_API_KEY
```

Run an explicit UTC date window (`--from` inclusive, `--to` exclusive):

```sh
python3 -m sports_briefing ingest arsenal --from 2026-09-01 --to 2026-11-01
python3 -m sports_briefing inspect arsenal
python3 -m sports_briefing briefing arsenal --hide-results
python3 -m sports_briefing briefing arsenal
python3 -m unittest discover -s tests -v
```

The default database is `data/sports_briefing.sqlite3`, relative to the working directory. Use `--db PATH` on any command to select another file. Without dates, ingestion requests the interval from 30 days before today (UTC) to 90 days after today, excluding the end date. When overriding, supply both dates. `--timeout` controls the network timeout (default 15 seconds).

The CLI prints JSON to stdout and stage-specific logs to stderr. `inspect` is a debugging command and exposes saved scores; it is not a spoiler-safe display. Only the briefing's `--hide-results` output has the spoiler guarantee. No result is deleted by hiding it.

Briefing defaults to the last successful fetch time as its evaluation time, so running it repeatedly against unchanged saved state is deterministic. `--as-of 2026-09-20T12:00:00Z` supplies another reference time. This does **not** replay historical provider state: the database keeps the latest accepted version of each fixture. Relative freshness should be read from timestamps, not a claim that the data is live.

The fixture/result endpoint is authenticated with `X-Auth-Token`. Free access can be delayed. A successful request only proves the data returned for that account and window, not complete Arsenal coverage or real-time delivery. Keep the required provider attribution when displaying derived output. See [provider registration terms](https://www.football-data.org/client/register).

## Provider contract

Arsenal is provider team ID **57**. Fetch `/v4/teams/57/matches` with a bounded date range and explicit limit. The documented team-match filters do not include competitions, so filter returned records to PL/CL locally. Unsupported matches are not normalized into football fixtures; the diagnostics may retain their original response as received.

The source's `lastUpdated` describes the provider record; fetch time describes when this process received it. Neither establishes a guaranteed live feed. A missing match in a later response does not prove cancellation or authorize deleting it. `SCHEDULED` means a tentative time; `TIMED` is a finalized kickoff. Unknown/null fields must remain distinguishable from zero scores.

`score.fullTime` is also the running score, and its meaning depends on `score.duration`. For knockout matches, preserve extra-time/penalty context rather than claiming every displayed total is a 90-minute result. A `FINISHED` flag alone must not manufacture a missing score. [Team endpoint](https://docs.football-data.org/general/v4/team.html), [statuses](https://docs.football-data.org/general/v4/match.html), [score semantics](https://docs.football-data.org/general/v4/overtime.html), [null policy](https://docs.football-data.org/general/v4/policies.html).

## Data flow and storage

`cli.py` parses the command and environment. `football_data.py` requests the team-match endpoint and validates/normalizes the response into football fixtures. `storage.py` commits the accepted batch and source metadata together. `briefing.py` reads saved state and selects next/latest matches using deterministic rules; it makes no network calls.

| Table | Why it exists |
| --- | --- |
| `football_fixtures` | One current row per provider match, including competition, season, home/away teams, kickoff, status, score components, provider update time, fetch provenance and the latest accepted raw record. |
| `provider_fetches` | A bounded diagnostic history of requests, windows, timing, outcomes, counts and response excerpts, including failed attempts. It is not an event log used to reconstruct fixtures. |

The SQLite row ID is internal. A unique `(provider, provider_match_id)` maps the external record to that same row on every run. Kickoff, status and scores are mutable attributes, never identity keys. Competition/season IDs are retained on fixtures; two competitions do not justify separate catalogue tables yet.

An insert means a new provider identity. An update means accepted normalized football fields changed. A no-change result means the football data stayed the same; source-fetch metadata may still refresh. Newer provider data can correct an existing record. Older revisions must not regress it. Absent records are retained because a bounded or permission-limited response is not a deletion notice.

HTTP bodies are limited to 2 MiB. Each accepted fixture retains its latest raw match JSON, replacing that value rather than appending revisions. Fetch diagnostics retain the latest 20 attempts plus the last successful attempt (at most 21 rows), with each response excerpt capped at 256 KiB and a truncation flag. This preserves usable freshness after a run of failures without growing a response archive indefinitely. Per-match history is not retained.

Fetch and normalization finish before fixture writes. One SQLite transaction updates the batch and inserts its successful-fetch metadata. A persistence failure rolls back both. A failed provider/normalization attempt can add diagnostic metadata but never partially replace accepted fixtures. SQLite failures themselves are logged; a broken/unwritable database cannot be relied on to save its own failure report.

The initial schema uses `CREATE TABLE IF NOT EXISTS`; no migration system exists. Use a new database for this version, not an unrelated SQLite file. Future incompatible schema changes require an explicit migration decision. All SQLite data and journals are ignored by Git.

To inspect raw provider evidence directly, use SQLite (these queries expose spoilers):

```sh
sqlite3 data/sports_briefing.sqlite3 'SELECT provider_match_id, raw_record_json FROM football_fixtures LIMIT 1;'
sqlite3 data/sports_briefing.sqlite3 'SELECT outcome, error_stage, error_message, raw_response_truncated FROM provider_fetches ORDER BY id DESC LIMIT 5;'
```

Spoiler-safe output is constructed from allowed identity, competition, time and status fields. It omits result fields rather than modifying the row or passing raw JSON through a text renderer. Selection is based on time/status, not win/loss significance.

## Failure behavior and verification

- Missing key or invalid command configuration: nonzero exit before a request.
- Access/quota/server error, timeout, oversized response or invalid JSON: provider-stage failure. There are no automatic retries; inspect the error and retry deliberately, respecting provider limits.
- Missing/wrongly typed required fields, unknown status, duplicate supported match ID, mismatched count or a response reaching the 500-match limit: reject normalization rather than silently persist a partial batch.
- Unwritable/invalid/locked SQLite database: persistence-stage failure; preserve transaction atomicity.
- Invalid briefing timestamp or malformed stored score JSON: briefing-stage failure.
- Empty returned set: a valid observation, not proof of complete coverage or deletion of previously saved rows.

The automated suite tests first insert, no-op rerun, update of the same record, readback from another Python process, network and malformed-response preservation, SQLite rollback, deterministic output, spoiler hiding, stale-revision rejection, diagnostic retention and actual HTTP request construction/error handling. It uses only synthetic responses and real temporary SQLite databases; no live API is contacted.

## What to understand before the next milestone

The important boundary is **observed provider data → validated football record → committed SQLite state → public briefing projection**. Provider/network errors, normalization errors, persistence errors and briefing errors must remain distinguishable.

Review the tests alongside the implementation. Fixture-based success is not proof of authenticated provider access. The initial implementation session had no credential. On 2026-09-20, authenticated CLI ingestion/readback/hidden briefing succeeded with 22 PL/CL fixtures, and rerunning produced 22 no-ops. See the [live verification record](../.scratch/milestone-1/spec.md) for observed fields, the provider/fetch timestamp discrepancy and unobserved edge cases. This does not establish a provider latency guarantee. Future providers, retention licensing for a public app, a server, scheduling and UI are deliberately left for later decisions.

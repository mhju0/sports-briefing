# Milestone 3: Texans availability ingestion

Implementation and offline verification are complete. Authenticated NFL provider verification is pending; no NFL credential was present, and the user confirmed that these APIs are not ready yet. Scope is Houston Texans schedule, injury description, practice participation and game designation. The iPhone app is unchanged.

## Provider decision — checked 2026-09-20

| Candidate | Current documented evidence | Decision |
| --- | --- | --- |
| API-NFL / API-Sports | Current injury records provide identity/date/status/description; the official guide says injury history is not retained. Practice participation is not documented. Free access is 100 requests/day; Pro is listed at $15/month. | Cheapest candidate, but not enough evidence for Full/Limited/DNP. No key was available for an authenticated trial; do not substitute generic injury text for practice status. |
| SportsDataIO | NFL injury schema includes PlayerID, InjuryID, BodyPart, Status and Updated. Current OpenAPI marks Practice and PracticeDescription deprecated; schedule data has ScoreID/GameKey and DateTimeUTC. Trial data can be scrambled; product entitlements differ. | Defer until entitled real payloads demonstrate reliable practice fields. A documented injury-status feed alone does not satisfy M3. |
| Sportradar NFL v7 | Weekly Injuries explicitly separates player GUID, primary injury text, practice.status, injury.status and status_date. Official examples show DNP, Full and missing game designation. Season Schedule supplies game/team IDs and week identity. | Provisional single integration. Best documented match to the actual practice-change question; authenticated behavior still unverified. |

Sources: [API-NFL guide](https://www.api-football.com/news/post/how-to-get-started-with-api-nfl-the-complete-beginners-guide), [API-NFL pricing](https://api-sports.io/sports/nfl), [SportsDataIO workflow](https://sportsdata.io/developers/workflow-guide/nfl), [SportsDataIO OpenAPI](https://cdn.sportsdata.io/openapi/NFL-openapi-3.1.json), [Sportradar weekly injuries](https://developer.sportradar.com/football/reference/nfl-weekly-injuries), [official injury examples](https://developer.sportradar.com/football/docs/nfl-ig-rosters), [schedule guide](https://developer.sportradar.com/football/docs/nfl-ig-schedules).

The current Sportradar account guide states a **30-day** trial, normally **1,000 calls per rolling 30 days and 1 QPS**. This corrects the older 90-day figure in the initial feasibility document. Production access/pricing are contractual; account-specific limits must be checked. The trial is described as real-world data with limited exceptions, not a universal entitlement guarantee. [Account/access guide](https://developer.sportradar.com/getting-started/docs/your-account).

API access is not clearance to publish the data. Display, retention, attribution and derivative-use terms remain unresolved; current terms also discuss data destruction after agreement termination. No commercial rights, permanent retention rights or public release are claimed. No accounts or subscriptions were created. [Sportradar terms](https://developer.sportradar.com/sportradar-updates/page/terms-and-conditions), [SportsDataIO rights](https://sportsdata.io/help/data-rights-and-licensing-questions).

## What is verified versus assumed

**Verified current documentation:** official v7 response examples use a season/week scope, teams with players, and each player's injury entries. Injury fields include `primary`, optional game `status`, `status_date`, and nested `practice.status`. The example is a trimmed Jaguars report, not a Texans capture. Texans team GUID `82d2d380-3834-4938-835f-aec541e5ece7` appears in the [official historical schedule example](https://developer.sportradar.com/football/docs/nfl-ig-historical-data). Player names/jersey numbers are not identity keys.

The [header documentation](https://developer.sportradar.com/getting-started/docs/authentication) distinguishes `x-generated-date` (upstream generation) from `Last-Modified` (versioned/translated file build). Injury `status_date` is documented as a status timestamp, but examples are at midnight; it cannot safely be treated as a precise intraday revision clock.

**Architectural judgment:** use the upstream generation timestamp to order snapshots, with report-date regression checks. Do not silently substitute local fetch time. Persist local before/after changes because a historical weekly endpoint does not establish access to every prior daily practice state.

**Unverified:** actual credential entitlement, Texans payloads, header presence/ordering, status spelling variations, multiple injury entries, missing/empty team semantics, live nulls, latency and error/quota responses. Synthetic fixtures exercise a documented contract; they do not close this gap.

## Boundaries and limitations

NFL games and weekly availability stay separate from football fixtures. A player appearing in a new week is a new weekly report, not automatically an improvement or worsening from the previous week. Disappearance is only report membership evidence; it is never a claim that the player recovered or is cleared to play. No sophisticated player importance scoring is justified yet.

No all-team user-facing ingestion, opponent availability, full roster, statistics, play-by-play, betting, press conferences, reporters/X, news, scheduling, notifications, golf, cross-sport ranking, LLM calls, deployment or SwiftUI changes.

## Storage boundary

Arsenal's existing tables remain unchanged. The additive NFL tables have separate responsibilities:

| Table | Why it exists |
| --- | --- |
| `nfl_games` | Texans games, provider game identity, season/week context, teams, kickoff/status and latest raw game record. |
| `nfl_availability_current` | Latest observed player availability within one season/type/week/team scope; retains provider player ID, unknown fields and report membership. No full roster database. |
| `nfl_availability_changes` | Meaningful observed field changes with previous/new value and source/observation time. These are locally observed transitions, not a provider-complete historical archive. |
| `nfl_source_revisions` | Durable accepted revision and normalized-content hash per endpoint scope. Diagnostic pruning cannot erase stale-update protection. |
| `nfl_fetches` | Bounded fetch diagnostics, failure stage and raw response excerpts. |

Game identity is `(provider, provider_game_id)`. Availability identity is `(provider, season_year, season_type, week, team_id, player_id)`. Names are display attributes, not join keys. The same player appearing in a new week starts a new scope.

The ingestion boundary validates both payloads before opening a short SQLite write transaction. Accepted games, availability, change history, source revisions and success diagnostics commit together. Failed persistence rolls back the batch; a separate best-effort failure diagnostic explains the failed attempt. This deliberately favors consistent scope over partially refreshing a schedule when the required injury report fails.

Verification status is recorded in the [local tracker](../.scratch/milestone-3/spec.md).


## Local commands

Use the existing Python environment from [M2 setup](milestone-2.md). No new runtime dependency, database server or scheduler is needed. Obtain a credential entitled to **Sportradar NFL Official v7 trial**; this adapter currently uses the trial URL, not an arbitrary provider URL.

The CLI reads process environment variables; creating `.env` alone does **not** load it. For an interactive zsh session, enter the token without putting it in shell history:

```sh
read -rs 'SPORTRADAR_API_KEY?Sportradar NFL token: '
export SPORTRADAR_API_KEY
python3 -m sports_briefing ingest texans
python3 -m sports_briefing inspect texans
python3 -m sports_briefing briefing texans
```

Default ingestion fetches the current-season schedule and chooses the next Texans game's week for the injury request. To inspect a specific game-week report, provide all three scope arguments:

```sh
python3 -m sports_briefing ingest texans --season 2026 --season-type REG --week 3
```

This example chooses a scope; it does not claim that the account has that report. `--db /path/to/file.sqlite3` keeps experiments separate from the default `data/sports_briefing.sqlite3`. Do not put synthetic fixtures into the real provider database.

`briefing texans --as-of <timezone-aware timestamp>` evaluates **current saved state** against a chosen time. It does not restore the state known at that time and must not be used as historical replay. Without the switch, evaluation uses the last successful fetch time, preserving deterministic saved-state output.

For HTTP, start the existing server from the repository root:

```sh
.venv/bin/python -m uvicorn sports_briefing.api:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/briefings/texans
```

The endpoint only reads persisted state. It never fetches from Sportradar. No client changes, authentication or remote exposure are included.


## Meaningful changes and clocks

Compare the incoming normalized values against the immediately preceding accepted state **within the same weekly scope**:

- First appearance: `NEW_REPORT`.
- Changed practice participation: `PRACTICE_STATUS_CHANGED` (`FULL`, `LIMITED`, `DNP` for the documented spellings).
- Changed game designation: `GAME_STATUS_CHANGED` (for example, `QUESTIONABLE` to `OUT`).
- Changed injury description: `INJURY_CHANGED`.
- Previously present player absent from an explicit newer Texans player list: `REMOVED_FROM_REPORT`. This means only “not present in this response,” never “recovered” or “cleared.” The retained previous status is not presented as current availability.
- Same semantic availability: no new change row (`NO_CHANGE` is an outcome, not an event).

A transition can change several fields and produce several typed change rows. Source revision is part of change identity: repeated identical fetches add nothing, while Limited → DNP → Limited → DNP remains three distinct transitions. Unknown/null is not Full, healthy or available. Unknown status spellings remain explicit provider values rather than being guessed into a known category.

`x-generated-date` orders accepted snapshots within each season schedule or weekly injury scope. An older revision rejects the batch. An equal revision with different normalized content is a conflict, not a silent overwrite. A newer revision may change same-day participation; a regressing player `status_date` is rejected against that same player's prior date. A report-level date is only the maximum date among currently listed players, not an authoritative snapshot clock: removing the newest-dated player must not make a valid snapshot appear stale. Change rows use the affected player's own date; removal has no new player report date. Missing upstream revision evidence fails clearly instead of substituting local receipt time.

These are conservative implementation rules, pending actual account payloads. A game ID cannot silently move to a different season identity, and a payload listing the same game as active and deleted fails clearly. CLI selection and briefing share one upcoming-status policy (`scheduled`, `created`, `time-tbd`, `flex-schedule`); postponed/delayed/live games are not selected as upcoming in this milestone. Each player must currently have exactly one injury entry; zero/multiple entries fail normalization rather than arbitrarily choosing one. A missing Texans team or missing `players` array also fails clearly. Explicit empty lists are a different observation from missing fields, but do not prove roster health. All-or-nothing ingestion may therefore fail before a weekly report is published; previous accepted data remains available with its old freshness.

Raw response retention is bounded to 256 KiB per endpoint per attempt, for the latest 20 attempts plus the latest success when outside that window. Each accepted game/player keeps its latest raw record. HTTP bodies have a 2 MiB hard limit. Meaningful changes are retained; repeated unchanged polls do not accumulate change rows. This is not full event sourcing, and no complete historical replay is offered.


## Briefing and HTTP boundary

`build_texans_briefing` reads a consistent SQLite snapshot. It selects the next saved game with a supported upcoming status and kickoff at or after the evaluation time. It attaches only that season/type/week's availability report, present players and the latest 20 observed change rows for that scope. This is deterministic backend output, not player-importance scoring or home timeline ranking. Historical report inspection remains available through `inspect texans` even when there is no next-game briefing attachment.

`availability_report.available=false` means the next game's report has not been ingested. `true` with an empty availability list means an explicit report snapshot was accepted with no present players; it does not mean everyone is healthy. Source generation timestamps remain separate from the latest successful local fetch time. No live freshness guarantee is made.

`GET /briefings/texans` calls the same builder, then projects explicit response models:

- `entity`, `headline`, `summary`, `reason_shown`, `as_of` describe the saved context.
- `next_game` supplies teams, kickoff, status and season/week identity.
- `availability_report` identifies the selected game's report scope and availability/freshness.
- `availability` supplies player ID/name, practice/game status, injury text and provenance.
- `changes` supplies typed previous/new values and timestamps.
- `source` supplies provider attribution and timestamps.

Raw records, raw responses, provider URLs, local row IDs and credentials are not part of the HTTP contract. M3 does not ingest or display NFL scores/results, so no Texans score-reveal feature is added. Existing Arsenal spoiler behavior remains intact. Missing NFL state returns 404; invalid/unreadable state returns 503. HTTP requests do not create tables or trigger ingestion.

The data flow is `CLI → Sportradar fetch → NFL normalization → atomic SQLite write → NFL briefing builder → CLI or HTTP projection`. `inspect` exposes normalized state, observed changes and latest attempt diagnostics. Logs distinguish provider, normalization and persistence failures. At most two requests occur in a successful ingestion with spacing for the documented 1 QPS trial limit; concurrent CLI invocations share no rate limiter. There is no retry loop or scheduled polling.

## Verification gate

The deterministic suite uses synthetic documentation-shaped fixtures; no test contacts the real provider. Run:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

A separate local smoke check copied the actual Arsenal database into a temporary database, injected synthetic Texans responses at the HTTP transport boundary, reran ingestion, restarted CLI processes and served both entities through actual loopback Uvicorn HTTP requests. The Arsenal briefing was unchanged. This proves local integration, not authenticated NFL provider fidelity.

Authenticated validation remains pending. Before marking M3 complete, capture entitled Texans schedule/report responses and confirm GUIDs, scope identity, `x-generated-date`, player `status_date`, null/empty semantics, practice spelling, status changes and encountered error/quota behavior. Do not commit the credential or raw licensed payloads without a retention/redistribution review. Final test/review evidence is in the local milestone record.

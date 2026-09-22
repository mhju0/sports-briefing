# Milestone 4: Arsenal + Texans ranked home timeline

## What exists

M4 adds a read-only deterministic home-timeline layer over the existing Arsenal and Texans structured data. Sport adapters interpret normalized persisted records into a small shared candidate model; the common layer ranks and selects candidates. It does not read provider payloads, fetch data, or write SQLite.

Retrieve the timeline through either interface:

```sh
python3 -m sports_briefing timeline
python3 -m sports_briefing timeline --as-of 2026-09-23T12:00:00Z
python3 -m sports_briefing timeline --show-results
curl 'http://127.0.0.1:8000/timeline'
```

The API is spoiler-safe by default. `GET /timeline?hide_results=false` explicitly includes a supported recent Arsenal result. `unavailable_entities` distinguishes missing ingestion state from an entity that is available but quiet. Raw provider payloads and provider URLs are not exposed.

Without `--as-of` or an API `as_of`, evaluation uses current UTC. An explicit evaluation time evaluates the **current saved database state** at that instant; it is not historical replay and can include information ingested later. Each sport is read in its own consistent SQLite read transaction. Concurrent ingestion between the two reads could make their freshness times differ, and the response preserves those times rather than claiming one atomic cross-sport snapshot.

## Candidate representation

The shared candidate contains only ranking and presentation facts: stable item identity; entity and sport; item type and state; tier; headline and summary; event/change times; optional competition; source provider, attribution, generation/observation times and underlying record identity; and optional Arsenal result data. The reason is derived from the tier so the two cannot disagree.

Sport meaning remains local:

- Arsenal derives one nearest live match, one nearest fixed-time upcoming match and one latest recent result when eligible.
- Texans derives one nearest live game, one nearest fixed-time upcoming game, one latest recent completed game, and at most one availability-change topic for the nearest live/upcoming game's week.
- The Texans topic processes each player's transitions newest first. A report appearance or removal establishes a lifecycle boundary that suppresses every older membership, practice, game-status and injury transition for that player; fields newer than the boundary remain eligible. Freshness is evaluated only after supersession, so filtered reappearance evidence cannot resurrect an older removal or prior status. It explains the newest eligible transition and counts any additional recent transitions. Repeated unchanged reports create no change row and therefore no fresh change candidate.

Candidates with the same stable identity are deduplicated before selection. Conflicting content with the same identity fails clearly.

## Exact ranking and selection rules

Precedence is categorical:

1. `live` (`reason=live`)
2. `imminent` (`reason=starts_soon`)
3. `meaningful_change` (`reason=meaningful_status_change`)
4. `recent_result` (`reason=recent_result`)
5. `routine` (`reason=upcoming_context`)

Within a tier, nearer event time ranks first for live/upcoming context; newer observation ranks first for changes; and newer scheduled kickoff ranks first for results. Remaining ties use entity ID and then stable candidate ID. There are no hidden weights or competition-specific importance scores.

Eligibility is intentionally bounded:

- Arsenal live: `IN_PLAY` or `PAUSED`, kickoff between 15 minutes ahead and three hours ago, and saved observation no older than 30 minutes.
- Texans live: `inprogress` or `halftime`, kickoff between 15 minutes ahead and six hours ago, and saved observation no older than 30 minutes.
- Imminent: fixed-time `TIMED`/`SCHEDULED` Arsenal match or `scheduled`/`created` Texans game starting within 24 hours.
- Meaningful change: existing NFL change event observed within 48 hours, whose provider generation time and non-null report date are also within 48 hours. Future-dated evidence is excluded.
- Recent result: supported completed status within 36 hours after scheduled kickoff. Kickoff is a conservative proxy because neither current model stores an authoritative completion timestamp.
- Routine context: nearest fixed-time upcoming event within seven days.

Postponed/suspended Arsenal fixtures and delayed, `time-tbd`, or `flex-schedule` NFL games are not treated as live or imminent. Saved live status can lag real play; the observation-age guard reduces false live items but does not turn the schedule endpoint into a live feed.

The global selection keeps at most two items per entity and never forces an entity to appear. A live and a separate recent/upcoming item may coexist if both survive the cap. Full NFL `POST_GAME`/`EARLY_WEEK`/`PRACTICE`/`FINAL_STATUS`/`PRE_GAME`/`LIVE` lifecycle inference remains deferred; M4 uses only supported `LIVE`, `PRE_GAME`, `POST_GAME`, and availability-change meanings.

## Response boundary

Each timeline item exposes:

- `id`, `entity`, `sport`, `type`, `state`, `tier`, and deterministic `reason`
- `title`, `summary`, `event_time`, `change_time`, and optional `competition`
- source `provider`, `attribution`, `generated_at`, `observed_at`, and `record_id`
- optional `result_hidden` or structured `result` for a recent Arsenal result

Missing one sport does not fail the whole timeline; it appears in `unavailable_entities`. Corrupt persisted data produces a controlled API 503 or CLI failure. A malformed API `as_of` is a 422 client error.

## Verification and limits

Offline scenarios cover live dominance in both directions, imminent versus routine in both directions, a new Texans change versus stale context, recent result versus routine, stable ties, duplicate identity, per-entity limits, a quiet/missing entity, nearest-game week scoping, stale/future evidence, unchanged refreshes, spoiler hiding/reveal, CLI output and the HTTP contract. The complete M1–M4 suite remains network-free.

Final local verification passed 78 tests on the original frozen candidate. A separate CLI process and loopback HTTP server read the same temporary mixed SQLite database and returned HTTP 200 with Arsenal imminent, Texans meaningful change, then Texans routine context; repeated CLI output was identical to the HTTP contract except for API omission of null fields. All seven tables in the actual project database retained identical row counts and content hashes across read-only timeline checks. A missing database returned HTTP 200 with both entities unavailable without creating a file; corrupt SQLite returned a controlled 503.

Frozen review found lifecycle-supersession defects: freshness filtering could hide a later reappearance and resurrect an older removal or pre-reappearance status transition. The corrected candidate applies report-membership lifecycle boundaries before field freshness while retaining genuinely newer fields. Exact removal/reappearance and practice-status regressions now pass. The corrected complete suite passes 81 tests.

M3 remains separately open: Sportradar's current Week 3 injury endpoint still returned `teams: []`, so authenticated Texans persistence and live idempotency acceptance are not complete. M4 does not weaken that validation or claim live NFL freshness.

Deferred: Scottie Scheffler/golf, news/reporters, a generic sports-event model, player-importance scoring, full NFL lifecycle inference, universal behavioral personalization, scheduling, notifications, LLMs, production deployment, and SwiftUI timeline work.

# V1 product specification

Status: user-provided product decisions, recorded 2026-09-20. Technical proposals live separately in [decisions.md](decisions.md).

## Purpose and scope

The user follows teams and athletes across countries, sports, time zones, and sources. Current habits span ESPN, FotMob, Naver Sports, X, official sites, and reporters. The product consolidates what matters now, with provenance, rather than reproducing any source's feed.

V1 follows exactly Houston Texans (NFL), Arsenal (all relevant competitions), and Scottie Scheffler (golf). These test different information structures. The primary client is iPhone; English and Korean briefings may derive from sources in either language. Visual design is undecided; define content and behavior before choosing cards or another presentation.

## Home and deep dive

- Home is a continuously refreshed personal timeline, available at any time, not a morning digest or a scoreboard.
- Usually one primary briefing per entity, at most two for genuinely distinct important developments. No minimum: absence is correct when nothing meaningful happened.
- Rank explainably: live event; imminent important event; meaningful new change; recent major event/result; routine context. Apply explicit preferences, freshness, importance and urgency; never simple reverse chronology or hidden ML weights.
- Group by topic, not source: matchup injuries can combine the followed team's starter change with a major opponent availability change. Next-game context and meaningful preparation comments can belong together; results, major stats and postgame comments can form a postgame briefing.
- Each item has a headline, 1–2 sentence summary, relevant event/status, source timestamp, source name/type, and reason such as “Starter status changed”, “Game in 3h”, “New since last check”, or “Official update”. “New since last check” requires a real last-check marker.
- Deep dive provides recent important updates, next event, latest result, relevant injuries/media and limited schedule context. It can say “No meaningful updates”. No full roster browser or large historical statistics product.
- Time is stored unambiguously and presented in the user's time zone; Korea morning can be NFL live time, while football may occur late at night.

## Sport-specific behavior

| Entity | Information needed | Important boundary |
| --- | --- | --- |
| Texans | Recent result and selected major stats; next opponent, venue and time; practice/injury changes; significant opponent availability; meaningful coach/QB and postgame comments; trusted reporter material | Use game-relative phases: POST_GAME, EARLY_WEEK, PRACTICE, FINAL_STATUS, PRE_GAME, LIVE. No weekday hardcoding; handle Thursday/Monday games, byes and rescheduling. These are candidate rules, not a mandated state-machine framework. |
| Arsenal | Live state; next match; recent result; upcoming week; competition identity (EPL, Champions League, domestic cups); injuries and meaningful team/match developments | Preserve competition identity across the club's schedule; live matches normally rank very highly. |
| Scheffler | Previous tournament and his performance; upcoming tournament; useful prior performance at the event/course | Tournament, round and player result are distinct. An event on the tour calendar is not proof he will enter. No forced home item during quiet periods. |

## Changes and relevance

Initial types: RESULT, UPCOMING_EVENT, INJURY_STATUS, LINEUP_OR_STARTER, TEAM_NEWS, MEDIA_OR_QUOTE. Add a sport-specific type such as TOURNAMENT_CONTEXT only when examples require it.

Prioritize new injuries, meaningful practice participation or designation changes, starters and important players. An unchanged report, repeated long-term injury, or low-impact depth-player update usually does not merit home space. Missing data is not recovery. Do not infer a starter or player importance without evidence or an explicit curated designation.

Opponent information must materially affect the followed entity's upcoming event, with an explainable reason. Do not import full opponent injury reports.

A press conference existing is not news. Surface only obtained content containing meaningful new information or a relevant notable quote. Media should have a short faithful summary plus original link; if the content was not obtained, do not claim to summarize it. No viral-quote detection.

## Provenance and generated language

Preserve source identity, original URL, timestamps and type: official team/league/competition, trusted reporter, major publication, or secondary/social source. Separately distinguish OFFICIAL FACT, REPORTED INFORMATION and INTERPRETATION. Source reputation alone cannot convert a report into an official fact.

Scores, times, designations, competitions, venues, game status and leaderboard positions come from structured or verified sources. Bounded LLM tasks may include extraction, topic grouping, deduplication, source-grounded summaries and translation. Generated causes, turning points, dominance or significance require supporting evidence. Conflicting sources remain distinguishable; do not resolve them through confident prose.

Trusted-source ingestion is in scope for investigation. General sports discovery, X For You replication and virality are out of scope. V1 must work without X.

## Preferences and spoilers

Explicit per-entity/category controls may cover injuries, practice, meaningful press comments, trusted reporter updates, scores/results, and roster/team news. Language preference is required in the model; concise versus standard density remains optional. The system owns ordering; users do not assign numeric weights.

Spoiler-free settings work by sport with an entity override. A completed-event item can say “Game finished 2h ago / Score hidden” with intentional reveal and postgame navigation. Live-state handling must also respect the setting. Apply this to headlines, summaries, stats, media previews, accessibility text, ordering explanations and deep dives, not just a score field. An external source may reveal results; make that transition explicit. Opening postgame content must not accidentally reveal it before an intentional action.

V1 uses explicit preferences only. Later: well-defined engagement events (V1.5), then user-approved preference suggestions (V2). Dwell time is ambiguous; never silently reshape the timeline from behavior.

## Deliberate exclusions

No NBA, MLB, KBO, UFC, NCAAF or other added sports. No broad sports search, betting/odds/favorites markets, tickets, fantasy, viral discovery, notifications or notification infrastructure, generic sports chatbot, autonomous agents, multi-agent product architecture, speculative RAG, behavioral ranking, large stats archive, arbitrary weighting editor, or dedicated iPad/Mac/web frontend polish. No copying ESPN, FotMob or Apple Sports visual design. Content stays presentation-independent for later adaptation.

## Quality and learning

Evaluate real examples for important developments surfaced/missed, irrelevant or stale items suppressed, repeated information, source fidelity, reported-versus-official distinctions, and spoiler leaks. Build a small manually reviewed example set before choosing metrics or thresholds.

Later implementation proceeds in bounded steps: trace behavior, explain data flow, propose the smallest change, state failure risks, implement, inspect the diff, test success and relevant failures, and explain what changed. Learning goals include useful LLM calls, Python backend work, Docker, CI/CD, logs/monitoring, external-data debugging, evaluation, Git, deployment and sustained operation. Technology must earn its place through product need.

# Data feasibility

Research date: **2026-09-20**. Sources below are current public primary documentation, not authenticated API results or signed licenses. Prices are listed currencies before any applicable taxes; recheck at purchase. **Documented** means a provider states it; **judgment** means our recommendation; **unverified** means a remaining gate. No keys obtained, paid subscriptions started, publisher contacted, or scraping performed.

Milestone 1 subsequently authorizes only a local football-data.org Arsenal PL/CL pipeline. Its tests use synthetic responses; account coverage, real latency and public distribution rights remain unverified. No other candidate below is integrated. The [local milestone record](../.scratch/milestone-1/spec.md) tracks implementation evidence separately from this research.

## Verdict

The product is technically plausible, but the complete three-sport V1 is **not yet cleared for public release**. Structured schedules/results have realistic APIs. The hardest gaps are affordable permitted golf data, NFL practice-change fidelity, Arsenal's complete competition coverage, and substantive news/quotes that may legally be processed and displayed. The product can exclude X, but official video links alone do not fulfill the meaningful-news requirement.

## Candidate comparison

All listed data providers offer documented APIs: scraping is unnecessary for their offered fields. Unlisted features are not assumed. Commercial providers' advertised coverage is not an observed SLA.

### Texans / NFL

| Candidate | Documented coverage / cadence / history | Access / cost / limits | Suitability and gaps |
| --- | --- | --- | --- |
| API-Sports API-NFL | NFL schedules, results, events, team/player stats and historical seasons; live updates approximately 30 seconds. Current injuries include player/team/date/status/description, but no injury history; check season `coverage.injuries`. | API key (`x-apisports-key`). NFL-specific pricing: free 100/day; Pro **$15/month**, 7,500/day, 300/min; Ultra $25, 75,000/day, 450/min; Mega $35, 150,000/day, 900/min. Free: 10 requests/min. | Low-cost structured-data trial candidate. Not verified to deliver full DNP/limited/full practice semantics or current-season injury coverage. Need authorized snapshots for changes. Publication rights not supplied by the API subscription. |
| SportsDataIO NFL | Schedule, scores/state, stats, roster/depth charts, injuries and news feeds. Workflow distinguishes roster status, game designation and practice reporting; inactives about 90 minutes pregame. Injury start date can mean list placement, not injury onset. | API key via header/query. Live League API is sales-priced. Free trial is **scrambled**, not real-world validation. Discovery Lab has previous-season free data and next-day-delayed personal-use paid access; limits/retention/history depth depend on product. | Stronger fit for practice/availability than API-NFL. Need sample current Texans practice payload, feed entitlement, quote and display/summary license. A paid live product and Discovery Lab are not interchangeable. |
| Sportradar NFL | Weekly injury/depth-chart data, practice participation, primary injury, designation/date, game rosters, schedules, scores and play-by-play. NFL history from 2000; field/feed depth varies. Roster endpoint TTL: 60s pregame, 3s live, 10m after close. | Authenticated B2B API. Current account guide (rechecked for M3, 2026-09-20): 30-day trial, default 1,000 calls per rolling 30 days and 1 QPS; production price and entitlements by contract. Trial quota is unsuitable for sustained live polling. | Selected provisionally for M3 based on documented practice fields; authenticated Texans verification remains pending. Likely heavier production procurement. TTL is cache guidance, not end-to-end latency. Contract must cover display, history, retention and attribution. |

Sources: API-NFL [pricing](https://api-sports.io/sports/nfl), [guide](https://www.api-football.com/news/post/how-to-get-started-with-api-nfl-the-complete-beginners-guide); SportsDataIO [NFL product](https://sportsdata.io/nfl-api), [workflow](https://sportsdata.io/developers/workflow-guide/nfl), [access products](https://sportsdata.io/developers), [licensing FAQ](https://sportsdata.io/help/data-rights-and-licensing-questions); Sportradar [overview](https://developer.sportradar.com/football/reference/nfl-overview), [injuries](https://developer.sportradar.com/football/docs/nfl-ig-rosters), [roster timing](https://developer.sportradar.com/football/reference/nfl-game-roster), [history](https://developer.sportradar.com/football/docs/nfl-ig-historical-data), [access FAQ](https://developer.sportradar.com/golf/v2/docs/faqs).

### Arsenal / football

| Candidate | Documented coverage / cadence / history | Access / cost / limits | Suitability and gaps |
| --- | --- | --- | --- |
| football-data.org v4 | PL and Champions League among 12 free competitions; fixtures/results, UTC time, status, competition/season and standings. Season-filtered history, depth by subscription. Lineups/substitutions/cards require deeper access. No injuries/news API established. | `X-Auth-Token`. Free: delayed scores/schedules, 10 calls/min. Live basic: **€12/month**, 20/min. Deep Data: **€29/month**, 30/min. Standard: €49, 60/min. Higher plans available. Free delay and paid end-to-end live latency are not quantified in reviewed pricing. | Good first fixture/result slice, not complete V1. FA Cup/League Cup appear in broader catalogue but exact paid tier must be confirmed. Registration terms require visible credit: “Football data provided by the Football-Data.org API”. Cancellation affects continued data display under registration terms. |
| API-Football | Fixtures/results, live events, lineups, injuries, player/team statistics, historical seasons across 1,200+ leagues/cups; advertised live update interval 15s. Coverage flags vary by league/season. | API key. Free 100/day; Pro **$19/month**, 7,500/day; Ultra $29, 75,000/day; Mega $39, 150,000/day. Confirm per-minute entitlement in dashboard. | Broader candidate if one football feed must cover injuries and domestic cups. Actual Arsenal competition/season flags and lineup/injury completeness untested. Publication rights remain separate. |
| Sportradar Soccer | Schedules, live summaries/timelines, lineups, missing players (injury/suspension, missing/doubtful, start time), statistics; tiered competition coverage. Live schedule TTL 1s; lineups commonly around 1h pre-kickoff and can change afterward. | Authenticated B2B API; trial/production access differ; sales pricing and production limits. Trial allowance as above; exact history/tier required for each competition. | Rich fit, likely too much procurement for first slice. PL/CL documented; verify current FA Cup/League Cup and missing-player coverage. One-second TTL is not proof of one-second source updates. |

Sources: football-data.org [pricing](https://www.football-data.org/pricing), [coverage](https://www.football-data.org/coverage), [match model](https://docs.football-data.org/general/v4/match.html), [policies](https://docs.football-data.org/general/v4/policies.html), [FAQ](https://www.football-data.org/documentation/faq), [registration terms](https://www.football-data.org/client/register); API-Football [coverage/product](https://www.api-football.com/), [pricing](https://www.api-football.com/pricing); Sportradar [overview](https://developer.sportradar.com/soccer/reference/soccer-overview), [coverage basics](https://developer.sportradar.com/soccer/docs/soccer-ig-api-basics), [live schedules](https://developer.sportradar.com/soccer/reference/soccer-live-schedules), [missing players](https://developer.sportradar.com/soccer/reference/soccer-season-missing-players).

### Scheffler / golf

| Candidate | Documented coverage / cadence / history | Access / cost / limits | Suitability and gaps |
| --- | --- | --- | --- |
| Data Golf | Tour schedules, fields/tee times, player IDs, finishes, live stats/model endpoints (models about every 5m), historical round data across tours. Model cadence is not a universal score-latency guarantee. | Key in query string; **Scratch Plus $30/month or $270/year**; annual subscription required for historical archive endpoints. 45 requests/min globally; exceeding causes a 5-minute suspension. No free API entitlement established. | Useful private research candidate. Public terms limit personal noncommercial use and prohibit redistribution/transfer. Do not use as app distribution source without separate permission. Redact keys from URL logs. |
| SportsDataIO Golf | PGA Tour **stroke-play** schedules, tournaments/courses, tee times, live hole-by-hole leaderboards, results, withdrawals, cuts and ranking/player data. Updates within minutes of TV broadcasts; final data about 5–10m after conclusion. Historical depth by product. | API key; free scrambled trial, Discovery Lab personal/delayed options, commercial live quote. Exact rate/caching/attribution/retention contract needed. | Candidate for Scheffler result/entry/context if budget allows. No assumption that match-play/team formats are covered. Need confirmed field-entry semantics and prior-event/course results. |
| Sportradar Golf | PGA Tour and Majors, schedules, fields/tee times, live/final leaderboards, scorecards, player history, rounds/course and statistics; PGA history from 2013. REST and push feeds; daily change log supports corrections. | Authenticated API; trial limits above, production quote and entitlements. No public fixed production price or end-to-end latency guarantee established. | Strong technical shortlist for cross-event player history. Verify exact Scheffler field/withdrawal and course-history payloads, retention, display rights and price. |

Sources: Data Golf [API](https://datagolf.com/api-access), [pricing](https://datagolf.com/subscribe), [terms](https://datagolf.com/terms-and-conditions); SportsDataIO [workflow](https://sportsdata.io/developers/workflow-guide/golf), [dictionary](https://sportsdata.io/developers/data-dictionary/golf), [licensing](https://sportsdata.io/help/data-rights-and-licensing-questions); Sportradar [overview](https://developer.sportradar.com/golf/reference/golf-overview), [history](https://developer.sportradar.com/golf/docs/golf-ig-historical-data), [player details](https://developer.sportradar.com/golf/docs/golf-ig-retrieving-player-details-statistics), [change log](https://developer.sportradar.com/golf/docs/golf-ig-monitoring-data-changes).

## Rights, attribution and operational limits

API-Sports explicitly disclaims supplying a use/publication license for data, forbids resale and leaves rights-holder permissions to the customer; complaints can lead to suspension. It also disclaims guaranteed coverage/update timing. This is a publication-rights gap, not a blanket claim that all private experiments are banned. [Terms](https://www.api-football.com/terms).

SportsDataIO Discovery Lab is a personal/noncommercial product; live redistribution needs the applicable agreement. Sportradar's public technical docs do not establish this app's permitted redistribution. For either, obtain written scope for single-user/private, TestFlight, public app, retention, screenshots, generated translations/summaries and source credit. Logos, photos and media may have separate rights even when score data is licensed. [SportsDataIO licensing](https://sportsdata.io/help/data-rights-and-licensing-questions).

Every candidate needs bounded requests, timeout/backoff, quota telemetry and last-known-good data. football-data.org documents 429 quota responses; Data Golf documents temporary suspension; Sportradar documents access/quota failures including 403. API-Sports responses also need payload-level error checks, not just HTTP success. Exact production failure/SLA behavior remains untested. Never label stale scores live, silently switch authority, or infer “no injury” from a missing/failed response. Full request budgets must include pagination, metadata, retries and injury feeds, not just live scores.

Illustrative budget: polling one endpoint every minute for a four-hour game uses 240 calls before retries or other endpoints. A 100/day free quota cannot support that. This arithmetic is a planning example, not a provider latency promise. No defensible full monthly V1 price exists until NFL/golf rights and access are quoted.

## X / trusted reporters

**Technical access is feasible.** [User Posts](https://docs.x.com/x-api/users/get-posts) supports `GET /2/users/{id}/tweets`, bearer/app-only or user-context auth, `since_id`, pagination and exclusions. [Timeline docs](https://docs.x.com/x-api/posts/timelines/introduction) describe up to 3,200 recent posts (800 when replies excluded). An approved developer account/app and credits are required; private posts require appropriate authorization. Recent search is limited to seven days. These are API limits, not durable archive rights.

[Filtered stream](https://docs.x.com/x-api/posts/filtered-stream/introduction) supports named-account rules, 1,000 rules/project and one pay-per-use connection, advertising roughly 4–5s P99 delivery. Polling adds the chosen interval to upstream delay. Endpoint-specific request limits must be confirmed through current console/response headers; the reviewed [rate-limit page](https://docs.x.com/fundamentals/rate-limits) does not establish a numeric user-timeline quota for this account. Reconnect/gap recovery and 429 handling are necessary.

**Pricing is currently pay-per-use**, not the old fixed Basic/Pro price ladder: $0.005/Post read, $0.010/User read, $0.005/List read; 3 million Post reads/month pay-per-use cap. Same-resource reads are normally deduplicated within a UTC day, described as a soft guarantee. Ten new posts/day × 30 days × $0.005 = **$1.50/month in Post reads alone**; 100/day gives $15. User reads, re-reads on later days and other products add cost. Small monitors need not be expensive. [Current pricing](https://docs.x.com/x-api/getting-started/pricing). Policy text still mentions legacy plans; confirm account entitlements rather than resolving inconsistent terminology by assumption.

**Storage/display:** cached content must follow edits/deletions; display must use the current version, with removal as soon as reasonably possible and within 24h of a removal request. Public display and bulk/API redistribution are different uses: redistribution generally permits IDs, with limited exceptions. Storing IDs and links minimizes copied content, but IDs/metadata are still governed content, not a blanket exemption. [Developer Policy](https://docs.x.com/developer-terms/policy).

**Summarization is not cleared.** The agreement includes derivative works in X Content, limits modification to display formatting, restricts derivative redistribution, and explicitly prohibits foundation/frontier model training or fine-tuning. That training rule is not identical to inference, but it also does not grant permission for external LLM summarization, translation or retained summaries. Get the proposed processing/display use approved before implementing it. [Developer Agreement, sections I–III](https://docs.x.com/developer-terms/agreement). Judgment: exclude X from initial V1 integration; do not replace it with scraping.

### Cleaner alternatives and their actual limits

| Source route | Verified possibility | Limitation / decision |
| --- | --- | --- |
| Official team/league pages | Original links can identify a source for a user to open | No documented Texans/Arsenal public news API or permitted RSS contract verified. Arsenal terms restrict reuse and automated access. A public press release is not automatically licensed ingestion. |
| Official YouTube channels via Data API | `channels.list` → uploads playlist → `playlistItems.list`; ordinary list reads usually 1 quota unit, default allocation 10,000/day; API key for public metadata | Useful metadata/link/embed route, not a transcript source. Refresh/delete nonauthorized API data within policy limits (generally 30 days); do not download/store audiovisual copies without permission. |
| YouTube captions | Documented `captions.download` API | Requires OAuth and permission to edit the video, costs 200 units; arbitrary public captions are not downloadable through this route. A video title cannot support a substantive interview summary. |
| Licensed provider news / publisher RSS | SportsDataIO advertises NFL news; a publisher may license feeds | Specific text/translation/LLM rights, freshness, reporter coverage and cost are unverified. Verify an actual feed and its terms before activation. RSS is a format, not permission. |
| Manual source curation | A small original fact note plus source link can support a private, explicitly labeled experiment | Not an automated V1 solution; copying source text/media remains subject to rights. Use only authorized evidence for model processing. |

Sources: [Arsenal terms](https://www.arsenal.com/terms-and-conditions-of-use), [Texans official site](https://www.houstontexans.com/), [YouTube access/quota](https://developers.google.com/youtube/v3/getting-started), [uploads workflow](https://developers.google.com/youtube/v3/guides/implementation/videos), [YouTube policies](https://developers.google.com/youtube/terms/developer-policies), [caption authorization](https://developers.google.com/youtube/v3/docs/captions/download).

No stable official PGA/public reporter RSS contract was verified either. ESPN, FotMob, Naver and undocumented site endpoints are not recommended data integrations. News APIs are not a presumed workaround for underlying publisher rights.

## Recommended source strategy and remaining gate

1. **First private slice:** football-data.org fixtures/results for PL/CL, subject to terms/access confirmation. Free delayed data is acceptable only if explicitly approved for the milestone; use a paid live tier for later live validation. Domestic cups and injuries stay explicit gaps, not silently omitted V1 requirements.
2. **Texans validation:** evaluate API-NFL for schedules/results at low cost, but demand a real practice/designation-change example. If unavailable, compare SportsDataIO/Sportradar access; do not pretend generic injury text meets practice semantics.
3. **Golf validation:** seek suitable SportsDataIO/Sportradar terms and price; Data Golf only for permitted private research unless separate rights are granted. Verify Scheffler's entry, previous finish and prior event/course history, including missed-cut/withdrawal states.
4. **Trusted content:** start with authorized facts and original links. Choose one permitted substantive text feed before claiming meaningful news/quotes are automated. YouTube metadata alone should not produce “coach spoke” home filler.
5. **Release gate:** confirm provider-specific rights, authenticated current coverage, cost ceiling, actual freshness and graceful failures for all three entities. If no affordable permitted golf/news route exists, return a product/budget trade-off for approval; do not silently narrow V1 or substitute scraping.

For each selected provider, collect a small permitted response sample (normal + missing/delayed/corrected), external IDs, coverage flags, source time, quota headers, storage/display/LLM terms and a full daily request estimate. No SLA or real operational reliability was tested in this session. Technical architecture is proposed in [decisions.md](decisions.md).

## M3 NFL research update

The [M3 provider record](milestone-3.md) supersedes the earlier NFL shortlist where they differ. API-NFL still lacks documented practice-participation fidelity. SportsDataIO’s current OpenAPI marks Practice/PracticeDescription deprecated. Sportradar v7 documents explicit practice/designation fields and upstream generation headers; that is the sole provisional M3 adapter, not proof of live access or licensed publication. The [current account guide](https://developer.sportradar.com/getting-started/docs/your-account) states a 30-day trial, correcting the initial 90-day note.

## Public deployment rights (checked 2026-09-27)

This section is the canonical public-deployment rights view. It supersedes earlier rows here where they differ. It records current public terms, not signed licences or provider replies. Nothing has been deployed, purchased or sent to a provider.

**football-data.org** ([registration terms](https://www.football-data.org/client/register), last updated 2018-06-01; [FAQ](https://www.football-data.org/documentation/faq)):
- **Public display: UNRESOLVED.** The terms bind one key to "a single Application, in its web and/or mobile form" and require credit "in your app or website". After cancellation the customer may not "reference the football data … on their own site or service". Display is therefore implied, but no licence to publish is expressly granted.
- **Commercial use:** the terms are silent. They draw no distinction between personal, non-commercial and commercial use.
- **Caching:** the terms are silent.
- **External LLM processing: UNRESOLVED — provider confirmation required.**
- **Attribution:** the exact text "Football data provided by the Football-Data.org API", placed "in a visible section of your app/website" (for example the footer or an about screen).

**Sportradar NFL and Golf** ([Terms and Conditions](https://developer.sportradar.com/sportradar-updates/page/terms-and-conditions), last updated 2026-08-05):
- **Trial scope:** "solely for purposes of internally evaluating the Products" (§3.1); "internal testing and evaluation purposes only" (§1.14). Public display of trial data is **BLOCKED**.
- **Destruction obligation (§7.4):** "Upon termination or expiration of this Agreement for any reason", the customer must cease use. "Within thirty (30) days of the effective date of termination", it must "commence and thereafter diligently pursue the destruction and sanitization" of all data made available, "together with any derivatives, copies, extracts, or compilations thereof". A Certificate of Destruction is due "no later than ninety (90) days following the effective date of termination".
- **Unresolved:**
  - whether trial expiry is the Agreement's "expiration" (the Effective Date is defined by an Order Form, which a trial lacks);
  - whether hashes and provenance metadata count as derivatives;
  - whether trial users must file the certificate.
- **Local evidence:**
  - The first recorded authenticated call was 2026-09-22T12:29:45Z (`nfl_fetches` id 1, deleted on 2026-09-27). No trial start or expiry date is recorded in the repository.
  - Remediation (2026-09-27): the fixtures derived from authenticated responses (`tests/fixtures/golf/*`, `tests/fixtures/texans_schedule_live_shape.json`) were replaced with independently authored synthetic payloads; captured values were removed from the M3/M5 records; all NFL/Golf rows were deleted from the local database (then `VACUUM`, no backup kept); repo-related captures under `/private/tmp` were deleted.
  - History remediation (2026-09-27, before any remote existed): `git filter-repo` removed the derived fixture versions and the historical M5 test versions from earlier commits, and redacted captured values in historical M3/M5 records and one M3 test version. Reflogs were expired and unreachable objects pruned. Scans of all reachable history found no remaining captured payloads or extracts.
  - Still present: Scottie's and the Texans' provider UUIDs, kept as configuration identifiers.
  - The current repository and reachable history are sanitized. The trial dates, the certificate of destruction, and whether hashes/provenance count as derivatives remain external administrative questions. No certificate of destruction has been issued. Publication still depends on the other rights items in this section.

**Texans replacement candidates:**
- **[nflverse](https://github.com/nflverse/nflverse-data):**
  - The `nflverse-data` releases carry a CC-BY-4.0 repository licence, but its README describes the data as scraped. The schedule source [`nfldata`](https://github.com/nflverse/nfldata) has no licence file, and its dataset notes cite Pro Football Reference, ESPN and NFL identifiers.
  - `load_injuries` is "collected from an API" that is not named ([nflreadr reference](https://cran.r-project.org/web/packages/nflreadr/refman/nflreadr.html)).
  - Classification:
    - schedules/scores **UNRESOLVED** (updated every 5 minutes in season);
    - rosters **UNRESOLVED** (daily);
    - injuries **NOT SUITABLE** (unnamed upstream, daily 07:00 UTC cadence) ([update schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)).
- **[BALLDONTLIE](https://www.balldontlie.io/terms.html)** (terms updated 2026-09-17):
  - The terms allow users to "publish, display, distribute … and create derivative works". They list AI/ML use as permitted and require no attribution.
  - They also state users are "solely responsible for determining and obtaining any third-party rights".
  - NFL tiers ([docs](https://nfl.balldontlie.io/)): games are free; injuries cost $9.99/month; practice designations cost $39.99/month.
  - Classification: **LIKELY** at the provider level. League rights remain disclaimed.

**Scottie:**
- [Data Golf](https://datagolf.com/terms-and-conditions) allows "personal, non-commercial use" and no redistribution, so it is **BLOCKED** for public use.
- [TheSportsDB](https://www.thesportsdb.com/pricing) has no tee times.
- [BALLDONTLIE PGA](https://pga.balldontlie.io/) puts results at $9.99/month, but field and tee times need the $39.99/month tier, which alone exceeds the $10–25/month deployment budget.
- **Decision: Scottie remains fixture/demo-only until a suitable licensed source exists.**

**Wikinews:** the pinned 2016 pages are CC BY 2.5, which requires attribution and has no share-alike term ([copyright](https://en.wikinews.org/wiki/Wikinews:Copyright)). Wikinews has been read-only since 2026-05-04 ([closure](https://en.wikinews.org/wiki/Wikinews:Closure_of_Wikinews)).

| Entity / source | Local engineering use | Public live use | Public demo / fixture use | External LLM use | Status |
| --- | --- | --- | --- | --- | --- |
| Arsenal · football-data.org free | ALLOWED | UNRESOLVED (display implied, not granted) | ALLOWED with synthetic fixtures | UNRESOLVED | UNRESOLVED — provider confirmation |
| Texans · Sportradar NFL trial | ALLOWED until trial end, then §7.4 | BLOCKED | BLOCKED for Sportradar-derived fixtures | BLOCKED | BLOCKED |
| Scottie · Sportradar Golf trial | ALLOWED until trial end, then §7.4 | BLOCKED | BLOCKED for Sportradar-derived fixtures | BLOCKED | BLOCKED |
| Texans · synthetic fixtures | ALLOWED | — | ALLOWED, labelled | ALLOWED | DEMO ONLY |
| Scottie · synthetic fixtures | ALLOWED | — | ALLOWED, labelled | ALLOWED | DEMO ONLY |
| Texans · BALLDONTLIE (not integrated) | Not integrated | LIKELY (league rights disclaimed) | — | LIKELY (terms permit AI use) | Candidate only |
| Texans · nflverse (not integrated) | Not integrated | UNRESOLVED | — | UNRESOLVED | Not selected |
| Wikinews archive (CC BY 2.5) | ALLOWED | ALLOWED with attribution (archival, not current news) | ALLOWED | ALLOWED with attribution | ALLOWED |
| Reviewed Texans news | Operator-reviewed only | BLOCKED (site terms) | BLOCKED | BLOCKED | BLOCKED |

Public demo fixtures must be synthetic. Sanitized fixtures derived from Sportradar responses are provider-derived data and must not be published; the tracked fixtures are synthetic, and derived versions were removed from Git history on 2026-09-27.

### Proposed public deployment target (not approved or deployed)

- **Host:** one always-on Hetzner CX23 in an EU location, running FastAPI/Uvicorn behind Caddy (automatic HTTPS) as a systemd service.
- **Ingestion:** systemd timers call the existing ingestion CLI, so no new application scheduler is needed.
- **Storage:** SQLite on the local disk. Postgres is not needed for one writer on one host.
- **Backups:**
  - a nightly online `sqlite3 .backup` to dated files on the host, keeping 14;
  - Hetzner server backups;
  - a periodic off-host copy.
- **Restore:**
  1. Stop the service.
  2. Copy a dated backup into place.
  3. Run `PRAGMA integrity_check`.
  4. Start the service.
  5. Verify `/health` and `/timeline`.

  Rehearse this once before launch.
- **Operator responsibilities:** OS security updates, SSH and firewall hygiene, certificate renewal checks, timer failure alerts, quota and 429 handling, and the §7.4 obligations above.
- **Cost (Hetzner USD list prices before VAT):**
  - Fixed: server $6.49, primary IPv4 about $0.60, backups about $1.30 (20% of the server price), for about **$8.40/month**.
  - Optional: a domain at about $1/month.
  - Variable: LLM $0 while templates are used.
  - Monitoring: a free uptime checker.
- **Render** Starter with a disk (about $7.25/month) is the alternative if owner OS maintenance is unwanted. It needs an in-process scheduler because a Render disk attaches to a single service.

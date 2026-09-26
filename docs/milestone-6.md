# Milestone 6: provenance-first developments

M6's first slice proves that several publications can support one Texans roster development while the timeline changes only when a reviewed normalized fact changes. It does not fetch official articles automatically. The current proof is deliberately narrow: Houston Texans, `placed_on_ir`, an explicit stable player key, an effective date, and the optional exact placement qualifier `designated_for_return`. The qualifier means **Reserve/Injured (Designated for Return) at placement**, not a later return-to-practice window. Omission means unknown, not false. No LLM extracts facts, merges topics, or ranks items.

## Source evidence and permission boundary

On September 26, 2026, the official Texans [news](https://www.houstontexans.com/news/) and [transactions](https://www.houstontexans.com/team/transactions/2026) surfaces returned HTTP 200. The [September 16 article](https://www.houstontexans.com/news/houston-texans-transactions-9-16-2026) supplied canonical URL and JSON-LD article ID, author (`Houston Texans Public Relations`), and a precise `datePublished` timestamp. Its JSON-LD `articleBody` contained headings but omitted player transactions held in HTML tables. A September 17 press-room article and the monthly transactions page both represented the Bryce Oliver practice-squad signing and Mark Gronowski release. This proves that two official representations can discuss one development, but the monthly page contains multiple transactions and cannot safely be treated as a one-topic document under this P1 schema.

The Texans [site terms](https://www.houstontexans.com/news/houston-texans-website-terms-conditions) currently prohibit systematic retrieval and database storage without prior written consent. `robots.txt` permits `/news` discovery but does not grant database/redistribution rights. Consequently there is no crawler, HTTP source adapter, automatic article extraction, live official import, or claim of publication rights. Metadata shapes above were observed manually; **all imported facts in the tests are synthetic**. The reviewed import requires a source-use authorization attestation supplied by the operator. That attestation is an input boundary, not proof of legal permission. `reviewed` means a person supplied/checked the normalized facts; it does not mean the application independently verified them. An authorized ingestion path and actual source-derived acceptance remain open.

## Run the offline proof

Use a separate test database. Synthetic evidence cannot target the CLI's default database. The CLI accepts a bounded local JSON file and never makes a network request:

```sh
python3 -m sports_briefing import-news texans \
  --input tests/fixtures/news/synthetic-placement.json --db /tmp/sports-briefing-m6.sqlite3
python3 -m sports_briefing inspect texans-news --db /tmp/sports-briefing-m6.sqlite3
python3 -m sports_briefing timeline --db /tmp/sports-briefing-m6.sqlite3
python3 -m sports_briefing import-news texans \
  --input tests/fixtures/news/synthetic-placement.json --db /tmp/sports-briefing-m6.sqlite3
python3 -m unittest tests.test_milestone_six -v
python3 -m unittest discover -s tests -q
```

`GET /timeline` reads the same SQLite-backed candidates. A fixed `--as-of` evaluates current stored state, not historical replay. The dated synthetic fixture may yield zero items when run after its 48-hour eligibility period; the tests use a fixed import clock to demonstrate its eligible window. JSON accepts 1–20 documents and a maximum 512 KiB file. Each document supplies an HTTPS canonical URL (without query/fragment), optional external ID/author/publication timestamp, title, short text used only for a content hash, explicit player key/name, action, effective date, and optional placement qualifier. Synthetic URLs must use `example.test`. Reviewed URLs must be canonical `www.houstontexans.com/news/<slug>` articles; they require `source_use_authorized: true`. The text is not stored as article body. Publication time may be absent for provenance, but then the topic cannot enter home through that material revision. Manually curated subject keys are separate from Sportradar NFL player IDs; no implicit identity sync occurs.

## State and clocks

`news_sources` identifies the fixed official/synthetic source and evidence mode. `news_documents` stores one immutable canonical URL record with source, title, author, external ID, publication time, immutable first observation, normalized-content hash, optional exact-duplicate pointer, and reviewed normalized transaction fields. `news_topics` stores the one `texans + placed_on_ir + subject_key + effective_date` development, current qualifier, revision, first observation, last new-evidence observation, and latest material contributor. `news_topic_documents` links every publication to its topic and records whether it supplied the placement or a new qualifier. A document maps to one topic in this proof. A changed body/metadata/fact at an existing URL is rejected atomically rather than silently replacing evidence; in-place source updates remain a later design question.

`published_at` is the publisher clock; `first_observed_at` is the first successful Sports Briefing import of the document; `meaningful_changed_at` is when the application accepted a new normalized fact. These are distinct. A first placement creates revision 1. A second URL restating it adds evidence without a revision or fresh timeline time. A later document adding the previously unknown exact placement qualifier creates revision 2 once. Identical URL/refetch does not change any stored row. Documents in a batch are processed by publication time then URL, so input list order cannot change the first contributor. A publication after its stated observation or an out-of-order observation fails atomically. An older article imported today cannot qualify for home solely from the recent import.

The source document that last changed the topic remains linked by `material_document_id`. A new repeating publication cannot advance `material_published_at`. Exact normalized text under different URLs is marked as a duplicate; identical text that asserts conflicting normalized facts fails. Text hashing detects exact normalized repeats only; there is no fuzzy similarity or generalized claims graph. The reviewed JSON remains the human-checked fact boundary; it is not an automatic extractor.

## Sparse timeline and structured boundary

One qualifying topic maps to the existing `MEANINGFUL_CHANGE` tier through a news-specific adapter. It needs both `meaningful_changed_at` and its material contributor's `published_at` within 48 hours of evaluation, plus an effective date from today back through seven days. The date is an eligibility guard, not an invented event timestamp. At most the latest one Texans news topic is offered to the shared ranker, then the existing two-items-per-entity cap applies across structured and news candidates. No new rank tier or weight was added. A quiet news table offers zero candidates. The timeline's source metadata identifies the material publication URL, publisher timestamp, and first Sports Briefing observation. Synthetic output is visibly labeled as synthetic.

News persistence uses four `news_*` tables and never writes NFL game, practice, injury, or revision tables. A reviewed report cannot overwrite a Sportradar designation. P1 has no result payload, notification, source-trust scoring, generic article feed, or spoiler-revealing text. Broader news, other V1 entities, automated rights-cleared discovery, in-place publication changes, and LLM synthesis remain outside this slice.

## Acceptance state

Eighteen focused M6 tests and 136 complete offline tests pass. They cover exact reruns, two URLs/one topic, exact-content duplicates, old publication, repeat without novel information, one synthetic qualifier follow-up, atomic conflict rejection, source identity, separate-process readback, CLI/API candidate output, sparse selection, existing ranking precedence, and unchanged structured NFL tables. The synthetic follow-up proves persistence semantics only; it is not evidence that an actual official source published that sequence. M6-P1 remains an **offline implementation proof with live-source rights and real-source acceptance open**. M3 and M5 acceptance gates are unaffected.

In a separate local smoke check, the proof was run against a **copy** of the existing SQLite database. Two synthetic documents produced one topic and two evidence links at revision 1; an identical import left every news row unchanged. A third synthetic clarification produced the same topic at revision 2 with three evidence links; another identical import again left all rows unchanged. Every row in the 12 preexisting structured tables stayed byte-equivalent. Separate-process CLI output was stable, and loopback HTTP returned one synthetically labeled item with no result payload in either spoiler mode. These are offline product tests, not authenticated official news ingestion.

Independent persistence review found and corrected fractional-second string ordering and inconsistent multi-table inspection during concurrent writes. Chronology now uses parsed timestamps; inspection uses a SQLite read snapshot. Regression tests include an interleaved WAL writer, fractional timestamps, malformed evidence mode, and database filenames containing URI-special characters. No generic framework was added.


## P2 source investigation (2026-09-26)

Baseline: `main` at `8b90305e4c1fb2c2a4baaa7079b33418ca19bfaf`, clean; 136 offline tests rerun successfully. This section records a separate permitted-source proof, not retroactive live acceptance of the synthetic P1 scenarios.

| Candidate | Observed | Documented access/storage | Decision |
| --- | --- | --- | --- |
| Sportradar AP NFL Editorial v3 | Existing key: `GET /content-nfl-t3/ap/news/2026/09/25/all.json` returned 403 HTML Authentication Error at 12:21:36 UTC. Same-key NFL v7 schedule control returned 200. No editorial JSON obtained. | Separate Editorial product with daily news manifests, IDs, original publication and entity references. Trial restrictions and contracted product/property scope require checking intended retention/display rights. | Not currently accessible; 403 alone does not identify the account cause. Sports-data entitlement is not Editorial entitlement. |
| SportsDataIO NFL/Golf RotoBaller News | No configured credential; no authenticated payload obtained. | Documented team/date news routes, NewsID, publication/source/URL fields. Trial is scrambled; real feed provisioning and licensed storage scope must be confirmed. | Credible next current-source access candidate, not approved or integrated. |
| Guardian Open Platform | Official access/legal pages available; no configured API key and no authenticated article request. | Developer access: noncommercial, 1 request/second, 500/day. Default terms restrict aggregation and require 24-hour replacement/deletion. | Default developer access does not establish permission for this retained topic-analysis proof. |
| Wikinews MediaWiki API | Three bounded discovery/content requests returned JSON. Two Arsenal articles contained stable page/revision IDs, canonical URLs, date templates, publication/archive markers and text. | Article text from 2005–2024 is CC BY 2.5, with Wikinews attribution. Copying/adaptation permitted subject to license. Images and external linked articles have separate rights. | Select one reviewed Arsenal signing article for a bounded archival proof. Archive age is not a permission failure; it must remain quiet on home. |

Primary access references: [Sportradar Editorial News](https://developer.sportradar.com/images-and-editorials/reference/editorial-news), [Editorial overview](https://developer.sportradar.com/images-and-editorials/reference/editorial-overview), [Sportradar terms](https://developer.sportradar.com/sportradar-updates/page/master-terms-and-conditions-for-non-betting-services), [SportsDataIO NFL API](https://sportsdata.io/developers/api-documentation/nfl), [NFL dictionary](https://sportsdata.io/developers/data-dictionary/nfl), [SportsDataIO licensing](https://sportsdata.io/help/data-rights-and-licensing-questions), [trial limitations](https://sportsdata.io/developers), [Guardian access](https://open-platform.theguardian.com/access/), [Guardian terms](https://www.theguardian.com/open-platform/terms-and-conditions), [Wikinews copyright policy](https://en.wikinews.org/wiki/Wikinews:Copyright), [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/), [MediaWiki API etiquette](https://www.mediawiki.org/wiki/API:Etiquette).

No account/product was activated, purchased or changed. No sales/support message was sent. Sportradar's control request was read-only and does not close M3. No Golf request or M5 acceptance work occurred.

## P2 selected evidence and precision

Selected publication: [Arsenal signs Mönchengladbach captain Granit Xhaka](https://en.wikinews.org/wiki/Arsenal_signs_M%C3%B6nchengladbach_captain_Granit_Xhaka), Wikinews page `2790899`, observed revision `5024729`. Its article date is **2016-05-25**; its revision timestamp is **2026-05-04T03:20:02Z**. Those are different facts. The announcement date is not the contract commencement date (July 1). The other observed article, page `2802062`, concerned Bellerín's separate contract extension and was not selected for ingestion. Neither linked Arsenal nor Borussia source pages count as fetched evidence.

The source is community reporting, not Arsenal's official statement surface. Text attribution is **Wikinews**, under **CC BY 2.5**. The proof uses explicit reviewed normalization bound to the actual fetched article identity and content; it is not automatic arbitrary-article extraction. Only the allowlisted article is fetched; no broad search, pagination, images or linked-source retrieval occurs in the adapter. Unexpected source changes must fail before persistence rather than silently reuse stale reviewed facts.

Wikinews is archived/read-only following its [May 2026 closure](https://en.wikinews.org/wiki/Wikinews:Closure_of_Wikinews). It is a legitimate real retrieval/storage proof, not an ongoing timely sports-news service. A date-only publication is retained as a date with `published_at` absent. Revision time is provenance only. No midnight timestamp, backdated observation or artificial home freshness is created.

## P2 acceptance boundary

One live publication can prove retrieval, provenance, persistence and identical-refetch behavior. It cannot prove two real publications describe the same development. Existing repeat/follow-up scenarios remain clearly synthetic. M6 cannot be closed on this single-document archival proof alone: the minimum remaining acceptance is a permitted real same-development pair, with timestamp precision sufficient to exercise qualifying candidate behavior honestly. This may use a separately authorized current vendor feed; it does not require a broad news platform. M3/M5 gates remain unchanged and M7 is not started.


## P2 adapter behavior (extended by the P3 pair below)

```sh
python3 -m sports_briefing ingest-news wikinews-arsenal --db /tmp/sports-briefing-wikinews.sqlite3
python3 -m sports_briefing inspect news --db /tmp/sports-briefing-wikinews.sqlite3
python3 -m sports_briefing ingest-news wikinews-arsenal --db /tmp/sports-briefing-wikinews.sqlite3
python3 -m sports_briefing timeline --db /tmp/sports-briefing-wikinews.sqlite3
```

The public API needs no credential. Each explicit ingestion performs one bounded request for page `2790899`; no background polling or continuation is used. The adapter accepts the reviewed revision `5024729` and exact main-slot content hash. New revisions/content require a new explicit review, not silent fact reuse. Provider errors, malformed responses and mismatches stop before persistence. `inspect news` is an alias for the existing news inspection surface; `inspect texans-news` and offline imports continue to work.

The schema remains four news tables. Two nullable document columns retain date-only publication and source metadata. The topic constraint admits exactly Texans IR placements and Arsenal signing announcements; no universal event ontology was added. The migration preserves existing topic/document IDs and evidence links. Source metadata retains article/revision identity, edit time, reviewed hash, license, attribution and normalization notice. Article text is used for binding/hash verification and is not retained in SQLite. The attributed captured fixture does retain the selected source text needed for regression verification.

`synthetic` remains useful import-origin metadata and a safety boundary: it is visibly labeled and cannot target the CLI default database. Reviewed factual normalization remains distinct from source authority or permission. The real adapter's source identifies Wikinews community reporting; it cannot masquerade as the official Texans import. No generic source registry or claims model was added. The shared ranker and its caps remain unchanged; the archived date-only article is ineligible under the existing precise-publication freshness guard.


## P2 verification snapshot

On 2026-09-26, the implemented command fetched the selected public API page twice successfully (HTTP 200 required by the adapter). First accepted observation: `2026-09-26T12:34:36.429720Z`. The first run inserted **1 source, 1 document, 1 topic at revision 1, 1 evidence link**. The second run reported one unchanged document, zero inserts/updates/links; a separate-process inspection compared **every news row equal**, including first observation, meaningful-change time and revision. This is real network retrieval of historical content, not a current-news publication or multi-document example.

Persisted publication: `published_at=NULL`, `published_date=2016-05-25`; source revision: `2026-05-04T03:20:02Z`. Accepted topic identity: `arsenal:signing_announced:player:granit-xhaka:2016-05-25`. Content SHA-256 and exact main-slot binding hash, canonical/revision URLs, attribution/license and normalization notice survived readback. The legacy evidence-link column `contributed_placement` is retained for compatibility: value 1 records the initial normalized action contribution (the signing announcement in this proof), not an IR claim. No qualifier is populated for Arsenal.

Validation used `/tmp/m6p2-live.sqlite3`, a SQLite backup copy of the existing application database. All rows in its **12 preexisting structured tables** stayed equal, and the original application's database remained untouched. Repeated CLI timeline output at a fixed evaluation time was byte-identical with zero items. Loopback HTTP `/timeline` returned 200 and zero items for both hidden/revealed result modes. The old article correctly produced no news candidate; this does not prove an eligible live-news candidate.

Offline verification: **8 P2 / 26 combined M6 / 144 complete tests passed**. Tests cover pinned live-shaped parsing, identity/hash/revision mismatch, date precision, attribution, bounded/error responses, persistence/rerun, old-source suppression, CLI inspection, structured isolation, legacy IDs/duplicate/evidence-link migration, and migration rollback on invalid references. Existing P1 synthetic duplicate/repeat/follow-up and candidate tests remain green. Compile and whitespace checks passed. No network is used by the suite. Source investigation used three bounded Wikinews API queries, one Sportradar Editorial request and one NFL control; implementation validation added two one-page Wikinews requests. No archive crawl, linked-source retrieval or scheduled polling occurred.

**M6 REMAINS OPEN — permitted real same-development grouping and qualifying news-candidate acceptance remain unverified.** P2's licensed archival fetch/persist/idempotency subset is verified. The next slice should obtain a permitted pair of real publications about one development with adequate publication metadata, then reuse this persistence/ranking boundary. No new provider framework or M7 work is needed first.


## P3: real grouping and remaining candidate gate

Starting state: `main`, clean at `10c6ed444863bb6ebb30803ec7459f379b611bd2`; 26 focused M6 and 144 full offline tests passed. The remaining requirements were a real permitted same-development pair and a real qualifying current/recent candidate. No M3/M5 gate was retried or closed; M7 remains planned.

### Bounded discovery and evidence classification

Three serialized public Wikinews API search/content requests returned HTTP 200, each limited to five namespace-0 pages, with no continuation or linked-source fetch. Queries were `"Granit Xhaka"`, `"Arsenal" "signs"`, and `"Houston Texans" OR "Scottie Scheffler"`. Results included the original Xhaka article, unrelated Euro match reports, the separate Bellerín extension, and historical Texans draft/release reports. These are a bounded sample, not a claim that the whole archive was enumerated.

The useful second publication is [Arsenal signs Japanese Takuma; Chelsea signs Batshuayi](https://en.wikinews.org/wiki/Arsenal_signs_Japanese_Takuma;_Chelsea_signs_Batshuayi), page `2793763`, reviewed revision `4813539`, published **2016-07-06**, revision timestamp **2024-12-18T03:28:56Z**. Its body explicitly identifies Xhaka from Borussia Mönchengladbach as Arsenal's previous summer signing. A related-news entry identifies the May 25 original. This is real repeated background evidence in a separately published report from the **same publisher**, not independent corroboration, a new Xhaka signing, or a genuine follow-up.

Both articles carry the archived CC BY 2.5 marker, consistent with [Wikinews copyright policy](https://en.wikinews.org/wiki/Wikinews:Copyright). Attribution/license references and reviewed transformation notices are retained. Only the Xhaka passage contributes normalized evidence. The Asano/Chelsea transfers, images and linked publications are not ingested as developments. The May 25 topic date is explicitly reviewed resolution to the original announcement; the July report does not itself state that exact announcement date. No contract start date is substituted.

The [closure record](https://en.wikinews.org/wiki/Wikinews:Closure_of_Wikinews) confirms read-only operation from May 4, 2026. Therefore this archive cannot provide a September 2026 publication within the existing 48-hour candidate window. Both observed articles supply date-only publication, not a precise publisher timestamp. Their edit/revision timestamps remain provenance only.

### Minimal extension

The existing manual command fetches exactly the two allowlisted page IDs in one request and verifies each reviewed revision/body hash before any persistence. Unknown/missing/changed pages fail closed. No discovery loop, generic parser, schema migration or new ranker behavior is added. Both documents normalize to `arsenal:signing_announced:player:granit-xhaka:2016-05-25`.

Real date-only evidence exposed one ordering limitation: P2's precise-timestamp-or-URL ordering could place July's report before May's original when both timestamps were absent. Publication dates now order these documents by day without inventing a timestamp or granting eligibility. This only selects the correct initial material contributor; current-candidate rules remain unchanged.

```sh
python3 -m sports_briefing ingest-news wikinews-arsenal --db /tmp/m6p3-proof.sqlite3
python3 -m sports_briefing inspect news --db /tmp/m6p3-proof.sqlite3
python3 -m sports_briefing ingest-news wikinews-arsenal --db /tmp/m6p3-proof.sqlite3
python3 -m sports_briefing timeline --db /tmp/m6p3-proof.sqlite3
```

### Candidate scope remains open

No real qualifying candidate is claimed. In addition to historical/date-only publication, the current news candidate adapter explicitly supports only Texans IR-placement topics. Arsenal emission must not be added speculatively to make old evidence appear. Current source access is the next prerequisite; then any necessary source-specific normalization/candidate mapping must be bounded by the observed payload. Thus M6 is **not** labeled implementation-complete across all possible selected source paths.


### Current-source access check

Repository/local configuration inspection found only the existing football-data.org and Sportradar credential names; no SportsDataIO/news/editorial-specific credential or product-activation evidence was found. Values were not printed. This cannot establish account entitlements outside the repository. Per the bounded retry rule, Sportradar Editorial was **not** called again: the last actual result remains P2's 403, not a new P3 observation. Guardian was not revisited because no changed permission evidence exists. No account was changed and no external message sent.

Current [SportsDataIO NFL workflow](https://sportsdata.io/developers/workflow-guide/nfl) and [data dictionary](https://sportsdata.io/developers/data-dictionary/nfl) document team/player RotoBaller news, item IDs, source, `Updated`, title/content/URL and TermsOfUse. These are documentation-only findings; exact timestamp semantics and useful Texans payloads remain unobserved. Its [developer access](https://sportsdata.io/developers) distinguishes scrambled trial from real production access. The [licensing FAQ](https://sportsdata.io/help/data-rights-and-licensing-questions) permits storage within commercial licensed scope, but does not itself grant this project's third-party text normalization, retention and display rights. No trial payload is used as real evidence.

Smallest external requirement: provision real, non-scrambled **NFL team-level RotoBaller Player News & Notes / News-by-Team access**, with explicit permission for minimal SQLite provenance/content retention, deterministic topic normalization and local derived-topic display, attribution requirements and post-license retention rules. A current Texans IR-placement pair would fit the existing candidate action most directly. The feed must actually contain such evidence; a credential alone does not close acceptance. After access, only the demonstrated provider normalization/source attribution mapping is justified. If a different Arsenal topic is selected instead, its candidate mapping remains a small engineering task, not something already completed.


### P3 live verification and final acceptance

On 2026-09-26 the adapter retrieved both reviewed pages in one successful API request (HTTP 200 required). Using its validated batch and the existing persistence function, the original document was accepted first at **13:24:13.772980 UTC**, then the background repeat at **13:24:13.778408 UTC**. This was a real-source incremental proof on `/tmp/m6p3-live.sqlite3`, a backup copy of the application DB, not SQL edits or backdated observations.

| State | Documents | Topics | Evidence links | Topic revision | Meaningful change |
| --- | --- | --- | --- | --- | --- |
| Original accepted | 1 | 1 | 1 | 1 | `2026-09-26T13:24:13.772980Z` |
| Real repeat accepted | 2 | 1 | 2 | 1 | unchanged |
| CLI pair refetch | 2 | 1 | 2 | 1 | unchanged |

The repeat's two contribution flags are zero. Only last-new-evidence observation advances when B is first attached; it does not replace the original material document. The full CLI rerun made a second real API request and reported two unchanged documents, no inserts/updates/links. Separate-process `inspect news` matched every pre-rerun news row exactly. Thus **real same-development grouping and real repeat-without-novelty acceptance pass**. No genuine material follow-up was observed; P1's synthetic follow-up tests remain labeled synthetic.

Both articles retain `published_at=NULL` and their distinct 2016 publication dates; the topic announcement date remains May 25. At current evaluation the CLI returned zero items, and repeated programmatic timeline output at a fixed current evaluation time was identical. The Xhaka historical regression remains quiet. No current candidate, tier/position or result summary is claimed; the existing Texans-only `MEANINGFUL_CHANGE` adapter and global ranking are unchanged.

All rows in **12 preexisting structured tables** matched before/after in the proof copy and original application DB. The original DB was only read. Offline verification: **11 source-adapter / 29 combined M6 / 147 complete tests pass**; compile and whitespace checks pass. New tests exercise the real-shaped pair, initial versus repeat contribution, reverse date-only ordering, source mismatch rejection before writes, restart readback and P2 document compatibility. The P2 original normalized document, including metadata JSON, remains byte-equal to the prior implementation. No new schema, dependency, fixture fabrication, network-dependent test, LLM or ranker change was introduced. Three bounded discovery requests plus two pair-validation requests were made; no Sportradar/Guardian retry or SportsDataIO API call occurred.

**M6 REMAINS OPEN — permitted real current/recent news-candidate acceptance.** Real grouping is closed. Current-source access is the immediate external prerequisite; provider normalization/attribution and any required supported-topic candidate mapping remain evidence-dependent engineering work. Do not label the entire milestone implementation-complete before that work is known. The smallest next action is rights-cleared, non-scrambled team-level NFL news access with a qualifying Texans IR-development publication; this targets existing topic/candidate semantics. M3/M5 gates remain open and M7 planned only.


## Status classification and reopen trigger (2026-09-26 audit)

Audit baseline: `main`, clean at `54155759860b76da394bc8ddf197cfe4a89e943b`; 147 complete offline tests passing. No code changed.

**Status: source-independent implementation complete — acceptance blocked externally.** This is not DONE.

| Area | State |
| --- | --- |
| Engineering independent of source access | Complete: four news tables, publication/observation/meaningful-change clocks, idempotency, exact-duplicate and same-development grouping, repeat versus follow-up, atomic writes, structured isolation, the Texans IR `MEANINGFUL_CHANGE` adapter through the unchanged ranker, CLI/HTTP, and the licensed Wikinews adapter |
| Real-source acceptance completed | Licensed archival ingestion/idempotency (P2); real same-development grouping and repeat-without-novelty (P3) |
| Acceptance open | A permitted real current/recent development producing a qualifying deterministic candidate |
| Remaining engineering | Source-specific only: provider normalization/attribution and, if the observed development is not a Texans IR placement, one bounded candidate mapping. It depends on real payload evidence, so the milestone is not labeled fully implementation-complete |
| Blocker | External: permitted current/recent source access and rights, plus a qualifying development actually appearing in it |

No additional generic M6 engineering is justified now. M6 is paused, not abandoned.

**Reopen M6 acceptance** only when one of these becomes available:

- permitted real current/recent source access with precise publication metadata and adequate retention, processing and local display rights;
- new entitlement evidence for an already-investigated provider (Sportradar Editorial 403, Guardian default terms);
- another source meeting the same provenance and rights requirements.

SportsDataIO NFL News-by-Team (RotoBaller) remains the leading candidate, not a required vendor. Before any adapter it still needs: real non-scrambled access, a configured credential, confirmed minimal retention rights, confirmed normalization/processing rights, confirmed local display rights, known attribution obligations, post-license retention/deletion terms, and inspection of a real payload including its timestamp semantics. No provider module is added before that evidence.

On reopening, validate: real source → persisted current development → deterministic qualifying `MEANINGFUL_CHANGE` candidate → CLI/HTTP timeline → idempotent rerun. Eligibility windows, tiers and the shared ranker stay unchanged.

**M7 is not blocked by this gate.** M7 consumes already-ranked `TimelineCandidate` output. News candidates already reach that interface through synthetic and archival evidence, and a current source would add candidates without changing the interface.

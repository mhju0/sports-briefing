# Milestone 6: reviewed Texans development evidence (P1 offline proof)

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

Fourteen focused M6 tests and 132 complete offline tests pass. They cover exact reruns, two URLs/one topic, exact-content duplicates, old publication, repeat without novel information, one synthetic qualifier follow-up, atomic conflict rejection, source identity, separate-process readback, CLI/API candidate output, sparse selection, existing ranking precedence, and unchanged structured NFL tables. The synthetic follow-up proves persistence semantics only; it is not evidence that an actual official source published that sequence. M6-P1 remains an **offline implementation proof with live-source rights and real-source acceptance open**. M3 and M5 acceptance gates are unaffected.

In a separate local smoke check, the proof was run against a **copy** of the existing SQLite database. Two synthetic documents produced one topic and two evidence links at revision 1; an identical import left every news row unchanged. A third synthetic clarification produced the same topic at revision 2 with three evidence links; another identical import again left all rows unchanged. Every row in the 12 preexisting structured tables stayed byte-equivalent. Separate-process CLI output was stable, and loopback HTTP returned one synthetically labeled item with no result payload in either spoiler mode. These are offline product tests, not authenticated official news ingestion.

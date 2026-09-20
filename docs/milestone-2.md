# Milestone 2: local Arsenal API and iPhone

Completed and verified locally on 2026-09-20. The existing Python ingestion and SQLite database feed a thin FastAPI read endpoint and a single SwiftUI iPhone screen. Coverage remains **Arsenal, Premier League and UEFA Champions League only**. Refreshing the app reads saved data; it does not fetch football-data.org.

## Run locally

From the repository root, use Python 3.11+ and install the HTTP/test dependencies in a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Export `FOOTBALL_DATA_API_KEY` before ingestion. The CLI does not automatically load `.env`; the file's existence alone does not export its value. See [M1 credential setup](milestone-1.md#setup-and-commands). The HTTP server and iPhone do not need this secret.

```sh
python -m sports_briefing ingest arsenal
python -m sports_briefing inspect arsenal
python -m sports_briefing briefing arsenal --hide-results
python -m uvicorn sports_briefing.api:app --host 127.0.0.1 --port 8000
```

Keep that terminal running. In a second terminal:

```sh
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/briefings/arsenal?hide_results=true'
```

The default SQLite file is `data/sports_briefing.sqlite3`, relative to the server's working directory. Run ingestion and the server from the same repository root. The server opens existing state for reading and does not create or migrate a database.

Open `ios/SportsBriefing/SportsBriefing.xcodeproj`, choose the SportsBriefing scheme and an iPhone Simulator, then Run. The committed project is ready to open; XcodeGen is only needed if you edit `project.yml` and regenerate it. The simulator's `http://localhost:8000` reaches the Mac's local backend. This is a simulator-first development setup, not a deployed backend. A physical phone's localhost refers to the phone itself; physical-device networking/signing is not required or verified here.

Local HTTP uses an ATS exception for `localhost` only (`NSExceptionAllowsInsecureHTTPLoads`), not `NSAllowsArbitraryLoads`. Keep the server bound to loopback for this milestone. Do not expose this unauthenticated development API publicly. [Apple transport security documentation](https://developer.apple.com/documentation/security/preventing-insecure-network-connections).

## HTTP contract

`GET /health` returns `200 {"status":"ok"}`. It is process liveness, not a provider freshness or database-readiness guarantee.

`GET /briefings/arsenal` defaults to `hide_results=true`. The explicit `hide_results=false` query allows result data; the phone starts in hidden mode. “Reveal result” intentionally refetches shown mode; it does not change the database. There is no preferences/account system.

The success response has a small allowlisted shape:

| Field | Meaning |
| --- | --- |
| `entity.id`, `entity.name` | `arsenal`, `Arsenal` |
| `headline`, `summary`, `reason_shown` | Deterministic text from selected saved matches; no unsupported interpretation |
| `as_of` | M1 evaluation time: last successful fetch, not request time |
| `spoiler.results_hidden` | Requested spoiler mode |
| `next_match` | Selected upcoming match, or null |
| `latest_completed_match` | Selected completed match, or null |
| `source.provider`, `source.attribution`, `source.checked_at` | Provider credit and most recent successful request time |

Match objects include competition code/name, home/away names, kickoff in UTC and provider status. Their `provenance.observed_at` and `provenance.provider_updated_at` retain the accepted match observation time and provider update time to distinguish record provenance from the latest successful request. Completed matches indicate whether their result is hidden. Only shown mode adds the result's full-time home/away values, winner and duration. Unknown scores remain unknown; extra-time/penalty duration must not be described as a regular-time score.

Hidden output has no result object, score or winner, including in summary/headline text. API responses never include raw payloads, diagnostic history, internal SQLite row IDs, provider request URLs or API credentials. Explicit response models enforce this transport boundary. [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/).

Missing database, no successful ingestion or no selected next/latest match returns a controlled `404`. Invalid/unreadable persisted state returns a controlled `503`; internal exception details remain in server logs. Invalid query values return `422`. A phone unable to connect distinguishes that failure from an absent briefing and an unexpected response.

## Boundaries and behavior

```text
CLI ingest → football_data.py → storage.py → SQLite
GET /briefings/arsenal → api.py → briefing.py → SQLite (read only)
JSON → BriefingAPIClient.swift → ArsenalBriefing.swift → BriefingView.swift
```

The route calls `build_arsenal_briefing` and maps its output into an HTTP response. The existing function owns next/latest selection, timestamp interpretation and spoiler-safe projection. Neither the route nor Swift repeats fixture selection or reads SQLite directly. No schema or ingestion change is necessary. M1 reads fixture rows and latest-fetch metadata separately; overlapping ingestion could mix adjacent snapshots. For this local milestone, finish ingestion before refreshing the client. Atomic concurrent snapshot reads remain a later bounded reliability decision.

The screen presents one Arsenal briefing with next match as its focal context when available, otherwise the latest completed match. A completed match can be supporting context. This is fixed presentation of the existing M1 output, not the universal timeline ranking system. No claim is made that every routine fixture deserves a home timeline item in the eventual product.

URLSession obtains the JSON; a typed decoder translates it into Swift values; the view renders loading, loaded or failed state. Networking/decoding errors are separate from layout. Dates are stored/transmitted in UTC and displayed in the device's local timezone. Source timestamps remain visible so a saved snapshot is not mistaken for live coverage.

Two M1 semantics remain important:

- Stale update rejection compares incoming provider `lastUpdated` with stored provider `lastUpdated`, never local fetch time. A later successful request can leave an older accepted fixture observation unchanged. Provider and local clocks are not assumed synchronized.
- `as_of` evaluates the latest persisted records against a reference time. It does not reconstruct historical provider state. The HTTP slice does not add historical replay or a new time-selection policy.

## Tests and limitations

Backend tests use synthetic provider fixtures and temporary SQLite databases; the test suite does not contact football-data.org. Swift tests focus on contract decoding and error behavior. Exact commands, counts and simulator evidence are recorded in the [local milestone record](../.scratch/milestone-2/spec.md).

```sh
.venv/bin/python -m unittest discover -s tests -v
xcodebuild test \
  -project ios/SportsBriefing/SportsBriefing.xcodeproj \
  -scheme SportsBriefing \
  -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.0' \
  -derivedDataPath ios/DerivedData \
  CODE_SIGNING_ALLOWED=NO
```

Choose an installed iPhone simulator destination on your Mac (`xcrun simctl list devices available`). Xcode's Product → Test runs the same Swift test target. No football-data.org key is needed for either suite.

No Texans, Scheffler, cross-sport ranking, scheduling, notifications, production deployment, authentication, news/reporters or LLM summarization. Also unsupported: FA Cup, EFL Cup, other competitions, injuries and press conferences. There is no live push, offline cache, persistence on the phone or public distribution claim. M1 selection has next/latest slots, not a live-match slot; M2 intentionally does not add live ranking or selection. M1's bounded data window and provider access/delay limitations still apply.

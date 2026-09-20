# Milestone 2: Arsenal HTTP and iPhone slice

Status: complete

Authorized 2026-09-20. Review baseline: `05fd86b`.

## Scope

Prove existing football-data.org ingestion → SQLite → deterministic briefing → local HTTP → SwiftUI iPhone rendering. Preserve M1 schema, normalization, idempotency, CLI and tests. The API reads persisted state; it never triggers ingestion.

Add only a thin FastAPI HTTP layer, an explicit small response contract, and a native one-screen SwiftUI client using URLSession. Default to hidden results. Show loading, unavailable backend, absent briefing and malformed response states distinctly. Keep provenance/freshness visible and raw provider data private to local diagnostics.

Only Arsenal PL/CL fixtures/results. No Texans, Scheffler, universal ranking, other competitions, injuries, news/reporters, scheduling, notifications, authentication, deployment, Docker or LLMs.

## Acceptance evidence required

- Existing offline M1 tests still pass and ingestion remains usable.
- API health, persisted readback, hidden result safety, controlled missing state and reuse of domain selection are tested without provider access.
- Swift decoding/network failure logic has bounded tests; the app builds for iPhone Simulator.
- Local server serves the existing real SQLite database; the running simulator fetches and visibly renders that response.
- Local setup and contract documentation explain fetch/provider timestamps and preserve M1's snapshot evaluation semantics.
- Review the final diff before integration; record actual evidence and remaining verification gaps below.

## Boundary decisions

This is a Class 2 client/HTTP integration with no new persistence writes or schema changes. A task branch isolates implementation. One implementation owner writes Python/Swift/tests; the root owns documentation and end-to-end verification. No production actions are authorized.

The M1 default evaluation time remains the last successful fetch time. The API and phone display a saved briefing, not a live promise. Refreshing the phone only rereads SQLite; ingestion remains a separate manual command. Future ranking and live-state selection are not part of this milestone.

## Verification

Before changes, all 21 existing offline tests passed.

2026-09-20 implementation verification:

- Live ingestion still returned HTTP 200 and 22 PL/CL records; all 22 were no-ops, no duplicates. Receipt time: `2026-09-20T10:01:47.536315Z`. The credential stayed in the local environment; `.env` and database remain ignored.
- Python: 31 offline tests pass, including 21 unchanged M1 tests. New coverage includes health, persisted API projection/direct builder reuse, hidden result omission, unchanged DB bytes/no provider call, missing/empty state and malformed DB/timestamp/score handling. Pinned direct dependencies installed successfully; `pip check` passes. Starlette emits a non-failing deprecation warning for its HTTPX test adapter.
- Swift: Xcode 27 / Swift 6.4 built the iOS app and passed six Swift Testing functions (seven parameterized cases) on iPhone 17 / iOS 26.0. Coverage includes UTC timestamps with/without fractional seconds, hidden/shown decoding, hidden-request mismatch rejection, 404/503, unexpected JSON and transport error mapping.
- Actual Uvicorn HTTP requests against the real M1 database returned health 200 and deterministic Arsenal data. Default and explicit hidden output matched; shown scores matched persisted CLI results; the SQLite file hash was unchanged by API reads.
- Installed and launched `com.michaelju.sportsbriefing` on iPhone 17 Simulator. Visually inspected the actual HTTP-fetched Arsenal/Leeds upcoming fixture, Brighton/Arsenal completed fixture with result hidden, local-time rendering and provider attribution/observed/checked timestamps. This was not a SwiftUI preview or mock success screen.
- Visually inspected backend-unavailable state after stopping the server, absent-briefing state using the real API against a temporary missing database, and loading/unexpected-response states with a temporary delayed loopback stub. The real database was not changed for failure tests. Restored the real server and hidden briefing afterward.
- Temporary screenshots: `/tmp/sports-briefing-m2-{live,unavailable,empty,loading,malformed}.png`. They are session evidence, not versioned product assets. Physical-device networking and production operation were not tested.

Final gate completed on 2026-09-20:

- Implementation commits: `4ba8b56` and `fc89ee0`. Independent Spec/correctness and Standards review passed exact frozen code `fc89ee03bdfe7c7ab368e9b97f6c7dec4ca3d3dd` with no outstanding blocking findings. The generated app target and XcodeGen source both target iPhone only.
- A review concern about view-owned refresh cancellation was tested rather than assumed. Two temporary XCUITests against the actual API with a two-second delay passed: intentional reveal displayed a numeric result and duration; pull-to-refresh returned to the hidden loaded state without error. No cancellation defect was reproduced and no state-management framework or permanent UI-test target was added. The temporary test project is `/tmp/sports-briefing-m2-ui.jE10mU`; it is session evidence only.
- The regular seven Swift cases passed again after the device-family alignment. M1 application files, schema and original tests are unchanged from the baseline. No provider credential, SQLite file, virtual environment, build output or user-specific Xcode state is committed.
- Completion is local implementation/test/live-data-to-simulator verification. No push, production deployment or physical-iPhone verification is claimed.

# Milestone 5: Scottie Scheffler Golf provider proof and bounded ingestion

Status: in-progress

Provider gate: authenticated Sportradar Golf trial succeeds with the existing application key. Scottie's provider UUID and completed [redacted tournament] field/round/tee/leaderboard/result shapes were observed. The implementation stores a single confirmed stroke-play tournament, source clocks, and conservative tee-time candidates. After independent review corrected endpoint-owned source hashes and round-list shrinkage, M5-only validation tables were archived/rebuilt; the corrected live run again inserted six domain rows/five sources, then an immediate nine-request rerun yielded six unchanged rows/five unchanged sources and no duplicates. Readback passed and all [redacted] preexisting table hashes/counts remained unchanged. The offline suite passes 106 tests, including 25 Golf tests. Exact evidence is in `docs/milestone-5.md`.

Open acceptance gates: live Scottie-specific active predicate; changed Golf response revision ordering; honest recent-result eligibility timestamp; exception statuses beyond observed WD. These remain distinct from M3's separate current-week NFL blocker.

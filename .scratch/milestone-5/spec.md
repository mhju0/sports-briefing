# Milestone 5: Scottie Scheffler Golf provider proof and bounded ingestion

Status: in-progress

Provider gate: authenticated Sportradar Golf trial succeeds with the existing application key. Scottie's provider UUID and completed [redacted tournament] field/round/tee/leaderboard/result shapes were observed. The implementation stores a single confirmed stroke-play tournament, source clocks, and conservative tee-time candidates. Authenticated ingestion succeeded twice on September 23: six domain inserts then six no-change rows; five accepted source revisions then five no-change sources, with no duplicate rows. Persisted readback, spoiler-hidden deterministic timeline, and 102 offline tests passed. The exact evidence is in `docs/milestone-5.md`.

Open acceptance gates: live Scottie-specific active predicate; changed Golf response revision ordering; honest recent-result eligibility timestamp; exception statuses beyond observed WD. These remain distinct from M3's separate current-week NFL blocker.

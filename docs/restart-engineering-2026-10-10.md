# Restart engineering verification

Date: 2026-10-10. Starting commit: `a60efba`. Reviewed implementation: `1b535a1a52695254b82b11e0ade426ca7d1e7adc`.

## Completed

- Preserved both `Synthetic example: ` and `Demo data: ` in synthesis generation and cached reads. The English prompt is now `summary-en-v3`; older profiles do not reuse the new contract's cache. Real inference remains disabled.
- Unified package, OpenAPI and `/meta` versions at `0.2.0` through `sports_briefing.__version__`. Built a wheel from a temporary source copy and installed it into an isolated target; imported version, package metadata and API version agreed.
- Strengthened deployment smoke checks: nonempty Texans/Scottie demo output, disclosure in title/summary/attribution, synthetic provider identity, per-entity cap, default hidden results, explicit shown mode and restricted briefing endpoints returning 404. Explicit checks remain effective under Python optimization.
- Replaced unsafe shell backup creation/pruning with a Python standard-library helper behind the existing entry point. It validates retention before mutation, serializes concurrent runs, verifies a unique online SQLite copy before non-overwriting publication, retains the new copy and excludes symlinks, unrelated names and the source database/hard links from pruning.
- Corrected stale status wording while retaining dated historical evidence. LLM ranking is prohibited, not deferred. M3/M5/M6 acceptance gates are unchanged.
- Prepared provider-permission and quote requests in `provider-permission-requests.md`. No requests were sent.

## Fresh verification

- Full offline suite: **212 tests passed** (22.316 seconds in the implementation run).
- Focused checks: **29 synthesis, 7 deployment and 6 backup tests** passed.
- Compilation: `sports_briefing`, `tests` and `deploy/backup.py`; shell syntax and `git diff --check` passed.
- Actual loopback Uvicorn API on an isolated public-mode path: smoke check passed with four synthetic items, both spoiler modes, and blocked provider briefings. Direct timeline readback reported `hide_results`, Arsenal unavailable, Texans and Scottie only. No provider calls or credentials were used.
- Backup tests used temporary SQLite files only: invalid retention left files unchanged; concurrent runs made intact unique copies; failed copies did not prune; quoted/newline paths worked; bounded retention and restored contents were checked; source, hard links and symlinks were protected.
- Independent read-only Astra review accepted the exact frozen implementation commit without blocking findings. It independently ran all 42 focused tests plus temporary probes for eight concurrent backups at retention two, publication failure and corrupt-source failure. Retained copies stayed intact.
- Offline synthesis evaluation: 24 hand-authored cases, 13 accepted/11 rejected, zero expectation mismatches and three sampled semantic blind spots. This is not a real-model evaluation.

## Remaining limits

No host was provisioned and no public URL, Linux systemd/Caddy deployment or on-server restore was verified. Local backup success is not a disaster-recovery guarantee; independent host backups remain a deployment task. No source rights were granted, provider subscription purchased, current authenticated sports/news acceptance run performed, or source data transmitted to a model.

The restart report and ten interactive HTML concepts are exploratory artifacts, not an integrated API client or native SwiftUI delivery. Their browser checks are recorded separately with the report.

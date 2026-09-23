# Local milestone tracking

The user selected local Markdown on 2026-09-20. No external tracker is configured.

Milestone scope and completion evidence live in `.scratch/<milestone>/spec.md`.
Use a `Status:` field (`in-progress`, `complete`, or `blocked`) and append verification results when available. Split into individual tickets only if a later milestone needs that structure. This milestone does not use automatic triage.

Current implementation records: [Milestone 4](../../.scratch/milestone-4/spec.md) is complete as an offline read-only ranking layer. [Milestone 3](../../.scratch/milestone-3/spec.md) remains in progress behind its separate authenticated NFL provider verification gate. [Milestone 1](../../.scratch/milestone-1/spec.md) and [Milestone 2](../../.scratch/milestone-2/spec.md) are complete.
The bounded [Milestone 5](../../.scratch/milestone-5/spec.md) Golf slice is in progress. Its two remaining acceptance gates—Scottie-specific `LIVE` evidence and an approved honest `RECENT_RESULT` time rule—are documented in [docs/milestone-5.md](../milestone-5.md).
Product behavior remains in `docs/product-spec.md`; proposed future architecture in `docs/decisions.md` is not authorization to build it.

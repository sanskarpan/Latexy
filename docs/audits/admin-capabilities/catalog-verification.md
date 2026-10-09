# Catalog and quota verification

Verified against the shared implementation on 2026-10-09. No real accounts, payment providers, purchases or provider configuration were used.

## Passed

- 81 backend catalog, quota-policy, B57 pricing and subscription tests against isolated PostgreSQL 17 and Redis 8, using the repository's migrated test schema.
- Actual database concurrent-edit tests: one winner and one optimistic-version conflict for both catalog metadata and quota limits.
- Existing subscription IDs, status and paid-period boundaries remain unchanged when sales or public visibility are disabled.
- Catalog and quota migration downgrade/re-upgrade retain administrator edits and audit history.
- Lowering, raising and removing a quota limit use the same Redis counter and reset window. A receipt issued before the edit still refunds exactly once.
- Public/admin/current display consistency, free API daily allowance, granular capability denials, strict immutable-price and fixed-window validation.
- Billing-sales flag off still allows cancellation requests; provider unavailability is surfaced rather than reported as a successful cancellation.
- 28 frontend unit/render tests covering the shared catalog, numeric-limit serialization, period switching, visibility, disabled purchase actions and billing recovery.
- 8 existing Playwright harness isolation/lifecycle unit tests after the loopback-only hostname adjustment.
- Scoped frontend ESLint and full TypeScript `tsc --noEmit`, using Node 22.23.2.
- Python Ruff and `git diff --check` for the owned changes.

## Browser execution blocked before UI assertions

Four browser scenarios are present in `frontend/e2e/plan-catalog.spec.ts`: public pricing error/retry and period selection, admin metadata/sales edits, stale-version recovery, and quota-limit/unlimited edits. The first three were attempted before the fourth was added. No page or screenshot was successfully opened.

The pinned Playwright Chromium download returned a tiny HTML document rather than an archive. The available system Chromium was 154.0.8037.57 (not Playwright's bundled engine). The local Next test server starts when explicitly bound to 127.0.0.1, but Chromium aborts before page creation because this execution environment prohibits its local IPC socket:

`process_singleton_posix.cc:297: socket() failed: Operation not permitted (1)`

One reviewed escalation retry produced the same restriction. Browser retries stopped; no workaround to the denied IPC permission was attempted. Google Fonts also could not be fetched by the isolated Next harness, which used its declared fallback fonts.

A browser-enabled execution environment is still needed for visual QA and the four browser scenarios. This report does not represent those scenarios as passed.

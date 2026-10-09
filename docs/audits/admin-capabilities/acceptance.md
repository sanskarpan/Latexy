# Admin capability and plan controls: review acceptance

Status: **draft implementation; browser and provider acceptance remain open**.

Base: `bdee48926ce0e2e6c9c5e2b281d2ab07c4355b98` (main, checked 2026-10-09).

## Delivered scope

- One catalog entry for each of the 129 audited main-branch capabilities: 107 optional controls and 22 visible, deliberate always-on security/recovery/public-information baselines. The 31 existing family entries remain, including always-on compilation: 160 registry entries, 137 gateable.
- Global switches, five entitlement families and eleven concrete plan SKUs resolve through one database-authoritative policy. Legacy flag writes use the same source. Missing/unknown/malformed settings and policy outages do not grant optional features. Product access does not bypass switches for admin/support roles; authorization to administer or recover an account remains separate.
- Server admission and existing-artifact gates close the audited job, raw export, integration sync, developer key, builder, workspace and snippet bypasses. Anonymous paths, owner-controlled public publishing, BYOK consumption and connected collaboration sessions obey the applicable policy.
- UI loading/error/account-switch states fail closed for optional features; recovery controls remain. The admin inventory explains parent restrictions and immutable exceptions. Browser-extension actions use a fresh authenticated policy check.
- Versioned, audited catalog names/copy/order/visibility/new-sale availability drive public pricing, billing cards and current subscription display. Versioned exact-SKU compile/optimization/AI-assist limits preserve atomic counters, fixed reset windows and old refund receipts.
- Non-destructive migration upgrades/rollback/re-upgrade preserve administrator settings, existing subscriptions and audit history.

The [generated inventory matrix](feature-matrix.json) records source paths and actual verification status per capability. Its 90 backend-policy-covered entries are not 90 live-provider end-to-end passes; 17 client-only entries have wiring evidence rather than exhaustive browser behavior coverage. No claim of 129 manually tested workflows is made.

## Verification

Final commands were rerun after the code freeze on 2026-10-09. Supplemental focused evidence is in [backend verification](backend-verification.md), [catalog verification](catalog-verification.md), and [frontend verification](../../admin/frontend-capability-validation.md). These focused counts overlap; do not add them to aggregate totals.

- Final full backend regression: **4,649 passed, 12 failed, 4 skipped** out of 4,665. All 12 failures are the unchanged host TeX cases listed in [environment comparison](environment-comparison.json). The complete capability, migration, quota, accounting and matrix tests passed.
- Final frontend: **179 files / 1,242 tests passed**, using `pnpm exec vitest run --maxWorkers=2` with unchanged test timeouts. TypeScript and full ESLint passed; extension tests: **8 passed**, with syntax and least-privilege package checks.
- Final production Next.js build: **passed**, including static generation and standalone artifact output. An earlier concurrent attempt was killed with exit 137 under shared memory pressure; the final rerun serialized tests and build.
- Prior full backend regression (before final fixture/matrix refresh): **4,641 passed, 16 failed, 4 skipped** out of 4,661. The 15 non-matrix failures reproduce with exactly the same test IDs on clean main: 12 host TeX format/font-map failures and three mocked scraper success fixtures that unexpectedly depended on live DNS. Matrix drift came from concurrent UI wiring additions, then was regenerated. The scraper fixtures are made deterministic without changing SSRF protection.
- Main comparison: **268 passed, 15 failed, 4 skipped** across the eight affected existing test files. The set of failures equals the aggregate failures minus matrix freshness.
- Earlier main-baseline orchestration failures were caused by unit helpers that mocked Popen/Path without producing the PDF required by durable persistence. Those two helpers now explicitly mock the persistence boundary. **80 orchestration/finalization/refund tests passed** afterward; production engine behavior is unchanged by that fixture repair.
- Real PostgreSQL/Redis tests verify migration preservation, optimistic edit conflicts, new admission denial without charging, already-admitted completion/failure handling, and exactly-once refund/redelivery behavior.
- Follow-up policy regression: **56 passed**, including an additional real `0060` seed migration test proving complete SKU coverage, preservation of existing global/family/SKU denials and labels, mandatory baselines, and non-destructive downgrade/re-upgrade. This test was added after the aggregate run; application code is unchanged.
- Additional quota-outage unit coverage verifies that both limited and formerly unlimited plans deny before Redis mutation when the current policy is unavailable; read snapshots explicitly report unavailability rather than unlimited access.
- No real model, email, OAuth or payment-provider action was used. PostgreSQL, Redis and synthetic S3 were isolated local test services.

## Browser acceptance blocker

The local Next server starts on loopback. Chromium terminates before page creation because the execution environment prohibits its required local IPC socket (`process_singleton_posix.cc: socket() failed: Operation not permitted`). A permitted retry produced the same restriction. No sandbox/security setting was changed and no bypass was attempted. No browser assertions or screenshots passed.

API-mocked acceptance scenarios are committed in `frontend/e2e/capability-controls.spec.ts` and `frontend/e2e/plan-catalog.spec.ts`. Run `pnpm exec playwright test --config=playwright.capabilities.config.ts` in a supported browser environment before acceptance. These scenarios avoid paid/provider actions.

## Remaining requirements and rollout risks

1. **Browser and full workflow acceptance:** run the committed browser cases, responsive/visual checks and representative enabled/disabled transitions across the inventory. Live provider success, real OAuth exchanges and real payments remain unverified and are not needed to review this draft.
2. **Commercial price administration:** immutable price amounts, currency, billing interval, provider IDs and creation of new SKUs remain operator-controlled/read-only. Display and new-sale controls do not implement provider repricing. A reviewed immutable offer/version and billing integration is required; existing subscriptions/quotes/refunds must retain their identity.
3. **Other numeric controls:** Developer API daily request limits and quota reset windows remain operator-configured/read-only. Compile, optimization and AI-assist limits are editable per SKU. This is not every numeric operational/rate-limit setting.
4. **Migration integration:** this draft intentionally builds only on current main. Its `0060_capability_catalog → 0061_plan_catalog → 0062_plan_quotas` chain must be reconciled with open engine PR #1833 and billing PR #1834 before merging either combination. All eleven PR-only audit groups are listed in [the integration inventory](pr-integration-inventory.json) as unmerged and unverified; no placeholder switch is presented as implemented enforcement. Other open ownership/integration PRs need normal conflict review. No unrelated PR was silently merged.
5. **Admission semantics:** a switch denies new work, not cancellation of work already admitted. Existing finalization/refund rules finish admitted work. Already downloaded data cannot be recalled, and issued presigned URLs remain usable until expiry. See [enforcement contract](../../capability-enforcement.md).
6. **Rollout:** migrate before application deployment; avoid mixed old/new binaries when relying on immediate enforcement. Database-authoritative checks trade stale grants for additional reads; production load/latency acceptance remains open. Application rollback retains settings but older code does not enforce new controls.
7. **Engine environment:** 12 real TeX rendering tests remain blocked by this host's format/font setup and reproduce unchanged on main. No compile sandbox weakening was used to make them pass.

No merge, deployment, production mutation or provider-price mutation is part of this draft.

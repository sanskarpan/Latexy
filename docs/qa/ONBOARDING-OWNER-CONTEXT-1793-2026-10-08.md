# Onboarding owner-context QA — #1793

Date: 2026-10-08  
Candidate worktree: `/private/tmp/latexy-onboarding-owner-20261008`  
Base: current main `9c88f40a816b7255082c5f34bae3408494f31ee8`

## Scope

The candidate scopes onboarding completion and replay state to the authenticated owner, passes confirmed session context from Workspace and Settings, and ignores stale owner/request callbacks. Anonymous compatibility remains local-only: `useOnboarding()` with no argument and an explicit confirmed null-owner scope use the legacy `latexy_onboarding_completed` key; neither reads nor writes account preferences. An explicit unconfirmed scope is inert and cannot fall back to anonymous mode. A signed-in owner does not inherit the global anonymous completion flag.

Account API contexts additionally check confirmation immediately before dispatch. The post-dispatch result path retains the existing owner/generation/request-revision checks; a same-owner tour already opened or reset locally remains visible through confirmation loss. Server preference writes are best-effort; owner-scoped completion/replay intent is retained locally if they fail.

## Verification

- Tests-first runtime suite on the unmodified base: 13/13 failed in `/private/tmp/latexy-onboarding-owner-red-20261008.log`. These failures are assertions for the new owner/readiness/context contract, not 13 independently verified defects.
- Final full frontend unit suite: 168 files, 1,077 passed, in `/private/tmp/latexy-onboarding-owner-full-anon-final-20261008.log`.
- Focused final onboarding runtime suite: 16 passed in `/private/tmp/latexy-onboarding-owner-anon-focused-20261008.log`.
- `tsc --noEmit --incremental false`, ESLint over the changed TS/TSX files, and `git diff --check` passed.

The baseline browser run is `/private/tmp/latexy-onboarding-baseline-browser-20261008.log`: 3 selected, 1 passed and 2 failed. The held-server-true case showed a premature tour. The ABA case failed before releasing the held old-A response body, so it does **not** establish behavior after that stale body is released.

Root subsequently built the candidate in a disposable production copy (Next
15.5.24, application source checkpoint `662c7644`) and ran the seven onboarding
cases together with the five editor regressions: **12 passed**, one Chromium
worker, zero retries, strict page-error assertions and traces. The ABA candidate
test consumed the held old-A body before asserting that the fresh owner's tour
remained suppressed. The new onboarding file is added to the existing shared
production browser CI step, not a new globally triggered workflow. Deployment
manifest contracts (92) and changed-component classifier tests (21) also pass.

The first local production-build attempt failed because the new worktree had
only the frontend dependency symlink, not the root pnpm dependency-store path.
Adding the root symlink to the same frozen dependencies resolved that setup
failure without changing application code or installing into shared symlinks.
It is not recorded as an application defect. Generated caches and both local
dependency symlinks are excluded from commits.

| Browser evidence | SHA-256 |
| --- | --- |
| baseline log | `51e0f590a6fda46ef6877f6f5b5c3418514ecd7a0f8340d210a2e79760fb4f16` |
| integrated candidate log | `45c5997bd3d710c39a985cf8ff32021a67138c22099fbf73f2f572e2e096196c` |

Candidate log: `/private/tmp/latexy-onboarding-integrated-browser-20261008.log`;
traces in the sibling output directory. Build log:
`/private/tmp/latexy-onboarding-owner-production-server-corrected-20261008.log`.

This is synthetic local-browser acceptance, not deployed acceptance. No real
account mutations or provider/payment operations occurred. The Workbox test
shim is not native service-worker/PWA certification. Historical hydration issue
#1772 remains open; this passing suite does not establish its cause or fix.
The Next security patch #1857 / issue #1856 is a release prerequisite: refresh
from patched main and obtain fresh exact-head CI before protected merge and
production verification. Do not use an older green audit as acceptance.

## Changed source and tests

- `frontend/src/components/onboarding/OnboardingFlow.tsx`
- `frontend/src/app/workspace/page.tsx`
- `frontend/src/app/settings/page.tsx` (only the account-scope hook-call hunk)
- `frontend/src/__tests__/onboarding-runtime.test.ts`
- `frontend/src/__tests__/gap-fixes.test.ts`
- `frontend/src/__tests__/settings-oauth-ownership.test.ts`
- `frontend/e2e/onboarding-owner-isolation.spec.ts` (restored synthetic acceptance artifact; seven cases pass)

The report's initial agent-authored checkpoint preceded root's build/browser
validation and one-file commits; the follow-up above records those later checks.
`frontend/tsconfig.tsbuildinfo` was updated by typechecking and is an excluded
generated side effect, not a source target. Server writes are best-effort and
these tests do not establish atomic ordering across independent hook instances
or across multiple tabs/devices.

## Fixture isolation follow-up

Independent review found that later path-only Playwright routes could fulfill
external lookalike URLs before the fail-closed catch-all saw them. This was a
test-coverage flaw, not evidence of an application leak. Mocks now bind exact
app/API origins and explicit methods, distinguish template navigation from
backend JSON, and record/close unexpected WebSockets. A deliberate eighth
case proves external lookalikes, wrong-method requests and an external socket
are rejected and recorded instead of fulfilled by synthetic endpoints.

All eight onboarding cases pass against the same sealed Next 15.5.24 candidate
on port 5526, one worker, zero retries, strict page errors; ESLint and diff checks
pass. Log: `/private/tmp/latexy-onboarding-origin-guard-20261008.log`, SHA-256
`dcc8499ebecf0429a67c5fb21baaba09d15ce9802ed473840d158057dd501775`.
Test source SHA-256:
`36b10cfb595b2c1801763d684eda104d15c5ec653cd60f80d915779a5cac918c`.
This follow-up changes only fixtures, not application code. The earlier
production run remains a seven-onboarding-plus-five-editor checkpoint; it is
not relabeled as a 13-case integrated run.

Published checkpoint: draft PR #1858. Security PR #1857 has since merged and
passed production certification; Settings PR #1854 has also merged. Refresh
this branch from their canonical main state and obtain new exact-head CI before
release. Earlier local checks are not a claim of that future combined acceptance.

## Patched-main integration checkpoint

Merged canonical main `26e802ca3e83b11b565365f817407911080c5ff3` into
the draft without replacing the Settings file. The CI-only conflict was resolved
by keeping both provider and onboarding suites in the existing shared production
step. Two inherited manual React test harnesses lacked `useMemo`, causing
29 failures / 1,095 passes at the integration checkpoint. Only those mocks were
extended with indexed, dependency-aware memo slots; every original assertion
was preserved and no application code was weakened to accommodate mocks.

Final full frontend unit suite: **171 files, 1,124 passed**; focused inherited
Settings tests: 29 passed. Node 22 ESLint, non-incremental types and diff checks
pass. Dependencies are read-only symlinks to the separately frozen-installed
15.5.27 security worktree; no install ran through the shared symlinks.

Root rebuilt the combined application/dependency source checkpoint `3bf9c06e`
in a new disposable production copy on port 5527 (Next.js 15.5.27), then ran
editor5 + provider6 + onboarding8: **19 passed**, one Chromium worker, zero
retries, strict page errors and traces. Later changes touch only unit mocks and
this report, not that validated application source. The deliberate isolation
case expects its own blocked-traffic records; other cases require no unknown
traffic. This is synthetic local-browser acceptance, not live account/provider
or native PWA certification.

| Patched-main evidence | SHA-256 |
| --- | --- |
| integrated browser log | `ba69b884e3a55f55b297db7468d23c495ad3bb7010b0ad6fa458971450210800` |
| full frontend unit log | `4f279ebe9fd7420c2ff45304fb37ded72b6c59c34945f07b4b5868ba8bcaa649` |

Logs: `/private/tmp/latexy-onboarding-patched-main-integrated-browser-20261008.log`
and `/private/tmp/latexy-onboarding-harness-full-20261008.log`. Browser traces
are in the former's sibling output directory. Publish this checkpoint to draft
#1858; require fresh exact-head CI and normal protected merge followed by
production verification before release acceptance. Notification draft #1855
and legacy callback issue #1794 remain separate, as does hydration #1772.

## Current-main release review — 2026-10-10

Refreshed the existing branch from canonical main
`b96aa3b59463b82c2a6ce1df2a0ab79aa5960890`, including notification owner
isolation and GitHub OAuth ticket retention. The workflow conflict retains
both onboarding and notification browser regressions. The newly inherited
notification harness now has an indexed, dependency-aware `useMemo` slot;
its existing assertions are unchanged.

The change remains necessary: main still has a global anonymous completion
key and unscoped onboarding preference requests. Independent review also found
that dialog-local step progress survived account switching. Workspace now
keys `OnboardingFlow` by stable owner ID, so A/B/A transitions remount the tour
at step one while same-owner token rotation preserves current progress. A new
production-browser case exercises both switches without reloading the page.

Local cloud verification: 173 frontend unit files / 1,142 tests passed; full
non-incremental TypeScript and changed-file ESLint passed, plus `git diff
--check`. These runs use Node 24.19.0 and the existing frozen Next 15.5.27
dependencies through read-only links; no install was performed through the
links. An initial unit invocation from the repository root failed cwd-relative
file lookups; rerunning from the documented frontend directory passed. These
are unit/test-double results, not browser acceptance. The new browser test and
full Node 22 acceptance must pass on the final GitHub CI head before merge.
Local Chromium is not claimed because the cloud browser process has an IPC
restriction. No security setting was changed to bypass it.

No live account, provider, or payment mutation is part of this verification.
Preference persistence remains best-effort and does not promise atomic writes
across independent tabs/devices. Other draft PRs were not merged.

A second review found a narrow pre-dispatch credential-rotation window for
queued writes: the owner's current credential changed during render before
AuthSync published it to the shared API client. Both write contexts now compare
the captured credential with the hook's current token at dispatch, without
invalidation of already-dispatched UI state. Skip and replay regressions were
added first: both failed before the guard and pass after it. The complete
18-case onboarding runtime suite is included in the 1,142-test result above.

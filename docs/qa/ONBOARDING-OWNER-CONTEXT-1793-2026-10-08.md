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

The baseline browser run is `/private/tmp/latexy-onboarding-baseline-browser-20261008.log`: 3 selected, 1 passed and 2 failed. The held-server-true case showed a premature tour. The ABA case failed before releasing the held old-A response body, so it does **not** establish behavior after that stale body is released. The candidate browser suite/build has not been run; no candidate production behavior is claimed.

## Changed source and tests

- `frontend/src/components/onboarding/OnboardingFlow.tsx`
- `frontend/src/app/workspace/page.tsx`
- `frontend/src/app/settings/page.tsx` (only the account-scope hook-call hunk)
- `frontend/src/__tests__/onboarding-runtime.test.ts`
- `frontend/src/__tests__/gap-fixes.test.ts`
- `frontend/src/__tests__/settings-oauth-ownership.test.ts`
- `frontend/e2e/onboarding-owner-isolation.spec.ts` (restored synthetic acceptance artifact; unrun)

No build, candidate browser/E2E run, commit, or push was performed for this QA report. `frontend/tsconfig.tsbuildinfo` was updated by typechecking and is an excluded generated side effect, not a source target.

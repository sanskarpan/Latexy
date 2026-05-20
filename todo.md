# Audit Todo — 2026-05-19

## Scope Covered
- Backend: FastAPI routes, services, models, Celery workers, Redis integration, Alembic/test harness
- Frontend: Next.js app router pages, shared components, hooks, unit tests, Playwright flows
- Infra/dev workflow: Makefile, local stack startup, Postgres/Redis/Celery interactions
- GitHub context: recent `main` history, open issues, open PRs

## Fixed In This Audit
- [x] Registered the missing rate-limiting middleware path in the backend app and added config flags to control it.
- [x] Made backend test DB setup deterministic by recreating `latexy_test` from scratch before running the suite.
- [x] Removed stale-schema test flakiness by requiring migrated test DBs instead of silently `create_all`-ing partial schemas.
- [x] Disabled rate limiting in tests to avoid non-deterministic failures during the backend suite.
- [x] Flushed Redis test state between runs so job/cache assertions stop leaking across tests.
- [x] Fixed frontend lint issues in `/workspace/[resumeId]/edit` and BYOK key management code.
- [x] Removed Next.js metadata/themeColor and PWA cache-size warnings from the frontend build.
- [x] Fixed scraper test mocking so async warnings and un-awaited coroutine noise are gone.
- [x] Fixed reorder tests so Redis cache state cannot short-circuit prompt assertions in full-suite runs.
- [x] Fixed cleanup/health Celery tasks that were using async Redis paths from sync worker code and crashing with `Event loop is closed`.
- [x] Fixed job timestamp handling in Redis status tracking by using wall-clock time instead of event-loop monotonic time.
- [x] Hardened the auto-save checkpoint worker against stale queue payloads by resolving the current resume owner at execution time and tolerating missing users.
- [x] Added direct worker tests for stale queued user IDs and missing resumes.
- [x] Fixed `/try` hydration failures by moving `LaTeXEditor` decoration CSS out of an inline `<style>` block and into global CSS.
- [x] Removed `localStorage`-driven auto-compile SSR/client mismatch risk by loading persisted state after mount.
- [x] Hardened public trial status creation against concurrent first-load requests using an idempotent Postgres upsert.
- [x] Switched anonymous usage tracking to the atomic `check_and_track_usage()` path.
- [x] Fixed the editor linter auto-fix path to read Monaco’s current content safely and avoid wiping the document when the editor momentarily reported an empty value.
- [x] Preserved page-count and extracted-text metadata across later `job.started` events in the job-stream reducer and added regression test coverage.
- [x] Stabilized workspace Playwright fixtures by pre-completing onboarding in the `project-search`, `quick-tailor`, `resume-variants`, and `share-links` suites.
- [x] Reworked the LaTeX linter browser tests to use user-visible readiness and outcomes instead of brittle `networkidle` and `window.monaco` assumptions.
- [x] Stabilized the page-count warning browser suite by replacing brittle `networkidle`, exact-text, and Monaco DOM readiness waits with visible editor/banner readiness checks.
- [x] Fixed a real collaborative-editor bootstrap bug where authenticated edit sessions could render a blank Monaco model because Y.js binding eagerly overwrote the fetched resume before collaboration sync completed.
- [x] Added a development-only Monaco test hook and rewrote the writing-assistant browser flow to drive real Monaco selection/action state instead of flaky headless context-menu keyboard behavior.
- [x] Hardened the optimize-page ATS badge placeholder tests by freezing timers and asserting the pre-score state before debounced quick-score refreshes can replace it.
- [x] Revalidated the standalone frontend production build after isolating the earlier `.next` contention from concurrent dev/build runs.
- [x] Added production-aware environment validation for `API_KEY_ENCRYPTION_KEY`, removed silent production fallback encryption, and documented fail-fast startup rules.
- [x] Added explicit billing configuration modes, surfaced billing availability/status through the subscription API, and fixed the frontend billing flow to stop using nonexistent `/api/subscription/*` routes.
- [x] Normalized LaTeX capability detection/logging so startup reports one authoritative availability state instead of contradictory messages.
- [x] Reduced collaboration WebSocket auth/permission log noise by converting expected pre-room rejections into accept-then-close flows instead of noisy 4xx handshakes.
- [x] Added a repo-owned full-stack smoke target (`bash scripts/ci/full-stack-smoke.sh` / `make smoke`) plus a dedicated Playwright smoke spec and CI workflow job.
- [x] Split rarely used editor-side panels/modals behind dynamic imports on `/try` and `/workspace/[resumeId]/edit`, cutting the edit route from roughly `667 kB` to `394 kB` first-load JS in the verified production build.
- [x] Reconciled stale GitHub tracker items by verifying and closing fixed issues `#153` and `#366`–`#372`.
- [x] Fixed anonymous-session billing/header handling so guest users no longer trip authenticated UI assumptions on `/billing` and the global nav.
- [x] Fixed billing plan card heading semantics and portal assertions so the billing/developer browser flow is accessible and deterministic.
- [x] Removed the one-time full developer API key from the persistent documentation example area in the developer portal.
- [x] Guarded unsupported Monaco CodeLens refresh commands to eliminate a real runtime error that surfaced during the extra Playwright pass.
- [x] Implemented template admin CRUD endpoints behind `ADMIN_SECRET_KEY` and added backend test coverage for template management.
- [x] Implemented Feature `#46` Developer Public API end to end: DB/migrations, key service, key management routes, public API routes, portal UI, and backend/browser coverage.
- [x] Implemented Feature `#57` Advanced Subscription Tiers end to end: annual/student/team/coupon flows, team-seat management, pricing UI, and backend coverage.
- [x] Implemented `FEATURES.md` market-gap feature `7.1` Academic CV → Industry Resume Conversion with academic-CV detection, variant creation, conversion prompting, and editor workflow.
- [x] Upgraded `FEATURES.md` market-gap feature `7.2` DOCX Export Quality so macro-heavy resume templates export with structured headings/bullets instead of flattened raw text.
- [x] Reconciled stale feature checklist entries so the feature audit documents now match the verified codebase.

## Verification Completed
- [x] `cd backend && .venv/bin/pytest test/ -q`
- [x] `cd backend && .venv/bin/pytest test/test_checkpoints.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_gap_fixes.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_phase12_mvp.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_template_routes.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_tracker.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_developer_api.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_subscriptions.py -q`
- [x] `cd backend && .venv/bin/pytest test/test_academic_cv_conversion.py test/test_export.py -q`
- [x] `cd backend && .venv/bin/ruff check app/ test/`
- [x] `cd frontend && pnpm run lint`
- [x] `cd frontend && pnpm build`
- [x] `cd frontend && pnpm run test:unit`
- [x] `bash scripts/ci/full-stack-smoke.sh`
- [x] Live stack restart with `./scripts/dev.sh app`
- [x] Targeted Playwright reruns for the `/billing`, developer portal, template admin, `/try` hydration, ATS badge, linter, project-search, quick-tailor, page-count, resume-variants, share-links, and writing-assistant flows
- [x] Full Playwright suite `cd frontend && PLAYWRIGHT_PORT=5182 pnpm test` — 400 passed, 1 skipped on the final verification pass

## Remaining Production Backlog

No open audited P0/P1/P2 production-code items remain on this pass. The sections below are closure status plus residual operational follow-up.

### P0 / P1
- [x] Secrets and env hardening
- [x] Billing hardening
- [x] LaTeX capability logging
- [x] GitHub issue triage for `#153` and `#366`–`#372`

### P2
- [x] Reduce noisy WebSocket/auth 403 logs during mocked collaboration flows.
- [x] Review frontend bundle size and split editor-heavy optional panels more aggressively.
- [x] Add a CI-safe full-stack smoke target that boots services, waits for readiness, and runs a small Playwright smoke subset before broader browser coverage.
- [x] Review open dependency PRs `#374`–`#383`.
  Review outcome: `#374`–`#381` and `#383` are routine patch/minor bumps that can be merged in normal dependency batches after CI.
  Review outcome: `#382` (Tailwind 4) is a real migration, not a blind dependency bump; it should stay isolated behind a dedicated UI migration pass.

### Feature / Product Gaps
- [x] `#46` Developer Public API
- [x] `#57` Advanced Subscription Tiers

## Notes
- Recent repo history already contains merged fixes for several issues that are still open in GitHub. The codebase and issue tracker are currently out of sync.
- The checklist markdown had stale unchecked items for already-shipped features; that documentation has now been reconciled with the verified implementation.
- The current stack is materially healthier than the starting point, but production readiness still depends on environment discipline, issue triage, and keeping the full browser suite green continuously.
- Operational follow-up: deploy a strong high-entropy `BETTER_AUTH_SECRET`; local build output still warns when the configured value is weak.

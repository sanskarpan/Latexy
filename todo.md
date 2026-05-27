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

## Observability Program — 2026-05-26

### Current State Audit
- [x] Repo contains infrastructure scaffolding for Prometheus, Grafana, Alertmanager, Flower, Kubernetes monitoring manifests, and Nginx status.
- [x] `docker-compose.prod.yml` already defines Prometheus and Grafana services.
- [x] Kubernetes manifests already define Prometheus, Grafana, and exporter resources.
- [x] Nginx has an `/nginx_status` location for basic upstream visibility.
- [ ] Backend application metrics exposure is not verified as production-complete.
- [ ] Frontend `/api/metrics` exposure is referenced by Prometheus config but is not verified as implemented and production-useful.
- [ ] Redis and Postgres scrape targets in the root `monitoring/prometheus.yml` currently point at raw service ports, but the actual exporter wiring in the local compose stack is incomplete.
- [ ] Alerting configuration exists, but delivery is placeholder-level and not validated against a real notification channel.
- [ ] Structured application logging, request correlation, and trace propagation are not yet implemented to production standard.
- [ ] There is no verified OpenTelemetry tracing pipeline across frontend, backend, worker, and external calls.
- [ ] There are no production-grade SLOs, error budgets, runbooks, dashboard ownership, or alert review rules encoded in the repo.

### Gap Summary
- [ ] Monitoring exists as partial infra scaffolding, not as a fully wired observability system.
- [ ] The largest gap is application-level telemetry, not dashboard YAML.
- [ ] Current monitoring config overstates readiness because some scrape targets assume exporters or endpoints that are not fully integrated into the running stack.
- [ ] The project currently has health checks and some logs, but not end-to-end debuggability.

### Target End State
- [ ] Every user request and async job can be traced end to end with a stable request/job correlation ID.
- [ ] Backend exposes Prometheus metrics for HTTP, DB latency, Redis latency, Celery queue depth, job outcomes, external API calls, compile latency, and auth/billing/storage failures.
- [ ] Frontend exposes production-safe web vitals and API route metrics, and forwards correlation headers to the backend.
- [ ] Celery workers expose task execution metrics, queue lag, retry counts, failure rates, and task duration histograms.
- [ ] Prometheus scrapes real application/exporter endpoints only.
- [ ] Grafana dashboards cover product health, infra health, queue health, external dependency health, and deployment/regression visibility.
- [ ] Alertmanager sends real alerts to Slack/email/PagerDuty or the chosen on-call path.
- [ ] Runbooks exist for every critical alert class.

### Phase 1 — Logging Foundation
- [ ] Introduce structured JSON logging in backend API, worker, and beat processes.
  Why: current logs are readable but not consistently machine-queryable.
  Deliverable: one logging formatter config shared across FastAPI, Celery, and app services.
- [ ] Add request correlation IDs for every HTTP request.
  Deliverable: middleware that generates/propagates `X-Request-ID` and includes it in all log lines.
- [ ] Add job correlation IDs for all async work.
  Deliverable: every Celery task logs `job_id`, `resume_id`, `user_id`, and request origin metadata where available.
- [ ] Normalize log severity and event names.
  Deliverable: explicit event taxonomy such as `resume.compile.started`, `resume.compile.failed`, `auth.session.invalid`, `billing.webhook.failed`.
- [ ] Add log redaction rules.
  Deliverable: prevent secrets, API keys, auth tokens, and raw PII-heavy payloads from entering logs.

### Phase 2 — Metrics Instrumentation
- [ ] Add backend Prometheus metrics endpoint and instrumentation if missing or incomplete.
  Deliverable: verified `/metrics` endpoint with HTTP request counters, latency histograms, and in-flight request gauges.
- [ ] Instrument DB and Redis latency.
  Deliverable: metrics for query latency buckets, connection pool usage, Redis operation latency, and error counts.
- [ ] Instrument resume pipeline metrics.
  Deliverable: counters and histograms for compile success/failure, compile timeout, PDF extraction fallback use, ATS scoring latency, optimize latency, export latency.
- [ ] Instrument external-provider metrics.
  Deliverable: per-provider counters for OpenAI/Gemini/Anthropic/email/storage/billing calls, including errors, retries, and latencies.
- [ ] Instrument Celery metrics.
  Deliverable: task counts by name/status, retries, execution duration, worker heartbeat visibility, queue lag metrics.
- [ ] Add frontend observability metrics.
  Deliverable: capture web vitals, route transition failures, API route latencies, auth bootstrap failures, and editor hydration errors.

### Phase 3 — Exporters And Scrape Topology
- [ ] Replace invalid direct Redis/Postgres scrape assumptions in the root Prometheus config with verified exporter targets.
  Deliverable: local compose and production scrape configs both use real exporters or real app metrics endpoints.
- [ ] Add or wire Redis exporter in compose.
  Deliverable: `redis-exporter` service and Prometheus scrape target.
- [ ] Add or wire Postgres exporter in compose.
  Deliverable: `postgres-exporter` service and Prometheus scrape target.
- [ ] Add node/container metrics only where justified.
  Deliverable: `node-exporter` and `cadvisor` are either fully wired or removed from the config to avoid false readiness.
- [ ] Verify frontend metrics path.
  Deliverable: either real `/api/metrics` instrumentation or removal from scrape config until implemented.

### Phase 4 — Dashboards
- [ ] Create a Backend API dashboard.
  Panels: request rate, error rate, p50/p95/p99 latency, top failing routes, auth failures, billing failures, 5xx trends.
- [ ] Create a Resume Pipeline dashboard.
  Panels: compile volume, compile success rate, timeout rate, ATS latency, optimize latency, export failure breakdown, PDF extraction fallback rate.
- [ ] Create a Worker/Queue dashboard.
  Panels: queue depth by queue, task throughput, retry volume, oldest queued job age, worker heartbeat status.
- [ ] Create a Data Layer dashboard.
  Panels: Postgres connections, slow queries, deadlocks, Redis memory, Redis rejected connections, cache hit/miss, storage errors.
- [ ] Create an External Dependencies dashboard.
  Panels: provider error rates, billing webhook failures, email failures, storage failures, third-party latency.
- [ ] Create a Release/Regression dashboard.
  Panels: deploy time markers, smoke-test status, post-deploy error rate changes, browser-suite regression signal.

### Phase 5 — Alerting
- [ ] Replace placeholder Alertmanager delivery config with real channel integration.
  Deliverable: Slack/email/PagerDuty values loaded from env/secret manager.
- [ ] Define critical alerts.
  Examples:
  - API down
  - worker down
  - queue lag above threshold
  - compile timeout spike
  - 5xx rate spike
  - auth/session failure spike
  - billing webhook failure spike
  - storage failure spike
  - DB connection saturation
  - Redis rejected connections
- [ ] Define warning alerts.
  Examples:
  - p95 latency regression
  - elevated retry rates
  - fallback extraction usage spike
  - email backlog/failure increase
  - disk/memory pressure
- [ ] Add alert routing rules and severity ownership.
  Deliverable: who gets paged for infra vs application vs billing incidents.

### Phase 6 — Tracing
- [ ] Introduce OpenTelemetry tracing for FastAPI, outbound HTTP, DB, Redis, and Celery.
  Deliverable: spans across request entry, service logic, DB, Redis, provider calls, and worker execution.
- [ ] Propagate trace context from frontend to backend and backend to worker.
  Deliverable: request-triggered background jobs can be traced back to the initiating user action.
- [ ] Select a trace backend.
  Options to evaluate:
  - Grafana Tempo
  - Jaeger
  - vendor SaaS if operational simplicity is preferred
- [ ] Add sampling strategy.
  Deliverable: high-value failures kept at higher fidelity, low-value high-volume traffic sampled.

### Phase 7 — Runbooks And SLOs
- [ ] Define service-level objectives.
  Examples:
  - API availability
  - compile success rate
  - p95 compile latency
  - ATS scoring latency
  - job queue freshness
  - auth success rate
- [ ] Define error budgets and escalation policy.
- [ ] Add runbooks for every critical alert.
  Runbooks should cover:
  - how to identify blast radius
  - how to mitigate
  - rollback criteria
  - owner/team path
- [ ] Add deployment smoke gates tied to observability checks.
  Deliverable: post-deploy smoke validates health, metrics endpoint, worker heartbeat, and queue processing.

### Immediate P0 Observability Work
- [ ] Verify whether backend `/metrics` is actually implemented and usable in the current runtime.
- [ ] Verify whether frontend `/api/metrics` exists and whether it reports anything meaningful.
- [ ] Fix Prometheus scrape config so every listed target is real.
- [ ] Add structured JSON logging with request IDs in backend.
- [ ] Add worker/task/job correlation fields to Celery logs.
- [ ] Add one minimal Grafana dashboard that is guaranteed to work with the real metrics we expose.

### Immediate P1 Observability Work
- [ ] Add Redis and Postgres exporters to local compose if they are not already present there.
- [ ] Add backend metrics for compile outcomes, queue lag, ATS, optimize, export, and provider failures.
- [ ] Add alerting for API down, worker down, queue lag, and 5xx spikes.
- [ ] Add deployment/runbook documentation for observability bring-up.

### Immediate P2 Observability Work
- [ ] Add distributed tracing.
- [ ] Add frontend web vitals dashboarding.
- [ ] Add business-health metrics: sign-in failures, billing conversion failures, export usage, share-link errors, feature adoption.

### Blockers / Inputs Needed Later
- [ ] Final notification destination for alerts.
  Needed for: Alertmanager production rollout.
- [ ] Choice of trace backend.
  Needed for: OpenTelemetry deployment.
- [ ] SLO ownership model.
  Needed for: final alert thresholds and escalation policy.

### Execution Order Recommendation
- [ ] Step 1: Instrument backend logs and request IDs.
- [ ] Step 2: Verify and wire backend/frontend metrics endpoints.
- [ ] Step 3: Fix Prometheus target topology and exporters.
- [ ] Step 4: Create minimal working dashboards.
- [ ] Step 5: Add critical alerts only.
- [ ] Step 6: Add tracing.
- [ ] Step 7: Add runbooks, SLOs, and on-call policy.

# ISSUES — Latexy Production Audit
**Date:** 2026-06-11  
**Auditor:** Multi-agent production readiness audit (23-phase)  
**Scope:** Full codebase — backend, frontend, workers, database, security, performance, observability  
**Total findings:** 86 (31 high, 38 medium, 17 low)  
**Confirmed by adversarial verification:** 22/24 critical/high verified; 2 refuted (noted below)

---

## SECURITY

### [AUTH-001] Legacy JWT `is_admin=true` bypasses ADMIN_EMAIL gate
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
**File:** `backend/app/middleware/auth_middleware.py:249`

In `require_admin()`, after checking `ADMIN_EMAIL`, there is an unconditional fallback: `if _jwt_validator.is_admin(token): return user_id`. Any token signed with `JWT_SECRET_KEY` carrying `role=admin` or `is_admin=true` grants full admin access regardless of `ADMIN_EMAIL`. If `JWT_SECRET_KEY` is weak, leaked, or predictable, an attacker can mint their own admin token offline with no database interaction.

**Root Cause:** The legacy JWT admin fallback was added as a migration convenience but never removed or gated behind explicit configuration.  
**Impact:** Full admin access compromise — bypass subscription management, access all users' data, manipulate analytics.  
**Fix:** Remove the legacy JWT admin fallback entirely. Admin access should only be granted via session table lookup against `ADMIN_EMAIL`.

---

### [INJECT-001] `--shell-escape` flag enables arbitrary code execution in LaTeX compiler
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `backend/app/workers/latex_worker.py:31`, `backend/app/api/resume_routes.py`  
**Fixed in:** current branch

`--shell-escape` was present in `_ALLOWED_EXTRA_FLAGS` in `latex_worker.py` AND in `ALLOWED_LATEXMK_FLAGS` in `resume_routes.py`. When set, pdflatex executes shell commands embedded in LaTeX source via `\write18{...}`. A user can run arbitrary OS commands as the worker process user, exfiltrate environment variables, or pivot to other containers.

**Root Cause:** Convenience flag for tikz/pgf libraries added without security review; no input sanitization for shell-escape directives.  
**Impact:** Full RCE on the LaTeX worker container.  
**Fix Applied:** Removed `--shell-escape` from both whitelists. Added validation in `latex_service.py` to reject `\write18`, `\input{/`, `\openout`, `\openin{/`.

---

### [INJECT-002] LaTeX content not validated for shell-escape attack vectors
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/services/latex_service.py`

Even with `--shell-escape` removed, patterns like `\write18`, `\input{/etc/passwd}`, `\openout` can be present in submitted content. Existing validation only checked document structure.

**Fix Applied:** Added `_DANGEROUS_PATTERNS` check in `validate_latex()` that rejects content containing known execution/filesystem-access directives.

---

### [PAYMENT-001] Razorpay webhook has no replay attack protection
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/services/payment_service.py:534`

The webhook signature is validated cryptographically (HMAC-SHA256), but there is no event deduplication. A legitimately signed `subscription.activated` event captured by a network monitor can be replayed to re-upgrade a cancelled subscription or double-credit a user.

**Root Cause:** Replay protection was not implemented — only signature verification.  
**Impact:** Subscription fraud; account state inconsistency.  
**Fix:** Extract `event_data['id']`, store in a `webhook_events` table (or short-TTL Redis set), reject duplicate IDs with HTTP 200 (Razorpay retries on non-200).

---

### [AUTH-002] Job state/result endpoints have no authentication
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/api/job_routes.py`

`GET /jobs/{job_id}/state`, `GET /jobs/{job_id}/result`, and `DELETE /jobs/{job_id}` accept any job_id with no auth requirement. Any unauthenticated client who guesses or observes a job_id can read its state, download its result (including optimized LaTeX), or cancel it.

**Root Cause:** Auth was not applied to read-only job state endpoints.  
**Fix:** Add `user_id: Optional[str] = Depends(get_current_user_optional)` and verify the job belongs to the requesting user before returning.

---

### [CONFIG-001] MinIO credentials default to well-known values
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/core/config.py`

`MINIO_ACCESS_KEY` defaults to `minioadmin` and `MINIO_SECRET_KEY` defaults to `minioadmin_secret`. If a MinIO port is accidentally exposed or an operator doesn't override these, compiled PDFs and uploads are accessible to anyone who knows the defaults.

**Fix:** Remove defaults entirely; fail at startup if these are not set in production.

---

### [CONFIG-002] CORS allowed origins include localhost with no production enforcement
**Severity:** LOW | **Status:** Open  
**File:** `backend/app/core/config.py`

`CORS_ORIGINS` allows `http://localhost:5180` regardless of environment. In production, this should be restricted.

**Fix:** Log a warning at startup when running in production-like mode with localhost in CORS origins.

---

### [AUTH-003] Session token DB lookup is not timing-attack safe
**Severity:** LOW | **Status:** Open  
**File:** `backend/app/middleware/auth_middleware.py`

Session token is compared via SQL `WHERE token = :token` — database query timing can leak whether a token prefix is valid.

**Fix:** Store a HMAC-SHA256 of the token instead; index on the hash.

---

## BACKEND CORRECTNESS & RELIABILITY

### [TRIAL-01] TOCTOU race condition in `/public/compile` legacy route
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `backend/app/api/routes.py:525`

`check_rate_limits()` (plain SELECT) and `track_usage()` (separate INSERT/UPDATE) are two distinct transactions. Concurrent requests from the same device can both pass the limit check before either increments the counter, allowing unlimited parallel compilations regardless of the trial cap.

**Root Cause:** The atomic `check_and_track_usage()` helper (which uses `SELECT FOR UPDATE`) existed and was used on other routes but was never applied to the legacy compile endpoint.  
**Fix Applied:** Replaced the two-step pattern with a single `check_and_track_usage()` call.

---

### [JOB-01] Jobs stuck in `processing` state permanently on worker hard-kill
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
**File:** `backend/app/workers/orchestrator.py`, `backend/app/workers/cleanup_worker.py`

When Celery sends a hard `SIGKILL` (e.g., OOM, hard time limit), Python cannot run any handler. `latexy:job:{job_id}:state` stays in `status=processing` forever. The cleanup worker explicitly skips jobs that aren't already in `{completed, failed, cancelled}`. With `task_reject_on_worker_lost=True`, the task re-queues — but if the re-queue also fails, the job is permanently stuck.

**Root Cause:** No reconciliation sweep for stale `processing` jobs; cleanup worker has wrong status check.  
**Fix:** Add a `task_postrun` signal handler that transitions to `failed` if the task ends with `FAILURE` or `REVOKED`; update cleanup worker to flag jobs in `processing` state older than 10 minutes.

---

### [JOB-02] Cleanup worker scans dead Redis key namespace
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/cleanup_worker.py`

The cleanup task scans `latexy:job:*` but the actual job state keys are namespaced as `latexy:job:{job_id}:state`. The pattern never matches, so expired job metadata is never purged.

**Fix:** Update to scan `latexy:job:*:state` and derive the job_id by stripping the `:state` suffix.

---

### [EVENT-01] Live event loss window between task submission and WebSocket subscription
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/core/event_bus.py`

When a job is submitted and the WebSocket connects within milliseconds, there is a window between `create_task()` and `pubsub.subscribe(channel)` where published events can be missed. The XREAD replay covers events already in the stream, but events published before the stream entry is written (e.g., `job.started`) may be lost.

**Fix:** Ensure `pubsub.subscribe()` is called before XREAD replay, or use an atomic "subscribe then replay from 0" pattern.

---

### [EVENT-02] XREAD replay truncated at 500 events — LLM token streams silently incomplete
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/core/event_bus.py`

A single `XREAD COUNT 500` call is used for replay. LLM streaming jobs can emit thousands of token events. Any reconnect after a 500+ event job will miss earlier tokens, silently delivering an incomplete response.

**Fix:** Replace with a `while True: xread(last_id)` loop that pages through all events until the stream is exhausted.

---

### [CANCEL-01] Cancel event not written to Redis Stream — lost after reconnect
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/api/job_routes.py`

The `DELETE /jobs/{job_id}` handler publishes the cancel event directly via `r.publish()` to the Pub/Sub channel but does not call `XADD` to write it to the stream. If the client disconnects and reconnects before the job processes the cancel, it will never see the cancellation event in the replay.

**Fix:** Route the cancel event through `publish_event()` (which does both Pub/Sub and XADD) instead of direct `r.publish()`.

---

### [CANCEL-02] Cancel+completion race leaves frontend in indeterminate state
**Severity:** LOW | **Status:** Open  
**File:** `frontend/src/hooks/useJobStream.ts`

If `job.cancelled` arrives after `job.completed`, the frontend can flip from showing a success state back to a cancelled state. The reducer doesn't guard against terminal-state overwrites.

**Fix:** In the reducer, ignore transition events when the current status is already in a terminal state.

---

### [PUBSUB-01] Pub/Sub listener task leaks on job completion
**Severity:** LOW | **Status:** Open  
**File:** `backend/app/core/event_bus.py`

The `_pubsub_listener` task uses `break` to exit its loop but doesn't remove itself from `self._listeners`. If the job completes and the key is popped in the `finally`, but the listener dict lookup uses a stale reference, a dangling entry remains.

**Fix:** Add `self._listeners.pop(job_id, None)` at the top of the `finally` block.

---

## CELERY WORKERS

### [CW-001] Orphan subprocess on `SoftTimeLimitExceeded` in `latex_worker`
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `backend/app/workers/latex_worker.py:431`

The `except SoftTimeLimitExceeded` handler published a failure event and returned but never called `proc.kill()`. The pdflatex/Docker subprocess continued running, holding the Docker socket, file handles, and the temp directory.

**Fix Applied:** Added `proc.kill(); proc.wait()` in the `SoftTimeLimitExceeded` handler in both `latex_worker.py` and `orchestrator.py`.

---

### [CW-002] No dead-letter queue — exhausted retries silently disappear
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
**File:** `backend/celery_app.py`

When a task exhausts its max_retries, Celery moves it to `FAILURE` state but there is no `task_failure` signal handler, no dead-letter queue, and no notification. Failed jobs are invisible unless actively polled.

**Fix:** Implement an `on_failure` signal handler in `celery_app.py` that: (1) publishes a `job.failed` event to the Redis stream with the error, (2) updates job state to `failed` in Redis.

---

### [CW-003] Duplicate `job.started` event on every retry
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `backend/app/workers/latex_worker.py:174`, `backend/app/workers/orchestrator.py:117`

Both workers published `job.started` unconditionally at the top of the task, including on retries. A job that retries 3 times would emit 3 `job.started` events, confusing the frontend state machine and inflating analytics.

**Fix Applied:** Guarded `job.started` publication with `if self.request.retries == 0`. On retries, emits `job.retrying` with the attempt number.

---

### [CW-004] No exponential backoff on retries — fixed 60s countdown
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/latex_worker.py`, `backend/app/workers/orchestrator.py`

Retry countdown is hardcoded to `60` seconds. Under a sustained failure (e.g., LaTeX Docker down), multiple workers will all retry at 60s intervals, creating a retry storm that hammers the same failing resource at a fixed rate.

**Fix:** Use exponential backoff: `countdown=min(60 * (2 ** self.request.retries), 600)`.

---

### [CW-005] Temp directories never cleaned up on compilation failure
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/latex_worker.py`

On exception paths (parse errors, task failure before cleanup), the temp directory for the job is never removed. Under load, accumulated temp directories can exhaust disk space.

**Fix:** Wrap the compilation logic in a `try/finally` with `shutil.rmtree(job_dir, ignore_errors=True)`.

---

### [CW-006] Orchestrator retries emit `job.failed` with wrong `stage` field
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/orchestrator.py:287`

When the orchestrator fails and retries, it emits `job.failed` with hardcoded `'stage': 'llm_optimization'` even if the failure occurred during the LaTeX or ATS stage. This misattributes errors in monitoring and makes debugging harder.

**Fix:** Replace with `'stage': current_stage` where `current_stage` tracks the active stage.

---

### [CW-007] Cleanup worker failures are swallowed silently
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/cleanup_worker.py`

Exceptions in cleanup tasks are caught and logged at WARNING level but not re-raised. Celery marks the task as `SUCCESS`, so no alerting is triggered. Failed cleanup runs silently accumulate orphaned data.

**Fix:** Re-raise after logging, or add a metric increment to track cleanup failures.

---

### [CW-008] No poison-message handling — malformed payloads loop on retry
**Severity:** LOW | **Status:** Open  
**File:** All workers

If a task receives an unexpected payload shape (missing required keys), it raises an unhandled exception and retries up to `max_retries` times. The job appears stuck from the user's perspective.

**Fix:** Add a guard at the top of each task catching `TypeError` and `ValueError` that immediately marks the job as failed without retrying.

---

## DATABASE

### [DB-001] `compilations.resume_id` has no index
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/database/models.py:237`  
**Fixed in:** `models.py` + `backend/alembic/versions/0030_add_missing_indexes.py`

`resume_id` FK column on `compilations` has no B-tree index. Multiple hot query paths filter on this column. Causes sequential scans as the table grows.

---

### [DB-002] `optimizations.resume_id` has no index
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/database/models.py:258`  
**Fixed in:** Same as DB-001.

---

### [DB-003] `session.userId` has no index — every auth request pays a sequential scan
**Severity:** HIGH | **Status:** Open  
**File:** `backend/alembic/versions/0001_initial_complete_schema.py`

The Better Auth `session` table is queried on every authenticated request by `auth_middleware.py` using `WHERE token = :token AND userId = :user_id`. Neither column has an index in the migration. With thousands of active sessions, every API call performs a full table scan.

**Fix:** Add: `op.create_index('idx_session_user_id', 'session', ['userId'])` and `op.create_index('idx_session_token', 'session', ['token'])` in a new migration.

---

### [DB-004] N+1 query in tenant member listing
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/api/tenant_routes.py:253`

`list_members()` fetched all `TenantMember` rows then executed one `SELECT User` per member — N+1. Fixed with a single JOIN query.

---

### [DB-005] N+1 query in `list_my_tenants`
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/api/tenant_routes.py:197`

One `SELECT Tenant` per membership. Fixed with bulk `WHERE id IN (...)` fetch.

---

### [DB-006] N+1 query in career analysis path-role resolution
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/api/career_routes.py:159`, `backend/app/api/career_routes.py:207`

Both `analyze_career_path` and `get_career_analysis` fetched one `CareerRole` per role ID. Fixed with `WHERE id IN (...)` bulk fetch.

---

### [DB-007] Coupon redemption TOCTOU race — `max_uses` can be exceeded under concurrency
**Severity:** HIGH | **Status:** Open  
**File:** `backend/app/services/payment_service.py:259`

`validate_coupon()` performs a plain `SELECT` (no `FOR UPDATE`) to check `used_count < max_uses`, then a separate `UPDATE` to increment. Concurrent redemptions can both pass the check before either increments.

**Fix:** Use atomic `UPDATE coupon_codes SET used_count = used_count + 1 WHERE id = :id AND used_count < max_uses RETURNING id` — reject if 0 rows returned.

---

### [DB-008] Resume model has duplicate `archived_at` mapped_column
**Severity:** HIGH | **Status:** FIXED  
**File:** `backend/app/database/models.py`

Two `archived_at` column definitions in the `Resume` class. SQLAlchemy silently uses the last definition; the first is dead code and can cause confusion in migrations.

**Fix Applied:** Removed the duplicate declaration.

---

### [DB-009] Migration is massively out of sync with ORM models — 30+ tables missing
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/alembic/versions/0001_initial_complete_schema.py`

The single "complete schema" migration does not include many tables present in models.py (analytics tables, career tables, tenant tables, etc.). The database can only be bootstrapped by running `Base.metadata.create_all()` directly, not via Alembic. Rollback is impossible.

**Fix:** Generate individual incremental migrations for each missing table group; ensure each has a working `downgrade()`.

---

### [DB-010] Analytics service loads all rows into Python memory for aggregation
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/services/analytics_service.py:93`

`get_user_analytics()` fetches all `Compilation`, `Optimization`, and `UsageAnalytics` rows for a user with no LIMIT, then aggregates in Python. No upper bound on the `days` parameter. A power user with years of history or a DoS request with `days=99999` can OOM the worker.

**Fix:** Push aggregations to SQL using `func.count`, `func.avg`, `func.date_trunc`; add `Query(ge=1, le=365)` validation on the `days` parameter.

---

### [DB-011] Conversion funnel fetches all page_view events for Python-side filtering
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/services/analytics_service.py:544`

All `UsageAnalytics` rows are fetched then filtered in Python by `event_metadata->>'page'`. Scales poorly with analytics volume.

**Fix:** Add a functional index on `event_metadata->>'page'` or a generated column; push the filter to SQL.

---

### [DB-012] Payment webhook: UPDATE then SELECT — extra round trip, no transaction boundary
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/services/payment_service.py`

Subscription update and subsequent read are separate statements with no explicit transaction, risking inconsistency under concurrent webhook delivery.

**Fix:** Wrap in a single `UPDATE ... RETURNING` statement.

---

### [DB-013 to DB-018] Additional missing indexes and constraints
**Severity:** MEDIUM/LOW | **Status:** Open

- **DB-013:** Missing composite index on `compilations(resume_id, status)` for hot query paths
- **DB-014:** `resume_views.viewed_at` not indexed — range queries do full table scans  
- **DB-015:** `resumes.updated_at` not indexed — ORDER BY on list queries does filesort
- **DB-016:** No audit trail for anonymous compilations (`compilations.user_id IS NULL`)
- **DB-017:** SQLAlchemy connection pool unconfigured — defaults (5 idle + 10 overflow)
- **DB-018:** `payments.razorpay_payment_id` is UNIQUE but nullable — allows multiple NULL rows

---

## FRONTEND

### [F1] `useJobStream` reducer state not reset between consecutive jobs
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `frontend/src/hooks/useJobStream.ts:35`

When `jobId` changes (user submits a second job), `useEffect` re-subscribes but `useReducer` state is never cleared. Stale `logLines`, `streamingLatex`, `atsScore`, and `pdfJobId` from the previous job remain visible until the new job's events overwrite them.

**Fix Applied:** Added `dispatch({ type: '__reset__' })` at the top of the `useEffect` when `jobId` changes.

---

### [F2] Auth token race: API calls on mount fire before `AuthSync` sets the token
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
**File:** `frontend/src/app/workspace/[resumeId]/optimize/page.tsx:102`

The optimize page's data-fetch `useEffect` fires `apiClient.getResume()` and `apiClient.compileLatex()` on mount without checking session readiness. `AuthSync` sets the token in its own `useEffect([session])` which is deferred. When Better Auth's `useSession()` is still `isPending` on first render, `apiClient.authToken` is `null`, causing unauthenticated 401 requests.

**Fix:** Add `if (!session || session.isPending) return` guard before any API call in data-fetch effects.

---

### [F3] `deleteResume` and `cancelJob` swallow errors silently
**Severity:** HIGH | **Status:** FIXED | **Verified:** Yes  
**File:** `frontend/src/lib/api-client.ts`

Both methods called `fetch()` directly without inspecting `res.ok`. A 404 or 500 response from the server was silently discarded; callers would assume success and update UI state incorrectly.

**Fix Applied:** Added `res.ok` check and throw with `body.detail || 'operation failed (${res.status})'` in both methods.

---

### [F4] `useJobManagement` double-interval — dangling poll after re-render
**Severity:** HIGH | **Status:** Refuted by verification  
**Note:** Adversarial verifier found this is architecturally safe due to React's cleanup ordering guarantees. Not a real issue.

---

### [F5] REST polling fallback in `useJobStatus` discards the fetched state
**Severity:** MEDIUM | **Status:** Open  
**File:** `frontend/src/hooks/useJobStatus.ts`

The `refresh` callback calls `apiClient.getJobState()` but doesn't use the result — it just triggers a WebSocket reconnect. The fallback REST poll serves no actual purpose.

---

### [F6] `ATSDetails` interface missing `industry_key` field
**Severity:** MEDIUM | **Status:** Open  
**File:** `frontend/src/hooks/useATSScoring.ts`

Forces `as any` cast at call sites. The field is present in backend responses but missing from the TypeScript type definition.

---

### [F7] `request()` falls back to `text()` for non-JSON, non-empty responses
**Severity:** MEDIUM | **Status:** Open  
**File:** `frontend/src/lib/api-client.ts`

Typed callers receive a `string` instead of their expected type when the server returns unexpected content-type. This silently corrupts typed results.

---

### [F8] `WebSocketProvider` never disconnects on unmount
**Severity:** MEDIUM | **Status:** Open  
**File:** `frontend/src/components/WebSocketProvider.tsx`

`wsClient.disconnect()` is never called in the `useEffect` cleanup. If the provider remounts (e.g., during hot reload or a layout change), a second WebSocket connection is opened alongside the first.

---

### [F9] Blob URLs from `getPdfBlobUrl()` are never revoked
**Severity:** LOW | **Status:** Open  
**File:** `frontend/src/lib/api-client.ts`

Created `blob:` URLs are never tracked or revoked, causing memory accumulation proportional to the number of PDFs viewed per session.

---

### [F10] `clearError()` in `useJobStatus` is a no-op
**Severity:** LOW | **Status:** Open  
**File:** `frontend/src/hooks/useJobStatus.ts`

Consumers expect `clearError()` to reset error state, but it doesn't call `reset()` from `useJobStream`. Error state persists across job submissions until the next event overwrites it.

---

## PERFORMANCE & MEMORY

### [PERF-001] Analytics full table scan OOM risk
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
See [DB-010] above.

### [PERF-002] Conversion funnel Python-side JSON field filter
**Severity:** HIGH | **Status:** Open | **Verified:** Yes  
See [DB-011] above.

### [PERF-003] Analytics queries have no Redis caching
**Severity:** HIGH | **Status:** Open  
**File:** `backend/app/services/analytics_service.py`

Every `GET /analytics/me` request re-executes expensive aggregation queries. No cache-aside pattern. A single user can generate hundreds of DB queries per minute by refreshing the dashboard.

**Fix:** Wrap public methods with CacheManager cache-aside; TTL of 5 minutes is sufficient for analytics data.

---

### [PERF-004] `redis.keys()` pattern scan in production code paths
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/core/redis.py`

`KEYS` is a blocking O(N) command that scans the entire keyspace. Under production load with thousands of active jobs, a single `KEYS latexy:job:*` call can block Redis for hundreds of milliseconds.

**Fix:** Replace with cursor-based `SCAN` iteration.

---

### [PERF-005] Redis Streams `maxlen=10000` is far too large
**Severity:** MEDIUM | **Status:** Open  
**File:** `backend/app/workers/event_publisher.py`

Even for long LLM streaming jobs, 10000 events is far more than needed. With many concurrent jobs, stream memory grows proportionally.

**Fix:** Lower `maxlen` to `1000` with `approximate=True`.

---

### [PERF-006 to PERF-010] Frontend timer leaks and state accumulation
**Severity:** MEDIUM/LOW  

- **PERF-006:** `setTimeout` in settings page `useEffect` lacks cleanup  
- **PERF-007:** `NotificationProvider` timers may fire on unmounted components  
- **PERF-008:** SQLAlchemy pool unconfigured (see DB-017)  
- **PERF-009:** `logLines` in `useJobStream` accumulates without bound — cap at 2000  
- **PERF-010:** `PDFPreview` `setTimeout` calls lack cleanup refs

---

## OBSERVABILITY

### [OBS-001] Primary `/health` endpoint does not probe DB or Redis
**Severity:** HIGH | **Status:** Open  
**File:** `backend/app/api/routes.py:200`

`GET /health` only checks LaTeX binary availability. Container orchestration reports healthy even when the database or Redis is unreachable. A separate `/health` in `job_routes.py` does probe Redis, but is undocumented and not the canonical health URL used by `docker-compose.prod.yml`.

**Fix:** Add async `SELECT 1` and `redis_client.ping()` to the primary `/health` endpoint.

---

### [OBS-002] Exception handlers log `str(exc)` without `exc_info=True` — stack traces lost
**Severity:** HIGH | **Status:** Open  
**File:** All Celery workers

Every `logger.error(...)` in `except` blocks across `latex_worker`, `llm_worker`, `orchestrator`, and `cleanup_worker` lacks `exc_info=True`. Stack traces are never written to logs, making production debugging extremely slow.

**Fix:** Add `exc_info=True` to all `logger.error` calls inside `except` blocks.

---

### [OBS-003] Request ID not propagated into Celery worker tasks
**Severity:** HIGH | **Status:** Open  

HTTP request IDs are not passed as task arguments. There is no way to correlate an API request with its resulting job events in logs.

**Fix:** Pass `request_id` as a kwarg to all worker tasks; include it in all `logger.info/error` calls.

---

### [OBS-004 to OBS-011] Additional observability gaps
- **OBS-004:** `REDIS_URL` not validated at startup — silent default to localhost  
- **OBS-005:** LaTeX failure logs omit the actual pdflatex error line  
- **OBS-006:** Analytics admin endpoints have `TODO` comments about missing auth  
- **OBS-007:** LLM timeout produces no log metric  
- **OBS-008:** Hardcoded timestamp `'2024-01-01T00:00:00Z'` in `/system/health`  
- **OBS-009:** `LOG_LEVEL` not set in `docker-compose.prod.yml`  
- **OBS-010:** uvicorn access logs silenced at WARNING threshold  
- **OBS-011:** No DB slow-query observability  

---

## TEST COVERAGE GAPS

### [GAP-001] No tests for payment webhook signature validation
**Severity:** HIGH — see TEST_RESULTS.md for full coverage gap analysis.

### [GAP-002 through GAP-013]
See TEST_RESULTS.md for the complete test gap analysis.

# Latexy — Issue Tracker

Consolidated output of two full-stack audits (2026-07-25 and 2026-07-26, the latter after pulling
the admin-control-plane / entitlements / auth-completion drop).

**183 confirmed findings.** Every one was produced by an auditor reading source, then handed to an
independent agent instructed to *refute* it; only survivors are listed. 31 refuted claims were dropped
(listed in §Refuted so nobody re-files them).

Status legend: `OPEN` · `FIXED` (verified fixed — kept for history) · `PARTIAL` · `UNVERIFIED`

Do not delete entries. When something is fixed, change the status to `FIXED` and add the commit.

---

## Re-verification against current `main`

Every finding from round 1 that had a decisive runtime probe was re-run against `main` after the
feature drop (migration `0035` applied). Result at that point: **0 of 8 fixed.**

**Update (2026-07-27, branch `fix/audit-p0-p1`):** a fix pass has since landed. Re-running the same
probes now give **11 of 11 FIXED**, verified independently against the live stack. Suites after the fix pass: backend **2342 passed**, frontend **421 passed** + `tsc` clean,
TUI **118 passed** + typecheck/build clean.

| Issue | Probe result after the fix pass | Status |
|---|---|---|
| LX-006 — GET /analytics/me GroupingError 500 | status=200 body={"user_id":"dc9ec6e5-d466-4d75-88e8-15458a2f7ea4","period_days":30,"total_compilations":144,"successful_compilations":66,"success_ | `FIXED` |
| LX-008 — BYOK proxy double-wrap -> page TypeError | proxy api_keys is list=True; body={"success":true,"api_keys":[],"total_count":0} | `FIXED` |
| LX-008b — BYOK proxy launders upstream 401 into 500 | unauthenticated proxy GET -> 401 (want 401, not 500) | `FIXED` |
| LX-009 — /ats/score job_id unpollable (store_job_meta never called) | submit=200 job=88a48991-2db4-4c69-936d-3753e860315d -> state=200 {"status":"completed","stage":"","percent":100,"last_updated":1785132068.884912} | `FIXED` |
| LX-001 — Optimize+Compile completes but PDF/logs/synctex 404 | job=completed; /download=200 (40482b magic=b'%PDF-'); /logs=200; /synctex=200 | `FIXED` |
| LX-002 — Compilation stuck 'processing' -> share links 404 | compile=completed; DB row: completed \| compilations/30fe6cee-69ff-47c9-8662-fb7986efca25/resume.pdf \| 37376; anon GET /share/{token} -> 200; all-rows: fa | `FIXED` |
| LX-002c — Cancelled job leaves Compilation row wedged at 'processing' | DELETE /jobs/{id} -> 200; row status now: failed | `FIXED` |
| LX-004 — 429/413 lack CORS headers (CORSMiddleware innermost) | 200 ACAO=True; status 429 ACAO=True; expose-headers='Retry-After, X-Request-ID' | `FIXED` |
| LX-004b — 413 response lacks CORS headers | 413 headers: HTTP/1.1 413 Request Entity Too Large date: Mon, 27 Jul 2026 06:02:00 GMT server: uvicorn content-length: 148 content-type: application/json x | `FIXED` |
| LX-007 — Per-plan quotas advertised but never enforced | free account ran 8/8 compiles; never blocked | `OPEN` |
| LX-2.11 — POST /optimize is an unauthenticated LLM endpoint | anonymous POST /optimize -> 200 {"success":true,"optimized_latex":"\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}\n\\begin{document} | `OPEN` |

---

## Headline issues (runtime-reproduced)

These were each reproduced against a live stack, not inferred from source.

### LX-001 · `P0` · `FIXED` — `Optimize + Compile` reports success but produces no PDF

- **Where:** `backend/app/workers/orchestrator.py:522-639`
- **Mechanism:** `_run_latex_stage` `rmtree`s `TEMP_DIR/{job_id}` in its `finally` and — unlike `latex_worker` — never caches PDF/log/synctex to Redis.
- **Evidence:** Job returns `status=completed`, `success=true`, ATS score. Then `/download/{id}` → 404, `/logs/{id}` → 404, `/download/{id}/synctex` → 404. Identical resume via plain `latex_compilation` returns a 53,764-byte PDF. The flagship paid feature yields no document.
- **Fix:** Cache the artifacts to Redis before the `rmtree`, or defer the `rmtree`.
- **Fixed:** Artifacts (PDF/log/synctex) are now cached to Redis and the Compilation row reconciled from the worker **before** the `rmtree`. Verified live: combined job -> `/download` 200 (40,482 b, `%PDF-`), `/logs` 200, `/synctex` 200.

### LX-002 · `P0` · `FIXED` — `Compilation` rows never reach `completed`, killing 4 shipped features

- **Where:** `backend/app/api/job_routes.py:443` (create), `:769-799` (only reconciler)
- **Mechanism:** Rows are created `status="processing"`; the only code that sets `completed` is a side effect inside `GET /jobs/{id}/result`, which the frontend never calls (it uses WS + `/download`). The update also never sets `pdf_path`.
- **Evidence:** Live DB: **46 `processing` / 4 `completed`**, rows from 2026-07-02 still pending. Everything gated on `status == "completed"` is dead: share links (verified: fresh compile → `POST /share` 200 → `GET /share/{token}` **404**), one-click apply (422), compile error history (empty), bulk export, dashboard success-rate (always 0%).
- **Fix:** Update the row from the worker on terminal transition, and set `pdf_path`.
- **Fixed:** The worker now reconciles the `Compilation` row on every terminal path and populates `pdf_path`/`pdf_size` (MinIO upload happens only after the guarded UPDATE matches a row, so no orphaned objects; `cleanup_worker` gained a prune for the `compilations/` prefix). Verified live: row `completed` with `pdf_path=compilations/<job>/resume.pdf`, and **anonymous `GET /share/{token}` -> 200**.

### LX-003 · `P0` · `FIXED` — TUI: every authenticated job hangs 5 minutes then reports a false timeout

- **Where:** `packages/tui/src/lib/ws-client.ts:31-33`; `backend/app/api/ws_routes.py:171`
- **Mechanism:** The TUI sends the session token as an `Authorization: Bearer` **header** on the WS handshake. `ws_routes.py:171` reads `websocket.query_params.get("token")` — the header is never consulted. So the socket is anonymous, `_job_ws_access_ok` fails, and the backend replies `{"type":"error","code":"forbidden"}` — which `ws-client.ts` explicitly discards (*"Other outer types (heartbeat, error) are intentionally ignored"*).
- **Evidence:** Proven side-by-side on one real job id: with the `Authorization` header → `{"type":"error","code":"forbidden"}` then silence; with `?token=` → full event replay immediately. `latexy compile` exits 1 with *"Job timed out after 5 minutes"* while the compile had actually **succeeded** and the PDF (33,508 bytes) was downloadable the whole time. `app.tsx:38` shares this client, so the interactive TUI is equally dead for all 32 job-based commands.
- **Fix:** Append `?token=` to the WS URL, and stop swallowing `type:"error"` frames.
- **Fixed:** The TUI now passes the token as `?token=` (what `ws_routes.py` actually reads) and surfaces server `error` frames instead of discarding them. Verified live: `latexy compile` exits 0 with a real `%PDF`; previously exited 1 with a false "Job timed out after 5 minutes".

### LX-004 · `P1` · `FIXED` — Middleware error responses carry no CORS headers — browser sees opaque failures

- **Where:** `backend/app/main.py:120` (CORS added first ⇒ innermost)
- **Mechanism:** Starlette's `add_middleware` prepends, so `CORSMiddleware` ends up innermost and every short-circuiting middleware sits outside it.
- **Evidence:** Measured: `200 /health` → has `access-control-allow-origin`; `429` → **no** `access-control-*` (its `Retry-After: 60` is unreadable); `413` (13 MB body) → **no** `access-control-*`; `401` from a route handler → header present. So rate-limited / too-large / timed-out all reach JS as `TypeError: Failed to fetch`. Produced a flood of misleading "blocked by CORS policy" errors during the page walk.
- **Fix:** Register `CORSMiddleware` last so it is outermost.
- **Fixed:** `CORSMiddleware` is now registered last (outermost), and `Retry-After`/`X-Request-ID` were added to `expose_headers` so the browser can actually read them. Verified live: 429 and 413 both carry `access-control-allow-origin`; a 200 carries exactly one.

### LX-005 · `P1` · `FIXED` — Auth-token race silently breaks integration and plan state on mount

- **Where:** `frontend/src/components/AuthSync.tsx:20-28`; `workspace/[resumeId]/edit/page.tsx:972,978,983`
- **Mechanism:** Auth is an in-memory Bearer token; `setAuthToken` only assigns a field and **nothing ever writes `localStorage.auth_token`**, so the fallbacks at `api-client.ts:887` and `:1781` are dead code. `AuthSync` sets the token in a `useEffect` after the async session resolves, but those three fetches use `[]` deps and `.catch(() => {})`.
- **Evidence:** Observed live on the editor: `2x 401 /github/status`, `2x 401 /dropbox/status`, `2x 401 /subscription/current`, never retried, while `/resumes/{id}` returned 200 on the same page. A user who *has* connected GitHub/Dropbox sees them disconnected; a paying user's badge falls back to free. Also caused a spurious `403 /download/{job}/synctex` (returns 200 with correct auth).
- **Fix:** Depend on the resolved session, and stop swallowing 401s.
- **Fixed:** `AuthSync` now waits for `isPending` to clear; the dead `localStorage.auth_token` fallbacks were removed and mount-time fetches gated on a bounded auth-ready signal (bounded after review found an unbounded gate could hang anonymous `/try`).

### LX-006 · `P1` · `FIXED` — `GET /analytics/me` is a hard 500 for every user

- **Where:** `backend/app/services/analytics_service.py:153,160`
- **Mechanism:** Two separate `func.date_trunc("day", ...)` expressions are built, so SQLAlchemy emits `date_trunc($1, …)` in SELECT and `date_trunc($4, …)` in GROUP BY.
- **Evidence:** `asyncpg.exceptions.GroupingError: column "usage_analytics.created_at" must appear in the GROUP BY clause`. Reproduced on every call. `/analytics/me/timeseries` works (200, 7.8 KB).
- **Fix:** Bind the expression once and reuse it, or `group_by(literal_column("day"))`.
- **Fixed:** The `date_trunc` expression is built once and reused in both `select()` and `group_by()`. Verified live: `GET /analytics/me` -> 200.

### LX-007 · `P1` · `FIXED` — Quotas still unenforced — the new "entitlements engine" is boolean-only

- **Where:** `backend/app/core/feature_registry.py:19-27`; `alembic/versions/0035_admin_control_plane.py:84-91`; `backend/app/api/job_routes.py:243-266`
- **Mechanism:** The new engine has **no numeric limit field, no counters, no usage rows, no reset window, no INCR** — it resolves `has_feature(key) → bool`. Migration 0035 seeds every (plan × feature) row and every kill-switch to **enabled**. `SUBSCRIPTION_PLANS` limits are still read only by `payment_service` for display. `POST /jobs/submit` — the primary compile+LLM path — carries no gate at all, and `sync_has_feature()` (the worker hook) is called from nowhere.
- **Evidence:** Verified live: free-plan account ran **8/8 compiles** with no block; anonymous `/try` ran **5 compiles against a 3-trial quota**, counter stuck at 2, never refused. `GET /config/entitlements` returns all 27 features `true` to an anonymous caller.
- **Fix:** Add real usage counters keyed to `SUBSCRIPTION_PLANS`, and gate `/jobs/submit` and `/resumes/{id}/quick-tailor`.
- **Fixed:** Real numeric metering added (`QUOTA_DIMENSIONS` = compilations/optimizations/ai_assists, read straight out of `SUBSCRIPTION_PLANS` so advertised and enforced numbers cannot drift). Counter is a single atomic Redis `INCRBY` on `latexy:quota:{dim}:{user}:{YYYYMM}` with a 40-day TTL and `DECRBY` rollback on rejection; window is the UTC calendar month, so reset needs no cron. Wired into `/jobs/submit`, `/jobs/batch`, `/compile`, `/optimize`, `/optimize-and-compile`, `quick-tailor`, `academic-cv-convert`, `/formats/upload` and three `/ai/*` routes. Returns 402 `quota_exceeded` with `{dimension, limit, used, remaining, plan_family, period, resets_at}`. **Verified live:** free user blocked at 3 compiles; 20 concurrent requests against a 3-limit produced exactly 3 winners with the Redis counter at 3 (not 20); a 422 and a 400 burned nothing; unlimited plans short-circuit before touching Redis so a Redis outage cannot deny a paying tier.

### LX-008 · `P1` · `FIXED` — BYOK page crashes for every signed-in user (proxy double-wraps)

- **Where:** `frontend/src/app/api/byok/api-keys/route.ts:19-23`; `components/byok/APIKeyManager.tsx:39`
- **Mechanism:** Backend returns a dict; the proxy assigns that whole dict to `api_keys`.
- **Evidence:** Verified live — proxy emits `{"success":true,"total_count":0,"api_keys":{"success":true,"api_keys":[],"total_count":0}}`. The consumer then calls `.map()` on an object → `TypeError`. Fails even with zero saved keys.
- **Fix:** Forward the backend body as-is, or unwrap `data.api_keys`.
- **Fixed:** The BYOK proxy no longer double-wraps, and forwards upstream status instead of laundering it into a 500. Verified live: `api_keys` is an array; unauthenticated proxy GET -> 401 (was 500).

### LX-009 · `P2` · `FIXED` — `/ats/score` hands out a job id that can never be polled

- **Where:** `backend/app/api/ats_routes.py:215-236`; `backend/app/workers/event_publisher.py:183`
- **Mechanism:** `store_job_meta()` is defined and unit-tested but **never called from any production path**. The async branch mints a `job_id` without writing `latexy:job:{id}:meta`, which `/jobs/{id}/state` requires. `/ats/deep-analyze` does it correctly at `ats_routes.py:607-647` — the inconsistency is inside one file.
- **Evidence:** Verified live: submit 200 with a job id, 4 events published to `latexy:events:{id}`, `/jobs/{id}/state` → **404 forever**. The editor is spared (it uses sync `/ats/quick-score`) but `useATSScoring` and API consumers are not.
- **Fix:** Call `store_job_meta()` on the async submit paths.
- **Fixed:** The async `/ats/score` and `/ats/analyze-job-description` paths now register job meta/state via the canonical `_write_initial_redis_state`. Verified live: `GET /jobs/{id}/state` -> 200 (was 404 forever).

### LX-010 · `P2` · `OPEN` — Bad resume IDs silently bounce to `/workspace` with no explanation

- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx`
- **Mechanism:** No not-found state; the page redirects.
- **Evidence:** `/workspace/<nonexistent-uuid>/edit`, `/workspace/not-a-uuid/edit` and `/workspace/..%2F..%2Fetc%2Fpasswd/edit` all land on the library with **no message**. No crash and no traversal leak. `/r/` with an empty token falls through to the raw Next 404 instead of the styled "Link unavailable".
- **Fix:** Render an explicit not-found state.

### LX-011 · `P3` · `OPEN` — `dev.sh` reports partial infra as healthy; Redis/MinIO host ports hardcoded

- **Where:** `scripts/dev.sh` `is_infra_running()`, `:206-208`; `docker-compose.yml:71,91`
- **Mechanism:** `is_infra_running()` greps only `latexy-postgres`. Redis `"6379:6379"` and MinIO `"9000:9000"` are not env-templated the way `DB_PORT`/`MINIO_CONSOLE_PORT` are.
- **Evidence:** With Redis+MinIO down it printed "Shared infra already running… Skipping" and would have started the app against missing services. Both ports collided with unrelated local containers, which had to be stopped to run this audit — defeating the documented multi-slot workflow.
- **Fix:** Check all three containers; template both ports.

### LX-012 · `P3` · `UNVERIFIED` — One-off 186 s `POST /jobs/submit`, not reproducible

- **Where:** `backend/app/api/job_routes.py`
- **Mechanism:** Observed once during the TUI run.
- **Evidence:** A single `POST /jobs/submit` took **186.5 s** (status 200). Not reproducible afterwards: idle 40-135 ms; 12 concurrent submits completed in 0.6 s wall. Ruled out event-loop blocking by a sync LLM call — `/health` stayed at 10 ms throughout an `/optimize`. Logged for visibility only; cause unknown.
- **Fix:** Add submit-path latency metrics to catch a recurrence.

### LX-013 · `P2` · `FIXED` — Celery worker crash-loops with SIGSEGV on macOS whenever a task resolves an external host

- **Where:** `backend/app/core/celery_app.py` (`worker_process_init`)
- **Mechanism:** A Celery prefork child inherits CoreFoundation/`Network.framework` state from the multi-threaded
  parent. The first time that child resolves an **external** hostname, macOS runs the NAT64 synthesis pass
  (`nw_path_evaluator_evaluate` → `_gai_nat64_second_pass` → `getaddrinfo`) against invalid inherited state and
  dies with `EXC_BAD_ACCESS`. macOS annotates the crash report itself: *"crashed on child side of fork pre-exec"*.
- **Evidence:** 10,015 SIGSEGVs in one worker log. Only tasks that reach an external host died
  (`optimize_and_compile_task`, `embed_resume_task` — both call `api.openai.com`); `compile_latex_task`, which
  only touches localhost Redis/Postgres/MinIO, always survived. Isolated repro: `getaddrinfo` after a bare fork
  is fine; after an ancestor makes any outbound TLS request it segfaults 3/3. `AF_UNSPEC` and `AF_INET6` crash,
  `AF_INET` survives — only the NAT64 path. `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` does **not** help.
- **Fixed:** A Darwin-only `_install_darwin_fork_safe_resolver()` runs once per forked child before anything
  resolves a hostname, rewriting `AF_UNSPEC` → `AF_INET` in `socket.getaddrinfo`. No-op off Darwin, so
  Linux/Docker production keeps stock dual-stack resolution. Verified: 93 SIGSEGVs → **0** on an identical
  poisoned worker, 12/12 jobs completing with valid PDFs.
- **Note:** this is a **local-dev-only** crash (macOS prefork). It was not in the original audit — it surfaced
  during the fix pass. My own first bisect wrongly blamed the new reconciliation code; the 25-second clean-tree
  control run simply never executed an orchestrator task, so it was a false negative.


### LX-014 · `P1` · `FIXED` — `POST /optimize` and `/optimize-and-compile` were unauthenticated LLM endpoints

- **Where:** `backend/app/api/routes.py:536-606`
- **Evidence:** Anonymous `POST /optimize` returned 200 with real optimized LaTeX — no account, no trial record, no attribution, on the platform OpenAI key.
- **Fixed:** Both now require authentication and charge one `optimizations` unit, refunded when the LLM returns `success=false` or raises. Verified live: anonymous → **401**; authenticated paid user → 200 with real output and the counter incremented. The anonymous `/try` device-fingerprint trial path is untouched and still works.

### LX-015 · `P0` · `FIXED` — LaTeX hardening would have bricked all production compilation

- **Where:** `backend/app/services/latex_service.py`
- **Mechanism:** A first attempt at closing the unsandboxed-`pdflatex` hole added a gate that refused the local engine outside Docker. But the production worker image **bakes texlive in** and ships no docker CLI and no docker socket, so `docker_engine_available()` is False in prod — every compile would have raised `RuntimeError` on deploy. The gate conflated "texlive inside a container" with "unsandboxed pdflatex on a shared host".
- **Fixed:** `running_in_container()` now detects k8s (`KUBERNETES_SERVICE_HOST`) and cgroup markers, so the in-image engine is allowed; it fails closed **only** for production-on-a-bare-host, and `ALLOW_LOCAL_LATEX_ENGINE` remains an explicit operator override. Caught by the adversarial review before it went anywhere — logged here because it is exactly the class of regression this process exists to catch.

### LX-016 · `P1` · `FIXED` — Auth rate limiting was ineffective, and a first fix made it worse

- **Where:** `frontend/src/lib/auth-rate-limit.ts` (new), `frontend/src/app/api/auth/[...all]/route.ts`, `backend/alembic/versions/0036_add_auth_rate_limit.py` (new), `nginx/nginx.conf`
- **Mechanism:** Better Auth's limiter used in-memory storage, so on the documented serverless/multi-instance target it was per-instance and ineffective — a mail-bomb vector on forgot-password. A first fix swapped in a DB-backed `customStorage`, which was **worse**: read-modify-write from a stale `get()` meant 60 concurrent requests all returned 200 with the counter at 1 (90 reset emails to one victim), and storage errors propagated out of `auth.handler`, 500-ing *every* auth route including `get-session`.
- **Fixed:** That approach was abandoned. A separate limiter now runs at the route-handler level using a single atomic `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, with the table owned by migration `0036` rather than DDL on the request path, and per-path rules (5/hour for reset/verification, 3/10s for sign-in/sign-up). nginx additionally rate-limits the credential endpoints at the edge with exact-match locations, while `/api/auth/get-session` stays on the 10r/s zone. **Verified live:** 60 concurrent `/api/auth/request-password-reset` → exactly **5 × 200, 55 × 429**.


### LX-017 · `P1` · `FIXED` — Free-tier quota calibration made signing up *worse* than browsing anonymously

- **Where:** `backend/app/core/config.py` (`PLAN_QUOTAS`, new), `backend/app/services/entitlement_service.py`
- **Mechanism:** The first quota implementation enforced the marketing `SUBSCRIPTION_PLANS.features` numbers verbatim — free = 3 compilations/month and **0** optimizations. So every AI action 402'd for the entire registered free tier, while the same request made *anonymously* (device fingerprint only) succeeded. Signing up strictly removed capability. It also contradicted shipped copy: `OnboardingFlow.tsx` promised "unlimited compilations" and `HelpCenter.tsx` described the 3-compile limit as the anonymous trial "resetting every 24 hours".
- **Fixed (owner decision: generous free tier):** `PLAN_QUOTAS` is now the *only* enforced table, and the customer-facing strings in `SUBSCRIPTION_PLANS` are rewritten **from** it at import (`_sync_plan_feature_copy`), so pricing copy can no longer drift from enforcement. The window is per-dimension *and* per-plan. Free is **10 compilations/day, 3 optimizations/month, 25 ai_assists/month** — every allowance exceeds the 3-use anonymous trial, so signing up is always an upgrade. Onboarding and help copy reconciled.
- **Verified live:** 10 compiles then 402 with `{"window":"day","period":"20260728","resets_at":"2026-07-29T00:00:00+00:00"}`; 3 optimization jobs then 402 with `window: month`; `GET /subscription/plans` reports `free = "10 / day"`.

### LX-018 · `P0` · `FIXED` — Orphan-PDF pruner could have deleted every live PDF

- **Where:** `backend/app/workers/cleanup_worker.py`, `backend/app/workers/latex_worker.py`, `backend/app/utils/db_url.py`, `backend/app/workers/storage_guard.py` (new)
- **Mechanism:** The new MinIO pruner and the Compilation reconciler resolved `DATABASE_URL` **differently** — one fell back to `settings.DATABASE_URL`, the other did not. This repo's root `.env` points `DATABASE_URL` at a **production Neon instance** while `scripts/dev.sh` exports the local one. A reviewer demonstrated the pruner connecting to prod Neon, finding 95/95 local job ids "unknown", and therefore classifying every live PDF under `compilations/` as an orphan to delete.
- **Fixed:** One shared resolver (`resolve_database_url()`), plus positive same-database confirmation: the uploader stamps the DB identity into Redis and the pruner **refuses to delete** unless its own resolved identity matches the stamp (fail-closed — no stamp means no deletes). It also refuses when the DB holds zero `Compilation` rows, and logs the resolved host before any delete. A test asserts neither accessor reads `os.environ["DATABASE_URL"]` directly.

### LX-019 · `P2` · `FIXED` — `metadata: {"resume_id": null}` silently prevented the `Compilation` row, breaking share links

- **Where:** `backend/app/api/job_routes.py:364`
- **Mechanism:** The metadata sanitiser did `str(v)` unconditionally, so a JSON `null` became the **truthy 4-character string `"None"`**. That reached the `Compilation` insert as a UUID and failed it — `asyncpg DataError: invalid input for query argument $3: 'None'` — leaving the row uncreated. Because share links now require a completed `Compilation` row (LX-002), a null `resume_id` silently broke sharing for that job. Pre-existing (`git show HEAD` confirms the line is unchanged); the LX-002 fix made it load-bearing.
- **Fixed:** Nulls are dropped rather than stringified. Regression test added (`test_submit_with_null_metadata_value_creates_compilation_row`). Verified live: the row is now created with `resume_id = NULL`.


---

## Full catalogue

Detail for every entry (evidence, repro, suggested fix, and the verifier's severity correction)
lives in `docs/audit-artifacts/` (see §Artifacts). The tables below are the index.

## Round 2 — new surface + previously-untested domains (64)

### entitlements
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-001 | `P0` | `OPEN` | Per-plan quotas are still completely unenforced — the new engine is boolean-only and ships all-on | `backend/app/core/feature_registry.py:19-27, backend/alembic/versions/0035_admin_control_plane.py:84-91, backen` |
| R2-002 | `P0` | `OPEN` | POST /optimize and /optimize-and-compile are unauthenticated, unmetered LLM endpoints on the platform API key | `backend/app/api/routes.py:552-557, 592-597` |
| R2-003 | `P1` | `OPEN` | POST /jobs/submit — the primary LLM+compile path — has no entitlement gate, and the worker-side hook sync_has_feature() is dead code | `backend/app/api/job_routes.py:243-249, 260-266; backend/app/services/entitlement_service.py:283-302` |
| R2-004 | `P1` | `OPEN` | POST /resumes/{id}/quick-tailor spawns an LLM optimize+compile job with no entitlement check and no quota | `backend/app/api/resume_routes.py:1100-1110, 1134-1152` |

### tui-core
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-005 | `P0` | `OPEN` | WS client sends the session token as an Authorization header, but /ws/jobs only reads ?token= — every subscribe to an owned job is rejected, and the rejection is silently discarded | `packages/tui/src/lib/ws-client.ts:31-33 (and src/app.tsx:22, src/headless.ts:47)` |
| R2-006 | `P0` | `OPEN` | Interactive login POSTs Better Auth to the FastAPI backend, which 404s — there is no working interactive auth path | `packages/tui/src/components/overlays/LoginOverlay.tsx:41-44` |
| R2-007 | `P1` | `OPEN` | Interactive local-file compile posts to POST /compile expecting an async job with a WS stream, but that endpoint is fully synchronous and emits no events | `packages/tui/src/tools/compile.ts:47-56` |
| R2-008 | `P1` | `OPEN` | JobController.onComplete dereferences ev.result, which the backend never emits — TypeError is swallowed by an empty catch, so the compile result card is never rendered | `packages/tui/src/hooks/useJobStream.ts:83-99` |
| R2-009 | `P1` | `OPEN` | Headless --output writes the HTTP response body to the PDF file without checking res.ok, then reports success and exits 0 | `packages/tui/src/headless.ts:93-100` |
| R2-010 | `P2` | `OPEN` | 25 of 32 registered slash commands have no handler — they are autocompleted, documented in the README, and answer "Unknown command" | `packages/tui/src/commands/registry.ts:8-40 vs packages/tui/src/commands/dispatch.ts:22-80` |
| R2-011 | `P2` | `OPEN` | Headless argument parsing treats flag values as the positional .tex path | `packages/tui/src/headless.ts:53-73` |
| R2-012 | `P2` | `OPEN` | WS client discards every server error frame and every parse failure with a bare empty catch | `packages/tui/src/lib/ws-client.ts:38-51` |
| R2-013 | `P3` | `OPEN` | wsConnected indicator uses `once` listeners, so the status bar is permanently wrong after the first reconnect | `packages/tui/src/app.tsx:41-48` |
| R2-014 | `P3` | `OPEN` | Published README tells users to install the wrong package name and documents a /login command that does not exist | `packages/tui/README.md:6-10, 22-24 (README.md is in package.json `files`)` |

### admin-plane
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-015 | `P1` | `OPEN` | Startup admin reconcile promotes ADMIN_EMAIL matches to role='admin' without checking email_verified, defeating require_admin's stated safeguard | `backend/app/main.py:47-70` |
| R2-016 | `P2` | `OPEN` | Demoting an ADMIN_EMAIL user via the admin UI is silently reverted on the next backend restart | `backend/app/main.py:56-63 and backend/app/api/admin_routes.py:306-309` |
| R2-017 | `P2` | `OPEN` | No audit trail for any admin mutation (role changes, kill-switch flips, plan-matrix edits, feature-flag toggles) | `backend/app/api/admin_routes.py:255-309` |
| R2-018 | `P2` | `OPEN` | Admin nav link is gated on the build-time NEXT_PUBLIC_ADMIN_EMAIL, not on the new RBAC role, so users promoted through the Users & Roles tab never get a way into /admin | `frontend/src/components/GlobalHeader.tsx:75-83, 200-207` |
| R2-019 | `P2` | `OPEN` | Last-admin guard is a TOCTOU check-then-write: concurrent demotions can drive the admin count to zero | `backend/app/api/admin_routes.py:288-307` |
| R2-020 | `P3` | `OPEN` | Admin page's authorization probe only recognizes '403', so unauthenticated and 503 responses render the full admin shell with generic load errors | `frontend/src/app/admin/page.tsx:656-665` |

### auth-completion
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-021 | `P1` | `OPEN` | Successful email verification renders "Verification failed" — the banner's callbackURL strips the token | `frontend/src/components/EmailVerifyBanner.tsx:55, frontend/src/app/verify-email/page.tsx:17-36` |
| R2-022 | `P1` | `OPEN` | Email sender silently falls back to console-logging password-reset/verification links in production | `frontend/src/lib/email.ts:37-50; frontend/.env.production.example (no RESEND_API_KEY entry)` |
| R2-023 | `P1` | `OPEN` | Password reset does not revoke existing sessions | `frontend/src/lib/auth.ts:64-80 (emailAndPassword block)` |
| R2-024 | `P2` | `OPEN` | OAuth error path permanently locks the whole sign-in/sign-up form | `frontend/src/components/auth/SignInForm.tsx:36-45 and frontend/src/components/auth/SignUpForm.tsx:36-45` |
| R2-025 | `P2` | `OPEN` | Rate limiting on forgot-password / resend-verification uses in-memory storage on a serverless deploy | `frontend/src/lib/auth.ts:98-105; frontend/.env.production.example (Vercel deployment target)` |

### tui-ux
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-026 | `P1` | `OPEN` | TranscriptView feeds a non-append-only array to Ink <Static>, so streaming log updates are frozen, completed tool rows are dropped, and cards are duplicated | `packages/tui/src/components/TranscriptView.tsx:46-64` |
| R2-027 | `P1` | `OPEN` | JobController.onComplete dereferences `ev.result`, which the backend never sends; the TypeError is silently swallowed and the CompileResultCard never renders | `packages/tui/src/hooks/useJobStream.ts:82-96` |
| R2-028 | `P1` | `OPEN` | Prompt input is unmounted while a job is running, making the /cancel the UI tells the user to type impossible to enter | `packages/tui/src/components/PromptInput.tsx:56-67` |
| R2-029 | `P1` | `OPEN` | LoginOverlay posts credentials to /api/auth/sign-in/email on the FastAPI backend, which returns 404 — interactive sign-in cannot succeed | `packages/tui/src/components/overlays/LoginOverlay.tsx:36-44` |
| R2-030 | `P1` | `OPEN` | 25 of the 32 registered and README-documented slash commands have no handler and fall through to "Unknown command" | `packages/tui/src/commands/dispatch.ts:22-108` |
| R2-031 | `P2` | `OPEN` | `latexy compile file.tex` on a TTY without --json silently ignores the subcommand and opens the interactive TUI | `packages/tui/src/cli.tsx:7-24` |
| R2-032 | `P2` | `OPEN` | README and an in-app error both tell the user to run `/login`, which is not a registered command | `packages/tui/README.md:24` |
| R2-033 | `P2` | `OPEN` | LogStreamCard's collapse toggle is dead code — `isActive` is never passed, so the keybinding is permanently disabled | `packages/tui/src/components/LogStreamCard.tsx:20-27` |
| R2-034 | `P3` | `OPEN` | Keyboard hint line is rendered twice, once by PromptInput and again by KeyboardHints, with different content | `packages/tui/src/components/PromptInput.tsx:72-74` |
| R2-035 | `P3` | `OPEN` | vitest config omits the `__LATEXY_VERSION__` define that tsup provides, so any test rendering TranscriptView or AppShell throws ReferenceError | `packages/tui/vitest.config.ts:3-10` |

### parsers-upload
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-036 | `P1` | `OPEN` | All parsers do blocking CPU work inside async handlers — one OCR upload freezes the entire event loop | `backend/app/parsers/image_parser.py:45, backend/app/api/format_routes.py:311` |
| R2-037 | `P1` | `OPEN` | /formats/upload burns a platform LLM call with no entitlement, quota, or trial gate | `backend/app/api/format_routes.py:334-444` |
| R2-038 | `P1` | `OPEN` | Plain-text resumes are misdetected as YAML and rejected with a raw parser error; TextParser is unreachable | `backend/app/services/format_detection.py:206-211` |
| R2-039 | `P2` | `OPEN` | Frontend HTTP-status error mapping is dead code — users see the raw JSON error envelope | `frontend/src/lib/api-client.ts:1845-1848, frontend/src/hooks/useFormatConversion.ts:141-146` |
| R2-040 | `P2` | `OPEN` | Unbounded structured content is concatenated into the LLM prompt | `backend/app/services/document_converter_service.py:83, 154-204` |
| R2-041 | `P3` | `OPEN` | Client-side size limits are looser than the server's for five formats | `frontend/src/components/MultiFormatUpload.tsx:26-38 vs backend/app/services/format_detection.py:61-102` |

### integrations
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-042 | `P1` | `OPEN` | OAuth callbacks are unauthenticated and never bind the state nonce to the completing browser session — account-linking CSRF on all four integrations | `backend/app/api/github_routes.py:90-163 (same pattern: dropbox_routes.py:157-235, mendeley_routes.py:89-160, z` |
| R2-043 | `P1` | `OPEN` | Job-scraper rate limit is bypassable with a spoofed X-Forwarded-For header (proven live) | `backend/app/api/scraper_routes.py:52-83` |
| R2-044 | `P1` | `OPEN` | Dropbox per-resume sync state is never returned by the resume API, so the editor's Dropbox Push/Pull controls never appear after a reload | `backend/app/api/resume_routes.py:86-93,155-160 vs frontend/src/app/workspace/[resumeId]/edit/page.tsx:1030,202` |
| R2-045 | `P2` | `OPEN` | Every OAuth failure redirect emitted by the backend is silently ignored by the settings page | `frontend/src/app/settings/page.tsx:98-128 vs backend/app/api/github_routes.py:83-87 (and dropbox_routes.py:150` |
| R2-046 | `P2` | `OPEN` | Entitlement gate is only on /connect — push, pull, import and status stay fully usable after a plan downgrade | `backend/app/api/github_routes.py:59, dropbox_routes.py:125, zotero_routes.py:139, mendeley_routes.py:58` |
| R2-047 | `P2` | `OPEN` | Connect buttons authenticate only via the Better Auth cookie on the API origin, while every other API call is Bearer-token-only | `frontend/src/app/settings/page.tsx:163,167,185,203 and frontend/src/lib/api-client.ts:924-936,956-959; fronten` |
| R2-048 | `P2` | `OPEN` | SSRF guard resolves DNS separately from the connection, leaving a TOCTOU / DNS-rebinding window to the cloud metadata service | `backend/app/services/job_scraper_service.py:61-93` |

### multiuser
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-049 | `P1` | `OPEN` | /ws/collab bypasses the LEGACY_JWT_ENABLED kill-switch and accepts self-signed HS256 tokens | `backend/app/api/ws_routes.py:270-282` |
| R2-050 | `P1` | `OPEN` | Removing a collaborator does not terminate their live /ws/collab session | `backend/app/api/ws_routes.py:284-346, backend/app/api/resume_routes.py:2247-2269` |
| R2-051 | `P1` | `OPEN` | Real-time collaboration cannot work in production: CollabManager rooms are process-local while prod runs 4 uvicorn workers | `backend/app/services/collab_manager.py:178-200, backend/Dockerfile.prod:69` |
| R2-052 | `P1` | `OPEN` | Team seats are never revoked when the owner's team subscription ends — members keep team entitlements forever | `backend/app/services/payment_service.py:855-875, backend/app/api/team_routes.py:50-63` |
| R2-053 | `P2` | `OPEN` | Team seat limit is racy — concurrent invites exceed TEAM_PLAN_MAX_SEATS | `backend/app/api/team_routes.py:99-135` |
| R2-054 | `P2` | `OPEN` | Workspace member role (editor/viewer) is decorative — never enforced anywhere | `backend/app/api/workspace_routes.py:393-434, backend/app/api/comment_routes.py:60-91` |
| R2-055 | `P2` | `OPEN` | Comments feature (Feature 74) has no UI — CommentsPanel is never mounted | `frontend/src/components/CommentsPanel.tsx:17, frontend/src/app/workspace/[resumeId]/edit/page.tsx:107` |
| R2-056 | `P2` | `OPEN` | Tenant invite adds any user without consent, an admin can mint co-admins, and members cannot leave | `backend/app/api/tenant_routes.py:319-372, 375-405, 408-447` |

### fe-a11y-mobile
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R2-057 | `P1` | `OPEN` | Editor pane collapses to ~0px width on phones — the mobile editor is rendered but invisible | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:2191,2398-2405` |
| R2-058 | `P2` | `OPEN` | MobileEditor stubs 9 ref methods as silent no-ops, so Apply-fix / Apply-rewrite / jump-to-line buttons do nothing on mobile | `frontend/src/components/MobileEditor.tsx:104-114` |
| R2-059 | `P2` | `OPEN` | KeyboardShortcutsPanel advertises 8 shortcuts that are bound nowhere in the codebase | `frontend/src/lib/editor-shortcuts.ts:15,19,20,40,44,48,49` |
| R2-060 | `P2` | `OPEN` | Two of three service-worker runtime-caching routes have regexes that can never match — the PWA offline strategy is inert | `frontend/next.config.js:46,54` |
| R2-061 | `P2` | `OPEN` | No focus trapping in any modal; 14 full-screen overlays have no Escape handler and 28 of 34 lack role="dialog"/aria-modal | `frontend/src/components/ApplyModal.tsx, GenerateReferencesModal.tsx, ExportDropdown.tsx, byok/APIKeyManager.ts` |
| R2-062 | `P2` | `OPEN` | pdf.js worker is loaded from a protocol-relative third-party CDN at module scope | `frontend/src/components/PDFPreview.tsx:11` |
| R2-063 | `P3` | `OPEN` | Editor split-pane resize handle is mouse-only — unreachable by keyboard and by touch | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:2389-2395` |
| R2-064 | `P3` | `OPEN` | MobileEditor's virtual-keyboard height adjustment is dead code — flex-basis:0 overrides the inline height | `frontend/src/components/MobileEditor.tsx:162-173,227-231` |

---

## Round 1 — backend / frontend / infra (119)

### fe-routes
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-001 | `P0` | `OPEN` | BYOK page crashes with a TypeError: the /api/byok/api-keys proxy double-wraps the backend response | `frontend/src/app/api/byok/api-keys/route.ts:19-24, frontend/src/components/byok/APIKeyManager.tsx:39-42,150-15` |
| R1-002 | `P1` | `OPEN` | Pages that fetch on mount send unauthenticated requests (auth token race with AuthSync) | `frontend/src/components/AuthSync.tsx:20-28, frontend/src/lib/api-client.ts:876-892,903-921, frontend/src/app/s` |
| R1-003 | `P1` | `OPEN` | Signed-out visitors get a permanent loading spinner instead of a login redirect on five pages | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:997,1058-1061,1794-1800; frontend/src/app/workspace/[resum` |
| R1-004 | `P1` | `OPEN` | Workspace resume list is hard-capped at 20 with no pagination — extra resumes and their variants become unreachable | `frontend/src/app/workspace/page.tsx:156,211-221,781-787; frontend/src/lib/api-client.ts:1002-1007; backend/app` |
| R1-005 | `P2` | `OPEN` | Public portfolio page exposes the titles of every non-archived resume, not just public ones | `backend/app/api/portfolio_routes.py:270-292; frontend/src/app/u/[username]/page.tsx:19-24,79-101` |
| R1-006 | `P2` | `OPEN` | dropbox_sync_enabled is missing from the backend ResumeResponse, so the editor's Dropbox toggle always shows "off" | `backend/app/api/resume_routes.py:72-96 (ResumeResponse); backend/app/database/models.py:206-208; frontend/src/` |
| R1-007 | `P2` | `OPEN` | middleware.ts provides no auth gating and runs a blocking backend fetch on every request for any host not named latexy.io | `frontend/src/middleware.ts:5-10,24-62,64-72` |
| R1-008 | `P2` | `OPEN` | Six shipped pages are unreachable from the UI, and the "Settings" menu item points at /byok instead of /settings | `frontend/src/components/GlobalHeader.tsx:14-28,164-171; frontend/src/components/marketing/MarketingFooter.tsx:` |
| R1-009 | `P3` | `OPEN` | ?next= redirect parameter is generated but never honoured after sign-in | `frontend/src/components/auth/SignInForm.tsx:19-23,33-38; frontend/src/app/billing/page.tsx:181; frontend/src/a` |
| R1-010 | `P3` | `OPEN` | Proxy route PUT /api/byok/api-keys/[keyId] forwards to a backend route that does not exist | `frontend/src/app/api/byok/api-keys/[keyId]/route.ts:41-55; backend/app/api/byok_routes.py:134,158,178` |

### workers
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-011 | `P0` | `OPEN` | Orchestrator deletes the compiled PDF before publishing job.completed — every AI optimize+compile download 404s | `backend/app/workers/orchestrator.py:638-639, backend/app/workers/orchestrator.py:218-232, backend/app/api/rout` |
| R1-012 | `P1` | `OPEN` | Batch Tailor variants are never updated with the tailored LaTeX — every variant is a byte-identical copy of the parent | `backend/app/api/job_routes.py:576-644, backend/app/workers/orchestrator.py:246-256, frontend/src/app/workspace` |
| R1-013 | `P1` | `OPEN` | Cancelling a combined job during LLM streaming triggers a full retry (second billed LLM call) and reports "internal error" instead of cancelled | `backend/app/workers/orchestrator.py:411, backend/app/workers/orchestrator.py:294-313, backend/app/api/job_rout` |
| R1-014 | `P2` | `OPEN` | cleanup_expired_jobs_task marks still-running jobs as failed based on submission time, without revoking them | `backend/app/workers/cleanup_worker.py:319, backend/app/workers/cleanup_worker.py:352-370` |
| R1-015 | `P2` | `OPEN` | embed_resume_task reuses the module-global async SQLAlchemy engine across per-task asyncio.run() event loops | `backend/app/workers/ats_worker.py:705-741, backend/app/database/connection.py:16-17, backend/app/database/conn` |
| R1-016 | `P2` | `OPEN` | Orchestrator delimiter state machine never flushes its residual buffer, silently truncating up to 14 characters of LaTeX | `backend/app/workers/orchestrator.py:428-467` |
| R1-017 | `P2` | `OPEN` | Every streamed LLM token costs 6 sequential Redis round-trips, including a full job-state SETEX | `backend/app/workers/event_publisher.py:85-141, backend/app/models/event_schemas.py:162-176, backend/app/worker` |

### security
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-018 | `P0` | `OPEN` | LaTeX runs unsandboxed: docker fallback silently degrades to local pdflatex, and even the docker path has no network/memory/cpu/pids/read-only limits | `backend/app/workers/latex_worker.py:272-305, backend/app/workers/orchestrator.py:546-580, backend/app/services` |
| R1-019 | `P0` | `OPEN` | LaTeX injection blacklist is trivially bypassable, giving arbitrary host file read exfiltrated through streamed compile logs | `backend/app/services/latex_service.py:25-40, backend/app/workers/latex_worker.py:330-345` |
| R1-020 | `P1` | `OPEN` | The combined optimize+compile job path never calls validate_latex_content at all | `backend/app/api/job_routes.py:388-401, backend/app/api/resume_routes.py:1126-1135, backend/app/workers/orchest` |
| R1-021 | `P1` | `OPEN` | Two per-route rate limiters trust X-Forwarded-For unconditionally, contradicting TRUST_PROXY_HEADERS and letting anonymous callers bypass the anti-abuse caps | `backend/app/api/ats_routes.py:59-64, backend/app/api/ats_routes.py:670-700, backend/app/api/scraper_routes.py:` |
| R1-022 | `P1` | `OPEN` | k8s manifests ship committed Secrets with known weak passwords that deploy.sh applies as-is | `k8s/database/postgres.yaml:17-18, k8s/redis/redis.yaml:37-42, k8s/deploy.sh:85,98` |
| R1-023 | `P1` | `OPEN` | BYOK key-list proxy mangles the backend response shape, crashing the /byok settings page | `frontend/src/app/api/byok/api-keys/route.ts:14-27, frontend/src/components/byok/APIKeyManager.tsx:36-40,150-15` |
| R1-024 | `P2` | `OPEN` | Global body-size limit only inspects Content-Length, so chunked uploads reach unbounded file.read() | `backend/app/middleware/limits.py:28-44, backend/app/api/resume_routes.py:383-403, backend/app/api/routes.py:33` |

### billing
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-025 | `P0` | `OPEN` | Per-plan quotas (compilations / optimizations / history retention) are advertised and sold but never enforced anywhere in the backend | `backend/app/core/config.py:262-412 (SUBSCRIPTION_PLANS), backend/app/api/job_routes.py:242-300, backend/app/se` |
| R1-026 | `P1` | `OPEN` | GET /subscription/current returns 404 for any user with more than one subscription row (guaranteed after a retried or upgraded checkout) | `backend/app/services/payment_service.py:940-944, backend/app/api/routes.py:951-955, frontend/src/components/bi` |
| R1-027 | `P1` | `OPEN` | Nothing prevents creating a second live Razorpay subscription — plan switch double-bills the customer | `backend/app/services/payment_service.py:354-412 (create_subscription), backend/app/services/payment_service.py` |
| R1-028 | `P1` | `OPEN` | cancel_subscription reports success even when the Razorpay cancel API call fails — user is told they cancelled but keeps being charged | `backend/app/services/payment_service.py:986-1009` |
| R1-029 | `P1` | `OPEN` | Coupon codes are validated and consumed but the discount is never sent to Razorpay — customer is shown "20% off" and charged full price | `backend/app/services/payment_service.py:287-321 (_create_paid_subscription), backend/app/services/payment_serv` |
| R1-030 | `P2` | `OPEN` | Webhook idempotency key is read from a body field Razorpay does not send, so replay protection never actually engages and stale events can re-grant a cancelled plan | `backend/app/services/payment_service.py:530-545, backend/app/api/routes.py:1013-1020, backend/test/test_webhoo` |
| R1-031 | `P2` | `OPEN` | Anonymous trial use is consumed before the request is validated, so a 400 error burns one of three free uses and triggers a 5-minute cooldown | `backend/app/api/routes.py:718-760, backend/app/api/job_routes.py:271-330, backend/app/services/trial_service.p` |
| R1-032 | `P2` | `OPEN` | Team seat members keep team/pro-level access forever after the owner's team subscription is cancelled or halted | `backend/app/api/team_routes.py:190-208, backend/app/services/payment_service.py:841-884 (_handle_subscription_` |
| R1-033 | `P2` | `OPEN` | Student-plan verification tells the user "Student plan activated" while silently discarding the Razorpay payment link, so nothing is activated and nothing is paid | `backend/app/services/payment_service.py:196-233, backend/app/api/routes.py:904-913, frontend/src/app/billing/p` |
| R1-034 | `P2` | `OPEN` | The "device fingerprint" is a random localStorage value and the trial never resets, contradicting the shipped help copy | `frontend/src/lib/api-client.ts:3119-3128, backend/app/services/trial_service.py:296-300, backend/app/core/cele` |

### llm
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-035 | `P0` | `OPEN` | AI summary cache key hashes only the first 500 chars of the resume → one user's generated summary is served to another user | `backend/app/api/ai_routes.py:284-291 (_summary_cache_key), used at ai_routes.py:302-313 and 357-364` |
| R1-036 | `P1` | `OPEN` | BYOK API keys are never used by the main optimize / quick-tailor flows — the platform key always pays | `backend/app/api/job_routes.py:376-385 and 399-413; backend/app/api/resume_routes.py:1123-1146; backend/app/wor` |
| R1-037 | `P1` | `OPEN` | Client-supplied `model` string is forwarded to the platform OpenAI key with no allowlist | `backend/app/api/job_routes.py:97 (`model: Optional[str] = None`), :258 (safe_model), :383/:409; consumed at or` |
| R1-038 | `P1` | `OPEN` | Cancelling a job during LLM streaming is turned into a retry (second full LLM call) and reported as a hard failure | `backend/app/workers/orchestrator.py:409-411 (raise) and :294-311 (generic except → self.retry)` |
| R1-039 | `P1` | `OPEN` | No output-truncation guard: 4000-token cap on a whole-document rewrite, finish_reason never checked, silent fallback to the unmodified resume | `backend/app/core/config.py:101 (OPENAI_MAX_TOKENS=4000); backend/app/workers/orchestrator.py:384; backend/app/` |
| R1-040 | `P1` | `OPEN` | LLM-generated LaTeX is compiled by the orchestrator without the shell-escape/file-write validation the direct compile path enforces | `backend/app/workers/orchestrator.py:536-568 (_run_latex_stage) vs backend/app/workers/latex_worker.py:209; bac` |
| R1-041 | `P2` | `OPEN` | Delimiter state machine never flushes its hold-back buffer, silently dropping the last ~14 characters of LaTeX when the end marker is absent | `backend/app/workers/orchestrator.py:428-443 (_IN_LATEX branch) and :455-465 (_IN_CHANGES branch)` |
| R1-042 | `P2` | `OPEN` | Every AI endpoint maps provider errors and rate-limit exhaustion to HTTP 200 with echoed-back input, so the UI shows a fake success | `backend/app/api/ai_routes.py:497-499, 530-532 (rewrite), 223-225 and 266-268 (bullets), 320-322 and 368-370 (s` |
| R1-043 | `P2` | `OPEN` | Anthropic and OpenRouter BYOK keys can be stored and validated but are consumed by nothing; Gemini is advertised and unimplemented | `backend/app/services/api_key_service.py:53-57, :328-336; backend/app/services/llm_provider_service.py:24-29; b` |
| R1-044 | `P2` | `OPEN` | BYOK cost accounting is wrong by 10-60x for unknown models; OpenRouter has no pricing table and Anthropic's default contradicts its own table | `backend/app/services/llm_provider_service.py:104-126 (get_model_pricing/calculate_cost), :133-139, :233-239, :` |
| R1-045 | `P2` | `OPEN` | Anthropic key validation hardcodes a single Claude 3 model id, so valid keys can be rejected outright | `backend/app/services/llm_provider_service.py:314-332 (AnthropicProvider.validate_api_key), :346-351 (get_avail` |
| R1-046 | `P2` | `OPEN` | Quick Tailor result is persisted only by the browser — closing the modal loses the tailored resume (and cancels/retries the job) | `frontend/src/components/QuickTailorModal.tsx:32-53, 77-96; backend/app/api/resume_routes.py:1099-1146; backend` |
| R1-047 | `P3` | `OPEN` | llm_worker and cover_letter_worker stream the raw delimiter scaffold to the editor, contradicting the documented behaviour | `backend/app/workers/llm_worker.py:160-164; backend/app/workers/cover_letter_worker.py:188-192; frontend/src/ap` |

### latex-pipeline
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-048 | `P0` | `OPEN` | AI "optimize & compile" produces a PDF that is immediately deleted and never cached — download/preview/logs/SyncTeX always 404 | `backend/app/workers/orchestrator.py:522-639 (esp. 634-639), backend/app/api/routes.py:410-455, frontend/src/ap` |
| R1-049 | `P1` | `OPEN` | XeLaTeX / LuaLaTeX are offered in the UI but not installed in the backend/worker images; failure is retried for ~7 minutes while the UI shows "processing" | `backend/Dockerfile:8-18, backend/Dockerfile.prod:34-42, backend/app/core/config.py:48, frontend/src/components` |
| R1-050 | `P1` | `OPEN` | LaTeX compile errors are never shown to the user; the status bar says "LaTeX editor ready" after a failed compile | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1775-1790, 3036-3049, 1095-1104; backend/app/workers/latex` |
| R1-051 | `P2` | `OPEN` | Compile-settings modal exposes flags and a TeX Live version that the worker silently discards | `frontend/src/components/CompileSettingsModal.tsx:20-34, backend/app/workers/latex_worker.py:40-45 and 237-241,` |
| R1-052 | `P2` | `OPEN` | Export dropdown in the editor exports the last-saved DB copy, not the current buffer; its "PDF" entry is a dead end | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1830, frontend/src/components/ExportDropdown.tsx:86-146, b` |
| R1-053 | `P2` | `OPEN` | Image/OCR upload is advertised in the UI but the production image lacks tesseract and poppler | `backend/Dockerfile.prod:34-42, backend/Dockerfile:8-18, frontend/src/components/MultiFormatUpload.tsx:9-21, ba` |
| R1-054 | `P2` | `OPEN` | Non-resume compiles (TikZ preview, anonymised share) are tagged with `resume_id` and get written into the resume's version history | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1401-1426, backend/app/api/resume_routes.py:1746-1762, bac` |
| R1-055 | `P3` | `OPEN` | `POST /compile` and `POST /public/compile` are Docker-only and cannot work in the Docker deployment; the failure path also leaks temp dirs | `backend/app/services/latex_service.py:96-193 and 223-319, backend/app/api/routes.py:334-382 and 706-776` |
| R1-056 | `P3` | `OPEN` | /health reports `latex_available: true` whenever the docker CLI exists, even with no daemon or image | `backend/app/services/latex_compiler.py:31-43 and 246-256, backend/app/api/routes.py:239 and 265-269, backend/a` |

### docs-drift
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-057 | `P0` | `OPEN` | Compilation rows never leave status='processing' — silently breaks Feature 10 (share links), 87 (one-click apply), 88 (compile error history), 49 (bulk PDF export) and dashboard success-rate, all marked done | `backend/app/api/job_routes.py:443, backend/app/api/job_routes.py:769-799, backend/app/api/routes.py:1198-1213,` |
| R1-058 | `P1` | `OPEN` | Feature 74 (Resume Collaboration Comments, all boxes `[x]`) is unreachable from the UI — CommentsPanel is never imported and the editor's comment props are never passed | `features-checklist/P2_checklist.md:1864-1920, frontend/src/components/CommentsPanel.tsx:17, frontend/src/compo` |
| R1-059 | `P1` | `OPEN` | Compile Queue Priority (Feature 34) is inverted — Pro/BYOK users get the LOWEST Redis broker priority | `backend/app/core/celery_app.py:122-126,140-142,174-192, features-checklist/P1_checklist.md:2901-2965` |
| R1-060 | `P1` | `OPEN` | Compile Settings modal offers `--shell-escape`, which the backend rejects with 422 — and docs/FINAL_REPORT.md claims this flag was removed everywhere | `frontend/src/lib/api-client.ts:27-33, frontend/src/components/CompileSettingsModal.tsx:117-137,253-280, backen` |
| R1-061 | `P2` | `OPEN` | Portfolio contact form is a permanently disabled stub, but P2 Feature 67C checks it off as "submits to user's email via Resend SMTP" | `features-checklist/P2_checklist.md:1627, frontend/src/app/u/[username]/ContactForm.tsx:5-9,14-18,52-54` |
| R1-062 | `P2` | `OPEN` | Next.js middleware hard-codes the production hostname allowlist, so any other deployment domain triggers a blocking backend fetch on every request | `frontend/src/middleware.ts:4-9,39-57,61-68, features-checklist/P2_checklist.md:1631-1634` |
| R1-063 | `P2` | `OPEN` | Reverse drift: the guided form-based resume builder, feature-flag/admin system, telemetry and all marketing pages are shipped but appear in no feature doc; README lists 11 of 35 routes | `README.md:88-103, backend/app/services/resume_builder_service.py, backend/app/api/resume_routes.py:363-444,710` |
| R1-064 | `P3` | `OPEN` | No React error boundary is mounted anywhere despite ErrorBoundary.tsx existing; three other components are orphaned | `frontend/src/components/ErrorBoundary.tsx, frontend/src/components/JobStatusTracker.tsx, frontend/src/componen` |

### infra
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-065 | `P0` | `OPEN` | Production backend image listens on port 8000 while every consumer (nginx, healthchecks, k8s probes, Prometheus) targets 8030 | `backend/Dockerfile.prod:63-70, nginx/nginx.conf:63, docker-compose.prod.yml:81, k8s/backend/deployment.yaml (c` |
| R1-066 | `P0` | `OPEN` | Production sets FASTAPI_ENV, which no code reads — ENVIRONMENT stays "development", disabling all prod hardening (public /docs, localhost CORS with credentials, skipped secret checks) | `docker-compose.prod.yml:57,104,148; k8s/backend/deployment.yaml:26; backend/app/core/config.py:37,445-447,493,` |
| R1-067 | `P0` | `OPEN` | docker-compose.prod.yml never passes BETTER_AUTH_SECRET or JWT_SECRET_KEY, which Settings requires at import time | `docker-compose.prod.yml:56-74,103-118; backend/app/core/config.py:484-499` |
| R1-068 | `P0` | `OPEN` | nginx proxies the frontend to port 5180 but the production frontend container serves on 3000 | `nginx/nginx.conf:70; frontend/Dockerfile.prod (EXPOSE 3000 / CMD node server.js); docker-compose.prod.yml:25-4` |
| R1-069 | `P0` | `OPEN` | Production WebSocket URL is wrong by construction: released frontend connects to /ws/ws/jobs, nginx proxies /jobs/ws/ (compose) — real backend route is /ws/jobs | `frontend/Dockerfile.prod (ARG NEXT_PUBLIC_WS_URL=/ws), .github/workflows/release.yml (build-args NEXT_PUBLIC_W` |
| R1-070 | `P0` | `OPEN` | k8s nginx does not strip the /api prefix, so every API call from the production frontend build 404s | `k8s/nginx/nginx.yaml (location /api/ { proxy_pass http://backend; }), nginx/nginx.conf:111, frontend/Dockerfil` |
| R1-071 | `P1` | `OPEN` | No MinIO/S3 configuration in any production manifest — storage_service silently targets http://localhost:9000 | `backend/app/core/config.py:110-114, backend/app/services/storage_service.py:28-36, docker-compose.prod.yml (no` |
| R1-072 | `P1` | `OPEN` | FRONTEND_URL and BETTER_AUTH_URL are never set in production, so share links, e-mails and OAuth redirects point at http://localhost:5180 | `backend/app/core/config.py:139-142, backend/app/api/resume_routes.py:101,1779, backend/app/services/payment_se` |
| R1-073 | `P1` | `OPEN` | TRUST_PROXY_HEADERS is never enabled behind nginx, so all anonymous traffic shares one rate-limit bucket | `backend/app/core/config.py:192-195, backend/app/middleware/rate_limiting.py:46-51, nginx/nginx.conf:117, k8s/n` |
| R1-074 | `P2` | `OPEN` | k8s image names do not match anything the build pipeline produces (celery/beat/flower use latexy-backend:latest, app pods use ghcr.io/your-org/...) | `k8s/celery/celery-worker.yaml (image: latexy-backend:latest, three deployments), k8s/backend/deployment.yaml (` |
| R1-075 | `P2` | `OPEN` | scripts/deploy/deploy.sh cannot succeed: tags images that compose never creates and health-checks an unpublished port | `scripts/deploy/deploy.sh:6,209-211,254-286; docker-compose.prod.yml (backend has no ports:)` |
| R1-076 | `P2` | `OPEN` | Release notes tell operators to `docker compose -f docker-compose.prod.yml pull`, but that file has no image: keys — the published GHCR images are never used | `.github/workflows/release.yml (Deploy section of the release body), docker-compose.prod.yml:25-176` |
| R1-077 | `P2` | `OPEN` | Makefile dev/test targets reference a different compose file than the test helpers require, so `make infra && make test-backend` cannot work | `Makefile:24,110-131,152-166; backend/docker-compose.yml:24,32,43` |
| R1-078 | `P2` | `OPEN` | worktree-up.sh starts per-slot Compose projects that re-create the shared infra containers, hitting container-name and host-port conflicts | `scripts/worktree-up.sh (start_slot: `docker compose -p "$PROJECT_NAME" up -d backend worker beat frontend flow` |
| R1-079 | `P3` | `OPEN` | docker-compose.prod.yml nginx healthcheck probes port 80 /health, which only ever returns a 301 redirect | `docker-compose.prod.yml:16-20, nginx/nginx.conf:75-79,99-104` |

### fe-realtime
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-080 | `P1` | `OPEN` | Auth token is silently dropped if the session resolves while the WebSocket is still CONNECTING, leaving real-time permanently dead for logged-in users | `frontend/src/lib/ws-client.ts:73-81, frontend/src/components/AuthSync.tsx:20-29, backend/app/api/ws_routes.py:` |
| R1-081 | `P1` | `OPEN` | WebSocket onclose handler does not check socket identity, so a token change leaks an orphaned live socket and can double-deliver every event | `frontend/src/lib/ws-client.ts:73-81,167-175,247-252` |
| R1-082 | `P1` | `OPEN` | Server-sent WebSocket error frames have zero listeners, so 'forbidden'/'rate_limited'/'invalid_request' are silently swallowed | `frontend/src/lib/ws-client.ts:217-222, backend/app/api/ws_routes.py:104-134,203-207` |
| R1-083 | `P1` | `OPEN` | First subscribe never requests replay, so all events published before the subscribe frame lands are lost with no recovery path | `frontend/src/hooks/useJobStream.ts:47, backend/app/core/event_bus.py:98-101, backend/app/api/job_routes.py:200` |
| R1-084 | `P2` | `OPEN` | Reconnect resubscribes without last_event_id whenever no event was received on the previous connection, dropping the entire outage window | `frontend/src/lib/ws-client.ts:101-104,152-161,196-209` |
| R1-085 | `P2` | `OPEN` | useJobStatus's advertised 'REST polling fallback' can never bootstrap state and re-fires onComplete every 5 seconds | `frontend/src/hooks/useJobStatus.ts:6,109-147` |
| R1-086 | `P2` | `OPEN` | job.retrying is published by workers but is unhandled everywhere on the frontend, freezing the UI silently for up to 10 minutes | `backend/app/workers/latex_worker.py:194,551; backend/app/workers/orchestrator.py:125,300; frontend/src/hooks/u` |
| R1-087 | `P2` | `OPEN` | Collab WebSocket accepts legacy HS256 JWTs even when the legacy auth path is disabled | `backend/app/api/ws_routes.py:263-282, backend/app/middleware/auth_middleware.py:108,154-163` |
| R1-088 | `P3` | `OPEN` | WebSocket job-ownership check fails open on Redis errors and missing metadata | `backend/app/api/ws_routes.py:184-200 vs backend/app/api/job_routes.py:718-726` |

### be-api
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-089 | `P1` | `OPEN` | Anonymous share links always return a presigned URL for a MinIO object that is never created — anonymous sharing is 100% broken | `backend/app/api/routes.py:1158-1183, backend/app/services/storage_service.py:79-86, backend/app/api/resume_rou` |
| R1-090 | `P1` | `OPEN` | Invited resume collaborators cannot load the resume — every REST resume endpoint is owner-only, so the collab editor 404s | `backend/app/api/resume_routes.py:768-786, backend/app/api/resume_routes.py:533-545, backend/app/api/ws_routes.` |
| R1-091 | `P1` | `OPEN` | Collaborator `role` (viewer / commenter) is stored and validated but never enforced — read-only collaborators get full write access | `backend/app/api/ws_routes.py:300-320, backend/app/services/collab_manager.py:205-260, backend/app/api/resume_r` |
| R1-092 | `P1` | `OPEN` | `Compilation.ats_score` does not exist on the model — the weekly digest email task always fails and is silently swallowed | `backend/app/workers/email_worker.py:163, backend/app/database/models.py:240-263, backend/app/core/celery_app.p` |
| R1-093 | `P2` | `OPEN` | `dropbox_sync_enabled` is missing from `ResumeResponse`, so the editor's Dropbox sync state is always false after reload | `backend/app/api/resume_routes.py:70-95 (ResumeResponse) and 138-165 (_resume_response_from_obj), backend/app/d` |
| R1-094 | `P2` | `OPEN` | `GET /resumes/export/bulk` exports archived resumes despite claiming otherwise, and issues one extra query per resume in pdf mode | `backend/app/api/resume_routes.py:1948-1968, 1999-2022` |
| R1-095 | `P3` | `OPEN` | `WorkspaceMember.role` (editor vs viewer) is validated on input but never checked by any handler | `backend/app/api/workspace_routes.py:21 (VALID_ROLES), 116-133, 431-680` |

### authz
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-096 | `P1` | `OPEN` | Anonymous share links are broken by construction and fall back to serving the UNREDACTED resume PDF | `backend/app/api/routes.py:1155-1195, backend/app/api/routes.py:1197-1258, backend/app/services/storage_service` |
| R1-097 | `P1` | `OPEN` | POST /optimize and POST /optimize-and-compile are completely unauthenticated LLM endpoints on the platform API key | `backend/app/api/routes.py:536-570, backend/app/api/routes.py:572-606` |
| R1-098 | `P1` | `OPEN` | Collaboration WebSocket ignores the collaborator role — "viewer"/"commenter" get full write access to the document | `backend/app/api/ws_routes.py:284-338, backend/app/services/collab_manager.py:205-260, backend/app/api/resume_r` |
| R1-099 | `P2` | `OPEN` | Collab WebSocket accepts legacy HS256 JWTs, bypassing the LEGACY_JWT_ENABLED kill switch that the REST path enforces | `backend/app/api/ws_routes.py:269-275, backend/app/middleware/auth_middleware.py:150-158` |
| R1-100 | `P2` | `OPEN` | Public portfolio exposes every non-archived resume of the user, with no per-resume visibility flag | `backend/app/api/portfolio_routes.py:257-292, backend/app/database/models.py:56-59` |

### db
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-101 | `P1` | `OPEN` | `alembic revision --autogenerate` generates a migration that DROPS the Better Auth session/account/verification tables | `backend/alembic/env.py:37 (`target_metadata = Base.metadata`, no include_object filter); backend/alembic/versi` |
| R1-102 | `P2` | `OPEN` | Downgrade path 0034→0029 is impossible: 0032's downgrade drops two indexes owned by 0030 | `backend/alembic/versions/0032_session_and_performance_indexes.py:19-22,35-36; backend/alembic/versions/0030_ad` |
| R1-103 | `P2` | `OPEN` | pgvector extension and HNSW index on resumes.content_embedding are never used by any query | `backend/alembic/versions/0002_ats_vectors_and_deep_analysis.py:21-46; backend/app/database/models.py:181; back` |
| R1-104 | `P2` | `OPEN` | Snippet install/upvote counters: lost-update race plus unhandled composite-PK IntegrityError → HTTP 500 | `backend/app/api/snippet_routes.py:264-273,289-298,313-328; backend/app/database/models.py:846,858 (PrimaryKeyC` |
| R1-105 | `P3` | `OPEN` | Models declare index=True on FK columns that no migration ever created; three FK columns have no usable index | `backend/app/database/models.py:723, 805, 699-704; backend/alembic/versions/0017_add_recruiter_notes.py:24-25; ` |
| R1-106 | `P3` | `OPEN` | Redundant duplicate index on session.token, plus a stale TODO claiming the index is missing | `backend/alembic/versions/0032_session_and_performance_indexes.py:19; backend/alembic/versions/0001_initial_com` |

### fe-quality
| ID | Pri | Status | Issue | Location |
|---|---|---|---|---|
| R1-107 | `P1` | `OPEN` | No error boundary anywhere in the app — any render throw is a blank white page | `frontend/src/components/ErrorBoundary.tsx:16; frontend/src/app/layout.tsx:34-60` |
| R1-108 | `P1` | `OPEN` | wsClient.setToken ignores the CONNECTING state, so the job WebSocket can open anonymously and every subscribe is silently rejected | `frontend/src/lib/ws-client.ts:76-82; frontend/src/components/AuthSync.tsx:20-28; frontend/src/hooks/useJobStre` |
| R1-109 | `P1` | `OPEN` | The documented REST polling fallback for job status is unreachable by construction, and the main editor has no fallback at all | `frontend/src/hooks/useJobStatus.ts:8,115,140-147; frontend/src/hooks/useJobStream.reducer.ts:53 (`status: 'idl` |
| R1-110 | `P1` | `OPEN` | Offline drafts are write-only: saved drafts are never loaded back, and reloading while offline kicks the user out of the editor | `frontend/src/lib/offline-drafts.ts:47-51 (`getDraft`); frontend/src/app/workspace/[resumeId]/edit/page.tsx:997` |
| R1-111 | `P1` | `OPEN` | Workspace dashboard swallows all load errors in production and renders the empty state instead | `frontend/src/app/workspace/page.tsx:149-171, 766-777` |
| R1-112 | `P2` | `OPEN` | handleSave swallows backend validation errors, and the title input has no length/emptiness constraint, so the whole document silently fails to save | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1364-1375, 1812-1818; backend/app/api/resume_routes.py:60-` |
| R1-113 | `P2` | `OPEN` | Offline save and offline compile-queue paths have unguarded awaits — IndexedDB failure is a silent unhandled rejection | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1347-1362, 1379-1384, 917-946` |
| R1-114 | `P2` | `OPEN` | Deleting all editor content unmounts Monaco and leaves editorRef pointing at a disposed editor | `frontend/src/components/LaTeXEditor.tsx:1538-1560, 764-770, 415-417` |
| R1-115 | `P2` | `OPEN` | JobQueue job-type labels and the type filter are dead — the API shim never populates job.metadata | `frontend/src/components/JobQueue.tsx:116,247,251; frontend/src/lib/job-api-client.ts:207-218` |
| R1-116 | `P2` | `OPEN` | JobQueue system-health footer renders literal "undefined" because /jobs/health returns none of the expected fields | `frontend/src/components/JobQueue.tsx:298,428-429; frontend/src/lib/api-client.ts:1343-1348; backend/app/api/jo` |
| R1-117 | `P2` | `OPEN` | WYSIWYG mode is persisted to localStorage but the parsed document is not, leaving the editor stuck on "Parsing…" after reload | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:874-879, 1324-1340, 2254-2264` |
| R1-118 | `P2` | `OPEN` | A previously-rendered PDF is destroyed as soon as a new job starts, so a failed compile leaves the user with no preview | `frontend/src/app/workspace/[resumeId]/edit/page.tsx:1122-1133` |
| R1-119 | `P2` | `OPEN` | Two download paths revoke the blob URL synchronously after click, contradicting the fix already applied in ExportDropdown | `frontend/src/app/workspace/page.tsx:197-205; frontend/src/app/workspace/[resumeId]/edit/page.tsx:1503-1509; fr` |

---

## Refuted — do not re-file

Claims an independent verifier disproved. Recorded so they don't get re-raised.

**Round 1:**

- [fe-routes] Integration OAuth "Connect" buttons will 401 in production (top-level navigation to the API origin carries no credentials)
- [fe-routes] White-label tenant branding can never resolve — the frontend never sends X-Tenant-Slug and the backend reads the API request's Hos
- [fe-routes] Dead HelpCenter/Header components ship four links to routes that do not exist
- [fe-routes] Two shipped features are documented/labelled as working but are stubs: tenant domain verification and portfolio contact form
- [authz] Collaborator invite accepts an arbitrary unvalidated role string
- [workers] Workers publish terminal job.failed before retrying, and the frontend reducer permanently pins the UI to "failed" even when the re
- [db] 0008's idempotency guard is column-level incomplete, and 0009's downgrade drops a table it may not have created
- [security] Compile timeout is only checked between pdflatex output lines, so a silent TeX loop is never killed by the app
- [latex-pipeline] `extra_packages` is stored unvalidated and injected into the .tex after the LaTeX security validation has already run, defeating t
- [latex-pipeline] WebSocket subscribe sends no `last_event_id`, so events published before/while subscribing are dropped and the editor has no REST 
- [infra] k8s passes GOOGLE_API_KEY but config.py reads GEMINI_API_KEY — the Gemini provider is silently unconfigured
- [fe-quality] The advanced editor has no auto-save and no unsaved-changes guard — closing the tab or clicking a nav link discards all work
- [fe-quality] localStorage side effects inside setState updaters and useState initializers can throw during render
- [fe-quality] wsClient subscriptions are not reference-counted, so one unmount can silently kill another component's event stream

**Round 2:**

- [entitlements] Three LLM-spending ai_routes endpoints were skipped by the enforcement pass; their only brake is a fail-open per-minute meter
- [entitlements] Every layer of the entitlement stack fails open simultaneously, so one Redis/DB blip disables all gating including kill-switches
- [entitlements] /jobs/batch multiplies spend 10x per call and is gated only by a boolean that is seeded on for the free plan
- [admin-plane] The 'support' role is a stub: it is assignable in the admin UI and silently grants a full entitlement bypass, while require_role (
- [admin-plane] Migration 0035 downgrade deletes feature_flags rows it never inserted, contradicting its own comment
- [auth-completion] Timing-based user enumeration on /request-password-reset and /send-verification-email; probed email logged at error level
- [auth-completion] Resend delivery failures are swallowed and reported to the user as success
- [auth-completion] Verify-email banner dismissal is browser-global, permanent, and not scoped to the user
- [tui-core] Ctrl+C mid-job orphans the server-side job — no cancel frame or DELETE is sent, and the WS client has no cancel support at all
- [tui-core] ApiClient retries non-idempotent POSTs on timeout/network error, so a slow /jobs/submit can queue up to 3 duplicate jobs and consu
- [tui-ux] Log streaming copies the entire line buffer into the store on every line — quadratic allocation and unbounded retention
- [integrations] A single GitHub OAuth app (GITHUB_CLIENT_ID/SECRET) is used by two flows with different callback URLs — one of them must fail with
- [integrations] GitHub repo_name is stored and interpolated into GitHub API paths with no validation
- [multiuser] Any authenticated user can create a white-label tenant and claim an arbitrary unverified custom domain; domain verification is a s
- [multiuser] Tenant middleware provides zero isolation and leaks any tenant's record to unauthenticated callers via X-Tenant-Slug
- [multiuser] Tenant negative cache never hits: every HTTP request runs a fresh DB session + SELECT for tenant resolution
- [fe-a11y-mobile] Cached authenticated /resumes responses are never purged on sign-out, defeating the sign-out data-purge added in GlobalHeader

---

## Known-broken adjacent issue (not yet fixed)

- **`embed_resume_task` reuses the module-global async engine across `asyncio.run()` loops.** Confirmed and
  reproduced during the SIGSEGV investigation: `Task ... got Future ... attached to a different loop` and
  `RuntimeError: Event loop is closed` inside `asyncpg/protocol.pyx`. It is a *different* bug from LX-013 and was
  deliberately left alone to keep that change single-purpose. Fix shape: give `_async_embed_resume` its own
  short-lived engine, as `_update_compilation_record` now does. (Already catalogued as R2 `workers` finding.)
- **Crash-loop wreckage:** ~10 `compilations` rows created during the SIGSEGV window are still stuck at
  `processing`. They are historical artifacts, not a live defect; reconcile or delete them.


## Fix-pass record

Four waves, each implementation adversarially reviewed by an independent agent before being accepted.
The review rounds caught real regressions the implementers had missed and self-reported as verified —
including one that would have **bricked all production LaTeX compilation** (LX-015) and one that could
have **deleted every live PDF** (LX-018). Two of those were introduced *by* the fixes.

| Wave | Scope | Reviewer verdict |
|---|---|---|
| 1 | Job artifacts, `Compilation` reconciliation, CORS ordering, analytics `date_trunc`, auth-token race, BYOK proxy, TUI WS auth | 6 majors raised → remediated in 1b |
| 2 | Quotas, unauth LLM endpoints, LaTeX sandbox, billing, collab, auth completion, prod deploy | 22 blockers/majors raised → remediated in 2b |
| final review | Whole diff re-reviewed (the wave-2b review round died on transient API errors) | 3 blockers + 17 majors → remediated in wave 3 |
| 3 | All 20 findings | 19 fixed, 1 rejected with evidence; 0 outstanding |

**Suites after the fix pass:** backend **2489 passed, exit 0**, `ruff` clean · frontend **467 passed**, `tsc`
clean · TUI **121 passed** (was 94), typecheck + build clean.

**Independently re-verified by me against the live stack** (not agent self-reports): combined-job
`/download` + `/logs` + `/synctex` all 200 with a real 41 KB PDF · `Compilation` row `completed` with
`pdf_path` · anonymous `GET /share/{token}` → 200 with a working presigned URL · free tier 10 compiles/day
then a 402 carrying the correct window and reset date · 3 optimizations/month · `/jobs/compile-watermarked`
now metered (402) and requiring a fingerprint when anonymous (400) · anonymous `POST /optimize` → 401 ·
`/analytics/me` → 200 · `/ats/score` job id pollable · 429 carries CORS with `Retry-After` exposed ·
30 password-reset requests with 30 *different* spoofed `X-Forwarded-For` values → only 5 allowed ·
`docker compose -f docker-compose.prod.yml --env-file .env.production config` renders with the frontend
carrying `BETTER_AUTH_SECRET`, `DATABASE_URL`, `BACKEND_URL`, `BETTER_AUTH_URL`.

### Test-environment side effects (not product defects)

- `audit.alice@example.com`'s password was changed by an agent walking a real password-reset round trip;
  verification switched to `verify.carol@example.com` / `VerifyPassw0rd!carol`. Reset alice if you want the
  original fixture back.
- ~10 `compilations` rows are stuck at `processing` from the LX-013 SIGSEGV crash-loop window, plus more
  from before the reconciliation fix. Historical wreckage, not a live defect.
- Two of my own "FAIL" results during verification turned out to be harness bugs (a response body truncated
  mid-JSON, and a `flush_quota()` that ran before the assertion it was meant to set up). Both re-tested clean.
  Chasing the first one is what surfaced LX-019, which is a genuine bug.


## Coverage — what is still NOT tested

Stated plainly so the gaps are tracked rather than assumed covered:

- **Load/soak and concurrency at scale** — only a 12-request burst was run. LX-012 hints at something here.
- **Razorpay against a real sandbox** — all billing findings are static; no live webhook/checkout was exercised.
- **OAuth against real providers** — GitHub/Dropbox/Zotero/Mendeley flows are static-only; no live consent round-trip.
- **Production/k8s deploy** — every §infra finding is static. Nothing was deployed.
- **Interactive TUI rendering** — driven headlessly and by reading source; not driven through a real PTY, so the
  `<Static>` and overlay findings are code-level, not observed.
- **Screen readers** — a11y findings are code-level; no VoiceOver/NVDA pass.
- **Real mobile hardware** — viewport math only, no device testing.
- **Email delivery** — Resend was never configured; the console-fallback path is what ran.
- **pgvector semantic search quality** — noted as unused by any query, not evaluated.

---

## Artifacts
| File | Contents |
|---|---|
| `docs/audit-artifacts/findings_sorted.json` | Round 1 — 119 findings with evidence, repro, fix, severity corrections |
| `docs/audit-artifacts/audit2_result.json` | Round 2 — 64 findings, same shape, plus per-domain maps |
| `docs/audit-artifacts/reverify.json` | Re-verification probe results against current `main` |
| `docs/audit-artifacts/probe_unauth.json` | All 278 API operations probed unauthenticated |
| `docs/audit-artifacts/idor_results.json` | 58-request cross-tenant authorization matrix (zero leaks) |
| `docs/AUDIT-2026-07-25.md` | Round 1 narrative report |
| `frontend/e2e/audit-*.spec.ts` | Three diagnostic Playwright specs (log, don't assert) |

## What is confirmed working

Worth recording so it isn't re-litigated:

- **Authorization: zero IDORs** in 58 cross-tenant attacks — 403/404 throughout. Two `200 []` responses
  turned out to filter by `user_id` correctly. Round 2 found no classic IDOR either.
- **Plain compile pipeline** — WS subscribe → replay → progress → live `log.line` → `job.pdf_extracted` →
  `job.completed` with `page_count`, real PDF delivered. Event names/fields match publisher↔reducer.
- **DB schema** — 41 revisions, `upgrade head` green, all merge points resolve, `--autogenerate` shows no
  column drift, zero FKs on `NO ACTION`.
- **Admin RBAC** — all seven `/admin/*` routes carry `Depends(require_admin)`; all 401 unauthenticated. No
  privilege-escalation path found; `users.role` is not mass-assignable.
- **Password-reset tokens** — DB-backed, ~143 bits, single-use, 1 h expiry, exact-identifier lookup.
- **Open-redirect** — every `callbackURL`/`redirectTo` passes Better Auth's `originCheck`.
- **TUI hygiene** — typecheck clean, build clean, 94/94 tests pass; config written `0600` with `chmod`.


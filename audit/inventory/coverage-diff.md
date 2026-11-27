# Independent coverage inventory and diff — 2026-11-27

**Auditor role:** independent coverage auditor (read-only)
**Repository:** `C:\Users\Sansk\Projects\Latexy`, branch `audit/production-2026-11-27`
**Source commit:** `f9e34fa6a5212189ea70977d4c68c1ab2e3afed6` (parent `d2cbc51a`, the deployed frontend SHA); no `backend/` or `frontend/` change between `d2cbc51a` and this checkout (`git diff --stat d2cbc51a..HEAD` touches `audit/` only).
**Live backend:** `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
**Live probes:** 2026-11-27 10:41–11:12 UTC. All probes were GET/HEAD only; no mutations, no test identities, no load.

## Method

1. Imported `app.main:app` from the checkout, called `app.openapi()` to force FastAPI's lazy `_IncludedRouter` resolution, then walked `app.routes` recursively (including each `_IncludedRouter.include_context.prefix`) to recover the **registration-order, pre-schema** route list. This is the only way to see `include_in_schema=False` routes and duplicate registrations.
2. Independently parsed every `backend/app/api/**/*.py` with `ast` to confirm which modules define route decorators and which never register.
3. Diffed the runtime route list against `audit/inventory/openapi-source.json` and `audit/inventory/http.csv` by `(method, path)`.
4. Parsed `backend/modal_app.py` and `backend/app/workers/*.py` with `ast` for every `@app.function` / `@celery_app.task` / beat entry; mapped worker reachability from `.spawn()` call sites and `modal_app.py` schedules.
5. Recomputed App Router pages (`frontend/src/app/**/page.tsx`), template files (`backend/app/data/templates/**/*.tex`, cross-checked against live `GET /templates/?limit=200`), and the capability catalog (`backend/app/core/capability_catalog.json` + `feature_registry.py`).
6. Static frontend reachability: extracted every quoted path literal in `frontend/src` (excluding `__tests__`), normalized template parameters, matched to backend paths; counted `apiClient.*` method call sites outside `api-client.ts`.

**Limits.** The inventory is static for WS/worker runtime behaviour. No WS frames were sent, no admin login was available (`GET /admin/entitlements` → 401), and no Modal/Celery runtime was inspected beyond live health/queue-depth output. Those are recorded as blocked, not passed.

---

## 1. Headline counts

| Surface | Recomputed from source | Live / canonical | Verdict |
|---|---|---|---|
| HTTP operations registered in code | **674** | — | — |
| HTTP paths registered in code | **588** | — | — |
| OpenAPI operations (`openapi-source.json`) | **636** | live `/openapi.json` = 404 | source is canonical |
| OpenAPI paths | **558** | live `/openapi.json` = 404 | source is canonical |
| Operations absent from OpenAPI | **38** | — | hidden from schema |
| OpenAPI operations absent from code | **0** | — | no orphan schema |
| `audit/inventory/http.csv` rows | **636** | equals OpenAPI exactly | 38 code ops missing |
| Exact duplicate `(method, path)` registrations | **0** | — | none |
| Handlers registered at >1 path | **35** | 82 path registrations | 47 duplicate paths |
| Multi-path operations | **84** | — | 27 hidden, 57 visible |
| WebSocket paths | **2** (`/ws/jobs`, `/ws/collab/{resume_id}`) | — | both in code |
| WS ticket endpoint | **1** (`POST /ws/ticket`) | — | in OpenAPI/http.csv |
| Jobs event types | **18 emitted** (17 schema + `job.retrying`); 18 schema types include `sys.error`, which is never emitted | — | — |
| Modal functions | **36** (19 job, 5 scheduled, 5 spawned runners, 6 operations, 1 ASGI) | — | — |
| Celery tasks | **30** (28 in workers + `debug_task`, `sample_queue_depths`) | — | — |
| Celery logical queues | **7** (`latex, llm, email, cleanup, ats, combined`, latent default `celery`) | `/jobs/health` reports the 6 configured queues, depth 0 | queues inert on Modal |
| Celery beat entries | **11** | — | beat not deployed |
| App Router pages | **44** | 44 `page.tsx` | matches prompt |
| Templates | **61** source `.tex` | **61** live `GET /templates/` | prompt "~63" stale |
| Audited capability IDs | **129** | live export 401 | 129 claim verified |
| Capability registry entries | **165** (31 coarse + 129 product + 5 subfeatures) | — | docs say 160 |
| Gateable registry keys | **149** (31 coarse + 113 product + 5 sub) | — | docs say 144 |

### Live evidence

| Probe | Observed |
|---|---|
| `GET /health` | 200 `healthy`; `commit_sha=ee1a405de6058e814c3a6f5ffba5fe3630576421`; database/redis/storage ok |
| `GET /readyz` | 200 `ready` (database/redis/redis_cache ok) |
| `GET /jobs/health` | 200 healthy; depths `cleanup=0,email=0,combined=0,llm=0,latex=0,ats=0` |
| `GET /openapi.json`, `/api/openapi.json`, `/docs`, `/api/docs` | **404** (all four) |
| `GET /templates/?limit=200` | 200; **61** rows across 14 categories |
| `GET /templates/categories` | 200; sums to 61 |
| `GET /admin/entitlements` | **401** — live capability export blocked without admin auth |

---

## 2. HTTP diff

### 2.1 Three-way diff

`openapi-source.json` and `http.csv` are identical: all **636** operations and **558** paths match by method/path, with 0 rows in either direction. `http.csv` adds nothing beyond the schema and is **not** a complete inventory: it omits all 38 schema-hidden operations. All 636 `http.csv` rows are still `status=TODO`; none carries an observed test disposition from this or the lead inventory.

| Set | Count | Evidence |
|---|---|---|
| Code operations | 674 | `audit/inventory/http-coverage-audit.csv` |
| Schema operations | 636 | `audit/inventory/openapi-source.json`; `http.csv` |
| Code-only (missing from schema and `http.csv`) | **38** | table 2.2 |
| Schema-only (no handler) | **0** | verified by `(method,path)` set diff |
| Duplicate exact `(method,path)` | **0** | verified |
| Duplicate OpenAPI `operationId` | **0** | verified |

### 2.2 All 38 operations absent from OpenAPI and `http.csv`

These are `include_in_schema=False`; 35 are admin endpoints (including CSV exports, legacy aliases, incidents, saved segments, dunning) and 3 are infrastructure probes.

| Method | Path | Handler (file:line) |
|---|---|---|
| GET | `/admin/access-review/export.csv` | `admin_access_review_routes:93` |
| GET | `/admin/analytics/ats-scores` | `admin_ats_score_routes:70` |
| GET | `/admin/analytics/career-feature-adoption` | `admin_career_adoption_routes:67` |
| GET | `/admin/analytics/dunning-recovery` | `admin_dunning_routes:52` |
| GET | `/admin/analytics/optimization-acceptance/export.csv` | `admin_optimization_acceptance_routes:88` |
| GET | `/admin/analytics/paths/export.csv` | `admin_path_analysis_routes:94` |
| GET | `/admin/billing/coupon-student-performance` | `admin_revenue_lifecycle_routes:28` |
| GET | `/admin/billing/dunning` | `admin_dunning_routes:52` |
| GET | `/admin/billing/dunning/recovery` | `admin_dunning_routes:52` |
| GET | `/admin/content-library/adoption/export.csv` | `admin_content_library_routes:92` |
| GET | `/admin/dunning` | `admin_dunning_routes:52` |
| GET | `/admin/dunning/recovery` | `admin_dunning_routes:52` |
| GET | `/admin/incidents` | `admin_incident_routes:133` |
| POST | `/admin/incidents` | `admin_incident_routes:210` |
| GET | `/admin/incidents/timeline` | `admin_incident_routes:166` |
| DELETE | `/admin/incidents/{incident_id}` | `admin_incident_routes:345` |
| GET | `/admin/incidents/{incident_id}` | `admin_incident_routes:197` |
| PATCH | `/admin/incidents/{incident_id}` | `admin_incident_routes:246` |
| PUT | `/admin/incidents/{incident_id}` | `admin_incident_routes:246` |
| POST | `/admin/incidents/{incident_id}/open` | `admin_incident_routes:316` |
| POST | `/admin/incidents/{incident_id}/reopen` | `admin_incident_routes:316` |
| POST | `/admin/incidents/{incident_id}/resolve` | `admin_incident_routes:291` |
| PUT | `/admin/operations/incidents/{incident_id}` | `admin_incident_routes:246` |
| POST | `/admin/operations/incidents/{incident_id}/open` | `admin_incident_routes:316` |
| GET | `/admin/referrals/summary/export.csv` | `admin_referral_analytics_routes:80` |
| GET | `/admin/saved-segments` | `admin_saved_views_routes:295` |
| POST | `/admin/saved-segments` | `admin_saved_views_routes:312` |
| GET | `/admin/saved-segments/fields` | `admin_saved_views_routes:272` |
| POST | `/admin/saved-segments/preview` | `admin_saved_views_routes:280` |
| DELETE | `/admin/saved-segments/{segment_id}` | `admin_saved_views_routes:393` |
| GET | `/admin/saved-segments/{segment_id}` | `admin_saved_views_routes:341` |
| PATCH | `/admin/saved-segments/{segment_id}` | `admin_saved_views_routes:371` |
| GET | `/admin/saved-segments/{segment_id}/preview` | `admin_saved_views_routes:353` |
| GET | `/admin/subscriptions/dunning` | `admin_dunning_routes:52` |
| GET | `/admin/templates/performance/export.csv` | `admin_template_performance_routes:84` |
| GET | `/livez` | `routes:697` |
| GET | `/metrics` | `routes:743` |
| GET | `/readyz` | `routes:703` |

Breakdown: **25 GET, 7 POST, 2 DELETE, 2 PATCH, 2 PUT**; **31 unique paths**, **13 modules**. Auth: 35 `admin`, 3 `public-infra`.

**Why it matters.** The canonical live schema is disabled (`backend/app/main.py:166-178`), and even the source-generated schema hides these 38 operations. Any auditor who enumerates only OpenAPI/live docs will miss 100% of the hidden admin exports, the legacy incident/saved-segment/dunning aliases, and `/livez`, `/readyz`, `/metrics`. The `http.csv` baseline therefore covers 636/674 = **94.4%** of registered operations.

### 2.3 Duplicate route registrations (aliases)

No exact duplicate `(method,path)` exists, no handler is listed twice for the same method/path, and no duplicate `operationId` exists. However **35 handlers are registered at 2–7 paths**, producing **84 operations from 82 distinct path registrations** (47 paths are duplicates/aliases). 18 of those handlers have at least one hidden alias.

| Handler | Ops | Paths (hidden marked) |
|---|---|---|
| `admin_dunning_routes.get_admin_dunning_recovery` | 7 | GET /admin/analytics/dunning-recovery (hidden); GET /admin/billing/dunning (hidden); GET /admin/billing/dunning-recovery; GET /admin/billing/dunning/recovery (hidden); GET /admin/dunning (hidden); GET /admin/dunning/recovery (hidden); GET /admin/subscriptions/dunning (hidden) |
| `admin_incident_routes.reopen_admin_incident` | 4 | POST /admin/incidents/{incident_id}/open (hidden); POST /admin/incidents/{incident_id}/reopen (hidden); POST /admin/operations/incidents/{incident_id}/open (hidden); POST /admin/operations/incidents/{incident_id}/reopen |
| `admin_incident_routes.update_admin_incident` | 4 | PATCH /admin/incidents/{incident_id} (hidden); PUT /admin/incidents/{incident_id} (hidden); PATCH /admin/operations/incidents/{incident_id}; PUT /admin/operations/incidents/{incident_id} (hidden) |
| `admin_stuck_job_routes.cancel_admin_stuck_job` | 3 | POST /admin/jobs/{job_id}/cancel; POST /admin/operations/jobs/{job_id}/cancel; POST /admin/operations/stuck-jobs/{job_id}/cancel |
| `admin_stuck_job_routes.fence_admin_stuck_job` | 3 | POST /admin/jobs/{job_id}/fence; POST /admin/operations/jobs/{job_id}/fence; POST /admin/operations/stuck-jobs/{job_id}/fence |
| `admin_stuck_job_routes.list_admin_stuck_jobs` | 3 | GET /admin/jobs/stuck; GET /admin/operations/jobs/stuck; GET /admin/operations/stuck-jobs |
| `admin_stuck_job_routes.requeue_admin_stuck_job` | 3 | POST /admin/jobs/{job_id}/requeue; POST /admin/operations/jobs/{job_id}/requeue; POST /admin/operations/stuck-jobs/{job_id}/requeue |
| `admin_stuck_job_routes.retry_admin_stuck_job` | 3 | POST /admin/jobs/{job_id}/retry; POST /admin/operations/jobs/{job_id}/retry; POST /admin/operations/stuck-jobs/{job_id}/retry |
| `admin_incident_routes.create_admin_incident` | 2 | POST /admin/incidents (hidden); POST /admin/operations/incidents |
| `admin_incident_routes.delete_admin_incident` | 2 | DELETE /admin/incidents/{incident_id} (hidden); DELETE /admin/operations/incidents/{incident_id} |
| `admin_incident_routes.get_admin_incident` | 2 | GET /admin/incidents/{incident_id} (hidden); GET /admin/operations/incidents/{incident_id} |
| `admin_incident_routes.get_admin_incident_timeline` | 2 | GET /admin/incidents/timeline (hidden); GET /admin/operations/incidents/timeline |
| `admin_incident_routes.list_admin_incidents` | 2 | GET /admin/incidents (hidden); GET /admin/operations/incidents |
| `admin_incident_routes.resolve_admin_incident` | 2 | POST /admin/incidents/{incident_id}/resolve (hidden); POST /admin/operations/incidents/{incident_id}/resolve |
| `admin_revenue_lifecycle_routes.get_coupon_student_performance` | 2 | GET /admin/billing/coupon-student-performance (hidden); GET /admin/revenue/coupon-student-performance |
| `admin_saved_views_routes.create_segment` | 2 | POST /admin/saved-segments (hidden); POST /admin/segments |
| `admin_saved_views_routes.delete_segment` | 2 | DELETE /admin/saved-segments/{segment_id} (hidden); DELETE /admin/segments/{segment_id} |
| `admin_saved_views_routes.get_segment` | 2 | GET /admin/saved-segments/{segment_id} (hidden); GET /admin/segments/{segment_id} |
| `admin_saved_views_routes.get_segment_fields` | 2 | GET /admin/saved-segments/fields (hidden); GET /admin/segments/fields |
| `admin_saved_views_routes.list_segments` | 2 | GET /admin/saved-segments (hidden); GET /admin/segments |
| `admin_saved_views_routes.preview_saved_segment` | 2 | GET /admin/saved-segments/{segment_id}/preview (hidden); GET /admin/segments/{segment_id}/preview |
| `admin_saved_views_routes.preview_segment_definition` | 2 | POST /admin/saved-segments/preview (hidden); POST /admin/segments/preview |
| `admin_saved_views_routes.update_segment` | 2 | PATCH /admin/saved-segments/{segment_id} (hidden); PATCH /admin/segments/{segment_id} |
| `email_webhook_routes.resend_email_webhook` | 2 | POST /email/webhooks/resend; POST /webhooks/resend |
| `export_routes.export_canva` | 2 | GET /export/builder/v1/{resume_id}/canva; GET /export/{resume_id}/canva |
| `export_routes.export_figma` | 2 | GET /export/builder/v1/{resume_id}/figma; GET /export/{resume_id}/figma |
| `export_routes.export_resume` | 2 | GET /export/builder/v1/{resume_id}/{fmt}; GET /export/{resume_id}/{fmt} |
| `resume_routes.create_builder_resume` | 2 | POST /resumes/builder; POST /resumes/builder/v1 |
| `resume_routes.get_builder_resume` | 2 | GET /resumes/{resume_id}/builder; GET /resumes/{resume_id}/builder/v1 |
| `resume_routes.seed_builder_from_upload` | 2 | POST /resumes/builder/seed-upload; POST /resumes/builder/v1/seed-upload |
| `routes.cancel_subscription` | 2 | POST /billing/dodo/subscription/cancel; POST /subscription/cancel |
| `routes.create_subscription` | 2 | POST /billing/dodo/subscription/create; POST /subscription/create |
| `routes.dodo_webhook` | 2 | POST /billing/dodo/webhook; POST /billing/webhook |
| `routes.reconcile_subscription` | 2 | POST /billing/dodo/subscription/reconcile; POST /subscription/reconcile |
| `routes.verify_student_subscription` | 2 | GET /billing/dodo/subscription/student/verify/{token}; GET /subscription/student/verify/{token} |

Most are deliberate migration compatibility (`/subscription/*` → `/billing/dodo/subscription/*`, `/admin/saved-segments` → `/admin/segments`, legacy `/admin/incidents` → `/admin/operations/incidents`). The call-site inventory shows the frontend uses the newer visible aliases; the legacy hidden aliases have no first-party UI caller. They still accept live traffic and should be treated as supported surface until removed.

One code-level `operationId` collision exists because FastAPI assigns the same `unique_id` to stacked decorators: `get_admin_dunning_recovery_admin_billing_dunning_recovery_get` is shared by the visible `GET /admin/billing/dunning-recovery` and the hidden `GET /admin/billing/dunning/recovery` (`backend/app/api/admin_dunning_routes.py:51-57`). It does not collide in the OpenAPI document because the hidden alias is excluded; it does mean any generated client that keys on operation id would see one endpoint, not two.

### 2.4 Route-order / shadowing check

No concrete route is shadowed by an earlier dynamic route. Starlette evaluates routes in registration order; a full pairwise check of every concrete path against all earlier parameterized paths found **0 shadowed routes**. No static path like `/templates/categories` is captured by `/templates/{template_id}`.

### 2.5 `http.csv` auth-label quality

`http.csv` auth labels are coarse and disagree with code-derived dependencies on most rows. They should not be used as an enforcement oracle.

| `http.csv` label | Rows |
|---|---|
| `user-or-optional` | 372 |
| `admin` | 202 |
| `public/provider` | 26 |
| `tenant-owner/member` | 19 |
| `api-key/user` | 10 |
| `user` | 7 |

Code-derived guesses in `http-coverage-audit.csv` are `user=292`, `admin=249`, `optional-user=82`, `public=24`, `public-callback=9`, `api_key=5`, `public-token=5`, `public-infra=5`, `anonymous=3`. Notable understatements in `http.csv`:

* 12 operations labeled `user-or-optional` actually use `require_admin_actor`/`require_admin` (analytics admin overview, conversion funnel, dashboard, system, user analytics, BYOK system health, `/jobs/system/cleanup`, template create/update/delete/activate/deactivate). Example: `/templates` POST at `backend/app/api/template_routes.py:461` requires admin.
* 5 operations labeled `api-key/user` are ordinary user routes; 5 are genuine developer-key routes.
* 19 tenant operations are labeled `tenant-owner/member`, but the code expresses them as `user` + tenant-role checks inside the handler; they are not a distinct auth class at the HTTP layer.

Auth in `http-coverage-audit.csv` is explicitly a **guess** from `Depends(...)` and route-level dependencies (`require_admin*`, `get_current_user_required`, `get_current_user_optional`, `require_feature`, `require_developer_operation`), plus path-based classification for public callbacks/assets. Handlers may add ACL checks the dependency graph does not show.

---

## 3. WebSocket inventory diff

**Files:** `audit/inventory/ws-coverage-audit.csv` (49 rows).

| WS surface | Path | Auth | Client message types | Server message types |
|---|---|---|---|---|
| Jobs | `/ws/jobs` | optional single-use `?ticket=`; no ticket allowed for owner-less anonymous jobs; presented-invalid ticket closes 4001 | `subscribe`, `unsubscribe`, `cancel`, `ping` | `subscribed`, `event`, `pong`, `error` + 19 event-type rows (18 emitted + `sys.error`) |
| Collaboration | `/ws/collab/{resume_id}` | **required** purpose-bound `?ticket=`; owner/collaborator ACL; live role re-check per frame | Yjs `SYNC_STEP1`, `SYNC_STEP2`, `MSG_UPDATE`, `MSG_AWARENESS`, `MSG_QUERY_AWARENESS`, `MSG_CHAT` | `SYNC_STEP2` catch-up, awareness relay, chat relay, `MSG_PERMISSION_DENIED` notices, close 4001/4003/4004/4005 |
| Ticket mint | `POST /ws/ticket` (HTTP) | `get_current_user_required` | `{purpose: jobs|collab, resume_id?}` | `{ticket, expires_in}` |

### 3.1 Jobs event types

Present in `AnyEvent` (`backend/app/models/event_schemas.py:209-228`) and emitted: `job.queued`, `job.started`, `job.progress`, `job.completed`, `job.failed`, `job.cancelled`, `artifact.ready`, `context.ready`, `section.ready`, `patch.ready`, `review.ready`, `llm.token`, `llm.complete`, `log.line`, `ats.deep_complete`, `job.pdf_extracted`, `sys.heartbeat` — **17**.

Additional emitted type **not** in the schema union:

* `job.retrying` — published by 13 worker call sites (`backend/app/workers/event_publisher.py:518,552`; e.g. `ats_worker.py`, `cover_letter_worker.py`, `github_import_worker.py`) and consumed by `frontend/src/hooks/useJobStream.ts:36-67` and `frontend/src/__tests__/job-stream-retrying.test.ts`. It is absent from `AnyEvent`, `event-types.ts:7-24`, and `_STATUS_MAP`, so schema-validating consumers will reject or ignore it.

Defined but never emitted:

* `sys.error` — `SystemErrorEvent` at `event_schemas.py:200`; zero producers in `backend/app`. Frontend has a type at `frontend/src/lib/event-types.ts:231` but no emitter.

### 3.2 Persistence / replay

| Surface | Persistence | Replay |
|---|---|---|
| `/ws/jobs` | Redis Stream `latexy:stream:{job_id}` with `maxlen~10000`, TTL 86400 | Yes — `last_event_id` triggers XREAD after that id (`backend/app/core/event_bus.py:10-11,269+`) |
| `/ws/jobs` transient events | `llm.token`, `log.line`, `artifact.ready`, semantic `*.ready`, `sys.heartbeat` bypass job-state updates (`event_publisher.py:462`); token/log are emitted to Pub/Sub + Stream but are not user-readable state | Replayed if in stream |
| `/ws/collab/{resume_id}` updates | Redis list `collab:{resume_id}:updates` (base64, max 500, TTL 24h; `collab_manager.py:991-1004`) | Catch-up on `SYNC_STEP1`, not stream-id replay |
| Collab chat / awareness | **not persisted** | No replay (documented ephemeral) |
| Collab revocation | Redis Pub/Sub `latexy:collab:{resume_id}` with `kind=revoke` (`collab_manager.py:670-679`) | No replay; new connections re-authorize |

### 3.3 WS gaps / observations

* `/ws/jobs` is **not** in `http.csv` or OpenAPI (expected for WebSocket), so `http.csv` undercounts the real-time surface by 2 paths.
* The jobs socket explicitly allows anonymous owner-less trial jobs when no ticket is supplied (`ws_routes.py:177-186`), but rejects a presented invalid ticket. This split is intentional and is covered by `frontend/src/lib/ws-client.ts`.
* `job.retrying` is the only emitted-but-unschema'd event; `sys.error` is the only schema'd-but-unemitted event.
* `_ws_message_counts` is a **process-local** rate-limit map (`ws_routes.py:63,153-166`). With multiple API workers, the 20 msg/s limit is per process, not per user; a client can multiply it by hitting different workers. The collab chat limiter has a Redis-backed path (`collab_manager.py:310-333`), but the jobs socket limiter does not.
* `/ws/jobs` events are persisted by the publisher before fan-out; `_request_cancellation` writes both the stream and the Pub/Sub channel (`ws_routes.py:747-778`), consistent with replay.
* No evidence of duplicate suppression for Pub/Sub redelivery beyond stream id; `event_bus.subscribe` starts Pub/Sub before replay (`event_bus.py:81-136`), which is the correct ordering to avoid a gap, but a frame can be delivered twice if it is both replayed and published during the replay window. No de-dupe by `event_id` was found in the client or server path.

---

## 4. Workers, schedules, queues

**File:** `audit/inventory/workers-coverage-audit.csv` (84 rows).

| Kind | Count | Detail |
|---|---|---|
| Modal job runner | 19 | one per Celery task family dispatched by `.spawn()` |
| Modal scheduled function (`schedule=`) | **5** | hourly cleanup, 30-min temp cleanup, Monday 09:00 digest, 5-min maintenance fan-out, 1-min recovery fan-out |
| Modal scheduled runner (spawned by a schedule) | 5 | health check, tracker notifications, admin alert evaluation, comment-mention recovery, document-email recovery |
| Modal operations function | 6 | `renderer_preflight`, `migrate`, `freeze_redis_recovery`, `handover_redis_recovery`, `billing_preflight`, `sync_templates` |
| Modal ASGI | 1 | `fastapi_app` (`min_containers=1`, `max_inputs=100`) |
| Celery task | 30 | 28 in 13 worker modules (all routed by `task_routes`) + `sample_queue_depths` (beat-routed to cleanup) + unrouted `debug_task` |
| Celery queue | 7 | `latex, llm, email, cleanup, ats, combined`, plus the implicit default `celery` queue reached only by unrouted `debug_task` |
| Celery beat entry | 11 | none executed by Celery beat in production |

### 4.1 Beat → Modal schedule mapping

| Beat entry | Beat cadence | Production path | Verdict |
|---|---|---|---|
| `cleanup-expired-jobs` | 3600 s | `scheduled_cleanup_expired_jobs` hourly | mirrored |
| `cleanup-temp-files` | 1800 s | `scheduled_cleanup_temp_files` 30 min | mirrored |
| `retention-due-previews` | **900 s** | inside hourly cleanup | **4× slower** (15 min → 60 min) |
| `health-check` | 300 s | `run_scheduled_health_check` via 5-min fan-out | mirrored |
| `refresh-daily-metrics` | **600 s** | **none** | **orphaned** |
| `weekly-digest-monday-9am` | Mon 09:00 | `scheduled_weekly_digest` | mirrored |
| `admin-digest-dispatch` | 3600 s | inside hourly cleanup | mirrored |
| `comment-mention-delivery-recovery` | 60 s | `scheduled_comment_mention_recovery` via 1-min fan-out | mirrored |
| `document-email-delivery-recovery` | 60 s | `scheduled_document_email_recovery` via 1-min fan-out | mirrored |
| `tracker-notifications` | 300 s | `scheduled_tracker_notifications` via 5-min fan-out | mirrored |
| `sample-queue-depths` | **20 s** | `sample_queue_depths()` in 1-min recovery | **3× slower**; broker depth is 0 on Modal |

`_DEPLOYMENT_TRAFFIC_HELD` sets every Modal `schedule=None` (`backend/modal_app.py:766,800,848,947,984`), so all periodic work is disabled while a deployment is held. The five-schedule Modal budget is fully consumed (`test_modal_deployment_parity.py:1007-1020`).

### 4.2 Orphan worker: `refresh_daily_metrics_task`

* Defined at `backend/app/workers/cleanup_worker.py:2045-2097`.
* Referenced only from `backend/app/core/celery_app.py:348-352` (`refresh-daily-metrics` beat entry) and tests.
* Celery beat is **not deployed** on Modal (`modal_app.py:751-759` explicitly says beat runs only in docker/k8s/dev; `test_modal_deployment_parity.py:916` waives the entry).
* No `.spawn()`, `.apply()`, `.delay()`, HTTP admin trigger, or Modal schedule invokes it.
* Consequence: the admin daily-metrics rollup never refreshes in production. The admin endpoint falls back to base tables and labels the payload stale (`test_modal_deployment_parity.py:916`), so this is a stale-read optimisation gap, not a total dashboard failure. Severity **P2** because analytics freshness is part of the launch gate.

### 4.3 Broken manual cleanup path

`run_cleanup_task` (`backend/modal_app.py:569-586`) is the only Modal worker runner that does **not** call `_init_worker_redis()`. Both `cleanup_expired_jobs_task` (`cleanup_worker.py:1482-1484`) and `cleanup_temp_files_task` (`cleanup_worker.py:74-76`) publish `job.started` as their first action. `publish_event` requires an initialized worker Redis and raises otherwise (`event_publisher.py:403-415`), so an admin `POST /jobs/system/cleanup` that routes to `run_cleanup_task` aborts before the expired-job reaper and MinIO orphan pruner execute.

The **scheduled** path is safe: `scheduled_cleanup_expired_jobs` and `scheduled_cleanup_temp_files` call `_init_worker_redis()` before `.apply()` (`modal_app.py:780,816`). This is a manual/admin-path defect only. Severity **P2** (admin recovery path silently fails; scheduled sweeps still work).

### 4.4 Worker documentation coverage

Of the 30 named worker/schedule entrypoints in `modal_app.py` (19 runners + 5 schedules + 5 spawned runners + `refresh_daily_metrics_task`), **25 are not named anywhere in `docs/`**. Only `run_latex_task`, `run_orchestrator_task`, `run_llm_task` (`docs/RESUME_ENGINE_ARCHITECTURE.md`), `run_document_conversion_task` (one latency audit), and `run_scheduled_health_check` (one QA publication) appear. None of the `scheduled_*` functions or `refresh_daily_metrics_task` appear, and `docs/LAUNCH_CHECKLIST.md` does not document the periodic fleet. The audit inventory is therefore the first complete worker list.

### 4.5 Queue reality on Modal

The live 6 sampled queues are Celery/Redis concepts. On Modal, job entrypoints execute the Celery task in-process via `.apply()`, and `CELERY_RESULT_BACKEND` is forced to `disabled://` (`backend/app/core/celery_app.py:242-255`). The broker queues exist only for non-Modal deployments. Live `/jobs/health` reports all depths 0, consistent with no Celery worker/beat consuming them. Monitoring these queues in production proves nothing about in-process Modal work; conversely, a Modal worker crash is not visible as queue backlog. `debug_task` is unrouted and would use the implicit default `celery` queue, which is neither in `task_routes` nor `_SAMPLED_QUEUES` (`celery_app.py:288-302,478`); it has no caller.

---

## 5. Frontend surface recomputation

### 5.1 App Router pages: **44**

Exactly **44** `frontend/src/app/**/page.tsx` files, matching the prompt and `docs/FEATURES.md:91`. No route-group parentheses directories change the URL count. Full list is derivable from the 44 files; notable dynamic routes: `/r/[token]`, `/u/[username]`, `/workspace/builder/[resumeId]`, `/workspace/variant/[resumeId]`, `/workspace/[resumeId]/{batch-tailor,career,cover-letter,edit,optimize}`, `/workspaces/[workspaceId]/{,recruiter}`.

### 5.2 Templates: **61**, not ~63

* Source: **61** `.tex` files under `backend/app/data/templates/` across 14 categories (`academic 5, ats_safe 5, creative 4, executive 4, finance 4, graduate 4, legal 4, marketing 4, medical 4, minimal 4, presentation 5, regional 4, software_engineering 6, two_column 4`).
* Live: `GET /templates/?limit=200` returned **61** rows; category counts match source exactly.
* Seeder: `backend/app/scripts/seed_templates.py` walks the same directory; no additional hard-coded template rows were found.
* A recursive `*.tex` count under `backend/` finds **62** files: the 61 catalog templates plus `backend/test/fixtures/accepted-sharing.tex`. The "~63" in the prompt is not reproducible from the catalog or live DB.

Docs disagree with themselves: `docs/FEATURES.md:5` says **63**, `:169` says **56**, `:268` says **60**, and `docs/LAUNCH_CHECKLIST.md:62` says **61**. Code and live say **61**. Recorded as a documentation-drift finding, not a product defect.

### 5.3 Capabilities: **129 claim verified**

* `backend/app/core/capability_catalog.json` has **129 rows**, unique keys `a01`–`i04` (9/14/26/26/13/11/13/13/4 across families a–i), **113 gateable + 16 always-on**.
* **414** `source_paths` references across those rows; **0** point to a missing file. This is a strong positive: the catalog's claimed UI/backend entry points still exist.
* `capability_subfeature_catalog.json` adds **5** child controls (`d14_latex`, `d14_table_text`, `d14_table_image`, `d14_math_text`, `d14_math_image`).
* `feature_registry.py` adds **31** coarse parent features. Registry total = **165** entries; **149** gateable (31+113+5), **16** non-gateable.
* `docs/LAUNCH_CHECKLIST.md:363-364` says "31 coarse parents make 160 registry entries / 144 switches". Code says **165 / 149**; the doc omits the 5 subfeatures. The 129 product-ID claim itself is correct.
* Live export was blocked: `GET /admin/entitlements` → **401**; no admin credential was available. The audit therefore verified the catalog from source, not from the live grant matrix.

### 5.4 Dead / orphan UI entry points

Static inbound-link analysis (all quoted path literals + template literals in `frontend/src`, excluding tests, normalized for `[param]`/`${...}`) found **3 pages with no inbound reference** beyond their own file:

| Page | Evidence | Assessment |
|---|---|---|
| `frontend/src/app/workspace/cover-letters/page.tsx` | only referenced by `frontend/src/lib/analytics/traffic-source.ts:62` (analytics allow-list) and tests; no `href`, `router.push`, or `Link` anywhere | **dead entry point** — cover-letter library page is unreachable from the UI |
| `frontend/src/app/admin/tenant/page.tsx` | no `href`/`router.push`/`Link` in any `.tsx`; only tests and `frontend/src/app/admin` siblings | **dead entry point** — tenant admin page is unreachable from the admin UI |
| `frontend/src/app/workspace/[resumeId]/batch-tailor/page.tsx` | no inbound link; `capability-ui-policy.ts:67` only maps the route to `d05`; the page itself calls `createBatchTailor`/`getBatchStatus`, but nothing navigates to the page | **dead entry point** — whole batch-tailor feature has no navigation entry |

`/r/[token]` is intentionally a direct public link target (share URLs), not dead. `/u/[username]` is reached from middleware/portfolio URLs and is not counted.

### 5.5 Dead `api-client` methods

`frontend/src/lib/api-client.ts` defines **568** methods. **59** have zero `.method(` call sites in `frontend/src` outside `api-client.ts` (tests excluded). Two are internal (`constructor`, `setTenantSlug`), leaving **57 user-facing methods with no caller**. Several are superseded duplicates rather than missing features — e.g. `createReminder`/`listReminders`/`updateReminder`/`deleteReminder` are superseded by `createApplicationReminder`/`listApplicationReminders`/`updateApplicationReminder`/`deleteApplicationReminder`, which the tracker page does use. But the list is a reliable map of stale client surface and should be pruned or wired:

```
constructor, setTenantSlug, health, listResumes, listResumesPaginated,
getAdminDailyMetrics, getArtifactManifest, getPdfImport, getPdfBlobUrl,
trackUsage, getPersonas, getOptimizationHistory, getEmailResumePdfStatus,
retryEmailResumePdf, getResumeVariants, trackEvent, trackSignupStarted,
trackOAuthFailure, forkResumeElementVersion, getAdminExperiment,
evaluateCohortFlags, getAdminIncident, deleteAdminIncident,
getAdminViewAsSessions, bulkUpdateAdminEntitlements, getGdprRequest,
getApplication, getTrackerStats, getStaleApplications, createReminder,
listReminders, deleteReminder, updateReminder, createInterview,
listInterviews, updateInterview, deleteInterview, downloadInterviewIcs,
createCompany, listCompanies, updateCompany, deleteCompany, createContact,
listContacts, updateContact, deleteContact, getInterviewPrep,
getResumeGitHubStatus, getResumeDropboxStatus, setupPortfolio,
checkUsernameAvailability, searchCareerSkills, getSnippet, createSnippet,
uninstallSnippet, getCurrentTenantContext, leaveTenant, getSubmissions,
getSubmission
```

### 5.6 Backend paths with no frontend literal

**82 of 588** backend paths have no matching path literal anywhere in `frontend/src` (including Next proxy `/api/*` calls). This is **not** a dead-route list; it is dominated by:

* external/public API and callbacks — `/api/v1/*` (5), `/billing/*webhook`, `/webhooks/resend`, `/email/webhooks/resend`, provider OAuth callbacks, `/public/compile`;
* legacy aliases the UI replaced — `/admin/incidents/*`, `/admin/jobs/*`, `/admin/dunning*`, `/admin/saved-segments/*`, `/subscription/*`, `/export/builder/v1/*`;
* infra probes — `/livez`, `/readyz`, `/metrics`, `/jobs/system/cleanup`;
* template assets returned as absolute URLs by `/templates/` (`/templates/{id}/thumbnail`, `/pdf`) rather than constructed in the client;
* BYOK endpoints called through the Next `/api/byok/*` proxy with paths built at runtime.

No route in this set is proven unreachable. The groups with neither a first-party literal caller nor an obvious external-provider justification are the legacy admin aliases (see 2.3) and a handful of BYOK/legacy analytics endpoints. All of them are still reachable over HTTP and remain an attack surface.

### 5.7 Orphan route/decorator check

No API module defines routes that fail to register: **114** files contain `@router`/`@ws_router` decorators, and all 114 appear in the runtime route list. There is no dead module.

---

## 6. Findings

| ID | Severity | Finding | Evidence |
|---|---|---|---|
| C-001 | P2 | Live OpenAPI/docs are disabled, so the canonical schema cannot be fetched from production; audit must use source at the deployed SHA. | `GET /openapi.json`, `/api/openapi.json`, `/docs`, `/api/docs` → 404 on 2026-11-27; `backend/app/main.py:166-178` |
| C-002 | P2 | **38 registered operations are absent from OpenAPI and `http.csv`** (35 admin, 3 infra). The baseline inventory covers 94.4% of the registered surface; all hidden admin exports and legacy aliases are missed. | `http-coverage-audit.csv` rows with `include_in_schema=false`; table 2.2 |
| C-003 | P3 | **35 handlers are registered at 2–7 paths**, yielding 84 operations from 82 path registrations (47 duplicate paths). `http.csv` counts each alias separately, inflating the "path" surface and obscuring which path is canonical. | table 2.3; `http-coverage-audit.csv` `alias_group` |
| C-004 | P3 | `http.csv` auth labels are coarse and wrong for at least 12 admin operations (labeled `user-or-optional` but `require_admin_actor`). They cannot be used for enforcement testing. | section 2.5; e.g. `/templates` POST `template_routes.py:461`; `/jobs/system/cleanup` `job_routes.py:2092` |
| C-005 | P2 | `refresh_daily_metrics_task` has **no production trigger**: its only caller is a Celery beat entry, and Celery beat is not deployed on Modal. The admin daily-metrics rollup is stale; fallback to base tables hides it. | `cleanup_worker.py:2045-2097`; `celery_app.py:348-352`; `modal_app.py:751-759`; `test_modal_deployment_parity.py:916` |
| C-006 | P2 | `run_cleanup_task` omits `_init_worker_redis()`, but both cleanup tasks publish `job.started` first. The admin-triggered `POST /jobs/system/cleanup` path aborts before the reaper/orphan pruner; scheduled sweeps still work. | `modal_app.py:569-586`; `cleanup_worker.py:74-76,1482-1484`; `event_publisher.py:403-415` |
| C-007 | P3 | Retention preview cadence is 4× slower on Modal: beat 900 s, production hourly (3600 s). Dry-run previews only; purges are explicit. | `celery_app.py:338-341`; `modal_app.py:785-789` |
| C-008 | P3 | Queue-depth sampling is 3× slower (20 s beat → 60 s Modal) and samples Celery broker queues that are structurally empty on Modal. The admin queue view measures nothing useful in production. | `celery_app.py:376-382`; `modal_app.py:993-1000`; live `/jobs/health` all 0 |
| C-009 | P3 | Template count claims drift across docs: 63 (`FEATURES.md:5`), 56 (`:169`), 60 (`:268`), 61 (`LAUNCH_CHECKLIST.md:62`); source and live are both **61**. | source `.tex` count; live `/templates/` |
| C-010 | P3 | Capability registry totals in docs are stale: 160 entries / 144 switches vs code **165 / 149** (5 subfeatures omitted). The 129 product-ID claim is correct. | `feature_registry.py:46-137`; `capability_catalog.json`; `capability_subfeature_catalog.json`; `LAUNCH_CHECKLIST.md:363-364` |
| C-011 | P2 | Three app pages have no UI entry point: cover-letter library, admin tenant, batch-tailor. The batch-tailor page works only if the URL is typed directly, so the whole feature is unreachable through navigation. | section 5.4; `frontend/src/app/...`; `capability-ui-policy.ts:67` |
| C-012 | P3 | 59/568 `api-client` methods have no call site outside the client (57 user-facing). Some are superseded duplicates; all are stale surface that hides real feature gaps. | section 5.5 |
| C-013 | P3 | 82/588 backend paths have no frontend path literal. Most are external/callback/alias/assets; legacy admin aliases and a few BYOK/legacy analytics paths have no obvious UI or external consumer. | section 5.6 |
| C-014 | P3 | 25 of 30 worker/schedule entrypoints are not named anywhere in `docs/`; the five that appear are runners in architecture/latency/QA docs. No periodic `scheduled_*` function is documented. | section 4.4; `modal_app.py` |
| C-015 | P3 | `job.retrying` is emitted by 13 worker sites and consumed by the UI but absent from `AnyEvent`/`event-types.ts`; `sys.error` is declared and typed but never emitted. | `event_publisher.py:518,552`; `event_schemas.py:200-228`; `frontend/src/lib/event-types.ts:7-24` |
| C-016 | P3 | `/ws/jobs` rate limiting is process-local (20 msg/s per process), so a multi-worker deployment multiplies the effective limit per client. Collab chat has a Redis-backed limiter; jobs does not. | `ws_routes.py:63,153-166`; `collab_manager.py:310-333` |

No P0/P1 coverage finding was observed in this read-only pass. C-005/C-006/C-011 affect admin/analytics or an unreachable page, not the core compile/optimize path; they are P2 because they invalidate parts of the launch checklist.

---

## 7. Blocked / not verified

| Item | Status | Reason |
|---|---|---|
| Live OpenAPI export | **BLOCKED** | 404 on all four schema/docs paths |
| Live capability/entitlement matrix | **BLOCKED** | `GET /admin/entitlements` → 401; no admin credential in this audit context |
| WS frame-level tests (ticket, replay, ordering, backpressure) | **NOT RUN** | Read-only inventory mandate; no test identity or ticket minting |
| Modal container counts / min-max actuals | **PARTIAL** | Derived from `modal_app.py` and `engine_capacity.py`; no `modal app` introspection or runtime metrics |
| Celery worker/beat liveness | **PROVEN DORMANT** | Beat not deployed per code/docs; live queue depths all 0; tasks run in-process on Modal |
| PostHog/admin analytics reconciliation | **OUT OF SCOPE** | Different sub-agent; this inventory only proves the rollup worker is orphaned |
| Dead UI call sites beyond static literals | **PARTIAL** | Methods could be called via dynamic property access; 59 is a static lower bound on dead client surface |

---

## 8. Files written by this auditor

* `audit/inventory/http-coverage-audit.csv` — 674 rows, one per registered `(method,path)`, with operation id, tags, inferred auth, handler module, source file/line, schema/http.csv presence, and alias group.
* `audit/inventory/ws-coverage-audit.csv` — 49 rows covering both WS paths, the ticket endpoint, all message types, persistence/replay, UI consumers, and internal Redis control messages.
* `audit/inventory/workers-coverage-audit.csv` — 84 rows covering 36 Modal functions, 30 Celery tasks, 7 queues, and 11 beat entries, with trigger, timeout, capacity, retry/idempotency, DLQ/recovery, and production reachability.
* `audit/inventory/coverage-diff.md` — this report.

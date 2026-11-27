# Workers, queues, schedules and WebSocket/job events — reconciliation

**Audit window:** 2026-11-27, live probes 10:34–10:42 UTC; Modal log/call window 09:15–10:42 UTC.
**Source:** current checkout `8689a250` (`audit/production-2026-11-27`), which is audit-only commits on top of `origin/main` `d2cbc51ab8c25106d073e0e0065b985fc6dc6490`; `git diff --stat d2cbc51a..HEAD` contains only `audit/**` files. All application-code citations below are the deployed source.
**Production app:** Modal `latexy-backend` (`ap-IB2XwK8MjL2xmeI7wOUyEZ`), deployment v2 2026-11-27 08:15 UTC, 30 functions, 5 registered schedules, deployment-hold header `false`.
**Safety:** read-only. No jobs, users, config, queues or schedules were created or changed. The only live writes were WebSocket protocol probes from disposable anonymous sockets (ping / invalid subscribe / malformed frame / oversize frame / unauthenticated collab handshake).

---

## 1. Executive reconciliation

| Question | Answer | Evidence |
|---|---|---|
| Does production run Celery workers or beat? | **No.** Production is Modal-only. `DEPLOY_TARGET=modal` and every submit path branches to `modal_dispatch.spawn()`. | `backend/modal_app.py:12,322,346`; `backend/app/core/modal_dispatch.py:66-76`; no Celery worker/beat in the Modal app |
| Do the six Celery queues have consumers in production? | **No.** All six sampled depths are 0 and `/jobs/health` omits `worker_count` (no Celery worker answered `inspect().ping()`). | live `/jobs/health` 10:34 UTC; `backend/app/api/job_routes.py:2030-2086` |
| Are the queue metrics meaningful in production? | **No, not for work admission.** Modal spawns are fire-and-forget with no depth/backlog metric. The sampler measures empty Redis lists. | `backend/app/core/celery_app.py:475-527,608-664`; live depths `{cleanup:0,email:0,combined:0,llm:0,latex:0,ats:0}` |
| How many Modal schedules exist? | **5** (Modal's stated five-schedule budget is saturated). | `modal app info latexy-backend --env main`; `backend/modal_app.py:786-792` |
| How many Celery Beat entries exist? | **11.** Ten have a Modal equivalent; **one (`refresh-daily-metrics`, every 600s) has none.** | `backend/app/core/celery_app.py:327-383`; `modal app info` function list |
| Do all scheduled jobs actually run? | All five registered schedules have call evidence in this deployment **except** `scheduled_weekly_digest`, whose first run is Monday 2026-11-30 09:00 UTC (the app was deployed Friday 08:11 UTC). | `modal function calls` counts in §3; log window |
| Are scheduled runs completing? | Cleanup, temp cleanup, retention previews, admin digests, tracker, recovery, health and admin-alert runs all log `success`; health check reports **`degraded` on every observed run**. | Modal logs 09:15–10:42 UTC |
| Is there exactly-once job-event delivery? | **No.** Events are persisted then published; replay is bounded at 500 entries per reconnect and the publisher stream is capped near 1,000, so a long disconnect can lose the terminal event. Client dedupe is by stream ID. | `backend/app/core/event_bus.py:94-137,265-319`; `backend/app/workers/event_publisher.py:303-309` |
| Is `/ws/collab` history durable? | **No.** Yjs updates live only in a Redis list capped at 500 updates / 24h, with no database snapshot or compaction. | `backend/app/services/collab_manager.py:79,989-1005` |
| Are job events ordered under replay? | **Not guaranteed.** Pub/Sub is subscribed before replay; the live listener can deliver newer events while `XREAD` is still sending older ones. The client drops old IDs, so missed token/progress events can be dropped. | `backend/app/core/event_bus.py:94-137,204-218,297-310`; `frontend/src/lib/ws-client.ts:303-319` |

**Counts**

- 30 Modal functions = **1 API** (`fastapi_app`) + **19 job workers** + **5 child runners** + **5 schedule entry points**.
- 6 logical Celery queues (`latex`, `llm`, `combined`, `ats`, `cleanup`, `email`); **0 production consumers**.
- 11 Beat entries; **10 mapped**, **1 orphaned**.
- **18 job-event types actually produced**; 18 backend schema classes (one swap: `job.retrying` produced but absent from the schema; `sys.error` declared but not produced); 19 frontend `EventType`s (adds `document.convert_complete`, omits `job.retrying`).
- 2 WebSocket paths; **41 protocol/event rows** in `ws-events.csv` (30 `/ws/jobs`, 11 `/ws/collab`).

---

## 2. Production execution model (why queue numbers are misleading)

`backend/modal_app.py` bakes `DEPLOY_TARGET=modal` into every image (`modal_app.py:322,333,346`). Every API submit helper checks that variable and uses Modal spawn, e.g.:

- `backend/app/workers/latex_worker.py:2925-2968`
- `backend/app/workers/llm_worker.py:589-604`
- `backend/app/workers/orchestrator.py:1659-1686`
- `backend/app/workers/ats_worker.py:486-502`
- `backend/app/workers/cleanup_worker.py:2110-2133`
- `backend/app/workers/email_worker.py:1090-1104`

The Modal function then runs the Celery task **in-process** with `.apply(kwargs=..., throw=False)` (`modal_app.py:456-466,483-490,500-507,...`). Consequences:

1. There is no broker hop, no Celery worker, no prefetch, no visibility timeout, and no Celery queue backpressure in production.
2. The Celery queue labels (`latex`, `llm`, etc.) are routing metadata only. Logs show `"queue": "default"` because eager `.apply()` has no `delivery_info`; the labels do not describe a live queue.
3. `/jobs/health` `queue_depths` are produced by a sampler that reads empty Redis lists. They cannot tell an idle deployment from a stopped sampler, and they say nothing about Modal spawn backlog.
4. Celery `time_limit` / `soft_time_limit` are worker-enforced; under eager `.apply()` they are **not enforced**. Only the Modal function timeout caps execution (e.g. `run_llm_task` 300s vs task `time_limit=180`; `run_ats_task` 120s vs task `time_limit=60`).
5. Celery `self.retry(countdown=...)` works under eager `.apply()` but **the countdown is ignored** (verified locally with Celery 5.6.3: `countdown=2` completed in 0.1s). Provider rate-limit retries therefore fire immediately, not after the configured 30/60/120s.
6. Modal function `Max Retries` is unset (`-`, effectively 0) for every worker. A hard Modal timeout, OOM or container kill receives **no retry**; no `task_failure` signal and no DLQ entry are produced.

**Celery deployment artifacts exist, but none are attached to the live production backend.** `backend/docker-compose.yml:85-146` (dev), root `docker-compose.prod.yml:211-286`, and `k8s/celery/celery-worker.yaml:4-194` define worker/beat/Flower. Modal does not deploy those services, and `modal_app.py:754-759` states that Celery beat is only launched by dev/docker/k8s manifests "none of which run in production". Live evidence agrees: `/jobs/health` has no `worker_count` and all six queues are 0. This audit did not inspect the k8s cluster; the finding is about the live backend's Redis, not the existence of manifests.

**Excluded from `workers.csv` with reason:** `renderer_preflight`, `migrate`, `freeze_redis_recovery`, `handover_redis_recovery`, `billing_preflight` and `sync_templates` are registered on the separate `operations_app` (`latexy-backend-operations`, `modal_app.py:61,1024-1305`). They are operator/deployment functions, not queue or schedule workers, and `modal app list --env main` shows no deployed `latexy-backend-operations` app. The 30 deployed `latexy-backend` functions are the complete worker/API surface.

---

## 3. Scheduled-job reconciliation

Beat source: `backend/app/core/celery_app.py:327-383`. Modal source: `backend/modal_app.py:762-1018`. Call counts are from `modal function calls <fn> --env main --since ...`; timings from `modal function logs`.

| Beat entry | Beat cadence | Modal owner | Effective cadence | Observed calls / result | Verdict |
|---|---|---|---|---|---|
| `cleanup-expired-jobs` (`cleanup_expired_jobs_task`) | 3600s | `scheduled_cleanup_expired_jobs` | 1h (`Period(hours=1)`) | 2 calls / 3h at 09:15, 10:15 UTC; `success` in 69.3s and 89.8s; MinIO prune 3/3 verified; 0/344 jobs cleaned | **RUNS** |
| `cleanup-temp-files` (`cleanup_temp_files_task`) | 1800s | `scheduled_cleanup_temp_files` | 30m (`Period(minutes=30)`) | 4 calls / 2h at 08:45, 09:15, 09:45, 10:15 UTC; `success` ~2s; **0 files / 0 bytes freed every run** | **RUNS, ineffective by design** (isolated Modal FS; `modal_app.py:809-813`) |
| `retention-due-previews` (`run_due_retention_previews_task`) | 900s | piggyback in `scheduled_cleanup_expired_jobs` | 1h (4× slower) | 2 calls / 3h (inside cleanup); `success` 7.9s and 15.3s | **RUNS, cadence drift** |
| `health-check` (`health_check_task`) | 300s | `run_scheduled_health_check` spawned by `scheduled_five_minute_maintenance` | 5m | 12 calls / 1h; each logs `Health check task ... completed: degraded` | **RUNS, always degraded** |
| `refresh-daily-metrics` (`refresh_daily_metrics_task`) | 600s | **NONE** | **never** | No Modal function, no schedule, no calls; task exists at `cleanup_worker.py:2045-2109` | **ORPHANED / DORMANT** |
| `weekly-digest-monday-9am` (`send_weekly_digest_to_all`) | Mon 09:00 | `scheduled_weekly_digest` | `Cron('0 9 * * 1', UTC)` | 0 calls / 6d because the app deployed Fri 08:11 UTC after the last Monday; schedule is registered in `modal app info` | **SCHEDULED, UNEXERCISED** |
| `admin-digest-dispatch` (`send_admin_digests`) | 3600s | piggyback in `scheduled_cleanup_expired_jobs` | 1h | 2 calls / 3h; `EMAIL: admin digest dispatch completed (0 sent, 0 failed)` in 2.8s/5.5s | **RUNS** |
| `comment-mention-delivery-recovery` | 60s | `scheduled_comment_mention_recovery` spawned by `scheduled_minute_recovery` | 1m | 60 calls / 1h; `success` ~0.43s | **RUNS** |
| `document-email-delivery-recovery` | 60s | `scheduled_document_email_recovery` spawned by `scheduled_minute_recovery` | 1m | 60 calls / 1h; `success` ~1.0s | **RUNS** |
| `tracker-notifications` (`send_tracker_notifications`) | 300s | `scheduled_tracker_notifications` spawned by five-minute maintenance | 5m | 12 calls / 1h; `success` 2.8–5.9s; delivered 0 | **RUNS** |
| `sample-queue-depths` (`sample_queue_depths`) | 20s | inline in `scheduled_minute_recovery` | 1m (3× slower) | 60 scheduler calls / 1h; sampler logs not emitted; snapshots persist every minute | **RUNS, coarser cadence** |
| *(not in Beat)* | — | `run_scheduled_admin_alert_evaluation` spawned by five-minute maintenance | 5m | 12 calls / 1h; `{'opened':0,'updated':1,'resolved':0}` most ticks; `opened:1` at 16:05 IST | **PRODUCTION-ONLY, RUNS** |

**Schedule facts that matter**

- `schedule=None if _DEPLOYMENT_TRAFFIC_HELD` on four schedules (`modal_app.py:766,800,848,947,984`). Live header is `X-Latexy-Deployment-Hold: false`, and the call logs prove the schedules are active. A held redeploy silently removes every schedule (while `/health` can still be 200).
- The five schedule slots are exactly: 1h cleanup, 30m temp cleanup, weekly digest, 5m maintenance, 1m recovery. Adding daily metrics as a sixth Modal schedule is not possible without replacing/merging one; the code comment explicitly cites the five-schedule budget (`modal_app.py:786-792`).
- `scheduled_cleanup_expired_jobs` runs three tasks **serially** in one 600s function: cleanup (~70–90s), retention (~8–15s), admin digest (~3–6s). A future cleanup overrun starves retention and admin digests in the same tick.
- `scheduled_minute_recovery` samples queue depths **before** spawning the two recovery children. If `sample_queue_depths()` raises, neither recovery child is spawned (`modal_app.py:996-1012`).
- `modal function info <child>` reports a `Schedule:` line for some unscheduled children (e.g. `scheduled_tracker_notifications` shows the weekly digest cron). This is a CLI display inconsistency: `modal app info` lists only five scheduled functions, source/tests assert no schedule on those children, and call cadence matches spawns. Per-function `Schedule:` output was not used as evidence.

---

## 4. Queue reconciliation

| Queue | Producers in source | Producer in production | Consumer in production | Live depth | Verdict |
|---|---|---|---|---|---|
| `latex` | `submit_latex_compilation` | Modal `run_latex_task` (not the queue) | **none** | 0 | logical only |
| `llm` | `submit_resume_optimization`, cover letter, interview prep, GitHub import, document conversion | Modal `run_llm_task` / `run_cover_letter_task` / `run_interview_prep_task` / `run_github_import_task` / `run_document_conversion_task` | **none** | 0 | logical only |
| `ats` | `submit_ats_scoring`, JD analysis, deep analyze, embed | Modal `run_ats_task` / `run_jd_analysis_task` / `run_deep_analyze_task` / `run_embed_resume_task` | **none** | 0 | logical only |
| `combined` | `submit_optimize_and_compile` | Modal `run_orchestrator_task` | **none** | 0 | logical only; also omitted from `start_celery.sh` |
| `cleanup` | auto-save, admin cleanup, retention (Beat), cleanup scheduler | Modal `run_auto_save_task` / `run_cleanup_task` / scheduled `.apply()` | **none** | 0 | logical only |
| `email` | completion, failure, share-view, comment-mention, document delivery, weekly digest, tracker | Modal `run_email_task` / `run_comment_mention_task` / ... | **none** | 0 | logical only |

**Evidence of zero consumers:** live `GET /jobs/health` at 10:34 UTC returned all six depths `0` and **no `worker_count` key**; `_count_workers()` returns `None` when `inspect().ping()` gets no reply (`job_routes.py:2030-2048`), and the route omits `None` (`job_routes.py:2085-2086`).

**Producer/consumer mismatches**

- `debug_task` (`celery_app.py:461-465`) is registered but has no caller.
- `refresh_daily_metrics_task` is registered and Beat-scheduled, but has no Modal wrapper, no producer and no schedule in production — the single orphaned scheduled task.
- `start_celery.sh:16` starts `--queues=latex,llm,email,cleanup,ats` but **omits `combined`**, while orchestrator routes to `combined` (`celery_app.py:295`). `backend/docker-compose.yml` does include `combined` (`docker-compose.yml:88`); the dev shell script would leave orchestrator work unconsumed.
- If any `.apply_async` fallback ever runs in production (e.g. `DEPLOY_TARGET` is missing/incorrect in a process), the message lands on a queue with no consumer and the job hangs until cleanup. All current submit helpers guard on `DEPLOY_TARGET == "modal"`, so this is latent, not observed.
- `sample_queue_depths()` reads `queue` + `queue:1..9` Redis lists (`celery_app.py:514-527`) and writes six rows per tick. In production those lists are empty; the snapshots are a heartbeat of the sampler, not of work.

**Freshness gap:** `latest_depths()` returns the newest row per queue with no age (`queue_snapshot_service.py:159-161`). `/jobs/health` exposes only the depth, no `sampled_at`. `queue_backlog()` also classifies the latest row without checking its timestamp (`admin_alert_service.py:276-302`). If `scheduled_minute_recovery` stops, the last zero snapshot remains "healthy" forever and the queue alert cannot fire.

---

## 5. Job-event pipeline

### 5.1 Producers and keys

| Event group | Producer | Persistence |
|---|---|---|
| `job.queued` | API admission (`initialize_job_state`, job/cover-letter routes) | Stream `latexy:stream:{job_id}` `MAXLEN~10000`, state snapshot, meta, Pub/Sub; 24h TTL |
| `job.started`, `job.progress`, `job.completed`, `job.failed`, `job.cancelled`, `job.retrying` | Worker `publish_event()`; terminal result via `publish_job_result()` | Stream `MAXLEN~1000` + Pub/Sub + state snapshot; 24h TTL; lifecycle/owner/epoch fence in Lua |
| `llm.token`, `llm.complete` | LLM/cover-letter/orchestrator workers | Stream + Pub/Sub; no state snapshot |
| `log.line` | Latex compiler and orchestrator | Stream + Pub/Sub; no state snapshot |
| `artifact.ready` | Render engine artifact store | Stream + Pub/Sub; no state snapshot |
| `context.ready`, `section.ready`, `patch.ready`, `review.ready` | Resume semantic engine | Stream + Pub/Sub; no state snapshot |
| `ats.deep_complete`, `job.pdf_extracted` | ATS/deep-analysis and compile workers | Stream + Pub/Sub; no state snapshot |
| `sys.heartbeat` | `/ws/jobs` handler per connection | **none** — generated every 30s, not in Stream/Pub/Sub |

The publisher uses one Lua script to allocate the next sequence, `XADD`, `PUBLISH`, refresh the state snapshot and enforce owner/epoch/cancel/terminal fencing (`event_publisher.py:177-323`). This gives atomic sequence + stream + live publish and prevents a stale worker from publishing after cleanup fenced it. That part is sound.

### 5.2 Replay and ordering

Flow:

1. On `subscribe`, the server adds the socket, subscribes to `latexy:events:{job_id}` **before** replay, starts one listener, then runs `XREAD` from `last_event_id` (`event_bus.py:85-137`).
2. Replay reads **at most 500 entries in one call and never loops** (`event_bus.py:282-285`). If more than 500 events were missed, the rest are never sent on that reconnect.
3. The publisher stream is `MAXLEN ~ 1000` (`event_publisher.py:303-309`), so long `llm.token` streams evict older events. A job that emits more than ~1,000 events cannot replay its full history.
4. The live listener is active during replay (`event_bus.py:94-118`) and can `send_text` a newer event while `_replay_events` is still sending older ones (`204-218` vs `297-310`).
5. The client tracks only the highest stream ID seen and drops anything not strictly newer (`ws-client.ts:303-319`). Therefore, a live event during replay can advance the watermark and cause older replayed events to be **dropped**, or the UI can apply events out of order. `llm.token` is the highest-volume and most affected type.
6. A missing terminal event is mitigated by the REST poll fallback (3s for the first four polls, then 10s, up to 157 polls / ~26 min; `useJobStream.ts:258-370`), so the user eventually recovers. This is recovery, not correct replay.

**Duplicate suppression:** stream IDs are compared lexicographically by milliseconds/sequence (`ws-client.ts:45-53`). This works for replayed and live stream entries. It does not cover:
- `sys.heartbeat` (no `stream_id`, `job_id=""`);
- the `/deep-analyze` initial `job.queued` envelope, which publishes without `stream_id` (`ats_routes.py:822`);
- `document.convert_complete` (never emitted).

### 5.3 Cancellation

REST and WS cancellation both commit the DB arbiter first, then set the Redis flag/lifecycle, write `state`/`result`, `XADD` a `job.cancelled` entry, `PUBLISH` it, and return (`job_routes.py:1898-1965`; `ws_routes.py:707-779`). This is the correct ordering. The WS handler does not send a `cancelled` acknowledgement frame; the client learns via the `job.cancelled` event (or the REST response).

---

## 6. WebSocket protocol audit

### 6.1 `/ws/jobs`

- **Auth:** optional one-time ticket minted by `POST /ws/ticket` (purpose-bound, 60s TTL, SHA-256 key, `GETDEL`; `ws_routes.py:118-150,295-325`). Anonymous sockets may connect with no ticket for owner-less trial jobs; a presented invalid ticket is closed with 4001 before upgrade (`ws_routes.py:177-184`). Owned jobs require the matching user (`ws_routes.py:328-349`).
- **Limits:** 64 KiB frame bound before JSON parse (`ws_routes.py:60,80-108`), 20 messages/s per connection (`ws_routes.py:153-166`), one socket per client in the UI, multi-job subscriptions on one socket.
- **Heartbeat:** server sends `sys.heartbeat` every 30s (`ws_routes.py:372-389`); client sends `ping` every 25s (`ws-client.ts:377-380`), receiving `pong`. Both are live.
- **Live probe results (10:34–10:42 UTC):**
  - `ping` → `{"type":"pong","server_time":...}` (200)
  - malformed text → `{"type":"error","code":"invalid_json",...}`
  - 70,000-byte frame → `{"type":"error","code":"message_too_large",...}`
  - 22 rapid pings → `{"type":"error","code":"rate_limited",...}` after the 20/s budget
  - anonymous subscribe to a random UUID → `{"type":"error","code":"forbidden",...}`
  - idle socket → `sys.heartbeat` with `job_id:""`, `sequence:0`, no `stream_id`
- **Missing protection:** no cap on the number of job IDs per connection. `subscribed_jobs` is an unbounded set and every new job starts a Pub/Sub listener task (`ws_routes.py:191,239-246`; `event_bus.py:92-118`). The 20 msg/s limit slows but does not bound this.
- **Backpressure:** the listener iterates all sockets and `await ws.send_text()` sequentially with no per-socket queue or timeout (`event_bus.py:209-229`). One slow client can delay fan-out for every client on that job; high-rate `llm.token` makes this a realistic head-of-line risk.
- **UI consumers:** `useJobStream` + reducer (`frontend/src/hooks/useJobStream.ts`, `useJobStream.reducer.ts`), used by `/try`, editor, optimize, cover-letter, interview prep, compare, quick tailor and format conversion. `ws-client.ts` owns one socket and resubscribes on reconnect with the stored stream ID.

### 6.2 `/ws/collab/{resume_id}`

- **Auth:** purpose-bound single-use ticket with `resume_id` scope (`ws_routes.py:529-579`). Missing/invalid ticket closes 4001; malformed UUID closes 4004 before consuming a ticket; non-collaborator closes 4003 (`ws_routes.py:549-618`).
- **Authorization:** owner or `resume_collaborators` row; capability `f05`, editor capability `f04`, source-write capability `c01` (`ws_routes.py:429-437,616-618`). Every frame re-checks live access, including current owner and current collaborator role (`ws_routes.py:498-526`, `collab_manager.py:385-424`).
- **Protocol:** binary Yjs `MSG_SYNC` step1/step2, `MSG_UPDATE`, `MSG_AWARENESS`, `MSG_QUERY_AWARENESS`; text extension `MSG_CHAT=62`; server denial `MSG_PERMISSION_DENIED=63`. Details and schemas are in `ws-events.csv`.
- **Persistence:** only accepted document updates are stored, base64 in `collab:{resume_id}:updates`; `LTRIM -500..-1`; 24h TTL (`collab_manager.py:989-1005`). Catch-up replays that list on SYNC_STEP1 (`1008-1034`). There is **no database snapshot, no compaction, and no event sequence**.
- **Ephemeral:** awareness/presence, chat and denial frames are never persisted. Chat is plain text, ≤2 KiB, 20 messages/10s per user/resume, no history (`collab_manager.py:112-136,245-333,949-984`).
- **Cross-process:** frames are relayed locally and via Redis Pub/Sub with an origin-process filter (`collab_manager.py:481-566,686-805`).
- **Heartbeat:** server sends `MSG_QUERY_AWARENESS` every 15s to keep idle sockets alive (`ws_routes.py:426-455`).
- **Live probe results:** valid UUID without ticket → close 4001 `Unauthorized`; malformed path → close 4004 `Resume not found`.
- **Cost/latency risk:** `has_access()` is called for every recipient on every relayed frame and performs entitlement checks plus DB queries for current owner/role (`collab_manager.py:385-424,489-526`; `ws_routes.py:498-526`). A busy room issues several DB queries per Yjs update.
- **UI consumers:** `y-websocket` `WebsocketProvider` + `MonacoBinding` in `LaTeXEditor.tsx:2218-2480`; chat via `createYWebsocketChatTransport` (`collab-chat.ts`); `CollaboratorChat` renders frames and denial codes.

### 6.3 Contract drift / dead message types

| Type | Declared where | Producer | Consumer | Status |
|---|---|---|---|---|
| `job.retrying` | backend emits; absent from `event_schemas.AnyEvent` and frontend `EventType` | workers on retry | **none** (reducer default ignores) | UI relies on the following `job.started` to leave the transient `job.failed` state; may flash a failure |
| `sys.error` | `event_schemas.py:199-203`, frontend `EventType` | **none** | none | dead |
| `document.convert_complete` | frontend `event-types.ts:25,235-241` | **none** (converter emits `job.completed`) | **none** (no reducer case) | dead |
| `unsubscribed` | frontend `WSServerMessage` | **none** (server sends nothing on unsubscribe) | none | dead |
| `cancelled` | frontend `WSServerMessage` | **none** (server emits `job.cancelled` event) | none | dead |

`job.pdf_extracted` and `ats.deep_complete` are auxiliary events allowed after the terminal fence only when the completed owner/epoch matches (`event_publisher.py:218-228`); they are replayable only for completed jobs.

---

## 7. Dormant, orphaned and risky paths

| Item | State | Risk |
|---|---|---|
| `refresh_daily_metrics_task` | Dormant: Beat-only, no Modal schedule | Admin daily rollup never refreshed; reads fall back to base tables and report stale (`admin_daily_metrics_service.py:544-614`) |
| `debug_task` | Registered, no caller | none (dead code) |
| `document.convert_complete` | Frontend-only type | dead contract |
| `sys.error` | Schema-only type | dead contract |
| `unsubscribed`, `cancelled` | Frontend-only server frames | dead contract |
| `scheduled_cleanup_temp_files` | Runs, always 0 files | Green but cannot clean the warm compile container's `/tmp` (isolated FS; documented) |
| `scheduled_weekly_digest` | Registered, first run 2026-11-30 | Unexercised; no digest-period dedupe; fan-out unbounded |
| `health_check_task` | Runs every 5m, reports `degraded` every time | Noisy/misleading health signal; cause not logged (result only in synthetic Redis job) |
| `celery_app.control.revoke` in cleanup | Executes in Modal but no Celery workers exist | Cannot terminate a stuck Modal container; the fence stops its output but compute continues |
| DLQ lists `latexy:dlq:*` | Written on exhausted Celery retries | **No reader, retry tool, admin UI or alert**; 7-day TTL; max 500/task |
| Celery Beat `retention-due-previews` | 15m source cadence | Runs hourly in production; up to 45m late |
| Celery Beat `sample-queue-depths` | 20s source cadence | Runs 60s in production; 3× coarser |
| `start_celery.sh` | Dev helper omits `combined` | Local orchestrator jobs would never be consumed |

---

## 8. Findings

### W-01 — P1 — Collaboration history is capped at 500 updates with no snapshot or compaction

`_MAX_UPDATES = 500`; `_persist_update()` does `RPUSH` + `LTRIM` and sets a 24h TTL (`collab_manager.py:989-1005`). Catch-up replays only that list (`1008-1034`). Yjs updates are append-only; once a room exceeds 500 updates the oldest operations are discarded permanently. A client that reconnects, or a new collaborator who joins, receives a document reconstructed from a truncated update history. There is no DB snapshot/compaction job. At normal editing rates this is reachable in one long session. Data-loss severity.

### W-02 — P1 — A killed/timed-out Modal invocation has no retry and can leave the job non-terminal for ~10–70 minutes

Every worker has Modal `Max Retries: -` (0) and no `retries=` decorator. A hard Modal timeout/OOM/kill therefore produces no Celery `task_failure`, no DLQ entry, and no retry. The only recovery is the hourly cleanup sweep, which fails `processing` jobs after `processing_timeout = 10 * 60` (`cleanup_worker.py:1571`), i.e. the next hourly tick after the 10-minute threshold — up to ~70 minutes after the kill. `celery_app.control.revoke(..., terminate=True)` in that sweep is a no-op in Modal (`cleanup_worker.py:1767`), so the abandoned container keeps burning compute until its own timeout. In-process exceptions are handled quickly; this finding is specifically hard container death/timeout.

### W-03 — P2 — Replay can miss the terminal event and does not preserve order

Replay is a single `XREAD count=500` (`event_bus.py:282-285`) against a publisher stream capped at ~1,000 entries (`event_publisher.py:303-309`). It does not loop, so a reconnect after >500 missed events loses the remainder. Pub/Sub is subscribed before replay (`event_bus.py:94-118`), so a live event can arrive while older replayed events are still being sent (`204-218` vs `297-310`); the client's monotonic watermark then drops the older events (`ws-client.ts:303-319`). `llm.token` bursts make this realistic. The REST poller recovers the terminal UI state within ~10s (up to 26 min), so user impact is degraded, not permanent loss.

### W-04 — P2 — `refresh-daily-metrics` is scheduled in Beat but never runs in production

The task exists (`cleanup_worker.py:2045-2109`) and Beat schedules it every 600s (`celery_app.py:348-352`), but no Modal function or schedule references it; `modal_app.py` has no `refresh_daily_metrics` string, and `modal app info` has no such function. The admin endpoint intentionally has no manual refresh (`admin_daily_metrics_routes.py:1-10`). Reads fall back to base tables when the rollup is stale/absent and label the source (`admin_daily_metrics_service.py:544-614`), so numbers are not silently wrong, but the freshness contract and the rollup's latency/cost benefit are not delivered.

### W-05 — P2 — Queue health is a zero-depth snapshot with no freshness, and cannot see Modal backlog

`/jobs/health` returns six zero depths from the last snapshot and no `worker_count` (`job_routes.py:2053-2086`). `latest_depths()` does not expose `sampled_at` (`queue_snapshot_service.py:159-161`). The `queue.backlog` alert classifies the latest row without checking age (`admin_alert_service.py:276-302`). If the one-minute sampler stops, the stale zeros remain "healthy" and the alert never fires. Even when the sampler works, the six Celery queues carry no production work; Modal spawn backlog/concurrency is invisible to the product admin surface.

### W-06 — P2 — The dead-letter queue is write-only

`task_failure` writes `latexy:dlq:{task_name}` only when Celery retries are exhausted (`celery_app.py:1034-1092`). There is no reader, replay tool, admin route, alert or cleanup besides the 7-day TTL/500-entry trim. On Modal, hard kills never reach this path at all. A failed job can therefore be "dead-lettered" with no operator-visible queue of failed work.

### W-07 — P2 — No `max_containers` on any job worker; Modal fan-out is uncapped and unobservable

`capacity_options()` only sets `min_containers`, `buffer_containers` and `scaledown_window` unless `MODAL_<KIND>_MAX_CONTAINERS` is present (`engine_capacity.py:32-42`); `modal function info` shows `Max: -` for every worker. Each admitted job submit, admin retry and email digest fan-out can spawn another container. There is no product-side spawn queue, depth or backpressure. The 20 msg/s WS limit and quota checks bound some paths but not all (admin retries, weekly fan-out, recovery sweeps).

### W-08 — P2 — The hourly cleanup function serially owns three jobs and performs a full Redis scan

`scheduled_cleanup_expired_jobs` runs cleanup, retention previews and admin digests in one 600s invocation (`modal_app.py:762-793`). Cleanup scans every `latexy:job:*:state` key (`cleanup_worker.py:1540-1560`) and currently takes 70–90s at ~344 states. Growth is linear; once cleanup approaches 600s, retention and admin digests are starved in the same tick. There is no cursor/incremental scan.

### W-09 — P2 — The five-minute health check reports `degraded` on every observed run

Observed logs 09:15–10:42 UTC: every `health_check_task` ends `completed: degraded`. The task only marks degraded for Redis issues, free disk <1 GiB, or >1,000 active job states (`cleanup_worker.py:1952-1970`). The detailed `health_issues` are written only into the synthetic job result, which has no owner metadata and is not retrievable anonymously; the log line omits the reason. This is an unactionable/misleading green-path signal until the cause is captured in logs. Cause not verified in this read-only pass.

### W-10 — P2 — Collaboration broadcast is sequential and re-authorizes every frame with DB queries

`CollabRoom.relay`/`broadcast` send to local sockets sequentially; for each recipient it calls `has_access()`, which re-runs entitlement checks and DB queries for owner/role (`collab_manager.py:385-424,489-526`). `_collab_live_access_callback` queries `Resume` and `ResumeCollaborator` per check (`ws_routes.py:498-526`). A slow socket or DB delays every peer, and a busy room multiplies DB load by frame × recipients. Chat has a 2s timeout, but document/awareness frames do not.

### W-11 — P3 — `job.retrying` is outside both event contracts

Workers emit `job.retrying` before `self.retry` (e.g. `llm_worker.py:544-559`, `latex_worker.py:2852-2863`), and the publisher uses it to release the lifecycle lease. It is absent from `event_schemas.AnyEvent` and from frontend `EventType`; the reducer default ignores it (`useJobStream.reducer.ts:275-276`). Some workers emit `job.failed` with `retryable: true` immediately before it, so the UI can briefly show a terminal failure that later recovers.

### W-12 — P3 — Dead WebSocket/message contracts

`document.convert_complete` (frontend only), `sys.error` (schema only), `unsubscribed` and `cancelled` (frontend only; server sends nothing or uses `job.cancelled`) have no producer or no consumer. They inflate the contract and make generated clients/types claim capabilities the server does not have. See `ws-events.csv`.

### W-13 — P3 — `/deep-analyze` initial `job.queued` has no `stream_id`

`ats_routes.py:822` publishes `{"type":"event","event":event}` without `stream_id`, unlike the other queued writers (`cover_letter_routes.py:167`; `job_routes.py:1960`). The client cannot advance its watermark from that frame, so a reconnect before the next worker event replays the queued event and can duplicate it in the reducer. Low impact (queued is idempotent) but inconsistent with the replay contract.

### W-14 — P3 — Temp-file cleanup is green but ineffective on Modal

`scheduled_cleanup_temp_files` runs on a fresh `latex_image` container every 30m and logs `0 files, 0 bytes freed` on every observed run. The source comment correctly notes that each Modal container has its own `/tmp` and that this schedule only sees its own filesystem (`modal_app.py:809-813`). Primary hygiene is the per-job `shutil.rmtree`; the schedule cannot clean the warm `run_latex_task` container. Operators should not read its success as storage hygiene.

### W-15 — P3 — Weekly digest is unexercised, undeduplicated and unbounded

The first production run is Monday 2026-11-30 09:00 UTC; the app deployed Friday 08:11 UTC, so there are no calls in the 6-day window. The fan-out issues one `spawn()` per opted-in user with no batch/cap (`email_worker.py:1057-1075`) inside a 300s function, and `send_weekly_digest` has no digest-period dedupe key (`863-950`). A duplicate schedule/manual run can resend; a large opt-in list can exceed the 300s parent timeout mid-fan-out.

### W-16 — P3 — Cadence drift and a 120s manual-cleanup timeout

Retention previews run hourly instead of every 15m; queue sampling runs every 60s instead of every 20s. Admin-triggered `run_cleanup_task` has a 120s Modal timeout (`modal_app.py:569-586`) while the scheduled cleanup has 600s; the current cleanup already takes 70–90s, leaving little headroom for the manual path.

### W-17 — P3 — `start_celery.sh` omits the `combined` queue

`start_celery.sh:16` (dev helper) starts `--queues=latex,llm,email,cleanup,ats`; `submit_optimize_and_compile` routes to `combined` (`celery_app.py:295`). Both Docker Compose files and the k8s worker include `combined` (`backend/docker-compose.yml:88`, root `docker-compose.prod.yml:217`, `k8s/celery/celery-worker.yaml:23`), so the omission is specific to the shell helper. Local dev using that script will leave orchestrator jobs unconsumed; production is unaffected because it uses Modal.

---

## 9. Blocked / unverified

| Item | Why blocked | What would prove it |
|---|---|---|
| End-to-end job-event delivery, exactly-once, cancellation, reconnect replay | Read-only research scope; no test identity/job was created, and no existing owned job ID was available | Events auditor creates a disposable compile/optimize job and records WS frames + Redis Stream IDs + job result |
| Cross-user WS isolation for owned jobs | Would require a real job owned by a test user | Two test identities, one job each, subscribe attempts |
| `/ws/collab` presence/chat/read-only/reconnect | Valid ticket requires an authenticated collaborator and a resume | Events auditor with two collaborator accounts |
| Admin queue dashboard and worker heartbeat view | Admin auth required; no admin credential used here | Read-only admin GET `/admin/operations/queues` and `/admin/operations/health` |
| `scheduled_weekly_digest` execution | First cron is 2026-11-30 09:00 UTC, after this audit snapshot | Re-check call/log after Monday |
| `health_check_task` degraded reason | Detail only in synthetic Redis job result; no anonymous access | Read the health-check result with an admin/Redis read, or add `health_issues` to the log line |
| Modal cost/concurrency under load | Load testing prohibited in this research task | Performance auditor under the audit cost ceiling |
| Whether all 5 schedules fire after a held->released redeploy | Only one released deployment observed; schedule registration is deployment-time | Re-run `modal app info` + call counts after next release |

**Live evidence captured**

- `GET /health` 200 `healthy`, `commit_sha=ee1a405d...`, `deployment_target=modal`, `X-Latexy-Deployment-Hold: false`.
- `GET /readyz` 200 `ready` (database/redis/cache).
- `GET /jobs/health` 200 `healthy`, six queue depths all 0, no `worker_count`.
- `modal app info latexy-backend --env main`: app `ap-IB2XwK8MjL2xmeI7wOUyEZ`, 30 functions, 5 schedules, deployment v2 2026-11-27 08:15 UTC.
- `modal function calls`: 60/h `scheduled_minute_recovery`; 12/h five-minute + three children; 2/3h hourly cleanup; 4/2h temp cleanup; 0/6d weekly digest.
- `modal function logs`: cleanup 69.3s / 89.8s `success`; retention 7.9s / 15.3s `success`; admin digest 2.8s / 5.5s; health check `degraded` every run; admin alert evaluator `opened:1` at 16:05 IST.
- WS probes: pong, invalid_json, message_too_large, rate_limited, forbidden, 4001, 4004, heartbeat.

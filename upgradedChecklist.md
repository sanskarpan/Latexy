# Latexy — Event-Driven Architecture Overhaul Checklist

> **Architecture**: REST commands + WebSocket events + LLM token streaming
> **Status**: Phase 1 ✅ | Phase 2 ✅ | Phase 3 ✅ | Phase 4 ✅ | Phase 5 ✅ | Phase 6 ✅ | Phase 7 ✅

---

## Architecture Summary

```
Frontend (Next.js 14)
  |
  |-- POST /jobs/submit ────────► FastAPI (REST: submit command)
  |◄── {job_id: "abc"} ──────────  FastAPI (REST: acknowledge)
  |
  |══ WS /ws/jobs ══════════════► FastAPI (persistent WebSocket)
  |◄── job.queued ──────────────── event push
  |◄── job.started ─────────────── event push
  |◄── llm.token (×N) ──────────── streaming tokens → live Monaco update
  |◄── llm.complete ────────────── full optimized LaTeX
  |◄── log.line (×N) ──────────── pdflatex lines → live log viewer
  |◄── job.progress ────────────── percent updates
  |◄── job.completed ───────────── final result + ATS score + PDF ready
  |◄── job.failed ──────────────── error_code, retryable flag
  |
  |-- GET /download/{job_id} ───► FastAPI (REST: fetch PDF)

FastAPI process(es)
  └── EventBusManager
       └── asyncio task per job: Redis Pub/Sub latexy:events:{job_id}
            → forwards to subscribed WebSocket clients

Redis
  ├── Pub/Sub: latexy:events:{job_id}      [live delivery, ephemeral]
  └── Streams: latexy:stream:{job_id}      [event log, replay on reconnect]

Celery Worker(s)
  ├── worker_process_init → initialize_worker_redis()  [sync redis.Redis]
  └── publish_event(job_id, event_type, data)
       ├── XADD latexy:stream:{job_id}     [event history]
       └── PUBLISH latexy:events:{job_id}  [live delivery]
```

---

## Event Types

| Event Type | Direction | Payload |
|---|---|---|
| `job.queued` | Server→Client | `job_type`, `user_id`, `estimated_seconds` |
| `job.started` | Server→Client | `worker_id`, `stage` |
| `job.progress` | Server→Client | `percent` (0-100), `stage`, `message` |
| `job.completed` | Server→Client | `pdf_job_id`, `ats_score`, `ats_details`, `changes_made`, `compilation_time`, `optimization_time`, `tokens_used` |
| `job.failed` | Server→Client | `stage`, `error_code`, `error_message`, `retryable` |
| `job.cancelled` | Server→Client | _(base fields only)_ |
| `llm.token` | Server→Client | `token` (single OpenAI delta) |
| `llm.complete` | Server→Client | `full_content`, `tokens_total` |
| `log.line` | Server→Client | `source` (pdflatex/lualatex), `line`, `is_error` |
| `sys.heartbeat` | Server→Client | `server_time` |
| `sys.error` | Server→Client | `message` |

### WebSocket Protocol Messages

| Message Type | Direction | Fields |
|---|---|---|
| `subscribe` | Client→Server | `job_id`, `last_event_id?` |
| `unsubscribe` | Client→Server | `job_id` |
| `cancel` | Client→Server | `job_id` |
| `ping` | Client→Server | _(none)_ |
| `subscribed` | Server→Client | `job_id`, `replayed_count` |
| `event` | Server→Client | `event` (typed event object) |
| `pong` | Server→Client | `server_time` |
| `error` | Server→Client | `code`, `message` |

---

## Redis Key Namespaces

| Key Pattern | Type | Purpose | TTL |
|---|---|---|---|
| `latexy:events:{job_id}` | Pub/Sub channel | Live delivery to FastAPI→WebSocket | ephemeral |
| `latexy:stream:{job_id}` | Redis Stream (MAXLEN~10000) | Event log, replay on reconnect | 24h |
| `latexy:job:{job_id}:state` | String (JSON) | Status snapshot for REST polling | 24h |
| `latexy:job:{job_id}:result` | String (JSON) | Final result payload | 24h |
| `latexy:job:{job_id}:meta` | String (JSON) | job_type, user_id, submitted_at | 24h |
| `latexy:job:{job_id}:seq` | String (counter) | Monotonic event sequence number | 24h |
| `latexy:job:{job_id}:cancel` | String ("1") | Cancel request flag | 1h |
| `latexy:user:{user_id}:jobs` | ZSET (score=timestamp) | User job history | 30 days |

---

## Phase 1 — Fix Build Breakers ✅

> Goal: `pnpm build` passes with 0 errors.

- [x] **Create** `frontend/src/lib/event-types.ts`
  - [x] `BaseEvent` interface
  - [x] `JobQueuedEvent`, `JobStartedEvent`, `JobProgressEvent`, `JobCompletedEvent`, `JobFailedEvent`, `JobCancelledEvent`
  - [x] `LLMTokenEvent`, `LLMStreamCompleteEvent`
  - [x] `LogLineEvent`, `HeartbeatEvent`, `SystemErrorEvent`
  - [x] `AnyEvent` discriminated union
  - [x] `WSClientMessage` / `WSServerMessage` protocol types

- [x] **Create** `frontend/src/lib/api-client.ts`
  - [x] `ApiClient` class with auth token management
  - [x] `submitJob()` → `POST /jobs/submit`
  - [x] `getJobState()` → `GET /jobs/{id}/state`
  - [x] `getJobResult()` → `GET /jobs/{id}/result`
  - [x] `cancelJob()` → `DELETE /jobs/{id}`
  - [x] `downloadPdf()`, `getPdfUrl()`, `getPdfBlobUrl()`
  - [x] `getTrialStatus()`, `trackUsage()`
  - [x] `health()`, `getSystemHealth()`
  - [x] `compileLatex()`, `optimizeAndCompile()`, `scoreResume()` convenience wrappers
  - [x] `getDeviceFingerprint()` utility (localStorage-backed)
  - [x] `getWebSocketUrl()` function (fixes missing `@/lib/job-api-client` import)
  - [x] Singleton `apiClient` export

- [x] **Create** `frontend/src/lib/api.ts`
  - [x] Re-exports all of `api-client.ts`
  - [x] Legacy types: `CompilationResponse`, `OptimizationRequest`, `OptimizationResponse`, `OptimizeAndCompileResponse`, `ApiError`
  - [x] `isApiError()` type guard
  - [x] Extended `apiClient` with legacy method signatures for `useApi.ts`
  - [x] `cancelRequests()` noop (cancellation via WebSocket)
  - [x] `compileLatex(latexContent)`, `compileLatexFile(file)`, `optimizeResume(req)`, `optimizeAndCompile(req)`
  - [x] `downloadPdf(jobId)` returning raw `Response`

---

## Phase 2 — Backend Event Infrastructure ✅

> Goal: Workers can publish typed events to Redis; FastAPI can read job state.

- [x] **Create** `backend/app/models/event_schemas.py`
  - [x] `BaseEvent` Pydantic model with `event_id`, `job_id`, `timestamp`, `sequence`
  - [x] All event classes with `Literal` type discriminators
  - [x] `AnyEvent` union type
  - [x] `status_from_event_type(event_type) -> str` helper
  - [x] `_STATUS_MAP` dict

- [x] **Create** `backend/app/workers/event_publisher.py`
  - [x] Module-level `_worker_redis: Optional[redis.Redis] = None`
  - [x] `initialize_worker_redis(redis_url, password)` — sync `redis.from_url()` + ping
  - [x] `get_worker_redis()` — raises `RuntimeError` if not initialized
  - [x] `_next_sequence(r, job_id, ttl)` — atomic `INCR` counter
  - [x] `publish_event(job_id, event_type, payload_extra, ttl)` — XADD + PUBLISH + state snapshot
  - [x] `_update_state_snapshot()` — `SETEX latexy:job:{job_id}:state`
  - [x] `publish_job_result(job_id, result)` — `SETEX latexy:job:{job_id}:result`
  - [x] `store_job_meta(job_id, user_id, job_type)` — meta + user ZSET
  - [x] `is_cancelled(job_id)` — checks cancel key existence

- [x] **Modify** `backend/app/core/celery_app.py`
  - [x] Add `"app.workers.orchestrator"` to `include` list
  - [x] Add `"app.workers.orchestrator.*": {"queue": "combined"}` to `task_routes`
  - [x] Add `worker_process_init` signal → calls `initialize_worker_redis()`
  - [x] Add `orchestrator` to worker import block

---

## Phase 3 — Rewrite Celery Workers ✅

> Goal: All workers use `publish_event()` instead of async Redis. LLM streams tokens. LaTeX streams log lines.

- [x] **Rewrite** `backend/app/workers/latex_worker.py`
  - [x] Remove all `asyncio.run()` calls
  - [x] Remove `job_status_manager` imports
  - [x] Import `publish_event`, `is_cancelled` from `event_publisher`
  - [x] `compile_latex_task(job_id, latex_content, ...)`:
    - [x] `publish_event(job_id, "job.started", {"worker_id": ..., "stage": "latex_compilation"})`
    - [x] Use `subprocess.Popen(cmd, stdout=PIPE, stderr=STDOUT, text=True)` instead of `subprocess.run`
    - [x] Stream stdout line by line: `for line in proc.stdout:` → `publish_event(job_id, "log.line", {...})`
    - [x] Progress events at key milestones (10%, 50%, 80%, 100%)
    - [x] Poll `is_cancelled(job_id)` between compilation passes
    - [x] On success: `publish_event(job_id, "job.completed", {...})`
    - [x] On error: `publish_event(job_id, "job.failed", {"stage": "latex_compilation", "error_code": "latex_error", ...})`

- [x] **Rewrite** `backend/app/workers/llm_worker.py`
  - [x] Remove all `asyncio.run()` calls
  - [x] Switch `AsyncOpenAI` → sync `openai.OpenAI`
  - [x] Remove `response_format={"type": "json_object"}` constraint (parse accumulated JSON at end)
  - [x] `optimize_latex_task(job_id, latex_content, job_description, ...)`:
    - [x] `publish_event(job_id, "job.started", {"worker_id": ..., "stage": "llm_optimization"})`
    - [x] `client.chat.completions.create(..., stream=True)`
    - [x] `for chunk in stream:` → extract `delta.content` → `publish_event(job_id, "llm.token", {"token": delta})`
    - [x] Accumulate full content in local string
    - [x] After loop: parse accumulated JSON for changes_made
    - [x] `publish_event(job_id, "llm.complete", {"full_content": ..., "tokens_total": ...})`
    - [x] Poll `is_cancelled(job_id)` every 10 tokens
    - [x] BYOK support: read user API key from encrypted DB, pass to `OpenAI(api_key=...)`
    - [x] On error: `publish_event(job_id, "job.failed", {"stage": "llm_optimization", "error_code": "llm_error", ...})`

- [x] **Modify** `backend/app/workers/ats_worker.py`
  - [x] Remove `asyncio.run(job_status_manager.set_job_status(...))` calls
  - [x] Import `publish_event`, `is_cancelled` from `event_publisher`
  - [x] Replace all status updates with `publish_event()` calls
  - [x] `ats_scoring_task(job_id, latex_content, job_description, ...)`:
    - [x] `publish_event(job_id, "job.started", {"worker_id": ..., "stage": "ats_scoring"})`
    - [x] Progress: `publish_event(job_id, "job.progress", {"percent": 50, "stage": "ats_scoring", "message": "Scoring resume..."})`
    - [x] Use `asyncio.run(ats_service.score_resume(...))` only for the pure-Python ATS service call (no Redis inside)
    - [x] On success: `publish_event(job_id, "job.completed", {...ats results...})`
    - [x] On error: `publish_event(job_id, "job.failed", {...})`

- [x] **Create** `backend/app/workers/orchestrator.py`
  - [x] `optimize_and_compile_task(job_id, latex_content, job_description, optimization_level, user_id, ...)`:
    - [x] `publish_event(job_id, "job.started", {"worker_id": ..., "stage": "llm_optimization"})`
    - [x] **Stage 1 — LLM** (10% → 40%): stream tokens via `llm.token`; publish `llm.complete` at end
    - [x] Check `is_cancelled(job_id)` after LLM stage
    - [x] `publish_event(job_id, "job.progress", {"percent": 40, "stage": "latex_compilation", ...})`
    - [x] **Stage 2 — LaTeX** (40% → 80%): `Popen` + stream `log.line` per stdout line
    - [x] Check `is_cancelled(job_id)` after compile stage
    - [x] `publish_event(job_id, "job.progress", {"percent": 80, "stage": "ats_scoring", ...})`
    - [x] **Stage 3 — ATS** (80% → 100%): `asyncio.run(ats_service.score_resume(...))` (pure Python, safe)
    - [x] `publish_job_result(job_id, {...complete result...})`
    - [x] `publish_event(job_id, "job.completed", {pdf_job_id: job_id, ats_score, ats_details, changes_made, compilation_time, optimization_time, tokens_used})`
    - [x] On any stage failure: `publish_event(job_id, "job.failed", {"stage": ..., "error_code": ..., "retryable": ...})`

---

## Phase 4 — FastAPI Event Bus ✅

> Goal: WebSocket endpoint forwards Redis Pub/Sub events to connected clients with replay support.

- [x] **Create** `backend/app/core/event_bus.py`
  - [x] `EventBusManager` class (one singleton per FastAPI process)
  - [x] `async def init(redis_client)` — store async Redis client
  - [x] `async def subscribe(job_id, websocket, last_event_id)`:
    - [x] Register websocket in `_connections[job_id]`
    - [x] If `last_event_id` provided: call `_replay_events(job_id, websocket, last_event_id)`
    - [x] Start `asyncio.create_task(_pubsub_listener(job_id))` if not already running
  - [x] `async def disconnect(job_id, websocket)`:
    - [x] Remove from `_connections[job_id]`
    - [x] If no more connections for job_id: cancel listener task
  - [x] `async def _pubsub_listener(job_id)`:
    - [x] `pubsub = redis.pubsub()`
    - [x] `await pubsub.subscribe(f"latexy:events:{job_id}")`
    - [x] `async for message in pubsub.listen():` → send to all `_connections[job_id]` WebSockets
    - [x] Handle WebSocket disconnects gracefully
  - [x] `async def _replay_events(job_id, websocket, last_event_id)`:
    - [x] `await redis.xread({stream_key: last_event_id}, count=500)`
    - [x] Send each entry's `payload` field to websocket
    - [x] Return `replayed_count`

- [x] **Create** `backend/app/api/ws_routes.py`
  - [x] `ws_router = APIRouter()`
  - [x] `@ws_router.websocket("/ws/jobs")` endpoint:
    - [x] `await websocket.accept()`
    - [x] Main receive loop:
      - [x] Handle `type: "subscribe"` → `event_bus.subscribe(job_id, ws, last_event_id?)`; reply `{"type": "subscribed", ...}`
      - [x] Handle `type: "unsubscribe"` → `event_bus.disconnect(job_id, ws)`
      - [x] Handle `type: "cancel"` → `redis.setex(cancel_key, 3600, "1")` + `celery_app.control.revoke()`
      - [x] Handle `type: "ping"` → reply `{"type": "pong", "server_time": time.time()}`
    - [x] On `WebSocketDisconnect`: disconnect all subscribed job_ids
  - [x] Background heartbeat task: send `sys.heartbeat` event every 30s

- [x] **Modify** `backend/app/main.py`
  - [x] Import `event_bus` from `core.event_bus`
  - [x] In `lifespan` startup: `await event_bus.init(async_redis_client)`
  - [x] In `lifespan` shutdown: cleanup event_bus connections

- [x] **Modify** `backend/app/api/job_routes.py`
  - [x] Remove `ConnectionManager` class (lines 74-144) entirely
  - [x] Remove all `connection_manager` usage
  - [x] Add `GET /jobs/{job_id}/state` → read `latexy:job:{job_id}:state`, return 404 if missing
  - [x] Add `GET /jobs/{job_id}/result` → read `latexy:job:{job_id}:result`, return 404 if missing
  - [x] Fix `ats_scoring` job type → route to `ats_worker.ats_scoring_task`
  - [x] Fix `cancel_job` → `redis.setex(cancel_key)` + `celery_app.control.revoke(terminate=True)`
  - [x] `POST /jobs/submit`: call `store_job_meta()` + `publish_event(job_id, "job.queued", {...})` before returning

- [x] **Modify** `backend/app/api/routes.py`
  - [x] Import `ws_router` from `api.ws_routes`
  - [x] `app.include_router(ws_router)` (no prefix — WebSocket path is `/ws/jobs`)

- [x] **Check** `backend/app/core/redis.py`
  - [x] Ensure async Redis client getter exported for `EventBusManager`
  - [x] Verify `redis.asyncio` used for async client (not `aioredis`)

---

## Phase 5 — Frontend Real-Time Layer ✅

> Goal: React hooks and WebSocket client that power live UI updates.

- [x] **Create** `frontend/src/lib/ws-client.ts`
  - [x] `WSClient` class with singleton export `wsClient`
  - [x] Private state: `_ws`, `_reconnectTimer`, `_pendingSubscriptions: Map<string, string | undefined>`
  - [x] `connect()`: open WebSocket to `getWebSocketUrl()`, wire all handlers
  - [x] Exponential backoff reconnect: 100ms → 200ms → 400ms → … → max 30s
  - [x] `onopen`: re-subscribe all entries in `_pendingSubscriptions`
  - [x] `subscribe(jobId, lastEventId?)`: send subscribe if connected; else buffer
  - [x] `unsubscribe(jobId)`: send unsubscribe, remove from pending
  - [x] `cancelJob(jobId)`: send `{type: "cancel", job_id: jobId}`
  - [x] `ping()`: send ping
  - [x] `on(event, handler)` / `off(event, handler)`: typed event emitter
  - [x] Events emitted: `"connected"`, `"disconnected"`, `"event"` (AnyEvent), `"subscribed"`, `"error"`
  - [x] `lastEventId` tracking per job_id for replay on reconnect
  - [x] Heartbeat: send ping every 25s when connected

- [x] **Create** `frontend/src/hooks/useJobStream.ts`
  - [x] `JobStreamState` interface: `{ status, percent, stage, message, streamingLatex, logLines, atsScore, atsDetails, changesMade, pdfJobId, compilationTime, optimizationTime, tokensUsed, error, errorCode, retryable }`
  - [x] `jobStreamReducer(state, action)` handling all `AnyEvent` types:
    - [x] `job.queued` → `status: "queued"`
    - [x] `job.started` → `status: "processing"`, update `stage`
    - [x] `job.progress` → update `percent`, `stage`, `message`
    - [x] `llm.token` → append to `streamingLatex`
    - [x] `llm.complete` → set `streamingLatex` to `full_content`
    - [x] `log.line` → append to `logLines` array
    - [x] `job.completed` → `status: "completed"`, set all result fields
    - [x] `job.failed` → `status: "failed"`, set `error`, `errorCode`, `retryable`
    - [x] `job.cancelled` → `status: "cancelled"`
  - [x] `useJobStream(jobId)`:
    - [x] Subscribe to `wsClient` on mount
    - [x] Unsubscribe on unmount or `jobId` change
    - [x] Route incoming events through dispatch
    - [x] Return `{ state, cancel }`

- [x] **Rewrite** `frontend/src/components/WebSocketProvider.tsx`
  - [x] Remove broken `getWebSocketUrl` import
  - [x] `WSContext = createContext<WSContextValue>(...)`
  - [x] `WSProvider` component: mount → `wsClient.connect()`; track `connected` state
  - [x] Export `useWS()` convenience hook
  - [x] Export `WSProvider` as default

- [x] **Modify** `frontend/src/hooks/useJobStatus.ts`
  - [x] Delegate to `useJobStream` internally
  - [x] Keep same public interface: `{ status, percent, stage, isComplete, isFailed, error }`

---

## Phase 6 — Live Monaco Editor + Log Viewer ✅

> Goal: LLM tokens stream into Monaco in real-time; pdflatex logs shown live.

- [x] **Modify** `frontend/src/components/LaTeXEditor.tsx`
  - [x] Forward `editorRef` via `forwardRef` / `useImperativeHandle`
  - [x] Export `LaTeXEditorRef` interface: `{ setValue(content: string): void; getValue(): string }`
  - [x] Set `editorRef.current` in `onMount` callback
  - [x] `readOnly?: boolean` prop

- [x] **Wire streaming tokens** in `frontend/src/app/try-new/page.tsx`
  - [x] Get `streamingLatex` from `useJobStream`
  - [x] `useEffect` → `editorRef.current?.setValue(streamingLatex)` (direct Monaco model mutation)
  - [x] **No React state per token** — React state syncs only on `llm.complete` / job completion
  - [x] Real-time progress bar (percent + stage), status badge, cancel button, PDF download button

- [x] **Create** `frontend/src/components/LogViewer.tsx`
  - [x] Props: `LogLine[]` (from useJobStream), `maxHeight`, `className`, `showLineNumbers`
  - [x] Auto-scroll to bottom on new lines (`useEffect([lines.length])` + `scrollIntoView`)
  - [x] Error lines in red (`text-red-400`), normal lines in gray, dark terminal theme

---

## Phase 7 — Integration & Verification ✅

> Goal: Full end-to-end flow works. All regression tests pass.

### Automated Test Suite — 88/88 passing
```
test/test_health.py      (5)  — API health, OpenAPI docs
test/test_auth.py        (10) — Session, JWT, cookie auth
test/test_jobs.py        (14) — Job submission, state, cancel, PDF, trial
test/test_ws.py          (10) — WebSocket protocol (ping, subscribe, cancel, replay)
test/test_event_bus.py   (23) — EventBusManager: lifecycle, replay, multi-job isolation
test/test_integration.py (26) — HTTP↔Redis consistency, cancel flag TTL, stream isolation
```

### Backend Smoke Tests (automated)
- [x] `POST /jobs/submit` with `latex_compilation` → `{job_id, success: true}`
- [x] Redis state written: `latexy:job:{id}:state`, `latexy:stream:{id}`, `latexy:job:{id}:meta`
- [x] WS subscribe/unsubscribe/ping/cancel/replay protocol verified (10 tests)
- [x] EventBusManager subscribe → listener task created (no duplicates)
- [x] EventBusManager replay: `XREAD` with `last_event_id` → events replayed in envelope format
- [x] Multi-job isolation: job A events never reach job B subscriber
- [x] Cancel flow: `DELETE /jobs/{id}` → `latexy:job:{id}:cancel = "1"` with TTL ≤ 3600s
- [x] Cancel is idempotent, does not affect other job IDs

### Frontend Build ✅
- [x] `pnpm build` passes with 0 TypeScript/ESLint errors
- [x] 12 routes generated, `/try-new` = 23.7 kB
- [x] Monaco editor wired for streaming tokens (direct model mutation, no per-token re-renders)
- [x] LogViewer component auto-scrolls, error lines in red
- [x] Progress bar, status badge, cancel button, PDF download button

### Regression Tests (automated)
- [x] Anonymous trial status endpoint: responds, has required fields, rejects missing fingerprint
- [x] Auth: session, JWT, cookie, expired token all correct
- [x] Job type routing: latex, combined, ats_scoring, llm_optimization all accepted
- [x] Multi-user job isolation: two submitted jobs have independent Redis state and streams
- [x] Cancel isolation: cancelling job A does not set cancel flag for job B
- [x] WebSocket isolation: EventBusManager routes events to correct subscribers only

---

## Files Reference

### New Files

| File | Status | Purpose |
|---|---|---|
| `backend/app/models/event_schemas.py` | ✅ Done | Pydantic event models + AnyEvent union + status helper |
| `backend/app/workers/event_publisher.py` | ✅ Done | Sync Redis publisher for workers |
| `backend/app/core/event_bus.py` | ✅ Done | EventBusManager: Redis Pub/Sub → WebSocket + replay |
| `backend/app/api/ws_routes.py` | ✅ Done | WebSocket endpoint `/ws/jobs` |
| `backend/app/workers/orchestrator.py` | ✅ Done | Full LLM→compile→ATS pipeline Celery task |
| `frontend/src/lib/event-types.ts` | ✅ Done | TypeScript event type definitions |
| `frontend/src/lib/api-client.ts` | ✅ Done | Typed REST client singleton |
| `frontend/src/lib/api.ts` | ✅ Done | Compatibility shim + legacy type shapes |
| `frontend/src/lib/ws-client.ts` | ✅ Done | WSClient singleton: reconnect + event emitter |
| `frontend/src/hooks/useJobStream.ts` | ✅ Done | useReducer hook for all event types |
| `frontend/src/components/LogViewer.tsx` | ✅ Done | Real-time pdflatex log viewer |
| `backend/test/test_event_bus.py` | ✅ Done | 23 EventBusManager unit tests (lifecycle, replay, isolation) |
| `backend/test/test_integration.py` | ✅ Done | 26 HTTP↔Redis integration tests |

### Rewritten Files

| File | Status | Key Changes |
|---|---|---|
| `backend/app/workers/latex_worker.py` | ✅ Done | Remove asyncio.run; Popen line-by-line; publish_event |
| `backend/app/workers/llm_worker.py` | ✅ Done | Sync OpenAI; stream=True; llm.token per chunk |
| `backend/app/workers/ats_worker.py` | ✅ Done | Replace asyncio.run + job_status_manager with publish_event |
| `frontend/src/components/WebSocketProvider.tsx` | ✅ Done | Remove broken import; wrap wsClient in React context |

### Modified Files

| File | Status | Changes |
|---|---|---|
| `backend/app/core/celery_app.py` | ✅ Done | Added orchestrator; worker_process_init signal |
| `backend/app/core/redis.py` | ✅ Done | Verified async client exported (get_redis_client) |
| `backend/app/main.py` | ✅ Done | `event_bus.init()` in lifespan |
| `backend/app/api/job_routes.py` | ✅ Done | Remove ConnectionManager; add state/result endpoints; fix cancel |
| `backend/app/api/routes.py` | ✅ Done | Include ws_router |
| `frontend/src/components/LaTeXEditor.tsx` | ✅ Done | Forward editorRef via forwardRef + useImperativeHandle |
| `frontend/src/hooks/useJobStatus.ts` | ✅ Done | Delegate to useJobStream |

### Preserved Files (Do Not Touch)

`ats_scoring_service.py`, `latex_service.py`, `latex_compiler.py`, `llm_service.py`, `encryption_service.py`, `payment_service.py`, `trial_service.py`, `api_key_service.py`, `format_detection.py`, `database/models.py`, `database/connection.py`, `auth_middleware.py`, `rate_limiting.py`, `parsers/`, `models/schemas.py`, `models/llm_schemas.py`, `app/page.tsx`, `app/layout.tsx`, `app/billing/`, `app/dashboard/`, `ATSScoreCard.tsx`, `components/ui/`, `useATSScoring.ts`, `useJobManagement.ts`

---

## Success Metrics

### Technical ✅
- [x] `pnpm build` passes with 0 TypeScript/ESLint errors (12 routes)
- [x] FastAPI starts without import errors
- [x] 88/88 automated tests pass (health, auth, jobs, ws, event_bus, integration)
- [x] All events flow: Celery → Redis Pub/Sub → EventBusManager → WebSocket → Frontend (verified by test_event_bus + test_integration)
- [x] Stream replay works on reconnect (verified: XREAD with last_event_id → events replayed in envelope format)
- [x] Job submit → Redis state key, stream entry, metadata all written (verified by test_integration)
- [x] Cancel sets Redis flag with correct TTL ≤ 3600s (verified by test_integration)

### UX ✅
- [x] LLM tokens stream into Monaco via direct model mutation (no per-token React re-renders)
- [x] pdflatex log lines render in real-time via LogViewer auto-scroll
- [x] Progress bar advances through all stages (percent + stage from useJobStream)
- [x] ATS score card appears on completion
- [x] PDF download button functional (visible when stream.pdfJobId is set)
- [x] Reconnect transparent to user (WSClient exponential backoff + auto-resubscribe)
- [x] Cancel button sets Redis cancel flag (workers poll is_cancelled() between stages)

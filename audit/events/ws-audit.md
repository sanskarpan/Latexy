# WebSocket & Event Audit — `/ws/jobs` and `/ws/collab/{resume_id}`

**Audit:** Latexy production audit v2 — Phase 5 (events sub-agent)
**Cohort:** `pro-monthly` (primary), with cross-user checks from `free` and `team-member`
**Primary identity:** `audit+pro-monthly-20261127103328@example.test` · user `2c27be6f-138f-4e98-b311-38892520b1eb` · plan `pro` · role `user`
**Cross-user identities:** free `96c507cd-e7a2-4749-9153-96b6321742db`; team member `7a3d3b80-000c-49f0-a067-96c177b7c848`
**Test window:** `2026-11-27T10:51:17Z` – `2026-11-27T11:25:33Z`
**Backend:** `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run` · WS `wss://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
**Deployment observed:** `/health` 200 `healthy`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421`; `/readyz` 200 `ready`; `/jobs/health` 200 `healthy`, all queue depths 0 at 11:25:33Z.
**Companion evidence:** [`audit/events/ws-observations.csv`](ws-observations.csv) — 75 rows, `EVT-001`…`EVT-075`.

## Verdict

| Surface | Verdict | Notes |
|---|---|---|
| `/ws/jobs` ticket auth and handshake | **PASS** | Unauthenticated 401; invalid/spent/expired/wrong-purpose tickets rejected; anonymous sockets accepted by design but cannot read owned jobs. |
| `/ws/jobs` protocol, limits, heartbeat | **PASS** | Ping/pong, 30 s heartbeat, 64 KiB frame cap, 20 msg/s per-connection cap, malformed-frame recovery all behave as documented. |
| `/ws/jobs` normal compile event path | **PASS** | 58/58 events matched the Redis Stream exactly; sequence 1–58 contiguous; one terminal; live lifecycle events delivered in 0.3–57.6 ms. |
| `/ws/jobs` replay and reconnect | **PASS (normal)** / **RISK (>500 events)** | Mid-stream replay, post-completion reconnect, multi-job multiplexing, and no-gap/no-duplicate checks pass. The 500-entry XREAD cap was not exercised because a verbose compile stalled. |
| `/ws/jobs` cancellation | **FAIL (exactly-once/order)** | One mid-compile cancel produces **two** `job.cancelled` events; sequence can invert (6 before 5). Repeated cancel is not idempotent. |
| `/ws/jobs` cross-user isolation | **PASS** | Free/team/anonymous cannot subscribe, cancel, or REST-replay a pro-owned job. |
| `/ws/collab` authorization | **PASS** | Non-collaborators close 4003; wrong ticket/resume closes 4001; owner and invited viewer work. |
| `/ws/collab` presence, chat, read-only | **PASS (function)** / **SLOW (latency)** | Bidirectional awareness and chat work; viewer writes are refused; chat relays in ~0.83 s per frame. |
| `/ws/collab` chat rate limit | **FAIL** | A 21-frame burst produced **0** `chat_rate_limited` denials; serialized processing (~0.83 s/frame) outlives the 10 s Redis window. |
| `/ws/collab` frame limits and revocation | **PASS** | 256 KiB+ update and >4 KiB chat dropped without closing; role change closes 4005; removal closes 4003; reconnect after removal is forbidden. |
| Event-to-UI render latency | **NOT MEASURED** | No authenticated browser session was available for the audit identity. Event-to-client is measured; client dedupe/reducer tests pass 46/46. |

No P0 was observed. The audit produced **six P2 defects** and **four P3 items**; the CSV has seven P2 evidence rows because `EVT-047` is the REST confirmation of WS-01. No global config, capability, plan, flag, or deploy change was made **by this sub-agent**; no live payment was attempted; no LLM call was made (all compiles were CPU-only).

---

## 1. Method and evidence rules

- Production was used directly. All HTTP calls carried the provisioned `pro-monthly` session token; cross-user calls used the provisioned free/team tokens.
- Tickets were minted through `POST /ws/ticket`; WebSockets were opened with `wss://…/ws/jobs?ticket=…` or `wss://…/ws/collab/{resume_id}?ticket=…`.
- Every HTTP response recorded `X-Request-Id` and `Modal-Function-Call-Id`. WebSocket evidence uses the job ID plus Redis Stream entry IDs; those are the trace identifiers for a socket event.
- **Redis Stream persistence** was verified through the authenticated owner endpoint `GET /jobs/{job_id}/stream`, which reads `latexy:stream:{job_id}` and returns the stored events in `XRANGE` order. No direct Redis shell was used.
- **Event-to-client latency** uses the Redis Stream entry ID (milliseconds at `XADD`) as the server send timestamp. The production server clock is ahead of the audit client by **0.6365 s**; values are normalized by subtracting the minimum `(receive_wall − stream_xadd)` across live events. The normalized p50/p95 are therefore transport/fanout latency, not clock skew.
- Request rate stayed within the prompt's ≤20 HTTP requests/minute ceiling (typically ~10–13/min). This was a boundary/protocol audit, **not a load test**; no 1/5/20/50-concurrency ramp, no slow-consumer backpressure test, and no network-partition emulation.
- Two early collab harness runs were discarded because their frame-window/drain accounting was wrong (they counted late live chat frames as replay). The clean runs `stage4b`/`stage4c` are the cited evidence.

## 2. Ticket auth and handshake matrix

| Test | Expected | Observed | Status | Evidence |
|---|---|---|---|---|
| `POST /ws/ticket` without auth | 401/403 | HTTP 401 | PASS | EVT-001, req `42ebb0ff…` |
| Jobs ticket, authenticated | 200, ticket, `expires_in=60` | HTTP 200, `expires_in=60` | PASS | EVT-002, req `3f8a339b…`, 3.73 s |
| Jobs ticket with `resume_id` | 400 (collab-only field) | HTTP 400 `http_error` | PASS | EVT-003, req `7c5914c5…` |
| Collab ticket without `resume_id` | 400 | HTTP 400 `http_error` | PASS | EVT-004, req `fdb3879e…` |
| Collab ticket with `resume_id` | 200 | HTTP 200, `expires_in=60` | PASS | EVT-005, req `6ede90d9…` |
| Ticket reuse (second handshake) | Rejected | HTTP 403 at handshake | PASS | EVT-006 |
| Invalid ticket string | Rejected | HTTP 403 at handshake | PASS | EVT-007 |
| Ticket older than 60 s | Rejected | HTTP 403 at handshake | PASS | EVT-008 |
| Collab-purpose ticket on `/ws/jobs` | Rejected | HTTP 403 at handshake | PASS | EVT-009 |
| Jobs-purpose ticket on `/ws/collab/{id}` | Close 4001 | Close `4001 Unauthorized` | PASS | EVT-010 |
| Collab malformed resume UUID | Close 4004 before DB/ticket | Close `4004 Resume not found`; ticket not spent | PASS | EVT-011 |
| Collab missing ticket | Close 4001 | Close `4001 Unauthorized` | PASS | EVT-012 |
| Collab ticket for resume A, socket resume B | Close 4001 | Close `4001 Unauthorized` | PASS | EVT-013 |
| Anonymous `/ws/jobs` without ticket | Accepted (owner-less trial support) | Accepted; ping/pong works | PASS (by design) | EVT-015 |
| Anonymous socket on an owned job | Forbidden | `error forbidden` with `job_id` | PASS | EVT-030 |

Notes:
- Tickets are single-use and purpose-bound; the 60 s expiry and second-handshake rejection were observed. Code also binds collab tickets to the resume ID; the real-resume mismatch test (`EVT-013`) confirms it.
- Anonymous sockets are accepted when no ticket is supplied. They still cannot subscribe to owned jobs (`EVT-030`); only owner-less trial jobs are reachable. That is the documented design, but it does mean possession of an owner-less job ID is sufficient to subscribe or cancel—worth recording as an access-model observation, not a defect.

## 3. `/ws/jobs` protocol and limits

| Test | Expected | Observed | Status | Evidence |
|---|---|---|---|---|
| Connect + ping/pong | `pong` with `server_time` | Connected in 993.8 ms; pong RTT 254.3 ms | PASS | EVT-014 |
| 64 KiB frame boundary | 65,536-byte frame accepted; 65,537 rejected | 64 KiB → pong; 64 KiB+1 → `message_too_large`; follow-up pong | PASS | EVT-016 |
| 20 msg/s per-connection limit | 20 admitted, excess `rate_limited` | 25-frame burst → 20 pongs, 5 `rate_limited`; after 1.2 s ping → pong | PASS | EVT-017 |
| Malformed JSON / unknown type / missing job_id | Error frames; socket stays open | `invalid_json`, `unknown_message_type`, `invalid_request` ×2, then pong | PASS | EVT-018 |
| Subscribe/cancel unknown job | `forbidden` (missing ownership metadata) | Both `forbidden` with `job_id`; socket stays open | PASS | EVT-019 |
| Heartbeat | `sys.heartbeat` every 30 s; `job_id=""`, `sequence=0` | Received at 30.7 s after connect; not in Stream | PASS | EVT-025 |
| `subscribed` ack ordering | Ack before replay per protocol doc | First frame was a replayed event; ack arrived after 1 event | OBSERVED / P3 | EVT-024 |

The 64 KiB guard is applied to the raw ASGI frame before JSON parsing, so oversized payloads are rejected without a large JSON allocation. The rate limiter counts malformed and oversized frames too; the observed 20/5 split matches the intended per-connection budget and recovers after one second.

## 4. Real compile: event trace, persistence, latency

**Job:** `ba3231c6-ef96-419b-a24d-d5930291425a` (pro-monthly; `latex_compilation`; submit request `894731c8-381b-4f80-894c-25993f3acd5c`).
**Submit:** HTTP 200, 6,216.3 ms; `estimated_time=21`.
**Socket:** ticket mint 2,213.1 ms; connect 993.8 ms; ping RTT 254.3 ms; subscription `last_event_id="0"`.

### 4.1 Event counts

| Type | Count |
|---|---:|
| `job.queued` | 1 |
| `job.started` | 1 |
| `job.progress` | 3 |
| `log.line` | 50 |
| `artifact.ready` | 1 |
| `job.pdf_extracted` | 1 |
| `job.completed` | 1 |
| **Total** | **58** |

Sequence values were exactly `1..58`; all 58 `event_id` values and all 58 Stream entry IDs were unique; Stream IDs were strictly monotonic; the only terminal event was `job.completed`. (`EVT-021`)

### 4.2 Key milestones

| Seq | Event | Stream entry | Server timestamp | Normalized delivery | Notes |
|---:|---|---|---|---:|---|
| 1 | `job.queued` | `1795776834392-0` | 834.392 | replay age 4.81 s | Replayed because submit returned after enqueue. |
| 2 | `job.started` | `1795776840387-0` | 840.388 | 0.3 ms | Live. |
| 3 | `job.progress` 5% | `1795776840601-0` | 840.601 | 3.0 ms | Live. |
| 4 | `job.progress` 10% | `1795776841453-0` | 841.453 | 0.3 ms | Live. |
| 56 | `artifact.ready` | `1795776858676-0` | 858.676 | 1.7 ms | Live. |
| 57 | `job.pdf_extracted` | `1795776861552-0` | 861.553 | 57.6 ms | Live. |
| 58 | `job.completed` | `1795776861766-0` | 861.766 | 5.3 ms | Live terminal. |

**Stage timing from event timestamps:** queued→started **5,995.5 ms**; started→artifact **18,288.7 ms**; artifact→completed **3,090.2 ms**; queued→completed **27,374.4 ms**. The HTTP submit itself took 6,216.3 ms and the `job.queued` event was already 4.81 s old when the client subscribed. The WebSocket delivery leg is not the dominant cost for this compile; queue/worker execution is.

### 4.3 Redis Stream persistence

`GET /jobs/ba3231c6…/stream` returned **58** events, exactly matching the WebSocket set by Stream ID and `event_id` (`EVT-022`). First entry `1795776834392-0`; last `1795776861766-0`. This is direct evidence that every observed WS job event was persisted in `latexy:stream:{job_id}` and re-readable by the owner. The Stream TTL is 24 hours by code; no direct Redis inspection was performed.

### 4.4 Event-to-client latency

- Live events: **57**; replayed: **1**.
- Normalized delivery: **p50 6.2 ms, p95 215.6 ms, max 216.6 ms** (`EVT-023`).
- Lifecycle events (`started`, `progress`, `artifact.ready`, `pdf_extracted`, `completed`) delivered in **0.3–57.6 ms**. The p95 is driven by bursts of `log.line` events in the 165–217 ms band, not by the terminal path.
- The replayed `job.queued` was 4.81 s old at receipt; that is replay age, not delivery latency.
- **Event-to-UI render was not measured.** The audit identity is a backend session token, not a Better Auth browser session. The same frames are consumed by `wsClient` + `jobStreamReducer` in the frontend; the client dedupe/reducer tests pass **46/46** locally (`EVT-071`), but that is not a production paint measurement.

## 5. Replay, reconnect, duplicate suppression

| Test | Expected | Observed | Status | Evidence |
|---|---|---|---|---|
| Replay from mid-stream `last_event_id` (seq 20 watermark) | Exactly later events | `replayed_count=38`; first seq 21; last `job.completed` | PASS | EVT-026 |
| Full replay on fresh subscribe (`last_event_id="0"`) | All stored events; duplicates possible | 58 events replayed; all 58 `event_id`s repeat | OBSERVED | EVT-027 |
| Client duplicate suppression | Drop non-newer Stream IDs | `isNewerStreamId` logic passes 46/46 tests | PASS (client) | EVT-071 |
| `last_event_id` = event's `event_id` (UUID) | Accept event ID or reject explicitly | `replayed_count=0`, zero events, **no error frame** | OBSERVED / P2 | EVT-028 |
| Disconnect mid-compile, reconnect after completion | Replay missed events incl. terminal | 49 missed events replayed; last `job.completed` | PASS | EVT-037 |
| Reconnect no gap/duplicate | Pre-disconnect + replay == full Stream | 4 + 49 = 53; exact match; 0 duplicates | PASS | EVT-038 |
| Multi-job on one socket | Each job replays its own Stream | Acks 58 and 53; both exact | PASS | EVT-044 |

The server does **not** suppress duplicates across a fresh/full replay; it is a per-socket replay, and the frontend dedupes by monotonic Stream ID. That split is important: the production UI is protected, but the wire protocol and durable Stream can contain duplicates (see cancellation, below). The `last_event_id` field is used directly as an `XREAD` Stream ID; passing an `event_id` UUID is silently swallowed by the exception path and returns zero events with no error. A third-party client following the field name would lose the terminal event. This is a P2 API-contract defect.

**500-entry replay cap:** `event_bus._replay_events` performs a single `XREAD … count=500`; it does not loop. The normal 58-event job is safe. A job with more than 500 events and an early watermark could truncate replay before the terminal event. This was **not exercised** because the verbose compile probes stalled (see §10, WS-08); the risk is recorded as `BLOCKED` / `EVT-074`, not asserted as a production failure.

## 6. Multi-client, unsubscribe, disconnect

**Job:** `89cf20bc-b710-417f-a41f-31fdd23167a1`.

- Two sockets connected (1,290.6 ms and 1,213.3 ms) and both subscribed with `last_event_id="0"` (`EVT-033`).
- Both received the same 4 ordered events up to the first live `job.progress` (`EVT-039`).
- Socket A sent `unsubscribe` and received **0** job events afterwards; only connection-level heartbeats continued (`EVT-034`). That is correct: unsubscribe stops job delivery, not the socket heartbeat.
- Socket B closed after the first live progress while the job was still running (`EVT-035`). The job completed with no subscriber; REST state became `completed` after 4 polls (`EVT-036`).
- Reconnect with the last-seen Stream ID `1795777373042-0` replayed **49** missed events, including `job.completed`; pre-disconnect 4 + replay 49 = the full 53-event Stream, with no gap and no duplicate (`EVT-037`, `EVT-038`).

There is no server `unsubscribed` acknowledgment in the protocol; the frontend type union includes one, but the server only sends `subscribed`, `event`, `pong`, and `error`. That is a harmless protocol/documentation mismatch unless a client waits for an ack.

## 7. Cancellation — the main correctness failure

### 7.1 Cancel before worker start — behavior passes

Job `c5b31fe8-54b7-4298-95aa-7137f5a0d415`: submit 3,870.6 ms; WS connect 1,260.2 ms; cancel 1,261.5 ms after connect. Events: `job.queued` → `job.cancelled` (no `job.started`). REST state `cancelled`; result `success=false`, `error="Job cancelled"` (`EVT-040`, `EVT-043`). Cross-user cancel by the free user was rejected `forbidden` (`EVT-042`).

### 7.2 Cancel mid-compile — two terminal events and sequence inversion

Job `8a270ee7-5a68-4cf3-a857-6fa92f78169f`: heavy compile; cancel sent 3 s after `job.started`. The socket saw `job.queued`, `job.started`, `job.progress` ×2, `job.cancelled`; state `cancelled` (`EVT-045`). The durable Stream, however, contained **6** events:

| Stream entry | Sequence | Type | Server timestamp |
|---|---:|---|---:|
| `1795778082503-0` | **6** | `job.cancelled` | 8082.503 |
| `1795778082672-0` | **5** | `job.cancelled` | 8082.539 |

The later XADD (`…2672-0`) carries the **lower** sequence (5). One user action produced two terminal events, and the `sequence` field is not monotonic in Stream order (`EVT-046`). The frontend reducer ignores the duplicate terminal and the UI is protected, but the durable Stream, replay, and any analytics consumer are not exactly-once.

### 7.3 The duplication is systemic, not WS-only

- A repeated WS cancel produced a second `job.cancelled` entry (seq 2 and 3) for `c5b31fe8…` (`EVT-041`).
- REST `DELETE /jobs/c6096e9a-e248-4600-834c-dffb3813a331` during a running compile returned 200, state became `cancelled`, and the Stream contained 6 events including **two** `job.cancelled` (`EVT-047`, request `ac9c1d0b…`).
- The same happened for `a25593bd-34e5-4d66-bff5-5723cd634096` (`EVT-048`).

The likely shape is two publishers: the WS/REST provisional `_request_cancellation` path and the worker's terminal `job.cancelled` path. Both allocate a sequence and XADD, but not atomically as a pair; the result is duplicate terminal events and, under race, inverted sequence. A completed job cancel is correctly a no-op (`EVT-032`).

**Impact:** cancel semantics work for the UI, but the event contract (“exactly once”) and ordering are violated. Cancellation analytics that count Stream events can double count; consumers that assume `sequence` monotonicity can misorder. Severity **P2** (`P1` if cancellation dashboards count Stream events directly).

## 8. Cross-user isolation

- Free user on pro job `ba3231c6…`: `subscribe` → `forbidden`; `cancel` → `forbidden`; socket stayed open (`EVT-029`).
- Anonymous socket on the same owned job: `subscribe` → `forbidden` (`EVT-030`).
- REST `GET /jobs/ba3231c6…/stream`: free token **403**, anonymous **403**, owner **200** (`EVT-031`, free request `be8cf063…`, owner request `93bdc51c…`).
- Collab: free and team-member non-collaborators closed `4003 Forbidden`; pro user on the free user's resume closed `4003` (`EVT-050`–`EVT-052`).

No cross-user event leakage was found.

## 9. `/ws/collab/{resume_id}`

### 9.1 Authorization and resume scoping

| Test | Observed | Status | Evidence |
|---|---|---|---|
| Free non-collaborator on pro resume | Close `4003 Forbidden` | PASS | EVT-050 |
| Team member non-collaborator on pro resume | Close `4003 Forbidden` | PASS | EVT-051 |
| Pro user on free user's resume | Close `4003 Forbidden` | PASS | EVT-052 |
| Jobs-purpose ticket on collab path | Close `4001 Unauthorized` | PASS | EVT-010 |
| Collab ticket for resume A on resume B | Close `4001 Unauthorized` | PASS | EVT-013 |
| Malformed resume UUID | Close `4004`; ticket not spent | PASS | EVT-011 |
| Missing ticket | Close `4001` | PASS | EVT-012 |

### 9.2 Owner, viewer, read-only, presence, chat

- Pro and free test resumes were created 201 (`EVT-049`). Owner `7180a217…` connected in 1,380.6 ms; `SYNC_STEP1` returned the empty-document `SYNC_STEP2` payload `00 00`; no read-only notice (`EVT-053`). Owner seeded update `U1 = 10 11 12`; no self-echo (`EVT-054`).
- Invite free user as `viewer`: HTTP 201, request `a8181a5a…` (`EVT-055`).
- Viewer connected and immediately received `MSG_PERMISSION_DENIED` with `code=read_only` and message “Your role does not allow editing this document” (`EVT-056`).
- Viewer `SYNC_STEP1` catch-up returned `U1` (`EVT-057`).
- Presence was bidirectional: owner received viewer awareness `09 0a 0b`; viewer received owner awareness `0c 0d 0e` (`EVT-058`).
- Viewer `MSG_UPDATE` `U2` was refused `read_only`; the owner's update count did not change (`EVT-059`).
- Chat was bidirectional. The server supplied canonical labels: viewer chat arrived at owner as `sender_label="Audit free"`; owner chat arrived at viewer as `sender_label="Audit pro-monthly"`. Frames were not echoed to the sender (`EVT-060`). Chat is ephemeral and not persisted; after both peers drained and the owner reconnected, catch-up had **1** sync frame (empty document) and **0** chat frames (`EVT-064`).

### 9.3 Reconnect, role change, removal

- Owner reconnect catch-up replayed `U1` and `U3` in order (`EVT-063`). The first attempt's “chat replay” was late live chat from a still-open peer; the clean rerun with peers drained shows zero chat frames.
- `PATCH` viewer→editor returned 200 and closed the live viewer socket with **4005 Role changed** (`EVT-065`, request `c07c6fa7…`).
- The reconnected editor's update `U4 = 40 41 42` relayed to the owner (`EVT-066`).
- `DELETE` collaborator returned 204 and closed the live editor socket with **4003 Access removed** (`EVT-067`, request `28c9cfcc…`); a subsequent reconnect was `4003 Forbidden` (`EVT-068`).

### 9.4 Frame limits and chat rate limit

- A 256 KiB+ binary update and a >4 KiB chat frame were silently dropped; the socket stayed open and a following `SYNC_STEP1` still returned catch-up (`EVT-062`).
- There is **no general non-chat frame rate limit**. Awareness and update frames are bounded only by the 256 KiB size cap; oversized frames are fully received by the ASGI server before the application drops them. Recorded as P3 (`EVT-073`).
- **Chat rate limit fails under observed throughput.** A 21-frame burst from the viewer produced **0** `chat_rate_limited` denials while the harness waited 20 s (24.7 s elapsed including setup). With the measured chat relay latency of ~0.83 s/frame (`EVT-069`: 841.0, 821.5, 829.4 ms), 21 frames span ~17.5 s, longer than the 10 s Redis window. The limiter increments at processing time, so the window expires before the 21st frame. A client can queue a burst that is delivered slowly instead of being rate-limited (`EVT-061`, P2).
- The ~0.83 s/frame chat latency is itself a P2 for interactive chat. Per-frame `has_access` performs entitlement + DB checks for each recipient; chat also performs a pre-send ACL check. Presence/awareness likely shares the per-recipient cost, though only chat was timed.

## 10. Latency summary

| Measurement | n | p50 | p95 | max | Notes |
|---|---:|---:|---:|---:|---|
| `POST /ws/ticket` | 29 | 2,178.9 ms | 2,796.3 ms | 3,043.0 ms | Every reconnect mints a fresh ticket over HTTP. |
| `/ws/jobs` and `/ws/collab` connect | 14 | 1,018.0 ms | 1,418.8 ms | 1,422.9 ms | TLS + Modal admission. |
| Jobs pong RTT | 2 | — | — | 254.8 ms | Ping/pong on a warm socket. |
| Job event-to-client (live) | 57 | 6.2 ms | 215.6 ms | 216.6 ms | p95 driven by `log.line` bursts; lifecycle events 0.3–57.6 ms. |
| Collab chat send→peer | 3 | 829.4 ms | — | 841.0 ms | Same resume, one peer; ACL/DB per frame. |
| Job submit HTTP | 6 | ~3.7 s | ~6.2 s | 6,216.3 ms | Backend/Modal admission, not WS. |
| Heartbeat interval | 1 | — | — | 30.7 s | `sys.heartbeat` after connect. |

A real network-loss reconnect pays the ticket mint (~2.2 s p50) plus the WS upgrade (~1.0 s p50) before replay, roughly **3.2 s** before the client can resubscribe. That is an observation (`EVT-072`, P3), not a correctness failure.

## 11. Defects

### WS-01 — Mid-compile cancel emits two terminal events and can invert sequence (P2)
**Surface:** `/ws/jobs` cancel, `_request_cancellation` + worker terminal path.
**Evidence:** Job `8a270ee7-5a68-4cf3-a857-6fa92f78169f`, Stream entries `1795778082503-0` (seq 6) and `1795778082672-0` (seq 5), both `job.cancelled`; one user cancel. REST cancel reproduces the same duplicate on `c6096e9a…` and `a25593bd…`.
**Expected:** exactly one terminal event per job; sequence monotonic in Stream order.
**Actual:** two `job.cancelled` events; later XADD has lower sequence.
**Impact:** UI reducer ignores the duplicate, but durable Stream/replay/analytics are not exactly-once; consumers assuming monotonic `sequence` misorder. P1 if cancellation analytics counts Stream events.
**Proposed fix:** make one component the sole terminal publisher (arbiter), or make the provisional cancellation event idempotent and suppress/fence the worker's duplicate; allocate sequence and XADD atomically per job and never accept a lower sequence after terminal.

### WS-02 — Repeated cancel is not idempotent (P2)
**Surface:** `/ws/jobs` cancel.
**Evidence:** Job `c5b31fe8-54b7-4298-95aa-7137f5a0d415`: two `job.cancelled` entries (seq 2 and 3) after a second cancel sent post-terminal (`EVT-041`).
**Expected:** a cancel after terminal is a no-op or returns an explicit “already terminal” result.
**Actual:** another terminal Stream entry is appended.
**Impact:** double-click / retry produces duplicate terminal events and analytics noise. UI dedupes.
**Proposed fix:** check the finalization arbiter outcome before publishing; return an ack/no-op; dedupe terminal events by `(job_id, terminal_type)`.

### WS-03 — `last_event_id` silently accepts only Stream IDs; `event_id` loses all replay (P2)
**Surface:** `/ws/jobs` subscribe replay.
**Evidence:** Passing `event_id` UUID `…` as `last_event_id` → `replayed_count=0`, zero events, no error (`EVT-028`). Passing a Stream ID works (`EVT-026`).
**Expected:** the field named `last_event_id` accepts the event ID it names, or rejects non-Stream IDs explicitly.
**Actual:** `XREAD` raises on the UUID; `_replay_events` catches and returns 0; the client sees a successful `subscribed` with no events.
**Impact:** third-party/API clients that follow the field name silently lose replay, including the terminal event.
**Proposed fix:** rename to `last_stream_id`; validate `^\d+-\d+$`; return `error invalid_request` with `job_id` on malformed values; optionally resolve `event_id` to its Stream entry.

### WS-04 — Collab chat rate limit is ineffective at observed throughput (P2)
**Surface:** `/ws/collab/{resume_id}` `MSG_CHAT`.
**Evidence:** 21-frame burst → 0 `chat_rate_limited` denials while waiting 20 s (24.7 s elapsed incl. setup); relay ~0.83 s/frame (`EVT-061`, `EVT-069`).
**Expected:** 20 frames per 10 s per user/resume; 21st rejected.
**Actual:** the Redis counter increments when each frame is processed; serialized ACL/entitlement/DB work stretches 21 frames beyond the 10 s window, so the counter resets and no denial is emitted.
**Impact:** spam/abuse control is ineffective; a client can queue a large burst that is slowly delivered while consuming DB/entitlement work per frame.
**Proposed fix:** token-bucket at frame ingress before ACL work; cap per-connection queue depth; cache connection authorization with event-driven invalidation; use receive-time accounting.

### WS-05 — Collab chat relay is ~0.83 s per frame (P2)
**Surface:** `/ws/collab/{resume_id}` chat/presence fan-out.
**Evidence:** 841.0 / 821.5 / 829.4 ms send→peer for three consecutive chats (`EVT-069`).
**Expected:** interactive chat should be well under 500 ms at p95; no explicit SLO was found.
**Actual:** per-frame `has_access` performs entitlement + DB checks for each recipient; chat also runs a pre-send ACL check.
**Impact:** chat feels laggy; presence likely shares the cost. This is also the root cause of WS-04.
**Proposed fix:** cache the connection's ACL/capability for a short TTL and invalidate on role change/removal (the revocation paths already exist); batch or parallelize recipient checks.

### WS-06 — `subscribed` ack arrives after replay events (P3)
**Surface:** `/ws/jobs` subscribe.
**Evidence:** First frame was `job.queued`; `subscribed` arrived after 1 replay event (`EVT-024`).
**Expected:** protocol doc implies the ack first.
**Actual:** replay is sent inside `event_bus.subscribe`, then the handler sends the ack.
**Impact:** a strict client that buffers events until `subscribed` would drop the replayed prefix; the production frontend handles pre-ack events.
**Proposed fix:** send the ack before replay, or document the ordering explicitly.

### WS-07 — No general collab frame rate limit; oversized frames are fully received (P3)
**Surface:** `/ws/collab/{resume_id}` non-chat frames.
**Evidence:** Only chat has a rate limit; 256 KiB+ binary dropped after full receive; socket stayed open (`EVT-062`, `EVT-073`).
**Expected:** a per-connection frame/byte budget for all collab frames.
**Actual:** awareness/update frames are bounded only by size, not rate; the ASGI server reads the full frame before the app drops it.
**Impact:** a peer can force repeated large reads and Redis/fan-out work; no load test was run, so the practical ceiling is unknown.
**Proposed fix:** add a per-connection token bucket at ingress and a queue-depth cap; reject early where the server supports it.

### WS-08 — Verbose compile stalled at 10%; >500-event replay test blocked (P2, adjacent)
**Surface:** compile worker → `log.line` publication / WS event path.
**Evidence:** Jobs `c6096e9a…` and `a25593bd…` (LaTeX with ~620 `\typeout` lines) stayed at `processing`, `percent=10` with only 4 Stream events; `c6096e9a` was still at 10% ~48 s after its last progress event, and `a25593bd` was still at 10% after 124 s. Both were cancelled; cancel then produced the usual two `job.cancelled` entries. (`EVT-048`)
**Expected:** a valid compile completes and emits log lines; replay cap can then be tested.
**Actual:** no log/terminal events; worker appeared stalled. Root cause not diagnosed; log publication/backpressure or transcript handling is suspected.
**Impact:** core compile flow can stall for a synthetic verbose document (one run ~48 s at 10%, one >120 s); if reproducible with normal input, this is P1. It blocked `EVT-074`.
**Proposed fix/handoff:** reproduce with the reliability/performance auditor, inspect worker CPU/transcript buffer/Redis publish path, and add a completion timeout/terminal fallback. Do not attribute to WebSocket without worker-side evidence.

### WS-09 — Ticket mint + connect adds ~3.2 s before reconnect replay (P3)
**Surface:** `/ws/jobs` reconnect.
**Evidence:** ticket p50 2,178.9 ms (n=29); connect p50 1,018.0 ms (n=14) (`EVT-072`).
**Expected:** reconnect after network loss resumes promptly.
**Actual:** the frontend must mint a fresh single-use ticket over HTTP before each upgrade; the ticket call is the long pole.
**Impact:** user sees a ~3 s gap before missed events replay; exponential backoff adds more.
**Proposed fix:** short-lived reusable reconnect ticket, or broker-issued ticket cache; separate metric from WS delivery.

### WS-10 — Replay is capped at 500 entries (P3, blocked)
**Surface:** `/ws/jobs` replay.
**Evidence:** `event_bus._replay_events` calls `XREAD … count=500` once; 58-event job replay exact; >500-event test blocked by WS-08 (`EVT-074`).
**Expected:** every stored event needed to reach the terminal is replayed.
**Actual:** a single 500-entry read; a job with >500 events and an early watermark silently truncates before terminal.
**Impact:** reconnect/replay loss for very verbose jobs; the REST fallback may mask it in the UI.
**Proposed fix:** loop `XREAD` until no entries remain (bounded by Stream max length/time), or page by count and verify the terminal is included.

## 12. Observations and non-defects

- **Anonymous sockets are accepted without a ticket** (by design for owner-less trial jobs). They cannot read owned jobs, but an owner-less job ID is sufficient to subscribe/cancel. EVT-015, EVT-030.
- **Server-side duplicate replay on a fresh subscribe is expected**; the client dedupes by monotonic Stream ID. 46/46 client tests pass; the server does not maintain a per-socket watermark. EVT-027, EVT-071.
- **No unsubscribe/cancel ack.** The protocol defines only `subscribed`, `event`, `pong`, `error`; the frontend type union includes `unsubscribed`/`cancelled` but the server never sends them. Harmless unless a client waits for an ack.
- **Heartbeat is connection-level** and continues after unsubscribe; observed on socket A after it stopped receiving job events. EVT-034.
- **Event-to-client p95 215.6 ms** is acceptable without an SLO but is ~35× the p50; it is driven by `log.line` bursts, not lifecycle events. A future optimization could coalesce log lines.
- **Collab chat `sender_id` is a per-connection UUID, not the user ID**; the display identity is the server-derived `sender_label`. That avoids leaking user IDs but means clients cannot correlate a sender across a reconnect by `sender_id` (`EVT-060`).
- **Chat rate-limit test used no peer** for the 21-frame burst (to isolate the limiter). “Relayed” count is therefore not meaningful; the absence of a denial and the measured per-frame latency are the evidence.
- **The verbose compile stall is synthetic-input-specific** (620 `\typeout` lines). It is recorded as a handoff, not a general production outage.

## 13. Coverage matrix vs the brief

| Brief item | Result | Evidence |
|---|---|---|
| `/ws/jobs` ticket auth | PASS | EVT-001–013 |
| Subscribe / unsubscribe | PASS | EVT-019, EVT-034, EVT-039 |
| Ping/pong | PASS | EVT-014 |
| Ordering | PASS normal; FAIL cancel | EVT-021, EVT-046 |
| Duplicate suppression | Client PASS; server duplicates on replay | EVT-027, EVT-071 |
| Replay with `last_event_id` | PASS Stream ID; FAIL UUID misuse | EVT-026, EVT-028 |
| Disconnect/reconnect during compile | PASS | EVT-035–038 |
| Cancel | PASS behavior; FAIL exactly-once | EVT-040–047 |
| Cross-user isolation | PASS | EVT-029–031, EVT-042, EVT-050–052 |
| Frame/rate limits | Jobs PASS; collab size PASS; chat rate FAIL | EVT-016, EVT-017, EVT-061, EVT-062 |
| Real compile job ID | `ba3231c6-ef96-419b-a24d-d5930291425a` | EVT-020–023 |
| Event sequence | 1..58 contiguous | EVT-021 |
| Redis Stream persistence | 58/58 exact | EVT-022 |
| Event-to-client latency | p50 6.2 ms / p95 215.6 ms | EVT-023 |
| Event-to-UI latency | NOT MEASURED | §4.4, §14 |
| Heartbeat | 30.7 s | EVT-025 |
| Collab auth / read-only / presence / chat / reconnect | PASS | EVT-050–068 |
| Collab rate limit | FAIL | EVT-061 |
| Collab frame limit | PASS | EVT-062 |
| Cross-tenant isolation | PASS | EVT-051, EVT-052 |
| >500-event replay | BLOCKED | EVT-074 |

## 14. Artifacts, cleanup, and state

### Jobs created (all terminal; Redis TTL 24 h)

| Job ID | Purpose | Final state |
|---|---|---|
| `eb79ac7f-7d99-4f9a-97a1-13b50fb6c74f` | initial compile probe | completed |
| `ba3231c6-ef96-419b-a24d-d5930291425a` | main 58-event compile | completed |
| `0d1351eb-ee8d-4321-ab5d-121670034570` | discarded stage-3 harness | completed |
| `268d6fe2-4c2a-4916-b8cd-0b3a90f6db21` | discarded stage-3 cancel | completed |
| `89cf20bc-b710-417f-a41f-31fdd23167a1` | multi-client / reconnect | completed |
| `c5b31fe8-54b7-4298-95aa-7137f5a0d415` | pre-start cancel | cancelled |
| `8a270ee7-5a68-4cf3-a857-6fa92f78169f` | mid-compile cancel / sequence inversion | cancelled |
| `c6096e9a-e248-4600-834c-dffb3813a331` | verbose compile stall (REST cancel) | cancelled |
| `a25593bd-34e5-4d66-bff5-5723cd634096` | verbose compile stall (WS read) | cancelled |

No job is still running; `/jobs/health` queue depths were all 0 at 11:25:33Z. The Redis Streams and job state expire after 24 h; DB `Compilation`/job rows may remain under normal retention. `DELETE /jobs/{id}` was used only to cancel the two stalled jobs, not to delete job records; the cleanup auditor should purge the audit job IDs if a clean launch state is required.

### Resumes / collaborators

| Resource | ID | Status |
|---|---|---|
| Pro collab resume | `7180a217-86cb-486c-aa4e-77cd931e0a33` | deleted 204 (request `9615e630…`) |
| Free collab resume | `598e8e65-80c3-4dad-9d99-3f4ad0028cc2` | deleted 204 (request `9cad4f67…`) |
| Chat-rate resume | `cbaf5137-2234-45ba-84ff-d1dbae55d932` | deleted 204 |
| Chat-rate resume 2 | `d3e5e305-b4f0-4771-901b-b0c2534d66c7` | deleted 204 |
| Free collaborator rows on the above | user `96c507cd…` | removed 204 in each case (`EVT-070`) |

### Changes and spend

- **Global configuration/capability/plan/flag changes:** none by this sub-agent.
- **Deploy:** none by this sub-agent.
- **Live payments:** none.
- **LLM calls:** none by this sub-agent; all jobs were `latex_compilation` (CPU only). The pro plan has unlimited compiles, so no quota was consumed in a way that needs restoration.
- **Free account:** created/deleted test resumes and sent chat frames only; no free compile quota spent.
- **Tickets:** dozens minted across the stages (the latency sample alone contains 29 successful mints); every ticket was consumed, expired, or unused-and-expired within 60 s. No persistent ticket artifact.

## 15. Limitations

1. **Event-to-UI render not measured.** The provisioned identity is a backend session token; there was no authenticated Better Auth browser session for the audit. The client reducer/dedupe code is covered by 46 passing vitest tests, but production paint/JS main-thread latency is unmeasured.
2. **No load test.** No 1/5/20/50 concurrent compiles, no slow-consumer backpressure, no sustained frame flood. Conclusions about rate/throughput ceilings are bounded by the observed single-client behavior.
3. **Clean closes, not network partitions.** Disconnect/reconnect used an orderly WebSocket close; a real TCP drop may behave differently at the proxy.
4. **Redis inspected through REST.** `GET /jobs/{id}/stream` reads the Stream; no direct Redis `XRANGE`/`XLEN` or memory inspection was performed.
5. **Clock skew.** Server time was ahead of the client by 0.6365 s; event delivery figures are normalized. Absolute receive ages include that offset.
6. **>500-event replay and the verbose compile stall** remain unexercised/unexplained; see WS-08/WS-10. They are the main open questions for the reliability auditor.
7. **Collab chat rate-limit test** used a viewer with no peer to isolate the limiter; per-recipient fan-out cost was measured separately in the relay-latency test.
8. **Single region/client.** No geographic or multi-worker fan-out comparison; the backend may run multiple uvicorn workers and the collab Pub/Sub bridge was not stressed across processes.

## 16. Handoff

- **Backend / events owner:** WS-01/WS-02 (single terminal publisher, idempotent cancel, atomic sequence+XADD), WS-03 (`last_stream_id` validation), WS-06 (ack ordering), WS-10 (loop replay past 500).
- **Collab owner:** WS-04/WS-05 (ingress token bucket, cached authorization, queue cap), WS-07 (general frame budget).
- **Reliability/performance auditor:** reproduce WS-08 with worker-side telemetry (CPU, transcript buffer, Redis publish, worker timeout) and then exercise the >500-event replay cap. This is the only blocked correctness test in this report.
- **Analytics auditor:** check whether cancellation dashboards count `job.cancelled` Stream entries; if so, WS-01/WS-02 cause double counting. Compare a known job's two cancel entries against the dashboard.
- **Cleanup auditor:** purge the nine terminal audit jobs and their Redis Streams if a clean launch state is required; all test resumes and collaborator rows are already deleted.

---

**Bottom line:** `/ws/jobs` is functionally healthy for the normal compile path—ticket auth, limits, ordering, persistence, replay, fan-out, and cross-user isolation all have production evidence. The defects are concentrated in cancellation exactly-once/ordering and in the replay contract (`last_event_id`), not in basic delivery. `/ws/collab` authorization and read-only behavior are solid, but chat is slow and its rate limit does not actually bound a burst at the observed processing rate.

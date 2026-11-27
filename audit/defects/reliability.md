# Defect records — Reliability: failure, quota, idempotency, recovery

- **Audit window:** 2026-11-27T11:22:52Z – 2026-11-27T11:52:05Z (UTC)
- **Environment:** production backend `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421` (`/health` at 11:22:52Z and 11:48:30Z); `/readyz` 200; `/jobs/health` 200 with all queue depths 0.
- **Identities:** `free` `96c507cd-e7a2-4749-9153-96b6321742db`; `basic-annual` `2f49586c-570d-4802-82bc-187ec0a516df`; `basic-monthly` `0e0b7f8d-e7d0-48da-9e66-dcee3e52f0cb`; operator `admin-superadmin` `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad`. Suffix `20261127103328`.
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\reliability_evidence.jsonl` (220 request/response captures with `X-Request-Id`), plus read-only PostgreSQL queries for `compilations`, `job_finalizations`, `admin_audit_log`, and `users`. No secrets are reproduced here.
- **Status:** all records are open; no fixes were attempted. Per-account mutations used for the mid-job tests were restored and verified (§ Cleanup in the cohort report).
- **Global configuration:** no global capability, plan-catalog, feature-flag, or deployment change was made.

| ID | Sev | Title | Cohort |
|---|---|---|---|
| R-D01 | **P2** | Job submission is not idempotent: retries/double-clicks create duplicate jobs and charge duplicate quota | All plans |
| R-D02 | **P2** | Cancellation is not idempotent and emits multiple `job.cancelled` terminal events | All plans |
| R-D03 | **P2** | Large valid document retries at 90% and hangs past the plan and worker timeouts; the cancelled job keeps its quota unit | Basic annual (likely all plans) |
| R-D04 | **P3** | 429 body does not use the standard error envelope; no proactive rate-limit headers | BYOK / developer surfaces |
| R-D05 | **P3** | Failed compile result is the generic `"Job failed"`; the typed error exists only in the event stream and DB | All plans, Developer API |
| R-D06 | **P3** | RTL/Arabic/Hebrew is not supported by the default engine; xelatex silently emits replacement glyphs | All plans |

---

## R-D01 — P2 — Job submission is not idempotent

**Surface:** `POST /jobs/submit` (and by inspection `POST /api/v1/compile`); the frontend `submitJob` path (`frontend/src/hooks/useJobManagement.ts:138-177`, `frontend/src/lib/api-client.ts:8353-8362`). The client sends no idempotency key; `isSubmitting` is a per-component boolean, and the offline/reconnect reservation is explicitly process-local and not a cross-tab lock (`frontend/src/lib/reconnect-reservations.ts:1-12`).

**Cohorts / users:** `basic-annual` `2f49586c-570d-4802-82bc-187ec0a516df`; applies to every authenticated plan and to the developer API.

**Repro (observed):**

1. Send two identical `POST /jobs/submit` requests in parallel with the same body and the same `Idempotency-Key: audit-rel-idem-20261127-dup-1` header.
2. One second later, retry the same body and key once more.
3. Read `GET /config/entitlements` before and after, then poll all three jobs to terminal.

**Expected:** one job for one logical submission; a repeated key returns the original `job_id` (or `409 Conflict`); one quota unit is charged. A retry after a client timeout must not create a second billable job.

**Actual:** three distinct jobs were created and three units were charged:

| Time (UTC) | Request | Result | Job id | Request id |
|---|---|---|---|---|
| 11:30:45.964 | parallel submit #1, same key | 200, 3,709 ms | `1892ef25-a34a-43a2-8edd-1f8da31bd869` | `6c3fb3a7-6ee6-44c0-bfd3-acc06baeea10` |
| 11:30:45.964 | parallel submit #2, same key | 200, 4,718 ms | `48dce8bf-afd3-4869-a4ec-b02e96975bad` | `99a5a23b-557f-47c3-8d34-828e6a944f62` |
| 11:30:51.685 | sequential retry, same key | 200, 3,433 ms | `7598d6f8-29e0-4e9d-9ecb-0b726bcf06bc` | `5dd018c2-3ec4-444d-8def-7205031264b2` |

- Quota `compilations` went **3 → 6** (request `1ae08c79-7d99-459c-9656-a43baf7f2470`); final 6/400 (request `332117b3-e3de-485b-99c8-45b2a8cf427b`).
- All three completed. Two were exact-render cache hits (`compilation_time` 0.0 s), so duplicate *compute* was largely avoided, but duplicate **billing and jobs** were not. DB rows: `compilations` created 11:30:48.473 / 11:30:48.488 / 11:30:53.932; `job_finalizations` all `state:completed`.
- No `Idempotency-Key` value was echoed in any response; the header had no observable effect.

**Impact:** a double-click in two tabs, a retried request after a gateway timeout, or the offline queue flushing twice creates independent jobs and consumes the plan allowance per copy. On Free (10 compiles/day) a single double-click can burn 2–3 units; on paid plans it inflates usage and produces duplicate completion events/artifacts even when the render cache hides the compute. It also makes the client's job ID nondeterministic after a retry.

**Proposed fix:**

1. Accept `Idempotency-Key` (header or body) on `/jobs/submit` and `/api/v1/compile`; store `key → job_id` for a bounded TTL (for example 24 h) keyed by user.
2. On replay, return the existing job (`200`) without consuming quota or dispatching; if the body hash differs, return `409`.
3. Make the charge conditional on the idempotency claim (single Lua/DB transaction), so a concurrent second request cannot consume a second unit while the first is in flight.
4. Add a cross-tab submission guard or server-side dedupe window as a second layer.
5. Regression test: two concurrent identical submits with the same key → one job, one quota unit.

**Owner:** Job submission / quota service. **Status:** open.

---

## R-D02 — P2 — Cancellation is not idempotent and emits duplicate terminal events

**Surface:** `DELETE /jobs/{job_id}` (`backend/app/api/job_routes.py:1858-1968`), `WS {type:"cancel"}` (`backend/app/api/ws_routes.py:255-265,707-779`), and the worker cancellation path (`backend/app/workers/latex_worker.py:2324-2353,2396-2417`).

**Cohort / user:** `basic-annual` `2f49586c-570d-4802-82bc-187ec0a516df`; applies to every job owner.

**Repro A — first cancel:**

1. Submit a long compile (`3daa9f12-76ca-481b-864c-2769cc7b6d13`, 236,540-character document) at 11:31:54Z.
2. `DELETE /jobs/3daa9f12…` at 11:31:58.711Z.
3. Read `GET /jobs/3daa9f12…/stream`.

**Repro B — repeat cancel after the job is terminal:**

1. `DELETE /jobs/3daa9f12…` again at 11:32:18.087Z.
2. Read the stream again.

**Expected:** exactly one `job.cancelled` terminal event per job. A repeat cancel on an already-cancelled job returns a terminal result (for example `{"success":true,"message":"Job already cancelled"}`) and emits nothing.

**Actual:**

- Repro A produced **two** `job.cancelled` events: sequence 3 at 11:32:01.427 (`event_id 644f6811-0e11-4d49-bbae-f7386bcc3790`) from the API's provisional write, and sequence 4 at 11:32:03.209 (`event_id 50a84a2d-29b6-48b1-bf89-b0c142452c39`) from the worker.
- Repro B returned **200 `{"success": true, "message": "Cancellation requested"}`** (request `b5724959-04bb-4677-ae10-ae90d286a25b`, 2,801 ms) and appended a **third** `job.cancelled` event (sequence 5 at 11:32:20.889, `event_id e778e8c2-b3a7-44b9-a15b-3851c44dad83`). All three have distinct event IDs and sequences.
- State/result remained correct (`cancelled`; `"error":"Job cancelled"`, request `1e0e2025-a297-42b6-854b-4968119bb118`) and the unit was refunded (`compilations` 6 → 6; requests `c3959ea0…` and `cbbb0020…`).

**Impact:** `job.cancelled` is a terminal event. Emitting it two or three times breaks the exactly-once event contract used by analytics, notification/email consumers, and any client that increments a cancellation counter. A repeated `DELETE` returning success without a terminal-state message also hides that the job was already finished; a retrying client cannot distinguish "cancel accepted" from "already cancelled". The UI reducer happens to be idempotent for this event, which limits user-visible damage, but downstream consumers are not protected.

**Proposed fix:**

1. Make `cancel_job` idempotent: if the durable finalization state is already `cancelled`, return `{"success":true,"message":"Job already cancelled"}` and do not publish another event. For `completed`/`failed`/`fenced`, keep the existing terminal message.
2. Suppress the worker's duplicate `job.cancelled` when the API already wrote a provisional terminal event (for example use a per-job `cancel-event-published` marker or let only the finalization arbiter publish the terminal event).
3. Add a contract test that a single cancel and a repeated cancel each yield exactly one terminal event.

**Owner:** Job cancellation / event publisher. **Status:** open.

---

## R-D03 — P2 — Large valid document retries at 90% and hangs past both timeouts; quota is not refunded

**Surface:** `POST /jobs/submit` `latex_compilation` with `compiler:"pdflatex"`; worker finalization stage after the `90% — Finalizing PDF` event (`backend/app/workers/latex_worker.py:2496-2695`); `DELETE /jobs/{job_id}`; the quota-refund sweep.

**Cohort / user:** `basic-annual` `2f49586c-570d-4802-82bc-187ec0a516df`; the input is a valid, authenticated, under-limit source (348,940 characters, below the 1,000,000-character request cap).

**Repro:**

1. Submit a 2,500-page document (348,940 chars; 2,500 `\newpage`-separated pages) at 11:33:07.640Z. The submit itself took **10,653 ms** (request `86f4c6b3-eb87-40f4-b507-e87d06309072`).
2. Observe `GET /jobs/f1d55ffa-bcd7-45c3-a5c7-df8cde86aaf3/state` and the stream.
3. At 11:40:03.985Z, after the job had been stuck for over six minutes, cancel it.
4. Read `GET /config/entitlements` immediately and repeatedly for the next ~12 minutes.

**Expected:** the compile either finishes, or fails with `compile_timeout` within the 120 s Basic timeout (or at the latest at the 300 s Modal function timeout), publishes one terminal event, and refunds the unit. A worker death should be terminalized by the recovery sweep within a bounded time.

**Actual:**

| Time (UTC) | Observation | Evidence |
|---|---|---|
| 11:33:14.658 | `job.queued` | stream seq 1 |
| 11:33:22.881 | `job.started` (queue wait 8.22 s) | stream seq 2 |
| 11:33:33.916 | `job.progress` 90% “Finalizing PDF” | stream seq 18 |
| 11:33:35.133 / 11:33:42.293 | two `job.retrying` events (attempt 2) | stream seq 19/20 |
| 11:33:44.176 → 11:33:53.806 | retry reaches 90% again | stream seq 21-36 |
| 11:39:44.697 | still `processing` at 90%, 6m22s after first start | state request `137ad624-4149-441d-a9c5-7f99bef7c61a` |
| 11:40:03.985 | manual `DELETE` → 200 “Cancellation requested” | request `983801eb-801f-4546-9ea4-70617ade14b0` |
| 11:40:10.743 | state `cancelled`, `job.cancelled` seq 37 | request `925c8175-597b-453b-ba7a-d36231b3fdfc` |
| 11:41:43.369 | `compilations.used` still **7** (no refund) | request `ca03e3f5-e908-4e39-9a6f-de69931c8d3c` |
| 11:48:48.843 | still **8/400** after later charges; the stuck unit was never returned | request `70d0b2c6-1da4-4d24-857a-60a95737f5e2` |
| 11:52:05 | end of window, still no refund line | `compilations 10/400`, request `b050f793-7622-4c21-bfc2-3a6f91afe1fb` |

- The finalization row stayed `pending` with `owner_epoch:2`, `created_at 11:33:14.186`, `updated_at 11:33:43.893`, `decided_at:null`, until the manual cancel committed `cancelled` at 11:40:05.401/646. The `compilations` row stayed `processing` until it was reconciled to `cancelled`.
- No terminal event was published by the worker; the only terminal event in the stream is the API's `job.cancelled` at 11:40:06.806.
- Controls: a 400-page document with the same structure completed in **4.98 s** (`compilation_time`; job `732efb06-aefb-4974-a1cb-36bc6ad5dbc3`, PDF 160,172 B), and a 1-page CJK document completed in **5.69 s** (job `cf81f32a-6fd0-4c0e-8cce-4c17a086479d`, PDF 52,121 B). This is not a general worker/queue outage.

**Impact:** a valid authenticated document can leave the client polling `processing` indefinitely, consume one quota unit for work that never terminalizes, and occupy a worker/container slot until the platform timeout. The client receives no timeout error and no refund; a manual cancel is required, and even then the unit stays consumed for at least 12 minutes. The `job.retrying` event is also not handled by the frontend reducer (`frontend/src/hooks/useJobStream.reducer.ts:275-276`), so the UI shows 90% with no retry indication. If this shape recurs under load, it becomes a P1 (worker fleet / quota integrity); it is P2 here because only an extreme page count reproduced it.

**Proposed fix:**

1. Enforce an absolute task deadline at the Modal function boundary, not only inside the pdflatex loop; the current 120 s/300 s limits did not terminalize this job.
2. Bound every post-compile step (`pdftotext`, extraction, upload, finalization commit) with its own deadline and a typed failure (`artifact_finalize_timeout`) that publishes a terminal event.
3. Add page-count/source-complexity admission limits (or a much lower page cap) before charging, with a clear 422.
4. Ensure orphaned `processing` finalizations are recovered within minutes (not only by the hourly cleanup sweep), and refund the receipt on recovery/cancel.
5. Make cancellation refund synchronously when the worker is already gone or fenced, instead of waiting for the sweep.
6. Surface `job.retrying` in the UI, or at least keep the stage/percent moving.

**Owner:** LaTeX worker / finalization arbiter / cleanup. **Status:** open.

---

## R-D04 — P3 — 429 body and headers are inconsistent with the API error contract

**Surface:** `APIKeyRateLimitMiddleware` (`backend/app/middleware/rate_limiting.py:325-420`); all rate-limited responses. Observed on `POST /byok/validate`.

**Cohort / user:** `basic-monthly` `0e0b7f8d-e7d0-48da-9e66-dcee3e52f0cb`.

**Repro:**

1. Send 11 `POST /byok/validate` requests 6 s apart with an invalid key.
2. Observe the 11th and 12th responses and headers.

**Expected:** the standard error envelope (`{"error":{"code":"rate_limited","message":…,"request_id":…}}`), `Retry-After`, and preferably `X-RateLimit-Limit/Remaining/Reset` (the rest of the API uses the envelope).

**Actual:** the 11th request at 11:45:34.923Z returned **429** (request `d87a404f-fbb8-4066-b3be-a315662bad32`, 453 ms) with:

```json
{"error":"Operation rate limit exceeded: 10 validate operations per 300 seconds","retry_after":300}
```

and `Retry-After: 300`. The 12th returned the same (request `6cbeb7a6-af60-4e93-8f37-3092d855e7d7`). There were no `X-RateLimit-*` headers. The first ten requests were 200 with `valid:false, error_kind:"unknown"` (0.94–1.95 s). The limiter itself works; only the contract is inconsistent. This overlaps PB-D05 (no rate-limit headers) but is recorded separately because the 429 path was exercised here.

**Impact:** SDK/CLI clients that parse the documented error envelope cannot read `error.code`/`request_id`; clients cannot see the remaining budget before being throttled. No quota was consumed by the rejected calls.

**Proposed fix:** return the standard `error_body("rate_limited", …, request_id)` envelope (or extend the envelope with `retry_after`), add `X-RateLimit-*` to success and 429 responses, and add a contract test for the 429 body.

**Owner:** API middleware / developer API. **Status:** open.

---

## R-D05 — P3 — Failed compile result is the generic `"Job failed"`

**Surface:** `GET /jobs/{job_id}/result` (`backend/app/api/job_routes.py:1728-1790`), `GET /api/v1/jobs/{job_id}`; the event stream is richer.

**Cohort / user:** `free` `96c507cd-e7a2-4749-9153-96b6321742db`; any plan, and the Developer API.

**Repro:**

1. Submit an invalid-but-structurally-valid LaTeX document (`\undefinedcommand`) at 11:26:37.798Z (job `a957f42f-5db4-4976-b08b-6d3b393202ce`, request `5a1e95ac-c0bd-42c2-8064-590c72c4e42f`).
2. Poll to terminal and read `GET /jobs/{id}/result` and `GET /jobs/{id}/stream`.

**Expected:** a typed failure in the result (`error_code`, sanitized `error_message`, `request_id`/`job_id`), matching the stream.

**Actual:** `GET /jobs/a957f42f…/result` returned `{"success":false,"job_id":"a957f42f…","result":null,"error":"Job failed"}` (request `2160f654-30e8-43a2-8401-a58b2d8533c2`). The stream had `job.failed` at 11:26:51.623 with `error_code:"latex_error"`, `error_message:"pdflatex exited with code 1"`, `retryable:false` (seq 19). The DB row held the useful compiler first-error line: `error_class:"engine"`, `error_message:"! Undefined control sequence."`, `compilation_time:5.2989`, `section_count:0`.

**Impact:** API clients and any UI path that reads the result cannot distinguish invalid LaTeX from a timeout, a provider failure, or an outage; support must correlate the stream/DB by job ID. The quota refund worked (1 → 1), so this is diagnosability, not billing.

**Proposed fix:** add `error_code`, sanitized `error_message`, `error_class`, and `request_id` to `JobResultResponse`; preserve the compiler's first error line in the result as already done in the DB; keep the generic message only as a fallback.

**Owner:** Job API / compile worker. **Status:** open.

---

## R-D06 — P3 — RTL/Arabic/Hebrew is not supported by default; xelatex emits replacement glyphs

**Surface:** `POST /jobs/submit` `latex_compilation` with Unicode content; `compiler` selection.

**Cohort / user:** `basic-annual` `2f49586c-570d-4802-82bc-187ec0a516df`.

**Repro / observations:**

1. **CJK control (PASS):** `\usepackage{CJKutf8}` + `\begin{CJK*}{UTF8}{gbsn}` with Chinese text on pdflatex compiled successfully (job `cf81f32a-6fd0-4c0e-8cce-4c17a086479d`, 5.69 s, PDF 52,121 B); `extracted_text` contained the Chinese text correctly.
2. **RTL on pdflatex (FAIL):** a one-page document containing Arabic, Hebrew, and CJK with `\usepackage[utf8]{inputenc}` failed with `! LaTeX Error: Unicode character م (U+0645)` (job `d37530aa-b980-4a54-94d6-934b639ff98a`, request `92805d46-80f2-47d9-94c1-118d114a2edb`; failure 7.99 s; quota refunded 3 → 3). The failure is graceful (typed `latex_error`), but the user gets no guidance.
3. **RTL on xelatex (FAIL, silent):** the same content with `compiler:"xelatex"` and `\usepackage{fontspec}` completed (job `cc79a5b5-c0ee-4894-924d-ae8f4f6d0d0d`, request `048c73b4-21c0-47f9-9876-ff3f91eb65fd`, `compilation_time` 20.35 s, PDF 4,146 B), but `extracted_text` was `"RTL audit: ������ .������ Hebrew: ������ .���� CJK: ������"` — every non-Latin glyph is U+FFFD. The PDF is almost certainly tofu as well; no font was selected.

**Expected:** either render RTL/CJK with an available font (for example a Noto/Arabic/Hebrew font on xelatex/lualatex), or reject the document with a clear preflight message (“this font/engine has no Arabic glyphs; use XeLaTeX with font X”). Silent replacement characters are not acceptable output.

**Actual:** default pdflatex hard-fails on Arabic; xelatex succeeds with missing glyphs and no warning. There is no font preflight in the submit path.

**Impact:** RTL users get either an opaque compile error or a PDF with blank boxes and corrupted text extraction; CJK only works if the author knows to use `CJKutf8` with the right font family. This is an edge/cohort gap (P3), but it is user-visible and hard to self-diagnose.

**Proposed fix:** add a lightweight Unicode/script preflight at admission; route RTL documents to xelatex/lualatex with a bundled font that covers Arabic/Hebrew; detect U+FFFD or missing-glyph warnings in `_extract_pdf_text` and fail or warn instead of returning a silently corrupted artifact; document the supported engines/fonts.

**Owner:** LaTeX engine / document admission. **Status:** open.

---

## Related records / duplicates

- **PB-D01** (P1, optimization `llm_error`) and **PB-D03** (P0, BYOK OpenAI credential routing): independently corroborated. Ten `POST /byok/validate` calls with plausible `sk-` keys all returned `error_kind:"unknown"` (not `rejected`), and a stored invalid BYOK key produced a generic 502 on `/ai/rewrite` with no platform fallback (request `fe5eb95e-20f0-4d14-9a9b-4faa5dc6bd45`). R-D05 is the compile analogue of the diagnosability gap in PB-D01.
- **PB-D05** (P3, no rate-limit headers): R-D04 adds the exercised 429 body shape.
- **D-FB-01** (all capabilities true): the capability tests here are explicit per-user revokes, not plan-family differences.

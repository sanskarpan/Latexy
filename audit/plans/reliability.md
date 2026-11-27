# Reliability audit — failure, quota, idempotency and recovery

**Window:** 2026-11-27T11:22:52Z → 2026-11-27T11:52:05Z (UTC)
**Environment:** production `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`
**Backend attestation:** commit `ee1a405de6058e814c3a6f5ffba5fe3630576421`; `/health` 200 `healthy` at 11:22:52Z (`dd5c6b43-2ac8-49ca-8ff0-d1b2127b5a19`) and 11:48:30Z (`f22e73de-294f-4753-8bba-6dc95ee66e0a`, 5.58 s); `/readyz` 200 `ready`; `/jobs/health` 200 `healthy` with queue depths `cleanup/email/combined/llm/latex/ats = 0` at 11:48:37Z (`c27f2ede-c1e8-4dd4-ba90-57d5c544b65f`) and 11:52:16Z (`5daa5bcf-127c-457c-8a08-96770744d6ab`).
**Identities:** Free `96c507cd-e7a2-4749-9153-96b6321742db`; Basic annual `2f49586c-570d-4802-82bc-187ec0a516df`; Basic monthly `0e0b7f8d-e7d0-48da-9e66-dcee3e52f0cb`; operator `admin-superadmin` `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad`. Suffix `20261127103328`.
**Method:** direct HTTPS with the provisioned session tokens, one request at a time except three deliberate concurrency probes; pacing kept the average under 20 requests/minute (220 captures over ~29 minutes, ~7.6/min; peak was the 10-in-5-min BYOK limiter probe). No load ramp. No worker kill, Redis/DB/S3 outage injection, or destructive infrastructure test. Raw evidence: `C:\Users\Sansk\AppData\Local\Temp\opencode\reliability_evidence.jsonl`, plus read-only PostgreSQL queries against `compilations`, `job_finalizations`, `admin_audit_log`, and `users`.
**Global changes:** none. Per-account Free quota reset and Basic-annual feature/plan mutations were performed for the tests and restored; they are listed in §11 and in `admin_audit_log`. The lead should mirror them into `changes/production-changes.md` (this sub-agent was restricted to the two assigned files).

## Verdict

| Scenario | Result | One-line evidence |
|---|---|---|
| Free quota exhaustion | **PASS** | used 10/10; next submit 402 `quota_exceeded` with dimension/used/limit/reset; no job created (`195f0715…`) |
| Concurrent race for the last unit | **PASS** | 3 simultaneous submits → exactly 1 accepted, 2×402; used 10; `8c09be34…`, `a590aaf2…`, `e77cb8f2…` |
| Refund on compile failure | **PASS** | malformed LaTeX job `a957f42f…` failed; `compilations` stayed 1 before/after (`7b244ee7…`) |
| Duplicate submit / `Idempotency-Key` | **FAIL (R-D01)** | same key 3× → 3 jobs, 3 units; two cache hits (`1892ef25…`, `48dce8bf…`, `7598d6f8…`) |
| Double-click / two tabs | **FAIL for server idempotency; PASS for shared state** | parallel submits duplicate; both tabs read the same job state/artifact |
| Tab reload / stream replay | **PASS** | full stream 20 events; replay from mid returns only 9 later events, `_stream_id` exclusive (`442746b2…`, `61c55555…`) |
| Cancellation (normal) | **PARTIAL (R-D02)** | state `cancelled`, unit refunded, but 2 `job.cancelled` events; repeat DELETE adds a 3rd |
| Capability revoke mid-job | **PASS** | new submit 403 `feature_disabled c05`; in-flight 400-page job completed; restore probe 422 |
| Plan downgrade mid-job | **PASS** | entitlements switched to Free immediately; in-flight job completed; new job used Free quota; restored |
| Malformed LaTeX | **PASS** | `job.failed` `latex_error`; refund; result text generic (R-D05) |
| Oversize source | **PASS** | 1,000,001 chars → 422 `string_too_long`; quota unchanged |
| Unicode CJK | **PASS** | `CJKutf8` compiled; extracted Chinese text correct; PDF 52,121 B |
| Unicode RTL | **FAIL (R-D06)** | pdflatex hard-fails on Arabic; xelatex compiles but all non-Latin text becomes U+FFFD |
| 429 / `Retry-After` | **PASS with P3 contract issue (R-D04)** | 11th/12th validate → 429, `Retry-After: 300`; body not the standard envelope |
| Invalid provider response | **PASS (fail-closed)** | stored invalid BYOK key → `/ai/rewrite` 502; no platform fallback; `ai_assists` unchanged |
| Large document / recovery | **FAIL (R-D03)** | 2,500-page valid source retried at 90% and hung >6 min past both timeouts; cancel did not refund |
| Worker kill / outage injection | **BLOCKED** | would be destructive to shared infrastructure; not attempted |

## 1. Quota baseline and ledger

| Cohort | Dimension | Start | End | Limit | Charges observed | Refunds observed |
|---|---|---|---|---|---|---|
| free | compilations | 1 | **0** (reset after test) | 10/day | 8× direct `/compile`; 1 race winner; 1 malformed attempt (refunded) | malformed job refund; admin reset 10→0 |
| free | optimizations | 1 | 1 | 3/month | — | — |
| free | ai_assists | 2 | 2 | 25/month | — | — |
| basic-annual | compilations | 2 | **10** | 400/month | CJK, RTL fail, 3 duplicate, cancel probe, 2 capability probes, plan-change probe, 2×400-page, xelatex, 400-page isolation | normal cancellation refunded; **stuck job unit never refunded** |
| basic-annual | optimizations / ai_assists | 0 / 0 | 0 / 0 | 10 / 100 | — | — |
| basic-monthly | compilations / optimizations / ai_assists | 1 / 1 / 2 | 1 / 1 / 2 | 400 / 10 / 100 | BYOK validate/rewrite (no quota dimension) | — |

Baseline snapshots: Free `d123aaa0-3454-4603-afa5-99421ff04a68` at 11:26:35Z; Basic annual `13408fe6-0505-4934-8c65-8dbd6faa2abd` at 11:29:05Z; Basic monthly `0615798e-62d5-4cbc-a3d2-0bc2f08cd4ee` at 11:23:02Z. Final snapshots: Free `4f8144a4-f4d1-4aa1-a3b6-af91c4148293`; Basic annual `b050f793-7622-4c21-bfc2-3a6f91afe1fb`; Basic monthly `db515421-cd0a-49e5-96bc-57bc428a2c08`.

The Basic-annual end state includes two units that are not successful paid output: one for the stuck/cancelled `f1d55ffa…` (not refunded) and one for the cancelled `3daa9f12…` (refunded). It also includes the intentionally retained test artifacts. Another auditor's `4d083a75…` job is visible in the same identity's job list; the baseline was captured after it.

## 2. Free quota exhaustion and concurrent last unit

**Exhaustion.** With Free at 1/10, eight valid direct compiles were run (`POST /compile`; each 200 `success:true`, 1.38–1.45 s). Quota became 9/10 (`c43de64c-4222-44c5-a511-3f771a7c0d9a`). Three simultaneous `POST /jobs/submit` requests then raced for the last unit:

| Request | Result | Job | Request id |
|---|---|---|---|
| race 1 | 200, 3,864 ms | `3b7a5ecc-6db9-4e2a-befe-aecfe7fc732e` | `8c09be34-9a14-4fab-a221-2eb95c04167d` |
| race 2 | **402**, 2,334 ms | — | `a590aaf2-b11e-4230-8c4d-279282954132` |
| race 3 | **402**, 2,311 ms | — | `e77cb8f2-70ed-4d9c-b550-0b9e98b612d7` |

After the race: 10/10 (`7ed02cb9-9e45-42cd-80e0-309ed15c3890`). The next submit returned:

```json
{"error":{"code":"quota_exceeded",
  "message":"Your plan's compilations allowance (10 per day) is used up. Upgrade your plan to continue.",
  "request_id":"195f0715-efcf-48d2-894a-481289084636",
  "details":{"dimension":"compilations","limit":10,"used":10,"remaining":0,
             "plan_family":"free","period":"20261127","window":"day",
             "resets_at":"2026-11-28T00:00:00+00:00"}}}
```

No job was created for the 402s (the Free job list contains only the failed malformed job and the race winner). The atomic Lua counter behaved correctly: exactly one of three concurrent callers got the last unit; there was no overspend and no readable-then-write race. The Free compilations counter was then reset to 0 through the audited admin quota-reset path (`97a3ab13-4433-425f-9c1f-e538fabc1f34`, 11:28:35Z; `before_used:10`, `after_used:0`) so later auditors are not blocked.

**Refund on failure.** A structurally valid but invalid LaTeX job (`\undefinedcommand`) was accepted at 11:26:37Z (`a957f42f-5db4-4976-b08b-6d3b393202ce`, submit `5a1e95ac-c0bd-42c2-8064-590c72c4e42f`, 2,599 ms). Timeline:

| Stage | Timestamp | Measured |
|---|---|---|
| `job.queued` | 11:26:39.658 | admission → queue |
| `job.started` | 11:26:43.565 | **queue wait 3.91 s** |
| pdflatex progress 10% | 11:26:44.646 | 1.08 s after start |
| `job.failed` `latex_error` | 11:26:51.623 | **compile subprocess 5.30 s** (DB `compilation_time`) |
| finalization `failed` | 11:26:51.044 (DB) | reporting ≈0.4 s |

`compilations.used` stayed **1** before and after (`7b244ee7-0a59-4232-a1dc-2a9d8631f9e4`). The DB row recorded `error_class:"engine"`, `error_message:"! Undefined control sequence."`. PASS for quota integrity and typed event delivery; the result-body diagnosability issue is R-D05.

## 3. Duplicate submit, idempotency keys, double-click and two tabs

Three submissions used the identical body and `Idempotency-Key: audit-rel-idem-20261127-dup-1`: two in parallel, then one sequential retry one second later. All three returned 200 with distinct job ids (`1892ef25…`, `48dce8bf…`, `7598d6f8…`) and the quota went **3 → 6** (`1ae08c79-7d99-459c-9656-a43baf7f2470`). The header was not echoed and had no effect. Two jobs were exact-render cache hits (`compilation_time` 0.0 s), so the system avoided duplicate compute but not duplicate jobs or billing. Full defect: R-D01.

**Two tabs / reload.** While the duplicate jobs were processing, two independent HTTP clients using the same session read the same job:

- Tab A state at 11:31:04Z: `processing`, 10%, request `a59094a5-724f-4f05-bcd0-afcbc77b62a8`.
- Tab B state at 11:31:09Z: `processing`, 90%, request `11bac33d-eb1b-4f42-be5d-e73a8b7291f6`.
- Early stream (tab B): 17 events, request `78ae29ac-0490-429a-967d-5e05d1bda654`.
- After completion, both tabs read `completed` with the same artifact (`dfaaa706-b88f-4188-9db3-c2200ebdd2eb`, `eec323d4-eb33-44bb-882e-2733a3ea20d1`).
- Full reload stream: 20 events, `job.queued → job.started → progress → artifact.ready → job.pdf_extracted → job.completed` (`442746b2-6d49-4a80-8fd3-e01055dc7741`).
- Replay `?from_id=1795779059256-1` returned 9 events starting at `1795779059256-2`; the requested entry was excluded and ordering was monotonic (`61c55555-5013-4feb-90bb-8ec998729153`). All 20 event IDs in the full stream were unique.
- Result: `GET /jobs/{id}/result` returned `success:true`, 26,549 B PDF, same `pdf_sha256` from both tabs.

PASS for server-side job persistence, cross-tab consistency, reload, and exclusive stream replay. The only failure is that a second tab or retry can create a second billable job (R-D01).

## 4. Cancellation

**Normal case (`3daa9f12-76ca-481b-864c-2769cc7b6d13`).** Submitted at 11:31:54Z (request `442ce9d0-77d1-4a57-a5cf-6dd04d48168e`, 3,188 ms). The first `DELETE` at 11:31:58.711Z returned 200 “Cancellation requested” in 2,609 ms (request `4cf55738-2ed1-4a38-85c0-c608bba7230b`). State became `cancelled` on the first poll (`60b30e25-733f-45dc-9a54-b148d20b4b58`), result was `{"success":false,"error":"Job cancelled"}` (`1e0e2025-a297-42b6-854b-4968119bb118`), and the unit was refunded (6 → 6; `cbbb0020…`, `ce7c8322…`). The finalization row is `state:cancelled`, `cancel_requested:true`.

**Defect.** The first cancel produced two `job.cancelled` events (seq 3/4); a second `DELETE` at 11:32:18.087Z returned 200 “Cancellation requested” again and appended a third (seq 5). Full record: R-D02. The UI/state/refund outcome is correct; event consumers are not.

**Stuck-job case (`f1d55ffa…`).** The 2,500-page job was `processing` at 90% for over six minutes, so it was cancelled manually at 11:40:03.985Z (`983801eb-801f-4546-9ea4-70617ade14b0`). State flipped to `cancelled` (`925c8175-597b-453b-ba7a-d36231b3fdfc`), the finalization committed `cancelled` at 11:40:05.401/646, and the stream gained one `job.cancelled` (seq 37 at 11:40:06.806). The unit was **not** refunded: `compilations.used` was 7 immediately before and after and still 7 at 11:41:43Z (`ca03e3f5…`); subsequent successful jobs took the counter to 8, 9, 10. No refund line exists for this job by 11:52Z. This is part of R-D03.

## 5. Capability and plan change mid-job

**Capability revoke (`compile` → child `c05`).** A 400-page compile (`732efb06-aefb-4974-a1cb-36bc6ad5dbc3`, submit `c25a9fdb-92bf-48ac-bac1-696b281dba83`, 2,771 ms) was allowed to reach `processing` 10%. The operator then revoked `compile` for the identity at 11:51:41.961Z (request `0e96caec-39dc-49f6-af78-15c7416ae03f`, 2,030 ms; `changed:true`, `effective:false`). Results:

- `GET /config/entitlements` immediately showed `compile:false`, `c05:false` (`f88aae9a-e226-4f7f-8e99-685384a9743d`).
- A new `POST /jobs/submit` was blocked **403** `feature_disabled` “The 'c05' feature is not available on your plan.” (request `c6e701f6-6764-49a6-afdc-3012c5aaad7d`, 765 ms).
- The in-flight job was **not** cancelled: it reached 90% (`b9120826-c866-4a21-af00-d9ebb4464c0a`) and completed successfully at 11:51:55Z (`700b1c8c-cf80-452c-8ad1-e108468bb799`), PDF 160,172 B, `compilation_time` 4.98 s.
- Restore at 11:51:56.893Z (`e04b0fdc-0c2e-4355-b096-e0ba7becd04c`, `changed:true`, `effective:true`); entitlements showed `compile:true` again (`51b98f0a-0395-4d36-bab1-4d982fb7f0f7`); a probe submit with an empty body passed the gate and failed validation with 422 (`3dcf4af2-b00f-47e5-83a0-cd6fc7d8e5e5`), proving the admission switch was restored without creating a job.

PASS. The gate uses the child `c05` under the `compile` parent; the in-flight job is isolated from the admission switch exactly as the feature description promises. A first attempt with a 2,500-page job also showed the job was not terminated by the revoke, but that job independently hit R-D03 and had to be cancelled; the clean 400-page run above is the actionable evidence.

**Plan downgrade mid-job.** A 400-page compile (`f31a9fbc-1d47-4ffb-ab9f-0f04ab387985`, submit `68f45360-4f1b-40e5-b16e-1b78094e3ae9`, 2,754 ms) was `processing` when the operator changed the identity from `basic_annual` active to `free` active at 11:43:01.227Z (`4c1325d9-d29e-4972-b021-8e77e0db1793`, 1,357 ms). Immediately (and after 5 s) `/config/entitlements` returned Free limits `0/10/day`, `0/3`, `0/25` (`22065610…`, `8d863e62…`), and `/me` returned `plan:"free"`; there was no stale-cache window. The in-flight job still completed at 11:43:18.201Z with the Basic-era limits (`job.completed`, 400 pages, 159,141 B, `compilation_time` 3.76 s). A new submit while downgraded was accepted (`4af497f4-808c-44df-b8c6-8074c1e62fc1`, job `f69ea898-586b-4c33-9464-4e505818399b`) and completed under the Free allowance; the Basic monthly counter did not move for it. Restore at 11:43:57.884Z (`60546116-6e03-46da-86b7-1ec6e7d9feba`); `/subscription/current` returned `planId:"basic_annual"`, `status:"active"` (`9378b451-8465-4e21-8bae-0701b875bdf3`), and entitlements returned 400/month. PASS.

## 6. Malformed, oversize and Unicode inputs

| Case | Job / request | Outcome | Quota |
|---|---|---|---|
| Malformed `\undefinedcommand` | `a957f42f…` / `5a1e95ac…` | 200 queued → `job.failed` `latex_error`; DB `! Undefined control sequence.` | refunded (1→1) |
| Oversize source 1,000,001 chars | `425b1e7a-1a74-4fdf-98bb-c6f36bdfe87e` | **422** `string_too_long` “String should have at most 1000000 characters”; 8,151 ms (1 MB body) | unchanged |
| CJK (`CJKutf8`, pdflatex) | `cf81f32a-6fd0-4c0e-8cce-4c17a086479d` / `887cdb6b…` | completed 11:29:27.019; 1 page; PDF 52,121 B; extracted Chinese text correct | 2→3 |
| Arabic+Hebrew+CJK, pdflatex | `d37530aa-b980-4a54-94d6-934b639ff98a` / `92805d46…` | `job.failed` `latex_error`, DB `! LaTeX Error: Unicode character م (U+0645)`; graceful | refunded (3→3) |
| Arabic+Hebrew+CJK, xelatex + fontspec | `cc79a5b5-c0ee-4894-924d-ae8f4f6d0d0d` / `048c73b4…` | completed 11:51:08.063; 1 page; PDF 4,146 B; all non-Latin text U+FFFD | 9→10 |

The oversize request is rejected before quota consumption; the malformed request is charged and refunded on terminal failure. CJK is usable when the author selects the right package/font; RTL is not (R-D06). The xelatex run took 20.35 s of subprocess time for one page because the default font lacks the glyphs; the client gets a “successful” job with corrupt text, which is the worst outcome of the three.

## 7. 429 handling

`POST /byok/validate` with an invalid key was repeated 11 times at 6 s spacing (requests `c01bc0dd…` through `890bd4c2…`, 0.94–1.95 s each). The 11th at 11:45:34.923Z returned **429**, 453 ms, `Retry-After: 300` (request `d87a404f-fbb8-4066-b3be-a315662bad32`); a 12th immediately after also returned 429 (`6cbeb7a6-af60-4e93-8f37-3092d855e7d7`). The limiter correctly stops the operation after 10 calls per 300 s. The body is `{"error":"Operation rate limit exceeded: 10 validate operations per 300 seconds","retry_after":300}` rather than the API's standard `{"error":{"code":…}}` envelope, and there are no `X-RateLimit-*` headers (R-D04; overlaps PB-D05). The general per-token ceiling (60/min) and developer daily ceilings were not driven to 429 under the ≤20/min rule; only this operation limiter was exercised.

## 8. Invalid provider response

With a stored invalid OpenAI BYOK key (`0f2698bc-8be2-4a64-aaad-7ce3c2292bb1`, added unvalidated with `34058647-0b13-409b-8ac5-de16d7f1bd49`):

- `POST /byok/test/openai` → 200 `{success:false, validation_details:{valid:false, error_kind:"unknown"}}` (`74eb2208-55eb-46ae-903f-614ae1e82264`).
- `POST /ai/rewrite` → **502** “AI provider could not complete the rewrite. Please retry.” in 1,062 ms (`fe5eb95e-20f0-4d14-9a9b-4faa5dc6bd45`).
- `ai_assists` stayed **2** (BYOK calls are not platform-metered), so there was no platform spend and no refund needed. No platform-key fallback occurred.
- Key deleted (`942567f4-e2cc-4324-852d-2a463c78c39d`); `GET /byok/api-keys` then returned empty.

PASS for fail-closed behavior and billing. The error remains generic/`unknown`, which is consistent with PB-D03 (the key is likely being sent to the platform-compatible endpoint) and PB-D01 (provider failures are not typed). The 10 validate calls all returned `error_kind:"unknown"` rather than `rejected`, independently corroborating PB-D03.

## 9. Large document, 90% stall and recovery

Full defect: R-D03. Summary of the measured path:

- Valid 2,500-page source, 348,940 chars, below the 1 MB cap. Submit latency **10,653 ms** (job `f1d55ffa-bcd7-45c3-a5c7-df8cde86aaf3`; request `86f4c6b3-eb87-40f4-b507-e87d06309072`).
- `job.queued` 11:33:14.658 → `job.started` 11:33:22.881 (**queue wait 8.22 s**) → 90% “Finalizing PDF” 11:33:33.916.
- `job.retrying` at 11:33:35.133 and 11:33:42.293; retry reached 90% again at 11:33:53.806 and then produced no further event.
- Still `processing` at 11:39:44.697 (`137ad624-4149-441d-a9c5-7f99bef7c61a`), i.e. **6 m 22 s after first start**, past the 120 s Basic timeout and the 300 s Modal function timeout. DB finalization stayed `pending`, `owner_epoch:2`, `updated_at 11:33:43.893`, `decided_at:null`.
- Manual cancel at 11:40:03.985 flipped state to `cancelled` and committed the finalization at 11:40:05.4, but the quota stayed consumed; the job's unit was not refunded by 11:52Z.
- Controls: a 400-page document completed in 4.98 s (PDF 160,172 B); a 1-page CJK document in 5.69 s; a 1-page xelatex document in 20.35 s. The stall is input-shape-specific, not a platform-wide queue outage.
- The frontend reducer ignores `job.retrying` (`frontend/src/hooks/useJobStream.reducer.ts:275-276`), so a browser would show 90% with no retry indicator during the stall.

This is the highest-impact reliability finding of this scope. It is P2 because the input is extreme and a manual cancel recovers the UI, but the lack of a terminal event, the held quota, and the missed recovery bound would be P1 if reproduced on a normal-size resume.

## 10. Latency and stage observations (single region; not a load test)

| Operation | n | min / median / max | Notes |
|---|---|---|---|
| `POST /jobs/submit` small/medium | 12 | 2,541 / 2,754 / 4,718 ms | includes admission, quota, dispatch |
| `POST /jobs/submit` 349 KB source | 1 | 10,653 ms | 2,500-page document |
| `POST /jobs/submit` oversize 1 MB | 1 | 8,151 ms | 422 validation |
| queue wait (`job.queued`→`started`) | 8 | 3.55 / 8.22 / 9.25 s | CJK 3.55; plan-change 9.25; stuck 8.22 |
| pdflatex subprocess (`compilation_time`) | 7 | 3.76 / 5.30 / 7.99 s | 1–400 pages; 400-page 3.76–4.98 |
| xelatex subprocess | 1 | 20.35 s | 1 page, missing glyphs |
| `job.started`→terminal (normal) | 6 | 7.4 / 14.0 / 19.1 s | includes extraction/finalization |
| `GET /jobs/{id}/state` | 60+ | 0.90 / 1.30 / 1.66 s | one 8.15 s sample was the submit, not state |
| `DELETE /jobs/{id}` | 3 | 2,609 / 2,756 / 2,801 ms | normal cancel and stuck-job cancel |
| `POST /byok/validate` (invalid key) | 10 | 941 / 1,002 / 1,954 ms | provider rejection is fast |
| `POST /ai/rewrite` (invalid BYOK) | 1 | 1,062 ms | 502 fail-closed |
| 429 response | 2 | 453 ms | `Retry-After: 300` |

Measured stage examples: malformed job queue 3.91 s + pdflatex 5.30 s + reporting ~0.4 s; CJK job queue 3.55 s, start→complete 13.87 s (5.69 s pdflatex, remainder extraction/finalization); 400-page plan-change job queue 9.25 s, start→complete 19.13 s (3.76 s pdflatex, remainder finalization/extraction); 400-page capability job start→complete ~14.7 s (4.98 s pdflatex). The admission endpoint, not pdflatex, is the slowest single client-visible step for small jobs; for 400-page jobs the post-compile extraction/finalization is the largest stage.

`/health` was 5.58 s at 11:48:30Z versus 1.66 s at 11:22:52Z, and `/jobs/health` 3.11–3.61 s in both samples. Those two samples are noted for the performance auditor; they are not treated as a reliability defect here.

## 11. Cleanup and audit-trail state

**Per-account changes (all restored and verified):**

| Time (UTC) | Change | Evidence | Restore |
|---|---|---|---|
| 11:28:35.651 | Free compilations quota reset 10→0 after exhaustion test | `97a3ab13-4433-425f-9c1f-e538fabc1f34`; audit `user.quota.reset.completed` 11:28:37.107 | final Free 0/10 (`4f8144a4…`) |
| 11:33:19.791 | Basic-annual `compile` revoke (first, on stuck job) | `04a6938e-ac7b-4a55-bd92-6f5c28d9a9c9` | grant `c6422ef8…` 11:36:19; entitlements true |
| 11:43:01.227 | Basic-annual plan `basic_annual`→`free` | `4c1325d9-d29e-4972-b021-8e77e0db1793`; audit `user.plan.change` 11:43:02.863 | plan restore `60546116…` 11:43:57.884; audit 11:43:59.296 |
| 11:51:41.961 | Basic-annual `compile` revoke (clean mid-job test) | `0e96caec-39dc-49f6-af78-15c7416ae03f` | grant `e04b0fdc…` 11:51:56.893; probe 422 `3dcf4af2…` |

Final users table: Free `free/active`; Basic annual `basic_annual/active`; Basic monthly `basic/active`. `GET /subscription/current` for Basic annual returns `basic_annual/active` (`9378b451-…`). `/config/entitlements` final: Basic annual compilations 10/400, Free 0/10, Basic monthly 1/400; optimizations/ai_assists match the baseline. No test jobs remain `queued` or `processing`; `/jobs/health` queues are 0.

**Artifacts left as evidence (all synthetic, `AUDIT`-tagged):**

| Cohort | Job | Final state | Notes |
|---|---|---|---|
| free | `a957f42f-5db4-4976-b08b-6d3b393202ce` | failed | malformed LaTeX; refunded |
| free | `3b7a5ecc-6db9-4e2a-befe-aecfe7fc732e` | completed | last-unit race winner |
| free | 8 direct-compile jobs (`82a2c6c7…`, `cad60501…`, `3c6e12d1…`, `2491563c…`, `80aeba26…`, `2d33511e…`, `584a6f3a…`, `18faddd5…`) | success | quota-consumption fixtures |
| basic-annual | `cf81f32a…` | completed | CJK, 52,121 B |
| basic-annual | `d37530aa…` | failed | RTL pdflatex, refunded |
| basic-annual | `1892ef25…`, `48dce8bf…`, `7598d6f8…` | completed | duplicate-key trio |
| basic-annual | `3daa9f12…`, `f1d55ffa…` | cancelled | R-D02 and R-D03 evidence |
| basic-annual | `f31a9fbc…`, `f69ea898…` | completed | plan-change in-flight and Free follow-up |
| basic-annual | `732efb06…` | completed | capability-isolation control |
| basic-annual | `cc79a5b5…` | completed | xelatex tofu evidence |

**Deleted/revoked:** BYOK key `0f2698bc-8be2-4a64-aaad-7ce3c2292bb1` deleted (`942567f4…`); `GET /byok/api-keys` is empty. No other keys were created by this scope. No global flag, plan catalog, capability matrix, or deployment state was changed. The only pending cleanup is the unrefunded `f1d55ffa…` unit (quota at 10/400); the hourly cleanup sweep may eventually refund it, but it was not observed. Cleanup owner: lead / cleanup auditor.

## 12. Limitations

1. **No worker-kill or outage injection.** The brief forbids killing shared infrastructure; `kill -9`, Redis/DB/S3 blackholing, and provider-outage tests are **BLOCKED**, not passed. The 2,500-page stall is a natural observation, not a controlled worker kill.
2. **No Modal logs.** The root cause of the 90% stall is inferred from events and code (`backend/app/workers/latex_worker.py:2496-2695`); the worker log/finish reason was not available to this agent.
3. **General rate ceilings not exhausted.** Driving the 60/min token bucket or 1,000/day developer limit would exceed the audit pacing rule; only the BYOK 10/300 s operation limiter produced a 429. Developer 429 headers remain unverified (same gap as PB-D05).
4. **No browser UI.** Two tabs and reload were simulated with independent HTTPS clients using the same session; the browser WebSocket client and its reducer were inspected in source, not driven live. The events auditor owns `/ws/jobs` replay and event-to-UI latency.
5. **Free identity is shared.** Another auditor applied a `compile` revoke/grant to the Free identity at 11:46Z (admin audit). Our Free tests ended at 11:28Z and the quota was already reset; the final Free snapshot is 0/10. The Free compilations counter was not affected by that capability test.
6. **Quota baselines include prior audit traffic.** Basic annual started at 2/400 (one job from the Free/Basic auditor remains in its list); the per-test deltas above are based on the snapshots immediately before and after each action.
7. **All plans currently report all 165 capabilities true** (environment-wide, recorded by the Free/Basic auditor as D-FB-01). This scope therefore verifies explicit per-user revoke/restore and in-flight isolation, not plan-family differentiation or the intended launch matrix.
8. **The 2,500-page document is an extreme input.** It is valid under the 1 MB source cap, but it is not representative of a normal resume. R-D03 severity is P2 on that basis; a reproduction on a normal-size document would raise it to P1.
9. **Xelatex “success” was diagnosed from extracted text.** The PDF itself was not visually inspected; the U+FFFD sequence and 4,146 B size are strong evidence of missing glyphs, but a visual check would confirm.

## 13. Related records

`audit/defects/reliability.md`: R-D01 (duplicate submit/idempotency), R-D02 (cancel idempotency/duplicate events), R-D03 (90% stall/recovery/refund), R-D04 (429 envelope), R-D05 (generic failed result), R-D06 (RTL/xelatex glyphs). Cross-references: PB-D01/PB-D03 (LLM/BYOK failures corroborated), PB-D05 (rate-limit headers), D-FB-01 (all-enabled capability matrix).

# Compile stage breakdown — production, 2026-11-27

- **Window:** 2026-11-27T11:33:30Z – 2026-11-27T11:51:30Z (measured jobs; read samples until 11:57Z).
- **Environment:** production backend `ee1a405de6058e814c3a6f5ffba5fe3630576421` (`sanskarpandey2004--latexy-backend-fastapi-app.modal.run`), Modal app `ap-IB2XwK8MjL2xmeI7wOUyEZ`.
- **Identity:** `pro-monthly`, `audit+pro-monthly-20261127103328@example.test`, user `2c27be6f-138f-4e98-b311-38892520b1eb`.
- **Method:** 38 `POST /jobs/submit` jobs (`job_type: latex_compilation`, compiler `pdflatex`), all with unique source. Client timing by an asyncio/aiohttp harness; server timestamps from the production job lifecycle hash and the Redis Stream `latexy:stream:{job_id}`; final state from `compilations`. A WebSocket `/ws/jobs` subscriber measured event delivery for 33 of the 38 jobs.
- **Load ceiling:** 38 compiles (hard ceiling 40). **No 5xx, no failed jobs, no duplicate terminal events in captured streams, all 38 durable rows `completed`.**
- **No configuration, plan, flag or deployment change was made.** No live payment or LLM call is part of a compile.
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\audit_perf\` (`simple1_recovered.json`, `load_20261127T114027Z.json`, `load_20261127T114214Z.json`, `load_20261127T114428Z.json`, `load_20261127T114629Z.json`, `load_20261127T114801Z.json`, `read_samples_*.json`, `summary.json`).

## Bottom line

Compile latency in production is **not** a 5–10 s flow. Across 38 successful jobs:

| Metric (server-side, submit→terminal event) | p50 | p95 | p99 | min | max |
|---|---:|---:|---:|---:|---:|
| `server_total` | **33.305 s** | **57.083 s** | **62.648 s** | 20.111 s | 62.648 s |
| Client-observed submit response | 3.148 s | 4.282 s | 4.428 s | 2.578 s | 4.428 s |

The median is **3.3–6.6×** the prompt's 5–10 s observation. There is no single dominant stage:

- **Warm path:** pdflatex **~8.5 s (simple) / ~15.7 s (complex)** and object-storage/finalization **~6.7 s** together account for ~75% of the ~20.6 s warm simple total.
- **Cold/scale-out path:** container acquisition **12.8 s p50 / 21.6 s p99** and worker initialization **2.8 s p50 / 5.8 s p99** add 15–27 s before compilation; total rises to **38.6–62.6 s**.
- **pdflatex is CPU-starved and highly variable:** the same complex document compiled in **1.197 s** (job `474c7d3f…`) and **21.066 s** (job `886505c5…`), a 17.6× spread. This is not cold start (both were scale-out jobs); it is consistent with Modal's default 0.125-core minimum plus opportunistic CPU bursting.
- **Object-storage/finalization is the second bottleneck and is not just cold start:** warm simple jobs spend **6.4–6.9 s** between progress 90% and the terminal event; the scale-out groups have medians of **12.1 s (simple) / 14.2 s (complex)** and range **6.3–25.4 s**. The 1.197 s complex compile still spent **24.2 s** in finalization.

## Stage definitions and observed values

All values are seconds. `n=38` except where noted. `finalize_upload_publish` = progress 90% → terminal event. `artifact_upload` and `durable_finalize` split that window for the 33 jobs where `artifact.ready` was emitted; the first five jobs (simple warm baseline) are included only in the combined `finalize_upload_publish` column.

| Stage | What is actually measured | p50 | p95 | p99 | max |
|---|---|---:|---:|---:|---:|
| admission / quota | `meta.submitted_at` → lifecycle `created_at` (DB + quota + initial Redis state) | 0.401 | 0.406 | 0.433 | 0.433 |
| dispatch call | lifecycle `created_at` → `accepted_at` (Modal spawn call returns) | 0.962 | 1.948 | 2.041 | 2.041 |
| queue + container acquisition | `accepted_at` → `started_at` (Modal scheduling + container boot + claim). **Queue wait is not separately observable.** | **9.606** | 19.385 | 21.633 | 21.633 |
| worker initialization | `started_at` → `job.started` event (module import → first task) | 2.369 | 5.494 | 5.838 | 5.838 |
| validation | `job.started` → progress 5% | 0.188 | 0.221 | 0.252 | 0.252 |
| source prepare | progress 5% → progress 10% (settings, cache lookup, TeX write) | 0.754 | 0.891 | 1.014 | 1.014 |
| **pdflatex total (pass 1..2)** | result `compilation_time` (subprocess + converge/re-run passes) | **10.219** | 18.375 | 21.066 | 21.066 |
| post-subprocess → 90% | progress 10% + `compilation_time` → progress 90% (recorder check, log cache, finalize progress event) | 0.377 | 0.475 | 0.516 | 0.516 |
| artifact upload / manifest | progress 90% → `artifact.ready` (render artifact upload + manifest registration; n=33) | **5.911** | 9.585 | 11.617 | 11.617 |
| durable finalize | `artifact.ready` → `job.pdf_extracted` (durable DB commit + `upload_compilation_pdf` + result publication; n=33) | **7.178** | 13.630 | 14.484 | 14.484 |
| terminal publish | `job.pdf_extracted` → `job.completed` | 0.144 | 0.227 | 0.251 | 0.251 |
| **storage/finalization total** | progress 90% → terminal | **12.111** | 24.076 | 25.391 | 25.391 |
| **server total** | `meta.submitted_at` → terminal event | **33.305** | 57.083 | 62.648 | 62.648 |

Every job ran **two pdflatex passes** (`This is pdfTeX` banner count 2); the fixture has no images or external files. The `compilation_time` value is the worker's own subprocess timer and matches the `progress 10 → progress 90` window minus the ~0.3–0.5 s post-subprocess bookkeeping.

### Warm simple timeline (job `6ffbca83-8bf4-4e1f-8b4a-a91d4fe43da7`)

| Offset | Event | Delta |
|---:|---|---:|
| 0.000 | `meta.submitted_at` / `job.queued` | — |
| +0.403 | lifecycle `created_at` (admission complete) | 0.403 |
| +1.339 | lifecycle `accepted_at` (Modal spawn returned) | 0.936 |
| +2.705 | lifecycle `started_at` (worker claim) | 1.367 |
| +3.670 | `job.started` | 0.964 |
| +3.866 | progress 5% | 0.196 |
| +4.653 | progress 10% (pdflatex starts) | 0.787 |
| +14.251 | progress 90% (pdflatex + post) | 9.598 (compile 9.167) |
| +18.046 | `artifact.ready` | **3.795** |
| +20.903 | `job.pdf_extracted` | **2.857** |
| +21.119 | `job.completed` | 0.215 |
| | **server total** | **21.119 s** |

The client-observed submission for this job was 2.578 s; the server-side admission + spawn path was 1.339 s. The remainder is edge/network and response transport (no `Server-Timing` header exists; this is an estimate).

## Concurrency results (simple vs complex, 1 / 5 / 10)

All 38 jobs completed; error rate 0.0%; 38/38 durable rows `completed`. Totals below are server-side p50/p95 with the scenario's median stage values.

| Scenario | n | submit p50 | acquire p50 | worker init p50 | pdflatex p50 | storage/finalize p50 | **server total p50** | **p95** | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| simple 1-concurrent | 5 | 3.28 s | 1.35 s | 0.98 s | 9.16 s | 6.80 s | **20.73 s** | 35.61 s | 35.61 s |
| simple 5-concurrent | 5 | 3.04 s | 13.21 s | 2.82 s | 6.84 s | 14.40 s | **39.91 s** | 62.65 s | 62.65 s |
| simple 10-concurrent | 10 | 3.47 s | 9.67 s | 1.02 s | 9.96 s | 8.02 s | **30.18 s** | 45.72 s | 45.72 s |
| complex 1-concurrent | 3 | 3.29 s | 1.21 s | 1.05 s | 15.68 s | 7.05 s | **27.76 s** | 33.19 s | 33.19 s |
| complex 5-concurrent | 5 | 3.03 s | 13.26 s | 2.81 s | 11.18 s | 13.35 s | **42.86 s** | 59.86 s | 59.86 s |
| complex 10-concurrent | 10 | 3.15 s | 9.61 s | 2.37 s | 11.69 s | 12.13 s | **42.17 s** | 51.88 s | 51.88 s |

**Pool-state caveat:** the scenarios ran in that order. The 10-concurrent simple burst benefited from containers left warm by the 5-concurrent burst (`scaledown_window=120 s`), so simple-10 is not a from-zero cold test and is faster than simple-5 at p50. The from-zero scale-out evidence is the 5-concurrent burst and the cold subset (acquire >5 s).

### Warm vs scale-out (classified by acquisition >5 s)

| Group | n | acquire p50 | worker init p50 | pdflatex p50 | storage/finalize p50 | server total p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| simple warm | 9 | 1.44 s | 1.00 s | 8.52 s | 6.81 s | **20.73 s** | 30.96 s |
| simple scale-out | 11 | 13.21 s | 2.63 s | 9.96 s | 12.11 s | **39.91 s** | 62.65 s |
| complex warm | 7 | 1.47 s | 1.05 s | 15.35 s | 7.78 s | **29.17 s** | 33.31 s |
| complex scale-out | 11 | 12.84 s | 2.83 s | 11.69 s | 14.20 s | **44.10 s** | 59.86 s |

A clean warm-only subset (acquire ≤1.5 s) gives **simple n=6, total 20.11–21.12 s, median 20.62 s** and **complex acquire ≤2 s, n=4, total 25.67–29.17 s, median 27.34 s**. This is the baseline to use for SLO comparison.

## Is it cold start? What is proven

- **Yes for the scale-out penalty.** Warm claims are 0.92–1.48 s; scale-out claims are 8.41–21.63 s, an 8–15× difference. Worker initialization is 0.94–1.00 s warm vs 2.37–5.84 s scale-out (module import → first task). Jobs with those signatures take 38.6–62.6 s total.
- **No for the dominant warm cost.** Warm simple jobs still take 20.1–21.1 s. The warm path has no cold container and still spends 8.2–9.2 s in pdflatex and 6.4–6.9 s in finalization.
- **No for the 17.6× pdflatex spread.** `474c7d3f…` (scale-out, acquire 9.56 s) compiled the complex fixture in **1.197 s**; `886505c5…` (scale-out, acquire 13.24 s) compiled the same fixture in **21.066 s**. Both emitted two passes and the same 163,726-byte PDF. The difference is CPU availability/contention, not container boot.
- **No for the 1.197 s compile's 24.2 s finalization.** `474c7d3f…` spent 9.717 s in `artifact_upload` and 14.484 s in `durable_finalize` after a 1.2 s compile. Storage/finalization is an independent bottleneck.

## Event publish, WebSocket delivery, client render

- **Event publish (Redis Stream ID timestamp vs event `timestamp`):** **|p50| < 1 ms** across 1,935 events (the measured difference is -0.4 ms, i.e. within millisecond truncation/rounding). The stream append and Pub/Sub publish are effectively atomic from the client's point of view.
- **WS delivery (server event timestamp → Python client receive, clock offset corrected by WS pong):**

| Event type | n | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| `job.started` | 33 | 0.165 s | 0.277 s | 2.115 s |
| `job.progress` | 99 | 0.164 s | 0.205 s | 1.133 s |
| `log.line` | 1,671 | 0.172 s | 0.408 s | 0.414 s |
| `artifact.ready` | 33 | 0.164 s | 0.332 s | 2.209 s |
| `job.pdf_extracted` | 33 | 0.165 s | 1.015 s | 2.606 s |
| `job.completed` | 33 | 0.163 s | 0.827 s | 2.476 s |

These are client-observed delivery lags from the audit workstation (IST/UTC+5:30) to Modal/AWS us-east-1; they include public-network one-way latency. They are **not** client render times. Five simple-1 jobs are excluded from the WS stats because the first harness run did not persist WS frames (a harness serialization bug, not a product failure).

- **Client render:** **not observable** in this API/WS harness. No browser or PDF viewer was instrumented. The closest observable is PDF retrieval: `GET /download/{job_id}` for a 163,726-byte PDF, 30 warm samples, p50 **2.136 s**, p95 3.060 s, p99 3.146 s, TTFB p50 2.048 s. A single cold first download of the 114,018-byte simple PDF took **30.649 s** and is reported separately, not in the 30-sample warm set. Browser paint/render remains unmeasured.

## Findings for the defect register (measurement only; no fixes applied)

1. **P1 candidate — compile p95 is 57.1 s vs a 5–10 s expectation; warm p50 is 20.6 s (simple) / 27.3 s (complex).** 38/38 completed, so this is latency, not availability. The warm floor alone is 2–4× the prompt's upper bound.
2. **P1 candidate — post-compile storage/finalization adds 6.4–7.2 s on warm jobs and 12–25 s on scale-out jobs**, independent of pdflatex. The timeline shows two distinct storage/finalize windows (`artifact.ready` then durable finalization). This is a code-path observation from event boundaries; S3/R2 spans were not directly instrumented.
3. **P1/P2 candidate — default CPU allocation starves pdflatex.** `backend/modal_app.py` does not pass `cpu=`/`memory=` for `run_latex_task`; `capacity_options("LATEX")` controls only containers/scaledown. Modal's default request is 0.125 CPU / 128 MiB. The observed 1.2–21.1 s spread for the same document is consistent with CPU burst/contention, but actual CPU/memory usage is not exposed by the app or Modal console to this auditor. Treat "CPU starvation" as a strong inference, not a measured fact until Modal metrics are pulled.
4. **P2 — queue wait and container acquisition are indistinguishable.** `accepted_at → started_at` conflates Modal scheduling, container boot and worker claim. `/jobs/health` reports only Celery queues (all zero) and cannot see Modal spawn backlog (already recorded as Q-01). This report cannot separate queue wait from acquisition without Modal input metrics.
5. **Observation — duplicate terminal events are possible after completion.** A separate completed job (`4d083a75-33f5-4e3b-b536-a98804ccd8f7`, basic-annual, 11:04Z) emitted `job.completed` twice in its stream (sequence 39 at 11:04:31Z and sequence 40 at 11:16:24Z, the latter `stage:"recovered"`). None of the 38 audit jobs showed a duplicate in the captured stream; this is an events/worker finding for the events auditor, not a compile-stage claim.

## Exact job IDs

- **simple-1 (5):** `6ffbca83-8bf4-4e1f-8b4a-a91d4fe43da7`, `b98199f9-d44a-4f1e-96dd-41be6f50273f`, `d582e594-50a1-434c-8071-e505d6774d98`, `45efe5dc-6863-4bb6-bf36-eb4c6a6c0828`, `727b62ed-3f23-493a-a97f-2d92bb5daffb`
- **simple-5 (5):** `6227812c-6bed-4fda-ac58-d228353afd73`, `b0556029-2f3f-4103-8451-92f9fdba448f`, `029bd467-dbd1-4b60-b932-5f6a1ef9d5fa`, `6e94035c-d0bc-4219-9dd7-6f38c7b1e7f5`, `cd767631-a3d5-4d11-a360-4e9ec71e36fb`
- **simple-10 (10):** `a5fe31b1-040d-4ebd-ae5b-5a715fa03935`, `84a6dc66-bd32-438d-9df1-8fa92b052296`, `5a6a53e4-91fa-4820-9718-1005e0c3b836`, `32df5bf2-7b78-45bc-8d47-5e47a4f93a30`, `d290c2b7-0422-4700-890d-ae6f1d6b8953`, `f17ce12e-239e-45d0-9e43-27ac11cc02ac`, `498bb3c1-7056-4ffd-a4e3-b33bd140a385`, `d997b56d-4905-4216-9ed0-229afd187a10`, `f6d357b8-3d3c-4e94-9f58-25c0fc65cbcb`, `f9612b3a-fe7e-424e-9494-6437e855c44d`
- **complex-1 (3):** `3a34e04c-f911-4e4a-850f-bc5431843ef4`, `737905e6-fc13-4bc4-b6e8-a983e1ffc69b`, `46a8f4f9-ff0a-4a73-a2b2-cbad137e3549`
- **complex-5 (5):** `90bde429-23f2-4a5f-b22b-57c4c8340fce`, `a2ec1394-3ff5-4157-a5a1-43d3186d3b5e`, `5586943d-7e75-469b-a474-d7ec0b5765c4`, `ec50bbc8-12d5-495d-b8f0-8823c8fc4a18`, `fb49a2ee-fe0b-486c-a313-cf696238177e`
- **complex-10 (10):** `91a235fe-6798-4862-8273-c8bfbe46949c`, `11d5ab72-3704-477f-a911-0c9225369ef2`, `474c7d3f-c62d-4fd6-9591-78f0198ef026`, `8e2d4a94-be24-4462-b50b-02c6c3f5d019`, `119c019e-d2c0-4389-9156-26d04ddc7bd5`, `8cd3edfa-449f-46e8-9d35-6505c3cbf64d`, `acda9b36-774c-45f8-9f91-340169e05af1`, `8cc6cf5f-a580-4ccd-b81a-5ac7d154f007`, `ea4a3331-4c58-476f-8335-342a75cd91b8`, `886505c5-380b-4790-99fe-d6412361e677`

## Limitations

- No Modal console/token, so container CPU/memory, input queue time, cold-boot start and worker restarts are not directly observable. `container_acquire` is the only queue+boot bound.
- No S3/R2 spans; `artifact_upload` and `durable_finalize` are event-boundary buckets, not per-request storage timings.
- No browser instrumentation, so client render is unmeasured.
- Scenario order and residual warm pools make 5- and 10-concurrent runs non-independent. The warm-only subsets are the fair baseline.
- External audit traffic overlapped the window: `f1d55ffa-bcd7-45c3-a5c7-df8cde86aaf3` was cancelled at 11:33:14Z (before the run), and completed jobs `25f2ce19…`, `f31a9fbc…`, `f69ea898…`, `cc79a5b5…`, `732efb06…` appear in the same window. The first simple-1 job's 10.3 s acquisition and 35.6 s total coincide with that external activity; the warm subset excludes it.
- `n=3–10` per scenario; p95/p99 are near-neighbor order statistics, not high-confidence tails.

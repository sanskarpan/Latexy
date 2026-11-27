# Load test — production compile throughput, 2026-11-27

- **Window:** 2026-11-27T11:33:30Z – 2026-11-27T11:51:30Z (compiles); read sampling 11:53–11:57Z.
- **Environment:** production Modal backend `ee1a405de6058e814c3a6f5ffba5fe3630576421`, app `ap-IB2XwK8MjL2xmeI7wOUyEZ`.
- **Identity:** `pro-monthly`, user `2c27be6f-138f-4e98-b311-38892520b1eb`; plan quotas unlimited (`compilations.limit=null`).
- **Workload:** 38 `latex_compilation` jobs via `POST /jobs/submit`; simple 1-page fixture and a 4-page complex fixture (tables, math, multicol, headers); compiler `pdflatex`; every job used unique source. Six scenarios: simple 1/5/10 concurrent and complex 1/5/10 concurrent.
- **Ceiling:** 40 compiles. **Used 38; stopped at the cap.** No configuration/plan/flag/deploy change. No live payments; compile does not call an LLM.
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\audit_perf\load_*.json`, `simple1_recovered.json`, `read_samples_*.json`, `summary.json`; endpoint rows are in `audit/latency/endpoints.csv`.

## Result summary

| Scenario | n | Success | submit p50 | acquire p50 | pdflatex p50 | storage/finalize p50 | **server total p50** | **p95** | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| simple, 1 concurrent | 5 | 5/5 | 3.28 s | 1.35 s | 9.16 s | 6.80 s | **20.73 s** | 35.61 s | 35.61 s |
| simple, 5 concurrent | 5 | 5/5 | 3.04 s | 13.21 s | 6.84 s | 14.40 s | **39.91 s** | 62.65 s | 62.65 s |
| simple, 10 concurrent | 10 | 10/10 | 3.47 s | 9.67 s | 9.96 s | 8.02 s | **30.18 s** | 45.72 s | 45.72 s |
| complex, 1 concurrent | 3 | 3/3 | 3.29 s | 1.21 s | 15.68 s | 7.05 s | **27.76 s** | 33.19 s | 33.19 s |
| complex, 5 concurrent | 5 | 5/5 | 3.03 s | 13.26 s | 11.18 s | 13.35 s | **42.86 s** | 59.86 s | 59.86 s |
| complex, 10 concurrent | 10 | 10/10 | 3.15 s | 9.61 s | 11.69 s | 12.13 s | **42.17 s** | 51.88 s | 51.88 s |

- **Total:** 38/38 completed, **0% job error rate**, **0/38 submission errors**, 38/38 durable `compilations.status='completed'`.
- **Overall server-side p50/p95/p99:** 33.305 s / 57.083 s / 62.648 s.
- **Clean warm baseline** (acquire ≤1.5 s): simple n=6, 20.11–21.12 s (median 20.62 s); complex (acquire ≤2 s) n=4, 25.67–29.17 s (median 27.34 s).
- **Scale-out penalty:** acquire 12.84 s p50 / 21.63 s p99 and total 38.6–62.6 s.

The 5-concurrent simple burst is the worst p95 because it is the first from-zero scale-out burst. The 10-concurrent simple burst is faster at p50 because it reused containers left warm by the 5-concurrent burst (`scaledown_window=120 s`). Scenarios are **not independent**; the warm subsets above are the fair baseline. Full stage detail is in [`compile-stages.md`](compile-stages.md).

## Endpoint latency (warm, authenticated, 30 samples unless noted)

All rows are appended to `audit/latency/endpoints.csv`. Latency is client-observed total; TTFB is shown where it differs materially. `mean_bytes` is the response body size.

| Endpoint | n | OK | Error | p50 | p95 | p99 | min | max | mean | mean bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `POST /jobs/submit` | 38 | 38 | 0.0% | **3,147.9 ms** | **4,281.9 ms** | **4,428.2 ms** | 2,577.6 | 4,428.2 | 3,415.9 | ~110 |
| `GET /jobs/{job_id}/state` | 30 | 30 | 0.0% | **1,491.6 ms** | **3,288.5 ms** | **3,616.3 ms** | 1,400.8 | 3,616.3 | 1,622.1 | 861 |
| `GET /download/{job_id}` | 30 | 30 | 0.0% | **2,136.1 ms** | **3,060.4 ms** | **3,146.3 ms** | 1,932.7 | 3,146.3 | 2,237.3 | 163,726 |
| `GET /jobs/{job_id}/stream?from_id=0` | 10 | 10 | 0.0% | **1,094.9 ms** | **1,127.7 ms** | **1,127.7 ms** | 1,033.1 | 1,127.7 | 1,087.5 | 38,626 |

For these read endpoints TTFB ≈ total (state TTFB p50 1,491 ms; download 2,048 ms; stream 1,095 ms), so body transfer is not the cost. The floor is request admission + edge + handler, not payload.

Existing 30-sample baseline rows in the same CSV (captured earlier in the audit) for context:

| Endpoint | Identity | p50 | p95 | p99 | mean bytes |
|---|---|---:|---:|---:|---:|
| `/health` | anonymous | 1,185.0 ms | 2,926.4 ms | 4,101.5 ms | 510 |
| `/readyz` | anonymous | 1,177.8 ms | 1,240.3 ms | 3,348.9 ms | 77 |
| `/jobs/health` | anonymous | 3,553.5 ms | 4,561.6 ms | 4,774.3 ms | 195 |
| `/me` | pro | 1,173.1 ms | 1,210.1 ms | 1,210.1 ms | 145 |
| `/config/entitlements` | pro | 1,864.5 ms | 2,331.9 ms | 2,729.1 ms | 2,728 |
| `/subscription/current` | pro | 1,277.1 ms | 3,446.9 ms | 3,616.3 ms | 386 |
| `/resumes` | pro | 2,326.4 ms | 3,219.6 ms | 23,373.7 ms | 708 |
| `/resumes/builder/templates` | pro | 1,290.1 ms | 1,573.5 ms | 2,141.3 ms | 10,534 |
| `/analytics/admin/overview?days=30` | admin | 1,405.0 ms | 3,804.5 ms | 4,148.2 ms | 23,473 |

### Edge vs application

- `POST /jobs/submit` client p50 is **3.15 s**. The server-side stages measured from the same jobs are admission **0.401 s** + dispatch call **0.962 s** = **1.363 s**. The remaining **~1.8 s** is public edge/network/response transport, not compile admission. There is no `Server-Timing` or `X-Process-Time` response header, so this split is an estimate, not a header-derived measurement.
- A trivial `/health` request has p50 **1.19 s** and `/me` 1.17 s from the same workstation. That supports a ~1.2 s edge/application floor and is already recorded as P-01 (edge latency). The authenticated compile path is not the only slow API surface.
- No 429 was observed. The harness enforced ≤18 API requests in any rolling 60 s and used a 3.3 s schedule for read sampling; a full clear window was forced before the 10-concurrent bursts. Bursts of 10 submissions were issued concurrently, so individual submit latency includes queueing at the edge/API, not just server work.

## Throughput and capacity behavior

- **Burst 5 (simple):** 5 submissions accepted in ~2 s; 1 warm container served one job (20.6 s); four new containers acquired in 12.6–21.4 s and completed in 38.5–62.6 s. This is the clearest from-zero scale-out observation.
- **Burst 10 (simple):** 10 submissions accepted and all 10 finished in 20.6–45.7 s. The residual pool from the previous burst reduced acquisition for some jobs (1.4–19.4 s). No submission was rejected.
- **Burst 10 (complex):** all 10 finished in 26.9–51.9 s. The pdflatex spread for identical source was 1.197–21.066 s. This is CPU contention/burst variance, not a queue rejection.
- **Throughput:** the 10-concurrent simple burst completed in ~45.7 s wall (≈13 jobs/min at that burst); the 10-concurrent complex burst in ~51.9 s (≈11.6 jobs/min). The steady-state warm single-container rate is ~3 jobs/min (20.6 s each). A second concurrent compile is only fast if another warm container already exists; otherwise the first burst pays 13–21 s of acquisition.
- **Queue depth:** `/jobs/health` returned 200 with all Celery queue depths `0` after every burst. Production is Modal-only; this endpoint cannot see Modal spawn backlog (known Q-01). No worker restart, OOM, 5xx or poison-message evidence was observed in the API/lifecycle data; worker restarts are not directly observable without Modal console access.
- **Abort criteria:** 5xx 0/38 (0% < 2%); no queue backlog growth; no 429; no runaway spend (estimated $0.011–$0.022 total, see [`cost.md`](cost.md)); p99 62.6 s is >2× the warm baseline 20.6 s, but the excess is attributable to measured scale-out acquisition and storage/finalization, and all jobs completed. I did not abort: the ceiling is cost/5xx/queue/worker failure, not cold-capacity latency. The p99 result is recorded as a finding, not hidden.

## External traffic and contamination

Six non-audit compilations appeared in the same window (from the durable table, excluding the 38 audit job IDs):

| Job | User | Status | Compilation time | Created (UTC) |
|---|---|---|---:|---|
| `f1d55ffa-bcd7-45c3-a5c7-df8cde86aaf3` | basic-annual | cancelled | — | 11:33:14 |
| `25f2ce19-e399-449c-b2d9-6e51e2d6b8f5` | pro-monthly | completed | 12.240 s | 11:35:04 |
| `f31a9fbc-1d47-4ffb-ab9f-0f04ab387985` | basic-annual | completed | 3.762 s | 11:42:49 |
| `f69ea898-586b-4c33-9464-4e505818399b` | basic-annual | completed | 4.226 s | 11:43:13 |
| `cc79a5b5-c0ee-4894-924d-ae8f4f6d0d0d` | basic-annual | completed | 20.345 s | 11:50:31 |
| `732efb06-aefb-4974-a1cb-36bc6ad5dbc3` | basic-annual | completed | 4.978 s | 11:51:36 |

`f1d55ffa…` was already `processing` at preflight and was cancelled before our first job; its container occupancy likely explains the one 10.3 s warm-baseline acquisition (`727b62ed…`, 35.6 s total) and is excluded from the clean warm subset. The other jobs overlap the later bursts and can only make results worse, not better. The audit cohort itself is synthetic; dashboards cannot exclude it (AN-08).

## Limitations

- No Modal console/token: actual CPU/memory, input queue time, container start time and restart count are not observable. `container_acquire` is a single bound covering Modal queue + container boot + claim.
- No S3/R2 spans; `storage/finalize` is an event-boundary bucket.
- No browser/PDF viewer: client render unmeasured; PDF download is the closest observable (2.14 s p50 warm; 30.65 s first cold download, reported separately).
- Small n per scenario (3–10); p95/p99 are order statistics.
- Scenarios ran in a fixed order and reused warm pools; only the warm subsets are a clean baseline.
- The audit workstation is in IST (UTC+5:30); backend is Modal/AWS us-east-1. Absolute WS delivery and read latency include public-network transit; compare same-day samples, not absolute SLOs from another region.

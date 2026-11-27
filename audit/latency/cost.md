# Cost per successful compile — production, 2026-11-27

- **Scope:** 38 successful `latex_compilation` jobs on `pro-monthly`; compile path only. No LLM call, no live payment, no plan change.
- **Window:** 2026-11-27T11:33:30Z – 2026-11-27T11:51:30Z.
- **Environment:** Modal app `ap-IB2XwK8MjL2xmeI7wOUyEZ`, backend `ee1a405de6058e814c3a6f5ffba5fe3630576421`.
- **Raw evidence:** `C:\Users\Sansk\AppData\Local\Temp\opencode\audit_perf\summary.json` and `cost_rows`; job ids in [`compile-stages.md`](compile-stages.md).

All dollar values are **estimates**. Only `active_s`, `compile_s`, `pdf_size` and event counts are directly observed. Modal CPU/memory, Upstash command counts and Neon query cost are not exposed by any production endpoint available to this auditor.

## Assumptions

| Item | Rate / assumption | Source / label |
|---|---|---|
| Modal CPU | **$0.0000131 per physical-core-second**, minimum 0.125 cores | Modal public pricing, 2026 |
| Modal memory | **$0.00000222 per GiB-second**, minimum 128 MiB | Modal public pricing, 2026 |
| Modal billable window | Worker `started_at` → terminal event (`job.completed`) | Observed lifecycle/stream |
| CPU lower bound | 0.125 core (the default request; `run_latex_task` sets no `cpu=`) | Code + Modal default |
| CPU upper bound | 1.0 core (pdflatex is single-threaded; allows for Python/streaming overhead) | Inference |
| Memory bound | 0.125 GiB (default minimum) | Modal default |
| Excluded | Container boot before worker claim; warm-pool idle; image cache; network egress | Not observable |
| R2 / S3-compatible storage | $0.015/GB-month; Class A $4.50/million; egress $0 | Cloudflare R2 list pricing |
| Upstash Redis | $0.20 per 100k commands; $0.25/GB-month | Upstash list pricing |
| Redis command estimate | `2 × stream_events + 12` per job (EVAL/publish/result/state/lifecycle/artifact writes) | Heuristic; see caveat |
| LLM tokens | 0 | Compile result reports `tokens_used:0`, `optimization_time:0` |
| Payment fees | $0 | No live checkout in this test |
| Neon / Postgres | Excluded | No per-query cost signal |

## Per-job cost table (p50 of 20 simple / 18 complex jobs)

`active_s` is the billed container window from worker claim to terminal. `compile_s` is the worker's pdflatex timer. Storage total is the event-boundary storage/finalization window.

| Component | Simple (1 page, 114,018 B) | Complex (4 pages, 163,726 B) |
|---|---:|---:|
| Active container seconds, p50 | 22.549 s | 28.253 s |
| pdflatex seconds, p50 | 8.528 s | 11.692 s |
| Stream events, mean | ~39 | 75 |
| **Modal CPU, lower ($0.0000131 × 0.125 × active)** | **$0.0000369** | **$0.0000463** |
| **Modal CPU, upper ($0.0000131 × 1.0 × active)** | **$0.0002954** | **$0.0003701** |
| **Modal memory ($0.00000222 × 0.125 × active)** | **$0.0000063** | **$0.0000078** |
| Upstash commands (estimate) | $0.000180 | $0.000324 |
| R2 Class A upload | $0.0000045 | $0.0000045 |
| R2 storage, 1 month | $0.0000016 | $0.0000023 |
| Redis storage, 24 h TTL | $0.0000015 | $0.0000020 |
| **Total, lower bound** | **$0.000228** | **$0.000386** |
| **Total, upper bound** | **$0.000469** | **$0.000710** |
| **Per 1,000 successful jobs** | **$0.23 – $0.47** | **$0.39 – $0.71** |
| **Per 10,000 successful jobs** | **$2.28 – $4.69** | **$3.86 – $7.10** |

**Observed 38-job total: $0.0109 – $0.0225.** This is the entire variable compile spend for the load test; it is far below the cost ceiling. The dominant **marginal** component is Upstash event/command volume, followed by Modal CPU at the upper bound. At the lower bound, Modal CPU and Upstash are similar.

### Why the ranges are wide

- **CPU:** the app does not request a CPU size for `run_latex_task`; Modal's default request is 0.125 cores. The same complex document compiled in 1.197 s in one container and 21.066 s in another (17.6×). If the container is allowed to burst to one core, the upper bound applies; if it is pinned near 0.125, the lower bound applies. The truth is workload- and host-dependent and cannot be read from the app.
- **Upstash:** 75 events for a complex compile are mostly `log.line` frames. If Upstash counts the Lua-internal `XADD`/`PUBLISH` separately, double the command estimate; if the account is on a flat plan, the marginal cost is $0. If log streaming is reduced or batched, this line falls proportionally.
- **Storage:** R2/MinIO is cheap per object; the real cost of the 12 s finalization is not the PUT. It is **held container time**: the worker stays billed while it waits for the two storage/finalize windows. Reducing that window reduces Modal active seconds.

## Cost of the latency pathologies

Using the same rates, the measured stage overhead converts to container time:

| Pathology | Extra active time vs clean path | Extra Modal CPU (0.125 core) | Extra Modal CPU (1 core) |
|---|---:|---:|---:|
| Warm finalization (12.1 s p50) vs a 2 s target | ~10 s/job | +$0.000016 | +$0.000131 |
| Cold scale-out (40.1 s p50 simple vs 20.6 s warm) | ~19.5 s/job | +$0.000032 | +$0.000255 |
| Cold acquisition + init (15–27 s) | per cold job | +$0.000025–0.000044 | +$0.00020–0.00035 |
| Warm-pool memory, 1 container 24/7 | 86,400 s/day | $0.0246/day ($0.747/month) | — |

A failed job is not free: it still consumes Modal container time, Redis events and a durable row until recovery/cleanup. This run had **0 failures**, so failed-job cost is not measured. The one external cancelled job (`f1d55ffa…`, basic-annual, 11:33:14Z) still consumed a worker slot before cancellation; its container time was not captured.

## Fixed vs variable cost

- **Warm pool:** `min_containers=1` for `run_latex_task` (`capacity_options("LATEX")` default) and `scaledown_window=120 s`. Modal's docs state idle containers are billed for residual resources such as memory; CPU idle is assumed not billed. At 128 MiB and $0.00000222/GiB-s, the warm pool costs about **$0.0246/day (~$0.75/month)**. Allocated over 1,000 compiles/month that is **$0.00075/job**; over 10,000 it is **$0.000075/job**. At the audit's 38 jobs, fixed warm-pool cost is ~33–66× the entire variable spend, so per-job cost is meaningless without a volume assumption.
- **Scale-out containers:** each cold container also has boot time and idle scaledown. At launch concurrency, the number of cold containers, not the per-compile CPU, determines the bill. The 5-concurrent burst created four new containers; the 10-concurrent bursts created up to nine. If Modal bills boot time, add roughly $0.00002–$0.00003 CPU+memory per cold container at 0.125 core.

## Cost per successful job by shape and scenario

| Shape / scenario | n | Active p50 | Total low p50 | Total high p50 |
|---|---:|---:|---:|---:|
| simple, all | 20 | 22.55 s | $0.00023 | $0.00047 |
| complex, all | 18 | 28.25 s | $0.00039 | $0.00071 |
| simple 1-concurrent | 5 | 20.73 s | ~$0.00021 | ~$0.00044 |
| simple 5-concurrent | 5 | 39.91 s | ~$0.00031 | ~$0.00060 |
| simple 10-concurrent | 10 | 30.18 s | ~$0.00026 | ~$0.00052 |
| complex 1-concurrent | 3 | 27.76 s | ~$0.00038 | ~$0.00070 |
| complex 5-concurrent | 5 | 42.86 s | ~$0.00050 | ~$0.00085 |
| complex 10-concurrent | 10 | 42.17 s | ~$0.00049 | ~$0.00084 |

Scenario values are derived from the p50 active seconds plus the same event/storage heuristics; they are approximate because active seconds and event counts vary per job.

## Cost drivers (ranked)

1. **Fixed warm capacity at low volume** — ~$0.75/month regardless of traffic; dominates a 38-job sample.
2. **Upstash event/command volume** — ~$0.00018 simple / ~$0.00032 complex per job at list rates; driven by 29–75 stream events, mostly `log.line`.
3. **Modal CPU at realistic burst** — $0.00004–$0.00037 per job depending on whether the container gets 0.125 or 1 core.
4. **Storage/finalization holding time** — 6.4–25.4 s of billed container time per job; the storage PUT itself is negligible.
5. **Cold scale-out** — 12–22 s acquisition and 2–6 s init per cold job; it multiplies the effective per-job cost relative to warm steady state.
6. **Neon/Postgres and network egress** — not observable; excluded, not assumed zero in reality.

## Recommendations (measurement only; no optimization applied)

1. **Make CPU explicit and measure it.** Add `cpu=` (and `memory=`) to `run_latex_task`, then repeat this stage test. Without it, cost and latency cannot be attributed between CPU starvation and cold start. Target: a documented CPU/price trade-off, not a blind increase.
2. **Remove or collapse the duplicate storage/finalize path.** The event timeline shows a first artifact upload (`artifact.ready` at progress 90% + 3.4–11.6 s) and a second durable upload/finalization (`job.pdf_extracted` 2.0–14.5 s later). Pool the DB/storage clients instead of creating a fresh engine per finalize. Target: ≤2 s total storage/finalize on a warm job (measured baseline 6.4–6.9 s warm, 13.5–25.4 s scale-out).
3. **Batch or suppress `log.line` events.** Complex compiles emit 75 events; simple emit ~39. This is the largest marginal Upstash line and also adds WS fan-out load. Target: bounded progress-level streaming, full log only on request/failure.
4. **Right-size the warm pool for launch concurrency.** One warm container cannot serve a 5- or 10-concurrent burst; four to nine cold containers cost 13–22 s each. Use `buffer_containers`/`min_containers` matched to the measured launch concurrency, then re-measure cost per job at that pool size.
5. **Do not chase storage cost first.** At list prices the object bytes are fractions of a cent per thousand jobs. The measurable win is latency and held container time, not the PUT price.

## Limitations

- Modal CPU/memory and container boot billing are not observable from the app or any endpoint used here. The lower bound is a reservation estimate; the upper bound is a single-core assumption.
- Upstash billing semantics for Lua-internal commands are not confirmed. The command count is a heuristic and is the largest uncertainty in the variable cost.
- Neon query cost, R2 vs MinIO selection, egress and retention lifecycle are excluded.
- 38 jobs is a small sample; per-scenario cost figures are indicative, not statistically robust.
- No failed jobs in this sample, so cost of failure/retry is unmeasured. Modal worker retries are not configured for compile (WORK-02), so a killed container's cost is bounded by its lifetime, not a retry loop.

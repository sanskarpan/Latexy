# Optimization backlog - Latexy production audit 2026-11-27

**Status:** baseline candidate, pending final performance/cost numbers. Optimization must not start until `AUDIT-MASTER.md` baseline sign-off.
**Scoring:** user impact 1-5 x frequency 1-5 / effort 1-5. Higher first. Latency and cost are separate; correctness/security work is listed last because it is not optional optimization.

Measured baselines are client-observed from the audit workstation unless labelled server-side. The ~1.2 s floor on trivial endpoints is an edge/network observation and is separated from application time. See `audit/latency/endpoints.csv` and `audit/latency/compile-stages.md` (performance auditor, when complete).

## A. Latency

| Rank | Item | Impact | Freq | Effort | Score | Measured baseline | Target | Proposed change |
|---|---|---|---|---|---|---|---|---|
| 1 | Cache `/config/entitlements` effective snapshot | 5 | 5 | 2 | 12.5 | p50 1.86 s, p95 2.33 s, one 17.65 s; called on every authenticated page | p95 < 300 ms | Short-TTL per-user Redis cache keyed by user+plan+version; invalidate on plan/role/entitlement change; single-flight the cold miss. Do not cache the `available:false` outage state as a denial. |
| 2 | Fix `/admin/plan-catalog` | 4 | 2 | 1 | 8.0 | 23,051 ms for 92 KB; 11 plans from application constants, `plan_catalog` table has 0 rows | p95 < 1.5 s | Serve the constant catalog from memory/static cache; stop a per-request build/serialization path. |
| 3 | Make `/jobs/health` Modal-aware and cached | 4 | 3 | 2 | 6.0 | p50 3.55 s, p95 4.56 s; six Celery queue snapshots with no `sampled_at` | p95 < 500 ms | Cache queue/worker snapshot (15-30 s); report Modal spawn backlog, not empty Celery queues; add `sampled_at` and `worker_count`. |
| 4 | Pre-aggregate admin analytics | 4 | 3 | 3 | 4.0 | overview p50 1.40 s, p95 3.80 s; feature-adoption 574 KB / 2.49 s; daily rollup empty | p95 < 1.5 s | Repair the daily-metrics rollup (AN-05/CRON-01) and read rollups for date ranges; paginate large lists; cache per-window. |
| 5 | Fix `/resumes` tail latency | 4 | 4 | 3 | 5.3 | p50 2.33 s, p95 3.22 s, p99 23.37 s | p95 < 500 ms, p99 < 2 s | Add covering index on owner+updated_at, keyset pagination, avoid N+1/thumbnail work in list; investigate the 23 s outlier. |
| 6 | Cache developer usage aggregation | 3 | 2 | 2 | 3.0 | `/developer/usage` 2.5-3.3 s | p95 < 500 ms | Pre-aggregate daily usage per key; return cached counters; add rate-limit headers while touching the path. |
| 7 | Locate/remove the 1.2 s edge floor | 4 | 5 | 3 | 6.7 | `/readyz` p50 1.18 s, `/health` 1.19 s, `/me` 1.17 s, templates 1.29 s from the audit host | p95 < 300 ms in-region | Measure TTFB at the edge vs origin; move the probe/region or add a regional read replica/CDN; separate network RTT from application time before changing code. |
| 8 | Compile submit-to-terminal latency | 5 | 4 | 4 | 5.0 | 38/38 completed; p50 33.3 s, p95 57.1 s, p99 62.6 s; warm simple p50 20.6 s; acquisition 12.8 s p50 scale-out | p95 < 30 s, warm p50 < 12 s | Warm containers and queue admission; the dominant lever is storage/finalize, not pdflatex. See `latency/compile-stages.md`, `load-test.md`. |
| 8b | Storage/finalize window | 5 | 4 | 3 | 6.7 | 6.8 s warm, 12.1 s p50 all jobs, 12-25 s scale-out | < 2 s | Remove the two-window upload/finalize path; parallelize upload and terminal publish; measure R2 spans. |
| 8c | LATEX CPU allocation | 4 | 4 | 2 | 8.0 | `run_latex_task` sets no CPU/memory; 1.2-21.1 s spread for same document (inference) | explicit measured CPU; stable p50 | Pull Modal metrics, set CPU/memory explicitly, re-measure warm p50. |
| 9 | Remove synchronous work from auth/account reads | 3 | 4 | 3 | 4.0 | `/subscription/current` p95 3.45 s; `/me` p95 1.21 s | p95 < 300 ms | Cache plan/status projection; avoid provider calls in read paths. |
| 10 | De-duplicate admin dashboard payloads | 2 | 2 | 2 | 2.0 | feature-adoption 574 KB; flag-exposure 54 KB | < 100 KB per view | Field selection, pagination, ETag/If-None-Match. |
| 11 | Bound analytics `days=N` queries | 3 | 3 | 2 | 4.5 | Mixed UTC-day and rolling windows (AN-07), up to 13 h extra scan | one window definition | Define UTC-day windows and add indexes; cap range. |
| 12 | Email delivery latency | 3 | 3 | 3 | 3.0 | 199 delayed / 107 sent in 30 days; 20 bounced | < 1% delayed, < 2% bounce | Fix Resend domain/auth and suppression list; separate transactional from marketing. |

## B. Cost

| Rank | Item | Impact | Freq | Effort | Score | Measured baseline | Target | Proposed change |
|---|---|---|---|---|---|---|---|---|
| 1 | Stop BYOK credentials going to the platform proxy | 5 | 3 | 2 | 7.5 | P0 PB-D03: OpenAI BYOK key sent to non-OpenAI `OPENAI_BASE_URL`; platform may also pay for BYOK traffic | 0 cross-provider sends | Set `base_url` explicitly per provider in every SDK client; add a client-construction test that asserts the URL for each key source. |
| 2 | Stop retrying deterministic LLM failures | 4 | 4 | 2 | 8.0 | PB-D01: 2/2 optimizations fail after retry with `llm_error`; each retry burns tokens | retry only 429/5xx/timeouts | Classify provider errors; retry with jitter only transient classes; refund quota once; emit the provider error class. |
| 3 | Cap Modal job-worker fan-out | 4 | 3 | 2 | 6.0 | 19 job workers with no `max_containers`; no product-side backpressure | explicit per-worker cap + queue metric | Set `max_containers` per function; alert on spawn backlog; reject/defer at the API when saturated. |
| 4 | Reclaim failed/stuck job compute | 4 | 3 | 3 | 4.0 | No Modal retries; killed jobs stay non-terminal up to ~70 min (WORK-02); hourly sweep is the only reaper | terminal within 5 min | Add Modal-level retry/timeout and a fast finalizer; make the sweep idempotent and Modal-aware. |
| 5 | Repair daily rollups to stop base-table scans | 4 | 4 | 2 | 8.0 | `admin_daily_metrics` 0 rows, `last_refreshed_at=null`; every dashboard falls back to base tables | daily rollup complete by 00:15 UTC | Add a Modal schedule for `refresh_daily_metrics_task`; verify one run; alert on stale rollup. |
| 6 | Bound artifact/storage growth | 3 | 4 | 2 | 6.0 | `CLEAN-01`: admin cleanup aborts before reaper/MinIO pruner; scheduled sweeps still run | 0 orphaned artifacts > 24 h | Initialize worker Redis before publish; run the pruner on a schedule; report bytes reclaimed. |
| 7 | Reduce email waste | 3 | 3 | 2 | 4.5 | 20 bounced, 1 complaint, 199 delayed; outbound ledger reports 0 | bounce < 2%, ledger parity | Validate addresses, suppress hard bounces, reconcile ledger with provider events. |
| 8 | Cache/deduplicate LLM prompts | 3 | 5 | 4 | 3.8 | Token cost per optimize/assist not exposed; no prompt cache or idempotency on repeated submits | measured tokens/job; cache hit > 30% | Hash prompt+model, cache deterministic completions; dedupe duplicate job submits by idempotency key. |
| 9 | Trim analytics payload work | 2 | 3 | 2 | 3.0 | 574 KB feature-adoption; 41 first-party-only events | < 100 KB; fewer writes | Batch first-party writes, sample high-volume events, drop unused event names. |
| 10 | Right-size warm containers | 3 | 3 | 4 | 2.3 | Warm API/LaTeX policy not measured; cold-start vs cost trade-off unknown | cost per successful job published | Measure warm hit rate and cold-start cost; tune `min_containers` per function, not globally. |

## C. Correctness/security prerequisites (not optional)

These are not "optimizations"; they block launch sign-off:

1. **PB-D03 (P0)** - BYOK credential routing.
2. **CAP-01/CAP-02** - all-on entitlement matrix and ungated BYOK key management; decide the intended plan matrix before any pricing launch.
3. **AAG-D01 (P1)** - one global auth rate-limit bucket; fix proxy trust or keying before launch traffic.
4. **WORK-01 (P1)** - Yjs history truncation at 500 updates; add snapshots/compaction.
5. **WORK-02 (P1)** - job recovery up to ~70 min; add worker-level retry/finalizer.
6. **AN-01/AN-02/AN-03 (P1)** - compile source loss, paid-conversion and MRR definitions; do not make revenue decisions on current dashboards.
7. **ST-D01/ST-D02** - trial/past-due entitlement and display disagreement.

## D. Measurement plan after sign-off

- Re-run `audit/scripts/latency_probe.py` (30 samples/endpoint) from the same region and a second region; record server `x-response-time` where available.
- Add stage timestamps to job events and recompute compile p50/p95/p99 from 20 warm jobs.
- Report cost per successful compile/optimize from Modal usage + provider token counts; label estimates.
- Gate optimization PRs on: p95 improvement >= 20% or cost/job reduction >= 15%, no error-rate regression, entitlement and quota tests green.

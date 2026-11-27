# Latency & cost architecture plan — compile pipeline

> **Superseded in sequencing by the Claude Opus 5.5 review:** [`latency-advisor-opus.md`](latency-advisor-opus.md). The measured diagnosis below stands; Opus reorders the work (instrument first, CPU + container warm-up before the high-risk finalization rewrite, then finalize stage A, pool/admission, and client-perceived path) and adds invariants, gates and missed mechanisms.

**Role:** independent architecture advisor (research only — no code changes, no deploys, no commits).
**Basis:** production measurements 2026-11-27 in [`../latency/compile-stages.md`](../latency/compile-stages.md), [`../latency/load-test.md`](../latency/load-test.md), [`../latency/cost.md`](../latency/cost.md), [`../optimization-backlog.md`](../optimization-backlog.md), [`../AUDIT-MASTER.md`](../AUDIT-MASTER.md); source read at `backend/modal_app.py`, `backend/app/core/engine_capacity.py`, `backend/app/api/job_routes.py`, `backend/app/workers/latex_worker.py`, `backend/app/services/render_engine/{artifacts,retention,geometry}.py`, `backend/app/services/storage_service.py`, `backend/app/core/modal_dispatch.py`.

**Measured baseline (server-side, submit→terminal):** warm 1-page compile p50 **20.73 s** / p95 35.61 s; 5-concurrent p50 **39.91 s** / p95 62.65 s; complex-10 p50 42.17 s / p95 51.88 s. Cost ≈ **$0.00023–0.00047 (simple) / $0.00039–0.00071 (complex)** per successful compile — so CPU spend is nearly irrelevant next to LLM tokens and retry waste on the combined paths.

---

## 1. Where the time actually goes

### 1.1 Warm simple budget (20.7 s p50, job `6ffbca83…` timeline, n=5–6 clean warm)

| Stage | Warm p50 | What is actually happening | Bound by |
|---|---:|---|---|
| Admission + dispatch | 0.40 + 0.96 = **1.36 s** | `submit_job` in [`job_routes.py:557`](../../backend/app/api/job_routes.py:557) (plan resolve, quota, `Compilation`+`JobFinalization` rows, Redis state) then `submit_async` in [`modal_dispatch.py:30`](../../backend/app/core/modal_dispatch.py:30) (semaphore, Redis authority check, synchronous Modal `spawn` in a thread) | code (serialized queries) + Modal SDK |
| Container claim (warm) | **1.35 s** | Modal input queue → warm `run_latex_task` container picks the input ([`modal_app.py:445`](../../backend/modal_app.py:445)) | architecture (Modal scheduling) |
| Worker init | **0.98 s** | module import → first task; `_init_worker_redis` + Celery `.apply` ([`modal_app.py:456-466`](../../backend/modal_app.py:456)) | code (import time, constant) |
| Validation + source prepare | **0.98 s** | validate, settings, compile-cache lookup, TeX write, aux workspace | code (small) |
| **pdflatex (2 passes)** | **9.16 s** | `start_engine_process` + `converge` re-run ([`latex_worker.py:2228-2492`](../../backend/app/workers/latex_worker.py:2228)) | **architecture: CPU** — no `cpu=` set on `run_latex_task`; Modal default 0.125 core. Same complex doc: **1.197 s vs 21.066 s (17.6×)** |
| Post-subprocess → 90% | 0.38 s | recorder check, log cache, progress event | code (small) |
| **Artifact upload / manifest** (90% → `artifact.ready`) | **3.8 s** (warm timeline; 5.9 s p50 all jobs) | `cache_compile_output` → `persist_render` ([`latex_worker.py:2546`](../../backend/app/workers/latex_worker.py:2546), [`artifacts.py:236`](../../backend/app/services/render_engine/artifacts.py:236)): 2 parallel R2 PUTs, **geometry inspection subprocess** (`pdfinfo`+`pdftotext -bbox-layout`, 6 s deadline — [`geometry.py:160`](../../backend/app/services/render_engine/geometry.py:160)), manifest PUT, then `register_manifest` ([`retention.py:134`](../../backend/app/services/render_engine/retention.py:134)): `asyncio.run` + **fresh NullPool DB engine** → new TCP/TLS connection, `FOR UPDATE`, 3–4 advisory locks, **3–4 R2 HEADs** (`_storage_objects_present`), INSERT, commit, dispose | **code-bound: serialized DB + R2 round trips on the critical path** |
| **Durable finalize** (`artifact.ready` → `job.pdf_extracted`) | **2.9 s** (warm timeline; 7.2 s p50, max 14.5 s) | `_extract_pdf_text` (`pdftotext -layout` subprocess, ≤3 attempts with 0.5 s sleeps — [`latex_worker.py:640`](../../backend/app/workers/latex_worker.py:640)) + `begin_finalizing` + `commit_latex_finalization` ([`latex_worker.py:985`](../../backend/app/workers/latex_worker.py:985)): **another fresh NullPool engine**, preflight session (`FOR UPDATE`, rollback), manifest bind or a second `upload_compilation_pdf`, reacquire session + `commit_success` (arbiter→Compilation→Resume lock chain), commit, dispose | **code-bound: second full DB connect cycle + second extraction subprocess** |
| Terminal publish | 0.21 s | `pdf_extracted` + `job.completed` (each an `EVAL` XADD+PUBLISH) | code (fast; measured <1 ms publish) |

Two structural facts stand out:

1. **There is no single dominant stage** — ~45% pdflatex, ~33% storage/finalization, ~7% admission, ~12% container claim+init on the warm path.
2. **Storage/finalization is two full, serialized pipelines** (upload+register → extract+commit), each creating fresh DB engines with `NullPool` (`[`retention.py:51`](../../backend/app/services/render_engine/retention.py:51)`, `[`latex_worker.py:1016`](../../backend/app/workers/latex_worker.py:1016)`) and each paying TCP+TLS connection setup to Neon and multiple serialized round trips. Job `474c7d3f…` compiled in **1.197 s** and still spent **24.2 s** in these two windows — proving they are independent of compile speed.

### 1.2 Scale-out budget (39.9 s p50 simple-5; 38.6–62.6 s range)

| Extra stage | Scale-out p50 | Bound by |
|---|---:|---|
| Container acquisition | **12.84 s** (p99 21.6 s) | architecture: Modal scheduling + boot of the ~1.7 GB texlive image ([`modal_app.py:147-171`](../../backend/modal_app.py:147)); `min_containers=1`, `buffer_containers=0`, `scaledown_window=120 s` ([`engine_capacity.py:16`](../../backend/app/core/engine_capacity.py:16)) |
| Worker init | 2.83 s (p99 5.8 s) | architecture: image init in a fresh container |
| Storage/finalize inflated | 12.1–14.2 s | code: same two pipelines, now on a cold, CPU-starved container sharing a busy host |

Scale-out penalty is 19.5 s p50 over warm — **architecture-bound** (pool sizing / keep-alive), not code-bound. `accepted_at → started_at` conflates Modal queue wait + boot + claim; it is not separable without Modal console input metrics (recorded in [`compile-stages.md:124`](../latency/compile-stages.md)).

### 1.3 Architecture-bound vs code-bound

| Stage | Class | Rationale |
|---|---|---|
| Container acquisition (scale-out) | **Architecture** | Modal scheduling + image boot; only pool/keep-alive or admission changes it. |
| pdflatex spread (1.2–21.1 s) | **Architecture (CPU allocation)** | `run_latex_task` sets no `cpu=`/`memory=`; Modal default 0.125 core with opportunistic burst. Inference, not measured fact (no Modal console — [`compile-stages.md:123`](../latency/compile-stages.md)). |
| ~1.2 s read-endpoint floor | **Architecture** | `/health` p50 1.19 s, `/readyz` 1.18 s from IST to us-east-1 ([`load-test.md:58`](../latency/load-test.md)); edge/network, not app work. |
| Storage/finalization (6.8 s warm, 12–25 s scale-out) | **Code** | Serialized fresh-engine DB sessions, per-object advisory locks, R2 HEAD verification set, two pdftotext subprocesses, all on the critical path after the PDF exists. |
| Admission + dispatch 1.36 s | **Code** | Serialized queries in `submit_job`; synchronous Modal spawn in a thread under a semaphore of 8. |
| Event volume (39–75 events/job, mostly `log.line`) | **Code** | One Redis `EVAL` per event; largest marginal Upstash line ([`cost.md:53`](../latency/cost.md)). |
| Worker init (0.98 s warm) | **Code** (constant) | Import + Celery apply; shrinkable, low value. |

**Conclusion:** the warm floor is ~1/3 architecture (CPU) and ~1/3 code (finalization) plus ~1/3 admission/claim/init. Both levers must move to reach a <12 s warm p50; either alone only gets ~13–15 s.

---

## 2. Options ranked by impact / cost / risk / effort

Ranking key: **Impact** = expected Δ on warm p50/p95 and burst p95; **Cost** = $/job or $/mo; **Risk** = correctness/durability risk; **Effort** = engineer-weeks. All options below are safe to apply **only after** the Phase-0 measurement in §4 (CPU is an inference today).

| # | Option | Expected impact | Cost | Risk | Effort | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Collapse storage/finalization into one pipeline** | −4.7 to −5 s warm p50 (6.8 → ~2 s), −8–14 s on scale-out jobs | saves held-container time (~$0.00002–0.00013/job) | Medium: arbiter/lock ordering is correctness-critical; tests exist (`test_worker_typed_finalization.py`, `test_finalization_terminal_replay.py`) | 2–3 w | **Do first (code)** |
| 2 | **Explicit CPU (and memory) for `run_latex_task`** | pdflatex p50 9.2 → est. 2–4 s simple; kills the 17.6× spread → p95 collapse | +$0.00026/job at 1.0 core (upper bound of current estimate) | Low (config via existing env plumbing) | 1–2 d + re-measure | **Do immediately after measurement** |
| 3 | **Warm pool + admission control together** | scale-out p95 62.7 → ~30 s: kills 13–21 s acquisition for expected burst sizes | +$0.75/mo per idle container (memory); admission is free | Low–Medium | 1 w | **Do as a pair, never pool without admission** |
| 4 | **Signed-URL/terminal-event ordering** | −1–3 s perceived: client can fetch PDF while `pdf_extracted`/completed events drain; removes one client round trip | ~$0 | Low | 0.5–1 w | **Do in Phase 1** |
| 5 | **Streaming preview / draft fast path** | editor previews: −3–6 s (skip second pass, geometry, durable registration) | small saving | Medium (semantics: preview vs final artifact) | 2–3 w | **Do in Phase 2** |
| 6 | **Batch/suppress `log.line` events** | −0.5–1 s WS fan-out load + Upstash −50% | −$0.0001–0.00016/job (largest marginal line) | Low | 0.5–1 w | **Do in Phase 1** |
| 7 | **Edge/region** | −1.2 s on reads and submit response, not compile server time | ~$0 | Low–Medium (product depends on region) | 1–2 w | **Do in Phase 2** |
| 8 | **DB/Redis pooling in workers** | −1–2 s on finalize (connection setup), −0.3–0.5 s elsewhere | ~$0 | Low | 0.5–1 w | **Fold into option 1** |
| 9 | **Retry policy** | compile: none measurable (0 failures); **combined/LLM: the dominant $ lever** (PB-D01: retry only 429/5xx/timeout) | saves tokens, not CPU | Low | 1 w | **Do in Phase 2 (cost, not latency)** |

### Detail per option

**1. Collapse the two finalization windows.**
Today after progress 90% the worker executes, serially:
`persist_render` (2× R2 PUT + geometry subprocess + manifest PUT + `register_manifest`: fresh engine, FOR UPDATE, 3–4 advisory locks, 3–4 R2 HEADs, INSERT, commit) → `_extract_pdf_text` (second pdftotext subprocess) → `commit_latex_finalization` (second fresh engine: preflight session, optional second upload, reacquire session, `commit_success`, commit).
Redesign: (a) one pooled async DB engine per worker process (drop per-call `NullPool` engines at [`latex_worker.py:1016`](../../backend/app/workers/latex_worker.py:1016) and [`retention.py:51`](../../backend/app/services/render_engine/retention.py:51)); (b) one DB transaction for arbiter check + manifest registration + compilation row (respect the existing arbiter→Compilation→Resume lock order); (c) run geometry inspection and text extraction **off the critical path** (fire-and-forget after `job.completed`, or in parallel with uploads) — they are client-visible in `pdf_extracted`, so emit that event when extraction finishes; (d) verify object presence with one batched R2 call set instead of serialized HEADs inside DB locks. Target: ≤2 s total on warm jobs (the backlog item 8b target). Do not weaken the `FOR UPDATE`/advisory-lock protocol — it exists to prevent a stale owner overwriting a live replacement's artifacts ([`retention.py:140-155`](../../backend/app/services/render_engine/retention.py:140)).

**2. Explicit CPU.**
The plumbing already exists: `capacity_options` reads `MODAL_LATEX_CPU` (0.25–16) and `MODAL_LATEX_MEMORY`/`MODAL_LATEX_MAX_CONTAINERS`/`MODAL_ENGINE_REGION` ([`engine_capacity.py:38-55`](../../backend/app/core/engine_capacity.py:38)); it is simply unset in production. Recommend `cpu=1.0, memory=2048` as the first measured step. Expected effect on the 9.16 s simple / 15.68 s complex p50 is large because pdflatex is single-threaded but is currently starved to a 0.125-core floor with burst contention — the 17.6× spread on identical source is the smoking gun. Cost moves toward cost.md's "upper bound" (~$0.00030–0.00037 CPU/job), offset by shorter finalization-holding time. This must be paired with Modal console access to confirm actual CPU usage (currently unobservable).

**3. Warm pool + admission.**
`min_containers=1` serves exactly one concurrent job; every burst pays 4–9 cold acquisitions at 12.6–21.4 s each. Set `MODAL_LATEX_MIN_CONTAINERS=2`, `MODAL_LATEX_BUFFER_CONTAINERS=2` (plumbing exists) **and** `MODAL_LATEX_MAX_CONTAINERS` at a deliberate ceiling (e.g. 8–10). Admission must be product-side: when the worker pool is saturated, either queue with a visible position or reject with 429, instead of paying 20 s acquisition per extra job. `/jobs/health` must expose the Modal spawn backlog (Q-01) before this ships — otherwise operators tune blind.

**4. Signed-URL/terminal ordering.**
`job.completed` is emitted after all durability work; the client then still has to call `/download/{job_id}` (p50 2.14 s, TTFB-bound). Include a presigned URL (or the R2 public URL from the manifest, which already exists) in the `artifact.ready`/`job.completed` payload so the browser can start the fetch immediately. Never emit `job.completed` before the durable row commit — the exactly-once terminal contract is load-bearing (a duplicate-terminal-event defect was observed in the events audit, [`compile-stages.md:125`](../latency/compile-stages.md)).

**5. Streaming preview fast path.**
The editor has `draft_mode` and a distinct preview flag ([`job_routes.py:771-776`](../../backend/app/api/job_routes.py:771)); the compile path always runs `converge` (second pass) and the full artifact/geometry/finalization pipeline. A preview variant could: single pass, skip geometry projection, skip durable `RenderArtifactManifest` registration, terminal event after upload. This is the largest remaining warm-path cut after options 1–2, but it changes artifact semantics — gate it on a "preview vs final" flag that cannot be spoofed into the durable history (auto-save already skips previews, [`latex_worker.py:2688-2691`](../../backend/app/workers/latex_worker.py:2688)).

**6–8. Minor code levers.** Batch `log.line` into one Redis `EVAL` per ~200 ms window (39–75 events/job today — the largest Upstash line); reuse one engine in workers; edge/CDN and region work is read-path only (see backlog A-7), worth doing but does not move compile p50.

**9. Retries.** Compile has zero failures in the sample, and Modal retries are deliberately not configured for compile (double-execution guard, [`modal_app.py:458-460`](../../backend/modal_app.py:458)). For cost, the real lever is LLM: deterministic failures are retried and burn tokens (PB-D01). At $0.0002–0.0007 per compile, one wasted LLM optimization retry can cost more than ~100 compiles.

---

## 3. Target architecture

### 3.1 Diagram

```
 Client (browser, IST)                       Modal (us-east-1)
┌──────────────────┐      ~1.2s edge floor    ┌──────────────────────────────────────────┐
│ editor / viewer  │───HTTPS/WS────────────────│ Edge → FastAPI ASGI (min_containers=1)    │
└──────────────────┘                          │  POST /jobs/submit:                        │
                                              │   plan+quota → durable rows → Redis state  │
                                              │   → admission gate → spawn (sem 8)         │
                                              │            │ Modal input queue              │
                                              │            ▼                                │
                                              │  run_latex_task pool                        │
                                              │   cpu=1.0, mem=2Gi, min=2, buffer=2,        │
                                              │   max=8, scaledown 120s                    │
                                              │   ┌──────────────────────────────┐         │
                                              │   │ claim → validate → 1–2 pass   │         │
                                              │   │ pdflatex (explicit CPU)      │         │
                                              │   │   → ONE finalization txn:    │         │
                                              │   │   pooled DB conn             │         │
                                              │   │   parallel R2 PUTs           │         │
                                              │   │   arbiter+manifest+row commit│         │
                                              │   └──────────────────────────────┘         │
                                              │     │ terminal event (+ presigned URL)      │
                                              │     ▼                                      │
                                              │  Redis Stream + Pub/Sub ──▶ WS /jobs        │
                                              │  (batched log.line, <40 events/job)         │
                                              │                                             │
                                              │  off-path: pdftotext extraction, geometry    │
                                              │  inspection, compile-cache write            │
                                              └──────────────────────────────────────────────┘
                                              R2: content-addressed PDF/synctex/geometry/manifest
                                              Neon: Compilation + JobFinalization + RenderArtifactManifest
```

### 3.2 Request lifecycle (target)

0. Client POSTs source; edge + API floor ≈ 1.2 s.
1. **Admission** (≤0.4 s): plan/quota, durable rows, Redis lifecycle; saturated pool → queue position or 429, never silent 20 s waits.
2. **Dispatch** (≤0.5 s): Modal spawn returns.
3. **Claim** (warm ≤1.5 s, cold ≤13 s but rare): warm pool absorbs expected burst; cold path only for real scale-out.
4. **Init** (≤1 s warm): module import amortized by warm container.
5. **Compile** (simple ≤4 s, complex ≤8 s at explicit 1.0 CPU): one pass + converge when aux files demand it.
6. **Single finalization** (≤2 s): uploads in parallel, one DB transaction, manifest registration, terminal row.
7. **Terminal events** (<0.2 s): `job.completed` carries the presigned artifact URL.
8. **Deferred work** (not on the clock): text extraction → `pdf_extracted`; geometry; cache remember; auto-save checkpoint.

**Target SLO shape:** warm simple p50 **≤ 12 s** (backlog item 8), burst (≤5 concurrent) p50 ≤ 25 s / p95 ≤ 30 s, warm finalize ≤ 2 s, 0 job failures in any benchmark run.

---

## 4. Phased migration plan

### Phase 0 — Measure first (0–2 weeks)
No latency code changes except config that is already supported.

1. Set `MODAL_LATEX_CPU=1.0` (+ memory) on `run_latex_task`; deploy to a staging environment.
2. Obtain **Modal console metrics** (blocker, recorded in [`compile-stages.md:138`](../latency/compile-stages.md)): per-container CPU/memory, input-queue wait, container-start time, restart count. Without it, the CPU-starvation claim remains an inference and no further tuning is scientific.
3. Add sub-stage spans inside the two finalization windows (R2 PUT, geometry, register_manifest, extract, commit) so "storage/finalization" stops being an event-boundary bucket.
4. Re-run the stage benchmark (§6 scenario set A) and publish per-job cost at explicit CPU.

**Exit criteria:** pdflatex simple p50 ≤ 5 s at explicit CPU; finalize sub-stage attribution available; 0 job failures; cost/job measured (not estimated) within ±2×.

### Phase 1 — Structural wins (2–6 weeks)
1. Collapse finalization (option 1): pooled engine, single transaction, parallel uploads, deferred extraction/geometry, batched R2 verification.
2. Signed URL in terminal event (option 4).
3. Batch `log.line` (option 6).
4. Warm pool 2+2 with `max_containers` cap and admission/429 path (option 3), gated on `/jobs/health` Modal-backlog visibility (Q-01).
5. Re-run full benchmark set.

**Exit criteria:** warm simple p50 ≤ 12 s and p95 ≤ 30 s; warm finalize ≤ 2 s; 5-concurrent p50 ≤ 25 s; error rate 0.0%; duplicate-terminal-event count 0 across the run; cost/job unchanged or lower; entitlement/quota tests green.

### Phase 2 — Product-level (6+ weeks)
1. Preview fast path with explicit preview-vs-final semantics (option 5).
2. Edge/CDN/region work for read endpoints (backlog A-7, ~1.2 s floor).
3. LLM retry classification + prompt caching (PB-D01, backlog B-2/B-8) — the real cost program.
4. Capacity management: publish pool hit-rate and cost-per-successful-compile (backlog B-10), tune per launch concurrency.

**Exit criteria:** editor preview p50 ≤ 6 s; read endpoints p95 ≤ 300 ms in-region; combined-job cost per success tracked and LLM retry spend reduced ≥50%; documented pool sizing methodology.

---

## 5. What NOT to do

1. **Do not add a result cache that hides defects.** An exact-render cache already exists (`restore_compile_cache`/`remember_compile_cache`, [`latex_worker.py:909`](../../backend/app/workers/latex_worker.py:909)); adding coarser caching (e.g. per-user, per-template) would freeze current compile defects and duplicate-terminal-event behavior into production. Caching is keyed on exact content today — keep it that way.
2. **Do not raise `min_containers` without `max_containers` + admission.** More warm containers without a ceiling and a saturation policy just converts latency spikes into a cost and DB-lock-contention problem (every finalization takes `FOR UPDATE` on `JobFinalization`).
3. **Do not blindly raise CPU.** 1.0 core is ~8× the lower-bound CPU cost; the trade-off must be measured per the Phase-0 plan. Target a documented CPU/price point, not a maximum.
4. **Do not remove the second pdflatex pass, the recorder check, or read-confinement checks to gain speed.** `converge` exists for reference/aux correctness; the recorder-based `\openin` confinement check is a security gate ([`latex_worker.py:2464-2473`](../../backend/app/workers/latex_worker.py:2464)). These are the last things to optimize.
5. **Do not publish terminal events before the durable commit**, and do not "fix" perceived latency by emitting `job.completed` early with a lazy upload. The lifecycle/arbiter protocol (owner token + epoch + lease, [`job_lifecycle.py`](../../backend/app/workers/job_lifecycle.py)) is what keeps duplicate delivery and stale-owner overwrites out; one duplicate-terminal-event defect was already observed ([`compile-stages.md:125`](../latency/compile-stages.md)).
6. **Do not move extraction/geometry into the API container.** The API image already carries the full toolchain; adding pdftotext/pdfinfo subprocesses there blocks the one warm API container under burst.
7. **Do not chase R2 storage cost.** Object bytes are fractions of a cent per thousand jobs ([`cost.md:105`](../latency/cost.md)); the win is held container time.
8. **Do not switch compilers for speed** (xelatex/lualatex are slower and change output; templates depend on current engine behavior).
9. **Do not trust per-job cost numbers without a volume assumption.** At the audit's 38 jobs, the fixed warm pool is 33–66× the entire variable spend ([`cost.md:72`](../latency/cost.md)).

---

## 6. Benchmark plan

Run after each phase, from the same IST workstation and an in-region (us-east-1) probe for the server-side split. **All runs: hard ceiling 40 compiles, full clear of warm pools before cold scenarios (wait ≥ `scaledown_window` + margin), no payment/LLM calls.**

| # | Scenario | n | Purpose |
|---|---|---|---|
| A1 | Simple, 1-concurrent, warm | 20 | new warm p50/p95 baseline; acceptance target |
| A2 | Complex, 1-concurrent, warm | 10 | complex SLO |
| A3 | Simple, 5-concurrent, **from-zero** | 10 | scale-out + admission behavior (the honest burst test; 10-concurrent-after-5 is contaminated by residual warm pool) |
| A4 | Complex, 10-concurrent, warm-ish | 10 | saturation + CPU contention under explicit CPU |
| A5 | Exact-cache hit (repeat identical source) | 10 | cache path p50; verify no artifact duplication |
| A6 | Preview/draft path (Phase 2) | 20 | fast-path p50 vs final-path A1 |
| A7 | Read sweep: `/health`, `/state`, `/download`, `/jobs/health` | 30 each | edge floor and Modal backlog visibility |

**Metrics per job:** all stage p50/p95/p99 from §1.1 (admission, dispatch, acquire, init, pdflatex, artifact_upload, durable_finalize, terminal), server total, client submit p50, WS delivery lag per event type, PDF download TTFB, event count, error/duplicate-terminal count, estimated cost per job.

**Acceptance thresholds (Phase 1 exit):** warm simple p50 ≤ 12 s; warm simple p95 ≤ 30 s; warm finalize ≤ 2 s; 5-concurrent p50 ≤ 25 s; 0 failed jobs; 0 duplicate terminal events; cost/job within 20% of Phase-0 measurement; p95 improvement ≥ 20% vs the 20.73/35.61 s baseline (backlog gate D).

**Rollback criteria (abort the change, not just the run):** any job failure or 5xx not explained by fixture error; duplicate terminal events; p95 regression > 10% vs baseline on two consecutive runs; DB lock-timeout errors (`SET LOCAL lock_timeout = '5s'` tripping) in finalization; cost/job > +50%; quota-refund or entitlement test failures.

---

## 7. Cost-model cross-check

The arithmetic in [`cost.md`](../latency/cost.md) checks out against its own assumptions (recomputed: CPU lower 0.0000131 × 0.125 × 22.549 = $0.0000369 ✓; upper ×1.0 = $0.0002954 ✓; memory $0.0000063 ✓; R2 Class A $0.0000045 ✓; Upstash 90 cmds × $0.20/100k = $0.00018 ✓). What is **not** supportable:

1. **The CPU bounds stop being a range the moment you set `cpu=`.** Today's $0.00004–0.00037/job spread is "unknown actual allocation". After Phase-0 sets `cpu=1.0`, the bill deterministically approaches the upper bound (~$0.00030–0.00037 CPU/job). Treat the lower bound as historical only.
2. **Upstash command estimate (±2–3×).** `publish_event` is one Lua `EVAL` containing XADD + PUBLISH internally ([`event_publisher.py:497`](../../backend/app/workers/event_publisher.py:497)); Upstash's billing of Lua-internal commands is unconfirmed ([`cost.md:110`](../latency/cost.md)). The estimate also omits per-job Redis ops outside events: lifecycle hashes, cache keys, coalescing slots, admission, state writes. This is the largest variable-cost uncertainty and could make Upstash 2–3× the stated line.
3. **Idle-pool cost is an unverified residual-resource assumption.** $0.0246/day/container assumes only 128 MiB memory is billed while idle. With 3–4 warm containers this is $2.25–3/mo; fine either way, but do not put it in a launch budget without a Modal bill confirming it.
4. **Boot-time billing is excluded.** Modal bills container boot CPU; every cold acquisition (4–9 per burst) adds unmeasured cost. Not material at these rates, but it makes the "cost of scale-out" line an underestimate.
5. **Neon query cost is excluded.** Finalization alone does ~10–20 queries/job (preflight, arbiter, locks, inserts) and Neon typically bills CPU-time; unobservable from the app. At 10k jobs/mo this line is likely comparable to R2 — unknown sign and magnitude.
6. **Egress is excluded.** R2 lists $0 egress, but the audit could not confirm the bucket backend is R2 vs MinIO/other S3 ([`cost.md:111`](../latency/cost.md)); a non-R2 backend could bill egress on every `/download`.
7. **The claim "LLM and failed retries matter more than CPU" is correct** — but only for `combined`/`llm_optimization` jobs, which the compile cost test did not exercise. Compile-only jobs have zero tokens ([`cost.md:24`](../latency/cost.md)); one wasted LLM retry (PB-D01) plausibly exceeds the cost of ~100 compiles. The cost program's first target is retry classification, not compile CPU.

**Net:** the model is sound as a magnitude estimate and its ranking (fixed warm capacity ≫ event volume ≈ CPU ≫ storage bytes) survives ±3× uncertainty on Upstash and ±8× on CPU. Do not make pricing decisions off the current per-job figures; re-publish after Phase-0 measurement.

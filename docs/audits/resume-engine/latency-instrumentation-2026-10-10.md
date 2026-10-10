# Latency instrumentation follow-up — 10 October 2026

This change adds diagnostics to PR #1833; it does not establish a production speedup, alter capacity, deploy an engine, or close latency acceptance. It was developed on `fed556813b68a999e03813bf2ecdf170259ba834`. Integration with the separately updated billing/builder branch #1834 still needs final-head verification.

## What the existing measurements establish

The [production audit](production-latency-audit-2026-10-08.md) remains the production baseline: 18.823 seconds guest action-to-visible-PDF and 57.736 seconds for a saved-editor scenario containing overlapping jobs. These are diagnostic samples, not p95 acceptance. There is no new production sample in this follow-up.

The committed local whole-worker comparisons must not be presented as a speedup:

| Warm isolated worker condition | Baseline p50 / p95 | Candidate p50 / p95 |
| --- | --- | --- |
| Fresh render | 1.008 / 1.188 s | 1.644 / 2.095 s |
| Exact cache | 0.246 / 0.340 s | 0.430 / 0.598 s |

Sources: [baseline](render-pipeline-latency-baseline-2026-10-08.json), [candidate](render-pipeline-latency-candidate-2026-10-08.json). Each records 30 measured pairs, the same managed-English fixture and engine image, and a host-load label of `quiet`. TeX, storage and finalization all slowed in the candidate run. The available observations cannot distinguish host effects from a code regression; a controlled alternating A/B rerun is required.

In the baseline, warm TeX p50 was 657 ms, artifact storage 112 ms and durable finalization 82 ms. The corresponding single browser sample spent another 498 ms between verified blob and paint. Those observations have different sample sets and overlapping boundaries; they are not additive percentile estimates. The one-second fresh and 500-ms cached action-to-paint targets remain unmet or uncertified.

The [parallel binary upload experiment](production-2026-10-08/upload-storage-paired.json) separately measured serial/concurrent p50 of 299.64/161.09 ms with an **explicitly simulated 40-ms delay per PUT**. It excludes geometry, manifest/DB registration, admission, TeX and browser work. It does not resolve the whole-worker comparison.

## Diagnostic changes

- `worker_initialization` now measures memoized native imports and ORM mapper preparation. It emits once per cold runtime configuration, including failed preparation, and excludes warm no-op calls. It is not an image-pull, container-boot or pre-import measurement.
- Modal compile, combined and LLM wrappers attach the existing trace before preparation, while retaining preparation before task import/execution.
- `queue_wait` records the existing API-submission-to-task-entry observation using the existing clock-skew clamp. It includes dispatch/startup and overlaps initialization; it is not pure broker wait.
- `source_prepare` measures direct and combined pre-cache validation/settings/transformation work. Direct auto-fit includes its existing preparatory probes and progress publication. Successful timing ends before cache lookup/coalescing/final rendering; failures finish once before cleanup.
- Direct phase observations now emit the same slow-phase JSON diagnostics as spans when duration is at least 250 ms. The payload remains only a fixed phase, fixed outcome and duration, plus existing trace context. No source, filename, user/document/job identifier or provider response is added to phase metadata.

## Remaining critical path

1. Exact-cache admission bypasses a renderer queue, but still awaits a bounded executor, cached PDF retrieval, fresh manifest/DB registration and durable finalization before returning the job ID. It shares the eight-per-event-loop submission limit with broker SDK calls. Measure saturation separately from an isolated hit before changing that design.
2. PDF and SyncTeX uploads overlap, but geometry, its upload, manifest upload/registration and publication remain on the artifact-ready path. Required durability and identity checks must remain intact when investigating those intervals.
3. Duplicate-render coordination avoids duplicate TeX work, but waiting jobs still occupy workers. Burst behavior and regional round trips need real distributions; a single warm-container setting is not evidence of burst readiness.
4. Browser verified-blob-to-paint remains material even after PDF.js preloading. The existing `PDF_USER_ACTION_PAINT` and `PDF_RENDER_PAINT` measurements need distinct cold/warm/browser/device sample groups.

## Validation of this patch

- Final DB-free selection: **57 passed, one deselected**, RuntimeWarnings treated as errors. Includes new phase-boundary/once-only/error tests, queue timestamp/skew tests, actual extracted Modal wrapper ordering, worker preparation, structured logging, bounded capacity validation, upload/check join behavior and broker responsiveness.
- Existing Modal dispatch/task/dependency-order contract selection: **four passed, 25 deselected**.
- Full backend Ruff (`app test scripts modal_app.py`), Python compilation and `git diff --check`: passed. The aggregate lint check initially found one existing import-group spacing error in the render benchmark script; this follow-up fixes that formatting only.
- A broader selection with `SKIP_INFRA_CHECK=1` produced **67 passed, three failed, one deselected**. The three existing task-timing tests require their worker environment: two fail before task admission because worker Redis is not initialized; one produces no completion-timing record. Running those tests on unchanged `fed55681` with the same no-infrastructure setup reproduces all three failures (10 passed, three failed). Assertions were not relaxed. This is not a full backend pass.
- Local native LuaLaTeX has no `lualatex.fmt`, so this follow-up does not claim a new real-engine benchmark. No live model call, payment, production mutation or deployment was performed.

## Acceptance plan after a reviewed rollout

1. Attest exact frontend/backend commits, engine image/assets, compiler, capacity and API/worker/data regions; retain sanitized identities with every run.
2. On the same build/image and controlled host, alternate baseline/candidate runs. Separate cold-first-job, warm fresh-source, exact-cache, and identical/distinct-source bursts. Use at least 30 valid samples per warm condition, report sample counts, failures/timeouts and p50/p95, and retain unsuccessful runs. Use ordinary authorized test-account quota.
3. Correlate admission, dispatch wait/call, initialization, queue, source preparation, TeX, drain, storage, artifact-ready, finalization, download and first paint. Compare within-clock intervals; do not sum overlapping metrics or infer cold boot from import-to-first-task time.
4. Verify guest and saved flows, duplicate clicks, interrupted/repeated previews, mobile/desktop rendering and unchanged content correctness. Run wider browser and full backend/CI gates on the exact integrated head.
5. Separately verify configured-provider conversion success and prompt terminal failure/refund recovery under explicit provider-test authorization. Mocked provider tests establish behavior, not live availability or output quality.
6. Keep the one-second fresh/500-ms cached action-to-paint acceptance open until those end-to-end distributions support it. Investigate the dominant measured phase before tuning capacity or proposing a new optimization.

# Compile stage breakdown - lead measurement (independent of the performance auditor)

**Window:** 2026-11-27T11:33:34Z-11:35:09Z (warm single jobs), 11:40-11:48Z (concurrent load).
**Identity:** `pro-monthly` for warm jobs and simple/concurrent; `basic-annual` for four recovery/cancel jobs.
**Method:** read job events from `GET /jobs/{id}/stream`, joined to `compilations` rows. Stage timestamps are server epoch seconds. The performance auditor's `compile-stages.md` is the primary load report; this file is an independent cross-check.

## Warm single 1-page compile (n=6)

| Job | Queue wait | Worker init/validate | pdflatex + post | Total | PDF |
|---|---:|---:|---:|---:|---:|
| `6ffbca83…` | 3.67 s | 0.98 s | 16.47 s | 21.12 s | 114,018 B |
| `b98199f9…` | 3.61 s | 1.08 s | 15.42 s | 20.11 s | 114,018 B |
| `d582e594…` | 3.49 s | 0.98 s | 16.00 s | 20.47 s | 114,018 B |
| `45efe5dc…` | 3.69 s | 0.98 s | 16.06 s | 20.73 s | 114,018 B |
| `25f2ce19…` | 5.04 s | 1.37 s | 20.80 s | 27.21 s | 9,827 B |
| `727b62ed…` | 14.49 s | 0.68 s | 20.44 s | 35.61 s | 114,018 B |
| **Median** | **3.68 s** | **0.98 s** | **16.26 s** | **20.92 s** | - |

- `pdflatex` is **~78% of total**; queue wait is the second-largest and spikes to 14.5 s under concurrent load.
- Artifact upload + durable finalize + publish is 3.7-6.9 s in the detailed event timeline; that is included in the "pdflatex + post" column for jobs where the split was not exposed.
- One job with a smaller PDF (9,827 B) was slower (27.2 s), so output size is not the driver.

## Concurrent simple-5 (5 simultaneous)

Server totals: 20.61 s, 62.65 s, 40.99 s, 38.52 s, 39.91 s (median ~40 s, max 62.6 s). All five completed, one terminal event each, 114,018 B PDFs. Concurrency inflates p50 from ~21 s to ~40 s (~1.9x) and max to ~3x.

## Complex-1 (sequential, n=3)

Server totals: 33.19 s, 25.67 s, 27.76 s (median 27.76 s). All completed. Complex documents add ~7 s over the simple warm median.

## Failures observed

- Unicode Arabic `م` in LaTeX failed in 8.0 s with `error_class:"engine"`; the API returned a failed job, not a 5xx.
- A second engine failure (plain document) failed in 5.3 s with `error_class:"engine"`; the error message was generic.
- A verbose document stalled at `processing/10%` or `processing/90%` for >120 s and was cancelled; see WSE-08. The 90% stall is reproducible across the events and reliability runs.

## Interpretation

1. **Container/queue is not the dominant cost at warm single concurrency.** Pre-compile work is ~1 s; queue wait is 3.5-3.7 s warm and the largest variance source under load.
2. **pdflatex execution is the dominant cost.** Tuning API JSON, entitlement checks, or the frontend cannot move p95 materially; the compile container and LaTeX pass are the target.
3. **Concurrency roughly doubles latency with no queue rejection.** A 5-way burst still completed, but tail latency reached 62.6 s. Capacity planning should use the 5-concurrent distribution, not the warm single median.
4. **The 90% stall is a correctness/recovery issue, not just slowness.** It blocked the >500-event replay test and left jobs non-terminal until cancellation.

## Cost note

Per-job cost cannot be measured from the public API. Modal CPU/memory time is the likely dominant cost (pdflatex ~16 s), followed by artifact storage/egress; LLM cost is zero for these CPU-only compiles. See `audit/latency/cost.md` for the performance auditor's estimate.

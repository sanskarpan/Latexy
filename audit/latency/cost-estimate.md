# Cost estimate - compile and AI flows (labelled estimate)

**Status:** estimate, not a provider invoice. The audit has no Modal billing export or LLM token ledger access. The performance auditor's `cost.md` is the primary report; this file records the arithmetic used by the lead.

## Measured inputs

| Input | Value | Source |
|---|---:|---|
| Warm 1-page compile, submit to terminal | 20.9 s median | `latency/lead-compile-stages.md` |
| Warm pdflatex + post | 16.3 s median | same |
| Complex-1 | 27.8 s median | same |
| Complex-10 | 42.9 s median | performance load JSON |
| Simple-5 | ~40 s median, 62.6 s max | performance load JSON |
| PDF size | 9.8-114 KB | compilations |
| LLM calls in audit | 2 optimize, 2 assist, 1 ATS, 1 deep analyze | cohort reports |

## Modal compute estimate

Modal list prices used (published, rounded): CPU **$0.000038 / core-s**, memory **$0.0000045 / GiB-s**. The deployment does not set explicit CPU/memory for LATEX/ORCHESTRATOR, so the estimate is bracketed:

| Assumption | 21 s compile | 43 s compile |
|---|---:|---:|
| 1 vCPU, 2 GiB | ~$0.0010 | ~$0.0020 |
| 2 vCPU, 4 GiB | ~$0.0020 | ~$0.0040 |
| 4 vCPU, 8 GiB | ~$0.0040 | ~$0.0080 |

Storage: 114 KB per PDF; at $0.02/GB-month, 10,000 PDFs/month is ~1.1 GB, ~$0.02/month. Egress: 114 KB at $0.05/GB is ~$0.000006 per download.

**Compile cost is not the main cost driver.** Even the 4 vCPU upper bound is under one cent per compile. The main cost drivers are LLM tokens, failed/retried LLM jobs, and always-warm containers.

## LLM cost

No token ledger is exposed. A typical optimize/assist call on a 1-2 page resume is 2k-8k input tokens and 500-2k output tokens. At current frontier prices, that is roughly **$0.01-$0.10 per successful call**, i.e. 5-50x a compile. Failed optimizations (PB-D01) retry and fail, so the spend produces no artifact. That is the highest-value cost defect.

## Cost of a failed/retried job

- A deterministic LLM failure that retries once doubles token spend and still fails; the quota unit is refunded but the provider spend is not.
- A killed/stuck Modal job can hold a container for up to the 300 s timeout plus recovery; at the upper-bound 4 vCPU rate that is ~$0.05 per stuck job.
- A cancelled job still pays for the work already done; the audit observed cancellation after >120 s at 90%, so most of the compile cost was already spent.

## Targets

- Publish `tokens_in`, `tokens_out`, `provider`, `model` per LLM job and a daily cost rollup.
- Block retries on deterministic provider errors (PB-D01) and alert on retry rate > 5%.
- Right-size warm containers from measured queue wait and cold-start data, not the stale "~3.5 s" comment.
- Track cost per successful compile/optimize, not cost per request.

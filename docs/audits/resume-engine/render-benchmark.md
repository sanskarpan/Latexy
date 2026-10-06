# Resume renderer benchmark

This is a controlled rendering experiment, not a production latency measurement. It executes real `pdflatex` and production sandbox/read-confinement gates inside a network-disabled worker container. Redis transport is simulated with a fixed delay; Redis Lua execution, real queueing, admission, dispatch, durable persistence, AI generation and browser PDF paint are excluded.

The baseline is the unchanged `_run_latex_stage` function extracted from main `317b9b3d0b1cf05cb4a007dbf179129993d67ba5`, loaded against the same helper modules as the new implementation. The input is a generic one-page resume. Each condition has 20 measured samples after two warmups. Baseline/current order alternates within paired iterations. Both use fresh temporary workspaces in a warm container.

The Docker image was `latexy-local-worker:latest`, image ID `sha256:37fc35a6250979d9d87ea8fa236892ebe890ad52f92ba68e7173165e3046c717`. The host also ran development/test containers. Alternating pair order mitigates drift; it does not eliminate CPU/storage contention or make this a production benchmark.

## Ordinary fixture (19 compiler log events)

| Simulated RTT | Renderer | p50 wall time | p95 wall time | Median transport requests |
| --- | --- | ---: | ---: | ---: |
| 0 ms | baseline | 1.372 s | 2.033 s | 89 |
| 0 ms | buffered | 1.517 s | 1.875 s | 32 |
| 5 ms | baseline | 1.959 s | 3.325 s | 97 |
| 5 ms | buffered | 1.539 s | 2.476 s | 29 |

At 5 ms simulated RTT the paired run observed about 21% lower median and 26% lower p95 wall time. At zero RTT the buffered median was slower and the p95 was lower. The earlier blocked-order experiment did not show a material 5 ms end-to-end gain and is retained in `render-benchmark-blocked-order.json`. This variation is a reason to avoid promising a fixed production speedup. Transport request reduction is consistent; actual document latency depends on compiler work and deployment conditions.

All measured PDFs had a valid PDF header and identical normalized extracted text and page count. An attempted external file read was rejected before subprocess creation. A real infinite TeX loop was killed by the independent watchdog. The fractional injected timeout is displayed as `0s` by the existing integer timeout error formatter; elapsed termination was about 0.23 seconds.

The subprocess timing field still includes stdout draining and publication. It is not a measurement of raw process exit. The sub-second p95 target is not established by these results.

## Reproduce

Use `backend/scripts/benchmark_resume_render.py --baseline /evidence/render_baseline.py --samples 20 --rtt-ms 0 5`. Run with the backend mounted read-only at `/workspace`, this evidence directory mounted read-only at `/evidence`, `PYTHONPATH=/workspace`, `SKIP_ENV_VALIDATION=true`, `ALLOW_LOCAL_LATEX_ENGINE=true`, dummy database/Redis/JWT environment values, and Docker `--network none`. Do not mount credentials or a production `.env`.

The optional `--extra-log-lines 100 --rtt-ms 0 5 25` condition inserts 100 harmless TeX `typeout` messages without changing the displayed resume. It is a log/transport stress fixture and should not be described as an ordinary document benchmark. Complete per-sample results, fixture hashes and correctness assertions are retained in the JSON evidence files.

## Log/transport stress fixture (122 compiler log events)

This variant adds 100 harmless `typeout` messages to the same document. It isolates how verbosity and remote transport multiply serial publication/cancellation costs; it is not representative of every resume. Each condition has 20 measured samples after two warmups, with alternating paired renderer order.

| Simulated RTT | Renderer | p50 wall time | p95 wall time | Median transport requests |
| --- | --- | ---: | ---: | ---: |
| 0 ms | baseline | 1.124 s | 2.998 s | 396 |
| 0 ms | buffered | 1.081 s | 2.180 s | 24 |
| 5 ms | baseline | 3.060 s | 4.511 s | 428 |
| 5 ms | buffered | 1.093 s | 2.655 s | 23 |
| 25 ms | baseline | 10.168 s | 10.650 s | 508 |
| 25 ms | buffered | 0.838 s | 1.895 s | 14 |

All PDFs again had identical normalized text/page count and valid headers. Hostile input was rejected before spawning TeX, and the independent watchdog stopped a real infinite loop. At 5 and 25 ms simulated RTT, the stress fixture demonstrates that batched publication and bounded cancellation polling remove the serial per-line transport multiplier. These results support the mechanism, not a universal speedup claim. No real Redis server, Lua workload, network jitter, tenant lifecycle, durable storage or browser rendering was included.

The zero-RTT result and ordinary fixture remain necessary context: buffering adds machinery and compiler/host work can dominate. Production p50/p95/p99 and the sub-second fresh PDF target need deployment traces and larger realistic template/load corpora.

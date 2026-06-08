# Benchmarks

## Environment
- Local macOS arm64 workstation
- Backend on `http://localhost:8030`
- Frontend on `http://localhost:5180`
- Local Docker Postgres/Redis/MinIO

## Benchmark 1 — `/health` concurrency sample
- Method:
  - `40` requests
  - `10` worker threads
  - Python `urllib.request`
- Result:
  - requests: `40`
  - wall time: `0.111s`
  - throughput: `361.64 req/s`
  - p50: `7.04ms`
  - p95: `92.52ms`
  - max: `92.59ms`
- Interpretation:
  - Health endpoint latency is low and stable on the local stack.

## Benchmark 2 — LaTeX compile success
- Method:
  - submit valid `latex_compilation` job to `/jobs/submit`
  - poll `/jobs/{id}/result`
- Result sample:
  - compile time: `1.99s`
  - page count: `1`
  - extracted text: present
- Interpretation:
  - Single-document compile path is healthy on local infra.

## Benchmark 3 — LaTeX compile failure
- Method:
  - submit invalid `latex_compilation` job to `/jobs/submit`
  - poll `/jobs/{id}/result`
- Result:
  - terminal failure payload persisted and returned
- Interpretation:
  - Failure path now resolves deterministically instead of hanging on missing result state.

## Limitations
- No before/after load baseline was captured for the entire system.
- No soak or sustained-pressure benchmark was executed in this pass.
- Browser-performance metrics such as LCP/INP were not captured in this pass.

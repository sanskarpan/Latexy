# Audit Log

## Scope
- Date: 2026-06-06
- Branch: `track/479-smoke-spec`
- Audit mode: production stabilization / QA / reliability / security / performance pass

## Repository Discovery
- Backend application code: `backend/app` (`438` files total, `133` Python modules)
- Frontend application code: `frontend/src` (`203` files)
- Test surfaces: `backend/test` + `frontend/e2e` (`118` files)
- Deployment/runtime assets: `docker-compose*.yml`, `k8s/`, `monitoring/`, `.github/workflows`, `scripts/`

## Runtime Model Confirmed
- Shared local infra: Docker `latexy-postgres`, `latexy-redis`, `latexy-minio`
- Local app layer: backend (`:8030`), frontend (`:5180`), Celery worker, Celery beat
- Startup path used: `./scripts/dev.sh app` against local Docker infra

## Major Observations
- Root `.env` contains live-looking provider secrets and a remote Neon `DATABASE_URL`.
- Local runtime path is healthier when forced onto local Docker infra instead of trusting root `.env`.
- Backend and worker startup are clean on the local stack.
- Prometheus metrics are exposed and structured logging is active.

## Confirmed Findings

### A-001 High — Terminal failed LaTeX jobs did not persist final results
- Evidence:
  - `GET /jobs/{id}/state` reached `failed`
  - `GET /jobs/{id}/result` returned `404`
- Root cause:
  - `backend/app/workers/latex_worker.py` returned failure payloads without calling `publish_job_result()`
- Resolution:
  - Persisted terminal result payloads for validation failures, invalid watermark, cancellation, timeout, non-zero compiler exit, and unrecoverable exceptions

### A-002 High — Successful compile text extraction was brittle
- Evidence:
  - Successful compile result returned `extracted_text: null`
  - Host `pdftotext` on the same generated PDF produced readable text
- Root cause:
  - Worker extraction path depended on brittle `pdftotext` assumptions around Docker compile flow
- Resolution:
  - Added host binary resolution, retry/backoff, and `pdfminer` fallback in `backend/app/workers/latex_worker.py`

### A-003 Medium — Frontend API client assumed `headers.get()` always existed
- Evidence:
  - `pnpm run test:unit` failed in `src/__tests__/p2-feature-69.test.ts`
  - Error: `Cannot read properties of undefined (reading 'get')`
- Root cause:
  - `frontend/src/lib/api-client.ts` assumed every successful `fetch()` response implemented `headers.get`
- Resolution:
  - Defensive response header parsing with fallback to header objects and headerless JSON parsing

### A-004 Medium — Full-stack smoke harness was unsafe for live local validation
- Evidence:
  - Script always attempted to start its own backend process
- Root cause:
  - `scripts/ci/full-stack-smoke.sh` had no backend health probe / reuse path
- Resolution:
  - Reuse existing healthy backend and only manage a backend process when the script starts it

### A-005 Medium — Browser smoke and template suites had flake-prone readiness logic
- Evidence:
  - `frontend/e2e/full-stack-smoke.spec.ts` failed with aborted `/try` navigation
  - `frontend/e2e/templates.spec.ts` failed on `networkidle` and brittle mocked-render assumptions
- Root cause:
  - Over-reliance on `networkidle` and overly optimistic route readiness assumptions for heavy dev routes
- Resolution:
  - Replaced `networkidle` dependency with explicit route/request/UI readiness checks and retryable navigation where appropriate

## Security / Ops Findings

### A-006 High — Root `.env` contains production-like secrets and remote DB target
- Evidence:
  - Root `.env` includes live-looking provider API keys and a Neon database URL
- Impact:
  - Secret exposure risk
  - Accidental writes against non-local infrastructure
- Resolution in this pass:
  - Validation was intentionally run against local Docker infra, not the remote DB URL
- Remaining action:
  - Rotate secrets and separate local/dev credentials from production-like values

### A-007 High — Backend pytest harness could inherit the development/remote database
- Evidence:
  - `backend/test/conftest.py` previously fell back from `TEST_DATABASE_URL` to `DATABASE_URL`
  - root `.env` contains a remote Neon `DATABASE_URL`
- Impact:
  - backend tests could run against non-test infrastructure when invoked outside `make test-backend`
  - session cleanup is best-effort and tables are not recreated by pytest, so accidental writes were a real risk
- Resolution in this pass:
  - pytest now prefers `TEST_DATABASE_URL`, accepts `DATABASE_URL` only when it already targets a test database, and otherwise defaults to local `latexy_test`
  - app settings are forced to use the resolved isolated test DB inside the test harness

## Validation Notes
- Live health: `/health` returned healthy
- Live metrics: `/metrics` returned Prometheus payload with request metrics
- Live billing surface: `/subscription/plans` returned consistent `billing_unconfigured` state
- Live compile success: terminal result persisted with non-null `extracted_text`
- Live compile failure: terminal result persisted instead of `404`
- Test harness isolation: with `TEST_DATABASE_URL` and `DATABASE_URL` unset, pytest resolved to local `latexy_test`
- Builder import flow: dedicated Playwright coverage passes on the mocked local page path

## Coverage Gaps Observed
- External provider end-to-end validation remains credential-gated
- No full soak/stress run was performed in this pass

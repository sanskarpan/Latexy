# Fixes

## A-001 / A-002
- Files changed:
  - [latex_worker.py](/Users/sanskar/dev/Latexy/backend/app/workers/latex_worker.py:1)
- Rationale:
  - Ensure terminal worker outcomes persist result payloads and successful compiles produce ATS-readable extracted text.
- Before:
  - Failed jobs could end in `404` on `/result`
  - Successful jobs could return `extracted_text: null`
- After:
  - Terminal failure/cancel/timeout/validation paths persist result payloads
  - Successful jobs use resilient host `pdftotext` plus `pdfminer` fallback extraction
- Validation:
  - unit tests in `backend/test/test_latex_worker.py`
  - live compile success/failure probes

## A-001 / A-002 Regression Coverage
- Files changed:
  - [test_latex_worker.py](/Users/sanskar/dev/Latexy/backend/test/test_latex_worker.py:1)
- Rationale:
  - Lock in failure-result persistence and extraction fallback behavior.
- Before:
  - Runtime bug existed without dedicated regression coverage.
- After:
  - Focused tests cover failed-result persistence, cancelled-result persistence, host extraction, and `pdfminer` fallback.
- Validation:
  - `cd backend && .venv/bin/pytest test/test_latex_worker.py -q`

## A-003
- Files changed:
  - [api-client.ts](/Users/sanskar/dev/Latexy/frontend/src/lib/api-client.ts:777)
- Rationale:
  - Make response parsing robust to mock/partial response shapes without regressing normal browser behavior.
- Before:
  - Missing `headers.get()` crashed the client.
- After:
  - Client tolerates `Headers`, plain objects, or absent headers and still parses JSON safely.
- Validation:
  - `cd frontend && pnpm run test:unit`

## A-004
- Files changed:
  - [full-stack-smoke.sh](/Users/sanskar/dev/Latexy/scripts/ci/full-stack-smoke.sh:1)
- Rationale:
  - Align smoke harness behavior with real local validation and CI startup semantics.
- Before:
  - Always spawned a backend process.
- After:
  - Reuses an existing healthy backend and only cleans up a backend it started itself.
- Validation:
  - `bash scripts/ci/full-stack-smoke.sh`

## A-005
- Files changed:
  - [full-stack-smoke.spec.ts](/Users/sanskar/dev/Latexy/frontend/e2e/full-stack-smoke.spec.ts:1)
  - [templates.spec.ts](/Users/sanskar/dev/Latexy/frontend/e2e/templates.spec.ts:1)
- Rationale:
  - Replace brittle browser readiness heuristics with route/request/UI-based readiness.
- Before:
  - Smoke and template tests could fail due to route compile churn or websocket-induced non-idle state.
- After:
  - Explicit URL, response, and control visibility checks drive readiness.
- Validation:
  - `bash scripts/ci/full-stack-smoke.sh`
  - `cd frontend && PLAYWRIGHT_PORT=5180 NEXT_PUBLIC_API_URL=http://localhost:8030 pnpm exec playwright test e2e/templates.spec.ts --project=chromium --workers=1`

## A-007
- Files changed:
  - [conftest.py](/Users/sanskar/dev/Latexy/backend/test/conftest.py:1)
  - [README.md](/Users/sanskar/dev/Latexy/README.md:171)
- Rationale:
  - Ensure backend tests only target an isolated test database and never inherit a development or remote `DATABASE_URL` by accident.
- Before:
  - pytest fell back from `TEST_DATABASE_URL` to `DATABASE_URL`
  - direct backend test runs could point at the remote/development DB from root `.env`
- After:
  - pytest prefers `TEST_DATABASE_URL`
  - `DATABASE_URL` is only reused when it already points at a test database
  - otherwise the harness defaults to local `latexy_test` and forces app settings to use that resolved test DB
- Validation:
  - `cd backend && env -u TEST_DATABASE_URL -u DATABASE_URL .venv/bin/python - <<'PY' ...`
  - `cd backend && RATE_LIMIT_ENABLED=false TEST_DATABASE_URL=postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy_test .venv/bin/pytest test/test_latex_worker.py -q`

## A-008
- Files changed:
  - [page.tsx](/Users/sanskar/dev/Latexy/frontend/src/app/workspace/new/page.tsx:1)
  - [builder-import.spec.ts](/Users/sanskar/dev/Latexy/frontend/e2e/builder-import.spec.ts:1)
- Rationale:
  - Make builder imports finishable from the UI and lock that path in with dedicated browser coverage.
- Before:
  - Builder mode could import content but never exposed `Create Resume`
- After:
  - Builder mode shows the same `Create Resume` action as other non-template creation flows
  - Dedicated Playwright coverage exercises builder import, platform selection, conversion, and create-button availability
- Validation:
  - `cd frontend && pnpm exec playwright test e2e/builder-import.spec.ts --project=chromium --workers=1`

## A-009
- Files changed:
  - [api-client.ts](/Users/sanskar/dev/Latexy/frontend/src/lib/api-client.ts:1)
  - [api-client-headers.test.ts](/Users/sanskar/dev/Latexy/frontend/src/__tests__/api-client-headers.test.ts:1)
  - [config.py](/Users/sanskar/dev/Latexy/backend/app/core/config.py:1)
- Rationale:
  - Remove unnecessary JSON content-type headers from simple read-only requests and align default backend CORS origins with the repo's slot-based local-dev ports.
- Before:
  - Shared API client sent `Content-Type: application/json` on simple GET requests
  - default backend CORS origins only covered `5180`
- After:
  - JSON content-type is only added when the request actually sends a JSON body
  - common no-body fetches omit the header
  - default backend CORS origins now include `5181` to `5183`
- Validation:
  - `cd frontend && pnpm exec vitest run src/__tests__/api-client-headers.test.ts`
  - `cd backend && .venv/bin/ruff check app/core/config.py test/conftest.py`

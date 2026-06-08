# Test Results

## Environment
- OS: macOS arm64
- Runtime path:
  - local Docker infra (`latexy-postgres`, `latexy-redis`, `latexy-minio`)
  - local backend/worker/beat/frontend via `./scripts/dev.sh app`

## Startup Validation
- `./scripts/dev.sh status`
  - Pass
- backend startup and migrations
  - Pass
- worker startup
  - Pass
- frontend startup
  - Pass

## API / Runtime Validation
- `GET /health`
  - Pass
- `GET /metrics`
  - Pass
- `GET /subscription/plans`
  - Pass
- malformed `/jobs/submit` request: missing `latex_content`
  - Pass, `400`
- malformed `/jobs/submit` request: unsupported `job_type`
  - Pass, `400`

## Async Job Validation
- valid LaTeX compile
  - Pass
  - terminal result returned
  - `extracted_text` returned
- invalid LaTeX compile
  - Pass
  - terminal failed result returned instead of `404`

## Automated Validation
- `cd backend && .venv/bin/ruff check app/workers/latex_worker.py test/test_latex_worker.py`
  - Pass
- `cd backend && .venv/bin/pytest test/test_latex_worker.py -q`
  - Pass
- `cd backend && env -u TEST_DATABASE_URL -u DATABASE_URL .venv/bin/python - <<'PY' ...`
  - Pass, resolved default backend test DB to local `latexy_test`
- `cd backend && RATE_LIMIT_ENABLED=false TEST_DATABASE_URL=postgresql+asyncpg://latexy:latexy_password@localhost:5434/latexy_test .venv/bin/pytest test/ -q`
  - Pass
- `cd frontend && pnpm run test:unit`
  - Pass (`410` tests)
- `cd frontend && pnpm exec vitest run src/__tests__/api-client-headers.test.ts src/__tests__/p2-feature-69.test.ts`
  - Pass (`21` tests)
- `cd frontend && pnpm lint --file src/lib/api-client.ts --file e2e/full-stack-smoke.spec.ts --file e2e/templates.spec.ts`
  - Pass
- `cd frontend && pnpm lint --file src/lib/api-client.ts --file src/__tests__/api-client-headers.test.ts --file src/app/workspace/new/page.tsx --file e2e/builder-import.spec.ts`
  - Pass
- `bash scripts/ci/full-stack-smoke.sh`
  - Pass
- `cd frontend && PLAYWRIGHT_PORT=5180 NEXT_PUBLIC_API_URL=http://localhost:8030 pnpm exec playwright test e2e/templates.spec.ts --project=chromium --workers=1`
  - Pass (`43` tests)
- `cd frontend && pnpm exec playwright test e2e/builder-import.spec.ts --project=chromium --workers=1`
  - Pass (`2` tests)

## Coverage Notes
- Validated browser surfaces:
  - top-level smoke route flow
  - template gallery and mocked template API flow
  - builder import wizard flow
- Validated backend surfaces:
  - health
  - metrics
  - billing plans
  - async compile success/failure
  - malformed job submission handling
  - safe backend test DB resolution
  - multi-slot default CORS config

## Remaining Gaps
- No live credentialed validation for OAuth, billing webhooks, external LLM vendor behavior, or email delivery
- No long soak test in this pass
- No distributed multi-instance concurrency benchmark in this pass

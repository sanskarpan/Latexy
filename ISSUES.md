# Issues

## A-001
- Severity: High
- Title: Terminal failed LaTeX jobs did not persist final result payloads
- Description:
  - Worker-side terminal failures updated state/events but not the Redis result key.
- Root cause:
  - `compile_latex_task()` returned early without calling `publish_job_result()` on non-success paths.
- Impact:
  - Clients polling `/jobs/{id}/result` received `404` after terminal failure.
- Affected components:
  - [latex_worker.py](/Users/sanskar/dev/Latexy/backend/app/workers/latex_worker.py:1)
  - job result API path
- Reproduction:
  1. Submit invalid LaTeX to `/jobs/submit`
  2. Wait for `/jobs/{id}/state` to become `failed`
  3. Request `/jobs/{id}/result`
- Validation evidence:
  - Fixed and revalidated live: failed jobs now return terminal error payloads

## A-002
- Severity: High
- Title: Successful PDF text extraction was unreliable
- Description:
  - Valid compile jobs could complete with `extracted_text: null`.
- Root cause:
  - Brittle `pdftotext` execution path coupled to Docker compile context and lacking fallback.
- Impact:
  - ATS preflight and text-dependent post-processing silently degraded.
- Affected components:
  - [latex_worker.py](/Users/sanskar/dev/Latexy/backend/app/workers/latex_worker.py:1)
- Reproduction:
  1. Submit valid LaTeX compile job
  2. Inspect `/jobs/{id}/result`
  3. Compare with host `pdftotext` output on generated PDF
- Validation evidence:
  - Fixed and revalidated live: successful job now returns populated `extracted_text`

## A-003
- Severity: Medium
- Title: Frontend API client crashed on partial/mock response headers
- Description:
  - `ApiClient.request()` threw when `res.headers.get` was absent.
- Root cause:
  - Unconditional assumption that `fetch()` response headers always implement the browser `Headers` interface.
- Impact:
  - Unit suite failures and brittle parsing around mocked or partial responses.
- Affected components:
  - [api-client.ts](/Users/sanskar/dev/Latexy/frontend/src/lib/api-client.ts:777)
- Reproduction:
  1. Run `cd frontend && pnpm run test:unit`
  2. Observe failures in `p2-feature-69.test.ts`
- Validation evidence:
  - Unit suite passes after defensive parsing fix

## A-004
- Severity: Medium
- Title: Full-stack smoke harness could conflict with a healthy local backend
- Description:
  - Smoke script always attempted to start a backend process.
- Root cause:
  - No backend reuse path in `scripts/ci/full-stack-smoke.sh`.
- Impact:
  - Port conflicts and false-negative smoke failures during local validation.
- Affected components:
  - [full-stack-smoke.sh](/Users/sanskar/dev/Latexy/scripts/ci/full-stack-smoke.sh:1)
- Reproduction:
  1. Start the backend locally
  2. Run `bash scripts/ci/full-stack-smoke.sh`
  3. Observe duplicate backend startup behavior
- Validation evidence:
  - Smoke script now reuses healthy backend and passes

## A-005
- Severity: Medium
- Title: Browser smoke and template suites used flaky readiness heuristics
- Description:
  - Playwright specs used `networkidle` and one-shot navigation assumptions on websocket-heavy or heavy dev routes.
- Root cause:
  - Test harness logic was not aligned with actual route boot behavior.
- Impact:
  - False-negative E2E failures.
- Affected components:
  - [full-stack-smoke.spec.ts](/Users/sanskar/dev/Latexy/frontend/e2e/full-stack-smoke.spec.ts:1)
  - [templates.spec.ts](/Users/sanskar/dev/Latexy/frontend/e2e/templates.spec.ts:1)
- Reproduction:
  1. Run smoke or template suite on a cold dev server
  2. Observe aborted `/try` navigation or stalled `networkidle` waits
- Validation evidence:
  - Both suites pass after replacing brittle waits with explicit readiness checks

## A-006
- Severity: High
- Title: Root `.env` contains production-like secrets and a remote database URL
- Description:
  - Local repo config includes live-looking API keys and a remote Neon target.
- Root cause:
  - Secrets and environment concerns are mixed into the root local config.
- Impact:
  - Secret leakage risk and accidental non-local data mutation risk.
- Affected components:
  - [.env](/Users/sanskar/dev/Latexy/.env:1)
- Reproduction:
  1. Read the root `.env`
  2. Observe provider keys and non-local `DATABASE_URL`
- Validation evidence:
  - Not code-fixed in this pass; documented as an operational blocker

## A-007
- Severity: High
- Title: Backend test harness could default to the development or remote database
- Description:
  - pytest resolved `TEST_DATABASE_URL` from `DATABASE_URL` when the test-specific variable was unset.
- Root cause:
  - [conftest.py](/Users/sanskar/dev/Latexy/backend/test/conftest.py:1) treated the general app database setting as a safe backend test fallback.
- Impact:
  - Running backend tests outside `make test-backend` could hit non-test infrastructure, including the remote Neon target from root `.env`.
- Affected components:
  - [conftest.py](/Users/sanskar/dev/Latexy/backend/test/conftest.py:1)
  - backend pytest invocation paths
- Reproduction:
  1. Leave `TEST_DATABASE_URL` unset
  2. Export or load a non-test `DATABASE_URL`
  3. Run backend pytest directly
- Validation evidence:
  - Fixed and revalidated: with both DB env vars unset, pytest now resolves to local `latexy_test`

## A-008
- Severity: Medium
- Title: Builder import flow had no visible resume-creation action
- Description:
  - Builder mode could import LaTeX content, but the page footer never rendered the `Create Resume` action for that mode.
- Root cause:
  - [page.tsx](/Users/sanskar/dev/Latexy/frontend/src/app/workspace/new/page.tsx:1) only showed the create footer for `import` and `linkedin`, even though the page logic already treated `builder` as a creatable flow.
- Impact:
  - Users could finish a builder import and still be unable to create the resume from the UI.
- Affected components:
  - [page.tsx](/Users/sanskar/dev/Latexy/frontend/src/app/workspace/new/page.tsx:1)
- Validation evidence:
  - Fixed and revalidated with dedicated Playwright coverage

## A-009
- Severity: Medium
- Title: API client sent `Content-Type: application/json` on simple GET requests
- Description:
  - Shared API client logic added JSON content-type headers even when no body was sent.
- Root cause:
  - [api-client.ts](/Users/sanskar/dev/Latexy/frontend/src/lib/api-client.ts:1) defaulted `Content-Type` inside the generic request path instead of only for JSON request bodies.
- Impact:
  - Unnecessary CORS preflights and noisier local cross-origin behavior for read-only requests like tenant context and template fetches.
- Affected components:
  - [api-client.ts](/Users/sanskar/dev/Latexy/frontend/src/lib/api-client.ts:1)
  - [api-client-headers.test.ts](/Users/sanskar/dev/Latexy/frontend/src/__tests__/api-client-headers.test.ts:1)
- Validation evidence:
  - Fixed and revalidated with unit coverage for GET vs POST header behavior

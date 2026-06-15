# TEST RESULTS — Latexy Production Audit
**Date:** 2026-06-11  
**Scope:** Backend pytest suite + frontend E2E (Playwright)

---

## Test Suite Overview

| Area | Files | Approx Tests | Notes |
|------|-------|-------------|-------|
| Backend (pytest) | ~25 files | 917+ | Asyncio mode=auto; Neon DB from DATABASE_URL |
| Frontend E2E (Playwright) | 1 file | ~10 | templates.spec.ts only |
| Frontend Unit | 0 files | 0 | No Jest/Vitest unit tests |

### Backend Test Collection Status
Running `python -m pytest --collect-only` fails with:
```
ImportError while loading conftest '/Users/sanskar/dev/Latexy/backend/test/conftest.py'.
test/conftest.py:100: in <module>
    from app.database.connection import get_db
ModuleNotFoundError: No module named 'app.database.connection'
```

**Root Cause:** `conftest.py` imports from `app.database.connection` which does not exist in the codebase. The module was likely renamed or removed in a prior refactor. This blocks ALL test collection in the default environment.

**Secondary failure:** `test_apply.py` triggers a DB schema mismatch (`column "default_tenant_id" of relation "users" does not exist`) — this test uses a live Neon database whose schema is out of sync with the current ORM models.

---

## What the Tests Cover Well

Based on test file inspection:

| Area | Coverage | Quality |
|------|----------|---------|
| LaTeX worker compilation paths | Good | Multiple scenarios, error cases |
| LLM worker streaming | Good | Token streaming, timeout, cancellation |
| Orchestrator combined flow | Good | Happy path, failure escalation |
| Event bus Pub/Sub | Good | Subscribe, replay, XREAD |
| WebSocket events | Moderate | Basic subscribe/deliver |
| ATS scoring | Good | Multiple job description types |
| Resume CRUD | Moderate | Happy path, some 404/403 |
| Health check | Minimal | Returns 200, nothing deeper |

---

## Coverage Gaps (Prioritized)

### [GAP-001] HIGH — No tests for payment webhook signature validation
**File:** `backend/app/services/payment_service.py:534`

`_verify_webhook_signature()` and `handle_webhook()` have zero test coverage. A forged webhook could silently upgrade subscriptions. There is no test for:
- Valid signature passes
- Tampered payload is rejected  
- Missing `RAZORPAY_WEBHOOK_SECRET` causes rejection
- `subscription.activated` / `charged` / `cancelled` dispatch

**Recommended test:**
```python
class TestWebhookSignature:
    def test_valid_signature_accepted(self): ...
    def test_tampered_body_rejected(self): ...
    def test_missing_secret_rejects(self): ...
    def test_subscription_activated_upgrades_plan(self): ...
    def test_replay_of_same_event_id_rejected(self): ...
```

---

### [GAP-002] HIGH — Auth middleware critical paths not unit-tested
**File:** `backend/app/middleware/auth_middleware.py`

`test_auth.py` tests optional/legacy-JWT auth but never exercises:
- `require_admin()` with a legitimate admin session
- `require_admin()` with a forged legacy JWT carrying `is_admin=true`
- Multi-tenant auth (`require_tenant_access`)
- Session expiry behavior

---

### [GAP-003] HIGH — Trial service race condition has no concurrent test
**File:** `backend/app/services/trial_service.py`

No test fires two concurrent `POST /jobs/submit` or `POST /public/compile` requests and verifies only one succeeds when one trial use remains. This is the exact race condition identified in TRIAL-01.

**Recommended test:**
```python
async def test_trial_concurrent_no_double_spend():
    results = await asyncio.gather(
        client.post("/public/compile", data={"latex": MINIMAL_TEX}),
        client.post("/public/compile", data={"latex": MINIMAL_TEX}),
    )
    success_count = sum(1 for r in results if r.status_code == 200)
    assert success_count <= 1  # only one should win if only 1 trial remains
```

---

### [GAP-004] HIGH — Job cancellation during execution not integration-tested
**File:** `backend/app/api/job_routes.py`, `backend/app/workers/orchestrator.py`

The cancel flow is tested at the worker layer (unit) but not at the API+worker integration level. There is no test that submits a job, issues `DELETE /jobs/{id}` while it's running, and verifies the job transitions to `cancelled` and worker stops processing.

---

### [GAP-005] HIGH — No tests for api-client.ts response header parsing
**File:** `frontend/src/lib/api-client.ts`

The recent fix (branch: `track/477-api-client-response`) hardened response header parsing. There are zero frontend unit tests for this code path. The fix cannot be regression-tested automatically.

**Recommended:** Create `frontend/src/__tests__/api-client-parse-body.test.ts` with mocked fetch responses.

---

### [GAP-006] MEDIUM — 317 test functions assert only status_code, no body content
**Scope:** Backend test suite

Many tests pattern-match `assert response.status_code == 200` without asserting any field of the response body. These tests can pass when the endpoint returns an empty `{}` or wrong data.

---

### [GAP-007] MEDIUM — `dependency_overrides[get_current_user_required]` leaked between tests
**File:** Multiple test files

5 test files set `app.dependency_overrides[get_current_user_required] = lambda: "user-id"` in test bodies without restoring the original after the test. This leaks auth bypass state across tests, making test order significant and masking real auth failures.

**Fix:** Wrap all `dependency_overrides` mutations in a fixture:
```python
@pytest.fixture
def authenticated(app):
    app.dependency_overrides[get_current_user_required] = lambda: TEST_USER_ID
    yield
    app.dependency_overrides.pop(get_current_user_required, None)
```

---

### [GAP-008] MEDIUM — No E2E coverage for core user flows
**File:** `frontend/e2e/`

`templates.spec.ts` covers template selection only. No E2E test covers:
- Login / signup
- Upload LaTeX → compile → preview PDF
- Job streaming (WebSocket events reflected in UI)
- Optimize flow
- Workspace resume management

---

### [GAP-009] MEDIUM — conftest.py has a broken import that blocks all local test runs
**File:** `backend/test/conftest.py:100`

`from app.database.connection import get_db` fails with `ModuleNotFoundError`. Until fixed, no one can run the test suite locally without a workaround. This means PRs may be merged without running any tests.

**Fix:** Update the import to match the actual module path, or add:
```python
import os
os.environ.setdefault('OTEL_SDK_DISABLED', 'true')
```
before the import if the issue is an OpenTelemetry initialization side-effect.

---

### [GAP-010] MEDIUM — Event replay on reconnect not tested end-to-end
**File:** `backend/test/test_ws.py`

The backend correctly implements XREAD replay but there is no test that:
1. Connects via WebSocket
2. Receives some events
3. Disconnects
4. Reconnects with `last_event_id`
5. Verifies missed events are replayed

---

### [GAP-011] MEDIUM — `templates.spec.ts` has fragile conditional clear-button assertion
**File:** `frontend/e2e/templates.spec.ts`

The diff (from git status) shows a conditional test for the clear button: it only asserts the button is visible if it exists. This masks cases where the clear button is missing entirely.

---

### [GAP-012] LOW — Auth bypass via `dependency_overrides` in 11 locations
**File:** Multiple test files

Tests using `lambda: 'hardcoded-id'` as the auth override bypass ALL auth logic. They can't detect auth middleware regressions (e.g., a bug that silently sets `user_id = None`).

---

### [GAP-013] LOW — No tests for infrastructure failure scenarios
No tests cover: DB connection refused, Redis connection refused, LaTeX Docker unavailable. The system's behavior under these conditions is untested.

---

## E2E Test Status

**File:** `frontend/e2e/templates.spec.ts`

The file has uncommitted changes (per git status). The test covers:
- Template gallery loading
- Template selection
- Template preview rendering

**Not covered:**
- Authentication flow
- LaTeX compilation
- WebSocket streaming in browser
- PDF preview rendering
- Workspace operations

---

## Recommended Test Additions (Priority Order)

1. `backend/test/test_webhook_security.py` — Razorpay signature validation (GAP-001)
2. `backend/test/test_auth_middleware.py` — require_admin, tenant auth (GAP-002)
3. `backend/test/test_trial_concurrency.py` — asyncio.gather race (GAP-003)
4. `backend/test/test_job_cancellation_integration.py` — API + worker cancel (GAP-004)
5. `frontend/src/__tests__/api-client.test.ts` — response parsing (GAP-005)
6. Fix conftest.py broken import (GAP-009) — unblocks ALL existing tests
7. Fix `dependency_overrides` leak in 5 test files (GAP-007)
8. `frontend/e2e/auth-and-compile.spec.ts` — core user flow (GAP-008)

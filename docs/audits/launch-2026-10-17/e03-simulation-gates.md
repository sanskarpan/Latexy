# E03 text interview simulation acceptance

Scope: the **E03** text simulation capability and its separation from sibling
E02 interview-prep generation. This is one capability acceptance, not a claim
that the 129-item launch inventory is complete.

Base commit: `25ecfe99defda3706c740159f3f43317ff3d1dc8`.

## Coverage added

- `backend/test/test_interview_simulation.py::TestInterviewSimulation::test_e03_live_controls_deny_recover_and_preserve_owned_prep` uses the real FastAPI route, isolated PostgreSQL test database, and synthetic authenticated users. It checks global E03 OFF denial before evaluator/quota calls, E03 ON recovery with deterministic provider stubs, E02 sibling OFF independence, role and plan denial/recovery, cross-owner 404, saved prep reads/deletes, and transient answer handling.
- `frontend/e2e/e03-interview-simulation-fullstack.spec.ts` uses the real browser, auth, API, and loopback `*_test` database without API route interception. It toggles E03 through the admin UI, checks the owner UI/API OFF and ON states, verifies the active answer survives live revocation and recovery, denies a second ordinary account against another owner's prep, confirms read/delete recovery, and exercises the no-key provider boundary. The test runner requires `PLAYWRIGHT_REQUIRE_BACKEND=1`, so it is not a mocked or silently skipped acceptance in the full-stack job.
- `scripts/ci/full-stack-smoke.sh` includes the E03 browser test in the existing isolated CI smoke run.

## Local execution limits

Docker CLI and Compose are installed, but Docker Desktop’s Linux engine is not
running (`docker version` cannot connect to its named pipe). No local Postgres
or Redis listeners are available. The worktree has no backend virtualenv or
frontend `node_modules`; the system Python has no `pytest`. The API/DB/browser
tests therefore require the repository’s existing isolated CI services.

CI result: pending publication and workflow execution.

## Remaining limits

The browser test intentionally has no model credential and expects the real
backend to stop at its provider-unavailable response after the E03 gate opens.
The backend route acceptance separately proves a successful evaluation with a
deterministic in-process provider stub. It does not measure live provider
quality or replace the remaining capability and operator acceptance work.

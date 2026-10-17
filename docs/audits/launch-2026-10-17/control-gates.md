# Launch Control Gate Evidence - 2026-10-17

## Scope

Reviewed the source snapshot `25ecfe99defda3706c740159f3f43317ff3d1dc8` on
`codex/latexy-control-gates`. The root launch checklist was read but not changed.
No root, backend, or frontend `AGENTS.md` and no `.agents/skills` directory are
present in this source snapshot.

Selected **F01 - Public share links**, a gateable child of the `collaboration`
parent. The launch matrix records policy/static evidence and leaves exact role,
plan, browser, API, and recovery acceptance open. This is a high-impact boundary:
F01 governs creation and serving of public resume links, while source ownership
and revocation must remain available to the owner.

## Acceptance added

- `backend/test/test_capability_shared_access_integration.py::test_share_child_denials_compose_across_role_plan_sku_and_parent_with_owner_recovery`
  uses real isolated PostgreSQL-backed API fixtures and two ordinary synthetic
  accounts. It checks account-role, `pro` family, `pro_annual` SKU, and parent
  denials; confirms the F01 child can remain explicitly enabled while its parent
  is off; checks public serving returns 404; preserves the owner's source read,
  review-disable, and share-revocation paths; then verifies re-enable.
- `frontend/e2e/sharing-controls-fullstack.spec.ts::real sharing child gates honor role, family, SKU and parent while ordinary owner recovery survives`
  is selected last by `scripts/ci/full-stack-smoke.sh` to avoid colliding with
  the production signup rate limit in later synthetic suites. It uses real Next
  auth, the Admin UI, FastAPI, PostgreSQL, and browser state without API route
  interception. It checks the same control axes, a refreshed open share modal,
  public-link denial, ordinary cross-owner denial, and in-product revoke recovery.

## Local execution

- Python 3.12.10 and Node 22.23.2 are present.
- Docker CLI is present, but the Docker Desktop Linux engine is unavailable
  (`docker info` cannot connect to its named pipe). No isolated local services
  were started.
- `python -m pytest --version` could not start because `pytest` is not installed.
  Frontend/root `node_modules` are absent; the local `pnpm --version` command did
  not return, so local browser execution was unavailable.
- Passed local checks: Python AST parse of the changed integration module,
  Node's TypeScript syntax check for the two Playwright specs, the targeted
  classifier assertion that E2E changes select Full-Stack Smoke, and
  `git diff --check`. The full local classifier suite cannot initialize its
  temporary Git repositories here because this Windows sandbox denies writing
  their `HEAD` symrefs; CI runs that suite successfully.
- Exact-head GitHub CI run `39029663154` at `ee17de2372ae994593bf2334a50d24b3d1f2c91a`:
  **Backend Tests passed** (including the new real-DB/API integration case),
  **Classify Changed Components passed** and selected Full-Stack Smoke, and
  **Full-Stack Smoke failed** with 3 other browser cases passing. The new F01
  browser case passed the role-off denial, then received 200 after the Admin UI
  disabled the `pro` family. Source inspection traced this to invalid test
  setup: the synthetic account had `subscription_plan='pro_annual'` but retained
  the auth default `subscription_status='inactive'`, so the correct billing
  resolver downgraded it to `free` before checking the family cell. The backend
  fixture had the same omission, so its plan assertions did not prove the paid
  family path either. That run did not reach browser SKU, parent, public-token,
  cross-owner, or recovery assertions. A later existing core browser case also
  got a real signup 429 because the F01 test had just created three synthetic
  accounts from the same loopback IP. Both synthetic plan fixtures now use an
  active test-only status, the backend fixture restores its prior status, and
  the browser case asserts the persisted `pro_annual` active state plus its
  effective F01 grant before changing controls. The browser case runs last to
  remove suite-order interference. Fresh CI is required before browser
  acceptance can pass.
- The Vercel preview check was rejected by its provider's daily deployment
  limit (`api-deployments-free-per-day`). No deployment or production action was
  run.

## Limits and remaining gaps

F01 evidence remains scoped to one ordinary user on `pro_annual`, its parent,
three control axes, private source ownership, and share recovery. It does not
close the rest of the 129-product inventory, other applicable roles/SKUs,
external-provider acceptance, deployment behavior, or launch gates. This task
does not change checklist status.

The matrix still labels B07's JSON export bypass as pending, while the inspected
source at this revision routes JSON exports through both H01 and B07 and includes
`test_json_export_composes_interchange_and_export_grants_before_data_access`.
That discrepancy was not executed or resolved here and should remain separately
reviewed; this evidence does not claim B07 acceptance.

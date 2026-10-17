# Launch Control Gate Evidence — 2026-10-17

## Scope

Reviewed the source snapshot `25ecfe99defda3706c740159f3f43317ff3d1dc8` on
`codex/latexy-control-gates`. The root launch checklist was read but not changed.
No root, backend, or frontend `AGENTS.md` and no `.agents/skills` directory are
present in this source snapshot.

Selected **F01 — Public share links**, a gateable child of the `collaboration`
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
- `frontend/e2e/capability-fullstack.spec.ts::real sharing child gates honor role, family, SKU and parent while ordinary owner recovery survives`
  is selected by `scripts/ci/full-stack-smoke.sh`. It uses real Next auth, the
  Admin UI, FastAPI, PostgreSQL, and browser state without API route interception.
  It checks the same control axes, a refreshed open share modal, public-link
  denial, ordinary cross-owner denial, and in-product revoke recovery.

## Local execution

- Python 3.12.10 and Node 22.23.2 are present.
- Docker CLI is present, but the Docker Desktop Linux engine is unavailable
  (`docker info` cannot connect to its named pipe). No isolated local services
  were started.
- `python -m pytest --version` could not start because `pytest` is not installed.
  Frontend/root `node_modules` are absent; the local `pnpm --version` command did
  not return, so local browser execution was unavailable.
- Passed local checks: Python AST parse of the changed integration module,
  `node --experimental-strip-types --check` of the changed Playwright spec, and
  `git diff --check`.
- Exact-head GitHub PR CI is pending. Update this section with the precise job,
  assertion, pass/fail/skip result after the run; do not count a skipped job as
  acceptance.

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

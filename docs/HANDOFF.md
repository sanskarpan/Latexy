# Latexy current handoff

Last reconciled: 2026-11-18. This is the canonical handoff; dated handoff files
are historical snapshots.

## Production topology

- Frontend: Next.js on Vercel at `https://latexy.xyz`.
- Backend: FastAPI and workers on Modal at
  `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`.
- Data services: Neon Postgres, dedicated Redis connections, and Cloudflare R2
  storage. Configuration values live in provider/repository secrets, never in
  this document.

Current serving identities at reconciliation:

- Frontend `/api/deployment-identity` returned `19d11cea…`.
- Backend `/health.commit_sha` returned `4b0729f331edfae92eba81aaec8d1e30897ea33c`
  (2026-11-03), **16 commits behind `main`**. The frontend is on `19d11cea…`;
  matching frontend/backend contracts are not established.
- A read-only re-probe at 2026-11-18 14:21 UTC found `/health` degraded with Redis
  unavailable, `/readyz` 503 and `/jobs/health` unhealthy. A follow-up at
  14:38 UTC returned healthy/ready with database, Redis and storage `ok`. The
  transient cause is unexplained, and `redis_capacity.status` remains
  `unconfigured`; re-check before any cutover and do not treat the recovery as a
  capacity pass.

Frontend delivery is automatic after a merge to `main`. Backend delivery is
intended to be automatic, but the current deployment workflow is not operative:

1. `.github/workflows/ci.yml` validates the exact main revision.
2. Vercel's GitHub integration builds and deploys that revision.
3. `.github/workflows/deploy-modal.yml` is intended to run after successful main
   CI, check out the CI-validated SHA, and perform the initial held cutover: the
   operator-pointer gate, migration, rolling Modal deploy, and health checks.

The last workflow-driven deploy that executed steps was a manual dispatch of
`f2f8d4a2` on 2026-11-02. The serving backend `4b0729f3` has no recorded
workflow run that executed deploy steps; its 2026-11-03 automatic run skipped
as already approved through `MODAL_TRAFFIC_RELEASE_APPROVED_SHA=4b0729f3`.
`deploy-modal.yml` is red on every new main push because the cutover approval
inputs are stale. Treat current release provenance as incomplete.

The Modal workflow also supports manual dispatch with an explicit ref and
`traffic_mode`. Automatic deployments remain held; releasing an already-held
candidate requires an explicit manual `traffic_mode=release`. A local `modal
deploy` is unsupported for production. Direct Modal source imports
default to held traffic, and an unheld production import requires the exact
workflow-approved SHA. Local `modal serve` remains available with an explicit
`MODAL_ENVIRONMENT=dev` and `MODAL_DEPLOYMENT_TRAFFIC_HOLD=false`.

The migration gate is a trusted operator-pointer gate, not verified external
drain evidence. It checks candidate-SHA equality, App ID format/equality, a
completion timestamp no more than 300 seconds old, a nonempty reference, and
read-only current Modal App identity/state. An arbitrary nonempty reference and
recent timestamp can pass those pointer checks when the named App is stopped.
The workflow does not fetch or authenticate the referenced material, establish
that the external procedure happened, or verify queued/in-flight work. A
separately authorized drain/recovery procedure and production change freeze
must be independently verified before setting the pointer variables and
allowing migration. The workflow never stops the App; Modal's stopped state
does not prove queued or in-flight work has settled. Automatic post-CI runs fail
closed when pointer fields are absent or stale, or the live App checks fail.
Use manual dispatch only after the external prerequisites are verified.
The release phase skips the old-App pointer/state gate and Alembic migration;
it requires the exact release-approved candidate to be currently deployed in
held mode with fresh health checks before redeploying that same candidate with
the hold disabled.

**Before any held cutover, clear repository variable
`MODAL_REDIS_HANDOVER_ID`.** Redis authority is already on the spare (phase
`spare`); with the variable set, the workflow attempts the freeze step, which
requires phase `legacy`, and fails after migration. Current schema, recovery and
release approvals still name `4b0729f3`; the drain variables still name the
2026-11-02 `f2f8d4a2` procedure. Use
[RELEASE-RUNBOOK-2026-11-18.md](RELEASE-RUNBOOK-2026-11-18.md); do not dispatch
from this summary.

## Development and verification

Use [local-dev.md](local-dev.md) for prerequisites and multi-worktree details.
The normal hybrid stack is:

```bash
./scripts/dev.sh infra
./scripts/dev.sh app
./scripts/dev.sh status
```

Slot 1 serves FastAPI on `http://localhost:8030` and Next.js on
`http://localhost:5180`; later slots increment both ports. Before claiming a
change complete, select checks proportional to its risk and include a live
browser flow for user-facing work. The full merge contract is:

1. Reproduce the defect and create a focused GitHub issue.
2. Branch from current `main`; keep one file per commit where practical.
3. Run the smallest relevant tests plus type/lint/build checks for affected
   packages, then the relevant local E2E flow.
4. Open a focused PR and wait for every required check. Duplicate push/PR runs
   may appear; both must be green when present.
5. Merge only after a clean mergeability check.
6. Verify the new exact main SHA in CI, the Vercel deployment, and the automatic
   Modal workflow.
7. Exercise the deployed behavior at `latexy.xyz` and recheck backend health.
8. Record exact-SHA evidence on the issue/epic; close only when all operational
   dependencies are actually satisfied.

Do not commit generated Playwright reports, incremental TypeScript build files,
local `.env` data, or unrelated dirty-worktree artifacts.

## Current remediation tracker and external blockers

GitHub issue [#1621](https://github.com/sanskarpan/Latexy/issues/1621) is the
active P0-P3 remediation epic. Query GitHub for live status instead of copying
issue totals into this file.

Known launch blockers at reconciliation time (details in
[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md#2026-11-18-reconciliation)):

- Backend drift: serving `4b0729f3` is 16 commits behind `main` `19d11cea`;
  frontend/backend contracts are not established.
- Release provenance: stale cutover approvals, stale 2026-11-02 drain variables,
  and the `MODAL_REDIS_HANDOVER_ID` trap. The deploy workflow is red on new main
  pushes; the current serving revision has no workflow run that executed deploy
  steps.
- Redis capacity/observability: `redis_capacity.status=unconfigured`; a
  transient 14:21 UTC re-probe found Redis unavailable and `/readyz` 503, then
  recovered by 14:38 UTC. The cause is unexplained and capacity is still not
  configured.
- Legal/public copy: live Terms contain `[Company Address]`, `latexy.com`, and
  trial/storage/limitation claims that do not match current behavior. Published
  `@latexy.com` addresses are undeliverable.
- Signup is open with no invite or beta gate. A free invite-only beta is a
  recommendation, not an approved launch.

Known operator/provider dependencies at reconciliation time:

- [#1628](https://github.com/sanskarpan/Latexy/issues/1628): Redis capacity
  monitoring is deployed, but provider-management credentials/database identity
  are still needed to configure the production capacity probe. The probe remains
  unconfigured.
- [#1668](https://github.com/sanskarpan/Latexy/issues/1668): the TUI trusted npm
  publishing workflow is implemented, but the npm package must be bound once to
  that GitHub Actions publisher. The registry still serves `1.0.3`; source is
  `1.0.4`.
- [#1670](https://github.com/sanskarpan/Latexy/issues/1670): headless optimize,
  ATS, status, and list commands are implemented and deployed in source, but
  user delivery is blocked by #1668.
- [#1683](https://github.com/sanskarpan/Latexy/issues/1683): closed by owner
  direction on 2026-10-31. The accounts were declared stale, rotation was
  explicitly waived, and no rotation was performed; old values remain in git
  history. This is a residual risk acceptance, not a security-verification pass.

Never put the missing provider credentials or replacement account passwords in
GitHub, tracked documentation, or chat transcripts. Confirm external changes by
capability/status only.

## Fast state checks

```bash
git fetch origin main
git status --short
git rev-parse HEAD origin/main
gh variable list --repo sanskarpan/Latexy
gh variable list --repo sanskarpan/Latexy --env Production
gh run list --workflow ci.yml --branch main --limit 5
gh run list --workflow deploy-modal.yml --branch main --limit 5
gh issue view 1621
gh pr list --state open
```

Production identities and health (PowerShell):

```powershell
$base = "https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run"
$health = Invoke-RestMethod "$base/health"
$health | Select-Object status, commit_sha, database, redis, redis_cache, storage, redis_capacity, redis_binding_fingerprint | Format-List
curl.exe -sS -o NUL -w "readyz=%{http_code}`n" "$base/readyz"
Invoke-RestMethod "$base/jobs/health"
Invoke-RestMethod "https://latexy.xyz/api/deployment-identity"
```

Compare `commit_sha` with `main`; the current serving backend is expected to be
behind. A 503 from `/readyz` is a hard stop, not a green light.

See [README.md](README.md) for the documentation map and the distinction between
current operating guidance and dated audit evidence.

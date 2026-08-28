# Latexy current handoff

Last reconciled: 2026-08-28. This is the canonical handoff; dated handoff files
are historical snapshots.

## Production topology

- Frontend: Next.js on Vercel at `https://latexy.xyz`.
- Backend: FastAPI and workers on Modal at
  `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`.
- Data services: Neon Postgres, dedicated Redis connections, and Cloudflare R2
  storage. Configuration values live in provider/repository secrets, never in
  this document.

Frontend and backend delivery are automatic after a merge to `main`:

1. `.github/workflows/ci.yml` validates the exact main revision.
2. Vercel's GitHub integration builds and deploys that revision.
3. `.github/workflows/deploy-modal.yml` runs only after successful main CI,
   checks out the CI-validated SHA, applies migrations, performs a rolling Modal
   deploy, and verifies `/health`, `/readyz`, and `/jobs/health`.

The Modal workflow also supports a manual `workflow_dispatch` with an explicit
ref for recovery. Routine releases must use the automatic post-CI path; a local
`modal deploy` is not the normal production procedure.

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

Known operator/provider dependencies at reconciliation time:

- [#1628](https://github.com/sanskarpan/Latexy/issues/1628): Redis capacity
  monitoring is deployed, but provider-management credentials/database identity
  are still needed to configure the production capacity probe.
- [#1668](https://github.com/sanskarpan/Latexy/issues/1668): the TUI trusted npm
  publishing workflow is implemented, but the npm package must be bound once to
  that GitHub Actions publisher. The registry still serves `1.0.3`; source is
  `1.0.4`.
- [#1670](https://github.com/sanskarpan/Latexy/issues/1670): headless optimize,
  ATS, status, and list commands are implemented and deployed in source, but
  user delivery is blocked by #1668.
- [#1683](https://github.com/sanskarpan/Latexy/issues/1683): public documentation
  was sanitized and guarded, but the formerly published production test
  accounts must be rotated or disabled by an identity operator.

Never put the missing provider credentials or replacement account passwords in
GitHub, tracked documentation, or chat transcripts. Confirm external changes by
capability/status only.

## Fast state checks

```bash
git status --short
git rev-parse HEAD
gh issue view 1621
gh run list --branch main --limit 10
gh pr list --state open
```

Production health:

```bash
base=https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run
curl --fail --silent --show-error "$base/health"
curl --fail --silent --show-error "$base/readyz"
curl --fail --silent --show-error "$base/jobs/health"
```

See [README.md](README.md) for the documentation map and the distinction between
current operating guidance and dated audit evidence.

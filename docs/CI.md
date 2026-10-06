# Continuous integration policy

The canonical `CI` workflow has three intentionally different entry points:

- pushes to `main`, where the classifier selects the relevant component
  contract (and fail-closed changes select every component);
- every `pull_request`, without a branch or path filter, so fork and stacked
  pull requests receive the required check contexts; and
- `workflow_dispatch` for an operator-requested full run (every scope).

There is no feature-branch push workflow and no duplicate push-only feature
check: manual dispatch uses this same workflow. The workflow always runs the
privacy guard. A dependency-free change classifier then selects component jobs:

| Scope | Jobs |
| --- | --- |
| `backend` | Backend Lint, Modal Deployment Parity, Backend Tests |
| `frontend` | Frontend Lint, Frontend Build, Cross-Browser Quality |
| `tui` | TUI Tests |
| `extension` | Browser Extension |
| `render_cv` | Reusable Render CV Action |
| `templates` | Template PDF Extraction Contract |
| `observability` | Observability Smoke |
| `full_stack` | Frontend Build and Full-Stack Smoke (with backend prerequisite rules below) |

Documentation-only changes therefore retain the visible privacy/classification
and required check contexts, while unrelated database, package, build, or
browser work is skipped. A skipped check is visible as skipped/successful to
branch protection; it does not mean that suite ran. The previously visible
33/34 entries were check runs, including duplicate CI jobs, not 33 workflows.
External Vercel, CodeQL, and GitGuardian checks are not controlled by this classifier.

Classification is fail-closed. Missing or ambiguous event ranges, unknown
paths, workflow or CI changes, and classifier errors select every component.
Renames select the union of their old and new paths; deletions select the
remaining path scope, while unresolved type/submodule metadata selects every
component. A selected job is never hidden after it starts;
its failure remains a failed required check. Full-stack smoke requires its
frontend build and, when the backend scope is selected, a successful backend
test; for a frontend/shared-lock-only full-stack change the backend test may be
explicitly skipped because the smoke job bootstraps its own backend. A skipped
component is intentional only when the classifier emitted an explicit `false`
for that scope.

Deployment workflows are separate from this policy and keep their own
provenance, freshness, and environment guards. This document describes CI
selection only; it does not authorize deployment or imply that a skipped
component was tested.

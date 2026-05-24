# Production Backlog — 2026-05-21

This file is no longer an audit transcript. It is the active post-audit backlog for production hardening, polish, and scale-readiness.

## In Progress

### TKT-005: Shared outbound HTTP clients for external integrations
Status: `planned_next`

Problem:
- Greenhouse and Lever integration services create fresh `httpx.AsyncClient` instances per request.
- This is acceptable at current scale, but not ideal for connection reuse, latency, or sustained throughput.

Target outcome:
- Shared lifespan-managed HTTP clients for outbound integrations.

Acceptance criteria:
- Shared client lifecycle is centralized.
- Apply integrations and similar outbound services reuse connection pools.
- Existing behavior and tests remain stable.

### TKT-006: Per-user rate limiting for expensive apply flows
Status: `planned_next`

Problem:
- One-click apply endpoints perform expensive external fetch-and-submit work.
- They currently lack explicit per-user throttling aligned with cost and abuse risk.

Target outcome:
- Introduce per-user rate limiting for apply submissions.

Acceptance criteria:
- Apply endpoints enforce bounded per-user limits.
- Error responses are explicit and retry-friendly.
- Limits are testable and configurable.

### TKT-007: Canva export semantic splitting polish
Status: `planned_next`

Problem:
- Combined bold/date lines in Canva export remain visually correct but semantically flattened.

Target outcome:
- Split company/title and date fragments into separate structured export elements where possible.

Acceptance criteria:
- Common `\\hfill`-style or equivalent date layouts export as separate semantic units.
- Existing export fidelity does not regress.

### TKT-009: Production observability pass
Status: `planned_next`

Problem:
- The product is test-verified, but production-grade observability is still thinner than ideal.

Target outcome:
- Improve request correlation, queue visibility, external integration failure visibility, and smoke/deploy diagnostics.

Acceptance criteria:
- Structured request or trace IDs across critical workflows.
- Clearer logging around compile/apply/collab failures.
- Documented alert surface for CI smoke and runtime health regressions.

### TKT-010: Deployment and ops runbooks
Status: `planned_next`

Problem:
- Code readiness is ahead of operations documentation.

Target outcome:
- Add practical runbooks for secret rotation, rollback, backups, restore checks, and environment validation.

Acceptance criteria:
- Operator docs exist in-repo.
- Secret setup and rotation paths are explicit.
- Rollback and restore procedures are documented.

### TKT-011: Tailwind 4 migration
Status: `planned_next`

Problem:
- Tailwind 4 is still a dedicated migration project, not a safe patch bump.

Target outcome:
- Plan and execute the migration in isolation.

Acceptance criteria:
- Migration is tracked as a deliberate UI/platform effort.
- Existing design system behavior is preserved or intentionally improved.

## Completed In This Pass

### TKT-001: Better Auth secret hardening
Status: `completed`

Problem:
- `BETTER_AUTH_SECRET` is required, but the current code path still tolerates weak or placeholder-style secrets too easily.
- The frontend auth bootstrap currently falls back to a permissive development string.
- This leaves room for accidental weak-secret deployments even though the broader codebase is otherwise production-aware.

Target outcome:
- Production-like environments reject obviously weak `BETTER_AUTH_SECRET` values.
- Frontend auth bootstrap fails fast in production when the secret is missing or clearly placeholder-grade.
- Development keeps a safe local fallback path without silently normalizing that behavior into production.

Acceptance criteria:
- Production/staging config rejects missing or weak Better Auth secrets.
- Frontend auth config does not use `"change-me-in-production"` in production.
- CI and local development continue to work with explicit test/dev secrets.

### TKT-002: Tenant branding cache invalidation
Status: `completed`

Problem:
- Tenant resolution is cached in Redis for 5 minutes.
- Tenant PATCH updates can leave stale branding in cache for slug/domain-based resolution.

Target outcome:
- Tenant updates immediately invalidate all relevant cache keys.

Acceptance criteria:
- Updating tenant branding clears the slug cache key.
- Updating custom domain clears both previous and current domain cache keys when applicable.
- Regression coverage exists for the invalidation path.

### TKT-003: BYOK system health timestamp correctness
Status: `completed`

Problem:
- `/byok/system/health` still returns a fake static timestamp.

Target outcome:
- The endpoint returns a real UTC timestamp generated at request time.

Acceptance criteria:
- Response timestamp is dynamically generated and ISO-8601 formatted.
- Route-level regression coverage exists.

### TKT-004: CI Node 24 readiness
Status: `completed`

Problem:
- GitHub Actions currently emits Node 20 deprecation warnings through JavaScript-based actions.
- This is not failing CI yet, but it is a near-term operational risk.

Target outcome:
- CI is explicitly opted into Node 24 execution for JavaScript actions where supported by GitHub.

Acceptance criteria:
- Workflow is updated so CI is no longer dependent on GitHub’s Node 20 fallback window.
- Change does not alter app runtime behavior.

### TKT-008: Analytics route cleanup and authorization clarity
Status: `completed`

Problem:
- Analytics routes contain stale TODO comments implying missing auth even though `require_admin` is already wired on the relevant endpoints.
- This creates confusion about actual security posture.

Target outcome:
- Remove stale TODOs and tighten route intent/docs where needed.

Acceptance criteria:
- Comments match reality.
- No route loses auth enforcement.

Verification:
- Targeted backend tests for config hardening, tenant caching, and BYOK health passed.
- Frontend lint passed for auth hardening changes.

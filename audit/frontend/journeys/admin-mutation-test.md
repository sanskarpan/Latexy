# Admin mutation in local test mode - 2026-11-28

**Verdict:** PASS. A synthetic feature flag was enabled and restored through the real admin API, with audit rows recorded.

## Setup

- Local backend (`ENVIRONMENT=test`, local Postgres `latexy_test` on 5435, local Redis on 6380).
- Synthetic admin user with a direct DB session token.
- Synthetic flag `audit_admin_mutation` (enabled=false), unrelated to product flags.

## Mutation

| Step | Result |
|---|---|
| `PATCH /admin/feature-flags/audit_admin_mutation` `{enabled:true, reason:...}` | **200**, flag enabled=true |
| `GET /admin/feature-flags` | **200**, flag enabled=true |
| `PATCH ... {enabled:false, reason:...}` | **200**, flag enabled=false |
| `GET /admin/feature-flags` | **200**, flag enabled=false |
| `admin_audit_log` | **2** `feature_flag.update` rows for the synthetic flag |

The enable/restore path works and is audited.

## Local-only caveat

`GET /config/feature-flags` returned **500** because the local `latexy_test` database is missing the `feature_cohort_flag_mappings` table (migration gap). The admin endpoints themselves worked. This is a local fixture issue, not a production defect; production `/config/feature-flags` is served normally.

## Cleanup

- Synthetic flag, session and admin user deleted.
- Two admin audit rows retained as the audit trail.
- Local backend stopped.
- No production flag, plan, user or config was changed.

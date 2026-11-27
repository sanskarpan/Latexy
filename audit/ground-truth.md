# Audit ground truth — 2026-11-27

Captured from live production and `origin/main` (`d2cbc51ab8c25106d073e0e0065b985fc6dc6490`).

## Production

| Item | Observed | Expected by prompt | Verdict |
|---|---|---|---|
| Frontend deployment identity | `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (`source: vercel`) | `ee1a405d...` | docs-only advance; runtime equal |
| Backend `/health` | 200 `healthy`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421` | `ee1a405d...` | matches |
| `/readyz` | 200 `ready` (database/redis/cache ok) | ready | matches |
| `/jobs/health` | 200 `healthy`, all queue depths 0 | healthy | matches |
| Database head | `0109_error_alerts` | `0109_error_alerts` | matches |
| Redis capacity | Upstash ok; 1,913,497 monthly requests (limit unset/large) | watch #1628 | available |
| Storage | ok | ok | matches |

### Live OpenAPI
- `GET /openapi.json`, `/api/openapi.json`, `/docs`, `/api/docs` all return **404**. The production schema endpoint is disabled.
- Source-generated schema at the same commit: **558 paths / 636 operations**.
- The prompt's 322 paths / 377 operations is stale. Finding recorded.

### Data safety gate
- Users: 833 total; sessions: 895.
- Non-test accounts: **7**. The two Gmail accounts (`kunalbhan33@gmail.com`, `sheiszer26@gmail.com`) are the owner's own accounts, confirmed 2026-11-27.
- Payments: 0. Active/trialing subscriptions: 0. There are **no external customers**.
- **Decision:** controlled global capability flips are permitted. The global grant matrix is snapshotted before each pass, every change is logged in `changes/production-changes.md`, and the intended launch configuration is restored and verified afterwards. Synthetic identities remain the primary evidence path.

### GitHub
- Open issues: 66 (prompt expected 67).
- Open PRs: 10, all Dependabot; no human feature PRs.

## Immediate findings

| ID | Severity | Finding |
|---|---|---|
| F-001 | P2 | Live OpenAPI/docs endpoints are disabled in production, so the canonical schema cannot be fetched live; the audit uses source at the deployed SHA. |
| F-002 | P3 | Production contains 7 non-test accounts; the two Gmail accounts are the owner's. No external customers exist, so controlled global passes are allowed with snapshot/restore. |
| F-003 | P3 | Prompt inventory counts (322/377, 67 issues, 0 PRs) do not match live state (558/636, 66 issues, 10 dependabot PRs). |

## Method constraints from this point

- All tests use `audit+<cohort>@example.test` identities and a recorded time window.
- Global config changes are replaced by cohort-scoped grants/flags; any unavoidable global change is serialized, logged in `changes/production-changes.md`, and restored with verification.
- No live charges; no destructive infrastructure changes.
- Test data is deleted or listed in `cleanup.md`.


## Post-audit state check - 2026-11-27T11:47Z

- Backend `/health` 200 `healthy`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421`.
- `/readyz` 200; `/jobs/health` 200 `healthy`, all six Celery queue depths 0.
- DB head `0109_error_alerts`; database `neondb`.
- `GET /admin/entitlements` SHA-256 `b2b63b363b6e785c8ca8a6a14b1f5ba2e1e7e21a5ece357363afcb2a59921aef` - identical to the pre-test snapshot; `d25` kill switch true and free matrix `d25` true.
- Audit identities still present for cleanup: 16 users, 2 tenants, 55 compilations, 9 optimizations, 26 usage rows. See `cleanup-before.json`.


## Cleanup state - 2026-11-27T12:06Z

- 0 `audit+%` users, 0 audit sessions, 0 audit subscriptions, 0 audit developer keys, 0 audit tenants, 0 audit compilations/optimizations/usage rows, 0 device trials. See `cleanup-after.json`.
- Backend `/health` 200 `healthy`, commit `ee1a405de6058e814c3a6f5ffba5fe3630576421`; `/readyz` 200; `/jobs/health` 200 `healthy`.
- DB head `0109_error_alerts` unchanged.
- Entitlement state was last verified at 11:47Z, hash `b2b63b36…`, identical to the pre-test snapshot. No global change was made after that check; the admin session used for the check was then deleted.
- Six GDPR request rows remain by legal-retention trigger; four have `user_id=NULL`, the disposable signup keeps its anonymized UUID. Listed in `cleanup-verification.md`.

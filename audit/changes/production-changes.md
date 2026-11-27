# Production changes - audit 2026-11-27

All times UTC. Suffix `20261127103328`; audit identities in `audit/plans/identity-matrix.json`.

## Identity provisioning 2026-11-27T10:33:28Z

- Method: direct production PostgreSQL insert (documented fallback).
- Scope: users/sessions/subscriptions/tenant/team seats/developer key/device trial with `audit+` prefix.
- Identity matrix: `audit/plans/identity-matrix.json`.
- Restore/cleanup: run `audit/scripts/cleanup_identities.py` for suffix `20261127103328`.
- Global configuration changed: none.

## Controlled entitlement mutation test (Phase 4)

Purpose: prove the global kill-switch and per-plan matrix actually change the live effective entitlement response, and that the pre-test state can be restored byte-for-byte. Performed with the `admin-superadmin` audit identity against production.

Snapshots (SHA-256 of `GET /admin/entitlements` response body):

- Before: `audit/changes/snapshots/entitlements-before.json`, `b2b63b363b6e785c8ca8a6a14b1f5ba2e1e7e21a5ece357363afcb2a59921aef`
- After first test (kill switch left false by mistake): `audit/changes/snapshots/entitlements-after.json`
- After exact restore: `audit/changes/snapshots/entitlements-after-restore.json`, `b2b63b363b6e785c8ca8a6a14b1f5ba2e1e7e21a5ece357363afcb2a59921aef` - **identical to before**
- After matrix restore: `audit/changes/snapshots/entitlements-after-matrix-restore.json`, **identical to before**

Sequence and observed effects:

| # | Change | Observed |
|---|---|---|
| 1 | `PATCH /admin/entitlements/kill-switch/d25 {"enabled": true}` | 200; no effective change (d25 was already true) |
| 2 | `PATCH /admin/entitlements/kill-switch/d25 {"enabled": false}` | 200; `free` and `pro` `/config/entitlements.features.d25` became `false`; `/byok/api-keys` still 200 |
| 3 | `PATCH /admin/entitlements/kill-switch/d25 {"enabled": false}` again while restoring | This was the mistake: true means enabled, not killed. d25 remained off. |
| 4 | `PATCH /admin/entitlements/kill-switch/d25 {"enabled": true}` | 200; d25 true again for free/pro; full state equal to before |
| 5 | `PATCH /admin/entitlements/matrix {"plan_family":"free","feature_key":"d25","enabled":false}` | 200; free `d25=false`, pro `d25=true`; `/byok/api-keys` still 200 for both |
| 6 | `PATCH /admin/entitlements/matrix {"plan_family":"free","feature_key":"d25","enabled":true}` | 200; free/pro `d25=true`; full state equal to before |

Restore verification: `GET /admin/entitlements` after step 6 is byte-identical to the pre-test snapshot (same SHA-256). Every admin mutation is in the immutable `admin_audit` rows with actor, reason and before/after.

Findings from this pass:

- The entitlement resolver and matrix are functional and plan-specific.
- `kill_switches[key] = true` means **enabled** in this implementation, despite the name. The admin request/response shape inverts the usual kill-switch convention and is easy to misread (audit operational hazard).
- BYOK key-management endpoints (`/byok/api-keys`) do not consult `d25`; they stayed 200 while free d25 was false. Only the resume-engine/GitHub BYOK admission paths check d25. Recorded as `CAP-02`.

## R2 CORS fix for public share PDFs (2026-11-27)

Purpose: fix #2344, where `/r/{token}` could not render the compiled PDF because the R2 presigned URL had no `Access-Control-Allow-Origin`.

- Before: `get_bucket_cors(Bucket=latexy)` -> `NoSuchCORSConfiguration`.
- Change: `put_bucket_cors` with one rule:
  - Origins: `https://latexy.xyz`, `https://www.latexy.xyz`, `http://localhost:3000`
  - Methods: `GET, HEAD`
  - Allowed headers: `Range, Content-Type, Authorization, Origin, Accept`
  - Exposed headers: `Content-Length, Content-Range, Accept-Ranges, ETag, Content-Type`
  - `MaxAgeSeconds`: 86400
- After: `get_bucket_cors` returns the rule; `curl` with `Origin: https://latexy.xyz` returns `Access-Control-Allow-Origin` and `Access-Control-Expose-Headers`; browser plain fetch 200 and Range fetch 206.
- Verification: synthetic compiled/accepted share link renders the PDF and accepts a page-1 public review comment (see `audit/frontend/journeys/share-review.md`).
- Restore: not restored - this is the intended production fix for #2344. It only adds cross-origin read access for the listed first-party origins; it does not broaden write access or expose other buckets.
- Test objects under `audit-cors-check/` were deleted immediately after verification.

## Cleanup

- No plan catalog, pricing, role grant or deployment was changed.
- Test identities and their artifacts are deleted by `audit/scripts/cleanup_identities.py` after evidence capture; see `audit/cleanup.md`.

# Admin control room

Status: Phase 1 implementation (billing/webhook control room, User 360, audit).

## Surfaces

| Tab | Endpoint | Purpose |
| --- | --- | --- |
| Revenue | `GET /admin/billing/summary` | MRR/ARR, plan mix, period revenue net of INR refunds, open refunds, unacknowledged webhook failures |
| Revenue | `GET /admin/billing/webhooks` | Durable Dodo webhook receipts with local-ledger link, acknowledgement, and reconcile state |
| Revenue | `POST /admin/billing/webhooks/{id}/acknowledge` | Record review of a known provider-side/dead-letter event; never changes provider state |
| Revenue | `POST /admin/billing/webhooks/{id}/reconcile` | Re-read the linked checkout from Dodo; fails honestly when no local intent exists |
| Revenue | `POST /admin/billing/refunds` | Create a refund request (full, or partial with a provider line-item ID) |
| Revenue | `POST /admin/billing/refunds/{id}/approve\|reject` | Second-admin decision; the requester cannot decide their own request |
| Revenue | `POST /admin/billing/refunds/{id}/execute` | Submit an approved/retryable refund to Dodo |
| Growth & Cost | `GET /admin/analytics/activation` | Signup → résumé → compile → export → AI optimize → paid funnel, with plan/provider segments |
| Growth & Cost | `GET /admin/analytics/retention` | Weekly D1/D7/D30 cohorts with a minimum cohort size |
| Growth & Cost | `GET /admin/analytics/ai-cost` | Estimated token cost, model/plan/user breakdowns, margin estimates, spend-cap and outlier alerts |
| Growth & Cost | `GET /admin/analytics/timeseries` | Event/compile/optimize/revenue series filtered by plan, auth provider, or feature |
| Customers | `GET /admin/users/{id}/360` | Masked account, activation, usage, billing, security, and integration summary |
| Customers | `POST /admin/users/{id}/pii/reveal` | Admin-only email/name reveal with a mandatory reason and audit record |
| Customers | `POST /admin/users/{id}/plan` · `POST /trial/reset` · `POST /quota/reset` · `POST /sessions/revoke` · `POST /passkeys/revoke` · `POST /api-keys/revoke` | Admin-only audited support actions |
| Audit | `GET /admin/audit` | Append-only operator audit trail |

## Security invariants

- `admin_audit_log` is append-only enforced by a PostgreSQL trigger. Application
  code has no update or delete path.
- Audit payloads are bounded and redacted. Secrets, credentials, document
  content, prompts, job descriptions, and direct identifiers must not be stored.
- Support can open only the Customers surface. Support sees masked email/name,
  no admin actions, and cannot reveal PII or perform mutations.
- Refunds use separation of duties: one admin requests, a different admin
  approves/rejects, and execution is never automatic.
- Billing webhook acknowledgement is independent of provider status. A failed
  event stays failed until the local outcome is genuinely reconciled.
- User 360 never selects resume/LaTeX/prompt/job-description content. It returns
  titles, counts, timestamps, statuses, and redacted event names only.
- No provider credential, card detail, or bank detail is returned to the browser.
- Growth segments and retention cohorts suppress rates below five users to
  avoid re-identifying a small group.
- AI cost is deliberately labeled estimated: only total tokens are stored, so
  the dashboard applies a blended input/output rate from the configured
  `RESUME_ENGINE_MODEL_PRICING` table and the `ADMIN_AI_COST_USD_INR_RATE`
  conversion. Unknown models use a visible fallback estimate, never a claim of
  zero cost.

## Migrations

`0077_admin_control_room` creates:

- `admin_audit_log` + append-only trigger/indexes
- `admin_refund_requests` + one-open-request partial unique index
- `billing_webhook_events` review/acknowledgement/reconcile columns and index

## Tests

- `backend/test/test_admin_control_room_api.py` covers audit immutability,
  billing summary, webhook acknowledgement/reconcile, dual-control refunds,
  masked User 360, PII reveal audit, quota/session/key actions, and plan changes.
- `backend/test/test_analytics_admin_fixes.py` pins the INR-only refund
  timeseries and substring-based telemetry redaction.
- `frontend/src/__tests__/admin-control-room.test.ts` pins the tab wiring,
  support-only navigation, refund controls, and PostHog privacy hardening.

## Rollout

1. Apply Alembic `0077_admin_control_room`.
2. Deploy backend with the migration in the held release path.
3. Deploy the frontend after the backend health check.
4. Verify `/health`, `/readyz`, `/admin/billing/summary`, and the Revenue tab.
5. The five known quarantined Dodo test dead letters may be acknowledged with a
   reason after review; acknowledgement does not grant access or move money.

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
| Customers | `POST /admin/users/{id}/features/grant\|revoke` | Row-locked, idempotent per-user feature override stored in `users.user_metadata`; confirmation and reason required |
| Customers | `POST /admin/users/{id}/trial/extend` · `POST /trial/eligibility` | Support trial extension or explicit eligibility, confirmation and reason required |
| Audit | `GET /admin/audit` | Append-only operator audit trail with cursor pagination |
| Overview | `GET /analytics/admin/overview` | Seven executive KPIs with equal-length prior-period comparison, absolute/percent deltas and daily sparklines; cached for 60 seconds in-process and in Redis |
| Overview | `GET /admin/operations/attention` | Failed webhooks/payments, past-due subscriptions, stuck jobs, and partial domain coverage with one-click filtered links |
| Overview | `GET /admin/operations/health` | Cached aggregate of dependency, storage, capacity, queue, billing and compile health with per-section status |
| Overview | `GET /admin/alerts` | Durable, deduplicated alerts with severity, owner, state, occurrence count and runbook |
| Overview | `PATCH /admin/alerts/{id}` | Acknowledge or snooze an alert with a mandatory reason; every action is audited |

## Security invariants

- `admin_audit_log` is append-only enforced by a PostgreSQL trigger. Application
  code has no update or delete path, and there is no mutation API for audit rows.
- `GET /admin/audit` uses a stable `(created_at, id)` descending keyset cursor.
  `limit` is bounded to 200; responses return `next_cursor`, `has_more`, the
  applied `filters`, and a filtered `total`. Actor, action, target type/id, and
  time-range filters apply to cursor pages exactly as they do to the first page.
- Audit payloads are bounded and redacted. Secrets, credentials, document
  content, prompts, job descriptions, and direct identifiers are dropped rather
  than stored, and before/after contain only fields whose values changed.
- Support can open only the Customers surface. Support sees masked email/name,
  no admin actions, and cannot reveal PII or perform mutations.
- Refunds use separation of duties: one admin requests, a different admin
  approves/rejects, and execution is never automatic.
- Billing webhook acknowledgement is independent of provider status. A failed
  event stays failed until the local outcome is genuinely reconciled.
- User 360 never selects resume/LaTeX/prompt/job-description content. It returns
  titles, counts, timestamps, statuses, and redacted event names only. Masked
  responses are cached for 60 seconds and invalidated by support mutations;
  revealed PII is overlaid live and is never cached.
- No provider credential, card detail, or bank detail is returned to the browser.
- Growth segments and retention cohorts suppress rates below five users to
  avoid re-identifying a small group.
- KPI comparisons use an equal-length previous window. A zero (or negative)
  baseline returns no percent delta instead of infinity, and the UI uses a
  neutral tone in that case. Snapshot KPIs compare against the count at the
  start of the period.
- Operations responses contain counts, ages, statuses and safe metric values
  only. Probe failures return fixed details; raw provider errors, connection
  strings, credentials, document content and customer identifiers are never
  returned.
- Attention rows are read-only. Nothing in the queue auto-retries, refunds,
  cancels or acknowledges a provider event. Custom-domain and certificate
  expiry inside 30 days is actionable; null metadata is reported as `unknown`
  or `partial`, never as healthy or far-future. Every row links to its filtered
  Revenue, Job queue or Customers view.
- Per-user feature overrides live in `users.user_metadata.entitlement_overrides`
  and are consumed by `entitlement_service`. A grant supplements the plan/SKU
  matrix for one capability; a revoke denies it. Neither bypasses a global kill
  switch or account-role refusal. Writes take a row lock, are idempotent, and
  invalidate the User 360 and compatibility entitlement caches.
- Alerts deduplicate on a stable key while active, update an occurrence count
  and auto-resolve when the condition clears. A resolved incident may create a
  new row if it returns later. Acknowledgement and snooze require a reason and
  write an append-only audit record.
- Alert payloads contain counts, ages, thresholds and safe metric values only.
  Per-user spend outliers stay in the Growth tab and are never copied into the
  alert strip.
- AI cost is deliberately labeled estimated: legacy optimization rows store
  only total tokens, so the dashboard applies a blended input/output rate from
  the configured `RESUME_ENGINE_MODEL_PRICING` table and the
  `ADMIN_AI_COST_USD_INR_RATE` conversion. Resume-engine stage rows prefer the
  provider-recorded `cost_usd`. Costs are reported in USD cents and revenue /
  margin in INR paise. Unknown models use a visible fallback estimate and are
  listed explicitly, never a claim of zero cost. Each response carries the
  versioned pricing table (no provider keys) and a sampled-invoice
  reconciliation contract.
- Soft caps warn and hard caps pause *new* AI job admissions for the affected
  user; already-admitted work is never interrupted, accounts are never
  auto-suspended, and each decision is logged with actor and reason. Rolling
  anomalies use a median+MAD baseline with a minimum sample window before
  alerting. Alert payloads contain aggregate counts only; per-user details stay
  in the Growth tab.

## Migrations

`0077_admin_control_room` creates:

- `admin_audit_log` + append-only trigger/indexes
- `admin_refund_requests` + one-open-request partial unique index
- `billing_webhook_events` review/acknowledgement/reconcile columns and index

`0078_admin_alerts` creates:

- `admin_alerts` with one active row per `dedupe_key` (partial unique index)
- severity/state/history indexes and a fixed severity/state check constraint

`0079_tenant_domain_expiry` adds nullable `tenants.domain_expires_at` and
`tenants.domain_certificate_expires_at` timestamps. Null means unknown, so the
attention view reports partial coverage rather than assuming a far-future date.

The evaluator runs from the existing five-minute Modal maintenance fan-out; it
upserts signals, reopens expired snoozes and auto-resolves cleared conditions.
It never pages or mutates a payment, job or provider object.

## Database role hardening

Migration `0077_admin_control_room` installs the append-only trigger, but table
privileges are environment-specific. Run the role-neutral script after
migrations as the table owner (never as the application role):

```bash
psql "$DATABASE_URL" -v app_role=latexy_app \
  -f backend/scripts/harden_admin_audit_role.sql
```

The script is idempotent, refuses an application role that owns the table, and
fails if the append-only trigger is missing or disabled. It revokes all
privileges on `admin_audit_log`, then grants only `SELECT` and `INSERT`, so the
application role cannot `UPDATE` or `DELETE` audit rows even if a future code
path tries to. `backend/test/test_admin_audit_hardening.py` executes the same
script against a throwaway role and asserts the resulting grants.

Retention is an explicit, reviewed operator action by a role that does not
serve normal traffic; there is no application delete path or scheduled purge.

## Tests

- `backend/test/test_admin_control_room_api.py` covers audit immutability,
  billing summary, webhook acknowledgement/reconcile, dual-control refunds,
  masked User 360, PII reveal audit, quota/session/key actions, and plan changes.
- `backend/test/test_admin_audit_hardening.py` covers cursor stability under
  identical timestamps, filter echo, page-size bounds, changed-only redaction,
  the absence of audit mutation routes, and the database-role grant script.
- `backend/test/test_analytics_admin_fixes.py` pins the INR-only refund
  timeseries and substring-based telemetry redaction.
- `backend/test/test_admin_operations_api.py` covers admin-only access, the
  attention aggregate, partial-source visibility, health-cache behavior and
  fixed failure details.
- `backend/test/test_admin_kpi_trends.py` covers current/previous/absolute/
  percent deltas (including the clamped conversion rate over the prior UTC
  window), sparkline completeness and bounds, zero-baseline handling, finite
  JSON output and the 60-second overview cache (in-process, Redis hit/miss and
  Redis outage fallback).
- `backend/test/test_admin_alerts_api.py` covers evaluator deduplication,
  occurrence counts, auto-resolution, admin-only acknowledgement/snooze and
  audit coverage.
- `frontend/src/__tests__/admin-control-room.test.ts` pins the tab wiring,
  support-only navigation, refund controls, operations-panel loading and
  PostHog privacy hardening.

## Rollout

1. Apply Alembic `0077_admin_control_room`.
2. Deploy backend with the migration in the held release path.
3. Deploy the frontend after the backend health check.
4. Verify `/health`, `/readyz`, `/admin/billing/summary`, and the Revenue tab.
5. The five known quarantined Dodo test dead letters may be acknowledged with a
   reason after review; acknowledgement does not grant access or move money.

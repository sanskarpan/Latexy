# Cohort report — `admin-superadmin`

Status: read-only admin surface verified; analytics reconciled against the production database.
Owner: admin-superadmin test sub-agent.
Audit branch: `audit/production-2026-11-27`.
Date: 2026-11-27 (UTC).

Companion evidence: [`analytics/reconciliation.md`](../analytics/reconciliation.md),
[`identity-matrix.json`](identity-matrix.json), [`cohort-baselines.json`](cohort-baselines.json),
[`ground-truth.md`](../ground-truth.md), [`defects.md`](../defects.md).

---

## 1. Identity and baseline

| Item | Value |
|---|---|
| Matrix cohort | `admin-superadmin` |
| Production role | `admin` (highest RBAC role; there is no separate `superadmin` value) |
| Email | `audit+admin-superadmin-20261127103328@example.test` |
| User ID | `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` |
| Session | Provisioned `session` row for this user (token held in `identity-matrix.json`, not reproduced here) |
| Plan | `free` (admin does **not** bypass product entitlements) |
| Created | `2026-11-27T10:33:38.218893Z` |
| Email verified | yes |
| Quota at start | compilations 0/10 per day; optimizations 0/3 per month; AI assists 0/25 per month |
| Quota at end of test | compilations **2/10** (two compiles, see §6); other dimensions unchanged |

The `/admin` UI accepts `support` and `admin`; `support` sees only the Customers tab, `admin` sees all
22 tabs (`frontend/src/app/admin/page.tsx:83-110`). The audit label "superadmin" maps to the single
production `admin` role; there is no finer tier to test.

**Baseline entitlement snapshot** (from `/config/entitlements`, not the pricing page): the global
kill-switch matrix returned 149 switches, all `true`, and every one of the 165 registry entries was
enabled for this identity — consistent with the all-enabled pass that another audit cohort was
running during this window. This is an observation of shared production state, not a change made by
this sub-agent.

---

## 2. Access and role boundaries

| Probe | Identity | Status | Latency | Result |
|---|---|---:|---:|---|
| `/admin/analytics/daily-metrics?days=7` | admin | 200 | 1,268.0 ms | payload returned |
| `/admin/analytics/activity?limit=10&cursor=…` | admin | 200 | 1,209.1 ms | incremental page; `has_more=true` |
| `/admin/analytics/daily-metrics?days=7` | support | **403** | 1,184.4 ms | `Admin privileges required` (request `db898289-36f9-4041-975b-634094fca853`) |
| `/admin/analytics/retention?weeks=4` | support | **403** | 1,129.4 ms | `Admin privileges required` (request `1b1854d2-8248-4454-b429-132acaca12e0`) |
| `/admin/analytics/daily-metrics?days=7` | anonymous | **401** | 945.7 ms | `Authentication required` (request `7cc99638-1e2a-4f5d-a594-99d54b2e645c`) |

**Verdict: PASS.** Analytics is admin-only. The support role is deliberately scoped to Customers in
the UI and is rejected by `require_admin_actor` (which accepts `role == "admin"` or an allowlisted
admin email, `backend/app/middleware/auth_middleware.py:331-350`). This matches least privilege and
the roadmap's "support and admin are not equivalent" rule. If the intended support role should read
analytics, that is a product decision, not an enforcement bug.

---

## 3. Admin analytics surface

All **35/35** `GET /admin/analytics/*` operations responded 200 with the admin token, including both
path-parameter share/portfolio endpoints. No 401/403/5xx and no rate limiting.

The primary Analytics tab endpoint, `GET /analytics/admin/overview?days=30`, returned 200 in
**4,101.3 ms / 23,497 bytes** (request `e5366aa9-3e1f-4ee9-a202-822994deac58`). Its user/compile/
subscription counts reconciled to the DB, but its `real_time_metrics.today` block was all zeros while
the DB already had 21 compilations, 8 optimizations and 17 registrations for the day.

Latency of the 33 non-path probes at 10:45Z:

| Statistic | Value |
|---|---:|
| min | 1,154.6 ms |
| p50 | 1,216.9 ms |
| p95 | 1,648.0 ms |
| p99 / max | 2,493.3 ms |
| DB execution time for the daily-metrics CTE | 0.382 ms |

The ~1.2 s floor is request/transport overhead, not database work (849 users, 242 compilations at the
probe). The fastest result is still >1.1 s, so the roadmap target "dashboards p95 < 1.5 s" is only
met for the median, not the tail.

**Largest / slowest analytics responses**

| Endpoint | Bytes | Latency |
|---|---:|---:|
| `/admin/analytics/feature-adoption?days=30` | 574,422 | 2,493.3 ms |
| `/admin/analytics/flag-exposure` | 54,068 | 1,648.0 ms |
| `/admin/analytics/timeseries?days=30&metric=events` | 1,361 | 1,584.7 ms |
| `/admin/analytics/collaboration?days=30` | 3,209 | 1,373.6 ms |
| `/admin/analytics/activation?days=30` | 9,107 | 1,328.8 ms |

Adjacent admin dashboards were also reachable: checkout funnel 1,157.1 ms / 2,888 B, dunning recovery
1,240.2 ms, referrals 1,227.4 ms, coupon/student 1,307.2 ms, subscription analytics 1,252.1 ms.

**Outlier:** `/admin/plan-catalog` returned 92,435 bytes in **23,051.5 ms** (request
`949adbae-b7b5-492e-8c5d-ca7f18491f16`). This is a single warm sample; it needs a second measurement
before being called a persistent regression, but it is far outside the 1.5 s dashboard target.

---

## 4. Reconciliation results (summary)

Full endpoint-by-endpoint numbers and SQL are in
[`analytics/reconciliation.md`](../analytics/reconciliation.md). The admin cohort's bottom line:

**Counts reconcile in all 35 endpoints** (two are returned as null/zero by `<5` suppression:
`feature-depth`, `editor-modes`): daily metrics, activation cohort counts, compile latency, compile errors,
consent, feature adoption, feature depth suppression, timeseries (182 events), trial health (1/3/27),
device-trial windows, career adoption, collaboration suppression, team-seat suppression, share/
portfolio period counts, onboarding, ATS, AI cost/usage/latency, credential mix, optimization
acceptance, flags, integrations, errors.

The `analytics/admin/overview` counts also reconcile (users 850, new 18, compilations 22/completed 17,
trials 3, revenue 0), but its real-time strip and three KPI definitions do not (AN-18/AN-19).

**Material disagreements (admin-facing):**

| Finding | Dashboard says | Source says | Severity |
|---|---|---|---|
| Paid conversions | landing 10, trial-attribution 10, checkout funnel 10 paid | `payments` = 0; 12 synthetic subscriptions (9 active, 1 trialing, 1 past-due, 1 cancelled) | P1 (AN-02) |
| Revenue / subscription state | `/admin/subscriptions/analytics`: 0 active, 0 MRR, 0 upgrades; `paths`: 0 outcomes | 12 subscription rows; `subscription_history` = 0 | P1 (AN-03) |
| Direct compile visibility | compile latency/errors/complexity ignore direct compiles | `POST /compile` charged quota 0→1 but wrote 0 `compilations` rows and 0 events | P1 (AN-01) |
| Compile events | `timeseries` events / feature adoption see no compile activity | 17 compilations today, 0 `compile` events | P2 (AN-04) |
| Daily rollup | `source=base_tables`, freshness `no_rollup` | `admin_daily_metrics` = 0 rows, `last_refreshed_at` null | P2 (AN-05) |
| Optimizations | daily 1 (at probe), activation counts it | AI usage excludes auto-save; the only row is `is_auto_save=true`/`is_checkpoint=true` | P2 (AN-06) |
| Test traffic | all dashboards include `audit+*`; no exclusion filter | 16/17 users, 12/12 subs, 10/10 paid are synthetic | P2 (AN-08) |
| Traffic / sessions | traffic-sources 0 sessions, privacy 80 "sessions" | 150 page views, 0 `visitor_id`, 80 device fingerprints | P2 (AN-09) |
| Compile dimensions | by-template empty; missing dimensions 3 | `template_id` NULL on 16/16 compilations today | P2 (AN-10) |
| Plan health | weekly/lifetime 0 | 0 weekly/lifetime, but 12 basic/pro/byok/student/team subs are out of scope | P3 (AN-13) |
| Real-time KPI strip | `system.real_time_metrics.today` = 0/0/0/0 | 21 compilations, 8 optimizations, 17 registrations today | P2 (AN-18) |
| KPI labels | "Conversion" 100%, "active subscriptions" 10, "optimizations" 9 | conversion is new_users/trials clamped; active includes past_due; optimizations includes auto-saves | P2 (AN-19) |
| Suppression | primary fields hide <5 | reconciliation publishes 1 tenant/2 members, 2 seats, 1 row, 1 active user | P3 (AN-11) |

---

## 5. Admin read-only journeys

| Journey | Steps | Expected | Observed | Status |
|---|---|---|---|---|
| Analytics tab load | open `/admin`, Analytics | all admin-only endpoints return data | overview 200 (4.1 s); 35/35 analytics endpoints 200; 1.2 s median | PASS, one slow payload |
| Real-time strip | overview `real_time_metrics` | today/hour activity | all zeros against 21 compiles/8 optimizations/17 registrations in DB | FAIL (AN-18) |
| Activity feed | initial page + cursor | newest events, incremental cursor | 50 items, `mode=live`; cursor page returned newer events; `has_more` false on initial page | PASS with P3 note (AN-15) |
| Auth boundary | support token on analytics | 403 | 403 with request ID | PASS |
| Anonymous boundary | no token | 401 | 401 | PASS |
| User lookup | `/admin/users?limit=5` | paginated list | 200, total 850, 1,301 B | PASS |
| Audit log | `/admin/audit?limit=5` | redacted immutable list | 200, total 219, 4,356 B | PASS |
| Alerts | `/admin/alerts?limit=5` | 200 | 18 alerts | PASS |
| Feature flags | `/admin/feature-flags` | 200 | 155 flags, 155 enabled | PASS (shared all-enabled state) |
| Entitlements matrix | `/admin/entitlements` | 200 | 165 registry / 149 kill switches / 11 plan keys, 85 KB | PASS |
| Operations health | `/admin/operations/health` | aggregate health | **degraded** (billing: 5 failed webhooks, 1 past-due; infra healthy) | PASS signal, needs owner action |
| Plan catalog | `/admin/plan-catalog` | 200 | 200, 11 plans, **23 s** | SLOW (AN-16) |
| Subscriptions analytics | `/admin/subscriptions/analytics` | MRR/plan mix | 200 but 0 active / 0 MRR vs 12 rows | FAIL (AN-03) |

**Not exercised (and why)**

- Any mutation: global flags, entitlements, plan grants, feature flags, user role changes, quota
  resets, refunds, approval execution, view-as. The sub-agent rules prohibit global config changes
  and this scope is read-only; another cohort owns the mutation passes.
- GDPR deletion/export, billing replay/acknowledge, incident create/resolve, abuse decisions.
- PostHog saved insights/replays: the production build serves no PostHog project key (see
  `reconciliation.md` §4.8).
- `POST /admin/analytics/errors/evaluate` (mutating alert evaluation) and CSV exports.

---

## 6. Fresh actions and artifacts

Performed with the admin-superadmin token to test whether a fresh action moves the metrics (all
within the free plan; no payment, no upgrade):

| Action | Result | Artifact |
|---|---|---|
| `POST /resumes/` | 201, 1,081.5 ms | resume `7af40e7a-c2a3-4ac2-b123-a01addab429b` |
| `POST /compile` | 200, 1,470.2 ms, job `388d4ad5-904a-44dc-87a0-8eefe0780ffd` | quota 0→1; no `compilations` row; no event |
| `POST /jobs/submit` (`latex_compilation`) | 200, 3,967.1 ms; queued 11:02:43–11:03:03Z, processing 11:03:03–11:03:18Z | job `f7732594-056a-44e9-a7a1-a2caa6d3c4b5`; compilation `b22f39c5-1607-4aab-b84e-d228e6526094`; quota 1→2 |

Stage observation for the async job: request 3.97 s → queue wait ≈29 s → worker execution 7.93 s →
completed at ≈37 s. Queue wait dominates; this is consistent with the performance cohort's remit and
is recorded here only as context for "fresh action moves the metric".

**Cleanup:** resume and compilation are left in place for evidence. Owner: cleanup auditor. No global
state was changed; no user, tenant, flag, entitlement or plan was created or deleted by this
sub-agent. The admin quota will reset at `2026-11-28T00:00:00Z` (daily compilations).

---

## 7. Admin-specific findings and risks

| ID | Sev | Finding | Evidence | Owner / action |
|---|---|---|---|---|
| AD-01 | P1 | Revenue/paid dashboards count comped subscriptions as paid while `payments` is empty. | 10 paid vs 0 payments; all 12 subs synthetic; `billing_mode=live` | Billing + analytics owner: settle on payments or an explicit comp flag (AN-02) |
| AD-02 | P1 | Subscription analytics and paths report 0 active/0 MRR/0 upgrades because `subscription_history` is empty. | request `9b9e4afe-cc61-4627-8b85-fc62486ee582`; 12 subs | Billing owner: backfill/write history; pick one source of truth (AN-03) |
| AD-03 | P1 | Direct compile charges quota but is invisible to compile analytics. | quota 0→1; 0 rows | Backend owner (AN-01) |
| AD-04 | P2 | Analytics cannot exclude test/internal traffic; current numbers are 94–100% synthetic. | 16/17 users, 12/12 subs | Analytics owner: add cohort/internal flag and purge before launch (AN-08) |
| AD-05 | P2 | Operations health is `degraded`: 5 failed billing webhooks and 1 past-due subscription. | ops payload at 11:13Z; DB 5/5 failed `billing_webhook_events` | Billing/reliability owner; not caused by this test |
| AD-06 | P2 | Error alert delivery is not configured. | `delivery.configured=false`, channels `[]` | Operations owner (AN-17) |
| AD-07 | P2 | `/admin/plan-catalog` took 23.05 s (single sample, 92 KB). | request `949adbae…` | Performance owner (AN-16) |
| AD-08 | P2 | The daily-metrics rollup is never populated; every request recomputes base tables. | `admin_daily_metrics` 0 rows; freshness `no_rollup`; worker reports no queue ownership; matches CRON-01 (`refresh-daily-metrics` has no Modal schedule) | Reliability/analytics owner (AN-05) |
| AD-09 | P2 | `billing_mode` is `live` in the checkout-funnel payload. | `/admin/billing/checkout-funnel` at 11:11Z | Owner: confirm intended production mode; no live charge was made by this audit |
| AD-10 | P3 | The cohort label `admin-superadmin` does not correspond to a distinct production role; only `user`/`support`/`admin` exist. | role matrix; `/admin` tab lists | Documentation/audit lead |
| AD-11 | P3 | The admin analytics surface is broad but not cross-linked to the legacy `AdminAnalytics` overview: the tab uses `/analytics/admin/overview` while the individual dashboard components use the 35 `/admin/analytics/*` endpoints. Both were reachable. | `frontend/src/app/admin/page.tsx`, `api-client.ts` | Frontend owner: confirm the intended IA |
| AD-12 | P2 | The primary Analytics tab's "today"/"this hour" counters are all zero while the database has same-day activity. | request `e5366aa9…`; 21 compiles / 8 optimizations / 17 registrations vs 0 | Backend owner (AN-18) |
| AD-13 | P2 | Overview KPI labels are misleading: "Conversion" is new-users/trials clamped to 100%, "active subscriptions" includes past_due, "optimizations" includes auto-saves. | system block; `analytics_service.py:533-583` | Analytics owner (AN-19) |

---

## 8. Disposition

**Admin cohort: PASS for read-only analytics access and role separation, FAIL for revenue/paid
semantics and compile instrumentation.** The 35 endpoints are live, admin-only, DB-backed and
reconcilable; the wrong numbers come from source definitions (status-based "paid", empty
`subscription_history`, missing compile rows/events, auto-save counted as optimization) and from the
absence of a test-traffic exclusion, not from broken routes.

Recommended next steps for the lead:

1. Resolve the payments-vs-status definition (AN-02/AN-03) before any launch decision uses the
   revenue or conversion dashboards.
2. Fix the direct-compile write path and the compile event emission (AN-01/AN-04), then re-run the
   fresh-action test.
3. Populate or decommission the daily rollup (AN-05) and add a stale-rollup alert.
4. Add an `exclude_test` filter and record the audit window so launch metrics can be computed cleanly
   (AN-08).
5. Re-measure `/admin/plan-catalog` warm and profile the 574 KB feature-adoption payload
   (AN-16).
6. Fix or remove the all-zero real-time counters and the misleading overview KPIs (AN-18/AN-19)
   before the Analytics tab is used for launch decisions.

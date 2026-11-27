# Admin analytics reconciliation — cohort `admin-superadmin`

Status: complete for the read-only surface. Production was queried, not a local copy.
Owner: admin-superadmin test sub-agent.
Audit branch: `audit/production-2026-11-27`.
Report date: 2026-11-27 (UTC).

Related files: [`admin.md`](../plans/admin.md), [`identity-matrix.json`](../plans/identity-matrix.json),
[`ground-truth.md`](../ground-truth.md), [`production-changes.md`](../changes/production-changes.md),
[`http.csv`](../inventory/http.csv).

---

## 1. Scope and method

**Question:** for every admin analytics endpoint/dashboard, does the number the API returns match the
source tables for the same window, and does a fresh user action move it?

**Surfaces covered**

- 35 `GET /admin/analytics/*` operations (all that exist in the source OpenAPI at the deployed SHA),
  including the two path-parameter share/portfolio endpoints.
- The primary Analytics tab endpoint `GET /analytics/admin/overview` (the payload the admin landing
  tab actually loads).
- The adjacent analytics dashboards that share the same source data:
  `/admin/billing/checkout-funnel`, `/admin/billing/dunning-recovery`,
  `/admin/subscriptions/analytics`, `/admin/referrals/summary`,
  `/admin/revenue/coupon-student-performance`.
- Read-only admin surfaces that gate or contextualise analytics: `/admin/audit`, `/admin/users`,
  `/admin/alerts`, `/admin/feature-flags`, `/admin/entitlements`, `/admin/operations/health`,
  `/admin/plan-catalog`.

**Environment**

| Item | Value |
|---|---|
| Backend | `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run` (Modal) |
| Database | Production PostgreSQL 17.12, direct read-only `asyncpg` session |
| Admin identity | `audit+admin-superadmin-20261127103328@example.test`, user `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` |
| Role / plan | `admin` / `free` (product entitlements still plan-gated) |
| Probe window (all dashboards) | `2026-11-27T10:45:02Z` – `2026-11-27T10:45:57Z` |
| DB reconciliation cutoff | `2026-11-27T10:46:00Z` (matches the probe window, excludes later audit traffic) |
| Fresh-action window | `2026-11-27T10:59:55Z` – `2026-11-27T11:03:29Z` |
| Final freshness check | `2026-11-27T11:17Z` |
| Rate | 33 analytics calls in ~55 s (≈36/min burst; no 429). Later probes used ≥2 s spacing (≤20/min). |

**Method**

1. Captured the 30-day endpoint response with the `admin-superadmin` bearer token.
2. Re-ran equivalent SQL against the production DB with the same window and filters.
3. Tested one fresh resume creation, one direct `POST /compile`, and one async
   `POST /jobs/submit` (`latex_compilation`); checked user-scoped rows and the dashboard payloads
   before/after. Endpoint totals were treated as secondary because other audit cohorts were writing
   concurrently.
4. Re-checked suppression, timezone, event counts, funnel denominators and PostHog observability.

**Test-traffic caveat.** The audit cohort is 16–17 `audit+*` users plus e2e fixtures. The 30-day
window is dominated by synthetic data:
16/17 new users at the cutoff (94%), 12/12 subscription rows, and 10/10 "paid" subscriptions. Other
cohorts were actively writing during this test (resumes, compiles, template events, consent
withdrawals, student verification, feature-flag updates). All numbers below are therefore tied to the
timestamps above.

---

## 2. Result summary

| Result | Count |
|---|---|
| Analytics endpoints reachable with the admin token (200) | 35 / 35 |
| Endpoint values explained by the same SQL window (including documented suppression) | 35 / 35 |
| Primary Analytics tab endpoint reachable | `GET /analytics/admin/overview` 200 in 4,101.3 ms / 23,497 B |
| Endpoints returning null/zero instead of a small suppressed count | 2 (`feature-depth`, `editor-modes`) |
| Semantic disagreements with the source of record | 4 (paid conversion, MRR/upgrade history, auto-save counted as optimization, overview KPI definitions) |
| Source tables empty or key field missing | 4 (`subscription_history`, rollup table, traffic session ids, compile template ids) |
| PostHog parity observable | 0 (not configured in the served frontend) |

The admin endpoints are **available and fast enough**; the material problems are definitional and
instrumentation problems, not missing routes.

---

## 3. Endpoint-by-endpoint reconciliation

Window for all rows: `2026-10-29T00:00:00Z` to `2026-11-28T00:00:00Z` (30 UTC calendar days) unless
stated. "DB" is the independent SQL result at the same cutoff.

### 3.1 Core analytics

| # | Endpoint | HTTP | Latency (ms) | Bytes | Source table(s) | Endpoint value | DB value | Verdict |
|---:|---|---:|---:|---:|---|---|---|---|
| 1 | `/admin/analytics/activation` | 200 | 1328.8 | 9,107 | `users`, `resumes`, `compilations`, `optimizations`, `payments`, `signup_funnel_events` | cohort 17; first resume/compile/export/optimize/paid = 0/0/0/0/0 | 17; 0/0/0/0/0 | PASS counts; funnel denominator defect (AN-12) |
| 2 | `/admin/analytics/activity` | 200 | 1212.1 | 9,243 | `users`, `payments`, `compilations`, `optimizations` | 50 items, `mode=live`, `has_more=false` | 50 newest signups at 10:45; 849 users total | PASS; `has_more` semantics note (AN-15) |
| 3 | `/admin/analytics/ai-cost` | 200 | 1217.5 | 5,347 | `optimizations`, `llm_call_attempts`, price table | 0 tokens / USD 0 | 0 in window (`llm_call_attempts` 0; optimization tokens NULL) | PASS |
| 4 | `/admin/analytics/ai-latency-retry` | 200 | 1311.5 | 2,764 | `llm_call_attempts` | 0 attempts | 0 in window | PASS |
| 5 | `/admin/analytics/ai-usage` | 200 | 1196.1 | 3,123 | `llm_call_attempts`, `resume_optimization_stages`, non-autosave `optimizations` | 0 runs / 0 tokens | 0 real runs; 1 auto-save row excluded | PASS for AI; conflicts with #13 (AN-06) |
| 6 | `/admin/analytics/ats-score-distribution` | 200 | 1216.9 | 3,818 | `optimizations` (ATS fields) | 0 runs | 0 rows with ATS scores | PASS |
| 7 | `/admin/analytics/career-adoption` | 200 | 1276.2 | 9,403 | `usage_analytics`, `cover_letters`, `interview_prep`, `career_analyses` | audience 849, optimization users 2 (`optimization_lookback_days=365`), features 0 | 849 users; 2 distinct users with optimization events in 365 d (73 events); 1 cover letter (2026-08); 0 feature events in 30 d | PASS counts |
| 8 | `/admin/analytics/collaboration` | 200 | 1373.6 | 3,209 | `resume_comments`, `resume_comment_mentions`, `resume_review_comments`, `tenants`, `tenant_members` | all events 0; tenant count 1 / members 2, both suppressed | 0 comments/mentions/reviews; 1 tenant, 2 members | PASS suppression (AN-11 leak) |
| 9 | `/admin/analytics/compile-errors` | 200 | 1197.2 | 2,989 | `compilations` (failed) | 0 failed | 0 failed | PASS |
| 10 | `/admin/analytics/compile-latency` | 200 | 1243.2 | 656 | `compilations` | samples 1; p50 18.524 s; missing dimensions 3 | 1 completed; `compilation_time=18.523728609`; plan/compiler/template all NULL | PASS exact (AN-10) |
| 11 | `/admin/analytics/consent` | 200 | 1213.5 | 9,465 | `usage_analytics` (`consent_*`) | 15 granted / 0 denied / 3 withdrawn; 6 sessions; total suppressed | 15 / 0 / 3; 6 sessions | PASS exact (AN-12 naming) |
| 12 | `/admin/analytics/credential-mix` | 200 | 1205.3 | 4,085 | `optimizations`, `resume_optimization_stages` | 0 calls; self-check `mix_share_sum` ok=false | 0 calls | PASS count; false self-check at zero (AN-14) |
| 13 | `/admin/analytics/daily-metrics` | 200 | 1205.8 | 10,030 | `users`, `compilations`, `optimizations`, `usage_analytics`, `payments`, `payment_refunds` | 17 new / 1 compile / 1 optimization / 182 events / 0 payments | 17 / 1 / 1 / 182 / 0 | PASS exact; rollup empty (AN-05) |
| 14 | `/admin/analytics/document-complexity` | 200 | 1154.6 | 5,433 | `compilations` | totals 0; `source_rows=1`; hidden by suppression | 1 row; page/section counts NULL | PASS suppression; no complexity data |
| 15 | `/admin/analytics/editor-modes` | 200 | 1255.8 | 3,257 | `usage_analytics` editor events, `compilations` | all values null | 0 editor events; 1 compile | PASS (no telemetry; suppressed) |
| 16 | `/admin/analytics/errors` | 200 | 1257.9 | 667 | `admin_error_groups`, error usage | 0 events/groups | 0 groups; 0 error events | PASS; delivery unconfigured (AN-17) |
| 17 | `/admin/analytics/feature-adoption` | 200 | 2493.3 | 574,422 | `usage_analytics` + registry + `users` | usage 2, matrix 2, 100% matched | 2 attributed events (compile ×2, 2026-11-03) | PASS exact; payload/latency (AN-16) |
| 18 | `/admin/analytics/feature-depth` | 200 | 1172.4 | 981 | `usage_analytics` join `users` | suppressed; totals 0 | 1 user, 2 events | PASS suppression |
| 19 | `/admin/analytics/flag-exposure` | 200 | 1648.0 | 54,068 | `admin_experiments`, `admin_experiment_exposures` | 6 flags, 0 exposures | 0 experiments / 0 exposures | PASS; observational only |
| 20 | `/admin/analytics/integrations` | 200 | 1223.4 | 5,976 | `usage_analytics` integration events, token columns | 0 connections/events | 0 GitHub/Dropbox tokens; 0 events | PASS |
| 21 | `/admin/analytics/landing-conversion` | 200 | 1237.3 | 3,007 | `usage_analytics` page_view, `device_trials`, `users`, `subscriptions` | 46 / 3 / 17 / 10 | 46 / 3 / 17 / 10 (10 = active/past-due subs) | counts PASS; paid step FAIL (AN-02) |
| 22 | `/admin/analytics/onboarding` | 200 | 1156.8 | 3,257 | onboarding events | 0 accounts | 0 events | PASS (no telemetry) |
| 23 | `/admin/analytics/optimization-acceptance` | 200 | 1204.8 | 3,124 | `resume_optimization_runs`, `resume_suggestion_decisions` | 0 candidates/decisions | 0 runs/stages/decisions | PASS |
| 24 | `/admin/analytics/paths` | 200 | 1171.0 | 3,671 | `usage_analytics` page_view, `subscription_history` | 0 outcomes | `subscription_history` 0 rows; 12 subscriptions | PASS source; blind to comped subs (AN-03) |
| 25 | `/admin/analytics/plan-health` | 200 | 1239.1 | 3,503 | `subscriptions`, `payments`, `payment_refunds` (weekly/lifetime only) | 0 active, 0 revenue | 0 weekly/lifetime; 12 other-plan subs | PASS within scope; coverage gap (AN-13) |
| 26 | `/admin/analytics/privacy-breakdowns` | 200 | 1196.0 | 2,930 | `usage_analytics` page_view, `users` | 150 views / 80 "sessions" / 17 signups | 150 views / 80 devices / 17 users | counts PASS; session definition (AN-09) |
| 27 | `/admin/analytics/retention` | 200 | 1219.9 | 5,594 | `users`, `usage_analytics`, `compilations`, `optimizations`, `resumes` | cohort 16; no eligible rates | 16 users in week 2026-11-23+; no D1 elapsed | PASS |
| 28 | `/admin/analytics/share-portfolio` | 200 | 1193.8 | 3,482 | `resumes`, `resume_views`, usage | 0 links/views | 2 share tokens from 2026-08; 1 view older | PASS (period-scoped) |
| 29 | `/admin/analytics/team-seats` | 200 | 1215.7 | 3,154 | `team_seats`, `users`, `subscriptions`, `tenants` | seats 2, summary suppressed | 2 seats; 2 team subscriptions; 1 tenant | PASS suppression (AN-11) |
| 30 | `/admin/analytics/timeseries` (`events`) | 200 | 1584.7 | 1,361 | `usage_analytics` | total 182 | 182 | PASS exact |
| 31 | `/admin/analytics/traffic-sources` | 200 | 1198.5 | 963 | `usage_analytics` page_view + first-touch, `users`, `payments` | 0 sessions / 0 visitors; 17 unattributed signups | 0 `visitor_id` in 150 page views | PASS counts; structurally blind (AN-09) |
| 32 | `/admin/analytics/trial-attribution` | 200 | 1216.9 | 1,906 | `device_trials`, `trial_attributions`, `users`, `subscriptions` | 3 trials / 17 signups / 10 paid | 3 / 17 / 10 status-based / 0 payments | counts PASS; paid FAIL (AN-02) |
| 33 | `/admin/analytics/trial-health` | 200 | 1224.8 | 9,110 | `device_trials`, `deep_analysis_trials` | 7d 1 / 30d 3 / 90d 27 | 1 / 3 / 27 | PASS exact |
| 34 | `/admin/analytics/share-portfolio/portfolios/{username}` | 200 | 1256.7 | 3,542 | share/portfolio sources | 0 links/views | portfolio disabled; 0 views | PASS |
| 35 | `/admin/analytics/share-portfolio/resumes/{resume_id}` | 200 | 1186.7 | 1,914 | share/portfolio sources | 0 links/views in window | share link created 2026-08-11; 0 views in window | PASS (period-scoped; name is misleading) |

### 3.2 Adjacent dashboards

| Endpoint | HTTP | Latency (ms) | Endpoint value | DB value | Verdict |
|---|---:|---:|---|---|---|
| `/admin/billing/checkout-funnel` | 200 | 1157.1 | 12 started / 12 provider-created / 10 paid; `billing_mode=live` | 12 subscriptions in window; **0 payments**; 10 active/past-due | FAIL: "paid" 10 with zero settlement (AN-02) |
| `/admin/billing/dunning-recovery` | 200 | 1240.2 | 0 cases | `subscription_history` 0 | PASS (no history) |
| `/admin/subscriptions/analytics` | 200 | 1252.1 | active 0, MRR 0, plan mix [], suppressed | 9 active + 1 trialing + 1 past-due + 1 cancelled; 0 history rows | FAIL: zero MRR on 12 subscriptions (AN-03) |
| `/admin/referrals/summary` | 200 | 1227.4 | 0 captured/paid/rewards | 0 attributions, 0 rewards | PASS |
| `/admin/revenue/coupon-student-performance` | 200 | 1307.2 | 2 coupons / 1 active / 0 redemptions | 2 coupons (1 expired), 0 redemptions | PASS |

### 3.3 Primary Analytics tab payload (`GET /analytics/admin/overview`)

Probed at `2026-11-27T11:19Z`, request `e5366aa9-3e1f-4ee9-a202-822994deac58` (200, 4,101.3 ms,
23,497 bytes). This is the payload the admin Analytics tab actually renders
(`frontend/src/components/admin/AdminAnalytics.tsx`).

| Field | Endpoint | DB at 11:21Z | Verdict |
|---|---|---|---|
| `system.total_users` | 850 | 850 | PASS |
| `system.new_users` (30 d) | 18 | 18 | PASS |
| `system.total_compilations` | 22 | 22 | PASS |
| `system.successful_compilations` | 17 | 17 | PASS |
| `system.success_rate` | 77.27 % | 17 / 22 (17 completed, 4 cancelled, 1 failed) | PASS numerically; in-flight/cancelled lower it |
| `system.total_optimizations` | 9 | 9 rows, but only **2** are non-auto-save | FAIL definition (AN-06) |
| `system.active_subscriptions` | 10 | 10 rows in active/past-due | PASS count; **includes past_due** (AN-02) |
| `system.total_revenue_inr` | 0 | 0 payments | PASS |
| `system.trial_users` | 3 | 3 device trials in 30 d | PASS |
| `system.conversion_rate` | 100 % | 18 new users / 3 trials, clamped to 100 | FAIL label/semantics (AN-19) |
| `system.real_time_metrics.today` | 0 / 0 / 0 / 0 | 21 compilations, 8 optimizations, 17 registrations | **FAIL: all-zero Redis counters** (AN-18) |
| `conversion_funnel` | 46 / 3 / 18 / 10 | 46 / 3 / 18 / 10 | counts PASS; paid step FAIL (AN-02) |
| `signup` funnel | started 0, completed 18, verified 17 | 0 / 18 / 17 | PASS counts; start denominator 0 (AN-12) |
| `top_features` | page_view 150, consent 17, resume 15, compile 4 | 150 / 17 / 15 / 4 | PASS; compile 4 vs 22 compilations shows the event gap |
| `metrics_freshness` | `no_rollup` | rollup 0 rows | PASS fallback; AN-05 |

### 3.4 Supporting read-only admin surfaces

| Endpoint | HTTP | Latency (ms) | Bytes | Observed |
|---|---:|---:|---:|---|
| `/admin/audit?limit=5` | 200 | 1230.7 | 4,356 | 219 audit rows; newest are GDPR/approval events at 10:58 |
| `/admin/users?limit=5` | 200 | 2030.2 | 1,301 | 850 users |
| `/admin/alerts?limit=5` | 200 | 1186.7 | 3,929 | 18 alerts |
| `/admin/feature-flags` | 200 | 1440.3 | 19,793 | 155 flags, 155 enabled |
| `/admin/entitlements` | 200 | 1656.2 | 85,184 | registry 165, kill switches 149, 11 plan keys, 5 families |
| `/admin/operations/health` | 200 | 2353.0 | 2,082 | `degraded`: 5 failed webhooks, 1 past-due; all infra sections healthy |
| `/admin/plan-catalog` | 200 | **23,051.5** | 92,435 | 11 plans served from application constants; `plan_catalog` table has 0 rows |

**Reference request IDs** (all from the 10:45Z probe unless stated)

| Endpoint | `x-request-id` |
|---|---|
| `daily-metrics` | `e33be564-12ae-42af-acfe-5c22d86ddc6e` |
| `compile-latency` | `10e370cb-f6d3-40ab-8ece-35aa60cc81d2` |
| `activation` | `96a1c19f-a4c5-40a1-906e-4ec5e8ac7316` |
| `feature-adoption` | `3c28a0c6-8de4-4557-b657-44a92ddea623` |
| `consent` | `5ef47b13-b372-4c6c-9186-8ac3863912ce` |
| `timeseries` | `8b7ef033-014c-4d1e-bf20-b1ecadd40b6d` |
| `landing-conversion` | `417ef26b-9f5f-490f-8d09-99dd1361183b` |
| `trial-attribution` | `8b94ed2a-f8c0-461e-9e37-fde5bfb6e0ba` |
| `checkout-funnel` (11:11Z) | `0203194f-bb7f-4ce0-95f5-3cf713b2a1ab` |
| `subscriptions/analytics` (11:13Z) | `9b9e4afe-cc61-4627-8b85-fc62486ee582` |
| `plan-catalog` (11:13Z) | `949adbae-b7b5-492e-8c5d-ca7f18491f16` |
| `analytics/admin/overview` (11:19Z) | `e5366aa9-3e1f-4ee9-a202-822994deac58` |

---

## 4. Independent SQL evidence

### 4.1 Exact daily-metrics match

```sql
-- At 2026-11-27T10:46Z, window 2026-10-29T00:00Z .. 2026-11-28T00:00Z
SELECT count(*) FROM users
 WHERE created_at >= '2026-10-29 00:00:00+00' AND created_at < '2026-11-27 10:46:00+00';
-- 17 (1 on 2026-11-01 + 16 audit users on 2026-11-27)

SELECT status, count(*) FROM compilations
 WHERE created_at >= '2026-10-29 00:00:00+00' AND created_at < '2026-11-27 10:46:00+00'
 GROUP BY 1;
-- completed 1

SELECT count(*) FROM optimizations
 WHERE created_at >= '2026-10-29 00:00:00+00' AND created_at < '2026-11-27 10:46:00+00';
-- 1

SELECT action, count(*), count(DISTINCT user_id) FROM usage_analytics
 WHERE created_at >= '2026-10-29 00:00:00+00' AND created_at < '2026-11-27 10:46:00+00'
 GROUP BY 1;
-- page_view 150 (0 users); consent_granted 15 (0); render_artifact_gc.sweep 10 (0);
-- compile 3 (1); consent_withdrawn 3 (0); feature_usage 1 (1)  = 182 events, 1 distinct user

SELECT count(*) FROM payments WHERE created_at >= '2026-10-29 00:00:00+00';
-- 0
```

The endpoint returned `new_users=17, compilations=1, completed=1, optimizations=1, events=182,
active_user_days=1, peak_active_users=1, payments=0`, and its series summed to exactly the same
values. Days match the UTC date buckets (`2026-11-01` 1 user; `2026-11-03` 1 compile/1 optimization/
4 events/1 user; `2026-11-25` 8 events; `2026-11-26` 69; `2026-11-27` 16 users/101 events).

The one sparse day is `2026-11-03` (`active_users=1`). The endpoint exposes `active_users=1` and the
exact event/compile counts and merely flags `sparse=true`; it does not withhold the values (AN-11).

### 4.2 Direct `/compile` is metered but invisible to analytics

Fresh action, admin user `8b2ee54b-…`:

| Evidence | Value |
|---|---|
| `POST /resumes/` | 201, 1,081.5 ms, resume `7af40e7a-c2a3-4ac2-b123-a01addab429b` |
| `POST /compile` | 200, 1,470.2 ms, job `388d4ad5-904a-44dc-87a0-8eefe0780ffd`, `compilation_time=0.226 s` |
| Quota before → after | `compilations.used` 0 → **1** (later 2 after the async job) |
| `compilations` rows for user | **0** |
| `usage_analytics` rows for user | 1 (`resume_created` only) |
| `/admin/analytics/daily-metrics?days=1` | compilations unchanged by this call |
| `/admin/analytics/compile-latency?days=1` | sample count unchanged by this call |

The handler (`backend/app/api/routes.py:767`) calls `entitlement_service.enforce_quota()` and
`latex_service.compile_latex()`, but never inserts a `compilations` row and never records a
`usage_analytics` event. Every compile-health dashboard therefore omits direct compiles, while the
customer is still charged. The async job path does insert a row (see 4.3).

### 4.3 Async job compile moves the table metric, not the event metric

| Evidence | Value |
|---|---|
| `POST /jobs/submit` | 200, 3,967.1 ms; job `f7732594-056a-44e9-a7a1-a2caa6d3c4b5` |
| States | queued 11:02:43–11:03:03Z, processing 11:03:03–11:03:18Z, completed 11:03:18Z |
| `compilations` row | `b22f39c5-1607-4aab-b84e-d228e6526094`, completed, `compilation_time=7.9276`, `plan_family=free`, `compiler=pdflatex`, `template_id=NULL` |
| `usage_analytics` compile events for user | **0** |
| `compile-latency` before → after | samples 10 → 14 (my 1 + concurrent 3), all `missing_dimension_fields` |
| `daily-metrics` before → after | compilations 10 → 15 (my 1 + concurrent 4) |

`compilations` moves; the event-based `timeseries`, feature-adoption and paths dashboards do not.

### 4.4 Event loss and duplication

```sql
-- 30 days to the probe cutoff
SELECT count(*) FROM usage_analytics WHERE action='compile' AND created_at >= '2026-10-29';  -- 3
SELECT count(*) FROM compilations    WHERE created_at >= '2026-10-29';                       -- 1 at probe (18 later)
-- today at 11:07Z
SELECT count(*) FROM usage_analytics WHERE action='compile' AND created_at >= '2026-11-27';  -- 0
SELECT count(*) FROM compilations    WHERE created_at >= '2026-11-27';                       -- 17
```

- At the probe cutoff: **3 compile events vs 1 compilation row** (2 anonymous-trial events, 1
  owner event). At 11:07Z: **0 compile events vs 17 compilation rows** — 100% event loss for
  authenticated compiles in the current period.
- Historical duplication is present: 3 `compilation_id` groups with more than one event in 90 days,
  **29 extra events**, with one `compilation_id` emitted **28 times** between 17:29:26 and 17:32:04
  on 2026-10-06. Client retry/duplicate emission is not idempotent at the event layer.
- `usage_analytics` has no unique key on `(action, compilation_id)`, so the dashboards that count raw
  rows can double count.

### 4.5 Paid conversions with zero payments

| Source | Count |
|---|---:|
| `payments` (all time) | 0 |
| `subscriptions` created in window | 12 (all `audit+*`, all direct inserts) |
| status `active` | 9 |
| status `past_due` | 1 |
| status `trialing` | 1 |
| status `cancelled` | 1 |
| `landing-conversion` "subscriptions" | 10 |
| `trial-attribution` "paid users" | 10 |
| `checkout-funnel` "paid" | 10 |

All three dashboards define "paid" as `subscriptions.status IN (active, cancel_scheduled, past_due)`
(`landing_conversion_service.py:318`, `trial_attribution_service.py:631`,
`checkout_funnel_service.py:194`), not as a settled payment. In this window that makes 10 comped rows
look like ₹ paid conversions against a `payments` table with 0 rows.

`subscription_history` has 0 rows, and `/admin/subscriptions/analytics`/`paths` derive MRR and
upgrade outcomes from it, so the same 12 subscriptions are reported as **0 active / 0 MRR / 0
upgrades** there. Two dashboards answer the same question in opposite directions.

### 4.6 Timezone and day boundaries

- `/admin/analytics/daily-metrics` window: `2026-10-29T00:00:00+00:00` → `2026-11-28T00:00:00+00:00`,
  `timezone: UTC`. SQL uses `created_at AT TIME ZONE 'UTC'` and `[start, end)`. Verified exact
  per-day match (section 4.1). **PASS.**
- `/admin/analytics/consent` puts all 18 consent events on `2026-11-26` in both API and DB. **PASS.**
- `/admin/analytics/privacy-breakdowns` and `landing-conversion` use a rolling window anchored at
  query time (`10:45Z`, not midnight), while `daily-metrics`/`retention` use UTC calendar days.
  A "30-day" number from two dashboards is therefore not the same 30 days (AN-07).
- `/admin/analytics/trial-health` uses rolling `24h × N` windows ending at query time
  (`2026-11-20T10:45:57Z` → `2026-11-27T10:45:57Z`), so its 7-day count is not comparable to the
  calendar buckets used elsewhere.

### 4.7 Suppression (`<5`) audit

Working as designed in the primary payloads:

| Surface | Suppressed value | Evidence |
|---|---|---|
| consent | `withdrawn=3` and `total` hidden; `suppressed_cells=["total","withdrawn"]` | 3 withdrawals in DB |
| collaboration | tenant with 2 members omitted from `tenants[]`; `visible_tenant_count=0` | 1 tenant, 2 members |
| document-complexity | 1 compilation hidden (`hidden_by_suppression=true`) | 1 source row |
| team-seats | 2 seats / 2 invitations hidden; `summary.current=null` | 2 seats |
| feature-depth | 1 user / 2 events hidden; totals zeroed | 1 user |
| editor-modes | all summary values null | 0/1 events |
| ats / daily sparse | flagged | 1 user |
| trial-health | 1-device usage bucket hidden | 1 device |

Suppression leak (AN-11): the reconciliation blocks publish the exact small counts that the primary
fields hide — `collaboration.reconciliation` (`tenant_count=1`, `tenant_member_count=2`),
`team-seats.reconciliation` (`seats_scanned=2`, `period_invitations=2`),
`document-complexity.reconciliation` (`source_rows=1`), and daily-metrics `sparse` days still show
`active_users=1` plus exact event counts. If an admin UI renders these fields, a <5 cohort is
recoverable.

### 4.8 PostHog parity — **NOT OBSERVABLE**

- The served production HTML for `https://latexy.xyz` and `https://www.latexy.xyz` (95,174 bytes,
  2026-11-27T11:10Z) contains **no `phc_*` key and no `*.posthog.com` host**, so the browser SDK is
  not configured in the deployed build.
- `/admin/analytics/paths` reports `data_source.kind=first_party_event_sequences` and
  `posthog_paths_queried=false`.
- The audit has no PostHog personal API key/read access, so event-to-PostHog duplication/loss cannot
  be measured. The backend `posthog_service` is a no-op when `POSTHOG_API_KEY` is empty
  (`backend/app/services/posthog_service.py:153-160`); production key presence is not inspectable
  from here.
- **Verdict:** PostHog vs DB parity is blocked, not passed. All dashboards verified here are
  first-party Postgres only.

### 4.9 Query latency vs database time

- 33 analytics GETs: min 1,154.6 ms, p50 **1,216.9 ms**, p95 1,648.0 ms, p99/max 2,493.3 ms.
- `EXPLAIN (ANALYZE)` of the daily-metrics CTE: **0.382 ms** execution, 0.344 ms planning, 850 users.
- The 1.2 s floor is request/transport overhead (Modal + middleware), not SQL. No analytics query
  exceeded 2.5 s except `/admin/plan-catalog` at **23,051.5 ms**.
- Largest payloads: feature-adoption 574,422 bytes (2,493.3 ms), flag-exposure 54,068 bytes
  (1,648.0 ms), daily-metrics 10,030 bytes. All requests returned 200; no 429 observed.

---

## 5. Fresh-action tests — did the metric move?

The dashboard totals were noisy because other cohorts were writing during the test; the user-scoped
DB rows are the authoritative before/after evidence.

| Action | DB effect | Dashboard effect | Verdict |
|---|---|---|---|
| Create resume (11:00:15Z) | `resumes` 0→1; `usage_analytics` 0→1 (`resume_created`) | activation `first_resume` 5→6 in the concurrent window; feature-adoption usage 12→15 | **Moves** |
| Direct `POST /compile` (11:00:2xZ) | quota 0→1; no `compilations` row; no usage event | no compile sample, no compilation count attributable to the user | **Does not move** (AN-01) |
| Async `POST /jobs/submit` (11:02:34Z) | quota 1→2; 1 `compilations` row; no usage event | `compilations` and `compile-latency.samples` moved (with concurrent traffic); event metrics did not | **Partly moves** (AN-04) |

The following two rows are **observed from audit provisioning / other cohorts**, not actions taken by
this sub-agent; they are included because they explain the state of the conversion dashboards:

| Observation | DB effect | Dashboard effect | Verdict |
|---|---|---|---|
| Audit subscriptions inserted | 12 rows (9 active, 1 trialing, 1 past-due, 1 cancelled) | landing/trial/checkout "paid" = 10; subscriptions analytics stayed 0 | **Inconsistent** (AN-02/03) |
| Consent e2e fixture | 15 grants / 3 withdrawals / 6 sessions | consent summary matched exactly | **Moves** |

---

## 6. Defects found (for `defects.md`)

| ID | Sev | Surface | Finding | Evidence | Proposed fix |
|---|---|---|---|---|---|
| AN-01 | P1 | `POST /compile`, compile dashboards | Direct authenticated compile charges quota but writes no `compilations` row and no usage event, so compile latency/errors/document complexity/activation never see it. | quota 0→1; 0 rows for user; job `388d4ad5…` | Insert a `compilations` row + `compile` event in `compile_latex_endpoint`, or route all direct compiles through the job pipeline. |
| AN-02 | P1 | landing, trial-attribution, checkout-funnel | "Paid" is inferred from `subscriptions.status`, not settled payments. With 0 payments, all three dashboards report 10 paid conversions. | 10 vs `payments`=0; all 12 subs synthetic | Require `payments.status IN (paid,captured,…)` or an explicit comp flag; label comped separately. |
| AN-03 | P1 | `/admin/subscriptions/analytics`, `/admin/analytics/paths`, plan-health | MRR/upgrades are derived from `subscription_history` (0 rows), so 12 live subscription rows report 0 active/0 MRR/0 outcomes; the sibling dashboards report 10 paid. | history_rows=0; 9 active subs; request `9b9e4afe…` | Backfill history on direct/admin grants or derive current state from `subscriptions` with a declared source. |
| AN-04 | P2 | timeseries, feature adoption, paths | Authenticated compiles do not emit a `compile` usage event: at 11:07Z, 0 events vs 17 compilations today; over the 30 days ending 11:07Z, 3 events vs 18 compilations. Event-based metrics undercount authenticated compiles by 83–100%. | SQL counts; section 4.4 | Emit a server-side compile event on job completion, independent of the browser. |
| AN-05 | P2 | daily-metrics rollup | `admin_daily_metrics` has 0 rows and `last_refreshed_at=null`; every request falls back to base tables. The 10-minute Celery beat task exists but never populated the table. | freshness `no_rollup`; 0 rows; `/admin/operations/health` worker owns no queues | Verify beat is running and a worker consumes the `cleanup` queue; alert on stale rollup. |
| AN-06 | P2 | daily-metrics, activation | Daily/activation count every `optimizations` row, including auto-save checkpoints; AI usage excludes them. Probe: 1 vs 0. At the 11:05Z check all 7 optimization rows were `is_auto_save=true`, `is_checkpoint=true`; daily had risen to 8 by 11:17Z while AI usage still excluded them. | row `d24e7914…`; 7/7 auto-save | Add the same `is_auto_save/is_checkpoint` exclusion to daily metrics and activation. |
| AN-07 | P2 | all "days=N" dashboards | Calendar-day windows and rolling `now−N×24h` windows are mixed, so identical `days=30` values cover different intervals (10 h 45 m apart in this sample). | daily start 00:00 vs landing/consent start 10:45 | Standardise on UTC calendar days and return the exact interval (already returned by some). |
| AN-08 | P2 | all analytics | No endpoint can exclude the `audit+*` cohort or internal traffic. 94–100% of this window is synthetic, and every dashboard includes it. | 16/17 new users, 12/12 subs, 10/10 paid are audit | Add an internal/test cohort flag and an `exclude_test` filter; purge before launch. |
| AN-09 | P2 | privacy-breakdowns, traffic-sources | `privacy-breakdowns.sessions` is distinct device fingerprints (80), not sessions; page views have 0 `visitor_id` values, so traffic-sources can never attribute a session. | 150 views / 80 devices / 0 session ids | Store a consent-safe session/visitor id on page views; rename the device count. |
| AN-10 | P2 | compile-latency/errors/document-complexity | `template_id` is NULL on 100% of compilations; the probe compile also had NULL plan/compiler. By-template and by-plan cutovers are empty. | `missing_dimension_fields=3` for 1; `null_template=16/16` at 11:05Z | Populate plan/compiler/template at job admission. |
| AN-11 | P3 | collaboration, team-seats, document-complexity, daily | Primary fields suppress <5, but reconciliation blocks publish the exact suppressed counts (1 tenant/2 members, 2 seats, 1 row, 1 active user). | Section 4.7 | Remove or bucket reconciliation counts that are below the privacy floor. |
| AN-12 | P3 | activation signup funnel, consent | Funnel shows `signup_started=0` with 17 completions and 0% start→complete; consent names `eligible_sessions=5` while `sessions_with_consent=6` (coverage 83.33%). | signup funnel block; consent `replay_coverage` | Intersect completions with starts; swap/enforce the consent field definitions. |
| AN-13 | P3 | plan-health | Only `weekly` and `lifetime` are modelled (2 of 11 plan keys); actual basic/pro/byok/student/team subscriptions are absent, so zeros can be misread. | `PLANS=("weekly","lifetime")`; 12 subs across 7 other plan IDs | Cover all plan keys or label the scope explicitly in the UI. |
| AN-14 | P3 | credential-mix | At zero calls the self-check reports `mix_share_sum` expected 100 / actual 0 / `ok=false`. | probe body | Skip the percentage check when the denominator is 0. |
| AN-15 | P3 | activity feed | Initial page reports `has_more=false` while returning a `next_cursor`; feed sources exclude resume and subscription events, so two of the four fresh-action classes never appear. | `/admin/analytics/activity`; `resume_created` absent | Clarify `has_more` semantics; include resume/subscription lifecycle. |
| AN-16 | P2 | `/admin/plan-catalog` | Single sample 23,051.5 ms for 92 KB (roadmap target p95 < 1.5 s). | request `949adbae…` | Profile query/serialisation; cache the constant catalog. |
| AN-17 | P2 | error alerts | Error feed delivery is unconfigured (`configured=false`, channels `[]`), so threshold alerts exist only in the UI. | `/admin/analytics/errors.delivery` | Configure an email/Slack channel; verify with a synthetic error. |
| AN-18 | P2 | `/analytics/admin/overview` | The "today" / "this hour" real-time counters are all zero while the DB has 21 compilations, 8 optimizations and 17 registrations today. The service reads Redis `analytics:daily:*` keys that no producer appears to increment. | request `e5366aa9…`; system block vs DB at 11:21Z | Write the counters at event time or compute from first-party tables; alert on zero while activity exists. |
| AN-19 | P2 | `/analytics/admin/overview` | KPI labels do not match their formulas: `conversion_rate` = `min(new_users/trial_users*100,100)` (18/3 → 100%), `active_subscriptions` includes `past_due`, `total_optimizations` includes auto-saves, `success_rate` includes cancelled/in-flight compiles. | system block; `analytics_service.py:533-583` | Rename the KPI or use trial→paid / settled-payment definitions; exclude auto-saves and pending states. |

---

## 7. Test artifacts, traffic exclusion and cleanup

**Time windows to exclude from analytics**

- Audit identity provisioning: `2026-11-27T10:33:28Z` onward (all `audit+*@example.test` users).
- This reconciliation probe: `2026-11-27T10:45:02Z` – `2026-11-27T10:45:57Z`.
- Fresh action: `2026-11-27T10:59:55Z` – `2026-11-27T11:03:29Z`.
- Supporting read-only probes: `2026-11-27T11:06Z` – `2026-11-27T11:21Z`.

**Audit user IDs to exclude** (all share the `audit+*` prefix; the matrix has the full snapshot)

| Cohort | User ID | Email |
|---|---|---|
| free | `96c507cd-e7a2-4749-9153-96b6321742db` | `audit+free-20261127103328@example.test` |
| basic-monthly | `0e0b7f8d-e7d0-48da-9e66-dcee3e52f0cb` | `audit+basic-monthly-20261127103328@example.test` |
| basic-annual | `2f49586c-570d-4802-82bc-187ec0a516df` | `audit+basic-annual-20261127103328@example.test` |
| pro-monthly | `2c27be6f-138f-4e98-b311-38892520b1eb` | `audit+pro-monthly-20261127103328@example.test` |
| pro-annual | `c30d524c-a2db-4a6c-8aee-d8d5d2a9f7f4` | `audit+pro-annual-20261127103328@example.test` |
| byok-monthly | `373bf051-a804-4ae5-a10e-46970964c508` | `audit+byok-monthly-20261127103328@example.test` |
| student | `d91e5bf0-bbc9-4558-9e10-151e728cdeec` | `audit+student-20261127103328@example.test` |
| trial-active | `3b8ddb07-2b18-486c-9c18-d32ce3fbbb47` | `audit+trial-active-20261127103328@example.test` |
| trial-expired | `620c8a6e-db14-4be2-806a-13365c667fdd` | `audit+trial-expired-20261127103328@example.test` |
| past-due | `a24f1fd9-34f9-4a84-8ba8-74d8fa431ca1` | `audit+past-due-20261127103328@example.test` |
| cancelled | `dfd20a28-a4d5-40db-aa77-597ce6f3e589` | `audit+cancelled-20261127103328@example.test` |
| team-owner | `6bb81a84-860b-46a5-8ab4-f1c483068479` | `audit+team-owner-20261127103328@example.test` |
| team-member | `7a3d3b80-000c-49f0-a067-96c177b7c848` | `audit+team-member-20261127103328@example.test` |
| admin-support | `942247dc-f834-43d9-b012-a552ec6632a4` | `audit+admin-support-20261127103328@example.test` |
| admin-superadmin | `8b2ee54b-a2ee-4009-9eee-4cc995b3d2ad` | `audit+admin-superadmin-20261127103328@example.test` |
| developer-api | `dc001b15-2133-4c18-a1a1-d0af1952835c` | `audit+developer-api-20261127103328@example.test` |

**Accounts / rows created by this sub-agent**

| Artifact | ID | Notes |
|---|---|---|
| Resume | `7af40e7a-c2a3-4ac2-b123-a01addab429b` | "Audit admin-superadmin analytics probe" |
| Direct compile job | `388d4ad5-904a-44dc-87a0-8eefe0780ffd` | Quota charged; no DB row |
| Async job | `f7732594-056a-44e9-a7a1-a2caa6d3c4b5` | Quota charged |
| Compilation row | `b22f39c5-1607-4aab-b84e-d228e6526094` | Keep for evidence; cleanup owner: cleanup auditor |
| Admin quota | 2 / 10 compilations used, 0 / 3 optimizations, 0 / 25 assists | Free plan; resets 2026-11-28T00:00Z |

No global config, plan, entitlement, feature flag or deployment change was made. No deletion was
performed; the artifacts above are listed for the cleanup auditor.

**Limitations / methodology deviations**

- The initial 33-endpoint probe ran at ≈36 requests/min for under a minute, slightly above the
  20/min target. No 429 or throttling was returned; every later probe used ≥2 s spacing.
- All figures are single-shot observations at low data volume (849 users, 242 compilations at the
  probe). They demonstrate correctness, not steady-state percentiles.
- Concurrent audit cohorts wrote resumes, compiles, template events and consent events during this
  test. User-scoped DB rows were used for causal claims; dashboard totals are timestamped.
- PostHog parity could not be measured (section 4.8).

**Blocked / not tested**

- PostHog parity: no PostHog key/read access and no client SDK in the served HTML (section 4.8).
- `optimization-acceptance`/`ats` with real data: no resume-engine runs or scored optimizations exist.
- Rollup path (`source="rollup"`): cannot be exercised without forcing a write to
  `admin_daily_metrics`; the table is empty.
- Mutating admin analytics actions (error evaluate, exports): out of scope for a read-only
  reconciliation; no global config was touched.

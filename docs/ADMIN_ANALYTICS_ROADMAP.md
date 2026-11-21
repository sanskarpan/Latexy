# Admin analytics roadmap

Status: current-state review + prioritized build plan.
Owner surface: `/admin` and `/admin/tenant`.

> Phase 1 and the first Phase 2 growth slice (2026-11-22): the billing/webhook
> control room, User 360, audited support actions, immutable audit log, refund
> approval workflow, activation/retention cohorts, AI cost/margin, and
> dimension-filtered timeseries are implemented. See
> `docs/ADMIN_CONTROL_ROOM.md`. The tracker issues remain open for the
> remaining Phase 1 follow-ups (needs-attention queue, job actions, export)
> and the rest of Phases 2-3.

## 1. What the admin dashboard holds today

| Area | Current capability | Source | Gap |
| --- | --- | --- | --- |
| Analytics | New **Analytics** tab: KPIs, funnel, daily events/compiles, top features, redacted recent events, 24h operations strip, PostHog deep links | `GET /analytics/admin/overview`, `usage_analytics`, `compilations`, `optimizations`, `payments`, `billing_webhook_events` | No revenue/cohort/AI-cost drill-down, no saved views, no exports |
| Feature flags | Six operational flags (`trial_limits`, `deep_analysis_trial`, `compile_timeouts`, `task_priority`, `billing`, `upgrade_ctas`) | `feature_flags` | No change history, scheduling, targeting, or impact readout |
| Entitlements | Global kill-switches, family/SKU defaults, role matrix, ancestry/effective-permission explanations | `entitlement_service` + feature registry | No bulk edit, diff, approval, or "who is affected" preview |
| Plan catalog | Plan/SKU quota editing | `plan_catalog_routes` | No price/quote history, no revenue impact preview |
| Users & roles | Search, pagination, plan, verification, role change with last-admin guard | `users` | No user 360, support actions, audit trail, or session/API-key controls |
| Job queue | Queue list, filters, search, status | Redis job state / `JobQueue` | No retry/cancel/fence actions, latency percentiles, or stuck-job diagnosis |
| Tenant admin | Branding, custom domain + DNS verification, cohorts, members, member count, recruiter review link | tenant routes + cohort tables | No activation/engagement analytics, seat/billing view, or domain health history |
| Billing | None in admin | Dodo + `payments`, `subscriptions`, `payment_refunds`, `billing_webhook_events` | No MRR/ARR, invoice/refund workflow, webhook dead-letter queue, or reconciliation |
| Audit/security | Structured logs only | logger | No in-product immutable audit log, approvals, or access review |
| Alerts | None | — | No threshold alerts or "needs attention" queue |
| Experiments/surveys | None | — | No exposure/impact analysis or feedback inbox |

The new Analytics tab is deliberately a **single authoritative round-trip**:
`GET /analytics/admin/overview?days=7|30|90`. PostHog is the replay and
exploration layer; Postgres remains the source of truth for billing,
entitlements, and operational counts.

## 2. Target information architecture

Keep `/admin` as the platform control plane and add these top-level sections:

1. **Overview** — command center, alerts, needs-attention queue.
2. **Growth** — acquisition, signup, referral, SEO/content.
3. **Product** — activation, feature adoption, retention, paths, replays.
4. **Quality** — compile health, AI quality/cost, templates, accessibility.
5. **Revenue** — MRR/ARR, plans, checkout, dunning, refunds, webhooks.
6. **Customers** — user 360, segments, support actions, GDPR.
7. **Operations** — jobs, workers, infrastructure, email, incidents.
8. **Tenants** — agency/career-centre analytics and domain health.
9. **Governance** — audit log, approvals, access review, consent.
10. **Experiments** — flags, A/B tests, surveys, feedback.

`/admin/tenant` remains the tenant-owner surface; platform admins get a
cross-tenant view under **Tenants**.

## 3. Detailed feature backlog

Priority: **P0** = launch/operational necessity, **P1** = next high-value layer,
**P2** = optimization/scale.

### A. Command center

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| A1 | Executive KPI header with previous-period comparison and sparklines | P0 | Extend `/analytics/admin/overview` with prior-period deltas | Show absolute + % change; color only for meaningful movement |
| A2 | “Needs attention” queue | P0 | Failed webhooks, failed payments, stuck jobs, expiring domains, past-due subs | One click to the relevant filtered view |
| A3 | Alert strip with severity and owner | P0 | `admin_alerts` table or PostHog alerts mirrored by a cron | Acknowledge/snooze; link to runbook |
| A4 | Live activity feed (signups, payments, compiles, errors) | P1 | Redis stream or `usage_analytics` tail | Respect privacy: IDs and event names only |
| A5 | Saved views and segments | P1 | `admin_saved_views` table | Per-admin and shared views |
| A6 | CSV/PDF export and scheduled email digest | P1 | Streaming CSV endpoint; Resend | Include generation time and filters in the file |
| A7 | Release/deploy markers on charts | P2 | Deployment identity + timestamps | Correlate metric shifts with releases |

### B. Growth and acquisition

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| B1 | Traffic sources, UTM campaigns, referrers | P0 | PostHog `$pageview` properties + first-party referral cookie | Aggregate; no raw IP |
| B2 | Landing-page conversion by page/variant | P0 | PostHog funnels + `page_view` events | Compare mobile/desktop |
| B3 | Signup funnel by provider (Google, GitHub, email, OIDC, passkey) | P0 | Auth events + PostHog | Verification rate and time-to-verify |
| B4 | Referral program analytics | P1 | `referral_service`, referral tables | Signups, paid conversions, payout status, fraud flags |
| B5 | Trial-start and trial-abuse signals | P1 | `device_trials`, fingerprints (aggregated) | Never expose raw fingerprints in the UI |
| B6 | SEO/content performance | P2 | Search Console API / PostHog web analytics | Top pages, queries, CTR, dwell time |
| B7 | Geo/device/browser breakdown | P1 | PostHog aggregated properties | Suppress cohorts below a minimum size |
| B8 | Campaign ROI | P2 | UTM + paid conversion + revenue | Needs a cost table per campaign |

### C. Activation and product usage

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| C1 | Activation funnel: signup → first résumé → first compile → first export → first AI optimize → paid | P0 | PostHog funnel + first-party milestones | Segment by plan, provider, cohort |
| C2 | Feature adoption matrix by plan/role/cohort | P0 | `usage_analytics` + entitlement registry | “Used at least once” vs “weekly active” |
| C3 | Feature depth and frequency | P0 | `usage_analytics` grouped by action/feature | Identify shallow vs habitual use |
| C4 | Onboarding step completion and drop-off | P1 | Onboarding events | Per-step time and abandonment |
| C5 | Retention cohorts (D1/D7/D30, weekly) | P1 | PostHog retention or SQL cohort query | Compare signup months |
| C6 | Path analysis / Sankey | P1 | PostHog paths | Top routes before upgrade/churn |
| C7 | Editor-mode usage (source/visual/PDF), auto-compile, sync | P1 | Frontend events + compile records | Which mode correlates with success? |
| C8 | Document complexity metrics | P1 | Compile metadata: pages, sections, latency, error class | Aggregate only; never content |
| C9 | Template popularity and success | P1 | Template ID + compile/export outcome | See Quality section |
| C10 | Collaboration usage | P1 | Comments, mentions, review links, tenant cohorts | Distinct from document ACLs |
| C11 | Integration adoption and failure | P1 | GitHub/Dropbox/Drive/Zotero/Mendeley events | OAuth success, sync failures, disconnects |
| C12 | Public share/portfolio performance | P1 | `resume_views`, portfolio routes | Views → contact → signup |
| C13 | Browser extension / public API / TUI usage | P2 | Developer keys, API logs, extension events | Quota and error rates |
| C14 | Rage clicks, dead clicks, JS errors by route | P1 | PostHog autocapture/error tracking | Route-level triage, not per-user surveillance |
| C15 | Session replay browser | P0 | PostHog replays | Filters: route, plan, error, duration, checkout failure |
| C16 | Power-user vs churned-user comparison | P2 | Cohort analysis | Identify leading indicators |

### D. AI quality and cost

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| D1 | AI usage by feature/provider/model/persona | P0 | `optimizations`, `byok` usage, events | Include success/error |
| D2 | Token and cost per user/plan/feature | P0 | Token counts + provider price table | Show gross margin per plan |
| D3 | BYOK vs platform-key mix | P1 | `user_api_keys`, settings | Cost and privacy implications |
| D4 | AI latency and retry rate | P1 | Optimization records + job state | p50/p95/p99 |
| D5 | ATS score distribution and improvement | P1 | `optimizations.ats_score` | Before/after delta, by industry |
| D6 | Optimization acceptance rate | P1 | Candidate applied/discarded events | Quality signal, not just usage |
| D7 | Cover letter/interview prep/career path adoption | P1 | Feature events | Cross-sell and retention |
| D8 | Model routing/fallback analytics | P2 | Provider/model metadata | Detect silent downgrades |
| D9 | Spend caps and anomaly alerts | P0 | Aggregated token spend | Alert on outlier users/models |
| D10 | Prompt/version performance | P2 | Version ID + outcome (never prompt text) | Compare quality and cost |

### E. Revenue and billing

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| E1 | MRR/ARR, ARPU, net revenue, refunds, chargebacks | P0 | `payments`, `subscriptions`, `payment_refunds` | Daily/monthly, plan mix |
| E2 | Plan mix and upgrade/downgrade/churn | P0 | Subscription history | Cohort by signup month |
| E3 | Checkout funnel and failure reasons | P0 | `checkout_started`, payment events, provider errors | Link to replay |
| E4 | Dodo webhook health | P0 | `billing_webhook_events` | Received, processed, failed, dead-letter, replay |
| E5 | Payment/refund reconciliation queue | P0 | “No local intent” dead letters + payments | One-click replay/acknowledge |
| E6 | Subscription timeline per user | P0 | Subscription + payment + webhook events | Support-ready view |
| E7 | Dunning/past-due/on-hold recovery | P1 | Subscription status history | Recovery rate and time |
| E8 | Coupon/student verification performance | P1 | Coupon tables | Abuse and conversion |
| E9 | Invoice/receipt lookup and resend | P1 | Dodo invoice API + Resend | Audit every resend |
| E10 | Refund workflow with approval | P0 | Refund request + audit log | Never auto-refund without policy |
| E11 | Revenue by country/currency/payment method | P2 | Aggregated payment metadata | Tax/currency caveats |
| E12 | Trial-to-paid cohort conversion | P0 | Trials + subscriptions | By acquisition source |
| E13 | Lifetime/weekly plan monitoring | P1 | Subscription plan IDs | Refund/chargeback risk |
| E14 | Team seat utilization | P1 | `team_seats`, tenant data | Invite → accept → active |

### F. Reliability and operations

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| F1 | Job queue depth/age/throughput | P0 | Redis job state + `job_finalizations` | Alert on age |
| F2 | Stuck-job diagnosis and safe actions | P0 | Job state + fence/cancel APIs | Require confirmation and audit |
| F3 | Compile latency percentiles | P0 | `compilations` | By plan/compiler/template |
| F4 | Compile error taxonomy | P0 | Error classes + linter | Top errors and trend |
| F5 | Worker/container health | P0 | `/health`, Modal metrics, CPU/memory | Link to provider console |
| F6 | Redis/DB/Upstash capacity | P0 | Existing health/capacity probes | Warn before quota exhaustion |
| F7 | Email delivery status | P1 | Resend/SMTP events | Bounce/complaint rate |
| F8 | Storage/PDF artifact lifecycle | P1 | R2/DB artifact records | Orphan count and cleanup |
| F9 | Incident timeline | P1 | `admin_incidents` table | Start/end, severity, affected services |
| F10 | Synthetic checks/status page | P2 | Existing production smoke | Show last run and failures |
| F11 | Provider status (Dodo, Modal, Neon, Upstash, Resend) | P2 | Provider status APIs | Read-only feed |

### G. Customers and support

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| G1 | User 360 | P0 | Users + plans + usage + payments + integrations + events | One page, no raw document content |
| G2 | Search by email/ID/payment/subscription | P0 | Admin search endpoint | Debounced, paginated |
| G3 | Safe PII reveal with audit | P0 | Masked by default; reveal logs actor/reason | Support role gets least privilege |
| G4 | Read-only “view as user” | P1 | Scoped, time-boxed, audited | Prefer read-only over impersonation |
| G5 | Grant/revoke entitlement, extend trial, reset quota | P0 | Entitlement service + audit | Confirmation + reason |
| G6 | Resend verification/password reset/receipt | P1 | Auth/email services | Rate-limited |
| G7 | Revoke sessions/passkeys/API keys | P0 | Auth + BYOK/developer keys | Immediate effect |
| G8 | Notes, tags, support timeline | P1 | `admin_user_notes` | Internal only |
| G9 | GDPR export/delete workflow | P0 | Existing deletion paths + status | Legal review before launch |
| G10 | Abuse signals | P1 | Trials, fingerprints (aggregated), payments | Avoid automated punishment without review |
| G11 | Segment builder and saved cohorts | P1 | Query builder over safe fields | Sync to PostHog cohorts |
| G12 | Refund/goodwill action | P1 | Dodo API + approval | Financial audit trail |

### H. Security, audit, and governance

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| H1 | Immutable admin audit log | P0 | `admin_audit_log` table | Actor, action, target, before/after, IP, request ID |
| H2 | Flag/entitlement change history | P0 | Audit log + diff view | Who changed what and when |
| H3 | Sensitive-action approvals | P1 | `admin_approvals` table | Refund, delete, impersonate, role change |
| H4 | Access review | P1 | Users, roles, 2FA, last login | Quarterly review |
| H5 | Consent analytics | P1 | Consent events + PostHog | Grant/deny/withdraw, replay coverage |
| H6 | Data retention controls | P1 | Retention jobs + policy | Show next run and affected records |
| H7 | Secret/provider credential health | P2 | Config metadata + last rotation | Never display secret values |
| H8 | Rate-limit/abuse dashboard | P2 | Gateway metrics | Top offenders, false-positive review |
| H9 | Legal hold/export | P2 | Case records | Legal-only access |

### I. Content, templates, and quality

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| I1 | Template catalog performance | P1 | Views, selections, compiles, exports | Rank by successful export |
| I2 | Template error and regression status | P1 | Compile errors + visual tests | Link to CI evidence |
| I3 | ATS keyword/industry coverage | P2 | ATS profiles + keyword data | Identify thin industries |
| I4 | Content library usage | P1 | Bullets, personas, macros, snippets | Adoption and quality |
| I5 | Academic CV/publication adoption | P2 | Academic feature events | Separate funnel |
| I6 | Linter rule frequency and fix rate | P1 | Linter events | Prioritize noisy rules |
| I7 | PDF accessibility/tagging status | P2 | Render metadata | Honest disclosure |
| I8 | Localization usage and errors | P2 | Locale cookie + events | Coverage gaps |

### J. Tenant and agency analytics

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| J1 | Tenant overview | P1 | Tenants + members + cohorts | Seats, activation, submissions |
| J2 | Cohort progress and recruiter engagement | P1 | Cohort submissions + comments | Time-to-review |
| J3 | Custom-domain health | P1 | DNS verification history | Expiry/certificate warnings |
| J4 | Branding adoption | P2 | Tenant settings | Logo/color/domain completion |
| J5 | Tenant billing/seat utilization | P1 | Subscriptions + seats | Upgrade prompts |
| J6 | Cross-tenant benchmark | P2 | Aggregated, opt-in | Minimum cohort size |

### K. Experimentation and feedback

| # | Feature | Priority | Data / implementation | Notes |
| --- | --- | --- | --- | --- |
| K1 | Feature flag exposure and impact | P1 | PostHog flags + first-party metrics | Guardrail metrics |
| K2 | A/B experiments | P1 | PostHog experiments | Pre-register success metric |
| K3 | In-app surveys/NPS/CSAT | P2 | PostHog surveys | Tie to plan/feature |
| K4 | Feedback inbox with replay links | P2 | Support + PostHog | Triage workflow |
| K5 | Changelog adoption | P2 | Updates page events | Feature announcement impact |
| K6 | Feature request voting | P2 | Public roadmap | Moderation |

### L. PostHog-native capabilities to expose

| # | Capability | Priority | How |
| --- | --- | --- | --- |
| L1 | Replay playlists by route/error/plan | P0 | PostHog saved filters; link from admin |
| L2 | Funnels, trends, paths, retention, stickiness | P1 | Saved insights; link or embed |
| L3 | Cohorts synced to feature flags | P1 | PostHog cohorts + flags |
| L4 | Error tracking and alerts | P1 | PostHog error tracking + Slack/email |
| L5 | Surveys and experiments | P2 | PostHog products |
| L6 | Notebooks for investigations | P2 | PostHog notebooks |
| L7 | HogQL queries from admin | P2 | Server-side proxy with a **personal** API key; never expose the key |
| L8 | Warehouse joins with Neon read replica | P2 | PostHog data warehouse | Join billing/entitlements safely |
| L9 | Embedded dashboards | P2 | PostHog sharing/embed with access control |
| L10 | CDP exports to support/email | P2 | PostHog destinations | PII review required |

## 4. Data and API work required

| Work | Why | Notes |
| --- | --- | --- |
| Extend `/analytics/admin/overview` with prior-period deltas | A1 | One payload, cached 60s |
| `/admin/analytics/timeseries` with dimension filters | C1–C3 | Plan, provider, feature, cohort |
| `/admin/users/{id}/360` | G1–G2 | Compose from existing tables; no document content |
| `/admin/billing/summary` and `/admin/billing/webhooks` | E1–E5 | Include dead-letter replay action |
| `/admin/operations/health` | F1–F6 | Aggregate existing probes; no secrets |
| `/admin/audit` | H1–H2 | Append-only, indexed by actor/target/time |
| `/admin/alerts` | A2–A3 | Acknowledge/snooze with audit |
| `/admin/exports` | A6 | Streaming CSV, signed download |
| Materialized daily metrics view | Performance | Refresh every 5–15 min |
| PostHog server-side proxy | L7 | Personal API key only in backend secret |
| Saved views/segments tables | A5/G11 | Per-admin + shared |
| Alert evaluator (cron) | A3/F1/E4 | Deduplicate and throttle |
| Audit middleware/helper | H1 | Use for every mutating admin route |

## 5. Delivery phases

### Phase 0 — done in this change

- PostHog project, consent banner, masked replay, editor/share/portfolio blocks.
- Backend mirror + explicit billing/job/admin lifecycle events.
- Admin **Analytics** tab with KPIs, funnel, timeseries, features, events, ops.
- Privacy policy, accessibility statement, CI guard, tests, operating guide.

### Phase 1 — operational control (1–2 weeks)

1. Billing/webhook admin: dead-letter list, replay, reconciliation, refund request.
2. User 360 + safe support actions (entitlement, trial, quota, sessions, resend).
3. Immutable admin audit log + change history.
4. “Needs attention” queue and alert strip.
5. Job queue actions (retry/cancel/fence) with confirmation.
6. Prior-period deltas and CSV export.

**Exit criteria:** a failed payment/webhook or stuck job is visible and
actionable in under five minutes; every mutating action is audited.

### Phase 2 — growth and quality (3–4 weeks)

1. Activation/retention cohorts and path analysis.
2. AI cost/margin dashboard with spend alerts.
3. Template/content/linter quality dashboards.
4. Integration adoption/failure dashboards.
5. Tenant analytics and domain health.
6. PostHog saved insights, replay playlists, and error tracking links.
7. Segment builder + PostHog cohort sync.

**Exit criteria:** every major feature has an adoption view; AI gross margin is
visible by plan; template and compile regressions are attributable.

### Phase 3 — optimization and scale (5–8 weeks)

1. Experiments and surveys with guardrail metrics.
2. HogQL proxy and embedded PostHog dashboards.
3. Warehouse joins with a Neon read replica.
4. Scheduled digests, anomaly detection, incident timeline.
5. Access reviews, approvals, GDPR workflow automation.
6. Cross-tenant benchmarks (opt-in, aggregated).

**Exit criteria:** weekly operating review can run from the admin dashboard
without ad-hoc SQL; alerts fire before users report incidents.

## 6. Privacy and security constraints

- Never send résumé/LaTeX content, prompts, job descriptions, emails, names,
  tokens, or payment credentials to PostHog.
- Session replay stays consent-based, fully masked, and blocked on document
  surfaces. Do not add a “disable masking for this user” switch.
- Aggregate small cohorts before display (suggested minimum 5 users) to avoid
  re-identification.
- PII reveal, impersonation, refunds, deletions, and role changes require an
  audit record with actor, reason, and request ID.
- The PostHog **personal** API key (if added for HogQL) belongs in the backend
  secret only; the browser gets the public project token.
- Support and admin roles must not be treated as equivalent. Least privilege is
  the default; the current matrix already separates account roles.
- Admin analytics must fail closed: if PostHog is unavailable, the first-party
  KPI cards still load from Postgres.

## 7. Success metrics for the dashboard itself

| Metric | Target |
| --- | --- |
| Time to detect a payment/webhook failure | < 5 minutes |
| Time to answer “why did signups/compiles drop?” | < 10 minutes |
| Features with an adoption view | 100% of shipped features |
| Admin mutations with audit coverage | 100% |
| Consented sessions with replay coverage | > 95% |
| Replay captures on document surfaces | 0 |
| Dashboards loading from cache | p95 < 1.5 s |
| Weekly operating review run from admin only | Yes |

## 8. Immediate next three builds

1. **Billing & webhook control room** — highest operational risk after the live
   payment incident; includes dead-letter replay and reconciliation.
2. **User 360 + audited support actions** — removes the need for manual DB
   queries and makes support safe.
3. **Activation/retention cohorts + AI cost** — tells the owner whether the
   product is being used well and whether AI usage is profitable.

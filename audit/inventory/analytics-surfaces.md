# Admin analytics surfaces, event inventory and #2186 reconciliation

Audit: Latexy production audit, 2026-11-27. Scope: analytics events, admin analytics surfaces, roadmap reconciliation. Read-only.

Source of truth for code: current checkout at `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (main); `git diff d2cbc51 -- backend frontend` is empty on this audit branch. Live backend: `https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run`. Live frontend identity: `https://latexy.xyz/api/deployment-identity` returned `d2cbc51ab8c25106d073e0e0065b985fc6dc6490` (`source: vercel`).

Companion machine-readable inventory: `audit/inventory/analytics.csv` (104 data rows).

Status legend for the roadmap table:

- **IMPLEMENTED** - route/component/service exists at this checkout, and the live route answers 401 (present; authentication required). Data correctness is not implied.
- **PARTIAL** - a subset exists; the named gap remains.
- **PLANNED** - no implementation found in this checkout.
- **BLOCKED** - external dependency prevents implementation.

## 1. Executive summary

| Measure | Count | Notes |
|---|---:|---|
| PostHog event names in the taxonomy | 47 | 37 emitted, 10 declared but never emitted |
| - Browser-emitted events | 18 | `$pageview`, autocapture, exception/frustration, product and billing events |
| - Explicit server events | 11 | `backend_job_submitted`, billing lifecycle, five admin mutations |
| - Live mirrored `backend_<event_type>` events | 8 | Only 8 of the 17 allowlisted mirror names have a writer |
| - Declared but never emitted | 10 | `product_event` + 9 allowlisted mirror names |
| Disabled PostHog name | 1 | `$pageleave` (`capture_pageleave: false`) |
| `usage_analytics` action values | 49 | Plus 4 `signup_funnel_events`, 1 `resume_views` write, 1 error-group signal |
| `usage_analytics` actions mirrored to PostHog | 8 | 41 of 49 action families are first-party only |
| Admin top-level tabs | 22 | `frontend/src/app/admin/page.tsx:83-106`; support role sees only Customers |
| Admin components | 68 | `frontend/src/components/admin/*.tsx` |
| Admin route modules | 50 | `backend/app/api/admin_*_routes.py` |
| Admin-prefixed services | 41 | `backend/app/services/admin_*.py` |
| Auxiliary analytics/tenant route modules | 9 | analytics, consent, onboarding, signup, traffic, landing, trial, tenant, tenant-billing |
| Admin HTTP operations | 218 | 110 GET; includes aliases |
| Dashboard-oriented admin GET reads | 93 | Of 110 total admin GET operations; excludes auxiliary analytics/tenant modules |
| Dashboard surfaces inventoried | 84 | Section 3 |
| #2186 roadmap items | 130 | 100 implemented, 7 partial, 22 planned, 1 blocked |
| #2186 P0 status | 44 | 44 implemented |
| #2186 P1 status | 56 | 55 implemented, 1 partial (X9) |
| #2186 P2 status | 30 | 1 implemented, 6 partial, 22 planned, 1 blocked |

Top-line verdict: the control plane is broad and the P0 build-out is complete in source and 55/56 P1 items are present. The analytics layer is **not yet launch-trustworthy** because production KPIs include every synthetic account, revenue figures use three different refund-date policies, the headline "trial conversion" is actually new-users/trial-devices, and PostHog person `plan` is always `unknown`. PostHog is a link-out/exploration layer, not a reconciled second source: 41 of 49 first-party action families never reach it, and 10 of 47 PostHog names are dead.

## 2. Live verification (read-only)

Captured 2026-11-27. No mutations, no accounts created, no PostHog API calls.

| Probe | Observed | Verdict |
|---|---|---|
| `GET /health` | 200 | healthy |
| `GET /readyz` | 200 | ready |
| `GET /jobs/health` | 200 | healthy |
| `GET /openapi.json` | 404 | schema endpoint disabled (F-001) |
| `GET /analytics/admin/overview?days=30` | 401 | route present |
| `GET /admin/analytics/daily-metrics?days=30` | 401 | route present |
| `GET /admin/analytics/activity` | 401 | route present |
| `GET /admin/alerts` | 401 | route present |
| `GET /admin/operations/queues` | 401 | route present |
| `GET /admin/analytics/editor-modes` | 401 | route present |
| 21 additional admin analytics/read routes | 401 each | all sampled routes present |
| Live schema endpoint (any path) | 404 | no live schema |
| PostHog project configuration | not verified | no personal API key in this sub-agent; project `756020` documented in `docs/POSTHOG.md` |

All 27 sampled admin analytics/operations routes returned 401, so the route surface exists at the deployed SHA. This does **not** prove data correctness; no authenticated admin session was available.

## 3. Every admin dashboard surface and its source table

Information architecture: the admin shell has 22 top-level tabs (`frontend/src/app/admin/page.tsx:83-106`), a 68-component component library, and a separate tenant-owner dashboard at `/admin/tenant`. The Support role is restricted to the Customers tab (`page.tsx:108-110,950`).

### 3.1 Tab-to-component map

| Tab | Label | Components rendered | Primary source |
|---|---|---|---|
| `analytics` | Analytics | `AdminAnalytics`, `AdminAtsScoreDistribution`, `AdminDocumentComplexity`; nested `AdminActivityFeed`, `AdminAiLatencyRetry`, `AdminCompileErrors`, `AdminCompileLatency`, `AdminConsentAnalytics`, `AdminOperations`, `AdminPathAnalysis`, `AdminPostHogInsights` | `usage_analytics`, billing/compile tables, PostHog links |
| `operations` | Operations | `AdminIncidentTimeline`, `AdminArtifactLifecycle`, `AdminRetentionControls` | incidents, artifact manifests, retention tables |
| `product` | Product | `AdminCollaboration`, `AdminCareerAdoption`, `AdminIntegrations`, `AdminProduct` (contains `AdminEditorModeUsage`) | collaboration, career, integration, editor telemetry |
| `replays` | Replays | `AdminReplayBrowser` | PostHog |
| `quality` | Quality | `AdminQualityTriage`, `AdminErrorFeed`, `AdminTemplateHealth`, `AdminTemplatePerformance`, `AdminContentLibraryQuality`, `AdminOptimizationAcceptance`, `AdminLinterRules` | PostHog + error groups + template/optimization/linter tables |
| `billing` | Revenue | `AdminBilling` (contains `AdminCheckoutFunnel`, `AdminRevenueBreakdown`, `AdminCouponStudentPerformance`, `AdminPlanHealth`, `AdminTeamSeatUtilization`) | payments, refunds, subscriptions, webhooks |
| `subscriptions` | Subscriptions | `AdminSubscriptions`, `AdminDunningRecovery` | subscriptions, history, dunning history |
| `receipts` | Receipts | `AdminReceiptLookup` | payments, subscriptions, users |
| `email` | Email Health | `AdminEmailHealth` | email delivery events/suppressions |
| `exports` | Exports | `AdminExports` | audit log + report source tables |
| `growth` | Growth & Cost | `AdminGrowth` (contains `AdminCredentialMix`, `AdminLandingConversion`, `AdminOnboardingAnalytics`, `AdminPrivacyBreakdowns`, `AdminReferralAnalytics`, `AdminSharePortfolio`, `AdminTrafficSources`, `AdminTrialAttribution`, `AdminTrialHealth`) | product, billing, auth, referral, trial tables |
| `customers` | Customers | `UsersTab`, `AdminUserDetail` (contains `AdminUserNotes`, `AdminSupportActions`) | users and every user-linked table |
| `audit` | Audit | `AdminAudit`, `AdminChangeHistory` | `admin_audit_log` |
| `access` | Access Review | `AdminAccessReview` | users, audit log |
| `abuse` | Abuse | `AdminAbuseQueue` | abuse items, trials, payments, coupons, referrals |
| `approvals` | Approvals | `AdminApprovals` | `admin_approvals`, audit log |
| `privacy` | Privacy | `AdminGdpr` | GDPR requests/events/holds |
| `flags` | Feature Flags | `FeatureFlagsTab`, `AdminFlagExposure`, `AdminCohorts` | feature flags, exposures, cohorts |
| `experiments` | Experiments | `AdminExperiments` | experiment registry/assignments/exposures |
| `matrix` | Features x Plans & Roles | `MatrixTab` | flags, plan/role grants, subscriptions, seats |
| `plans` | Plan Catalog | `AdminPlanCatalog` | plan catalog/features |
| `views` | Saved Views | `AdminSavedViews` | saved views, segments |
| global | View as / Job Queue | `AdminViewAs`, `JobQueue` | view-as sessions, Redis job state |

### 3.2 Surface inventory (endpoint, source table, cache)

| Surface | Component | Endpoint | Source tables | Cache/refresh | Reconciliation risk |
|---|---|---|---|---|---|
| Analytics / Executive KPI header | AdminAnalytics | GET /analytics/admin/overview | users; subscriptions; payments; payment_refunds; compilations; optimizations; device_trials; usage_analytics; admin_daily_metrics | 60s in-process + Redis | No test-cohort exclusion; refund attribution differs from Revenue tab |
| Analytics / Conversion funnel | AdminAnalytics | GET /analytics/admin/overview | usage_analytics (page_view); device_trials; users; subscriptions; signup_funnel_events | 60s | Period ratios, not cohorts; first-party page_view is not consent-gated |
| Analytics / Daily series | AdminAnalytics | GET /analytics/admin/overview -> admin_daily_series | admin_daily_metrics or base tables | 10m rollup; 30m stale fallback | INR-only; active_users excludes anonymous; rollup refresh is not scheduled in production (AS-18) |
| Analytics / Top features | AdminAnalytics | GET /analytics/admin/overview -> get_admin_top_features | usage_analytics | 60s | Coalesces metadata.feature with action, so page_view/compile rank as features |
| Analytics / Recent product events | AdminAnalytics | GET /analytics/admin/overview -> get_admin_recent_events | usage_analytics | 60s | Arbitrary client event names; no test filter |
| Analytics / Live activity feed | AdminActivityFeed | GET /admin/analytics/activity | users; payments; compilations; optimizations; admin_error_groups; usage_analytics fallback | cursor pagination | Falls back to event-name-only rows when a live source is unavailable |
| Analytics / AI latency and retry | AdminAiLatencyRetry | GET /admin/analytics/ai-latency-retry | llm_call_attempts | request-time | Rows without provider/model land in missing attribution buckets |
| Analytics / Compile error taxonomy | AdminCompileErrors | GET /admin/analytics/compile-errors | compilations; resume_templates | request-time | No durable error rollup; reads compilations directly |
| Analytics / Compile latency | AdminCompileLatency | GET /admin/analytics/compile-latency | compilations | request-time | Percentiles only for rows with recorded latency |
| Analytics / Consent and replay coverage | AdminConsentAnalytics | GET /admin/analytics/consent | usage_analytics (consent_* actions) | request-time | Only rows written after consent event support existed |
| Analytics / Operations strip | AdminOperations | GET /admin/operations/attention; /health; /queues; /alerts; /stuck-jobs | admin_alerts; admin_incidents; billing_webhook_events; compilations; job_finalizations; payments; subscriptions; tenants; celery_queue_snapshots | 45s health cache | Probe failures and fallbacks can make counters disagree with source tables |
| Analytics / Path analysis | AdminPathAnalysis | GET /admin/analytics/paths | usage_analytics; subscription_history; users | request-time | Only routes emitted by LandingPageviewTracker; public document paths excluded |
| Analytics / PostHog saved insights | AdminPostHogInsights | none (URL builder only) | PostHog (external) | n/a | No API read; cannot reconcile counts from admin |
| Analytics / ATS score distribution | AdminAtsScoreDistribution | GET /admin/analytics/ats-score-distribution | optimizations; users | request-time | Only runs with a post-optimization score; missing baseline counted separately |
| Analytics / Document complexity | AdminDocumentComplexity | GET /admin/analytics/document-complexity | compilations; resume_templates | request-time | Unknown class bucket absorbs unmatched rows |
| Operations / Incident timeline | AdminIncidentTimeline | GET /admin/operations/incidents | admin_incidents; admin_alerts | request-time | Manual incidents only; no automatic provider incident ingestion |
| Operations / PDF artifact lifecycle | AdminArtifactLifecycle | GET /admin/operations/artifacts/lifecycle | compilations; job_finalizations; render_artifact_manifests; usage_analytics; gdpr_legal_holds | request-time | GC telemetry only exists after the instrumentation release |
| Operations / Data retention | AdminRetentionControls | GET/PATCH/POST /admin/operations/retention | retention_policies; retention_policy_revisions; retention_runs; usage_analytics; render_artifact_manifests; job_finalizations; gdpr_* | request-time | Dry-run/purge are audited; retention exceptions require legal-hold state |
| Analytics / Worker and container health | AdminOperationsHealth | GET /admin/operations/health | admin_operations probes; Redis/DB/cache; Modal/provider links | 45s health cache | Probe failures and provider links only; no provider status feed |
| Analytics / Stuck jobs | AdminStuckJobs | GET/POST /admin/operations/stuck-jobs | compilations; job_finalizations; resumes; users; admin_audit_log | request-time | Safe actions are audited; a fence does not guarantee the worker stops |
| Product / Collaboration | AdminCollaboration | GET /admin/analytics/collaboration | resumes; resume_comments; resume_comment_mentions; resume_review_comments; resume_views; tenants; tenant_members; workspaces; workspace_members; workspace_resumes | request-time | View debounce and <5 suppression; tenant totals aggregate small cohorts |
| Product / Career adoption | AdminCareerAdoption | GET /admin/analytics/career-adoption | career_analyses; cover_letters; interview_prep; optimizations; subscriptions; usage_analytics; users | request-time | Accepts legacy event aliases; small cohorts suppressed |
| Product / Integrations | AdminIntegrations | GET /admin/analytics/integrations | resumes; usage_analytics; users | request-time | No provider API read; reconciles against local connection tables |
| Product / Feature adoption matrix | AdminProduct | GET /admin/analytics/feature-adoption | subscriptions; usage_analytics; users | request-time | Feature keys are client-supplied and not allowlisted |
| Product / Editor modes | AdminEditorModeUsage | GET /admin/analytics/editor-modes | compilations; usage_analytics; users | request-time | Mode attribution uses 12h document-hash lookback; unknown bucket |
| Replays / Session replay browser | AdminReplayBrowser | none (PostHog URL builder) | PostHog (external) | n/a | No DB count; consent and masking are the only controls |
| Quality / Quality triage | AdminQualityTriage | none (PostHog URL builder) | PostHog (external) | n/a | Separate pipeline from AdminErrorFeed; counts cannot be reconciled |
| Quality / Error feed | AdminErrorFeed | GET /admin/analytics/errors | admin_error_groups | request-time | Frontend signals are consent-gated; backend groups are separate |
| Quality / Template health | AdminTemplateHealth | GET /admin/templates/health; POST /admin/templates/{id}/health/retry | compilations; resume_templates; template_health_checks | request-time | Health checks are CI/manual; not a per-compile signal |
| Quality / Template performance | AdminTemplatePerformance | GET /admin/templates/performance | compilations; resume_templates; usage_analytics | request-time | Aggregates template_view/select/use/export/compile |
| Quality / Content library adoption | AdminContentLibraryQuality | GET /admin/content-library/adoption | snippets; snippet_installs; snippet_upvotes; usage_analytics; user_macros | request-time | Deletes leave aggregate tombstones only; no body text |
| Quality / Optimization acceptance | AdminOptimizationAcceptance | GET /admin/analytics/optimization-acceptance | resumes; resume_optimization_runs; resume_suggestion_decisions; users | request-time | Requires explicit shown/decided denominators |
| Quality / Linter rules | AdminLinterRules | GET /admin/linter/rules | usage_analytics (linter_issue) | request-time | Client-side rolling dedupe influences counts |
| Revenue / Billing control room | AdminBilling | GET /admin/billing/summary; /webhooks; /reconciliation; /refunds | payments; payment_refunds; subscriptions; subscription_history; billing_webhook_events; admin_refund_requests; admin_audit_log | request-time | Refund date policy differs from Analytics; single-currency summary |
| Revenue / Checkout funnel | AdminCheckoutFunnel | GET /admin/billing/checkout-funnel | subscriptions; payments; billing_webhook_events | request-time | Provider failures are bucketed; no PostHog join |
| Revenue / Revenue breakdown | AdminRevenueBreakdown | GET /admin/billing/summary | payments; payment_refunds; subscriptions | request-time | Currency filter only; no country/method view |
| Revenue / Coupon and student performance | AdminCouponStudentPerformance | GET /admin/revenue/coupon-student-performance | coupon_codes; coupon_redemptions; payments; subscriptions; usage_analytics | request-time | Abuse flags are advisory only |
| Revenue / Weekly and lifetime plan health | AdminPlanHealth | GET /admin/analytics/plan-health | payments; payment_refunds; subscriptions; subscription_history | request-time | Advisory risk flags; no automatic action |
| Revenue / Team seat utilization | AdminTeamSeatUtilization | GET /admin/analytics/team-seats | subscriptions; team_seats; tenants; tenant_members; users | request-time | Small tenant/seat groups suppressed |
| Subscriptions / Subscription analytics | AdminSubscriptions | GET /admin/subscriptions/analytics | subscriptions; subscription_history; users | request-time | History starts at 0084; earlier plan movement unavailable |
| Subscriptions / Dunning recovery | AdminDunningRecovery | GET /admin/billing/dunning-recovery | subscriptions; subscription_status_history; users | request-time | History starts at 0091; provider ordering is opaque |
| Receipts / Invoice and receipt lookup | AdminReceiptLookup | GET /admin/receipts/search; GET /admin/users/{id}/payments/{payment}/receipt | payments; subscriptions; users | request-time | Resend is audited and cooldown-limited; no invoice table |
| Email Health / Delivery health | AdminEmailHealth | GET /admin/email/health | document_email_deliveries; email_delivery_events; email_recipient_suppressions | request-time | Resend webhook only; unsigned requests fail closed |
| Exports / CSV, PDF and digest | AdminExports | GET/POST /admin/exports; /stream; /download; /digest; /history | admin_audit_log; users; compilations; optimizations; payments; subscriptions; resumes | request-time | 10k CSV / 2k PDF caps; digest state is audit-event sourced |
| Growth / Activation funnel | AdminGrowth | GET /admin/analytics/activation | users; account (Better Auth); resumes; compilations; usage_analytics; optimizations; payments; signup_funnel_events | request-time | Cohort window and provider join; all accounts included |
| Growth / Signup funnel by provider | AdminGrowth (SignupFunnel) | activation.signup_funnel | signup_funnel_events; account; users | request-time | Provider is derived from Better Auth; unknown bucket |
| Growth / Retention cohorts | AdminGrowth | GET /admin/analytics/retention | users; usage_analytics; compilations; optimizations; resumes | request-time | Activity definition differs from Analytics active_users |
| Growth / Dimension-filtered timeseries | AdminGrowth | GET /admin/analytics/timeseries | users; compilations; optimizations; payments; usage_analytics; account | service cache | Plan/provider/feature/signup-cohort filters; anonymous events excluded |
| Growth / Feature depth and frequency | AdminGrowth | GET /admin/analytics/feature-depth | usage_analytics; users | request-time | Client feature labels; small groups suppressed |
| Growth / AI usage breakdown | AdminGrowth | GET /admin/analytics/ai-usage | optimizations; resume_optimization_runs; resume_optimization_stages; users | request-time | Runs by feature/provider/model/persona; no invoice join |
| Growth / AI cost and margin | AdminGrowth | GET /admin/analytics/ai-cost | optimizations; resume_optimization_runs; resume_optimization_stages; payments; payment_refunds; users; resumes | request-time | Estimated provider prices; USD cost vs INR revenue; unpriced fallback |
| Growth / BYOK vs platform-key mix | AdminCredentialMix | GET /admin/analytics/credential-mix | users; user_api_keys; optimizations; resume_optimization_runs; resume_optimization_stages | request-time | Credential ownership from local key rows |
| Growth / Traffic sources | AdminTrafficSources | GET /admin/analytics/traffic-sources | usage_analytics (traffic_landing/signup); payments; users | request-time | First-touch attribution; small cells suppressed |
| Growth / Landing conversion | AdminLandingConversion | GET /admin/analytics/landing-conversion | usage_analytics; device_trials; subscriptions; users | request-time | Consent basis differs from PostHog |
| Growth / Onboarding drop-off | AdminOnboardingAnalytics | GET /admin/analytics/onboarding | usage_analytics (onboarding_*); users | request-time | Rejects events without a granted consent decision |
| Growth / Privacy-safe breakdowns | AdminPrivacyBreakdowns | GET /admin/analytics/privacy-breakdowns | usage_analytics; users | request-time | Server-derived country; <5 suppression |
| Growth / Referral analytics | AdminReferralAnalytics | GET /admin/referrals/summary | payments; referral_attributions; referral_rewards; subscriptions; users | request-time | Payout and fraud flags are advisory |
| Growth / Share and portfolio performance | AdminSharePortfolio | GET /admin/analytics/share-portfolio | resumes; resume_views; usage_analytics; users | request-time | 5-minute view debounce; 30-day signup claim window |
| Growth / Trial-to-paid cohorts | AdminTrialAttribution | GET /admin/analytics/trial-attribution | device_trials; trial_attributions; subscriptions; usage_analytics; users | request-time | Attribution source; small cohorts suppressed |
| Growth / Trial health and abuse | AdminTrialHealth | GET /admin/analytics/trial-health | device_trials; deep_analysis_trials; trial_attributions | request-time | Aggregate signals only; no raw fingerprints |
| Customers / User search | UsersTab | GET /admin/users | users; subscriptions | 300ms debounce | Masked-by-default projection; audited single-field reveal |
| Customers / User 360 | AdminUserDetail | GET /admin/users/{id}/360 | users; resumes; compilations; optimizations; usage_analytics; payments; payment_refunds; subscriptions; subscription_history; user_api_keys; developer_api_keys; device_trials; tenant_members; referral_attributions; admin_user_notes; admin_user_tags; admin_view_as_sessions | 60s masked cache | Counts can lag; revealed PII overlaid live and audited |
| Customers / Notes, tags and support timeline | AdminUserNotes | GET/POST/PATCH/DELETE /admin/users/{id}/notes, /tags, /support-timeline | admin_user_notes; admin_user_tags; admin_approvals; admin_audit_log; admin_refund_requests; gdpr_legal_holds; payments; payment_refunds; subscription_history; users | request-time | Internal only; reason required for mutations |
| Customers / Support email actions | AdminSupportActions | POST /admin/users/{id}/support/resend-verification; /password-reset; /resend-receipt | payments; subscriptions; users; admin_audit_log | request-time | Rate-limited/cooldown; provider failures surfaced honestly |
| Audit / Admin audit log | AdminAudit | GET /admin/audit | admin_audit_log | cursor pagination | Append-only trigger; no DB-role isolation |
| Audit / Change history | AdminChangeHistory | GET /admin/change-history | admin_audit_log; feature_flags; plan_features; role_features | request-time | Diff derived from audit rows |
| Access Review / Quarterly access review | AdminAccessReview | GET /admin/access-review; POST /attest | users; admin_audit_log | request-time | Attestation is recorded but no scheduled reminder |
| Abuse / Abuse review queue | AdminAbuseQueue | GET /admin/abuse/queue; POST /scan, /assign, /decision | abuse_review_items; device_trials; payments; coupon_redemptions; referral_attributions; usage_analytics; users | request-time | Advisory only; no automated punishment |
| Approvals / Two-person approvals | AdminApprovals | GET/POST /admin/approvals | admin_approvals; users; admin_audit_log | request-time | Dual-control for sensitive actions |
| Privacy / GDPR and legal holds | AdminGdpr | GET/POST /admin/gdpr/* | gdpr_requests; gdpr_request_events; gdpr_legal_holds; users; admin_audit_log | request-time | Legal hold blocks deletion; legal sign-off recorded |
| Feature Flags / Operational flags | FeatureFlagsTab | GET/PATCH /admin/feature-flags | feature_flags; admin_audit_log | request-time | Reason required; six operational flags only |
| Feature Flags / Flag exposure | AdminFlagExposure | GET /admin/analytics/flag-exposure | feature_flags; usage_analytics; compilations; optimizations; payments; resumes; subscriptions | request-time | Exposure only with consent; outcomes are guardrails |
| Feature Flags / PostHog cohort sync | AdminCohorts | GET/POST /admin/cohorts; POST /{id}/sync | feature_cohorts; feature_cohort_members; feature_cohort_flag_mappings; feature_flags; usage_analytics; users; tenants; tenant_members | request-time | Snapshot ingestion only; no PostHog API connector |
| Experiments / A/B registry and results | AdminExperiments | GET/POST /admin/experiments | admin_experiments; admin_experiment_assignments; admin_experiment_exposures; feature_flags | request-time | Preregistered metrics; <5 suppression |
| Features x Plans & Roles / Capability matrix | MatrixTab | GET /admin/entitlements; PATCH kill-switch/matrix/roles | feature_flags; plan_features; role_features; subscriptions; team_seats; users; admin_audit_log | request-time | Effective access requires every ancestor; reason required |
| Plan Catalog / Plans and quotas | AdminPlanCatalog | GET/PATCH /admin/plan-catalog | plan_catalog; plan_features | request-time | Quota edits audited; no price-history table |
| Saved Views / Saved views and segments | AdminSavedViews | GET/POST/PATCH/DELETE /admin/saved-views; /admin/segments | admin_saved_views; admin_segments; users; tenants; tenant_members; usage_analytics; admin_audit_log | request-time | Per-admin/shared; segment previews are bounded |
| Global / View as user | AdminViewAs | POST /admin/view-as/requests; /sessions; /sessions/{id}/end | admin_view_as_sessions; users; resumes; subscriptions; usage_analytics; admin_audit_log | request-time | Read-only, time-boxed, audited; no impersonation token |
| Global / Job queue | JobQueue | GET job routes + /ws/jobs | Redis job state; job_finalizations; compilations | live | Not an analytics KPI; queue state can differ from DB status |
| Tenant Admin / Overview | TenantOverviewAnalytics | GET /tenants/{id}/stats | tenants; tenant_members; workspaces; workspace_members; workspace_resumes; resumes; usage_analytics | request-time | Aggregates small cohorts; pending invites from Redis can degrade to unavailable |
| Tenant Admin / Cohort progress | TenantCohortProgress | GET /tenants/{id}/cohorts/{id}/engagement | workspace_resumes; recruiter_notes; resume_comments; workspaces; workspace_members | request-time | <5 members/submissions suppressed; no comment text |
| Tenant Admin / Billing and seats | TenantBillingPanel | GET /tenants/{id}/billing; POST upgrade-intent | subscriptions; team_seats; tenants; tenant_members; usage_analytics | request-time | Seat utilization; upgrade intent is a usage_analytics row |
| Tenant Admin / Domain health | tenant page | GET /tenants/{id}/domain/health; POST /domain/verify | tenants (domain/certificate fields) | request-time | Expiry metadata only from 0079; DNS/cert checks are point-in-time |
| Tenant Admin / Branding and members | tenant page | PATCH /tenants/{id}; GET/POST/DELETE /members | tenants; tenant_members | request-time | Branding adoption is settings-only, not an analytics view |


## 4. Core analytics endpoints (not admin-tab-specific)

| Endpoint | Auth | Reads/writes | Consumer |
|---|---|---|---|
| `POST /analytics/track` | optional user | writes arbitrary `usage_analytics.action` | top features, recent events, feature depth |
| `POST /analytics/track/compilation` | optional user | writes `compile` (terminal rows idempotent) | KPIs, top features, template performance |
| `POST /analytics/track/optimization` | optional user | writes `optimize` | KPIs, AI usage/cost |
| `POST /analytics/track/page-view` | optional user | writes `page_view` | landing conversion, path analysis, retention, tenant overview |
| `POST /analytics/track/feature-usage` | optional user | writes `feature_usage` | feature adoption, top features, feature depth |
| `GET /analytics/me` | user + `analytics` feature | reads compilations/optimizations/usage | user-facing analytics |
| `GET /analytics/me/timeseries` | user + `analytics` feature | reads compilations/optimizations/usage | user-facing analytics |
| `GET /analytics/user/{user_id}` | admin | same | User 360/analytics drill-down |
| `GET /analytics/system` | admin | users/subscriptions/payments/compilations/optimizations/trials | Analytics KPI header |
| `GET /analytics/conversion-funnel` | admin | page_view, trials, users, subscriptions, signup events | Analytics funnel |
| `GET /analytics/admin/overview` | admin | all of the above + daily rollup + ops | Analytics tab |
| `GET /analytics/dashboard` | admin | system + funnel | legacy dashboard |
| `POST /analytics/consent` | anonymous | writes consent_* | Privacy tab |
| `POST /analytics/onboarding/events` | user | writes onboarding_* | Growth onboarding |
| `POST /analytics/signup/started`, `/oauth-failure`, `/milestones` | anonymous/user | writes `signup_funnel_events` | Growth signup funnel |
| `POST /analytics/traffic/landing`, `/claim` | anonymous/user | writes traffic_landing/signup | Growth traffic sources |
| `POST /analytics/cohorts/evaluate` | user | writes cohort_flag_exposed | Flags exposure |
| `POST /analytics/flag-exposure` | user | writes flag_exposed | Flags exposure |
| `POST /templates/{id}/events` | user | writes template_view/select | Template performance |
| `POST /portfolio/{username}/analytics/view`, `/contact`, `/claim-signup` | anonymous/user | writes portfolio_view/contact/signup | Share/portfolio |
| `POST /telemetry/errors` (frontend beacon) | anonymous | writes `admin_error_groups` | Error feed |

## 5. Event pipeline and parity model

### 5.1 Paths

1. **Browser PostHog path** - consent-gated (`readAnalyticsConsent() === 'granted'`) -> `captureAnalyticsEvent` / `capturePageview` -> PostHog US Cloud. No server round-trip for product events except the separate first-party call.
2. **First-party DB path** - API routes/services -> `usage_analytics`, `signup_funnel_events`, or `resume_views`.
3. **Server mirror** - `AnalyticsService.track_event` calls `posthog_service.capture_event`; only 17 allowlisted event types, of which 8 have a writer. Explicit lifecycle and admin events call `posthog_service.capture` directly.
4. **Admin read path** - all KPI/funnel/activity surfaces read Postgres (or the `admin_daily_metrics` rollup). PostHog is used only for link-outs (saved insights, replays, quality triage) and is never read through an API.

### 5.2 PostHog taxonomy and dead names

- **Browser emitted (18):** `$pageview`, `$autocapture`, `$exception`, `$rageclick`, `$dead_click`, `consent_granted`, `compilation_tracked`, `optimization_tracked`, `feature_used`, `checkout_started`, `checkout_failed`, `subscription_cancel_requested`, `export_completed`, `export_failed`, `cover_letter_generated`, `share_link_created`, `portfolio_generated`, `template_event`.
- **Server explicit (11):** `backend_job_submitted`, `backend_checkout_created`, `backend_checkout_failed`, `backend_payment_succeeded`, `backend_subscription_status_changed`, `backend_refund_status_changed`, `backend_admin_flag_changed`, `backend_admin_kill_switch_changed`, `backend_admin_entitlement_changed`, `backend_admin_role_matrix_changed`, `backend_admin_user_role_changed`.
- **Live mirrored (8):** `backend_page_view`, `backend_feature_usage`, `backend_compile`, `backend_optimize`, `backend_resume_created`, `backend_resume_forked`, `backend_academic_cv_converted`, `backend_export`.
- **Declared but never emitted (10):**
  - `product_event` - `apiClient.trackEvent` calls it, but no caller invokes `trackEvent`.
  - `backend_signup`, `backend_login`, `backend_share_viewed`, `backend_checkout_started`, `backend_upgrade_clicked`, `backend_ats_score`, `backend_cover_letter`, `backend_interview_prep`, `backend_error` - allowlisted in `posthog_service.py:71-91`, no first-party writer.
- **Disabled by design:** `$pageleave` (`capture_pageleave: false`, because the SDK builds it from the raw URL).

### 5.3 `usage_analytics` action families (49)

| Family | Actions | Writers | Admin consumers |
|---|---|---|---|
| Navigation and core product | `page_view`, `feature_usage`, `compile`, `optimize`, `export` | `analytics_routes.py`, `analytics_service.py`, `export_routes.py` | Analytics, Growth, Product, Template performance |
| Resume milestones | `resume_created`, `resume_forked`, `academic_cv_converted` | `resume_routes.py` | Growth activation, Activity feed |
| Templates | `template_view`, `template_select`, `template_use` | `template_analytics_service.py` | Template performance/health |
| Acquisition | `traffic_landing`, `traffic_signup` | `traffic_source_service.py` | Growth traffic/landing |
| Consent | `consent_granted`, `consent_denied`, `consent_withdrawn` | `consent_analytics_service.py` | Privacy consent |
| Onboarding | `onboarding_step_viewed`, `onboarding_step_completed`, `onboarding_step_skipped` | `onboarding_analytics_service.py` | Growth onboarding |
| Flags | `flag_exposed`, `cohort_flag_exposed` | `flag_exposure_service.py`, `cohort_sync_service.py` | Flags, experiments |
| Editor | `editor_mode_selected`, `auto_compile_toggled`, `synctex_used` | `editor_mode_analytics_service.py` | Product editor modes |
| Integrations | `connect_started`, `connected`, `disconnected`, `sync_succeeded`, `sync_failed` | `integration_analytics_service.py` | Product integrations |
| Portfolio | `portfolio_view`, `portfolio_contact`, `portfolio_signup` | `share_portfolio_analytics_service.py` | Growth share/portfolio |
| Content library | `snippet_insert`, `snippet_delete`, `macro_use` | `content_library_events.py` | Quality content library |
| Linter | `linter_issue` | `linter_telemetry_service.py` | Quality linter rules |
| Coupon/student | `coupon_reserved`, `coupon_redeemed`, `coupon_released`, `student_verification_requested`, `student_verification_verified`, `student_verification_paid`, `student_verification_failed` | `coupon_student_analytics_service.py` | Revenue coupon/student |
| Career | `cover_letter_generated`, `interview_prep_generated`, `career_analysis_generated` | `career_feature_events.py` | Product career adoption |
| Artifact GC | `render_artifact_gc.sweep`, `render_artifact_gc.manual_cleanup` | `render_engine/retention.py`, `artifact_lifecycle_service.py` | Operations artifact lifecycle |
| Tenant billing | `tenant_billing_upgrade_intent` | `tenant_billing_service.py` | Tenant billing panel |

Dedupe/idempotency summary:

- Compile terminal rows: `event_id=compile:<job_id>:<completed|failed>` (`analytics_service.py:1237-1255`).
- Consent and onboarding: `event_id` + `pg_advisory_xact_lock` (`consent_analytics_service.py:217-240`, `onboarding_analytics_service.py:244-330`).
- Template events: `event_id` + advisory lock (`template_analytics_service.py:190-205`); `template_use` keyed by resume id.
- Flag exposure: `(user, flag, variant, window)` advisory lock (`flag_exposure_service.py:278-305`); cohort exposure one row per subject/flag/UTC day.
- Editor toggles: 60-second per-document/mode/action dedupe.
- Portfolio view: Redis `SET NX` 300-second viewer debounce; `resume_views` has the same 300-second debounce.
- Linter: in-batch dedupe plus client rolling window.
- **No dedupe:** `page_view`, `feature_usage`, `optimize`, `resume_created`, `resume_forked`, `academic_cv_converted`, integration events, content-library events, coupon/student events, career events, GC telemetry, tenant billing intent.

## 6. #2186 roadmap reconciliation - 130 items

Method: parsed the 130 tracker rows from issue #2186, parsed the 130 feature titles from `docs/ADMIN_ANALYTICS_ROADMAP.md` (X rows from the issue body), then checked each item against routes, services, and admin components at `d2cbc51`. A route is marked implemented only if the live endpoint returns 401 (present). The issue body checkbox state is stale: only A1, A3, X3, X5 and X13 are checked, while the latest comments (2026-11-27) claim all P0/P1 delivery.

### 6.1 Status counts

| Priority | Items | Implemented | Partial | Planned | Blocked |
|---|---:|---:|---:|---:|---:|
| P0 | 44 | 44 | 0 | 0 | 0 |
| P1 | 56 | 55 | 1 | 0 | 0 |
| P2 | 30 | 1 | 6 | 22 | 1 |
| **Total** | **130** | **100** | **7** | **22** | **1** |

All 44 P0 items are implemented. 55 of 56 P1 items are implemented; X9 (materialized daily metrics) exists but its refresh task is only in the Celery beat schedule, which production does not run. The remaining gaps are P2: only I3 is fully implemented; 6 P2 items are partial, 22 are planned and L8 is blocked.

### 6.2 Full item table

| ID | Roadmap item | Priority | Status | Evidence in this checkout |
|---|---|---|---|---|
| **A. Command center** | | | | |
| A1 | Executive KPI header with previous-period comparison and sparklines | P0 | IMPLEMENTED | GET /analytics/admin/overview -> kpi_trends; AdminAnalytics |
| A2 | Needs attention queue | P0 | IMPLEMENTED | GET /admin/operations/attention; AdminOperations |
| A3 | Alert strip with severity and owner | P0 | IMPLEMENTED | GET/PATCH /admin/alerts; AdminOperations |
| A4 | Live activity feed (signups, payments, compiles, errors) | P1 | IMPLEMENTED | GET /admin/analytics/activity; AdminActivityFeed |
| A5 | Saved views and segments | P1 | IMPLEMENTED | /admin/saved-views + /admin/segments; AdminSavedViews |
| A6 | CSV/PDF export and scheduled email digest | P1 | IMPLEMENTED | /admin/exports + /admin/exports/stream + digest; AdminExports |
| A7 | Release/deploy markers on charts | P2 | PLANNED | No chart release markers (only PostHog release property) |
| **B. Growth and acquisition** | | | | |
| B1 | Traffic sources, UTM campaigns, referrers | P0 | IMPLEMENTED | GET /admin/analytics/traffic-sources; AdminTrafficSources |
| B2 | Landing-page conversion by page/variant | P0 | IMPLEMENTED | GET /admin/analytics/landing-conversion; AdminLandingConversion |
| B3 | Signup funnel by provider (Google, GitHub, email, OIDC, passkey) | P0 | IMPLEMENTED | activation.signup_funnel; AdminGrowth SignupFunnel |
| B4 | Referral program analytics | P1 | IMPLEMENTED | GET /admin/referrals/summary; AdminReferralAnalytics |
| B5 | Trial-start and trial-abuse signals | P1 | IMPLEMENTED | GET /admin/analytics/trial-health; AdminTrialHealth |
| B6 | SEO/content performance | P2 | PLANNED | No Search Console/SEO surface found |
| B7 | Geo/device/browser breakdown | P1 | IMPLEMENTED | GET /admin/analytics/privacy-breakdowns; AdminPrivacyBreakdowns |
| B8 | Campaign ROI | P2 | PARTIAL | UTM paid conversion exists; no campaign cost/spend table -> no ROI |
| **C. Activation and product usage** | | | | |
| C1 | Activation funnel: signup → first résumé → first compile → first export → first AI optimize → paid | P0 | IMPLEMENTED | GET /admin/analytics/activation; AdminGrowth |
| C2 | Feature adoption matrix by plan/role/cohort | P0 | IMPLEMENTED | GET /admin/analytics/feature-adoption; AdminProduct |
| C3 | Feature depth and frequency | P0 | IMPLEMENTED | GET /admin/analytics/feature-depth; AdminGrowth |
| C4 | Onboarding step completion and drop-off | P1 | IMPLEMENTED | GET /admin/analytics/onboarding; AdminOnboardingAnalytics |
| C5 | Retention cohorts (D1/D7/D30, weekly) | P1 | IMPLEMENTED | GET /admin/analytics/retention; AdminGrowth |
| C6 | Path analysis / Sankey | P1 | IMPLEMENTED | GET /admin/analytics/paths; AdminPathAnalysis |
| C7 | Editor-mode usage (source/visual/PDF), auto-compile, sync | P1 | IMPLEMENTED | GET /admin/analytics/editor-modes; AdminEditorModeUsage |
| C8 | Document complexity metrics | P1 | IMPLEMENTED | GET /admin/analytics/document-complexity; AdminDocumentComplexity |
| C9 | Template popularity and success | P1 | IMPLEMENTED | GET /admin/templates/performance; AdminTemplatePerformance |
| C10 | Collaboration usage | P1 | IMPLEMENTED | GET /admin/analytics/collaboration; AdminCollaboration |
| C11 | Integration adoption and failure | P1 | IMPLEMENTED | GET /admin/analytics/integrations; AdminIntegrations |
| C12 | Public share/portfolio performance | P1 | IMPLEMENTED | GET /admin/analytics/share-portfolio; AdminSharePortfolio |
| C13 | Browser extension / public API / TUI usage | P2 | PLANNED | No extension/public-API/TUI adoption view |
| C14 | Rage clicks, dead clicks, JS errors by route | P1 | IMPLEMENTED | GET /admin/analytics/errors + QualityTriage; AdminErrorFeed |
| C15 | Session replay browser | P0 | IMPLEMENTED | /admin >> Replays; AdminReplayBrowser |
| C16 | Power-user vs churned-user comparison | P2 | PLANNED | No power-user vs churned-user comparison |
| **D. AI quality and cost** | | | | |
| D1 | AI usage by feature/provider/model/persona | P0 | IMPLEMENTED | GET /admin/analytics/ai-usage; AdminGrowth |
| D2 | Token and cost per user/plan/feature | P0 | IMPLEMENTED | GET /admin/analytics/ai-cost; AdminGrowth |
| D3 | BYOK vs platform-key mix | P1 | IMPLEMENTED | GET /admin/analytics/credential-mix; AdminCredentialMix |
| D4 | AI latency and retry rate | P1 | IMPLEMENTED | GET /admin/analytics/ai-latency-retry; AdminAiLatencyRetry |
| D5 | ATS score distribution and improvement | P1 | IMPLEMENTED | GET /admin/analytics/ats-score-distribution; AdminAtsScoreDistribution |
| D6 | Optimization acceptance rate | P1 | IMPLEMENTED | GET /admin/analytics/optimization-acceptance; AdminOptimizationAcceptance |
| D7 | Cover letter/interview prep/career path adoption | P1 | IMPLEMENTED | GET /admin/analytics/career-adoption; AdminCareerAdoption |
| D8 | Model routing/fallback analytics | P2 | PLANNED | No model routing/fallback report |
| D9 | Spend caps and anomaly alerts | P0 | IMPLEMENTED | check_user_spend_guard + hard/soft caps, MAD anomaly signals, spend.caps alert |
| D10 | Prompt/version performance | P2 | PLANNED | No prompt/version performance report |
| **E. Revenue and billing** | | | | |
| E1 | MRR/ARR, ARPU, net revenue, refunds, chargebacks | P0 | IMPLEMENTED | GET /admin/billing/summary; AdminBilling/RevenueBreakdown |
| E2 | Plan mix and upgrade/downgrade/churn | P0 | IMPLEMENTED | GET /admin/subscriptions/analytics; AdminSubscriptions |
| E3 | Checkout funnel and failure reasons | P0 | IMPLEMENTED | GET /admin/billing/checkout-funnel; AdminCheckoutFunnel |
| E4 | Dodo webhook health | P0 | IMPLEMENTED | GET /admin/billing/webhooks; AdminBilling |
| E5 | Payment/refund reconciliation queue | P0 | IMPLEMENTED | GET /admin/billing/reconciliation; AdminBilling |
| E6 | Subscription timeline per user | P0 | IMPLEMENTED | GET /admin/users/{id}/360 + subscription_history; AdminUserDetail |
| E7 | Dunning/past-due/on-hold recovery | P1 | IMPLEMENTED | GET /admin/billing/dunning-recovery; AdminDunningRecovery |
| E8 | Coupon/student verification performance | P1 | IMPLEMENTED | GET /admin/revenue/coupon-student-performance; AdminCouponStudentPerformance |
| E9 | Invoice/receipt lookup and resend | P1 | IMPLEMENTED | GET /admin/receipts/search; AdminReceiptLookup |
| E10 | Refund workflow with approval | P0 | IMPLEMENTED | /admin/billing/refunds; AdminBilling |
| E11 | Revenue by country/currency/payment method | P2 | PARTIAL | Currency filter only; no country/payment-method view |
| E12 | Trial-to-paid cohort conversion | P0 | IMPLEMENTED | trial_attributions + trial_to_paid_pct; AdminTrialAttribution |
| E13 | Lifetime/weekly plan monitoring | P1 | IMPLEMENTED | GET /admin/analytics/plan-health; AdminPlanHealth |
| E14 | Team seat utilization | P1 | IMPLEMENTED | GET /admin/analytics/team-seats; AdminTeamSeatUtilization |
| **F. Reliability and operations** | | | | |
| F1 | Job queue depth/age/throughput | P0 | IMPLEMENTED | GET /admin/operations/queues; AdminOperations |
| F2 | Stuck-job diagnosis and safe actions | P0 | IMPLEMENTED | GET /admin/operations/stuck-jobs; AdminStuckJobs |
| F3 | Compile latency percentiles | P0 | IMPLEMENTED | GET /admin/analytics/compile-latency; AdminCompileLatency |
| F4 | Compile error taxonomy | P0 | IMPLEMENTED | GET /admin/analytics/compile-errors; AdminCompileErrors |
| F5 | Worker/container health | P0 | IMPLEMENTED | GET /admin/operations/health; AdminOperationsHealth |
| F6 | Redis/DB/Upstash capacity | P0 | IMPLEMENTED | capacity probes in /admin/operations/health + /readyz |
| F7 | Email delivery status | P1 | IMPLEMENTED | GET /admin/email/health; AdminEmailHealth |
| F8 | Storage/PDF artifact lifecycle | P1 | IMPLEMENTED | GET /admin/operations/artifacts/lifecycle; AdminArtifactLifecycle |
| F9 | Incident timeline | P1 | IMPLEMENTED | GET /admin/operations/incidents; AdminIncidentTimeline |
| F10 | Synthetic checks/status page | P2 | PLANNED | No synthetic-check/status-page surface |
| F11 | Provider status (Dodo, Modal, Neon, Upstash, Resend) | P2 | PARTIAL | Provider console links only; no provider status feed |
| **G. Customers and support** | | | | |
| G1 | User 360 | P0 | IMPLEMENTED | GET /admin/users/{id}/360; AdminUserDetail |
| G2 | Search by email/ID/payment/subscription | P0 | IMPLEMENTED | GET /admin/users (q or id) + /admin/receipts/search |
| G3 | Safe PII reveal with audit | P0 | IMPLEMENTED | POST /admin/users/{id}/reveal-pii (audited); AdminUserDetail |
| G4 | Read-only “view as user” | P1 | IMPLEMENTED | /admin/view-as/*; AdminViewAs |
| G5 | Grant/revoke entitlement, extend trial, reset quota | P0 | IMPLEMENTED | plan/feature/trial/quota routes; AdminUserDetail |
| G6 | Resend verification/password reset/receipt | P1 | IMPLEMENTED | support resend-verification/password-reset/receipt; AdminSupportActions |
| G7 | Revoke sessions/passkeys/API keys | P0 | IMPLEMENTED | sessions/passkeys/api-keys/byok/developer revoke routes |
| G8 | Notes, tags, support timeline | P1 | IMPLEMENTED | notes/tags/support-timeline; AdminUserNotes |
| G9 | GDPR export/delete workflow | P0 | IMPLEMENTED | /admin/gdpr/*; AdminGdpr |
| G10 | Abuse signals | P1 | IMPLEMENTED | /admin/abuse/queue; AdminAbuseQueue |
| G11 | Segment builder and saved cohorts | P1 | IMPLEMENTED | /admin/segments; AdminSavedViews |
| G12 | Refund/goodwill action | P1 | IMPLEMENTED | /admin/billing/refunds; AdminBilling |
| **H. Security, audit, and governance** | | | | |
| H1 | Immutable admin audit log | P0 | IMPLEMENTED | GET /admin/audit; append-only admin_audit_log |
| H2 | Flag/entitlement change history | P0 | IMPLEMENTED | GET /admin/change-history; AdminChangeHistory |
| H3 | Sensitive-action approvals | P1 | IMPLEMENTED | /admin/approvals; AdminApprovals |
| H4 | Access review | P1 | IMPLEMENTED | GET /admin/access-review; AdminAccessReview |
| H5 | Consent analytics | P1 | IMPLEMENTED | GET /admin/analytics/consent; AdminConsentAnalytics |
| H6 | Data retention controls | P1 | IMPLEMENTED | /admin/operations/retention; AdminRetentionControls |
| H7 | Secret/provider credential health | P2 | PLANNED | No credential/secret-health surface |
| H8 | Rate-limit/abuse dashboard | P2 | PARTIAL | Abuse queue only; no rate-limit offender/false-positive view |
| H9 | Legal hold/export | P2 | PARTIAL | Legal holds + GDPR export exist; no legal-case export |
| **I. Content, templates, and quality** | | | | |
| I1 | Template catalog performance | P1 | IMPLEMENTED | GET /admin/templates/performance; AdminTemplatePerformance |
| I2 | Template error and regression status | P1 | IMPLEMENTED | GET /admin/templates/health; AdminTemplateHealth |
| I3 | ATS keyword/industry coverage | P2 | IMPLEMENTED | ATS distribution by industry/profile; AdminAtsScoreDistribution |
| I4 | Content library usage | P1 | IMPLEMENTED | GET /admin/content-library/adoption; AdminContentLibraryQuality |
| I5 | Academic CV/publication adoption | P2 | PLANNED | No academic CV/publication adoption surface |
| I6 | Linter rule frequency and fix rate | P1 | IMPLEMENTED | GET /admin/linter/rules; AdminLinterRules |
| I7 | PDF accessibility/tagging status | P2 | PLANNED | No PDF tagging/accessibility status surface |
| I8 | Localization usage and errors | P2 | PLANNED | No locale/localization analytics |
| **J. Tenant and agency analytics** | | | | |
| J1 | Tenant overview | P1 | IMPLEMENTED | GET /tenants/{id}/stats; TenantOverviewAnalytics |
| J2 | Cohort progress and recruiter engagement | P1 | IMPLEMENTED | GET /tenants/{id}/cohorts/{id}/engagement; TenantCohortProgress |
| J3 | Custom-domain health | P1 | IMPLEMENTED | GET /tenants/{id}/domain/health; tenant page |
| J4 | Branding adoption | P2 | PLANNED | Branding settings only; no adoption view |
| J5 | Tenant billing/seat utilization | P1 | IMPLEMENTED | Tenant billing + seat panel; TenantBillingPanel |
| J6 | Cross-tenant benchmark | P2 | PLANNED | No cross-tenant benchmark |
| **K. Experimentation and feedback** | | | | |
| K1 | Feature flag exposure and impact | P1 | IMPLEMENTED | GET /admin/analytics/flag-exposure; AdminFlagExposure |
| K2 | A/B experiments | P1 | IMPLEMENTED | /admin/experiments; AdminExperiments |
| K3 | In-app surveys/NPS/CSAT | P2 | PLANNED | No PostHog surveys/NPS/CSAT |
| K4 | Feedback inbox with replay links | P2 | PLANNED | No feedback inbox |
| K5 | Changelog adoption | P2 | PLANNED | No changelog adoption analytics |
| K6 | Feature request voting | P2 | PLANNED | No feature-request voting |
| **L. PostHog-native capabilities** | | | | |
| L1 | Replay playlists by route/error/plan | P0 | IMPLEMENTED | /admin >> Replays + prefiltered links; AdminReplayBrowser |
| L2 | Funnels, trends, paths, retention, stickiness | P1 | IMPLEMENTED | PostHog saved-insight links; AdminPostHogInsights |
| L3 | Cohorts synced to feature flags | P1 | IMPLEMENTED | /admin/cohorts snapshot sync -> flags; AdminCohorts |
| L4 | Error tracking and alerts | P1 | IMPLEMENTED | /admin/analytics/errors + error alerts; AdminErrorFeed |
| L5 | Surveys and experiments | P2 | PARTIAL | A/B experiments exist (K2); surveys absent |
| L6 | Notebooks for investigations | P2 | PLANNED | No PostHog notebooks |
| L7 | HogQL queries from admin | P2 | PLANNED | No HogQL proxy/personal API key |
| L8 | Warehouse joins with Neon read replica | P2 | BLOCKED | Blocked: no Neon read replica/PostHog warehouse |
| L9 | Embedded dashboards | P2 | PLANNED | No embed by design |
| L10 | CDP exports to support/email | P2 | PLANNED | No CDP exports |
| **X. Data and API workstreams** | | | | |
| X1 | Extend /analytics/admin/overview with prior-period deltas | P0 | IMPLEMENTED | overview.kpi_trends |
| X2 | /admin/analytics/timeseries with dimension filters | P1 | IMPLEMENTED | GET /admin/analytics/timeseries |
| X3 | /admin/users/{id}/360 | P0 | IMPLEMENTED | GET /admin/users/{id}/360 |
| X4 | /admin/billing/summary and /admin/billing/webhooks | P0 | IMPLEMENTED | GET /admin/billing/summary + /admin/billing/webhooks |
| X5 | /admin/operations/health | P0 | IMPLEMENTED | GET /admin/operations/health |
| X6 | /admin/audit | P0 | IMPLEMENTED | GET /admin/audit |
| X7 | /admin/alerts | P0 | IMPLEMENTED | GET/PATCH /admin/alerts |
| X8 | /admin/exports | P1 | IMPLEMENTED | /admin/exports + stream/download |
| X9 | Materialized daily metrics view | P1 | PARTIAL | Table + read path exist; refresh task only in Celery beat (not dispatched by Modal) |
| X10 | PostHog server-side proxy | P2 | PLANNED | No PostHog proxy/HogQL endpoint |
| X11 | Saved views/segments tables | P1 | IMPLEMENTED | admin_saved_views + admin_segments |
| X12 | Alert evaluator (cron) | P0 | IMPLEMENTED | Modal five-minute alert evaluator |
| X13 | Audit middleware/helper | P0 | IMPLEMENTED | record_admin_audit on mutating admin routes |

## 7. Findings and reconciliation risks

Severity follows the audit scale. These are analytics/admin-surface findings, not re-reports of unrelated product defects.

### AS-01 (P1) Every admin KPI includes synthetic/test accounts; there is no test-cohort filter

Ground truth records 833 users, of which only 7 are non-test. `get_system_analytics` counts `User` rows with no test/audit predicate (`backend/app/services/analytics_service.py:487-585`), and `admin_growth_service.activation` starts from all `users` created in the window (`backend/app/services/admin_growth_service.py:235-260`). Saved views/segments filter plan, provider, feature and signup cohort, but no `is_test`/audit cohort field exists. Every user, trial, conversion, activation and retention denominator is therefore contaminated before cleanup. This directly violates the audit rule that a dashboard which cannot exclude test traffic is itself a finding.

### AS-02 (P1) Three different refund-attribution policies guarantee Revenue vs Analytics disagreement

- Analytics overview KPI: refunds are joined on `Payment.created_at >= start_date`, so a refund created later is subtracted from the original payment period (`analytics_service.py:540-558`).
- Daily rollup: refunds are bucketed by `p.created_at` (`admin_daily_metrics_service.py:109-120`).
- Revenue control room: refunds are filtered by `PaymentRefund.created_at` (`admin_revenue_service.py:89-91`), so the same refund lands in a different period.
- Payment status sets also differ: overview uses `paid, partially_refunded, captured, refunded`; revenue adds `succeeded`.

Whenever a refund crosses a period boundary, the Analytics KPI and Revenue tab disagree by the refund amount. This is the highest-value reconciliation check to run first.

### AS-03 (P1) The headline "trial conversion" is not trial-to-paid conversion

`get_system_analytics` computes `conversion_rate = new_users / trial_users` (`analytics_service.py:581-583`), and `AdminAnalytics.tsx:425` labels that number "trial conversion" on the Active subscriptions card. It is a period registration/devices ratio, not trial-to-paid. The actual trial-to-paid metric exists in `trial_health_service` / `trial_attribution_service` but is not the executive KPI. The same value feeds the "Conversion" KPI trend (`analytics_service.py:1096-1099`).

### AS-04 (P1) PostHog person `plan` is always `unknown`

`identifyAnalyticsUser` defaults `plan: user.plan ?? 'unknown'` (`frontend/src/lib/analytics/posthog.ts:643-645`), but `AnalyticsProvider` calls it with only `id`, `role` and `createdAt` (`frontend/src/components/analytics/AnalyticsProvider.tsx:117-121`). Every PostHog person therefore has `plan=unknown`. The replay browser builds a person-property filter on `plan` (`frontend/src/lib/analytics/replay-browser.ts`), and cohort/flag segmentation by plan cannot work. This makes the "replays by plan" and L3 cohort-by-plan promises false in practice.

### AS-05 (P1) The PostHog Activation funnel references a dead event

`frontend/src/lib/analytics/saved-insights.ts:101` defines the Activation funnel as `$pageview -> product_event -> compilation_tracked -> checkout_started`. `product_event` is only emitted by `apiClient.trackEvent` (`frontend/src/lib/api-client.ts:10088-10101`), and no caller invokes `trackEvent`. The second funnel step is always empty. The first-party activation report uses different milestones, so the two "activation funnels" cannot be compared.

### AS-06 (P2) 9 of 17 allowlisted server-mirror event names have no writer

`posthog_service.py:71-91` allowlists `page_view`, `feature_usage`, `compile`, `optimize`, `resume_created`, `resume_forked`, `academic_cv_converted`, `export`, `signup`, `login`, `share_viewed`, `checkout_started`, `upgrade_clicked`, `ats_score`, `cover_letter`, `interview_prep`, `error`. Only the first eight are written by first-party code. The other nine never reach PostHog. `cover_letter_generated`, `interview_prep_generated` and `career_analysis_generated` are written to `usage_analytics` but do not match the allowlist names (`cover_letter`, `interview_prep`), so career usage never mirrors either.

### AS-07 (P2) First-party `page_view` is not consent-gated while PostHog `$pageview` is

`trackFirstPartyPageview` has no consent check (`frontend/src/lib/analytics/landing.ts:159-189`) and `LandingPageviewTracker` calls it for every landing route and selected authenticated app route (`frontend/src/components/analytics/LandingPageviewTracker.tsx:37-61`). PostHog capture requires `readAnalyticsConsent() === 'granted'` (`frontend/src/lib/analytics/posthog.ts:544-590`). Consequently the DB landing/funnel counts include visitors who denied analytics, while PostHog does not. The Analytics funnel and Growth landing/retention surfaces use the DB numbers; PostHog funnels use the consented subset. This is both a parity and a privacy-consistency issue.

### AS-08 (P2) "Top features" mixes event actions with feature labels

`get_admin_top_features` groups by `coalesce(event_metadata->>'feature', action)` (`analytics_service.py:1102-1131`). Every `page_view`, `compile`, `optimize` or `export` event without a `feature` field appears as a feature row. The Analytics "Top features" table is therefore a mixed event/feature ranking, not a feature adoption ranking. `feature_depth` has the same expression (`admin_growth_service.py:717-722`).

### AS-09 (P2) Authenticated clients can create arbitrary analytics actions/features

`POST /analytics/track` accepts any `event_type` matching `^[A-Za-z0-9_.:-]+$` (`backend/app/api/analytics_routes.py:73-80`) and `/track/feature-usage` accepts any `feature` string (`analytics_routes.py:561-583`). There is no server-side vocabulary/allowlist. PostHog is protected by `_MIRRORED_EVENT_TYPES`, but `usage_analytics` is not, so a signed-in user can poison top-feature, feature-depth, recent-event and saved-segment results and inflate DB cardinality.

### AS-10 (P2) PostHog cohort sync is a manual snapshot, not a connector

`cohort_sync_service.py` stores a cohort definition, members and flag mappings supplied by a connector; it makes no PostHog API call (the only "snapshot" language is at line 654). `POST /admin/cohorts/{id}/sync` accepts a consent-filtered snapshot or a bounded failure code (`admin_cohort_routes.py:216-230`). L3 "cohorts synced to feature flags" is therefore operator-mediated, not a scheduled PostHog sync. The admin screen cannot prove that PostHog and the local cohort agree.

### AS-11 (P2) Two independent error-count pipelines sit on the same Quality tab

`AdminQualityTriage` links to PostHog `$exception` / `$rageclick` / `$dead_click` (`frontend/src/lib/analytics/quality-triage.ts`). `AdminErrorFeed` reads `admin_error_groups` (`backend/app/services/error_tracking_service.py:1-30`), populated from consent-gated client signals plus backend telemetry. Frontend errors are only mirrored when consent is granted (`error-signals.ts`), so the two counts differ by consent and by ingestion path. The tab presents them as complementary but does not reconcile them.

### AS-12 (P2) The daily rollup is INR-only, non-anonymous and has a different status/refund policy

`admin_daily_metrics_service.py`:

- Payments are INR-only and `status IN ('paid','captured','partially_refunded','refunded')` (lines 95-108), excluding `succeeded`.
- Refunds are bucketed by original payment date (lines 109-120).
- `active_users = count(distinct user_id)` from `usage_analytics`, so anonymous events are excluded (lines 121-130).
- Refresh every 10 minutes; data older than 30 minutes falls back to base tables (`REFRESH_INTERVAL_SECONDS`, `STALE_AFTER_SECONDS`).

The rollup is internally consistent with the Analytics tab but not with the Revenue tab (multi-currency, refund-date bucketing, `succeeded` status). `metrics_freshness` does expose the source/fallback, which is good.

### AS-13 (P3) The 60-second overview cache is not invalidated by admin mutations or completed jobs

`GET /analytics/admin/overview` caches by `days` in-process and in Redis for 60 seconds (`analytics_routes.py:54-55,615-666`). There is no invalidation call after compile completion, payment, refund, plan change or test-cohort cleanup. A reconciliation run that performs an action and immediately reads the dashboard can see stale numbers. Test windows must be padded by at least 60 seconds or the cache flushed.

### AS-14 (P3) Generic `$autocapture` may include clicked element text on document surfaces

`sanitizeAnalyticsEvent` removes `$el_text`/`$elements_chain` only for `$rageclick` and `$dead_click` (`posthog.ts:378-391`), and path-blocks only `$exception`/rage/dead "content events" (`posthog.ts:346-357`). Generic `$autocapture` stays enabled. Document surfaces rely on `.ph-no-capture` containers (`workspace/[resumeId]/edit/page.tsx`, `r/[token]/page.tsx`, `u/[username]/page.tsx`, `try/page.tsx`), but any clicked element outside those containers can still carry text. This is a residual privacy risk, not a proven leak.

### AS-15 (P3) PostHog is link-only; no programmatic parity is possible from the admin

`AdminPostHogInsights` builds URLs with the public project id and optional saved-insight short ids (`frontend/src/lib/analytics/saved-insights.ts`, `posthog.ts:720-741`). It never reads counts from PostHog. There is no server-side proxy/HogQL endpoint (X10 planned). Any PostHog-vs-DB comparison must be done manually in the PostHog UI, and the admin cannot prove its own link targets.

### AS-16 (P2) 41 of 49 first-party action families never reach PostHog

The mirror allowlist has 17 names and only 8 live writers. Consent, onboarding, flag exposure, cohort flag exposure, editor mode, integrations, portfolio, content library, linter, coupon/student, career, artifact GC and tenant billing are first-party-only. PostHog cannot explore or alert on them. This is a structural missing-telemetry gap, not a bug in any one dashboard.

### AS-17 (P2) The Revenue KPI and Analytics KPI disagree on chargebacks

`get_system_analytics` subtracts only succeeded refunds and never chargebacks/disputes (`analytics_service.py:539-558`). `admin_revenue_service` computes "net after chargebacks" and displays chargeback exposure (`AdminRevenueBreakdown`). When a dispute exists, the two "revenue" numbers differ by the disputed amount.

### AS-18 (P2) The materialized daily-metrics rollup is dormant in production

`refresh_daily_metrics_task` is registered only in the Celery beat schedule (`backend/app/core/celery_app.py:348-353`). `backend/modal_app.py:754-760` states that Celery beat is only launched by dev/docker manifests and not in production, and none of the Modal scheduled functions dispatches `refresh_daily_metrics_task` (the hourly cleanup, five-minute maintenance and one-minute recovery fan-outs do not reference it). `daily_series` therefore always falls back to `source="base_tables"` with `fallback_reason` after 30 minutes (`admin_daily_metrics_service.py:453-517`). The dashboard remains correct because it falls back, but X9's performance goal is not met and every Analytics read scans the base tables. Verify `metrics_freshness.source` live; if it is always `base_tables`, the rollup has never been refreshed.

## 8. Missing telemetry and dead UI entry points

| Missing item | Evidence | Impact |
|---|---|---|
| Test-cohort exclusion | No `is_test`/audit predicate in any KPI query | All dashboards contaminated by 826 synthetic users |
| `product_event` emitter | `trackEvent` exists but no caller (`api-client.ts:10088`) | PostHog Activation funnel step always empty |
| 9 mirrored event names | `posthog_service.py:71-91`; no writers | PostHog signup/login/share/ATS/career/error analytics empty |
| First-party signup/login | No `usage_analytics` writer for `signup`/`login` | DB cannot reconcile PostHog auth events |
| First-party checkout_started/export_failed/share_link_created/portfolio_generated/subscription_cancel_requested | Client-only PostHog events | Billing/share funnels cannot be reconciled to DB |
| Extension/public API/TUI adoption | No admin component/service | C13 planned |
| SEO/Search Console | No service/integration | B6 planned |
| Surveys/NPS/feedback/changelog/voting | No component/table | K3-K6 planned |
| Model routing/fallback | No report/service | D8 planned |
| Prompt/version performance | No report (privacy constraint) | D10 planned |
| PDF accessibility/tagging status | Accessibility statement only | I7 planned |
| Locale/localization analytics | No locale dimension | I8 planned |
| Campaign cost/ROI | UTM paid conversion exists; no cost table | B8 partial |
| Cross-tenant benchmark | No admin/tenant surface | J6 planned |
| PostHog HogQL/proxy/embed | No backend proxy; `AdminPostHogInsights` is link-only | X10, L7, L9 planned |

## 9. Reconciliation checklist for the lead analytics auditor

No live numeric reconciliation was possible in this sub-agent: the live admin endpoints require an authenticated admin session, and no credentials were provided. The following checks are the minimum evidence set once an admin session is available. Use a fixed UTC window and record the test-cohort prefix.

```sql
-- 0. Test-cohort contamination
SELECT count(*) AS total_users,
       count(*) FILTER (WHERE email LIKE 'audit+%' OR email LIKE '%@example.test') AS test_users
FROM users;

-- 1. Analytics user KPI vs source
SELECT count(*) FILTER (WHERE created_at >= :start AND created_at < :end) AS new_users
FROM users;

-- 2. Compile KPI vs source
SELECT status, count(*) FROM compilations
WHERE created_at >= :start AND created_at < :end GROUP BY status;

-- 3. Event counts by action (top features / recent events)
SELECT action, count(*) FROM usage_analytics
WHERE created_at >= :start AND created_at < :end GROUP BY action ORDER BY 2 DESC;

-- 4. Analytics revenue KPI (payment-date refunds, INR only)
SELECT coalesce(sum(p.amount),0) AS gross_minor
FROM payments p
WHERE p.created_at >= :start AND p.created_at < :end
  AND p.currency = 'INR'
  AND p.status IN ('paid','partially_refunded','captured','refunded');
SELECT coalesce(sum(r.amount),0) AS refund_minor
FROM payment_refunds r JOIN payments p ON p.id = r.payment_id
WHERE p.created_at >= :start AND p.created_at < :end
  AND p.currency = 'INR' AND r.status = 'succeeded';

-- 5. Revenue tab refund policy (refund-date bucketing)
SELECT coalesce(sum(r.amount),0) AS refund_minor
FROM payment_refunds r JOIN payments p ON p.id = r.payment_id
WHERE r.created_at >= :start AND r.created_at < :end
  AND p.currency = 'INR' AND r.status = 'succeeded';

-- 6. Funnel steps
SELECT date_trunc('day', created_at) AS day, count(*)
FROM usage_analytics
WHERE action = 'page_view'
  AND event_metadata->>'page' = 'landing'
  AND created_at >= :start AND created_at < :end
GROUP BY 1 ORDER BY 1;
```

PostHog parity checks (manual UI or export):

1. Compare PostHog `$pageview` to `usage_analytics action='page_view' event_metadata->>'page'='landing'` for the same window. Expect DB >= PostHog (AS-07); document the delta.
2. Compare PostHog `compilation_tracked` to DB `compile` terminal rows. Client retries and non-terminal statuses make PostHog >= DB.
3. Compare PostHog `checkout_started`/`checkout_failed` to `subscription_history` `checkout_failed`/`checkout_unknown` and `payments`. These are different event models; no exact parity is expected.
4. Compare `AdminQualityTriage` PostHog `$exception` counts to `admin_error_groups.occurrence_count`. Consent and source differences will produce a delta (AS-11).
5. Compare `AdminReplayBrowser` plan filter counts to `users.subscription_plan`. The filter is always empty/unknown because of AS-04.
6. Check every suppression surface returns null/withheld instead of counts for groups <5: consent, privacy breakdowns, integrations, career adoption, retention, coupon/student, team seats, ATS, optimization acceptance, path analysis.

Test-window procedure:

1. Record `window_start`/`window_end` UTC and the synthetic account IDs.
2. Run the SQL checks before and after the test window.
3. Read the admin endpoints at least 60 seconds after the last mutation (AS-13) and record the `generated_at` / `metrics_freshness` fields.
4. Delete the synthetic rows, then re-run the KPI query to prove the cleanup delta.
5. If a dashboard cannot exclude the audit cohort, record that as a continuing finding.

## 10. Blocked and limitations

- **No authenticated admin session** - all 27 sampled admin analytics endpoints return 401; numeric dashboard-vs-DB comparison is blocked. The routes are present, but data values are unverified.
- **No PostHog personal API key** - no programmatic event counts, saved-insight verification, cohort membership or replay inventory. Project configuration is documented (`docs/POSTHOG.md`) but not verified live.
- **OpenAPI disabled** - live schema is 404; route inventory uses `audit/inventory/openapi-source.json` and the source at the deployed SHA.
- **No production DB access** - SQL above is the required follow-up, not executed here.
- **Read-only mandate** - no test identities, no capability flips, no cleanup performed. The 826 synthetic users remain in production analytics until the cleanup auditor removes them.

## 11. Method and source index

- Event inventory: `frontend/src/lib/analytics/posthog.ts`, `frontend/src/lib/api-client.ts`, `frontend/src/lib/analytics/*.ts`, `backend/app/services/posthog_service.py`, `backend/app/services/analytics_service.py`, all `UsageAnalytics` writers, `signup_funnel_service.py`.
- Admin surfaces: `frontend/src/app/admin/page.tsx`, `frontend/src/app/admin/tenant/page.tsx`, `frontend/src/components/admin/*.tsx`, `frontend/src/lib/api-client.ts` endpoint methods.
- Backend read paths: 50 `backend/app/api/admin_*_routes.py` modules plus `admin_routes.py`, `analytics_routes.py`, `traffic_source_routes.py`, `landing_conversion_routes.py`, `trial_attribution_routes.py`, `consent_analytics_routes.py`, `onboarding_analytics_routes.py`, `tenant_routes.py`.
- Services/tables: `backend/app/services/admin_*.py`, `admin_growth_service.py`, `error_tracking_service.py`, `queue_snapshot_service.py`, `cohort_sync_service.py`, and the model classes in `backend/app/database/models.py`.
- Roadmap: GitHub issue #2186 body + comments (2026-11-22 through 2026-11-27), `docs/ADMIN_ANALYTICS_ROADMAP.md`.

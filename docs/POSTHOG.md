# PostHog integration and analytics policy

Status: **implemented** (frontend + backend + admin overview). PostHog project:
`756020`, US Cloud.

## Why PostHog sits beside the first-party analytics

Latexy already stores authoritative product events in `usage_analytics`,
compilations, optimizations, payments, subscriptions, and webhook dead letters.
Those tables remain the source of truth for billing, entitlements, and the admin
KPI cards. PostHog adds the exploration layer: funnels, paths, retention,
feature adoption, and **consented, masked session replay**.

The backend mirrors first-party events into PostHog through
`app/services/posthog_service.py`; it never replaces the database record.

## Privacy contract

These rules are enforced in code and by
`scripts/ci/no-session-recording.sh`:

1. **No browser analytics or replay before consent.** `posthog-js` is imported
   only by `frontend/src/lib/analytics/posthog.ts`. `AnalyticsProvider`
   initializes it only when `latexy-analytics-consent === "granted"`. Limited
   server-side service/billing analytics is a separate, non-replay path and is
   disclosed in the privacy policy.
2. **Total masking.** The SDK sets `mask_all_text`, `mask_all_element_attributes`,
   `session_recording.maskAllInputs`, and `session_recording.maskTextSelector: '*'`.
   The PostHog project is also set to “Total privacy (mask all text/images)”.
3. **Document surfaces are blocked.** The résumé editor, guest editor, public
   share page, and portfolio page carry `ph-no-capture` /
   `data-ph-no-capture`. The wrapper uses
   `blockSelector: '.ph-no-capture, [data-ph-no-capture]'`.
4. **No IP storage.** The PostHog project discards client IP data. The backend
   sends `$geoip_disable: true`.
5. **URLs are templated before every send.** `before_send` rewrites
   `$current_url` and `$referrer` for all SDK-created events, including
   autocapture. Pageleave capture is disabled because the SDK derives it from
   the raw browser URL, which can contain a share token.
6. **No content in events.** The frontend sanitizer drops keys matching email,
   name, résumé, LaTeX, content, prompt, text, token, secret, password, auth,
   cookie, SSN, birth, salary, job description, and cover letter. The backend
   sanitizer applies the same rule and drops nested objects/arrays.
7. **Withdrawal works.** “Privacy choices” in the footer clears consent; the
   provider stops recording, opts out, and resets the identity immediately.

If any of these change, update the privacy policy, accessibility statement, and
the CI guard in the same pull request.

## Environment variables

### Frontend (Vercel)

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_POSTHOG_KEY` | Public, write-only project token (`phc_…`). |
| `NEXT_PUBLIC_POSTHOG_HOST` | Ingestion host, `https://us.i.posthog.com`. |
| `NEXT_PUBLIC_POSTHOG_UI_HOST` | App host for admin links, `https://us.posthog.com`. |
| `NEXT_PUBLIC_POSTHOG_PROJECT_ID` | `756020`; enables admin deep links. |

Leave the key blank to disable analytics without changing code.

### Backend (Modal secret `latexy-posthog`)

| Variable | Purpose |
| --- | --- |
| `POSTHOG_API_KEY` | Same public project token; the Python SDK uses it. |
| `POSTHOG_HOST` | `https://us.i.posthog.com`. |
| `POSTHOG_ENABLED` | `true`; set `false` for an emergency stop. |

The secret is attached through `_base_secrets` in `backend/modal_app.py`.

## Event taxonomy

### Frontend

| Event | Properties | Where |
| --- | --- | --- |
| `$pageview` | `path`, sanitized `$current_url`, sanitized `$referrer` | `AnalyticsProvider` on route change |
| `product_event` | `event_type`, sanitized metadata | `apiClient.trackEvent` |
| `compilation_tracked` | `status`, `duration_ms` | `apiClient.trackCompilation` |
| `optimization_tracked` | `provider`, `model`, `tokens_used` | `apiClient.trackOptimization` |
| `feature_used` | `feature` | `apiClient.trackFeatureUsage` |
| `checkout_started` / `checkout_failed` | `plan_key`, `billing_period`, `has_coupon` | `apiClient.createSubscription` |
| `subscription_cancel_requested` | none | `apiClient.cancelSubscription` |
| `export_completed` / `export_failed` | `format`, `guided_builder` | `apiClient.exportResume` |
| `cover_letter_generated` | none | `apiClient.generateCoverLetter` |
| `share_link_created` | `anonymous`, `review_comments` | `apiClient.createShareLink` |
| `portfolio_generated` | none | `apiClient.generatePortfolioSite` |

Paths are templated before capture: `/r/:token`, `/u/:username`,
`/workspace/:resumeId`, `/workspaces/:workspaceId`.

### Backend

The analytics mirror emits `backend_<event_type>` for every first-party
`analytics_service.track_event` call (for example `backend_compile`,
`backend_optimize`, `backend_feature_usage`).

Explicit lifecycle events:

| Event | Properties |
| --- | --- |
| `backend_job_submitted` | `job_type`, `plan_key`, `cached` |
| `backend_checkout_created` | `plan_key`, `billing_period`, `provider` |
| `backend_checkout_failed` | `plan_key`, `billing_period`, `failure_code` |
| `backend_payment_succeeded` | `plan_key`, `amount`, `currency`, `provider` |
| `backend_subscription_status_changed` | `plan_key`, `status`, `provider` |
| `backend_refund_status_changed` | `status`, `amount`, `currency`, `provider` |
| `backend_admin_flag_changed` | `feature_key`, `enabled` |
| `backend_admin_kill_switch_changed` | `feature_key`, `enabled` |
| `backend_admin_entitlement_changed` | `plan_key`, `feature_key`, `enabled` |
| `backend_admin_role_matrix_changed` | `role`, `feature_key`, `enabled` |
| `backend_admin_user_role_changed` | `target_user_id`, `previous_role`, `new_role` |

IDs are opaque UUIDs. Amounts are integer minor units for payments and are not
linked to card data. No endpoint sends a customer email or name to PostHog.

## Admin surface

`GET /analytics/admin/overview?days=7|30|90` returns one admin payload:

- authoritative system KPIs (users, subscriptions, revenue, compilations,
  optimizations, trials, conversion);
- conversion funnel;
- per-day timeseries (new/active users, compilations, optimizations, events,
  net revenue);
- top features;
- redacted recent events;
- 24-hour operations counters (queued, processing, completed, failed, webhook
  failures, active users).

The admin **Analytics** tab renders this payload and links to PostHog replays,
dashboards, people, replay privacy settings, and a set of **pre-filtered replay
triage** links (see below).

## Dashboards to create in PostHog

Create these once in the project; the admin deep links assume the project.

1. **Acquisition → activation**: `$pageview` → `product_event` (sign-up) →
   `compilation_tracked` → `optimization_tracked` → `checkout_started`.
2. **Compile health**: `compilation_tracked` broken down by `status`; alert on
   failure rate over 10% for 30 minutes.
3. **AI adoption and cost**: `optimization_tracked` by `model`; sum
   `tokens_used`; compare against plan.
4. **Billing funnel**: `checkout_started` → `backend_payment_succeeded` →
   `backend_subscription_status_changed`.
5. **Retention**: weekly retained users after first `compilation_tracked`.
6. **Replay review**: filter to `/workspace/:resumeId/edit`,
   `/dashboard`, `/billing`, `/pricing`; exclude `/r/:token` and `/u/:username`
   (already blocked at the project level).
7. **Admin actions**: `backend_admin_*` events grouped by admin ID.

## Replay review workflow

1. Open **Analytics → Open session replays**.
2. Prefer replays with console errors, rage clicks, or failed `checkout_*`
   events.
3. Watch layout, navigation, and interaction timing; text is intentionally
   masked, so use the linked event stream for state.
4. Never ask a user to disable masking for a recording. If a specific document
   bug needs reproduction, use a synthetic test account and the local test
   fixture, not a production replay.
5. File product issues with the replay URL, event name, and approximate UTC time.

## Pre-filtered replay triage links

The admin **Analytics** tab exposes direct, pre-filtered replay lists so common
triage cases are one click away. Links are built by
`frontend/src/lib/analytics/replay-links.ts` (a pure, browser-free module with
unit tests in `frontend/src/__tests__/replay-links.test.ts`) and resolved
against the configured project by `analyticsReplayTriageLinks` in
`frontend/src/lib/analytics/posthog.ts`.

Every link targets `{UI_HOST}/project/{POSTHOG_PROJECT_ID}/replay/home` with the
filter JSON URL-encoded into the `filters` search param, using PostHog's
universal recording-filters shape (`RecordingUniversalFilters`). The selected
admin date range (7/30/90 days) is preserved as a relative `date_from`
(`-7d` / `-30d` / `-90d`); PostHog fills the remaining defaults on load.

| Link | PostHog filter |
| --- | --- |
| Checkout failures | `filter_group` event `checkout_failed` |
| JS errors | `filter_group` property `{ key: "level", operator: "exact", type: "log_entry", value: ["error"] }` |
| Long sessions | `duration: [{ key: "active_seconds", operator: "gt", type: "recording", value: 120 }]` |
| By route (editor, dashboard, billing, pricing) | `filter_group` property `{ key: "$current_url", operator: "icontains", type: "event", value: "<templated path>" }` |
| By plan (free, basic, pro, byok, team) | `filter_group` property `{ key: "plan", operator: "exact", type: "person", value: ["<plan>"] }` |

Route paths use the already-templated values from `sanitizeAnalyticsPath`
(`/workspace/:resumeId/edit`, `/dashboard`, `/billing`, `/pricing`), and plan
values are the low-cardinality `plan` person-property enums. A link therefore
never contains a token, an email, a résumé or workspace id, or document
content.

Guardrails hold for these links exactly as for the rest of the analytics
boundary:

- **Admin-only.** The links render inside the admin Analytics tab, which is
  behind the admin role; there is no new public surface.
- **Consent-based and masked.** They only *open* the existing replay list; they
  do not change capture. Replays remain opt-in and fully text/input masked.
- **No document surfaces.** The links do not reference `/r/:token`, `/u/:username`,
  or `/share/:token`; résumé, share, and portfolio pages stay blocked.
- **No tokens or PII in URLs.** Filter values are enum strings and templated
  paths only.

## Retention and deletion

- Session replay: 30 days (PostHog project setting).
- Product analytics events: up to one year (PostHog plan default).
- `usage_analytics`, payments, subscriptions, and webhook records: governed by
  the application database and the privacy policy.

## Operational checks

```bash
# Frontend guard
bash scripts/ci/no-session-recording.sh

# Frontend unit tests
cd frontend && pnpm exec vitest run src/__tests__/analytics-posthog.test.ts

# Backend data-boundary tests
cd backend && SKIP_INFRA_CHECK=1 .venv/Scripts/python.exe -m pytest test/test_posthog_analytics.py -q

# Live config check
curl -s https://latexy.xyz/api/deployment-identity
```

If PostHog ingestion stops, analytics fails closed: the product keeps working,
the database events remain authoritative, and the admin KPI cards still load.

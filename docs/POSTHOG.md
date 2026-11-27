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
| `NEXT_PUBLIC_POSTHOG_INSIGHT_FUNNEL_ID` | Optional PostHog short id for the saved **Activation funnel**. Blank opens a prefilled funnel draft. |
| `NEXT_PUBLIC_POSTHOG_INSIGHT_TRENDS_ID` | Optional short id for **Product event trends**. |
| `NEXT_PUBLIC_POSTHOG_INSIGHT_PATHS_ID` | Optional short id for **Navigation paths**. |
| `NEXT_PUBLIC_POSTHOG_INSIGHT_RETENTION_ID` | Optional short id for **Weekly retention**. |
| `NEXT_PUBLIC_POSTHOG_INSIGHT_STICKINESS_ID` | Optional short id for **Feature stickiness**. |
| `NEXT_PUBLIC_APP_RELEASE` | Deployed git SHA or semver tag. Bounded to 64 safe characters and sent as `release` / `$release_id`; leave blank when unattested rather than inventing a version. |

Leave the key blank to disable analytics without changing code. If the release
is not configured, quality links omit the release filter and label it as
missing instead of pretending every event belongs to an unknown release.

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
| `$exception` | sanitized `error_type`, bounded exception value, sanitized stack filenames, `route`, `$release_id` | PostHog exception autocapture (`capture_exceptions: true`) |
| `$rageclick` | sanitized `$current_url`, `route`, `$release_id` | PostHog autocapture |
| `$dead_click` | sanitized `$current_url`, `route`, `$release_id` | PostHog dead-click extension (`capture_dead_clicks: true`) |

Paths are templated before capture: `/r/:token`, `/u/:username`,
`/workspace/:resumeId`, `/workspaces/:workspaceId`. Every SDK event also gets a
`route` property derived from the sanitized pathname and, when configured, the
`release` super property and `$release_id`.

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

The admin **Analytics** tab renders this payload and links to PostHog saved
funnels, trends, paths, retention, and stickiness, plus replays, dashboards,
people, replay privacy settings, and a set of **pre-filtered replay triage**
links (see below). The admin **Replays** tab hosts the fuller replay
library/browser with saved filters and a custom filter builder. The admin
**Quality** tab hosts route-level JavaScript-error, rage-click, and dead-click
triage.

## Dashboards and saved insights to create in PostHog

Create these once in the project; the admin deep links assume the project. The
five **saved insight** names match the typed catalog and are opened directly by
the admin Analytics tab when their short ids are configured.

1. **Activation funnel** (saved insight): `$pageview` → `product_event`
   (sign-up) → `compilation_tracked` → `optimization_tracked` →
   `checkout_started`.
2. **Product event trends** (saved insight): daily `compilation_tracked`,
   `optimization_tracked`, and `checkout_started`, grouped by sanitized `route`.
3. **Compile health**: `compilation_tracked` broken down by `status`; alert on
   failure rate over 10% for 30 minutes.
4. **AI adoption and cost**: `optimization_tracked` by `model`; sum
   `tokens_used`; compare against plan.
5. **Billing funnel**: `checkout_started` → `backend_payment_succeeded` →
   `backend_subscription_status_changed`.
6. **Weekly retention** (saved insight): weekly retained users after first
   `compilation_tracked`.
7. **Navigation paths** (saved insight): `$pageview` paths starting at
   `/dashboard`.
8. **Feature stickiness** (saved insight): daily `feature_used` grouped by the
   bounded `feature` key.
9. **Replay review**: filter to `/dashboard`, `/templates`, `/tracker`,
   `/billing`, `/pricing`, and `/settings`; exclude `/r/:token`,
   `/u/:username`, `/share/:token`, `/portfolio/:username`, and workspace/editor
   paths (already blocked at capture).
10. **Admin actions**: `backend_admin_*` events grouped by admin ID.
11. **Quality triage**: `$exception` (breakdowns: `error_type`, `route`,
    `$release_id`), `$rageclick`, and `$dead_click` (breakdowns: `route`,
    `$release_id`) as tables over 7 and 30 days. Add a minimum-count filter in
    PostHog if a saved view needs to exclude groups below five events.

## Saved insight catalog (admin Analytics)

`frontend/src/lib/analytics/saved-insights.ts` is the typed catalog behind the
**PostHog saved insights** panel on the admin Analytics tab. It covers five
aggregate views:

| Descriptor | PostHog type | Events / grouping |
| --- | --- | --- |
| Activation funnel | `FUNNELS` | `$pageview` → `product_event` → `compilation_tracked` → `checkout_started` |
| Product event trends | `TRENDS` | daily `compilation_tracked`, `optimization_tracked`, `checkout_started`, grouped by sanitized `route` |
| Navigation paths | `PATHS` | `$pageview` paths starting at `/dashboard` |
| Weekly retention | `RETENTION` | weekly recurring `compilation_tracked` cohorts |
| Feature stickiness | `STICKINESS` | daily `feature_used`, grouped by bounded `feature` |

Every descriptor carries the selected 7/30/90-day range. The panel is rendered
inside `AdminAnalytics`, which is reachable only through the admin tab list;
there is no public page, share link, or export.

There is no public share URL for these views; the only links point at the
authenticated PostHog project.

**Saved ids are optional.** No database migration is needed: the ids are
deployment configuration, and the catalog always has a prefilled-draft
fallback. When a `NEXT_PUBLIC_POSTHOG_INSIGHT_*_ID` is set, the link opens
`{UI_HOST}/project/{PROJECT_ID}/insights/{SHORT_ID}?filters_override=...` with
`{"date_from":"-30d","date_to":null}` so the saved view re-runs over the admin's
selected range. When an id is blank or invalid, the same card opens
`.../insights/new?insight={TYPE}&q=...` with a complete, prefilled
`InsightVizNode` query that already embeds the date range. Save that view once
in PostHog and set the environment variable if you want a stable saved id.

**First-party fallback.** If `NEXT_PUBLIC_POSTHOG_PROJECT_ID` is missing, the
panel labels the exploration links as unavailable and lists the five
descriptors without hrefs. The authoritative first-party KPI cards continue to
load from the Latexy database; no count is zero-filled from a missing PostHog
project.

**Privacy guardrails.**

- Breakdowns are limited to `route`, `plan`, `feature`, `event_type`, `status`,
  `format`, `provider`, `model`, `billing_period`, and a few browser/enums.
  Emails, names, user/distinct ids, person histories, document paths, prompts,
  and tokens are rejected by the catalog before a URL is built.
- PostHog groups with fewer than five users or events are suppressed during
  review. The panel states the policy and the helper in the module suppresses
  any small local aggregate before display.
- **No embed.** The panel renders no iframe and generates no PostHog share or
  embed token. PostHog embeds require a public sharing token plus a CSP
  `frame-src` review, so this surface deliberately links out to the
  authenticated project instead. There is no CSP exception to review for the
  current implementation.

Tests live in `frontend/src/__tests__/saved-insights.test.ts` (URL, project,
range, saved-id validation, breakdown allowlist, fallback, and cohort
suppression) and `frontend/src/__tests__/admin-posthog-insights.test.ts`
(admin-only wiring, rendering, embedded-content guardrail, and docs).

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
| By route (dashboard, templates, tracker, billing, pricing, settings) | `filter_group` property `{ key: "$current_url", operator: "icontains", type: "event", value: "<templated path>" }` |
| By plan (free, basic, pro, byok, team) | `filter_group` property `{ key: "plan", operator: "exact", type: "person", value: ["<plan>"] }` |

Route paths use the already-templated values from `sanitizeAnalyticsPath`
(`/dashboard`, `/templates`, `/tracker`, `/billing`, `/pricing`, `/settings`),
and plan values are the low-cardinality `plan` person-property enums. A link
therefore never contains a token, an email, a résumé or workspace id, or
document content. Document, share, portfolio, and guest-editor paths are
deliberately absent from the allowlist.

## Replay library/browser

The admin **Replays** tab (`?tab=replays`) is a library over the same link
builders. It adds:

- **Saved filters** for checkout failures, console errors, long sessions,
  route-specific errors, plan-specific errors, and combined route + checkout
  triage.
- A **custom filter builder** that combines sanitized route, plan, console
  error, minimum active duration, and `checkout_failed` under one AND group.
- A **consent coverage and masking policy** panel. It states the opt-in model,
  the capture-before-consent block, withdrawal behavior, excluded surfaces,
  total text/input/attribute masking, the PostHog "Total privacy" project
  setting, and the absence of any disable-masking control.
- **Triage deep links** for the common views plus the configured project's
  replay home and replay privacy settings.

The browser stores no replay data and renders no replay player. Every action is
an external PostHog link for the configured project and selected 7/30/90-day
range; the filter contract lives in
`frontend/src/lib/analytics/replay-browser.ts` and is unit tested in
`frontend/src/__tests__/replay-browser.test.ts`.

Guardrails hold for these links exactly as for the rest of the analytics
boundary:

- **Admin-only.** The links render inside the admin Analytics and Replays tabs,
  which are behind the admin role; there is no new public surface.
- **Consent-based and masked.** They only *open* the existing replay list; they
  do not change capture. Replays remain opt-in and fully text/input masked.
- **No document surfaces.** The links do not reference `/workspace*`, `/try`,
  `/r/:token`, `/u/:username`, `/share/:token`, or `/portfolio/:username`;
  résumé, share, portfolio, and guest-editor pages stay blocked.
- **No tokens or PII in URLs.** Filter values are enum strings and templated
  paths only.

## Error, rage-click, and dead-click triage

The browser wrapper enables three additional signals under the same consent and
masking boundary:

- **Exception autocapture** (`capture_exceptions: true`) sends `$exception`
  events for uncaught errors and unhandled rejections.
- **Dead clicks** (`capture_dead_clicks: true`) send `$dead_click` events when
  a click produces no visible response.
- **Rage clicks** remain part of PostHog autocapture and send `$rageclick`.

`before_send` (`sanitizeAnalyticsEvent` in
`frontend/src/lib/analytics/posthog.ts`) is the single boundary for every SDK
event. It now:

1. Drops `$exception`, `$rageclick`, and `$dead_click` events whose
   `$current_url` or `$pathname` is `/workspace*`, `/workspaces*`, `/try`,
   `/r/*`, `/u/*`, `/share/*`, or `/portfolio/*`. Errors and frustration
   signals on document surfaces are therefore not captured at all. Other
   events keep the existing templated-path sanitization, and replay remains
   blocked there by the `ph-no-capture` markers.
2. Templates URL paths and attaches `route`.
3. Attaches `release` and `$release_id` from `NEXT_PUBLIC_APP_RELEASE` when it
   is a bounded identifier. Invalid free-form values are dropped.
4. Redacts exception values and stack frame filenames: URL query strings,
   emails, vendor tokens, and UUIDs are removed, values are bounded, and the
   exception type is reduced to a safe class name (`error_type`).
5. Removes `$input*`, `$selected_content`, and `$exception_steps` before the
   event leaves the browser, and strips `$el_text` / `$elements_chain` /
   `$elements` from rage-click and dead-click events so clicked element text is
   not part of the quality data.

Consent withdrawal calls `stopExceptionAutocapture()`, stops replay, opts out,
and resets identity. Re-granting starts both replay and exception autocapture
again.

### Admin Quality tab

The admin **Quality** tab (`?tab=quality`) renders `AdminQualityTriage`. It
offers 7- and 30-day ranges plus sanitized route and release filters, then:

- lists the three saved-insight descriptors
  (`frontend/src/lib/analytics/quality-triage.ts`);
- builds a PostHog trends link for each descriptor with breakdowns by `route`,
  optional `$release_id`, and `error_type` for JavaScript errors;
- builds a filtered replay list for the same event, route, and release;
- links JavaScript errors to PostHog error tracking;
- renders a route matrix so an operator can open the same aggregate views per
  sanitized product route.

PostHog ranks the opened table by event count; the admin page deliberately does
not mirror counts, so route/release ordering is always the source-of-truth
PostHog aggregate rather than a stale or zero-filled local copy.

The view never embeds replay data, person rows, session histories, or event
payloads. It has no unmask switch, no per-user filter, and no mutation or
enforcement action. Links are filtered to the selected release and route; when
`NEXT_PUBLIC_POSTHOG_PROJECT_ID` is absent, the UI says **Missing telemetry**
instead of displaying zeroes. PostHog breakdown groups with fewer than five
events must be suppressed during review; the admin copy states that policy
explicitly.

The module and UI are unit tested in
`frontend/src/__tests__/quality-triage.test.ts` and
`frontend/src/__tests__/admin-quality-triage.test.ts`.

### Backend error grouping and threshold alerts

PostHog remains the source of truth for browser exception grouping, error
tracking, and masked replay. In addition, the backend keeps an aggregate-only
error feed keyed by `(source, route, release, error_class)`:

- The consent-gated `before_send` hook mirrors a sanitized
  `{route, release, error_class}` signal to `POST /telemetry/errors`; it never
  sends an exception message or stack.
- Unhandled backend 5xx responses record the route template and
  `type(exc).__name__` only.
- `/admin/analytics/errors` returns groups with at least five occurrences,
  suppression counts, the current threshold, delivery configuration, and a
  runbook link. It never returns per-user rows.
- `/admin/analytics/errors/evaluate` previews or dispatches one aggregate
  Slack/email message per group per cooldown window. A real dispatch requires
  `confirm: true` and an audited reason.

Alert payloads carry the sanitized route, release, error class, counters,
environment, and the
[error alert runbook](observability/error-alert-runbook.md) link. Document,
share, portfolio, and guest-editor routes are dropped before storage.

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
cd frontend && pnpm exec vitest run src/__tests__/analytics-posthog.test.ts src/__tests__/replay-links.test.ts src/__tests__/replay-browser.test.ts src/__tests__/quality-triage.test.ts src/__tests__/admin-quality-triage.test.ts src/__tests__/saved-insights.test.ts src/__tests__/admin-posthog-insights.test.ts

# Backend data-boundary tests
cd backend && SKIP_INFRA_CHECK=1 .venv/Scripts/python.exe -m pytest test/test_posthog_analytics.py -q

# Live config check
curl -s https://latexy.xyz/api/deployment-identity
```

If PostHog ingestion stops, analytics fails closed: the product keeps working,
the database events remain authoritative, and the admin KPI cards still load.

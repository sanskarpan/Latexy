# Error Alert Runbook

Audience: on-call engineer or admin operator responding to a Latexy error
threshold alert (issue #2166).

## What the alert means

An aggregate error group crossed the configured threshold in a rolling burst
window. Groups are keyed by **source** (`frontend` or `backend`), sanitized
**route**, **release**, and **error class**. The alert message contains only
those fields, occurrence counts, and this runbook link.

The admin feed suppresses groups with fewer than five occurrences. Alert
payloads never contain exception messages, stack traces, source snippets,
prompts, document content, emails, tokens, user IDs, IP addresses, or user
agents.

## First five minutes

1. Open the admin **Quality** tab and find the error feed row matching the
   alert (source, route, release, class).
2. Open the row's **Error tracking** link to inspect PostHog's grouped issue for
   that class and release.
3. Open the row's **Replay** link to view masked session replays filtered to
   `$exception`, the same route, release, and error class. Replay is
   intentionally text-masked; there is no unmask control.
4. Check whether the route is a document surface in the alert. If it is, treat
   the alert and the feed as a privacy incident: document surfaces are excluded
   and must never appear. Escalate to the security owner.
5. Compare the release tag with the current `NEXT_PUBLIC_APP_RELEASE` and backend
   `APP_VERSION`. A new release immediately before the spike is the strongest
   rollout signal.

## Triage and mitigation

- **Frontend-only, one route**: inspect the PostHog error issue and masked
  replay. Disable the affected feature flag or roll back the release through the
  normal two-person approval flow. Do not hot-fix directly on production.
- **Backend 5xx**: correlate with request IDs in server logs and the incident
  timeline. The grouped class is derived from `type(exc).__name__` only. Web
  responses intentionally do not include tracebacks.
- **Many routes, one class**: suspect a shared dependency, provider, or release
  regression. Check provider and queue health before changing application code.
- **Noise or duplicate alerts**: the dispatcher sends at most one aggregate
  message per group per cooldown window (default 60 minutes) and at most five
  groups per evaluation. Do not disable tracking; adjust the threshold only
  through a reviewed configuration change.

## Privacy guardrails

- Never add exception messages, stack traces, prompts, document content,
  emails, tokens, raw IPs, or user agents to an alert, issue, replay note, or
  dashboard.
- Never ask a customer to paste document content into an incident.
- Do not unmask replay, and do not create a per-user error history.
- Errors raised on `/workspace`, `/resumes`, `/documents`, `/share`,
  `/portfolio`, `/r/*`, `/u/*`, and `/try` are dropped at ingestion and must
  remain dropped.

## Configuration

| Variable | Purpose |
| --- | --- |
| `ERROR_TRACKING_ENABLED` | Master switch for aggregate capture |
| `ERROR_ALERT_THRESHOLD` | Occurrences in the burst window that trigger an alert (default 10) |
| `ERROR_ALERT_WINDOW_MINUTES` | Burst window (default 15) |
| `ERROR_ALERT_COOLDOWN_MINUTES` | Minimum time between deliveries per group (default 60) |
| `ALERT_SLACK_WEBHOOK_URL` | Slack incoming webhook; https only |
| `ALERT_SLACK_CHANNEL` | Channel label included in the Slack payload |
| `ALERT_EMAIL_TO` | Comma-separated operator inboxes (requires `EMAIL_ENABLED`) |

If no channel is configured, the admin evaluation endpoint reports
`delivery_configured: false` and does not mark groups as alerted, so alerts begin
as soon as a channel is added.

## Verification

```bash
# Backend error tracking and alert tests
cd backend && TEST_DATABASE_URL=... DATABASE_URL=... \
  .venv/Scripts/python.exe -m pytest test/test_admin_error_tracking.py -q

# Frontend quality link tests
cd frontend && pnpm exec vitest run src/__tests__/error-tracking-links.test.ts
```

The admin evaluation endpoint requires an explicit `confirm` and a reason for a
real dispatch; preview mode never sends or mutates alert state.

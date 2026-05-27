# Alert Delivery Integration

## Current Delivery Model

- Alertmanager is rendered at runtime by [render-alertmanager-config.sh](/Users/sanskar/dev/Latexy/scripts/monitoring/render-alertmanager-config.sh:1).
- The rendered config supports:
  - generic webhook delivery
  - Slack webhook delivery
  - SMTP email delivery for critical alerts
- If no delivery env vars are set, Alertmanager falls back to a no-op local webhook target so the config remains valid but does not emit externally.

## Required Environment Variables

- `ALERT_WEBHOOK_URL`
- `ALERT_SLACK_WEBHOOK_URL`
- `ALERT_SLACK_CHANNEL`
- `ALERT_EMAIL_FROM`
- `ALERT_SMARTHOST`
- `ALERT_EMAIL_USER`
- `ALERT_EMAIL_PASSWORD`
- `ALERT_EMAIL_TO`

## Deployment Notes

1. Set at least one of webhook, Slack, or email in the production environment.
2. Keep webhook and Slack channels pointed at real incident destinations, not personal inboxes.
3. Use the observability smoke script to validate the rendered configuration before deploy.

## Validation

- Local and CI validation is handled by [observability-smoke.sh](/Users/sanskar/dev/Latexy/scripts/ci/observability-smoke.sh:1).
- The smoke path renders a config with representative env vars and validates it with `amtool check-config`.

#!/bin/sh
set -eu

output_path="${1:-/etc/alertmanager/alertmanager.generated.yml}"

cat >"$output_path" <<'YAML'
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'job', 'team']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'critical'
      repeat_interval: 1h
    - match:
        severity: warning
      receiver: 'default'
      repeat_interval: 4h

receivers:
  - name: 'default'
YAML

if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
  cat >>"$output_path" <<YAML
    webhook_configs:
      - url: '${ALERT_WEBHOOK_URL}'
        send_resolved: true
YAML
else
  cat >>"$output_path" <<'YAML'
    webhook_configs:
      - url: 'http://127.0.0.1:65535/alerts'
        send_resolved: true
YAML
fi

if [ -n "${ALERT_SLACK_WEBHOOK_URL:-}" ]; then
  cat >>"$output_path" <<YAML
    slack_configs:
      - api_url: '${ALERT_SLACK_WEBHOOK_URL}'
        channel: '${ALERT_SLACK_CHANNEL:-#alerts}'
        send_resolved: true
        title: '[{{ .Status | toUpper }}] {{ .CommonLabels.alertname }}'
        text: >
          {{ range .Alerts -}}
          *Alert:* {{ .Annotations.summary }}
          *Description:* {{ .Annotations.description }}
          *Severity:* {{ .Labels.severity }}
          {{ end }}
YAML
fi

cat >>"$output_path" <<'YAML'

  - name: 'critical'
YAML

if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
  cat >>"$output_path" <<YAML
    webhook_configs:
      - url: '${ALERT_WEBHOOK_URL}'
        send_resolved: true
YAML
else
  cat >>"$output_path" <<'YAML'
    webhook_configs:
      - url: 'http://127.0.0.1:65535/alerts'
        send_resolved: true
YAML
fi

if [ -n "${ALERT_SLACK_WEBHOOK_URL:-}" ]; then
  cat >>"$output_path" <<YAML
    slack_configs:
      - api_url: '${ALERT_SLACK_WEBHOOK_URL}'
        channel: '${ALERT_SLACK_CHANNEL:-#alerts}'
        send_resolved: true
        title: '[CRITICAL] {{ .CommonLabels.alertname }}'
        text: >
          {{ range .Alerts -}}
          *Alert:* {{ .Annotations.summary }}
          *Description:* {{ .Annotations.description }}
          *Severity:* {{ .Labels.severity }}
          {{ end }}
YAML
fi

if [ -n "${ALERT_EMAIL_TO:-}" ] && [ -n "${ALERT_SMARTHOST:-}" ] && [ -n "${ALERT_EMAIL_FROM:-}" ]; then
  cat >>"$output_path" <<YAML
    email_configs:
      - to: '${ALERT_EMAIL_TO}'
        from: '${ALERT_EMAIL_FROM}'
        smarthost: '${ALERT_SMARTHOST}'
        auth_username: '${ALERT_EMAIL_USER:-}'
        auth_password: '${ALERT_EMAIL_PASSWORD:-}'
        require_tls: true
        send_resolved: true
        headers:
          Subject: '[CRITICAL] Latexy Alert: {{ .CommonLabels.alertname }}'
        html: >
          {{ range .Alerts -}}
          <p><strong>Alert:</strong> {{ .Annotations.summary }}</p>
          <p><strong>Description:</strong> {{ .Annotations.description }}</p>
          <p><strong>Severity:</strong> {{ .Labels.severity }}</p>
          {{ end }}
YAML
fi

cat >>"$output_path" <<'YAML'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'job']
YAML

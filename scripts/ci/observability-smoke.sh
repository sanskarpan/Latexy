#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "==> Validating production compose rendering"
docker compose -f docker-compose.prod.yml config >/tmp/latexy-observability-compose.out

echo "==> Validating monitoring YAML and dashboard JSON"
python3 - <<'PY'
import json
from pathlib import Path

import yaml

for path in (
    Path("monitoring/prometheus.yml"),
    Path("monitoring/alert_rules.yml"),
    Path("monitoring/alertmanager.yml"),
    Path("monitoring/tempo.yml"),
):
    with path.open() as handle:
        yaml.safe_load(handle)

with Path("monitoring/grafana/provisioning/dashboards/latexy-overview.json").open() as handle:
    json.load(handle)

print("static-config-ok")
PY

echo "==> Running promtool validation"
docker run --rm --entrypoint promtool \
  -v "$PROJECT_ROOT/monitoring:/etc/prometheus" \
  prom/prometheus:latest \
  check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint promtool \
  -v "$PROJECT_ROOT/monitoring:/etc/prometheus" \
  prom/prometheus:latest \
  check rules /etc/prometheus/alert_rules.yml

echo "==> Running Alertmanager config validation"
ALERT_WEBHOOK_URL="https://alerts.example.test/webhook" \
ALERT_SLACK_WEBHOOK_URL="https://hooks.slack.example/services/T000/B000/XYZ" \
ALERT_SLACK_CHANNEL="#alerts" \
ALERT_EMAIL_FROM="alerts@example.test" \
ALERT_SMARTHOST="smtp.example.test:587" \
ALERT_EMAIL_USER="alerts" \
ALERT_EMAIL_PASSWORD="secret" \
ALERT_EMAIL_TO="ops@example.test" \
sh "$PROJECT_ROOT/scripts/monitoring/render-alertmanager-config.sh" /tmp/latexy-alertmanager.generated.yml
docker run --rm --entrypoint amtool \
  -v /tmp/latexy-alertmanager.generated.yml:/etc/alertmanager/alertmanager.generated.yml:ro \
  prom/alertmanager:latest \
  check-config /etc/alertmanager/alertmanager.generated.yml

if [[ -n "${BACKEND_URL:-}" ]]; then
  echo "==> Validating live backend metrics at ${BACKEND_URL}"
  metrics_payload="$(curl -fsS "${BACKEND_URL%/}/metrics")"
  grep -q 'latexy_http_requests_total' <<<"$metrics_payload"
  grep -q 'latexy_http_request_duration_seconds' <<<"$metrics_payload"
  grep -q 'latexy_celery_tasks_total' <<<"$metrics_payload"
fi

echo "observability-smoke-ok"

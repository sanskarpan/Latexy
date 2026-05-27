"""Observability regression tests."""

import re


async def test_health_echoes_request_id(client):
    response = await client.get("/health", headers={"X-Request-ID": "req-observability-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-observability-123"


async def test_health_generates_request_id_when_missing(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["X-Request-ID"])


async def test_metrics_endpoint_exposes_backend_metrics(client):
    health_response = await client.get("/health", headers={"X-Request-ID": "req-metrics-1"})
    assert health_response.status_code == 200

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "latexy_http_requests_total" in body
    assert 'latexy_http_requests_total{method="GET",route="/health",status_code="200"}' in body
    assert "latexy_http_request_duration_seconds_bucket" in body
    assert "latexy_celery_tasks_total" in body


async def test_frontend_telemetry_ingestion_updates_metrics(client):
    response = await client.post(
        "/telemetry/frontend",
        json={
            "kind": "web_vital",
            "name": "LCP",
            "route": "/try",
            "value": 250.5,
            "unit": "ms",
            "metadata": {"id": "metric-1"},
        },
    )
    assert response.status_code == 202

    metrics = await client.get("/metrics")
    body = metrics.text
    assert 'latexy_frontend_telemetry_events_total{kind="web_vital",name="LCP",route="/try"}' in body
    assert 'latexy_frontend_web_vital_value_bucket{le="500.0",name="LCP",route="/try"}' in body

# Tracing Architecture

## Current Backend Tracing

- Backend API uses OpenTelemetry instrumentation for:
  - FastAPI
  - SQLAlchemy
  - Redis
  - Celery
- Trace IDs and span IDs are injected into structured backend logs.
- Frontend HTTP requests attach `traceparent` and `X-Request-ID` headers.
- Celery producer and worker instrumentation propagates trace context across queue boundaries.

## Local Trace Backend

- The production compose stack now includes Grafana Tempo.
- Backend, worker, and beat services export OTLP HTTP traces to `http://tempo:4318/v1/traces`.
- Grafana is provisioned with both Prometheus and Tempo datasources.

## Key Environment Variables

- `OTEL_ENABLED`
- `OTEL_EXPORTER_MODE`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_HEADERS`
- `OTEL_SERVICE_NAME`
- `OTEL_RESOURCE_ATTRIBUTES`

## Frontend Propagation

- Browser requests generate W3C `traceparent` headers.
- Business telemetry and Web Vitals are emitted with the same request-correlation pattern.
- WebSocket connections append the current `traceparent` and `request_id` as query parameters so socket sessions can be tied back to browser activity in logs.

## Remaining Gaps

- There is not yet a browser OpenTelemetry SDK with span timelines; the frontend currently propagates trace context and emits telemetry events rather than full browser spans.
- Deeper product-flow spans can be added later if client-side sampling requirements justify it.

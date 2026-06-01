# Observability SLOs

## Scope

These SLOs define the first production baseline for Latexy core platform health.

## Service Level Indicators

### API Availability

- SLI: successful backend HTTP responses excluding expected 4xx
- Source: `latexy_http_requests_total`
- Target: 99.5% over 30 days

### API Latency

- SLI: backend p95 latency across user-facing routes
- Source: `latexy_http_request_duration_seconds`
- Target: p95 under 2.0s over 30 days

### Compile Pipeline Reliability

- SLI: compile jobs that complete successfully without worker failure
- Source: `latexy_celery_tasks_total` plus compile-result job status
- Target: 99.0% over 30 days

### Dependency Availability

- SLI: Redis exporter and Postgres exporter up-state
- Source: `up`, `redis_up`, `pg_up`
- Target: 99.9% over 30 days

## Error Budgets

- API availability 99.5%:
  - monthly error budget: 0.5%
- Dependency availability 99.9%:
  - monthly error budget: 0.1%
- Compile pipeline reliability 99.0%:
  - monthly error budget: 1.0%

## Policy

1. When an SLO is burning rapidly, feature velocity should pause until the incident is contained.
2. Rollback is preferred over hot-patching a broken deploy during active burn.
3. New risky launches should include dedicated observability checks before widening traffic.

## Ownership

- Platform owns API, queue, Redis, Postgres, and deployment health.
- Product engineering owns route-level regressions and user-flow degradation.
- Billing and external-provider owners must define service-specific error budgets once live integrations are enabled.

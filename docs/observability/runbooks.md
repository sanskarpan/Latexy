# Observability Runbooks

## ServiceDown

### Trigger

- `ServiceDown` alert for `latexy-backend`, `redis-exporter`, or `postgres-exporter`

### Immediate Checks

1. Confirm container or pod status.
2. Check deploy recency and whether a rollout is in progress.
3. Verify `/health` and `/metrics` on the backend if the process is reachable.
4. Check Redis and Postgres availability before restarting the backend.

### Likely Causes

- broken deploy or missing env var
- database outage
- Redis outage
- bad migration
- process crash loop

### Response

1. Roll back the latest deploy if the incident correlates with a release.
2. If database or Redis is unhealthy, restore the dependency first.
3. If only the backend is failing, inspect request-correlated logs using `request_id`.
4. Re-run smoke checks:
   - `/health`
   - `/metrics`
   - compile job submission and result fetch

## BackendHighErrorRate

### Trigger

- backend 5xx ratio exceeds 5% over 5 minutes

### Immediate Checks

1. Filter logs by `status_code >= 500`.
2. Group failures by route and `request_id`.
3. Check whether failures correlate with:
   - compile jobs
   - payment routes
   - auth/session lookups
   - Redis or DB latency

### Response

1. Identify the top failing route.
2. If one dependency is failing, degrade or disable that feature where possible.
3. If failures follow a deploy, roll back first and investigate second.

## SlowBackendResponses

### Trigger

- backend p95 latency exceeds 2 seconds

### Immediate Checks

1. Compare route-level latency in Grafana.
2. Check DB connection pressure and Redis connectivity.
3. Distinguish synchronous API latency from Celery queue backlog.

### Response

1. If a single route regressed, throttle or disable the path.
2. If queue-heavy flows are causing synchronous waits, move more work out of request time.
3. If DB latency is dominant, inspect connection count and slow queries.

## CeleryTaskFailures

### Trigger

- one or more Celery tasks fail within the last 5 minutes

### Immediate Checks

1. Group failures by `task_name`, `queue`, and `job_id`.
2. Verify worker health and broker connectivity.
3. Check whether failures are input-specific or global.

### Response

1. Retry one failing task manually if safe.
2. If only one queue is affected, drain or scale that queue.
3. If failures are caused by provider outages, degrade the affected feature and communicate status.

## RedisDown / RedisHighMemory

### Immediate Checks

1. Confirm Redis process/container health.
2. Check memory pressure and eviction behavior.
3. Verify Celery broker connectivity and cache-manager health.

### Response

1. Restore Redis before restarting dependent services.
2. If memory is exhausted, raise limits or reduce noisy cache usage.
3. Flush non-critical cache DBs only if absolutely necessary.

## PostgresDown / PostgresTooManyConnections / PostgresDeadlocks

### Immediate Checks

1. Confirm database availability and connection saturation.
2. Inspect recent migrations and deploys.
3. Check whether deadlocks correlate with a newly introduced write path.

### Response

1. Restore DB service health first.
2. Reduce traffic if saturation is ongoing.
3. Roll back the offending deploy when deadlocks or connection explosions started after release.

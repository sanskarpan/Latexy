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

## Redis Provider Request Capacity

### Environment and credential map

| Environment | Queue / job state | Cache / quotas / OAuth state | Capacity metadata |
| --- | --- | --- | --- |
| Local Docker | `REDIS_URL`, database 0 | `REDIS_CACHE_URL`, database 1 | Normally not applicable |
| GitHub CI | Ephemeral Redis service, database 0 | Same service, database 1 | Not applicable |
| Modal production | Dedicated `latexy-redis` Modal secret | Dedicated `latexy-redis` Modal secret | Optional Upstash Developer API credentials in that same dedicated secret |
| Vercel frontend | No Redis client | No Redis client | Not applicable |

`backend/.env` overrides the repository-root `.env` for local backend settings.
`UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are database command
credentials only. They do not configure the native `redis://` clients and cannot
read monthly account usage. Authoritative capacity monitoring needs all three of
`UPSTASH_MANAGEMENT_EMAIL`, `UPSTASH_MANAGEMENT_API_KEY`, and
`UPSTASH_REDIS_DATABASE_ID`. The configured database ID is rejected if its
provider endpoint does not match the runtime Redis host.

Production uses the separately rotatable `latexy-redis` secret, last confirmed
present and active on 2026-08-28. Never add Redis values back to the opaque
`latexy-backend-secrets`; the dedicated secret intentionally overrides any
legacy values there without risking unrelated production credentials.

### Alerts and immediate checks

- `RedisProviderCapacityWarning`: provider usage crossed the configured warning
  ratio (default 80%). Upgrade or plan a rotation immediately.
- `RedisProviderCapacityCritical`: usage crossed the critical ratio (default
  95%) or the provider reports exhaustion. Treat this as an incident.
- `RedisProviderHardExhaustion`: a real application command received
  `ERR max requests limit exceeded`. Rotate or upgrade now.
- `RedisCapacityMonitorBlind`: the management credentials are absent, invalid,
  unavailable, or point at a different database.
- `RedisApplicationDependencyDown`: the queue or cache client is failing actual
  commands, even if a standalone exporter still looks healthy.

Check `/health`, `/readyz`, `/jobs/health`, and `/metrics`. `/health` reports
queue Redis, cache Redis, and a credential-safe `redis_capacity` snapshot.
Prometheus exposes monthly requests, request limit, utilization, monitor state,
per-role command outcomes, and hard-exhaustion state. Compare these values with
the Upstash console before changing production.

The Upstash database REST token cannot provide early-warning usage data. The
Developer API database and stats endpoints are the authoritative source for
`db_request_limit` and `total_monthly_requests`; the backend caches them for five
minutes and never spends Redis requests to meter Redis requests.

### Failure policy

- Queue Redis unavailable: job/event operations fail and `/readyz` returns 503;
  coarse HTTP rate limiting deliberately fails open to preserve availability.
- Cache Redis unavailable: finite-plan quota enforcement fails closed, OAuth
  states/tickets cannot be consumed, and `/readyz` returns 503. Unlimited plans
  continue because their counter is reporting-only.
- Capacity management API unavailable: traffic continues, the monitor reports
  `unavailable`, and `RedisCapacityMonitorBlind` alerts. A monitoring-provider
  outage must not become a product outage.
- Capacity critical/exhausted or database-ID mismatch: `/health` degrades so a
  production deployment cannot be declared healthy while its configured Redis
  is about to reject or is measuring the wrong database.

### Rotation and failover

The project owner is accountable for plan upgrades; the on-call maintainer with
Upstash, Modal, and GitHub Production access executes and verifies rotation.

1. Prefer upgrading the existing database before its cap is reached. This keeps
   in-flight job events, OAuth tickets, rate-limit windows, and quota counters.
2. If a new database is required, obtain its native TLS Redis URL in addition to
   its REST pair. A REST URL/token alone cannot replace `REDIS_URL`.
3. Drain new job submissions when practical. An emergency database switch can
   invalidate 24-hour job metadata and short-lived OAuth states/tickets; users
   may need to retry those operations.
4. Build a temporary dotenv file containing the complete replacement secret:
   `REDIS_URL`, `REDIS_CACHE_URL`, `CELERY_BROKER_URL`,
   `CELERY_RESULT_BACKEND`, and, when enabled, the three Upstash management
   fields. Use the same serverless database URL for queue/cache rather than
   unsupported database-number suffixes.
5. Replace the dedicated secret with
   `modal secret create --env main --force --from-dotenv <path> latexy-redis`.
   Keep credentials out of command-line arguments and shell history, then
   securely remove the temporary file.
6. Trigger the `Deploy Modal Backend` GitHub workflow against the exact current
   `main` SHA. Watch migration, rolling deploy, and health verification to green.
7. Verify `/health` is `healthy`, `/readyz` is `ready`, `/jobs/health` is
   `healthy`, both Redis roles are `ok`, and capacity reports the intended host's
   database. Submit and observe a disposable job plus an OAuth invalid-state
   probe before closing the incident.
8. Retain the old database until the maximum in-flight metadata window has
   elapsed when the provider plan permits it. Record the rotation, reason,
   deployment SHA, workflow run, and production evidence in the GitHub issue.

## PostgresDown / PostgresTooManyConnections / PostgresDeadlocks

### Immediate Checks

1. Confirm database availability and connection saturation.
2. Inspect recent migrations and deploys.
3. Check whether deadlocks correlate with a newly introduced write path.

### Response

1. Restore DB service health first.
2. Reduce traffic if saturation is ongoing.
3. Roll back the offending deploy when deadlocks or connection explosions started after release.

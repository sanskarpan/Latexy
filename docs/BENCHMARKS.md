# BENCHMARKS — Latexy Production Audit
**Date:** 2026-06-11  
**Method:** Static analysis + code inspection. Live benchmarks require a running stack.

---

## Methodology

Live load/stress tests were not executed during this audit (they require a running deployment with production-like data volume). This document records:
1. Static analysis findings with estimated performance impact
2. Configuration parameters discovered in code
3. Benchmarks that MUST be run before production go-live
4. Expected baselines based on system architecture

---

## Environment (from code inspection)

| Component | Version | Config Source |
|-----------|---------|--------------|
| FastAPI | latest | `requirements.txt` |
| SQLAlchemy async | 2.x | asyncpg driver |
| PostgreSQL | 14+ | Neon or self-hosted |
| Redis | 7+ | docker-compose |
| Celery | 5.x | `celery_app.py` |
| Next.js | 14 | `package.json` |
| Python | 3.13 (dev) / 3.11 (prod) | Dockerfiles |

---

## Database Configuration (from code)

| Parameter | Current Value | Recommended |
|-----------|--------------|-------------|
| SQLAlchemy `pool_size` | Not set (default: 5) | 10–20 for API, 3–5 per worker |
| `max_overflow` | Not set (default: 10) | 10 for API |
| `pool_timeout` | Not set (default: 30s) | 10s (fail fast) |
| `pool_pre_ping` | Not set | `True` (detect stale connections) |
| Effective max connections | 15 per process | Set explicitly |

**Risk:** With 4 uvicorn workers (prod Dockerfile) and 6 Celery workers, default pool means up to 15×10 = 150 potential DB connections, likely exceeding the Neon connection limit.

---

## Redis Configuration (from code)

| Parameter | Current Value | Recommended |
|-----------|--------------|-------------|
| Stream MAXLEN | 10,000 events/job | 1,000 (more than sufficient) |
| Job state TTL | 86,400s (24h) | OK |
| Result TTL | 86,400s (24h) | OK |
| SCAN vs KEYS | KEYS used in cleanup | Switch to SCAN cursor loop |
| Pub/Sub cleanup | Listener tasks | Verify cleanup on job complete |

---

## Static Performance Findings (ranked by impact)

### CRITICAL — Analytics memory OOM risk
**File:** `backend/app/services/analytics_service.py`

```python
# Current (dangerous):
compilations = (await db.execute(select(Compilation).where(...))).scalars().all()
# ^ Loads ALL compilation rows into Python memory, no LIMIT

# Estimated impact:
# 1 user × 1000 compilations × ~2KB/row = 2MB per request (acceptable)
# 1 user × 50,000 compilations × ~2KB/row = 100MB per request (OOM risk)
# 100 concurrent dashboard loads = potential cascade failure
```

**Benchmark to run:** `locust -f locustfile.py --headless -u 10 -r 2 -t 30s --host http://localhost:8030`  
Target: `GET /analytics/me?days=365` P99 < 500ms under 10 concurrent users.

---

### HIGH — Session table sequential scan on every auth
**File:** `backend/app/middleware/auth_middleware.py`

Every authenticated API call runs:
```sql
SELECT * FROM session WHERE token = $1
```
Without an index on `session.token`, this is a sequential scan. With 10,000 active sessions:
- Estimated scan time: 5–50ms per request
- Under 100 req/s: 500–5000ms/s wasted on auth alone

**Fix:** Add `idx_session_token` index (see DB-003).  
**Expected improvement after fix:** Auth overhead < 1ms per request.

---

### HIGH — N+1 queries (all fixed)

| Endpoint | Before | After | Savings at N=50 |
|----------|--------|-------|-----------------|
| `GET /tenants/me` | N+1 tenant queries | 1 bulk query | 49 queries saved |
| `GET /tenants/{id}/members` | N+1 user queries | 1 JOIN query | N-1 queries saved |
| `GET /career/{id}` | N+1 role queries | 1 bulk query | N-1 queries saved |

---

### MEDIUM — Conversion funnel full-table Python filter

```python
# Current (dangerous):
events = (await db.execute(select(UsageAnalytics))).scalars().all()
funnel = [e for e in events if e.event_metadata.get('page') == 'landing']
```

With 1M analytics events, this loads ~500MB into Python. Full table scan + Python iteration.

**Estimated latency:** 2–10 seconds per funnel request at 100K rows.  
**After fix (SQL filter):** < 50ms.

---

### MEDIUM — Redis `KEYS` pattern scan (blocking)

```python
# Current:
keys = redis_client.keys("latexy:job:*")
```

Redis `KEYS` is O(N) on all keys and blocks the entire Redis instance for its duration.  
With 10,000 active job keys: estimated 5–50ms of Redis stall.  
**Fix:** Replace with `SCAN` cursor loop.

---

## Required Benchmarks Before Production

### 1. API Latency Baseline

```bash
# Install wrk or hey
hey -n 1000 -c 50 -m GET http://localhost:8030/health

# Target SLOs:
# P50 < 50ms
# P95 < 200ms  
# P99 < 500ms
# Error rate < 0.1%
```

### 2. Analytics Endpoint Under Load

```bash
# After adding DB-side aggregation and caching:
hey -n 200 -c 20 http://localhost:8030/analytics/me?days=90

# Target: P99 < 500ms (from cache: < 20ms)
```

### 3. LaTeX Compilation Throughput

```bash
# Submit 20 concurrent compile jobs:
# Expected: queue depth grows, workers drain at ~1 compile/10s each
# Verify: no stuck jobs, all complete or fail within timeout
# Monitor: docker stats for zombie pdflatex processes
```

### 4. WebSocket Event Delivery Latency

```bash
# Measure time from task start to first WS event delivery
# Expected: < 100ms
# Measure time for full event replay on reconnect
# Expected: < 500ms for 100 events
```

### 5. Database Connection Pool Saturation Test

```bash
# Saturate with concurrent authenticated requests
ab -n 500 -c 100 -H "Authorization: Bearer TOKEN" http://localhost:8030/resumes/

# Verify: no "QueuePool limit of size X overflow Y reached" errors
# Verify: P99 < 1s even under pool pressure
```

### 6. Frontend Bundle Analysis

```bash
cd frontend && npx next build && npx @next/bundle-analyzer
# Target: initial JS bundle < 200KB gzipped
# Check for: large tree-shaking failures, unoptimized Monaco bundle
```

---

## Soak Test Recommendations

Run the following for 30 minutes with realistic traffic:
- 5 concurrent users compiling LaTeX documents
- 2 concurrent users running optimizations
- 10 concurrent dashboard views (analytics)

Monitor:
- Redis memory growth (expect linear with active jobs, should not grow unboundedly)
- Worker RSS memory (should return to baseline between jobs)
- DB connection pool usage (should not exhaust)
- Temp directory size in `/tmp` (should not accumulate if cleanup works)
- Stuck jobs in `processing` state (should be 0 after 10 min)

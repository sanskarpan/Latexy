"""E2E tests for liveness/readiness probes and the Prometheus scrape endpoint."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_livez_always_ok(client: AsyncClient):
    """/livez is a pure process liveness check — always 200, no dependency checks."""
    resp = await client.get("/livez")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


async def test_readyz_ok_when_dependencies_up(client: AsyncClient):
    """/readyz returns 200 + ready when DB and Redis are reachable.

    The app lifespan does not run under the in-process ASGI transport, so the
    Redis manager has no live client — stub a healthy async ping to exercise
    the ready path.
    """
    from app.api import routes

    class _FakeRedis:
        async def ping(self):
            return True

    with patch.object(routes._redis_manager, "redis_client", _FakeRedis()), \
         patch.object(routes._redis_manager, "redis_cache_client", _FakeRedis()):
        resp = await client.get("/readyz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"
    assert body["checks"]["redis_cache"] == "ok"


async def test_readyz_503_when_cache_redis_is_down(client: AsyncClient):
    """Security/quota metadata Redis is critical even when the queue Redis works."""
    from app.api import routes

    class _FakeRedis:
        async def ping(self):
            return True

    with patch.object(routes._redis_manager, "redis_client", _FakeRedis()), \
         patch.object(routes._redis_manager, "redis_cache_client", None):
        resp = await client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["checks"]["redis"] == "ok"
    assert resp.json()["checks"]["redis_cache"] == "unavailable"


async def test_readyz_503_when_database_down(client: AsyncClient):
    """/readyz returns 503 not_ready when the DB probe raises (unlike /health)."""
    from app.api import routes

    def _boom(*_a, **_kw):
        raise RuntimeError("db down")

    with patch.object(routes, "get_async_db_session", _boom):
        resp = await client.get("/readyz")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"


async def test_metrics_exposes_new_series(client: AsyncClient):
    """/metrics returns Prometheus text exposition including the new metric families."""
    # Emit at least one sample so the family shows up in the registry output.
    from app.core import observability

    observability.record_compile("success", duration_seconds=1.2, pdf_bytes=42_000, pages=2)
    observability.record_llm_call(
        "openai", "gpt-4o", "success",
        total_seconds=3.0, prompt_build_seconds=0.1, provider_call_seconds=2.8,
        prompt_tokens=100, completion_tokens=200, total_tokens=300,
    )
    observability.record_ats_score("comprehensive", "success", duration_seconds=0.3)
    observability.record_job_submitted("optimize", authenticated=True)
    observability.record_trial_use("allowed")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    for family in (
        "latexy_llm_latency_seconds",
        "latexy_llm_tokens_total",
        "latexy_compiles_total",
        "latexy_compile_duration_seconds",
        "latexy_ats_scores_total",
        "latexy_jobs_submitted_total",
        "latexy_trial_uses_total",
        "latexy_db_pool_connections",
        "latexy_redis_provider_monthly_requests",
        "latexy_redis_provider_request_limit",
        "latexy_redis_provider_request_utilization_ratio",
        "latexy_redis_provider_capacity_status",
    ):
        assert family in text, f"expected metric family {family} in /metrics output"


# --- object storage -------------------------------------------------------
# /health probed the database and Redis but not object storage, so in production
# it reported {"status": "healthy"} while every template thumbnail and preview PDF
# returned 502 Storage unavailable — 0 of 147 served. The outage was invisible to
# anything watching health.


async def test_health_reports_storage_ok_when_reachable(client: AsyncClient):
    from app.services import storage_service

    class _FakeRedis:
        async def ping(self):
            return True

    from app.api import routes

    with patch.object(storage_service, "probe", lambda: (True, "ok")), \
         patch.object(routes._redis_manager, "redis_client", _FakeRedis()), \
         patch.object(routes._redis_manager, "redis_cache_client", _FakeRedis()):
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["storage"] == "ok"
    assert body["redis_cache"] == "ok"
    assert body["status"] == "healthy"


async def test_health_degrades_at_critical_provider_capacity(client: AsyncClient):
    from app.api import routes
    from app.services import storage_service
    from app.services.redis_capacity_service import RedisCapacitySnapshot

    class _FakeRedis:
        async def ping(self):
            return True

    capacity = RedisCapacitySnapshot(
        provider="upstash",
        status="critical",
        configured=True,
        monthly_requests=950,
        request_limit=1000,
        utilization_ratio=0.95,
    )
    with patch.object(storage_service, "probe", lambda: (True, "ok")), \
         patch.object(routes._redis_manager, "redis_client", _FakeRedis()), \
         patch.object(routes._redis_manager, "redis_cache_client", _FakeRedis()), \
         patch.object(routes.redis_capacity_service, "snapshot", AsyncMock(return_value=capacity)):
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["redis_capacity"]["status"] == "critical"


async def test_health_degrades_when_storage_unreachable(client: AsyncClient):
    """The exact production failure: DB and Redis fine, storage dead."""
    from app.api import routes
    from app.services import storage_service

    class _FakeRedis:
        async def ping(self):
            return True

    with patch.object(storage_service, "probe", lambda: (False, "EndpointConnectionError")), \
         patch.object(routes._redis_manager, "redis_client", _FakeRedis()):
        resp = await client.get("/health")

    # Still 200 so availability probes that only check the status code keep working.
    assert resp.status_code == 200
    body = resp.json()
    assert body["storage"] == "unavailable"
    assert body["status"] == "degraded", (
        "storage being down must not report as healthy — that is what hid the outage"
    )
    assert body["database"] == "ok"
    assert body["redis"] == "ok"


async def test_health_survives_a_raising_storage_probe(client: AsyncClient):
    """A probe that raises must degrade, not 500 the health endpoint."""
    from app.api import routes
    from app.services import storage_service

    def _boom():
        raise RuntimeError("boto3 exploded")

    class _FakeRedis:
        async def ping(self):
            return True

    with patch.object(storage_service, "probe", _boom), \
         patch.object(routes._redis_manager, "redis_client", _FakeRedis()):
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["storage"] == "unavailable"

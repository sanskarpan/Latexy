"""Regression coverage for Redis provider capacity monitoring."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import redis
import redis.asyncio as aioredis
import respx
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.observability import classify_redis_error
from app.core.redis import ObservedAsyncRedis, ObservedSyncRedis
from app.services.redis_capacity_service import RedisCapacityService

_DATABASE_ID = "db-capacity-test"
_DATABASE_URL = f"https://api.upstash.com/v2/redis/database/{_DATABASE_ID}"
_STATS_URL = f"https://api.upstash.com/v2/redis/stats/{_DATABASE_ID}"


def _configure_monitor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "REDIS_URL", "rediss://default:secret@knowing-cow-120053.upstash.io:6379")
    monkeypatch.setattr(settings, "REDIS_CACHE_URL", "rediss://default:secret@knowing-cow-120053.upstash.io:6379")
    monkeypatch.setattr(settings, "UPSTASH_MANAGEMENT_EMAIL", "ops@example.com")
    monkeypatch.setattr(settings, "UPSTASH_MANAGEMENT_API_KEY", "management-secret")
    monkeypatch.setattr(settings, "UPSTASH_REDIS_DATABASE_ID", _DATABASE_ID)
    monkeypatch.setattr(settings, "REDIS_CAPACITY_WARNING_RATIO", 0.80)
    monkeypatch.setattr(settings, "REDIS_CAPACITY_CRITICAL_RATIO", 0.95)
    monkeypatch.setattr(settings, "REDIS_CAPACITY_CACHE_SECONDS", 300)


def test_capacity_threshold_order_is_validated(monkeypatch):
    monkeypatch.setenv("SKIP_ENV_VALIDATION", "true")
    with pytest.raises(ValidationError, match="WARNING_RATIO must be lower"):
        Settings(
            _env_file=None,
            REDIS_CAPACITY_WARNING_RATIO=0.95,
            REDIS_CAPACITY_CRITICAL_RATIO=0.90,
        )


def test_partial_management_credentials_are_rejected(monkeypatch):
    monkeypatch.setenv("SKIP_ENV_VALIDATION", "true")
    with pytest.raises(ValidationError, match="must be configured together"):
        Settings(
            _env_file=None,
            UPSTASH_MANAGEMENT_EMAIL="ops@example.com",
        )


async def test_capacity_monitor_is_explicitly_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "rediss://default:secret@knowing-cow-120053.upstash.io:6379")
    monkeypatch.setattr(settings, "REDIS_CACHE_URL", "rediss://default:secret@knowing-cow-120053.upstash.io:6379")
    monkeypatch.setattr(settings, "UPSTASH_MANAGEMENT_EMAIL", "")
    monkeypatch.setattr(settings, "UPSTASH_MANAGEMENT_API_KEY", "")
    monkeypatch.setattr(settings, "UPSTASH_REDIS_DATABASE_ID", "")

    snapshot = await RedisCapacityService().snapshot()

    assert snapshot.status == "unconfigured"
    assert snapshot.configured is False
    assert "management" not in str(snapshot.public_dict()).lower()


@pytest.mark.parametrize(
    ("monthly_requests", "expected_status"),
    [
        (10, "ok"),
        (800, "warning"),
        (950, "critical"),
        (1000, "exhausted"),
        (1200, "exhausted"),
    ],
)
@respx.mock
async def test_capacity_thresholds_use_authoritative_provider_values(
    monkeypatch,
    monthly_requests,
    expected_status,
):
    _configure_monitor(monkeypatch)
    respx.get(_DATABASE_URL).mock(return_value=httpx.Response(200, json={
        "endpoint": "knowing-cow-120053",
        "state": "active",
        "db_request_limit": 1000,
    }))
    respx.get(_STATS_URL).mock(return_value=httpx.Response(200, json={
        "total_monthly_requests": monthly_requests,
    }))

    snapshot = await RedisCapacityService().snapshot()

    assert snapshot.status == expected_status
    assert snapshot.monthly_requests == monthly_requests
    assert snapshot.request_limit == 1000
    assert snapshot.utilization_ratio == monthly_requests / 1000
    assert "management-secret" not in str(snapshot.public_dict())


@respx.mock
async def test_capacity_snapshot_is_cached(monkeypatch):
    _configure_monitor(monkeypatch)
    database_route = respx.get(_DATABASE_URL).mock(return_value=httpx.Response(200, json={
        "endpoint": "knowing-cow-120053.upstash.io",
        "state": "active",
        "db_request_limit": 1000,
    }))
    stats_route = respx.get(_STATS_URL).mock(return_value=httpx.Response(200, json={
        "total_monthly_requests": 20,
    }))
    service = RedisCapacityService()

    first = await service.snapshot()
    second = await service.snapshot()

    assert first is second
    assert database_route.call_count == 1
    assert stats_route.call_count == 1


@respx.mock
async def test_capacity_database_id_must_match_runtime_redis_host(monkeypatch):
    _configure_monitor(monkeypatch)
    respx.get(_DATABASE_URL).mock(return_value=httpx.Response(200, json={
        "endpoint": "different-database-999999",
        "state": "active",
        "db_request_limit": 1000,
    }))
    respx.get(_STATS_URL).mock(return_value=httpx.Response(200, json={
        "total_monthly_requests": 20,
    }))

    snapshot = await RedisCapacityService().snapshot()

    assert snapshot.status == "misconfigured"
    assert snapshot.monthly_requests is None


@respx.mock
async def test_capacity_api_failure_is_visible_but_secret_safe(monkeypatch, caplog):
    _configure_monitor(monkeypatch)
    respx.get(_DATABASE_URL).mock(return_value=httpx.Response(503, text="unavailable"))
    respx.get(_STATS_URL).mock(return_value=httpx.Response(503, text="unavailable"))

    snapshot = await RedisCapacityService().snapshot()

    assert snapshot.status == "unavailable"
    assert "management-secret" not in caplog.text


def test_redis_provider_errors_have_stable_alert_classes():
    assert classify_redis_error(RuntimeError("ERR max requests limit exceeded")) == "request_quota_exhausted"
    assert classify_redis_error(TimeoutError("operation timed out")) == "timeout"
    assert classify_redis_error(ConnectionError("connection refused")) == "connection"
    assert classify_redis_error(RuntimeError("ERR max commands per second exceeded")) == "throttled"
    assert classify_redis_error(RuntimeError("WRONGTYPE")) == "other"


async def test_async_redis_client_records_success_without_an_extra_command():
    client = ObservedAsyncRedis.from_url(
        "redis://localhost:6379/0",
        dependency_role="cache",
        decode_responses=True,
    )
    execute = AsyncMock(return_value=True)
    with patch.object(aioredis.Redis, "execute_command", execute), \
         patch("app.core.redis.record_redis_command") as record:
        assert await client.ping() is True

    execute.assert_awaited_once()
    record.assert_called_once_with("cache")
    await client.aclose()


def test_sync_redis_client_records_provider_error_without_swallowing_it():
    client = ObservedSyncRedis.from_url(
        "redis://localhost:6379/0",
        dependency_role="queue",
        decode_responses=True,
    )
    error = redis.ResponseError("ERR max requests limit exceeded")
    execute = Mock(side_effect=error)
    with patch.object(redis.Redis, "execute_command", execute), \
         patch("app.core.redis.record_redis_command") as record:
        with pytest.raises(redis.ResponseError, match="max requests"):
            client.ping()

    execute.assert_called_once()
    record.assert_called_once_with("queue", error)
    client.close()

"""Regression tests for process-owned Redis client cleanup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.core.redis as redis_module


@pytest.fixture
def isolated_redis_globals():
    """Keep lifecycle tests from borrowing clients owned by another test."""
    manager = redis_module.redis_manager
    names = (
        "redis_client",
        "redis_cache_client",
        "sync_redis_client",
        "sync_redis_cache_client",
        "_fallback_sync_redis_client",
    )
    module_values = {name: getattr(redis_module, name) for name in names}
    manager_values = {
        name: getattr(manager, name)
        for name in (
            "redis_client",
            "redis_cache_client",
            "sync_redis_client",
            "sync_redis_cache_client",
        )
    }
    for name in names:
        setattr(redis_module, name, None)
    for name in manager_values:
        setattr(manager, name, None)

    yield manager

    for name, value in module_values.items():
        setattr(redis_module, name, value)
    for name, value in manager_values.items():
        setattr(manager, name, value)


@pytest.mark.asyncio
async def test_close_redis_closes_unique_clients_and_clears_every_reference(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    queue = AsyncMock()
    cache = AsyncMock()
    sync_queue = MagicMock()
    sync_cache = MagicMock()
    fallback = MagicMock()

    redis_module.redis_client = queue
    manager.redis_client = queue
    redis_module.redis_cache_client = cache
    manager.redis_cache_client = cache
    redis_module.sync_redis_client = sync_queue
    manager.sync_redis_client = sync_queue
    redis_module.sync_redis_cache_client = sync_cache
    manager.sync_redis_cache_client = sync_cache
    redis_module._fallback_sync_redis_client = fallback

    await manager.close_redis()

    queue.aclose.assert_awaited_once()
    cache.aclose.assert_awaited_once()
    sync_queue.close.assert_called_once()
    sync_cache.close.assert_called_once()
    fallback.close.assert_called_once()
    assert redis_module.redis_client is None
    assert redis_module.redis_cache_client is None
    assert redis_module.sync_redis_client is None
    assert redis_module.sync_redis_cache_client is None
    assert redis_module._fallback_sync_redis_client is None
    assert manager.redis_client is None
    assert manager.redis_cache_client is None
    assert manager.sync_redis_client is None
    assert manager.sync_redis_cache_client is None


@pytest.mark.asyncio
async def test_failed_initialization_closes_every_partial_pool(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    queue = AsyncMock()
    cache = AsyncMock()
    cache.ping.side_effect = ConnectionError("cache unavailable")
    sync_queue = MagicMock()
    sync_cache = MagicMock()

    with (
        patch.object(
            redis_module.ObservedAsyncRedis,
            "from_url",
            side_effect=[queue, cache],
        ),
        patch.object(
            redis_module.ObservedSyncRedis,
            "from_url",
            side_effect=[sync_queue, sync_cache],
        ),
    ):
        with pytest.raises(ConnectionError, match="cache unavailable"):
            await manager.init_redis()

    queue.aclose.assert_awaited_once()
    cache.aclose.assert_awaited_once()
    sync_queue.close.assert_called_once()
    sync_cache.close.assert_called_once()
    assert redis_module.redis_client is None
    assert redis_module.redis_cache_client is None
    assert redis_module.sync_redis_client is None
    assert redis_module.sync_redis_cache_client is None


@pytest.mark.asyncio
async def test_failed_initialization_does_not_log_credential_bearing_exception(
    isolated_redis_globals,
    caplog,
) -> None:
    manager = isolated_redis_globals
    leaked_secret = "redis://private-user:private-password@cache.example:6379/0"

    with patch.object(
        redis_module.ObservedAsyncRedis,
        "from_url",
        side_effect=ConnectionError(leaked_secret),
    ):
        with pytest.raises(ConnectionError):
            await manager.init_redis()

    assert leaked_secret not in caplog.text
    assert "private-password" not in caplog.text
    assert "ConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_one_broken_client_does_not_skip_remaining_cleanup(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    broken = AsyncMock()
    broken.aclose.side_effect = RuntimeError("loop already closed")
    healthy = AsyncMock()
    sync_client = MagicMock()

    redis_module.redis_client = broken
    redis_module.redis_cache_client = healthy
    redis_module.sync_redis_client = sync_client

    await manager.close_redis()

    broken.aclose.assert_awaited_once()
    healthy.aclose.assert_awaited_once()
    sync_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_does_not_capture_a_concurrently_reinitialized_sync_client(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    async_client = AsyncMock()
    old_sync = MagicMock()
    replacement_sync = MagicMock()

    async def _install_replacement_during_async_close() -> None:
        redis_module.sync_redis_client = replacement_sync

    async_client.aclose.side_effect = _install_replacement_during_async_close
    redis_module.redis_client = async_client
    redis_module.sync_redis_client = old_sync

    await manager.close_redis()

    old_sync.close.assert_called_once()
    replacement_sync.close.assert_not_called()
    assert redis_module.sync_redis_client is replacement_sync


def test_sync_cleanup_is_idempotent(isolated_redis_globals) -> None:
    manager = isolated_redis_globals
    client = MagicMock()
    redis_module._fallback_sync_redis_client = client

    manager.close_sync_redis()
    manager.close_sync_redis()

    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_observed_factories_own_their_connection_pools() -> None:
    async_client = redis_module.ObservedAsyncRedis.from_url(
        "redis://localhost:6379/15", dependency_role="queue"
    )
    sync_client = redis_module.ObservedSyncRedis.from_url(
        "redis://localhost:6379/15", dependency_role="queue"
    )

    assert async_client.auto_close_connection_pool is True
    assert sync_client.auto_close_connection_pool is True
    assert isinstance(async_client.connection_pool, redis_module.aioredis.BlockingConnectionPool)
    assert isinstance(sync_client.connection_pool, redis_module.redis.BlockingConnectionPool)

    await async_client.aclose()
    sync_client.close()


def test_sync_initialization_publishes_healthy_worker_clients(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    queue = MagicMock()
    cache = MagicMock()

    with patch.object(
        redis_module.ObservedSyncRedis,
        "from_url",
        side_effect=[queue, cache],
    ):
        manager.init_sync_redis()

    queue.ping.assert_called_once_with()
    cache.ping.assert_called_once_with()
    assert redis_module.sync_redis_client is queue
    assert redis_module.sync_redis_cache_client is cache
    assert manager.health_check_sync() == {
        "redis_queue": True,
        "redis_cache": True,
        "redis_sync": True,
    }


def test_failed_sync_initialization_closes_new_clients_without_publishing(
    isolated_redis_globals,
) -> None:
    manager = isolated_redis_globals
    queue = MagicMock()
    cache = MagicMock()
    cache.ping.side_effect = ConnectionError("cache unavailable")

    with patch.object(
        redis_module.ObservedSyncRedis,
        "from_url",
        side_effect=[queue, cache],
    ):
        with pytest.raises(ConnectionError, match="cache unavailable"):
            manager.init_sync_redis()

    queue.close.assert_called_once_with()
    cache.close.assert_called_once_with()
    assert redis_module.sync_redis_client is None
    assert redis_module.sync_redis_cache_client is None

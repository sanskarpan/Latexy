"""Regression tests for process-owned Redis client cleanup."""

from unittest.mock import AsyncMock, MagicMock

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

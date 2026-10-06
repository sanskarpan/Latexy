"""Regression tests for one-shot service Redis client ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.entitlement_service import EntitlementService
from app.services.feature_flag_service import FeatureFlagService


class TestFeatureFlagRedisLifecycle:
    def test_sync_fallback_closes_client_when_read_fails(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("read failed")

        with (
            patch(
                "app.workers.event_publisher.get_worker_redis",
                side_effect=RuntimeError("not in a worker"),
            ),
            patch("redis.from_url", return_value=client),
        ):
            assert FeatureFlagService().sync_get_flag("task_priority") is True

        client.close.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_async_push_closes_client_when_write_fails(self) -> None:
        client = AsyncMock()
        client.set.side_effect = ConnectionError("write failed")

        with patch("redis.asyncio.from_url", return_value=client):
            await FeatureFlagService()._push_to_redis("task_priority", True)

        client.aclose.assert_awaited_once_with()


class TestEntitlementRedisLifecycle:
    @pytest.mark.asyncio
    async def test_async_read_closes_client_when_read_fails(self) -> None:
        client = AsyncMock()
        client.get.side_effect = ConnectionError("read failed")

        with patch("redis.asyncio.from_url", return_value=client):
            assert await EntitlementService()._read_from_redis() is None

        client.aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_async_push_closes_client_when_write_fails(self) -> None:
        client = AsyncMock()
        client.set.side_effect = ConnectionError("write failed")

        with patch("redis.asyncio.from_url", return_value=client):
            await EntitlementService()._push_to_redis({"kill": {}, "matrix": {}})

        client.aclose.assert_awaited_once_with()

    def test_sync_fallback_closes_client_when_read_fails(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("read failed")

        with (
            patch(
                "app.workers.event_publisher.get_worker_redis",
                side_effect=RuntimeError("not in a worker"),
            ),
            patch("redis.from_url", return_value=client),
        ):
            assert EntitlementService()._sync_read_from_redis() is None

        client.close.assert_called_once_with()

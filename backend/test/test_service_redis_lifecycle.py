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


class TestEntitlementDatabaseLifecycle:
    @pytest.mark.asyncio
    async def test_async_snapshot_does_not_create_a_redis_connection(self) -> None:
        from contextlib import asynccontextmanager

        db = AsyncMock()
        db.execute.return_value = MagicMock(all=lambda: [])

        @asynccontextmanager
        async def session():
            try:
                yield db
            finally:
                await db.close()

        with (
            patch("app.database.connection.get_async_db_session", session),
            patch("redis.asyncio.from_url", side_effect=AssertionError("Redis is not entitlement authority")),
        ):
            assert (await EntitlementService()._get_blob())["kill"] == {}
        db.close.assert_awaited_once()

    def test_sync_snapshot_closes_database_connection_when_read_fails(self) -> None:
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = ConnectionError("read failed")
        with patch("psycopg2.connect", return_value=connection):
            assert EntitlementService().sync_has_feature("d01", "free") is False
        connection.close.assert_called_once_with()

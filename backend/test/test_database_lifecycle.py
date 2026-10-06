"""Regression tests for application database singleton teardown."""

from unittest.mock import AsyncMock

import pytest

import app.database.connection as connection


@pytest.mark.asyncio
async def test_close_db_disposes_and_clears_published_singletons() -> None:
    previous_engine = connection.engine
    previous_session_local = connection.SessionLocal
    test_engine = AsyncMock()
    connection.engine = test_engine
    connection.SessionLocal = object()

    try:
        await connection.close_db()

        test_engine.dispose.assert_awaited_once_with()
        assert connection.engine is None
        assert connection.SessionLocal is None

        await connection.close_db()
        test_engine.dispose.assert_awaited_once_with()
    finally:
        connection.engine = previous_engine
        connection.SessionLocal = previous_session_local

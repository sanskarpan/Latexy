"""Sync integration helpers dispose every DB pool before their loop exits."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database import connection
from test import test_imported_identity_db, test_resume_durable_ledger


@pytest.mark.parametrize("module,helper", [
    (test_imported_identity_db, "run"),
    (test_resume_durable_ledger, "database"),
])
@pytest.mark.parametrize("operation_fails", [False, True])
def test_short_loop_helpers_close_auxiliary_pool_on_owner_loop(module, helper, operation_fails, monkeypatch):
    private_engine = AsyncMock()
    auxiliary_engine = AsyncMock()
    session = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(module, "create_async_engine", MagicMock(return_value=private_engine))
    monkeypatch.setattr(module, "async_sessionmaker", MagicMock(return_value=factory))
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    owner_loop = None

    async def close_auxiliary():
        assert asyncio.get_running_loop() is owner_loop
        assert not owner_loop.is_closed()

    auxiliary_engine.dispose.side_effect = close_auxiliary

    async def operation(_argument):
        nonlocal owner_loop
        owner_loop = asyncio.get_running_loop()
        connection.engine = auxiliary_engine
        connection.SessionLocal = object()
        if operation_fails:
            raise ValueError("controlled callback failure")
        return "completed"

    if operation_fails:
        with pytest.raises(ValueError, match="controlled callback failure"):
            getattr(module, helper)(operation)
    else:
        assert getattr(module, helper)(operation) == "completed"
    auxiliary_engine.dispose.assert_awaited_once_with()
    private_engine.dispose.assert_awaited_once_with()
    assert connection.engine is None
    assert connection.SessionLocal is None
    assert owner_loop.is_closed()

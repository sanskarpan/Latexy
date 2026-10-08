"""Worker readiness fails closed before a partial native import can consume jobs."""
import sys
from unittest.mock import Mock

import pytest
from celery.exceptions import WorkerTerminate

from app.core import worker_runtime
from app.core.celery_app import prepare_worker_parent


def test_parent_preparation_loads_native_driver_without_opening_connections(monkeypatch):
    import asyncpg

    connect = Mock(side_effect=AssertionError("startup opened a database connection"))
    monkeypatch.setattr(asyncpg, "connect", connect)
    create_engine = Mock(side_effect=AssertionError("startup created a database engine"))
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", create_engine)
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        prepare_worker_parent()
        assert "asyncpg.protocol.protocol" in sys.modules
        assert "app.services.render_engine.retention" in sys.modules
        assert not connect.called
        create_engine.assert_not_called()
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()


def test_import_failure_aborts_readiness_and_is_not_memoized(monkeypatch):
    imported = Mock(side_effect=ImportError("synthetic missing dependency"))
    monkeypatch.setattr(worker_runtime, "import_module", imported)
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        with pytest.raises(WorkerTerminate):
            prepare_worker_parent()
        assert worker_runtime.prepare_worker_runtime.cache_info().currsize == 0
        imported.side_effect = None
        prepare_worker_parent()
        assert worker_runtime.prepare_worker_runtime.cache_info().currsize == 1
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()

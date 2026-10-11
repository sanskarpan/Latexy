"""Worker readiness fails closed before a partial native import can consume jobs."""
import sys
from unittest.mock import Mock

import pytest
from celery.exceptions import WorkerTerminate

from app.core import worker_runtime
from app.core.celery_app import prepare_worker_parent


def test_parent_preparation_loads_native_driver_without_opening_connections(monkeypatch):
    import asyncpg

    from app.services.render_engine import retention

    # Import aliases before patching: a lazy module's `from sqlalchemy import`
    # must not retain this test's mock after monkeypatch restores sqlalchemy.
    # The clean-process test below guards initial imports without suite leakage.
    connect = Mock(side_effect=AssertionError("startup opened a database connection"))
    monkeypatch.setattr(asyncpg, "connect", connect)
    create_engine = Mock(side_effect=AssertionError("startup created a database engine"))
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", create_engine)
    monkeypatch.setattr(retention, "create_async_engine", create_engine)
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        prepare_worker_parent()
        assert "asyncpg.protocol.protocol" in sys.modules
        assert "app.services.render_engine.retention" in sys.modules
        from app.database.connection import Base

        assert Base.registry.mappers
        assert all(mapper.configured for mapper in Base.registry.mappers)
        assert not connect.called
        create_engine.assert_not_called()
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()


def test_clean_process_preparation_configures_models_before_any_database_io():
    import subprocess
    from pathlib import Path

    result = subprocess.run([sys.executable, "-c", """
from unittest.mock import Mock
import asyncpg
import sqlalchemy.ext.asyncio
asyncpg.connect = Mock(side_effect=AssertionError('Database connection during preparation'))
sqlalchemy.ext.asyncio.create_async_engine = Mock(side_effect=AssertionError('Engine during preparation'))
from app.core.worker_runtime import prepare_worker_runtime
prepare_worker_runtime(False)
from app.database.connection import Base
assert Base.registry.mappers
assert all(mapper.configured for mapper in Base.registry.mappers)
asyncpg.connect.assert_not_called()
sqlalchemy.ext.asyncio.create_async_engine.assert_not_called()
"""], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


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


def test_mapper_failure_aborts_readiness_and_is_not_memoized(monkeypatch):
    from app.database.connection import Base

    configure = Mock(side_effect=RuntimeError("synthetic invalid relationship"))
    monkeypatch.setattr(Base.registry, "configure", configure)
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        with pytest.raises(WorkerTerminate):
            prepare_worker_parent()
        assert worker_runtime.prepare_worker_runtime.cache_info().currsize == 0
        configure.side_effect = None
        prepare_worker_parent()
        assert configure.call_count == 2
        assert worker_runtime.prepare_worker_runtime.cache_info().currsize == 1
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()

"""Read-only admission guard tests for the existing primary freeze row."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from app.core.redis_authority import (
    AuthorityAdmissionBlocked,
    RedisAuthorityState,
    authority_admission_guard_required,
    require_primary_authority_active,
    require_primary_authority_active_sync,
)


class _Result:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Row:
    def __init__(self, *, phase="legacy", backend="primary", generation=0,
                 freeze_reason=None, freeze_id=None):
        self._mapping = {
            "generation": generation,
            "phase": phase,
            "active_backend": backend,
            "freeze_reason": freeze_reason,
            "freeze_id": freeze_id,
        }


class _AsyncSession:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.statements = []

    async def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))
        if self.error:
            raise self.error
        return _Result(self.row)


class _Cursor:
    def __init__(self, values, read_only="on"):
        self.values = values
        self.read_only = read_only
        self.statements = []
        self.closed = False
        self.current_statement = None

    def execute(self, statement):
        self.statements.append(statement)
        self.current_statement = statement

    def fetchone(self):
        if self.current_statement == "SHOW transaction_read_only":
            return (self.read_only,)
        return self.values

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, values, read_only="on"):
        self.cursor_value = _Cursor(values, read_only=read_only)
        self.session_args = None
        self.rollback_called = False
        self.closed = False

    def set_session(self, **kwargs):
        self.session_args = kwargs

    def cursor(self):
        return self.cursor_value

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.closed = True


class RedisAuthorityAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_guard_allows_only_fresh_legacy_primary_row(self):
        session = _AsyncSession(_Row(generation=7))
        result = await require_primary_authority_active(session)
        self.assertEqual(result, RedisAuthorityState(7, "legacy", "primary", None, None))
        self.assertEqual(len(session.statements), 1)
        self.assertIn("FROM redis_authority_control WHERE id = 1", session.statements[0][0])
        self.assertIsNone(session.statements[0][1])

    async def test_async_guard_denies_frozen_missing_malformed_and_read_failure(self):
        cases = (
            _AsyncSession(_Row(phase="frozen", generation=8, freeze_reason="manual", freeze_id="op")),
            _AsyncSession(None),
            _AsyncSession(_Row(backend="backup")),
            _AsyncSession(error=RuntimeError("synthetic secret detail")),
        )
        for session in cases:
            with self.subTest(session=session), self.assertRaises(AuthorityAdmissionBlocked) as caught:
                await require_primary_authority_active(session)
            self.assertEqual(str(caught.exception), "Primary resource authority is frozen or unavailable.")
            self.assertNotIn("synthetic", str(caught.exception))
            self.assertEqual(len(session.statements), 1)

    async def test_async_guard_times_out_without_mutating_caller_session(self):
        class SlowSession(_AsyncSession):
            async def execute(self, statement, parameters=None):
                self.statements.append((str(statement), parameters))
                await asyncio.sleep(1)

        session = SlowSession(_Row())
        session.caller_transaction_marker = "unchanged"
        with patch("app.core.redis_authority._AUTHORITY_READ_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(AuthorityAdmissionBlocked) as caught:
                await require_primary_authority_active(session)

        self.assertEqual(str(caught.exception), "Primary resource authority is frozen or unavailable.")
        self.assertEqual(len(session.statements), 1)
        self.assertEqual(session.caller_transaction_marker, "unchanged")

    def test_isolation_policy_skips_only_test_environment_and_local_test_database(self):
        isolated_urls = (
            "postgresql+asyncpg://user:secret@localhost:5434/latexy_test",
            "postgresql://user:secret@127.0.0.1/test",
            "postgres://user:secret@[::1]/testing",
            "postgresql+psycopg2://user:secret@postgres:5432/service_test",
        )
        for url in isolated_urls:
            with self.subTest(url=url):
                self.assertFalse(authority_admission_guard_required("test", url))
        guarded = (
            ("development", "postgresql://user:secret@localhost/latexy_test"),
            ("test", "postgresql://user:secret@db.example.invalid/latexy_test"),
            ("test", "postgresql://user:secret@localhost/latexy"),
            ("test", "mysql://user:secret@localhost/testing"),
            ("test", None),
            (None, "postgresql://user:secret@localhost/latexy_test"),
        )
        for environment, url in guarded:
            with self.subTest(environment=environment, url=url):
                self.assertTrue(authority_admission_guard_required(environment, url))

    def _run_sync_with_fake_driver(self, values, *, environment="production", database_url=None):
        connection = _Connection(values)
        connect_calls = []
        driver = types.ModuleType("psycopg2")

        def connect(url, **kwargs):
            connect_calls.append((url, kwargs))
            return connection

        driver.connect = connect
        config_module = types.ModuleType("app.core.config")
        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT=environment,
            DATABASE_URL=database_url or "postgresql+asyncpg://user:secret@db.example.invalid/latexy",
        )
        with patch.dict(sys.modules, {"psycopg2": driver, "app.core.config": config_module}):
            state = require_primary_authority_active_sync()
        return state, connection, connect_calls

    def test_sync_guard_uses_bounded_readonly_transaction_and_cleans_up(self):
        state, connection, connect_calls = self._run_sync_with_fake_driver(
            (3, "legacy", "primary", None, None),
            database_url="postgresql+asyncpg://user:secret@db.example.invalid/latexy",
        )
        self.assertEqual(state, RedisAuthorityState(3, "legacy", "primary", None, None))
        self.assertEqual(connect_calls, [("postgresql://user:secret@db.example.invalid/latexy?sslmode=require", {"connect_timeout": 5})])
        self.assertEqual(connection.session_args, {"readonly": True, "autocommit": False})
        self.assertEqual(connection.cursor_value.statements[:2], [
            "SET LOCAL statement_timeout = '5s'",
            "SET LOCAL lock_timeout = '2s'",
        ])
        self.assertEqual(connection.cursor_value.statements[2], "SHOW transaction_read_only")
        self.assertIn("SELECT generation, phase, active_backend", connection.cursor_value.statements[3])
        self.assertTrue(connection.rollback_called)
        self.assertTrue(connection.cursor_value.closed)
        self.assertTrue(connection.closed)

    def test_sync_guard_frozen_state_is_sanitized_and_cleans_up(self):
        connection = _Connection((4, "frozen", "primary", "manual", "opaque-id"))
        driver = types.ModuleType("psycopg2")
        driver.connect = lambda *_args, **_kwargs: connection
        config_module = types.ModuleType("app.core.config")
        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:secret@db.example.invalid/latexy",
        )
        with patch.dict(sys.modules, {"psycopg2": driver, "app.core.config": config_module}):
            with self.assertRaises(AuthorityAdmissionBlocked) as caught:
                require_primary_authority_active_sync()
        self.assertEqual(str(caught.exception), "Primary resource authority is frozen or unavailable.")
        self.assertTrue(connection.rollback_called)
        self.assertTrue(connection.cursor_value.closed)
        self.assertTrue(connection.closed)

    def test_sync_guard_rejects_non_readonly_before_select_and_cleans_up(self):
        connection = _Connection((4, "legacy", "primary", None, None), read_only="off")
        driver = types.ModuleType("psycopg2")
        driver.connect = lambda *_args, **_kwargs: connection
        config_module = types.ModuleType("app.core.config")
        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:secret@db.example.invalid/latexy",
        )
        with patch.dict(sys.modules, {"psycopg2": driver, "app.core.config": config_module}):
            with self.assertRaises(AuthorityAdmissionBlocked):
                require_primary_authority_active_sync()
        self.assertEqual(connection.cursor_value.statements, [
            "SET LOCAL statement_timeout = '5s'",
            "SET LOCAL lock_timeout = '2s'",
            "SHOW transaction_read_only",
        ])
        self.assertTrue(connection.rollback_called)
        self.assertTrue(connection.cursor_value.closed)
        self.assertTrue(connection.closed)

    def test_sync_url_normalizes_only_strict_tls_modes(self):
        from app.core.redis_authority import _sync_postgres_url

        self.assertEqual(
            _sync_postgres_url("postgresql+asyncpg://u:p@db.invalid/app?ssl=require"),
            "postgresql://u:p@db.invalid/app?sslmode=require",
        )
        self.assertEqual(
            _sync_postgres_url("postgresql://u:p@db.invalid/app?sslmode=verify-full"),
            "postgresql://u:p@db.invalid/app?sslmode=verify-full",
        )
        self.assertEqual(
            _sync_postgres_url("postgresql+asyncpg://u:p@db.invalid/app?sslmode=require&channel_binding=require"),
            "postgresql://u:p@db.invalid/app?sslmode=require&channel_binding=require",
        )
        self.assertEqual(
            _sync_postgres_url("postgresql://u:p@db.invalid/app"),
            "postgresql://u:p@db.invalid/app?sslmode=require",
        )
        self.assertEqual(
            _sync_postgres_url("postgresql+asyncpg://u:p@localhost/latexy_test"),
            "postgresql://u:p@localhost/latexy_test",
        )
        self.assertEqual(
            _sync_postgres_url("postgresql://u:p@postgres/service?sslmode=require"),
            "postgresql://u:p@postgres/service?sslmode=require",
        )
        for url in (
            "postgresql://u:p@db.invalid/app?ssl=require&sslmode=verify-full",
            "postgresql://u:p@db.invalid/app?sslmode=disable",
            "postgresql://u:p@db.invalid/app?sslmode=",
            "postgresql://u:p@db.invalid/app?ssl=prefer",
            "postgresql://u:p@db.invalid/app?sslmode=require&channel_binding=disable",
            "postgresql://u:p@db.invalid/app?channel_binding=require&channel_binding=require",
            "postgresql://u:p@db.invalid/app?search_path=secret",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _sync_postgres_url(url)

    def test_sync_guard_skips_only_isolated_test_and_fails_closed_on_missing_driver(self):
        config_module = types.ModuleType("app.core.config")
        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT="test",
            DATABASE_URL="postgresql+asyncpg://user:secret@localhost/latexy_test",
        )
        with patch.dict(sys.modules, {"app.core.config": config_module, "psycopg2": None}):
            self.assertIsNone(require_primary_authority_active_sync())

        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT="development",
            DATABASE_URL="postgresql://user:secret@localhost/latexy_test",
        )
        with patch.dict(sys.modules, {"app.core.config": config_module, "psycopg2": None}):
            with self.assertRaises(AuthorityAdmissionBlocked) as caught:
                require_primary_authority_active_sync()
        self.assertEqual(str(caught.exception), "Primary resource authority is frozen or unavailable.")


if __name__ == "__main__":
    unittest.main()

"""Contract tests for the declared spare-authority handover primitive."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.core.redis_authority import (
    AuthorityAdmissionBlocked,
    AuthorityStateUnavailable,
    StaleAuthorityGeneration,
    freeze_primary_authority,
    handover_to_spare,
    read_redis_authority,
    require_active_authority,
    require_active_authority_sync,
    require_primary_authority_active,
    require_spare_authority_active,
)


def _migration(filename):
    path = Path(__file__).resolve().parents[1] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location("spare_handover_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(connection, filename):
    migration = _migration(filename)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    return migration


class _AsyncConnection:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, statement, parameters=None):
        return self.connection.execute(statement, parameters or {})


class SpareHandoverMigrationTests(unittest.TestCase):
    def test_chain_links_0075_to_0076(self):
        migration = _migration("0076_spare_authority_handover.py")
        self.assertEqual(migration.revision, "0076_spare_authority_handover")
        self.assertEqual(migration.down_revision, "0075_durable_quota_ledger")

    def test_downgrade_is_refused(self):
        from alembic.operations import Operations as _Operations  # noqa: F401

        migration = _migration("0076_spare_authority_handover.py")

        class _Op:
            pass

        migration.op = _Op()
        with self.assertRaises(RuntimeError):
            migration.downgrade()

    def test_upgrade_widens_constraints_on_sqlite(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                _upgrade(connection, "0074_redis_authority_freeze.py")
                _upgrade(connection, "0076_spare_authority_handover.py")
                connection.execute(text(
                    "UPDATE redis_authority_control SET generation = 1, phase = 'spare', "
                    "active_backend = 'spare', freeze_reason = 'spare_handover_fresh_start', "
                    "freeze_id = '00000000-0000-4000-8000-000000000000' WHERE id = 1"
                ))
        finally:
            engine.dispose()


class SpareHandoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            _upgrade(connection, "0074_redis_authority_freeze.py")
            _upgrade(connection, "0076_spare_authority_handover.py")

    def tearDown(self):
        self.engine.dispose()

    async def test_handover_requires_frozen_primary_first(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            with self.assertRaises(StaleAuthorityGeneration):
                await handover_to_spare(
                    session, expected_generation=0,
                    reason="spare_handover_fresh_start", handover_id=uuid4(),
                )

    async def test_freeze_then_handover_names_spare_with_fresh_start(self):
        handover_id = uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            frozen = await freeze_primary_authority(
                session, expected_generation=0, reason="quota_exhausted", freeze_id=uuid4(),
            )
            self.assertEqual((frozen.phase, frozen.active_backend), ("frozen", "primary"))
            handed = await handover_to_spare(
                session, expected_generation=frozen.generation,
                reason="spare_handover_fresh_start", handover_id=handover_id,
            )
            self.assertEqual(handed.generation, frozen.generation + 1)
            self.assertEqual((handed.phase, handed.active_backend), ("spare", "spare"))
            self.assertEqual(handed.freeze_reason, "spare_handover_fresh_start")
            self.assertEqual(handed.freeze_id, str(handover_id))
            persisted = await read_redis_authority(session)
            self.assertEqual(persisted, handed)

    async def test_second_handover_is_stale(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            frozen = await freeze_primary_authority(
                session, expected_generation=0, reason="quota_exhausted", freeze_id=uuid4(),
            )
            await handover_to_spare(
                session, expected_generation=frozen.generation,
                reason="spare_handover_fresh_start", handover_id=uuid4(),
            )
            with self.assertRaises(StaleAuthorityGeneration):
                await handover_to_spare(
                    session, expected_generation=frozen.generation,
                    reason="spare_handover_fresh_start", handover_id=uuid4(),
                )

    async def test_handover_validates_inputs(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            frozen = await freeze_primary_authority(
                session, expected_generation=0, reason="quota_exhausted", freeze_id=uuid4(),
            )
            with self.assertRaises(ValueError):
                await handover_to_spare(
                    session, expected_generation=frozen.generation,
                    reason="quota_exhausted", handover_id=uuid4(),
                )
            with self.assertRaises(ValueError):
                await handover_to_spare(
                    session, expected_generation=frozen.generation,
                    reason="spare_handover_fresh_start", handover_id="not-a-uuid",
                )
            with self.assertRaises(ValueError):
                await handover_to_spare(
                    session, expected_generation=-1,
                    reason="spare_handover_fresh_start", handover_id=uuid4(),
                )

    async def test_spare_acceptance_matches_handed_over_state_only(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            with self.assertRaises(AuthorityAdmissionBlocked):
                await require_spare_authority_active(session)
            frozen = await freeze_primary_authority(
                session, expected_generation=0, reason="quota_exhausted", freeze_id=uuid4(),
            )
            with self.assertRaises(AuthorityAdmissionBlocked):
                await require_spare_authority_active(session)
            handed = await handover_to_spare(
                session, expected_generation=frozen.generation,
                reason="spare_handover_fresh_start", handover_id=uuid4(),
            )
            self.assertEqual(await require_spare_authority_active(session), handed)
            with self.assertRaises(AuthorityAdmissionBlocked):
                await require_primary_authority_active(session)

    async def test_incompatible_rows_stay_unavailable(self):
        with self.engine.begin() as connection:
            # Passes the DB CHECKs but names a backend the phase cannot own.
            connection.execute(text("UPDATE redis_authority_control SET active_backend = 'spare'"))
            session = _AsyncConnection(connection)
            with self.assertRaises(AuthorityStateUnavailable):
                await read_redis_authority(session)
            with self.assertRaises(AuthorityAdmissionBlocked):
                await require_spare_authority_active(session)

    async def test_active_authority_accepts_handed_backend_only(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            legacy = await require_active_authority(session)
            self.assertEqual((legacy.phase, legacy.active_backend), ("legacy", "primary"))
            frozen = await freeze_primary_authority(
                session, expected_generation=legacy.generation,
                reason="quota_exhausted", freeze_id=uuid4(),
            )
            with self.assertRaises(AuthorityAdmissionBlocked):
                await require_active_authority(session)
            handed = await handover_to_spare(
                session, expected_generation=frozen.generation,
                reason="spare_handover_fresh_start", handover_id=uuid4(),
            )
            self.assertEqual(await require_active_authority(session), handed)


class _SyncCursor:
    """Minimal psycopg2 cursor double: flag reads vs row reads by statement."""

    def __init__(self, values, read_only="on"):
        self.values = values
        self.read_only = read_only
        self.closed = False
        self._last_statement = ""

    def execute(self, statement):
        self._last_statement = statement

    def fetchone(self):
        if self._last_statement == "SHOW transaction_read_only":
            return (self.read_only,)
        return self.values

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self, values, read_only="on"):
        self.cursor_value = _SyncCursor(values, read_only=read_only)
        self.rollback_called = False
        self.closed = False

    def set_session(self, **kwargs):
        pass

    def cursor(self):
        return self.cursor_value

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.closed = True


class SpareHandoverSyncTests(unittest.TestCase):
    def _run_sync(self, values, *, environment="production"):
        connection = _FakeConnection(values)
        driver = types.ModuleType("psycopg2")
        driver.connect = lambda *_args, **_kwargs: connection
        config_module = types.ModuleType("app.core.config")
        config_module.settings = types.SimpleNamespace(
            ENVIRONMENT=environment,
            DATABASE_URL="postgresql://user:secret@db.example.invalid/latexy",
        )
        with patch.dict(sys.modules, {"psycopg2": driver, "app.core.config": config_module}):
            return require_active_authority_sync(), connection

    def test_sync_accepts_legacy_primary(self):
        state, connection = self._run_sync((3, "legacy", "primary", None, None))
        self.assertEqual((state.phase, state.active_backend, state.generation), ("legacy", "primary", 3))
        self.assertTrue(connection.rollback_called)
        self.assertTrue(connection.closed)

    def test_sync_accepts_handed_spare(self):
        state, _connection = self._run_sync(
            (4, "spare", "spare", "spare_handover_fresh_start", "00000000-0000-4000-8000-000000000000")
        )
        self.assertEqual((state.phase, state.active_backend), ("spare", "spare"))

    def test_sync_blocks_frozen(self):
        with self.assertRaises(AuthorityAdmissionBlocked):
            self._run_sync((4, "frozen", "primary", "quota_exhausted", "some-id"))


if __name__ == "__main__":
    unittest.main()

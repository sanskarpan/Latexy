"""Contract tests for the disabled, durable Redis authority freeze primitive."""

import asyncio
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ResourceClosedError

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.redis_authority import (
    AuthorityStateUnavailable,
    StaleAuthorityGeneration,
    freeze_primary_authority,
    read_redis_authority,
)


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0074_redis_authority_freeze.py"
    spec = importlib.util.spec_from_file_location("redis_authority_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(connection):
    migration = _migration()
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()
    return migration


class _AsyncConnection:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, statement, parameters=None):
        return self.connection.execute(statement, parameters or {})


class RedisAuthorityFreezeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            _upgrade(connection)

    def tearDown(self):
        self.engine.dispose()

    async def test_quota_exhaustion_freezes_without_routing_to_backup(self):
        operation_id = uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            initial = await read_redis_authority(session)
            self.assertEqual((initial.generation, initial.phase, initial.active_backend),
                             (0, "legacy", "primary"))
            frozen = await freeze_primary_authority(
                session, expected_generation=0, reason="quota_exhausted", freeze_id=operation_id,
            )
            self.assertEqual((frozen.generation, frozen.phase, frozen.active_backend),
                             (1, "frozen", "primary"))
            self.assertEqual(frozen.freeze_id, str(operation_id))
        with self.engine.connect() as connection:
            persisted = await read_redis_authority(_AsyncConnection(connection))
            self.assertEqual(persisted, frozen)

    async def test_stale_worker_cannot_reserve_another_generation(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await freeze_primary_authority(
                session, expected_generation=0, reason="manual", freeze_id=uuid4(),
            )
            with self.assertRaises(StaleAuthorityGeneration):
                await freeze_primary_authority(
                    session, expected_generation=0, reason="manual", freeze_id=uuid4(),
                )
        with self.engine.connect() as connection:
            state = await read_redis_authority(_AsyncConnection(connection))
            self.assertEqual(state.generation, 1)

    async def test_uncertain_response_can_be_reconciled_by_operation_id(self):
        operation_id = uuid4()
        with self.engine.begin() as connection:
            # Model a committed write whose response was lost to the caller.
            await freeze_primary_authority(
                _AsyncConnection(connection), expected_generation=0,
                reason="connection_unavailable", freeze_id=operation_id,
            )
        with self.engine.connect() as connection:
            state = await read_redis_authority(_AsyncConnection(connection))
            self.assertEqual(state.freeze_id, str(operation_id))
            self.assertNotEqual(state.freeze_id, str(uuid4()))
            self.assertEqual(state.active_backend, "primary")

    async def test_missing_or_incompatible_state_never_defaults_to_backup(self):
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM redis_authority_control"))
        with self.engine.connect() as connection:
            with self.assertRaises(AuthorityStateUnavailable):
                await read_redis_authority(_AsyncConnection(connection))

        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO redis_authority_control (id, generation, phase, active_backend) "
                "VALUES (1, 0, 'legacy', 'primary')"
            ))
            connection.execute(text("PRAGMA ignore_check_constraints = ON"))
            connection.execute(text("UPDATE redis_authority_control SET active_backend = 'backup'"))
            connection.execute(text("PRAGMA ignore_check_constraints = OFF"))
            with self.assertRaises(AuthorityStateUnavailable):
                await read_redis_authority(_AsyncConnection(connection))

    async def test_invalid_freeze_inputs_do_not_write(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            with self.assertRaises(ValueError):
                await freeze_primary_authority(
                    session, expected_generation=True, reason="manual", freeze_id=uuid4(),
                )
            with self.assertRaises(ValueError):
                await freeze_primary_authority(
                    session, expected_generation=0, reason="untrusted", freeze_id=uuid4(),
                )
            with self.assertRaises(ValueError):
                await freeze_primary_authority(
                    session, expected_generation=0, reason="manual", freeze_id="not-a-uuid",
                )
            self.assertEqual((await read_redis_authority(session)).generation, 0)

    async def test_database_failure_propagates_without_a_healthy_default(self):
        connection = self.engine.connect()
        connection.close()
        with self.assertRaises(ResourceClosedError):
            await read_redis_authority(_AsyncConnection(connection))

    async def test_downgrade_refuses_to_erase_a_frozen_generation(self):
        with self.engine.begin() as connection:
            await freeze_primary_authority(
                _AsyncConnection(connection), expected_generation=0,
                reason="manual", freeze_id=uuid4(),
            )
        with self.engine.begin() as connection:
            migration = _migration()
            migration.op = Operations(MigrationContext.configure(connection))
            with self.assertRaises(RuntimeError):
                migration.downgrade()

    async def test_downgrade_refuses_even_before_freeze_to_avoid_race(self):
        with self.engine.begin() as connection:
            migration = _migration()
            migration.op = Operations(MigrationContext.configure(connection))
            with self.assertRaises(RuntimeError):
                migration.downgrade()
            self.assertEqual((await read_redis_authority(_AsyncConnection(connection))).generation, 0)


class ConcurrentRedisAuthorityFreezeTests(unittest.TestCase):
    def test_two_coordinators_cannot_both_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "authority.sqlite"
            engine = create_engine(
                f"sqlite:///{database}",
                connect_args={"check_same_thread": False, "timeout": 5},
                isolation_level="AUTOCOMMIT",
            )
            try:
                with engine.begin() as connection:
                    _upgrade(connection)
                barrier = Barrier(2)

                def attempt():
                    with engine.connect() as connection:
                        barrier.wait(timeout=5)
                        try:
                            asyncio.run(freeze_primary_authority(
                                _AsyncConnection(connection), expected_generation=0,
                                reason="quota_exhausted", freeze_id=uuid4(),
                            ))
                            return "won"
                        except (StaleAuthorityGeneration, OperationalError, sqlite3.OperationalError):
                            return "closed"

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: attempt(), range(2)))
                self.assertCountEqual(results, ["won", "closed"])
                with engine.connect() as connection:
                    state = asyncio.run(read_redis_authority(_AsyncConnection(connection)))
                self.assertEqual((state.generation, state.phase, state.active_backend),
                                 (1, "frozen", "primary"))
            finally:
                engine.dispose()


def _local_postgres_url():
    value = os.getenv("TEST_POSTGRES_URL")
    if not value or os.getenv("TEST_POSTGRES_ALLOW_SCHEMA_CREATE") != "1":
        return None
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return value


@unittest.skipUnless(_local_postgres_url(), "requires explicitly enabled loopback test PostgreSQL")
class PostgresAuthorityFreezeTests(unittest.TestCase):
    def test_concurrent_freeze_and_rollback(self):
        schema = "authority_test_" + uuid4().hex
        admin = create_engine(_local_postgres_url())
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(_local_postgres_url(), connect_args={"options": f"-c search_path={schema}"})
        try:
            with engine.begin() as connection:
                _upgrade(connection)
            try:
                with engine.begin() as connection:
                    asyncio.run(freeze_primary_authority(
                        _AsyncConnection(connection), expected_generation=0,
                        reason="manual", freeze_id=uuid4(),
                    ))
                    raise ConnectionError("transaction abandoned before commit")
            except ConnectionError:
                pass
            with engine.connect() as connection:
                state = asyncio.run(read_redis_authority(_AsyncConnection(connection)))
                self.assertEqual((state.generation, state.phase), (0, "legacy"))

            barrier = Barrier(2)

            def attempt():
                with engine.begin() as connection:
                    barrier.wait(timeout=10)
                    try:
                        asyncio.run(freeze_primary_authority(
                            _AsyncConnection(connection), expected_generation=0,
                            reason="quota_exhausted", freeze_id=uuid4(),
                        ))
                        return "won"
                    except StaleAuthorityGeneration:
                        return "closed"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: attempt(), range(2)))
            self.assertCountEqual(results, ["won", "closed"])
            with engine.connect() as connection:
                state = asyncio.run(read_redis_authority(_AsyncConnection(connection)))
                self.assertEqual((state.generation, state.phase, state.active_backend),
                                 (1, "frozen", "primary"))
        finally:
            engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()

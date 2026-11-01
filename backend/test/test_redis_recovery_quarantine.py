"""Synthetic contract tests for operator primary-freeze quarantine."""

from __future__ import annotations

import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.redis_authority import (
    AuthorityAdmissionBlocked,
    freeze_primary_authority,
    read_redis_authority,
    require_primary_authority_active,
)
from scripts.redis_recovery_quarantine import (
    RedisHandoverError,
    RedisRecoveryQuarantineError,
    freeze_primary_for_recovery,
    handover_spare_for_recovery,
)

SOURCE = "a" * 40
FREEZE_ID = str(uuid4())
ENV = {
    "MODAL_ENVIRONMENT": "main",
    "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
    "MODAL_REDIS_SECRET_NAME": "latexy-redis-held",
    "DEPLOY_SHA": SOURCE,
}


@dataclass
class _Row:
    generation: int
    phase: str
    active_backend: str
    freeze_reason: str | None
    freeze_id: str | None

    @property
    def _mapping(self):
        return vars(self)


class _Result:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Store:
    def __init__(self, state=None):
        self.state = state or _Row(0, "legacy", "primary", None, None)
        self.opens = 0
        self.fail_reads = False
        self.lose_commit_response = False
        self.competing_freeze = None

    def factory(self):
        store = self

        class Session:
            async def __aenter__(self):
                store.opens += 1
                return self

            async def __aexit__(self, *_args):
                return False

            async def execute(self, statement, parameters=None):
                sql = str(statement)
                if sql.startswith("SELECT generation"):
                    if store.fail_reads:
                        raise OSError("private database detail")
                    return _Result(_Row(**vars(store.state)))
                if sql.startswith("UPDATE redis_authority_control"):
                    if store.competing_freeze is not None:
                        store.state = store.competing_freeze
                        store.competing_freeze = None
                    if store.state.phase != "legacy" or store.state.generation != parameters["expected"]:
                        return _Result(None)
                    store.state = _Row(
                        store.state.generation + 1, "frozen", "primary",
                        parameters["reason"], str(parameters["freeze_id"]),
                    )
                    return _Result(_Row(**vars(store.state)))
                raise AssertionError("unexpected SQL")

            async def commit(self):
                if store.lose_commit_response:
                    store.lose_commit_response = False
                    raise OSError("private commit detail")

            async def rollback(self):
                return None

        return Session()


class RedisRecoveryQuarantineTests(unittest.IsolatedAsyncioTestCase):
    async def test_freezes_legacy_primary_and_returns_allowlisted_proof(self):
        store = _Store()
        proof = await freeze_primary_for_recovery(
            store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
        )
        self.assertEqual(proof["phase"], "frozen")
        self.assertEqual(proof["active_backend"], "primary")
        self.assertEqual(proof["generation"], 1)
        self.assertEqual(proof["freeze_id"], FREEZE_ID)
        self.assertEqual(proof["source_sha"], SOURCE)
        self.assertFalse(proof["jobs_allowed"])
        self.assertFalse(proof["newauthority_enabled"])
        self.assertTrue(proof["limits_unknown"])
        self.assertNotIn("latexy-redis-held", repr(proof))
        self.assertEqual(store.state.phase, "frozen")

    async def test_exact_existing_freeze_is_idempotent_without_update(self):
        store = _Store(_Row(1, "frozen", "primary", "quota_exhausted", FREEZE_ID))
        proof = await freeze_primary_for_recovery(
            store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
        )
        self.assertEqual(proof["generation"], 1)

    async def test_mismatched_frozen_identity_and_stale_generation_deny(self):
        for state in (
            _Row(1, "frozen", "primary", "quota_exhausted", str(uuid4())),
            _Row(1, "frozen", "primary", "manual", FREEZE_ID),
            _Row(2, "frozen", "primary", "quota_exhausted", FREEZE_ID),
            _Row(3, "legacy", "primary", None, None),
        ):
            store = _Store(state)
            with self.assertRaises(RedisRecoveryQuarantineError):
                await freeze_primary_for_recovery(
                    store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
                )

    async def test_cas_race_with_other_freeze_denies(self):
        store = _Store()
        store.competing_freeze = _Row(1, "frozen", "primary", "manual", str(uuid4()))
        with self.assertRaises(RedisRecoveryQuarantineError):
            await freeze_primary_for_recovery(
                store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
            )
        self.assertEqual(store.state.freeze_reason, "manual")

    async def test_lost_commit_response_is_confirmed_by_fresh_exact_readback(self):
        store = _Store()
        store.lose_commit_response = True
        proof = await freeze_primary_for_recovery(
            store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
        )
        self.assertEqual(proof["freeze_id"], FREEZE_ID)
        self.assertEqual(store.opens, 2)

    async def test_db_failure_is_sanitized(self):
        store = _Store()
        store.fail_reads = True
        with self.assertRaises(RedisRecoveryQuarantineError) as caught:
            await freeze_primary_for_recovery(
                store.factory, environ=ENV, source_revision=SOURCE, freeze_id=FREEZE_ID,
            )
        self.assertEqual(str(caught.exception), "Primary recovery quarantine could not be confirmed.")
        self.assertNotIn("private", str(caught.exception))

    async def test_config_rejections_happen_before_session_factory(self):
        invalid = (
            ({**ENV, "MODAL_ENVIRONMENT": "dev"}, SOURCE, FREEZE_ID, 0),
            ({**ENV, "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "TRUE"}, SOURCE, FREEZE_ID, 0),
            ({**ENV, "MODAL_REDIS_SECRET_NAME": "latexy-redis"}, SOURCE, FREEZE_ID, 0),
            ({**ENV, "DEPLOY_SHA": "b" * 40}, SOURCE, FREEZE_ID, 0),
            (ENV, SOURCE.upper(), FREEZE_ID, 0),
            (ENV, SOURCE, FREEZE_ID.upper(), 0),
            (ENV, SOURCE, FREEZE_ID, True),
            (ENV, SOURCE, FREEZE_ID, -1),
        )
        for env, revision, operation_id, generation in invalid:
            calls = 0

            def forbidden_factory():
                nonlocal calls
                calls += 1
                raise AssertionError("database factory called before validation")

            with self.assertRaises(RedisRecoveryQuarantineError):
                await freeze_primary_for_recovery(
                    forbidden_factory, environ=env, source_revision=revision,
                    freeze_id=operation_id, expected_generation=generation,
                )
            self.assertEqual(calls, 0)


def _local_postgres_url():
    value = os.getenv("TEST_POSTGRES_URL")
    if not value or os.getenv("TEST_POSTGRES_ALLOW_SCHEMA_CREATE") != "1":
        return None
    try:
        parsed = make_url(value)
    except Exception:
        return None
    if parsed.host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return value


class _PostgresSessionAdapter:
    """Tiny async-shaped wrapper around a sync connection for isolated tests."""

    def __init__(self, engine):
        self.engine = engine
        self.connection = None
        self.transaction = None

    async def __aenter__(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        return self

    async def __aexit__(self, *_args):
        try:
            if self.transaction is not None and self.transaction.is_active:
                self.transaction.rollback()
        finally:
            self.connection.close()

    async def execute(self, statement, parameters=None):
        return self.connection.execute(statement, parameters or {})

    async def commit(self):
        self.transaction.commit()

    async def rollback(self):
        if self.transaction is not None and self.transaction.is_active:
            self.transaction.rollback()


def _apply_authority_migration(connection):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0074_redis_authority_freeze.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("redis_authority_migration_pg", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(connection))
    migration.upgrade()


@unittest.skipUnless(_local_postgres_url(), "requires explicitly enabled loopback test PostgreSQL")
class PostgresRedisRecoveryQuarantineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "recovery_quarantine_" + uuid4().hex
        cls.admin = create_engine(_local_postgres_url())
        with cls.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(
            _local_postgres_url(), connect_args={"options": f"-c search_path={cls.schema}"},
        )
        with cls.engine.begin() as connection:
            _apply_authority_migration(connection)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.engine.dispose()
            with cls.admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
        finally:
            cls.admin.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(text(
                "UPDATE redis_authority_control SET generation=0, phase='legacy', "
                "active_backend='primary', freeze_reason=NULL, freeze_id=NULL WHERE id=1"
            ))

    def _factory(self):
        return _PostgresSessionAdapter(self.engine)

    def _run(self, operation_id):
        return asyncio.run(freeze_primary_for_recovery(
            self._factory,
            environ=ENV,
            source_revision=SOURCE,
            freeze_id=operation_id,
        ))

    def test_same_freeze_uuid_race_is_idempotent_at_generation_one(self):
        barrier = Barrier(2)

        def attempt():
            barrier.wait(timeout=10)
            return self._run(FREEZE_ID)

        with ThreadPoolExecutor(max_workers=2) as pool:
            proofs = list(pool.map(lambda _index: attempt(), range(2)))
        self.assertEqual([proof["generation"] for proof in proofs], [1, 1])
        self.assertEqual({proof["freeze_id"] for proof in proofs}, {FREEZE_ID})
        async def read_state():
            async with self._factory() as session:
                return await read_redis_authority(session)

        state = asyncio.run(read_state())
        self.assertEqual((state.generation, state.phase, state.active_backend), (1, "frozen", "primary"))

        async def check_admission():
            async with self._factory() as session:
                await require_primary_authority_active(session)

        with self.assertRaises(AuthorityAdmissionBlocked):
            asyncio.run(check_admission())

    def test_different_freeze_uuid_race_has_one_winner_and_fixed_loser_error(self):
        operation_ids = (str(uuid4()), str(uuid4()))
        barrier = Barrier(2)

        def attempt(operation_id):
            barrier.wait(timeout=10)
            try:
                return self._run(operation_id)
            except RedisRecoveryQuarantineError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, operation_ids))
        proofs = [item for item in outcomes if isinstance(item, dict)]
        errors = [item for item in outcomes if isinstance(item, str)]
        self.assertEqual(len(proofs), 1)
        self.assertEqual(errors, ["Primary recovery quarantine could not be confirmed."])
        self.assertEqual(proofs[0]["generation"], 1)
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT generation, phase, active_backend, freeze_reason, freeze_id "
                "FROM redis_authority_control WHERE id=1"
            )).first()
        self.assertEqual(tuple(row), (1, "frozen", "primary", "quota_exhausted", proofs[0]["freeze_id"]))

    def test_rollback_before_commit_leaves_legacy_generation_zero(self):
        with self.engine.connect() as connection:
            transaction = connection.begin()

            class Session:
                async def execute(self, statement, parameters=None):
                    return connection.execute(statement, parameters or {})

            asyncio.run(freeze_primary_authority(
                Session(), expected_generation=0, reason="quota_exhausted", freeze_id=uuid4(),
            ))
            transaction.rollback()
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT generation, phase, active_backend FROM redis_authority_control WHERE id=1"
            )).first()
        self.assertEqual(tuple(row), (0, "legacy", "primary"))


HANDOVER_ID = str(uuid4())
DEFAULT_ENV = {
    "MODAL_ENVIRONMENT": "main",
    "MODAL_DEPLOYMENT_TRAFFIC_HOLD": "true",
    "MODAL_REDIS_SECRET_NAME": "latexy-redis",
    "DEPLOY_SHA": SOURCE,
}


class _HandoverStore:
    """Fake authority store with frozen-source handover semantics."""

    def __init__(self, state=None):
        self.state = state or _Row(1, "frozen", "primary", "quota_exhausted", FREEZE_ID)
        self.opens = 0
        self.fail_reads = False
        self.lose_commit_response = False

    def factory(self):
        store = self

        class Session:
            async def __aenter__(self):
                store.opens += 1
                return self

            async def __aexit__(self, *_args):
                return False

            async def execute(self, statement, parameters=None):
                sql = str(statement)
                if sql.startswith("SELECT generation"):
                    if store.fail_reads:
                        raise OSError("private database detail")
                    return _Result(_Row(**vars(store.state)))
                if sql.startswith("UPDATE redis_authority_control"):
                    if "phase = 'spare'" not in sql:
                        raise AssertionError("unexpected SQL")
                    if store.state.phase != "frozen" or store.state.generation != parameters["expected"]:
                        return _Result(None)
                    store.state = _Row(
                        store.state.generation + 1, "spare", "spare",
                        parameters["reason"], str(parameters["handover_id"]),
                    )
                    return _Result(_Row(**vars(store.state)))
                raise AssertionError("unexpected SQL")

            async def commit(self):
                if store.lose_commit_response:
                    store.lose_commit_response = False
                    raise OSError("private commit detail")

            async def rollback(self):
                return None

        return Session()


class SpareHandoverQuarantineTests(unittest.IsolatedAsyncioTestCase):
    async def test_hands_frozen_primary_to_spare_with_fresh_start_proof(self):
        store = _HandoverStore()
        proof = await handover_spare_for_recovery(
            store.factory, environ=DEFAULT_ENV, source_revision=SOURCE, handover_id=HANDOVER_ID,
        )
        self.assertEqual(proof["phase"], "spare")
        self.assertEqual(proof["active_backend"], "spare")
        self.assertEqual(proof["generation"], 2)
        self.assertEqual(proof["handover_id"], HANDOVER_ID)
        self.assertEqual(proof["fresh_baseline"], "spare_handover_fresh_start")
        self.assertTrue(proof["jobs_allowed"])
        self.assertTrue(proof["traffic_held"])
        self.assertTrue(proof["limits_unknown"])
        self.assertEqual(store.state.phase, "spare")

    async def test_default_redis_label_is_accepted_for_rotated_spare_binding(self):
        store = _HandoverStore()
        proof = await handover_spare_for_recovery(
            store.factory, environ=dict(DEFAULT_ENV, MODAL_REDIS_SECRET_NAME="latexy-redis"),
            source_revision=SOURCE, handover_id=HANDOVER_ID,
        )
        self.assertEqual(proof["active_backend"], "spare")

    async def test_legacy_row_must_be_frozen_first(self):
        store = _HandoverStore(_Row(0, "legacy", "primary", None, None))
        with self.assertRaises(RedisHandoverError):
            await handover_spare_for_recovery(
                store.factory, environ=DEFAULT_ENV, source_revision=SOURCE, handover_id=HANDOVER_ID,
            )

    async def test_exact_existing_handover_is_idempotent(self):
        store = _HandoverStore(_Row(2, "spare", "spare", "spare_handover_fresh_start", HANDOVER_ID))
        proof = await handover_spare_for_recovery(
            store.factory, environ=DEFAULT_ENV, source_revision=SOURCE, handover_id=HANDOVER_ID,
            expected_generation=1,
        )
        self.assertEqual(proof["generation"], 2)

    async def test_mismatched_identity_and_unheld_deny(self):
        for state, handover_id, environ in (
            (_Row(2, "spare", "spare", "spare_handover_fresh_start", str(uuid4())), HANDOVER_ID, DEFAULT_ENV),
            (_Row(2, "spare", "spare", "spare_handover_fresh_start", HANDOVER_ID), str(uuid4()), DEFAULT_ENV),
        ):
            store = _HandoverStore(state)
            with self.assertRaises(RedisHandoverError):
                await handover_spare_for_recovery(
                    store.factory, environ=environ, source_revision=SOURCE, handover_id=handover_id,
                    expected_generation=1,
                )
        store = _HandoverStore()
        with self.assertRaises(RedisHandoverError):
            await handover_spare_for_recovery(
                store.factory, environ=dict(DEFAULT_ENV, MODAL_DEPLOYMENT_TRAFFIC_HOLD="false"),
                source_revision=SOURCE, handover_id=HANDOVER_ID,
            )

    async def test_lost_commit_response_is_confirmed_by_fresh_exact_readback(self):
        store = _HandoverStore()
        store.lose_commit_response = True
        proof = await handover_spare_for_recovery(
            store.factory, environ=DEFAULT_ENV, source_revision=SOURCE, handover_id=HANDOVER_ID,
        )
        self.assertEqual(proof["handover_id"], HANDOVER_ID)
        self.assertEqual(store.opens, 2)

    async def test_db_failure_is_sanitized(self):
        store = _HandoverStore()
        store.fail_reads = True
        with self.assertRaises(RedisHandoverError) as caught:
            await handover_spare_for_recovery(
                store.factory, environ=DEFAULT_ENV, source_revision=SOURCE, handover_id=HANDOVER_ID,
            )
        self.assertEqual(str(caught.exception), "Spare handover could not be confirmed.")
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

"""Contract tests for the disabled durable quota ledger."""

import asyncio
import hashlib
import importlib.util
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ResourceClosedError

from app.core.durable_quota_ledger import (
    QuotaBalanceUnknown,
    QuotaReplayConflict,
    QuotaReservationUnknown,
    read_quota_reservation,
    record_reconciled_opening,
    refund_quota_reservation,
    reserve_quota,
    settle_quota_reservation,
    stage_unknown_account,
)


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0075_durable_quota_ledger.py"
    spec = importlib.util.spec_from_file_location("durable_quota_ledger_migration", path)
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

    async def execute(self, statement):
        return self.connection.execute(statement)


async def _open_account(session, user_id, *, opening=3):
    await stage_unknown_account(session, user_id=user_id, dimension="ai", period="20261014")
    await record_reconciled_opening(
        session, user_id=user_id, dimension="ai", period="20261014",
        opening_used=opening, source_ref="verified-snapshot-1", source_sha256="a" * 64,
    )


def _fingerprint(reservation_id):
    return hashlib.sha256(f"persisted-intent:{reservation_id}".encode()).hexdigest()


async def _reserve(session, user_id, reservation_id, *, cost=1, limit=5, window="day", fingerprint=None):
    return await reserve_quota(
        session, reservation_id=reservation_id, user_id=user_id,
        dimension="ai", period="20261014", window=window, cost=cost, limit=limit,
        intent_fingerprint=_fingerprint(reservation_id) if fingerprint is None else fingerprint,
    )


async def _read(session, user_id, reservation_id, *, cost=1, limit=5, window="day", fingerprint=None):
    return await read_quota_reservation(
        session, reservation_id, user_id=user_id, dimension="ai", period="20261014",
        window=window, cost=cost, limit=limit,
        intent_fingerprint=_fingerprint(reservation_id) if fingerprint is None else fingerprint,
    )


async def _refund(session, reservation_id):
    return await refund_quota_reservation(
        session, reservation_id, intent_fingerprint=_fingerprint(reservation_id),
    )


async def _settle(session, reservation_id):
    return await settle_quota_reservation(
        session, reservation_id, intent_fingerprint=_fingerprint(reservation_id),
    )


class DurableQuotaLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.user_id = str(uuid4())
        with self.engine.begin() as connection:
            _upgrade(connection)

    def tearDown(self):
        self.engine.dispose()

    async def test_legacy_missing_and_unknown_balances_fail_closed(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            with self.assertRaises(QuotaBalanceUnknown):
                await _reserve(session, self.user_id, uuid4())
            await stage_unknown_account(
                session, user_id=self.user_id, dimension="ai", period="20261014",
            )
            with self.assertRaises(QuotaBalanceUnknown):
                await _reserve(session, self.user_id, uuid4())
            count = connection.scalar(text("SELECT count(*) FROM quota_ledger_reservations"))
            self.assertEqual(count, 0)

    async def test_opening_requires_explicit_evidence(self):
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await stage_unknown_account(session, user_id=self.user_id, dimension="ai", period="20261014")
            for invalid in (-1, True):
                with self.assertRaises(ValueError):
                    await record_reconciled_opening(
                        session, user_id=self.user_id, dimension="ai", period="20261014",
                        opening_used=invalid, source_ref="snapshot", source_sha256="a" * 64,
                    )
            with self.assertRaises(ValueError):
                await record_reconciled_opening(
                    session, user_id=self.user_id, dimension="ai", period="20261014",
                    opening_used=0, source_ref="", source_sha256="a" * 64,
                )
            with self.assertRaises(ValueError):
                await record_reconciled_opening(
                    session, user_id=self.user_id, dimension="ai", period="20261014",
                    opening_used=0, source_ref="snapshot", source_sha256="bad",
                )
            await record_reconciled_opening(
                session, user_id=self.user_id, dimension="ai", period="20261014",
                opening_used=3, source_ref="snapshot", source_sha256="a" * 64,
            )
            with self.assertRaises(QuotaBalanceUnknown):
                await record_reconciled_opening(
                    session, user_id=self.user_id, dimension="ai", period="20261014",
                    opening_used=0, source_ref="different", source_sha256="b" * 64,
                )

    async def test_null_opening_is_rejected_by_schema_and_read_path(self):
        reservation_id = uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await _open_account(session, self.user_id, opening=0)
            self.assertTrue((await _reserve(session, self.user_id, reservation_id)).allowed)
            with self.assertRaises(IntegrityError):
                connection.execute(text(
                    "UPDATE quota_ledger_accounts SET opening_used = NULL"
                ))
            with self.assertRaises(IntegrityError):
                connection.execute(text(
                    "UPDATE quota_ledger_accounts SET source_ref = ''"
                ))
            connection.execute(text("PRAGMA ignore_check_constraints = ON"))
            connection.execute(text("UPDATE quota_ledger_accounts SET opening_used = NULL"))
            connection.execute(text("PRAGMA ignore_check_constraints = OFF"))
            with self.assertRaises(QuotaBalanceUnknown):
                await _reserve(session, self.user_id, uuid4())
            with self.assertRaises(QuotaBalanceUnknown):
                await _refund(session, reservation_id)

    async def test_near_limit_denial_and_sticky_idempotency(self):
        allowed_id, denied_id = uuid4(), uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await _open_account(session, self.user_id)
            allowed = await _reserve(session, self.user_id, allowed_id, cost=2)
            self.assertEqual((allowed.allowed, allowed.used_after), (True, 5))
            self.assertEqual(await _reserve(session, self.user_id, allowed_id, cost=2), allowed)
            denied = await _reserve(session, self.user_id, denied_id)
            self.assertEqual((denied.allowed, denied.used_after), (False, 5))
            with self.assertRaises(QuotaReplayConflict):
                await _reserve(session, self.user_id, allowed_id, cost=1)
            self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")), 5)
            self.assertTrue(await _refund(session, allowed_id))
            self.assertFalse(await _refund(session, allowed_id))
            self.assertFalse(await _refund(session, denied_id))
            self.assertEqual(await _reserve(session, self.user_id, denied_id), denied)
            self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")), 3)

    async def test_settlement_blocks_every_later_refund_or_duplicate_dispatch(self):
        successful_id, failed_id, denied_id = uuid4(), uuid4(), uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await _open_account(session, self.user_id, opening=0)
            self.assertTrue((await _reserve(session, self.user_id, successful_id)).allowed)
            with self.assertRaises(QuotaReplayConflict):
                await settle_quota_reservation(session, successful_id, intent_fingerprint="b" * 64)
            with self.assertRaises(QuotaReplayConflict):
                await refund_quota_reservation(session, successful_id, intent_fingerprint="b" * 64)
            self.assertTrue(await _settle(session, successful_id))
            self.assertFalse(await _settle(session, successful_id))
            self.assertFalse(await _refund(session, successful_id))
            self.assertEqual((await _reserve(session, self.user_id, successful_id)).state, "settled")
            self.assertFalse((await _read(session, self.user_id, successful_id)).allowed)

            self.assertTrue((await _reserve(session, self.user_id, failed_id)).allowed)
            self.assertTrue(await _refund(session, failed_id))
            self.assertFalse(await _settle(session, failed_id))
            self.assertFalse(await _refund(session, failed_id))

            self.assertFalse((await _reserve(session, self.user_id, denied_id, limit=0)).allowed)
            self.assertFalse(await _settle(session, denied_id))
            self.assertFalse(await _refund(session, denied_id))
            self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")), 1)

    async def test_replay_checks_all_inputs_and_unique_persisted_intent(self):
        reservation_id = uuid4()
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            await _open_account(session, self.user_id, opening=0)
            await _reserve(session, self.user_id, reservation_id)
            for changed in (
                {"user_id": str(uuid4())}, {"dimension": "other"},
                {"period": "202610"}, {"cost": 2}, {"limit": 4},
                {"intent_fingerprint": "b" * 64},
            ):
                original = {
                    "user_id": self.user_id, "dimension": "ai", "period": "20261014",
                    "window": "day", "cost": 1, "limit": 5,
                    "intent_fingerprint": _fingerprint(reservation_id),
                }
                original.update(changed)
                if changed.get("period") == "202610":
                    original["window"] = "month"
                with self.assertRaises(QuotaReplayConflict):
                    await read_quota_reservation(session, reservation_id, **original)
            with self.assertRaises(QuotaReplayConflict):
                await _reserve(session, str(uuid4()), reservation_id)
            with self.assertRaises(QuotaReplayConflict):
                await _reserve(session, self.user_id, reservation_id, fingerprint="b" * 64)
            with self.assertRaises(QuotaReplayConflict):
                await _reserve(session, self.user_id, uuid4(), fingerprint=_fingerprint(reservation_id))
            with self.assertRaises(ValueError):
                await _reserve(session, self.user_id, uuid4(), window="month")
            with self.assertRaises(ValueError):
                await _reserve(session, self.user_id, uuid4(), fingerprint="not-a-digest")
            self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")), 1)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM quota_ledger_reservations")), 1)

    async def test_uncertain_commit_and_rollback_reuse_same_id(self):
        committed_id, rolled_back_id = uuid4(), uuid4()
        with self.engine.begin() as connection:
            await _open_account(_AsyncConnection(connection), self.user_id, opening=0)
        try:
            with self.engine.begin() as connection:
                await _reserve(_AsyncConnection(connection), self.user_id, committed_id)
            raise ConnectionError("commit acknowledgement lost")
        except ConnectionError:
            pass
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            self.assertTrue((await _read(session, self.user_id, committed_id)).allowed)
            with self.assertRaises(QuotaReplayConflict):
                await _read(session, self.user_id, committed_id, fingerprint="b" * 64)
            self.assertEqual((await _reserve(session, self.user_id, committed_id)).used_after, 1)
        try:
            with self.engine.begin() as connection:
                await _reserve(_AsyncConnection(connection), self.user_id, rolled_back_id)
                raise ConnectionError("transaction abandoned before commit")
        except ConnectionError:
            pass
        with self.engine.begin() as connection:
            session = _AsyncConnection(connection)
            self.assertIsNone(await _read(session, self.user_id, rolled_back_id))
            self.assertEqual((await _reserve(session, self.user_id, rolled_back_id)).used_after, 2)
            self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")), 2)

    async def test_missing_refund_and_database_outage_fail_closed(self):
        with self.engine.begin() as connection:
            with self.assertRaises(QuotaReservationUnknown):
                await _refund(_AsyncConnection(connection), uuid4())
        connection = self.engine.connect()
        connection.close()
        with self.assertRaises(ResourceClosedError):
            await _reserve(_AsyncConnection(connection), self.user_id, uuid4())

    async def test_downgrade_refuses_even_with_an_empty_ledger(self):
        with self.engine.begin() as connection:
            migration = _migration()
            migration.op = Operations(MigrationContext.configure(connection))
            with self.assertRaises(RuntimeError):
                migration.downgrade()


def _local_postgres_url():
    value = os.getenv("TEST_POSTGRES_URL")
    if not value or os.getenv("TEST_POSTGRES_ALLOW_SCHEMA_CREATE") != "1":
        return None
    url = make_url(value)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    return value


@unittest.skipUnless(_local_postgres_url(), "requires explicitly enabled loopback test PostgreSQL")
class PostgresQuotaConcurrencyTests(unittest.TestCase):
    def test_concurrent_reservations_settlement_refunds_and_readback(self):
        # Never run against a production host. Each invocation owns one schema.
        schema = "quota_test_" + uuid4().hex
        admin = create_engine(_local_postgres_url())
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(_local_postgres_url(), connect_args={"options": f"-c search_path={schema}"})
        try:
            user_id = str(uuid4())
            with engine.begin() as connection:
                _upgrade(connection)
                asyncio.run(_open_account(_AsyncConnection(connection), user_id, opening=0))
            with engine.begin() as connection:
                with self.assertRaises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(text(
                            "UPDATE quota_ledger_accounts SET opening_used = NULL"
                        ))
                with self.assertRaises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(text(
                            "UPDATE quota_ledger_accounts SET source_ref = ''"
                        ))
            barrier = Barrier(2)

            def reserve_one(reservation_id):
                with engine.begin() as connection:
                    barrier.wait(timeout=10)
                    return asyncio.run(_reserve(_AsyncConnection(connection), user_id, reservation_id, cost=1, limit=1))

            ids = [uuid4(), uuid4()]
            with ThreadPoolExecutor(max_workers=2) as pool:
                decisions = list(pool.map(reserve_one, ids))
            self.assertEqual(sum(decision.allowed for decision in decisions), 1)
            winner = next(decision for decision in decisions if decision.allowed)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda _: asyncio.run(_refund_in_new_transaction(engine, UUID(winner.reservation_id))),
                    range(2),
                ))
            self.assertCountEqual(results, [True, False])
            shared_id = uuid4()
            with ThreadPoolExecutor(max_workers=2) as pool:
                repeated = list(pool.map(reserve_one, [shared_id, shared_id]))
            self.assertEqual(repeated[0], repeated[1])
            self.assertTrue(repeated[0].allowed)

            terminal_barrier = Barrier(2)

            def finish(kind):
                with engine.begin() as connection:
                    terminal_barrier.wait(timeout=10)
                    session = _AsyncConnection(connection)
                    return asyncio.run(_settle(session, shared_id) if kind == "settle" else _refund(session, shared_id))

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(finish, ["settle", "refund"]))
            self.assertCountEqual(outcomes, [True, False])
            with engine.connect() as connection:
                terminal = asyncio.run(_read(_AsyncConnection(connection), user_id, shared_id, limit=1))
                self.assertIn(terminal.state, {"settled", "refunded"})
                self.assertFalse(terminal.allowed)
                self.assertEqual(connection.scalar(text("SELECT used FROM quota_ledger_accounts")),
                                 1 if terminal.state == "settled" else 0)
                self.assertEqual(connection.scalar(text(
                    "SELECT count(*) FROM quota_ledger_reservations WHERE id = :id"
                ), {"id": str(shared_id)}), 1)

            committed_id = uuid4()
            try:
                with engine.begin() as connection:
                    asyncio.run(_reserve(
                        _AsyncConnection(connection), user_id, committed_id, limit=None,
                    ))
                raise ConnectionError("commit acknowledgement lost")
            except ConnectionError:
                pass
            with engine.begin() as connection:
                session = _AsyncConnection(connection)
                prior = asyncio.run(_read(session, user_id, committed_id, limit=None))
                self.assertTrue(prior.allowed)
                for changed in (
                    {"user_id": str(uuid4())}, {"cost": 2}, {"limit": 5},
                    {"period": "202610", "window": "month"},
                    {"intent_fingerprint": "b" * 64},
                ):
                    expected = {
                        "user_id": user_id, "dimension": "ai", "period": "20261014",
                        "window": "day", "cost": 1, "limit": None,
                        "intent_fingerprint": _fingerprint(committed_id),
                    }
                    expected.update(changed)
                    with self.assertRaises(QuotaReplayConflict):
                        asyncio.run(read_quota_reservation(session, committed_id, **expected))
                self.assertEqual(asyncio.run(_reserve(session, user_id, committed_id, limit=None)), prior)
                with self.assertRaises(QuotaReplayConflict):
                    asyncio.run(_reserve(
                        session, user_id, uuid4(), limit=None, fingerprint=_fingerprint(committed_id),
                    ))

            settled_id = uuid4()
            with engine.begin() as connection:
                asyncio.run(_reserve(_AsyncConnection(connection), user_id, settled_id, limit=None))
            try:
                with engine.begin() as connection:
                    self.assertTrue(asyncio.run(_settle(_AsyncConnection(connection), settled_id)))
                raise ConnectionError("settlement commit acknowledgement lost")
            except ConnectionError:
                pass
            with engine.begin() as connection:
                session = _AsyncConnection(connection)
                self.assertFalse(asyncio.run(_settle(session, settled_id)))
                self.assertFalse(asyncio.run(_refund(session, settled_id)))
                self.assertEqual(asyncio.run(_read(session, user_id, settled_id, limit=None)).state, "settled")
                with self.assertRaises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(text(
                            "UPDATE quota_ledger_reservations "
                            "SET state = 'refunded', refunded_at = CURRENT_TIMESTAMP "
                            "WHERE id = :id"
                        ), {"id": str(settled_id)})
        finally:
            engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


async def _refund_in_new_transaction(engine, reservation_id):
    with engine.begin() as connection:
        return await _refund(_AsyncConnection(connection), reservation_id)

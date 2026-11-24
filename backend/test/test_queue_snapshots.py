"""Celery queue snapshots: sampling, persistence, admin API and backlog alerts."""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.celery_app as celery_module
from app.api import job_routes
from app.database import models
from app.services import admin_alert_service, queue_snapshot_service

QUEUE_TABLE_SQL = "DELETE FROM celery_queue_snapshots"


# ── Pure math helpers ─────────────────────────────────────────────────────────


def test_compute_oldest_age_tracks_the_tail_message_and_resets():
    assert queue_snapshot_service.compute_oldest_age(None, None, 100.0) == (None, None)

    stored, age = queue_snapshot_service.compute_oldest_age(None, "msg-1", 100.0)
    assert stored == {"id": "msg-1", "first_seen": 100.0}
    assert age == 0

    same, age = queue_snapshot_service.compute_oldest_age(stored, "msg-1", 160.0)
    assert same == stored
    assert age == 60

    reset, age = queue_snapshot_service.compute_oldest_age(stored, "msg-2", 250.0)
    assert reset == {"id": "msg-2", "first_seen": 250.0}
    assert age == 0

    repaired, age = queue_snapshot_service.compute_oldest_age(
        {"id": "msg-2", "first_seen": "not-a-timestamp"}, "msg-2", 300.0
    )
    assert repaired == {"id": "msg-2", "first_seen": 300.0}
    assert age == 0
    assert queue_snapshot_service.compute_oldest_age(["malformed"], "msg-3", 400.0) == (
        {"id": "msg-3", "first_seen": 400.0},
        0,
    )


def test_rate_per_minute_uses_consecutive_totals_and_clamps_negative_deltas():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert queue_snapshot_service.rate_per_minute(0, 60, start, start + timedelta(minutes=1)) == 60.0
    assert queue_snapshot_service.rate_per_minute(100, 160, start, start + timedelta(minutes=2)) == 30.0
    assert queue_snapshot_service.rate_per_minute(100, 90, start, start + timedelta(minutes=1)) == 0.0
    assert queue_snapshot_service.rate_per_minute(0, 10, start, start) is None


def test_compute_series_rates_returns_per_tick_throughput():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            sampled_at=start,
            depth=4,
            oldest_age_seconds=10,
            enqueued_total=100,
            completed_total=96,
        ),
        SimpleNamespace(
            sampled_at=start + timedelta(minutes=1),
            depth=8,
            oldest_age_seconds=70,
            enqueued_total=160,
            completed_total=152,
        ),
        SimpleNamespace(
            sampled_at=start + timedelta(minutes=3),
            depth=2,
            oldest_age_seconds=None,
            enqueued_total=220,
            completed_total=218,
        ),
    ]

    series = queue_snapshot_service.compute_series_rates(rows)

    assert len(series) == 2
    assert series[0]["depth"] == 8
    assert series[0]["oldest_age_seconds"] == 70
    assert series[0]["enqueue_rate_per_minute"] == 60.0
    assert series[0]["completion_rate_per_minute"] == 56.0
    # Two-minute gap: 60 enqueued and 66 completed => 30/min and 33/min.
    assert series[1]["enqueue_rate_per_minute"] == 30.0
    assert series[1]["completion_rate_per_minute"] == 33.0


def test_queue_status_thresholds_are_inclusive_and_backlog_wins():
    assert queue_snapshot_service.queue_status(0, None) == "healthy"
    assert queue_snapshot_service.queue_status(99, 599) == "healthy"
    assert queue_snapshot_service.queue_status(100, None) == "backlogged"
    assert queue_snapshot_service.queue_status(0, 600) == "stale"
    assert queue_snapshot_service.queue_status(100, 600) == "backlogged"


# ── Celery Beat sampler ───────────────────────────────────────────────────────


class _FakeBrokerRedis:
    def __init__(self, *, lists=None, values=None):
        self.lists = lists or {}
        self.values = values or {}
        self.deleted: list[str] = []

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lindex(self, key: str, index: int):
        items = self.lists.get(key, [])
        try:
            return items[index]
        except IndexError:
            return None

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.deleted.append(key)


def _capture_sampler(monkeypatch, broker: _FakeBrokerRedis, *, now: float = 1000.0):
    rows: list[dict] = []
    gauges: dict[str, int] = {}

    monkeypatch.setattr(celery_module, "_get_broker_redis", lambda: broker)
    monkeypatch.setattr(celery_module, "set_queue_depth", lambda queue, depth: gauges.__setitem__(queue, depth))
    monkeypatch.setattr(celery_module, "_persist_snapshots_sync", lambda captured: rows.extend(captured))
    monkeypatch.setattr(celery_module, "time", SimpleNamespace(time=lambda: now))
    return rows, gauges


def test_sampler_handles_an_empty_broker(monkeypatch):
    broker = _FakeBrokerRedis()
    rows, gauges = _capture_sampler(monkeypatch, broker)

    result = celery_module.sample_queue_depths()

    assert result == {queue: 0 for queue in celery_module._SAMPLED_QUEUES}
    assert gauges == result
    assert {row["queue"] for row in rows} == set(celery_module._SAMPLED_QUEUES)
    assert all(row["depth"] == 0 for row in rows)
    assert all(row["oldest_age_seconds"] is None for row in rows)
    assert all(row["enqueued_total"] == 0 for row in rows)
    assert all(row["completed_total"] == 0 for row in rows)


def test_sampler_sums_priority_lists_and_tracks_oldest_message(monkeypatch):
    oldest = json.dumps({"headers": {"id": "oldest-latex"}})
    newer = json.dumps({"headers": {"id": "newer-latex"}})
    priority_tail = json.dumps({"headers": {"id": "priority-tail"}})
    marker_key = f"{celery_module._OLDEST_MARKER_PREFIX}latex"
    completed_key = f"{celery_module._COMPLETED_COUNTER_PREFIX}latex"
    broker = _FakeBrokerRedis(
        lists={
            # Redis lists are LPUSH/RPOP: head is newest, tail is oldest.
            "latex": [newer, oldest],
            "latex:1": [priority_tail],
        },
        values={
            marker_key: json.dumps({"id": "oldest-latex", "first_seen": 900.0}),
            completed_key: "4",
        },
    )
    rows, gauges = _capture_sampler(monkeypatch, broker, now=1000.0)

    result = celery_module.sample_queue_depths()

    assert result["latex"] == 3
    assert gauges["latex"] == 3
    latex_row = next(row for row in rows if row["queue"] == "latex")
    assert latex_row == {
        "queue": "latex",
        "depth": 3,
        "oldest_age_seconds": 100,
        "enqueued_total": 7,
        "completed_total": 4,
    }
    # The same tail message keeps its first-seen marker and ages on the next tick.
    assert json.loads(broker.values[marker_key]) == {"id": "oldest-latex", "first_seen": 900.0}


def test_sampler_survives_an_unavailable_broker(monkeypatch):
    def unavailable():
        raise ConnectionError("broker down")

    monkeypatch.setattr(celery_module, "_get_broker_redis", unavailable)

    assert celery_module.sample_queue_depths() == {}


# ── Durable persistence and API ───────────────────────────────────────────────


async def _clear_snapshots(db: AsyncSession) -> None:
    await db.execute(text(QUEUE_TABLE_SQL))
    await db.commit()


@pytest.fixture
async def clean_queue_snapshots(db_session: AsyncSession):
    await _clear_snapshots(db_session)
    yield
    await _clear_snapshots(db_session)


async def _create_user(db: AsyncSession, *, role: str) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Queue Ops', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"queue_ops_{user_id.replace('-', '')}@example.com",
            "role": role,
        },
    )
    await db.commit()
    return user_id


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id = await _create_user(db, role=role)
    token = f"queue_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _insert_snapshot(
    db: AsyncSession,
    *,
    queue: str,
    depth: int,
    oldest_age_seconds: int | None,
    enqueued_total: int,
    completed_total: int,
    sampled_at: datetime,
) -> None:
    db.add(
        models.CeleryQueueSnapshot(
            queue=queue,
            depth=depth,
            oldest_age_seconds=oldest_age_seconds,
            enqueued_total=enqueued_total,
            completed_total=completed_total,
            sampled_at=sampled_at,
        )
    )
    await db.commit()


async def test_persisted_snapshots_drive_latest_metrics_and_rates(
    db_session: AsyncSession, clean_queue_snapshots
):
    now = datetime.now(timezone.utc)
    queue = f"test-metrics-{uuid.uuid4().hex[:8]}"
    await _insert_snapshot(
        db_session,
        queue=queue,
        depth=10,
        oldest_age_seconds=60,
        enqueued_total=100,
        completed_total=90,
        sampled_at=now - timedelta(minutes=1),
    )
    await _insert_snapshot(
        db_session,
        queue=queue,
        depth=120,
        oldest_age_seconds=700,
        enqueued_total=160,
        completed_total=130,
        sampled_at=now,
    )

    latest = await queue_snapshot_service.latest_snapshot_map(db_session)
    assert latest[queue].depth == 120

    metrics = await queue_snapshot_service.get_queue_metrics(db_session)
    entry = next(item for item in metrics["queues"] if item["queue"] == queue)
    assert entry["depth"] == 120
    assert entry["oldest_age_seconds"] == 700
    assert entry["status"] == "backlogged"
    assert entry["enqueue_rate_per_minute"] == 60.0
    assert entry["completion_rate_per_minute"] == 40.0
    assert len(metrics["throughput"][queue]) == 1


async def test_purge_snapshots_removes_only_expired_rows(
    db_session: AsyncSession, clean_queue_snapshots
):
    now = datetime.now(timezone.utc)
    old_queue = f"test-old-{uuid.uuid4().hex[:8]}"
    new_queue = f"test-new-{uuid.uuid4().hex[:8]}"
    await _insert_snapshot(
        db_session,
        queue=old_queue,
        depth=1,
        oldest_age_seconds=None,
        enqueued_total=1,
        completed_total=0,
        sampled_at=now - timedelta(hours=25),
    )
    await _insert_snapshot(
        db_session,
        queue=new_queue,
        depth=0,
        oldest_age_seconds=None,
        enqueued_total=1,
        completed_total=1,
        sampled_at=now,
    )

    removed = await queue_snapshot_service.purge_snapshots(db_session)

    assert removed == 1
    remaining = (
        await db_session.execute(
            text("SELECT queue FROM celery_queue_snapshots WHERE queue IN (:old, :new)"),
            {"old": old_queue, "new": new_queue},
        )
    ).scalars().all()
    assert remaining == [new_queue]


async def test_queue_endpoint_requires_an_admin(
    client: AsyncClient, db_session: AsyncSession
):
    anonymous = await client.get("/admin/operations/queues")
    assert anonymous.status_code == 401

    support_headers = await _headers(db_session, "support")
    supported = await client.get("/admin/operations/queues", headers=support_headers)
    assert supported.status_code == 403


async def test_queue_endpoint_returns_aggregates_without_secrets(
    client: AsyncClient, db_session: AsyncSession, clean_queue_snapshots
):
    admin_headers = await _headers(db_session)
    now = datetime.now(timezone.utc)
    queue = f"test-api-{uuid.uuid4().hex[:8]}"
    await _insert_snapshot(
        db_session,
        queue=queue,
        depth=10,
        oldest_age_seconds=60,
        enqueued_total=100,
        completed_total=90,
        sampled_at=now - timedelta(minutes=1),
    )
    await _insert_snapshot(
        db_session,
        queue=queue,
        depth=120,
        oldest_age_seconds=700,
        enqueued_total=160,
        completed_total=130,
        sampled_at=now,
    )

    response = await client.get("/admin/operations/queues", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    entry = next(item for item in body["queues"] if item["queue"] == queue)
    assert entry["depth"] == 120
    assert entry["oldest_age_seconds"] == 700
    assert entry["status"] == "backlogged"
    assert entry["enqueue_rate_per_minute"] == 60.0
    assert entry["completion_rate_per_minute"] == 40.0
    assert body["throughput"][queue][0]["depth"] == 120
    for secret in ("redis://", "password", "CELERY_BROKER_URL", "latex_content"):
        assert secret not in response.text


async def test_queue_endpoint_is_empty_before_the_first_sample(
    client: AsyncClient, db_session: AsyncSession, clean_queue_snapshots
):
    admin_headers = await _headers(db_session)

    response = await client.get("/admin/operations/queues", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["queues"] == []
    assert response.json()["throughput"] == {}


async def test_jobs_health_reports_real_depths_and_worker_count(
    client: AsyncClient,
    db_session: AsyncSession,
    clean_queue_snapshots,
    monkeypatch: pytest.MonkeyPatch,
):
    now = datetime.now(timezone.utc)
    queue = f"test-health-{uuid.uuid4().hex[:8]}"
    await _insert_snapshot(
        db_session,
        queue=queue,
        depth=7,
        oldest_age_seconds=30,
        enqueued_total=9,
        completed_total=2,
        sampled_at=now,
    )
    monkeypatch.setattr(job_routes, "_count_workers", AsyncMock(return_value=2))

    response = await client.get("/jobs/health")

    assert response.status_code == 200
    body = response.json()
    assert body["queue_depths"][queue] == 7
    assert body["worker_count"] == 2
    assert "redis://" not in response.text


async def test_jobs_health_empty_broker_does_not_degrade(
    client: AsyncClient,
    db_session: AsyncSession,
    clean_queue_snapshots,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(job_routes, "_count_workers", AsyncMock(return_value=None))

    response = await client.get("/jobs/health")

    assert response.status_code == 200
    body = response.json()
    assert body["queue_depths"] == {}
    assert "worker_count" not in body


# ── Backlog alert rule ────────────────────────────────────────────────────────


async def test_queue_backlog_alerts_at_depth_and_age_thresholds(
    db_session: AsyncSession, clean_queue_snapshots
):
    now = datetime.now(timezone.utc)
    healthy = f"test-q-healthy-{uuid.uuid4().hex[:8]}"
    backlogged = f"test-q-depth-{uuid.uuid4().hex[:8]}"
    stale = f"test-q-stale-{uuid.uuid4().hex[:8]}"
    await _insert_snapshot(
        db_session,
        queue=healthy,
        depth=99,
        oldest_age_seconds=599,
        enqueued_total=99,
        completed_total=0,
        sampled_at=now,
    )
    await _insert_snapshot(
        db_session,
        queue=backlogged,
        depth=100,
        oldest_age_seconds=None,
        enqueued_total=100,
        completed_total=0,
        sampled_at=now,
    )
    await _insert_snapshot(
        db_session,
        queue=stale,
        depth=0,
        oldest_age_seconds=600,
        enqueued_total=1,
        completed_total=1,
        sampled_at=now,
    )

    signals = await admin_alert_service.collect_signals(db_session, now)
    backlog = {signal["dedupe_key"]: signal for signal in signals if signal["kind"] == "queue.backlog"}

    assert f"queue.backlog.{healthy}" not in backlog
    assert backlog[f"queue.backlog.{backlogged}"]["payload"] == {
        "queue": backlogged,
        "depth": 100,
        "oldest_age_seconds": None,
        "status": "backlogged",
    }
    assert backlog[f"queue.backlog.{stale}"]["payload"]["status"] == "stale"
    assert backlog[f"queue.backlog.{stale}"]["severity"] == "high"
    assert backlog[f"queue.backlog.{stale}"]["owner"] == "Platform"
    assert "redis://" not in str(backlog)


# ── Migration contract ────────────────────────────────────────────────────────


def _migration():
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0080_queue_snapshots.py"
    )
    spec = importlib.util.spec_from_file_location("queue_snapshots_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queue_snapshot_migration_chains_from_0079():
    migration = _migration()
    calls: list[tuple] = []

    class FakeOp:
        def create_table(self, table: str, *items, **kwargs) -> None:
            calls.append(("create_table", table, items, kwargs))

        def create_index(self, name: str, table: str, columns: list[str]) -> None:
            calls.append(("create_index", name, table, columns))

        def drop_index(self, name: str, table_name: str) -> None:
            calls.append(("drop_index", name, table_name))

        def drop_table(self, table: str) -> None:
            calls.append(("drop_table", table))

    migration.op = FakeOp()
    migration.upgrade()

    assert migration.revision == "0080_queue_snapshots"
    assert migration.down_revision == "0079_tenant_domain_expiry"
    assert calls[0][0] == "create_table"
    assert calls[0][1] == "celery_queue_snapshots"
    column_names = [item.name for item in calls[0][2] if hasattr(item, "name")]
    assert {"id", "queue", "depth", "oldest_age_seconds", "enqueued_total", "completed_total", "sampled_at"} <= set(column_names)
    constraint_names = [item.name for item in calls[0][2] if type(item).__name__ == "CheckConstraint"]
    assert {"ck_queue_snapshots_depth", "ck_queue_snapshots_age"} == set(constraint_names)
    assert calls[1] == (
        "create_index",
        "idx_queue_snapshots_queue_sampled",
        "celery_queue_snapshots",
        ["queue", "sampled_at"],
    )

    calls.clear()
    migration.downgrade()
    assert calls == [
        ("drop_index", "idx_queue_snapshots_queue_sampled", "celery_queue_snapshots"),
        ("drop_table", "celery_queue_snapshots"),
    ]


def test_queue_snapshot_model_matches_the_migration():
    columns = models.CeleryQueueSnapshot.__table__.c
    assert set(columns.keys()) == {
        "id",
        "queue",
        "depth",
        "oldest_age_seconds",
        "enqueued_total",
        "completed_total",
        "sampled_at",
    }
    assert columns["oldest_age_seconds"].nullable is True
    assert columns["depth"].nullable is False
    assert columns["enqueued_total"].default is not None

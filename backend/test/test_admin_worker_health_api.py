"""Admin worker/container health: heartbeats, stale detection and privacy."""

from __future__ import annotations

import fnmatch
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_operations_service, worker_health_service

HEARTBEAT_PREFIX = worker_health_service.HEARTBEAT_KEY_PREFIX
EXPECTED_QUEUES = list(worker_health_service.EXPECTED_QUEUES)


class _FakeAsyncRedis:
    """In-memory Redis surface used by the heartbeat reader and health probe."""

    def __init__(self, values: dict[str, str] | None = None):
        self.values = dict(values or {})

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def scan_iter(self, match: str = "*", count: int = 100):
        for key in list(self.values):
            if fnmatch.fnmatch(key, match):
                yield key


class _OutageRedis:
    def scan_iter(self, *args, **kwargs):
        raise RuntimeError("redis://latexy:super-secret@provider-host:6379/0")


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_worker_health_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Worker Health User",
            "role": role,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"worker_health_sess_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


@pytest.fixture(autouse=True)
def _clear_health_cache():
    admin_operations_service.reset_admin_operations_cache()
    yield
    admin_operations_service.reset_admin_operations_cache()


@pytest.fixture
def heartbeat_redis(monkeypatch: pytest.MonkeyPatch):
    """Replace the shared Redis client so the test cannot be flushed by peers."""
    from app.core import redis as redis_module

    client = _FakeAsyncRedis()
    monkeypatch.setattr(redis_module.redis_manager, "redis_client", client)
    return client


def _write_heartbeat(
    store: _FakeAsyncRedis,
    *,
    worker_id: str = "celery-test0001",
    kind: str = "celery",
    queues: list[str] | None = None,
    recorded_at: datetime | None = None,
    cpu_percent: float | None = 12.5,
    memory_percent: float | None = 30.0,
    memory_mb: float | None = 256.0,
    extra: dict | None = None,
) -> dict:
    payload = {
        "worker_id": worker_id,
        "kind": kind,
        "queues": EXPECTED_QUEUES if queues is None else queues,
        "recorded_at": (recorded_at or datetime.now(timezone.utc)).isoformat(),
    }
    if cpu_percent is not None:
        payload["cpu_percent"] = cpu_percent
    if memory_percent is not None:
        payload["memory_percent"] = memory_percent
    if memory_mb is not None:
        payload["memory_mb"] = memory_mb
    if extra:
        payload.update(extra)
    store.values[f"{HEARTBEAT_PREFIX}{worker_id}"] = json.dumps(payload)
    return payload


def _heartbeat_payload(
    *,
    recorded_at: datetime,
    queues: list[str] | None = None,
    cpu_percent: float | None = 12.5,
    memory_percent: float | None = 30.0,
) -> dict:
    payload = {
        "worker_id": "celery-classify",
        "kind": "celery",
        "queues": EXPECTED_QUEUES if queues is None else queues,
        "recorded_at": recorded_at.isoformat(),
    }
    if cpu_percent is not None:
        payload["cpu_percent"] = cpu_percent
    if memory_percent is not None:
        payload["memory_percent"] = memory_percent
    if cpu_percent is not None and memory_percent is not None:
        payload["memory_mb"] = 128.0
    return payload


def test_worker_queue_discovery_prefers_consumed_queues():
    sender = SimpleNamespace(
        task_consumer=SimpleNamespace(queues=[SimpleNamespace(name="latex"), SimpleNamespace(name="llm")]),
        app=None,
    )
    assert worker_health_service.queues_from_worker(sender) == ["latex", "llm"]


def test_worker_status_mapping_healthy_degraded_and_unhealthy():
    now = datetime.now(timezone.utc)

    healthy = worker_health_service.classify_worker(
        _heartbeat_payload(recorded_at=now - timedelta(seconds=10)), now=now
    )
    assert healthy is not None
    assert healthy["status"] == "healthy"
    assert healthy["age_seconds"] == 10

    degraded = worker_health_service.classify_worker(
        _heartbeat_payload(recorded_at=now - timedelta(seconds=90)), now=now
    )
    assert degraded is not None
    assert degraded["status"] == "degraded"

    missing_metrics = worker_health_service.classify_worker(
        _heartbeat_payload(
            recorded_at=now - timedelta(seconds=10),
            cpu_percent=None,
        ),
        now=now,
    )
    assert missing_metrics is not None
    assert missing_metrics["status"] == "degraded"
    assert missing_metrics["missing_metrics"] is True

    missing_ownership = worker_health_service.classify_worker(
        _heartbeat_payload(recorded_at=now - timedelta(seconds=10), queues=[]),
        now=now,
    )
    assert missing_ownership is not None
    assert missing_ownership["status"] == "degraded"
    assert missing_ownership["missing_queue_ownership"] is True

    stale = worker_health_service.classify_worker(_heartbeat_payload(recorded_at=now - timedelta(seconds=300)), now=now)
    assert stale is not None
    assert stale["status"] == "unhealthy"
    assert stale["age_seconds"] == 300


def test_heartbeat_writer_sanitizes_identity_queues_and_metrics(monkeypatch):
    class _FakeWriter:
        def __init__(self):
            self.calls = []

        def set(self, key, value, ex=None):
            self.calls.append((key, value, ex))

    monkeypatch.setattr(
        worker_health_service,
        "_resource_snapshot",
        lambda: {"cpu_percent": 22.2, "memory_percent": 44.4, "memory_mb": 555.5},
    )
    writer = _FakeWriter()
    assert worker_health_service.record_worker_heartbeat(
        kind="celery",
        queues=["latex", "latex", "not a queue"],
        client=writer,
        worker_id="raw-host-or-container-id",
        recorded_at=datetime.now(timezone.utc),
    )

    assert len(writer.calls) == 1
    key, value, ttl = writer.calls[0]
    payload = json.loads(value)
    assert key == f"{HEARTBEAT_PREFIX}{payload['worker_id']}"
    assert ttl == worker_health_service.HEARTBEAT_TTL_SECONDS
    assert payload["worker_id"].startswith("celery-")
    assert payload["worker_id"] != "raw-host-or-container-id"
    assert payload["queues"] == ["latex"]
    assert payload["cpu_percent"] == 22.2
    assert payload["memory_percent"] == 44.4
    assert payload["memory_mb"] == 555.5
    assert set(payload) == {
        "worker_id",
        "kind",
        "queues",
        "recorded_at",
        "cpu_percent",
        "memory_percent",
        "memory_mb",
    }

    assert not worker_health_service.record_worker_heartbeat(kind="not-a-worker", client=writer)
    assert len(writer.calls) == 1


async def test_worker_health_requires_admin(client: AsyncClient, db_session: AsyncSession, heartbeat_redis):
    anonymous = await client.get("/admin/operations/health")
    assert anonymous.status_code == 401

    support_headers = await _headers(db_session, "support")
    supported = await client.get("/admin/operations/health", headers=support_headers)
    assert supported.status_code == 403

    admin_headers = await _headers(db_session, "admin")
    allowed = await client.get("/admin/operations/health", headers=admin_headers)
    assert allowed.status_code == 200


async def test_health_exposes_healthy_worker_and_queue_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    heartbeat_redis,
):
    admin_headers = await _headers(db_session, "admin")
    _write_heartbeat(heartbeat_redis, worker_id="celery-healthy0001")

    response = await client.get("/admin/operations/health", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    workers = body["workers"]

    assert workers["status"] == "healthy"
    assert workers["read_ok"] is True
    assert workers["last_check_at"]
    assert workers["active_workers"] == 1
    assert workers["stale_workers"] == 0
    assert workers["missing_metrics"] == 0
    assert workers["unowned_queues"] == []
    assert workers["queue_ownership"]["latex"] == 1
    assert body["sections"]["workers"]["status"] == "healthy"
    assert workers["providers"][0]["console_url"].startswith("https://modal.com/")

    component = workers["components"][0]
    assert component["worker_id"] == "celery-healthy0001"
    assert component["kind"] == "celery"
    assert component["status"] == "healthy"
    assert component["cpu_percent"] == 12.5
    assert component["memory_percent"] == 30.0
    assert component["memory_mb"] == 256.0
    assert component["queues"] == sorted(EXPECTED_QUEUES)
    assert "recorded_at" not in component


async def test_health_marks_missing_metrics_degraded(
    client: AsyncClient,
    db_session: AsyncSession,
    heartbeat_redis,
):
    admin_headers = await _headers(db_session, "admin")
    _write_heartbeat(
        heartbeat_redis,
        worker_id="celery-nometrics01",
        memory_percent=None,
        memory_mb=None,
    )

    response = await client.get("/admin/operations/health", headers=admin_headers)
    body = response.json()
    workers = body["workers"]
    assert workers["status"] == "degraded"
    assert workers["missing_metrics"] == 1
    assert workers["components"][0]["missing_metrics"] is True
    assert workers["components"][0]["status"] == "degraded"
    assert body["sections"]["workers"]["status"] == "degraded"


async def test_health_reports_stale_workers_and_partial_queue_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    heartbeat_redis,
):
    admin_headers = await _headers(db_session, "admin")
    _write_heartbeat(
        heartbeat_redis,
        worker_id="celery-stale000001",
        recorded_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    _write_heartbeat(
        heartbeat_redis,
        worker_id="celery-fresh000001",
        queues=["latex"],
    )

    response = await client.get("/admin/operations/health", headers=admin_headers)
    body = response.json()
    workers = body["workers"]

    assert workers["status"] == "unhealthy"
    assert workers["stale_workers"] == 1
    assert workers["active_workers"] == 1
    assert any(component["status"] == "unhealthy" for component in workers["components"])
    stale = next(component for component in workers["components"] if component["worker_id"] == "celery-stale000001")
    assert stale["age_seconds"] >= 300
    assert "llm" in workers["unowned_queues"]
    assert "latex" not in workers["unowned_queues"]
    assert "stale" in (workers["detail"] or "")
    assert body["sections"]["workers"]["stale_workers"] == 1


async def test_health_reports_no_heartbeats(
    client: AsyncClient,
    db_session: AsyncSession,
    heartbeat_redis,
):
    admin_headers = await _headers(db_session, "admin")
    response = await client.get("/admin/operations/health", headers=admin_headers)
    body = response.json()
    assert body["workers"]["status"] == "unhealthy"
    assert body["workers"]["read_ok"] is True
    assert body["workers"]["components"] == []
    assert body["workers"]["detail"] == "No worker heartbeats have been received"
    assert body["sections"]["workers"]["status"] == "unhealthy"


async def test_health_survives_provider_outage_without_leaking_details(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    admin_headers = await _headers(db_session, "admin")

    from app.core import redis as redis_module

    monkeypatch.setattr(redis_module.redis_manager, "redis_client", _OutageRedis())

    response = await client.get("/admin/operations/health", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["workers"]["status"] == "unhealthy"
    assert body["workers"]["read_ok"] is False
    assert body["workers"]["detail"] == "Worker heartbeats could not be read"
    assert "super-secret" not in response.text
    assert "provider-host" not in response.text
    assert "redis://" not in response.text


async def test_health_ignores_untrusted_heartbeat_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    heartbeat_redis,
):
    admin_headers = await _headers(db_session, "admin")
    _write_heartbeat(
        heartbeat_redis,
        worker_id="celery-private0001",
        extra={
            "redis_url": "redis://latexy:super-secret@provider-host:6379/0",
            "container_id": "raw-container-abc123",
            "hostname": "production-host-01",
            "environment": {"REDIS_PASSWORD": "super-secret"},
        },
    )
    heartbeat_redis.values[f"{HEARTBEAT_PREFIX}broken"] = "{not-json"

    response = await client.get("/admin/operations/health", headers=admin_headers)
    assert response.status_code == 200
    assert "super-secret" not in response.text
    assert "provider-host" not in response.text
    assert "raw-container-abc123" not in response.text
    assert "production-host-01" not in response.text
    assert "REDIS_PASSWORD" not in response.text

    body = response.json()
    assert len(body["workers"]["components"]) == 1
    component = body["workers"]["components"][0]
    assert set(component) == {
        "worker_id",
        "kind",
        "status",
        "last_seen",
        "age_seconds",
        "cpu_percent",
        "memory_percent",
        "memory_mb",
        "queues",
        "missing_metrics",
        "missing_queue_ownership",
    }

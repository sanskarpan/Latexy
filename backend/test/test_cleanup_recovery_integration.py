"""Real Postgres/Redis recovery regressions for cleanup transport repair."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import redis
from sqlalchemy import delete, text

from app.database.models import JobFinalization
from app.workers.cleanup_worker import (
    _FINALIZATION_DB_UNAVAILABLE,
    _FINALIZATION_EXPIRED,
    _normalize_recovery_ttl,
    _read_finalization_outcome,
    _reconcile_receipts_without_compilation_rows,
    _replay_durable_completion,
)
from app.workers.job_lifecycle import lifecycle_key


@pytest.fixture
def queue_redis():
    client = redis.from_url(os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15"))
    client.ping()
    yield client
    client.close()


@pytest.fixture
def cache_redis():
    client = redis.from_url(os.environ.get("TEST_REDIS_CACHE_URL", "redis://localhost:6380/14"))
    client.ping()
    yield client
    client.close()


async def _insert_finalization(db_session, job_id: str, state: str, payload: dict, expires_at):
    db_session.add(
        JobFinalization(
            job_id=job_id,
            state=state,
            terminal_result="cancelled" if state == "cancelled" else "failed",
            result_payload=payload,
            expires_at=expires_at,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_completed_commit_replays_after_publication_crash_with_remaining_ttl(
    db_session, queue_redis
):
    job_id = f"test_recovery_completed_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
    payload = {"success": True, "job_type": "llm", "message": "recovered"}
    await _insert_finalization(db_session, job_id, "completed", payload, expires_at)
    try:
        state, durable_payload, ttl = await asyncio.to_thread(_read_finalization_outcome, job_id)
        assert state == "completed"
        assert durable_payload == payload
        assert ttl is not None and 0 < ttl <= 90
        assert _replay_durable_completion(queue_redis, job_id, durable_payload, ttl)

        stored = json.loads(queue_redis.get(f"latexy:job:{job_id}:result"))
        assert stored["success"] is True
        assert queue_redis.hget(lifecycle_key(job_id), "status") == b"completed"
        events = queue_redis.xrange(f"latexy:stream:{job_id}")
        assert any(json.loads(fields[b"payload"])["type"] == "job.completed" for _, fields in events)
        assert queue_redis.ttl(f"latexy:job:{job_id}:result") <= ttl
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
        )
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_near_expiry_replay_uses_floor_ttl_without_refreshing_retention(
    db_session, queue_redis
):
    job_id = f"test_recovery_near_expiry_{uuid.uuid4().hex}"
    await _insert_finalization(
        db_session,
        job_id,
        "completed",
        {"success": True, "job_type": "llm"},
        datetime.now(timezone.utc) + timedelta(seconds=8),
    )
    try:
        state, payload, ttl = await asyncio.to_thread(_read_finalization_outcome, job_id)
        assert state == "completed"
        assert ttl is not None and 1 <= ttl <= 8
        # Simulate a publication retry delay. The DB-read TTL carries its
        # monotonic origin, so replay must not refresh the original deadline.
        time.sleep(1.1)
        delayed_ttl = _normalize_recovery_ttl(ttl)
        assert delayed_ttl is not None and delayed_ttl < ttl
        assert await asyncio.to_thread(
            _replay_durable_completion, queue_redis, job_id, payload, ttl
        )
        assert 0 < queue_redis.ttl(f"latexy:job:{job_id}:result") <= delayed_ttl
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
        )
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_subsecond_and_nonfinite_db_retention_fail_closed(
    db_session, queue_redis
):
    subsecond_job = f"test_recovery_subsecond_{uuid.uuid4().hex}"
    nonfinite_job = f"test_recovery_nonfinite_{uuid.uuid4().hex}"
    await _insert_finalization(
        db_session,
        subsecond_job,
        "completed",
        {"success": True},
        datetime.now(timezone.utc) + timedelta(milliseconds=250),
    )
    await _insert_finalization(
        db_session,
        nonfinite_job,
        "completed",
        {"success": True},
        datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    await db_session.execute(
        text("UPDATE job_finalizations SET expires_at = 'infinity' WHERE job_id = :job_id"),
        {"job_id": nonfinite_job},
    )
    await db_session.commit()
    try:
        state, payload, ttl = await asyncio.to_thread(
            _read_finalization_outcome, subsecond_job
        )
        assert state == _FINALIZATION_EXPIRED
        assert payload is None and ttl is None

        state, payload, ttl = await asyncio.to_thread(
            _read_finalization_outcome, nonfinite_job
        )
        assert state == _FINALIZATION_DB_UNAVAILABLE
        assert payload is None and ttl is None

        for invalid_ttl in (float("nan"), float("inf"), float("-inf"), 0.5):
            replay_job = f"test_recovery_invalid_ttl_{uuid.uuid4().hex}"
            assert not await asyncio.to_thread(
                _replay_durable_completion,
                queue_redis,
                replay_job,
                {"success": True},
                invalid_ttl,
            )
            assert queue_redis.exists(f"latexy:job:{replay_job}:result") == 0
            queue_redis.delete(
                lifecycle_key(replay_job),
                f"latexy:job:{replay_job}:result",
                f"latexy:stream:{replay_job}",
                f"latexy:job:{replay_job}:seq",
            )
    finally:
        await db_session.execute(
            delete(JobFinalization).where(
                JobFinalization.job_id.in_([subsecond_job, nonfinite_job])
            )
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_pending_durable_row_does_not_clear_stale_success_receipt(
    db_session, queue_redis, cache_redis
):
    job_id = f"test_recovery_pending_success_{uuid.uuid4().hex}"
    period = "209901"
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    receipt = {
        "dimension": "optimizations",
        "user_id": "test-recovery-pending",
        "period": period,
        "cost": 1,
        "receipt_id": uuid.uuid4().hex,
        # Exercise the stale-marker path: durable pending evidence must win
        # over cleanup's Redis-only timeout heuristics.
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp(),
        "created_at_clock": "redis",
    }
    await _insert_finalization(
        db_session,
        job_id,
        "pending",
        {"success": True, "job_type": "llm"},
        datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    queue_redis.hset(
        lifecycle_key(job_id),
        mapping={"status": "running", "owner": "live-worker", "lease_until": "9999999999"},
    )
    queue_redis.set(
        f"latexy:job:{job_id}:result",
        json.dumps({"job_id": job_id, "success": True}),
        ex=300,
    )
    queue_redis.set(
        f"latexy:job:{job_id}:dispatch-started",
        "1",
        ex=300,
    )
    cache_redis.set(receipt_key, json.dumps(receipt), ex=3600)
    try:
        await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        )
        assert cache_redis.exists(receipt_key) == 1
        assert cache_redis.get(f"latexy:quota-terminal:{job_id}") is None
        state, _payload, _ttl = await asyncio.to_thread(_read_finalization_outcome, job_id)
        assert state == "pending"
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
            f"latexy:job:{job_id}:dispatch-started",
        )
        cache_redis.delete(receipt_key, f"latexy:quota-terminal:{job_id}")
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_legacy_receipt_clock_origin_is_retained_without_durable_proof(
    queue_redis, cache_redis
):
    job_id = f"test_recovery_legacy_clock_{uuid.uuid4().hex}"
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    cache_redis.set(
        receipt_key,
        json.dumps(
            {
                "dimension": "optimizations",
                "user_id": "test-recovery-legacy",
                "period": "209901",
                "cost": 1,
                "receipt_id": uuid.uuid4().hex,
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp(),
            }
        ),
        ex=3600,
    )
    try:
        await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        )
        assert cache_redis.exists(receipt_key) == 1
    finally:
        cache_redis.delete(receipt_key, f"latexy:quota-terminal:{job_id}")


@pytest.mark.asyncio
async def test_failed_cancelled_and_fenced_rows_replay_canonical_terminal_transport(
    db_session, queue_redis
):
    rows = []
    for state in ("failed", "cancelled", "fenced"):
        job_id = f"test_recovery_{state}_{uuid.uuid4().hex}"
        payload = {"success": False, "error_code": f"canonical_{state}"}
        await _insert_finalization(
            db_session,
            job_id,
            state,
            payload,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        rows.append((job_id, state, payload))
        # Simulate a Redis snapshot that still says the old worker is running.
        queue_redis.hset(
            lifecycle_key(job_id),
            mapping={"status": "running", "owner": "stale-worker", "lease_until": "9999999999"},
        )

    try:
        from app.workers.cleanup_worker import _replay_durable_terminal

        for job_id, state, payload in rows:
            durable_state, durable_payload, ttl = await asyncio.to_thread(
                _read_finalization_outcome, job_id
            )
            assert durable_state == state
            status = "cancelled" if state == "cancelled" else "failed"
            assert _replay_durable_terminal(
                queue_redis,
                job_id,
                durable_payload,
                terminal_status=status,
                ttl=ttl,
            )
            stored = json.loads(queue_redis.get(f"latexy:job:{job_id}:result"))
            assert stored["success"] is False
            assert stored["error_code"] == payload["error_code"]
            assert queue_redis.hget(lifecycle_key(job_id), "status") == status.encode()
    finally:
        for job_id, _state, _payload in rows:
            queue_redis.delete(
                lifecycle_key(job_id),
                f"latexy:job:{job_id}:result",
                f"latexy:stream:{job_id}",
                f"latexy:job:{job_id}:seq",
                f"latexy:job:{job_id}:state",
            )
            await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_failed_receipt_refunds_after_db_terminal_replay_even_with_live_redis_state(
    db_session, queue_redis, cache_redis
):
    job_id = f"test_recovery_receipt_{uuid.uuid4().hex}"
    period = "209901"
    counter_key = f"latexy:quota:optimizations:test-recovery:{period}"
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    receipt = {
        "dimension": "optimizations",
        "user_id": "test-recovery",
        "period": period,
        "cost": 1,
        "receipt_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).timestamp(),
        "created_at_clock": "redis",
    }
    payload = {"success": False, "error_code": "provider_failed"}
    await _insert_finalization(
        db_session,
        job_id,
        "failed",
        payload,
        datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    queue_redis.hset(
        lifecycle_key(job_id),
        mapping={"status": "completed", "owner": "stale-worker", "lease_until": "9999999999"},
    )
    queue_redis.set(
        f"latexy:job:{job_id}:result",
        json.dumps({"job_id": job_id, "success": True, "error": "stale success"}),
        ex=300,
    )
    cache_redis.set(counter_key, 1)
    cache_redis.set(receipt_key, json.dumps(receipt), ex=3600)
    try:
        assert await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        ) >= 1
        assert cache_redis.get(receipt_key) is None
        assert int(cache_redis.get(counter_key) or 0) == 0
        assert json.loads(queue_redis.get(f"latexy:job:{job_id}:result"))["error_code"] == "provider_failed"
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
        )
        cache_redis.delete(counter_key, receipt_key, f"latexy:quota-terminal:{job_id}")
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_state", ["failed", "cancelled"])
async def test_ai_assists_terminal_receipt_refunds_once(
    db_session, queue_redis, cache_redis, terminal_state
):
    job_id = f"test_recovery_ai_assists_{terminal_state}_{uuid.uuid4().hex}"
    period = "209901"
    counter_key = f"latexy:quota:ai_assists:test-recovery:{period}"
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    receipt = {
        "dimension": "ai_assists",
        "user_id": "test-recovery",
        "period": period,
        "cost": 1,
        "receipt_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).timestamp(),
        "created_at_clock": "redis",
    }
    payload = {
        "success": False,
        "cancelled": terminal_state == "cancelled",
        "error_code": f"canonical_{terminal_state}",
    }
    await _insert_finalization(
        db_session,
        job_id,
        terminal_state,
        payload,
        datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    queue_redis.hset(
        lifecycle_key(job_id),
        mapping={"status": "running", "owner": "stale-worker", "lease_until": "9999999999"},
    )
    cache_redis.set(counter_key, 1)
    cache_redis.set(receipt_key, json.dumps(receipt), ex=3600)
    try:
        assert await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        ) >= 1
        assert cache_redis.get(receipt_key) is None
        assert int(cache_redis.get(counter_key) or 0) == 0
        assert await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        ) == 0
        assert int(cache_redis.get(counter_key) or 0) == 0
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
        )
        cache_redis.delete(
            counter_key,
            receipt_key,
            f"latexy:quota-terminal:{job_id}",
            f"latexy:quota-refund:ai_assists:{job_id}",
        )
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_stale_redis_failure_fences_pending_db_row_before_refund(
    db_session, queue_redis, cache_redis
):
    job_id = f"test_recovery_pending_stale_failure_{uuid.uuid4().hex}"
    period = "209901"
    counter_key = f"latexy:quota:optimizations:test-recovery:{period}"
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    receipt = {
        "dimension": "optimizations",
        "user_id": "test-recovery",
        "period": period,
        "cost": 1,
        "receipt_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).timestamp(),
        "created_at_clock": "redis",
    }
    await _insert_finalization(
        db_session,
        job_id,
        "pending",
        {"success": False},
        datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    await db_session.execute(
        JobFinalization.__table__.update()
        .where(JobFinalization.job_id == job_id)
        .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    await db_session.commit()
    queue_redis.hset(
        lifecycle_key(job_id),
        mapping={"status": "failed", "owner": "stale-worker", "lease_until": "9999999999"},
    )
    cache_redis.set(counter_key, 1)
    cache_redis.set(receipt_key, json.dumps(receipt), ex=3600)
    try:
        assert await asyncio.to_thread(
            _reconcile_receipts_without_compilation_rows, queue_redis, cache_redis
        ) >= 1
        assert cache_redis.get(receipt_key) is None
        assert int(cache_redis.get(counter_key) or 0) == 0
        state, payload, _ttl = await asyncio.to_thread(_read_finalization_outcome, job_id)
        assert state == "fenced"
        assert payload["error_code"] == "terminal_failure"
        stored = json.loads(queue_redis.get(f"latexy:job:{job_id}:result"))
        assert stored["error_code"] == "terminal_failure"
    finally:
        queue_redis.delete(
            lifecycle_key(job_id),
            f"latexy:job:{job_id}:result",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}:seq",
            f"latexy:job:{job_id}:state",
        )
        cache_redis.delete(
            counter_key,
            receipt_key,
            f"latexy:quota-terminal:{job_id}",
            f"latexy:quota-refund:optimizations:{job_id}",
        )
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_expired_row_is_not_replayed_or_refunded_and_db_outage_fails_closed(
    db_session, monkeypatch
):
    expired_job = f"test_recovery_expired_{uuid.uuid4().hex}"
    await _insert_finalization(
        db_session,
        expired_job,
        "completed",
        {"success": True},
        datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    try:
        state, payload, ttl = await asyncio.to_thread(_read_finalization_outcome, expired_job)
        assert state == _FINALIZATION_EXPIRED
        assert payload is None and ttl is None

        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://127.0.0.1:1/unreachable")
        unavailable, payload, ttl = await asyncio.to_thread(
            _read_finalization_outcome, expired_job
        )
        assert unavailable == _FINALIZATION_DB_UNAVAILABLE
        assert payload is None and ttl is None
    finally:
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id == expired_job))
        await db_session.commit()

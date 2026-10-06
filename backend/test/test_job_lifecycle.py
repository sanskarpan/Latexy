"""Redis race tests for metered dispatch ownership fencing."""

from __future__ import annotations

import os
import time
import uuid
from unittest.mock import patch

import pytest
import redis

from app.workers.job_lifecycle import (
    admit_worker,
    begin_dispatch,
    begin_finalizing,
    claim_worker,
    clear_current_owner,
    fence_expired_dispatch_without_lifecycle,
    fence_job,
    lifecycle_key,
    mark_dispatch_accepted,
    renew_worker_lease,
    request_cancel,
    set_current_owner,
    stop_lease_heartbeat,
)


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


def test_live_worker_lease_blocks_cleanup_refund_fence(queue_redis):
    job_id = f"lifecycle-live-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        assert not fence_job(queue_redis, job_id, "timeout")
        assert not claim_worker(queue_redis, job_id, "worker-b")
    finally:
        queue_redis.delete(key)


def test_expired_lease_fences_and_rejects_late_delivery(queue_redis):
    job_id = f"lifecycle-expired-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        queue_redis.hset(key, "lease_until", time.time() - 1)
        assert fence_job(queue_redis, job_id, "timeout")
        assert not claim_worker(queue_redis, job_id, "worker-b")
    finally:
        queue_redis.delete(key)


def test_dispatch_acceptance_does_not_clobber_fast_worker_claim(queue_redis):
    job_id = f"lifecycle-fast-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert queue_redis.hget(key, "status") == b"running"
        assert queue_redis.hget(key, "owner") == b"worker-a"
    finally:
        queue_redis.delete(key)


def test_existing_lifecycle_requires_ownership_for_unmetered_worker(queue_redis):
    """Anonymous/unlimited jobs still use the dispatch/result fence."""
    job_id = f"lifecycle-unmetered-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert admit_worker(queue_redis, job_id, "worker-unmetered", None)
        assert queue_redis.hget(key, "owner") == b"worker-unmetered"
        stop_lease_heartbeat(job_id)
        clear_current_owner(job_id)
    finally:
        queue_redis.delete(key)


def test_legacy_unmetered_job_without_lifecycle_remains_compatible(queue_redis):
    job_id = f"legacy-unmetered-{uuid.uuid4()}"
    assert admit_worker(queue_redis, job_id, "worker-legacy", None)


def test_cancel_requested_worker_cannot_be_reclaimed_or_finalized(queue_redis):
    job_id = f"lifecycle-cancel-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        assert request_cancel(queue_redis, job_id)
        assert not claim_worker(queue_redis, job_id, "worker-b")
        queue_redis.hset(key, "lease_until", time.time() + 60)
        assert not begin_finalizing(queue_redis, job_id, "worker-a")
    finally:
        queue_redis.delete(key)


def test_expired_owner_cannot_renew_or_enter_finalizing(queue_redis):
    job_id = f"lifecycle-expired-lease-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        queue_redis.hset(key, "lease_until", time.time() - 1)
        assert not renew_worker_lease(queue_redis, job_id, "worker-a")
        assert not begin_finalizing(queue_redis, job_id, "worker-a")
    finally:
        queue_redis.delete(key)


def test_finalizing_owner_can_renew_until_result_commit(queue_redis):
    job_id = f"lifecycle-finalizing-renew-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        assert begin_finalizing(queue_redis, job_id, "worker-a")
        assert renew_worker_lease(queue_redis, job_id, "worker-a")
        assert queue_redis.hget(key, "status") == b"finalizing"
    finally:
        queue_redis.delete(key)


def test_expired_owner_cannot_publish_event_or_result(queue_redis):
    from app.workers.event_publisher import publish_event, publish_job_result

    job_id = f"lifecycle-expired-publish-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        set_current_owner(job_id, "worker-a")
        queue_redis.hset(key, "lease_until", time.time() - 1)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_event(job_id, "job.progress", {"percent": 50}) == ""
            assert not publish_job_result(job_id, {"success": True, "job_id": job_id})
        assert not queue_redis.exists(f"latexy:job:{job_id}:result")
        assert queue_redis.hget(key, "status") == b"running"
    finally:
        clear_current_owner(job_id)
        queue_redis.delete(key, f"latexy:job:{job_id}:result", f"latexy:job:{job_id}:seq", f"latexy:stream:{job_id}")


def test_ownerless_event_cannot_bypass_live_lifecycle(queue_redis):
    from app.workers.event_publisher import publish_event

    job_id = f"lifecycle-ownerless-event-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        # Simulate post-run/context cleanup happening before a stale helper
        # attempts another progress event.
        clear_current_owner(job_id)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_event(job_id, "job.progress", {"percent": 50}) == ""
        assert not queue_redis.exists(f"latexy:job:{job_id}:seq")
    finally:
        clear_current_owner(job_id)
        queue_redis.delete(key, f"latexy:job:{job_id}:seq", f"latexy:stream:{job_id}")


def test_result_then_terminal_event_is_atomic_and_late_failure_is_rejected(queue_redis):
    from app.workers.event_publisher import publish_event, publish_job_result

    job_id = f"lifecycle-result-event-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        set_current_owner(job_id, "worker-a")
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})
            assert publish_event(job_id, "job.completed", {"stage": "done"})
            assert publish_event(job_id, "job.failed", {"retryable": False}) == ""
            assert publish_event(job_id, "job.progress", {"percent": 100}) == ""
        assert queue_redis.hget(key, "status") == b"completed"
        assert queue_redis.exists(f"latexy:job:{job_id}:result")
    finally:
        clear_current_owner(job_id)
        queue_redis.delete(key, f"latexy:job:{job_id}:result", f"latexy:job:{job_id}:seq", f"latexy:stream:{job_id}")


def test_legacy_result_is_first_writer_wins(queue_redis):
    """Jobs predating lifecycle admission cannot race terminal result writers."""
    from app.workers.event_publisher import publish_job_result

    job_id = f"lifecycle-legacy-result-{uuid.uuid4()}"
    result_key = f"latexy:job:{job_id}:result"
    with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
        try:
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})
            assert not publish_job_result(job_id, {"success": False, "job_id": job_id})
            raw = queue_redis.get(result_key)
            assert raw and b'"success": true' in raw
        finally:
            queue_redis.delete(result_key)


def test_completion_aux_event_is_delivered_before_terminal_event(queue_redis):
    from app.workers.event_publisher import publish_event, publish_job_result

    job_id = f"lifecycle-completion-aux-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    stream = f"latexy:stream:{job_id}"
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        set_current_owner(job_id, "worker-a")
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})
            assert publish_event(job_id, "job.pdf_extracted", {"text": "safe text"})
            assert publish_event(job_id, "ats.deep_complete", {"overall_score": 88.0})
            assert publish_event(job_id, "job.completed", {"stage": "done"})
            assert publish_event(job_id, "job.pdf_extracted", {"text": "late"}) == ""
        payloads = [entry[b"payload"] for _, entry in queue_redis.xrange(stream)]
        assert any(b"safe text" in payload for payload in payloads)
        assert any(b"overall_score" in payload for payload in payloads)
    finally:
        clear_current_owner(job_id)
        queue_redis.delete(key, f"latexy:job:{job_id}:result", f"latexy:job:{job_id}:seq", stream, f"latexy:job:{job_id}:state")


def test_stale_failure_snapshot_cannot_refund_until_lifecycle_is_fenced(queue_redis, cache_redis):
    from app.workers.cleanup_worker import _reconcile_receipts_without_compilation_rows

    job_id = f"lifecycle-refund-race-{uuid.uuid4()}"
    lifecycle = lifecycle_key(job_id)
    receipt_key = f"latexy:quota-refund-pending:{job_id}"
    state_key = f"latexy:job:{job_id}:state"
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        queue_redis.hset(lifecycle, "lease_until", time.time() - 1)
        queue_redis.set(state_key, '{"status":"failed"}')
        cache_redis.set(
            receipt_key,
            '{"dimension":"optimizations","user_id":"user-1","period":"202610",'
            f'"created_at":{time.time() - 3600}}}',
        )
        with patch("app.workers.cleanup_worker._refund_pending_quota_receipt", return_value=True) as refund:
            assert _reconcile_receipts_without_compilation_rows(queue_redis, cache_redis) == 0
            refund.assert_not_called()
            assert fence_job(queue_redis, job_id, "timeout")
            assert _reconcile_receipts_without_compilation_rows(queue_redis, cache_redis) == 1
            refund.assert_called_once()
    finally:
        queue_redis.delete(lifecycle, state_key)
        cache_redis.delete(receipt_key)


def test_orphan_tombstone_wins_dispatch_race(queue_redis):
    from concurrent.futures import ThreadPoolExecutor

    from app.workers.job_lifecycle import fence_orphan_without_lifecycle

    job_id = f"lifecycle-orphan-race-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            tombstone = pool.submit(fence_orphan_without_lifecycle, queue_redis, job_id)
            dispatch = pool.submit(begin_dispatch, queue_redis, job_id)
        tombstone_won = tombstone.result()
        dispatch_won = dispatch.result()
        assert tombstone_won != dispatch_won
        if tombstone_won:
            assert queue_redis.hget(key, "status") == b"failed"
            assert not claim_worker(queue_redis, job_id, "late-worker")
        else:
            assert queue_redis.hget(key, "status") == b"dispatching"
    finally:
        queue_redis.delete(key)


def test_aged_dispatch_marker_without_lifecycle_gets_admission_tombstone(queue_redis):
    """A broker marker cannot leave a quota receipt refundable forever."""
    job_id = f"lifecycle-marker-orphan-{uuid.uuid4()}"
    key = lifecycle_key(job_id)
    marker = f"latexy:job:{job_id}:dispatch-started"
    try:
        queue_redis.set(marker, "1")
        assert fence_expired_dispatch_without_lifecycle(queue_redis, job_id)
        assert queue_redis.hget(key, "status") == b"failed"
        # A delayed broker delivery sees the tombstone and cannot claim work.
        assert not claim_worker(queue_redis, job_id, "late-worker")
        # The decision is idempotent and cannot be replaced by a second fence.
        assert not fence_expired_dispatch_without_lifecycle(queue_redis, job_id)
    finally:
        queue_redis.delete(key, marker)

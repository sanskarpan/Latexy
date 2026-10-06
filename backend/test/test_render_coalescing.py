"""Real Redis leader leases cannot cross cancellation or replacement fences."""
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.services.render_engine.coalescing import await_render_slot
from app.services.render_engine.passes import RenderPassError
from app.workers.event_publisher import get_worker_redis
from app.workers.job_lifecycle import clear_current_owner, lifecycle_key, set_current_capability


def test_real_redis_lease_release_cannot_delete_replacement():
    redis = get_worker_redis()
    key = "latexy:compile-cache:" + uuid4().hex + uuid4().hex
    lease = await_render_slot(redis, key, "leader", 10)
    redis.set(lease.key, "replacement", ex=30)
    lease.close()
    assert redis.get(lease.key) in {"replacement", b"replacement"}


def test_real_redis_waiter_coalesces_ready_artifact_without_ownership_transfer():
    redis = get_worker_redis()
    key = "latexy:compile-cache:" + uuid4().hex + uuid4().hex
    leader = await_render_slot(redis, key, "leader", 10)
    redis.hset(lifecycle_key("waiter"), mapping={"status": "running", "owner": "waiter-owner",
        "epoch": 1, "lease_until": time.time() + 60})
    def wait():
        set_current_capability("waiter", "waiter-owner", 1)
        try:
            return await_render_slot(redis, key, "waiter", 10)
        finally:
            clear_current_owner("waiter")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(wait)
        redis.set(key, '{"schema_version":1}', ex=60)
        assert future.result(timeout=2) is None
    assert redis.hget(lifecycle_key("waiter"), "owner") in {"waiter-owner", b"waiter-owner"}
    leader.close()


def test_real_redis_waiter_cancellation_fails_closed():
    redis = get_worker_redis()
    key = "latexy:compile-cache:" + uuid4().hex + uuid4().hex
    leader = await_render_slot(redis, key, "leader", 10)
    redis.hset(lifecycle_key("cancelled"), mapping={"status": "running", "owner": "waiter-owner",
        "epoch": 1, "lease_until": time.time() + 60, "cancel_requested": 1})
    set_current_capability("cancelled", "waiter-owner", 1)
    try:
        with pytest.raises(RenderPassError, match="ownership"):
            await_render_slot(redis, key, "cancelled", 10)
    finally:
        clear_current_owner("cancelled")
        leader.close()

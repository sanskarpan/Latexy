"""One-round-trip initialization, plus the real Redis replay/access contract."""

import asyncio
import json
import os
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.services.job_admission_state import initialize_job_state


async def initialize(redis, job_id, owner="owner"):
    await initialize_job_state(redis, job_id=job_id, job_type="combined", user_id=owner,
                               estimated_seconds=25, ttl=3600)


async def test_initialization_uses_one_async_redis_operation():
    redis = AsyncMock()
    await initialize(redis, "job")
    redis.eval.assert_awaited_once()
    for operation in (redis.set, redis.incr, redis.xadd, redis.expire, redis.publish, redis.zadd):
        operation.assert_not_awaited()
    args = redis.eval.call_args.args
    assert args[1] == 9
    assert json.loads(args[12])["user_id"] == "owner"


async def test_anonymous_metadata_contains_explicit_null_owner():
    redis = AsyncMock()
    await initialize(redis, "job", None)
    args = redis.eval.call_args.args
    assert json.loads(args[12]) == {"job_id": "job", "job_type": "combined", "user_id": None}
    assert json.loads(args[13])["user_id"] is None
    assert args[-1] == "0"


@pytest_asyncio.fixture
async def actual_redis():
    # A dedicated URL is required so this test never silently selects a
    # developer/production Redis endpoint or flushes an unrelated database.
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TEST_REDIS_URL to an isolated Redis test database")
    redis = aioredis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    await redis.ping()
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest.mark.parametrize("owner", [None, "owner"])
async def test_real_redis_state_metadata_ttls_index_and_replay_message(actual_redis, owner):
    redis = actual_redis
    job_id = f"test_admission_{uuid4()}"
    prefix = f"latexy:job:{job_id}"
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"latexy:events:{job_id}")
    await pubsub.get_message(ignore_subscribe_messages=False, timeout=1)
    try:
        await initialize(redis, job_id, owner)
        entries = await redis.xrange(f"latexy:stream:{job_id}")
        assert len(entries) == 1
        stream_id, fields = entries[0]
        event = json.loads(fields["payload"])
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
        assert json.loads(message["data"]) == {"type": "event", "event": event, "stream_id": stream_id}
        assert event["sequence"] == 1
        assert event["user_id"] == owner
        assert fields["sequence"] == "1"
        assert fields["type"] == "job.queued"
        assert fields["event_id"] == event["event_id"]
        meta = json.loads(await redis.get(f"{prefix}:meta"))
        state = json.loads(await redis.get(f"{prefix}:state"))
        assert meta["job_id"] == job_id and meta["user_id"] == owner
        assert state["status"] == "queued" and state["percent"] == 0 and state["stage"] == ""
        assert meta["submitted_at"] == event["timestamp"] == state["last_updated"]
        for key in [f"{prefix}:state", f"{prefix}:meta", f"{prefix}:seq", f"latexy:stream:{job_id}"]:
            assert 3590 <= await redis.ttl(key) <= 3600
        if owner:
            # Redis's Lua cjson encoding rounds epoch seconds to 14 significant
            # digits; the sorted-set score keeps the full double precision.
            assert await redis.zscore(f"latexy:user:{owner}:jobs", job_id) == pytest.approx(event["timestamp"], abs=.001, rel=0)
            assert 3590 <= await redis.ttl(f"latexy:user:{owner}:jobs") <= 3600
        else:
            assert not await redis.exists(f"{prefix}:unindexed")
    finally:
        await pubsub.aclose()


async def test_repeated_and_concurrent_initialization_do_not_duplicate_events(actual_redis):
    job_id = f"test_admission_{uuid4()}"
    await asyncio.gather(*(initialize(actual_redis, job_id) for _ in range(20)))
    assert await actual_redis.xlen(f"latexy:stream:{job_id}") == 1
    assert await actual_redis.get(f"latexy:job:{job_id}:seq") == "1"


@pytest.mark.parametrize("suffix", ["state", "meta", "seq", "lifecycle", "result", "cancel"])
async def test_existing_admission_or_terminal_evidence_is_not_overwritten(actual_redis, suffix):
    job_id = f"test_admission_{uuid4()}"
    key = f"latexy:job:{job_id}:{suffix}"
    if suffix == "lifecycle":
        await actual_redis.hset(key, mapping={"status": "running", "owner": "other", "epoch": 4})
    else:
        await actual_redis.set(key, "existing terminal or private data")
    await actual_redis.expire(key, 30)
    before = await actual_redis.dump(key)
    await initialize(actual_redis, job_id, "another-owner")
    assert await actual_redis.dump(key) == before
    assert 1 <= await actual_redis.ttl(key) <= 30
    assert not await actual_redis.exists(f"latexy:stream:{job_id}")
    assert await actual_redis.zscore("latexy:user:another-owner:jobs", job_id) is None


async def test_wrong_user_index_type_fails_before_partial_initialization(actual_redis):
    owner = f"test_admission_owner_{uuid4()}"
    job_id = f"test_admission_{uuid4()}"
    await actual_redis.set(f"latexy:user:{owner}:jobs", "incorrect type")
    with pytest.raises(RedisError, match="index type"):
        await initialize(actual_redis, job_id, owner)
    assert not await actual_redis.exists(f"latexy:job:{job_id}:state", f"latexy:job:{job_id}:meta",
                                          f"latexy:job:{job_id}:seq", f"latexy:stream:{job_id}")

"""Red/green boundaries for durable canonical terminal result publication."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
import redis
from sqlalchemy import delete, select

from app.database.models import JobFinalization
from app.workers.event_publisher import publish_job_result
from app.workers.finalization_arbiter import bounded_result_payload
from app.workers.job_lifecycle import (
    begin_dispatch,
    claim_worker,
    clear_current_owner,
    lifecycle_key,
    mark_dispatch_accepted,
    set_current_capability,
)


def _expires() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


@pytest.fixture
def queue_redis():
    client = redis.from_url(os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15"))
    client.ping()
    yield client
    client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("matches_canonical", [True, False])
async def test_completed_db_winner_controls_redis_result_publication(
    db_session_factory, queue_redis, matches_canonical: bool
):
    """ALREADY_COMPLETED accepts only the exact bounded canonical payload."""

    job_id = f"test_terminal_canonical_{uuid4().hex}"
    canonical = bounded_result_payload(
        job_id,
        {"success": True, "job_id": job_id, "optimized_latex": r"\\section{canonical}"},
    )
    candidate = {
        "success": True,
        "job_id": job_id,
        "optimized_latex": canonical["optimized_latex"] if matches_canonical else r"\\section{losing}",
    }
    lifecycle = lifecycle_key(job_id)
    result_key = f"latexy:job:{job_id}:result"
    stream = f"latexy:stream:{job_id}"

    async with db_session_factory() as session:
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                job_type="llm_optimization",
                owner_token="worker-a",
                owner_epoch=1,
                state="completed",
                terminal_result="completed",
                result_payload=canonical,
                expires_at=_expires(),
            )
        )
        await session.commit()

    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        def publish_from_worker_thread() -> bool:
            set_current_capability(job_id, "worker-a", 1)
            try:
                with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
                    return publish_job_result(job_id, candidate)
            finally:
                clear_current_owner(job_id)

        published = await asyncio.to_thread(publish_from_worker_thread)

        assert published is matches_canonical
        if matches_canonical:
            assert queue_redis.get(result_key)
            assert queue_redis.hget(lifecycle, "terminal_result") == b"completed"
        else:
            # A losing candidate must not mutate Redis or consume the
            # lifecycle terminal capability, even though the DB row is already
            # completed and the arbiter returns ALREADY_COMPLETED.
            assert not queue_redis.exists(result_key)
            assert queue_redis.hget(lifecycle, "status") == b"running"
            assert queue_redis.hget(lifecycle, "terminal_result") is None

        async with db_session_factory() as session:
            row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
            assert row is not None
            assert row.state == "completed"
            assert row.result_payload == canonical
    finally:
        clear_current_owner(job_id)
        queue_redis.delete(lifecycle, result_key, f"latexy:job:{job_id}:seq", f"latexy:job:{job_id}:state", stream)
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
            await session.commit()

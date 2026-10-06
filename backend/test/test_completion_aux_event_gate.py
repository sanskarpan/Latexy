"""Redis regressions for terminal completion-auxiliary event fencing.

Final content (for example ``llm.complete``) is published after the durable
result reservation but before ``job.completed``.  These tests exercise the
same Redis Lua gate used by workers, rather than only checking a mocked
publisher call.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import redis

from app.workers.event_publisher import publish_event, publish_job_result
from app.workers.job_lifecycle import (
    begin_dispatch,
    claim_worker,
    clear_current_owner,
    lifecycle_key,
    mark_dispatch_accepted,
    set_current_capability,
)


@pytest.fixture
def queue_redis():
    client = redis.from_url(os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15"))
    client.ping()
    yield client
    client.close()


def _admit(queue_redis: redis.Redis, job_id: str) -> tuple[str, int]:
    assert begin_dispatch(queue_redis, job_id)
    assert mark_dispatch_accepted(queue_redis, job_id)
    assert claim_worker(queue_redis, job_id, "worker-a")
    epoch = int(queue_redis.hget(lifecycle_key(job_id), "epoch"))
    # Capture the immutable invocation capability.  The publisher must not
    # reread a changed lifecycle epoch for a late delivery.
    set_current_capability(job_id, "worker-a", epoch)
    return "worker-a", epoch


def _cleanup(queue_redis: redis.Redis, job_id: str) -> None:
    clear_current_owner(job_id)
    queue_redis.delete(
        lifecycle_key(job_id),
        f"latexy:job:{job_id}:result",
        f"latexy:job:{job_id}:seq",
        f"latexy:job:{job_id}:state",
        f"latexy:stream:{job_id}",
    )


def test_llm_completion_auxiliary_event_precedes_terminal_event(queue_redis):
    """A canonical result permits exactly its owner/epoch's final content."""

    job_id = f"completion-aux-order-{uuid.uuid4()}"
    stream = f"latexy:stream:{job_id}"
    try:
        _admit(queue_redis, job_id)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{Safe}"})
            assert publish_event(job_id, "job.completed", {"stage": "done"})
            # ``job.completed`` consumes the one-shot terminal capability;
            # replaying final content after it must not append a second copy.
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{replay}"}) == ""

        entries = queue_redis.xrange(stream)
        event_types = [entry[b"type"] for _, entry in entries]
        assert event_types == [b"llm.complete", b"job.completed"]
    finally:
        _cleanup(queue_redis, job_id)


@pytest.mark.parametrize(
    ("result", "terminal_event"),
    [
        ({"success": False, "job_id": "placeholder", "error": "failed"}, "job.failed"),
        ({"success": False, "job_id": "placeholder", "cancelled": True}, "job.cancelled"),
    ],
)
def test_completion_auxiliary_event_is_rejected_for_noncompleted_terminal(
    queue_redis, result, terminal_event
):
    """Failed/cancelled decisions never expose a stale successful payload."""

    job_id = f"completion-aux-noncompleted-{uuid.uuid4()}"
    result = {**result, "job_id": job_id}
    stream = f"latexy:stream:{job_id}"
    try:
        _admit(queue_redis, job_id)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, result)
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{stale}"}) == ""
            assert publish_event(job_id, terminal_event, {"stage": terminal_event})

        event_types = [entry[b"type"] for _, entry in queue_redis.xrange(stream)]
        assert event_types == [terminal_event.encode()]
    finally:
        _cleanup(queue_redis, job_id)


def test_completion_auxiliary_event_rejects_stale_epoch_and_lost_owner(queue_redis):
    """A same-owner retry cannot publish after epoch rollover or context loss."""

    job_id = f"completion-aux-stale-capability-{uuid.uuid4()}"
    try:
        _admit(queue_redis, job_id)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})

            lifecycle = lifecycle_key(job_id)
            queue_redis.hset(lifecycle, "epoch", "2")
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{old}"}) == ""

            # The terminal result still belongs to the original owner, but a
            # late callback with no owner token must fail closed as well.
            queue_redis.hset(lifecycle, "epoch", "1")
            clear_current_owner(job_id)
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{ownerless}"}) == ""
    finally:
        _cleanup(queue_redis, job_id)


def test_running_completion_auxiliary_event_remains_a_stage_event(queue_redis):
    """Orchestrator/LLM stage-complete events remain valid before finalization."""

    job_id = f"completion-aux-running-stage-{uuid.uuid4()}"
    stream = f"latexy:stream:{job_id}"
    try:
        _admit(queue_redis, job_id)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{stage}"})

            # The normal running/finalizing capability guard still fences a
            # stale epoch and a callback whose owner context was cleared.
            queue_redis.hset(lifecycle_key(job_id), "epoch", "2")
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{stale}"}) == ""
            queue_redis.hset(lifecycle_key(job_id), "epoch", "1")
            clear_current_owner(job_id)
            assert publish_event(job_id, "llm.complete", {"full_content": "\\section{ownerless}"}) == ""

        assert [entry[b"type"] for _, entry in queue_redis.xrange(stream)] == [b"llm.complete"]
    finally:
        _cleanup(queue_redis, job_id)


def test_terminal_event_rejects_same_owner_stale_epoch_after_aba_reclaim(queue_redis):
    """A reused worker token cannot consume a newer attempt's terminal cap."""

    job_id = f"completion-terminal-aba-{uuid.uuid4()}"
    stream = f"latexy:stream:{job_id}"
    try:
        assert begin_dispatch(queue_redis, job_id)
        assert mark_dispatch_accepted(queue_redis, job_id)
        assert claim_worker(queue_redis, job_id, "worker-a")
        set_current_capability(job_id, "worker-a", 1)
        queue_redis.hset(lifecycle_key(job_id), "lease_until", 1)

        # The same token is reclaimed for a distinct immutable epoch.
        assert claim_worker(queue_redis, job_id, "worker-a")
        assert int(queue_redis.hget(lifecycle_key(job_id), "epoch")) == 2
        set_current_capability(job_id, "worker-a", 2)
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            assert publish_job_result(job_id, {"success": True, "job_id": job_id})

            # A late callback from epoch 1 has the same owner token. It must
            # not be accepted merely because terminal_owner matches.
            set_current_capability(job_id, "worker-a", 1)
            assert publish_event(job_id, "job.completed", {"stage": "stale"}) == ""

        assert queue_redis.xrange(stream) == []
        assert queue_redis.hget(lifecycle_key(job_id), "terminal_result") == b"completed"
    finally:
        _cleanup(queue_redis, job_id)


def test_recovery_owned_terminal_completion_keeps_ownerless_exception(queue_redis):
    """DB recovery may publish its ownerless terminal event exactly once."""

    job_id = f"completion-terminal-recovery-{uuid.uuid4()}"
    lifecycle = lifecycle_key(job_id)
    stream = f"latexy:stream:{job_id}"
    try:
        queue_redis.hset(
            lifecycle,
            mapping={
                "status": "completed",
                "terminal_result": "completed",
                "terminal_owner": "recovery",
                "epoch": "7",
            },
        )
        with patch("app.workers.event_publisher.get_worker_redis", return_value=queue_redis):
            clear_current_owner(job_id)
            assert publish_event(job_id, "job.completed", {"stage": "recovered"})
            assert publish_event(job_id, "job.completed", {"stage": "duplicate"}) == ""

        assert [entry[b"type"] for _, entry in queue_redis.xrange(stream)] == [b"job.completed"]
    finally:
        _cleanup(queue_redis, job_id)

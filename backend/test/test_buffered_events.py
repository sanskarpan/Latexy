import threading
from unittest.mock import MagicMock

import pytest

from app.workers import event_publisher as ep
from app.workers.buffered_events import BufferedEventPublisher
from app.workers.job_lifecycle import (
    clear_current_owner,
    current_owner,
    current_owner_epoch,
    set_current_capability,
    set_current_owner,
)


def test_order_capability_and_close_barrier():
    delivered = []
    set_current_capability("job", "attempt-a", 3)
    try:
        def publish(job, kind, payload):
            delivered.append((payload["token"], current_owner(job), current_owner_epoch(job)))
        with BufferedEventPublisher("job", publisher=publish, max_events=2) as events:
            for i in range(40):
                events.publish("llm.token", {"token": str(i)})
            events.flush()
            assert len(delivered) == 40
        assert delivered == [(str(i), "attempt-a", 3) for i in range(40)]
        assert current_owner("job") == "attempt-a"
    finally:
        clear_current_owner("job")


def test_queue_bounds_do_not_lose_events_under_backpressure():
    started = threading.Event()
    release = threading.Event()
    done = threading.Event()
    output = []
    def publish(job, kind, payload):
        started.set()
        assert release.wait(2)
        output.append(payload["line"])
    events = BufferedEventPublisher("job", publisher=publish, max_events=1, max_bytes=64)
    events.publish("log.line", {"line": "first"})
    assert started.wait(2)
    events.publish("log.line", {"line": "second"})
    def producer():
        events.publish("log.line", {"line": "third"})
        done.set()
    thread = threading.Thread(target=producer)
    thread.start()
    assert not done.wait(.02)
    release.set()
    thread.join(2)
    events.close()
    assert done.is_set()
    assert output == ["first", "second", "third"]


def test_publication_errors_propagate_no_retry():
    calls = []
    def publish(*args):
        calls.append(args)
        raise OSError("redis unavailable")
    events = BufferedEventPublisher("job", publisher=publish)
    events.publish("llm.token", {"token": "x"})
    with pytest.raises(RuntimeError, match="publication failed"):
        events.close()
    assert len(calls) == 1


def test_lifecycle_and_oversized_events_rejected():
    with BufferedEventPublisher("job", publisher=lambda *args: None, max_bytes=16) as events:
        with pytest.raises(ValueError, match="Lifecycle"):
            events.publish("job.completed", {})
        with pytest.raises(ValueError, match="byte limit"):
            events.publish("log.line", {"line": "x" * 100})


def test_large_provider_delta_splits_without_changing_text():
    import json
    original = "Resume 😀 多言語 \\ \n" * 1000
    delivered = []
    def publish(job, kind, payload):
        assert len(json.dumps(payload).encode()) <= 128
        delivered.append(payload["token"])
    with BufferedEventPublisher("job", publisher=publish, max_bytes=128, max_events=3) as events:
        events.publish("llm.token", {"token": original})
    assert "".join(delivered) == original


def test_pipeline_uses_existing_fence_and_immutable_capability(monkeypatch):
    redis = MagicMock()
    pipeline = redis.pipeline.return_value.__enter__.return_value
    monkeypatch.setattr(ep, "_worker_redis", redis)
    set_current_capability("job", "attempt-a", 7)
    try:
        with BufferedEventPublisher("job", max_events=64) as events:
            for i in range(20):
                events.publish("llm.token", {"token": str(i)})
        import json
        assert pipeline.execute.call_count == 1
        assert pipeline.eval.call_count == 20
        for call in pipeline.eval.call_args_list:
            assert call.args[0] == ep._PUBLISH_EVENT_SCRIPT
            payload = json.loads(call.args[7])
            assert payload["_lifecycle_owner"] == "attempt-a"
            assert payload["_lifecycle_epoch"] == "7"
    finally:
        clear_current_owner("job")


def test_legacy_epoch_frozen_before_handoff(monkeypatch):
    redis = MagicMock()
    redis.hget.side_effect = [8, 9]
    pipeline = redis.pipeline.return_value.__enter__.return_value
    monkeypatch.setattr(ep, "_worker_redis", redis)
    set_current_owner("job", "legacy-attempt")
    try:
        with BufferedEventPublisher("job") as events:
            events.publish("llm.token", {"token": "one"})
            events.publish("llm.token", {"token": "two"})
        import json
        assert redis.hget.call_count == 1
        assert [json.loads(call.args[7])["_lifecycle_epoch"] for call in pipeline.eval.call_args_list] == ["8", "8"]
    finally:
        clear_current_owner("job")

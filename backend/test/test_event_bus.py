"""
EventBusManager unit tests.

Tests app/core/event_bus.py directly with mocked Redis and WebSocket objects.
No running Redis is required for these tests.

Coverage:
- Subscribe / disconnect connection lifecycle
- Listener task creation and deduplication
- Event replay from Redis Streams
- Multi-job isolation (events for job A never reach job B's subscriber)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from app.core.event_bus import EventBusManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws(connected: bool = True) -> MagicMock:
    """Return a mock WebSocket."""
    ws = MagicMock()
    ws.client_state = (
        WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
    )
    ws.send_text = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _make_pubsub(blocking: bool = False, stop_event: asyncio.Event | None = None):
    """
    Return a mock pubsub object whose listen() is an async generator.

    blocking=True: listen() blocks until stop_event is set (simulates a live subscription).
    blocking=False: listen() exits immediately (no messages delivered).
    """
    pubsub = AsyncMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    if blocking and stop_event is not None:
        async def _blocking_listen():
            await stop_event.wait()
            if False:  # pragma: no cover
                yield  # make this an async generator function

        pubsub.listen = _blocking_listen
    else:
        async def _empty_listen():
            return
            yield  # pragma: no cover  # makes this an async generator function

        pubsub.listen = _empty_listen

    return pubsub


def _make_redis(
    stream_entries: list | None = None,
    blocking: bool = False,
    stop_event: asyncio.Event | None = None,
) -> tuple:
    """Return (mock_redis, mock_pubsub)."""
    r = AsyncMock()
    r.xread = AsyncMock(return_value=stream_entries or [])

    pubsub = _make_pubsub(blocking=blocking, stop_event=stop_event)
    r.pubsub = MagicMock(return_value=pubsub)

    return r, pubsub


async def _cancel_task(task: asyncio.Task) -> None:
    """Cancel a task and wait for it to finish."""
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# Tests: init
# ---------------------------------------------------------------------------


class TestEventBusInit:
    @pytest.mark.asyncio
    async def test_init_stores_redis_client(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        assert bus._redis is redis

    @pytest.mark.asyncio
    async def test_initial_state_empty(self):
        bus = EventBusManager()
        assert bus._connections == {}
        assert bus._listeners == {}


# ---------------------------------------------------------------------------
# Tests: subscribe / disconnect lifecycle
# ---------------------------------------------------------------------------


class TestSubscribeDisconnect:
    @pytest.mark.asyncio
    async def test_subscribe_registers_websocket(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws = _make_ws()

        await bus.subscribe(job_id, ws)

        assert job_id in bus._connections
        assert ws in bus._connections[job_id]

        await _cancel_task(bus._listeners.get(job_id))

    @pytest.mark.asyncio
    async def test_subscribe_creates_listener_task(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws = _make_ws()

        await bus.subscribe(job_id, ws)

        assert job_id in bus._listeners
        task = bus._listeners[job_id]
        assert isinstance(task, asyncio.Task)

        await _cancel_task(task)

    @pytest.mark.asyncio
    async def test_subscribe_returns_zero_without_last_event_id(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws = _make_ws()

        replayed = await bus.subscribe(job_id, ws)

        assert replayed == 0
        redis.xread.assert_not_called()

        await _cancel_task(bus._listeners.get(job_id))

    @pytest.mark.asyncio
    async def test_subscribe_does_not_duplicate_listener(self):
        """Subscribing twice to the same job creates exactly one listener task."""
        stop = asyncio.Event()
        bus = EventBusManager()
        redis, _ = _make_redis(blocking=True, stop_event=stop)
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        await bus.subscribe(job_id, ws1)
        task1 = bus._listeners.get(job_id)

        await bus.subscribe(job_id, ws2)
        task2 = bus._listeners.get(job_id)

        # Same task object — not duplicated
        assert task1 is task2

        stop.set()
        await _cancel_task(task1)

    @pytest.mark.asyncio
    async def test_subscribe_multiple_websockets_registered(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        await bus.subscribe(job_id, ws1)
        await bus.subscribe(job_id, ws2)

        assert ws1 in bus._connections[job_id]
        assert ws2 in bus._connections[job_id]

        await _cancel_task(bus._listeners.get(job_id))

    @pytest.mark.asyncio
    async def test_disconnect_removes_websocket(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws = _make_ws()

        await bus.subscribe(job_id, ws)
        await bus.disconnect(job_id, ws)

        # Connection set deleted when empty
        assert job_id not in bus._connections

    @pytest.mark.asyncio
    async def test_disconnect_removes_listener_key(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws = _make_ws()

        await bus.subscribe(job_id, ws)
        task = bus._listeners.get(job_id)
        await bus.disconnect(job_id, ws)

        # Either listener key removed, or task was already done
        assert job_id not in bus._listeners or (task and task.done())

    @pytest.mark.asyncio
    async def test_disconnect_keeps_other_subscribers(self):
        """Disconnecting ws1 should leave ws2 still subscribed."""
        stop = asyncio.Event()
        bus = EventBusManager()
        redis, _ = _make_redis(blocking=True, stop_event=stop)
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        await bus.subscribe(job_id, ws1)
        await bus.subscribe(job_id, ws2)
        await bus.disconnect(job_id, ws1)

        assert job_id in bus._connections
        assert ws2 in bus._connections[job_id]
        assert ws1 not in bus._connections[job_id]

        stop.set()
        await _cancel_task(bus._listeners.get(job_id))

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_job_is_noop(self):
        """disconnect() on a job_id that has no connections should not raise."""
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        ws = _make_ws()

        # Should not raise
        await bus.disconnect("nonexistent_job_id", ws)

    @pytest.mark.asyncio
    async def test_disconnect_all_removes_all_jobs(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_ids = [str(uuid.uuid4()) for _ in range(3)]
        ws = _make_ws()

        for jid in job_ids:
            await bus.subscribe(jid, ws)

        await bus.disconnect_all(ws)

        for jid in job_ids:
            assert jid not in bus._connections

    @pytest.mark.asyncio
    async def test_disconnect_all_only_removes_given_websocket(self):
        """disconnect_all(ws1) should not remove ws2 subscriptions."""
        stop = asyncio.Event()
        bus = EventBusManager()
        redis, _ = _make_redis(blocking=True, stop_event=stop)
        await bus.init(redis)
        job_id = str(uuid.uuid4())
        ws1 = _make_ws()
        ws2 = _make_ws()

        await bus.subscribe(job_id, ws1)
        await bus.subscribe(job_id, ws2)

        await bus.disconnect_all(ws1)

        # ws2 still connected to job_id
        assert job_id in bus._connections
        assert ws2 in bus._connections[job_id]

        stop.set()
        await _cancel_task(bus._listeners.get(job_id))


# ---------------------------------------------------------------------------
# Tests: event replay
# ---------------------------------------------------------------------------


class TestEventReplay:
    @pytest.mark.asyncio
    async def test_replay_empty_stream_returns_zero(self):
        bus = EventBusManager()
        redis, _ = _make_redis(stream_entries=[])
        await bus.init(redis)
        ws = _make_ws()
        job_id = str(uuid.uuid4())

        count = await bus._replay_events(job_id, ws, "0-0")

        assert count == 0
        ws.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_replay_sends_stream_entries(self):
        job_id = str(uuid.uuid4())
        event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": 1234567890.0,
            "sequence": 1,
            "type": "job.started",
            "stage": "latex_compilation",
        }
        payload = json.dumps(event)

        stream_entries = [
            (
                f"latexy:stream:{job_id}",
                [("1-1", {"payload": payload, "type": "job.started", "sequence": "1"})],
            )
        ]

        redis, _ = _make_redis(stream_entries=stream_entries)
        bus = EventBusManager()
        await bus.init(redis)
        ws = _make_ws()

        count = await bus._replay_events(job_id, ws, "0-0")

        assert count == 1
        ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_replay_sends_correct_envelope(self):
        """Replayed events are wrapped in {type: 'event', event: {...}}."""
        job_id = str(uuid.uuid4())
        event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": 1234567890.0,
            "sequence": 2,
            "type": "job.progress",
            "percent": 50,
        }
        stream_entries = [
            (
                f"latexy:stream:{job_id}",
                [("2-0", {"payload": json.dumps(event)})],
            )
        ]

        redis, _ = _make_redis(stream_entries=stream_entries)
        bus = EventBusManager()
        await bus.init(redis)
        ws = _make_ws()

        await bus._replay_events(job_id, ws, "1-0")

        sent_text = ws.send_text.call_args[0][0]
        envelope = json.loads(sent_text)
        assert envelope["type"] == "event"
        assert envelope["event"]["type"] == "job.progress"
        assert envelope["event"]["percent"] == 50
        assert envelope["event"]["job_id"] == job_id

    @pytest.mark.asyncio
    async def test_replay_multiple_entries(self):
        job_id = str(uuid.uuid4())
        event_types = ["job.started", "job.progress", "llm.token", "job.completed"]
        messages = [
            (
                f"{i + 1}-0",
                {
                    "payload": json.dumps({
                        "event_id": str(uuid.uuid4()),
                        "job_id": job_id,
                        "timestamp": 1234567890.0 + i,
                        "sequence": i + 1,
                        "type": etype,
                    }),
                },
            )
            for i, etype in enumerate(event_types)
        ]
        stream_entries = [(f"latexy:stream:{job_id}", messages)]

        redis, _ = _make_redis(stream_entries=stream_entries)
        bus = EventBusManager()
        await bus.init(redis)
        ws = _make_ws()

        count = await bus._replay_events(job_id, ws, "0-0")

        assert count == len(event_types)
        assert ws.send_text.call_count == len(event_types)

    @pytest.mark.asyncio
    async def test_replay_uses_correct_stream_key_and_last_event_id(self):
        job_id = str(uuid.uuid4())
        redis, _ = _make_redis(stream_entries=[])
        bus = EventBusManager()
        await bus.init(redis)
        ws = _make_ws()

        last_id = "42-7"
        await bus._replay_events(job_id, ws, last_id)

        redis.xread.assert_called_once_with(
            {f"latexy:stream:{job_id}": last_id},
            count=500,
        )

    @pytest.mark.asyncio
    async def test_subscribe_with_last_event_id_triggers_replay(self):
        """subscribe() with last_event_id calls _replay_events and counts them."""
        job_id = str(uuid.uuid4())
        event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": 1234567890.0,
            "sequence": 1,
            "type": "job.queued",
        }
        stream_entries = [
            (f"latexy:stream:{job_id}", [("1-0", {"payload": json.dumps(event)})])
        ]

        redis, _ = _make_redis(stream_entries=stream_entries)
        bus = EventBusManager()
        await bus.init(redis)
        ws = _make_ws()

        replayed = await bus.subscribe(job_id, ws, last_event_id="0-0")

        assert replayed == 1
        ws.send_text.assert_called_once()

        await _cancel_task(bus._listeners.get(job_id))


# ---------------------------------------------------------------------------
# Tests: multi-job isolation
# ---------------------------------------------------------------------------


class TestMultiJobIsolation:
    @pytest.mark.asyncio
    async def test_different_jobs_have_independent_connection_sets(self):
        bus = EventBusManager()
        redis, _ = _make_redis()
        await bus.init(redis)
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())
        ws_a = _make_ws()
        ws_b = _make_ws()

        await bus.subscribe(job_a, ws_a)
        await bus.subscribe(job_b, ws_b)

        assert ws_a in bus._connections[job_a]
        assert ws_b not in bus._connections.get(job_a, set())
        assert ws_b in bus._connections[job_b]
        assert ws_a not in bus._connections.get(job_b, set())

        await _cancel_task(bus._listeners.get(job_a))
        await _cancel_task(bus._listeners.get(job_b))

    @pytest.mark.asyncio
    async def test_disconnect_job_a_does_not_affect_job_b(self):
        """Disconnecting a WS from job_a should leave its job_b subscription intact."""
        stop = asyncio.Event()
        bus = EventBusManager()
        redis, _ = _make_redis(blocking=True, stop_event=stop)
        await bus.init(redis)
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())
        ws = _make_ws()

        await bus.subscribe(job_a, ws)
        await bus.subscribe(job_b, ws)
        await bus.disconnect(job_a, ws)

        # job_b connection still alive
        assert job_b in bus._connections
        assert ws in bus._connections[job_b]
        # job_a connection gone
        assert job_a not in bus._connections

        stop.set()
        await _cancel_task(bus._listeners.get(job_b))

    @pytest.mark.asyncio
    async def test_different_jobs_have_independent_listener_tasks(self):
        stop = asyncio.Event()
        bus = EventBusManager()
        redis, _ = _make_redis(blocking=True, stop_event=stop)
        await bus.init(redis)
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())
        ws_a = _make_ws()
        ws_b = _make_ws()

        await bus.subscribe(job_a, ws_a)
        await bus.subscribe(job_b, ws_b)

        task_a = bus._listeners.get(job_a)
        task_b = bus._listeners.get(job_b)

        assert task_a is not None
        assert task_b is not None
        # Two separate listener tasks
        assert task_a is not task_b

        stop.set()
        await _cancel_task(task_a)
        await _cancel_task(task_b)

    @pytest.mark.asyncio
    async def test_replay_for_job_a_does_not_read_job_b_stream(self):
        """_replay_events for job_a only reads latexy:stream:{job_a}, not job_b."""
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())

        redis, _ = _make_redis(stream_entries=[])
        bus = EventBusManager()
        await bus.init(redis)
        ws_a = _make_ws()

        await bus._replay_events(job_a, ws_a, "0-0")

        # XREAD called with job_a's stream key only
        call_args = redis.xread.call_args[0][0]  # first positional arg (the dict)
        assert f"latexy:stream:{job_a}" in call_args
        assert f"latexy:stream:{job_b}" not in call_args

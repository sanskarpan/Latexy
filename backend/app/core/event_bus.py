"""
EventBusManager — Redis Pub/Sub → WebSocket bridge with Stream replay.

Design:
- One singleton per FastAPI OS process.
- Each job_id gets exactly ONE asyncio listener task that subscribes to
  the Redis Pub/Sub channel latexy:events:{job_id}.
- Multiple WebSocket clients can subscribe to the same job_id; the
  listener task fans out to all of them.
- On reconnect, the client sends last_event_id and replay_events()
  calls XREAD on latexy:stream:{job_id} to deliver missed events.
- The listener task auto-cancels when no more clients are subscribed
  to a job.

Concurrency: all state transitions are serialized with an asyncio lock.  The
lock is released before listener cancellation is awaited so a replacement
subscriber can start while an old Pub/Sub object finishes closing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

_STREAM_PREFIX = "latexy:stream:"
_PUBSUB_PREFIX = "latexy:events:"


class EventBusManager:
    """
    Per-FastAPI-process singleton.

    Call await event_bus.init(async_redis_client) once during lifespan
    startup before accepting WebSocket connections.
    """

    def __init__(self):
        self._redis = None
        self._lock = asyncio.Lock()
        # job_id → set of WebSocket instances
        self._connections: Dict[str, Set[WebSocket]] = {}
        # job_id → running asyncio.Task
        self._listeners: Dict[str, asyncio.Task] = {}

    # ---------------------------------------------------------------- #
    #  Initialisation                                                   #
    # ---------------------------------------------------------------- #

    async def init(self, redis_client: Any) -> None:
        """Store the async Redis client.  Called during lifespan startup."""
        async with self._lock:
            self._redis = redis_client
        logger.info("EventBusManager initialised")

    # ---------------------------------------------------------------- #
    #  Subscribe / disconnect                                           #
    # ---------------------------------------------------------------- #

    async def subscribe(
        self,
        job_id: str,
        websocket: WebSocket,
        last_event_id: Optional[str] = None,
    ) -> int:
        """
        Register a WebSocket for job_id.  Replays missed events if
        last_event_id is provided.  Starts a listener task if one isn't
        already running for this job.

        Returns the number of replayed events.

        EVENT-01 fix: pubsub.subscribe() is called BEFORE _replay_events so
        that any event published between the end of replay and the first
        listen() iteration is not lost.
        """
        listener_started: Optional[asyncio.Event] = None
        async with self._lock:
            if self._redis is None:
                raise RuntimeError("EventBusManager is not initialized")

            self._connections.setdefault(job_id, set()).add(websocket)

            listener = self._listeners.get(job_id)
            if listener is None or listener.done():
                # EVENT-01: subscribe to the Pub/Sub channel NOW, before replay,
                # so we do not miss events published during the replay window.
                channel = f"{_PUBSUB_PREFIX}{job_id}"
                pubsub = self._redis.pubsub()
                try:
                    await pubsub.subscribe(channel)
                except BaseException:
                    self._connections[job_id].discard(websocket)
                    if not self._connections[job_id]:
                        self._connections.pop(job_id, None)
                    try:
                        await pubsub.aclose()
                    except Exception as cleanup_exc:
                        logger.debug(
                            "[EventBus] failed subscription cleanup: %s",
                            cleanup_exc,
                        )
                    raise
                logger.debug(f"[EventBus] subscribed to {channel} (pre-replay)")

                listener_started = asyncio.Event()
                self._listeners[job_id] = asyncio.create_task(
                    self._pubsub_listener(job_id, pubsub, listener_started),
                    name=f"pubsub:{job_id}",
                )

        # Ensure the task owns its Pub/Sub cleanup before subscribe returns.
        # Immediate unsubscribe can otherwise cancel a never-started coroutine
        # and leak the already-subscribed Pub/Sub connection.
        if listener_started is not None:
            try:
                await listener_started.wait()
            except BaseException:
                # Cancellation may win the scheduling race before the new
                # listener has entered its try/finally.  Let it claim cleanup
                # ownership before stopping it.
                await listener_started.wait()
                await self.disconnect(job_id, websocket)
                raise

        replayed = 0
        if last_event_id:
            replayed = await self._replay_events(job_id, websocket, last_event_id)

        return replayed

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from job_id subscriptions."""
        task: Optional[asyncio.Task] = None
        async with self._lock:
            conns = self._connections.get(job_id)
            if conns:
                conns.discard(websocket)
                if not conns:
                    del self._connections[job_id]
                    task = self._listeners.pop(job_id, None)

        if task is not None:
            await self._stop_listener(task)

    async def disconnect_all(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from ALL job subscriptions (called on WS close)."""
        job_ids = list(self._connections.keys())
        for job_id in job_ids:
            await self.disconnect(job_id, websocket)

    async def shutdown(self) -> None:
        """Cancel and await every Pub/Sub listener owned by this process."""
        async with self._lock:
            tasks = list(self._listeners.values())
            self._listeners.clear()
            self._connections.clear()
            self._redis = None

        if tasks:
            await asyncio.gather(*(self._stop_listener(task) for task in tasks))

    @staticmethod
    async def _stop_listener(task: asyncio.Task) -> None:
        """Cancel a listener and wait until its Pub/Sub cleanup finishes."""
        if task is asyncio.current_task():
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # ---------------------------------------------------------------- #
    #  Internal: Pub/Sub listener task                                  #
    # ---------------------------------------------------------------- #

    async def _pubsub_listener(
        self,
        job_id: str,
        pubsub: Any,
        started: Optional[asyncio.Event] = None,
    ) -> None:
        """
        Fan out Pub/Sub messages for job_id to all registered WebSocket
        clients.  Accepts a pre-subscribed pubsub object so that the
        subscription is active before replay begins (EVENT-01).
        Auto-exits when no clients remain or on error.
        """
        channel = f"{_PUBSUB_PREFIX}{job_id}"
        listener_task = asyncio.current_task()
        if started is not None:
            started.set()
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data: str = message["data"]

                # Fan out to all WebSocket clients subscribed to this job
                conns = list(self._connections.get(job_id, []))
                if not conns:
                    break  # No one listening — exit the task

                dead: List[WebSocket] = []
                for ws in conns:
                    try:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.send_text(data)
                    except Exception as exc:
                        logger.debug(f"[EventBus] WS send failed: {exc}")
                        dead.append(ws)

                for ws in dead:
                    await self.disconnect(job_id, ws)
                if not self._connections.get(job_id):
                    break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[EventBus] listener error for {job_id}: {exc}")
        finally:
            # A replacement can be installed while this task awaits Redis
            # cleanup.  Only remove the registration if it is still ours.
            if self._listeners.get(job_id) is listener_task:
                self._listeners.pop(job_id, None)
            try:
                await pubsub.unsubscribe(channel)
            except Exception as exc:
                logger.debug(f"Error during pubsub unsubscribe: {exc}")
            finally:
                try:
                    await pubsub.aclose()
                except Exception as exc:
                    logger.debug(f"Error during pubsub close: {exc}")
            logger.debug(f"[EventBus] listener exited for {job_id}")

    # ---------------------------------------------------------------- #
    #  Internal: Stream replay                                          #
    # ---------------------------------------------------------------- #

    async def _replay_events(
        self,
        job_id: str,
        websocket: WebSocket,
        last_event_id: str,
    ) -> int:
        """
        XREAD from latexy:stream:{job_id} starting after last_event_id.
        Sends each replayed event to the WebSocket.  Returns count.

        Reads up to 500 entries in a single call — sufficient for any job's
        event history within the 24-hour stream TTL.
        """
        stream_key = f"{_STREAM_PREFIX}{job_id}"
        count = 0

        try:
            entries = await self._redis.xread(
                {stream_key: last_event_id},
                count=500,
            )
        except Exception as exc:
            logger.warning(f"[EventBus] replay XREAD failed for {job_id}: {exc}")
            return count

        if not entries:
            return count

        for _stream, messages in entries:
            for msg_id, fields in messages:
                payload = fields.get("payload")
                if not payload:
                    continue
                try:
                    # Wrap in the same envelope the live listener sends.
                    # Include stream_id (Redis Stream entry ID, format ms-seq)
                    # so the frontend can update its last_event_id for the next reconnect.
                    event = json.loads(payload)
                    envelope = json.dumps(
                        {"type": "event", "event": event, "stream_id": msg_id}
                    )
                    await websocket.send_text(envelope)
                    count += 1
                except Exception as exc:
                    logger.warning(f"[EventBus] replay send failed: {exc}")
                    return count

        return count


# Singleton — imported by ws_routes.py and main.py
event_bus = EventBusManager()

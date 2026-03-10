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

Thread-safety: All operations are called from asyncio tasks in the same
event loop.  No locks needed.
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
        # job_id → set of WebSocket instances
        self._connections: Dict[str, Set[WebSocket]] = {}
        # job_id → running asyncio.Task
        self._listeners: Dict[str, asyncio.Task] = {}

    # ---------------------------------------------------------------- #
    #  Initialisation                                                   #
    # ---------------------------------------------------------------- #

    async def init(self, redis_client: Any) -> None:
        """Store the async Redis client.  Called during lifespan startup."""
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
        """
        if job_id not in self._connections:
            self._connections[job_id] = set()
        self._connections[job_id].add(websocket)

        # Start listener BEFORE replay to avoid a race where two concurrent
        # subscribe() calls both see no listener and both create tasks.
        # Replay events arrive via send_text() directly and do not need the
        # Pub/Sub task; the task only handles live events after replay.
        if job_id not in self._listeners or self._listeners[job_id].done():
            task = asyncio.create_task(
                self._pubsub_listener(job_id),
                name=f"pubsub:{job_id}",
            )
            self._listeners[job_id] = task

        replayed = 0
        if last_event_id:
            replayed = await self._replay_events(job_id, websocket, last_event_id)

        return replayed

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from job_id subscriptions."""
        conns = self._connections.get(job_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[job_id]
                task = self._listeners.pop(job_id, None)
                if task and not task.done():
                    task.cancel()

    async def disconnect_all(self, websocket: WebSocket) -> None:
        """Remove a WebSocket from ALL job subscriptions (called on WS close)."""
        job_ids = list(self._connections.keys())
        for job_id in job_ids:
            await self.disconnect(job_id, websocket)

    # ---------------------------------------------------------------- #
    #  Internal: Pub/Sub listener task                                  #
    # ---------------------------------------------------------------- #

    async def _pubsub_listener(self, job_id: str) -> None:
        """
        Subscribe to latexy:events:{job_id} and fan out each message to
        all registered WebSocket clients.  Auto-exits when no clients
        remain or on error.
        """
        channel = f"{_PUBSUB_PREFIX}{job_id}"
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(channel)
            logger.debug(f"[EventBus] subscribed to {channel}")

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

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"[EventBus] listener error for {job_id}: {exc}")
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:
                logger.debug(f"Error during pubsub cleanup: {exc}")
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
        """
        stream_key = f"{_STREAM_PREFIX}{job_id}"
        try:
            entries = await self._redis.xread(
                {stream_key: last_event_id},
                count=500,
            )
        except Exception as exc:
            logger.warning(f"[EventBus] replay XREAD failed for {job_id}: {exc}")
            return 0

        if not entries:
            return 0

        count = 0
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
                    envelope = json.dumps({"type": "event", "event": event, "stream_id": msg_id})
                    await websocket.send_text(envelope)
                    count += 1
                except Exception as exc:
                    logger.warning(f"[EventBus] replay send failed: {exc}")
                    break

        return count


# Singleton — imported by ws_routes.py and main.py
event_bus = EventBusManager()

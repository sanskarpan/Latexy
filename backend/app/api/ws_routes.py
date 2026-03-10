"""
WebSocket endpoint /ws/jobs

Protocol (all messages are JSON):

Client → Server:
  {"type": "subscribe",   "job_id": "...", "last_event_id": "..."}
  {"type": "unsubscribe", "job_id": "..."}
  {"type": "cancel",      "job_id": "..."}
  {"type": "ping"}

Server → Client:
  {"type": "subscribed",  "job_id": "...", "replayed_count": N}
  {"type": "event",       "event": { ...typed event... }}
  {"type": "pong",        "server_time": 1234567890.0}
  {"type": "error",       "code": "...", "message": "..."}
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi.websockets import WebSocket, WebSocketDisconnect

from ..core.event_bus import event_bus
from ..core.logging import get_logger
from ..core.redis import get_redis_client

logger = get_logger(__name__)

ws_router = APIRouter()

_HEARTBEAT_INTERVAL = 30  # seconds

# Per-connection message rate limiting
_ws_message_counts: dict = {}  # {connection_id: [timestamp, ...]}


def _check_rate_limit(connection_id: str, max_per_second: int = 20) -> bool:
    """Return True if within rate limit, False if exceeded."""
    now = time.time()
    timestamps = _ws_message_counts.get(connection_id, [])
    # Keep only timestamps within the last second
    timestamps = [t for t in timestamps if now - t < 1.0]
    timestamps.append(now)
    _ws_message_counts[connection_id] = timestamps
    return len(timestamps) <= max_per_second


@ws_router.websocket("/ws/jobs")
async def jobs_websocket(websocket: WebSocket) -> None:
    """
    Single persistent WebSocket connection for all real-time job events.
    One client can subscribe to multiple jobs simultaneously.
    """
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    logger.info("WebSocket connection accepted")

    # Track which jobs this connection is subscribed to (for cleanup)
    subscribed_jobs: set[str] = set()

    # Background heartbeat task
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError as exc:
                # Malformed JSON — send error and keep connection open
                logger.warning(f"WS malformed JSON: {exc}")
                await _send_error(websocket, "invalid_json", "Message must be valid JSON")
                continue
            except Exception as exc:
                logger.warning(f"WS receive error: {exc}")
                break

            # Rate limit: max 20 messages/second per connection
            if not _check_rate_limit(connection_id):
                await _send_error(websocket, "rate_limited", "Too many messages")
                continue

            msg_type = data.get("type")

            if msg_type == "subscribe":
                job_id: Optional[str] = data.get("job_id")
                last_event_id: Optional[str] = data.get("last_event_id")

                if not job_id:
                    await _send_error(websocket, "invalid_request", "job_id is required")
                    continue

                replayed = await event_bus.subscribe(job_id, websocket, last_event_id)
                subscribed_jobs.add(job_id)

                await websocket.send_json({
                    "type": "subscribed",
                    "job_id": job_id,
                    "replayed_count": replayed,
                })
                logger.debug(f"WS subscribed to job {job_id} (replayed {replayed})")

            elif msg_type == "unsubscribe":
                job_id = data.get("job_id")
                if job_id:
                    await event_bus.disconnect(job_id, websocket)
                    subscribed_jobs.discard(job_id)

            elif msg_type == "cancel":
                job_id = data.get("job_id")
                if not job_id:
                    await _send_error(websocket, "invalid_request", "job_id is required")
                    continue
                await _request_cancellation(job_id)

            elif msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "server_time": time.time(),
                })

            else:
                await _send_error(
                    websocket,
                    "unknown_message_type",
                    f"Unknown type: {msg_type!r}",
                )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"WS handler error: {exc}")
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        _ws_message_counts.pop(connection_id, None)
        await event_bus.disconnect_all(websocket)
        logger.info("WebSocket connection closed")


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "code": code, "message": message})
    except Exception:
        pass


async def _heartbeat(websocket: WebSocket) -> None:
    """Send sys.heartbeat every HEARTBEAT_INTERVAL seconds."""
    try:
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            heartbeat_event = {
                "event_id": str(uuid.uuid4()),
                "job_id": "",
                "timestamp": time.time(),
                "sequence": 0,
                "type": "sys.heartbeat",
                "server_time": time.time(),
            }
            await websocket.send_json({"type": "event", "event": heartbeat_event})
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _request_cancellation(job_id: str) -> None:
    """
    Set the cancellation flag in Redis.  Workers poll is_cancelled()
    and will stop gracefully.  Also publish a provisional cancelled
    event so the client gets immediate feedback.
    """
    try:
        r = await get_redis_client()
        await r.setex(f"latexy:job:{job_id}:cancel", 3600, "1")

        # Publish provisional cancellation event to Pub/Sub channel
        cancel_event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": time.time(),
            "sequence": 0,
            "type": "job.cancelled",
        }
        await r.publish(
            f"latexy:events:{job_id}",
            json.dumps({"type": "event", "event": cancel_event}),
        )
        logger.info(f"Cancellation requested for job {job_id}")
    except Exception as exc:
        logger.error(f"Failed to set cancel flag for job {job_id}: {exc}")

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
  {"type": "error",       "code": "...", "message": "...", "job_id": "..."}
                          (job_id present only when the error concerns one job)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import uuid
from typing import Awaitable, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..core.event_bus import event_bus
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..middleware.auth_middleware import get_current_user_required
from ..services.collab_manager import (
    MAX_CHAT_FRAME_BYTES,
    _safe_chat_label,
    collab_manager,
    handle_collab_message,
    is_chat_frame,
    notify_if_read_only,
    reset_chat_rate_limit,
)
from .job_metadata import parse_ownership_metadata

logger = get_logger(__name__)

ws_router = APIRouter()

_HEARTBEAT_INTERVAL = 30  # seconds
_WS_TICKET_TTL_SECONDS = 60
_WS_TICKET_KEY_PREFIX = "latexy:ws_ticket:"
_MAX_JOB_WS_MESSAGE_BYTES = 64 * 1024

# Per-connection message rate limiting
_ws_message_counts: dict = {}  # {connection_id: [timestamp, ...]}


class WebSocketTicketRequest(BaseModel):
    purpose: Literal["jobs", "collab"]
    resume_id: Optional[str] = None


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int


class _WebSocketMessageTooLarge(ValueError):
    """Raised before JSON parsing when a jobs frame exceeds its bound."""


def _decode_job_ws_message(message: dict) -> dict:
    """Decode one bounded text/binary ASGI WebSocket message.

    ``WebSocket.receive_json`` parses the complete client frame before the
    handler can apply a rate limit.  Decode the ASGI frame ourselves so an
    unauthenticated client cannot force an arbitrarily large JSON allocation.
    """
    if message.get("type") != "websocket.receive":
        raise ValueError("not a WebSocket data message")
    raw_text = message.get("text")
    raw_bytes = message.get("bytes")
    if raw_text is not None:
        try:
            encoded = raw_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("invalid UTF-8") from exc
    elif raw_bytes is not None:
        encoded = bytes(raw_bytes)
    else:
        raise ValueError("empty WebSocket data message")
    if len(encoded) > _MAX_JOB_WS_MESSAGE_BYTES:
        raise _WebSocketMessageTooLarge
    try:
        data = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON message must be an object")
    return data


def _ws_ticket_key(ticket: str) -> str:
    # Redis snapshots/logging should not contain the bearer ticket itself. The
    # random value only travels to the browser; Redis indexes its SHA-256 digest.
    digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    return f"{_WS_TICKET_KEY_PREFIX}{digest}"


@ws_router.post("/ws/ticket", response_model=WebSocketTicketResponse)
async def create_websocket_ticket(
    body: WebSocketTicketRequest,
    user_id: str = Depends(get_current_user_required),
) -> WebSocketTicketResponse:
    """Mint a short-lived, single-use ticket for one WebSocket purpose.

    Browsers cannot attach an Authorization header to a WebSocket handshake.
    Exchanging the normal session over authenticated HTTP prevents the reusable
    seven-day Better Auth token from appearing in WebSocket URLs and access logs.
    """
    if body.purpose == "collab" and not body.resume_id:
        raise HTTPException(status_code=400, detail="resume_id is required for collaboration tickets")
    if body.purpose == "jobs" and body.resume_id is not None:
        raise HTTPException(status_code=400, detail="resume_id is only valid for collaboration tickets")

    ticket = secrets.token_urlsafe(32)
    envelope = json.dumps({
        "user_id": user_id,
        "purpose": body.purpose,
        "resume_id": body.resume_id,
        "expires_at": time.time() + _WS_TICKET_TTL_SECONDS,
    })
    redis = await get_redis_client()
    stored = await redis.set(
        _ws_ticket_key(ticket),
        envelope,
        ex=_WS_TICKET_TTL_SECONDS,
        nx=True,
    )
    if not stored:  # cryptographically improbable collision; fail closed.
        raise HTTPException(status_code=503, detail="Could not create WebSocket ticket")
    return WebSocketTicketResponse(ticket=ticket, expires_in=_WS_TICKET_TTL_SECONDS)


def _check_rate_limit(connection_id: str, max_per_second: int = 20) -> bool:
    """Return True if within rate limit, False if exceeded."""
    now = time.time()
    timestamps = _ws_message_counts.get(connection_id, [])
    # Keep only timestamps within the last second
    timestamps = [t for t in timestamps if now - t < 1.0]
    if len(timestamps) >= max_per_second:
        # Do not append rejected frames: a flood must not turn this per-socket
        # guard into an unbounded allocation before the timestamps expire.
        _ws_message_counts[connection_id] = timestamps
        return False
    timestamps.append(now)
    _ws_message_counts[connection_id] = timestamps
    return True


@ws_router.websocket("/ws/jobs")
async def jobs_websocket(websocket: WebSocket) -> None:
    """
    Single persistent WebSocket connection for all real-time job events.
    One client can subscribe to multiple jobs simultaneously.
    """
    # Authenticated clients exchange their reusable session credential over HTTP
    # for a one-time ?ticket=. Anonymous trial sockets omit it entirely.
    ticket_present = bool(websocket.query_params.get("ticket"))
    ws_user_id = await _consume_ws_ticket(websocket, purpose="jobs")
    if ticket_present and ws_user_id is None:
        # Reject a presented-but-invalid credential before completing the
        # WebSocket upgrade. Anonymous sockets are still supported when no
        # ticket is supplied for owner-less trial jobs.
        await websocket.close(code=4001, reason="Invalid or expired WebSocket ticket")
        return

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
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                # Count every received frame, including malformed and
                # oversized frames, so the size guard cannot be used to
                # bypass the per-connection rate limit.
                if not _check_rate_limit(connection_id):
                    await _send_error(websocket, "rate_limited", "Too many messages")
                    continue
                data = _decode_job_ws_message(message)
            except WebSocketDisconnect:
                break
            except _WebSocketMessageTooLarge:
                await _send_error(websocket, "message_too_large", "Message exceeds the 64 KiB limit")
                continue
            except ValueError as exc:
                # Malformed JSON — send error and keep connection open
                logger.warning("WS malformed JSON: %s", type(exc).__name__)
                await _send_error(websocket, "invalid_json", "Message must be valid JSON")
                continue
            except Exception as exc:
                logger.warning("WS receive error", extra={"error_type": type(exc).__name__})
                break

            msg_type = data.get("type")

            if msg_type == "subscribe":
                job_id: Optional[str] = data.get("job_id")
                last_event_id: Optional[str] = data.get("last_event_id")

                if not job_id:
                    await _send_error(websocket, "invalid_request", "job_id is required")
                    continue

                if not await _job_ws_access_ok(job_id, ws_user_id):
                    await _send_error(
                        websocket, "forbidden", "Access denied for this job", job_id=job_id
                    )
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
                if not await _job_ws_access_ok(job_id, ws_user_id):
                    await _send_error(
                        websocket, "forbidden", "Access denied for this job", job_id=job_id
                    )
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
        logger.error("WS handler error", extra={"error_type": type(exc).__name__})
    finally:
        await _stop_background_task(heartbeat_task, "jobs heartbeat")
        _ws_message_counts.pop(connection_id, None)
        await event_bus.disconnect_all(websocket)
        logger.info("WebSocket connection closed")


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

async def _consume_ws_ticket(
    websocket: WebSocket,
    *,
    purpose: Literal["jobs", "collab"],
    resume_id: Optional[str] = None,
) -> Optional[str]:
    """Atomically consume a purpose-bound WebSocket ticket.

    ``GETDEL`` makes tickets single-use even when two handshakes race. Any Redis
    failure, malformed envelope, expiry, or scope mismatch fails closed.
    """
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        return None
    try:
        redis = await get_redis_client()
        raw = await redis.getdel(_ws_ticket_key(ticket))
        if not raw:
            return None
        envelope = json.loads(raw)
        if envelope.get("purpose") != purpose:
            return None
        if float(envelope.get("expires_at") or 0) <= time.time():
            return None
        if purpose == "collab" and envelope.get("resume_id") != resume_id:
            return None
        user_id = envelope.get("user_id")
        return str(user_id) if user_id else None
    except Exception as exc:  # pragma: no cover - transient/malformed
        logger.debug("WS ticket validation failed", extra={"error_type": type(exc).__name__})
        return None


async def _job_ws_access_ok(job_id: str, user_id: Optional[str]) -> bool:
    """Return True if this connection may read/cancel the job.

    Owned jobs (meta.user_id set) require the matching authenticated user; owner-less
    (anonymous/trial) jobs are accessible to anyone. Every submitted job receives
    metadata, so missing, unreadable, or malformed metadata cannot prove access.
    """
    try:
        r = await get_redis_client()
        meta_raw = await r.get(f"latexy:job:{job_id}:meta")
        if not meta_raw:
            return False
        job_owner = parse_ownership_metadata(meta_raw, job_id)["user_id"]
        return job_owner is None or job_owner == user_id
    except Exception as exc:  # pragma: no cover - transient/malformed
        logger.debug(
            "WS ownership lookup failed for job %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )
        return False


async def _send_error(
    websocket: WebSocket,
    code: str,
    message: str,
    job_id: Optional[str] = None,
) -> None:
    """Send an error frame.

    ``job_id`` is included whenever the rejection is about a specific job so a
    client with several concurrent job subscriptions on the one socket can route
    the error to the right stream instead of failing all of them.
    """
    payload: dict = {"type": "error", "code": code, "message": message}
    if job_id:
        payload["job_id"] = job_id
    try:
        await websocket.send_json(payload)
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


async def _stop_background_task(task: asyncio.Task, owner: str) -> None:
    """Cancel one request-owned task and await its terminal cleanup."""
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("%s stopped with an error", owner, extra={"error_type": type(exc).__name__})


async def _close_expected_collab_rejection(
    websocket: WebSocket,
    code: int,
    reason: str,
) -> None:
    """Accept then close expected auth/permission failures to avoid noisy 4xx handshakes."""
    try:
        await websocket.accept()
    except Exception:
        pass
    await websocket.close(code=code, reason=reason)


# y-websocket clients send nothing while their user is idle, so a solo editor
# generates no traffic at all and the proxy force-closes the socket at its idle
# timeout (~30s), producing a reconnect-per-30s churn for the commonest case: one
# person editing alone. The jobs socket already has _heartbeat for this; the
# collab socket had none.
#
# MSG_QUERY_AWARENESS is the right frame to send: it is part of the stock
# y-protocol, so every client already handles it, and the reply is bounded (each
# peer re-broadcasts its own awareness) rather than a document resync.
_COLLAB_HEARTBEAT_INTERVAL = 15


async def _collab_heartbeat(websocket: WebSocket) -> None:
    """Keep the collab socket alive through idle-timeout proxies."""
    from ..services.collab_manager import MSG_QUERY_AWARENESS, _encode_varuint

    frame = _encode_varuint(MSG_QUERY_AWARENESS)
    try:
        while True:
            await asyncio.sleep(_COLLAB_HEARTBEAT_INTERVAL)
            await websocket.send_bytes(frame)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("Collab: heartbeat stopped", extra={"error_type": type(exc).__name__})


async def _collab_chat_access_ok(resume_id: str, user_id: str) -> bool:
    """Re-check live resume access immediately before chat fan-out.

    Collaboration sockets intentionally remain open across collaborator
    changes. Chat therefore must not rely only on the role captured at join;
    this check fails closed on a database error and logs only exception type.
    """
    from sqlalchemy import select as sa_select

    from ..database.connection import get_async_db_session
    from ..database.models import Resume, ResumeCollaborator

    try:
        async with get_async_db_session() as db:
            result = await db.execute(sa_select(Resume).where(Resume.id == resume_id))
            resume = result.scalar_one_or_none()
            if resume is None or resume.user_id == user_id:
                return resume is not None
            result = await db.execute(
                sa_select(ResumeCollaborator).where(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == user_id,
                )
            )
            return result.scalar_one_or_none() is not None
    except Exception as exc:
        logger.debug("Collab chat authorization check failed: %s", type(exc).__name__)
        return False


def _collab_chat_access_callback(
    resume_id: str, user_id: str
) -> Callable[[], Awaitable[bool]]:
    """Create a deferred ACL check for the post-parse, post-limit chat path."""
    async def check() -> bool:
        return await _collab_chat_access_ok(resume_id, user_id)

    return check


@ws_router.websocket("/ws/collab/{resume_id}")
async def collab_websocket(websocket: WebSocket, resume_id: str) -> None:
    """
    Y.js CRDT collaboration WebSocket for a specific resume.

    Auth:       ?ticket=<short-lived single-use collaboration ticket>
    Permission: resume owner OR a row in resume_collaborators for this user.
                The collaborator's role travels with the connection and is
                enforced on every frame by collab_manager (viewers and
                commenters cannot mutate the document).

    Binary protocol: lib0-encoded Y.js messages (MSG_SYNC / MSG_AWARENESS),
    plus a bounded plain-text MSG_CHAT extension with no server-side history.
    See collab_manager.py for the full protocol description.
    """
    from sqlalchemy import select as sa_select

    from ..database.connection import get_async_db_session
    from ..database.models import Resume, ResumeCollaborator, User

    try:
        uuid.UUID(resume_id)
    except (TypeError, ValueError, AttributeError):
        # Resume ids are PostgreSQL UUIDs. Reject malformed path values before
        # consuming a one-time ticket or allowing asyncpg to turn the bad bind
        # parameter into an internal server error.
        await _close_expected_collab_rejection(
            websocket,
            code=4004,
            reason="Resume not found",
        )
        return

    # Sanitise display fields
    user_name = (websocket.query_params.get("name") or "Anonymous")[:60]
    user_color = (websocket.query_params.get("color") or "#7c3aed")[:20]

    # ── Auth ──────────────────────────────────────────────────────────────
    user_id = await _consume_ws_ticket(
        websocket,
        purpose="collab",
        resume_id=resume_id,
    )

    if not user_id:
        await _close_expected_collab_rejection(
            websocket,
            code=4001,
            reason="Unauthorized",
        )
        return

    # ── Permission ────────────────────────────────────────────────────────
    is_owner = False
    role = "owner"
    async with get_async_db_session() as db:
        result = await db.execute(sa_select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one_or_none()

        if resume is None:
            await _close_expected_collab_rejection(
                websocket,
                code=4004,
                reason="Resume not found",
            )
            return

        is_owner = resume.user_id == user_id

        if not is_owner:
            collab_result = await db.execute(
                sa_select(ResumeCollaborator).where(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == user_id,
                )
            )
            collab = collab_result.scalar_one_or_none()
            if collab is None:
                await _close_expected_collab_rejection(
                    websocket,
                    code=4003,
                    reason="Forbidden",
                )
                return
            role = collab.role

        # The query-string `name` is only legacy cursor metadata and is
        # client-controlled. Chat labels must come from the authenticated
        # account row, never from an email, raw id, or websocket parameter.
        name_result = await db.execute(sa_select(User.name).where(User.id == user_id))
        authenticated_name = name_result.scalar_one_or_none()

    # ── Accept and join room ──────────────────────────────────────────────
    await websocket.accept()
    client_id = str(uuid.uuid4())
    user_info = {
        "client_id": client_id,
        "user_id": user_id,
        "name": user_name,
        "chat_label": _safe_chat_label(authenticated_name),
        "color": user_color,
        "is_owner": is_owner,
        "role": role,
    }

    room = await collab_manager.get_or_create(resume_id)
    await room.add(client_id, websocket, user_info)
    # Read-only roles are told up-front so the client can disable its editor
    # instead of discovering the restriction only after edits are dropped.
    await notify_if_read_only(room, client_id)
    logger.info(
        "Collab: %s joined %s as %s (room=%d)",
        user_name,
        resume_id[:8],
        role,
        room.size,
    )

    heartbeat_task = asyncio.create_task(_collab_heartbeat(websocket))

    try:
        while True:
            try:
                data = await websocket.receive_bytes()
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.debug(
                    "Collab: receive error %s",
                    client_id[:8],
                    extra={"error_type": type(exc).__name__},
                )
                break

            chat_access_check = None
            if is_chat_frame(data) and len(data) <= MAX_CHAT_FRAME_BYTES:
                chat_access_check = _collab_chat_access_callback(resume_id, user_id)
            await handle_collab_message(
                resume_id,
                client_id,
                data,
                room,
                chat_access_check=chat_access_check,
                chat_user_id=user_id,
                chat_sender_label=user_info["chat_label"],
            )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Collab: handler error", extra={"error_type": type(exc).__name__})
    finally:
        await _stop_background_task(heartbeat_task, "collaboration heartbeat")
        reset_chat_rate_limit(client_id)
        await room.remove(client_id)
        await collab_manager.maybe_cleanup(resume_id)
        logger.info(
            "Collab: %s left %s (room=%d)",
            user_name,
            resume_id[:8],
            room.size,
        )


async def _request_cancellation(job_id: str) -> None:
    """
    Set the cancellation flag in Redis.  Workers poll is_cancelled()
    and will stop gracefully.  Also publish a provisional cancelled
    event so the client gets immediate feedback.

    Mirrors the REST cancel_job path: the event is assigned a monotonic
    sequence and written to the Redis Stream (for replay on reconnect)
    in addition to being published to the live Pub/Sub channel.
    """
    _JOB_TTL = 86400
    try:
        r = await get_redis_client()
        # The DB arbiter is the cancellation linearization point.  Redis is
        # updated only after this commit so a worker cannot publish a success
        # after cancellation and still be considered refundable.
        from ..database.connection import get_async_db_session
        from ..workers.finalization_arbiter import FinalizationOutcome
        from ..workers.finalization_arbiter import request_cancel as request_cancel_finalization
        from ..workers.job_lifecycle import request_cancel_async

        async with get_async_db_session() as session:
            db_cancel = await request_cancel_finalization(session, job_id=job_id)
            await session.commit()
        if db_cancel in {
            FinalizationOutcome.ALREADY_COMPLETED,
            FinalizationOutcome.FAILED,
            FinalizationOutcome.FENCED,
        }:
            return
        await r.set(f"latexy:job:{job_id}:cancel", "1", ex=3600)
        await request_cancel_async(r, job_id)
        cancel_result = {"success": False, "job_id": job_id, "cancelled": True}
        await r.set(
            f"latexy:job:{job_id}:state",
            json.dumps({"status": "cancelled", "stage": "cancelled", "percent": 100, "last_updated": time.time()}),
            ex=_JOB_TTL,
        )
        await r.set(f"latexy:job:{job_id}:result", json.dumps(cancel_result), ex=_JOB_TTL)

        event_id = str(uuid.uuid4())
        seq_key = f"latexy:job:{job_id}:seq"
        seq = await r.incr(seq_key)
        await r.expire(seq_key, _JOB_TTL)

        cancel_event = {
            "event_id": event_id,
            "job_id": job_id,
            "timestamp": time.time(),
            "sequence": seq,
            "type": "job.cancelled",
        }
        payload_json = json.dumps(cancel_event)

        stream_key = f"latexy:stream:{job_id}"
        entry_id = await r.xadd(
            stream_key,
            {
                "payload": payload_json,
                "type": "job.cancelled",
                "sequence": str(seq),
                "event_id": event_id,
            },
            maxlen=10000,
            approximate=True,
        )
        await r.expire(stream_key, _JOB_TTL)

        await r.publish(
            f"latexy:events:{job_id}",
            json.dumps({"type": "event", "event": cancel_event, "stream_id": entry_id}),
        )
        logger.info(f"Cancellation requested for job {job_id}")
    except Exception as exc:
        logger.error(
            "Failed to set cancel flag for job %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )

"""
Collaboration manager for Feature 40 — Real-Time Collaboration (Multi-Cursor CRDT).

Implements a Y.js WebSocket relay server in Python.  The server does NOT
interpret Y.js CRDT semantics — it merely:

  1. Relays binary Y.js messages between all clients in the same room.
  2. Persists raw update bytes in Redis so late-joining clients can catch up.

Y.js / lib0 binary protocol summary
─────────────────────────────────────
  MSG_SYNC (0):
    SYNC_STEP1 (0) + varBuffer(stateVector)  → client requests server state
    SYNC_STEP2 (1) + varBuffer(updateBytes)  → server responds with full state
    MSG_UPDATE  (2) + varBuffer(updateBytes) → incremental document update
  MSG_AWARENESS (1) + varBuffer(awarenessUpdate) → cursor / presence info
  MSG_QUERY_AWARENESS (3) → ask peers to re-broadcast their awareness

All integers use lib0 variable-length unsigned encoding (see helpers below).

Multi-process fan-out
─────────────────────
The API runs several uvicorn workers in production, so two peers editing the
same resume usually land in different processes.  Every frame a room relays is
therefore also published to the Redis Pub/Sub channel ``latexy:collab:{id}``;
each process runs one listener task per live room and re-broadcasts frames that
originated elsewhere.  The same channel carries access-revocation control
messages so that removing a collaborator terminates their live sockets on
whichever worker they happen to be connected to.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi.websockets import WebSocket

from ..core.logging import get_logger
from ..core.redis import get_redis_client

logger = get_logger(__name__)

# ── lib0 message type constants ───────────────────────────────────────────────
MSG_SYNC = 0
MSG_AWARENESS = 1
MSG_QUERY_AWARENESS = 3
# Protocol extension outside the y-protocol range. Existing Yjs clients ignore
# this frame until they opt into chat support.
MSG_CHAT = 62

SYNC_STEP1 = 0
SYNC_STEP2 = 1
MSG_UPDATE = 2

# Latexy protocol extension, deliberately outside the y-protocol range: the
# server uses it to tell a client that one of its frames was refused.  Stock
# y-websocket clients ignore unknown message types, so it is safe to send.
MSG_PERMISSION_DENIED = 63

# Collaborator roles allowed to mutate the shared Y.Doc.  "commenter" and
# "viewer" are read-only on the document — comments are written through the
# REST comment API (comment_routes.py), never through the CRDT stream.
EDIT_ROLES = frozenset({"owner", "editor"})

# Redis TTL for collaboration document state (24 h)
_COLLAB_TTL = 86_400

# Pub/Sub channel prefix used to bridge rooms across API worker processes.
_COLLAB_CHANNEL_PREFIX = "latexy:collab:"

# Identifies this OS process so it can ignore the frames it published itself.
_PROCESS_ID = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"

# WebSocket close code sent to a collaborator whose access was revoked.
CLOSE_ACCESS_REVOKED = 4003

# A role change is NOT a revocation: the socket has to drop so the client
# re-handshakes and picks up the new role, but the client must reconnect rather
# than lock its buffer read-only. Sharing 4003 meant promoting someone
# viewer->editor left them with LESS access than before — the frontend saw
# "access revoked" and locked the editor.
CLOSE_ROLE_CHANGED = 4005

# Maximum accepted size of a single collaboration frame (256 KiB). Oversized
# frames are dropped to bound Redis writes and broadcast amplification.
MAX_COLLAB_MESSAGE_BYTES = 256 * 1024

# Chat is deliberately much smaller than binary Yjs updates and is never
# persisted. These limits bound JSON parsing, fan-out, and memory per sender.
MAX_CHAT_FRAME_BYTES = 4 * 1024
MAX_CHAT_TEXT_BYTES = 2 * 1024
_CHAT_MESSAGES_PER_WINDOW = 20
_CHAT_RATE_WINDOW_SECONDS = 10.0
_CHAT_SEND_TIMEOUT_SECONDS = 2.0
_CHAT_RATE_BACKEND_TIMEOUT_SECONDS = 1.0
_CHAT_RATE_WARNING_INTERVAL_SECONDS = 60.0
_MAX_LOCAL_CHAT_BUCKETS = 4096
_chat_timestamps: dict[str, deque[float]] = {}
_last_chat_rate_warning = float("-inf")
_CHAT_RATE_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return n
"""
_EMAIL_LIKE_LABEL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_BIDI_LABEL_CONTROLS = frozenset({"\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"})


# ── lib0 variable-length uint helpers ────────────────────────────────────────

def _encode_varuint(n: int) -> bytes:
    """Encode *n* as a lib0 variable-length unsigned integer."""
    buf: list[int] = []
    while n > 127:
        buf.append((n & 0x7F) | 0x80)
        n >>= 7
    buf.append(n)
    return bytes(buf)


def _decode_varuint(data: bytes, pos: int) -> Tuple[int, int]:
    """
    Decode a lib0 varuint starting at *pos*.
    Returns ``(value, new_pos)``.
    Raises ``ValueError`` on truncated data.
    """
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("Truncated data while reading varuint")
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _encode_varbuffer(payload: bytes) -> bytes:
    """Prefix *payload* with its lib0 varuint length."""
    return _encode_varuint(len(payload)) + payload


def _decode_varbuffer(data: bytes, pos: int) -> Tuple[bytes, int]:
    """
    Read a lib0 varbuffer starting at *pos*.
    Returns ``(payload_bytes, new_pos)``.
    """
    length, pos = _decode_varuint(data, pos)
    if pos + length > len(data):
        raise ValueError("Truncated data while reading varbuffer")
    return data[pos : pos + length], pos + length


# ── Message builders ──────────────────────────────────────────────────────────

def _build_sync_step2(update: bytes) -> bytes:
    """Build a MSG_SYNC + SYNC_STEP2 message wrapping *update*."""
    return _encode_varuint(MSG_SYNC) + _encode_varuint(SYNC_STEP2) + _encode_varbuffer(update)


def _build_permission_denied(code: str, message: str) -> bytes:
    """Build a MSG_PERMISSION_DENIED message carrying a JSON reason payload."""
    payload = json.dumps({"code": code, "message": message}).encode("utf-8")
    return _encode_varuint(MSG_PERMISSION_DENIED) + _encode_varbuffer(payload)


@dataclass(frozen=True)
class ChatMessage:
    """Validated, plain-text chat content received from one room participant."""

    text: str


def _safe_chat_label(value: Optional[str]) -> str:
    """Return a bounded, plain-text display name; never fall back to an id."""
    label = (value or "").strip()
    if (
        not label
        or "@" in label
        or _EMAIL_LIKE_LABEL.fullmatch(label)
        or len(label.encode("utf-8", errors="ignore")) > 320
    ):
        return "Collaborator"
    if any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"}
        or char in _BIDI_LABEL_CONTROLS
        for char in label
    ):
        return "Collaborator"
    return label[:80] or "Collaborator"


def _build_chat_frame(text: str, sender_id: str, sender_label: Optional[str] = None) -> bytes:
    """Build a canonical ephemeral chat frame with minimal sender metadata."""
    encoded_text = text.encode("utf-8")
    if not text or len(encoded_text) > MAX_CHAT_TEXT_BYTES:
        raise ValueError("chat text exceeds the bound")
    if not sender_id or len(sender_id) > 128 or any(ord(char) < 32 for char in sender_id):
        raise ValueError("invalid chat sender")
    payload = json.dumps(
        {
            "type": "chat",
            "text": text,
            "sender_id": sender_id,
            "sender_label": _safe_chat_label(sender_label),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    frame = _encode_varuint(MSG_CHAT) + _encode_varbuffer(payload)
    if len(frame) > MAX_CHAT_FRAME_BYTES:
        raise ValueError("chat frame exceeds the bound")
    return frame


def _parse_chat_frame(data: bytes) -> Optional[ChatMessage]:
    """Strictly decode one client chat frame; never interpret HTML."""
    if len(data) > MAX_CHAT_FRAME_BYTES:
        return None
    try:
        msg_type, pos = _decode_varuint(data, 0)
        if msg_type != MSG_CHAT:
            return None
        raw, end = _decode_varbuffer(data, pos)
        if end != len(data):
            return None
        decoded = raw.decode("utf-8", errors="strict")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"type", "text"}:
        return None
    if payload.get("type") != "chat" or not isinstance(payload.get("text"), str):
        return None
    text = payload["text"]
    try:
        text_bytes = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        # json.loads accepts escaped lone UTF-16 surrogates, but they are not
        # valid UTF-8 text and must not escape the parser into the websocket
        # handler's disconnect path.
        return None
    if not text or len(text_bytes) > MAX_CHAT_TEXT_BYTES:
        return None
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        return None
    return ChatMessage(text=text)


def is_chat_frame(data: bytes) -> bool:
    """Return whether the bounded frame header identifies the chat extension."""
    try:
        msg_type, _ = _decode_varuint(data, 0)
    except ValueError:
        return False
    return msg_type == MSG_CHAT


def _chat_rate_allowed(client_id: str, *, bucket_key: Optional[str] = None) -> bool:
    now = time.monotonic()
    key = bucket_key or client_id
    timestamps = _chat_timestamps.get(key)
    if timestamps is None:
        if len(_chat_timestamps) >= _MAX_LOCAL_CHAT_BUCKETS:
            cutoff = now - _CHAT_RATE_WINDOW_SECONDS
            for stale_key, stale_timestamps in list(_chat_timestamps.items()):
                if not stale_timestamps or stale_timestamps[-1] <= cutoff:
                    _chat_timestamps.pop(stale_key, None)
            if len(_chat_timestamps) >= _MAX_LOCAL_CHAT_BUCKETS:
                return False
        timestamps = deque()
        _chat_timestamps[key] = timestamps
    while timestamps and now - timestamps[0] >= _CHAT_RATE_WINDOW_SECONDS:
        timestamps.popleft()
    if len(timestamps) >= _CHAT_MESSAGES_PER_WINDOW:
        return False
    timestamps.append(now)
    return True


async def _chat_user_rate_allowed(
    resume_id: str,
    client_id: str,
    user_id: Optional[str],
) -> bool:
    """Apply one bounded user/resume budget, shared through Redis when possible."""
    if not user_id:
        return _chat_rate_allowed(client_id)
    digest = hashlib.sha256(f"{user_id}:{resume_id}".encode("utf-8")).hexdigest()[:32]
    key = f"latexy:collab:chat-rate:{digest}"
    try:
        redis = await asyncio.wait_for(
            get_redis_client(), timeout=_CHAT_RATE_BACKEND_TIMEOUT_SECONDS
        )
        count = await asyncio.wait_for(
            redis.eval(_CHAT_RATE_LUA, 1, key, int(_CHAT_RATE_WINDOW_SECONDS)),
            timeout=_CHAT_RATE_BACKEND_TIMEOUT_SECONDS,
        )
        return int(count) <= _CHAT_MESSAGES_PER_WINDOW
    except Exception as exc:
        # Redis is not required for ordinary Yjs traffic. If unavailable, use
        # a capped user/resume guard and never retain unbounded local state.
        _warn_chat_rate_backend_unavailable(exc)
        return _chat_rate_allowed(client_id, bucket_key=f"user:{digest}")


def _warn_chat_rate_backend_unavailable(exc: Exception) -> None:
    """Emit at most one metadata-only outage warning per interval."""
    global _last_chat_rate_warning
    now = time.monotonic()
    if now - _last_chat_rate_warning >= _CHAT_RATE_WARNING_INTERVAL_SECONDS:
        _last_chat_rate_warning = now
        logger.warning("Collab chat rate backend unavailable (%s)", type(exc).__name__)


def reset_chat_rate_limit(client_id: str) -> None:
    """Drop per-connection chat-rate state when a socket disconnects."""
    _chat_timestamps.pop(client_id, None)


# Minimal valid Y.js empty-document update (0 structs, 0 deletes)
_EMPTY_YJS_UPDATE: bytes = bytes([0, 0])


# ── Room ─────────────────────────────────────────────────────────────────────

class CollabRoom:
    """
    Holds all WebSocket connections for one ``resume_id``.
    All mutations are protected by an ``asyncio.Lock``.
    """

    def __init__(self, resume_id: str) -> None:
        self.resume_id = resume_id
        # Maps client_id → (websocket, user_info)
        self._clients: Dict[str, Tuple[WebSocket, dict]] = {}
        self._lock = asyncio.Lock()

    # ── Connection management ─────────────────────────────────────────────

    async def add(self, client_id: str, ws: WebSocket, user_info: dict) -> None:
        async with self._lock:
            self._clients[client_id] = (ws, user_info)

    async def remove(self, client_id: str) -> None:
        async with self._lock:
            self._clients.pop(client_id, None)

    @property
    def size(self) -> int:
        return len(self._clients)

    async def all_clients(self) -> List[Tuple[str, dict]]:
        """Snapshot of ``[(client_id, user_info), ...]``."""
        async with self._lock:
            return [(cid, info) for cid, (_, info) in self._clients.items()]

    # ── Authorisation ─────────────────────────────────────────────────────

    def role_of(self, client_id: str) -> Optional[str]:
        """Role this client was authorised with at connection time."""
        entry = self._clients.get(client_id)
        return entry[1].get("role") if entry else None

    def can_edit(self, client_id: str) -> bool:
        """True if this client may mutate the shared document."""
        return self.role_of(client_id) in EDIT_ROLES

    async def close_user(
        self,
        user_id: str,
        *,
        code: int = CLOSE_ACCESS_REVOKED,
        reason: str = "Access revoked",
        notice_code: str = "access_revoked",
    ) -> int:
        """
        Terminate every socket belonging to *user_id* in this room.
        Returns the number of sockets closed.
        """
        async with self._lock:
            targets = [
                (cid, ws)
                for cid, (ws, info) in self._clients.items()
                if info.get("user_id") == user_id
            ]

        notice = _build_permission_denied(notice_code, reason)
        for cid, ws in targets:
            try:
                await ws.send_bytes(notice)
            except Exception:
                pass
            try:
                await ws.close(code=code, reason=reason[:120])
            except Exception:
                pass
            await self.remove(cid)

        return len(targets)

    # ── Messaging ─────────────────────────────────────────────────────────

    async def broadcast(
        self,
        data: bytes,
        *,
        exclude: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """Send *data* to every client except *exclude*."""
        async with self._lock:
            snapshot = list(self._clients.items())

        if timeout is None:
            # Preserve ordered, sequential delivery for Yjs frames.
            dead: list[str] = []
            for cid, (ws, _) in snapshot:
                if cid == exclude:
                    continue
                try:
                    await ws.send_bytes(data)
                except Exception:
                    dead.append(cid)
        else:
            async def send_bounded(cid: str, ws: WebSocket) -> Optional[str]:
                try:
                    await asyncio.wait_for(ws.send_bytes(data), timeout=timeout)
                except asyncio.TimeoutError:
                    return cid
                except Exception:
                    return cid
                return None

            tasks = [
                send_bounded(cid, ws)
                for cid, (ws, _) in snapshot
                if cid != exclude
            ]
            results = await asyncio.gather(*tasks)
            dead = [cid for cid in results if cid is not None]

        for cid in dead:
            await self.remove(cid)

    async def send_to(self, client_id: str, data: bytes) -> None:
        """Send *data* to a specific client."""
        async with self._lock:
            entry = self._clients.get(client_id)
        if entry is None:
            return
        ws, _ = entry
        try:
            await ws.send_bytes(data)
        except Exception:
            await self.remove(client_id)

    async def relay(
        self,
        data: bytes,
        *,
        exclude: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """
        Deliver *data* to peers in this room — both the ones connected to this
        process and the ones connected to other API workers (via Redis).
        """
        await self.broadcast(data, exclude=exclude, timeout=timeout)
        envelope = {"kind": "frame", "data": base64.b64encode(data).decode("ascii")}
        if timeout is None:
            await _publish(self.resume_id, envelope)
        else:
            try:
                await asyncio.wait_for(_publish(self.resume_id, envelope), timeout=timeout)
            except asyncio.TimeoutError:
                # Chat delivery is best-effort and bounded; a slow Redis
                # backend must not hold a websocket receive loop indefinitely.
                logger.warning("Collab: chat publish timed out for %s", self.resume_id[:8])


# ── Manager ───────────────────────────────────────────────────────────────────

class CollabManager:
    """Singleton that maps ``resume_id → CollabRoom`` plus its Redis bridge."""

    def __init__(self) -> None:
        self._rooms: Dict[str, CollabRoom] = {}
        # resume_id → running Redis Pub/Sub listener task
        self._listeners: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, resume_id: str) -> CollabRoom:
        listener_started: Optional[asyncio.Event] = None
        async with self._lock:
            if resume_id not in self._rooms:
                self._rooms[resume_id] = CollabRoom(resume_id)

            listener = self._listeners.get(resume_id)
            if listener is None or listener.done():
                # Subscribe before starting the task so frames published while
                # the task spins up are not lost (same ordering as EventBus).
                pubsub = await _subscribe(resume_id)
                if pubsub is not None:
                    listener_started = asyncio.Event()
                    self._listeners[resume_id] = asyncio.create_task(
                        self._bridge(resume_id, pubsub, listener_started),
                        name=f"collab:{resume_id}",
                    )

            room = self._rooms[resume_id]

        # Do not hand ownership of the room back until the bridge has entered
        # its try/finally.  Otherwise immediate cleanup can cancel a task
        # before its coroutine starts, leaving the already-open Pub/Sub object
        # with no finally block capable of closing it.
        if listener_started is not None:
            await listener_started.wait()
        return room

    async def maybe_cleanup(self, resume_id: str) -> None:
        """Remove the room and its Redis listener if no clients remain."""
        task: Optional[asyncio.Task] = None
        async with self._lock:
            room = self._rooms.get(resume_id)
            if room is not None and room.size == 0:
                del self._rooms[resume_id]
                task = self._listeners.pop(resume_id, None)

        # Await cancellation outside the manager lock.  The bridge performs
        # asynchronous Redis cleanup in ``finally``; fire-and-forget
        # cancellation otherwise lets that work survive the request (and, in
        # tests, the event loop) that owned the room.
        if task is not None:
            await self._stop_listener(task)

    async def shutdown(self) -> None:
        """Cancel and await every Redis bridge owned by this process."""
        async with self._lock:
            tasks = list(self._listeners.values())
            self._listeners.clear()
            self._rooms.clear()

        if tasks:
            await asyncio.gather(
                *(self._stop_listener(task) for task in tasks),
            )

    @staticmethod
    async def _stop_listener(task: asyncio.Task) -> None:
        """Cancel one listener and wait until its Pub/Sub cleanup finishes."""
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # A task cancelled before its coroutine first runs cannot execute
            # the bridge's own CancelledError handler.
            pass

    async def revoke_access(
        self,
        resume_id: str,
        user_id: str,
        *,
        reason: str = "Access revoked",
        code: int = CLOSE_ACCESS_REVOKED,
        notice_code: str = "access_revoked",
    ) -> int:
        """
        Terminate *user_id*'s live collaboration sockets for *resume_id*, on this
        process and on every other API worker.

        Called by the collaborator management routes whenever a collaborator is
        removed or their role changes, so that revocation takes effect
        immediately instead of at the next reconnect.  Returns the number of
        sockets closed locally.
        """
        closed = 0
        room = self._rooms.get(resume_id)
        if room is not None:
            closed = await room.close_user(
                user_id, code=code, reason=reason, notice_code=notice_code
            )
            await self.maybe_cleanup(resume_id)

        await _publish(
            resume_id,
            {
                "kind": "revoke",
                "user_id": user_id,
                "reason": reason,
                "code": code,
                "notice_code": notice_code,
            },
        )
        return closed

    # ── Internal: cross-process bridge ────────────────────────────────────

    async def _bridge(
        self,
        resume_id: str,
        pubsub: Any,
        started: Optional[asyncio.Event] = None,
    ) -> None:
        """Apply envelopes published by other API workers to the local room."""
        channel = f"{_COLLAB_CHANNEL_PREFIX}{resume_id}"
        # Capture this while the loop is known to be alive.  Calling
        # asyncio.current_task() from ``finally`` is unsafe when Python closes
        # a coroutine during event-loop teardown.
        listener_task = asyncio.current_task()
        if started is not None:
            started.set()
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    envelope = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                if envelope.get("origin") == _PROCESS_ID:
                    continue  # already applied locally by the publisher

                room = self._rooms.get(resume_id)
                if room is None:
                    break  # room went away — stop listening

                kind = envelope.get("kind")
                if kind == "frame":
                    try:
                        data = base64.b64decode(envelope.get("data", ""))
                    except Exception:
                        continue
                    if data:
                        await room.broadcast(
                            data,
                            timeout=_CHAT_SEND_TIMEOUT_SECONDS if is_chat_frame(data) else None,
                        )
                elif kind == "revoke":
                    await room.close_user(
                        envelope.get("user_id", ""),
                        code=int(envelope.get("code") or CLOSE_ACCESS_REVOKED),
                        reason=envelope.get("reason", "Access revoked"),
                        notice_code=envelope.get("notice_code") or "access_revoked",
                    )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(
                "Collab: bridge error for %s",
                resume_id[:8],
                extra={"error_type": type(exc).__name__},
            )
        finally:
            # Only de-register if we are still the registered listener: a
            # rejoin during our (awaiting) teardown may already have installed
            # a newer task, and clobbering it would leak an untracked bridge.
            if self._listeners.get(resume_id) is listener_task:
                self._listeners.pop(resume_id, None)
            try:
                await pubsub.unsubscribe(channel)
            except Exception as exc:
                logger.debug(
                    "Collab: bridge unsubscribe failed",
                    extra={"error_type": type(exc).__name__},
                )
            finally:
                try:
                    await pubsub.aclose()
                except Exception as exc:
                    logger.debug(
                        "Collab: bridge close failed",
                        extra={"error_type": type(exc).__name__},
                    )


# Module-level singleton used by the WebSocket handler.
collab_manager = CollabManager()


# ── Cross-process Pub/Sub helpers ────────────────────────────────────────────

async def _subscribe(resume_id: str) -> Optional[Any]:
    """Subscribe to this room's Pub/Sub channel; None if Redis is unavailable."""
    channel = f"{_COLLAB_CHANNEL_PREFIX}{resume_id}"
    pubsub = None
    try:
        r = await get_redis_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        return pubsub
    except asyncio.CancelledError:
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as cleanup_exc:
                logger.debug(
                    "Collab: cancelled subscribe cleanup failed",
                    extra={"error_type": type(cleanup_exc).__name__},
                )
        raise
    except Exception as exc:
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception as cleanup_exc:
                logger.debug(
                    "Collab: failed subscribe cleanup failed",
                    extra={"error_type": type(cleanup_exc).__name__},
                )
        logger.warning(
            "Collab: Pub/Sub subscribe failed for %s",
            resume_id[:8],
            extra={"error_type": type(exc).__name__},
        )
        return None


async def _publish(resume_id: str, envelope: dict) -> None:
    """Publish an envelope to the other API workers hosting this room."""
    envelope["origin"] = _PROCESS_ID
    try:
        r = await get_redis_client()
        await r.publish(f"{_COLLAB_CHANNEL_PREFIX}{resume_id}", json.dumps(envelope))
    except Exception as exc:
        logger.warning(
            "Collab: Pub/Sub publish failed for %s",
            resume_id[:8],
            extra={"error_type": type(exc).__name__},
        )


# ── Connection-time notices ───────────────────────────────────────────────────

async def notify_if_read_only(room: CollabRoom, client_id: str) -> bool:
    """
    Tell a freshly-joined client straight away when its role cannot edit.

    Without this the client only learns it is read-only after its first write
    is refused — by which point the user has already typed edits that the
    server drops, so they silently vanish on reload.  Returns True if a notice
    was sent.
    """
    if room.can_edit(client_id):
        return False
    await room.send_to(
        client_id,
        _build_permission_denied(
            "read_only",
            "Your role does not allow editing this document",
        ),
    )
    return True


# ── Per-message handler ───────────────────────────────────────────────────────

async def handle_collab_message(
    resume_id: str,
    client_id: str,
    data: bytes,
    room: CollabRoom,
    *,
    chat_authorized: Optional[bool] = None,
    chat_user_id: Optional[str] = None,
    chat_sender_label: Optional[str] = None,
    chat_access_check: Optional[Callable[[], Awaitable[bool]]] = None,
) -> None:
    """
    Dispatch one binary Y.js message received from *client_id*.

    * SYNC_STEP1  → send all stored updates back to the requesting client
    * SYNC_STEP2 / MSG_UPDATE → persist update bytes; relay to peers
                                (rejected unless the client's role can edit)
    * MSG_AWARENESS / MSG_QUERY_AWARENESS → relay to peers (no persistence)
    * MSG_CHAT → relay validated plain-text chat only (never persisted)

    ``chat_access_check`` is supplied by the websocket route and is deliberately
    invoked only after strict parsing and rate limiting. ``chat_authorized`` is
    an explicit internal/test override; ``None`` preserves the room-member
    assumption for internal callers, while ``False`` fails closed.
    """
    if not data:
        return

    # Bound per-frame size to prevent a single peer from flooding Redis / peers
    # with arbitrarily large binary frames.
    if len(data) > MAX_COLLAB_MESSAGE_BYTES:
        logger.warning(
            "Collab: dropping oversized frame (%d bytes) from %s",
            len(data),
            client_id[:8],
        )
        return

    try:
        msg_type, pos = _decode_varuint(data, 0)
    except ValueError:
        logger.debug("Collab: malformed varuint header from %s", client_id[:8])
        return

    if msg_type == MSG_SYNC:
        try:
            sync_type, pos = _decode_varuint(data, pos)
        except ValueError:
            return

        if sync_type == SYNC_STEP1:
            # Client requests the current document state.
            # Respond with all stored updates as individual SYNC_STEP2 messages.
            await _send_catchup(resume_id, client_id, room)

        elif sync_type in (SYNC_STEP2, MSG_UPDATE):
            # Actual document update — only editors and the owner may mutate
            # the document; viewers / commenters get a denial notice instead.
            if not room.can_edit(client_id):
                logger.info(
                    "Collab: rejected write from %s role=%s on %s",
                    client_id[:8],
                    room.role_of(client_id),
                    resume_id[:8],
                )
                await room.send_to(
                    client_id,
                    _build_permission_denied(
                        "read_only",
                        "Your role does not allow editing this document",
                    ),
                )
                return

            try:
                update_bytes, _ = _decode_varbuffer(data, pos)
            except ValueError:
                return

            if update_bytes:
                await _persist_update(resume_id, update_bytes)

            await room.relay(data, exclude=client_id)

    elif msg_type in (MSG_AWARENESS, MSG_QUERY_AWARENESS):
        # Cursor / presence data — relay without storage.  Allowed for every
        # role: read-only collaborators still appear in the presence list.
        await room.relay(data, exclude=client_id)

    elif msg_type == MSG_CHAT:
        message = _parse_chat_frame(data)
        if message is None:
            # Do not echo malformed input or include it in logs.  Dropping it
            # keeps the extension safe for clients that send arbitrary frames.
            return
        if not await _chat_user_rate_allowed(resume_id, client_id, chat_user_id):
            await room.send_to(
                client_id,
                _build_permission_denied(
                    "chat_rate_limited",
                    "Too many chat messages",
                ),
            )
            return

        if chat_access_check is not None:
            chat_authorized = await chat_access_check()
        if chat_authorized is False:
            await room.send_to(
                client_id,
                _build_permission_denied(
                    "chat_forbidden",
                    "You no longer have access to this resume",
                ),
            )
            return
        # Never trust sender metadata supplied by the client. The canonical
        # frame carries the authenticated room client identifier plus the
        # server-derived safe display label.
        canonical = _build_chat_frame(message.text, client_id, chat_sender_label)
        await room.relay(
            canonical,
            exclude=client_id,
            timeout=_CHAT_SEND_TIMEOUT_SECONDS,
        )


# ── Redis helpers ─────────────────────────────────────────────────────────────

_MAX_UPDATES = 500  # cap per-room update list to prevent unbounded growth

async def _persist_update(resume_id: str, update_bytes: bytes) -> None:
    """Append *update_bytes* (base64-encoded) to the Redis update list."""
    try:
        r = await get_redis_client()
        key = f"collab:{resume_id}:updates"
        encoded = base64.b64encode(update_bytes).decode("ascii")
        await r.rpush(key, encoded)
        await r.ltrim(key, -_MAX_UPDATES, -1)
        await r.expire(key, _COLLAB_TTL)
    except Exception as exc:
        logger.warning(
            "Collab: Redis write failed for %s",
            resume_id[:8],
            extra={"error_type": type(exc).__name__},
        )


async def _send_catchup(resume_id: str, client_id: str, room: CollabRoom) -> None:
    """
    Respond to a client's SYNC_STEP1 by replaying all stored updates
    as SYNC_STEP2 messages.  If nothing is stored, send an empty-doc update.
    """
    try:
        r = await get_redis_client()
        stored: list[str] = await r.lrange(f"collab:{resume_id}:updates", 0, -1)
    except Exception as exc:
        logger.warning(
            "Collab: Redis read failed for %s",
            resume_id[:8],
            extra={"error_type": type(exc).__name__},
        )
        stored = []

    if stored:
        for encoded in stored:
            try:
                update_bytes = base64.b64decode(encoded)
                msg = _build_sync_step2(update_bytes)
                await room.send_to(client_id, msg)
            except Exception:
                continue
    else:
        # Empty document — send a no-op update so the client completes sync.
        await room.send_to(client_id, _build_sync_step2(_EMPTY_YJS_UPDATE))

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
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi.websockets import WebSocket

from ..core.logging import get_logger
from ..core.redis import get_redis_client

logger = get_logger(__name__)

# ── lib0 message type constants ───────────────────────────────────────────────
MSG_SYNC = 0
MSG_AWARENESS = 1
MSG_QUERY_AWARENESS = 3

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

    async def broadcast(self, data: bytes, *, exclude: Optional[str] = None) -> None:
        """Send *data* to every client except *exclude*."""
        async with self._lock:
            snapshot = list(self._clients.items())

        dead: list[str] = []
        for cid, (ws, _) in snapshot:
            if cid == exclude:
                continue
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(cid)

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

    async def relay(self, data: bytes, *, exclude: Optional[str] = None) -> None:
        """
        Deliver *data* to peers in this room — both the ones connected to this
        process and the ones connected to other API workers (via Redis).
        """
        await self.broadcast(data, exclude=exclude)
        await _publish(
            self.resume_id,
            {"kind": "frame", "data": base64.b64encode(data).decode("ascii")},
        )


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
                        await room.broadcast(data)
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
            logger.error("Collab: bridge error for %s: %s", resume_id[:8], exc)
        finally:
            # Only de-register if we are still the registered listener: a
            # rejoin during our (awaiting) teardown may already have installed
            # a newer task, and clobbering it would leak an untracked bridge.
            if self._listeners.get(resume_id) is listener_task:
                self._listeners.pop(resume_id, None)
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception as exc:
                logger.debug("Collab: bridge cleanup failed: %s", exc)


# Module-level singleton used by the WebSocket handler.
collab_manager = CollabManager()


# ── Cross-process Pub/Sub helpers ────────────────────────────────────────────

async def _subscribe(resume_id: str) -> Optional[Any]:
    """Subscribe to this room's Pub/Sub channel; None if Redis is unavailable."""
    channel = f"{_COLLAB_CHANNEL_PREFIX}{resume_id}"
    try:
        r = await get_redis_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        return pubsub
    except Exception as exc:
        logger.warning("Collab: Pub/Sub subscribe failed for %s: %s", resume_id[:8], exc)
        return None


async def _publish(resume_id: str, envelope: dict) -> None:
    """Publish an envelope to the other API workers hosting this room."""
    envelope["origin"] = _PROCESS_ID
    try:
        r = await get_redis_client()
        await r.publish(f"{_COLLAB_CHANNEL_PREFIX}{resume_id}", json.dumps(envelope))
    except Exception as exc:
        logger.warning("Collab: Pub/Sub publish failed for %s: %s", resume_id[:8], exc)


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
) -> None:
    """
    Dispatch one binary Y.js message received from *client_id*.

    * SYNC_STEP1  → send all stored updates back to the requesting client
    * SYNC_STEP2 / MSG_UPDATE → persist update bytes; relay to peers
                                (rejected unless the client's role can edit)
    * MSG_AWARENESS / MSG_QUERY_AWARENESS → relay to peers (no persistence)
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
        logger.warning("Collab: Redis write failed for %s: %s", resume_id[:8], exc)


async def _send_catchup(resume_id: str, client_id: str, room: CollabRoom) -> None:
    """
    Respond to a client's SYNC_STEP1 by replaying all stored updates
    as SYNC_STEP2 messages.  If nothing is stored, send an empty-doc update.
    """
    try:
        r = await get_redis_client()
        stored: list[str] = await r.lrange(f"collab:{resume_id}:updates", 0, -1)
    except Exception as exc:
        logger.warning("Collab: Redis read failed for %s: %s", resume_id[:8], exc)
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

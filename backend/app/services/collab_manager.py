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
"""

from __future__ import annotations

import asyncio
import base64
from typing import Dict, List, Optional, Tuple

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

# Redis TTL for collaboration document state (24 h)
_COLLAB_TTL = 86_400


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


# ── Manager ───────────────────────────────────────────────────────────────────

class CollabManager:
    """Singleton that maps ``resume_id → CollabRoom``."""

    def __init__(self) -> None:
        self._rooms: Dict[str, CollabRoom] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, resume_id: str) -> CollabRoom:
        async with self._lock:
            if resume_id not in self._rooms:
                self._rooms[resume_id] = CollabRoom(resume_id)
            return self._rooms[resume_id]

    async def maybe_cleanup(self, resume_id: str) -> None:
        """Remove the room if it has no connected clients."""
        async with self._lock:
            room = self._rooms.get(resume_id)
            if room is not None and room.size == 0:
                del self._rooms[resume_id]


# Module-level singleton used by the WebSocket handler.
collab_manager = CollabManager()


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
    * MSG_AWARENESS / MSG_QUERY_AWARENESS → relay to peers (no persistence)
    """
    if not data:
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
            # Actual document update — persist then relay.
            try:
                update_bytes, _ = _decode_varbuffer(data, pos)
            except ValueError:
                return

            if update_bytes:
                await _persist_update(resume_id, update_bytes)

            await room.broadcast(data, exclude=client_id)

    elif msg_type in (MSG_AWARENESS, MSG_QUERY_AWARENESS):
        # Cursor / presence data — relay without storage.
        await room.broadcast(data, exclude=client_id)


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

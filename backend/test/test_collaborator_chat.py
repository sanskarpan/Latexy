"""Focused tests for the ephemeral collaborator-chat protocol extension."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.api.ws_routes import _collab_chat_access_ok
from app.database.models import Resume, User
from app.main import app
from app.services import collab_manager as collab


def _incoming_chat(text: str) -> bytes:
    payload = json.dumps({"type": "chat", "text": text}, separators=(",", ":")).encode()
    return collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(payload)


def _permission_payload(frame: bytes) -> dict:
    _, pos = collab._decode_varuint(frame, 0)
    payload, end = collab._decode_varbuffer(frame, pos)
    assert end == len(frame)
    return json.loads(payload)


def _outgoing_chat(text: str) -> bytes:
    payload = json.dumps({"type": "chat", "text": text}, separators=(",", ":")).encode()
    return collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(payload)


class TestChatFrames:
    def test_round_trip_uses_authenticated_sender_only(self) -> None:
        frame = _incoming_chat("hello")

        message = collab._parse_chat_frame(frame)
        assert message is not None and message.text == "hello"
        frame = collab._build_chat_frame(message.text, "client-1")
        _, pos = collab._decode_varuint(frame, 0)
        payload, _ = collab._decode_varbuffer(frame, pos)
        assert json.loads(payload) == {
            "type": "chat",
            "text": "hello",
            "sender_id": "client-1",
            "sender_label": "Collaborator",
        }

    @pytest.mark.parametrize(
        "frame",
        [
            _incoming_chat("hello") + b"trailing",
            collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(b"not-json"),
            collab._encode_varuint(collab.MSG_CHAT)
            + collab._encode_varbuffer(b'{"type":"chat","text":"x","sender_id":"spoof"}'),
            collab._encode_varuint(collab.MSG_CHAT)
            + collab._encode_varbuffer(b'{"type":"chat","text":"\\u0000"}'),
            collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(b"\xff"),
            collab._encode_varuint(collab.MSG_CHAT)
            + collab._encode_varbuffer(b'{"type":"chat","text":"\\ud800"}'),
        ],
    )
    def test_malformed_or_spoofed_frames_are_rejected(self, frame: bytes) -> None:
        assert collab._parse_chat_frame(frame) is None

    def test_oversized_text_and_frame_are_rejected(self) -> None:
        assert collab._parse_chat_frame(_incoming_chat("x" * (collab.MAX_CHAT_TEXT_BYTES + 1))) is None
        assert collab._parse_chat_frame(b"\x3e" + b"x" * collab.MAX_CHAT_FRAME_BYTES) is None

    def test_server_label_is_bounded_and_never_uses_raw_identifier(self) -> None:
        assert collab._safe_chat_label(None) == "Collaborator"
        assert collab._safe_chat_label("  Alice  ") == "Alice"
        assert collab._safe_chat_label("Alice\u0000") == "Collaborator"
        assert collab._safe_chat_label("alice@example.com") == "Collaborator"
        assert collab._safe_chat_label("Alice\u202e") == "Collaborator"
        assert collab._safe_chat_label("Alice\u200b") == "Collaborator"
        assert collab._safe_chat_label("x" * 400) == "Collaborator"
        frame = collab._build_chat_frame("hello", "private-client-id", "Alice")
        _, pos = collab._decode_varuint(frame, 0)
        payload, _ = collab._decode_varbuffer(frame, pos)
        assert json.loads(payload)["sender_label"] == "Alice"
        assert "private-client-id" not in json.loads(payload)["sender_label"]


@pytest.mark.asyncio
async def test_chat_fanout_is_canonical_ephemeral_and_excludes_sender() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peer = AsyncMock()
    await room.add("sender", sender, {"user_id": "user-1"})
    await room.add("peer", peer, {"user_id": "user-2"})

    with patch.object(collab, "_publish", new_callable=AsyncMock) as publish, patch.object(
        collab, "_persist_update", new_callable=AsyncMock
    ) as persist:
        await collab.handle_collab_message("resume-1", "sender", _incoming_chat("hello"), room)

    sender.send_bytes.assert_not_called()
    peer.send_bytes.assert_called_once()
    _, pos = collab._decode_varuint(peer.send_bytes.call_args.args[0], 0)
    payload, _ = collab._decode_varbuffer(peer.send_bytes.call_args.args[0], pos)
    assert json.loads(payload) == {"type": "chat", "text": "hello", "sender_id": "sender", "sender_label": "Collaborator"}
    assert publish.await_count == 1
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_fanout_uses_server_label_and_discards_client_metadata() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peer = AsyncMock()
    await room.add("sender", sender, {"user_id": "user-1"})
    await room.add("peer", peer, {"user_id": "user-2"})

    with patch.object(collab, "_publish", new_callable=AsyncMock):
        await collab.handle_collab_message(
            "resume-1",
            "sender",
            _incoming_chat("<b>plain text</b>"),
            room,
            chat_sender_label="Alice",
        )

    _, pos = collab._decode_varuint(peer.send_bytes.call_args.args[0], 0)
    payload, _ = collab._decode_varbuffer(peer.send_bytes.call_args.args[0], pos)
    assert json.loads(payload) == {
        "type": "chat",
        "text": "<b>plain text</b>",
        "sender_id": "sender",
        "sender_label": "Alice",
    }


@pytest.mark.asyncio
async def test_two_real_websocket_clients_exchange_ephemeral_chat() -> None:
    """Exercise the ASGI websocket route, not only CollabRoom fan-out."""
    from app.database.connection import get_async_db_session

    user_id = str(uuid.uuid4())
    resume_id = str(uuid.uuid4())
    async with get_async_db_session() as db:
        db.add(User(id=user_id, email=f"test_chat_{user_id}@example.com", name="Alice"))
        db.add(Resume(id=resume_id, user_id=user_id, title="Chat test", latex_content=""))
        await db.commit()

    async def consume_ticket(*_args, **_kwargs):
        return user_id

    with (
        patch("app.api.ws_routes._consume_ws_ticket", new=consume_ticket),
        patch.object(collab, "_subscribe", new_callable=AsyncMock, return_value=None),
        patch.object(collab, "_publish", new_callable=AsyncMock),
        patch.object(collab, "_chat_user_rate_allowed", new_callable=AsyncMock, return_value=True),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/collab/{resume_id}?ticket=one") as first:
                with client.websocket_connect(f"/ws/collab/{resume_id}?ticket=two") as second:
                    first.send_bytes(_outgoing_chat("<b>literal</b>"))
                    received = second.receive_bytes()

    _, pos = collab._decode_varuint(received, 0)
    body, end = collab._decode_varbuffer(received, pos)
    assert end == len(received)
    payload = json.loads(body)
    assert payload["type"] == "chat"
    assert payload["text"] == "<b>literal</b>"
    assert payload["sender_id"] and payload["sender_id"] != user_id
    assert payload["sender_label"] == "Alice"


@pytest.mark.asyncio
async def test_chat_live_authorization_denial_does_not_fan_out() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peer = AsyncMock()
    await room.add("sender", sender, {})
    await room.add("peer", peer, {})

    with patch.object(collab, "_publish", new_callable=AsyncMock) as publish:
        await collab.handle_collab_message(
            "resume-1", "sender", _incoming_chat("secret"), room, chat_authorized=False
        )

    peer.send_bytes.assert_not_called()
    publish.assert_not_awaited()
    assert _permission_payload(sender.send_bytes.call_args.args[0]) == {
        "code": "chat_forbidden",
        "message": "You no longer have access to this resume",
    }


@pytest.mark.asyncio
async def test_malformed_chat_never_invokes_deferred_acl_check() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    await room.add("sender", sender, {})
    access_check = AsyncMock(return_value=True)

    await collab.handle_collab_message(
        "resume-1",
        "sender",
        collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(b"not-json"),
        room,
        chat_access_check=access_check,
    )

    access_check.assert_not_awaited()
    sender.send_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_rate_rejected_chat_never_invokes_deferred_acl_check() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    await room.add("sender", sender, {})
    access_check = AsyncMock(return_value=True)

    with patch.object(collab, "_chat_user_rate_allowed", new=AsyncMock(return_value=False)):
        await collab.handle_collab_message(
            "resume-1",
            "sender",
            _incoming_chat("hello"),
            room,
            chat_user_id="user-1",
            chat_access_check=access_check,
        )

    access_check.assert_not_awaited()
    assert _permission_payload(sender.send_bytes.call_args.args[0])["code"] == "chat_rate_limited"


@pytest.mark.asyncio
async def test_allowed_chat_invokes_deferred_acl_check_before_fanout() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peer = AsyncMock()
    await room.add("sender", sender, {})
    await room.add("peer", peer, {})
    access_check = AsyncMock(return_value=True)

    with patch.object(collab, "_chat_user_rate_allowed", new=AsyncMock(return_value=True)), patch.object(
        collab, "_publish", new_callable=AsyncMock
    ):
        await collab.handle_collab_message(
            "resume-1",
            "sender",
            _incoming_chat("hello"),
            room,
            chat_user_id="user-1",
            chat_access_check=access_check,
        )

    access_check.assert_awaited_once()
    peer.send_bytes.assert_called_once()


@pytest.mark.asyncio
async def test_chat_rate_limit_stops_at_twenty_messages() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peer = AsyncMock()
    await room.add("sender", sender, {})
    await room.add("peer", peer, {})
    collab.reset_chat_rate_limit("sender")

    with patch.object(collab, "_publish", new_callable=AsyncMock) as publish:
        for _ in range(collab._CHAT_MESSAGES_PER_WINDOW + 1):
            await collab.handle_collab_message("resume-1", "sender", _incoming_chat("x"), room)

    assert peer.send_bytes.await_count == collab._CHAT_MESSAGES_PER_WINDOW
    assert publish.await_count == collab._CHAT_MESSAGES_PER_WINDOW
    assert sender.send_bytes.await_count == 1
    assert _permission_payload(sender.send_bytes.call_args.args[0])["code"] == "chat_rate_limited"
    collab.reset_chat_rate_limit("sender")


def test_local_chat_rate_bucket_capacity_recovers_after_expiry() -> None:
    collab._chat_timestamps.clear()
    with patch.object(collab, "_MAX_LOCAL_CHAT_BUCKETS", 2), patch.object(
        collab.time, "monotonic", side_effect=[0.0, 0.0, 11.0]
    ):
        assert collab._chat_rate_allowed("one", bucket_key="user:one")
        assert collab._chat_rate_allowed("two", bucket_key="user:two")
        assert collab._chat_rate_allowed("three", bucket_key="user:three")

    assert list(collab._chat_timestamps) == ["user:three"]
    collab._chat_timestamps.clear()


@pytest.mark.asyncio
async def test_chat_backpressure_drops_slow_peer() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    slow_peer = AsyncMock()

    async def slow_send(_data: bytes) -> None:
        await asyncio.sleep(0.02)

    slow_peer.send_bytes.side_effect = slow_send
    await room.add("sender", sender, {})
    await room.add("slow", slow_peer, {})
    with patch.object(collab, "_CHAT_SEND_TIMEOUT_SECONDS", 0.001), patch.object(
        collab, "_publish", new_callable=AsyncMock
    ):
        await collab.handle_collab_message("resume-1", "sender", _incoming_chat("x"), room)
    assert [client_id for client_id, _ in await room.all_clients()] == ["sender"]


@pytest.mark.asyncio
async def test_chat_backpressure_fans_out_slow_peers_concurrently() -> None:
    room = collab.CollabRoom("resume-1")
    sender = AsyncMock()
    peers = [AsyncMock() for _ in range(3)]
    active = 0
    max_active = 0
    for index, peer in enumerate(peers):
        async def slow_send(_data: bytes, *, delay=0.05) -> None:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(delay)
            finally:
                active -= 1

        peer.send_bytes.side_effect = slow_send
        await room.add(f"slow-{index}", peer, {})
    await room.add("sender", sender, {})

    with patch.object(collab, "_CHAT_SEND_TIMEOUT_SECONDS", 0.03):
        await room.broadcast(b"chat", exclude="sender", timeout=0.03)

    assert max_active == len(peers)
    assert active == 0
    assert room.size == 1


class _ChatRateRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, script: str, key_count: int, key: str, window: int) -> int:
        assert script == collab._CHAT_RATE_LUA
        assert key_count == 1
        assert window == int(collab._CHAT_RATE_WINDOW_SECONDS)
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


@pytest.mark.asyncio
async def test_chat_rate_limit_is_shared_by_user_and_resume_across_connections() -> None:
    redis = _ChatRateRedis()
    with patch.object(collab, "get_redis_client", new=AsyncMock(return_value=redis)):
        results = [
            await collab._chat_user_rate_allowed("resume-1", f"connection-{i % 2}", "user-1")
            for i in range(collab._CHAT_MESSAGES_PER_WINDOW + 1)
        ]

    assert results == [True] * collab._CHAT_MESSAGES_PER_WINDOW + [False]
    assert len(redis.counts) == 1


@pytest.mark.asyncio
async def test_chat_rate_limit_fallback_is_shared_and_capped_when_redis_is_down() -> None:
    collab._chat_timestamps.clear()
    with patch.object(collab, "get_redis_client", new=AsyncMock(side_effect=RuntimeError("offline"))):
        results = [
            await collab._chat_user_rate_allowed("resume-1", f"connection-{i % 2}", "user-1")
            for i in range(collab._CHAT_MESSAGES_PER_WINDOW + 1)
        ]

    assert results == [True] * collab._CHAT_MESSAGES_PER_WINDOW + [False]
    assert len(collab._chat_timestamps) == 1
    collab._chat_timestamps.clear()


def test_chat_rate_backend_warning_is_throttled() -> None:
    with (
        patch.object(collab, "_last_chat_rate_warning", float("-inf")),
        patch.object(collab.time, "monotonic", side_effect=[100.0, 110.0, 161.0]),
        patch.object(collab.logger, "warning") as warning,
    ):
        collab._warn_chat_rate_backend_unavailable(RuntimeError("offline"))
        collab._warn_chat_rate_backend_unavailable(RuntimeError("offline"))
        collab._warn_chat_rate_backend_unavailable(RuntimeError("offline"))

    assert warning.call_count == 2
    assert all("offline" not in str(call) for call in warning.call_args_list)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["owner", "collaborator", "removed", "missing", "db_error"])
async def test_chat_access_rechecks_owner_and_collaborator_acl(case: str) -> None:
    resume = MagicMock(user_id="owner") if case != "missing" else None
    collaborator = MagicMock() if case == "collaborator" else None
    db = AsyncMock()
    if case == "db_error":
        db.execute.side_effect = RuntimeError("database unavailable")
    elif case == "missing":
        db.execute.return_value = _Result(None)
    else:
        db.execute.side_effect = [_Result(resume), _Result(collaborator)]

    @asynccontextmanager
    async def session():
        yield db

    with patch("app.database.connection.get_async_db_session", session):
        allowed = await _collab_chat_access_ok("resume-1", "owner" if case == "owner" else "member")

    assert allowed is (case in {"owner", "collaborator"})

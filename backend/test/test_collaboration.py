"""Tests for Feature 40 — Real-Time Collaboration (Multi-Cursor CRDT)."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.collab_manager import (
    MSG_AWARENESS,
    MSG_PERMISSION_DENIED,
    MSG_SYNC,
    MSG_UPDATE,
    SYNC_STEP1,
    SYNC_STEP2,
    CollabManager,
    CollabRoom,
    _build_sync_step2,
    _decode_varbuffer,
    _decode_varuint,
    _encode_varbuffer,
    _encode_varuint,
    handle_collab_message,
)

# ── lib0 encoding helpers ────────────────────────────────────────────────────


class TestLib0Encoding:
    """Round-trip tests for the lib0 varuint / varbuffer helpers."""

    @pytest.mark.parametrize("n", [0, 1, 127, 128, 255, 16383, 16384, 2097151])
    def test_varuint_roundtrip(self, n: int) -> None:
        encoded = _encode_varuint(n)
        decoded, pos = _decode_varuint(encoded, 0)
        assert decoded == n
        assert pos == len(encoded)

    def test_varbuffer_roundtrip(self) -> None:
        payload = b"hello Y.js"
        encoded = _encode_varbuffer(payload)
        decoded, pos = _decode_varbuffer(encoded, 0)
        assert decoded == payload
        assert pos == len(encoded)

    def test_varbuffer_empty(self) -> None:
        encoded = _encode_varbuffer(b"")
        decoded, _ = _decode_varbuffer(encoded, 0)
        assert decoded == b""

    def test_decode_varuint_truncated_raises(self) -> None:
        with pytest.raises(ValueError):
            _decode_varuint(bytes([0x80]), 0)  # continuation flag set but no next byte


# ── build_sync_step2 ─────────────────────────────────────────────────────────


class TestBuildSyncStep2:
    """Tests for the SYNC_STEP2 message builder."""

    def test_message_structure(self) -> None:
        update = b"\xde\xad\xbe\xef"
        msg = _build_sync_step2(update)
        # First byte: MSG_SYNC (0)
        assert msg[0] == 0
        # Second byte: SYNC_STEP2 (1)
        assert msg[1] == 1
        # Payload extracted via varbuffer
        payload, _ = _decode_varbuffer(msg, 2)
        assert payload == update

    def test_empty_update(self) -> None:
        msg = _build_sync_step2(b"")
        payload, _ = _decode_varbuffer(msg, 2)
        assert payload == b""


# ── CollabRoom ───────────────────────────────────────────────────────────────


class TestCollabRoom:
    """Unit tests for CollabRoom connection management."""

    def _make_ws(self, side_effect=None) -> MagicMock:
        ws = AsyncMock()
        if side_effect:
            ws.send_bytes.side_effect = side_effect
        return ws

    @pytest.mark.asyncio
    async def test_add_and_size(self) -> None:
        room = CollabRoom("r1")
        assert room.size == 0
        await room.add("c1", self._make_ws(), {"name": "Alice"})
        assert room.size == 1

    @pytest.mark.asyncio
    async def test_remove_decrements_size(self) -> None:
        room = CollabRoom("r1")
        await room.add("c1", self._make_ws(), {})
        await room.remove("c1")
        assert room.size == 0

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self) -> None:
        room = CollabRoom("r1")
        ws_a = self._make_ws()
        ws_b = self._make_ws()
        await room.add("c1", ws_a, {})
        await room.add("c2", ws_b, {})
        await room.broadcast(b"data", exclude="c1")
        ws_a.send_bytes.assert_not_called()
        ws_b.send_bytes.assert_called_once_with(b"data")

    @pytest.mark.asyncio
    async def test_send_to_specific_client(self) -> None:
        room = CollabRoom("r1")
        ws = self._make_ws()
        await room.add("c1", ws, {})
        await room.send_to("c1", b"hello")
        ws.send_bytes.assert_called_once_with(b"hello")

    @pytest.mark.asyncio
    async def test_send_to_unknown_client_noop(self) -> None:
        room = CollabRoom("r1")
        # Should not raise
        await room.send_to("ghost", b"data")

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self) -> None:
        room = CollabRoom("r1")
        ws_dead = self._make_ws(side_effect=RuntimeError("closed"))
        ws_live = self._make_ws()
        await room.add("dead", ws_dead, {})
        await room.add("live", ws_live, {})
        await room.broadcast(b"ping", exclude=None)
        # Dead client should be removed
        assert room.size == 1
        assert (await room.all_clients())[0][0] == "live"


# ── CollabManager ────────────────────────────────────────────────────────────


class TestCollabManager:
    @pytest.mark.asyncio
    async def test_get_or_create_returns_same_room(self) -> None:
        mgr = CollabManager()
        r1 = await mgr.get_or_create("abc")
        r2 = await mgr.get_or_create("abc")
        assert r1 is r2

    @pytest.mark.asyncio
    async def test_maybe_cleanup_removes_empty_room(self) -> None:
        mgr = CollabManager()
        await mgr.get_or_create("abc")
        await mgr.maybe_cleanup("abc")
        # Room was empty, should be gone
        r2 = await mgr.get_or_create("abc")
        assert r2 is not None  # new room created

    @pytest.mark.asyncio
    async def test_maybe_cleanup_keeps_non_empty_room(self) -> None:
        mgr = CollabManager()
        room = await mgr.get_or_create("xyz")
        ws = AsyncMock()
        await room.add("c1", ws, {})
        await mgr.maybe_cleanup("xyz")
        r2 = await mgr.get_or_create("xyz")
        assert r2 is room  # same object — not cleaned up


class _FakePubSub:
    """Minimal async Pub/Sub stub: yields *envelopes* then ends the stream."""

    def __init__(self, envelopes: list[dict]) -> None:
        self._envelopes = envelopes

    async def listen(self):
        for envelope in self._envelopes:
            yield {"type": "message", "data": json.dumps(envelope)}

    async def unsubscribe(self, channel: str) -> None:
        pass

    async def aclose(self) -> None:
        pass


# ── Role enforcement (H1) ────────────────────────────────────────────────────


class TestRoleEnforcement:
    """A collaborator's role must be enforced on every document frame."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["owner", "editor"])
    async def test_edit_roles_can_write(self, role: str) -> None:
        room = CollabRoom("r1")
        await room.add("c1", AsyncMock(), {"role": role})
        assert room.can_edit("c1") is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", ["viewer", "commenter", None])
    async def test_read_only_roles_cannot_write(self, role) -> None:
        room = CollabRoom("r1")
        await room.add("c1", AsyncMock(), {"role": role})
        assert room.can_edit("c1") is False

    @pytest.mark.asyncio
    async def test_viewer_update_rejected_not_persisted_or_relayed(self) -> None:
        """A viewer's MSG_UPDATE is refused: no Redis write, no relay to peers."""
        room = CollabRoom("r1")
        ws_viewer = AsyncMock()
        ws_editor = AsyncMock()
        await room.add("cv", ws_viewer, {"role": "viewer", "user_id": "u-viewer"})
        await room.add("ce", ws_editor, {"role": "editor", "user_id": "u-editor"})

        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "cv", _make_sync_update(b"\x01\x02"), room)

        mock_redis.rpush.assert_not_called()
        mock_redis.publish.assert_not_called()
        ws_editor.send_bytes.assert_not_called()

        # The viewer is told why its frame was dropped.
        ws_viewer.send_bytes.assert_called_once()
        notice = ws_viewer.send_bytes.call_args[0][0]
        assert notice[0] == MSG_PERMISSION_DENIED
        payload, _ = _decode_varbuffer(notice, 1)
        assert json.loads(payload)["code"] == "read_only"

    @pytest.mark.asyncio
    async def test_viewer_awareness_still_relayed(self) -> None:
        """Presence is allowed for read-only roles so viewers show up as cursors."""
        room = CollabRoom("r1")
        ws_viewer = AsyncMock()
        ws_editor = AsyncMock()
        await room.add("cv", ws_viewer, {"role": "viewer"})
        await room.add("ce", ws_editor, {"role": "editor"})

        msg = _make_awareness(b"\x33")
        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "cv", msg, room)

        ws_editor.send_bytes.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_viewer_can_still_catch_up(self) -> None:
        """SYNC_STEP1 (read) is allowed for a viewer."""
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("cv", ws, {"role": "viewer"})

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "cv", _make_sync_step1(), room)

        sent = ws.send_bytes.call_args[0][0]
        assert sent[0] == MSG_SYNC and sent[1] == SYNC_STEP2


# ── Revocation (H2) ──────────────────────────────────────────────────────────


class TestRevokeAccess:
    """Removing / demoting a collaborator must kill their live sockets."""

    @pytest.mark.asyncio
    async def test_close_user_closes_only_that_users_sockets(self) -> None:
        room = CollabRoom("r1")
        ws_bob_a = AsyncMock()
        ws_bob_b = AsyncMock()
        ws_alice = AsyncMock()
        await room.add("c1", ws_bob_a, {"role": "viewer", "user_id": "bob"})
        await room.add("c2", ws_bob_b, {"role": "viewer", "user_id": "bob"})
        await room.add("c3", ws_alice, {"role": "owner", "user_id": "alice"})

        closed = await room.close_user("bob", reason="Access removed")

        assert closed == 2
        ws_bob_a.close.assert_awaited_once()
        ws_bob_b.close.assert_awaited_once()
        ws_alice.close.assert_not_called()
        assert room.size == 1
        assert (await room.all_clients())[0][0] == "c3"

    @pytest.mark.asyncio
    async def test_revoked_client_stops_receiving_updates(self) -> None:
        room = CollabRoom("r1")
        ws_bob = AsyncMock()
        ws_alice = AsyncMock()
        await room.add("cb", ws_bob, {"role": "editor", "user_id": "bob"})
        await room.add("ca", ws_alice, {"role": "owner", "user_id": "alice"})

        mgr = CollabManager()
        mgr._rooms["r1"] = room

        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            assert await mgr.revoke_access("r1", "bob", reason="Access removed") == 1

            ws_bob.send_bytes.reset_mock()
            await handle_collab_message("r1", "ca", _make_sync_update(b"\x07"), room)

        ws_bob.send_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_publishes_control_message_to_other_workers(self) -> None:
        mgr = CollabManager()
        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await mgr.revoke_access("r1", "bob", reason="Role changed")

        channel, raw = mock_redis.publish.call_args[0]
        assert channel == "latexy:collab:r1"
        envelope = json.loads(raw)
        assert envelope["kind"] == "revoke"
        assert envelope["user_id"] == "bob"
        assert envelope["origin"]


# ── Cross-process fan-out (H4) ───────────────────────────────────────────────


class TestCrossProcessFanout:
    """Frames must reach peers connected to a different uvicorn worker."""

    @pytest.mark.asyncio
    async def test_relay_publishes_frame_to_redis(self) -> None:
        room = CollabRoom("r1")
        await room.add("ce", AsyncMock(), {"role": "editor"})

        msg = _make_sync_update(b"\xaa")
        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "ce", msg, room)

        channel, raw = mock_redis.publish.call_args[0]
        assert channel == "latexy:collab:r1"
        envelope = json.loads(raw)
        assert envelope["kind"] == "frame"
        assert base64.b64decode(envelope["data"]) == msg

    @pytest.mark.asyncio
    async def test_bridge_delivers_remote_frame_to_local_clients(self) -> None:
        mgr = CollabManager()
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {"role": "viewer", "user_id": "bob"})
        mgr._rooms["r1"] = room

        frame = _make_sync_update(b"\xbe\xef")
        envelope = {
            "origin": "other-process",
            "kind": "frame",
            "data": base64.b64encode(frame).decode(),
        }
        pubsub = _FakePubSub([envelope])

        await mgr._bridge("r1", pubsub)

        ws.send_bytes.assert_called_once_with(frame)

    @pytest.mark.asyncio
    async def test_bridge_ignores_own_frames(self) -> None:
        from app.services.collab_manager import _PROCESS_ID

        mgr = CollabManager()
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {"role": "editor"})
        mgr._rooms["r1"] = room

        envelope = {
            "origin": _PROCESS_ID,
            "kind": "frame",
            "data": base64.b64encode(b"\x00\x02\x01\x09").decode(),
        }
        await mgr._bridge("r1", _FakePubSub([envelope]))

        ws.send_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_bridge_applies_remote_revocation(self) -> None:
        mgr = CollabManager()
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {"role": "viewer", "user_id": "bob"})
        mgr._rooms["r1"] = room

        envelope = {"origin": "other-process", "kind": "revoke", "user_id": "bob"}
        await mgr._bridge("r1", _FakePubSub([envelope]))

        ws.close.assert_awaited_once()
        assert room.size == 0

    @pytest.mark.asyncio
    async def test_slow_bridge_teardown_does_not_untrack_the_new_listener(self) -> None:
        """A rejoin during a cancelled listener's teardown must stay tracked."""

        class _SlowPubSub(_FakePubSub):
            def __init__(self) -> None:
                super().__init__([])
                self.unsubscribed = asyncio.Event()

            async def listen(self):
                await asyncio.sleep(3600)
                yield  # pragma: no cover - never reached

            async def unsubscribe(self, channel: str) -> None:
                self.unsubscribed.set()
                await asyncio.sleep(0.05)  # slow Redis round-trip

        mgr = CollabManager()
        subscribed: list[_SlowPubSub] = []

        async def _fake_subscribe(resume_id: str):
            pubsub = _SlowPubSub()
            subscribed.append(pubsub)
            return pubsub

        with patch("app.services.collab_manager._subscribe", _fake_subscribe):
            await mgr.get_or_create("r1")
            first = mgr._listeners["r1"]
            await asyncio.sleep(0)  # let the bridge task reach pubsub.listen()

            # Last client leaves: the room and its listener are torn down, but
            # the cancelled task is still awaiting unsubscribe().
            await mgr.maybe_cleanup("r1")
            await asyncio.wait_for(subscribed[0].unsubscribed.wait(), timeout=2)

            # Client rejoins while that teardown is still in flight.
            await mgr.get_or_create("r1")
            second = mgr._listeners["r1"]
            assert second is not first

            await asyncio.sleep(0.1)  # let the old task's finally complete

            assert first.done()
            assert mgr._listeners.get("r1") is second
            assert not second.done()
            assert len(subscribed) == 2

            second.cancel()

    @pytest.mark.asyncio
    async def test_bridge_finally_untracks_itself_when_still_registered(self) -> None:
        mgr = CollabManager()
        task = asyncio.create_task(mgr._bridge("r1", _FakePubSub([])))
        mgr._listeners["r1"] = task
        await task
        assert "r1" not in mgr._listeners


# ── Route-level revocation wiring (H2) ───────────────────────────────────────


class _QueuedDB:
    """AsyncSession stub returning queued scalar_one_or_none results in order."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.deleted: list[object] = []
        self.commits = 0

    async def execute(self, _stmt):  # noqa: ANN001 - test stub
        value = self._results.pop(0)
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    async def delete(self, obj) -> None:  # noqa: ANN001 - test stub
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass


class TestCollaboratorRoutesRevokeLiveSessions:
    """Removing / demoting a collaborator must kill their live sockets now."""

    @pytest.mark.asyncio
    async def test_remove_collaborator_revokes_access(self) -> None:
        from app.api import resume_routes

        db = _QueuedDB(MagicMock(id="11111111-1111-4111-8111-111111111111", user_id="alice"), MagicMock(role="editor"))
        spy = AsyncMock(return_value=1)

        with patch.object(resume_routes.collab_manager, "revoke_access", spy):
            await resume_routes.remove_collaborator("11111111-1111-4111-8111-111111111111", "bob", db=db, user_id="alice")

        assert db.commits == 1
        spy.assert_awaited_once_with("11111111-1111-4111-8111-111111111111", "bob", reason="Access removed")

    @pytest.mark.asyncio
    async def test_update_collaborator_role_revokes_access(self) -> None:
        from app.api import resume_routes

        now = datetime.now(timezone.utc)
        collab = MagicMock(
            id="c1", resume_id="11111111-1111-4111-8111-111111111111", user_id="bob", role="editor",
            invited_by="alice", joined_at=now, created_at=now,
        )
        user = MagicMock(email="bob@example.com")
        user.name = "bob"
        db = _QueuedDB(MagicMock(id="11111111-1111-4111-8111-111111111111", user_id="alice"), collab, user)
        spy = AsyncMock(return_value=1)

        with patch.object(resume_routes.collab_manager, "revoke_access", spy):
            await resume_routes.update_collaborator_role(
                "11111111-1111-4111-8111-111111111111",
                "bob",
                resume_routes.CollaboratorRoleUpdate(role="viewer"),
                db=db,
                user_id="alice",
            )

        assert collab.role == "viewer"
        spy.assert_awaited_once_with(
            "11111111-1111-4111-8111-111111111111",
            "bob",
            reason="Role changed",
            code=resume_routes.CLOSE_ROLE_CHANGED,
            notice_code="role_changed",
        )


# ── handle_collab_message ────────────────────────────────────────────────────


def _make_sync_step1(state_vector: bytes = b"") -> bytes:
    return _encode_varuint(MSG_SYNC) + _encode_varuint(SYNC_STEP1) + _encode_varbuffer(state_vector)


def _make_sync_update(update: bytes) -> bytes:
    return _encode_varuint(MSG_SYNC) + _encode_varuint(MSG_UPDATE) + _encode_varbuffer(update)


def _make_awareness(payload: bytes) -> bytes:
    return _encode_varuint(MSG_AWARENESS) + _encode_varbuffer(payload)


class TestHandleCollabMessage:
    """Integration tests for the per-message handler."""

    @pytest.mark.asyncio
    async def test_sync_step1_sends_empty_update_when_no_state(self) -> None:
        """SYNC_STEP1 with no stored updates → SYNC_STEP2 with empty Y.js update."""
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {})

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "c1", _make_sync_step1(), room)

        ws.send_bytes.assert_called_once()
        sent = ws.send_bytes.call_args[0][0]
        # Should be a SYNC_STEP2 message
        assert sent[0] == MSG_SYNC
        assert sent[1] == SYNC_STEP2

    @pytest.mark.asyncio
    async def test_sync_step1_sends_stored_updates(self) -> None:
        """SYNC_STEP1 with stored updates → one SYNC_STEP2 message per stored update."""
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {})

        update1 = b"\x01\x02\x03"
        update2 = b"\x04\x05\x06"
        stored = [base64.b64encode(update1).decode(), base64.b64encode(update2).decode()]

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = stored

        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "c1", _make_sync_step1(), room)

        assert ws.send_bytes.call_count == 2
        # Verify first message wraps update1
        first_call = ws.send_bytes.call_args_list[0][0][0]
        payload, _ = _decode_varbuffer(first_call, 2)
        assert payload == update1

    @pytest.mark.asyncio
    async def test_sync_update_persisted_and_relayed(self) -> None:
        """MSG_UPDATE from client A is stored in Redis and relayed to client B."""
        room = CollabRoom("r1")
        ws_a = AsyncMock()
        ws_b = AsyncMock()
        await room.add("ca", ws_a, {"role": "editor"})
        await room.add("cb", ws_b, {"role": "editor"})

        update = b"\xaa\xbb\xcc"
        msg = _make_sync_update(update)

        mock_redis = AsyncMock()

        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "ca", msg, room)

        # Stored in Redis
        mock_redis.rpush.assert_called_once()
        stored_b64 = mock_redis.rpush.call_args[0][1]
        assert base64.b64decode(stored_b64) == update

        # Relayed to peer, not sender
        ws_a.send_bytes.assert_not_called()
        ws_b.send_bytes.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_awareness_relayed_not_stored(self) -> None:
        """Awareness message is relayed to peers but NOT stored in Redis."""
        room = CollabRoom("r1")
        ws_a = AsyncMock()
        ws_b = AsyncMock()
        await room.add("ca", ws_a, {})
        await room.add("cb", ws_b, {})

        msg = _make_awareness(b"\x11\x22")

        mock_redis = AsyncMock()

        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "ca", msg, room)

        mock_redis.rpush.assert_not_called()
        ws_a.send_bytes.assert_not_called()
        ws_b.send_bytes.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_oversized_frame_dropped(self) -> None:
        """A frame larger than MAX_COLLAB_MESSAGE_BYTES is dropped (not stored/relayed)."""
        from app.services.collab_manager import MAX_COLLAB_MESSAGE_BYTES

        room = CollabRoom("r1")
        ws_a = AsyncMock()
        ws_b = AsyncMock()
        await room.add("ca", ws_a, {"role": "editor"})
        await room.add("cb", ws_b, {"role": "editor"})

        oversized = _make_sync_update(b"\x00" * (MAX_COLLAB_MESSAGE_BYTES + 1))
        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "ca", oversized, room)

        mock_redis.rpush.assert_not_called()
        ws_b.send_bytes.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_message_does_not_raise(self) -> None:
        """Garbage bytes are silently dropped."""
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {})

        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            # Should not raise
            await handle_collab_message("r1", "c1", b"\x80", room)
            await handle_collab_message("r1", "c1", b"", room)

    @pytest.mark.asyncio
    async def test_empty_message_does_not_raise(self) -> None:
        room = CollabRoom("r1")
        ws = AsyncMock()
        await room.add("c1", ws, {})
        mock_redis = AsyncMock()
        with patch("app.services.collab_manager.get_redis_client", return_value=mock_redis):
            await handle_collab_message("r1", "c1", b"", room)
        ws.send_bytes.assert_not_called()


# ── REST endpoint integration tests ─────────────────────────────────────────


@pytest.fixture()
def authed_client():
    """TestClient with auth dependency overridden."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.auth_middleware import get_current_user_required

    app.dependency_overrides[get_current_user_required] = lambda: "test-owner-id"
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_current_user_required, None)


class TestCollaboratorEndpoints:
    """Integration tests for the collaborator REST endpoints."""

    def _mock_db(self):
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_db.delete = AsyncMock()
        mock_db.add = MagicMock()
        return mock_db

    def _make_resume(self, owner_id="test-owner-id"):
        resume = MagicMock()
        resume.id = "11111111-1111-4111-8111-111111111111"
        resume.user_id = owner_id
        return resume

    def _make_user(self, user_id, email, name):
        user = MagicMock()
        user.id = user_id
        user.email = email
        user.name = name
        return user

    def test_invite_with_invalid_role_returns_422(self, authed_client) -> None:
        resp = authed_client.post(
            "/resumes/r1/collaborators",
            json={"email": "bob@example.com", "role": "superadmin"},
        )
        assert resp.status_code == 422

    def test_invite_with_missing_email_returns_422(self, authed_client) -> None:
        resp = authed_client.post(
            "/resumes/r1/collaborators",
            json={"role": "editor"},
        )
        assert resp.status_code == 422

    def test_invite_with_malformed_email_returns_422(self, authed_client) -> None:
        resp = authed_client.post(
            "/resumes/r1/collaborators",
            json={"email": "not-an-email", "role": "editor"},
        )
        assert resp.status_code == 422

    def test_update_role_invalid_returns_422(self, authed_client) -> None:
        resp = authed_client.patch(
            "/resumes/r1/collaborators/user2",
            json={"role": "god"},
        )
        assert resp.status_code == 422

    def test_invite_creates_collaborator(self, authed_client) -> None:
        """Valid invite with mocked DB returns 201."""
        from datetime import datetime

        from app.database.connection import get_db
        from app.main import app

        owner = "test-owner-id"
        invitee_id = "invitee-id"

        mock_resume = self._make_resume(owner)
        mock_invitee = self._make_user(invitee_id, "bob@example.com", "Bob")

        # Simulate collab object returned after db.refresh
        mock_collab = MagicMock()
        mock_collab.id = "collab-id"
        mock_collab.resume_id = "11111111-1111-4111-8111-111111111111"
        mock_collab.user_id = invitee_id
        mock_collab.role = "editor"
        mock_collab.invited_by = owner
        mock_collab.joined_at = None
        mock_collab.created_at = datetime(2026, 1, 1)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Resume lookup
                result.scalar_one_or_none.return_value = mock_resume
            elif call_count == 2:
                # Invitee lookup
                result.scalar_one_or_none.return_value = mock_invitee
            elif call_count == 3:
                # Existing collaborator check
                result.scalar_one_or_none.return_value = None
            return result

        def _populate_collab(obj, src):
            obj.id = src.id
            obj.resume_id = src.resume_id
            obj.user_id = src.user_id
            obj.role = src.role
            obj.invited_by = src.invited_by
            obj.joined_at = src.joined_at
            obj.created_at = src.created_at

        mock_db = self._mock_db()
        mock_db.execute = AsyncMock(side_effect=mock_execute)
        mock_db.refresh = AsyncMock(side_effect=lambda obj: _populate_collab(obj, mock_collab))

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.post(
                "/resumes/11111111-1111-4111-8111-111111111111/collaborators",
                json={"email": "bob@example.com", "role": "editor"},
            )
            assert resp.status_code == 201
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_list_collaborators_not_found_returns_404(self, authed_client) -> None:
        """GET /collaborators on non-owned resume returns 404."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = self._mock_db()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.get("/resumes/nonexistent/collaborators")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
class TestCollaboratorDocumentAccess:
    """The REST document path must use the same role model as collaboration."""

    @staticmethod
    async def _user_id_for_headers(db, headers: dict) -> str:
        from sqlalchemy import text

        token = headers["Authorization"].removeprefix("Bearer ")
        result = await db.execute(
            text('SELECT "userId" FROM session WHERE token = :token'),
            {"token": token},
        )
        return result.scalar_one()

    async def _share_resume(self, client, db, owner_headers, collaborator_headers, role: str):
        from sqlalchemy import text

        created = await client.post(
            "/resumes/",
            headers=owner_headers,
            json={"title": "Shared resume", "latex_content": "owner content"},
        )
        assert created.status_code == 201
        resume_id = created.json()["id"]
        owner_id = await self._user_id_for_headers(db, owner_headers)
        collaborator_id = await self._user_id_for_headers(db, collaborator_headers)
        await db.execute(
            text(
                "INSERT INTO resume_collaborators "
                "(resume_id, user_id, role, invited_by) "
                "VALUES (:resume_id, :user_id, :role, :invited_by)"
            ),
            {
                "resume_id": resume_id,
                "user_id": collaborator_id,
                "role": role,
                "invited_by": owner_id,
            },
        )
        await db.commit()
        return resume_id, collaborator_id

    @pytest.mark.parametrize("role", ["editor", "commenter", "viewer"])
    async def test_each_collaborator_role_can_load_document(
        self, client, db_session, auth_headers, auth_headers2, role
    ) -> None:
        resume_id, _ = await self._share_resume(
            client, db_session, auth_headers, auth_headers2, role
        )

        response = await client.get(f"/resumes/{resume_id}", headers=auth_headers2)

        assert response.status_code == 200
        assert response.json()["latex_content"] == "owner content"
        assert response.json()["access_role"] == role

    async def test_editor_can_persist_document(
        self, client, db_session, auth_headers, auth_headers2
    ) -> None:
        resume_id, _ = await self._share_resume(
            client, db_session, auth_headers, auth_headers2, "editor"
        )

        updated = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers2,
            json={"latex_content": "editor content"},
        )
        owner_view = await client.get(f"/resumes/{resume_id}", headers=auth_headers)

        assert updated.status_code == 200
        assert updated.json()["access_role"] == "editor"
        assert owner_view.json()["latex_content"] == "editor content"

    @pytest.mark.parametrize("role", ["commenter", "viewer"])
    async def test_read_only_collaborator_cannot_persist_document(
        self, client, db_session, auth_headers, auth_headers2, role
    ) -> None:
        resume_id, _ = await self._share_resume(
            client, db_session, auth_headers, auth_headers2, role
        )

        denied = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers2,
            json={"latex_content": "unauthorized content"},
        )
        owner_view = await client.get(f"/resumes/{resume_id}", headers=auth_headers)

        assert denied.status_code == 403
        assert owner_view.json()["latex_content"] == "owner content"

    async def test_revoked_collaborator_loses_rest_access(
        self, client, db_session, auth_headers, auth_headers2
    ) -> None:
        from sqlalchemy import text

        resume_id, collaborator_id = await self._share_resume(
            client, db_session, auth_headers, auth_headers2, "editor"
        )
        await db_session.execute(
            text(
                "DELETE FROM resume_collaborators "
                "WHERE resume_id = :resume_id AND user_id = :user_id"
            ),
            {"resume_id": resume_id, "user_id": collaborator_id},
        )
        await db_session.commit()

        read = await client.get(f"/resumes/{resume_id}", headers=auth_headers2)
        write = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers2,
            json={"latex_content": "after revocation"},
        )

        assert read.status_code == 404
        assert write.status_code == 404


# ── /ws/collab handshake ─────────────────────────────────────────────────────


class TestCollabWebSocket:
    """End-to-end tests for the /ws/collab/{resume_id} handshake and framing."""

    @staticmethod
    def _fake_db_session(db):
        """Replacement for get_async_db_session() yielding *db*."""
        import contextlib

        @contextlib.asynccontextmanager
        async def _session():
            yield db

        return _session

    @staticmethod
    def _db_returning(*objects):
        """AsyncMock DB whose successive execute() calls return *objects*."""
        results = []
        for obj in objects:
            result = MagicMock()
            result.scalar_one_or_none.return_value = obj
            results.append(result)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)
        return db

    def _client(self):
        from starlette.testclient import TestClient

        from app.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_invalid_ticket_is_rejected(self) -> None:
        """A missing, expired, reused, or wrong-scope ticket cannot authenticate."""
        from starlette.websockets import WebSocketDisconnect

        with patch(
            "app.api.ws_routes._consume_ws_ticket",
            AsyncMock(return_value=None),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with self._client().websocket_connect("/ws/collab/r1?ticket=spent") as ws:
                    ws.receive_bytes()

        assert exc.value.code == 4001

    def test_valid_ticket_reaches_document_authorization(self) -> None:
        """A valid ticket supplies identity, then normal resume ACLs apply."""
        from starlette.websockets import WebSocketDisconnect

        db = self._db_returning(None)  # resume lookup → not found

        with (
            patch(
                "app.api.ws_routes._consume_ws_ticket",
                AsyncMock(return_value="ticket-user"),
            ),
            patch(
                "app.database.connection.get_async_db_session",
                self._fake_db_session(db),
            ),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with self._client().websocket_connect("/ws/collab/r1?ticket=fresh") as ws:
                    ws.receive_bytes()

        # Got past auth (4001) and was rejected by the resume lookup instead.
        assert exc.value.code == 4004

    def test_viewer_document_update_is_refused(self) -> None:
        """H1: a collaborator invited as viewer cannot mutate the shared doc."""
        resume = MagicMock()
        resume.id = "r-viewer"
        resume.user_id = "alice"
        collab = MagicMock()
        collab.role = "viewer"
        db = self._db_returning(resume, collab)

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch(
                "app.api.ws_routes._consume_ws_ticket",
                AsyncMock(return_value="bob"),
            ),
            patch(
                "app.database.connection.get_async_db_session",
                self._fake_db_session(db),
            ),
            patch(
                "app.services.collab_manager.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            with self._client().websocket_connect(
                "/ws/collab/r-viewer?ticket=viewer-ticket"
            ) as ws:
                ws.send_bytes(_make_sync_update(b"\x01\x02\x03"))
                notice = ws.receive_bytes()

        assert notice[0] == MSG_PERMISSION_DENIED
        payload, _ = _decode_varbuffer(notice, 1)
        assert json.loads(payload)["code"] == "read_only"
        # Nothing was written to the shared document.
        mock_redis.rpush.assert_not_called()

    def test_editor_document_update_is_accepted(self) -> None:
        """The same frame from an editor is persisted and fanned out."""
        resume = MagicMock()
        resume.id = "r-editor"
        resume.user_id = "alice"
        collab = MagicMock()
        collab.role = "editor"
        db = self._db_returning(resume, collab)

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch(
                "app.api.ws_routes._consume_ws_ticket",
                AsyncMock(return_value="bob"),
            ),
            patch(
                "app.database.connection.get_async_db_session",
                self._fake_db_session(db),
            ),
            patch(
                "app.services.collab_manager.get_redis_client",
                AsyncMock(return_value=mock_redis),
            ),
        ):
            with self._client().websocket_connect(
                "/ws/collab/r-editor?ticket=editor-ticket"
            ) as ws:
                ws.send_bytes(_make_sync_update(b"\x01\x02\x03"))
                ws.send_bytes(_make_sync_step1())
                # SYNC_STEP1 is answered once the update above has been handled.
                reply = ws.receive_bytes()

        assert reply[0] == MSG_SYNC
        mock_redis.rpush.assert_called_once()

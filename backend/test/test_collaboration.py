"""Tests for Feature 40 — Real-Time Collaboration (Multi-Cursor CRDT)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.collab_manager import (
    MSG_AWARENESS,
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
        assert room.all_clients()[0][0] == "live"


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
        await room.add("ca", ws_a, {})
        await room.add("cb", ws_b, {})

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
        resume.id = "test-resume-id"
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
        mock_collab.resume_id = "test-resume-id"
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
                "/resumes/test-resume-id/collaborators",
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

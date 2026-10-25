"""Live ACL checks must distinguish reauthorization from actual access loss."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import resume_routes, ws_routes
from app.services import collab_manager as collab

RESUME_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def live_acl(monkeypatch):
    state = SimpleNamespace(owner="alice", role="editor", capability=True, error=None)
    db = AsyncMock()

    async def scalar(statement):
        if state.error:
            raise state.error
        column = next(iter(statement.selected_columns))
        return state.owner if column.name == "user_id" else state.role

    db.scalar.side_effect = scalar

    @asynccontextmanager
    async def session():
        yield db

    capability = AsyncMock(side_effect=lambda *_: state.capability)
    monkeypatch.setattr("app.database.connection.get_async_db_session", session)
    monkeypatch.setattr(ws_routes, "_collab_capabilities_available", capability)
    return state, db, capability


async def admitted_room(role="editor", user_id="bob"):
    room = collab.CollabRoom(RESUME_ID)
    socket = AsyncMock()
    await room.add(
        "actor", socket, {"user_id": user_id, "role": role},
        access_check=ws_routes._collab_live_access_callback(RESUME_ID, user_id, "alice", role),
    )
    return room, socket


def assert_role_changed(socket):
    socket.close.assert_awaited_once_with(code=4005, reason="Role changed")
    socket.send_bytes.assert_awaited_once()
    frame = socket.send_bytes.await_args.args[0]
    assert frame[0] == collab.MSG_PERMISSION_DENIED
    payload, end = collab._decode_varbuffer(frame, 1)
    assert end == len(frame)
    assert payload == b'{"code": "role_changed", "message": "Role changed"}'


@pytest.mark.parametrize("old_role,new_role", [
    ("editor", "commenter"), ("editor", "viewer"), ("commenter", "editor"),
    ("commenter", "viewer"), ("viewer", "commenter"), ("viewer", "editor"),
])
@pytest.mark.parametrize("delivery", ["update", "sync", "awareness", "chat", "send_to", "broadcast", "bounded_broadcast"])
async def test_stale_role_refuses_every_frame_and_requests_reauthorization(live_acl, monkeypatch, old_role, new_role, delivery):
    state, _, _ = live_acl
    state.role = old_role
    room, socket = await admitted_room(old_role)
    assert await room.has_access("actor") is True
    state.role = new_role
    persist = AsyncMock()
    relay = AsyncMock()
    monkeypatch.setattr(collab, "_persist_update", persist)
    monkeypatch.setattr(room, "relay", relay)
    frames = {
        "update": b"\x00\x02\x01x",
        "sync": b"\x00\x00\x00",
        "awareness": b"\x01\x01x",
        "chat": collab._encode_varuint(collab.MSG_CHAT) + collab._encode_varbuffer(b'{"type":"chat","text":"stale"}'),
    }
    if delivery in frames:
        await collab.handle_collab_message(RESUME_ID, "actor", frames[delivery], room)
    elif delivery == "send_to":
        await room.send_to("actor", b"private source")
    else:
        await room.broadcast(b"private source", timeout=1 if delivery == "bounded_broadcast" else None)
    assert_role_changed(socket)
    assert room.size == 0
    assert not await room.has_access("actor")
    persist.assert_not_awaited()
    relay.assert_not_awaited()


@pytest.mark.parametrize("failure", ["removed", "invalid_role", "missing_resume", "owner_changed", "capability", "lookup_error", "capability_error", "invalid_admitted_role", "owner_role_mismatch"])
async def test_real_access_loss_is_terminal_even_when_role_changes(live_acl, failure):
    state, _, capability = live_acl
    state.role = "viewer"
    role, user_id = "editor", "bob"
    if failure == "removed":
        state.role = None
    elif failure == "invalid_role":
        state.role = "admin"
    elif failure == "missing_resume":
        state.owner = None
    elif failure == "owner_changed":
        state.owner = "charlie"
    elif failure == "capability":
        state.capability = False
    elif failure == "lookup_error":
        state.error = RuntimeError("unavailable")
    elif failure == "capability_error":
        capability.side_effect = RuntimeError("unavailable")
    elif failure == "invalid_admitted_role":
        role = "admin"
    elif failure == "owner_role_mismatch":
        user_id = "alice"
    room, socket = await admitted_room(role, user_id)
    await room.send_to("actor", b"private source")
    socket.send_bytes.assert_not_awaited()
    socket.close.assert_awaited_once_with(code=4003, reason="Collaboration is unavailable")
    assert room.size == 0
    capability.assert_awaited_once_with(user_id, "alice")


@pytest.mark.parametrize("role,user_id", [("editor", "bob"), ("commenter", "bob"), ("viewer", "bob"), ("owner", "alice")])
async def test_unchanged_authorized_role_keeps_live_socket(live_acl, role, user_id):
    state, _, _ = live_acl
    state.role = role
    room, socket = await admitted_room(role, user_id)
    await room.send_to("actor", b"authorized source")
    socket.send_bytes.assert_awaited_once_with(b"authorized source")
    socket.close.assert_not_awaited()
    assert room.size == 1


async def test_frame_check_wins_commit_to_notification_race_then_new_session_is_revoked(live_acl, monkeypatch):
    """Run the actual role route, interrupting refresh after its commit.

    This puts the real live callback ahead of revoke_access without timers,
    sleeps, or a mocked access decision, as on separate production workers.
    """
    state, _, _ = live_acl
    state.role = "viewer"
    room, socket = await admitted_room("viewer")
    manager = collab.CollabManager()
    manager._rooms[RESUME_ID] = room
    monkeypatch.setattr(resume_routes, "collab_manager", manager)
    publish = AsyncMock()
    persist = AsyncMock()
    monkeypatch.setattr(collab, "_publish", publish)
    monkeypatch.setattr(collab, "_persist_update", persist)
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(id="c1", resume_id=RESUME_ID, user_id="bob", role="viewer", invited_by="alice", joined_at=now, created_at=now)
    db = AsyncMock()
    results = [SimpleNamespace(user_id="alice"), row, SimpleNamespace(name="Bob", email="bob@example.test")]
    db.execute.side_effect = lambda _: MagicMock(scalar_one_or_none=MagicMock(return_value=results.pop(0)))
    order = []

    async def commit():
        state.role = row.role
        order.append("committed")

    async def refresh(_):
        assert order == ["committed"]
        await collab.handle_collab_message(RESUME_ID, "actor", b"\x00\x02\x01x", room)
        assert_role_changed(socket)
        assert room.size == 0
        publish.assert_not_awaited()
        persist.assert_not_awaited()
        order.append("live_check_closed")

    db.commit.side_effect = commit
    db.refresh.side_effect = refresh
    response = await resume_routes.update_collaborator_role(
        RESUME_ID, "bob", resume_routes.CollaboratorRoleUpdate(role="editor"), db=db, user_id="alice",
    )
    assert response.role == "editor"
    assert order == ["committed", "live_check_closed"]
    assert_role_changed(socket)
    publish.assert_awaited_once()
    assert publish.await_args.args[1]["code"] == 4005
    assert publish.await_args.args[1]["notice_code"] == "role_changed"

    # A fresh, newly authorized provider works after the role-change close.
    replacement = AsyncMock()
    await room.add("replacement", replacement, {"user_id": "bob", "role": "editor"},
                   access_check=ws_routes._collab_live_access_callback(RESUME_ID, "bob", "alice", "editor"))
    await room.send_to("replacement", b"fresh source")
    replacement.send_bytes.assert_awaited_once_with(b"fresh source")
    replacement.reset_mock()
    state.role = None
    await collab.handle_collab_message(RESUME_ID, "replacement", b"\x00\x02\x01x", room)
    replacement.close.assert_awaited_once_with(code=4003, reason="Collaboration is unavailable")
    replacement.send_bytes.assert_not_awaited()
    persist.assert_not_awaited()
    assert room.size == 0

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.api.team_routes import (
    TeamInviteRequest,
    _require_same_origin_accept,
    invite_team_member,
    join_team_seat,
    preview_team_seat,
    router,
)


def _result(*, row=None, scalars=None):
    result = MagicMock()
    result.one_or_none.return_value = row
    result.scalar_one_or_none.return_value = row
    result.scalars.return_value.all.return_value = scalars or []
    return result


def _owner():
    return SimpleNamespace(
        email="owner@example.com",
        name="Owner",
        subscription_plan="team",
    )


def _seat(status="invited"):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        member_email="member@example.com",
        member_user_id=None,
        status=status,
        invited_at="now",
        joined_at=None,
    )


def _member_user(plan="free"):
    return SimpleNamespace(email="member@example.com", subscription_plan=plan)


def test_team_invite_normalizes_and_validates_email():
    assert TeamInviteRequest(email=" Member@Example.COM ").email == "member@example.com"
    with pytest.raises(ValidationError):
        TeamInviteRequest(email="not-an-email")


@pytest.mark.asyncio
async def test_redis_failure_rolls_back_before_invite_commit():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(row=_owner()),
            _result(row=None),
            _result(scalars=[]),
        ]
    )
    redis = AsyncMock()
    redis.set.side_effect = RuntimeError("redis unavailable")

    with patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc:
            await invite_team_member(
                TeamInviteRequest(email="member@example.com"),
                user_id="00000000-0000-0000-0000-000000000002",
                db=db,
            )

    assert exc.value.status_code == 503
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_invite_can_be_resent_after_delivery_failure(monkeypatch):
    seat = _seat()
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(row=_owner()),
            _result(row=seat),
        ]
    )
    redis = AsyncMock()
    monkeypatch.setattr("app.api.team_routes.settings.EMAIL_ENABLED", True)

    with (
        patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=redis)),
        patch("app.api.team_routes.email_service.send_email", AsyncMock(return_value=False)),
    ):
        with pytest.raises(HTTPException) as exc:
            await invite_team_member(
                TeamInviteRequest(email="member@example.com"),
                user_id="00000000-0000-0000-0000-000000000002",
                db=db,
            )

    assert exc.value.status_code == 503
    db.commit.assert_awaited_once()
    assert db.execute.await_count == 2  # owner + existing seat; no capacity rejection on resend
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_teammate_cannot_be_reset_by_duplicate_invite():
    seat = _seat(status="active")
    seat.member_user_id = "00000000-0000-0000-0000-000000000003"
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(row=_owner()),
            _result(row=seat),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        await invite_team_member(
            TeamInviteRequest(email="member@example.com"),
            user_id="00000000-0000-0000-0000-000000000002",
            db=db,
        )

    assert exc.value.status_code == 409
    assert seat.status == "active"
    assert seat.member_user_id == "00000000-0000-0000-0000-000000000003"
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_invite_token_state_never_reaches_database():
    db = AsyncMock()
    redis = AsyncMock()
    redis.get.return_value = "corrupt-value-without-delimiter"

    with patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=redis)):
        with pytest.raises(HTTPException) as exc:
            await join_team_seat(
                "token",
                user_id="00000000-0000-0000-0000-000000000002",
                db=db,
            )

    assert exc.value.status_code == 404
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_is_read_only_and_does_not_activate_seat():
    seat = _seat()
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(row=seat),
            _result(row=_member_user()),
        ]
    )
    redis = AsyncMock()
    redis.get.return_value = f"{seat.id}:member@example.com"

    with patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=redis)):
        result = await preview_team_seat(
            "token",
            user_id="00000000-0000-0000-0000-000000000002",
            db=db,
        )

    assert result["success"] is True
    assert seat.status == "invited"
    assert seat.member_user_id is None
    db.commit.assert_not_awaited()
    redis.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_accept_is_post_only_in_route_and_replay_is_idempotent():
    seat = _seat()
    user_id = "00000000-0000-0000-0000-000000000002"
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(row=seat),
            _result(row=_member_user()),
            MagicMock(),
        ]
    )
    redis = AsyncMock()
    redis.get.return_value = f"{seat.id}:member@example.com"

    with patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=redis)):
        first = await join_team_seat("token", user_id=user_id, db=db)

    assert first["success"] is True
    assert seat.status == "active"
    assert seat.member_user_id == user_id
    db.commit.assert_awaited_once()

    replay_db = AsyncMock()
    replay_db.execute = AsyncMock(
        side_effect=[
            _result(row=seat),
            _result(row=_member_user("team_member")),
        ]
    )
    replay_redis = AsyncMock()
    replay_redis.get.return_value = f"{seat.id}:member@example.com"
    with patch("app.api.team_routes.get_redis_cache_client", AsyncMock(return_value=replay_redis)):
        replay = await join_team_seat("token", user_id=user_id, db=replay_db)

    assert replay["success"] is True
    assert "already active" in replay["message"]
    replay_db.commit.assert_not_awaited()
    replay_redis.delete.assert_awaited_once_with("team_invite:token")


def test_invitation_preview_and_accept_have_separate_http_semantics():
    methods = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
        if route.path == "/team/join/{token}"
    }
    assert ("/team/join/{token}", "GET") in methods
    assert ("/team/join/{token}", "POST") in methods


@pytest.mark.asyncio
async def test_cookie_authenticated_accept_rejects_cross_origin_post():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("latexy.example", 443),
            "path": "/team/join/token",
            "raw_path": b"/team/join/token",
            "query_string": b"",
            "headers": [
                (b"host", b"latexy.example"),
                (b"cookie", b"better-auth.session_token=session"),
                (b"origin", b"https://attacker.example"),
            ],
        }
    )
    with pytest.raises(HTTPException) as exc:
        await _require_same_origin_accept(request)
    assert exc.value.status_code == 403

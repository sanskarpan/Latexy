"""F04 admission and owner recovery for collaborator role changes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import router
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.services.entitlement_service import entitlement_service

OWNER = "11111111-1111-4111-8111-111111111111"
ACTOR = "22222222-2222-4222-8222-222222222222"
RESUME_ID = "33333333-3333-4333-8333-333333333333"


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _client_app(db, user_id=OWNER):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optional] = lambda: user_id
    app.dependency_overrides[get_current_user_required] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: db
    return app


def _collaborator(role):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id="collab-id",
        resume_id=RESUME_ID,
        user_id=ACTOR,
        user_name="Collaborator",
        user_email="collaborator@example.test",
        role=role,
        invited_by=OWNER,
        joined_at=now,
        created_at=now,
    )


@pytest.mark.parametrize(
    ("current_role", "new_role"),
    [("editor", "commenter"), ("editor", "viewer"), ("commenter", "viewer")],
)
async def test_role_reductions_are_available_with_f04_off(monkeypatch, current_role, new_role):
    resume = SimpleNamespace(id=RESUME_ID, user_id=OWNER)
    collaborator = _collaborator(current_role)
    user = SimpleNamespace(id=ACTOR, name="Collaborator", email="collaborator@example.test")
    db = AsyncMock()
    db.execute.side_effect = [_result(resume), _result(collaborator), _result(user)]
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    from app.api import resume_routes

    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(resume_routes.collab_manager, "revoke_access", revoke)
    app = _client_app(db)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.patch(
            f"/resumes/{RESUME_ID}/collaborators/{ACTOR}",
            json={"role": new_role},
        )

    assert response.status_code == 200, response.text
    assert response.json()["role"] == new_role
    assert collaborator.role == new_role
    checker.assert_not_awaited()
    db.commit.assert_awaited_once()
    revoke.assert_awaited_once()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", f"/resumes/{RESUME_ID}/collaborators", {"email": "new@example.test", "role": "editor"}),
        ("POST", f"/resumes/{RESUME_ID}/collaborators", {"email": "new@example.test", "role": "commenter"}),
        ("PATCH", f"/resumes/{RESUME_ID}/collaborators/{ACTOR}", {"role": "editor"}),
    ],
)
async def test_f04_parent_gate_blocks_invites_and_role_upgrades(monkeypatch, method, path, body):
    db = AsyncMock()
    checker = AsyncMock(side_effect=lambda key, **kwargs: key != "f04")
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    app = _client_app(db)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.request(method, path, json=body)

    assert response.status_code == 403, response.text
    assert "f04" in response.text
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_leaf_gate_denies_stale_viewer_to_commenter_upgrade_with_f04_off(monkeypatch):
    """The database role, not a possibly stale client row, decides if commenter grants writes."""
    resume = SimpleNamespace(id=RESUME_ID, user_id=OWNER)
    collaborator = _collaborator("viewer")
    db = AsyncMock()
    db.execute.side_effect = [_result(resume), _result(collaborator)]
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    from app.api import resume_routes

    revoke = AsyncMock(return_value=1)
    monkeypatch.setattr(resume_routes.collab_manager, "revoke_access", revoke)
    app = _client_app(db)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.patch(
            f"/resumes/{RESUME_ID}/collaborators/{ACTOR}",
            json={"role": "commenter"},
        )

    assert response.status_code == 403, response.text
    assert "f04" in response.text
    assert collaborator.role == "viewer"
    checker.assert_awaited_once()
    db.commit.assert_not_awaited()
    revoke.assert_not_awaited()


async def test_non_owner_cannot_use_f04_off_to_change_collaborator_role(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = _result(None)
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    app = _client_app(db, user_id=ACTOR)

    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.patch(
            f"/resumes/{RESUME_ID}/collaborators/{OWNER}",
            json={"role": "viewer"},
        )

    assert response.status_code == 404, response.text
    checker.assert_not_awaited()
    db.commit.assert_not_awaited()

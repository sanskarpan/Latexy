"""Real registered suggestion routes with deterministic, fail-before-write doubles.

No database, queue, provider, or credential is used. These exercise the complete
FastAPI dependency + handler boundary, not just the payload selector.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.suggestion_routes import router
from app.database.connection import get_db
from app.database.models import Resume
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.services.entitlement_service import entitlement_service

ACTOR = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
RESUME = "33333333-3333-4333-8333-333333333333"
SOURCE = "Before Target After"
POST = f"/resumes/{RESUME}/suggestion-decisions"


def body(status="accepted"):
    return dict(suggestion_id="peer:proposal", status=status, expected_content=SOURCE,
                original_text="Target", replacement_text="Changed", prefix="Before ", suffix=" After")


def result(value):
    row = MagicMock()
    row.one_or_none.return_value = value
    row.scalar_one_or_none.return_value = value
    row.scalar_one.return_value = value
    row.scalars.return_value.all.return_value = value
    return row


def decision(status="accepted", content="Before Changed After"):
    return SimpleNamespace(suggestion_id="peer:proposal", status=status, decided_by_role="owner",
                           created_at=datetime.now(timezone.utc), result_content=content)


@pytest.fixture
def boundary(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optional] = lambda: ACTOR
    app.dependency_overrides[get_current_user_required] = lambda: ACTOR
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = AssertionError("Unexpected database access")
    app.dependency_overrides[get_db] = lambda: db
    denied = set()
    checker = AsyncMock(side_effect=lambda key, *, user: key not in denied and (key, user) not in denied)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    return SimpleNamespace(app=app, db=db, denied=denied, checker=checker)


def queue_post(boundary, role="owner", existing=None, after_role=None, count=0):
    owner = ACTOR if role == "owner" else OWNER
    access = (owner, None if role in {"owner", "outsider"} else role)
    after = access if after_role is None else (owner, after_role)
    resume = Resume(id=RESUME, user_id=owner, latex_content=SOURCE,
                    content_source="manual_latex", resume_settings={})
    boundary.db.execute.side_effect = [result(value) for value in
                                      [access, resume, after, existing, count, [], [], []]]

    async def refresh(row):
        row.created_at = datetime.now(timezone.utc)
    boundary.db.refresh.side_effect = refresh
    return resume


async def post(boundary, payload):
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        return await client.post(POST, json=payload)


@pytest.mark.parametrize("denied", [set(), {"f07"}, {"c01"}, {"f07", "c01"}])
@pytest.mark.parametrize("role", ["owner", "editor"])
@pytest.mark.parametrize("status", ["rejected", "conflicted"])
async def test_recovery_decisions_survive_off_and_on_with_acl_intact(boundary, denied, role, status):
    boundary.denied.update(denied)
    resume = queue_post(boundary, role)
    response = await post(boundary, body(status))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    assert response.json()["latex_content"] == ""
    assert resume.latex_content == SOURCE
    row = boundary.db.add.call_args.args[0]
    assert row.status == status and row.result_content == ""
    boundary.db.commit.assert_awaited_once()
    assert all(call.args[0] not in {"f07", "c01"} for call in boundary.checker.await_args_list)
    if role == "editor":
        assert {(call.args[0], call.kwargs["user"]) for call in boundary.checker.await_args_list} == {
            ("f04", ACTOR), ("f04", OWNER),
        }


@pytest.mark.parametrize("key", ["f07", "c01"])
async def test_acceptance_denial_precedes_every_handler_query_and_write(boundary, key):
    boundary.denied.add(key)
    response = await post(boundary, body())
    assert response.status_code == 403 and key in response.text
    boundary.db.execute.assert_not_awaited()
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("role", ["owner", "editor"])
async def test_enabled_acceptance_applies_source_once(boundary, role):
    resume = queue_post(boundary, role)
    response = await post(boundary, body())
    assert response.status_code == 200, response.text
    assert response.json()["latex_content"] == resume.latex_content == "Before Changed After"
    assert response.json()["replayed"] is False
    boundary.db.commit.assert_awaited_once()
    checks = {(call.args[0], call.kwargs["user"]) for call in boundary.checker.await_args_list}
    assert {("f07", ACTOR), ("c01", ACTOR)} <= checks
    if role == "editor":
        assert {("f04", ACTOR), ("f04", OWNER), ("f07", OWNER), ("c01", OWNER)} <= checks


@pytest.mark.parametrize("key", ["f04", "f07", "c01"])
async def test_acceptance_also_requires_document_owner_grants(boundary, key):
    boundary.denied.add((key, OWNER))
    resume = queue_post(boundary, "editor")
    response = await post(boundary, body())
    assert response.status_code == 403 and key in response.text
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("actor", [ACTOR, OWNER])
@pytest.mark.parametrize("status", ["rejected", "conflicted"])
async def test_recovery_cannot_bypass_independent_f04_document_access(boundary, actor, status):
    boundary.denied.update({"f07", "c01", ("f04", actor)})
    resume = queue_post(boundary, "editor")
    response = await post(boundary, body(status))
    assert response.status_code == 403 and "f04" in response.text
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["accepted", "rejected", "conflicted"])
@pytest.mark.parametrize("role", ["viewer", "commenter", "outsider"])
async def test_nonresolvers_cannot_decide_another_actors_proposal(boundary, role, status):
    resume = queue_post(boundary, role)
    response = await post(boundary, body(status))
    assert response.status_code == 403
    assert resume.latex_content == SOURCE
    assert boundary.db.execute.await_count == 1
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["accepted", "rejected", "conflicted"])
async def test_acl_revocation_after_lock_cannot_commit_a_transition(boundary, status):
    resume = queue_post(boundary, "editor", after_role="viewer")
    response = await post(boundary, body(status))
    assert response.status_code == 403
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("key", ["f07", "c01"])
async def test_acceptance_rechecks_owner_grant_after_lock(boundary, key):
    resume = queue_post(boundary)
    responses = list(boundary.db.execute.side_effect)
    async def execute(_query):
        value = responses.pop(0)
        if isinstance(value.scalar_one_or_none.return_value, Resume):
            boundary.denied.add(key)
        return value
    boundary.db.execute.side_effect = execute
    response = await post(boundary, body())
    assert response.status_code == 403 and key in response.text
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("stored", ["accepted", "rejected", "conflicted"])
@pytest.mark.parametrize("requested", ["rejected", "conflicted"])
async def test_first_outcome_cannot_be_changed_by_recovery_payload(boundary, stored, requested):
    boundary.denied.update({"f07", "c01"})
    existing = decision(stored, "Before Changed After" if stored == "accepted" else "")
    resume = queue_post(boundary, existing=existing)
    response = await post(boundary, {**body(requested), "expected_content": "stale source"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == stored and response.json()["replayed"] is True
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("key", ["f07", "c01"])
async def test_accepted_post_retry_remains_admission_gated(boundary, key):
    boundary.denied.add(key)
    response = await post(boundary, body())
    assert response.status_code == 403 and key in response.text
    boundary.db.execute.assert_not_awaited()


@pytest.mark.parametrize("status", ["accepted", "rejected", "conflicted"])
@pytest.mark.parametrize("role", ["owner", "editor", "commenter", "viewer"])
async def test_authenticated_existing_decision_get_survives_f07_and_c01_off(boundary, role, status):
    boundary.denied.update({"f07", "c01"})
    access = (ACTOR, None) if role == "owner" else (OWNER, role)
    boundary.db.execute.side_effect = [result(access), result(decision(status)), result(SOURCE)]
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        response = await client.get(POST + "/peer:proposal")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status and response.json()["replayed"] is True
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()
    assert all(call.args[0] not in {"f07", "c01"} for call in boundary.checker.await_args_list)


@pytest.mark.parametrize("denied_actor", [ACTOR, OWNER])
async def test_existing_get_recovery_still_requires_collaborator_and_owner_f04(boundary, denied_actor):
    boundary.denied.add(("f04", denied_actor))
    boundary.db.execute.side_effect = [result((OWNER, "viewer"))]
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        response = await client.get(POST + "/peer:proposal")
    assert response.status_code == 403 and "f04" in response.text
    assert boundary.db.execute.await_count == 1
    boundary.db.commit.assert_not_awaited()


async def test_outsider_get_does_not_disclose_existing_decision(boundary):
    boundary.db.execute.side_effect = [result((OWNER, None))]
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        response = await client.get(POST + "/peer:proposal")
    assert response.status_code == 404
    assert boundary.db.execute.await_count == 1


@pytest.mark.parametrize("method", ["get", "post"])
async def test_authentication_is_required_for_recovery(boundary, method):
    boundary.app.dependency_overrides[get_current_user_optional] = lambda: None
    boundary.app.dependency_overrides.pop(get_current_user_required)
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        response = await client.request(method, POST + ("/peer:proposal" if method == "get" else ""),
                                        json=body("rejected") if method == "post" else None)
    assert response.status_code == 401, response.text
    boundary.db.execute.assert_not_awaited()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("payload", [{}, {**body("rejected"), "status": "invalid"},
                                     {key: value for key, value in body("conflicted").items() if key != "status"},
                                     {**body("rejected"), "suggestion_id": ""}, None, []])
async def test_invalid_or_missing_payload_never_becomes_recovery_transition(boundary, payload):
    boundary.denied.update({"f07", "c01"})
    response = await post(boundary, payload)
    assert response.status_code == 422, response.text
    boundary.db.execute.assert_not_awaited()
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["rejected", "conflicted"])
async def test_recovery_preserves_cas_and_rate_limit(boundary, status):
    resume = queue_post(boundary)
    response = await post(boundary, {**body(status), "expected_content": "stale"})
    assert response.status_code == 409 and "document_changed" in response.text
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()
    queue_post(boundary, count=100)
    response = await post(boundary, body(status))
    assert response.status_code == 429
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


async def test_malformed_json_cannot_bypass_validation_or_write(boundary):
    boundary.denied.update({"f07", "c01"})
    async with AsyncClient(transport=ASGITransport(app=boundary.app), base_url="http://test") as client:
        response = await client.post(POST, content='{"status":', headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    boundary.db.execute.assert_not_awaited()
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("status", ["accepted", "rejected", "conflicted"])
async def test_missing_resume_never_receives_a_decision(boundary, status):
    boundary.db.execute.side_effect = [result(None)]
    response = await post(boundary, body(status))
    assert response.status_code == 404
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()


@pytest.mark.parametrize("actor", [ACTOR, OWNER])
async def test_recovery_rechecks_f04_after_resume_lock(boundary, actor):
    boundary.denied.update({"f07", "c01"})
    resume = queue_post(boundary, "editor")
    responses = list(boundary.db.execute.side_effect)
    async def execute(_query):
        value = responses.pop(0)
        if isinstance(value.scalar_one_or_none.return_value, Resume):
            boundary.denied.add(("f04", actor))
        return value
    boundary.db.execute.side_effect = execute
    response = await post(boundary, body("rejected"))
    assert response.status_code == 403 and "f04" in response.text
    assert resume.latex_content == SOURCE
    boundary.db.add.assert_not_called()
    boundary.db.commit.assert_not_awaited()

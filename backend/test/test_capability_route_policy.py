"""No-infrastructure regression tests for granular operation enforcement.

Exercise real registered routers with disabled capabilities and fail-on-use
database doubles. No provider, queue, payment, or production mutation is used.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.routes import router
from app.core.feature_registry import get_feature
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.middleware.capability_router import (
    DYNAMIC_ENDPOINTS,
    ROUTE_CAPABILITIES,
    CapabilityRouter,
    _route_gate,
    payload_capabilities,
)
from app.services.entitlement_service import entitlement_service

USER_ID = "11111111-1111-4111-8111-111111111111"


def _routes():
    def walk(current):
        for route in current.routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                yield from walk(route.original_router)

    return {
        (route.endpoint.__module__.rsplit(".", 1)[-1], route.endpoint.__name__): route
        for route in walk(router)
    }


POLICIES = [
    (module, name, key)
    for module, handlers in ROUTE_CAPABILITIES.items()
    for name, keys in handlers.items()
    for key in keys
]


@pytest.fixture
def policy_app(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_optional] = lambda: USER_ID
    app.dependency_overrides[get_current_user_required] = lambda: USER_ID
    db = AsyncMock()
    db.execute.side_effect = AssertionError("Disabled operation reached database")
    db.commit.side_effect = AssertionError("Disabled operation changed database")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(entitlement_service, "has_feature", AsyncMock(return_value=True))
    return app, db


@pytest.mark.parametrize("module,name,key", POLICIES)
async def test_disabled_capability_blocks_every_registered_operation(module, name, key, policy_app):
    app, db = policy_app
    route = _routes()[(module, name)]
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    path = route.path
    for parameter in route.param_convertors:
        path = path.replace("{" + parameter + "}", USER_ID)
    method = next(iter(route.methods))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json={})
    assert response.status_code == 403, (module, name, key, response.text)
    if method != "HEAD":
        assert "feature_disabled" in response.text
        assert key in response.text
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_registered_policy_keys_are_real_and_wiring_survives_router_inclusion():
    routes = _routes()
    pairs = set(DYNAMIC_ENDPOINTS) | {(module, name) for module, name, _ in POLICIES}
    for module, name in pairs:
        route = routes[(module, name)]
        gate = _route_gate(module, name)
        assert sum(dependency.call is gate for dependency in route.dependant.dependencies) == 1
    for _, _, key in POLICIES:
        assert get_feature(key) is not None
        assert get_feature(key).gateable


@pytest.mark.parametrize("job_type,key", [
    ("llm_optimization", "d01"), ("combined", "d01"),
    ("ats_scoring", "d18"), ("auto_fit", "c12"),
])
async def test_multiplexed_jobs_cannot_bypass_disabled_feature(job_type, key, policy_app):
    app, db = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/jobs/submit", json={"job_type": job_type, "latex_content": "content"})
    assert response.status_code == 403
    assert key in response.text
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("fmt,key", [("docx", "h01"), ("json", "h01"), ("svg", "h02")])
async def test_raw_export_has_same_gate_as_saved_export(fmt, key, policy_app):
    app, _ = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/export/content/{fmt}", json={"latex_content": "owned source"})
    assert response.status_code == 403
    assert key in response.text


async def test_source_export_survives_all_product_toggles_off(policy_app):
    app, _ = policy_app
    entitlement_service.has_feature.return_value = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/export/content/tex", json={"latex_content": "owned source"})
    assert response.status_code == 200
    assert response.text == "owned source"


async def test_malformed_multiplexed_input_keeps_validation_error(policy_app):
    app, db = policy_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/jobs/submit", json={"job_type": [], "latex_content": "source"})
    assert response.status_code == 422
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", [
    "/jobs/submit", "/jobs/compile-watermarked", "/ats/score", "/ats/quick-score",
    "/ats/deep-analyze", "/ai/generate-bullets", "/ai/generate-summary",
    "/ai/proofread", "/formats/parse", "/export/content/docx",
])
async def test_anonymous_studio_gate_covers_alternate_guest_admissions(path, policy_app):
    app, db = policy_app
    app.dependency_overrides[get_current_user_optional] = lambda: None
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != "a09"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={"job_type": "latex_compilation", "latex_content": "source"})
    assert response.status_code == 403, response.text
    assert "a09" in response.text
    db.execute.assert_not_awaited()


async def test_guest_source_recovery_does_not_require_studio(policy_app):
    app, _ = policy_app
    app.dependency_overrides[get_current_user_optional] = lambda: None
    entitlement_service.has_feature.return_value = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/export/content/tex", json={"latex_content": "my draft"})
    assert response.status_code == 200
    assert response.text == "my draft"


async def test_structured_import_checks_interchange_capability(policy_app):
    app, _ = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != "b07"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/resumes/builder/seed-upload",
            files={"file": ("resume.json", b'{"basics":{"name":"Test"}}', "application/json")},
        )
    assert response.status_code == 403
    assert "b07" in response.text


async def test_specialty_template_asset_rechecks_category_capability(monkeypatch):
    from app.api.template_routes import _template_asset_access

    db = AsyncMock()
    db.get.return_value = SimpleNamespace(is_active=True, category="academic")
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    with pytest.raises(HTTPException) as exc:
        await _template_asset_access(USER_ID, db, USER_ID)
    assert exc.value.status_code == 403
    checker.assert_awaited_once_with("b05", user=USER_ID)


@pytest.mark.parametrize("path,key", [("compile", "h09"), ("optimize", "d01"), ("ats/score", "d18")])
async def test_public_api_gate_runs_before_job_record_creation(path, key, policy_app):
    from app.middleware.auth_middleware import get_developer_api_key_required

    app, db = policy_app
    app.dependency_overrides[get_developer_api_key_required] = lambda: SimpleNamespace(
        user_id=USER_ID, scopes=["compile", "optimize", "ats"],
    )
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/v1/{path}", json={"latex_content": "source", "job_description": "role"})
    assert response.status_code == 403
    assert key in response.text
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_enabled_gate_calls_handler_and_retains_request_validation(monkeypatch):
    gated = CapabilityRouter()

    async def update_builder_resume():
        return {"updated": True}

    update_builder_resume.__module__ = "app.api.resume_routes"
    gated.add_api_route("/builder", update_builder_resume, methods=["PATCH"])
    app = FastAPI()
    app.include_router(gated)
    app.dependency_overrides[get_current_user_optional] = lambda: USER_ID
    checker = AsyncMock(return_value=True)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch("/builder", json={"structured_content": {}})
    assert response.status_code == 200
    assert response.json() == {"updated": True}
    checker.assert_awaited_once_with("b08", user=USER_ID)


def test_safe_downgrade_routes_do_not_gain_product_dependencies():
    safe = {
        "resume_routes": {"get_resume", "get_builder_resume", "delete_resume", "revoke_share_link", "remove_collaborator", "restore_optimization", "unpin_resume", "unarchive_resume"},
        "tracker_workflow_routes": {"list_saved_jobs", "delete_saved_job", "delete_alert", "export_interview_calendar"},
        "workspace_routes": {"list_workspaces", "delete_workspace", "remove_member", "remove_resume_from_workspace", "download_workspace_resume"},
        "github_routes": {"github_disconnect", "disable_github_sync", "get_github_import_result"},
        "dropbox_routes": {"dropbox_disconnect", "disable_dropbox_sync"},
        "developer_routes": {"list_developer_keys", "revoke_developer_key"},
        "byok_routes": {"get_user_api_keys", "delete_api_key"},
        "job_routes": {"get_job_state", "get_job_result", "cancel_job"},
        "public_api_routes": {"get_job_v1", "download_job_pdf_v1"},
        "routes": {"get_me", "get_entitlements_for_user", "download_pdf", "cancel_subscription"},
    }
    for module, names in safe.items():
        for name in names:
            route = _routes()[(module, name)]
            assert all(not dependency.call.__name__.startswith("capability_") for dependency in route.dependant.dependencies)
            assert all(dependency.call.__module__ != "app.middleware.entitlements" for dependency in route.dependant.dependencies), (module, name)


@pytest.mark.parametrize("module,name,body,expected", [
    ("job_routes", "submit_job", {"job_type": "latex_compilation"}, ()),
    ("job_routes", "submit_job", {"job_type": "combined", "tone": "formal"}, ("d01", "d18", "d02")),
    ("resume_routes", "create_share_link", {"anonymous": True, "review_comments": True}, ("f01", "f02", "f03")),
    ("resume_routes", "update_resume", {"portfolio_visible": False}, ()),
    ("tracker_workflow_routes", "update_alert", {"active": False}, ()),
    ("tracker_workflow_routes", "update_alert", {"active": False, "query": "new"}, ("e06",)),
    ("ws_routes", "create_websocket_ticket", {"purpose": "jobs"}, ()),
    ("ws_routes", "create_websocket_ticket", {"purpose": "collab"}, ("f05",)),
    ("resume_routes", "update_resume_tags", {"tags": []}, ()),
    ("resume_routes", "update_collaborator_role", {"role": "viewer"}, ()),
    ("resume_routes", "update_collaborator_role", {"role": "editor"}, ("f04",)),
    ("workspace_routes", "update_member_role", {"role": "viewer"}, ()),
    ("workspace_routes", "update_member_role", {"role": "editor"}, ("f08",)),
    ("portfolio_routes", "setup_portfolio", {"portfolio_enabled": False}, ()),
    ("ats_routes", "score_resume_ats", {"locale": "global"}, ()),
    ("ats_routes", "score_resume_ats", {"industry_override": "tech_saas"}, ("d19",)),
])
def test_dynamic_policy_preserves_recovery_and_checks_requested_operations(module, name, body, expected):
    assert payload_capabilities(module, name, body, {}, {}) == expected


@pytest.mark.parametrize("scope,key", [("compile", "h09"), ("optimize", "d01"), ("ats", "d18")])
async def test_existing_developer_key_cannot_dispatch_after_downgrade(scope, key, monkeypatch):
    from app.api.public_api_routes import _authorize, developer_key_service

    db = AsyncMock()
    checker = AsyncMock(side_effect=lambda candidate, **kwargs: candidate != key)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    meter = AsyncMock()
    monkeypatch.setattr(developer_key_service, "consume_rate_limit", meter)
    api_key = SimpleNamespace(user_id=USER_ID, scopes=["compile", "optimize", "ats"])
    with pytest.raises(HTTPException) as exc:
        await _authorize(scope, api_key, db)
    assert exc.value.status_code == 403
    db.execute.assert_not_awaited()
    meter.assert_not_awaited()


async def test_stored_byok_key_is_not_decrypted_or_replaced_with_platform_key(monkeypatch):
    from app.api.ai_routes import _resolve_ai_api_key
    from app.services.api_key_service import api_key_service

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = SimpleNamespace(encrypted_key="encrypted")
    db.execute.return_value = result
    decrypt = MagicMock()
    monkeypatch.setattr(api_key_service.encryption, "decrypt", decrypt)
    monkeypatch.setattr(entitlement_service, "has_feature", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        await _resolve_ai_api_key(db, USER_ID)
    assert exc.value.status_code == 403
    decrypt.assert_not_called()


async def test_public_review_uses_owner_entitlement_and_hides_disabled_link(monkeypatch):
    from app.api.review_routes import _review_resume

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(
        user_id=USER_ID, resume_settings={"share_review_comments": True},
    )
    db.execute.return_value = result
    checker = AsyncMock(side_effect=lambda candidate, **kwargs: candidate != "f03")
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    with pytest.raises(HTTPException) as exc:
        await _review_resume("valid_share_token_12345", db)
    assert exc.value.status_code == 404
    assert all(call.kwargs["user"] == USER_ID for call in checker.await_args_list)


async def test_disabled_public_share_cannot_issue_another_storage_url(monkeypatch):
    from app.api.routes import get_shared_resume

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(user_id=USER_ID, resume_settings={})
    db.execute.return_value = result
    checker = AsyncMock(return_value=False)
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    with pytest.raises(HTTPException) as exc:
        await get_shared_resume("known-token", MagicMock(), db)
    assert exc.value.status_code == 404
    checker.assert_awaited_once_with("f01", user=USER_ID)
    assert db.execute.await_count == 1  # No compiled-artifact/storage lookup.


async def test_owner_can_still_read_source_after_sharing_and_builder_disabled(policy_app, monkeypatch):
    from app.api import resume_routes

    app, db = policy_app
    entitlement_service.has_feature.return_value = False
    now = datetime.now(timezone.utc)
    db.execute.side_effect = None
    result = MagicMock()
    result.scalar_one_or_none.return_value = 0
    db.execute.return_value = result
    resume = SimpleNamespace(
        id=USER_ID, user_id=USER_ID, title="Owned resume", latex_content="my source",
        created_at=now, updated_at=now, is_template=False,
    )
    monkeypatch.setattr(resume_routes, "_get_resume_document_access", AsyncMock(return_value=(resume, "owner")))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/resumes/{USER_ID}")
    assert response.status_code == 200
    assert response.json()["latex_content"] == "my source"

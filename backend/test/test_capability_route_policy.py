"""No-infrastructure regression tests for granular operation enforcement.

Exercise real registered routers with disabled capabilities and fail-on-use
database doubles. No provider, queue, payment, or production mutation is used.
"""

from __future__ import annotations

from copy import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.api.routes import router
from app.core.feature_registry import CAPABILITY_ROLES, PLAN_MATRIX_KEYS, gateable_keys, get_feature
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.middleware.capability_router import (
    DYNAMIC_ENDPOINTS,
    ROUTE_CAPABILITIES,
    CapabilityRouter,
    _route_gate,
    payload_capabilities,
)
from app.services.entitlement_service import EntitlementService, entitlement_service

USER_ID = "11111111-1111-4111-8111-111111111111"


def _routes():
    def walk(current, prefix=""):
        for route in current.routes:
            if isinstance(route, APIRoute):
                effective_route = copy(route)
                effective_route.path = prefix + route.path
                yield effective_route
            elif hasattr(route, "original_router"):
                # FastAPI's lazy nested inclusion keeps child paths relative
                # until request matching. Preserve those prefixes in the audit.
                yield from walk(route.original_router, prefix + route.include_context.prefix)

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


@pytest.mark.parametrize(("module", "name"), [
    ("resume_routes", "quick_tailor_resume"),
    ("resume_routes", "convert_academic_cv"),
    ("job_routes", "create_batch_tailor"),
])
def test_routes_that_dispatch_combined_jobs_require_compilation(module, name):
    assert "c05" in ROUTE_CAPABILITIES[module][name]


@pytest.mark.parametrize("job_type,key", [
    ("latex_compilation", "c05"),
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


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/compile", None),
    ("POST", "/public/compile", None),
    ("POST", "/jobs/submit", {"job_type": "latex_compilation", "latex_content": "source"}),
    ("POST", "/jobs/compile-watermarked", {"latex_content": "source", "watermark": "Preview"}),
    ("POST", f"/resumes/{USER_ID}/share", {"anonymous": True}),
])
async def test_global_compile_off_blocks_every_new_compile_admission(method, path, body, policy_app):
    app, db = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != "c05"
    if path == "/public/compile":
        app.dependency_overrides[get_current_user_optional] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        if path in {"/compile", "/public/compile"}:
            response = await client.request(
                method, path,
                data={"latex_content": "source", "device_fingerprint": "device-1"},
            )
        else:
            response = await client.request(method, path, json=body)
    assert response.status_code == 403, response.text
    assert "c05" in response.text
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_existing_artifact_and_billing_recovery_paths_do_not_inherit_admission_gates():
    routes = _routes()
    for pair in (
        ("routes", "download_pdf"),
        ("job_routes", "get_job_result"),
        ("resume_routes", "get_resume"),
        ("resume_routes", "delete_resume"),
        ("cover_letter_routes", "get_cover_letter"),
        ("cover_letter_routes", "delete_cover_letter"),
        ("routes", "reconcile_subscription"),
        ("routes", "cancel_subscription"),
        ("tenant_routes", "resolve_tenant_host"),
        ("tenant_routes", "leave_tenant"),
    ):
        route = routes[pair]
        assert not any(
            getattr(dependency.call, "__name__", "").startswith("capability_")
            for dependency in route.dependant.dependencies
        ), pair

    assert ROUTE_CAPABILITIES["cover_letter_routes"]["update_cover_letter"] == ("e01", "c01")


async def test_developer_api_compile_uses_owner_capability_gate(monkeypatch):
    from types import SimpleNamespace

    from app.api import public_api_routes

    enforce = AsyncMock()
    monkeypatch.setattr(public_api_routes, "enforce_capabilities", enforce)
    key = SimpleNamespace(user_id=USER_ID, scopes=["compile"])
    await public_api_routes.require_developer_operation("compile")(key)
    enforce.assert_awaited_once_with(("h09", "c05"), USER_ID)


@pytest.mark.parametrize("method,path,body,key", [
    ("POST", "/resumes/", {"latex_content": "source"}, "b01"),
    ("PUT", f"/resumes/{USER_ID}", {"latex_content": "edited"}, "c01"),
    ("PATCH", f"/resumes/{USER_ID}/builder", {"structured_content": {}}, "c01"),
    ("POST", f"/resumes/{USER_ID}/record-optimization", {
        "original_latex": "source", "optimized_latex": "injected source",
    }, "c01"),
    ("POST", "/tenants", {"slug": "test-tenant", "name": "Test"}, "f10"),
    ("POST", f"/tenants/{USER_ID}/cohorts", {"name": "Class"}, "f10"),
    ("PATCH", f"/tenants/{USER_ID}", {"custom_domain": "example.com"}, "f11"),
])
async def test_new_resume_tenant_and_domain_admissions_fail_closed(method, path, body, key, policy_app):
    app, db = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != key
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json=body)
    assert response.status_code == 403, response.text
    assert key in response.text
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("path,body", [
    ("/resumes/", {"title": "New resume", "latex_content": r"\\documentclass{article}"}),
    ("/resumes/builder", {"title": "Builder resume", "template_id": USER_ID}),
    ("/resumes/{resume_id}/fork", {"title": "Resume copy"}),
    ("/templates/{template_id}/use", {}),
])
async def test_new_source_bearing_resume_admissions_require_c01(path, body, policy_app):
    app, db = policy_app
    entitlement_service.has_feature.side_effect = lambda candidate, **kwargs: candidate != "c01"
    path = path.replace("{resume_id}", USER_ID).replace("{template_id}", USER_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=body)
    assert response.status_code == 403, response.text
    assert "c01" in response.text
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_optimization_history_write_is_gated_but_restore_remains_recovery():
    routes = _routes()
    record = routes[("resume_routes", "record_optimization")]
    restore = routes[("resume_routes", "restore_optimization")]
    assert _route_gate("resume_routes", "record_optimization") in {
        dependency.call for dependency in record.dependant.dependencies
    }
    assert all(
        not getattr(dependency.call, "__name__", "").startswith("capability_")
        for dependency in restore.dependant.dependencies
    )


def test_source_transformation_and_variant_rendering_are_edit_admissions():
    assert "c01" in ROUTE_CAPABILITIES["optimize_routes"]["apply_changes_endpoint"]
    assert ROUTE_CAPABILITIES["resume_routes"]["update_variant_visibility"] == ("b12", "c01")


async def test_existing_optimization_restore_succeeds_while_source_edit_is_disabled(policy_app):
    app, db = policy_app
    entitlement_service.has_feature.return_value = False
    resume = SimpleNamespace(
        id=USER_ID, user_id=USER_ID, latex_content="old", content_source="manual_latex",
        selected_template_id=None, structured_content=None, resume_settings={},
    )
    optimization = SimpleNamespace(optimized_latex="recovered source")
    resume_result = MagicMock()
    resume_result.scalar_one_or_none.return_value = resume
    optimization_result = MagicMock()
    optimization_result.scalar_one_or_none.return_value = optimization
    db.execute.side_effect = [resume_result, optimization_result]
    db.commit.side_effect = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/resumes/{USER_ID}/restore-optimization/{USER_ID}")

    assert response.status_code == 200, response.text
    assert response.json()["latex_content"] == "recovered source"
    assert resume.latex_content == "recovered source"
    db.commit.assert_awaited_once()


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
    assert checker.await_args_list == [
        (("b08",), {"user": USER_ID}),
        (("c01",), {"user": USER_ID}),
    ]


@pytest.mark.parametrize(
    ("role", "plan", "restriction"),
    [
        ("user", "pro", "global"),
        ("support", "pro", "role"),
        ("admin", "pro", "role"),
        ("user", "pro_annual", "family"),
        ("user", "pro_annual", "sku"),
    ],
)
@pytest.mark.parametrize(
    ("handler", "suffix"),
    [("update_builder_resume", "builder"), ("update_builder_resume_v1", "builder/v1")],
)
async def test_force_reattach_capability_blocks_legacy_and_v1_routes_before_database(
    handler, suffix, role, plan, restriction, policy_app, monkeypatch,
):
    app, db = policy_app
    keys = gateable_keys()
    blob = {
        "kill": dict.fromkeys(keys, True),
        "matrix": {axis: dict.fromkeys(keys, True) for axis in PLAN_MATRIX_KEYS},
        "roles": {axis: dict.fromkeys(keys, True) for axis in CAPABILITY_ROLES},
    }
    if restriction == "global":
        blob["kill"]["b09"] = False
    elif restriction == "role":
        blob["roles"][role]["b09"] = False
    elif restriction == "family":
        blob["matrix"]["pro"]["b09"] = False
    elif restriction == "sku":
        blob["matrix"]["pro_annual"]["b09"] = False

    policy = EntitlementService()
    checker = AsyncMock(
        side_effect=lambda key, **kwargs: policy._decide(blob, key, plan, role),
    )
    monkeypatch.setattr(entitlement_service, "has_feature", checker)
    route = _routes()[("resume_routes", handler)]
    path = route.path
    for parameter in route.param_convertors:
        path = path.replace("{" + parameter + "}", USER_ID)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            path,
            json={
                "force_reattach": True,
                "expected_structured_version": 1,
                "expected_latex_content": "current source",
            },
        )

    assert response.status_code == 403, (handler, role, plan, restriction, response.text)
    assert "b09" in response.text
    assert [call.args[0] for call in checker.await_args_list] == ["b08", "c01", "b09"]
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


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
    ("job_routes", "submit_job", {"job_type": "latex_compilation"}, ("c05",)),
    ("job_routes", "submit_job", {"job_type": "combined", "tone": "formal"}, ("d01", "d18", "c05", "c01", "d02")),
    ("resume_routes", "create_share_link", {"anonymous": True, "review_comments": True}, ("f01", "f02", "f03", "c05")),
    ("resume_routes", "update_resume", {"portfolio_visible": False}, ()),
    ("resume_routes", "update_resume", {"title": "Metadata only"}, ()),
    ("resume_routes", "update_resume", {"latex_content": "new source"}, ()),
    ("tenant_routes", "update_tenant", {"name": "New name"}, ("f10",)),
    ("tenant_routes", "update_tenant", {"logo_url": "https://example.com/logo.png"}, ("f10",)),
    ("tenant_routes", "update_tenant", {"active": True}, ("f10",)),
    ("tenant_routes", "update_tenant", {"active": False}, ()),
    ("tenant_routes", "update_tenant", {"custom_domain": None}, ()),
    ("suggestion_routes", "decide_suggestion", {"status": "rejected"}, ()),
    ("suggestion_routes", "decide_suggestion", {"status": "conflicted"}, ()),
    ("suggestion_routes", "decide_suggestion", {"status": "accepted"}, ("f07", "c01")),
    ("tracker_workflow_routes", "update_alert", {"active": False}, ()),
    ("tracker_workflow_routes", "update_alert", {"active": False, "query": "new"}, ("e06",)),
    ("ws_routes", "create_websocket_ticket", {"purpose": "jobs"}, ()),
    ("ws_routes", "create_websocket_ticket", {"purpose": "collab"}, ("f05",)),
    ("resume_routes", "update_resume_tags", {"tags": []}, ()),
    ("resume_routes", "update_collaborator_role", {"role": "viewer"}, ()),
    # The stored role decides whether a commenter target is recovery or a write grant.
    ("resume_routes", "update_collaborator_role", {"role": "commenter"}, ()),
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


@pytest.mark.parametrize("role", ["anonymous", "user", "support", "admin"])
@pytest.mark.parametrize("disabled_key", ["b07", "h01"])
@pytest.mark.parametrize("method,path", [
    ("POST", "/export/content/json"),
    ("GET", f"/export/{USER_ID}/json"),
    ("GET", f"/export/builder/v1/{USER_ID}/json"),
])
async def test_json_export_composes_interchange_and_export_grants_before_data_access(
    role, disabled_key, method, path, policy_app, monkeypatch,
):
    if role == "anonymous" and method != "POST":
        pytest.skip("Saved and builder exports require authenticated ownership")
    from app.api import export_routes
    from app.services.entitlement_service import EntitlementService
    from test.test_capability_resolution import allowed_blob

    app, db = policy_app
    if role == "anonymous":
        app.dependency_overrides[get_current_user_optional] = lambda: None
    # Exercise the real policy decision, including the admin/support role axis;
    # only the authoritative snapshot I/O is replaced with a synthetic record.
    blob = allowed_blob()
    blob["roles"][role][disabled_key] = False
    monkeypatch.setattr(entitlement_service, "_snapshot_for_user", AsyncMock(return_value=(role, "pro", blob)))
    monkeypatch.setattr(entitlement_service, "has_feature", EntitlementService.has_feature.__get__(entitlement_service))
    db.get.side_effect = AssertionError("Denied JSON export read the saved document")
    convert = MagicMock(side_effect=AssertionError("Denied JSON export converted source"))
    structured = MagicMock(side_effect=AssertionError("Denied JSON export converted builder fields"))
    monkeypatch.setattr(export_routes, "_convert_latex", convert)
    monkeypatch.setattr(export_routes.json_resume_interchange_service, "to_json_resume", structured)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.request(method, path, json={"latex_content": "owned source"} if method == "POST" else None)
    assert response.status_code == 403, response.text
    assert disabled_key in response.text
    db.get.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()
    convert.assert_not_called()
    structured.assert_not_called()


@pytest.mark.parametrize("method,path", [
    ("POST", "/export/content/json"),
    ("GET", f"/export/{USER_ID}/json"),
    ("GET", f"/export/builder/v1/{USER_ID}/json"),
])
async def test_json_export_allows_the_composed_grants(method, path, policy_app, monkeypatch):
    from app.api import export_routes

    app, db = policy_app
    db.get.return_value = SimpleNamespace(
        user_id=USER_ID, latex_content="owned source", structured_content=None, content_source="manual_latex",
    )
    convert = MagicMock(return_value=b'{"basics": {}}')
    monkeypatch.setattr(export_routes, "_convert_latex", convert)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.request(method, path, json={"latex_content": "owned source"} if method == "POST" else None)
    assert response.status_code == 200, response.text
    assert response.json() == {"basics": {}}
    assert {call.args[0] for call in entitlement_service.has_feature.await_args_list} >= {"h01", "b07"}
    convert.assert_called_once_with("owned source", "json")


def test_json_export_gate_does_not_change_other_export_or_source_recovery_policies():
    assert payload_capabilities("export_routes", "export_content", {}, {"fmt": "json"}, {}) == ("h01", "b07")
    assert payload_capabilities("export_routes", "export_resume", {}, {"fmt": "docx"}, {}) == ("h01",)
    assert payload_capabilities("export_routes", "export_resume", {}, {"fmt": "svg"}, {}) == ("h02",)
    assert payload_capabilities("export_routes", "export_resume", {}, {"fmt": "tex"}, {}) == ()
    assert payload_capabilities("export_routes", "export_resume", {}, {"fmt": "pdf"}, {}) == ()

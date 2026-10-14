"""D14 child gates on the complete, registered ASGI router.

Policy decisions are real EntitlementService decisions over an isolated current
snapshot. Authentication is controlled for account-policy cases; anonymous
cases use the real required-auth dependency. Handler DB/cache/key/quota/image/
provider work has fail-on-use doubles for denied admissions. Multipart parsing
may receive the HTTP body before a dependency; these tests assert that handler
upload reads and normalization are never reached, not that reception is avoided.
"""
from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.api import ai_routes
from app.api.routes import router
from app.database.connection import get_db
from app.middleware.auth_middleware import get_current_user_optional, get_current_user_required
from app.middleware.capability_router import ROUTE_CAPABILITIES, _route_gate
from app.services.entitlement_service import entitlement_service
from test.test_capability_resolution import allowed_blob
from test.test_capability_route_policy import _routes

USER_ID = "11111111-1111-4111-8111-111111111111"


@dataclass(frozen=True)
class Operation:
    leaf: str
    handler: str
    path: str
    payload: dict | None

    @property
    def image(self):
        return self.payload is None


OPERATIONS = (
    Operation("d14_latex", "generate_latex", "/ai/generate-latex", {"intent": "Create a skills section"}),
    Operation("d14_table_text", "generate_table_from_text", "/ai/generate-table", {"table_text": "Name,Score\nAda,99"}),
    Operation("d14_table_image", "generate_table_from_image", "/ai/generate-table-image", None),
    Operation("d14_math_text", "generate_math_from_text", "/ai/generate-math", {"math_text": "x squared"}),
    Operation("d14_math_image", "generate_math_from_image", "/ai/generate-math-image", None),
)
PROVIDER_OPERATIONS = tuple(operation for operation in OPERATIONS if operation.leaf != "d14_table_text")


def png_bytes(*, format="PNG", size=(8, 8)):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format=format)
    return output.getvalue()


async def post_operation(client, operation, *, payload=None, image=None, data=None):
    if operation.image:
        return await client.post(operation.path, files={
            "file": ("sandbox.png", png_bytes() if image is None else image, "image/png"),
        }, data=data or {})
    return await client.post(operation.path, json=operation.payload if payload is None else payload)


@pytest.fixture(scope="module")
def registered_app():
    # The full API router preserves real nesting/mounting and installed gates.
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def harness(registered_app, monkeypatch):
    blob = allowed_blob()
    identity = SimpleNamespace(user=USER_ID, role="user", sku="student")
    db = AsyncMock()
    for name in ("execute", "commit", "flush", "refresh", "rollback"):
        getattr(db, name).side_effect = AssertionError(f"Unexpected handler DB {name}")
    registered_app.dependency_overrides[get_db] = lambda: db
    registered_app.dependency_overrides[get_current_user_optional] = lambda: identity.user
    registered_app.dependency_overrides[get_current_user_required] = lambda: identity.user

    async def current_snapshot(user):
        assert user == identity.user
        return ("anonymous", None, blob) if user is None else (identity.role, identity.sku, blob)

    snapshot = AsyncMock(side_effect=current_snapshot)
    monkeypatch.setattr(entitlement_service, "_snapshot_for_user", snapshot)
    result = SimpleNamespace(app=registered_app, blob=blob, identity=identity, db=db, snapshot=snapshot)
    yield result
    registered_app.dependency_overrides.clear()


@pytest.fixture
def forbidden_work(monkeypatch):
    doubles = {}
    for target, name, asynchronous in (
        (ai_routes.cache_manager, "get", True), (ai_routes.cache_manager, "set", True),
        (ai_routes, "read_upload_capped", True), (ai_routes, "_normalize_vision_image", False),
        (ai_routes, "_resolve_ai_api_key", True), (ai_routes, "_charge_ai_assist", True),
        (ai_routes, "_generate_math_body", True), (ai_routes, "_parse_delimited_table", False),
        (ai_routes.openai, "AsyncOpenAI", False), (entitlement_service, "refund_quota", True),
    ):
        cls = AsyncMock if asynchronous else Mock
        double = cls(side_effect=AssertionError(f"Denied admission reached {name}"))
        monkeypatch.setattr(target, name, double)
        doubles[name] = double
    return doubles


def assert_no_handler_work(harness, doubles):
    for name in ("execute", "commit", "flush", "refresh", "rollback"):
        getattr(harness.db, name).assert_not_awaited()
    for double in doubles.values():
        double.assert_not_called()


def permission_cell(harness, level, axis):
    key = level
    if axis == "global":
        return harness.blob["kill"], key
    if axis == "role":
        return harness.blob["roles"][harness.identity.role], key
    return harness.blob["matrix"]["pro" if axis == "family" else "student"], key


def test_d14_exact_route_leaf_mapping_and_registration():
    routes = _routes()
    for operation in OPERATIONS:
        assert ROUTE_CAPABILITIES["ai_routes"][operation.handler] == (operation.leaf,)
        route = routes[("ai_routes", operation.handler)]
        assert route.path == operation.path
        assert route.methods == {"POST"}
        gate = _route_gate("ai_routes", operation.handler)
        assert sum(dep.call is gate for dep in route.dependant.dependencies) == 1
        assert route.dependant.dependencies[0].call is gate


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("role", ["user", "support", "admin"])
@pytest.mark.parametrize("level", ["leaf", "d14", "ai_writing"])
@pytest.mark.parametrize("axis", ["global", "role", "family", "sku"])
async def test_d14_registered_denial_precedes_all_handler_work(operation, role, level, axis, harness, forbidden_work):
    harness.identity.role = role
    cells, key = permission_cell(harness, operation.leaf if level == "leaf" else level, axis)
    cells[key] = False
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 403, response.text
    assert "feature_disabled" in response.text
    assert operation.leaf in response.text
    assert_no_handler_work(harness, forbidden_work)


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("axis", ["global", "role", "family", "sku"])
async def test_d14_registered_missing_leaf_row_denies(operation, axis, harness, forbidden_work):
    cells, key = permission_cell(harness, operation.leaf, axis)
    del cells[key]
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 403
    assert_no_handler_work(harness, forbidden_work)


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
async def test_d14_registered_snapshot_outage_denies(operation, harness, forbidden_work):
    harness.snapshot.side_effect = ConnectionError("isolated policy unavailable")
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 403
    assert_no_handler_work(harness, forbidden_work)


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
async def test_d14_anonymous_enabled_operation_still_requires_authentication(operation, harness, forbidden_work):
    harness.identity.user = None
    del harness.app.dependency_overrides[get_current_user_required]
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"] == "Bearer"
    assert_no_handler_work(harness, forbidden_work)


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
async def test_d14_anonymous_disabled_operation_keeps_existing_pre_auth_denial(operation, harness, forbidden_work):
    # CapabilityRouter already gates anonymous admissions before required auth;
    # introducing leaves preserves its existing disabled-policy 403 semantics.
    harness.identity.user = None
    del harness.app.dependency_overrides[get_current_user_required]
    harness.blob["kill"][operation.leaf] = False
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 403
    assert operation.leaf in response.text
    assert_no_handler_work(harness, forbidden_work)


@pytest.fixture
def sandbox_provider(monkeypatch):
    create = AsyncMock()
    provider = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    key = AsyncMock(return_value=SimpleNamespace(key="sandbox-dummy-key"))
    ticket = object()
    charge = AsyncMock(return_value=ticket)
    refund = AsyncMock()
    cache_get = AsyncMock(return_value=None)
    cache_set = AsyncMock()
    monkeypatch.setattr(ai_routes.openai, "AsyncOpenAI", provider)
    monkeypatch.setattr(ai_routes, "_resolve_ai_api_key", key)
    monkeypatch.setattr(ai_routes, "_charge_ai_assist", charge)
    monkeypatch.setattr(entitlement_service, "refund_quota", refund)
    monkeypatch.setattr(ai_routes.cache_manager, "get", cache_get)
    monkeypatch.setattr(ai_routes.cache_manager, "set", cache_set)
    return SimpleNamespace(create=create, provider=provider, key=key, charge=charge,
                           ticket=ticket, refund=refund, cache_get=cache_get, cache_set=cache_set)


def provider_response(operation, *, unsafe=False):
    if operation.leaf == "d14_latex":
        content = r"\input{/etc/passwd}" if unsafe else r"\section{Skills}"
    elif operation.leaf == "d14_table_image":
        content = json.dumps({"rows": [["one column"]] if unsafe else [["Name", "Score"], ["Ada", "99"]]})
    else:
        content = json.dumps({"latex": r"\input{/etc/passwd}" if unsafe else r"x^2"})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("role", ["user", "support", "admin"])
async def test_d14_only_selected_child_allows_registered_generation(operation, role, harness, sandbox_provider):
    harness.identity.role = role
    for sibling in OPERATIONS:
        harness.blob["kill"][sibling.leaf] = sibling == operation
    # C01 controls a separate insertion mutation, not fragment generation.
    harness.blob["kill"]["c01"] = False
    sandbox_provider.create.return_value = provider_response(operation)
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code == 200, response.text
    assert response.json()["latex"]
    if operation.leaf == "d14_table_text":
        sandbox_provider.key.assert_not_awaited()
        sandbox_provider.charge.assert_not_awaited()
        sandbox_provider.provider.assert_not_called()
        sandbox_provider.cache_get.assert_not_awaited()
        sandbox_provider.cache_set.assert_not_awaited()
    else:
        sandbox_provider.key.assert_awaited_once()
        sandbox_provider.charge.assert_awaited_once()
        sandbox_provider.create.assert_awaited_once()
        if operation.image:
            content = sandbox_provider.create.call_args.kwargs["messages"][1]["content"]
            assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    sandbox_provider.refund.assert_not_awaited()
    harness.db.execute.assert_not_awaited()


@pytest.mark.parametrize("operation", [OPERATIONS[0], OPERATIONS[3]], ids=lambda operation: operation.leaf)
async def test_d14_enabled_cache_uses_same_leaf_admission_and_skips_quota(operation, harness, sandbox_provider):
    value = {"latex": r"\section{Cached}"} if operation.leaf == "d14_latex" else {"body": r"x^2"}
    sandbox_provider.cache_get.return_value = value
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
        harness.blob["kill"][operation.leaf] = False
        denied = await post_operation(client, operation)
    assert response.status_code == 200
    assert response.json()["cached"] is True
    assert denied.status_code == 403
    sandbox_provider.cache_get.assert_awaited_once()
    sandbox_provider.key.assert_not_awaited()
    sandbox_provider.charge.assert_not_awaited()
    sandbox_provider.provider.assert_not_called()


@pytest.mark.parametrize("operation", PROVIDER_OPERATIONS, ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("failure", ["provider", "unsafe_output"])
async def test_d14_provider_and_output_failure_refund_once(operation, failure, harness, sandbox_provider):
    if failure == "provider":
        sandbox_provider.create.side_effect = RuntimeError("sandbox provider failure")
    else:
        sandbox_provider.create.return_value = provider_response(operation, unsafe=True)
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation)
    assert response.status_code in {422, 502}, response.text
    sandbox_provider.charge.assert_awaited_once()
    sandbox_provider.refund.assert_awaited_once_with(sandbox_provider.ticket)
    sandbox_provider.cache_set.assert_not_awaited()


@pytest.mark.parametrize("operation", PROVIDER_OPERATIONS, ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("failure", [False, True], ids=["success", "provider_failure"])
async def test_d14_admitted_work_finishes_after_leaf_revocation_new_retry_denies(operation, failure, harness, sandbox_provider):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def suspended_provider(**kwargs):
        entered.set()
        await release.wait()
        if failure:
            raise RuntimeError("sandbox failure after revocation")
        return provider_response(operation)

    sandbox_provider.create.side_effect = suspended_provider
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        admitted = asyncio.create_task(post_operation(client, operation))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert not admitted.done()
            harness.blob["kill"][operation.leaf] = False
            denied = await post_operation(client, operation)
            assert denied.status_code == 403
            assert sandbox_provider.create.await_count == 1
            assert sandbox_provider.charge.await_count == 1
        finally:
            release.set()
        response = await asyncio.wait_for(admitted, timeout=5)
    assert response.status_code == (502 if failure else 200), response.text
    if failure:
        sandbox_provider.refund.assert_awaited_once_with(sandbox_provider.ticket)
    else:
        assert response.json()["latex"]
        sandbox_provider.refund.assert_not_awaited()


@pytest.mark.parametrize("operation", [OPERATIONS[2], OPERATIONS[4]], ids=lambda operation: operation.leaf)
@pytest.mark.parametrize("image,status", [(b"not an image", 415), (b"x" * 5_000_001, 413),
                                          (png_bytes(format="GIF"), 415)])
async def test_d14_image_bounds_remain_mandatory_before_key_and_quota(operation, image, status, harness, sandbox_provider):
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation, image=image)
    assert response.status_code == status, response.text
    sandbox_provider.key.assert_not_awaited()
    sandbox_provider.charge.assert_not_awaited()
    sandbox_provider.provider.assert_not_called()


@pytest.mark.parametrize("operation,payload", [
    (OPERATIONS[0], {"intent": " "}),
    (OPERATIONS[0], {"intent": "x" * 2001}),
    (OPERATIONS[0], {"intent": "Valid", "document_context": "x" * 20_001}),
    (OPERATIONS[1], {"table_text": "only one column"}),
    (OPERATIONS[1], {"table_text": ",".join("column" for _ in range(21))}),
    (OPERATIONS[3], {"math_text": " "}),
    (OPERATIONS[3], {"math_text": "x", "display_mode": "align"}),
], ids=lambda value: value.leaf if isinstance(value, Operation) else None)
async def test_d14_input_validation_is_preserved(operation, payload, harness, sandbox_provider):
    async with AsyncClient(transport=ASGITransport(app=harness.app), base_url="http://test") as client:
        response = await post_operation(client, operation, payload=payload)
    assert response.status_code == 422
    sandbox_provider.key.assert_not_awaited()
    sandbox_provider.charge.assert_not_awaited()
    sandbox_provider.provider.assert_not_called()

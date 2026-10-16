"""Direct-route D14 admissions against persisted PostgreSQL entitlements."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import ai_routes
from app.services.entitlement_service import entitlement_service
from test._entitlement_reset import reset_entitlements_baseline
from test.test_admin_control_plane_api import _create_session, _create_user


@pytest.fixture(autouse=True)
async def restore_entitlement_grants(db_session):
    # These rows are shared mutable test state. Reset before and after each
    # direct-route case so a failed assertion cannot poison later tests.
    await reset_entitlements_baseline()
    try:
        yield
    finally:
        await reset_entitlements_baseline()


@pytest.fixture
def latex_work(monkeypatch):
    """Fail on any route work before the capability admission succeeds."""
    cache_get = AsyncMock(side_effect=AssertionError("Denied route reached cache read"))
    cache_set = AsyncMock(side_effect=AssertionError("Denied route reached cache write"))
    resolve_key = AsyncMock(side_effect=AssertionError("Denied route resolved an API key"))
    charge = AsyncMock(side_effect=AssertionError("Denied route charged quota"))
    create = AsyncMock(side_effect=AssertionError("Denied route called the provider"))
    provider_factory = Mock(side_effect=AssertionError("Denied route constructed a provider"))
    provider_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )

    monkeypatch.setattr(ai_routes.cache_manager, "get", cache_get)
    monkeypatch.setattr(ai_routes.cache_manager, "set", cache_set)
    monkeypatch.setattr(ai_routes, "_resolve_ai_api_key", resolve_key)
    monkeypatch.setattr(ai_routes, "_charge_ai_assist", charge)
    monkeypatch.setattr(ai_routes.openai, "AsyncOpenAI", provider_factory)

    def allow_safe_generation():
        cache_get.side_effect = None
        cache_get.return_value = None
        cache_set.side_effect = None
        resolve_key.side_effect = None
        resolve_key.return_value = SimpleNamespace(key="test-only-key")
        charge.side_effect = None
        charge.return_value = object()
        create.side_effect = None
        create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=r"\section{Skills}"))],
        )
        provider_factory.side_effect = None
        provider_factory.return_value = provider_client

    return SimpleNamespace(
        cache_get=cache_get,
        cache_set=cache_set,
        resolve_key=resolve_key,
        charge=charge,
        create=create,
        provider_factory=provider_factory,
        allow_safe_generation=allow_safe_generation,
    )


async def _auth_for(db_session, *, role: str, plan: str) -> dict[str, str]:
    user_id, _ = await _create_user(db_session, role=role, plan=plan, name="D14 route integration")
    token = await _create_session(db_session, user_id)
    return {"Authorization": f"Bearer {token}"}


async def _grant_latex_leaf(db_session, *, role: str, sku: str) -> None:
    # Explicit leaf grants make the parent and SKU restrictions below the
    # deciding rows. The seeded pro family is also part of the intersection.
    await entitlement_service.set_role_cell(role, "d14_latex", True, db_session)
    await entitlement_service.set_kill_switch("d14_latex", True, db_session)
    await entitlement_service.set_matrix_cell("pro", "d14_latex", True, db_session)
    await entitlement_service.set_matrix_cell(sku, "d14_latex", True, db_session)


def _assert_no_handler_work(work):
    for double in (work.cache_get, work.cache_set, work.resolve_key, work.charge, work.create):
        double.assert_not_awaited()
    work.provider_factory.assert_not_called()


def _assert_safe_generation_reached(work):
    work.cache_get.assert_awaited_once()
    work.resolve_key.assert_awaited_once()
    work.charge.assert_awaited_once()
    work.provider_factory.assert_called_once()
    work.create.assert_awaited_once()
    work.cache_set.assert_awaited_once()


@pytest.mark.parametrize("role", ["user", "support", "admin"])
@pytest.mark.parametrize("parent", ["d14", "ai_writing"])
async def test_parent_revocation_denies_then_live_reenable_allows_real_route(
    client, db_session, latex_work, role, parent,
):
    headers = await _auth_for(db_session, role=role, plan="pro_annual")
    await _grant_latex_leaf(db_session, role=role, sku="pro_annual")

    # Persist the toggle using the real entitlement control path. The registered
    # CapabilityRouter then reads it through EntitlementService's DB snapshot.
    await entitlement_service.set_kill_switch(parent, False, db_session)
    denied = await client.post(
        "/ai/generate-latex",
        headers=headers,
        json={"intent": "Create a skills section"},
    )
    assert denied.status_code == 403, denied.text
    assert "d14_latex" in denied.text
    _assert_no_handler_work(latex_work)

    # No snapshot is patched or cached by the test: a new request sees the
    # committed DB grant and reaches the safely stubbed provider/quota path.
    await entitlement_service.set_kill_switch(parent, True, db_session)
    latex_work.allow_safe_generation()
    allowed = await client.post(
        "/ai/generate-latex",
        headers=headers,
        json={"intent": "Create a skills section"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["latex"] == r"\section{Skills}"
    _assert_safe_generation_reached(latex_work)


async def test_student_sku_denial_is_scoped_and_pro_annual_sibling_still_generates(
    client, db_session, latex_work,
):
    student_headers = await _auth_for(db_session, role="user", plan="student")
    annual_headers = await _auth_for(db_session, role="user", plan="pro_annual")
    await _grant_latex_leaf(db_session, role="user", sku="student")
    await _grant_latex_leaf(db_session, role="user", sku="pro_annual")

    # "student" and "pro_annual" are the repository's concrete commercial
    # SKU keys; both resolve to the pro family, so only this exact SKU row
    # should distinguish their outcome.
    await entitlement_service.set_matrix_cell("student", "d14_latex", False, db_session)
    denied = await client.post(
        "/ai/generate-latex",
        headers=student_headers,
        json={"intent": "Create a skills section"},
    )
    assert denied.status_code == 403, denied.text
    assert "d14_latex" in denied.text
    _assert_no_handler_work(latex_work)

    latex_work.allow_safe_generation()
    allowed = await client.post(
        "/ai/generate-latex",
        headers=annual_headers,
        json={"intent": "Create a skills section"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["latex"] == r"\section{Skills}"
    _assert_safe_generation_reached(latex_work)

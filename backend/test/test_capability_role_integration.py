"""Real isolated PostgreSQL/Redis role policy and admin concurrency regressions."""
import asyncio
import importlib.util
from pathlib import Path

import pytest
from _entitlement_reset import reset_entitlements_baseline
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import delete, insert, select, update
from test_admin_control_plane_api import _admin_headers, _create_session, _create_user

from app.core.feature_registry import CAPABILITY_ROLES, gateable_keys
from app.database.connection import get_async_db_session
from app.database.models import RoleFeature, User
from app.services.entitlement_service import entitlement_service


@pytest.fixture(autouse=True)
async def restore_grants():
    yield
    await reset_entitlements_baseline()


@pytest.mark.parametrize("role", ["user", "support", "admin"])
async def test_role_off_hides_effective_map_and_denies_real_search_route(client, db_session, role):
    owner, _ = await _create_user(db_session, role=role, plan="pro")
    token = await _create_session(db_session, owner)
    auth = {"Authorization": f"Bearer {token}"}
    before = await client.get("/config/entitlements", headers=auth)
    assert before.status_code == 200 and before.json()["features"]["b03"] is True
    assert (await client.get("/resumes/search?q=synthetic", headers=auth)).status_code == 200
    await entitlement_service.set_role_cell(role, "b03", False, db_session)
    disabled = await client.get("/config/entitlements", headers=auth)
    assert disabled.json()["features"]["b03"] is False
    blocked = await client.get("/resumes/search?q=synthetic", headers=auth)
    assert blocked.status_code == 403 and "feature_disabled" in blocked.text
    # Owner data list and account access are independent recovery baselines.
    assert (await client.get("/resumes/", headers=auth)).status_code == 200
    assert (await client.get("/me", headers=auth)).status_code == 200
    await entitlement_service.set_role_cell(role, "b03", True, db_session)
    assert (await client.get("/resumes/search?q=synthetic", headers=auth)).status_code == 200


async def test_anonymous_restriction_does_not_restrict_authenticated_free_context(client, db_session):
    owner, _ = await _create_user(db_session, role="user", plan="free")
    token = await _create_session(db_session, owner)
    await entitlement_service.set_role_cell("anonymous", "a09", False, db_session)
    assert (await client.get("/config/entitlements")).json()["features"]["a09"] is False
    assert (await client.get("/config/entitlements", headers={"Authorization": f"Bearer {token}"})).json()["features"]["a09"] is True


async def test_role_changes_are_seen_without_old_session_or_process_allow_cache(client, db_session):
    owner, _ = await _create_user(db_session, role="user", plan="pro")
    token = await _create_session(db_session, owner)
    auth = {"Authorization": f"Bearer {token}"}
    await entitlement_service.set_role_cell("support", "b03", False, db_session)
    assert (await client.get("/config/entitlements", headers=auth)).json()["features"]["b03"]
    await db_session.execute(update(User).where(User.id == owner).values(role="support"))
    await db_session.commit()
    assert not (await client.get("/config/entitlements", headers=auth)).json()["features"]["b03"]
    assert not entitlement_service.sync_has_feature("b03", "pro", user_id=owner)


@pytest.mark.parametrize("role", ["user", "support"])
async def test_non_admin_cannot_read_or_write_role_controls(client, db_session, role):
    owner, _ = await _create_user(db_session, role=role)
    token = await _create_session(db_session, owner)
    auth = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/admin/entitlements", headers=auth)).status_code == 403
    response = await client.patch("/admin/entitlements/roles", headers=auth, json={"role": "admin", "feature_key": "b03", "enabled": False})
    assert response.status_code == 403


async def test_admin_recovery_survives_all_product_role_grants_off(client, db_session):
    auth = await _admin_headers(db_session)
    await db_session.execute(update(RoleFeature).where(RoleFeature.role == "admin").values(enabled=False))
    await db_session.commit()
    assert (await client.get("/admin/entitlements", headers=auth)).status_code == 200
    response = await client.patch("/admin/entitlements/roles", headers=auth, json={"role": "admin", "feature_key": "b03", "enabled": True, "expected_enabled": False})
    assert response.status_code == 200
    assert response.json()["role_matrix"]["admin"]["b03"]
    assert (await client.get("/me", headers=auth)).status_code == 200


async def test_role_admin_validation_and_compare_swap(client, db_session):
    auth = await _admin_headers(db_session)
    url = "/admin/entitlements/roles"
    assert (await client.patch(url, headers=auth, json={"role": "reader", "feature_key": "b03", "enabled": False})).status_code == 400
    assert (await client.patch(url, headers=auth, json={"role": "user", "feature_key": "compile", "enabled": False})).status_code == 404
    body = {"role": "user", "feature_key": "b03", "enabled": False, "expected_enabled": True}
    assert (await client.patch(url, headers=auth, json=body)).status_code == 200
    conflict = await client.patch(url, headers=auth, json={**body, "enabled": True})
    assert conflict.status_code == 409 and "capability_conflict" in conflict.text
    state = (await client.get("/admin/entitlements", headers=auth)).json()
    assert not state["role_matrix"]["user"]["b03"]
    assert all(state["role_matrix"][r]["b03"] for r in CAPABILITY_ROLES if r != "user")


@pytest.mark.parametrize("axis", ["role", "plan", "global"])
async def test_concurrent_same_cell_has_one_winner_and_distinct_cells_survive(db_session, axis):
    async def write(key):
        async with get_async_db_session() as db:
            try:
                if axis == "role":
                    await entitlement_service.set_role_cell("user", key, False, db, expected_enabled=True)
                elif axis == "plan":
                    await entitlement_service.set_matrix_cell("pro", key, False, db, expected_enabled=True)
                else:
                    await entitlement_service.set_kill_switch(key, False, db, expected_enabled=True)
                return 200
            except HTTPException as error:
                return error.status_code
    assert sorted(await asyncio.gather(write("b03"), write("b03"))) == [200, 409]
    assert await write("b06") == 200
    state = await entitlement_service.get_state()
    cells = state["role_matrix"]["user"] if axis == "role" else state["matrix"]["pro"] if axis == "plan" else state["kill_switches"]
    assert cells["b03"] is False and cells["b06"] is False


async def test_role_migration_preserves_denials_and_reupgrade(db_session):
    saved = [dict(row) for row in (await db_session.execute(select(RoleFeature.__table__))).mappings()]
    path = Path(__file__).parents[1] / "alembic/versions/0063_capability_roles.py"
    spec = importlib.util.spec_from_file_location("capability_roles_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    def upgrade(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
    try:
        await db_session.execute(delete(RoleFeature))
        db_session.add(RoleFeature(role="user", feature_key="b03", enabled=False))
        await db_session.commit()
        await (await db_session.connection()).run_sync(upgrade)
        await db_session.commit()
        grants = {(r.role, r.feature_key): r.enabled for r in (await db_session.execute(select(RoleFeature))).scalars()}
        assert len(grants) == len(CAPABILITY_ROLES) * len(gateable_keys())
        assert not grants["user", "b03"]
        assert all(key != "compile" for role, key in grants)
    finally:
        await db_session.rollback()
        await db_session.execute(delete(RoleFeature))
        await db_session.execute(insert(RoleFeature.__table__), saved)
        await db_session.commit()


@pytest.mark.parametrize("role", ["user", "support", "admin"])
async def test_target_offer_uses_current_role_and_role_off_stops_new_checkout(client, db_session, monkeypatch, role):
    from unittest.mock import AsyncMock

    from app.services.feature_flag_service import feature_flag_service
    from app.services.payment_service import payment_service
    from app.services.plan_catalog_service import plan_catalog_service

    owner, _ = await _create_user(db_session, role=role, plan="free")
    token = await _create_session(db_session, owner)
    auth = {"Authorization": f"Bearer {token}"}
    # A restriction on the current free subscription must not prevent upgrading
    # to an allowed target offer; current role restrictions must still apply.
    await entitlement_service.set_matrix_cell("free", "i02", False, db_session)
    await plan_catalog_service.require_new_purchase(db_session, "student", user_id=owner)
    await entitlement_service.set_role_cell(role, "i02", False, db_session)
    provider = AsyncMock()
    monkeypatch.setattr(feature_flag_service, "get_flag", AsyncMock(return_value=True))
    monkeypatch.setattr(payment_service, "create_subscription", provider)
    response = await client.post("/subscription/create", headers=auth, json={
        "planId": "student", "customerEmail": "test_ignored@example.test", "customerName": "Ignored", "studentEmail": "test_student@example.edu",
    })
    assert response.status_code == 403, response.text
    provider.assert_not_awaited()
    plans = await client.get("/subscription/plans", headers=auth)
    assert plans.status_code == 200, plans.text
    assert plans.json()["plans"]["student"]["capabilities"]["i02"] is False
    assert plans.json()["plans"]["student"]["purchasable"] is False
    await entitlement_service.set_role_cell(role, "i02", True, db_session)
    plans = await client.get("/subscription/plans", headers=auth)
    assert plans.json()["plans"]["student"]["capabilities"]["i02"] is True


async def test_student_verification_uses_recorded_owner_role_before_provider_and_keeps_token(client, db_session, monkeypatch):
    import json
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from app.core.redis import get_redis_cache_client
    from app.services.payment_service import payment_service

    owner, _ = await _create_user(db_session, role="support", plan="free")
    token = "test_student_role_" + uuid4().hex
    redis = await get_redis_cache_client()
    key = f"student_plan_verify:{token}"
    await redis.set(key, json.dumps({"user_id": owner, "customer_email": "test_student@example.edu", "customer_name": "Synthetic"}), ex=60)
    provider = AsyncMock()
    monkeypatch.setattr(payment_service, "_create_paid_subscription", provider)
    await entitlement_service.set_role_cell("support", "i02", False, db_session)
    try:
        denied = await client.get(f"/subscription/student/verify/{token}")
        assert denied.status_code == 403, denied.text
        provider.assert_not_awaited()
        assert await redis.get(key)
        assert await redis.get(f"latexy:student-verify:{token}") is None
    finally:
        await redis.delete(key)

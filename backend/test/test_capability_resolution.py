"""Capability authorization contracts with controlled DB/network boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.feature_registry import FEATURE_REGISTRY, PLAN_MATRIX_KEYS, gateable_keys
from app.services.entitlement_service import EntitlementService, _blob_from_rows
from app.services.feature_flag_service import FeatureFlagService


def allowed_blob():
    keys = gateable_keys()
    return {"kill": dict.fromkeys(keys, True), "matrix": {p: dict.fromkeys(keys, True) for p in PLAN_MATRIX_KEYS}}


@pytest.mark.parametrize("role", [None, "user", "support", "admin"])
async def test_roles_cannot_bypass_disabled_product_features(role):
    svc = EntitlementService()
    blob = allowed_blob()
    blob["kill"]["llm_optimize"] = False
    svc._get_blob = AsyncMock(return_value=blob)
    user = SimpleNamespace(role=role, subscription_plan="pro")
    assert not await svc.has_feature("d01", user=user)
    assert await svc.has_feature("compile", user=user)


@pytest.mark.parametrize("failure", [RuntimeError("db down"), ValueError("bad state")])
async def test_errors_only_allow_explicit_recovery_baselines(failure):
    svc = EntitlementService()
    svc._get_blob = AsyncMock(side_effect=failure)
    features = await svc.effective_features(None)
    assert all(features[f.key] is (not f.gateable) for f in FEATURE_REGISTRY)
    assert not await svc.has_feature("unknown_typo", user=None)
    assert not await svc.has_feature("d20", user=None)


@pytest.mark.parametrize("axis", ["global", "family", "sku", "parent_global", "parent_family", "parent_sku"])
def test_every_restriction_axis_dominates_child_grants(axis):
    svc = EntitlementService()
    blob = allowed_blob()
    if axis == "global":
        blob["kill"]["d01"] = False
    if axis == "family":
        blob["matrix"]["pro"]["d01"] = False
    if axis == "sku":
        blob["matrix"]["student"]["d01"] = False
    if axis == "parent_global":
        blob["kill"]["llm_optimize"] = False
    if axis == "parent_family":
        blob["matrix"]["pro"]["llm_optimize"] = False
    if axis == "parent_sku":
        blob["matrix"]["student"]["llm_optimize"] = False
    assert not svc._decide(blob, "d01", "student")


def test_sku_restriction_does_not_change_annual_or_family_siblings():
    svc = EntitlementService()
    blob = allowed_blob()
    blob["matrix"]["student"]["d01"] = False
    assert not svc._decide(blob, "d01", "student_monthly")
    assert svc._decide(blob, "d01", "pro")
    assert svc._decide(blob, "d01", "pro_annual")


@pytest.mark.parametrize("missing", ["kill", "family", "sku"])
def test_missing_rows_never_grant(missing):
    blob = allowed_blob()
    if missing == "kill":
        del blob["kill"]["d01"]
    if missing == "family":
        del blob["matrix"]["pro"]["d01"]
    if missing == "sku":
        del blob["matrix"]["student"]["d01"]
    assert not EntitlementService()._decide(blob, "d01", "student")


@pytest.mark.parametrize("plan", ["typo_pro", "admin", "legacy_unknown"])
def test_unrecognized_plans_do_not_inherit_paid_or_free_grants(plan):
    assert not EntitlementService()._decide(allowed_blob(), "d01", plan)


async def test_each_read_observes_current_snapshot_not_stale_process_cache():
    svc = EntitlementService()
    enabled = allowed_blob()
    disabled = allowed_blob()
    disabled["kill"]["d01"] = False
    svc._rebuild_redis_blob = AsyncMock(side_effect=[enabled, disabled])
    assert await svc.has_feature("d01", user=None)
    assert not await svc.has_feature("d01", user=None)
    assert svc._rebuild_redis_blob.await_count == 2


def test_sync_matches_async_decision_and_fails_closed():
    svc = EntitlementService()
    blob = allowed_blob()
    blob["matrix"]["pro_annual"]["b06"] = False
    svc._sync_get_blob = Mock(return_value=blob)
    assert not svc.sync_has_feature("b06", "pro_annual")
    assert svc.sync_has_feature("b06", "pro")
    svc._sync_get_blob.side_effect = RuntimeError("db unavailable")
    assert not svc.sync_has_feature("b06", "pro")
    assert svc.sync_has_feature("c05", "pro")
    assert not svc.sync_has_feature("unknown", "pro")


async def test_legacy_mutation_uses_authoritative_product_write(monkeypatch):
    from app.services.entitlement_service import entitlement_service

    write = AsyncMock()
    monkeypatch.setattr(entitlement_service, "set_kill_switch", write)
    flag = SimpleNamespace(key="d01", enabled=False)
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one=Mock(return_value=flag))
    assert await FeatureFlagService().update_flag("d01", False, db) is flag
    write.assert_awaited_once_with("d01", False, db)


async def test_always_on_flags_cannot_be_mutated_by_legacy_api():
    with pytest.raises(KeyError):
        await FeatureFlagService().update_flag("compile", False, AsyncMock())


def test_snapshot_parser_rejects_unknown_keys_and_plan_axes():
    blob = _blob_from_rows(
        [
            ("kill", "d01", "", True),
            ("kill", "typo", "", True),
            ("matrix", "d01", "pro", True),
            ("matrix", "d01", "typo", True),
        ]
    )
    assert blob["kill"] == {"d01": True}
    assert "typo" not in blob["matrix"]
    assert not EntitlementService()._decide(blob, "d01", "pro")  # Parent grants absent.


async def test_legacy_reads_reject_unknown_keys_and_obey_parent_switch(monkeypatch):
    from app.services.entitlement_service import entitlement_service

    blob = allowed_blob()
    blob["kill"]["llm_optimize"] = False
    monkeypatch.setattr(entitlement_service, "_get_blob", AsyncMock(return_value=blob))
    monkeypatch.setattr(entitlement_service, "_sync_get_blob", Mock(return_value=blob))
    legacy = FeatureFlagService()
    assert not await legacy.get_flag("d01", AsyncMock())
    assert not legacy.sync_get_flag("d01")
    assert not await legacy.get_flag("nonexistent_typo", AsyncMock())
    assert not legacy.sync_get_flag("nonexistent_typo")


async def test_collaboration_batch_uses_one_filtered_snapshot(monkeypatch):
    from contextlib import asynccontextmanager

    db = AsyncMock()
    user_rows = [("owner", "pro"), ("member", "student")]
    blob = allowed_blob()
    rows = [("kill", key, "", enabled) for key, enabled in blob["kill"].items()]
    rows += [
        ("matrix", key, plan, enabled) for plan, grants in blob["matrix"].items() for key, enabled in grants.items()
    ]
    db.execute.side_effect = [Mock(all=lambda: user_rows), Mock(all=lambda: rows)]

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr("app.database.connection.get_async_db_session", session)
    assert await EntitlementService().users_have_feature("f05", ("owner", "member"))
    assert db.execute.await_count == 2
    snapshot_query = db.execute.await_args_list[1].args[0]
    params = snapshot_query.compile().params
    assert any(value == ("f05", "collaboration") or value == ["f05", "collaboration"] for value in params.values())


async def test_collaboration_batch_rejects_missing_owner(monkeypatch):
    from contextlib import asynccontextmanager

    db = AsyncMock()
    db.execute.return_value = Mock(all=lambda: [("member", "pro")])

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr("app.database.connection.get_async_db_session", session)
    assert not await EntitlementService().users_have_feature("f05", ("owner", "member"))
    assert db.execute.await_count == 1


async def test_unavailable_snapshot_is_distinct_from_an_explicit_denial():
    service = EntitlementService()
    service._get_blob = AsyncMock(side_effect=ConnectionError("offline"))
    snapshot = await service.effective_snapshot(None)
    assert snapshot["available"] is False
    assert snapshot["features"]["compile"] is True
    service._get_blob = AsyncMock(return_value=service._empty_blob())
    assert (await service.effective_snapshot(None))["available"] is True


async def test_config_route_reports_policy_outage_instead_of_false_plan_limits(monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import get_entitlements_for_user
    from app.services.entitlement_service import entitlement_service

    monkeypatch.setattr(entitlement_service, "effective_snapshot", AsyncMock(return_value={
        "available": False, "features": {"compile": True, "d01": False},
    }))
    quota = AsyncMock()
    monkeypatch.setattr(entitlement_service, "quota_snapshot", quota)
    with pytest.raises(HTTPException) as unavailable:
        await get_entitlements_for_user(db=AsyncMock(), user_id=None)
    assert unavailable.value.status_code == 503
    quota.assert_not_awaited()

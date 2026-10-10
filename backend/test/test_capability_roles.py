"""Account-role capability intersections; these are policy tests, not UI/provider QA."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_capability_resolution import allowed_blob

from app.core.feature_registry import CAPABILITY_ROLES, FEATURE_REGISTRY, PLAN_KEYS, gateable_keys
from app.services.entitlement_service import EntitlementService, _blob_from_rows


@pytest.mark.parametrize("role", CAPABILITY_ROLES)
@pytest.mark.parametrize("feature", FEATURE_REGISTRY, ids=lambda feature: feature.key)
def test_role_feature_plan_cross_product(feature, role):
    """Every registered capability and concrete SKU obeys each account role."""
    service = EntitlementService()
    blob = allowed_blob()
    for plan in PLAN_KEYS:
        assert service._decide(blob, feature.key, plan, role)
    if not feature.gateable:
        return
    blob["roles"][role][feature.key] = False
    for plan in PLAN_KEYS:
        assert not service._decide(blob, feature.key, plan, role)
        for other in CAPABILITY_ROLES:
            if other != role:
                assert service._decide(blob, feature.key, plan, other)
    blob["roles"][role][feature.key] = True
    for plan in PLAN_KEYS:
        assert service._decide(blob, feature.key, plan, role)


@pytest.mark.parametrize("role", CAPABILITY_ROLES)
@pytest.mark.parametrize("axis", ["global", "family", "sku", "parent_role", "missing_role", "missing_cell"])
def test_role_allow_cannot_override_other_denials(role, axis):
    blob = allowed_blob()
    if axis == "global":
        blob["kill"]["d01"] = False
    elif axis == "family":
        blob["matrix"]["pro"]["d01"] = False
    elif axis == "sku":
        blob["matrix"]["student"]["d01"] = False
    elif axis == "parent_role":
        blob["roles"][role]["llm_optimize"] = False
    elif axis == "missing_role":
        del blob["roles"][role]
    else:
        del blob["roles"][role]["d01"]
    assert not EntitlementService()._decide(blob, "d01", "student", role)


@pytest.mark.parametrize("role", [None, "reader", "viewer", "owner", "ADMIN", "", "unknown"])
def test_resource_roles_and_malformed_account_roles_never_grant(role):
    service = EntitlementService()
    for key in gateable_keys():
        assert not service._decide(allowed_blob(), key, "pro", role)
    assert service._decide({}, "compile", "pro", role)


async def test_anonymous_is_separate_from_authenticated_free_user():
    service = EntitlementService()
    blob = allowed_blob()
    blob["roles"]["anonymous"]["a09"] = False
    service._get_blob = AsyncMock(return_value=blob)
    assert not await service.has_feature("a09", user=None)
    assert await service.has_feature("a09", user=SimpleNamespace(role="user", subscription_plan="free"))


async def test_effective_snapshot_obeys_role_and_retains_recovery_baselines():
    service = EntitlementService()
    blob = allowed_blob()
    blob["roles"]["admin"] = dict.fromkeys(gateable_keys(), False)
    service._get_blob = AsyncMock(return_value=blob)
    snapshot = await service.effective_snapshot(SimpleNamespace(role="admin", subscription_plan="pro"))
    assert snapshot["available"]
    assert all(snapshot["features"][feature.key] is (not feature.gateable) for feature in FEATURE_REGISTRY)


def test_role_parser_rejects_unrecognized_and_nonboolean_grants():
    blob = _blob_from_rows([
        ("role", "d01", "user", "true"), ("role", "d01", "support", True),
        ("role", "d01", "reader", True), ("role", "compile", "admin", False),
    ])
    assert blob["roles"]["user"]["d01"] is False
    assert blob["roles"]["support"]["d01"] is True
    assert "reader" not in blob["roles"]
    assert "compile" not in blob["roles"]["admin"]


def test_sync_admission_uses_current_identity_not_callers_stale_plan():
    service = EntitlementService()
    blob = allowed_blob()
    blob["identity"] = ("support", "free")
    blob["roles"]["support"]["d19"] = False
    service._sync_get_blob = Mock(return_value=blob)
    assert not service.sync_has_feature("d19", "pro", user_id="test-owner")
    service._sync_get_blob.assert_called_once_with(user_id="test-owner")
    blob["roles"]["support"]["d19"] = True
    blob["matrix"]["free"]["d19"] = False
    assert not service.sync_has_feature("d19", "pro", user_id="test-owner")
    del blob["identity"]
    assert not service.sync_has_feature("d19", "pro", user_id="missing-owner")


async def test_stale_orm_role_and_plan_never_override_current_database_identity():
    service = EntitlementService()
    blob = allowed_blob()
    blob["roles"]["user"]["b03"] = False
    service._subject_snapshot = AsyncMock(return_value=({"owner": ("user", "free")}, blob))
    stale = SimpleNamespace(id="owner", role="admin", subscription_plan="pro")
    assert not await service.has_feature("b03", user=stale)
    service._subject_snapshot.assert_awaited_once_with(("owner",))
    assert not (await service.effective_snapshot(stale))["features"]["b03"]

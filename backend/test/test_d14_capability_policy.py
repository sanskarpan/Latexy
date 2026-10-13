"""Three-level D14 policy contracts, with no database or provider required.

The cross product covers all five leaves, four account contexts, and eleven
concrete SKUs. Every permission is stored independently; true leaf grants
cannot override either ancestor, and absent/nonboolean grants fail closed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import resolve_plan_family
from app.core.feature_registry import CAPABILITY_ROLES, PLAN_KEYS, feature_ancestry
from app.services.entitlement_service import EntitlementService, _blob_from_rows
from test.test_capability_resolution import allowed_blob

LEAVES = (
    "d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image",
)


def grant_cells(blob, key, role, sku):
    """Return every independent cell checked for this identity and SKU."""
    family = resolve_plan_family(sku)
    cells = [("global", blob["kill"]), ("role", blob["roles"][role]),
             ("family", blob["matrix"][family])]
    if sku != family:
        cells.append(("sku", blob["matrix"][sku]))
    return cells


@pytest.mark.parametrize("leaf", LEAVES)
@pytest.mark.parametrize("role", CAPABILITY_ROLES)
@pytest.mark.parametrize("sku", PLAN_KEYS)
def test_d14_leaf_role_sku_intersects_all_three_levels(leaf, role, sku):
    service = EntitlementService()
    blob = allowed_blob()
    chain = tuple(item.key for item in feature_ancestry(leaf))
    assert chain == (leaf, "d14", "ai_writing")
    assert service._decide(blob, leaf, sku, role)
    for key in chain:
        for axis, cells in grant_cells(blob, key, role, sku):
            cells[key] = False
            assert not service._decide(blob, leaf, sku, role), (key, axis, role, sku)
            if key == leaf:
                # A child-only denial has no effect on any enabled sibling.
                for sibling in LEAVES:
                    if sibling != leaf:
                        assert service._decide(blob, sibling, sku, role)
                assert service._decide(blob, "d14", sku, role)
            else:
                assert all(not service._decide(blob, sibling, sku, role) for sibling in LEAVES)
            cells[key] = True
            assert service._decide(blob, leaf, sku, role)


@pytest.mark.parametrize("leaf", LEAVES)
@pytest.mark.parametrize("role", CAPABILITY_ROLES)
@pytest.mark.parametrize("sku", PLAN_KEYS)
def test_d14_missing_and_nonboolean_cells_fail_closed_at_each_level(leaf, role, sku):
    service = EntitlementService()
    blob = allowed_blob()
    for item in feature_ancestry(leaf):
        for axis, cells in grant_cells(blob, item.key, role, sku):
            del cells[item.key]
            assert not service._decide(blob, leaf, sku, role), (item.key, axis, "missing")
            for value in (None, 1, "true", [], {}):
                cells[item.key] = value
                assert not service._decide(blob, leaf, sku, role), (item.key, axis, value)
            cells[item.key] = True
            assert service._decide(blob, leaf, sku, role)


@pytest.mark.parametrize("leaf", LEAVES)
@pytest.mark.parametrize("malformed", [None, {}, {"kill": None}, {"kill": {}, "roles": None}])
def test_d14_malformed_snapshots_deny(leaf, malformed):
    assert not EntitlementService()._decide(malformed, leaf, "student", "admin")


@pytest.mark.parametrize("leaf", LEAVES)
def test_d14_unrecognized_identity_plan_and_operation_deny(leaf):
    service = EntitlementService()
    blob = allowed_blob()
    for role in (None, "owner", "reader", "ADMIN", "", "unrecognized"):
        assert not service._decide(blob, leaf, "pro", role)
    for sku in ("unknown", "admin", "pro_typo"):
        assert not service._decide(blob, leaf, sku, "admin")
    assert not service._decide(blob, leaf + "_typo", "pro", "admin")


@pytest.mark.parametrize("leaf", LEAVES)
@pytest.mark.parametrize("role", CAPABILITY_ROLES)
async def test_d14_snapshot_error_denies_every_account_context(leaf, role, monkeypatch):
    service = EntitlementService()
    monkeypatch.setattr(service, "_snapshot_for_user", AsyncMock(side_effect=ConnectionError("offline")))
    assert not await service.has_feature(leaf, user=role)


@pytest.mark.parametrize("leaf", LEAVES)
async def test_d14_new_admission_uses_fresh_snapshot(leaf, monkeypatch):
    service = EntitlementService()
    blob = allowed_blob()
    snapshot = AsyncMock(side_effect=lambda user: ("user", "student", blob))
    monkeypatch.setattr(service, "_snapshot_for_user", snapshot)
    assert await service.has_feature(leaf, user="owner")
    blob["kill"][leaf] = False
    assert not await service.has_feature(leaf, user="owner")
    blob["kill"][leaf] = True
    assert await service.has_feature(leaf, user="owner")
    assert snapshot.await_count == 3


@pytest.mark.parametrize("leaf", LEAVES)
async def test_d14_batch_snapshot_requests_leaf_and_both_ancestors(leaf, monkeypatch):
    service = EntitlementService()
    blob = allowed_blob()
    snapshot = AsyncMock(return_value=({"owner": ("support", "student")}, blob))
    monkeypatch.setattr(service, "_subject_snapshot", snapshot)
    monkeypatch.setattr(service, "_effective_plan_for_billing_status", AsyncMock(return_value="student"))
    assert await service.users_have_feature(leaf, ("owner",))
    snapshot.assert_awaited_once_with(("owner",), (leaf, "d14", "ai_writing"))
    blob["roles"]["support"]["ai_writing"] = False
    assert not await service.users_have_feature(leaf, ("owner",))


def test_d14_snapshot_parser_recognizes_only_approved_children_and_axes():
    rows = []
    for leaf in LEAVES:
        rows.extend([("kill", leaf, "", True), ("role", leaf, "admin", True),
                     ("matrix", leaf, "student", True)])
    rows.extend([("kill", "d14_unapproved", "", True),
                 ("role", "d14_latex", "owner", True),
                 ("matrix", "d14_latex", "unrecognized", True)])
    blob = _blob_from_rows(rows)
    assert set(blob["kill"]) == set(LEAVES)
    assert set(blob["roles"]["admin"]) == set(LEAVES)
    assert set(blob["matrix"]["student"]) == set(LEAVES)
    assert "owner" not in blob["roles"]
    assert "unrecognized" not in blob["matrix"]
    for leaf in LEAVES:
        # True child rows alone never manufacture missing ancestor permission.
        assert not EntitlementService()._decide(blob, leaf, "student", "admin")

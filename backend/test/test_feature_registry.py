"""Feature registry integrity tests (Admin Control Plane).

Pure, synchronous checks on the code-defined catalog — no DB / Redis.
"""

from __future__ import annotations

from app.core.feature_registry import (
    FEATURE_REGISTRY,
    PLAN_FAMILIES,
    all_feature_keys,
    gateable_keys,
    get_feature,
    is_gateable,
)


def test_registry_has_complete_inventory_and_parent_controls():
    assert len(FEATURE_REGISTRY) == 165


def test_registry_has_parent_and_granular_switches():
    assert len(gateable_keys()) == 149


def test_compile_and_new_admissions_are_gateable_without_gating_recovery():
    compile_feature = get_feature("compile")
    assert compile_feature is not None
    assert compile_feature.gateable is True
    assert is_gateable("compile") is True
    assert "compile" in gateable_keys()
    assert "compile" in all_feature_keys()
    from app.core.feature_registry import feature_ancestry
    assert [feature.key for feature in feature_ancestry("c05")] == ["c05", "compile"]
    for key in ("b01", "c01", "c05", "f10", "f11", "i01"):
        assert is_gateable(key)


def test_plan_families_exact():
    assert PLAN_FAMILIES == ["free", "basic", "pro", "byok", "team"]


def test_keys_unique():
    keys = all_feature_keys()
    assert len(keys) == len(set(keys))


def test_get_feature_known_and_unknown():
    cover = get_feature("cover_letters")
    assert cover is not None
    assert cover.key == "cover_letters"
    assert cover.gateable is True
    assert get_feature("does_not_exist") is None


def test_is_gateable_correctness():
    assert is_gateable("cover_letters") is True
    assert is_gateable("compile") is True  # parent admission switch
    assert is_gateable("totally_unknown_key") is False  # unknown → not gateable


def test_gateable_keys_are_subset_of_all_keys():
    all_keys = set(all_feature_keys())
    for key in gateable_keys():
        assert key in all_keys
    # Every gateable key is genuinely gateable.
    for key in gateable_keys():
        assert is_gateable(key) is True


def test_every_feature_has_required_fields():
    valid_categories = {
        "core", "editor", "career", "advanced", "integrations", "analytics",
    }
    for f in FEATURE_REGISTRY:
        assert f.key and isinstance(f.key, str)
        assert f.label and isinstance(f.label, str)
        assert f.category in valid_categories
        assert f.description and isinstance(f.description, str)


def test_inventory_is_complete_unique_and_has_safe_baselines():
    from app.core.feature_registry import CAPABILITY_INVENTORY, feature_ancestry
    assert len(CAPABILITY_INVENTORY) == 129
    assert len({f["inventory_id"] for f in CAPABILITY_INVENTORY}) == 129
    for row in CAPABILITY_INVENTORY:
        feature = get_feature(row["key"])
        assert feature.inventory_id == row["inventory_id"]
        assert feature_ancestry(feature.key)
        assert row["source_paths"]
        if not feature.gateable:
            assert feature.always_on_reason


def test_annual_and_student_skus_have_independent_restriction_axes():
    from app.core.feature_registry import PLAN_KEYS, PLAN_MATRIX_KEYS
    assert len(PLAN_KEYS) == 11
    assert set(PLAN_FAMILIES) <= set(PLAN_MATRIX_KEYS)
    assert {"student", "weekly", "lifetime", "basic_annual", "pro_annual", "byok_annual"} <= set(PLAN_MATRIX_KEYS)


def test_five_child_controls_preserve_product_ids_and_immutable_baselines():
    from app.core.feature_registry import CAPABILITY_SUBFEATURES, feature_ancestry
    expected = {"d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image"}
    assert {row["key"] for row in CAPABILITY_SUBFEATURES} == expected
    assert len(CAPABILITY_SUBFEATURES) == 5
    assert sum(feature.control_kind == "parent" for feature in FEATURE_REGISTRY) == 31
    assert sum(feature.control_kind == "product" for feature in FEATURE_REGISTRY) == 129
    assert sum(feature.control_kind == "subfeature" for feature in FEATURE_REGISTRY) == 5
    assert sum(not feature.gateable for feature in FEATURE_REGISTRY) == 16
    for key in expected:
        feature = get_feature(key)
        assert feature.control_kind == "subfeature"
        assert feature.inventory_id is None
        assert feature.product_inventory_id == "D14"
        assert feature.gateable
        assert [entry.key for entry in feature_ancestry(key)] == [key, "d14", "ai_writing"]
    for feature in FEATURE_REGISTRY:
        if feature.control_kind == "product":
            assert feature.product_inventory_id == feature.inventory_id
        elif feature.control_kind == "parent":
            assert feature.inventory_id is None and feature.product_inventory_id is None


def test_ancestry_rejects_missing_or_cyclic_parent(monkeypatch):
    from dataclasses import replace

    import pytest

    from app.core import feature_registry
    key = "d14_latex"
    leaf = get_feature(key)
    monkeypatch.setitem(feature_registry._REGISTRY_BY_KEY, key, replace(leaf, parent_key="missing"))
    with pytest.raises(ValueError, match="Invalid capability hierarchy"):
        feature_registry.feature_ancestry(key)
    monkeypatch.setitem(feature_registry._REGISTRY_BY_KEY, key, leaf)
    monkeypatch.setitem(feature_registry._REGISTRY_BY_KEY, "ai_writing", replace(get_feature("ai_writing"), parent_key=key))
    with pytest.raises(ValueError, match="Invalid capability hierarchy"):
        feature_registry.feature_ancestry(key)


async def test_admin_registry_exports_explicit_control_kinds_and_product_owners(monkeypatch):
    from unittest.mock import AsyncMock

    from app.core.feature_registry import CAPABILITY_ROLES, PLAN_MATRIX_KEYS
    from app.services.entitlement_service import entitlement_service
    keys = gateable_keys()
    monkeypatch.setattr(entitlement_service, "_get_blob", AsyncMock(return_value={
        "kill": dict.fromkeys(keys, True),
        "matrix": {plan: dict.fromkeys(keys, True) for plan in PLAN_MATRIX_KEYS},
        "roles": {role: dict.fromkeys(keys, True) for role in CAPABILITY_ROLES},
    }))
    state = await entitlement_service.get_state()
    registry = {row["key"]: row for row in state["registry"]}
    assert registry["ai_writing"]["control_kind"] == "parent"
    assert registry["d14"]["control_kind"] == "product"
    assert registry["d14"]["product_inventory_id"] == "D14"
    for key in ("d14_latex", "d14_table_text", "d14_table_image", "d14_math_text", "d14_math_image"):
        assert registry[key]["control_kind"] == "subfeature"
        assert registry[key]["product_inventory_id"] == "D14"
        assert registry[key]["inventory_id"] is None
        assert all(state["matrix"][plan][key] for plan in PLAN_MATRIX_KEYS)
        assert all(state["role_matrix"][role][key] for role in CAPABILITY_ROLES)


def test_byok_catalog_matches_registered_provider_families():
    from app.services.api_key_service import api_key_service

    description = get_feature("d25").description
    assert set(api_key_service.provider_classes) == {"openai", "anthropic", "openrouter"}
    assert "supported BYOK provider families are OpenAI, Anthropic and OpenRouter" in description
    assert "Gemini BYOK is not supported" in description

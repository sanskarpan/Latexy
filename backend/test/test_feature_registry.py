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


def test_registry_has_28_entries():
    assert len(FEATURE_REGISTRY) == 28


def test_registry_has_27_gateable():
    assert len(gateable_keys()) == 27


def test_compile_present_and_non_gateable():
    compile_feature = get_feature("compile")
    assert compile_feature is not None
    assert compile_feature.gateable is False
    assert is_gateable("compile") is False
    assert "compile" not in gateable_keys()
    assert "compile" in all_feature_keys()


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
    assert is_gateable("compile") is False  # known but non-gateable
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

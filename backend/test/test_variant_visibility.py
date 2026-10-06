from __future__ import annotations

import pytest

from app.services.variant_visibility_service import (
    VariantVisibility,
    apply_variant_visibility,
    prune_variant_visibility,
    validate_variant_visibility,
)

SOURCE = {
    "basics": {"name": "Taylor", "summary": "Platform engineer"},
    "experience": [
        {
            "id": "role-1",
            "title": "Engineer",
            "company": "Acme",
            "bullets": ["Built APIs", "Reduced latency"],
        },
        {
            "id": "role-2",
            "title": "Intern",
            "company": "Beta",
            "bullets": ["Shipped tests"],
        },
    ],
    "skills": [{"id": "skills-1", "name": "Core", "keywords": ["Python", "Go"]}],
}


def test_visibility_filters_sections_entries_and_list_items_without_mutating_source():
    visibility = validate_variant_visibility(
        SOURCE,
        {
            "hidden_sections": ["skills"],
            "hidden_entries": {"experience": ["role-2"]},
            "hidden_list_items": {"experience": {"role-1": [{"index": 1, "value": "Reduced latency"}]}},
        },
    )

    effective = apply_variant_visibility(SOURCE, visibility)

    assert "skills" in effective["hidden_sections"]
    assert [entry["id"] for entry in effective["experience"]] == ["role-1"]
    assert effective["experience"][0]["bullets"] == ["Built APIs"]
    assert SOURCE["experience"][0]["bullets"] == ["Built APIs", "Reduced latency"]


def test_visibility_rejects_unknown_entry_and_item_selectors():
    with pytest.raises(ValueError, match="unknown entry"):
        validate_variant_visibility(SOURCE, {"hidden_entries": {"experience": ["missing"]}})
    with pytest.raises(ValueError, match="unknown item"):
        validate_variant_visibility(
            SOURCE,
            {"hidden_list_items": {"experience": {"role-1": [{"index": 1, "value": "Not a real bullet"}]}}},
        )


def test_stale_selectors_are_pruned_after_master_content_changes():
    visibility = VariantVisibility(
        hidden_entries={"experience": ["role-2"]},
        hidden_list_items={"experience": {"role-1": [{"index": 1, "value": "Reduced latency"}]}},
    )
    changed = {**SOURCE, "experience": [{**SOURCE["experience"][0], "bullets": ["Cut latency 40%"]}]}

    pruned = prune_variant_visibility(changed, visibility.model_dump())

    assert pruned.hidden_entries == {"experience": []}
    assert pruned.hidden_list_items == {}


def test_visibility_can_hide_only_one_of_two_identical_list_items():
    source = {
        **SOURCE,
        "experience": [{**SOURCE["experience"][0], "bullets": ["Repeated", "Repeated"]}],
    }
    visibility = validate_variant_visibility(
        source,
        {"hidden_list_items": {"experience": {"role-1": [{"index": 1, "value": "Repeated"}]}}},
    )

    effective = apply_variant_visibility(source, visibility)

    assert effective["experience"][0]["bullets"] == ["Repeated"]


def test_list_item_selector_is_pruned_instead_of_hiding_reordered_content():
    visibility = VariantVisibility(
        hidden_list_items={"experience": {"role-1": [{"index": 1, "value": "Reduced latency"}]}}
    )
    reordered = {
        **SOURCE,
        "experience": [
            {
                **SOURCE["experience"][0],
                "bullets": ["Reduced latency", "Built APIs"],
            }
        ],
    }

    pruned = prune_variant_visibility(reordered, visibility.model_dump())

    assert pruned.hidden_list_items == {}

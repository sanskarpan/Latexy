"""Regression coverage for source-template synchronization (#1687)."""

from pathlib import Path
from types import SimpleNamespace

from app.scripts.seed_templates import (
    CATEGORY_DOCUMENT_TYPE,
    CATEGORY_META,
    _reconcile_existing_template,
)


def test_presentation_seed_inventory_contains_all_five_beamer_templates():
    templates = Path(__file__).parents[1] / "app" / "data" / "templates" / "presentation"
    assert sorted(path.stem for path in templates.glob("*.tex")) == [
        "beamer_madrid",
        "beamer_metropolis",
        "beamer_pitch",
        "beamer_research",
        "beamer_warsaw",
    ]
    assert "presentation" in CATEGORY_META
    assert CATEGORY_DOCUMENT_TYPE["presentation"] == "presentation"


def test_reconcile_reactivates_and_restores_source_owned_fields():
    existing = SimpleNamespace(
        latex_content="stale",
        tags=["wrong"],
        sort_order=0,
        document_type="resume",
        is_active=False,
    )

    changed = _reconcile_existing_template(
        existing,
        latex_content="beamer source",
        category="presentation",
        sort_order=1200,
        document_type="presentation",
    )

    assert changed is True
    assert existing.latex_content == "beamer source"
    assert existing.tags == ["presentation"]
    assert existing.sort_order == 1200
    assert existing.document_type == "presentation"
    assert existing.is_active is True


def test_reconcile_is_idempotent_when_row_matches_source():
    existing = SimpleNamespace(
        latex_content="canonical",
        tags=["presentation"],
        sort_order=1200,
        document_type="presentation",
        is_active=True,
    )

    changed = _reconcile_existing_template(
        existing,
        latex_content="canonical",
        category="presentation",
        sort_order=1200,
        document_type="presentation",
    )

    assert changed is False

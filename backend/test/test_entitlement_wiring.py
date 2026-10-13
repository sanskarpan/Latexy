"""Inspect declared enforcement mappings, separate from behavioral route tests.

Recognized registry keys in real route/grant declarations count as wiring. A
quoted key in an arbitrary source string or catalog is not enforcement evidence.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.core.feature_registry import FEATURE_REGISTRY, feature_ancestry
from app.middleware.capability_router import ROUTE_CAPABILITIES

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location("capability_wiring_generator", ROOT / "backend/scripts/generate_capability_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_gateable_key_has_server_or_client_enforcement():
    known_keys = {feature.key for feature in FEATURE_REGISTRY}
    subfeature_keys = {feature.key for feature in FEATURE_REGISTRY if feature.control_kind == "subfeature"}
    wired = {
        key for handlers in ROUTE_CAPABILITIES.values()
        for keys in handlers.values() for key in keys
    }
    assert wired <= known_keys, f"Unknown route grants: {wired - known_keys}"
    generator = _generator()
    # Explicit owner/content-dependent declarations and actual client grant
    # calls are inspected by the generator; all child declarations require a
    # real grant call in their named component, not merely a catalog listing.
    generated = generator.generate()
    wired.update(generator.DYNAMIC)
    wired.update(generator.declared_client_controls(known_keys, subfeature_keys))
    for feature in generated["features"]:
        if feature["serverHandlers"] or feature["dynamicOrServiceGates"] or feature["clientControls"]:
            wired.add(feature["key"])
        for child in feature["subfeatures"]:
            assert child["serverHandlers"], child["key"]
            assert child["clientControls"], child["key"]
            wired.add(child["key"])
    # A gated descendant enforces every ancestor, including a product parent.
    for key in tuple(wired):
        wired.update(feature.key for feature in feature_ancestry(key))
    missing = sorted(feature.key for feature in FEATURE_REGISTRY if feature.gateable and feature.key not in wired)
    assert not missing, f"Capabilities without an enforcement point: {missing}"


def test_arbitrary_child_key_listing_is_not_client_enforcement(tmp_path, monkeypatch):
    import pytest

    generator = _generator()
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    source = tmp_path / "frontend/src"
    (source / "lib").mkdir(parents=True)
    (source / "components").mkdir()
    (source / "lib/capability-ui-policy.ts").write_text("  d14_latex: ['components/Panel.tsx'],\n")
    panel = source / "components/Panel.tsx"
    panel.write_text("const inventory = ['d14_latex']; const label = 'd14_latex';")
    with pytest.raises(RuntimeError, match="Missing child client grant"):
        generator.declared_client_controls({"d14_latex"}, {"d14_latex"})
    panel.write_text("const allowed = allows('d14_latex');")
    assert generator.declared_client_controls({"d14_latex"}, {"d14_latex"}) == {
        "d14_latex": ["frontend/src/components/Panel.tsx"],
    }


def test_client_grant_scanner_accepts_registered_descendants_only():
    generator = _generator()
    source = "allows('d14_latex'); can('d14_math_image'); canUseFeature('unknown_leaf'); const key = 'd14_table_text'"
    assert generator.client_grants(source, {"d14_latex", "d14_math_image", "d14_table_text"}) == {"d14_latex", "d14_math_image"}

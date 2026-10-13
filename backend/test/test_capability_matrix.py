"""The published audit matrix must match the current machine-readable policies."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_audit_matrix_is_current_and_covers_all_inventory_ids():
    spec = importlib.util.spec_from_file_location("generate_capability_matrix", ROOT / "backend/scripts/generate_capability_matrix.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generated = generator.generate()
    saved = json.loads((ROOT / "docs/audits/admin-capabilities/feature-matrix.json").read_text())
    assert saved == generated, "Regenerate with python backend/scripts/generate_capability_matrix.py"
    assert saved["inventoryCount"] == 129
    ids = [feature["inventoryId"] for feature in saved["features"]]
    assert len(ids) == len(set(ids)) == 129
    for feature in saved["features"]:
        if feature["gateable"]:
            assert feature["serverHandlers"] or feature["dynamicOrServiceGates"] or feature["clientControls"], feature["inventoryId"]
        else:
            assert feature["baselineReason"], feature["inventoryId"]
        assert feature["verification"]["liveProviderOrManualEndToEnd"] == "not verified by this change"


def test_generator_includes_tenant_product_controls_but_not_admin_control_plane():
    spec = importlib.util.spec_from_file_location("generate_capability_matrix", ROOT / "backend/scripts/generate_capability_matrix.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    features = {feature["key"]: feature for feature in generator.generate()["features"]}
    for key in ("f10", "f11"):
        assert "frontend/src/app/admin/tenant/page.tsx" in features[key]["clientControls"], key
        assert any("update_tenant" in gate for gate in features[key]["dynamicOrServiceGates"]), key
    assert all(
        "frontend/src/app/admin/page.tsx" not in feature["clientControls"]
        for feature in features.values()
    )

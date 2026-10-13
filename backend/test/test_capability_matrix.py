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


def test_d14_nested_operations_preserve_129_products_and_parent_surface():
    spec = importlib.util.spec_from_file_location("d14_capability_matrix", ROOT / "backend/scripts/generate_capability_matrix.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    matrix = generator.generate()
    expected = {
        "d14_latex": "generate_latex",
        "d14_table_text": "generate_table_from_text",
        "d14_table_image": "generate_table_from_image",
        "d14_math_text": "generate_math_from_text",
        "d14_math_image": "generate_math_from_image",
    }
    assert matrix["inventoryCount"] == 129
    assert matrix["subfeatureCount"] == 5
    assert matrix["runtimeRegistryCount"] == 165
    assert matrix["runtimeGateableCount"] == 149
    assert matrix["alwaysOnCount"] == 16
    parent = next(feature for feature in matrix["features"] if feature["key"] == "d14")
    assert {child["key"] for child in parent["subfeatures"]} == set(expected)
    assert set(parent["operationCapabilities"]) == {"d14", *expected}
    assert set(parent["serverHandlers"]) == {f"backend/app/api/ai_routes.py:{handler}" for handler in expected.values()}
    for child in parent["subfeatures"]:
        assert child["inventoryId"] is None
        assert child["productInventoryId"] == "D14"
        assert child["controlKind"] == "subfeature"
        assert child["parentKey"] == "d14"
        assert child["serverHandlers"] == [f"backend/app/api/ai_routes.py:{expected[child['key']]}"]
        assert child["clientControls"] == ["frontend/src/components/LatexGeneratorPanel.tsx"]
    assert sum(len(feature["subfeatures"]) for feature in matrix["features"]) == 5

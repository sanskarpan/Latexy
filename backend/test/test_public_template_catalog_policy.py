from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_public_template_catalog.py"
_SPEC = importlib.util.spec_from_file_location("verify_public_template_catalog", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("could not load public template catalog verifier")
_POLICY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_POLICY)
_BACKEND_ORIGIN = "https://api.example.test"


def _template(template_id: str, name: str) -> dict:
    root = f"https://api.example.test/templates/{template_id}"
    return {
        "id": template_id,
        "name": name,
        "description": "Synthetic template",
        "category": "presentation",
        "category_label": "Presentation",
        "tags": [],
        "thumbnail_url": f"{root}/thumbnail",
        "pdf_url": f"{root}/pdf",
        "sort_order": 0,
        "document_type": "presentation",
    }


class PublicTemplateCatalogPolicyTests(unittest.TestCase):
    def test_disabled_feature_requires_hidden_empty_catalog(self) -> None:
        result = _POLICY.verify_public_template_catalog(
            {"features": {"b05": False}},
            [],
            ["Source Template"],
            _BACKEND_ORIGIN,
        )

        self.assertEqual(result["catalog_state"], "feature_hidden")
        self.assertEqual(result["source_template_ids"], [])

        with self.assertRaisesRegex(_POLICY.CatalogPolicyError, "feature_hidden_catalog_not_empty"):
            _POLICY.verify_public_template_catalog(
                {"features": {"b05": False}},
                [_template("123e4567-e89b-12d3-a456-426614174000", "Source Template")],
                ["Source Template"],
                _BACKEND_ORIGIN,
            )

    def test_enabled_feature_requires_every_source_template_once(self) -> None:
        with self.assertRaisesRegex(
            _POLICY.CatalogPolicyError,
            "source_presentation_template_missing_or_duplicated",
        ):
            _POLICY.verify_public_template_catalog(
                {"features": {"b05": True}},
                [],
                ["Source Template"],
                _BACKEND_ORIGIN,
            )

    def test_enabled_feature_allows_custom_entries_but_returns_source_assets_only(self) -> None:
        source_id = "123e4567-e89b-12d3-a456-426614174000"
        custom_id = "123e4567-e89b-12d3-a456-426614174001"
        result = _POLICY.verify_public_template_catalog(
            {"features": {"b05": True}},
            [
                _template(source_id, "Source Template"),
                _template(custom_id, "Admin Custom Template"),
            ],
            ["Source Template"],
            _BACKEND_ORIGIN,
        )

        self.assertEqual(result["catalog_state"], "feature_enabled")
        self.assertEqual(result["source_template_ids"], [source_id])

    def test_unknown_feature_state_fails_closed(self) -> None:
        for feature_map in ({"features": {}}, {"features": {"b05": None}}, {}):
            with self.subTest(feature_map=feature_map):
                with self.assertRaisesRegex(_POLICY.CatalogPolicyError, "invalid_public_feature_map"):
                    _POLICY.verify_public_template_catalog(feature_map, [], ["Source Template"], _BACKEND_ORIGIN)

    def test_asset_urls_must_use_exact_backend_origin_and_valid_url_syntax(self) -> None:
        template_id = "123e4567-e89b-12d3-a456-426614174000"
        for invalid_url in (
            f"https://attacker.example/templates/{template_id}/thumbnail",
            f"https://user@api.example.test/templates/{template_id}/thumbnail",
            f"https://api.example.test:invalid/templates/{template_id}/thumbnail",
            f"https://api.example.test:/templates/{template_id}/thumbnail",
            f"https://api.example.test/templates/{template_id}/thumbnail?",
            f"https://api.example.test/templates/{template_id}/thumbnail#",
        ):
            with self.subTest(url=invalid_url):
                catalog = [_template(template_id, "Source Template")]
                catalog[0]["thumbnail_url"] = invalid_url
                with self.assertRaisesRegex(
                    _POLICY.CatalogPolicyError,
                    "source_presentation_assets_unavailable",
                ):
                    _POLICY.verify_public_template_catalog(
                        {"features": {"b05": True}},
                        catalog,
                        ["Source Template"],
                        _BACKEND_ORIGIN,
                    )

    def test_valid_url_uses_normalized_backend_origin(self) -> None:
        template_id = "123e4567-e89b-12d3-a456-426614174000"
        catalog = [_template(template_id, "Source Template")]
        catalog[0]["thumbnail_url"] = (
            f"HTTPS://API.EXAMPLE.TEST:443/templates/{template_id}/thumbnail"
        )

        result = _POLICY.verify_public_template_catalog(
            {"features": {"b05": True}},
            catalog,
            ["Source Template"],
            f"{_BACKEND_ORIGIN}:443/",
        )

        self.assertEqual(result["catalog_state"], "feature_enabled")
        self.assertEqual(result["source_template_ids"], [template_id])

        with self.assertRaisesRegex(_POLICY.CatalogPolicyError, "invalid_expected_backend_origin"):
            _POLICY.verify_public_template_catalog(
                {"features": {"b05": False}},
                [],
                ["Source Template"],
                "https://api.example.test?",
            )


if __name__ == "__main__":
    unittest.main()

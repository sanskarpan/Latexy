"""Verify the anonymous presentation catalog without assuming feature access."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

_TEMPLATE_FIELDS = {
    "id", "name", "description", "category", "category_label", "tags",
    "thumbnail_url", "pdf_url", "sort_order", "document_type",
}
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class CatalogPolicyError(ValueError):
    """A fixed, safe-to-log reason that public catalog verification failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _source_names(source_dir: Path) -> list[str]:
    stems = sorted(path.stem for path in source_dir.glob("*.tex") if path.is_file())
    if not stems:
        raise CatalogPolicyError("source_presentation_catalog_empty")
    names = [stem.replace("_", " ").title() for stem in stems]
    if len(names) != len(set(names)):
        raise CatalogPolicyError("source_presentation_names_ambiguous")
    return names


def _normalized_origin(parsed: SplitResult) -> str | None:
    try:
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    try:
        normalized_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if any(char.isspace() for char in normalized_host):
        return None
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    normalized_port = "" if port in (None, 443) else f":{port}"
    return f"https://{normalized_host}{normalized_port}"


def _normalized_https_origin(value: str) -> str | None:
    if (
        not value
        or value != value.strip()
        or "?" in value
        or "#" in value
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    return _normalized_origin(parsed)


def _asset_url_matches(value: Any, template_id: str, asset_name: str, expected_origin: str) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "?" in value
        or "#" in value
        or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        _normalized_origin(parsed) == expected_origin
        and not parsed.query
        and not parsed.fragment
        and parsed.path == f"/templates/{template_id}/{asset_name}"
    )


def verify_public_template_catalog(
    feature_map: Any,
    catalog: Any,
    source_names: list[str],
    expected_origin: str,
) -> dict[str, Any]:
    """Validate anonymous B05 visibility and identify only source-owned assets."""
    normalized_expected_origin = _normalized_https_origin(expected_origin)
    if normalized_expected_origin is None:
        raise CatalogPolicyError("invalid_expected_backend_origin")
    if not isinstance(feature_map, dict) or set(feature_map) != {"features"}:
        raise CatalogPolicyError("invalid_public_feature_map")
    features = feature_map.get("features")
    if not isinstance(features, dict) or not isinstance(features.get("b05"), bool):
        raise CatalogPolicyError("invalid_public_feature_map")
    if not isinstance(catalog, list):
        raise CatalogPolicyError("invalid_public_presentation_catalog")
    if not source_names or any(not isinstance(name, str) or not name for name in source_names):
        raise CatalogPolicyError("invalid_source_presentation_catalog")
    if len(source_names) != len(set(source_names)):
        raise CatalogPolicyError("source_presentation_names_ambiguous")

    if features["b05"] is False:
        if catalog:
            raise CatalogPolicyError("feature_hidden_catalog_not_empty")
        return {
            "status": "verified",
            "catalog_state": "feature_hidden",
            "source_template_count": len(source_names),
            "source_template_ids": [],
        }

    by_name: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    for item in catalog:
        if not isinstance(item, dict) or set(item) != _TEMPLATE_FIELDS:
            raise CatalogPolicyError("invalid_public_presentation_catalog")
        if (not isinstance(item["name"], str) or not item["name"]
                or item["category"] != "presentation"
                or not isinstance(item["category_label"], str)
                or not isinstance(item["tags"], list)
                or any(not isinstance(tag, str) for tag in item["tags"])
                or (item["description"] is not None and not isinstance(item["description"], str))
                or not isinstance(item["sort_order"], int)
                or isinstance(item["sort_order"], bool)
                or item["document_type"] != "presentation"
                or not isinstance(item["id"], str)
                or _UUID_RE.fullmatch(item["id"]) is None):
            raise CatalogPolicyError("invalid_public_presentation_catalog")
        if item["id"] in seen_ids:
            raise CatalogPolicyError("duplicate_public_template_id")
        seen_ids.add(item["id"])
        by_name.setdefault(item["name"], []).append(item)

    matched_ids: list[str] = []
    for name in source_names:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            raise CatalogPolicyError("source_presentation_template_missing_or_duplicated")
        item = matches[0]
        if (
            not _asset_url_matches(item["thumbnail_url"], item["id"], "thumbnail", normalized_expected_origin)
            or not _asset_url_matches(item["pdf_url"], item["id"], "pdf", normalized_expected_origin)
        ):
            raise CatalogPolicyError("source_presentation_assets_unavailable")
        matched_ids.append(item["id"])

    return {
        "status": "verified",
        "catalog_state": "feature_enabled",
        "source_template_count": len(source_names),
        "source_template_ids": matched_ids,
    }


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-map", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "presentation",
    )
    args = parser.parse_args()
    try:
        result = verify_public_template_catalog(
            _read_json(args.feature_map),
            _read_json(args.catalog),
            _source_names(args.source_dir),
            args.expected_origin,
        )
    except CatalogPolicyError as error:
        print(json.dumps({"status": "blocked", "reason": error.reason}, sort_keys=True))
        return 1
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"status": "blocked", "reason": "public_catalog_input_unavailable"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

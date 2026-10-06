"""Source-linked builder variants with per-variant visibility overrides."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .resume_builder_service import StructuredResume

SECTION_KEYS = frozenset(
    {
        "summary",
        "experience",
        "education",
        "skills",
        "projects",
        "certifications",
        "awards",
        "languages",
        "interests",
    }
)
ENTRY_SECTION_KEYS = SECTION_KEYS - {"summary"}
LIST_FIELDS = {
    "experience": "bullets",
    "education": "highlights",
    "skills": "keywords",
    "projects": "bullets",
}


class HiddenListItem(BaseModel):
    """A stable list-item selector that will not hide a different item after reorder."""

    model_config = ConfigDict(extra="forbid", strict=True)

    index: int = Field(ge=0, le=999)
    value: str = Field(min_length=1, max_length=20_000)


class VariantVisibility(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    hidden_sections: list[str] = Field(default_factory=list, max_length=len(SECTION_KEYS))
    hidden_entries: dict[str, list[str]] = Field(default_factory=dict)
    hidden_list_items: dict[str, dict[str, list[HiddenListItem]]] = Field(default_factory=dict)

    @field_validator("hidden_sections")
    @classmethod
    def validate_hidden_sections(cls, value: list[str]) -> list[str]:
        if any(section not in SECTION_KEYS for section in value):
            raise ValueError("hidden_sections contains an unsupported section")
        return list(dict.fromkeys(value))

    @field_validator("hidden_entries")
    @classmethod
    def validate_hidden_entries(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if any(section not in ENTRY_SECTION_KEYS for section in value):
            raise ValueError("hidden_entries contains an unsupported section")
        return {section: list(dict.fromkeys(ids)) for section, ids in value.items()}

    @field_validator("hidden_list_items")
    @classmethod
    def validate_hidden_list_items(
        cls, value: dict[str, dict[str, list[HiddenListItem]]]
    ) -> dict[str, dict[str, list[HiddenListItem]]]:
        if any(section not in LIST_FIELDS for section in value):
            raise ValueError("hidden_list_items contains an unsupported section")
        return {
            section: {
                entry_id: list({(item.index, item.value): item for item in items}.values())
                for entry_id, items in entries.items()
            }
            for section, entries in value.items()
        }


def _source_indexes(source: dict[str, Any]) -> tuple[StructuredResume, dict[str, dict[str, Any]]]:
    structured = StructuredResume.model_validate(source)
    dump = structured.model_dump()
    indexes = {section: {str(item["id"]): item for item in dump.get(section, [])} for section in ENTRY_SECTION_KEYS}
    return structured, indexes


def validate_variant_visibility(source: dict[str, Any], raw: dict[str, Any] | None) -> VariantVisibility:
    visibility = VariantVisibility.model_validate(raw or {}, strict=True, extra="forbid")
    _, indexes = _source_indexes(source)
    for section, entry_ids in visibility.hidden_entries.items():
        unknown = set(entry_ids) - set(indexes[section])
        if unknown:
            raise ValueError(f"hidden_entries.{section} references an unknown entry")
    for section, entries in visibility.hidden_list_items.items():
        list_field = LIST_FIELDS[section]
        for entry_id, selectors in entries.items():
            entry = indexes[section].get(entry_id)
            if entry is None:
                raise ValueError(f"hidden_list_items.{section} references an unknown entry")
            if any(
                selector.index >= len(entry[list_field]) or entry[list_field][selector.index] != selector.value
                for selector in selectors
            ):
                raise ValueError(f"hidden_list_items.{section}.{entry_id} references an unknown item")
    return visibility


def prune_variant_visibility(source: dict[str, Any], raw: dict[str, Any] | None) -> VariantVisibility:
    """Remove selectors made stale by a later master-document edit."""
    try:
        visibility = VariantVisibility.model_validate(raw or {})
    except Exception:
        return VariantVisibility()
    _, indexes = _source_indexes(source)
    visibility.hidden_entries = {
        section: [entry_id for entry_id in ids if entry_id in indexes[section]]
        for section, ids in visibility.hidden_entries.items()
        if section in indexes
    }
    cleaned_items: dict[str, dict[str, list[HiddenListItem]]] = {}
    for section, entries in visibility.hidden_list_items.items():
        if section not in LIST_FIELDS:
            continue
        list_field = LIST_FIELDS[section]
        cleaned_entries: dict[str, list[HiddenListItem]] = {}
        for entry_id, selectors in entries.items():
            entry = indexes[section].get(entry_id)
            if entry is None:
                continue
            kept = [
                selector
                for selector in selectors
                if selector.index < len(entry[list_field]) and entry[list_field][selector.index] == selector.value
            ]
            if kept:
                cleaned_entries[entry_id] = kept
        if cleaned_entries:
            cleaned_items[section] = cleaned_entries
    visibility.hidden_list_items = cleaned_items
    return visibility


def apply_variant_visibility(source: dict[str, Any], visibility: VariantVisibility) -> dict[str, Any]:
    structured = StructuredResume.model_validate(source).model_dump()
    structured = deepcopy(structured)
    structured["hidden_sections"] = list(
        dict.fromkeys([*structured.get("hidden_sections", []), *visibility.hidden_sections])
    )
    for section in ENTRY_SECTION_KEYS:
        hidden_ids = set(visibility.hidden_entries.get(section, []))
        list_field = LIST_FIELDS.get(section)
        filtered_entries = []
        for entry in structured.get(section, []):
            if entry["id"] in hidden_ids:
                continue
            if list_field:
                hidden_selectors = {
                    (selector.index, selector.value)
                    for selector in visibility.hidden_list_items.get(section, {}).get(entry["id"], [])
                }
                entry[list_field] = [
                    value for index, value in enumerate(entry[list_field]) if (index, value) not in hidden_selectors
                ]
            filtered_entries.append(entry)
        structured[section] = filtered_entries
    return structured

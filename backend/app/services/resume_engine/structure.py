"""Closed managed hierarchy and full-sibling structural mutations."""
from __future__ import annotations

import copy

from ..resume_builder_service import SECTION_TITLES, resume_builder_service
from .semantic import DocumentConflict

ITEM_IDS = {"bullets": "bullet_ids", "highlights": "highlight_ids", "keywords": "keyword_ids", "technologies": "technology_ids"}


def managed_containers(structured: dict, nodes: list[dict]) -> list[dict]:
    containers = [{"container_id": "sections", "kind": "sections", "label": "Sections",
                   "ordered_child_ids": list(structured["section_order"]), "node_ids": []}]
    index = {"sections": containers[0]}
    for section in structured["section_order"]:
        if section == "summary":
            continue
        container_id = "section." + section + ".entries"
        container = {"container_id": container_id, "kind": "entries", "section": section,
                     "label": structured["section_titles"].get(section, SECTION_TITLES[section]),
                     "parent_id": "sections", "ordered_child_ids": [entry["id"] for entry in structured[section]], "node_ids": []}
        containers.append(container)
        index[container_id] = container
        for entry in structured[section]:
            for field, ids_field in ITEM_IDS.items():
                if field not in entry:
                    continue
                child_id = "section." + section + ".entry." + entry["id"] + "." + field
                child = {"container_id": child_id, "kind": "bullets", "section": section, "entry_id": entry["id"],
                         "field": field, "label": field.title(), "parent_id": container_id,
                         "ordered_child_ids": list(entry[ids_field]), "node_ids": []}
                containers.append(child)
                index[child_id] = child
    for node in nodes:
        path = node["_path"]
        if node["kind"] == "section_heading" or path == ["basics", "summary"]:
            container_id, child_id = "sections", node["section"]
        elif node.get("entry_id"):
            section, entry_index, field = path[:3]
            entry = structured[section][entry_index]
            container_id, child_id = "section." + section + ".entries", entry["id"]
            if len(path) == 4:
                container_id = "section." + section + ".entry." + entry["id"] + "." + field
                child_id = entry[ITEM_IDS[field]][path[3]]
        else:
            continue
        node["container_id"], node["order_child_id"] = container_id, child_id
        index[container_id]["node_ids"].append(node["node_id"])
    return containers


def apply_reorder(document: dict, *, expected_revision: int, expected_source: str,
                  container_id: str, ordered_ids: list[str]) -> tuple[str, dict]:
    if document["source_mode"] != "managed":
        raise DocumentConflict("Custom source does not support structural mutations")
    if document["content_revision"] != expected_revision or document["source_sha256"] != expected_source:
        raise DocumentConflict("Document changed; refresh before moving content")
    container = next((c for c in document["containers"] if c["container_id"] == container_id), None)
    if (container is None or len(ordered_ids) != len(container["ordered_child_ids"])
            or len(set(ordered_ids)) != len(ordered_ids) or set(ordered_ids) != set(container["ordered_child_ids"])):
        raise DocumentConflict("Moving content requires the complete current sibling permutation")
    structured = copy.deepcopy(document["_structured_content"])
    if container["kind"] == "sections":
        structured["section_order"] = list(ordered_ids)
    elif container["kind"] == "entries":
        entries = {entry["id"]: entry for entry in structured[container["section"]]}
        structured[container["section"]] = [entries[identity] for identity in ordered_ids]
    else:
        entry = next(entry for entry in structured[container["section"]] if entry["id"] == container["entry_id"])
        field = container["field"]
        ids_field = ITEM_IDS[field]
        values = dict(zip(entry[ids_field], entry[field], strict=True))
        entry[field], entry[ids_field] = [values[identity] for identity in ordered_ids], list(ordered_ids)
    rendered = resume_builder_service.render(structured, document["template_category"]).latex_content
    if len(rendered) > 1_000_000:
        raise DocumentConflict("Edited document exceeds the source limit")
    return rendered, structured

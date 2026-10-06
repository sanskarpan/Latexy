"""Shared semantic document adapter with conservative source authority."""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from typing import Any

from ..resume_builder_service import StructuredResume, resume_builder_service
from .document import digest, project_literal_bullets
from .starter import project_starter_fields


class DocumentConflict(ValueError):
    pass


class UnsupportedDocument(ValueError):
    pass


def node_hash(node_id: str, text: str) -> str:
    return digest(node_id + "\0" + text)


def _identity(section: str, entry: str, field: str, item: str = "") -> str:
    # Identity follows persisted builder IDs, independent of list position/text.
    return section + "." + hashlib.sha256((entry + "\0" + field + "\0" + item).encode()).hexdigest()[:24]


def _span(source: str, text: str) -> dict | None:
    if not text:
        return None
    escaped = resume_builder_service._escape(text.strip())
    first = source.find(escaped)
    if first < 0 or source.find(escaped, first + 1) >= 0:
        return None
    return {"start": first, "end": first + len(escaped)}


def project_managed_document(
    *,
    document_id: str,
    owner_scope: str,
    content_revision: int,
    structured_content: dict,
    category: str,
    source: str | None = None,
    template_id: str | None = None,
    structured_version: int = 1,
) -> dict:
    structured = StructuredResume.model_validate(structured_content).model_dump()
    if not resume_builder_service.is_supported_category(category):
        raise UnsupportedDocument("Template has no managed semantic adapter")
    rendered = resume_builder_service.render(structured, category).latex_content
    if source is not None and source != rendered:
        raise UnsupportedDocument("Source differs from the managed template; preserve advanced edits")
    source = rendered
    nodes: list[dict] = []
    identities: set[str] = set()
    hidden = set(structured["hidden_sections"])

    def add(node_id: str, section: str, kind: str, text: str, path: list, ai=False, entry_id=None):
        if node_id in identities:
            raise UnsupportedDocument("Duplicate persisted semantic identity")
        identities.add(node_id)
        nodes.append(
            {
                "node_id": node_id,
                "section": section,
                "kind": kind,
                "text": text,
                "node_revision": node_hash(node_id, text),
                "source_span": _span(source, text),
                "editable": True,
                "ai_editable": bool(ai and section not in hidden),
                "entry_id": entry_id,
                "_path": path,
            }
        )

    for field, text in structured["basics"].items():
        add(
            "basics." + field,
            "summary" if field == "summary" else "basics",
            "summary" if field == "summary" else "field",
            text,
            ["basics", field],
            ai=field == "summary",
        )
    for section in (
        "experience",
        "education",
        "projects",
        "skills",
        "certifications",
        "awards",
        "languages",
        "interests",
    ):
        seen_entries: set[str] = set()
        for index, entry in enumerate(structured[section]):
            entry_id = entry["id"]
            if entry_id in seen_entries:
                raise UnsupportedDocument("Duplicate persisted entry IDs")
            seen_entries.add(entry_id)
            for field, value in entry.items():
                if field == "id" or field.endswith("_ids"):
                    continue
                if isinstance(value, str):
                    add(
                        _identity(section, entry_id, field),
                        section,
                        "summary" if field in {"summary", "description"} else "field",
                        value,
                        [section, index, field],
                        ai=field in {"summary", "description"},
                        entry_id=entry_id,
                    )
                elif field in {"bullets", "highlights", "keywords", "technologies"}:
                    ids_field = {
                        "bullets": "bullet_ids",
                        "highlights": "highlight_ids",
                        "keywords": "keyword_ids",
                        "technologies": "technology_ids",
                    }[field]
                    item_ids = entry.get(ids_field)
                    for item_index, text in enumerate(value):
                        item_id = (
                            item_ids[item_index]
                            if item_ids
                            else digest(entry_id + "\0" + field + "\0" + str(item_index))[:24]
                        )
                        add(
                            _identity(section, entry_id, field, item_id),
                            section,
                            "bullet" if field in {"bullets", "highlights"} else "skill",
                            text,
                            [section, index, field, item_index],
                            ai=field == "bullets",
                            entry_id=entry_id,
                        )
    return {
        "document_id": document_id,
        "owner_scope": owner_scope,
        "source_mode": "managed",
        "schema_version": 1,
        "structured_version": structured_version,
        "content_revision": content_revision,
        "source_sha256": digest(source),
        "template_id": template_id,
        "template_category": category,
        "nodes": nodes,
        "opaque_blocks": [],
        "_structured_content": structured,
        "_source": source,
    }


def project_document(resume: Any, category: str | None = None) -> dict:
    """Renderer/frontend shared entry point; source offsets always reference exact source."""
    revision = getattr(resume, "content_revision", 1) or 1
    source = resume.latex_content
    if (
        getattr(resume, "builder_status", None) == "active"
        and getattr(resume, "content_source", None) == "builder"
        and getattr(resume, "structured_content", None)
        and category
    ):
        try:
            return project_managed_document(
                document_id=str(resume.id),
                owner_scope=str(resume.user_id),
                content_revision=revision,
                structured_content=resume.structured_content,
                category=category,
                source=source,
                template_id=getattr(resume, "selected_template_id", None),
                structured_version=getattr(resume, "structured_version", 1),
            )
        except UnsupportedDocument:
            pass
    literal = project_literal_bullets(source)
    nodes = [
        {
            "node_id": "imported." + literal.revision[:16] + "." + node.node_id,
            "section": node.section,
            "kind": "bullet",
            "text": node.text,
            "node_revision": node_hash("imported." + literal.revision[:16] + "." + node.node_id, node.text),
            "source_span": {"start": node.start, "end": node.end},
            "editable": True,
            "ai_editable": False,
            "entry_id": None,
        }
        for node in literal.nodes
    ]
    for field in project_starter_fields(source):
        node_id = "imported." + literal.revision[:16] + "." + field["local_id"]
        nodes.append(
            {
                "node_id": node_id,
                "section": field["section"],
                "kind": field["kind"],
                "text": field["text"],
                "node_revision": node_hash(node_id, field["text"]),
                "source_span": {"start": field["start"], "end": field["end"]},
                "editable": True,
                "ai_editable": False,
                "entry_id": None,
                "_encoding": "starter_plain",
            }
        )
    nodes.sort(key=lambda node: node["source_span"]["start"])
    return {
        "document_id": str(resume.id),
        "owner_scope": str(resume.user_id),
        "source_mode": "imported",
        "schema_version": 1,
        "structured_version": getattr(resume, "structured_version", 1),
        "content_revision": revision,
        "source_sha256": digest(source),
        "template_id": getattr(resume, "selected_template_id", None),
        "template_category": None,
        "nodes": nodes,
        "opaque_blocks": [{"start": 0, "end": len(source), "reason": "Custom source remains authoritative"}],
        "_source": source,
    }


def public_document(document: dict) -> dict:
    return {
        key: [{k: v for k, v in node.items() if not k.startswith("_")} for node in value] if key == "nodes" else value
        for key, value in document.items()
        if not key.startswith("_") and key != "owner_scope"
    }


def validate_plain_text(text: str, max_length=4000) -> None:
    if not isinstance(text, str) or len(text) > max_length:
        raise DocumentConflict("Text exceeds the editable field limit")
    if any(
        (unicodedata.category(char).startswith("C") and char not in "\n\t")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in text
    ):
        raise DocumentConflict("Text contains unsupported invisible controls")


def apply_node_edits(
    document: dict,
    patches: list[dict],
    *,
    expected_revision: int,
    expected_source: str,
    merge_disjoint: bool = False,
    ai_only: bool = False,
) -> tuple[str, dict | None]:
    managed = document["source_mode"] == "managed"
    if (document["content_revision"] != expected_revision or document["source_sha256"] != expected_source) and not (
        managed and merge_disjoint
    ):
        raise DocumentConflict("Document changed; refresh or reconcile your changes")
    by_id = {node["node_id"]: node for node in document["nodes"]}
    used: set[str] = set()
    structured = copy.deepcopy(document.get("_structured_content"))
    replacements = []
    for patch in patches:
        node = by_id.get(patch["node_id"])
        if not node or not node["editable"] or node["node_id"] in used or (ai_only and not node["ai_editable"]):
            raise DocumentConflict("Patch target is unavailable or protected")
        used.add(node["node_id"])
        if patch["expected_node_revision"] != node["node_revision"]:
            raise DocumentConflict("This field changed; preserve its newer text")
        text = patch["text"]
        validate_plain_text(text)
        if managed:
            target = structured
            for key in node["_path"][:-1]:
                target = target[key]
            target[node["_path"][-1]] = text
        else:
            # Imported literal fields have no formatting-aware interpretation.
            starter = node.get("_encoding") == "starter_plain"
            if re.search(r"[\\^~\r\n\t]" if starter else r"[\\{}%$&#_^~\r\n\t]", text):
                raise DocumentConflict("Custom source only supports literal single-line text")
            span = node["source_span"]
            replacements.append((span["start"], span["end"], resume_builder_service._escape(text) if starter else text))
    if managed:
        rendered = resume_builder_service.render(structured, document["template_category"]).latex_content
        if len(rendered) > 1_000_000:
            raise DocumentConflict("Edited document exceeds the source limit")
        return rendered, structured
    source = document["_source"]
    for start, end, text in sorted(replacements, reverse=True):
        source = source[:start] + text + source[end:]
    return source, None

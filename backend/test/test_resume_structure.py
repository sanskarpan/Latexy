"""Managed headings and conservative complete-permutation structure editing."""
import copy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.resume_structure_routes import StructureMutation
from app.services.resume_builder_service import StructuredResume, resume_builder_service
from app.services.resume_engine.context import build_context
from app.services.resume_engine.semantic import (
    DocumentConflict,
    apply_node_edits,
    project_document,
    project_managed_document,
    public_document,
)
from app.services.resume_engine.structure import apply_reorder


def document(structured=None, revision=1):
    return project_managed_document(document_id="resume", owner_scope="owner", content_revision=revision, category="ats_safe",
                                    structured_content=structured or {
                                        "basics": {"name": "Jane", "summary": "Developer"},
                                        "experience": [{"id": "a", "company": "Acme", "bullets": ["Built Python services", "Managed SQL data"],
                                                        "bullet_ids": ["one", "two"], "technologies": ["Python", "SQL"], "technology_ids": ["py", "sql"]},
                                                       {"id": "b", "company": "Beta", "bullets": ["Led teams"], "bullet_ids": ["three"]}],
                                        "skills": [{"id": "skills-a", "name": "Languages", "keywords": ["Python", "SQL"], "keyword_ids": ["skill-py", "skill-sql"]}],
                                    })


def reorder(doc, container_id, ordered_ids):
    return apply_reorder(doc, expected_revision=doc["content_revision"], expected_source=doc["source_sha256"],
                         container_id=container_id, ordered_ids=ordered_ids)


def test_default_headings_preserve_canonical_render_and_exclude_facts():
    doc = document()
    legacy = copy.deepcopy(doc["_structured_content"])
    legacy.pop("section_titles")
    assert resume_builder_service.render(legacy, "ats_safe").latex_content == doc["_source"]
    headings = [node for node in doc["nodes"] if node["kind"] == "section_heading"]
    assert {node["section"] for node in headings} == {"summary", "experience", "skills"}
    assert all(not node["ai_editable"] and node["source_span"] for node in headings)
    context = build_context(doc, "Python required")
    assert not {node["node_id"] for node in headings} & {fact["node_id"] for fact in context["facts"]}
    assert all("_path" not in node for node in public_document(doc)["nodes"])


def test_heading_edit_escapes_tex_and_keeps_node_and_entry_identities():
    before = document()
    heading = next(node for node in before["nodes"] if node["node_id"] == "section.experience.heading")
    text = r"Work & Growth {50%} \input{secret}"
    source, structured = apply_node_edits(before, [{"node_id": heading["node_id"], "expected_node_revision": heading["node_revision"], "text": text}],
                                          expected_revision=1, expected_source=before["source_sha256"])
    assert resume_builder_service._escape(text) in source and r"\input{secret}" not in source
    after = document(structured, revision=2)
    assert after["_source"] == source
    edited = next(node for node in after["nodes"] if node["node_id"] == heading["node_id"])
    assert edited["text"] == text and edited["node_revision"] != heading["node_revision"]
    old_fields = {node["node_id"]: node["node_revision"] for node in before["nodes"] if node["kind"] != "section_heading"}
    assert old_fields == {node["node_id"]: node["node_revision"] for node in after["nodes"] if node["kind"] != "section_heading"}
    with pytest.raises(DocumentConflict):
        apply_node_edits(before, [{"node_id": heading["node_id"], "expected_node_revision": heading["node_revision"], "text": "Invented"}],
                         expected_revision=1, expected_source=before["source_sha256"], ai_only=True)


@pytest.mark.parametrize("titles", [{"unknown": "Unknown"}, {"experience": ""}, {"experience": "a" * 81},
                                    {"experience": "Hidden\u200b"}, {"experience": "Two\nlines"}, {"experience": 12}])
def test_heading_schema_rejects_invalid_or_invisible_titles(titles):
    with pytest.raises(ValidationError):
        StructuredResume(section_titles=titles)


@pytest.mark.parametrize("category", ["ats_safe", "minimal", "software_engineering", "executive", "graduate"])
def test_custom_heading_labels_render_in_every_supported_managed_family(category):
    data = document()["_structured_content"]
    data["section_titles"]["experience"] = "Work & Impact"
    projected = project_managed_document(document_id="r", owner_scope="u", content_revision=1,
                                         structured_content=data, category=category)
    assert r"Work \& Impact" in projected["_source"]
    assert next(node for node in projected["nodes"] if node["node_id"] == "section.experience.heading")["source_span"]


def test_hidden_heading_not_projected_and_duplicate_visible_text_has_no_overlay_span():
    data = document()["_structured_content"]
    data["hidden_sections"] = ["summary"]
    data["section_titles"]["experience"] = "Skills"
    doc = document(data)
    headings = [node for node in doc["nodes"] if node["kind"] == "section_heading"]
    assert not any(node["section"] == "summary" for node in headings)
    assert all(node["source_span"] is None for node in headings if node["text"] == "Skills")


@pytest.mark.parametrize("container_id,ids", [("section.experience.entries", ["b", "a"]),
                                              ("section.experience.entry.a.bullets", ["two", "one"]),
                                              ("section.experience.entry.a.technologies", ["sql", "py"]),
                                              ("section.skills.entry.skills-a.keywords", ["skill-sql", "skill-py"])])
def test_reorder_keeps_all_semantic_identities_and_item_value_pairings(container_id, ids):
    before = document()
    source, data = reorder(before, container_id, ids)
    after = document(data, 2)
    assert after["_source"] == source
    assert {n["node_id"]: (n["text"], n["node_revision"]) for n in before["nodes"]} == {
        n["node_id"]: (n["text"], n["node_revision"]) for n in after["nodes"]}
    container = next(c for c in after["containers"] if c["container_id"] == container_id)
    assert container["ordered_child_ids"] == ids


def test_section_order_reorders_exact_blocks_and_preserves_hidden_empty_slots():
    before = document()
    order = list(reversed(before["_structured_content"]["section_order"]))
    source, data = reorder(before, "sections", order)
    assert data["section_order"] == order and source.index("Skills") < source.index("Experience") < source.index("Summary")


@pytest.mark.parametrize("container,ids", [("section.experience.entries", ["a"]), ("section.experience.entries", ["a", "a"]),
                                         ("section.experience.entries", ["a", "skills-a"]), ("sections", ["experience"]),
                                         ("_structured_content", [])])
def test_incomplete_duplicate_cross_scope_and_arbitrary_path_commands_reject(container, ids):
    before = document()
    with pytest.raises(DocumentConflict):
        reorder(before, container, ids)
    assert before["_source"] == document()["_source"]


def test_stale_revision_hash_and_imported_source_fail_closed():
    doc = document()
    for revision, source in ((2, doc["source_sha256"]), (1, "0" * 64)):
        with pytest.raises(DocumentConflict):
            apply_reorder(doc, expected_revision=revision, expected_source=source, container_id="section.experience.entries", ordered_ids=["b", "a"])
    imported = project_document(SimpleNamespace(id="i", user_id="u", latex_content=doc["_source"] + "%custom", content_revision=1))
    with pytest.raises(DocumentConflict):
        reorder(imported, "sections", [])
    assert imported["_source"] == doc["_source"] + "%custom"
    with pytest.raises(ValidationError):
        StructureMutation(expected_content_revision=1, expected_source_sha256=doc["source_sha256"], container_id="sections", ordered_ids=[], arbitrary_path=[])

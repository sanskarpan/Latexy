"""Source-authoritative persistent IDs reject guessed or ambiguous mappings."""
import copy
from types import SimpleNamespace

import pytest

from app.services.resume_engine.imported_identity import bind_projection, reconcile_projection, seed_projection
from app.services.resume_engine.semantic import apply_node_edits, project_document

SOURCE = """\\documentclass{article}
\\begin{document}
\\section{Experience}
\\begin{itemize}
\\item Built Python services
\\item Built SQL services
\\end{itemize}
\\end{document}
"""


def resume(source=SOURCE, metadata=None, revision=1):
    return SimpleNamespace(id="document", user_id="owner", latex_content=source, content_revision=revision,
                           imported_projection=metadata, structured_version=1, selected_template_id=None)


def initial(source=SOURCE):
    return seed_projection(project_document(resume(source)))


def identities(document):
    return {node["text"]: node["node_id"] for node in document["nodes"]}


def test_unrelated_opaque_source_edit_retains_identity_and_node_revision():
    previous, metadata = initial()
    source = "% source-only note\n" + SOURCE
    fresh = project_document(resume(source, metadata, 2))
    revised, metadata = reconcile_projection(fresh, previous)
    assert identities(revised) == identities(previous)
    assert [n["node_revision"] for n in revised["nodes"]] == [n["node_revision"] for n in previous["nodes"]]
    assert revised["_source"] == source and all(not node["ai_editable"] for node in revised["nodes"])
    assert identities(project_document(resume(source, metadata, 2))) == identities(previous)


def test_unique_exact_reorder_and_insertion_preserve_only_proven_fields():
    previous, _ = initial()
    source = SOURCE.replace("\\item Built Python services\n\\item Built SQL services",
                            "\\item Built Java services\n\\item Built SQL services\n\\item Built Python services")
    revised, _ = reconcile_projection(project_document(resume(source, revision=2)), previous)
    mapping = identities(revised)
    assert mapping["Built Python services"] == identities(previous)["Built Python services"]
    assert mapping["Built SQL services"] == identities(previous)["Built SQL services"]
    assert mapping["Built Java services"] not in identities(previous).values()


def test_duplicates_never_guess_identity_after_source_change():
    source = SOURCE.replace("Built SQL services", "Built Python services")
    previous, metadata = initial(source)
    assert identities(project_document(resume(source, metadata))) == identities(previous)
    revised, _ = reconcile_projection(project_document(resume("% changed\n" + source, revision=2)), previous)
    assert {n["node_id"] for n in previous["nodes"]}.isdisjoint(n["node_id"] for n in revised["nodes"])


def test_delete_then_readd_does_not_resurrect_old_identity():
    previous, _ = initial()
    removed = SOURCE.replace("\\item Built Python services\n", "")
    middle, _ = reconcile_projection(project_document(resume(removed, revision=2)), previous)
    final, _ = reconcile_projection(project_document(resume(SOURCE, revision=3)), middle)
    assert identities(final)["Built Python services"] != identities(previous)["Built Python services"]
    assert identities(final)["Built SQL services"] == identities(previous)["Built SQL services"]


def test_explicit_exact_node_edit_keeps_edited_identity_and_changes_revision():
    previous, _ = initial()
    node = previous["nodes"][0]
    patch = {"node_id": node["node_id"], "expected_node_revision": node["node_revision"], "text": "Developed Python services"}
    source, _ = apply_node_edits(previous, [patch], expected_revision=1, expected_source=previous["source_sha256"])
    revised, _ = reconcile_projection(project_document(resume(source, revision=2)), previous, [patch])
    assert revised["nodes"][0]["node_id"] == node["node_id"]
    assert revised["nodes"][0]["node_revision"] != node["node_revision"]
    assert revised["nodes"][1]["node_id"] == previous["nodes"][1]["node_id"]
    with pytest.raises(ValueError, match="differs"):
        reconcile_projection(project_document(resume("% extra\n" + source, revision=2)), previous, [patch])


@pytest.mark.parametrize("corruption", ["span", "id", "owner", "source"])
def test_corrupted_or_cross_owner_metadata_never_binds(corruption):
    previous, metadata = initial()
    changed = copy.deepcopy(metadata)
    if corruption == "span":
        changed["nodes"][0]["start"] += 1
    elif corruption == "id":
        changed["nodes"][1]["node_id"] = changed["nodes"][0]["node_id"]
    elif corruption == "owner":
        changed["owner_scope"] = "another owner"
    else:
        changed["source_sha256"] = "0" * 64
    fresh = project_document(resume(), use_imported_identity=False)
    assert bind_projection(fresh, changed) is fresh


def test_opaque_macro_change_drops_unprovable_field_ids():
    previous, _ = initial()
    source = SOURCE.replace("Built Python services", r"Built \textbf{Python} services")
    revised, _ = reconcile_projection(project_document(resume(source, revision=2)), previous)
    assert "Built Python services" not in identities(revised)
    assert identities(revised)["Built SQL services"] == identities(previous)["Built SQL services"]


def test_projection_budget_keeps_source_opaque_without_blocking_technical_editor():
    source = SOURCE.replace("\\item Built Python services", "\n".join("\\item Literal field " + str(i) for i in range(410)))
    projected, metadata = initial(source)
    assert not projected["nodes"] and metadata["opaque"] is True
    assert projected["_source"] == source
    assert not project_document(resume(source, metadata))["nodes"]

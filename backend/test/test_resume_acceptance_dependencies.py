"""Factual dependencies remain frozen even when target edits are disjoint."""

import copy

import pytest

from app.services.resume_engine.acceptance import validate_factual_dependencies
from app.services.resume_engine.context import build_context
from app.services.resume_engine.semantic import DocumentConflict, node_hash


def node(identity, text, section="experience", entry="role-a"):
    return {"node_id": identity, "node_revision": node_hash(identity, text), "kind": "bullet", "text": text,
            "section": section, "entry_id": entry, "ai_editable": True}


@pytest.fixture
def review():
    document = {"document_id": "document", "content_revision": 1, "source_sha256": "a" * 64,
                "nodes": [node("bullet-a", "Built Python services"), node("company-a", "Acme"),
                          node("bullet-b", "Built SQL services", entry="role-b"),
                          node("name", "Jane", "basics", None)]}
    context = build_context(document, "Python required")
    patch = {"patch_id": "patch-a", "node_id": "bullet-a", "text": "Developed Python services",
             "expected_node_revision": document["nodes"][0]["node_revision"],
             "evidence_ids": [context["facts"][0]["fact_id"]]}
    return document, context, patch


def validate(review, *, effort="quick", statuses=None, candidates=None):
    document, context, patch = review
    validate_factual_dependencies(document, context, [patch], candidates or [patch], statuses or {}, effort=effort)


def test_supporting_company_change_blocks_disjoint_target(review):
    document, _, _ = review
    document["nodes"][1] = node("company-a", "Other company")
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review)


def test_quick_unrelated_role_change_can_merge(review):
    document, _, _ = review
    document["nodes"][2] = node("bullet-b", "Built SQL reporting services", entry="role-b")
    validate(review)


@pytest.mark.parametrize("effort", ["standard", "deep"])
def test_global_review_rechecks_all_facts(review, effort):
    document, _, _ = review
    document["nodes"][3] = node("name", "Someone else", "basics", None)
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review, effort=effort)


def test_explicit_external_evidence_rechecked_without_blocking_other_quick_roles(review):
    document, context, patch = review
    patch["evidence_ids"].append(context["facts"][2]["fact_id"])
    validate(review)
    document["nodes"][2] = node("bullet-b", "No SQL experience", entry="role-b")
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review)


def test_added_or_removed_supporting_fields_require_new_review(review):
    document, _, _ = review
    document["nodes"].append(node("new-fact", "Managed twelve engineers"))
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review)
    document["nodes"].pop()
    document["nodes"].pop(1)
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review)


def test_prior_explicit_acceptance_from_same_run_can_restate_fact(review):
    document, context, _ = review
    prior = {"patch_id": "prior", "node_id": "company-a", "text": "ACME",
             "expected_node_revision": document["nodes"][1]["node_revision"]}
    document["nodes"][1] = node("company-a", "ACME")
    validate(review, statuses={"prior": "accepted"}, candidates=[prior])
    document["nodes"][1] = node("company-a", "Unreviewed company")
    with pytest.raises(DocumentConflict, match="Supporting experience changed"):
        validate(review, statuses={"prior": "accepted"}, candidates=[prior])


def test_validation_does_not_mutate_frozen_context(review):
    _, context, _ = review
    frozen = copy.deepcopy(context)
    validate(review, effort="standard")
    assert context == frozen

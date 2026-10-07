"""Literal aliases guide coverage without inventing experience or entailment."""
import pytest

from app.services.resume_engine.context import build_context
from app.services.resume_engine.semantic_patches import validate_candidates
from app.services.resume_engine.service import plan_groups
from app.services.resume_engine.skills import skill_mention

from .test_resume_semantic_engine import document


def context(text, jd="PostgreSQL required"):
    doc = document(text)
    return doc, build_context(doc, jd)


def test_alias_coverage_and_priority_are_positive_source_mentions():
    doc, ctx = context("Built Postgres services")
    assert not ctx["coverage"][0]["unsupported"]
    assert ctx["coverage"][0]["missing_skills"] == []
    assert ctx["facts"][-1]["confirmation_state"] == "source_statement_unverified"
    assert skill_mention("postgresql", "Built Postgres services") == "positive"
    nodes = [dict(doc["nodes"][-1], node_id="irrelevant", text="Built other services", entry_id="a"),
             dict(doc["nodes"][-1], node_id="relevant", text="Built Postgres services", entry_id="b")]
    assert plan_groups({"nodes": nodes}, None, "quick", ctx["requirements"])[0][0]["node_id"] == "relevant"


def test_negated_skill_is_unknown_and_never_positive_coverage():
    _, ctx = context("No Python experience", "Python required")
    coverage = ctx["coverage"][0]
    assert coverage["unsupported"] and not coverage["evidence_ids"]
    assert coverage["ambiguous_skills"] == ["python"]
    assert coverage["ambiguous_evidence_ids"]
    assert coverage["missing_skills"] == []
    assert skill_mention("python", "Built Python services. No Java experience") == "positive"
    assert skill_mention("python", "Built Python, not Java services") == "ambiguous"


@pytest.mark.parametrize("text", ["go to market", "Go-to-market strategy", "We go beyond expectations"])
def test_go_verb_is_not_golang_evidence(text):
    assert skill_mention("golang", text) == "ambiguous"


@pytest.mark.parametrize("text", ["Go", "Go programming language", "Built Golang services"])
def test_explicit_go_technology_context_remains_supported(text):
    assert skill_mention("golang", text) == "positive"


def test_alias_restatement_still_requires_independent_review():
    doc, ctx = context("Built Postgres services")
    node = next(n for n in doc["nodes"] if n["text"] == "Built Postgres services")
    fact = next(f for f in ctx["facts"] if f["node_id"] == node["node_id"])
    candidate = {"node_id": node["node_id"], "expected_node_revision": node["node_revision"],
                 "text": "Developed PostgreSQL services", "evidence_ids": [fact["fact_id"]],
                 "requirement_ids": [], "reason": "Explicit alias restatement"}
    accepted, rejected = validate_candidates({"patches": [candidate], "missing_evidence": []}, doc, ctx, {node["node_id"]})
    assert not rejected and len(accepted) == 1
    assert accepted[0]["validation"] == "awaiting_independent_review"

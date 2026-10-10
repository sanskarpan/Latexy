"""User wording choices stay bounded, source-scoped and separate from facts."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.resume_engine.context import build_context
from app.services.resume_engine.memory import project_choices
from app.services.resume_engine.requirements import extract_requirements
from app.services.resume_engine.semantic import node_hash
from app.services.resume_engine.semantic_patches import validate_candidates
from app.services.resume_engine.stages import stage_fingerprint


def document(text="Built products"):
    return {"document_id": "fixture", "content_revision": 1, "source_sha256": "a" * 64,
            "nodes": [{"node_id": "summary.fixture", "node_revision": node_hash("summary.fixture", text),
                       "text": text, "section": "summary", "kind": "summary", "entry_id": None,
                       "ai_editable": True}]}


def previous_run(doc, target="Delivered products", decision="rejected", jd="Build products"):
    node = doc["nodes"][0]
    result = {"patches": [{"node_id": node["node_id"], "expected_node_revision": node["node_revision"],
                           "text": target, "patch_id": "patch.fixture"}]}
    result["result_sha256"] = stage_fingerprint(result)
    return SimpleNamespace(context_payload={"requirements": extract_requirements(jd)}, result=result,
                           decisions={"patches": {"patch.fixture": decision}})


@pytest.mark.parametrize("change", ["jd", "language", "version", "source", "tamper"])
def test_changed_target_source_or_corrupt_result_invalidates_choice(change):
    doc = document()
    run = previous_run(doc)
    requirements = extract_requirements("Build products")
    if change in {"jd", "language", "version"}:
        key = "jd_hash" if change == "jd" else change
        requirements[key] = "different"
    elif change == "source":
        doc = document("Created products")
    else:
        run.result["patches"][0]["text"] = "Tampered"
    assert project_choices([run], doc, requirements)["choices"] == []


def test_acceptance_is_reused_only_when_that_text_is_current_source():
    before = document()
    run = previous_run(before, decision="accepted")
    requirements = extract_requirements("Build products")
    assert not project_choices([run], before, requirements)["choices"]
    current = document("Delivered products")
    memory = project_choices([run], current, requirements)
    assert memory["choices"][0]["decision"] == "accepted"
    assert memory["provenance"] == "user_wording_choice_not_factual_verification"


def test_rejected_alternative_cannot_be_reintroduced_as_a_candidate_or_fact():
    doc = document()
    context = build_context(doc, "Build products")
    facts = deepcopy(context["facts"])
    context["decision_memory"] = project_choices([previous_run(doc)], doc, context["requirements"])
    raw = {"node_id": "summary.fixture", "expected_node_revision": doc["nodes"][0]["node_revision"],
           "text": "Delivered products", "evidence_ids": [facts[0]["fact_id"]], "requirement_ids": [],
           "reason": "Clearer wording"}
    valid, rejected = validate_candidates({"patches": [raw], "missing_evidence": []}, doc, context, {raw["node_id"]})
    assert not valid and "already rejected" in rejected[0]["reason"]
    assert context["facts"] == facts
    # A genuinely different alternative still proceeds to independent review.
    raw["text"] = "Created products"
    valid, rejected = validate_candidates({"patches": [raw], "missing_evidence": []}, doc, context, {raw["node_id"]})
    assert len(valid) == 1 and not rejected


def test_choice_history_deduplicates_and_caps_prompt_size():
    doc = document()
    requirements = extract_requirements("Build products")
    runs = [previous_run(doc, target="Alternative " + str(index)) for index in range(30)]
    runs.insert(1, runs[0])
    choices = project_choices(runs, doc, requirements)["choices"]
    assert len(choices) == 16
    assert len({choice["alternative_text"] for choice in choices}) == 16
    huge = previous_run(doc, target="x" * 1001)
    assert not project_choices([huge], doc, requirements)["choices"]

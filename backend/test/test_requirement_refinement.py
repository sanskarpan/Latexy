"""JD goals retain literal evidence and never become applicant facts."""

import copy

import pytest

from app.services.resume_engine.context import build_context
from app.services.resume_engine.requirements import (
    extract_requirements,
    refinement_cache_id,
    refinement_excerpts,
    validate_refinement,
)
from app.services.resume_engine.semantic import project_managed_document


def response(extracted, phrase="Budget management", canonical="budget management"):
    excerpt = extracted["requirements"][0]
    text = excerpt["excerpt"]
    first = text.index(phrase)
    return {"items": [{"excerpt_id": excerpt["requirement_id"], "start": 0, "end": len(text), "text": text,
                       "importance": "required", "skills": [{"start": first, "end": first + len(phrase),
                                                                "text": phrase, "canonical": canonical}]}]}


def test_nontechnical_source_phrase_enriches_goals_without_altering_facts():
    base = extract_requirements("Budget management required")
    refined = validate_refinement(response(base), base)
    doc = project_managed_document(document_id="r", owner_scope="u", content_revision=1,
                                  structured_content={"experience": [{"id": "a", "bullets": ["Built Python services"]}]},
                                  category="ats_safe")
    original, updated = build_context(doc, "Budget management required", requirements=base), build_context(doc, "Budget management required", requirements=refined)
    assert original["facts"] == updated["facts"]
    assert refined["requirements"][0]["skills"] == ["budget management"]
    assert updated["coverage"][0]["missing_skills"] == ["budget management"]


@pytest.mark.parametrize("field,value", [("excerpt_id", "unknown"), ("start", True), ("end", 5000),
                                         ("text", "Invented requirement"), ("importance", "preferred")])
def test_unknown_or_changed_requirement_evidence_rejected(field, value):
    base = extract_requirements("Budget management required")
    value_response = response(base)
    value_response["items"][0][field] = value
    with pytest.raises(ValueError):
        validate_refinement(value_response, base)


def test_model_cannot_alias_unlisted_phrase_or_shorten_evidence():
    base = extract_requirements("Budget management required")
    with pytest.raises(ValueError, match="alias"):
        validate_refinement(response(base, canonical="financial leadership"), base)
    invalid = response(base)
    invalid["items"][0]["skills"][0]["text"] = "Budget"
    with pytest.raises(ValueError, match="span"):
        validate_refinement(invalid, base)


def test_nearby_negation_cannot_be_removed_by_selecting_a_positive_subspan():
    base = extract_requirements("Budget management is not required")
    assert not base["requirements"][0]["skills"]
    value = response(base)
    value["items"][0].update(end=len("Budget management"), text="Budget management", importance="responsibility")
    with pytest.raises(ValueError, match="Negated"):
        validate_refinement(value, base)


def test_mixed_importance_must_be_split_into_literal_clauses():
    base = extract_requirements("Budget management required; SQL preferred")
    with pytest.raises(ValueError, match="importance"):
        validate_refinement(response(base), base)
    value = response(base)
    text = "Budget management required"
    value["items"][0].update(end=len(text), text=text)
    result = validate_refinement(value, base)["requirements"]
    assert any(item["importance"] == "required" and item["skills"] == ["budget management"] for item in result)
    assert any("SQL preferred" in item["excerpt"] for item in result)


def test_omitted_ambiguous_requirements_remain_visible_and_cache_is_exact_owner_source():
    base = extract_requirements("Budget management required")
    assert validate_refinement({"items": []}, base)["requirements"] == base["requirements"]
    assert refinement_cache_id("a", "Budget management required", "en") != refinement_cache_id("b", "Budget management required", "en")
    assert refinement_cache_id("a", "Budget management required", "en") != refinement_cache_id("a", "budget management required", "en")
    oversized = copy.deepcopy(base)
    oversized["requirements"] *= 100
    assert len(refinement_excerpts(oversized)) <= 12


def test_refinement_cache_invalidates_older_deterministic_extraction(monkeypatch):
    from app.services.resume_engine import requirements

    current = refinement_cache_id("u", "Python is not required", "en")
    assert extract_requirements("Python is not required")["version"] == "requirements-v2"
    monkeypatch.setattr(requirements, "EXTRACTION_VERSION", "requirements-v1")
    assert refinement_cache_id("u", "Python is not required", "en") != current


@pytest.mark.parametrize("hidden", ["\u200b", "\u202e", "\u2028", "\x00"])
def test_even_literal_hidden_control_characters_are_rejected(hidden):
    phrase = "Budget" + hidden + " management"
    base = extract_requirements(phrase + " required")
    with pytest.raises(ValueError):
        validate_refinement(response(base, phrase=phrase, canonical=phrase.casefold()), base)


def test_partially_refined_full_context_cannot_exceed64_requirements():
    base = extract_requirements("\n".join(f"Budget management required for department {number}" for number in range(64)))
    value = response(base)
    value["items"][0].update(end=len("Budget management required"), text="Budget management required")
    with pytest.raises(ValueError, match="context limit"):
        validate_refinement(value, base)

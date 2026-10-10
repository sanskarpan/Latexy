"""Immutable source facts and requirement coverage; model memory is never evidence."""

from __future__ import annotations

from .document import digest
from .requirements import ALIASES, extract_requirements
from .skills import positive_skill_mention, skill_mention


def build_context(document: dict, job_description: str, *, language="en", requirements: dict | None = None) -> dict:
    facts = []
    for node in document["nodes"]:
        if node["kind"] == "section_heading" or not node["text"].strip():
            continue
        facts.append(
            {
                "fact_id": "fact." + digest(node["node_id"] + "\0" + node["node_revision"])[:24],
                "node_id": node["node_id"],
                "node_revision": node["node_revision"],
                "text": node["text"],
                "section": node["section"],
                "entry_id": node.get("entry_id"),
                "immutable": not node["ai_editable"],
                "confirmation_state": "source_statement_unverified",
            }
        )
    extracted = requirements or extract_requirements(job_description, language=language)
    source_resume = "\n".join(fact["text"] for fact in facts)
    coverage = []
    for requirement in extracted["requirements"]:
        supporting = []
        ambiguous = []
        for fact in facts:
            if any(positive_skill_mention(skill, fact["text"]) and positive_skill_mention(skill, source_resume)
                   for skill in requirement["skills"]):
                supporting.append(fact["fact_id"])
            if any(skill_mention(skill, fact["text"]) == "ambiguous" for skill in requirement["skills"]):
                ambiguous.append(fact["fact_id"])
        missing = [
            skill
            for skill in requirement["skills"]
            if skill_mention(skill, source_resume) == "absent"
        ]
        coverage.append(
            {
                "requirement_id": requirement["requirement_id"],
                "evidence_ids": supporting,
                "missing_skills": missing,
                "ambiguous_skills": [skill for skill in requirement["skills"] if skill_mention(skill, source_resume) == "ambiguous"],
                "ambiguous_evidence_ids": ambiguous,
                "support_kind": "literal_source_mention_not_factual_verification",
                "unsupported": not supporting,
            }
        )
    return {
        "version": "facts-v3",
        "document_id": document["document_id"],
        "content_revision": document["content_revision"],
        "source_sha256": document["source_sha256"],
        "facts": facts,
        "requirements": extracted,
        "coverage": coverage,
        "aliases": ALIASES,
    }

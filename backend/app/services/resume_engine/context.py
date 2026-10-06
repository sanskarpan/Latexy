"""Immutable source facts and requirement coverage; model memory is never evidence."""

from __future__ import annotations

import re

from .document import digest
from .requirements import ALIASES, extract_requirements


def build_context(document: dict, job_description: str, *, language="en", requirements: dict | None = None) -> dict:
    facts = []
    for node in document["nodes"]:
        if not node["text"].strip():
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
    normalized_resume = " ".join(fact["text"] for fact in facts).casefold()
    coverage = []
    for requirement in extracted["requirements"]:
        supporting = []
        for fact in facts:
            lower = fact["text"].casefold()
            if any(re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", lower) for skill in requirement["skills"]):
                supporting.append(fact["fact_id"])
        missing = [
            skill
            for skill in requirement["skills"]
            if not re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", normalized_resume)
        ]
        coverage.append(
            {
                "requirement_id": requirement["requirement_id"],
                "evidence_ids": supporting,
                "missing_skills": missing,
                "unsupported": not supporting,
            }
        )
    return {
        "version": "facts-v1",
        "document_id": document["document_id"],
        "content_revision": document["content_revision"],
        "source_sha256": document["source_sha256"],
        "facts": facts,
        "requirements": extracted,
        "coverage": coverage,
        "aliases": ALIASES,
    }

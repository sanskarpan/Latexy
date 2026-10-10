"""Source-grounded candidate operations; assertions from the generator are not proof."""

from __future__ import annotations

import re

from .document import digest
from .requirements import _TECH as TECHNOLOGIES
from .requirements import ALIASES
from .semantic import DocumentConflict, validate_plain_text
from .skills import canonical_skill, positive_skill_mention, skill_mention

PATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["patches", "missing_evidence"],
    "properties": {
        "patches": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node_id", "expected_node_revision", "text", "evidence_ids", "requirement_ids", "reason"],
                "properties": {
                    key: {"type": "string"} for key in ("node_id", "expected_node_revision", "text", "reason")
                }
                | {key: {"type": "array", "items": {"type": "string"}} for key in ("evidence_ids", "requirement_ids")},
            },
        },
        "missing_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
    },
}

VERIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["patch_id", "supported", "reason"],
                "properties": {
                    "patch_id": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reject_patch_ids", "warnings"],
    "properties": {
        "reject_patch_ids": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}

_NUMBERS = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:%|x)?", re.I)
_RELATION = re.compile(
    r"\b(?:not|never|no|without|except|only|from|to|versus|before|after|less|more|over|under|at least|at most)\b", re.I
)
_PROMOTIONS = re.compile(
    r"\b(?:led|managed|owned|directed|supervised|architected|spearheaded|awarded|certified|expert|advanced|fluent|successfully|efficiently)\b",
    re.I,
)
_ORDERED_ANCHORS = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(x) for x in sorted((*TECHNOLOGIES, *ALIASES), key=len, reverse=True))
    + r"|[+-]?\d+(?:[.,]\d+)*(?:%|x)?|not|never|no|without|except|only|from|to|versus|before|after|less|more|over|under)(?!\w)",
    re.I,
)


def _present(term: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))


def validate_candidates(
    value: dict, document: dict, context: dict, allowed_ids: set[str]
) -> tuple[list[dict], list[dict]]:
    """Deterministic rejection precedes independent entailment review and user acceptance.

    This deliberately rejects some legitimate paraphrases. It is a guard, not a
    claim that lexical checks prove semantic equivalence.
    """
    if (
        set(value) != {"patches", "missing_evidence"}
        or not isinstance(value["patches"], list)
        or len(value["patches"]) > 6
    ):
        raise DocumentConflict("Invalid patch response")
    if (
        not isinstance(value["missing_evidence"], list)
        or len(value["missing_evidence"]) > 20
        or any(not isinstance(x, str) or len(x) > 1500 for x in value["missing_evidence"])
    ):
        raise DocumentConflict("Invalid missing evidence response")
    nodes = {n["node_id"]: n for n in document["nodes"]}
    facts = {f["fact_id"]: f for f in context["facts"]}
    requirements = {r["requirement_id"] for r in context["requirements"]["requirements"]}
    accepted, rejected, seen = [], [], set()
    for raw in value["patches"]:
        try:
            keys = {"node_id", "expected_node_revision", "text", "evidence_ids", "requirement_ids", "reason"}
            if not isinstance(raw, dict) or set(raw) != keys:
                raise DocumentConflict("Unexpected operation shape")
            node = nodes.get(raw["node_id"])
            if not node or node["node_id"] not in allowed_ids or not node["ai_editable"] or node["node_id"] in seen:
                raise DocumentConflict("Protected, duplicate or unknown target")
            seen.add(node["node_id"])
            if node["node_revision"] != raw["expected_node_revision"]:
                raise DocumentConflict("Stale node revision")
            validate_plain_text(raw["text"])
            if any(choice.get("decision") == "rejected" and choice.get("node_id") == node["node_id"]
                   and choice.get("node_revision") == node["node_revision"]
                   and choice.get("alternative_text") == raw["text"]
                   for choice in (context.get("decision_memory") or {}).get("choices", [])):
                raise DocumentConflict("This wording was already rejected for the unchanged node and target")
            if not raw["text"].strip() or len(raw["text"]) > max(1000, len(node["text"]) * 2 + 100):
                raise DocumentConflict("Candidate is empty or excessively expanded")
            if not isinstance(raw["reason"], str) or len(raw["reason"]) > 1500:
                raise DocumentConflict("Invalid change explanation")
            validate_plain_text(raw["reason"], max_length=1500)
            evidence_ids = raw["evidence_ids"]
            if (
                not isinstance(evidence_ids, list)
                or not evidence_ids
                or len(evidence_ids) > 24
                or any(x not in facts for x in evidence_ids)
            ):
                raise DocumentConflict("Unknown or absent factual evidence")
            evidence = [facts[x] for x in evidence_ids]
            if node["section"] != "summary" and any(
                f["section"] != node["section"] or f["entry_id"] != node["entry_id"] for f in evidence
            ):
                raise DocumentConflict("Evidence belongs to another role or project")
            if not isinstance(raw["requirement_ids"], list) or any(
                x not in requirements for x in raw["requirement_ids"]
            ):
                raise DocumentConflict("Unknown requirement reference")
            source = node["text"]
            target = raw["text"]
            if _NUMBERS.findall(source) != _NUMBERS.findall(target):
                raise DocumentConflict("Numbers or their order changed")
            if [x.casefold() for x in _RELATION.findall(source)] != [x.casefold() for x in _RELATION.findall(target)]:
                raise DocumentConflict("Negation, comparison or directional anchors changed")
            if [canonical_skill(x) for x in _ORDERED_ANCHORS.findall(source)] != [
                canonical_skill(x) for x in _ORDERED_ANCHORS.findall(target)
            ]:
                raise DocumentConflict("Ordered factual anchors changed")
            # Facts can be restated but never promoted to a higher role/claim.
            joined = " ".join(f["text"] for f in evidence)
            if any(not _present(x, joined) for x in _PROMOTIONS.findall(target)):
                raise DocumentConflict("Unsupported responsibility or proficiency claim")
            for term in TECHNOLOGIES:
                if skill_mention(term, target) != "absent" and not positive_skill_mention(term, joined):
                    raise DocumentConflict("Technology lacks evidence in this scope")
            # Names/capitalized acronyms already present must retain order.
            anchors = re.findall(r"(?<!\w)(?:[A-Z]{2,}[A-Za-z0-9+#.-]*|[A-Z][a-z]+(?:[A-Z][a-z]+)+)(?!\w)", source)
            positions = [target.find(anchor) for anchor in anchors]
            if any(x < 0 for x in positions) or positions != sorted(positions):
                raise DocumentConflict("Named factual anchors changed or reordered")
            if target == source:
                continue
            accepted.append(
                {
                    **raw,
                    "patch_id": "patch." + digest(node["node_id"] + "\0" + node["node_revision"] + "\0" + target)[:24],
                    "operation": "replace_text",
                    "original_text": source,
                    "validation": "awaiting_independent_review",
                }
            )
        except (DocumentConflict, TypeError, KeyError) as exc:
            rejected.append(
                {"node_id": raw.get("node_id") if isinstance(raw, dict) else None, "reason": str(exc)[:1500]}
            )
    return accepted, rejected


def apply_verdicts(candidates: list[dict], value: dict) -> tuple[list[dict], list[dict]]:
    if set(value) != {"verdicts"} or not isinstance(value["verdicts"], list):
        raise DocumentConflict("Invalid independent review response")
    ids = {p["patch_id"] for p in candidates}
    verdicts = {}
    for verdict in value["verdicts"]:
        if (
            not isinstance(verdict, dict)
            or set(verdict) != {"patch_id", "supported", "reason"}
            or verdict["patch_id"] not in ids
            or verdict["patch_id"] in verdicts
            or type(verdict["supported"]) is not bool
            or not isinstance(verdict["reason"], str)
        ):
            raise DocumentConflict("Invalid or duplicated entailment verdict")
        verdicts[verdict["patch_id"]] = verdict
    accepted, rejected = [], []
    for patch in candidates:
        verdict = verdicts.get(patch["patch_id"])
        if verdict and verdict["supported"]:
            accepted.append(
                {
                    **patch,
                    "validation": "source_guard_and_independent_review",
                    "review_reason": verdict["reason"][:1500],
                }
            )
        else:
            rejected.append(
                {
                    "node_id": patch["node_id"],
                    "patch_id": patch["patch_id"],
                    "reason": (verdict or {}).get("reason", "No explicit supporting verdict")[:1500],
                }
            )
    return accepted, rejected

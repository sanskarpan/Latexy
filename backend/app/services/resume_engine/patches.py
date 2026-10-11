"""Strict completed-patch validation and byte-preserving application."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .document import ResumeSnapshot, digest


class CompactOptimizationError(RuntimeError):
    """A terminal compact run failure: do not retry the entire paid job."""


class CompactOptimizationCancelled(CompactOptimizationError):
    pass


class NodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str = Field(min_length=1, max_length=96)
    expected_node_revision: str = Field(min_length=64, max_length=64)
    operation: Literal["replace_text"]
    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=1)
    reason_code: Literal["clarity", "conciseness"]


class PatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    base_revision: str = Field(min_length=64, max_length=64)
    changes: list[NodePatch] = Field(max_length=24)


# This release is a constrained wording editor, not a factual entailment model.
# New content-bearing tokens are rejected; a small list permits wording only.
_ARTICLES = frozenset({"a", "an", "the"})
_INITIAL_VERBS = {"built": "built", "developed": "built", "improved": "improved", "enhanced": "improved"}
_NUMBERS = re.compile(r"\d+(?:[.,]\d+)*(?:\s*%)?")
_WORDS = re.compile(r"[\w]+(?:[-'][\w]+)*|[^\w\s]", re.UNICODE)


def apply_patches(snapshot: ResumeSnapshot, raw: str) -> tuple[str, list[dict]]:
    try:
        response = PatchResponse.model_validate_json(raw, strict=True)
    except Exception as exc:
        raise CompactOptimizationError("AI returned an invalid completed patch response") from exc
    if response.base_revision != snapshot.revision or digest(snapshot.source) != snapshot.revision:
        raise CompactOptimizationError("Source revision changed")
    nodes = {node.node_id: node for node in snapshot.nodes}
    used: set[str] = set()
    edits: list[tuple[int, int, str]] = []
    changes: list[dict] = []
    for patch in response.changes:
        node = nodes.get(patch.node_id)
        if node is None or patch.node_id in used or node.revision != patch.expected_node_revision:
            raise CompactOptimizationError("Patch target or node revision is invalid")
        used.add(patch.node_id)
        if patch.evidence_ids != [node.node_id]:
            raise CompactOptimizationError("Patch must cite its own original bullet")
        text = patch.text.strip()
        if (re.search(r"[\\{}%$&#_^~\x00-\x1f\x7f]", text)
                or any(unicodedata.category(char).startswith("C") or unicodedata.category(char) in {"Zl", "Zp"} for char in text)
                or len(text) > min(1000, len(node.text) * 2 + 40)):
            raise CompactOptimizationError("Patch contains unsupported syntax or excessive text")
        before_numbers = Counter(_NUMBERS.findall(node.text))
        if Counter(_NUMBERS.findall(text)) != before_numbers:
            raise CompactOptimizationError("Patch changed protected numbers")
        def protected_sequence(value: str) -> list[str]:
            words = [word.casefold() for word in _WORDS.findall(value)]
            # Only the initial action verb has a narrow synonym allowance.
            # Relations/negation/connectives and repeated words retain order.
            if words and words[0] in _INITIAL_VERBS:
                words[0] = _INITIAL_VERBS[words[0]]
            return [word for word in words if word not in _ARTICLES]

        if protected_sequence(text) != protected_sequence(node.text):
            raise CompactOptimizationError("Patch changed protected source vocabulary or factual order")
        if text != node.text:
            edits.append((node.start, node.end, text))
            changes.append({"section": node.section, "change_type": "modified", "reason": patch.reason_code,
                            "node_id": node.node_id, "evidence_ids": patch.evidence_ids})
    result = snapshot.source
    for start, end, text in sorted(edits, reverse=True):
        result = result[:start] + text + result[end:]
    return result, changes

"""Deterministic server-side diff engine for per-change accept/reject review.

Feature 2 / P0 of docs/prd/2026-08-02-input-driven-optimization.md — the
flagship "AI drafts, you direct and approve" review layer.

The optimize pipeline (orchestrator.py) produces ``optimized_latex`` plus an
advisory ``changes_made`` list (``[{section, change_type, reason}]``) from the
LLM. We do NOT trust the LLM to emit exact substrings for granular apply.
Instead this module computes the diff **server-side** between the original and
optimized LaTeX, segments it into discrete, independently-applicable
``ChangeHunk`` objects, and applies only the hunks the client accepted.

Design invariants (see tests in test_resume_diff.py):
  * ``apply_changes(orig, hunks, ALL_ids) == optimized`` — every meaningful
    non-equal region is a hunk, so accepting all reconstructs the optimized doc
    exactly.
  * ``apply_changes(orig, hunks, set()) == original`` — rejecting all keeps
    every original span byte-for-byte.
  * Order-independent w.r.t. the accepted set (hunks are re-sorted by original
    position before reconstruction).
  * Pure — no LLM calls, no I/O, O(n) in document size, fully deterministic.

The advisory ``change_reasons`` are used ONLY to *label* hunks (map a rationale
by nearest section) — never to decide what text to apply.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

# Headings we treat as section anchors when inferring which resume section a
# hunk belongs to. Best-effort: captures the first brace group of common
# sectioning commands and resume-template subheadings.
_SECTION_RE = re.compile(
    r"\\(?:section|subsection|subsubsection|paragraph)\*?\s*\{([^}]*)\}"
    r"|\\resume(?:SubHeading|Subheading|SubSubHeading|ProjectHeading)\s*\{([^}]*)\}",
    re.IGNORECASE,
)


@dataclass
class ChangeHunk:
    """One discrete, independently-applicable change between original and optimized LaTeX.

    ``id`` is stable across identical inputs (hash of the original span + new
    span + ordinal index) so the client can accept/reject by id and re-post the
    same list. ``original_start``/``original_end`` are character offsets into the
    *original* document; the apply engine uses them to reconstruct exactly and
    order-independently.
    """

    id: str
    kind: str  # "modified" | "added" | "removed"
    original_text: str
    new_text: str
    before_context: str
    after_context: str
    section: Optional[str] = None
    rationale: Optional[str] = None
    # Character offsets of the hunk's span in the ORIGINAL document. For an
    # "added" hunk the span is empty (original_start == original_end == insertion
    # point).
    original_start: int = 0
    original_end: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _line_char_offsets(lines: list[str]) -> list[int]:
    """Return char offset of the start of each line, plus a final total-length entry.

    ``offsets[i]`` is the char index where ``lines[i]`` begins; ``offsets[len]``
    is the total document length. Built from ``splitlines(keepends=True)`` output
    so ``"".join(lines)`` reproduces the source exactly.
    """
    offsets = [0]
    total = 0
    for ln in lines:
        total += len(ln)
        offsets.append(total)
    return offsets


def _normalise_reasons(change_reasons: Optional[Iterable[dict]]) -> list[dict]:
    reasons: list[dict] = []
    for r in change_reasons or []:
        if not isinstance(r, dict):
            continue
        reason_text = r.get("reason")
        if not reason_text:
            continue
        reasons.append(
            {
                "section": (r.get("section") or "").strip(),
                "change_type": (r.get("change_type") or "").strip().lower(),
                "reason": str(reason_text),
                "_used": False,
            }
        )
    return reasons


def _infer_section(original_latex: str, position: int) -> Optional[str]:
    """Nearest preceding ``\\section``/``\\subsection``/resume-subheading before ``position``."""
    nearest: Optional[str] = None
    for m in _SECTION_RE.finditer(original_latex, 0, position):
        heading = m.group(1) if m.group(1) is not None else m.group(2)
        if heading is not None:
            nearest = heading.strip()
    return nearest or None


def _match_rationale(
    section: Optional[str], kind: str, reasons: list[dict]
) -> Optional[str]:
    """Best-effort: pick a reason whose section matches this hunk's section.

    Prefers a reason with a matching ``change_type`` too; consumes the reason so
    the same rationale is not reused for multiple hunks. Returns None when no
    section match exists — advisory labels never block the apply path.
    """
    if not section or not reasons:
        return None
    sec_l = section.strip().lower()

    # First pass: section AND change_type match.
    for r in reasons:
        if r["_used"]:
            continue
        if r["section"].lower() == sec_l and r["change_type"] == kind:
            r["_used"] = True
            return r["reason"]
    # Second pass: section match only.
    for r in reasons:
        if r["_used"]:
            continue
        if r["section"].lower() == sec_l:
            r["_used"] = True
            return r["reason"]
    return None


def _stable_id(index: int, original_text: str, new_text: str) -> str:
    digest = hashlib.sha1(
        f"{index}\x00{original_text}\x00{new_text}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def segment_changes(
    original_latex: str,
    optimized_latex: str,
    change_reasons: Optional[Iterable[dict]] = None,
) -> list[ChangeHunk]:
    """Segment the original→optimized diff into discrete, applicable change hunks.

    Line-based ``SequenceMatcher`` (robust and simple for LaTeX). Consecutive
    non-equal opcodes are grouped into a single hunk. Pure-whitespace-only hunks
    (the two sides are equal after ``.strip()``) are ignored — they are cosmetic
    reflows the user should not have to review. Hunks are returned ordered by
    original position with stable ids.

    ``change_reasons`` (``[{section, change_type, reason}]``, advisory) only
    labels hunks with a rationale by nearest section; it is never used to decide
    applied text.
    """
    orig_lines = original_latex.splitlines(keepends=True)
    opt_lines = optimized_latex.splitlines(keepends=True)
    offsets = _line_char_offsets(orig_lines)
    reasons = _normalise_reasons(change_reasons)

    matcher = SequenceMatcher(a=orig_lines, b=opt_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    hunks: list[ChangeHunk] = []
    index = 0
    i = 0
    n = len(opcodes)
    while i < n:
        tag, i1, i2, j1, j2 = opcodes[i]
        if tag == "equal":
            i += 1
            continue

        # Group a run of consecutive non-equal opcodes into one hunk. (In
        # practice get_opcodes separates non-equal blocks with 'equal', so a run
        # is normally length 1 — this loop is defensive.)
        run_i1, run_i2 = i1, i2
        run_j1, run_j2 = j1, j2
        k = i + 1
        while k < n and opcodes[k][0] != "equal":
            _, _, e_i2, _, e_j2 = opcodes[k]
            run_i2 = e_i2
            run_j2 = e_j2
            k += 1
        i = k

        original_text = "".join(orig_lines[run_i1:run_i2])
        new_text = "".join(opt_lines[run_j1:run_j2])

        # Ignore cosmetic whitespace-only reflows.
        if original_text.strip() == new_text.strip():
            continue

        if run_i1 == run_i2:
            kind = "added"
        elif run_j1 == run_j2:
            kind = "removed"
        else:
            kind = "modified"

        char_start = offsets[run_i1]
        char_end = offsets[run_i2]

        section = _infer_section(original_latex, char_start)
        rationale = _match_rationale(section, kind, reasons)

        before_context = orig_lines[run_i1 - 1].rstrip("\n") if run_i1 > 0 else ""
        after_context = orig_lines[run_i2].rstrip("\n") if run_i2 < len(orig_lines) else ""

        hunks.append(
            ChangeHunk(
                id=_stable_id(index, original_text, new_text),
                kind=kind,
                original_text=original_text,
                new_text=new_text,
                before_context=before_context.strip(),
                after_context=after_context.strip(),
                section=section,
                rationale=rationale,
                original_start=char_start,
                original_end=char_end,
            )
        )
        index += 1

    return hunks


def summarize(hunks: Iterable[ChangeHunk]) -> dict:
    """Count hunks by kind for the review summary card."""
    total = added = modified = removed = 0
    for h in hunks:
        total += 1
        if h.kind == "added":
            added += 1
        elif h.kind == "removed":
            removed += 1
        else:
            modified += 1
    return {"total": total, "added": added, "modified": modified, "removed": removed}


def _hunk_span(
    original_latex: str, h: dict
) -> Optional[tuple[int, int, str, str, Optional[str]]]:
    """Resolve a hunk dict to (start, end, original_text, new_text, id) in original_latex.

    Trusts the stored offsets when they still match the original span; otherwise
    falls back to locating ``original_text`` by search. Returns None when the
    hunk cannot be placed deterministically (dropped rather than mis-applied).
    """
    hid = h.get("id")
    original_text = h.get("original_text", "") or ""
    new_text = h.get("new_text", "") or ""
    start = h.get("original_start")
    end = h.get("original_end")

    n = len(original_latex)
    if (
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start <= end <= n
        and original_latex[start:end] == original_text
    ):
        return start, end, original_text, new_text, hid

    # Offsets missing/stale — try to locate the original span by content.
    if original_text:
        idx = original_latex.find(original_text)
        if idx != -1:
            return idx, idx + len(original_text), original_text, new_text, hid
        return None

    # "added" hunk (empty original span) with no usable offset: cannot place.
    return None


def apply_changes(
    original_latex: str,
    hunks: Iterable[dict],
    accepted_ids: Iterable[str],
) -> str:
    """Reconstruct the final LaTeX from the original + the accepted hunk ids.

    Walks the original left-to-right. For each hunk (re-sorted by original
    position, so the result is independent of the order/contents of
    ``accepted_ids``): emit ``new_text`` when the hunk id is accepted, otherwise
    keep the original span untouched. Untouched (equal) regions are copied
    verbatim.

    Guarantees ``apply_changes(orig, segment(orig, opt), ALL) == opt`` and
    ``apply_changes(orig, segment(orig, opt), set()) == orig`` whenever every
    non-equal region was captured as a hunk (i.e. no cosmetic whitespace-only
    regions were dropped).
    """
    accepted = set(accepted_ids)

    spans: list[tuple[int, int, str, str, Optional[str]]] = []
    for h in hunks:
        resolved = _hunk_span(original_latex, dict(h))
        if resolved is not None:
            spans.append(resolved)

    # Sort by original position; makes the walk order-independent w.r.t. input order.
    spans.sort(key=lambda s: (s[0], s[1]))

    out: list[str] = []
    cursor = 0
    for start, end, original_text, new_text, hid in spans:
        if start < cursor:
            # Overlapping spans (should not happen for hunks from segment_changes)
            # — skip to keep reconstruction deterministic and non-corrupting.
            continue
        out.append(original_latex[cursor:start])
        out.append(new_text if hid in accepted else original_text)
        cursor = end
    out.append(original_latex[cursor:])
    return "".join(out)

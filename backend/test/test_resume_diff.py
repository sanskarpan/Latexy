"""Tests for the per-change accept/reject diff engine (Feature 2 / P0).

Correctness-critical: the round-trip invariant (accept-all == optimized,
accept-none == original) is what makes selective apply safe. See
app/services/resume_diff_service.py.
"""

import pytest

from app.services.resume_diff_service import (
    apply_changes,
    segment_changes,
    summarize,
)

# ── Realistic LaTeX resume samples (multi-section) ───────────────────────────

_BASE = r"""\documentclass[letterpaper,11pt]{article}
\begin{document}
\section*{Experience}
\textbf{Software Engineer} at Acme Corp \hfill 2020--Present
\begin{itemize}
    \item Built distributed systems serving 1M users
    \item Reduced latency by 40 percent through caching
    \item Mentored two junior engineers
\end{itemize}
\section*{Skills}
Python, TypeScript, PostgreSQL, Redis
\section*{Education}
BSc Computer Science, State University
\end{document}
"""

# Reworded a line (modified).
_REWORDED = _BASE.replace(
    "    \\item Built distributed systems serving 1M users\n",
    "    \\item Architected distributed systems serving 1M+ users with 99.9\\% uptime\n",
)

# Added a bullet (insert).
_ADDED = _BASE.replace(
    "    \\item Mentored two junior engineers\n",
    "    \\item Mentored two junior engineers\n    \\item Led migration to Kubernetes\n",
)

# Removed a bullet (delete).
_REMOVED = _BASE.replace(
    "    \\item Reduced latency by 40 percent through caching\n",
    "",
)

# Changes in two different sections at once.
_MULTI = _BASE.replace(
    "    \\item Built distributed systems serving 1M users\n",
    "    \\item Architected distributed systems serving 1M+ users\n",
).replace(
    "Python, TypeScript, PostgreSQL, Redis\n",
    "Python, TypeScript, Go, PostgreSQL, Redis, Docker\n",
)

_ALL_PAIRS = {
    "reworded": (_BASE, _REWORDED),
    "added": (_BASE, _ADDED),
    "removed": (_BASE, _REMOVED),
    "multi_section": (_BASE, _MULTI),
}


def _apply_all(original, optimized):
    hunks = segment_changes(original, optimized)
    ids = [h.id for h in hunks]
    return apply_changes(original, [h.to_dict() for h in hunks], set(ids)), hunks


# ── Round-trip invariant ─────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(_ALL_PAIRS))
def test_round_trip_accept_all_equals_optimized(name):
    original, optimized = _ALL_PAIRS[name]
    result, hunks = _apply_all(original, optimized)
    assert hunks, f"{name}: expected at least one hunk"
    assert result == optimized, f"{name}: accept-all must reproduce the optimized doc exactly"


@pytest.mark.parametrize("name", sorted(_ALL_PAIRS))
def test_round_trip_accept_none_equals_original(name):
    original, optimized = _ALL_PAIRS[name]
    hunks = segment_changes(original, optimized)
    result = apply_changes(original, [h.to_dict() for h in hunks], set())
    assert result == original, f"{name}: accept-none must reproduce the original doc exactly"


def test_round_trip_is_order_independent():
    """Reconstruction must not depend on the order of accepted_ids."""
    original, optimized = _BASE, _MULTI
    hunks = segment_changes(original, optimized)
    ids = [h.id for h in hunks]
    forward = apply_changes(original, [h.to_dict() for h in hunks], ids)
    reverse = apply_changes(original, [h.to_dict() for h in hunks], list(reversed(ids)))
    # Passing hunks in reversed order to apply must also work (spans are re-sorted).
    reordered = apply_changes(
        original, [h.to_dict() for h in reversed(hunks)], set(ids)
    )
    assert forward == optimized
    assert reverse == optimized
    assert reordered == optimized


def test_identical_documents_yield_no_hunks():
    assert segment_changes(_BASE, _BASE) == []
    assert apply_changes(_BASE, [], set()) == _BASE


# ── Partial acceptance (hand-checked) ────────────────────────────────────────


def test_partial_acceptance_hand_checked():
    original = (
        "\\section*{Experience}\n"
        "\\item Alpha original\n"
        "\\item KEEP THIS LINE\n"
        "\\item Beta original\n"
    )
    optimized = (
        "\\section*{Experience}\n"
        "\\item Alpha changed\n"
        "\\item KEEP THIS LINE\n"
        "\\item Beta changed\n"
    )
    hunks = segment_changes(original, optimized)
    assert len(hunks) == 2, "expected two distinct hunks separated by the kept line"

    hunk_alpha = next(h for h in hunks if "Alpha" in h.original_text)
    hunk_beta = next(h for h in hunks if "Beta" in h.original_text)

    # Accept only the Alpha hunk.
    result = apply_changes(
        original, [h.to_dict() for h in hunks], {hunk_alpha.id}
    )
    expected = (
        "\\section*{Experience}\n"
        "\\item Alpha changed\n"      # accepted -> new_text
        "\\item KEEP THIS LINE\n"     # untouched equal region
        "\\item Beta original\n"      # rejected -> original span
    )
    assert result == expected

    # Accept only the Beta hunk (symmetric).
    result2 = apply_changes(
        original, [h.to_dict() for h in hunks], {hunk_beta.id}
    )
    assert "Alpha original" in result2
    assert "Beta changed" in result2


# ── Stable ids ───────────────────────────────────────────────────────────────


def test_ids_are_stable_across_identical_inputs():
    a = segment_changes(_BASE, _MULTI)
    b = segment_changes(_BASE, _MULTI)
    assert [h.id for h in a] == [h.id for h in b]


def test_ids_differ_across_distinct_hunks():
    hunks = segment_changes(_BASE, _MULTI)
    ids = [h.id for h in hunks]
    assert len(ids) == len(set(ids)), "each hunk must have a unique id"


# ── Kind classification ──────────────────────────────────────────────────────


def test_kind_added():
    hunks = segment_changes(_BASE, _ADDED)
    assert len(hunks) == 1
    assert hunks[0].kind == "added"
    assert hunks[0].original_text == ""
    assert "Kubernetes" in hunks[0].new_text


def test_kind_removed():
    hunks = segment_changes(_BASE, _REMOVED)
    assert len(hunks) == 1
    assert hunks[0].kind == "removed"
    assert hunks[0].new_text == ""
    assert "caching" in hunks[0].original_text


def test_kind_modified():
    hunks = segment_changes(_BASE, _REWORDED)
    assert len(hunks) == 1
    assert hunks[0].kind == "modified"


# ── Section + rationale inference ────────────────────────────────────────────


def test_section_inference_starred_heading():
    hunks = segment_changes(_BASE, _REWORDED)
    assert hunks[0].section == "Experience"


def test_section_inference_multiple_sections():
    hunks = segment_changes(_BASE, _MULTI)
    by_section = {h.section for h in hunks}
    assert "Experience" in by_section
    assert "Skills" in by_section


def test_section_inference_nonstarred_heading():
    original = "\\section{Projects}\n\\item Original project line\n"
    optimized = "\\section{Projects}\n\\item Rewritten project line\n"
    hunks = segment_changes(original, optimized)
    assert len(hunks) == 1
    assert hunks[0].section == "Projects"


def test_rationale_maps_by_section():
    reasons = [
        {"section": "Experience", "change_type": "modified", "reason": "Stronger action verb + quantified impact"},
    ]
    hunks = segment_changes(_BASE, _REWORDED, change_reasons=reasons)
    assert hunks[0].rationale == "Stronger action verb + quantified impact"


def test_rationale_none_when_no_matching_section():
    reasons = [{"section": "Publications", "change_type": "modified", "reason": "n/a"}]
    hunks = segment_changes(_BASE, _REWORDED, change_reasons=reasons)
    assert hunks[0].rationale is None


def test_rationale_none_when_no_reasons_supplied():
    hunks = segment_changes(_BASE, _REWORDED)
    assert hunks[0].rationale is None


# ── Whitespace-only diffs are ignored ────────────────────────────────────────


def test_whitespace_only_indentation_ignored():
    original = "\\section*{Skills}\n\\item Python and Go\n"
    optimized = "\\section*{Skills}\n        \\item Python and Go\n"  # indent only
    assert segment_changes(original, optimized) == []


def test_whitespace_only_blank_line_ignored():
    original = "\\item A\n\\item B\n"
    optimized = "\\item A\n\n\\item B\n"  # inserted blank line
    assert segment_changes(original, optimized) == []


def test_meaningful_change_not_ignored_despite_whitespace():
    original = "\\item  Python\n"
    optimized = "\\item Python and Go\n"
    hunks = segment_changes(original, optimized)
    assert len(hunks) == 1


# ── Summary ──────────────────────────────────────────────────────────────────


def test_summarize_counts():
    hunks = segment_changes(_BASE, _MULTI)
    summary = summarize(hunks)
    assert summary["total"] == len(hunks)
    assert summary["total"] == summary["added"] + summary["modified"] + summary["removed"]


# ── apply_changes robustness ─────────────────────────────────────────────────


def test_apply_tolerates_stale_offsets_via_content_search():
    """If offsets are missing, apply falls back to locating original_text."""
    hunks = segment_changes(_BASE, _REWORDED)
    payload = []
    for h in hunks:
        d = h.to_dict()
        d.pop("original_start", None)
        d.pop("original_end", None)
        payload.append(d)
    ids = {h.id for h in hunks}
    assert apply_changes(_BASE, payload, ids) == _REWORDED


def test_apply_unknown_ids_are_noops():
    hunks = segment_changes(_BASE, _REWORDED)
    result = apply_changes(_BASE, [h.to_dict() for h in hunks], {"does-not-exist"})
    assert result == _BASE


# ── Endpoint smoke tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_segment_then_apply_all_endpoint(client):
    seg = await client.post(
        "/optimize/segment-changes",
        json={"original_latex": _BASE, "optimized_latex": _MULTI},
    )
    assert seg.status_code == 200
    body = seg.json()
    assert body["summary"]["total"] == len(body["hunks"])
    assert body["hunks"], "expected hunks"

    accepted = [h["id"] for h in body["hunks"]]
    apply = await client.post(
        "/optimize/apply-changes",
        json={"original_latex": _BASE, "hunks": body["hunks"], "accepted_ids": accepted},
    )
    assert apply.status_code == 200
    assert apply.json()["latex"] == _MULTI


@pytest.mark.asyncio
async def test_apply_none_endpoint_returns_original(client):
    seg = await client.post(
        "/optimize/segment-changes",
        json={"original_latex": _BASE, "optimized_latex": _MULTI},
    )
    hunks = seg.json()["hunks"]
    apply = await client.post(
        "/optimize/apply-changes",
        json={"original_latex": _BASE, "hunks": hunks, "accepted_ids": []},
    )
    assert apply.status_code == 200
    assert apply.json()["latex"] == _BASE


@pytest.mark.asyncio
async def test_segment_rejects_oversized_latex(client):
    huge = "x" * 500_001
    resp = await client.post(
        "/optimize/segment-changes",
        json={"original_latex": huge, "optimized_latex": huge},
    )
    assert resp.status_code == 422

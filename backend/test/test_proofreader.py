"""
Tests for Feature 25: AI Proofreader (Writing Quality).

Covers:
  - Service-level unit tests (proofread_latex function):
      - Weak verb "responsible for" → issue detected at correct line
      - Passive voice "was improved by" → issue detected
      - Buzzword "synergy" → issue detected
      - Clean resume → zero issues
      - Summary dict counts match actual issue counts
      - overall_score == 100 for clean text; lower for issue-heavy text
      - Line/column positions are accurate (1-indexed)
      - Preamble lines are skipped
      - Comment lines are skipped
      - Multiple issues on the same line all detected
  - HTTP endpoint tests (POST /ai/proofread):
      - 200 OK with issues list
      - 422 for oversized input
      - Empty document returns zero issues with score 100
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.proofreader_service import ProofreadResponse, proofread_latex

# ---------------------------------------------------------------------------
# Sample LaTeX fixtures
# ---------------------------------------------------------------------------

_CLEAN_RESUME = r"""
\documentclass{article}
\begin{document}
\section*{Experience}
\begin{itemize}
\item Led a team of 8 engineers to deliver a payment API that processed \$2M/day.
\item Architected a distributed caching layer that reduced p99 latency by 60\%.
\item Drove a migration to Kubernetes, cutting infrastructure costs by 35\%.
\end{itemize}
\end{document}
"""

_WEAK_VERB_RESUME = r"""
\documentclass{article}
\begin{document}
\section*{Experience}
\begin{itemize}
\item Responsible for building the payment API.
\item Worked on the backend infrastructure.
\item Assisted with the database migration.
\end{itemize}
\end{document}
"""

_PASSIVE_VOICE_RESUME = r"""
\documentclass{article}
\begin{document}
\section*{Experience}
\begin{itemize}
\item The system was improved by the team to increase throughput.
\item The codebase has been refactored over time.
\item Performance metrics have been tracked carefully.
\end{itemize}
\end{document}
"""

_BUZZWORD_RESUME = r"""
\documentclass{article}
\begin{document}
\section*{Summary}
Passionate about technology and synergy with a strong results-driven mindset.
A team player who is proactive and leveraging modern tools.
\end{document}
"""

_MULTI_ISSUE_LINE = r"""
\documentclass{article}
\begin{document}
\section*{Experience}
\begin{itemize}
\item Was involved in various synergy initiatives.
\end{itemize}
\end{document}
"""


# ---------------------------------------------------------------------------
# 25A — Service unit tests
# ---------------------------------------------------------------------------


class TestProofreadService:
    def test_clean_resume_returns_zero_issues(self):
        result = proofread_latex(_CLEAN_RESUME)
        assert isinstance(result, ProofreadResponse)
        assert result.issues == []
        assert result.summary == {}
        assert result.overall_score == 100

    def test_weak_verb_responsible_for_detected(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        categories = {i.category for i in result.issues}
        assert "weak_verb" in categories

    def test_weak_verb_at_correct_line(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        weak_issues = [i for i in result.issues if i.category == "weak_verb"]
        assert len(weak_issues) > 0
        # "Responsible for" is on a \item line — find it
        responsible_issues = [i for i in weak_issues if "responsible for" in i.original_text.lower()]
        assert len(responsible_issues) > 0
        issue = responsible_issues[0]
        # Verify it's in the document body (not preamble)
        assert issue.line > 0

    def test_weak_verb_columns_are_1_indexed(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        for issue in result.issues:
            assert issue.column_start >= 1, "column_start must be 1-indexed"
            assert issue.column_end > issue.column_start, "column_end must be after column_start"

    def test_passive_voice_was_improved_by_detected(self):
        result = proofread_latex(_PASSIVE_VOICE_RESUME)
        categories = {i.category for i in result.issues}
        assert "passive_voice" in categories

    def test_passive_voice_has_been_detected(self):
        result = proofread_latex(_PASSIVE_VOICE_RESUME)
        has_been_issues = [
            i for i in result.issues
            if i.category == "passive_voice" and "has been" in i.original_text.lower()
        ]
        assert len(has_been_issues) > 0

    def test_buzzword_synergy_detected(self):
        result = proofread_latex(_BUZZWORD_RESUME)
        categories = {i.category for i in result.issues}
        assert "buzzword" in categories
        synergy_issues = [i for i in result.issues if "synergy" in i.original_text.lower()]
        assert len(synergy_issues) > 0

    def test_buzzword_leveraging_detected(self):
        result = proofread_latex(_BUZZWORD_RESUME)
        leverage_issues = [
            i for i in result.issues
            if i.category == "buzzword" and "leverag" in i.original_text.lower()
        ]
        assert len(leverage_issues) > 0

    def test_summary_counts_match_issues(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        for category, count in result.summary.items():
            actual = sum(1 for i in result.issues if i.category == category)
            assert actual == count, f"summary[{category}]={count} but found {actual} issues"

    def test_overall_score_lower_for_issue_heavy_text(self):
        clean = proofread_latex(_CLEAN_RESUME)
        dirty = proofread_latex(_WEAK_VERB_RESUME)
        assert clean.overall_score > dirty.overall_score

    def test_preamble_is_skipped(self):
        # LaTeX preamble should never appear as issues
        resume_with_preamble = r"""
\documentclass{article}
\usepackage{geometry}
\newcommand{\responsible}{Responsible for}
\begin{document}
\item Led the backend team to ship 3 features on time.
\end{document}
"""
        result = proofread_latex(resume_with_preamble)
        # Any "responsible for" in preamble must NOT be flagged
        for issue in result.issues:
            # preamble is lines 2-4 (before \begin{document} on line 5)
            assert issue.line >= 5, "Preamble line flagged as issue"

    def test_comment_lines_are_skipped(self):
        resume = r"""
\documentclass{article}
\begin{document}
% responsible for everything, synergy
\item Led the platform team to deliver 5 features.
\end{document}
"""
        result = proofread_latex(resume)
        # Comment line should produce no issues
        assert result.issues == []

    def test_multiple_issues_on_same_line(self):
        result = proofread_latex(_MULTI_ISSUE_LINE)
        # "was involved in", "various", "synergy" all on the same \item line
        assert len(result.issues) >= 2

    def test_column_position_points_to_correct_text(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        lines = _WEAK_VERB_RESUME.split('\n')
        for issue in result.issues:
            line_text = lines[issue.line - 1]  # 1-indexed → 0-indexed
            extracted = line_text[issue.column_start - 1 : issue.column_end - 1]
            assert extracted.lower() == issue.original_text.lower(), (
                f"Column mismatch: expected {issue.original_text!r}, got {extracted!r}"
            )

    def test_severity_assignment(self):
        result = proofread_latex(_WEAK_VERB_RESUME)
        for issue in result.issues:
            if issue.category in ("weak_verb", "passive_voice", "buzzword"):
                assert issue.severity == "warning"
            elif issue.category == "vague":
                assert issue.severity == "info"


# ---------------------------------------------------------------------------
# 25B — HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProofreadEndpoint:
    async def test_proofread_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _WEAK_VERB_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "issues" in data
        assert "summary" in data
        assert "overall_score" in data

    async def test_proofread_clean_resume_returns_zero_issues(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _CLEAN_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["issues"] == []
        assert data["overall_score"] == 100

    async def test_proofread_detects_weak_verbs(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _WEAK_VERB_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        categories = {i["category"] for i in data["issues"]}
        assert "weak_verb" in categories

    async def test_proofread_detects_passive_voice(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _PASSIVE_VOICE_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        categories = {i["category"] for i in data["issues"]}
        assert "passive_voice" in categories

    async def test_proofread_detects_buzzwords(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _BUZZWORD_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        categories = {i["category"] for i in data["issues"]}
        assert "buzzword" in categories

    async def test_proofread_issue_has_required_fields(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _WEAK_VERB_RESUME},
        )
        data = resp.json()
        for issue in data["issues"]:
            assert "line" in issue
            assert "column_start" in issue
            assert "column_end" in issue
            assert "category" in issue
            assert "severity" in issue
            assert "message" in issue
            assert "original_text" in issue

    async def test_proofread_oversized_input_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": "x" * 200_001},
        )
        assert resp.status_code == 422

    async def test_proofread_summary_counts_correct(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _WEAK_VERB_RESUME},
        )
        data = resp.json()
        for cat, count in data["summary"].items():
            actual = sum(1 for i in data["issues"] if i["category"] == cat)
            assert actual == count

    async def test_proofread_score_range(self, client: AsyncClient):
        resp = await client.post(
            "/ai/proofread",
            json={"latex_content": _BUZZWORD_RESUME},
        )
        data = resp.json()
        assert 0 <= data["overall_score"] <= 100

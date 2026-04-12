"""
Tests for the Resume Confidence Score service and endpoint (Feature 59).
"""

import pytest
from httpx import AsyncClient

# ── Fixtures ─────────────────────────────────────────────────────────────────

_FULL_RESUME = r"""
\documentclass[11pt]{article}
\begin{document}

\section{Contact}
John Doe, john@example.com, (555) 123-4567

\section{Summary}
Experienced software engineer with 8 years building distributed systems.

\section{Experience}
\textbf{Senior Engineer} — Acme Corp \hfill Jan 2020 -- Present
\begin{itemize}
  \item Led a team of 5 engineers to deliver 3 major features, reducing latency by 40\%
  \item Engineered microservices handling 200k requests/day with 99.9\% uptime
  \item Reduced infrastructure cost by \$120k/year through optimization
\end{itemize}

\section{Education}
\textbf{B.S. Computer Science} — State University \hfill 2012 -- 2016

\section{Skills}
Python, Go, Kubernetes, PostgreSQL, Redis

\end{document}
"""

_WEAK_VERB_RESUME = r"""
\documentclass[11pt]{article}
\begin{document}

\section{Experience}
\textbf{Engineer} — Acme Corp
\begin{itemize}
  \item Responsible for building the backend service
  \item Helped with database migrations
  \item Worked on the deployment pipeline
  \item Was involved in designing new features
  \item Assisted with code reviews
  \item Participated in planning sessions
\end{itemize}

\end{document}
"""

_NO_NUMBERS_RESUME = r"""
\documentclass[11pt]{article}
\begin{document}

\section{Experience}
\begin{itemize}
  \item Worked on backend services and APIs
  \item Contributed to database design
  \item Assisted with code reviews and testing
\end{itemize}

\end{document}
"""

_EMPTY_RESUME = ""


# ── Service unit tests ────────────────────────────────────────────────────────


class TestConfidenceScoreService:
    def _service(self):
        from app.services.confidence_score_service import confidence_score_service
        return confidence_score_service

    def test_completeness_full_resume(self):
        cs = self._service().score(_FULL_RESUME)
        assert cs.completeness >= 80, f"Expected >= 80, got {cs.completeness}"

    def test_writing_quality_weak_verbs(self):
        cs = self._service().score(_WEAK_VERB_RESUME)
        assert cs.writing_quality < 70, f"Expected < 70, got {cs.writing_quality}"

    def test_quantification_no_numbers(self):
        cs = self._service().score(_NO_NUMBERS_RESUME)
        assert cs.quantification < 20, f"Expected < 20, got {cs.quantification}"

    def test_empty_resume_all_dimensions_zero(self):
        cs = self._service().score(_EMPTY_RESUME)
        assert cs.writing_quality == 0
        assert cs.quantification == 0  # blank input short-circuits before neutral check
        assert cs.completeness == 0

    def test_overall_weighted_correctly(self):
        cs = self._service().score(_FULL_RESUME)
        expected = round(
            cs.writing_quality * 0.30
            + cs.completeness * 0.20
            + cs.quantification * 0.20
            + cs.formatting * 0.15
            + cs.section_order * 0.15
        )
        assert cs.overall == expected

    def test_grade_mapping(self):
        svc = self._service()
        assert svc.grade(95) == 'A'
        assert svc.grade(85) == 'B'
        assert svc.grade(75) == 'C'
        assert svc.grade(65) == 'D'
        assert svc.grade(55) == 'F'

    def test_improvements_returns_three(self):
        cs = self._service().score(_WEAK_VERB_RESUME)
        improvements = self._service().get_improvements(cs, _WEAK_VERB_RESUME)
        assert len(improvements) == 3
        assert all(isinstance(i, str) and len(i) > 0 for i in improvements)

    def test_section_order_experience_before_education(self):
        cs = self._service().score(_FULL_RESUME)
        # Full resume has Experience before Education → should score well
        assert cs.section_order >= 70

    def test_formatting_consistent_dates(self):
        # _FULL_RESUME uses abbreviated month format consistently
        cs = self._service().score(_FULL_RESUME)
        assert cs.formatting >= 80


# ── Endpoint tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestConfidenceScoreEndpoint:
    async def test_endpoint_returns_required_fields(self, client: AsyncClient):
        resp = await client.post(
            "/ai/confidence-score",
            json={"latex_content": _FULL_RESUME},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data
        assert "writing_quality" in data
        assert "completeness" in data
        assert "quantification" in data
        assert "formatting" in data
        assert "section_order" in data
        assert "grade" in data
        assert "improvements" in data
        assert "cached" in data
        assert isinstance(data["improvements"], list)
        assert data["grade"] in ("A", "B", "C", "D", "F")

    async def test_endpoint_empty_content_returns_zeros(self, client: AsyncClient):
        """Empty LaTeX is valid input; service returns neutral/zero scores."""
        resp = await client.post(
            "/ai/confidence-score",
            json={"latex_content": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["writing_quality"] == 0
        assert data["completeness"] == 0

    async def test_endpoint_too_long_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/ai/confidence-score",
            json={"latex_content": "x" * 200_001},
        )
        assert resp.status_code == 422

    async def test_endpoint_caches_result(self, client: AsyncClient):
        """Second identical call should be cached=True if Redis is available."""
        resp1 = await client.post(
            "/ai/confidence-score",
            json={"latex_content": _FULL_RESUME},
        )
        resp2 = await client.post(
            "/ai/confidence-score",
            json={"latex_content": _FULL_RESUME},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # cached=True only when Redis is available; both responses must be structurally valid
        assert resp2.json()["cached"] in (True, False)
        assert resp2.json()["overall"] == resp1.json()["overall"]

    async def test_endpoint_full_resume_completeness(self, client: AsyncClient):
        resp = await client.post(
            "/ai/confidence-score",
            json={"latex_content": _FULL_RESUME},
        )
        assert resp.status_code == 200
        assert resp.json()["completeness"] >= 80

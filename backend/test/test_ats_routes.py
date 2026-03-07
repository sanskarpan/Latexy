"""
ATS routes endpoint tests — /ats/score, /ats/analyze-job-description,
/ats/recommendations, /ats/industry-keywords/{industry}, /ats/supported-industries.

All async processing branches use mocked worker dispatch so no Celery worker
is required. Sync processing branches exercise the real scoring service.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# ── Shared test fixtures ──────────────────────────────────────────────────────

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}
\begin{center}
    \textbf{\Large Jane Smith} \\
    jane@example.com | (555) 123-4567
\end{center}
\section*{Summary}
Experienced software engineer with 5+ years building scalable systems.
\section*{Experience}
\textbf{Senior Software Engineer} at \textit{TechCorp} \hfill 2020--Present \\
\begin{itemize}
    \item Developed distributed microservices serving 1M+ users
    \item Reduced infrastructure costs by 35\% through optimization
    \item Led team of 5 engineers
\end{itemize}
\section*{Skills}
Python, TypeScript, PostgreSQL, Redis, Docker, Kubernetes, AWS
\section*{Education}
\textbf{B.S. Computer Science}, State University, 2019
\end{document}
"""

JOB_DESCRIPTION = (
    "Software Engineer with Python, Docker, and cloud experience. "
    "Must have strong skills in distributed systems and API development. "
    "Experience with Kubernetes and AWS preferred."
)


# ── POST /ats/score ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestATSScore:

    async def test_score_async_returns_job_id(self, client: AsyncClient):
        """Async branch returns a job_id and success=True."""
        with patch(
            "app.workers.ats_worker.submit_ats_scoring",
            return_value=str(uuid.uuid4()),
        ):
            resp = await client.post(
                "/ats/score",
                json={
                    "latex_content": VALID_LATEX,
                    "async_processing": True,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data
        uuid.UUID(data["job_id"])  # validates UUID format

    async def test_score_sync_returns_numeric_score(self, client: AsyncClient):
        """Sync branch returns ats_score as a float in 0-100 range."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": VALID_LATEX,
                "job_description": JOB_DESCRIPTION,
                "async_processing": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["ats_score"], (int, float))
        assert 0 <= data["ats_score"] <= 100

    async def test_score_sync_returns_category_scores(self, client: AsyncClient):
        """Sync response must include category_scores dict."""
        resp = await client.post(
            "/ats/score",
            json={"latex_content": VALID_LATEX, "async_processing": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "category_scores" in data
        assert isinstance(data["category_scores"], dict)
        assert len(data["category_scores"]) > 0

    async def test_score_sync_returns_recommendations(self, client: AsyncClient):
        """Sync response must include recommendations list."""
        resp = await client.post(
            "/ats/score",
            json={"latex_content": VALID_LATEX, "async_processing": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    async def test_score_sync_with_industry(self, client: AsyncClient):
        """Industry-specific scoring should still return valid scores."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": VALID_LATEX,
                "industry": "technology",
                "async_processing": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert 0 <= data["ats_score"] <= 100

    async def test_score_empty_content_returns_400(self, client: AsyncClient):
        """Empty latex_content must return 400 Bad Request."""
        resp = await client.post(
            "/ats/score",
            json={"latex_content": "   ", "async_processing": False},
        )
        assert resp.status_code == 400

    async def test_score_missing_content_returns_422(self, client: AsyncClient):
        """Missing required field returns 422 Unprocessable Entity."""
        resp = await client.post("/ats/score", json={"async_processing": False})
        assert resp.status_code == 422

    async def test_score_async_with_job_description(self, client: AsyncClient):
        """Async scoring with job description should still return job_id."""
        with patch(
            "app.workers.ats_worker.submit_ats_scoring",
            return_value=str(uuid.uuid4()),
        ):
            resp = await client.post(
                "/ats/score",
                json={
                    "latex_content": VALID_LATEX,
                    "job_description": JOB_DESCRIPTION,
                    "async_processing": True,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert "job_id" in resp.json()

    async def test_score_auth_not_required(self, client: AsyncClient):
        """ATS score endpoint does not require authentication."""
        with patch(
            "app.workers.ats_worker.submit_ats_scoring",
            return_value=str(uuid.uuid4()),
        ):
            resp = await client.post(
                "/ats/score",
                json={"latex_content": VALID_LATEX, "async_processing": True},
            )
        assert resp.status_code == 200

    async def test_score_authenticated_user_accepted(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Auth headers are accepted and don't break the endpoint."""
        with patch(
            "app.workers.ats_worker.submit_ats_scoring",
            return_value=str(uuid.uuid4()),
        ):
            resp = await client.post(
                "/ats/score",
                json={"latex_content": VALID_LATEX, "async_processing": True},
                headers=auth_headers,
            )
        assert resp.status_code == 200


# ── POST /ats/analyze-job-description ────────────────────────────────────────

@pytest.mark.asyncio
class TestATSAnalyzeJobDescription:

    async def test_analyze_async_returns_job_id(self, client: AsyncClient):
        """Async branch returns job_id."""
        with patch(
            "app.workers.ats_worker.submit_job_description_analysis",
            return_value=str(uuid.uuid4()),
        ):
            resp = await client.post(
                "/ats/analyze-job-description",
                json={
                    "job_description": JOB_DESCRIPTION,
                    "async_processing": True,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data

    async def test_analyze_sync_returns_keywords(self, client: AsyncClient):
        """Sync branch returns keywords list."""
        resp = await client.post(
            "/ats/analyze-job-description",
            json={
                "job_description": JOB_DESCRIPTION,
                "async_processing": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "keywords" in data
        assert isinstance(data["keywords"], list)

    async def test_analyze_sync_returns_optimization_tips(self, client: AsyncClient):
        """Sync branch includes optimization_tips."""
        resp = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "optimization_tips" in data
        assert isinstance(data["optimization_tips"], list)

    async def test_analyze_empty_description_returns_400(self, client: AsyncClient):
        """Empty job_description returns 400."""
        resp = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": "   ", "async_processing": False},
        )
        assert resp.status_code == 400

    async def test_analyze_missing_field_returns_422(self, client: AsyncClient):
        """Missing job_description field returns 422."""
        resp = await client.post(
            "/ats/analyze-job-description",
            json={"async_processing": False},
        )
        assert resp.status_code == 422

    async def test_analyze_sync_has_analysis_metrics(self, client: AsyncClient):
        """Sync branch includes analysis_metrics with word/sentence counts."""
        resp = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis_metrics" in data
        metrics = data["analysis_metrics"]
        assert "word_count" in metrics
        assert metrics["word_count"] > 0


# ── POST /ats/recommendations ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestATSRecommendations:

    async def test_recommendations_basic(self, client: AsyncClient):
        """Valid request returns success with priority_improvements."""
        resp = await client.post(
            "/ats/recommendations",
            json={
                "ats_score": 65.0,
                "category_scores": {
                    "formatting": 70.0,
                    "structure": 60.0,
                    "content": 65.0,
                    "keywords": 55.0,
                    "readability": 75.0,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "priority_improvements" in data
        assert isinstance(data["priority_improvements"], list)

    async def test_recommendations_high_priority_for_low_scores(self, client: AsyncClient):
        """Categories with score < 50 should appear as high priority."""
        resp = await client.post(
            "/ats/recommendations",
            json={
                "ats_score": 40.0,
                "category_scores": {"formatting": 30.0, "keywords": 45.0},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        high_priority = [
            item for item in data["priority_improvements"]
            if item["priority"] == "high"
        ]
        assert len(high_priority) > 0

    async def test_recommendations_returns_quick_wins(self, client: AsyncClient):
        """Response includes quick_wins list."""
        resp = await client.post(
            "/ats/recommendations",
            json={
                "ats_score": 60.0,
                "category_scores": {"formatting": 50.0, "keywords": 40.0},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "quick_wins" in data
        assert isinstance(data["quick_wins"], list)

    async def test_recommendations_with_industry(self, client: AsyncClient):
        """Industry parameter adds industry-specific tips."""
        resp = await client.post(
            "/ats/recommendations",
            json={
                "ats_score": 70.0,
                "category_scores": {"formatting": 80.0},
                "industry": "technology",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "industry_specific_tips" in data
        assert isinstance(data["industry_specific_tips"], list)
        assert len(data["industry_specific_tips"]) > 0

    async def test_recommendations_missing_ats_score_returns_422(self, client: AsyncClient):
        """Missing required ats_score field returns 422."""
        resp = await client.post(
            "/ats/recommendations",
            json={"category_scores": {"formatting": 70.0}},
        )
        assert resp.status_code == 422

    async def test_recommendations_empty_category_scores(self, client: AsyncClient):
        """Empty category_scores is valid — no improvements generated."""
        resp = await client.post(
            "/ats/recommendations",
            json={"ats_score": 85.0, "category_scores": {}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    async def test_recommendations_perfect_score_no_high_priority(self, client: AsyncClient):
        """A perfect score should produce no high-priority improvements."""
        resp = await client.post(
            "/ats/recommendations",
            json={
                "ats_score": 98.0,
                "category_scores": {
                    "formatting": 98.0,
                    "structure": 99.0,
                    "content": 97.0,
                    "keywords": 98.0,
                    "readability": 100.0,
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        high_priority = [
            item for item in data["priority_improvements"]
            if item["priority"] == "high"
        ]
        assert len(high_priority) == 0

    async def test_recommendations_score_improvement_is_reasonable(self, client: AsyncClient):
        """Estimated score improvement should be a non-negative number."""
        resp = await client.post(
            "/ats/recommendations",
            json={"ats_score": 60.0, "category_scores": {"formatting": 50.0}},
        )
        assert resp.status_code == 200
        improvement = resp.json()["estimated_score_improvement"]
        assert isinstance(improvement, (int, float))
        assert improvement >= 0


# ── GET /ats/industry-keywords/{industry} ────────────────────────────────────

@pytest.mark.asyncio
class TestATSIndustryKeywords:

    async def test_technology_keywords_returned(self, client: AsyncClient):
        """technology industry should return a non-empty keyword list."""
        resp = await client.get("/ats/industry-keywords/technology")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "keywords" in data
        assert len(data["keywords"]) > 0
        assert data["industry"] == "technology"

    async def test_finance_keywords_returned(self, client: AsyncClient):
        resp = await client.get("/ats/industry-keywords/finance")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert len(resp.json()["keywords"]) > 0

    async def test_healthcare_keywords_returned(self, client: AsyncClient):
        resp = await client.get("/ats/industry-keywords/healthcare")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_marketing_keywords_returned(self, client: AsyncClient):
        resp = await client.get("/ats/industry-keywords/marketing")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    async def test_unknown_industry_returns_404(self, client: AsyncClient):
        """Unknown industry should return 404."""
        resp = await client.get("/ats/industry-keywords/nonexistent_industry_xyz")
        assert resp.status_code == 404

    async def test_keywords_count_matches_list_length(self, client: AsyncClient):
        """count field must equal len(keywords)."""
        resp = await client.get("/ats/industry-keywords/technology")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(data["keywords"])

    async def test_keywords_are_strings(self, client: AsyncClient):
        """All keywords must be strings."""
        resp = await client.get("/ats/industry-keywords/technology")
        assert resp.status_code == 200
        for kw in resp.json()["keywords"]:
            assert isinstance(kw, str)


# ── GET /ats/supported-industries ────────────────────────────────────────────

@pytest.mark.asyncio
class TestATSSupportedIndustries:

    async def test_returns_list_of_industries(self, client: AsyncClient):
        """Endpoint returns a non-empty list of industry strings."""
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "industries" in data
        assert isinstance(data["industries"], list)
        assert len(data["industries"]) > 0

    async def test_count_matches_list_length(self, client: AsyncClient):
        """count field must match len(industries)."""
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(data["industries"])

    async def test_known_industries_present(self, client: AsyncClient):
        """technology, finance, healthcare, marketing must all be supported."""
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200
        industries = resp.json()["industries"]
        for expected in ("technology", "finance", "healthcare", "marketing"):
            assert expected in industries, f"Missing industry: {expected}"

    async def test_industries_are_strings(self, client: AsyncClient):
        """All industry names must be strings."""
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200
        for ind in resp.json()["industries"]:
            assert isinstance(ind, str)

    async def test_no_auth_required(self, client: AsyncClient):
        """Supported industries endpoint is public."""
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200

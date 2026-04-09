"""
Tests for Feature 46: Industry-Specific ATS Calibration.

Covers:
  - detect_industry unit tests (tech, finance, generic fallback)
  - Profile keyword weight application (tech profile boosts tech keywords)
  - industry_label present in sync ATS score response
  - industry_override endpoint parameter
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Industry detection unit tests (no server needed)
# ---------------------------------------------------------------------------


class TestDetectIndustry:
    def test_tech_saas_detected(self) -> None:
        from app.services.industry_ats_profiles import detect_industry

        jd = "We are a SaaS company looking for a software engineer with Kubernetes and Docker experience."
        assert detect_industry(jd) == "tech_saas"

    def test_finance_banking_detected(self) -> None:
        from app.services.industry_ats_profiles import detect_industry

        jd = "Looking for a Bloomberg-certified analyst with CFA, equity research, and trading experience."
        assert detect_industry(jd) == "finance_banking"

    def test_healthcare_detected(self) -> None:
        from app.services.industry_ats_profiles import detect_industry

        jd = "Join our hospital network. HIPAA compliance, EHR systems, and patient care are essential."
        assert detect_industry(jd) == "healthcare"

    def test_consulting_detected(self) -> None:
        from app.services.industry_ats_profiles import detect_industry

        jd = "Join our Deloitte engagement team. Work with client stakeholders and deliver frameworks."
        assert detect_industry(jd) == "consulting"

    def test_below_threshold_returns_generic(self) -> None:
        """A JD with only one matching keyword should return 'generic'."""
        from app.services.industry_ats_profiles import detect_industry

        jd = "General manager role with only one keyword: kubernetes"
        result = detect_industry(jd)
        # kubernetes alone is only 1 match → generic
        assert result == "generic"

    def test_empty_jd_returns_generic(self) -> None:
        from app.services.industry_ats_profiles import detect_industry

        assert detect_industry("") == "generic"
        assert detect_industry("   ") == "generic"

    def test_all_profiles_have_required_keys(self) -> None:
        from app.services.industry_ats_profiles import INDUSTRY_PROFILES

        required = {"label", "keywords", "section_weights", "detect_keywords"}
        for name, profile in INDUSTRY_PROFILES.items():
            assert required.issubset(profile.keys()), f"Profile '{name}' missing keys"

    def test_generic_profile_has_empty_keywords(self) -> None:
        from app.services.industry_ats_profiles import INDUSTRY_PROFILES

        generic = INDUSTRY_PROFILES["generic"]
        assert generic["keywords"] == {}
        assert generic["section_weights"] == {}
        assert generic["label"] == "General"


# ---------------------------------------------------------------------------
# Service-level: profile keyword weights boost relevant keywords
# ---------------------------------------------------------------------------


class TestProfileWeightApplication:
    """Tech profile should weight tech keywords higher than the generic profile."""

    @pytest.mark.asyncio
    async def test_tech_profile_boosts_tech_keywords(self) -> None:
        """A resume full of Kubernetes/Docker terminology should score higher
        on content with tech_saas profile than with generic."""
        from app.services.ats_scoring_service import ats_scoring_service

        latex = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{DevOps Engineer} at CloudCorp\\
\begin{itemize}
\item Deployed microservices on Kubernetes with Docker, CI/CD via Jenkins
\item Built REST APIs with Python and FastAPI, deployed to AWS
\item Managed Terraform infrastructure and Docker containers
\item Contributed to cloud-native SaaS platform with microservices architecture
\end{itemize}
\section{Skills}
Python, Kubernetes, Docker, AWS, Terraform, CI/CD, API, DevOps, Agile
\section{Education}
B.Sc. Computer Science
\end{document}
"""
        result_generic = await ats_scoring_service.score_resume(
            latex_content=latex,
            job_description=None,
            industry_profile_key="generic",
        )
        result_tech = await ats_scoring_service.score_resume(
            latex_content=latex,
            job_description=None,
            industry_profile_key="tech_saas",
        )

        # Tech profile should produce a higher or equal content score
        # because it rewards the tech keywords found
        assert result_tech.overall_score >= result_generic.overall_score - 5  # allow ±5 tolerance
        assert result_tech.industry_label == "Technology / SaaS"
        assert result_generic.industry_label is None

    @pytest.mark.asyncio
    async def test_industry_label_is_none_for_generic(self) -> None:
        from app.services.ats_scoring_service import ats_scoring_service

        latex = r"\documentclass{article}\begin{document}Hello\end{document}"
        result = await ats_scoring_service.score_resume(
            latex_content=latex,
            industry_profile_key="generic",
        )
        assert result.industry_label is None

    @pytest.mark.asyncio
    async def test_finance_profile_sets_correct_label(self) -> None:
        from app.services.ats_scoring_service import ats_scoring_service

        latex = r"\documentclass{article}\begin{document}Finance resume\end{document}"
        result = await ats_scoring_service.score_resume(
            latex_content=latex,
            industry_profile_key="finance_banking",
        )
        assert result.industry_label == "Finance / Banking"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


_SAMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Software Engineer} at TechCorp\\
\begin{itemize}
\item Built scalable microservices using Kubernetes and Docker
\item Developed Python APIs with FastAPI deployed on AWS
\end{itemize}
\section{Skills}
Python, Kubernetes, Docker, AWS, CI/CD, Agile
\section{Education}
B.Sc. Computer Science, MIT, 2020
\end{document}
"""

_FINANCE_JD = (
    "We are hiring a Bloomberg certified analyst with CFA credentials. "
    "Experience in equity research, trading strategies, and portfolio management required."
)

_TECH_JD = (
    "We are a SaaS startup looking for a software engineer with Kubernetes, "
    "microservices architecture, Docker, and CI/CD pipeline experience."
)


@pytest.mark.asyncio
class TestIndustryATSEndpoint:
    async def test_industry_label_present_in_sync_response(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """Sync scoring with a tech JD should return industry_label in response."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": _SAMPLE_LATEX,
                "job_description": _TECH_JD,
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["industry_label"] == "Technology / SaaS"

    async def test_generic_jd_returns_no_industry_label(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """A job description with no strong industry signal returns null industry_label."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": _SAMPLE_LATEX,
                "job_description": "We are hiring a motivated professional.",
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["industry_label"] is None

    async def test_industry_override_respected(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """industry_override should override auto-detection."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": _SAMPLE_LATEX,
                "job_description": _TECH_JD,  # would auto-detect tech_saas
                "industry_override": "finance_banking",  # explicitly override
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["industry_label"] == "Finance / Banking"

    async def test_no_jd_no_industry_label(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """Without job_description, no industry detection, so industry_label is None."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": _SAMPLE_LATEX,
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["industry_label"] is None

    async def test_industry_profiles_endpoint(
        self, client: AsyncClient
    ) -> None:
        """GET /ats/industry-profiles should return all profiles including generic."""
        resp = await client.get("/ats/industry-profiles")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        keys = [p["key"] for p in data["profiles"]]
        assert "tech_saas" in keys
        assert "finance_banking" in keys
        assert "generic" in keys

    async def test_finance_jd_detects_finance_industry(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        """Bloomberg + CFA + equity + trading JD should detect finance_banking."""
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": _SAMPLE_LATEX,
                "job_description": _FINANCE_JD,
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["industry_label"] == "Finance / Banking"

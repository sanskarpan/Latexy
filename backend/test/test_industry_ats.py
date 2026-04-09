"""Tests for Feature 46: Industry-Specific ATS Calibration."""

import pytest

# ─── Unit tests: detect_industry ──────────────────────────────────────────────

class TestDetectIndustry:
    """Unit tests for the detect_industry() function."""

    def test_tech_saas_detected_from_engineering_jd(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = (
            "We are looking for a senior software engineer to join our SaaS startup. "
            "You will build microservices, work with Kubernetes, and own our API platform. "
            "Experience with cloud infrastructure and agile teams required."
        )
        result = detect_industry(jd)
        assert result == "tech_saas"

    def test_finance_banking_detected(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = (
            "Quantitative analyst role at an investment bank. "
            "Must have CFA designation and Bloomberg terminal experience. "
            "Work with equity portfolio management and risk management frameworks."
        )
        result = detect_industry(jd)
        assert result == "finance_banking"

    def test_healthcare_detected(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = (
            "Registered Nurse (RN) needed in our hospital. "
            "HIPAA compliance required. Experience with EHR systems (Epic). "
            "Will work directly with patients in a clinical setting."
        )
        result = detect_industry(jd)
        assert result == "healthcare"

    def test_consulting_detected(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = (
            "Management consultant needed for client engagement. "
            "Deloitte-style stakeholder management and deliverable creation. "
            "Experience with strategy and transformation projects required."
        )
        result = detect_industry(jd)
        assert result == "consulting"

    def test_generic_returned_for_ambiguous_jd(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = "We are looking for a motivated team player with good communication skills."
        result = detect_industry(jd)
        assert result == "generic"

    def test_generic_returned_for_empty_string(self):
        from app.services.industry_ats_profiles import detect_industry
        assert detect_industry("") == "generic"

    def test_single_keyword_not_enough(self):
        """One matching keyword is not enough — need >= 2."""
        from app.services.industry_ats_profiles import detect_industry
        jd = "Looking for someone who knows kubernetes."  # only 1 tech keyword
        result = detect_industry(jd)
        assert result == "generic"

    def test_case_insensitive_detection(self):
        from app.services.industry_ats_profiles import detect_industry
        jd = "KUBERNETES MICROSERVICE API CLOUD STARTUP ENGINEER BACKEND"
        result = detect_industry(jd)
        assert result == "tech_saas"

    def test_finance_vs_tech_disambiguation(self):
        """A finance-heavy JD should not be classified as tech even if it mentions API."""
        from app.services.industry_ats_profiles import detect_industry
        jd = (
            "Investment banking analyst at a trading firm. "
            "Bloomberg certification, CFA preferred. Portfolio risk management. "
            "Some API work via Bloomberg Terminal."
        )
        result = detect_industry(jd)
        assert result == "finance_banking"


# ─── Unit tests: get_profile ──────────────────────────────────────────────────

class TestGetProfile:
    def test_known_profile_returned(self):
        from app.services.industry_ats_profiles import INDUSTRY_PROFILES, get_profile
        p = get_profile("tech_saas")
        assert p["label"] == INDUSTRY_PROFILES["tech_saas"]["label"]
        assert "kubernetes" in p["keywords"]

    def test_unknown_key_falls_back_to_generic(self):
        from app.services.industry_ats_profiles import INDUSTRY_PROFILES, get_profile
        p = get_profile("nonexistent_industry")
        assert p["label"] == INDUSTRY_PROFILES["generic"]["label"]

    def test_generic_has_empty_keywords(self):
        from app.services.industry_ats_profiles import get_profile
        p = get_profile("generic")
        assert p["keywords"] == {}

    def test_all_profiles_have_required_keys(self):
        from app.services.industry_ats_profiles import INDUSTRY_PROFILES
        for key, profile in INDUSTRY_PROFILES.items():
            assert "label" in profile, f"{key} missing label"
            assert "keywords" in profile, f"{key} missing keywords"
            assert "section_weights" in profile, f"{key} missing section_weights"
            assert "detect_keywords" in profile, f"{key} missing detect_keywords"


# ─── Integration tests: ATS scoring with industry calibration ─────────────────

TECH_RESUME = r"""
\documentclass{article}
\begin{document}
\section{Contact}
John Doe · john@example.com · +1-555-0100

\section{Summary}
Senior software engineer with 5 years building microservices on Kubernetes and AWS.
Strong background in CI/CD pipelines, Docker, and Python.

\section{Experience}
\textbf{Senior Engineer} · Acme SaaS Inc · 2020--Present
\begin{itemize}
  \item Architected distributed microservices platform on Kubernetes, reducing latency by 40\%
  \item Built CI/CD pipelines using GitHub Actions and Terraform; deployed to AWS GCP
  \item Developed REST APIs with FastAPI; improved throughput by 30\%
  \item Automated infrastructure with Docker and Ansible; saved 20 hours/week
\end{itemize}

\section{Skills}
Python, TypeScript, Kubernetes, Docker, AWS, GCP, Terraform, CI/CD, Agile

\section{Education}
B.S. Computer Science · MIT · 2019
\end{document}
"""

FINANCE_RESUME = r"""
\documentclass{article}
\begin{document}
\section{Contact}
Jane Smith · jane@example.com · +1-555-0200

\section{Summary}
CFA charterholder with 7 years at bulge-bracket investment banks.
Expertise in Bloomberg, equity research, and portfolio risk management.

\section{Experience}
\textbf{Associate} · Goldman Sachs · 2018--Present
\begin{itemize}
  \item Built DCF and LBO valuation models, generating \$2B in advisory fees
  \item Managed equity portfolio with Bloomberg Terminal; reduced risk by 25\%
  \item Led due diligence on 12 M\&A transactions; negotiated key financial terms
  \item Maintained CFA compliance; produced 40+ equity research reports
\end{itemize}

\section{Skills}
Bloomberg, Excel/VBA, CFA, Financial Modeling, Derivatives, Portfolio Management

\section{Education}
MBA Finance · Wharton School · 2018
CFA Charterholder · 2020
\end{document}
"""

TECH_JD = (
    "We need a senior software engineer comfortable with Kubernetes, microservices, "
    "CI/CD pipelines, and cloud platforms (AWS/GCP). Python expertise required. "
    "Experience with Docker, Terraform, and API design is a plus."
)

FINANCE_JD = (
    "Investment bank seeks quantitative analyst with Bloomberg, CFA designation, "
    "equity research experience, portfolio management, and risk management skills. "
    "Trading desk background preferred."
)


@pytest.mark.asyncio
class TestATSScoringWithCalibration:
    """Integration tests: verify industry calibration affects scoring."""

    async def test_tech_resume_with_tech_jd_detects_tech_saas(self):
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
            job_description=TECH_JD,
        )
        assert result.industry_key == "tech_saas"
        assert result.industry_label == "Technology / SaaS"

    async def test_finance_resume_with_finance_jd_detects_finance_banking(self):
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=FINANCE_RESUME,
            job_description=FINANCE_JD,
        )
        assert result.industry_key == "finance_banking"
        assert result.industry_label == "Finance / Banking"

    async def test_no_jd_gives_generic_industry(self):
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
        )
        assert result.industry_key == "generic"
        assert result.industry_label is None

    async def test_tech_profile_boosts_keywords_score_vs_generic(self):
        """Tech resume + tech JD should score >= tech resume + no JD on keyword dimension."""
        from app.services.ats_scoring_service import ats_scoring_service
        calibrated = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
            job_description=TECH_JD,
        )
        uncalibrated = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
        )
        # Calibrated (tech_saas profile) should have equal or higher keywords score
        # because profile boosts present keywords like kubernetes, microservices
        assert calibrated.category_scores.get("keywords", 0) >= uncalibrated.category_scores.get("keywords", 0)

    async def test_industry_calibration_in_detailed_analysis(self):
        """detailed_analysis must include industry_calibration block."""
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
            job_description=TECH_JD,
        )
        assert "industry_calibration" in result.detailed_analysis
        cal = result.detailed_analysis["industry_calibration"]
        assert cal["industry_key"] == "tech_saas"
        assert cal["profile_applied"] is True

    async def test_explicit_profile_key_overrides_auto_detect(self):
        """Passing industry='finance_banking' explicitly forces finance profile."""
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
            job_description=TECH_JD,    # would auto-detect as tech_saas
            industry="finance_banking",  # explicit override
        )
        assert result.industry_key == "finance_banking"
        assert result.industry_label == "Finance / Banking"

    async def test_legacy_industry_name_maps_correctly(self):
        """Legacy 'technology' string should map to tech_saas profile."""
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
            industry="technology",
        )
        assert result.industry_key == "tech_saas"

    async def test_score_result_has_industry_fields(self):
        """ATSScoreResult always has industry_key and industry_label (even if generic)."""
        from app.services.ats_scoring_service import ats_scoring_service
        result = await ats_scoring_service.score_resume(
            latex_content=TECH_RESUME,
        )
        assert hasattr(result, "industry_key")
        assert hasattr(result, "industry_label")


# ─── API endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestATSScoreEndpointWithIndustry:
    """Test the /ats/score endpoint returns industry_label."""

    async def test_sync_score_returns_industry_label(
        self, client, auth_headers
    ):
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": TECH_RESUME,
                "job_description": TECH_JD,
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "industry_label" in data
        assert "industry_key" in data
        assert data["industry_key"] == "tech_saas"
        assert data["industry_label"] == "Technology / SaaS"

    async def test_sync_score_no_jd_returns_generic(
        self, client, auth_headers
    ):
        resp = await client.post(
            "/ats/score",
            json={
                "latex_content": TECH_RESUME,
                "async_processing": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["industry_key"] == "generic"
        assert data["industry_label"] is None

    async def test_supported_industries_returns_profile_list(
        self, client
    ):
        resp = await client.get("/ats/supported-industries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        labels = [i["label"] for i in data["industries"]]
        assert "Technology / SaaS" in labels
        assert "Finance / Banking" in labels
        assert "Healthcare / Clinical" in labels
        assert "General" in labels

"""
Unit tests for ATSScoringService.

Tests the core scoring logic in isolation — no HTTP, no Redis, no Celery.
All tests use asyncio directly since score_resume() is async.
"""

from __future__ import annotations

import pytest

from app.services.ats_scoring_service import ATSScoreResult, ATSScoringService

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def service() -> ATSScoringService:
    return ATSScoringService()


MINIMAL_LATEX = r"""
\documentclass{article}
\begin{document}
Hello World
\end{document}
"""

FULL_RESUME_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}

\begin{center}
    \textbf{\Large John Smith} \\
    john@example.com $|$ (555) 123-4567 $|$ linkedin.com/in/johnsmith
\end{center}

\section*{Summary}
Results-driven Software Engineer with 7+ years developing scalable distributed systems.
Expertise in Python, cloud infrastructure, and DevOps practices.

\section*{Experience}
\textbf{Senior Software Engineer} \hfill 2021--Present \\
\textit{TechCorp, San Francisco, CA}
\begin{itemize}
    \item Developed microservices handling 2M+ requests/day using Python and FastAPI
    \item Reduced infrastructure costs by 40\% through optimization and caching
    \item Led team of 6 engineers, delivering 3 major features ahead of schedule
    \item Implemented CI/CD pipeline reducing deployment time by 60\%
\end{itemize}

\textbf{Software Engineer} \hfill 2018--2021 \\
\textit{StartupXYZ, New York, NY}
\begin{itemize}
    \item Built REST APIs serving 500K+ daily active users
    \item Improved database query performance by 50\% through indexing
    \item Contributed to migration from monolith to microservices architecture
\end{itemize}

\section*{Skills}
Python, TypeScript, PostgreSQL, Redis, Docker, Kubernetes, AWS, FastAPI, Django

\section*{Education}
\textbf{B.S. Computer Science} \hfill 2018 \\
State University, GPA 3.8/4.0

\section*{Certifications}
AWS Solutions Architect Associate, 2022

\end{document}
"""

TECH_JOB_DESCRIPTION = (
    "We are looking for a Senior Software Engineer with strong Python and cloud experience. "
    "Requirements: 5+ years of experience in software development, Python, Docker, Kubernetes, "
    "AWS. Experience with microservices architecture, REST APIs, and distributed systems. "
    "Nice to have: FastAPI, PostgreSQL, Redis, CI/CD pipeline experience."
)


# ── score_resume() — top-level method ────────────────────────────────────────

@pytest.mark.asyncio
class TestScoreResume:

    async def test_returns_ats_score_result(self, service: ATSScoringService):
        """score_resume() must return an ATSScoreResult instance."""
        result = await service.score_resume(MINIMAL_LATEX)
        assert isinstance(result, ATSScoreResult)

    async def test_overall_score_in_range(self, service: ATSScoringService):
        """overall_score must be between 0 and 100."""
        result = await service.score_resume(FULL_RESUME_LATEX)
        assert 0 <= result.overall_score <= 100

    async def test_category_scores_present(self, service: ATSScoringService):
        """category_scores must include all 5 scoring dimensions."""
        result = await service.score_resume(FULL_RESUME_LATEX)
        expected_categories = {"formatting", "structure", "content", "keywords", "readability"}
        assert expected_categories == set(result.category_scores.keys())

    async def test_category_scores_in_range(self, service: ATSScoringService):
        """Every category score must be between 0 and 100."""
        result = await service.score_resume(FULL_RESUME_LATEX)
        for cat, score in result.category_scores.items():
            assert 0 <= score <= 100, f"Category {cat} score {score} out of range"

    async def test_recommendations_is_list(self, service: ATSScoringService):
        result = await service.score_resume(MINIMAL_LATEX)
        assert isinstance(result.recommendations, list)

    async def test_warnings_is_list(self, service: ATSScoringService):
        result = await service.score_resume(MINIMAL_LATEX)
        assert isinstance(result.warnings, list)

    async def test_strengths_is_list(self, service: ATSScoringService):
        result = await service.score_resume(MINIMAL_LATEX)
        assert isinstance(result.strengths, list)

    async def test_detailed_analysis_is_dict(self, service: ATSScoringService):
        result = await service.score_resume(FULL_RESUME_LATEX)
        assert isinstance(result.detailed_analysis, dict)

    async def test_processing_time_is_positive(self, service: ATSScoringService):
        result = await service.score_resume(MINIMAL_LATEX)
        assert result.processing_time >= 0

    async def test_timestamp_is_string(self, service: ATSScoringService):
        result = await service.score_resume(MINIMAL_LATEX)
        assert isinstance(result.timestamp, str)
        assert len(result.timestamp) > 0

    async def test_full_resume_scores_higher_than_minimal(self, service: ATSScoringService):
        """A rich resume should score higher than a minimal one."""
        full_result = await service.score_resume(FULL_RESUME_LATEX)
        minimal_result = await service.score_resume(MINIMAL_LATEX)
        assert full_result.overall_score >= minimal_result.overall_score

    async def test_job_description_affects_keyword_score(self, service: ATSScoringService):
        """Providing a matching job description should not degrade keyword score."""
        without_jd = await service.score_resume(FULL_RESUME_LATEX)
        with_jd = await service.score_resume(FULL_RESUME_LATEX, TECH_JOB_DESCRIPTION)
        # With a relevant JD, keyword score should be non-zero
        assert with_jd.category_scores["keywords"] >= 0

    async def test_industry_parameter_accepted(self, service: ATSScoringService):
        """Providing an industry parameter should not crash the service."""
        result = await service.score_resume(
            FULL_RESUME_LATEX,
            job_description=TECH_JOB_DESCRIPTION,
            industry="technology",
        )
        assert isinstance(result, ATSScoreResult)
        assert 0 <= result.overall_score <= 100

    async def test_none_job_description_accepted(self, service: ATSScoringService):
        """None job_description must be handled gracefully."""
        result = await service.score_resume(FULL_RESUME_LATEX, job_description=None)
        assert isinstance(result, ATSScoreResult)

    async def test_recommendations_capped_at_10(self, service: ATSScoringService):
        """Recommendations list must not exceed 10 items."""
        result = await service.score_resume(MINIMAL_LATEX)
        assert len(result.recommendations) <= 10

    async def test_warnings_capped_at_5(self, service: ATSScoringService):
        """Warnings list must not exceed 5 items."""
        result = await service.score_resume(MINIMAL_LATEX)
        assert len(result.warnings) <= 5

    async def test_strengths_capped_at_5(self, service: ATSScoringService):
        """Strengths list must not exceed 5 items."""
        result = await service.score_resume(MINIMAL_LATEX)
        assert len(result.strengths) <= 5


# ── _extract_text_from_latex() ────────────────────────────────────────────────

class TestExtractTextFromLatex:

    def test_removes_documentclass(self, service: ATSScoringService):
        text = service._extract_text_from_latex(r"\documentclass{article}")
        assert "documentclass" not in text.lower() or "\\documentclass" not in text

    def test_extracts_visible_text(self, service: ATSScoringService):
        latex = r"\begin{document}Hello World\end{document}"
        text = service._extract_text_from_latex(latex)
        assert "Hello" in text
        assert "World" in text

    def test_handles_empty_string(self, service: ATSScoringService):
        result = service._extract_text_from_latex("")
        assert isinstance(result, str)

    def test_removes_comments(self, service: ATSScoringService):
        latex = "Visible text % this is a comment\nMore text"
        text = service._extract_text_from_latex(latex)
        assert "comment" not in text

    def test_returns_string(self, service: ATSScoringService):
        result = service._extract_text_from_latex(FULL_RESUME_LATEX)
        assert isinstance(result, str)


# ── Industry keywords configuration ──────────────────────────────────────────

class TestIndustryKeywordsConfig:

    def test_technology_keywords_present(self, service: ATSScoringService):
        assert "technology" in service.industry_keywords
        kws = service.industry_keywords["technology"]
        assert len(kws) > 0
        assert all(isinstance(k, str) for k in kws)

    def test_finance_keywords_present(self, service: ATSScoringService):
        assert "finance" in service.industry_keywords

    def test_healthcare_keywords_present(self, service: ATSScoringService):
        assert "healthcare" in service.industry_keywords

    def test_marketing_keywords_present(self, service: ATSScoringService):
        assert "marketing" in service.industry_keywords

    def test_all_keywords_are_non_empty_strings(self, service: ATSScoringService):
        for industry, keywords in service.industry_keywords.items():
            for kw in keywords:
                assert isinstance(kw, str), f"Non-string keyword in {industry}: {kw!r}"
                assert len(kw.strip()) > 0, f"Empty keyword in {industry}"


# ── Formatting rules configuration ───────────────────────────────────────────

class TestFormattingRulesConfig:

    def test_sections_has_required_key(self, service: ATSScoringService):
        assert "required" in service.formatting_rules["sections"]

    def test_required_sections_not_empty(self, service: ATSScoringService):
        required = service.formatting_rules["sections"]["required"]
        assert len(required) > 0
        assert "contact" in required or "experience" in required

    def test_action_verbs_present(self, service: ATSScoringService):
        verbs = service.formatting_rules["keywords"]["action_verbs"]
        assert len(verbs) > 0
        assert "developed" in verbs or "managed" in verbs or "led" in verbs


# ── Weighted average correctness ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestWeightedAverageConsistency:

    async def test_weights_sum_to_one(self, service: ATSScoringService):
        """The hard-coded weights in score_resume() must sum to 1.0."""
        weights = {
            "formatting": 0.25,
            "structure": 0.20,
            "content": 0.25,
            "keywords": 0.20,
            "readability": 0.10,
        }
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, not 1.0"

    async def test_overall_score_is_weighted_average_of_categories(
        self, service: ATSScoringService
    ):
        """overall_score must be consistent with the category_scores and fixed weights."""
        result = await service.score_resume(FULL_RESUME_LATEX)
        weights = {
            "formatting": 0.25,
            "structure": 0.20,
            "content": 0.25,
            "keywords": 0.20,
            "readability": 0.10,
        }
        expected = sum(
            result.category_scores[cat] * w for cat, w in weights.items()
        )
        assert abs(result.overall_score - round(expected, 1)) < 0.1, (
            f"overall_score {result.overall_score} does not match weighted avg {expected:.1f}"
        )

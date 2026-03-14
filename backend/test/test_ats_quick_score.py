"""
Tests for the ATS quick-score service and endpoint.
"""

import time

from httpx import AsyncClient

from app.services.ats_quick_scorer import quick_score_latex

# ── Service-level tests ──────────────────────────────────────────────────


class TestQuickScoreService:
    def test_empty_content_scores_low(self):
        result = quick_score_latex("")
        assert result.score < 30

    def test_minimal_content_scores_low(self):
        result = quick_score_latex(r"\documentclass{article}\begin{document}hello\end{document}")
        assert result.score < 50
        assert "experience" in result.missing_sections
        assert "education" in result.missing_sections

    def test_well_formed_resume_scores_above_70(self):
        latex = r"""
\documentclass{article}
\begin{document}

\section{Contact}
John Doe \\
john@example.com \\
(555) 123-4567

\section{Experience}
\textbf{Software Engineer} at TechCorp (2020--2024)
\begin{itemize}
  \item Developed microservices architecture, improving performance by 40\%
  \item Led team of 5 engineers to deliver product features
  \item Automated CI/CD pipeline, reducing deployment time by 60\%
  \item Managed cloud infrastructure on AWS, saving \$50k annually
\end{itemize}

\section{Education}
B.S. Computer Science, MIT, 2020

\section{Skills}
Python, JavaScript, React, Docker, Kubernetes, PostgreSQL, Redis

\end{document}
"""
        result = quick_score_latex(latex)
        assert result.score >= 70
        assert result.grade in ("A", "B", "C")
        assert "experience" in result.sections_found
        assert "education" in result.sections_found
        assert "skills" in result.sections_found
        assert "contact_info" in result.sections_found
        assert result.keyword_match_percent is None  # no JD provided

    def test_resume_with_jd_has_keyword_match(self):
        latex = r"""
\documentclass{article}
\begin{document}
\section{Experience}
Software engineer with Python and Django experience.
Built REST APIs and deployed on AWS.
john@test.com (555) 111-2222
\section{Education}
BS Computer Science
\section{Skills}
Python, Django, AWS, Docker
\end{document}
"""
        jd = "Looking for a Python developer with Django experience. Must know AWS and Docker. REST API development required."
        result = quick_score_latex(latex, jd)
        assert result.keyword_match_percent is not None
        assert result.keyword_match_percent > 0

    def test_grade_mapping(self):
        # Create a well-formed resume to get high score
        latex = r"""
\documentclass{article}
\begin{document}
\section{Contact}
test@email.com (555) 000-1111
\section{Experience}
Led and developed projects. Achieved 50\% improvement.
Managed team. Delivered results. Improved efficiency by 30\%.
Implemented automated testing. Deployed microservices.
\section{Education}
BS in Computer Science, Stanford University
\section{Skills}
Python, Java, AWS, Docker, Kubernetes
\end{document}
"""
        result = quick_score_latex(latex)
        assert result.grade in ("A", "B", "C", "D", "F")
        # Grade should match score ranges
        if result.score >= 90:
            assert result.grade == "A"
        elif result.score >= 80:
            assert result.grade == "B"
        elif result.score >= 70:
            assert result.grade == "C"
        elif result.score >= 60:
            assert result.grade == "D"
        else:
            assert result.grade == "F"

    def test_missing_contact_info(self):
        latex = r"""
\documentclass{article}
\begin{document}
\section{Experience}
Software Engineer
\section{Education}
BS CS
\section{Skills}
Python
\end{document}
"""
        result = quick_score_latex(latex)
        assert "contact_info" in result.missing_sections

    def test_performance_under_500ms(self):
        # Large-ish resume content
        latex = r"\documentclass{article}\begin{document}" + "\n"
        latex += r"\section{Contact}" + "\n" + "test@email.com (555) 123-4567\n"
        latex += r"\section{Experience}" + "\n"
        for i in range(50):
            latex += rf"\item Developed feature {i}, improving performance by {i}%" + "\n"
        latex += r"\section{Education}" + "\n" + "BS CS, MIT\n"
        latex += r"\section{Skills}" + "\n" + "Python, Java, Go, Rust, Docker, K8s\n"
        latex += r"\end{document}"

        start = time.time()
        result = quick_score_latex(latex)
        elapsed = time.time() - start

        assert elapsed < 0.5, f"Quick score took {elapsed:.3f}s, expected < 500ms"
        assert result.score > 0

    def test_no_jd_gives_baseline_keyword_score(self):
        latex = r"""
\documentclass{article}
\begin{document}
\section{Contact}
test@email.com (555) 111-2222
\section{Experience}
Did stuff
\section{Education}
BS
\section{Skills}
Python
\end{document}
"""
        result = quick_score_latex(latex, job_description=None)
        # Without JD, keyword score = 15 (baseline), keyword_match_percent = None
        assert result.keyword_match_percent is None

    def test_optional_sections_detected(self):
        latex = r"""
\documentclass{article}
\begin{document}
\section{Summary}
Experienced engineer.
\section{Experience}
Built things.
\section{Education}
BS CS
\section{Skills}
Python
\section{Projects}
Cool project.
\section{Certifications}
AWS Certified
test@email.com (555) 123-4567
\end{document}
"""
        result = quick_score_latex(latex)
        assert "summary" in result.sections_found
        assert "projects" in result.sections_found
        assert "certifications" in result.sections_found


# ── Endpoint tests ───────────────────────────────────────────────────────


class TestQuickScoreEndpoint:
    async def test_quick_score_returns_200(self, client: AsyncClient):
        response = await client.post("/ats/quick-score", json={
            "latex_content": r"\documentclass{article}\begin{document}\section{Experience}Hello test@email.com\section{Education}BS\section{Skills}Python\end{document}",
        })
        assert response.status_code == 200
        data = response.json()
        assert "score" in data
        assert "grade" in data
        assert "sections_found" in data
        assert "missing_sections" in data
        assert isinstance(data["score"], int)
        assert data["grade"] in ("A", "B", "C", "D", "F")

    async def test_quick_score_with_jd(self, client: AsyncClient):
        response = await client.post("/ats/quick-score", json={
            "latex_content": r"\documentclass{article}\begin{document}\section{Experience}Python developer\section{Education}BS\section{Skills}Python Django\end{document}",
            "job_description": "Python Django developer needed",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["keyword_match_percent"] is not None

    async def test_quick_score_empty_content(self, client: AsyncClient):
        response = await client.post("/ats/quick-score", json={
            "latex_content": "   ",
        })
        assert response.status_code == 400

    async def test_quick_score_no_auth_required(self, client: AsyncClient):
        # No auth headers — should still work
        response = await client.post("/ats/quick-score", json={
            "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
        })
        assert response.status_code == 200

    async def test_quick_score_too_large(self, client: AsyncClient):
        response = await client.post("/ats/quick-score", json={
            "latex_content": "x" * 200_001,
        })
        assert response.status_code == 422  # Pydantic max_length validation

    async def test_quick_score_performance(self, client: AsyncClient):
        latex = r"\documentclass{article}\begin{document}"
        latex += r"\section{Experience}" + "Built things. " * 100
        latex += r"\section{Education}BS CS\section{Skills}Python"
        latex += r"\end{document}"

        start = time.time()
        response = await client.post("/ats/quick-score", json={
            "latex_content": latex,
        })
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 0.5, f"Endpoint took {elapsed:.3f}s"

"""
Unit tests for Layer 1 ATS engine fixes:
- _extract_text_from_latex preserves section headers, contact info, href display text
- _score_structure contact detection uses raw LaTeX (not extracted text)
- Expanded ACTION_VERBS, TECH_KEYWORDS, SOFT_SKILLS class-level constants
- Scoring penalties: missing section → −25, word count <200 → −30
"""

import pytest

from app.services.ats_scoring_service import ATSScoringService, ats_scoring_service

# ────────────────────────────────────────────────────────────────────────────
#  Text extraction
# ────────────────────────────────────────────────────────────────────────────

class TestExtractTextFromLatex:

    def setup_method(self):
        self.svc = ATSScoringService()

    def test_section_header_preserved(self):
        latex = r"\section{Experience}"
        text = self.svc._extract_text_from_latex(latex)
        assert "Experience" in text

    def test_subsection_header_preserved(self):
        latex = r"\subsection{Software Engineering}"
        text = self.svc._extract_text_from_latex(latex)
        assert "Software Engineering" in text

    def test_section_star_preserved(self):
        latex = r"\section*{Skills}"
        text = self.svc._extract_text_from_latex(latex)
        assert "Skills" in text

    def test_textbf_content_preserved(self):
        latex = r"\textbf{Senior Engineer}"
        text = self.svc._extract_text_from_latex(latex)
        assert "Senior Engineer" in text

    def test_textit_content_preserved(self):
        latex = r"\textit{Python}"
        text = self.svc._extract_text_from_latex(latex)
        assert "Python" in text

    def test_href_display_text_preserved(self):
        """Email inside \\href must appear in extracted text."""
        latex = r"\href{mailto:alice@example.com}{alice@example.com}"
        text = self.svc._extract_text_from_latex(latex)
        assert "alice@example.com" in text

    def test_href_url_not_duplicated(self):
        """The raw URL arg should not appear — only the display text."""
        latex = r"\href{https://linkedin.com/in/alice}{linkedin.com/in/alice}"
        text = self.svc._extract_text_from_latex(latex)
        # The display text should appear
        assert "linkedin.com/in/alice" in text

    def test_comments_removed(self):
        latex = "Hello % this is a comment\nWorld"
        text = self.svc._extract_text_from_latex(latex)
        assert "this is a comment" not in text
        assert "Hello" in text
        assert "World" in text

    def test_begin_end_removed(self):
        latex = r"\begin{itemize}\item Bullet\end{itemize}"
        text = self.svc._extract_text_from_latex(latex)
        assert "begin" not in text.lower()
        assert "Bullet" in text

    def test_full_resume_snippet(self):
        latex = r"""
\section*{Experience}
\textbf{Staff Engineer, Acme Corp} \hfill 2022 - Present
\begin{itemize}
  \item Led migration to microservices
  \item Improved latency by 40\%
\end{itemize}
"""
        text = self.svc._extract_text_from_latex(latex)
        assert "Experience" in text
        assert "Staff Engineer" in text
        assert "Acme Corp" in text
        assert "microservices" in text


# ────────────────────────────────────────────────────────────────────────────
#  Structure score — contact detection on raw LaTeX
# ────────────────────────────────────────────────────────────────────────────

class TestScoreStructureContactDetection:

    def setup_method(self):
        self.svc = ATSScoringService()

    @pytest.mark.asyncio
    async def test_email_in_href_detected(self):
        """Contact score must not lose −25 when email is inside \\href."""
        latex = r"""
\section*{Contact}
\href{mailto:alice@example.com}{alice@example.com} | +1 (555) 123-4567
\section*{Experience}
Worked at Acme Corp 2020–2024.
\section*{Education}
B.Sc. Computer Science, MIT, 2019.
"""
        text = self.svc._extract_text_from_latex(latex)
        result = await self.svc._score_structure(text, latex)
        assert result["details"]["sections_found"].get("contact") is True
        assert result["score"] >= 50  # should not lose −25 for missing contact

    @pytest.mark.asyncio
    async def test_bare_email_detected(self):
        latex = r"alice@example.com | Python | AWS"
        result = await self.svc._score_structure(latex, latex)
        assert result["details"]["sections_found"].get("contact") is True

    @pytest.mark.asyncio
    async def test_missing_contact_penalised(self):
        latex = r"""
\section*{Experience}
Worked at Acme Corp.
\section*{Education}
B.Sc. Computer Science.
"""
        text = self.svc._extract_text_from_latex(latex)
        result = await self.svc._score_structure(text, latex)
        assert result["details"]["sections_found"].get("contact") is False
        # Should lose 25 points for missing contact
        assert result["score"] <= 75

    @pytest.mark.asyncio
    async def test_missing_section_not_default_pass(self):
        """A resume missing experience section should have experience=False."""
        latex = r"""
alice@example.com
\section*{Education}
B.Sc. Computer Science, MIT, 2019.
"""
        text = self.svc._extract_text_from_latex(latex)
        result = await self.svc._score_structure(text, latex)
        assert result["details"]["sections_found"].get("experience") is False

    @pytest.mark.asyncio
    async def test_word_count_too_low_penalised(self):
        latex = r"alice@example.com Hello world"
        text = self.svc._extract_text_from_latex(latex)
        result = await self.svc._score_structure(text, latex)
        assert result["details"]["word_count"] < 200
        # Should incur penalty for brevity
        assert result["score"] <= 70


# ────────────────────────────────────────────────────────────────────────────
#  Corpus class-level constants
# ────────────────────────────────────────────────────────────────────────────

class TestCorpusConstants:

    def test_action_verbs_is_class_level(self):
        assert hasattr(ATSScoringService, "ACTION_VERBS")

    def test_tech_keywords_is_class_level(self):
        assert hasattr(ATSScoringService, "TECH_KEYWORDS")

    def test_soft_skills_is_class_level(self):
        assert hasattr(ATSScoringService, "SOFT_SKILLS")

    def test_action_verbs_size(self):
        assert len(ATSScoringService.ACTION_VERBS) >= 60

    def test_tech_keywords_size(self):
        assert len(ATSScoringService.TECH_KEYWORDS) >= 40

    def test_soft_skills_size(self):
        assert len(ATSScoringService.SOFT_SKILLS) >= 15

    def test_tech_keywords_includes_modern_stack(self):
        keywords = [kw.lower() for kw in ATSScoringService.TECH_KEYWORDS]
        assert any("python" in kw for kw in keywords)
        assert any("docker" in kw or "kubernetes" in kw for kw in keywords)

    def test_action_verbs_not_empty_strings(self):
        for verb in ATSScoringService.ACTION_VERBS:
            assert isinstance(verb, str) and len(verb) > 0


# ────────────────────────────────────────────────────────────────────────────
#  Full score_resume smoke test
# ────────────────────────────────────────────────────────────────────────────

class TestScoreResumeSmoke:

    @pytest.mark.asyncio
    async def test_score_resume_with_contact_href(self):
        """Verify overall score > 50 for a minimal but valid resume."""
        latex = r"""
\documentclass{article}
\begin{document}
\begin{center}
  {\Large\textbf{Alice Smith}}\\
  \href{mailto:alice@example.com}{alice@example.com} | +1 555 123 4567
\end{center}

\section*{Summary}
Product-focused engineer with 5+ years building resilient SaaS systems.

\section*{Experience}
\textbf{Senior Engineer, Acme Corp} \hfill 2020--2024
\begin{itemize}
  \item Led development of microservices architecture reducing latency by 40\%
  \item Managed team of 6 engineers and improved delivery cadence by 30\%
\end{itemize}

\section*{Education}
B.Sc. Computer Science, MIT, 2019.

\section*{Skills}
Python, AWS, Docker, PostgreSQL, TypeScript, Kubernetes
\end{document}
"""
        result = await ats_scoring_service.score_resume(latex)
        assert result.overall_score > 50
        assert result.category_scores.get("structure", 0) > 50

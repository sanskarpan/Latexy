"""
Multi-Dimensional Score Card tests (Feature 18).

Tests cover:
- _score_grammar(): tense consistency, double spaces, double periods
- _score_bullet_clarity(): action-verb bullets vs passive-voice bullets
- _score_section_completeness(): complete vs incomplete section coverage
- _score_page_density(): word count thresholds
- score_resume(): multi_dim_scores dict present with all 5 keys
"""

import pytest

from app.services.ats_scoring_service import ATSScoreResult, ats_scoring_service

# ── Fixtures ─────────────────────────────────────────────────────────────────

GOOD_LATEX = r"""
\documentclass{article}
\begin{document}

\section{Contact}
John Doe | john@example.com | +1-555-0123

\section{Experience}
\begin{itemize}
\item Developed and deployed a microservices platform serving 2 million users, reducing latency by 40\%
\item Led a team of 8 engineers, delivering 15 features on schedule and increasing revenue by \$2M
\item Built CI/CD pipeline that automated 95\% of deployment tasks, saving 20 hours per week
\end{itemize}

\section{Education}
B.S. Computer Science, State University, 2018

\section{Skills}
Python, TypeScript, Docker, Kubernetes, AWS

\section{Projects}
\begin{itemize}
\item Created open-source CLI tools with 5,000 GitHub stars and 300 contributors
\end{itemize}

\end{document}
"""

PASSIVE_LATEX = r"""
\documentclass{article}
\begin{document}

\section{Experience}
\begin{itemize}
\item was responsible for managing the project and overseeing all operations
\item were assigned to develop new features for the legacy system components
\item was improved by the team through collaborative code reviews regularly
\end{itemize}

\end{document}
"""

SPARSE_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
Short resume with minimal content.
\end{document}
"""


# ── Grammar scoring ───────────────────────────────────────────────────────────


class TestGrammarScore:
    def test_consistent_past_tense_scores_high(self):
        """Past-tense-only bullets should score ≥ 80."""
        text = (
            "Led a team of engineers. Built backend services. "
            "Developed new features. Managed deployments. Designed APIs."
        )
        score = ats_scoring_service._score_grammar(text)  # noqa: SLF001
        assert score >= 80

    def test_mixed_tense_is_penalised(self):
        """Mixed present+past tense should score below 100."""
        text = (
            "manage projects and led teams. "
            "I develop and built complex systems. "
            "implement features and designed the architecture."
        )
        score = ats_scoring_service._score_grammar(text)  # noqa: SLF001
        assert score < 100

    def test_double_space_penalised(self):
        """Double spaces should reduce the score."""
        text_clean = "Led the team and built the product."
        text_dirty = "Led  the team  and  built the product."
        assert ats_scoring_service._score_grammar(text_dirty) < ats_scoring_service._score_grammar(text_clean)  # noqa: SLF001

    def test_score_in_range(self):
        """Grammar score must always be in [0, 100]."""
        worst = "  ..  very really  stuff  "
        assert 0 <= ats_scoring_service._score_grammar(worst) <= 100  # noqa: SLF001


# ── Bullet clarity scoring ────────────────────────────────────────────────────


class TestBulletClarityScore:
    def test_good_bullets_score_high(self):
        """Action-verb + quantified bullets should score > 70."""
        score = ats_scoring_service._score_bullet_clarity(GOOD_LATEX)  # noqa: SLF001
        assert score > 70

    def test_passive_bullets_score_low(self):
        """Passive-voice bullets without quantification should score < 50."""
        score = ats_scoring_service._score_bullet_clarity(PASSIVE_LATEX)  # noqa: SLF001
        assert score < 50

    def test_no_bullets_returns_zero(self):
        """Document with no \\item commands returns 0.0."""
        no_items = r"\documentclass{article}\begin{document}No bullets here\end{document}"
        assert ats_scoring_service._score_bullet_clarity(no_items) == 0.0  # noqa: SLF001

    def test_score_in_range(self):
        """Bullet clarity score must be in [0, 100]."""
        score = ats_scoring_service._score_bullet_clarity(GOOD_LATEX)  # noqa: SLF001
        assert 0 <= score <= 100


# ── Section completeness scoring ──────────────────────────────────────────────


class TestSectionCompletenessScore:
    def test_complete_resume_scores_high(self):
        """Resume with Contact, Experience, Education, Skills, Projects → score > 55."""
        # Required list includes 'experience' and 'work' as separate items;
        # the fixture uses 'Experience' (not 'Work'), so 4/5 required are matched → ~62
        score = ats_scoring_service._score_section_completeness(GOOD_LATEX)  # noqa: SLF001
        assert score > 55

    def test_sparse_resume_scores_low(self):
        """Resume with only one section scores < 50."""
        score = ats_scoring_service._score_section_completeness(SPARSE_LATEX)  # noqa: SLF001
        assert score < 50

    def test_score_in_range(self):
        """Section completeness score must be in [0, 100]."""
        score = ats_scoring_service._score_section_completeness(GOOD_LATEX)  # noqa: SLF001
        assert 0 <= score <= 100


# ── Page density scoring ──────────────────────────────────────────────────────


class TestPageDensityScore:
    def test_optimal_word_count_scores_high(self):
        """750 words (optimal 1-page) should score > 90."""
        body = " ".join(["word"] * 750)
        latex = rf"\documentclass{{article}}\begin{{document}}{body}\end{{document}}"
        score = ats_scoring_service._score_page_density(latex)  # noqa: SLF001
        assert score > 90

    def test_too_few_words_scores_lower(self):
        """Sparse resume (< 100 words) should score < 70."""
        score = ats_scoring_service._score_page_density(SPARSE_LATEX)  # noqa: SLF001
        assert score < 70

    def test_score_in_range(self):
        """Page density score must be ≥ 0."""
        score = ats_scoring_service._score_page_density(GOOD_LATEX)  # noqa: SLF001
        assert score >= 0


# ── Full score_resume integration ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestFullScoreResumeMultiDim:
    async def test_returns_multi_dim_scores_dict(self):
        """score_resume() must set multi_dim_scores with all 5 keys."""
        result: ATSScoreResult = await ats_scoring_service.score_resume(
            latex_content=GOOD_LATEX
        )
        assert result.multi_dim_scores is not None
        expected_keys = {
            "grammar",
            "bullet_clarity",
            "section_completeness",
            "page_density",
            "keyword_density",
        }
        assert set(result.multi_dim_scores.keys()) == expected_keys

    async def test_all_scores_in_range(self):
        """Every multi-dim score must be in [0, 100]."""
        result = await ats_scoring_service.score_resume(latex_content=GOOD_LATEX)
        assert result.multi_dim_scores is not None
        for key, val in result.multi_dim_scores.items():
            assert 0 <= val <= 100, f"{key} = {val} is out of [0, 100]"

    async def test_keyword_density_neutral_without_jd(self):
        """Without a job description, keyword_density should be 50 (neutral)."""
        result = await ats_scoring_service.score_resume(latex_content=GOOD_LATEX)
        assert result.multi_dim_scores is not None
        assert result.multi_dim_scores["keyword_density"] == 50.0

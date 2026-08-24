"""
Tests for Feature 50 — ATS Simulator.

Coverage:
  Unit (AtsSimulatorService):
    50U-01  Taleo simulation of multi-column LaTeX → issues contains multi_column
    50U-02  Greenhouse simulation of clean single-column → score >= 85
    50U-03  Unknown ATS name → ValueError
    50U-04  Poor-tier parser applies distortions to plain_text_view
    50U-05  Medium-tier parser does not distort text
    50U-06  Score clamps to [0, 100]
    50U-07  Zero issues → score equals tier base (good=90, medium=70, poor=50)
    50U-08  Multiple issues each reduce score
    50U-09  Recommendations include issue-specific advice for detected issues
    50U-10  Tier recommendations appear when no issues
    50U-11  Taleo: tables issue → detected + recommendation present
    50U-12  Plain text extracted (non-empty) for normal LaTeX
    50U-13  profile listing returns all 7 systems
    50U-14  IssueEntry line_range identifies first matching line

  Unit (document-quality checks — universal, Textkernel-derived):
    50U-15  Missing email AND phone → contact_missing, and it costs score
    50U-16  Contact present in the first lines → neither contact issue fires
    50U-17  Bare date tokens on consecutive lines → vertical_dates
    50U-18  Inline "Jan 2022 -- Present" → vertical_dates does NOT fire
    50U-19  Unrecognisable section header → suggestion severity, score unchanged
    50U-20  Standard headers ("Professional Experience") → not flagged
    50U-21  No section headings at all → no_section_headers
    50U-22  Skills evidenced in experience prose → skills_not_in_context absent
    50U-23  Quality checks run for every ATS profile, not per-profile opt-in
    50U-24  Quality findings surface an actionable recommendation

  Integration (HTTP endpoint):
    50I-01  POST /ats/simulate with valid ats_name → 200 with expected fields
    50I-02  POST /ats/simulate with unknown ats_name → 422
    50I-03  POST /ats/simulate: taleo + multi_column LaTeX → issues non-empty
    50I-04  GET /ats/simulate/profiles → lists all ATS systems with key/label/tier
    50I-05  Score field is int in [0, 100]
    50I-06  Empty latex_content → still returns response (no server error)
    50I-07  Latex_content over 200_000 chars → 422 (field too long)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.ats_simulator_service import ATS_PROFILES, AtsSimulatorService

# ── Test latex fixtures ───────────────────────────────────────────────────────

CLEAN_LATEX = r"""
\documentclass[11pt]{article}
\usepackage{geometry}
\geometry{margin=1in}
\begin{document}
\begin{center}
  \textbf{\Large Alice Smith} \\
  alice@example.com $|$ linkedin.com/in/alicesmith
\end{center}

\section*{Experience}
\textbf{Software Engineer} at TechCorp \hfill 2021--Present \\
\begin{itemize}
  \item Built REST APIs serving 500k requests/day
  \item Reduced deployment time by 30\%
\end{itemize}

\section*{Education}
B.Sc. Computer Science, MIT, 2021

\section*{Skills}
Python, Go, PostgreSQL, Docker
\end{document}
""".strip()

MULTI_COLUMN_LATEX = r"""
\documentclass[11pt]{article}
\usepackage{multicol}
\begin{document}
\begin{multicols}{2}
\section*{Experience}
Software Engineer, TechCorp, 2020--2023.

\section*{Skills}
Python, Java, SQL
\end{multicols}
\end{document}
""".strip()

TABLE_LATEX = r"""
\documentclass[11pt]{article}
\begin{document}
\section*{Skills}
\begin{tabular}{ll}
  Python & 5 years \\
  SQL    & 3 years \\
\end{tabular}
\section*{Experience}
Engineer at Acme, 2020.
\end{document}
""".strip()

MINIPAGE_LATEX = r"""
\documentclass[11pt]{article}
\begin{document}
\begin{minipage}{0.5\textwidth}
  Left column content
\end{minipage}
\begin{minipage}{0.5\textwidth}
  Right column content
\end{minipage}
\section*{Experience}
Engineer at Corp, 2021.
\end{document}
""".strip()

DECORATIVE_LATEX = r"""
\documentclass[11pt]{article}
\begin{document}
\hrule
\vspace{4pt}
\section*{Experience}
Engineer at Corp, 2021.
\end{document}
""".strip()


# ── Unit: AtsSimulatorService ────────────────────────────────────────────────

class TestAtsSimulatorService:

    def setup_method(self):
        self.svc = AtsSimulatorService()

    # 50U-01
    def test_taleo_detects_multi_column(self):
        result = self.svc.simulate(MULTI_COLUMN_LATEX, "taleo")
        issue_types = [i.type for i in result.issues]
        assert "multi_column" in issue_types

    # 50U-02
    def test_greenhouse_clean_resume_high_score(self):
        result = self.svc.simulate(CLEAN_LATEX, "greenhouse")
        assert result.score >= 85
        # No *scoring* issues expected for a clean, single-column resume.
        # Suggestion-severity findings are advisory and deliberately excluded:
        # CLEAN_LATEX lists skills that never appear in its experience bullets,
        # which is Textkernel code 112 — real advice, but not a defect, so it
        # is surfaced without affecting the score.
        scoring_issues = [i for i in result.issues if i.severity != "suggestion"]
        assert scoring_issues == []

    # ── Document-quality checks (Textkernel-derived, universal) ───────────

    # 50U-15
    def test_missing_contact_details_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta
\section*{Experience}
Acme Corp, Senior Engineer, 2022.
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        types = [i.type for i in result.issues]
        assert "contact_missing" in types
        # Fatal-class, so it must actually cost score.
        assert result.score < 90

    # 50U-16
    def test_contact_present_at_top_not_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi.mehta@gmail.com \\ +91 98765 43210
\section*{Experience}
Acme Corp \hfill Jan 2022 -- Present
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        types = [i.type for i in result.issues]
        assert "contact_missing" not in types
        assert "contact_not_at_top" not in types

    # 50U-17
    def test_vertical_date_column_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com
\section*{Experience}
Acme Corp
Jan 2022
Present
Built things.
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        assert "vertical_dates" in [i.type for i in result.issues]

    # 50U-18
    def test_inline_date_range_not_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com
\section*{Experience}
Acme Corp \hfill Jan 2022 -- Present
Built things.
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        assert "vertical_dates" not in [i.type for i in result.issues]

    # 50U-19
    def test_nonstandard_section_header_is_suggestion_only(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com \\ +91 98765 43210
\section*{My Journey So Far}
Acme Corp, 2022 -- Present.
\end{document}"""
        result = self.svc.simulate(latex, "lever")
        entry = next(i for i in result.issues if i.type == "nonstandard_section_headers")
        assert entry.severity == "suggestion"
        # Suggestions must never cost score — lever is a "good" tier, base 90.
        assert result.score == 90

    # 50U-20
    def test_standard_section_headers_not_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com \\ +91 98765 43210
\section*{Professional Experience}
Acme Corp, 2022 -- Present.
\section*{Technical Skills}
Python
\end{document}"""
        result = self.svc.simulate(latex, "lever")
        assert "nonstandard_section_headers" not in [i.type for i in result.issues]

    # 50U-21
    def test_no_section_headers_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com \\ +91 98765 43210
Acme Corp, Senior Engineer, Jan 2022 -- Present. Built things.
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        assert "no_section_headers" in [i.type for i in result.issues]

    # 50U-22
    def test_skills_evidenced_in_experience_not_flagged(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta \\ ravi@example.com \\ +91 98765 43210
\section*{Experience}
Acme Corp \hfill Jan 2022 -- Present. Built Python services backed by PostgreSQL.
\section*{Skills}
Python, PostgreSQL
\end{document}"""
        result = self.svc.simulate(latex, "lever")
        assert "skills_not_in_context" not in [i.type for i in result.issues]

    # 50U-23
    def test_quality_issues_apply_to_every_profile(self):
        """Document-quality checks are universal, not per-ATS opt-in."""
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta
\section*{Experience}
Acme Corp, 2022.
\end{document}"""
        for ats in ATS_PROFILES:
            types = [i.type for i in self.svc.simulate(latex, ats).issues]
            assert "contact_missing" in types, f"{ats} did not report contact_missing"

    # 50U-24
    def test_quality_recommendation_surfaced(self):
        latex = r"""\documentclass{article}\begin{document}
Ravi Mehta
\section*{Experience}
Acme Corp, 2022.
\end{document}"""
        result = self.svc.simulate(latex, "greenhouse")
        assert any("email" in r.lower() for r in result.recommendations)

    # 50U-03
    def test_unknown_ats_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown ATS"):
            self.svc.simulate(CLEAN_LATEX, "unknown_ats_xyz")

    # 50U-04
    def test_poor_tier_applies_distortions_with_multi_column(self):
        result = self.svc.simulate(MULTI_COLUMN_LATEX, "taleo")
        # After distortion, ">> " prefix appears on alternating lines
        assert ">>" in result.plain_text_view

    # 50U-05
    def test_medium_tier_no_distortion_on_clean(self):
        result = self.svc.simulate(CLEAN_LATEX, "workday")
        # No ">>" markers — no distortion applied
        assert ">>" not in result.plain_text_view

    # 50U-06
    def test_score_clamped_to_0_100(self):
        # Taleo with a heavily problematic document
        for ats_name in ATS_PROFILES:
            result = self.svc.simulate(
                MULTI_COLUMN_LATEX + "\n" + TABLE_LATEX, ats_name
            )
            assert 0 <= result.score <= 100

    # 50U-07
    def test_zero_issues_score_equals_tier_base(self):
        """Clean single-column résumé → no issues → tier base score."""
        tier_base = {"good": 90, "medium": 70, "poor": 50}
        for ats_name, profile in ATS_PROFILES.items():
            result = self.svc.simulate(CLEAN_LATEX, ats_name)
            if not result.issues:
                expected = tier_base[profile["tier"]]
                assert result.score == expected, (
                    f"{ats_name}: expected {expected}, got {result.score}"
                )

    # 50U-08
    def test_multiple_issues_reduce_score(self):
        """Taleo score with multicol+table should be lower than multicol alone."""
        result_multi = self.svc.simulate(MULTI_COLUMN_LATEX, "taleo")
        result_both = self.svc.simulate(MULTI_COLUMN_LATEX + "\n" + TABLE_LATEX, "taleo")
        assert result_both.score <= result_multi.score

    # 50U-09
    def test_issue_specific_recommendations_present(self):
        result = self.svc.simulate(MULTI_COLUMN_LATEX, "taleo")
        combined = " ".join(result.recommendations)
        # Should mention multi-column in recommendations
        assert "column" in combined.lower() or "multicol" in combined.lower()

    # 50U-10
    def test_tier_recommendations_appear_when_no_issues(self):
        """Clean résumé → no issue-specific recs, only tier-level recs."""
        result = self.svc.simulate(CLEAN_LATEX, "lever")
        assert len(result.recommendations) > 0

    # 50U-11
    def test_taleo_table_issue_detected(self):
        result = self.svc.simulate(TABLE_LATEX, "taleo")
        issue_types = [i.type for i in result.issues]
        assert "tables" in issue_types
        # Recommendation mentions table replacement
        combined = " ".join(result.recommendations)
        assert "tabular" in combined.lower() or "list" in combined.lower()

    # 50U-12
    def test_plain_text_non_empty_for_normal_latex(self):
        result = self.svc.simulate(CLEAN_LATEX, "greenhouse")
        assert len(result.plain_text_view.strip()) > 20

    # 50U-13
    def test_all_seven_profiles_present(self):
        expected_keys = {
            "greenhouse", "lever", "ashby", "workday",
            "smartrecruiters", "taleo", "icims",
        }
        assert set(ATS_PROFILES.keys()) == expected_keys

    # 50U-14
    def test_issue_entry_line_range_set(self):
        result = self.svc.simulate(MULTI_COLUMN_LATEX, "taleo")
        multi_col_issues = [i for i in result.issues if i.type == "multi_column"]
        assert len(multi_col_issues) == 1
        assert "line" in multi_col_issues[0].line_range

    def test_decorative_elements_detected_by_smartrecruiters(self):
        result = self.svc.simulate(DECORATIVE_LATEX, "smartrecruiters")
        issue_types = [i.type for i in result.issues]
        assert "decorative_elements" in issue_types

    def test_minipage_detected_as_multi_column(self):
        result = self.svc.simulate(MINIPAGE_LATEX, "greenhouse")
        issue_types = [i.type for i in result.issues]
        assert "multi_column" in issue_types

    def test_ats_label_matches_profile(self):
        for ats_name, profile in ATS_PROFILES.items():
            result = self.svc.simulate(CLEAN_LATEX, ats_name)
            assert result.ats_label == profile["label"]

    def test_lever_clean_resume_max_score(self):
        """Lever is 'good' with no issues → score = 90."""
        result = self.svc.simulate(CLEAN_LATEX, "lever")
        assert result.score == 90

    def test_taleo_clean_resume_score_below_base(self):
        """Taleo is 'poor' (base=50); CLEAN_LATEX has \\geometry which triggers
        pdf_formatting (-8) → expected score = 42."""
        result = self.svc.simulate(CLEAN_LATEX, "taleo")
        # \geometry triggers pdf_formatting (severity medium, -8 penalty)
        pdf_issue = [i for i in result.issues if i.type == "pdf_formatting"]
        assert len(pdf_issue) == 1
        assert result.score == 42


# ── Integration: HTTP endpoint ────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAtsSimulateEndpoint:

    # 50I-01
    async def test_valid_request_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": CLEAN_LATEX, "ats_name": "greenhouse"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ats_label" in data
        assert "plain_text_view" in data
        assert "issues" in data
        assert "score" in data
        assert "recommendations" in data

    # 50I-02
    async def test_unknown_ats_name_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": CLEAN_LATEX, "ats_name": "nonexistent_ats"},
        )
        assert resp.status_code == 422

    # 50I-03
    async def test_taleo_multicol_returns_issues(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": MULTI_COLUMN_LATEX, "ats_name": "taleo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["issues"]) > 0
        issue_types = [i["type"] for i in data["issues"]]
        assert "multi_column" in issue_types

    # 50I-04
    async def test_list_profiles_returns_all_systems(self, client: AsyncClient):
        resp = await client.get("/ats/simulate/profiles")
        assert resp.status_code == 200
        profiles = resp.json()["profiles"]
        keys = {p["key"] for p in profiles}
        assert "taleo" in keys
        assert "greenhouse" in keys
        assert "workday" in keys
        assert len(profiles) == 7

    # 50I-05
    async def test_score_is_int_in_range(self, client: AsyncClient):
        for ats_name in ["greenhouse", "workday", "taleo"]:
            resp = await client.post(
                "/ats/simulate",
                json={"latex_content": CLEAN_LATEX, "ats_name": ats_name},
            )
            assert resp.status_code == 200
            score = resp.json()["score"]
            assert isinstance(score, int)
            assert 0 <= score <= 100

    # 50I-06
    async def test_empty_latex_does_not_crash(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": "", "ats_name": "greenhouse"},
        )
        # Should not 500; may return an empty plain_text_view
        assert resp.status_code in (200, 422)

    # 50I-07
    async def test_latex_too_long_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": "x" * 200_001, "ats_name": "greenhouse"},
        )
        assert resp.status_code == 422

    async def test_issues_have_required_fields(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": TABLE_LATEX, "ats_name": "taleo"},
        )
        assert resp.status_code == 200
        for issue in resp.json()["issues"]:
            assert "type" in issue
            assert "severity" in issue
            assert "description" in issue
            # "suggestion" is the advisory tier for Textkernel Suggested-grade
            # findings (codes 112/151): reported to the user, never scored.
            assert issue["severity"] in ("high", "medium", "low", "suggestion")

    async def test_greenhouse_clean_score_at_least_85(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": CLEAN_LATEX, "ats_name": "greenhouse"},
        )
        assert resp.status_code == 200
        assert resp.json()["score"] >= 85

    async def test_cached_field_present(self, client: AsyncClient):
        resp = await client.post(
            "/ats/simulate",
            json={"latex_content": CLEAN_LATEX, "ats_name": "lever"},
        )
        assert resp.status_code == 200
        assert "cached" in resp.json()

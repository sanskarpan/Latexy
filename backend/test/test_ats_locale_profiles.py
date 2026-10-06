from app.services.ats_locale_profiles import (
    ATS_PASS_THRESHOLD,
    analyze_locale_conventions,
)
from app.services.ats_scoring_service import ats_scoring_service

SOURCE = r"""\documentclass{article}
\usepackage{graphicx}
\begin{document}
\includegraphics{photo.png}
Date of Birth: 1 January 1990
Marital Status: Married
Expected CTC: INR 20 lakh
\end{document}
"""


def test_us_profile_discourages_sensitive_personal_details():
    result = analyze_locale_conventions(SOURCE, SOURCE, "united_states")
    assert result["content_penalty"] == 20
    assert len(result["warnings"]) == 4
    assert result["threshold"] == 80


def test_india_profile_accepts_the_same_details_without_score_penalty():
    result = analyze_locale_conventions(SOURCE, SOURCE, "india")
    assert result["content_penalty"] == 0
    assert result["warnings"] == []
    assert len(result["found_personal_details"]) == 4
    assert ATS_PASS_THRESHOLD == 80


def test_global_profile_keeps_existing_scoring_behavior():
    result = analyze_locale_conventions(SOURCE, SOURCE, "global")
    assert result["content_penalty"] == 0
    assert "no country-specific" in result["calibration"]


async def test_locale_overlay_changes_real_score_and_publishes_calibration():
    india = await ats_scoring_service.score_resume(SOURCE, locale_key="india")
    us = await ats_scoring_service.score_resume(SOURCE, locale_key="united_states")
    assert india.category_scores["content"] > us.category_scores["content"]
    assert india.overall_score > us.overall_score
    assert us.score_threshold == 80
    assert us.locale_label == "United States"
    assert "US hiring conventions" in us.calibration_statement

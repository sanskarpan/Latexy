"""Explicit locale overlays for ATS guidance and published score semantics."""

from typing import Any

from ..utils import safe_regex as re

ATS_PASS_THRESHOLD = 80

ATS_LOCALE_PROFILES: dict[str, dict[str, str]] = {
    "global": {
        "label": "Global / role-only",
        "calibration": "Latexy document-quality checks plus any selected industry and job-description match; no country-specific personal-detail rules.",
    },
    "india": {
        "label": "India",
        "calibration": "Latexy document-quality checks with Indian resume conventions; photo, date of birth, marital status, and expected salary are not penalized when supplied.",
    },
    "united_states": {
        "label": "United States",
        "calibration": "Latexy document-quality checks with US hiring conventions; sensitive personal details are discouraged and reduce the content score.",
    },
    "united_kingdom": {
        "label": "United Kingdom",
        "calibration": "Latexy document-quality checks with UK hiring conventions; sensitive personal details are discouraged and reduce the content score.",
    },
}

_PERSONAL_DETAIL_RULES = (
    ("photo", "Photo", lambda raw, _text: bool(re.search(r"\\includegraphics\b", raw, re.IGNORECASE))),
    (
        "date_of_birth",
        "Date of birth",
        lambda _raw, text: bool(re.search(r"\b(?:date of birth|d\.?o\.?b\.?)\s*[:\-]", text, re.IGNORECASE)),
    ),
    (
        "marital_status",
        "Marital status",
        lambda _raw, text: bool(re.search(r"\bmarital status\s*[:\-]", text, re.IGNORECASE)),
    ),
    (
        "expected_salary",
        "Expected salary",
        lambda _raw, text: bool(
            re.search(r"\b(?:expected salary|expected ctc|current ctc)\s*[:\-]", text, re.IGNORECASE)
        ),
    ),
)


def get_locale_profile(locale_key: str) -> dict[str, str]:
    return ATS_LOCALE_PROFILES.get(locale_key, ATS_LOCALE_PROFILES["global"])


def analyze_locale_conventions(latex_content: str, text_content: str, locale_key: str) -> dict[str, Any]:
    """Return transparent locale findings; only US/UK profiles penalize them."""
    profile = get_locale_profile(locale_key)
    found = [
        {"key": key, "label": label}
        for key, label, predicate in _PERSONAL_DETAIL_RULES
        if predicate(latex_content, text_content)
    ]
    discouraged = locale_key in {"united_states", "united_kingdom"}
    penalty = min(20.0, 5.0 * len(found)) if discouraged else 0.0
    warnings = (
        [f"{item['label']} is discouraged for {profile['label']} applications" for item in found] if discouraged else []
    )
    recommendations = (
        [f"Remove {item['label'].lower()} unless the employer explicitly requires it" for item in found]
        if discouraged
        else []
    )
    return {
        "locale_key": locale_key,
        "locale_label": profile["label"],
        "calibration": profile["calibration"],
        "threshold": ATS_PASS_THRESHOLD,
        "found_personal_details": found,
        "content_penalty": penalty,
        "warnings": warnings,
        "recommendations": recommendations,
    }

"""Guided-intake direction fields flow into the optimization prompt.

Covers the input-driven-optimization P1 backend (PRD 2026-08-02): industry,
seniority, tone, emphasize, downplay are the user's explicit direction and must
appear in the prompt so the model honours them over generic ATS heuristics.
"""

from app.services.llm_service import LLMService

_LATEX = r"\documentclass{article}\begin{document}Jane Doe\end{document}"


def _prompt(**kwargs) -> str:
    svc = LLMService()
    return svc._create_optimization_prompt(  # noqa: SLF001
        _LATEX,
        kwargs.pop("job_description", None),
        kwargs.pop("keywords", []),
        kwargs.pop("optimization_level", "balanced"),
        **kwargs,
    )


def test_intake_fields_present_when_provided():
    p = _prompt(
        industry="Fintech",
        seniority="Senior",
        tone="confident and concise",
        emphasize=["AWS migration", "team leadership"],
        downplay=["early internships"],
    )
    assert "USER DIRECTION" in p
    assert "Fintech" in p
    assert "Senior" in p
    assert "confident and concise" in p
    assert "AWS migration" in p and "team leadership" in p
    assert "early internships" in p
    # De-emphasize must be explicit that it does NOT remove content.
    assert "do NOT remove" in p


def test_no_direction_block_when_absent():
    p = _prompt()
    assert "USER DIRECTION" not in p


def test_partial_fields_only_include_given_lines():
    p = _prompt(industry="Healthcare")
    assert "USER DIRECTION" in p
    assert "Healthcare" in p
    # Fields not provided must not appear as empty direction lines.
    assert "Seniority level:" not in p
    assert "Voice/tone:" not in p
    assert "Emphasize these" not in p

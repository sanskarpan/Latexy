"""The conversion prompt must not silently drop resume content.

The previous cap was ``raw_text[:4000]`` with no log and no signal to the model.
For a PDF that excerpt is the *entire* content the LLM receives — PDFParser fills
only ``raw_text``, so the structured-sections block is empty — which meant a
dense two-page resume was converted from a mid-sentence fragment and the user
got back a LaTeX file quietly missing its last role.
"""

from __future__ import annotations

import logging

from app.services.document_converter_service import (
    RAW_TEXT_CHAR_BUDGET,
    _clip_raw_text,
    document_converter_service,
)


def _line_block(n_lines: int, filler: str = "Delivered a measurable improvement to the system.") -> str:
    return "\n".join(f"{i:04d} {filler}" for i in range(n_lines))


def test_a_realistic_two_page_resume_is_not_truncated():
    """The old 4000-char cap cut exactly this size of document."""
    two_pages = _line_block(90)  # ~4.6k chars, a dense two-page resume
    assert len(two_pages) > 4000, "fixture must exceed the OLD cap to be meaningful"

    clipped, dropped = _clip_raw_text(two_pages)
    assert dropped == 0
    assert clipped == two_pages


def test_content_beyond_the_budget_is_reported_not_hidden():
    oversized = _line_block(2000)
    assert len(oversized) > RAW_TEXT_CHAR_BUDGET

    clipped, dropped = _clip_raw_text(oversized)
    assert dropped > 0
    assert len(clipped) <= RAW_TEXT_CHAR_BUDGET
    # Nothing is lost silently: what is kept plus what is reported is the whole input.
    assert len(clipped) + dropped == len(oversized)


def test_truncation_cuts_on_a_line_boundary():
    """A mid-word cut invites the model to complete the fragment."""
    oversized = _line_block(2000)
    clipped, _ = _clip_raw_text(oversized)
    assert not clipped.endswith(" ")
    # The final retained line is whole.
    assert oversized.startswith(clipped)
    remainder = oversized[len(clipped):]
    assert remainder.startswith("\n"), "cut landed mid-line"


def test_truncation_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        _clip_raw_text(_line_block(2000))
    assert any(
        "exceeded the conversion prompt budget" in r.getMessage()
        for r in caplog.records
    ), "truncation must leave a trace an operator can find"


def test_prompt_tells_the_model_when_content_was_omitted():
    """Otherwise a mid-resume cut reads as the end, and the model tidies it up."""
    structure = {"raw_text": _line_block(2000), "contact": {"name": "Priya Raman"}}
    user = document_converter_service.build_conversion_prompt(structure, "pdf")[-1]["content"]
    assert "characters were omitted" in user
    assert "do not" in user.lower() and "invent" in user.lower()


def test_prompt_has_no_omission_note_for_a_normal_resume():
    structure = {"raw_text": _line_block(90), "contact": {"name": "Priya Raman"}}
    user = document_converter_service.build_conversion_prompt(structure, "pdf")[-1]["content"]
    assert "characters were omitted" not in user


def test_full_two_page_resume_reaches_the_prompt_intact():
    """End-to-end on the prompt builder, not just the helper."""
    body = _line_block(90)
    structure = {"raw_text": body, "contact": {"name": "Priya Raman"}}
    user = document_converter_service.build_conversion_prompt(structure, "pdf")[-1]["content"]
    assert body.splitlines()[-1] in user, "last line of the resume never reached the model"

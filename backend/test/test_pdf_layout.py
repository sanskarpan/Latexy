"""Layout-aware PDF extraction.

``page.extract_text()`` flattened a resume into space-joined lines, which ran a
job title into its right-aligned date and turned a two-column skills block into
one sentence. It also yielded no section information at all, so
``section_hints`` came back empty and the LLM had to infer structure from a flat
blob.

PDFs here are built by hand rather than with a PDF library, so the suite needs no
dependency that production does not already have.
"""

from __future__ import annotations

import asyncio

import pytest

from app.parsers.pdf_layout import (
    CELL_GAP_PTS,
    _looks_like_section_heading,
    _split_cells,
    extract_layout_text,
)

# ── minimal PDF writer ───────────────────────────────────────────────────────


def make_pdf(items) -> bytes:
    """Build a one-page PDF. *items* are (x, y, size, bold, text) tuples."""
    ops = []
    for x, y, size, bold, text in items:
        font = "/F2" if bold else "/F1"
        esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT {font} {size} Tf {x} {y} Td ({esc}) Tj ET")
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font "
        b"<< /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


RESUME = make_pdf([
    (250, 750, 18, True, "Priya Raman"),
    (170, 730, 9, False, "Bangalore, India | priya@example.com | +91 98765 43210"),
    (60, 700, 11, True, "SUMMARY"),
    (60, 682, 10, False, "Backend engineer with six years on payment systems."),
    (60, 655, 11, True, "EXPERIENCE"),
    (60, 636, 10, True, "Senior Software Engineer, Razorpay"),
    (430, 636, 10, False, "Mar 2022 - Present"),
    (72, 620, 9.5, False, "- Led the settlement ledger migration."),
    (60, 590, 11, True, "SKILLS"),
    (72, 572, 9.5, False, "Languages: Go, Python"),
    (320, 572, 9.5, False, "Practices: Event sourcing"),
])


# ── cell splitting ───────────────────────────────────────────────────────────


def _w(text, x0, x1, size=10.0, font="Helvetica"):
    return {"text": text, "x0": x0, "x1": x1, "size": size, "fontname": font}


def test_wide_gap_splits_cells():
    """A right-aligned date is a separate cell, not the tail of the job title."""
    cells = _split_cells([
        _w("Engineer", 60, 110),
        _w("Razorpay", 112, 160),
        _w("Mar", 430, 452),   # far right — the date column
        _w("2022", 454, 480),
    ])
    assert cells == ["Engineer Razorpay", "Mar 2022"]


def test_ordinary_word_spacing_does_not_split():
    cells = _split_cells([_w("Backend", 60, 110), _w("engineer", 114, 165)])
    assert cells == ["Backend engineer"]


def test_gap_threshold_boundary():
    """Just under the threshold stays joined; just over splits."""
    under = _split_cells([_w("a", 60, 100), _w("b", 100 + CELL_GAP_PTS - 1, 200)])
    over = _split_cells([_w("a", 60, 100), _w("b", 100 + CELL_GAP_PTS + 1, 200)])
    assert len(under) == 1
    assert len(over) == 2


def test_words_are_ordered_by_position_not_input_order():
    cells = _split_cells([_w("second", 430, 470), _w("first", 60, 100)])
    assert cells == ["first", "second"]


# ── heading detection ────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS", "PROJECTS"])
def test_known_section_names_are_headings(text):
    assert _looks_like_section_heading(text, size=11.0, bold=True, body_size=9.5)


def test_unknown_all_caps_short_line_is_a_heading():
    """Real resumes invent section names; all-caps and short is the convention."""
    assert _looks_like_section_heading("CORE COMPETENCIES", 11.0, True, 9.5)


def test_bold_job_title_is_not_a_heading():
    """The discriminator that matters — job titles are bold and larger too."""
    assert not _looks_like_section_heading(
        "Senior Software Engineer, Razorpay", size=10.0, bold=True, body_size=9.5
    )


def test_body_text_is_not_a_heading():
    assert not _looks_like_section_heading(
        "Backend engineer with six years on payment systems.", 9.5, False, 9.5
    )


def test_a_long_prominent_line_is_not_a_heading():
    assert not _looks_like_section_heading(
        "ACHIEVEMENTS AND AWARDS RECEIVED THROUGHOUT MY ENTIRE CAREER", 12.0, True, 9.5
    )


# ── end to end ───────────────────────────────────────────────────────────────


def test_sections_are_detected_from_a_real_pdf():
    result = extract_layout_text(RESUME)
    assert result is not None
    assert result.section_hints == ["SUMMARY", "EXPERIENCE", "SKILLS"]


def test_right_aligned_date_is_separated_from_the_job_title():
    text = extract_layout_text(RESUME).text
    assert "Senior Software Engineer, Razorpay | Mar 2022 - Present" in text
    assert "Razorpay Mar 2022" not in text, "title and date ran together"


def test_two_column_block_is_not_run_into_one_line():
    text = extract_layout_text(RESUME).text
    assert "Languages: Go, Python | Practices: Event sourcing" in text
    assert "Go, Python Practices" not in text, "columns were linearised"


def test_headings_get_a_blank_line_before_them():
    text = extract_layout_text(RESUME).text
    assert "\n\nSUMMARY\n" in text
    assert "\n\nEXPERIENCE\n" in text


def test_no_positioned_words_returns_none_so_caller_can_fall_back():
    """A scanned page must not look like a successful empty parse."""
    assert extract_layout_text(make_pdf([])) is None


# ── parser integration ───────────────────────────────────────────────────────


def test_pdf_parser_populates_section_hints():
    from app.parsers.pdf_parser import PDFParser

    parsed = asyncio.run(PDFParser().parse(RESUME, "resume.pdf"))
    assert parsed.metadata["section_hints"] == ["SUMMARY", "EXPERIENCE", "SKILLS"]


def test_pdf_parser_still_extracts_contact_details():
    from app.parsers.pdf_parser import PDFParser

    parsed = asyncio.run(PDFParser().parse(RESUME, "resume.pdf"))
    assert parsed.contact.email == "priya@example.com"
    assert parsed.contact.phone == "+91 98765 43210"


def test_parser_falls_back_when_layout_extraction_raises(monkeypatch):
    """Layout is an enhancement; a failure in it must not fail the upload."""
    import app.parsers.pdf_parser as pdf_parser_mod

    def boom(*args, **kwargs):
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(pdf_parser_mod, "extract_layout_text", boom)
    parsed = asyncio.run(pdf_parser_mod.PDFParser().parse(RESUME, "resume.pdf"))
    assert "Priya Raman" in (parsed.raw_text or "")
    assert parsed.metadata["section_hints"] == []

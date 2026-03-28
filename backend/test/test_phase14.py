"""
Test Phase 14: Multi-Format Infrastructure
Tests format detection, parser framework, and file validation.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parsers.parser_factory import parser_factory
from app.services.format_detection import ResumeFormat, format_detection_service


def test_format_detection():
    """Test format detection service."""
    # Test 1: Detect from filename
    test_cases = [
        ("resume.tex", ResumeFormat.LATEX),
        ("resume.pdf", ResumeFormat.PDF),
        ("resume.docx", ResumeFormat.DOCX),
        ("resume.md", ResumeFormat.MARKDOWN),
        ("resume.txt", ResumeFormat.TEXT),
        ("resume.html", ResumeFormat.HTML),
        ("resume.json", ResumeFormat.JSON),
        ("resume.yaml", ResumeFormat.YAML),
        ("resume.unknown", ResumeFormat.UNKNOWN),
    ]

    for filename, expected in test_cases:
        detected = format_detection_service.detect_format_from_filename(filename)
        assert detected == expected, f"{filename}: expected {expected.value}, got {detected.value}"

    # Test 2: Detect from content
    latex_content = b"\\documentclass{article}\n\\begin{document}\nHello\\end{document}"
    assert format_detection_service.detect_format_from_content(latex_content) == ResumeFormat.LATEX

    html_content = b"<!DOCTYPE html><html><body>Resume</body></html>"
    assert format_detection_service.detect_format_from_content(html_content) == ResumeFormat.HTML

    json_content = b'{"name": "John Doe", "email": "john@example.com"}'
    assert format_detection_service.detect_format_from_content(json_content) == ResumeFormat.JSON

    pdf_content = b"%PDF-1.4\nSome PDF content"
    assert format_detection_service.detect_format_from_content(pdf_content) == ResumeFormat.PDF

    # Test 3: File size validation
    is_valid, _ = format_detection_service.validate_file_size(1024 * 1024, ResumeFormat.TEXT)
    assert is_valid  # 1 MB text - valid

    is_valid, _ = format_detection_service.validate_file_size(2 * 1024 * 1024, ResumeFormat.TEXT)
    assert not is_valid  # 2 MB text - invalid

    is_valid, _ = format_detection_service.validate_file_size(5 * 1024 * 1024, ResumeFormat.DOCX)
    assert is_valid  # 5 MB DOCX - valid

    is_valid, _ = format_detection_service.validate_file_size(11 * 1024 * 1024, ResumeFormat.PDF)
    assert not is_valid  # 11 MB PDF - invalid


def test_parser_factory():
    """Test parser factory."""
    supported_formats = parser_factory.get_supported_formats()
    assert len(supported_formats) > 0

    # LaTeX parser must exist
    parser = parser_factory.get_parser(ResumeFormat.LATEX)
    assert parser is not None

    # PDF and DOCX not yet implemented
    for fmt in [ResumeFormat.PDF, ResumeFormat.DOCX]:
        assert parser_factory.get_parser(fmt) is None


async def test_latex_parser():
    """Test LaTeX parser."""
    parser = parser_factory.get_parser(ResumeFormat.LATEX)
    assert parser is not None

    valid_latex = b"""\\documentclass{article}
\\author{John Doe}
\\title{Software Engineer Resume}
\\begin{document}
\\maketitle
\\section{Experience}
Software Engineer at Tech Corp
\\end{document}"""

    parsed = await parser.parse(valid_latex, "test.tex")
    assert parsed.raw_text is not None

    # Invalid LaTeX rejected
    is_valid, error = parser.validate(b"This is not LaTeX content")
    assert not is_valid

    # Valid LaTeX accepted
    is_valid, _ = parser.validate(valid_latex)
    assert is_valid


def test_format_info():
    """Test format information retrieval."""
    formats = format_detection_service.get_supported_formats()
    assert len(formats) > 0

    latex_info = format_detection_service.get_format_info(ResumeFormat.LATEX)
    assert "extensions" in latex_info
    assert "mime_types" in latex_info
    assert "max_size_mb" in latex_info

    assert format_detection_service.is_text_based(ResumeFormat.LATEX) is True
    assert format_detection_service.is_text_based(ResumeFormat.PDF) is False
    assert format_detection_service.requires_parsing(ResumeFormat.MARKDOWN) is True

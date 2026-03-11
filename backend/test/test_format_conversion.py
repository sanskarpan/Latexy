"""
Multi-format upload and document conversion tests.

Tests cover:
- Parser unit tests for each format (text extraction, no LLM)
- POST /formats/upload endpoint (LaTeX passthrough, async job queuing)
- Format detection edge cases
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ── Sample content fixtures ────────────────────────────────────────────────────

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}
\begin{center}
    \textbf{\Large Jane Smith} \\
    jane@example.com | (555) 123-4567
\end{center}
\section*{Experience}
\textbf{Senior Engineer} at \textit{TechCorp} \hfill 2021--Present \\
\begin{itemize}
    \item Built scalable APIs serving 10M+ requests/day
\end{itemize}
\section*{Skills}
Python, TypeScript, Docker, PostgreSQL
\end{document}
"""

SAMPLE_MARKDOWN = """
# Jane Smith
jane@example.com | (555) 123-4567 | linkedin.com/in/janesmith

## Experience

**Senior Engineer** — TechCorp (2021–Present)
- Built scalable APIs serving 10M+ requests/day
- Led team of 5 engineers

## Education

**B.S. Computer Science** — State University, 2019

## Skills
Python, TypeScript, Docker, PostgreSQL
"""

SAMPLE_TEXT = """Jane Smith
jane@example.com
(555) 123-4567

EXPERIENCE

Senior Engineer at TechCorp
2021 - Present
Built scalable APIs serving 10M+ requests/day

EDUCATION

B.S. Computer Science - State University, 2019

SKILLS

Python, TypeScript, Docker, PostgreSQL
"""

SAMPLE_HTML = """<!DOCTYPE html>
<html>
<body>
<h1>Jane Smith</h1>
<p>jane@example.com | (555) 123-4567</p>
<h2>Experience</h2>
<p><strong>Senior Engineer</strong> at TechCorp (2021-Present)</p>
<ul><li>Built scalable APIs serving 10M+ requests/day</li></ul>
<h2>Skills</h2>
<p>Python, TypeScript, Docker</p>
</body>
</html>"""

SAMPLE_JSON_RESUME = {
    "basics": {
        "name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "(555) 123-4567",
        "summary": "Senior software engineer with 5 years experience",
    },
    "work": [
        {
            "company": "TechCorp",
            "position": "Senior Engineer",
            "startDate": "2021-01",
            "highlights": ["Built scalable APIs"],
        }
    ],
    "education": [
        {
            "institution": "State University",
            "area": "Computer Science",
            "studyType": "B.S.",
            "endDate": "2019-05",
        }
    ],
    "skills": [{"name": "Python"}, {"name": "TypeScript"}],
}

SAMPLE_YAML_RESUME = """
basics:
  name: Jane Smith
  email: jane@example.com
  phone: "(555) 123-4567"
work:
  - company: TechCorp
    position: Senior Engineer
    startDate: "2021-01"
education:
  - institution: State University
    area: Computer Science
skills:
  - name: Python
  - name: TypeScript
"""

SAMPLE_TOML = """
[basics]
name = "Jane Smith"
email = "jane@example.com"

[[work]]
company = "TechCorp"
position = "Senior Engineer"

[[skills]]
name = "Python"
"""

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<resume>
    <contact>
        <name>Jane Smith</name>
        <email>jane@example.com</email>
    </contact>
    <experience>
        <job>
            <title>Senior Engineer</title>
            <company>TechCorp</company>
        </job>
    </experience>
    <skills>Python, TypeScript</skills>
</resume>"""

# ── Parser unit tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMarkdownParser:
    async def test_parse_returns_raw_text(self):
        from app.parsers.markdown_parser import MarkdownParser
        parser = MarkdownParser()
        result = await parser.parse(SAMPLE_MARKDOWN.encode(), "resume.md")
        assert result.raw_text
        assert "Jane Smith" in result.raw_text

    async def test_parse_extracts_email(self):
        from app.parsers.markdown_parser import MarkdownParser
        parser = MarkdownParser()
        result = await parser.parse(SAMPLE_MARKDOWN.encode(), "resume.md")
        assert result.contact.email == "jane@example.com"

    async def test_parse_strips_mdx_components(self):
        from app.parsers.markdown_parser import MarkdownParser
        mdx = b"# Jane\n<ResumeSection title='Skills' />\n<Contact>email</Contact>\nPython"
        parser = MarkdownParser()
        result = await parser.parse(mdx, "resume.mdx")
        assert "Jane" in result.raw_text
        # JSX components should be stripped
        assert "ResumeSection" not in result.raw_text

    async def test_validate_accepts_markdown(self):
        from app.parsers.markdown_parser import MarkdownParser
        parser = MarkdownParser()
        is_valid, err = parser.validate(SAMPLE_MARKDOWN.encode())
        assert is_valid
        assert err is None

    async def test_validate_rejects_empty(self):
        from app.parsers.markdown_parser import MarkdownParser
        parser = MarkdownParser()
        is_valid, err = parser.validate(b"")
        assert not is_valid


@pytest.mark.asyncio
class TestTextParser:
    async def test_parse_returns_raw_text(self):
        from app.parsers.text_parser import TextParser
        parser = TextParser()
        result = await parser.parse(SAMPLE_TEXT.encode(), "resume.txt")
        assert result.raw_text
        assert "Jane Smith" in result.raw_text

    async def test_parse_extracts_email(self):
        from app.parsers.text_parser import TextParser
        parser = TextParser()
        result = await parser.parse(SAMPLE_TEXT.encode(), "resume.txt")
        assert result.contact.email == "jane@example.com"

    async def test_parse_detects_sections(self):
        from app.parsers.text_parser import TextParser
        parser = TextParser()
        result = await parser.parse(SAMPLE_TEXT.encode(), "resume.txt")
        section_hints = result.metadata.get("section_hints", [])
        assert len(section_hints) > 0

    async def test_validate_accepts_text(self):
        from app.parsers.text_parser import TextParser
        parser = TextParser()
        is_valid, err = parser.validate(SAMPLE_TEXT.encode())
        assert is_valid

    async def test_validate_rejects_empty(self):
        from app.parsers.text_parser import TextParser
        parser = TextParser()
        is_valid, err = parser.validate(b"")
        assert not is_valid


@pytest.mark.asyncio
class TestHTMLParser:
    async def test_parse_returns_raw_text(self):
        from app.parsers.html_parser import HTMLParser
        parser = HTMLParser()
        result = await parser.parse(SAMPLE_HTML.encode(), "resume.html")
        assert result.raw_text
        assert "Jane Smith" in result.raw_text

    async def test_parse_extracts_email(self):
        from app.parsers.html_parser import HTMLParser
        parser = HTMLParser()
        result = await parser.parse(SAMPLE_HTML.encode(), "resume.html")
        assert result.contact.email == "jane@example.com"

    async def test_parse_extracts_headers_as_section_hints(self):
        from app.parsers.html_parser import HTMLParser
        parser = HTMLParser()
        result = await parser.parse(SAMPLE_HTML.encode(), "resume.html")
        section_hints = result.metadata.get("section_hints", [])
        assert len(section_hints) >= 2  # h1=Jane Smith, h2=Experience, h2=Skills

    async def test_parse_strips_scripts_and_styles(self):
        from app.parsers.html_parser import HTMLParser
        html_with_script = b"<html><script>alert('xss')</script><p>Jane Smith</p></html>"
        parser = HTMLParser()
        result = await parser.parse(html_with_script, "test.html")
        assert "alert" not in result.raw_text

    async def test_validate_accepts_html(self):
        from app.parsers.html_parser import HTMLParser
        parser = HTMLParser()
        is_valid, err = parser.validate(SAMPLE_HTML.encode())
        assert is_valid


@pytest.mark.asyncio
class TestJSONParser:
    async def test_parse_json_resume_schema(self):
        from app.parsers.json_parser import JSONParser
        parser = JSONParser()
        content = json.dumps(SAMPLE_JSON_RESUME).encode()
        result = await parser.parse(content, "resume.json")
        assert result.raw_text or result.contact.name == "Jane Smith"

    async def test_parse_json_resume_extracts_contact(self):
        from app.parsers.json_parser import JSONParser
        parser = JSONParser()
        content = json.dumps(SAMPLE_JSON_RESUME).encode()
        result = await parser.parse(content, "resume.json")
        assert result.contact.email == "jane@example.com"

    async def test_parse_generic_json_as_text(self):
        from app.parsers.json_parser import JSONParser
        generic = json.dumps({"some": "data", "no": "schema"}).encode()
        parser = JSONParser()
        result = await parser.parse(generic, "data.json")
        assert result.raw_text

    async def test_validate_accepts_valid_json(self):
        from app.parsers.json_parser import JSONParser
        parser = JSONParser()
        is_valid, err = parser.validate(json.dumps(SAMPLE_JSON_RESUME).encode())
        assert is_valid

    async def test_validate_rejects_invalid_json(self):
        from app.parsers.json_parser import JSONParser
        parser = JSONParser()
        is_valid, err = parser.validate(b"{not valid json")
        assert not is_valid


@pytest.mark.asyncio
class TestYAMLParser:
    async def test_parse_yaml_resume(self):
        from app.parsers.yaml_parser import YAMLParser
        parser = YAMLParser()
        result = await parser.parse(SAMPLE_YAML_RESUME.encode(), "resume.yaml")
        assert result.raw_text or result.contact.name == "Jane Smith"

    async def test_validate_accepts_valid_yaml(self):
        from app.parsers.yaml_parser import YAMLParser
        parser = YAMLParser()
        is_valid, err = parser.validate(SAMPLE_YAML_RESUME.encode())
        assert is_valid

    async def test_validate_rejects_invalid_yaml(self):
        from app.parsers.yaml_parser import YAMLParser
        parser = YAMLParser()
        is_valid, err = parser.validate(b"{\ninvalid: yaml: content: :")
        assert not is_valid


@pytest.mark.asyncio
class TestTOMLParser:
    async def test_parse_toml_content(self):
        from app.parsers.toml_parser import TOMLParser
        parser = TOMLParser()
        result = await parser.parse(SAMPLE_TOML.encode(), "resume.toml")
        assert result.raw_text

    async def test_validate_accepts_valid_toml(self):
        from app.parsers.toml_parser import TOMLParser
        parser = TOMLParser()
        is_valid, err = parser.validate(SAMPLE_TOML.encode())
        assert is_valid

    async def test_validate_rejects_invalid_toml(self):
        from app.parsers.toml_parser import TOMLParser
        parser = TOMLParser()
        is_valid, err = parser.validate(b"[invalid\nnot closed")
        assert not is_valid


@pytest.mark.asyncio
class TestXMLParser:
    async def test_parse_xml_content(self):
        from app.parsers.xml_parser import XMLParser
        parser = XMLParser()
        result = await parser.parse(SAMPLE_XML.encode(), "resume.xml")
        assert result.raw_text
        assert "Jane Smith" in result.raw_text

    async def test_validate_accepts_valid_xml(self):
        from app.parsers.xml_parser import XMLParser
        parser = XMLParser()
        is_valid, err = parser.validate(SAMPLE_XML.encode())
        assert is_valid

    async def test_validate_rejects_malformed_xml(self):
        from app.parsers.xml_parser import XMLParser
        parser = XMLParser()
        is_valid, err = parser.validate(b"<root><unclosed>")
        assert not is_valid


@pytest.mark.asyncio
class TestPDFParser:
    async def test_validate_rejects_non_pdf(self):
        from app.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        is_valid, err = parser.validate(b"this is not a pdf")
        assert not is_valid

    async def test_validate_accepts_pdf_magic_bytes(self):
        from app.parsers.pdf_parser import PDFParser
        parser = PDFParser()
        fake_pdf = b"%PDF-1.4 " + b"\x00" * 50  # minimal PDF magic bytes
        is_valid, err = parser.validate(fake_pdf)
        # Should at least recognize as PDF by magic bytes
        assert is_valid


class TestParserFactory:
    def test_factory_returns_parser_for_latex(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.LATEX)
        assert parser is not None

    def test_factory_returns_parser_for_pdf(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.PDF)
        assert parser is not None

    def test_factory_returns_parser_for_docx(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.DOCX)
        assert parser is not None

    def test_factory_returns_parser_for_markdown(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.MARKDOWN)
        assert parser is not None

    def test_factory_returns_parser_for_html(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.HTML)
        assert parser is not None

    def test_factory_returns_parser_for_json(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.JSON)
        assert parser is not None

    def test_factory_returns_parser_for_yaml(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.YAML)
        assert parser is not None

    def test_factory_returns_parser_for_toml(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.TOML)
        assert parser is not None

    def test_factory_returns_parser_for_xml(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.XML)
        assert parser is not None

    def test_factory_returns_parser_for_image(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.IMAGE)
        assert parser is not None

    def test_factory_returns_none_for_unknown(self):
        from app.parsers.parser_factory import parser_factory
        from app.services.format_detection import ResumeFormat
        parser = parser_factory.get_parser(ResumeFormat.UNKNOWN)
        assert parser is None

    def test_factory_lists_supported_formats(self):
        from app.parsers.parser_factory import parser_factory
        supported = parser_factory.get_supported_formats()
        # At minimum, the core formats should be supported
        from app.services.format_detection import ResumeFormat
        for fmt in [ResumeFormat.LATEX, ResumeFormat.PDF, ResumeFormat.MARKDOWN, ResumeFormat.TEXT]:
            assert fmt in supported


# ── Format detection tests ─────────────────────────────────────────────────────


class TestFormatDetection:
    def test_detects_latex_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.tex", None, b"")
        assert result == ResumeFormat.LATEX

    def test_detects_ltx_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.ltx", None, b"")
        assert result == ResumeFormat.LATEX

    def test_detects_mdx_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.mdx", None, b"")
        assert result == ResumeFormat.MARKDOWN

    def test_detects_pdf_by_magic_bytes(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("file", None, b"%PDF-1.4")
        assert result == ResumeFormat.PDF

    def test_detects_json_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.json", None, b"{}")
        assert result == ResumeFormat.JSON

    def test_detects_yaml_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.yaml", None, b"name: Jane")
        assert result == ResumeFormat.YAML

    def test_detects_yml_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.yml", None, b"name: Jane")
        assert result == ResumeFormat.YAML

    def test_detects_toml_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.toml", None, b"[basics]")
        assert result == ResumeFormat.TOML

    def test_detects_xml_by_extension(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("resume.xml", None, b"<resume/>")
        assert result == ResumeFormat.XML

    def test_detects_png_as_image(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        png_magic = b"\x89PNG\r\n\x1a\n"
        result = format_detection_service.detect_format("scan.png", "image/png", png_magic)
        assert result == ResumeFormat.IMAGE

    def test_detects_jpeg_as_image(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        jpeg_magic = b"\xFF\xD8\xFF\xE0"
        result = format_detection_service.detect_format("scan.jpg", "image/jpeg", jpeg_magic)
        assert result == ResumeFormat.IMAGE

    def test_unknown_format_returns_unknown(self):
        from app.services.format_detection import ResumeFormat, format_detection_service
        result = format_detection_service.detect_format("file.xyz", None, b"random bytes")
        assert result == ResumeFormat.UNKNOWN


# ── POST /formats/upload endpoint tests ───────────────────────────────────────


@pytest.mark.asyncio
class TestUploadForConversion:
    async def test_upload_latex_returns_direct(self, client: AsyncClient):
        """LaTeX files return is_direct=True immediately, no job queued."""
        files = {"file": ("resume.tex", VALID_LATEX.encode(), "text/plain")}
        resp = await client.post("/formats/upload", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_direct"] is True
        assert data["format"] == "latex"
        assert data["latex_content"] is not None
        assert r"\documentclass" in data["latex_content"]

    async def test_upload_ltx_returns_direct(self, client: AsyncClient):
        """`.ltx` extension also treated as LaTeX passthrough."""
        files = {"file": ("resume.ltx", VALID_LATEX.encode(), "text/plain")}
        resp = await client.post("/formats/upload", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_direct"] is True
        assert data["format"] == "latex"

    async def test_upload_markdown_queues_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Non-LaTeX files queue a conversion job."""
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            files = {"file": ("resume.md", SAMPLE_MARKDOWN.encode(), "text/markdown")}
            resp = await client.post("/formats/upload", files=files, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_direct"] is False
        assert data["job_id"] is not None
        assert data["format"] == "markdown"

    async def test_upload_text_queues_job(
        self, client: AsyncClient
    ):
        """Plain text files queue a conversion job."""
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            files = {"file": ("resume.txt", SAMPLE_TEXT.encode(), "text/plain")}
            resp = await client.post("/formats/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_direct"] is False
        assert data["job_id"] is not None

    async def test_upload_json_resume_schema_queues_job(self, client: AsyncClient):
        """JSON files queue a conversion job (LLM converts to LaTeX)."""
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            content = json.dumps(SAMPLE_JSON_RESUME).encode()
            files = {"file": ("resume.json", content, "application/json")}
            resp = await client.post("/formats/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["format"] == "json"

    async def test_upload_unsupported_format_returns_415(self, client: AsyncClient):
        """Unknown format returns 415 Unsupported Media Type."""
        files = {"file": ("resume.xyz", b"garbage", "application/octet-stream")}
        resp = await client.post("/formats/upload", files=files)
        assert resp.status_code == 415

    async def test_upload_html_queues_job(self, client: AsyncClient):
        """HTML files queue a conversion job."""
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            files = {"file": ("resume.html", SAMPLE_HTML.encode(), "text/html")}
            resp = await client.post("/formats/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["format"] == "html"
        assert data["is_direct"] is False

    async def test_upload_returns_filename(self, client: AsyncClient):
        """Response includes the original filename."""
        files = {"file": ("my_resume.tex", VALID_LATEX.encode(), "text/plain")}
        resp = await client.post("/formats/upload", files=files)
        assert resp.status_code == 200
        assert resp.json()["filename"] == "my_resume.tex"

    async def test_upload_queued_job_id_is_uuid(self, client: AsyncClient):
        """Queued job_id must be a valid UUID."""
        import uuid
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            files = {"file": ("resume.txt", SAMPLE_TEXT.encode(), "text/plain")}
            resp = await client.post("/formats/upload", files=files)
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        uuid.UUID(job_id)  # Raises if not a valid UUID

    async def test_upload_yaml_queues_job(self, client: AsyncClient):
        """YAML files queue a conversion job."""
        with patch("app.workers.converter_worker.submit_document_conversion", return_value=None), \
             patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock):
            files = {"file": ("resume.yaml", SAMPLE_YAML_RESUME.encode(), "text/yaml")}
            resp = await client.post("/formats/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "yaml"

    async def test_upload_no_file_returns_422(self, client: AsyncClient):
        """Missing file field returns 422."""
        resp = await client.post("/formats/upload")
        assert resp.status_code == 422


# ── Document converter service unit tests ─────────────────────────────────────


class TestDocumentConverterService:
    def test_build_conversion_prompt_returns_messages(self):
        from app.services.document_converter_service import document_converter_service
        structure = {"contact": {"name": "Jane Smith", "email": "jane@example.com"},
                     "raw_text": "Jane Smith\nEngineer"}
        messages = document_converter_service.build_conversion_prompt(structure, "markdown")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_prompt_includes_source_format(self):
        from app.services.document_converter_service import document_converter_service
        structure = {"contact": {"name": "Jane"}, "raw_text": "Jane"}
        messages = document_converter_service.build_conversion_prompt(structure, "pdf")
        user_content = messages[1]["content"]
        assert "pdf" in user_content.lower()

    def test_validate_latex_output_valid(self):
        from app.services.document_converter_service import document_converter_service
        is_valid, err = document_converter_service.validate_latex_output(VALID_LATEX)
        assert is_valid
        assert err == ""

    def test_validate_latex_output_missing_documentclass(self):
        from app.services.document_converter_service import document_converter_service
        latex = r"\begin{document}hello\end{document}"
        is_valid, err = document_converter_service.validate_latex_output(latex)
        assert not is_valid

    def test_validate_latex_output_missing_begin_document(self):
        from app.services.document_converter_service import document_converter_service
        latex = r"\documentclass{article}\end{document}"
        is_valid, err = document_converter_service.validate_latex_output(latex)
        assert not is_valid

    def test_clean_latex_output_strips_code_fences(self):
        from app.services.document_converter_service import document_converter_service
        raw = "```latex\n" + VALID_LATEX + "\n```"
        cleaned = document_converter_service.clean_latex_output(raw)
        assert "```" not in cleaned
        assert r"\documentclass" in cleaned

    def test_clean_latex_output_strips_plain_code_fences(self):
        from app.services.document_converter_service import document_converter_service
        raw = "```\n" + VALID_LATEX + "\n```"
        cleaned = document_converter_service.clean_latex_output(raw)
        assert "```" not in cleaned

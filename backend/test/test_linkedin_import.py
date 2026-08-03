"""
LinkedIn Profile Import tests (Feature 16).

Tests cover:
- document_converter_service: source_hint="linkedin" uses LINKEDIN_SYSTEM_PROMPT
- source_hint=None / "resume" uses the default system prompt
- POST /formats/upload with source_hint="linkedin" routes correctly
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.document_converter_service import (
    LINKEDIN_SYSTEM_PROMPT,
    document_converter_service,
)

# ── Minimal resume structure fixture ──────────────────────────────────────────

STRUCTURE = {
    "contact": {"name": "Alice Lee", "email": "alice@example.com"},
    "raw_text": "Alice Lee\nalice@example.com\n\nExperience\n\nSenior Engineer at Acme (2020–Present)",
    "experience": [
        {
            "title": "Senior Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
            "current": True,
            "description": ["Owned backend systems"],
        }
    ],
    "education": [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "graduation_date": "2019",
        }
    ],
    "skills": ["Python", "TypeScript", "Docker"],
}

SAMPLE_TEXT = b"Alice Lee\nalice@example.com\n\nExperience\nSenior Engineer at Acme\n2020 - Present\nBuilt things\n\nSkills\nPython"


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestLinkedInPromptSelection:
    def test_linkedin_hint_uses_linkedin_system_prompt(self):
        """source_hint='linkedin' must inject LINKEDIN_SYSTEM_PROMPT as system message."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="linkedin"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == LINKEDIN_SYSTEM_PROMPT

    def test_no_hint_uses_default_system_prompt(self):
        """source_hint=None must use the default system prompt (not LinkedIn)."""
        messages = document_converter_service.build_conversion_prompt(STRUCTURE, "pdf")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT
        assert "professional LaTeX resume generator" in messages[0]["content"]

    def test_resume_hint_uses_default_system_prompt(self):
        """source_hint='resume' must use the default system prompt (not LinkedIn)."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="resume"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT

    def test_unknown_hint_uses_default_system_prompt(self):
        """An unrecognised source_hint must fall back to the default prompt."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="github"
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] != LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_mentions_recommendations(self):
        """LinkedIn prompt should instruct the LLM to ignore recommendations."""
        assert "Recommendations" in LINKEDIN_SYSTEM_PROMPT
        assert "ignore" in LINKEDIN_SYSTEM_PROMPT.lower()

    def test_linkedin_prompt_mentions_experience_section(self):
        """LinkedIn prompt should describe the Experience section structure."""
        assert "Experience" in LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_mentions_skills(self):
        """LinkedIn prompt should handle Skills and Languages."""
        assert "Skills" in LINKEDIN_SYSTEM_PROMPT
        assert "Languages" in LINKEDIN_SYSTEM_PROMPT

    def test_linkedin_prompt_returns_two_messages(self):
        """build_conversion_prompt always returns exactly 2 messages."""
        messages = document_converter_service.build_conversion_prompt(
            STRUCTURE, "pdf", source_hint="linkedin"
        )
        assert len(messages) == 2
        assert messages[1]["role"] == "user"

    def test_default_prompt_returns_two_messages(self):
        """Default path also returns exactly 2 messages."""
        messages = document_converter_service.build_conversion_prompt(STRUCTURE, "pdf")
        assert len(messages) == 2


# ── Endpoint tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestUploadWithSourceHint:
    async def test_upload_with_linkedin_hint_queues_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        """source_hint=linkedin for a text file queues a job (not direct)."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("profile.txt", SAMPLE_TEXT, "text/plain")},
                data={"source_hint": "linkedin"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_direct"] is False
        assert data["job_id"] is not None

        # Verify source_hint reached the worker submission call
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") == "linkedin"

    async def test_upload_without_hint_passes_none_to_worker(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Omitting source_hint should pass None to submit_document_conversion."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("resume.txt", SAMPLE_TEXT, "text/plain")},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") is None

    async def test_upload_with_resume_hint_passes_through(
        self, client: AsyncClient, auth_headers: dict
    ):
        """source_hint='resume' should be forwarded to the worker as-is."""
        with patch(
            "app.workers.converter_worker.submit_document_conversion", return_value=None
        ) as mock_submit, patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ):
            resp = await client.post(
                "/formats/upload",
                files={"file": ("resume.txt", SAMPLE_TEXT, "text/plain")},
                data={"source_hint": "resume"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs.get("source_hint") == "resume"

    async def test_latex_with_linkedin_hint_still_direct(self, client: AsyncClient):
        """LaTeX files always pass through directly, even with source_hint=linkedin."""
        LATEX = (
            rb"\documentclass{article}\begin{document}Alice Lee\end{document}"
        )
        resp = await client.post(
            "/formats/upload",
            files={"file": ("profile.tex", LATEX, "text/plain")},
            data={"source_hint": "linkedin"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_direct"] is True
        assert data["latex_content"] is not None


# ── Converter worker unit test ─────────────────────────────────────────────────


class TestConverterWorkerSourceHint:
    def test_worker_run_passes_source_hint_to_service(self):
        """convert_document_task.run must pass source_hint to build_conversion_prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(
            content=r"\documentclass{article}\begin{document}x\end{document}"
        ))]
        mock_response.usage = MagicMock(total_tokens=100)

        with patch("app.workers.converter_worker.publish_event"), \
             patch("app.workers.converter_worker.publish_job_result"), \
             patch("openai.OpenAI") as mock_openai_cls, \
             patch.object(
                 document_converter_service,
                 "build_conversion_prompt",
                 wraps=document_converter_service.build_conversion_prompt,
             ) as mock_build:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai_cls.return_value = mock_client

            from app.workers.converter_worker import convert_document_task
            # .run() calls the underlying function directly, bypassing Celery routing
            convert_document_task.run(
                extracted_data=STRUCTURE,
                source_format="pdf",
                job_id="test-job-123",
                user_id=None,
                user_api_key="sk-test",
                source_hint="linkedin",
            )

        mock_build.assert_called_once_with(STRUCTURE, "pdf", source_hint="linkedin", source_platform=None)


# ═══════════════════════════════════════════════════════════════════════════════
# LinkedIn COMPLIANT export/resume import (Feature 1 Phase 3)
#
# These tests exercise the DATA-EXPORT parser (a user-uploaded LinkedIn export
# ZIP or resume file → ProjectEvidence). This is a distinct feature from the
# Feature-16 document-converter tests above and shares only the file name.
#
# COMPLIANCE: every test operates on in-memory bytes only. NO test performs (or
# permits) any network I/O to LinkedIn — one test actively blocks sockets to
# prove the parser is fully offline.
# ═══════════════════════════════════════════════════════════════════════════════

import io as _io
import zipfile as _zipfile

from app.parsers.base_parser import Experience, ParsedResume, Project
from app.services import linkedin_import_service as lin


def _make_export_zip(files: dict) -> bytes:
    """Build an in-memory LinkedIn-export-style ZIP from {name: csv_text}."""
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


_PROJECTS_CSV = (
    "Title,Description,Url,Started On,Finished On\r\n"
    'Latexy,"Resume compiler in the cloud.\nCut latency 40%.",'
    "https://example.com/latexy,Jan 2024,Dec 2024\r\n"
)
_POSITIONS_CSV = (
    "Company Name,Title,Description,Started On,Finished On\r\n"
    "Acme Corp,Senior Engineer,Owned backend systems. Led a team of 5.,"
    "Jan 2020,Present\r\n"
)


class TestParseLinkedInExport:
    def test_projects_csv_maps_to_project_evidence(self):
        zip_bytes = _make_export_zip({"Projects.csv": _PROJECTS_CSV})
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1
        ev = out[0]
        assert ev["source"] == "linkedin"
        assert ev["title"] == "Latexy"
        assert "Resume compiler" in ev["description"]
        assert ev["url"] == "https://example.com/latexy"
        assert ev["dates"]["last_active"] == "Dec 2024"
        assert ev["metrics"] == {}
        assert ev["tech"] == []
        # Newline-delimited description → multiple bullets
        assert len(ev["suggested_bullets"]) == 2

    def test_positions_csv_maps_title_at_company(self):
        zip_bytes = _make_export_zip({"Positions.csv": _POSITIONS_CSV})
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1
        ev = out[0]
        assert ev["source"] == "linkedin"
        assert ev["title"] == "Senior Engineer at Acme Corp"
        assert ev["dates"]["last_active"] == "Present"
        assert ev["suggested_bullets"]  # sentence-split description

    def test_both_files_combined(self):
        zip_bytes = _make_export_zip(
            {"Projects.csv": _PROJECTS_CSV, "Positions.csv": _POSITIONS_CSV}
        )
        out = lin.parse_linkedin_export(zip_bytes)
        titles = {e["title"] for e in out}
        assert "Latexy" in titles
        assert "Senior Engineer at Acme Corp" in titles

    def test_case_insensitive_filename_and_headers(self):
        csv_text = "TITLE,description\r\nMyProj,Did a thing.\r\n"
        zip_bytes = _make_export_zip({"data/PROJECTS.CSV": csv_text})
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1
        assert out[0]["title"] == "MyProj"

    def test_missing_relevant_files_tolerated(self):
        zip_bytes = _make_export_zip(
            {"Profile.csv": "First Name,Last Name\r\nAlice,Lee\r\n"}
        )
        assert lin.parse_linkedin_export(zip_bytes) == []

    def test_malformed_csv_tolerated(self):
        # Ragged rows / stray quotes must not raise.
        bad = 'Title,Description\r\n"unterminated,thing\r\nok,fine\r\n'
        zip_bytes = _make_export_zip({"Projects.csv": bad})
        out = lin.parse_linkedin_export(zip_bytes)
        assert isinstance(out, list)  # tolerated, whatever it could extract

    def test_bom_encoded_csv(self):
        text = "﻿Title,Description\r\nBOMProj,Handled BOM.\r\n"
        zip_bytes = _make_export_zip({"Projects.csv": text})
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1
        assert out[0]["title"] == "BOMProj"

    def test_not_a_zip_raises_value_error(self):
        with pytest.raises(ValueError):
            lin.parse_linkedin_export(b"this is not a zip file")

    def test_empty_bytes_raises_value_error(self):
        with pytest.raises(ValueError):
            lin.parse_linkedin_export(b"")

    def test_non_csv_members_ignored(self):
        zip_bytes = _make_export_zip(
            {
                "Projects.csv": _PROJECTS_CSV,
                "photo.jpg": "\x00\x01\x02binary",
                "README.txt": "hello",
            }
        )
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1  # only the CSV contributed

    def test_no_network_used_sockets_blocked(self, monkeypatch):
        """Prove the parser is fully offline: block sockets, parsing still works."""
        import socket

        def _boom(*args, **kwargs):
            raise AssertionError("network access attempted during LinkedIn parse")

        monkeypatch.setattr(socket, "socket", _boom)
        zip_bytes = _make_export_zip({"Projects.csv": _PROJECTS_CSV})
        out = lin.parse_linkedin_export(zip_bytes)
        assert len(out) == 1


class TestParseResumeFile:
    async def test_resume_file_maps_experience_and_projects(self):
        canned = ParsedResume(
            experience=[
                Experience(
                    title="Staff Engineer",
                    company="Globex",
                    start_date="2021",
                    end_date="2024",
                    description=["Shipped X", "Scaled Y to 1M users"],
                    technologies=["Go", "Kafka"],
                )
            ],
            projects=[
                Project(
                    name="OpenTool",
                    description="An open-source tool. Widely adopted.",
                    technologies=["Rust"],
                    url="https://example.com/opentool",
                    end_date="2023",
                )
            ],
        )

        class _FakeParser:
            async def parse(self, content, filename=""):
                return canned

        with patch(
            "app.parsers.parser_factory.parser_factory.get_parser_for_file",
            return_value=_FakeParser(),
        ):
            out = await lin.parse_resume_file(b"%PDF-1.4 fake", "resume.pdf")

        titles = {e["title"] for e in out}
        assert "Staff Engineer at Globex" in titles
        assert "OpenTool" in titles
        for e in out:
            assert e["source"] == "linkedin"
        proj = next(e for e in out if e["title"] == "OpenTool")
        assert proj["tech"] == ["Rust"]
        assert proj["url"] == "https://example.com/opentool"
        exp = next(e for e in out if e["title"] == "Staff Engineer at Globex")
        assert exp["suggested_bullets"] == ["Shipped X", "Scaled Y to 1M users"]

    async def test_unsupported_format_raises(self):
        with patch(
            "app.parsers.parser_factory.parser_factory.get_parser_for_file",
            return_value=None,
        ):
            with pytest.raises(ValueError):
                await lin.parse_resume_file(b"junk", "weird.xyz")

    async def test_empty_resume_bytes_raises(self):
        with pytest.raises(ValueError):
            await lin.parse_resume_file(b"", "resume.pdf")


@pytest.mark.asyncio
class TestSourcesImportEndpoint:
    async def test_import_zip_returns_projects(self, client: AsyncClient, auth_headers):
        zip_bytes = _make_export_zip({"Projects.csv": _PROJECTS_CSV})
        resp = await client.post(
            "/sources/import-linkedin",
            files={"file": ("export.zip", zip_bytes, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["projects"]) == 1
        assert body["projects"][0]["source"] == "linkedin"
        assert body["projects"][0]["title"] == "Latexy"

    async def test_import_bad_zip_returns_422(self, client: AsyncClient, auth_headers):
        resp = await client.post(
            "/sources/import-linkedin",
            files={"file": ("export.zip", b"definitely not a zip", "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_import_oversized_returns_413(self, client: AsyncClient, auth_headers):
        big = b"\x00" * (10 * 1024 * 1024 + 1)
        resp = await client.post(
            "/sources/import-linkedin",
            files={"file": ("big.zip", big, "application/zip")},
            headers=auth_headers,
        )
        assert resp.status_code == 413

    async def test_import_requires_auth(self, client: AsyncClient):
        zip_bytes = _make_export_zip({"Projects.csv": _PROJECTS_CSV})
        resp = await client.post(
            "/sources/import-linkedin",
            files={"file": ("export.zip", zip_bytes, "application/zip")},
        )
        assert resp.status_code in (401, 403)

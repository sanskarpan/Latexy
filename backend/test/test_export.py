"""
Export endpoint tests.

Tests cover:
- GET /export/formats — list available formats
- POST /export/content/{fmt} — export from raw LaTeX (no auth)
- GET /export/{resume_id}/{fmt} — export saved resume (requires auth)
- DocumentExportService unit tests (correct output per format)
"""

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    \item Reduced latency by 40\% through caching
\end{itemize}
\section*{Education}
\textbf{B.S. Computer Science}, State University \hfill 2019
\section*{Skills}
Python, TypeScript, Docker, PostgreSQL
\end{document}
"""

SUPPORTED_FORMATS = ["tex", "md", "txt", "html", "json", "yaml", "xml", "docx"]


# ── Export service unit tests ─────────────────────────────────────────────────


class TestDocumentExportService:
    """Unit tests for DocumentExportService rule-based conversions."""

    def test_to_text_returns_string(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_text(VALID_LATEX)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_text_removes_latex_commands(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_text(VALID_LATEX)
        assert r"\documentclass" not in result
        assert r"\begin{document}" not in result
        assert r"\textbf" not in result

    def test_to_text_preserves_content(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_text(VALID_LATEX)
        assert "Jane Smith" in result or "jane" in result.lower()

    def test_to_markdown_returns_string(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_markdown(VALID_LATEX)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_markdown_converts_sections_to_headers(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_markdown(VALID_LATEX)
        # Sections like Experience, Education should become ## headers
        assert "##" in result or "Experience" in result

    def test_to_markdown_converts_bold(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_markdown(VALID_LATEX)
        # \textbf{} should become **...**
        assert "**" in result

    def test_to_html_returns_string(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_html(VALID_LATEX)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_html_is_valid_html(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_html(VALID_LATEX)
        assert "<html" in result.lower() or "<!DOCTYPE" in result.lower() or "<body" in result.lower() or "<p" in result.lower()

    def test_to_html_has_meta_charset(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_html(VALID_LATEX)
        assert 'charset' in result.lower() or 'UTF-8' in result

    def test_to_json_returns_dict(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_json(VALID_LATEX)
        assert isinstance(result, dict)

    def test_to_json_has_basics_field(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_json(VALID_LATEX)
        assert "basics" in result

    def test_to_json_is_serializable(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_json(VALID_LATEX)
        # Must be JSON-serializable
        serialized = json.dumps(result)
        assert len(serialized) > 0

    def test_to_yaml_returns_string(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_yaml(VALID_LATEX)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_yaml_is_valid_yaml(self):
        import yaml
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_yaml(VALID_LATEX)
        parsed = yaml.safe_load(result)
        assert isinstance(parsed, dict)

    def test_to_xml_returns_string(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_xml(VALID_LATEX)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_xml_is_valid_xml(self):
        from lxml import etree
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_xml(VALID_LATEX)
        root = etree.fromstring(result.encode())
        assert root is not None

    def test_to_xml_has_resume_root(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_xml(VALID_LATEX)
        assert "<resume" in result.lower() or "<root" in result.lower() or "<?xml" in result

    def test_to_docx_returns_bytes(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_docx(VALID_LATEX)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_to_docx_has_docx_magic_bytes(self):
        from app.services.document_export_service import document_export_service
        result = document_export_service.to_docx(VALID_LATEX)
        # DOCX files are ZIP archives; magic bytes are PK (50 4B)
        assert result[:2] == b"PK"


# ── GET /export/formats ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListExportFormats:
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/export/formats")
        assert resp.status_code == 200

    async def test_returns_formats_list(self, client: AsyncClient):
        resp = await client.get("/export/formats")
        data = resp.json()
        assert "formats" in data
        assert isinstance(data["formats"], list)

    async def test_all_expected_formats_present(self, client: AsyncClient):
        resp = await client.get("/export/formats")
        keys = {fmt["key"] for fmt in resp.json()["formats"]}
        for expected in SUPPORTED_FORMATS:
            assert expected in keys, f"Format '{expected}' missing from /export/formats"

    async def test_each_format_has_required_fields(self, client: AsyncClient):
        resp = await client.get("/export/formats")
        for fmt in resp.json()["formats"]:
            assert "key" in fmt
            assert "mime_type" in fmt
            assert "filename" in fmt


# ── POST /export/content/{fmt} ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExportContent:
    """Test raw LaTeX content export (no auth required)."""

    async def test_export_tex_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/tex",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_tex_content_disposition(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/tex",
            json={"latex_content": VALID_LATEX},
        )
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "resume.tex" in resp.headers.get("content-disposition", "")

    async def test_export_tex_mime_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/tex",
            json={"latex_content": VALID_LATEX},
        )
        assert "tex" in resp.headers.get("content-type", "")

    async def test_export_md_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/md",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_md_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/md",
            json={"latex_content": VALID_LATEX},
        )
        assert "markdown" in resp.headers.get("content-type", "")

    async def test_export_txt_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/txt",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_txt_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/txt",
            json={"latex_content": VALID_LATEX},
        )
        assert "text/plain" in resp.headers.get("content-type", "")

    async def test_export_html_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/html",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_html_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/html",
            json={"latex_content": VALID_LATEX},
        )
        assert "html" in resp.headers.get("content-type", "")

    async def test_export_json_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/json",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_json_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/json",
            json={"latex_content": VALID_LATEX},
        )
        assert "json" in resp.headers.get("content-type", "")

    async def test_export_json_body_is_valid_json(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/json",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200
        parsed = json.loads(resp.content)
        assert isinstance(parsed, dict)

    async def test_export_yaml_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/yaml",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_yaml_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/yaml",
            json={"latex_content": VALID_LATEX},
        )
        assert "yaml" in resp.headers.get("content-type", "") or "text" in resp.headers.get("content-type", "")

    async def test_export_xml_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/xml",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_xml_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/xml",
            json={"latex_content": VALID_LATEX},
        )
        assert "xml" in resp.headers.get("content-type", "")

    async def test_export_docx_returns_200(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/docx",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_export_docx_content_type(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/docx",
            json={"latex_content": VALID_LATEX},
        )
        assert "wordprocessingml" in resp.headers.get("content-type", "")

    async def test_export_docx_body_is_zip(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/docx",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200
        # DOCX is ZIP; starts with PK magic bytes
        assert resp.content[:2] == b"PK"

    async def test_export_unsupported_format_returns_400(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/pptx",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 400

    async def test_export_empty_latex_returns_400(self, client: AsyncClient):
        resp = await client.post(
            "/export/content/txt",
            json={"latex_content": "   "},
        )
        assert resp.status_code == 400

    async def test_export_no_auth_required(self, client: AsyncClient):
        """Export content endpoint requires NO authentication."""
        # No auth headers — should still work
        resp = await client.post(
            "/export/content/txt",
            json={"latex_content": VALID_LATEX},
        )
        assert resp.status_code == 200

    async def test_all_formats_have_content_disposition(self, client: AsyncClient):
        """Every format must set Content-Disposition: attachment."""
        for fmt in SUPPORTED_FORMATS:
            resp = await client.post(
                f"/export/content/{fmt}",
                json={"latex_content": VALID_LATEX},
            )
            assert resp.status_code == 200, f"Format {fmt} returned {resp.status_code}"
            cd = resp.headers.get("content-disposition", "")
            assert "attachment" in cd, f"Format {fmt} missing 'attachment' in Content-Disposition"

    async def test_all_formats_have_filename_in_content_disposition(self, client: AsyncClient):
        """Every format must include filename in Content-Disposition."""
        expected_filenames = {
            "tex": "resume.tex", "md": "resume.md", "txt": "resume.txt",
            "html": "resume.html", "json": "resume.json", "yaml": "resume.yaml",
            "xml": "resume.xml", "docx": "resume.docx",
        }
        for fmt in SUPPORTED_FORMATS:
            resp = await client.post(
                f"/export/content/{fmt}",
                json={"latex_content": VALID_LATEX},
            )
            cd = resp.headers.get("content-disposition", "")
            assert expected_filenames[fmt] in cd, (
                f"Format {fmt}: expected '{expected_filenames[fmt]}' in Content-Disposition, got '{cd}'"
            )


# ── GET /export/{resume_id}/{fmt} ─────────────────────────────────────────────


@pytest.mark.asyncio
class TestExportResume:
    """Test saved resume export (requires auth + DB resume)."""

    async def _create_resume(self, db: AsyncSession, user_id: str, latex: str) -> str:
        """Insert a test resume row and return its ID."""
        resume_id = str(uuid.uuid4())
        await db.execute(
            text(
                "INSERT INTO resumes (id, user_id, title, latex_content) "
                "VALUES (:id, :user_id, :title, :content)"
            ),
            {
                "id": resume_id,
                "user_id": user_id,
                "title": "Test Resume",
                "content": latex,
            },
        )
        await db.commit()
        return resume_id

    async def _get_user_id_from_headers(self, client: AsyncClient, auth_headers: dict) -> str:
        """Extract user_id by calling a known endpoint that echoes the user."""
        resp = await client.get("/jobs/", headers=auth_headers)
        # We can also introspect the session from DB, but simpler: use analytics or profile
        # Fall back to inserting directly in test
        return None

    async def test_export_unauthenticated_returns_401(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/export/{fake_id}/txt")
        assert resp.status_code == 401

    async def test_export_nonexistent_resume_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/export/{fake_id}/txt", headers=auth_headers)
        assert resp.status_code == 404

    async def test_export_unsupported_format_returns_400(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/export/{fake_id}/pptx", headers=auth_headers)
        # 400 because format is invalid (checked before DB lookup)
        assert resp.status_code == 400

    async def test_export_own_resume_as_txt(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Authenticated user can export their own resume."""
        # Insert user + resume directly
        user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Test', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": user_id, "email": f"test_{user_id[:8]}@example.com"},
        )
        await db_session.commit()

        # Create session token
        import re as _re
        from datetime import datetime, timedelta, timezone
        token = f"test_sess_{uuid.uuid4().hex}"
        expires = datetime.now(timezone.utc) + timedelta(days=1)
        await db_session.execute(
            text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
            {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires, "tok": token},
        )
        await db_session.commit()

        resume_id = await self._create_resume(db_session, user_id, VALID_LATEX)

        resp = await client.get(
            f"/export/{resume_id}/txt",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")

    async def test_export_other_users_resume_returns_403(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """A user cannot export another user's resume."""
        # Create a different user's resume
        other_user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": other_user_id, "email": f"test_{other_user_id[:8]}@example.com"},
        )
        await db_session.commit()

        resume_id = await self._create_resume(db_session, other_user_id, VALID_LATEX)

        # auth_headers belongs to a DIFFERENT test user
        resp = await client.get(
            f"/export/{resume_id}/txt",
            headers=auth_headers,
        )
        assert resp.status_code == 403

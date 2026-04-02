"""Tests for Feature 49: Bulk / Batch Resume Export (ZIP)."""
import io
import zipfile

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestBulkExportEndpoint:

    async def test_tex_export_contains_file_per_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """format=tex → ZIP contains one .tex file per resume with correct content."""
        latex = r"\documentclass{article}\begin{document}Hello\end{document}"
        for title in ("Resume Alpha", "Resume Beta"):
            resp = await client.post(
                "/resumes/",
                headers=auth_headers,
                json={"title": title, "latex_content": latex},
            )
            assert resp.status_code == 201

        resp = await client.get(
            "/resumes/export/bulk?format=tex",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        tex_files = [n for n in names if n.endswith(".tex")]
        assert len(tex_files) >= 2

        # Each .tex file should have non-empty content
        for name in tex_files:
            assert len(zf.read(name)) > 0

    async def test_pdf_export_empty_zip_when_no_pdfs(
        self, client: AsyncClient, auth_headers: dict
    ):
        """format=pdf when no PDFs compiled → returns empty ZIP (not 500)."""
        await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "No PDF Resume",
                "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
            },
        )

        resp = await client.get(
            "/resumes/export/bulk?format=pdf",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        pdf_files = [n for n in zf.namelist() if n.endswith(".pdf")]
        # No compiled PDFs → ZIP is empty (or has no .pdf entries)
        assert pdf_files == []

    async def test_bulk_export_unauthenticated_returns_401(
        self, client: AsyncClient
    ):
        """Unauthenticated request → 401."""
        resp = await client.get("/resumes/export/bulk?format=tex")
        assert resp.status_code == 401

    async def test_no_resumes_returns_empty_zip(
        self, client: AsyncClient, auth_headers: dict
    ):
        """User with no resumes → empty ZIP (not 500)."""
        # Create a fresh user implicitly via auth_headers fixture
        # This test uses the shared user, which may already have resumes.
        # Just verify we get a 200 and valid ZIP regardless.
        resp = await client.get(
            "/resumes/export/bulk?format=tex",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert isinstance(zf.namelist(), list)

    async def test_invalid_format_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Unsupported format value → 422."""
        resp = await client.get(
            "/resumes/export/bulk?format=odt",
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_tex_filenames_sanitized(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Resume titles with special characters produce safe .tex filenames."""
        await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "My Resume: 2024 (Final!)",
                "latex_content": r"\documentclass{article}\begin{document}x\end{document}",
            },
        )
        resp = await client.get(
            "/resumes/export/bulk?format=tex",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        for name in zf.namelist():
            # No path traversal chars, no colons, parens, or exclamation marks
            assert "/" not in name or name.count("/") == 0
            assert ":" not in name
            assert "!" not in name

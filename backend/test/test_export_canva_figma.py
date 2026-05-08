"""
Feature 90 — Export to Canva / Figma tests.

Tests:
1. to_canva() — section headers map to HEADING elements, body to TEXT
2. to_canva() — bullet items appear as TEXT with "• " prefix
3. to_figma() — structured sections array is returned
4. to_figma() — bullet items end up in entries[].bullets list
5. GET /export/{id}/canva — returns JSON with non-empty elements array
6. GET /export/{id}/canva — section headers appear as type="HEADING"
7. GET /export/{id}/figma — returns JSON with sections array
8. GET /export/{id}/canva — non-owner gets 403
9. GET /export/{id}/figma — non-owner gets 403
10. GET /export/{id}/canva — missing resume returns 404
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.services.document_export_service import DocumentExportService

# ── Sample LaTeX for all tests ────────────────────────────────────────────────

SAMPLE_LATEX = r"""
\documentclass{article}
\begin{document}

\section{Experience}
\textbf{Acme Corp} \hfill \textbf{2021--2024}

\textit{Senior Engineer}

\begin{itemize}
  \item Built distributed systems serving 10M users
  \item Reduced latency by 40\%
\end{itemize}

\section{Skills}
Python, Go, Kubernetes

\end{document}
"""

# ── Service-level tests (no HTTP) ─────────────────────────────────────────────


class TestToCanva:
    service = DocumentExportService()

    def test_returns_design_type(self):
        result = self.service.to_canva(SAMPLE_LATEX)
        assert result["type"] == "DESIGN"

    def test_section_header_maps_to_heading_element(self):
        result = self.service.to_canva(SAMPLE_LATEX)
        types = [e["type"] for e in result["elements"]]
        assert "HEADING" in types

    def test_heading_text_matches_section_name(self):
        result = self.service.to_canva(SAMPLE_LATEX)
        headings = [e["text"] for e in result["elements"] if e["type"] == "HEADING"]
        assert any("Experience" in h or "experience" in h.lower() for h in headings)

    def test_bullets_prefixed_with_bullet_char(self):
        result = self.service.to_canva(SAMPLE_LATEX)
        texts = [e["text"] for e in result["elements"] if e["type"] == "TEXT"]
        bullet_texts = [t for t in texts if t.startswith("•")]
        assert len(bullet_texts) >= 1

    def test_elements_non_empty_for_non_trivial_latex(self):
        result = self.service.to_canva(SAMPLE_LATEX)
        assert len(result["elements"]) > 0

    def test_empty_latex_returns_empty_elements(self):
        result = self.service.to_canva("\\documentclass{article}\\begin{document}\\end{document}")
        # May have zero or very few elements — must not crash
        assert isinstance(result["elements"], list)


class TestToFigma:
    service = DocumentExportService()

    def test_returns_sections_key(self):
        result = self.service.to_figma(SAMPLE_LATEX)
        assert "sections" in result

    def test_sections_is_list(self):
        result = self.service.to_figma(SAMPLE_LATEX)
        assert isinstance(result["sections"], list)

    def test_section_titles_populated(self):
        result = self.service.to_figma(SAMPLE_LATEX)
        titles = [s["title"] for s in result["sections"]]
        assert any("Experience" in t or "experience" in t.lower() for t in titles)

    def test_bullets_appear_in_entries(self):
        result = self.service.to_figma(SAMPLE_LATEX)
        # Flatten all bullets from all sections/entries
        all_bullets: list[str] = []
        for section in result["sections"]:
            for entry in section["entries"]:
                all_bullets.extend(entry["bullets"])
        assert len(all_bullets) >= 1

    def test_empty_latex_returns_empty_sections(self):
        result = self.service.to_figma("\\documentclass{article}\\begin{document}\\end{document}")
        assert isinstance(result["sections"], list)


# ── Route-level tests via FastAPI test client ─────────────────────────────────


def _make_export_app(owner_id: str = "user-owner", resume_latex: str = SAMPLE_LATEX):
    """Build a minimal FastAPI app with the export router + mocked DB."""
    from app.api.export_routes import router as export_router
    from app.database.connection import get_db
    from app.middleware.auth_middleware import get_current_user_required

    app = FastAPI()
    app.include_router(export_router)

    resume_id = str(uuid.uuid4())

    mock_resume = MagicMock()
    mock_resume.id = resume_id
    mock_resume.user_id = owner_id
    mock_resume.latex_content = resume_latex

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_resume)

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_current_user_required] = lambda: owner_id
    app.dependency_overrides[get_db] = _get_db
    return app, resume_id


class TestCanvaRoute:

    @pytest.mark.asyncio
    async def test_returns_200_with_elements(self):
        app, resume_id = _make_export_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{resume_id}/canva")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "DESIGN"
        assert isinstance(data["elements"], list)
        assert len(data["elements"]) > 0

    @pytest.mark.asyncio
    async def test_section_headers_appear_as_heading_type(self):
        app, resume_id = _make_export_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{resume_id}/canva")
        elements = resp.json()["elements"]
        heading_types = [e for e in elements if e["type"] == "HEADING"]
        assert len(heading_types) >= 1

    @pytest.mark.asyncio
    async def test_non_owner_gets_403(self):
        from app.api.export_routes import router as export_router
        from app.database.connection import get_db
        from app.middleware.auth_middleware import get_current_user_required

        app = FastAPI()
        app.include_router(export_router)

        resume_id = str(uuid.uuid4())
        mock_resume = MagicMock()
        mock_resume.id = resume_id
        mock_resume.user_id = "owner-user"
        mock_resume.latex_content = SAMPLE_LATEX

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_resume)

        async def _get_db():
            yield mock_db

        # Authenticated as a *different* user
        app.dependency_overrides[get_current_user_required] = lambda: "different-user"
        app.dependency_overrides[get_db] = _get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{resume_id}/canva")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_resume_returns_404(self):
        from app.api.export_routes import router as export_router
        from app.database.connection import get_db
        from app.middleware.auth_middleware import get_current_user_required

        app = FastAPI()
        app.include_router(export_router)

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)  # resume not found

        async def _get_db():
            yield mock_db

        app.dependency_overrides[get_current_user_required] = lambda: "user-001"
        app.dependency_overrides[get_db] = _get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{str(uuid.uuid4())}/canva")
        assert resp.status_code == 404


class TestFigmaRoute:

    @pytest.mark.asyncio
    async def test_returns_200_with_sections(self):
        app, resume_id = _make_export_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{resume_id}/figma")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert isinstance(data["sections"], list)

    @pytest.mark.asyncio
    async def test_non_owner_gets_403(self):
        from app.api.export_routes import router as export_router
        from app.database.connection import get_db
        from app.middleware.auth_middleware import get_current_user_required

        app = FastAPI()
        app.include_router(export_router)

        resume_id = str(uuid.uuid4())
        mock_resume = MagicMock()
        mock_resume.id = resume_id
        mock_resume.user_id = "owner-user"
        mock_resume.latex_content = SAMPLE_LATEX

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_resume)

        async def _get_db():
            yield mock_db

        app.dependency_overrides[get_current_user_required] = lambda: "attacker"
        app.dependency_overrides[get_db] = _get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/export/{resume_id}/figma")
        assert resp.status_code == 403

"""Focused B50b tests for genuine Poppler-backed image exports."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


def test_render_pdf_first_page_uses_fixed_pdftocairo_command(monkeypatch):
    from app.api import export_routes

    calls = []

    monkeypatch.setattr(export_routes.shutil, "which", lambda name: "/usr/bin/pdftocairo")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(f"{command[-1]}.jpg")
        output.write_bytes(b"\xff\xd8\xffjpeg-bytes")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(export_routes.subprocess, "run", fake_run)

    result = export_routes._render_pdf_first_page(b"%PDF-1.7 test", "jpeg")

    assert result == b"\xff\xd8\xffjpeg-bytes"
    command, kwargs = calls[0]
    assert command[0] == "/usr/bin/pdftocairo"
    assert command[1:7] == ["-singlefile", "-f", "1", "-l", "1", "-r"]
    assert "-jpeg" in command
    assert kwargs["timeout"] == export_routes.PDF_RENDER_TIMEOUT_SECONDS
    assert kwargs["check"] is False
    assert kwargs["cwd"]


def test_render_pdf_first_page_uses_explicit_svg_output_and_signature(monkeypatch):
    from app.api import export_routes

    calls = []
    monkeypatch.setattr(export_routes.shutil, "which", lambda name: "/usr/bin/pdftocairo")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == "/usr/bin/pdftocairo"
        assert command[1:7] == ["-f", "1", "-l", "1", "-r", "150"]
        assert "-singlefile" not in command
        assert "-svg" in command
        assert command[-1].endswith("rendered.svg")
        Path(command[-1]).write_bytes(b'<?xml version="1.0"?><svg></svg>')
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(export_routes.subprocess, "run", fake_run)

    result = export_routes._render_pdf_first_page(b"%PDF-1.7 test", "svg")

    assert result.startswith(b"<?xml")
    assert calls[0][1]["timeout"] == export_routes.PDF_RENDER_TIMEOUT_SECONDS


def test_render_pdf_fails_closed_when_poppler_is_missing(monkeypatch):
    from app.api import export_routes

    monkeypatch.setattr(export_routes.shutil, "which", lambda _name: None)

    with pytest.raises(export_routes.PdfRenderUnavailable):
        export_routes._render_pdf_first_page(b"%PDF-1.7 test", "svg")


@pytest.mark.asyncio
async def test_saved_image_export_has_genuine_mime_and_filename(monkeypatch):
    from app.api import export_routes

    resume = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        user_id="user-1",
        latex_content="\\documentclass{article}",
        structured_content=None,
        content_source="manual_latex",
    )
    db = AsyncMock()
    db.get.return_value = resume
    monkeypatch.setattr(export_routes, "_get_latest_compiled_pdf", AsyncMock(return_value=b"%PDF-1.7"))
    monkeypatch.setattr(export_routes, "_render_pdf_first_page", lambda _pdf, _fmt: b"jpeg-bytes")

    response = await export_routes.export_resume(
        resume.id,
        "jpeg",
        db,
        "user-1",
    )

    assert response.media_type == "image/jpeg"
    assert response.body == b"jpeg-bytes"
    assert "filename=\"resume.jpeg\"" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_declared_oversized_pdf_is_rejected_before_storage_read():
    from app.api import export_routes

    compilation = SimpleNamespace(pdf_path="owned/object.pdf", pdf_size=export_routes.MAX_RENDER_INPUT_BYTES + 1)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: compilation)

    with pytest.raises(HTTPException) as caught:
        await export_routes._get_latest_compiled_pdf("resume-1", "user-1", db)

    assert caught.value.status_code == 413


@pytest.mark.asyncio
async def test_raw_latex_image_export_is_rejected():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.export_routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/export/content/svg", json={"latex_content": "test"})

    assert response.status_code == 400
    assert "compiled PDF" in response.json()["detail"]

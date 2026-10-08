"""Synthetic contract tests for template PDF/PNG asset completeness.

These tests deliberately replace the database, compiler process, storage, and
PDF converter.  They exercise ``compile_templates.main`` without Redis,
Postgres, TeX, object storage, or provider calls.
"""

import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.scripts import compile_templates


class _FakeEngine:
    async def dispose(self):
        return None


class _FakeSession:
    def __init__(self, templates):
        self.templates = templates

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: self.templates),
        )


def _template_runtime(monkeypatch, converter, *, existing_keys=(), upload=None):
    """Install a completely local runtime around the production entrypoint."""

    template = SimpleNamespace(
        id="synthetic-template",
        name="Synthetic template",
        latex_content=r"\documentclass{article}\begin{document}OK\end{document}",
    )
    engine = _FakeEngine()
    uploaded = []
    existing = set(existing_keys)

    monkeypatch.setattr(compile_templates, "create_async_engine", lambda *_a, **_k: engine)
    monkeypatch.setattr(
        compile_templates,
        "async_sessionmaker",
        lambda *_a, **_k: lambda: _FakeSession([template]),
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://synthetic.invalid/assets")
    monkeypatch.setattr(compile_templates.storage_service, "file_exists", lambda key: key in existing)

    def upload_bytes(key, data, content_type):
        if upload is not None:
            upload(key, data, content_type)
        uploaded.append((key, data, content_type))
        existing.add(key)

    monkeypatch.setattr(
        compile_templates.storage_service,
        "upload_bytes",
        upload_bytes,
    )

    def run(command, **kwargs):
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] == 60
        output_dir = Path(command[3])
        (output_dir / "template.pdf").write_bytes(b"%PDF-1.7\nsynthetic\n")
        (output_dir / "template.fls").write_text(f"PWD {output_dir}\nINPUT {output_dir / 'template.tex'}\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(compile_templates.subprocess, "run", run)
    fake_pdf2image = ModuleType("pdf2image")
    fake_pdf2image.convert_from_path = converter
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)
    return uploaded


class _PngImage:
    def save(self, stream, format):
        assert format == "PNG"
        stream.write(b"\x89PNG\r\n\x1a\nsynthetic")


class _BrokenPngImage:
    def save(self, _stream, format):
        assert format == "PNG"
        raise RuntimeError("synthetic PNG encoding failure")


@pytest.mark.asyncio
async def test_valid_pdf_and_png_are_both_uploaded(monkeypatch):
    uploaded = _template_runtime(
        monkeypatch,
        lambda *_a, **_k: [_PngImage()],
    )

    await compile_templates.main()

    assert {key for key, _data, _content_type in uploaded} == {
        "templates/synthetic-template.pdf",
        "templates/synthetic-template.png",
    }


@pytest.mark.asyncio
async def test_empty_png_conversion_is_a_batch_failure(monkeypatch):
    _template_runtime(monkeypatch, lambda *_a, **_k: [])

    with pytest.raises(RuntimeError, match=r"template asset generation failed for 1 template"):
        await compile_templates.main()


@pytest.mark.asyncio
async def test_png_conversion_exception_is_a_batch_failure(monkeypatch):
    def convert(*_args, **_kwargs):
        raise RuntimeError("synthetic converter failure")

    _template_runtime(monkeypatch, convert)

    with pytest.raises(RuntimeError, match=r"template asset generation failed for 1 template"):
        await compile_templates.main()


@pytest.mark.asyncio
async def test_png_save_failure_preserves_pdf_without_png(monkeypatch):
    uploaded = _template_runtime(monkeypatch, lambda *_a, **_k: [_BrokenPngImage()])

    with pytest.raises(RuntimeError, match=r"template asset generation failed for 1 template"):
        await compile_templates.main()

    assert [key for key, _data, _content_type in uploaded] == ["templates/synthetic-template.pdf"]


@pytest.mark.asyncio
async def test_png_upload_failure_preserves_pdf_and_retries(monkeypatch):
    state = {"fail_png": True}

    def upload(key, _data, _content_type):
        if key.endswith(".png") and state["fail_png"]:
            raise RuntimeError("synthetic PNG upload failure")

    uploaded = _template_runtime(monkeypatch, lambda *_a, **_k: [_PngImage()], upload=upload)

    with pytest.raises(RuntimeError, match=r"template asset generation failed for 1 template"):
        await compile_templates.main()
    assert [key for key, _data, _content_type in uploaded] == ["templates/synthetic-template.pdf"]

    state["fail_png"] = False
    await compile_templates.main()
    assert {key for key, _data, _content_type in uploaded} == {
        "templates/synthetic-template.pdf",
        "templates/synthetic-template.png",
    }


@pytest.mark.asyncio
async def test_both_existing_assets_are_skipped(monkeypatch):
    converter_called = False

    def convert(*_args, **_kwargs):
        nonlocal converter_called
        converter_called = True
        return [_PngImage()]

    uploaded = _template_runtime(
        monkeypatch,
        convert,
        existing_keys={
            "templates/synthetic-template.pdf",
            "templates/synthetic-template.png",
        },
    )

    await compile_templates.main()

    assert uploaded == []
    assert converter_called is False

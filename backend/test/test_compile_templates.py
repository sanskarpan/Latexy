"""Regression coverage for production template asset generation (#1689)."""

import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.scripts import compile_templates
from app.scripts.compile_templates import _raise_if_failed


class _FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


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


def _patch_compile_runtime(monkeypatch, templates, subprocess_run):
    engine = _FakeEngine()
    monkeypatch.setattr(compile_templates, "create_async_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(
        compile_templates,
        "async_sessionmaker",
        lambda *_args, **_kwargs: lambda: _FakeSession(templates),
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://example.invalid/template-assets")
    monkeypatch.setattr(compile_templates.subprocess, "run", subprocess_run)

    uploaded = []
    monkeypatch.setattr(compile_templates.storage_service, "file_exists", lambda _key: False)
    monkeypatch.setattr(
        compile_templates.storage_service,
        "upload_bytes",
        lambda key, data, content_type: uploaded.append((key, data, content_type)),
    )

    class _Image:
        def save(self, stream, format):
            assert format == "PNG"
            stream.write(b"png")

    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        ModuleType("pdf2image"),
    )
    sys.modules["pdf2image"].convert_from_path = lambda *_args, **_kwargs: [_Image()]
    return engine, uploaded


def _template(template_id, name, source):
    return SimpleNamespace(id=template_id, name=name, latex_content=source)


def test_asset_backfill_accepts_a_clean_batch():
    _raise_if_failed(0)


def test_asset_backfill_fails_the_caller_when_any_template_fails():
    with pytest.raises(
        RuntimeError,
        match=r"template asset generation failed for 2 template\(s\)",
    ):
        _raise_if_failed(2)


@pytest.mark.asyncio
async def test_asset_backfill_uses_new_resume_engine_for_latin_and_unicode_templates(monkeypatch):
    """The real batch path must invoke LuaLaTeX, not just expose a helper."""

    calls = []
    sources = {}

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 60
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        tex_path = Path(command[-1])
        sources[tex_path.read_text(encoding="utf-8")] = command[0]
        output_dir = Path(command[3])
        (output_dir / "template.pdf").write_bytes(b"%PDF-1.7\n")
        (output_dir / "template.fls").write_text(f"PWD {output_dir}\nINPUT {output_dir / 'template.tex'}\n")
        return SimpleNamespace(returncode=0)

    europecv = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "regional" / "europecv.tex").read_text()
    hindi = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "ats_safe" / "hindi_professional.tex").read_text()
    polish = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "regional" / "polish_cv_rodo.tex").read_text()
    templates = [
        _template("latin", "Latin", r"\documentclass{article}\begin{document}Hello\end{document}"),
        _template("hindi", "Hindi", hindi),
        _template("polish", "Polish", polish),
        _template("europecv", "EuroCV", europecv),
    ]
    monkeypatch.setattr(compile_templates.settings, "DEFAULT_NEW_RESUME_COMPILER", "lualatex")
    _engine, uploaded = _patch_compile_runtime(monkeypatch, templates, run)

    await compile_templates.main()

    assert calls
    assert len(calls) == len(templates) * 2
    assert {command[0] for command in calls} == {"lualatex"}
    assert any("{europecv}" in source and "\\documentclass[totpages,helvetica,openbib,nologo,nobranding,notitle,english]" in source for source in sources)
    assert {key for key, _data, _content_type in uploaded} == {
        f"templates/{template.id}.{extension}"
        for template in templates
        for extension in ("pdf", "png")
    }
    assert _engine.disposed


@pytest.mark.asyncio
async def test_asset_backfill_propagates_failed_compilation(monkeypatch):
    """A compiler failure remains a batch failure and cannot be uploaded."""

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output_dir = Path(command[3])
        (output_dir / "template.log").write_text("! synthetic compiler failure\nl.1", encoding="utf-8")
        (output_dir / "template.fls").write_text(f"PWD {output_dir}\nINPUT {output_dir / 'template.tex'}\n")
        return SimpleNamespace(returncode=1)

    hindi = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "ats_safe" / "hindi_professional.tex").read_text()
    polish = (Path(__file__).resolve().parents[1] / "app" / "data" / "templates" / "regional" / "polish_cv_rodo.tex").read_text()
    templates = [
        _template("hindi", "Hindi", hindi),
        _template("polish", "Polish", polish),
    ]
    monkeypatch.setattr(compile_templates.settings, "DEFAULT_NEW_RESUME_COMPILER", "lualatex")
    _engine, uploaded = _patch_compile_runtime(monkeypatch, templates, run)

    with pytest.raises(RuntimeError, match=r"template asset generation failed for 2 template\(s\)"):
        await compile_templates.main()

    assert len(calls) == len(templates) * 2
    assert all(command[0] == "lualatex" for command in calls)
    assert uploaded == []
    assert _engine.disposed

"""Focused, offline contract for the template backfill compiler boundary."""

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.scripts import compile_templates


class _Engine:
    async def dispose(self):
        return None


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _query):
        template = SimpleNamespace(
            id="synthetic-guard",
            name="Synthetic guard",
            latex_content=r"\documentclass{article}\begin{document}guard\end{document}",
        )
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [template]))


class _Image:
    def save(self, stream, format):
        assert format == "PNG"
        stream.write(b"synthetic-png")


@pytest.mark.asyncio
async def test_backfill_compiler_uses_restricted_environment_and_flags(monkeypatch):
    """Both real compiler passes must drop sensitive vars and disable shell escape."""

    monkeypatch.setattr(compile_templates, "_db_url", lambda: "synthetic://unused")
    monkeypatch.setattr(compile_templates, "create_async_engine", lambda *_a, **_k: _Engine())
    monkeypatch.setattr(
        compile_templates,
        "async_sessionmaker",
        lambda *_a, **_k: lambda: _Session(),
    )
    monkeypatch.setattr(compile_templates.storage_service, "file_exists", lambda _key: False)
    monkeypatch.setattr(compile_templates.storage_service, "upload_bytes", lambda *_a, **_k: None)
    monkeypatch.setenv("LATEXY_SYNTHETIC_SECRET", "sentinel-only")
    for credential_name in (
        "DATABASE_URL",
        "REDIS_URL",
        "OPENAI_API_KEY",
        "API_KEY_ENCRYPTION_KEY",
    ):
        monkeypatch.setenv(credential_name, "synthetic-secret-only")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1640995200")
    monkeypatch.setenv("TEXMFVAR", "/tmp/synthetic-texmfvar")
    monkeypatch.setenv("TEXMFHOME", "/tmp/synthetic-texmfhome")

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["timeout"] == 60
        output_dir = Path(command[command.index("-output-directory") + 1])
        (output_dir / "template.pdf").write_bytes(b"%PDF-1.7\nsynthetic\n")
        (output_dir / "template.fls").write_text(f"PWD {output_dir}\nINPUT {output_dir / 'template.tex'}\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(compile_templates.subprocess, "run", run)
    fake_pdf2image = ModuleType("pdf2image")
    fake_pdf2image.convert_from_path = lambda *_a, **_k: [_Image()]
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)

    await compile_templates.main()

    assert len(calls) == 2
    for command, kwargs in calls:
        engine_index = command.index("-interaction=nonstopmode") - 1
        assert command[engine_index] == compile_templates.settings.DEFAULT_NEW_RESUME_COMPILER
        output_dir = command[command.index("-output-directory") + 1]
        if command[engine_index] == "lualatex":
            assert command[1].endswith("linux_engine_sandbox.py")
            assert Path(command[2]).resolve() == Path(output_dir).resolve()
        assert command[-1].endswith("template.tex")
        assert kwargs["cwd"] == output_dir
        assert "-no-shell-escape" in command
        assert "-recorder" in command
        child_env = kwargs["env"]
        assert child_env["SOURCE_DATE_EPOCH"] == "1640995200"
        assert child_env["TEXMFVAR"] == str(Path(command[command.index("-output-directory") + 1]).resolve() / ".tex-cache")
        assert child_env["TEXMFCACHE"].startswith(child_env["TEXMFVAR"] + os.pathsep)
        assert child_env["TEXMFHOME"] == "/tmp/synthetic-texmfhome"
        assert child_env["openin_any"] == "p"  # Compatibility mode is set only inside the confined launcher.
        assert child_env["openout_any"] == "p"
        assert child_env["shell_escape"] == "f"
        for credential_name in (
            "LATEXY_SYNTHETIC_SECRET",
            "DATABASE_URL",
            "REDIS_URL",
            "OPENAI_API_KEY",
            "API_KEY_ENCRYPTION_KEY",
        ):
            assert credential_name not in child_env

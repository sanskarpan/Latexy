"""Image font preparation must not consume a user document's compile deadline."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.services import latex_service as ls
from scripts import warm_lualatex_cache as warmup

REAL_RECORDER_CHECK = ls.find_recorder_read_escape


def test_warmup_uses_fixed_input_and_no_application_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", "synthetic-private-canary")
    monkeypatch.setenv("DATABASE_URL", "synthetic-private-canary")
    monkeypatch.setenv("TEXINPUTS", "synthetic-private-canary")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        workspace = kwargs["cwd"]
        assert (workspace / "warmup.tex").read_text(encoding="utf-8") == warmup.TRUSTED_PROBES[len(calls) - 1]
        (workspace / "warmup.pdf").write_bytes(b"%PDF synthetic")
        return SimpleNamespace(returncode=0)

    with patch.object(warmup.subprocess, "run", side_effect=run):
        warmup.warm_cache(tmp_path / "cache", tmp_path / "config")
    command, options = calls[0]
    assert "-no-shell-escape" in command and "-recorder" in command
    assert options["env"]["openin_any"] == "r"
    assert options["env"]["openout_any"] == "p"
    assert options["env"]["shell_escape"] == "f"
    assert "synthetic-private-canary" not in repr(options["env"])
    assert all(key not in options["env"] for key in ("DODO_API_KEY", "DATABASE_URL", "TEXINPUTS"))
    assert len(calls) == 5
    assert len({options["cwd"] for _command, options in calls}) == 5
    assert all(0 < options["timeout"] <= 600 for _command, options in calls)
    for region, source in zip(("SC", "TC", "JP", "KR"), warmup.TRUSTED_PROBES[1:]):
        assert f"Noto Sans CJK {region}" in source


def test_probes_share_one_total_deadline(tmp_path):
    timeouts = []

    def run(_command, **kwargs):
        timeouts.append(kwargs["timeout"])
        (kwargs["cwd"] / "warmup.pdf").write_bytes(b"%PDF synthetic")
        return SimpleNamespace(returncode=0)

    with (
        patch.object(warmup.subprocess, "run", side_effect=run),
        patch.object(warmup.time, "monotonic", side_effect=[100, 101, 102, 103, 104, 105]),
    ):
        warmup.warm_cache(tmp_path / "cache", tmp_path / "config")
    assert timeouts == [599, 598, 597, 596, 595]


def test_remaining_deadline_exhaustion_stops_before_next_probe(tmp_path):
    def run(_command, **kwargs):
        (kwargs["cwd"] / "warmup.pdf").write_bytes(b"%PDF synthetic")
        return SimpleNamespace(returncode=0)

    with (
        patch.object(warmup.subprocess, "run", side_effect=run) as compiler,
        patch.object(warmup.time, "monotonic", side_effect=[0, 0, 601]),
        pytest.raises(TimeoutError, match="initialization timed out"),
    ):
        warmup.warm_cache(tmp_path / "cache", tmp_path / "config")
    assert compiler.call_count == 1


def test_engine_timeout_returns_only_safe_setup_error(tmp_path):
    with (
        patch.object(warmup.subprocess, "run", side_effect=warmup.subprocess.TimeoutExpired("synthetic-command", 1)),
        pytest.raises(TimeoutError, match="initialization timed out") as error,
    ):
        warmup.warm_cache(tmp_path / "cache", tmp_path / "config")
    assert "synthetic-command" not in str(error.value)


@pytest.mark.parametrize("returncode,produces_pdf", [(1, True), (0, False)])
def test_failed_warmup_fails_image_setup(tmp_path, returncode, produces_pdf):
    def run(_command, **kwargs):
        if produces_pdf:
            (kwargs["cwd"] / "warmup.pdf").write_bytes(b"%PDF synthetic")
        return SimpleNamespace(returncode=returncode)

    with patch.object(warmup.subprocess, "run", side_effect=run), pytest.raises(RuntimeError, match="initialization failed"):
        warmup.warm_cache(tmp_path / "cache", tmp_path / "config")


@pytest.mark.parametrize("filename,user", [("Dockerfile", "appuser"), ("Dockerfile.prod", "latexy")])
def test_images_warm_cache_after_font_install_and_switching_user(filename, user):
    source = (Path(__file__).parents[1] / filename).read_text()
    warm_command = source.index("RUN python scripts/warm_lualatex_cache.py")
    normalization = source.index("-exec touch -m -d '@1704067200'")
    fontconfig = source.index("fc-cache --force --system-only")
    assert source.index("fonts-noto-core") < normalization < fontconfig < source.index(f"USER {user}") < warm_command
    assert source.index("ENV TEXMFVAR=") < warm_command


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="Actual LuaTeX engine is not installed on this host")
def test_fresh_runtime_owned_cache_warms_before_30_second_document(monkeypatch):
    from app.workers import orchestrator as orch

    cache_parent = Path(os.environ.get("TEXMFVAR", "/var/lib/texmf/latexy-cache"))
    if not cache_parent.is_dir() or not os.access(cache_parent, os.W_OK):
        pytest.skip("A writable trusted runtime TeX cache is required")
    with tempfile.TemporaryDirectory(prefix="warmup-isolated-", dir=cache_parent) as directory:
        isolated = Path(directory)
        cache_dir, config_dir = isolated / "cache", isolated / "config"
        warmup.warm_cache(cache_dir, config_dir)
        names = cache_dir / "luatex-cache" / "generic" / "names"
        assert any(names.glob("luaotfload-names.*"))
        assert all(path.stat().st_uid == os.getuid() for path in isolated.rglob("*"))
        with tempfile.TemporaryDirectory(prefix="latexy-warmed-document-") as jobs:
            original_env = ls.engine_env

            def prepared_env(compiler):
                return {**original_env(compiler), "TEXMFVAR": str(cache_dir), "TEXMFCONFIG": str(config_dir)}

            monkeypatch.setattr(orch.settings, "TEMP_DIR", Path(jobs))
            monkeypatch.setattr(orch, "engine_env", prepared_env)
            monkeypatch.setattr(orch, "docker_engine_available", lambda: False)
            monkeypatch.setattr(orch, "assert_local_engine_allowed", lambda _job: None)
            monkeypatch.setattr(orch, "is_cancelled", lambda _job: False)
            monkeypatch.setattr(orch, "find_recorder_read_escape", REAL_RECORDER_CHECK)
            monkeypatch.setattr(orch, "publish_event", lambda *_args: None)
            monkeypatch.setattr(orch, "cache_compile_log", lambda *_args: None)
            monkeypatch.setattr(orch, "record_compile", lambda *_args, **_kwargs: None)
            monkeypatch.setattr(orch, "cache_compile_output", lambda _job, path: (path / "resume.pdf").read_bytes())
            result = orch._run_latex_stage(str(uuid4()), warmup.TRUSTED_SOURCE, compiler="lualatex", timeout_seconds=30)
            assert result[0] is True, result[2]
            assert result[4].startswith(b"%PDF")

"""Lua cache writes remain job-scoped and cannot expose app credentials."""

import os
from pathlib import Path

import pytest

from app.services.latex_service import docker_engine_command, docker_sandbox_args, engine_env, engine_sandbox_flags


def test_native_cache_is_private_to_each_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXMFCACHE", "/var/lib/texmf")
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a, b = engine_env(first), engine_env(second)
    assert a["TEXMFVAR"] != b["TEXMFVAR"]
    assert Path(a["TEXMFVAR"]).is_dir()
    assert a["TEXMFCACHE"] == a["TEXMFVAR"] + os.pathsep + "/var/lib/texmf"
    assert "OPENAI_API_KEY" not in a
    assert a["shell_escape"] == "f"


def test_cache_symlink_cannot_escape_workspace(tmp_path):
    workspace = tmp_path / "job"
    workspace.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    try:
        (workspace / ".tex-cache").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlinks; covered on Linux")
    with pytest.raises(ValueError, match="escapes"):
        engine_env(workspace)


def test_docker_cache_uses_engine_mount_without_host_credentials():
    args = docker_sandbox_args("/workdir")
    assert "TEXMFVAR=/workdir/.tex-cache" in args
    assert "TEXMFCACHE=/workdir/.tex-cache:$TEXMFSYSVAR" in args
    assert "--network" in args and "none" in args


def test_lua_keeps_paranoid_parent_policy_and_requires_kernel_launcher(tmp_path):
    env = engine_env(tmp_path, "lualatex")
    assert env["openin_any"] == "p"
    assert env["TEXMFOUTPUT"] == "/usr/share/texlive/texmf-dist"
    assert "--safer" not in engine_sandbox_flags("lualatex")
    assert "--safer" not in engine_sandbox_flags("pdflatex")
    assert "TEXMFOUTPUT" not in engine_env(tmp_path, "pdflatex")
    assert not list(tmp_path.glob("*.txt"))


def test_lua_names_cache_nested_symlink_is_rejected(tmp_path):
    external = tmp_path / "outside"
    external.mkdir()
    workspace = tmp_path / "job"
    (workspace / ".tex-cache").mkdir(parents=True)
    try:
        (workspace / ".tex-cache/luatex-cache").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlinks; covered on Linux")
    with pytest.raises(ValueError, match="escapes"):
        engine_env(workspace, "lualatex")


def test_docker_lua_bootstrap_keeps_arguments_out_of_shell_source():
    malicious = "resume.tex; cat /etc/passwd"
    command = docker_engine_command("lualatex", ["--safer", malicious])
    assert command[:2] == ["sh", "-c"]
    assert malicious not in command[2]
    assert command[4:] == ["/workspace", "lualatex", "--safer", malicious]
    assert 'exec python3 /latexy-engine-sandbox.py "$workspace" "$@"' in command[2]
    assert docker_engine_command("pdflatex", ["resume.tex"]) == ["pdflatex", "resume.tex"]
    with pytest.raises(ValueError, match="Invalid engine mount"):
        docker_engine_command("lualatex", [], "/tmp/client-selected")

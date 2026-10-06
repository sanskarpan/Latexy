import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.latex_compiler import LaTeXCompiler
from app.services.latex_service import docker_container_name


class _EmptyPipe:
    async def read(self, size: int) -> bytes:
        return b""


def _compiler() -> LaTeXCompiler:
    compiler = object.__new__(LaTeXCompiler)
    compiler.docker_image = "texlive:test"
    compiler.use_docker = False
    compiler.latex_command = None
    return compiler


def test_docker_capability_requires_configured_image():
    compiler = _compiler()
    with patch(
        "app.services.latex_compiler.subprocess.run",
        return_value=SimpleNamespace(returncode=1),
    ) as run:
        assert compiler._check_docker_available() is False

    run.assert_called_once_with(
        ["docker", "image", "inspect", "texlive:test"],
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_docker_capability_accepts_reachable_configured_image():
    compiler = _compiler()
    with patch(
        "app.services.latex_compiler.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ):
        assert compiler._check_docker_available() is True


def test_is_available_rechecks_capability_after_startup():
    compiler = _compiler()
    with (
        patch.object(compiler, "_check_docker_available", return_value=True) as docker,
        patch.object(compiler, "_get_latex_command") as local,
    ):
        assert compiler.is_available() is True
    docker.assert_called_once()
    local.assert_not_called()
    assert compiler.use_docker is True


def test_is_available_rechecks_local_engine_when_docker_disappears():
    compiler = _compiler()
    compiler.use_docker = True
    with (
        patch.object(compiler, "_check_docker_available", return_value=False),
        patch.object(compiler, "_get_latex_command", return_value="pdflatex"),
    ):
        assert compiler.is_available() is True
    assert compiler.use_docker is False
    assert compiler.latex_command == "pdflatex"


@pytest.mark.asyncio
async def test_docker_timeout_removes_exact_named_container():
    compiler = _compiler()
    process = MagicMock(returncode=None)
    process.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    process.kill = MagicMock()
    process.wait = AsyncMock()
    with (
        patch(
            "app.services.latex_compiler.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch("app.services.latex_service.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run,
    ):
        result = await compiler._compile_with_docker(Path("job-123"), timeout=1)

    assert result[0] is False
    container = docker_container_name("job-123", "legacy")
    assert any(call.args[0] == ["docker", "rm", "-f", container] for call in run.call_args_list)


@pytest.mark.asyncio
async def test_docker_cancellation_removes_exact_named_container():
    compiler = _compiler()
    process = MagicMock(returncode=None)
    process.stdout = _EmptyPipe()
    process.stderr = _EmptyPipe()
    process.kill = MagicMock()
    process.wait = AsyncMock()
    with (
        patch(
            "app.services.latex_compiler.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch(
            "app.services.latex_compiler.capture_process_output_bounded",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        patch("app.services.latex_service.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run,
    ):
        with pytest.raises(asyncio.CancelledError):
            await compiler._compile_with_docker(Path("job-456"), timeout=1)

    container = docker_container_name("job-456", "legacy")
    assert any(call.args[0] == ["docker", "rm", "-f", container] for call in run.call_args_list)


@pytest.mark.asyncio
async def test_local_engine_does_not_remove_docker_container(tmp_path):
    compiler = _compiler()
    process = MagicMock(returncode=0)
    process.stdout = _EmptyPipe()
    process.stderr = _EmptyPipe()
    process.wait = AsyncMock()
    work_dir = tmp_path / "job-789"
    work_dir.mkdir()
    (work_dir / "document.fls").write_text(f"PWD {work_dir}\nINPUT document.tex\nOUTPUT document.log\n")
    with (
        patch(
            "app.services.latex_compiler.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch("app.services.latex_service.subprocess.run") as run,
    ):
        result = await compiler._compile_local(work_dir, timeout=1)

    assert result == (True, None)
    run.assert_not_called()

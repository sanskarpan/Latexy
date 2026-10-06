"""The retained compiler adapter must not bypass shared engine confinement."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import latex_compiler as module


@pytest.fixture
def compiler(tmp_path):
    # No startup capability probes are needed for adapter contract tests.
    instance = object.__new__(module.LaTeXCompiler)
    instance.temp_dir = tmp_path
    instance.latex_command = "pdflatex"
    return instance


@pytest.mark.parametrize("identifier", ["..", "../outside", "/etc", "a/b", "", "a\\b"])
def test_workspace_rejects_traversal(compiler, identifier):
    with pytest.raises(ValueError):
        compiler._work_dir(identifier)


def test_workspace_rejects_existing_symlink_escape(compiler, tmp_path):
    external = tmp_path.parent / "outside-legacy-compiler"
    (tmp_path / "job").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        compiler._work_dir("job")


async def test_invalid_cleanup_cannot_remove_parent(compiler, tmp_path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("owned test fixture")
    await compiler.cleanup_job_files("..")
    assert sentinel.exists()


@pytest.mark.parametrize("docker", [False, True])
async def test_invocations_use_shared_sandbox_and_minimal_environment(monkeypatch, compiler, tmp_path, docker):
    monkeypatch.setenv("LEGACY_COMPILER_PRIVATE_KEY", "must-not-reach-engine")
    launch = AsyncMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(module, "capture_process_output_bounded", AsyncMock(return_value="safe output"))
    monkeypatch.setattr(module, "cleanup_docker_container_async", AsyncMock())
    allow = Mock()
    monkeypatch.setattr(module, "assert_local_engine_allowed", allow)
    compiler._read_escape = Mock(return_value=False)
    if docker:
        compiler.docker_image = "test-image"
        result = await compiler._compile_with_docker(tmp_path, 10)
    else:
        result = await compiler._compile_local(tmp_path, 10)
        allow.assert_called_once_with(tmp_path.name)
    assert result == (True, None)
    command = launch.call_args.args
    assert "-no-shell-escape" in command
    assert "-recorder" in command
    environment = launch.call_args.kwargs["env"]
    assert "LEGACY_COMPILER_PRIVATE_KEY" not in environment
    assert environment["openout_any"] == "p"
    assert environment["shell_escape"] == "f"
    if docker:
        assert command[command.index("--network") + 1] == "none"
        assert command[command.index("--cap-drop") + 1] == "ALL"


def test_success_without_recorder_fails_closed(compiler, tmp_path):
    assert compiler._read_escape("ordinary output", tmp_path, str(tmp_path), True)


def test_recorder_outside_read_fails_closed(compiler, tmp_path):
    (tmp_path / "document.fls").write_text(f"PWD {tmp_path}\nINPUT /etc/hostname\n")
    assert compiler._read_escape("ordinary output", tmp_path, str(tmp_path), True)


def test_transcript_escape_fails_before_log_context_is_returned(compiler, tmp_path):
    assert compiler._read_escape("(/etc/hostname\nprivate contents", tmp_path, str(tmp_path), False)

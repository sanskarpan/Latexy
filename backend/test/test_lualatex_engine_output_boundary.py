"""LuaTeX compatibility keeps credentials and unvalidated engine output confined."""

import shutil
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services import latex_service as ls

REAL_RECORDER_CHECK = ls.find_recorder_read_escape


@pytest.fixture(scope="session")
def warm_trusted_lualatex_font_cache():
    """Prepare engine data with fixed trusted input before timed canary jobs.

    LuaTeX rebuilds its font database on a fresh worker/cache directory. That
    setup can take longer than a document deadline; it is not user compilation.
    """
    with tempfile.TemporaryDirectory(prefix="latexy-trusted-lua-warmup-") as directory:
        workspace = Path(directory)
        (workspace / "warmup.tex").write_text(
            r"\documentclass{article}\begin{document}Trusted font cache warmup\end{document}",
        )
        result = subprocess.run(
            ["lualatex", *ls.LATEX_SANDBOX_FLAGS, "-interaction=nonstopmode", "-halt-on-error", "warmup.tex"],
            cwd=workspace, env=ls.engine_env("lualatex"), capture_output=True, timeout=180,
        )
        assert result.returncode == 0, "Trusted LuaTeX font-cache setup failed"
        assert (workspace / "warmup.pdf").is_file()
        assert REAL_RECORDER_CHECK(workspace / "warmup.fls", workspace, require_recorder=True) is None


@pytest.mark.parametrize("compiler,read_mode", [
    (None, "p"), ("pdflatex", "p"), ("xelatex", "p"), ("lualatex", "r"),
    ("lualatex --shell-escape", "p"), ("/usr/bin/lualatex", "p"), ("unknown", "p"),
])
def test_compiler_specific_read_policy_preserves_minimal_environment(monkeypatch, compiler, read_mode):
    monkeypatch.setenv("DODO_API_KEY", "synthetic-canary-only")
    monkeypatch.setenv("DATABASE_URL", "synthetic-canary-only")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-canary-only")
    monkeypatch.setenv("LATEXY_PRIVATE_CANARY", "synthetic-canary-only")
    env = ls.engine_env(compiler)
    assert env["openin_any"] == read_mode
    assert env["openout_any"] == "p"
    assert env["shell_escape"] == "f"
    assert all(name not in env for name in ("DODO_API_KEY", "DATABASE_URL", "OPENAI_API_KEY", "LATEXY_PRIVATE_CANARY"))
    assert ls.engine_env()["openin_any"] == "p"
    docker_args = ls.docker_sandbox_args(compiler)
    assert f"openin_any={read_mode}" in docker_args
    assert "openout_any=p" in docker_args and "shell_escape=f" in docker_args
    assert "no-new-privileges" in docker_args and "ALL" in docker_args
    assert docker_args[docker_args.index("--network") + 1] == "none"


class _Stream:
    def __init__(self, output):
        self.output = output.encode()

    def read(self, size=-1):
        chunk, self.output = self.output[:size], self.output[size:]
        return chunk


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["_compile_local", "_compile_with_docker"])
@pytest.mark.parametrize("return_code", [0, 1])
async def test_legacy_compiler_never_releases_diagnostics_without_recorder(tmp_path, method, return_code):
    from app.services import latex_compiler as legacy

    marker = "OWNED-ENGINE-CANARY-NOT-A-CREDENTIAL"
    compiler = object.__new__(legacy.LaTeXCompiler)
    compiler.latex_command = "pdflatex"
    compiler.docker_image = "synthetic-test-image"
    process = MagicMock(returncode=return_code)
    with (
        patch.object(legacy, "assert_local_engine_allowed"),
        patch.object(legacy.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)),
        patch.object(legacy, "capture_process_output_bounded", AsyncMock(return_value=f"! {marker}")),
        patch.object(legacy, "find_recorder_read_escape", REAL_RECORDER_CHECK),
        patch.object(legacy, "cleanup_docker_container_async", AsyncMock()),
    ):
        result = await getattr(compiler, method)(tmp_path, 30)
    assert result == (False, ls.ENGINE_UNVERIFIED_OUTPUT_ERROR)
    assert marker not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("return_code", [0, 1])
async def test_legacy_service_never_returns_log_file_without_recorder(tmp_path, return_code):
    marker = "OWNED-ENGINE-CANARY-NOT-A-CREDENTIAL"
    job_id = str(uuid4())
    process = MagicMock(returncode=return_code)

    async def capture(_process):
        (tmp_path / job_id / "resume.log").write_text(f"! {marker}")
        (tmp_path / job_id / "resume.pdf").write_bytes(b"%PDF synthetic unverified")
        return marker

    with (
        patch.object(ls.settings, "TEMP_DIR", tmp_path),
        patch.object(ls, "docker_engine_available", return_value=False),
        patch.object(ls, "assert_local_engine_allowed"),
        patch.object(ls.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)),
        patch.object(ls, "capture_process_output_bounded", capture),
        patch.object(ls, "find_recorder_read_escape", REAL_RECORDER_CHECK),
    ):
        result = await ls.LaTeXService().compile_latex(
            r"\documentclass{article}\begin{document}Example\end{document}", job_id=job_id,
        )
    assert result.success is False
    assert result.message == ls.ENGINE_UNVERIFIED_OUTPUT_ERROR
    assert marker not in repr(result)


@pytest.mark.parametrize("return_code", [0, 1])
@pytest.mark.parametrize("recorder_case", ["private_read", "missing", "tampered"])
def test_worker_releases_no_typeout_or_error_canary_before_recorder_validation(tmp_path, return_code, recorder_case):
    # Standalone engine proofs do not load the application's conftest first.
    # Initialize Celery registration before importing an individual task module.
    import_module("app.core.celery_app")
    from app.workers import latex_worker as worker

    marker = "OWNED-ENGINE-CANARY-NOT-A-CREDENTIAL"
    job_id = str(uuid4())
    events = []
    queue = MagicMock()
    queue.exists.return_value = False
    queue.get.return_value = None

    def popen(command, **kwargs):
        assert kwargs["env"]["openin_any"] == "r"
        assert "-no-shell-escape" in command and "-recorder" in command
        if recorder_case == "private_read":
            (tmp_path / job_id / "resume.fls").write_text(f"PWD {tmp_path / job_id}\nINPUT {tmp_path / 'owned-canary.txt'}\n")
        elif recorder_case == "tampered":
            (tmp_path / job_id / "resume.fls").write_bytes(b"\x00tampered")
        process = MagicMock()
        process.stdout = _Stream(f"{marker}\n! {marker}\n")
        process.returncode = return_code
        process.wait.return_value = return_code
        return process

    with (
        patch.object(worker.settings, "TEMP_DIR", tmp_path),
        patch.object(worker, "docker_engine_available", return_value=False),
        patch.object(worker, "get_worker_redis", return_value=queue),
        patch.object(worker, "admit_worker", return_value=True),
        patch.object(worker, "restore_compile_cache", return_value=None),
        patch.object(worker.subprocess, "Popen", side_effect=popen),
        patch.object(worker, "is_cancelled", return_value=False),
        patch.object(worker, "publish_event", side_effect=lambda *args: events.append(args)),
        patch.object(worker, "publish_job_result", return_value=True) as results,
        patch.object(worker, "find_recorder_read_escape", REAL_RECORDER_CHECK),
        patch.object(worker, "reconcile_compilation_record") as reconciliation,
        patch.object(worker, "cache_compile_log") as cached_log,
        patch.object(worker, "cache_compile_output") as cached_pdf,
        patch.object(worker, "_extract_pdf_text") as extracted_text,
    ):
        result = worker.compile_latex_task(
            r"\documentclass{article}\begin{document}Example\end{document}", job_id=job_id, compiler="lualatex",
        )
    assert result["success"] is False
    assert result["error"] == (ls.ENGINE_UNVERIFIED_OUTPUT_ERROR if recorder_case == "missing" else ls.ENGINE_READ_ESCAPE_ERROR)
    assert "latex_error_line" not in result
    assert marker not in repr(events) + repr(results.call_args_list) + repr(reconciliation.call_args_list) + repr(cached_log.call_args_list)
    cached_pdf.assert_not_called()
    extracted_text.assert_not_called()


@pytest.mark.skipif(shutil.which("lualatex") is None, reason="Actual LuaTeX engine is not installed on this host")
@pytest.mark.parametrize("case", ["benign", "typeout", "typeout_then_error", "luaio_typeout", "luaio_typeout_then_error"])
def test_actual_lualatex_outputs_only_after_recorder_validation(tmp_path, monkeypatch, case, warm_trusted_lualatex_font_cache):
    from app.workers import orchestrator as orch

    marker = "OWNED-ENGINE-CANARY-NOT-A-CREDENTIAL"
    canary = tmp_path / "owned-canary.txt"
    canary.write_text(marker + "\n")
    source = r"\documentclass{article}\begin{document}Safe résumé example\end{document}"
    if case.startswith("luaio_"):
        source = (
            r"\documentclass{article}\begin{document}"
            r"\expandafter\csname directl\string ua\endcsname{"
            r"local f=io.open([[" + canary.as_posix() + r"]]);texio.write_nl(f:read('*a'));f:close()}"
            + (r"\UndefinedCanaryCommand" if case.endswith("then_error") else "")
            + r"\end{document}"
        )
        assert orch.latex_service.validate_latex_content(source)
    elif case != "benign":
        source = (
            r"\documentclass{article}\begin{document}\newread\rr"
            r"\expandafter\csname openi\string n\endcsname\rr=" + canary.as_posix() + "\n"
            r"\read\rr to \zz\typeout{\zz}\zz"
            + (r"\UndefinedCanaryCommand" if case == "typeout_then_error" else "")
            + r"\end{document}"
        )
        # Deliberately exercise the engine boundary beyond the source denylist.
        assert orch.latex_service.validate_latex_content(source)
    monkeypatch.setattr(orch.settings, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(orch, "docker_engine_available", lambda: False)
    monkeypatch.setattr(orch, "assert_local_engine_allowed", lambda _job: None)
    monkeypatch.setattr(orch, "is_cancelled", lambda _job: False)
    events, logs, artifacts, commands, recorder_checks = [], [], [], [], []
    monkeypatch.setattr(orch, "publish_event", lambda *args: events.append(args))
    monkeypatch.setattr(orch, "cache_compile_log", lambda *args: logs.append(args))
    monkeypatch.setattr(orch, "record_compile", lambda *_args, **_kwargs: None)

    def cache_pdf(job_id, directory):
        data = (directory / "resume.pdf").read_bytes()
        artifacts.append((job_id, data))
        return data

    monkeypatch.setattr(orch, "cache_compile_output", cache_pdf)
    original_popen = subprocess.Popen

    def engine(command, **kwargs):
        commands.append((command, kwargs["env"]))
        return original_popen(command, **kwargs)

    monkeypatch.setattr(orch.subprocess, "Popen", engine)

    def recorder(fls_file, workspace, **kwargs):
        # Keep the real recorder check even in the shared suite's mock-friendly
        # fixture; retain evidence before the stage removes its workspace.
        outcome = REAL_RECORDER_CHECK(fls_file, workspace, **kwargs)
        recorder_checks.append(outcome)
        evidence = tmp_path / "engine-evidence"
        evidence.mkdir(exist_ok=True)
        if fls_file.exists():
            shutil.copyfile(fls_file, evidence / f"{case}.fls")
        return outcome

    monkeypatch.setattr(orch, "find_recorder_read_escape", recorder)
    result = orch._run_latex_stage(str(uuid4()), source, compiler="lualatex", timeout_seconds=30)
    assert commands and commands[0][1]["openin_any"] == "r"
    assert "-no-shell-escape" in commands[0][0] and "-recorder" in commands[0][0]
    if case == "benign":
        assert result[0] is True, result[2]
        assert result[4].startswith(b"%PDF")
        assert recorder_checks == [None]
        assert artifacts and any(event[1] == "log.line" for event in events)
    else:
        assert result[0] is False
        assert result[2] == ls.ENGINE_READ_ESCAPE_ERROR
        assert result[3] is None and result[4] is None
        assert recorder_checks == [str(canary)]
        assert not artifacts and not logs
        assert marker not in repr(events)
        assert not any(event[1] == "log.line" for event in events)

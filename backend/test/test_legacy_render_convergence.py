"""Legacy async compilation shares convergence and owns cancelled thread work."""
import asyncio
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from app.services import latex_service as service_module


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="real engine unavailable")
@pytest.mark.asyncio
async def test_legacy_compile_resolves_reference_with_common_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module.settings, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(service_module, "docker_engine_available", lambda: False)
    monkeypatch.setattr(service_module, "assert_local_engine_allowed", lambda job: None)
    monkeypatch.setattr(service_module, "get_compile_timeout", lambda plan: 30)
    source = (r"\documentclass{article}\begin{document}Reference: \ref{sec:one}."
              r"\section{Section}\label{sec:one}\end{document}")
    result = await service_module.LaTeXService().compile_latex(source, job_id="legacy-reference-proof")
    assert result.success is True, result.message
    text = subprocess.check_output(["pdftotext", str(tmp_path / "legacy-reference-proof/resume.pdf"), "-"], timeout=10).decode()
    assert "Reference: 1." in text
    assert "??" not in text


@pytest.mark.asyncio
async def test_legacy_cancellation_waits_for_convergence_before_cleanup(tmp_path, monkeypatch):
    from app.services.render_engine import passes
    entered, stopped = threading.Event(), threading.Event()
    monkeypatch.setattr(service_module.settings, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(service_module, "docker_engine_available", lambda: False)
    monkeypatch.setattr(service_module, "assert_local_engine_allowed", lambda job: None)
    monkeypatch.setattr(service_module, "find_recorder_read_escape", lambda *args, **kwargs: None)
    async def spawn(*args, **kwargs):
        (tmp_path / "legacy-cancel/resume.pdf").write_bytes(b"%PDF-fixture")
        return SimpleNamespace(returncode=0)
    async def capture(process):
        return "Rerun to get cross-references right"
    def converge(**kwargs):
        entered.set()
        while not kwargs["is_cancelled"]():
            time.sleep(.01)
        time.sleep(.05)
        stopped.set()
        raise passes.RenderPassError("cancelled")
    monkeypatch.setattr(service_module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(service_module, "capture_process_output_bounded", capture)
    monkeypatch.setattr(passes, "converge", converge)
    service = service_module.LaTeXService()
    cleanup = service.cleanup_temp_files
    def checked_cleanup(directory):
        assert stopped.is_set(), "Workspace deleted while convergence thread still owned it"
        cleanup(directory)
    monkeypatch.setattr(service, "cleanup_temp_files", checked_cleanup)
    task = asyncio.create_task(service.compile_latex(r"\documentclass{article}x", job_id="legacy-cancel"))
    for _ in range(500):
        if entered.is_set():
            break
        await asyncio.sleep(.01)
    assert entered.is_set()
    task.cancel()
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
    assert not (tmp_path / "legacy-cancel").exists()

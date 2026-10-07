"""Execution/session binding at the actual renderer entry points."""
import io
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.render_engine import backend, passes
from app.services.render_engine.backend import RendererBackend
from app.utils.bounded_io import BoundedTranscript
from app.workers import latex_worker, orchestrator

VM = RendererBackend("modal_vm", "modal-vm-assets:verified", "lua-credential-free-vm-v1", "im-test", "a" * 64)


class Session:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Process:
    def __init__(self, session, log):
        self.renderer_session = session
        self.remote_workspace = "/workspace"
        self.returncode = 0
        self.stdout = io.BytesIO(log)

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self.renderer_session.close()


def test_cache_identity_uses_selected_backend_and_rejects_mutable_image(monkeypatch):
    source = r"\documentclass{article}\begin{document}Hello\end{document}"
    monkeypatch.setattr(backend, "resolve_backend", lambda compiler: RendererBackend("native", "native-assets", "native-policy"))
    native = latex_worker.compile_cache_key(source, "lualatex", {}, "user:one")
    monkeypatch.setattr(backend, "resolve_backend", lambda compiler: VM)
    assert latex_worker.compile_cache_key(source, "lualatex", {}, "user:one") != native
    monkeypatch.setattr(backend, "resolve_backend", lambda compiler: RendererBackend("docker", "mutable-reference", "policy", cacheable=False))
    assert latex_worker.compile_cache_key(source, "lualatex", {}, "user:one") is None


@pytest.mark.parametrize("bibliography", [False, True])
def test_convergence_reuses_original_vm_session_for_every_engine(tmp_path, monkeypatch, bibliography):
    session, calls, processes = Session(), [], []
    (tmp_path / "resume.fls").write_text("INPUT /workspace/resume.tex\n")
    if bibliography:
        (tmp_path / "resume.aux").write_text(r"\citation{sample}\bibstyle{plain}\bibdata{references}")
        (tmp_path / "references.bib").write_text("@article{sample,title={Example}}")
    def start(command, **kwargs):
        calls.append(kwargs)
        assert kwargs["engine_session"] is session
        if kwargs["actual_engine"] == "bibtex":
            (tmp_path / "resume.bbl").write_text(r"\begin{thebibliography}{1}\bibitem{sample}Example.\end{thebibliography}")
        proc = Process(session, b"Output written on resume.pdf (1 page)\n")
        processes.append(proc)
        return proc
    monkeypatch.setattr(backend, "start_engine_process", start)
    transcript = BoundedTranscript()
    transcript.append("Rerun to get cross-references right")
    result = passes.converge(job_id="session-test", job_dir=tmp_path, command=["lualatex", "resume.tex"],
        cwd=str(tmp_path), workspace="/workspace", compiler="lualatex", timeout=10,
        started_at=time.time(), transcript=transcript, is_cancelled=lambda: False,
        publisher=lambda *args: None, container_name=None, engine_backend=VM, engine_session=session)
    assert result == 1
    assert [call["actual_engine"] for call in calls] == (["bibtex", "lualatex", "lualatex"] if bibliography else ["lualatex"])
    assert not session.closed, "Outer render retains ownership until artifact delivery"
    assert all(proc.stdout.closed for proc in processes)


def test_vm_convergence_without_owned_session_fails_closed(tmp_path, monkeypatch):
    start = Mock()
    monkeypatch.setattr(backend, "start_engine_process", start)
    transcript = BoundedTranscript()
    transcript.append("Rerun to get cross-references right")
    with pytest.raises(passes.RenderPassError, match="session unavailable"):
        passes.converge(job_id="missing-session", job_dir=tmp_path, command=["lualatex", "resume.tex"],
            cwd=str(tmp_path), workspace="/workspace", compiler="lualatex", timeout=10,
            started_at=time.time(), transcript=transcript, is_cancelled=lambda: False,
            publisher=lambda *args: None, container_name=None, engine_backend=VM)
    start.assert_not_called()


@pytest.mark.parametrize("escape,invalid_output", [(False, False), (True, False), (False, True)])
def test_combined_stage_uses_vm_and_closes_after_confinement(tmp_path, monkeypatch, escape, invalid_output):
    session, calls, logs = Session(), [], []
    monkeypatch.setattr(orchestrator, "settings", SimpleNamespace(ALLOWED_LATEX_COMPILERS=["lualatex"],
        DEFAULT_LATEX_COMPILER="lualatex", TEMP_DIR=str(tmp_path), COMPILE_TIMEOUT=10))
    monkeypatch.setattr(backend, "resolve_backend", lambda compiler: VM)
    native = Mock(side_effect=AssertionError("VM dispatch cannot invoke native launcher"))
    monkeypatch.setattr(orchestrator, "native_engine_command", native)
    monkeypatch.setattr(orchestrator, "assert_local_engine_allowed", native)
    monkeypatch.setattr(orchestrator, "publish_event", lambda job, kind, data: logs.append((kind, data)))
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda job: False)
    monkeypatch.setattr(orchestrator, "cache_compile_log", lambda *args: None)
    cache = Mock(return_value=b"%PDF-verified-fixture")
    if invalid_output:
        from app.utils.bounded_io import UntrustedFileError

        cache.side_effect = UntrustedFileError("synthetic output link")
    monkeypatch.setattr(orchestrator, "cache_compile_output", cache)
    def start(command, **kwargs):
        calls.append(kwargs)
        directory = tmp_path / "vm-stage-test"
        (directory / "resume.fls").write_text("INPUT " + ("/etc/private-credentials" if escape else "/workspace/resume.tex") + "\n")
        (directory / "resume.pdf").write_bytes(b"%PDF-verified-fixture")
        return Process(session, b"PRIVATE_LOG_SENTINEL\nOutput written on resume.pdf (1 page)\n")
    monkeypatch.setattr(backend, "start_engine_process", start)
    result = orchestrator._run_latex_stage("vm-stage-test", r"\documentclass{article}\begin{document}Hello\end{document}", compiler="lualatex")
    assert calls[0]["backend"] is VM
    assert session.closed
    assert not (tmp_path / "vm-stage-test").exists()
    native.assert_not_called()
    assert result[0] is (not escape and not invalid_output)
    if invalid_output:
        assert "outside" in result[2]
    if escape:
        assert "outside" in result[2]
        cache.assert_not_called()
        assert not any(kind == "log.line" for kind, _ in logs)
    else:
        cache.assert_called_once()


def test_combined_vm_cancellation_terminates_session_and_withholds_logs(tmp_path, monkeypatch):
    session, terminated = Session(), threading.Event()
    class Silent(Process):
        def __init__(self):
            super().__init__(session, b"")
            self.returncode = None
            self.stdout = self
        def read(self, size):
            assert terminated.wait(3), "Cancellation watchdog did not stop the VM"
            return b""
        def wait(self, timeout=None):
            assert terminated.wait(3)
            return self.returncode
        def kill(self):
            super().kill()
            terminated.set()
        def close(self):
            pass
    monkeypatch.setattr(orchestrator, "settings", SimpleNamespace(ALLOWED_LATEX_COMPILERS=["lualatex"],
        DEFAULT_LATEX_COMPILER="lualatex", TEMP_DIR=str(tmp_path), COMPILE_TIMEOUT=10))
    monkeypatch.setattr(backend, "resolve_backend", lambda compiler: VM)
    monkeypatch.setattr(backend, "start_engine_process", lambda *args, **kwargs: Silent())
    monkeypatch.setattr(orchestrator, "publish_event", lambda *args: None)
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda job: True)
    cache = Mock()
    monkeypatch.setattr(orchestrator, "cache_compile_output", cache)
    result = orchestrator._run_latex_stage("vm-cancel-test", r"\documentclass{article}\begin{document}Hello\end{document}", compiler="lualatex")
    assert result[0] is False and result[2] == "cancelled"
    assert session.closed and terminated.is_set()
    cache.assert_not_called()

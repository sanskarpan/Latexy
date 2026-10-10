"""Benign compiler diagnostics publish once, after each pass is verified."""

import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.render_engine import backend, passes
from app.services.render_engine.backend import RendererBackend
from app.workers import orchestrator


@pytest.mark.parametrize("compiler", ["pdflatex", "xelatex", "lualatex"])
def test_each_successful_pass_publishes_diagnostics_once_after_validation(tmp_path, monkeypatch, compiler):
    job_id = "verified-pass-logging"
    current_pass = 0
    verified_pass = 0
    lines = []
    monkeypatch.setattr(orchestrator, "settings", SimpleNamespace(
        ALLOWED_LATEX_COMPILERS=[compiler], DEFAULT_LATEX_COMPILER=compiler,
        TEMP_DIR=str(tmp_path), COMPILE_TIMEOUT=10,
    ))
    monkeypatch.setattr(backend, "resolve_backend", lambda _: RendererBackend("native", "test-renderer", None))
    monkeypatch.setattr(orchestrator, "assert_local_engine_allowed", lambda _: None)
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda _: False)
    monkeypatch.setattr(orchestrator, "cache_compile_log", lambda *_: None)
    monkeypatch.setattr(orchestrator, "cache_compile_output", lambda *_args, **_kwargs: b"%PDF-test")
    monkeypatch.setattr(orchestrator, "record_compile", lambda *_args, **_kwargs: None)

    def start(_command, **_kwargs):
        nonlocal current_pass
        current_pass += 1
        (tmp_path / job_id / "resume.pdf").write_bytes(b"%PDF-test")
        output = f"Pass {current_pass}\nOutput written on resume.pdf (1 page)\n"
        if current_pass == 1:
            output += "Rerun to get cross-references right\n"
        return MagicMock(stdout=io.BytesIO(output.encode()), returncode=0,
                         wait=MagicMock(return_value=0), poll=MagicMock(return_value=0),
                         renderer_session=None)

    def verify(_recorder, _workspace, *, require_recorder):
        nonlocal verified_pass
        assert require_recorder is True
        verified_pass = current_pass
        return None

    def publish(_job_id, event, payload):
        if event == "log.line":
            assert verified_pass == current_pass
            lines.append(payload["line"])

    monkeypatch.setattr(backend, "start_engine_process", start)
    monkeypatch.setattr(orchestrator, "find_recorder_read_escape", verify)
    monkeypatch.setattr(passes, "find_recorder_read_escape", verify)
    monkeypatch.setattr(orchestrator, "publish_event", publish)
    result = orchestrator._run_latex_stage(
        job_id, r"\documentclass{article}\begin{document}Example\end{document}", compiler=compiler,
    )
    assert result[0] is True, result[2]
    assert current_pass == verified_pass == 2
    assert lines == ["Pass 1", "Output written on resume.pdf (1 page)",
                     "Rerun to get cross-references right", "Pass 2", "Output written on resume.pdf (1 page)"]

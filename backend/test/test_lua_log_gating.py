"""A recorder-detected Lua read cannot leak earlier stdout to event clients."""
import io
from unittest.mock import MagicMock

from app.workers import orchestrator


def test_lua_stdout_is_withheld_when_recorder_fails(tmp_path, monkeypatch):
    settings = MagicMock(ALLOWED_LATEX_COMPILERS=["lualatex"], DEFAULT_LATEX_COMPILER="lualatex",
                         TEMP_DIR=str(tmp_path), COMPILE_TIMEOUT=10)
    monkeypatch.setattr(orchestrator, "settings", settings)
    monkeypatch.setattr(orchestrator, "docker_engine_available", lambda: False)
    monkeypatch.setattr(orchestrator, "assert_local_engine_allowed", lambda _: None)
    monkeypatch.setattr(orchestrator, "engine_env", lambda *args: {})
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda _: False)
    events = []
    monkeypatch.setattr(orchestrator, "publish_event", lambda job, kind, data: events.append((kind, data)))
    cached = MagicMock()
    monkeypatch.setattr(orchestrator, "cache_compile_log", cached)
    def spawn(*args, **kwargs):
        directory = tmp_path / "lua-test"
        (directory / "resume.pdf").write_bytes(b"%PDF-unverified")
        (directory / "resume.fls").write_text("INPUT /etc/private-credentials\n", encoding="utf-8")
        return MagicMock(stdout=io.BytesIO(b"PRIVATE_CREDENTIAL_VALUE\nOutput written on resume.pdf (1 page)\n"),
                         returncode=0, wait=MagicMock(return_value=0), poll=MagicMock(return_value=0))
    monkeypatch.setattr(orchestrator.subprocess, "Popen", spawn)
    result = orchestrator._run_latex_stage("lua-test", r"\documentclass{article}\begin{document}Hello\end{document}", compiler="lualatex")
    assert result[0] is False
    assert "outside" in result[2]
    assert not any(kind == "log.line" for kind, _ in events)
    cached.assert_not_called()

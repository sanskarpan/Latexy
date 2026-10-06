"""Combined compilation must honor the direct compiler's safe input contract."""

import base64
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.workers import orchestrator
from app.workers.latex_worker import _inject_packages

SOURCE = r"\documentclass{article}\begin{document}Hello\end{document}"


@pytest.fixture
def compile_probe(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(orchestrator.settings, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(orchestrator, "assert_local_engine_allowed", lambda *_: None)
    monkeypatch.setattr(orchestrator, "is_cancelled", lambda *_: False)
    monkeypatch.setattr(orchestrator, "publish_event", lambda *_: None)
    monkeypatch.setattr(orchestrator, "cache_compile_log", lambda *_: None)
    monkeypatch.setattr(orchestrator, "record_compile", lambda *_, **__: None)
    monkeypatch.setattr(orchestrator, "find_recorder_read_escape", lambda *_, **__: None)
    watchdog = MagicMock()
    watchdog.start.return_value = watchdog
    watchdog.stop.return_value = None
    monkeypatch.setattr(orchestrator, "ProcessWatchdog", lambda *_, **__: watchdog)

    def spawn(command, **kwargs):
        job_dir = tmp_path / "combined-settings"
        captured["command"] = command
        captured["kwargs"] = kwargs
        captured["files"] = {path.name: path.read_bytes() for path in job_dir.iterdir()}
        return SimpleNamespace(stdout=io.BytesIO(b"! controlled test failure\n"), returncode=1, wait=lambda: None)

    monkeypatch.setattr(orchestrator.subprocess, "Popen", spawn)
    return captured


@pytest.mark.parametrize("docker", [False, True])
def test_combined_settings_reach_engine_and_keep_artifact_names(compile_probe, monkeypatch, docker):
    monkeypatch.setattr(orchestrator, "docker_engine_available", lambda: docker)
    orchestrator._run_latex_stage(
        "combined-settings", SOURCE, main_file="letter.tex", extra_packages=["xcolor"],
        latexmk_flags=["--file-line-error", "--shell-escape"], draft_mode=True,
        halt_on_error=False,
    )
    command = compile_probe["command"]
    assert command[-1] == "letter.tex"
    assert command[command.index("-jobname") + 1] == "resume"
    assert "--file-line-error" in command
    assert "--shell-escape" not in command
    assert "-no-shell-escape" in command
    assert "-halt-on-error" not in command
    source = compile_probe["files"]["letter.tex"].decode()
    assert r"\usepackage{xcolor}" in source
    assert r"\PassOptionsToPackage{draft}{graphicx}" in source


@pytest.mark.parametrize("filename", ["../escape.tex", "valid.tex\n", "/tmp/escape.tex"])
def test_combined_filename_validation_cannot_escape_workspace(compile_probe, monkeypatch, filename):
    monkeypatch.setattr(orchestrator, "docker_engine_available", lambda: False)
    orchestrator._run_latex_stage("combined-settings", SOURCE, main_file=filename)
    assert compile_probe["command"][-1] == "resume.tex"
    assert "resume.tex" in compile_probe["files"]


def test_combined_materializes_embedded_signature_before_engine_start(compile_probe, monkeypatch):
    monkeypatch.setattr(orchestrator, "docker_engine_available", lambda: False)
    image = io.BytesIO()
    Image.new("RGBA", (2, 2), "black").save(image, format="PNG")
    payload = base64.b64encode(image.getvalue()).decode()
    source = SOURCE.replace(
        r"\end{document}",
        "\n% LATEXY_SIGNATURE_START\n% LATEXY_SIGNATURE_DATA:" + payload
        + "\n\\includegraphics{latexy-signature.png}\n% LATEXY_SIGNATURE_END\n\\end{document}",
    )
    orchestrator._run_latex_stage("combined-settings", source)
    assert compile_probe["files"]["latexy-signature.png"].startswith(b"\x89PNG")


def test_package_injection_handles_single_line_documents_and_rejects_tex_payloads():
    source = _inject_packages(SOURCE, ["xcolor", "xcolor", "evil}\\input{/etc/passwd", None])
    assert source.count(r"\usepackage{xcolor}") == 1
    assert "passwd" not in source
    assert source.index(r"\usepackage{xcolor}") < source.index(r"\begin{document}")


@pytest.mark.parametrize(
    "existing_package",
    [
        r"\usepackage[table]{xcolor}",
        r"\usepackage {xcolor}",
        r"\usepackage{xcolor,booktabs}",
        r"\RequirePackage{xcolor}",
    ],
)
def test_package_injection_recognizes_existing_package_variants(existing_package):
    source = SOURCE.replace(r"\begin{document}", existing_package + r"\begin{document}")
    result = _inject_packages(source, ["xcolor"])
    assert result.count("xcolor") == 1

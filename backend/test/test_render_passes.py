"""Real sandbox-policy TeX convergence and bounded auxiliary snapshots."""
import shutil
import subprocess
import time
from unittest.mock import MagicMock

import pytest

from app.services.latex_service import LATEX_SANDBOX_FLAGS, engine_env, find_recorder_read_escape
from app.services.render_engine.auxiliary import AuxiliaryWorkspace
from app.services.render_engine.passes import RenderPassError, converge
from app.utils.bounded_io import BoundedTranscript


def test_auxiliary_snapshot_never_restores_executable_macros():
    raw = (b"\\newlabel{safe}{{1.2}{3}}\n\\newlabel{bad}{{\\directlua{evil}}{3}}\n"
           b"\\input{/secret}\n\\@writefile{toc}{arbitrary}\n")
    assert AuxiliaryWorkspace.sanitize(raw) == b"\\relax\n\\newlabel{safe}{{1.2}{3}}\n"
    assert AuxiliaryWorkspace.sanitize(b"x" * 40000) == b"\\relax\n"


def test_auxiliary_busy_lease_uses_fresh_workspace(tmp_path):
    redis = MagicMock()
    redis.set.return_value = False
    workspace = AuxiliaryWorkspace(redis, tmp_path, {"document_id": "resume", "owner_scope": "user:one",
        "render_source": r"preamble\begin{document}body", "compiler": "pdflatex", "engine_fingerprint": "test", "settings": {}}, 60)
    assert workspace.loaded is False
    assert workspace.lease is None
    redis.get.assert_not_called()


@pytest.mark.skipif(not shutil.which("pdflatex"), reason="real TeX engine unavailable")
@pytest.mark.parametrize("bibliography", [False, True])
def test_real_tex_reference_and_classic_bibliography_converge(tmp_path, bibliography):
    source = (r"\documentclass{article}\begin{document}Reference: \ref{sec:one}."
              r"\section{Section}\label{sec:one}")
    if bibliography:
        source += r" Citation: \cite{sample}.\bibliographystyle{plain}\bibliography{references}"
        (tmp_path / "references.bib").write_text('@article{sample,title={Verified Title},author={Example, Ada},journal={Journal},year={2025}}', encoding="utf-8")
    source += r"\end{document}"
    (tmp_path / "resume.tex").write_text(source, encoding="utf-8")
    cmd = ["pdflatex", *LATEX_SANDBOX_FLAGS, "-interaction=nonstopmode", "-halt-on-error", "-jobname", "resume", "resume.tex"]
    started = time.time()
    first = subprocess.run(cmd, cwd=tmp_path, env=engine_env(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    assert first.returncode == 0, first.stdout[-4000:]
    assert find_recorder_read_escape(tmp_path / "resume.fls", str(tmp_path), require_recorder=True) is None
    transcript = BoundedTranscript()
    for line in first.stdout.decode(errors="replace").splitlines():
        transcript.append(line)
    events = []
    pages = converge(job_id="internal-test", job_dir=tmp_path, command=cmd, cwd=str(tmp_path),
        workspace=str(tmp_path), compiler="pdflatex", timeout=15, started_at=started,
        transcript=transcript, is_cancelled=lambda: False,
        publisher=lambda job, kind, payload: events.append(payload), container_name=None)
    assert pages == 1
    extracted = subprocess.check_output(["pdftotext", str(tmp_path / "resume.pdf"), "-"], timeout=3).decode()
    assert "Reference: 1." in extracted
    if bibliography:
        assert "Verified Title" in extracted or "Verified title" in extracted
        assert "[1]" in extracted


def test_biber_is_explicit_unsupported_adapter(tmp_path):
    (tmp_path / "resume.bcf").write_text("untrusted datasources", encoding="utf-8")
    with pytest.raises(RenderPassError, match="Biber"):
        converge(job_id="job", job_dir=tmp_path, command=["pdflatex"], cwd=str(tmp_path),
            workspace=str(tmp_path), compiler="pdflatex", timeout=10, started_at=time.time(),
            transcript=BoundedTranscript(), is_cancelled=lambda: False, publisher=MagicMock(), container_name=None)

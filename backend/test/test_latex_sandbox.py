"""
LaTeX engine sandboxing tests.

The denylist in validate_latex_content() is defence in depth only; the primary
control is how the engine is invoked. These tests pin that invocation:

  * -no-shell-escape on every command (Docker and local)
  * docker run hardening flags (no network, no caps, no new privileges)
  * a minimal subprocess environment that never leaks worker credentials
  * the local (unsandboxed) engine is opt-in and logged, never silent
  * the combined/orchestrator path runs the same content validation as the
    direct latex_compilation path
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services import latex_service as ls
from app.services.latex_service import find_recorder_read_escape as real_find_recorder

# real_find_recorder is bound at import time, so it survives the conftest fixture that
# relaxes the fail-closed "no recorder file" rule for the mocked-subprocess unit tests.

# ── Invocation hardening ──────────────────────────────────────────────────────

class TestSandboxFlags:

    def test_shell_escape_is_disabled(self):
        assert "-no-shell-escape" in ls.LATEX_SANDBOX_FLAGS

    def test_recorder_is_enabled(self):
        # Without -recorder there is no .fls file, and \openin reads (which the
        # transcript never mentions) become invisible.
        assert "-recorder" in ls.LATEX_SANDBOX_FLAGS

    def test_docker_args_confine_the_container(self):
        args = ls.docker_sandbox_args()
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--security-opt") + 1] == "no-new-privileges"
        assert args[args.index("--cap-drop") + 1] == "ALL"

    def test_docker_args_set_kpathsea_policy(self):
        args = ls.docker_sandbox_args()
        assert "openout_any=p" in args
        assert "openin_any=p" in args
        assert "shell_escape=f" in args


class TestEngineEnv:

    def test_worker_credentials_are_not_inherited(self):
        secrets = {
            "DATABASE_URL": "postgresql://u:p@host/db",
            "REDIS_URL": "redis://host:6379/0",
            "OPENAI_API_KEY": "sk-test",
            "API_KEY_ENCRYPTION_KEY": "topsecret",
        }
        with patch.dict("os.environ", secrets, clear=False):
            env = ls.engine_env()
        assert not (secrets.keys() & env.keys())

    def test_path_is_forwarded_so_the_engine_is_findable(self):
        with patch.dict("os.environ", {"PATH": "/usr/bin"}, clear=False):
            assert ls.engine_env()["PATH"] == "/usr/bin"

    def test_kpathsea_policy_is_applied(self):
        env = ls.engine_env()
        assert env["openout_any"] == "p"
        assert env["shell_escape"] == "f"


class TestLocalEngineGate:

    def test_opt_in_via_env(self):
        with patch.dict("os.environ", {"ALLOW_LOCAL_LATEX_ENGINE": "true"}, clear=False):
            assert ls.local_engine_allowed() is True

    def test_env_opt_out_wins_over_every_default(self):
        with (
            patch.dict("os.environ", {"ALLOW_LOCAL_LATEX_ENGINE": "false"}, clear=False),
            patch.object(ls, "running_in_container", return_value=True),
        ):
            assert ls.local_engine_allowed() is False

    def test_disallowed_in_production_on_a_bare_host(self):
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(ls.settings, "ENVIRONMENT", "production"),
            patch.object(ls, "running_in_container", return_value=False),
        ):
            import os
            os.environ.pop("ALLOW_LOCAL_LATEX_ENGINE", None)
            assert ls.local_engine_allowed() is False

    def test_production_worker_container_may_use_its_in_image_engine(self):
        """Regression: the gate used to brick every prod compile.

        backend/Dockerfile.prod bakes texlive into the worker image and ships no
        docker CLI and no /var/run/docker.sock, so docker_engine_available() is
        False there while ENVIRONMENT is "production". That topology must compile.
        """
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(ls.settings, "ENVIRONMENT", "production"),
            patch.object(ls, "running_in_container", return_value=True),
            patch.object(ls.shutil, "which", return_value=None),
        ):
            import os
            os.environ.pop("ALLOW_LOCAL_LATEX_ENGINE", None)
            assert ls.docker_engine_available() is False
            assert ls.local_engine_allowed() is True
            ls.assert_local_engine_allowed("job-1")  # must not raise

    def test_container_detection_reads_dockerenv(self):
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(ls.Path, "exists", return_value=True),
        ):
            import os
            os.environ.pop("KUBERNETES_SERVICE_HOST", None)
            assert ls.running_in_container() is True

    def test_allowed_in_development_by_default(self):
        with (
            patch.object(ls.settings, "ENVIRONMENT", "development"),
            patch.object(ls, "running_in_container", return_value=False),
        ):
            import os
            os.environ.pop("ALLOW_LOCAL_LATEX_ENGINE", None)
            assert ls.local_engine_allowed() is True

    def test_assert_raises_a_generic_message_and_logs_the_ops_detail(self):
        with (
            patch.object(ls, "local_engine_allowed", return_value=False),
            patch.object(ls.logger, "error") as err,
        ):
            with pytest.raises(RuntimeError) as excinfo:
                ls.assert_local_engine_allowed("job-1")
        # The message is echoed to the API caller, so it must not leak ops config…
        assert "ALLOW_LOCAL_LATEX_ENGINE" not in str(excinfo.value)
        assert str(excinfo.value) == ls.ENGINE_UNAVAILABLE_ERROR
        # …while the operator still gets the remedy in the logs.
        assert "ALLOW_LOCAL_LATEX_ENGINE" in err.call_args.args[0]

    def test_assert_logs_when_falling_back(self):
        with (
            patch.object(ls, "local_engine_allowed", return_value=True),
            patch.object(ls.logger, "warning") as warn,
        ):
            ls.assert_local_engine_allowed("job-1")
        assert warn.called
        assert "in-process" in warn.call_args.args[0]


# ── Read confinement ──────────────────────────────────────────────────────────

class TestEngineReadEscape:
    """The denylist cannot be won by string matching, so reads are policed on the
    engine's own transcript. One \\newcommand defeated the source-level guard:
    \\newcommand{\\zz}{\\input}\\zz{../../etc/hostname} compiled and the file came
    back in extracted_text."""

    @pytest.mark.parametrize("line,expected", [
        ("(/workspace/../../etc/hostname)", "/etc/hostname"),
        ("(/etc/passwd)", "/etc/passwd"),
        ("(../../etc/hostname)", "/etc/hostname"),
        ('("/etc/my secrets.txt")', "/etc/my secrets.txt"),
    ])
    def test_reads_outside_the_jail_are_detected(self, line, expected):
        assert ls.find_engine_read_escape(line, "/workspace") == expected

    @pytest.mark.parametrize("line", [
        "(/workspace/resume.aux)",
        "(./resume.aux) )",
        "(/usr/local/texlive/2026/texmf-dist/tex/latex/base/article.cls",
        "(/usr/share/texmf/tex/latex/foo.sty)",
        "Output written on /workspace/resume.pdf (1 page, 12439 bytes).",
        "Overfull \\hbox (12.0pt too wide) in paragraph at lines 10/12",
        "This is pdfTeX, Version 3.14 (TeX Live 2026)",
    ])
    def test_legitimate_lines_are_not_flagged(self, line):
        assert ls.find_engine_read_escape(line, "/workspace") is None

    def test_transcript_wrapping_is_disabled(self):
        # A 79-column wrap would split a path across two lines and hide it.
        assert ls.engine_env()["max_print_line"] == "10000"

    def test_worker_kills_the_compile_and_returns_no_content(self):
        """The escape must abort before the log line (and the PDF) reach the caller."""
        import app.workers.latex_worker as lw

        published = []
        proc = MagicMock()
        proc.stdout = iter([
            "(/workspace/resume.tex\n",
            "(/workspace/../../etc/hostname)\n",
            "c828f9c599ec\n",
            "Output written on resume.pdf (1 page, 100 bytes).\n",
        ])
        proc.returncode = 0
        proc.wait.return_value = 0

        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=proc),
            patch("app.workers.latex_worker.docker_engine_available", return_value=True),
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("app.workers.latex_worker.publish_event", side_effect=lambda j, e, p: published.append((e, p))),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
            patch("app.workers.latex_worker.cache_compile_log") as cache_log,
            patch("app.workers.latex_worker._extract_pdf_text") as extract,
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.mkdir"),
        ):
            result = lw.compile_latex_task(
                r"\documentclass{article}\begin{document}"
                r"\newcommand{\zz}{\input}\zz{../../etc/hostname}\end{document}",
                job_id=str(uuid.uuid4()),
            )

        assert result["success"] is False
        assert result["error"] == ls.ENGINE_READ_ESCAPE_ERROR
        assert "extracted_text" not in result
        extract.assert_not_called()
        proc.kill.assert_called_once()
        # Neither the offending path nor the file's contents were streamed or stored.
        streamed = [p.get("line", "") for e, p in published if e == "log.line"]
        assert not any("etc/hostname" in line or "c828f9c599ec" in line for line in streamed)
        assert "etc/hostname" not in cache_log.call_args.args[1]

    def test_orchestrator_kills_the_compile(self):
        import app.workers.orchestrator as orch

        proc = MagicMock()
        proc.stdout = iter(["(/workdir/../../etc/hostname)\n", "c828f9c599ec\n"])
        proc.returncode = 0
        proc.wait.return_value = 0

        with (
            patch("app.workers.orchestrator.subprocess.Popen", return_value=proc),
            patch("app.workers.orchestrator.docker_engine_available", return_value=True),
            patch("app.workers.orchestrator.publish_event") as pub,
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.mkdir"),
        ):
            success, _, error, page_count, pdf = orch._run_latex_stage(
                str(uuid.uuid4()),
                r"\documentclass{article}\begin{document}"
                r"\newcommand{\zz}{\input}\zz{../../etc/hostname}\end{document}",
            )

        assert success is False
        assert error == ls.ENGINE_READ_ESCAPE_ERROR
        assert page_count is None and pdf is None
        proc.kill.assert_called_once()
        assert not any(
            "etc/hostname" in str(call.args) for call in pub.call_args_list
        )


class TestRecorderReadEscape:
    r"""\openin/\read prints NOTHING in the transcript, so find_engine_read_escape
    never fires for it and openin_any=p is a no-op on TeX Live 2025+. Verified against
    the real engine: \newread\rr\expandafter\csname openi\string n\endcsname
    \rr=/etc/hostname \read\rr to \zz \zz compiled successfully with the file's
    contents in the PDF and a completely clean transcript. The -recorder .fls file is
    the only place that read shows up.
    """

    def _fls(self, tmp_path, body: str):
        fls = tmp_path / "resume.fls"
        fls.write_text(body)
        return fls

    def test_openin_read_outside_the_jail_is_detected(self, tmp_path):
        fls = self._fls(tmp_path, (
            "PWD /workspace\n"
            "INPUT /workspace/resume.tex\n"
            "INPUT /etc/hostname\n"
            "OUTPUT /workspace/resume.pdf\n"
        ))
        assert real_find_recorder(fls, "/workspace") == "/etc/hostname"

    def test_another_jobs_directory_is_detected(self, tmp_path):
        fls = self._fls(tmp_path, "PWD /workspace\nINPUT /tmp/latex_compile/other/resume.tex\n")
        assert real_find_recorder(fls, "/workspace") == "/tmp/latex_compile/other/resume.tex"

    def test_relative_traversal_is_detected(self, tmp_path):
        fls = self._fls(tmp_path, "PWD /workspace\nINPUT ../../etc/hostname\n")
        assert real_find_recorder(fls, "/workspace") == "/etc/hostname"

    def test_ordinary_compile_is_not_flagged(self, tmp_path):
        fls = self._fls(tmp_path, (
            "PWD /workspace\n"
            "INPUT /workspace/resume.tex\n"
            "INPUT sections/experience.tex\n"
            "INPUT /usr/local/texlive/2026/texmf-dist/tex/latex/base/article.cls\n"
            "OUTPUT /workspace/resume.log\n"
            "OUTPUT /workspace/resume.pdf\n"
            "INPUT /workspace/resume.aux\n"
        ))
        assert real_find_recorder(fls, "/workspace") is None

    def test_missing_recorder_file_fails_closed(self, tmp_path):
        assert real_find_recorder(tmp_path / "resume.fls", "/workspace") is not None

    def test_missing_recorder_file_tolerated_when_the_engine_never_ran(self, tmp_path):
        # `docker run` itself failing must surface as its own error, not as a
        # spurious confinement failure — there is nothing to leak.
        assert real_find_recorder(
            tmp_path / "resume.fls", "/workspace", require_recorder=False
        ) is None

    def test_recorder_file_clobbered_by_openout_is_rejected(self, tmp_path):
        """\\openout over <jobname>.fls is allowed by openout_any=p (same directory).

        Verified against the real engine: the document's write lands at offset 0 while
        kpathsea keeps appending at its own offset, so the recorded reads are replaced
        by NUL padding and the clobber records itself as an OUTPUT.
        """
        fls = tmp_path / "resume.fls"
        fls.write_bytes(
            b"PWD /workspace\n" + b"\x00" * 512 + b"OUTPUT /workspace/resume.pdf\n"
        )
        assert "overwritten" in real_find_recorder(fls, "/workspace")

    def test_document_writing_the_recorder_file_is_rejected(self, tmp_path):
        fls = self._fls(tmp_path, "PWD /workspace\nOUTPUT /workspace/resume.fls\n")
        assert "overwritten" in real_find_recorder(fls, "/workspace")

    def test_worker_publishes_nothing_when_the_recorder_shows_an_escape(self, tmp_path):
        """The transcript is clean, so only the post-run recorder check can stop this."""
        import app.workers.latex_worker as lw

        job_id = str(uuid.uuid4())
        published = []

        def _popen(cmd, **kwargs):
            # The engine would have written its recorder file by the time it exits.
            (tmp_path / job_id / "resume.fls").write_text(
                "PWD /workspace\nINPUT /workspace/resume.tex\nINPUT /etc/hostname\n"
            )
            proc = MagicMock()
            proc.stdout = iter(["(/workspace/resume.tex\n", "924acb30d9bb\n"])
            proc.returncode = 0
            proc.wait.return_value = 0
            return proc

        with (
            patch.object(lw.settings, "TEMP_DIR", tmp_path),
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=_popen),
            patch("app.workers.latex_worker.docker_engine_available", return_value=True),
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("app.workers.latex_worker.publish_event", side_effect=lambda j, e, p: published.append((e, p))),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
            patch("app.workers.latex_worker.cache_compile_log") as cache_log,
            patch("app.workers.latex_worker.cache_compile_output") as cache_pdf,
            patch("app.workers.latex_worker._extract_pdf_text") as extract,
        ):
            result = lw.compile_latex_task(
                r"\documentclass{article}\begin{document}"
                r"\newread\rr\expandafter\csname openi\string n\endcsname\rr=/etc/hostname"
                r"\read\rr to \zz \zz\end{document}",
                job_id=job_id,
            )

        assert result["success"] is False
        assert result["error"] == ls.ENGINE_READ_ESCAPE_ERROR
        assert "extracted_text" not in result
        extract.assert_not_called()
        cache_pdf.assert_not_called()
        assert "924acb30d9bb" not in cache_log.call_args.args[1]

    def test_orchestrator_returns_no_pdf_when_the_recorder_shows_an_escape(self, tmp_path):
        import app.workers.orchestrator as orch

        job_id = str(uuid.uuid4())

        def _popen(cmd, **kwargs):
            (tmp_path / job_id / "resume.fls").write_text(
                "PWD /workdir\nINPUT /workdir/resume.tex\nINPUT /etc/hostname\n"
            )
            proc = MagicMock()
            proc.stdout = iter(["(/workdir/resume.tex\n"])
            proc.returncode = 0
            proc.wait.return_value = 0
            return proc

        with (
            patch.object(orch.settings, "TEMP_DIR", tmp_path),
            patch("app.workers.orchestrator.subprocess.Popen", side_effect=_popen),
            patch("app.workers.orchestrator.docker_engine_available", return_value=True),
            patch("app.workers.orchestrator.publish_event"),
            patch("app.workers.orchestrator.is_cancelled", return_value=False),
            patch("app.workers.orchestrator.cache_compile_log") as cache_log,
            patch("app.workers.orchestrator.cache_compile_output") as cache_pdf,
        ):
            success, _, error, page_count, pdf = orch._run_latex_stage(
                job_id,
                r"\documentclass{article}\begin{document}x\end{document}",
            )

        assert success is False
        assert error == ls.ENGINE_READ_ESCAPE_ERROR
        assert page_count is None and pdf is None
        cache_pdf.assert_not_called()
        cache_log.assert_not_called()


# ── The unauthenticated /public/compile path ──────────────────────────────────

class TestServiceCompilePath:
    """LaTeXService.compile_latex backs POST /compile, POST /public/compile (no auth)
    and optimize-and-compile, so it needs the same controls as the Celery path."""

    def _run(self, tmp_path, fls_body: str | None, *, docker: bool = True):
        import asyncio

        job_id = str(uuid.uuid4())

        async def _fake_exec(*cmd, **kwargs):
            job_dir = tmp_path / job_id
            if fls_body is not None:
                (job_dir / "resume.fls").write_text(fls_body)
            (job_dir / "resume.pdf").write_bytes(b"%PDF-1.5 924acb30d9bb")
            (job_dir / "resume.log").write_text("(/workspace/resume.tex\n924acb30d9bb\n")
            proc = MagicMock()
            proc.returncode = 0

            async def _communicate():
                return b"", b""

            proc.communicate = _communicate
            _fake_exec.cmd = list(cmd)
            return proc

        with (
            patch.object(ls.settings, "TEMP_DIR", tmp_path),
            patch.object(ls, "docker_engine_available", return_value=docker),
            patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        ):
            result = asyncio.run(
                ls.LaTeXService().compile_latex("\\documentclass{article}x", job_id=job_id)
            )
        return result, getattr(_fake_exec, "cmd", []), tmp_path / job_id

    def test_recorder_escape_withholds_the_pdf_and_the_transcript(self, tmp_path):
        result, _, job_dir = self._run(
            tmp_path, "PWD /workspace\nINPUT /etc/hostname\n"
        )
        assert result.success is False
        assert result.message == ls.ENGINE_READ_ESCAPE_ERROR
        assert result.log_output is None
        assert result.pdf_size is None
        # GET /download/{job_id} reads this directory — it must be gone.
        assert not job_dir.exists()

    def test_successful_compile_does_not_hand_back_the_transcript(self, tmp_path):
        result, _, _ = self._run(tmp_path, "PWD /workspace\nINPUT /workspace/resume.tex\n")
        assert result.success is True
        assert result.log_output is None

    def test_command_is_hardened(self, tmp_path):
        _, cmd, _ = self._run(tmp_path, "PWD /workspace\n")
        assert cmd[0] == "docker"
        assert "-no-shell-escape" in cmd and "-recorder" in cmd
        assert cmd[cmd.index("--network") + 1] == "none"

    def test_falls_back_to_the_gated_local_engine_without_docker(self, tmp_path):
        """The prod image bakes texlive in and ships no docker CLI; a Docker-only
        path raised FileNotFoundError there and 500'd every request."""
        with patch.object(ls, "assert_local_engine_allowed") as gate:
            _, cmd, _ = self._run(tmp_path, "PWD /workspace\n", docker=False)
        gate.assert_called_once()
        assert cmd[0] == "pdflatex"
        assert "-no-shell-escape" in cmd and "-recorder" in cmd


# ── Worker command construction ───────────────────────────────────────────────

def _popen_stub(cmd, **kwargs):
    proc = MagicMock()
    proc.stdout = iter(["Output written on resume.pdf (1 page, 100 bytes).\n"])
    proc.returncode = 0
    proc.wait.return_value = 0
    return proc


class TestWorkerInvocation:
    """Both worker entrypoints must build the hardened command."""

    def _capture(self, module_path, run):
        seen = {}

        def _spy(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["env"] = kwargs.get("env")
            return _popen_stub(cmd, **kwargs)

        with patch(f"{module_path}.subprocess.Popen", side_effect=_spy):
            run()
        return seen

    def test_latex_worker_docker_command_is_hardened(self):
        import app.workers.latex_worker as lw

        def _run():
            with (
                patch("app.workers.latex_worker.docker_engine_available", return_value=True),
                patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
                patch("app.workers.latex_worker.publish_event"),
                patch("app.workers.latex_worker.publish_job_result"),
                patch("app.workers.latex_worker.is_cancelled", return_value=False),
                patch("app.workers.latex_worker.reconcile_compilation_record"),
                patch("app.workers.latex_worker.cache_compile_log"),
                patch("app.workers.latex_worker.cache_compile_output", return_value=b"%PDF"),
                patch("app.workers.latex_worker._extract_pdf_text", return_value=""),
                patch("pathlib.Path.exists", return_value=True),
                patch("pathlib.Path.stat", return_value=MagicMock(st_size=10)),
                patch("pathlib.Path.write_text"),
                patch("pathlib.Path.mkdir"),
            ):
                lw.compile_latex_task(
                    r"\documentclass{article}\begin{document}x\end{document}",
                    job_id=str(uuid.uuid4()),
                )

        seen = self._capture("app.workers.latex_worker", _run)
        cmd = seen["cmd"]
        assert cmd[0] == "docker"
        assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
        assert "-no-shell-escape" in cmd
        assert "DATABASE_URL" not in (seen["env"] or {})

    def test_orchestrator_docker_command_is_hardened(self):
        import app.workers.orchestrator as orch

        def _run():
            with (
                patch("app.workers.orchestrator.docker_engine_available", return_value=True),
                patch("app.workers.orchestrator.publish_event"),
                patch("app.workers.orchestrator.is_cancelled", return_value=False),
                patch("app.workers.orchestrator.cache_compile_log"),
                patch("app.workers.orchestrator.cache_compile_output", return_value=b"%PDF"),
                patch("app.workers.orchestrator.record_compile"),
                patch("pathlib.Path.exists", return_value=True),
                patch("pathlib.Path.write_text"),
                patch("pathlib.Path.mkdir"),
            ):
                orch._run_latex_stage(
                    str(uuid.uuid4()),
                    r"\documentclass{article}\begin{document}x\end{document}",
                )

        seen = self._capture("app.workers.orchestrator", _run)
        cmd = seen["cmd"]
        assert cmd[0] == "docker"
        assert "--cap-drop" in cmd
        assert "-no-shell-escape" in cmd
        assert "DATABASE_URL" not in (seen["env"] or {})


# ── Combined path shares the validator ────────────────────────────────────────

class TestCombinedPathValidates:
    """The combined job used to skip validate_latex_content entirely."""

    @pytest.mark.parametrize("body", [
        r"\input{/etc/passwd}",
        r"\makeatletter\@@input /etc/passwd",
        r"\csname input\endcsname{/etc/passwd}",
        r"\immediate\write 18{id}",
    ])
    def test_malicious_llm_output_is_rejected_before_compiling(self, body):
        import app.workers.orchestrator as orch

        latex = r"\documentclass{article}\begin{document}%s\end{document}" % body
        with patch("app.workers.orchestrator.subprocess.Popen") as popen, \
                patch("app.workers.orchestrator.publish_event"):
            success, _, error, page_count, pdf = orch._run_latex_stage("job-x", latex)

        popen.assert_not_called()
        assert success is False
        assert "Invalid LaTeX" in error
        assert page_count is None and pdf is None

"""
Unit tests for app.workers.latex_worker — synchronous Celery task tests.

All external I/O (subprocess, Redis) is mocked.
Tests use Celery eager mode: tasks run synchronously in the same process.
"""

from __future__ import annotations

import base64
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import delete, select

import app.workers.latex_worker as lw
from app.database.models import Compilation, JobFinalization
from app.services.auto_fit_service import AUTO_FIT_PROFILES, apply_auto_fit

# ── Celery eager mode ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _celery_eager():
    from app.core.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


@pytest.fixture(autouse=True)
def _docker_capability_probe():
    """Keep worker unit tests independent of the real Docker probe.

    These tests patch the shared ``subprocess.run`` module for pdftotext and
    other command doubles.  The production capability probe intentionally
    remains unmodified; this fixture supplies its explicit test result so the
    shared subprocess mock cannot be mistaken for a Docker probe response.
    """
    with patch("app.workers.latex_worker.docker_engine_available", return_value=False):
        yield


# ── Test helpers ──────────────────────────────────────────────────────────────

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
Hello World
\end{document}
"""


class _BoundedSyncStream:
    """Small Popen.stdout double with the bounded-read contract."""

    def __init__(self, chunks: list[str | bytes]):
        self._payload = b"".join(
            chunk.encode() if isinstance(chunk, str) else chunk for chunk in chunks
        )

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload)
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk

    def close(self) -> None:
        pass


def _make_popen(returncode: int = 0, lines: list | None = None) -> MagicMock:
    """Build a mock subprocess.Popen result."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = _BoundedSyncStream(lines if lines is not None else ["This is pdflatex output\n"])
    mock_proc.wait.return_value = None
    mock_proc.kill.return_value = None
    return mock_proc


@pytest.fixture
def mock_publish():
    with patch("app.workers.latex_worker.publish_event") as m:
        yield m


@pytest.fixture
def mock_job_result():
    with patch("app.workers.latex_worker.publish_job_result") as m:
        yield m


@pytest.fixture
def mock_cancelled():
    with patch("app.workers.latex_worker.is_cancelled", return_value=False):
        yield


@pytest.fixture
def mock_validate_ok():
    with patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True):
        yield


@pytest.fixture
def mock_popen_success():
    """Mock subprocess.Popen returning success with one log line."""
    with (
        patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])) as m,
        patch("app.workers.latex_worker.subprocess.run", return_value=MagicMock(returncode=0, stdout="Hello World\n")),
        patch("app.workers.latex_worker.shutil.which", return_value="/usr/bin/pdftotext"),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_text"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
    ):
        yield m


# ── Validation failure ────────────────────────────────────────────────────────


class TestLatexValidationFailure:
    def test_invalid_latex_emits_job_failed(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=False):
            lw.compile_latex_task("invalid latex content", job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_invalid_latex_returns_success_false(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=False):
            result = lw.compile_latex_task("bad content", job_id=str(uuid.uuid4()))
        assert result["success"] is False

    def test_invalid_latex_error_code_is_latex_error(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=False):
            lw.compile_latex_task("bad content", job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[0].args[2]["error_code"] == "latex_error"

    def test_invalid_latex_not_retryable(self, mock_publish, mock_job_result, mock_cancelled):
        with patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=False):
            lw.compile_latex_task("bad content", job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[0].args[2]["retryable"] is False


# ── Successful compilation ────────────────────────────────────────────────────


class TestLatexCompilationSuccess:
    @pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
    def test_real_auto_fit_probe_reports_the_candidate_page_count(self, tmp_path):
        source = r"""\documentclass{article}
\begin{document}
First block\vspace*{105mm}\par
Second block\vspace*{105mm}\par
\end{document}
"""
        candidate = apply_auto_fit(source, AUTO_FIT_PROFILES[-1])
        with (
            patch.object(lw.settings, "TEMP_DIR", tmp_path),
            patch("app.workers.latex_worker.docker_engine_available", return_value=False),
            patch.dict("os.environ", {"ALLOW_LOCAL_LATEX_ENGINE": "true"}, clear=False),
        ):
            success, page_count, error = lw._probe_auto_fit_candidate(
                job_id="test-real-fit",
                latex_content=candidate,
                profile_intensity=100,
                compiler="pdflatex",
                main_file="resume.tex",
                custom_flags=[],
                error_mode_flags=["-interaction=nonstopmode", "-halt-on-error"],
                bibtex=None,
                timeout=30,
            )

        assert success is True, error
        assert page_count == 1
        assert not (tmp_path / "test-real-fit-autofit-100").exists()

    def test_auto_fit_uses_first_profile_that_compiles_to_one_page(
        self,
        mock_publish,
        mock_job_result,
        mock_cancelled,
        mock_validate_ok,
        mock_popen_success,
    ):
        with patch(
            "app.workers.latex_worker._probe_auto_fit_candidate",
            side_effect=[(True, 2, ""), (True, 1, "")],
        ) as probe:
            result = lw.compile_latex_task(
                VALID_LATEX,
                job_id=str(uuid.uuid4()),
                auto_fit=True,
                metadata={"skip_auto_save": True},
            )

        assert probe.call_count == 2
        assert result["fit_succeeded"] is True
        assert result["fit_intensity"] == 50
        assert result["fit_attempts"] == 2
        assert r"\linespread{0.94}" in result["fitted_latex"]
        assert "Hello World" in result["fitted_latex"]

    def test_auto_fit_does_not_claim_success_beyond_safe_readability_limit(
        self,
        mock_publish,
        mock_job_result,
        mock_cancelled,
        mock_validate_ok,
        mock_popen_success,
    ):
        with patch(
            "app.workers.latex_worker._probe_auto_fit_candidate",
            return_value=(True, 2, ""),
        ) as probe:
            result = lw.compile_latex_task(
                VALID_LATEX,
                job_id=str(uuid.uuid4()),
                auto_fit=True,
                metadata={"skip_auto_save": True},
            )

        assert probe.call_count == 4
        assert result["fit_succeeded"] is False
        assert result["fit_intensity"] == 100
        assert r"\AtBeginDocument{\small}" in result["fitted_latex"]

    def test_derived_compile_can_skip_auto_save_history(
        self,
        mock_publish,
        mock_job_result,
        mock_cancelled,
        mock_validate_ok,
        mock_popen_success,
    ):
        with patch("app.workers.auto_save_worker.submit_auto_save_checkpoint") as auto_save:
            lw.compile_latex_task(
                VALID_LATEX,
                job_id=str(uuid.uuid4()),
                resume_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                metadata={"skip_auto_save": True},
            )
        auto_save.assert_not_called()

    def test_normal_owned_compile_still_creates_auto_save_checkpoint(
        self,
        mock_publish,
        mock_job_result,
        mock_cancelled,
        mock_validate_ok,
        mock_popen_success,
    ):
        resume_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        with patch("app.workers.auto_save_worker.submit_auto_save_checkpoint") as auto_save:
            lw.compile_latex_task(
                VALID_LATEX,
                job_id=str(uuid.uuid4()),
                resume_id=resume_id,
                user_id=user_id,
            )
        auto_save.assert_called_once_with(resume_id, user_id, VALID_LATEX)

    def test_success_returns_success_true(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["success"] is True

    def test_success_returns_pdf_job_id(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        job_id = str(uuid.uuid4())
        result = lw.compile_latex_task(VALID_LATEX, job_id=job_id)
        assert result["pdf_job_id"] == job_id

    def test_job_started_emitted_first(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert types[0] == "job.started"

    def test_job_started_stage_is_latex_compilation(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        started = [c for c in mock_publish.call_args_list if c.args[1] == "job.started"]
        assert started[0].args[2]["stage"] == "latex_compilation"

    def test_log_line_emitted_for_each_stdout_line(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        lines = ["Line 1\n", "Line 2\n", "Line 3\n"]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, lines)),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_line_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert len(log_line_events) == 3

    def test_log_line_source_is_pdflatex(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Some output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["source"] == "pdflatex"

    def test_error_line_detected(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """Lines containing 'error' keyword should have is_error=True."""
        with (
            patch(
                "app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["! LaTeX Error: undefined\n"])
            ),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["is_error"] is True

    def test_normal_line_not_error(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Normal output line\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["is_error"] is False

    def test_fatal_line_detected_as_error(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Fatal: something bad\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["is_error"] is True

    def test_job_completed_emitted(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.completed" in types

    def test_job_completed_has_pdf_job_id(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        job_id = str(uuid.uuid4())
        lw.compile_latex_task(VALID_LATEX, job_id=job_id)
        completed = [c for c in mock_publish.call_args_list if c.args[1] == "job.completed"]
        assert completed[0].args[2]["pdf_job_id"] == job_id

    def test_job_result_stored(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert mock_job_result.call_count == 1

    def test_empty_log_lines_skipped(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """Empty lines from stdout should not produce log.line events."""
        with (
            patch(
                "app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["\n", "\n", "Real line\n"])
            ),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert len(log_events) == 1

    def test_success_uses_host_pdftotext_when_available(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        run_result = MagicMock(returncode=0, stdout="Extracted text", stderr="")
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])),
            patch(
                "app.workers.latex_worker.shutil.which",
                side_effect=lambda name: "/opt/homebrew/bin/pdftotext" if name == "pdftotext" else "/usr/bin/docker",
            ),
            patch("app.workers.latex_worker.subprocess.run", return_value=run_result) as mock_run,
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["extracted_text"] == "Extracted text"
        assert mock_run.call_args.args[0][0] == "/opt/homebrew/bin/pdftotext"

    def test_success_falls_back_when_first_pdftotext_attempt_returns_empty(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        run_results = [
            MagicMock(returncode=1, stdout="", stderr="missing binary"),
            MagicMock(returncode=0, stdout="Recovered text", stderr=""),
        ]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])),
            patch(
                "app.workers.latex_worker.shutil.which",
                side_effect=lambda name: "/opt/homebrew/bin/pdftotext" if name == "pdftotext" else None,
            ),
            patch("app.workers.latex_worker._HOST_PDFTOTEXT_CANDIDATES", ()),
            patch("app.workers.latex_worker.subprocess.run", side_effect=run_results) as mock_run,
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["extracted_text"] == "Recovered text"
        assert mock_run.call_count >= 2

    def test_success_uses_pdfminer_after_pdftotext_retries_fail(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        run_results = [
            MagicMock(returncode=1, stdout="", stderr="missing text"),
            MagicMock(returncode=1, stdout="", stderr="missing text"),
            MagicMock(returncode=1, stdout="", stderr="missing text"),
        ]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])),
            patch(
                "app.workers.latex_worker.shutil.which",
                side_effect=lambda name: "/opt/homebrew/bin/pdftotext" if name == "pdftotext" else None,
            ),
            patch("app.workers.latex_worker._HOST_PDFTOTEXT_CANDIDATES", ()),
            patch("app.workers.latex_worker.subprocess.run", side_effect=run_results),
            patch("pdfminer.high_level.extract_text", return_value="Recovered via pdfminer"),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["extracted_text"] == "Recovered via pdfminer"


# ── Compilation failure (non-zero exit code) ──────────────────────────────────


class TestLatexCompilationFailure:
    def test_nonzero_exit_code_emits_job_failed(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["pdflatex error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),  # PDF not generated
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_nonzero_exit_code_persists_failed_result(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["pdflatex error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert mock_job_result.call_count == 1
        stored = mock_job_result.call_args.args[1]
        assert stored["success"] is False
        assert stored["error"].startswith("pdflatex exited with code")

    def test_nonzero_exit_code_returns_success_false(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["success"] is False

    def test_nonzero_exit_code_error_code_is_latex_error(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(2, ["error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[-1].args[2]["error_code"] == "latex_error"

    def test_success_exitcode_but_no_pdf_fails(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """returncode=0 but PDF file doesn't exist → job.failed."""
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["ok\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),  # no PDF
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_nonzero_exit_code_persists_terminal_result(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch(
                "app.workers.latex_worker.subprocess.Popen",
                return_value=_make_popen(1, ["! Undefined control sequence.\n"]),
            ),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        mock_job_result.assert_called_once_with(result["job_id"], result)


# ── Cancellation ──────────────────────────────────────────────────────────────


class TestLatexCancellation:
    def test_cancelled_during_compilation_returns_success_false(self, mock_publish, mock_job_result, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["success"] is False

    def test_cancelled_emits_job_cancelled(self, mock_publish, mock_job_result, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.cancelled" in types

    def test_cancelled_persists_failed_result(self, mock_publish, mock_job_result, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        stored = mock_job_result.call_args.args[1]
        assert stored["success"] is False
        assert stored["cancelled"] is True

    def test_cancelled_kills_process(self, mock_publish, mock_job_result, mock_validate_ok):
        mock_proc = _make_popen(0, ["output\n"])
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=mock_proc),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert mock_proc.kill.called

    def test_cancelled_persists_terminal_result(self, mock_publish, mock_job_result, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        mock_job_result.assert_called_once_with(result["job_id"], result)


# ── Timeout ───────────────────────────────────────────────────────────────────


class TestLatexTimeout:
    def test_timeout_kills_process(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        mock_proc = _make_popen(0, ["slow output\n", "more output\n"])
        # Simulate time advancing past timeout on second iteration
        time_calls = [0.0, 0.0, 9999.0]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=mock_proc),
            patch("app.workers.latex_worker.docker_engine_available", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch(
                "app.workers.latex_worker.time.time", side_effect=lambda: time_calls.pop(0) if time_calls else 9999.0
            ),
            patch("app.workers.latex_worker.settings") as ms,
        ):
            ms.COMPILE_TIMEOUT = 30
            ms.TEMP_DIR = __import__("pathlib").Path("/tmp/latexy_test")
            ms.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            ms.ALLOWED_LATEX_COMPILERS = ["pdflatex", "xelatex", "lualatex"]
            ms.DEFAULT_LATEX_COMPILER = "pdflatex"
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert mock_proc.kill.called

    def test_timeout_emits_job_failed_with_timeout_code(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        time_calls = [0.0, 0.0, 9999.0]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n", "output2\n"])),
            patch("app.workers.latex_worker.docker_engine_available", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch(
                "app.workers.latex_worker.time.time", side_effect=lambda: time_calls.pop(0) if time_calls else 9999.0
            ),
            patch("app.workers.latex_worker.settings") as ms,
        ):
            ms.COMPILE_TIMEOUT = 30
            ms.TEMP_DIR = __import__("pathlib").Path("/tmp/latexy_test")
            ms.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            ms.ALLOWED_LATEX_COMPILERS = ["pdflatex", "xelatex", "lualatex"]
            ms.DEFAULT_LATEX_COMPILER = "pdflatex"
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed
        assert failed[-1].args[2]["error_code"] == "compile_timeout"


# ── Exception handling ────────────────────────────────────────────────────────


class TestLatexExceptionHandling:
    @pytest.fixture(autouse=True)
    def _disable_propagation(self):
        from app.core.celery_app import celery_app

        celery_app.conf.task_eager_propagates = False
        yield
        celery_app.conf.task_eager_propagates = True

    def test_subprocess_exception_emits_job_failed(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=OSError("Docker not found")),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            lw.compile_latex_task.apply(args=[VALID_LATEX], kwargs={"job_id": job_id})

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_subprocess_exception_error_code_is_internal(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=OSError("Docker error")),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            lw.compile_latex_task.apply(args=[VALID_LATEX], kwargs={"job_id": job_id})

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[-1].args[2]["error_code"] == "internal"


class TestPdfTextExtraction:
    def test_success_uses_host_pdftotext_when_available(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])),
            patch(
                "app.workers.latex_worker.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="Extracted text\n"),
            ) as mock_run,
            patch("app.workers.latex_worker.shutil.which", return_value="/opt/homebrew/bin/pdftotext"),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["extracted_text"] == "Extracted text\n"
        assert mock_run.call_args.args[0][0] == "/opt/homebrew/bin/pdftotext"

    def test_success_falls_back_to_pdfminer_when_pdftotext_empty(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])),
            patch("app.workers.latex_worker.subprocess.run", return_value=MagicMock(returncode=0, stdout="   ")),
            patch("app.workers.latex_worker.shutil.which", return_value="/usr/bin/pdftotext"),
            patch("pdfminer.high_level.extract_text", return_value="Fallback text\n"),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result["extracted_text"] == "Fallback text\n"


# ── Page count extraction ─────────────────────────────────────────────────────


class TestLatexPageCount:
    PAGE_COUNT_LINE = "Output written on resume.pdf (2 pages, 54321 bytes).\n"
    SINGLE_PAGE_LINE = "Output written on output.pdf (1 page, 12345 bytes).\n"

    def test_page_count_extracted_from_log(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, [self.PAGE_COUNT_LINE])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=54321, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] == 2

    def test_page_count_in_job_completed_event(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, [self.PAGE_COUNT_LINE])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=54321, st_mode=0)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        completed = [c for c in mock_publish.call_args_list if c.args[1] == "job.completed"]
        assert completed[0].args[2]["page_count"] == 2

    def test_page_count_none_when_not_in_logs(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch(
                "app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Normal pdflatex output\n"])
            ),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] is None

    def test_single_page_extracted(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, [self.SINGLE_PAGE_LINE])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] == 1

    def test_page_count_from_last_occurrence(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """Multiple output lines — last page count line wins."""
        lines = [
            "Output written on pass1.pdf (1 page, 1000 bytes).\n",
            "Output written on pass2.pdf (3 pages, 3000 bytes).\n",
        ]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, lines)),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=3000, st_mode=0)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] == 3


class TestCompileCache:
    def test_key_is_exact_and_tenant_scoped(self):
        first = lw.compile_cache_key(VALID_LATEX, "pdflatex", {"main_file": "resume.tex"}, "user:one")
        assert first == lw.compile_cache_key(VALID_LATEX, "pdflatex", {"main_file": "resume.tex"}, "user:one")
        assert first != lw.compile_cache_key(
            VALID_LATEX + "% edit", "pdflatex", {"main_file": "resume.tex"}, "user:one"
        )
        assert first != lw.compile_cache_key(VALID_LATEX, "xelatex", {"main_file": "resume.tex"}, "user:one")
        assert first != lw.compile_cache_key(VALID_LATEX, "pdflatex", {"main_file": "resume.tex"}, "user:two")
        assert lw.compile_cache_key(VALID_LATEX, "pdflatex", {}, None) is None

    def test_restore_copies_artifacts_and_rewrites_job_identity(self):
        redis = MagicMock()
        redis.exists.return_value = 0
        redis.eval.return_value = 1
        redis.get.return_value = "source-job"
        redis.mget.return_value = [
            base64.b64encode(b"%PDF").decode("ascii"),
            "synctex data",
            "compile log",
            json.dumps(
                {
                    "success": True,
                    "job_id": "source-job",
                    "pdf_job_id": "source-job",
                    "compilation_time": 1.5,
                    "page_count": 1,
                }
            ),
        ]
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis):
            result = lw.restore_compile_cache("cache-key", "fresh-job")

        assert result is not None
        assert result["job_id"] == "fresh-job"
        assert result["pdf_job_id"] == "fresh-job"
        assert result["compilation_time"] == 0.0
        assert result["cached"] is True
        # The result is written only by publish_job_result(), which atomically
        # checks the current lifecycle owner. Cache restore may copy artifacts
        # but must not create an unfenced result key.
        assert not redis.pipeline.called

    def test_cache_hit_skips_tex_and_publishes_fresh_job_identity(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        job_id = str(uuid.uuid4())
        cached = {
            "success": True,
            "job_id": job_id,
            "pdf_job_id": job_id,
            "compilation_time": 0.0,
            "pdf_size": 8,
            "page_count": 2,
            "slide_count": None,
            "is_beamer": False,
            "extracted_text": "Cached resume text",
            "cached": True,
        }
        redis = MagicMock()
        redis.exists.return_value = 0
        redis.eval.return_value = 1
        redis.get.return_value = base64.b64encode(b"%PDF-1.4")
        with (
            patch("app.workers.latex_worker.restore_compile_cache", return_value=cached) as restore,
            patch("app.workers.latex_worker.get_worker_redis", return_value=redis),
            patch("app.workers.latex_worker.reconcile_compilation_record") as reconcile,
            patch("app.workers.latex_worker.subprocess.Popen") as popen,
        ):
            result = lw.compile_latex_task(
                VALID_LATEX,
                job_id=job_id,
                user_id="123e4567-e89b-42d3-a456-426614174099",
            )

        assert result == cached
        restore.assert_called_once()
        popen.assert_not_called()
        reconcile.assert_called_once_with(
            job_id,
            success=True,
            compilation_time=0.0,
            pdf_bytes=b"%PDF-1.4",
            lifecycle_owner=reconcile.call_args.kwargs["lifecycle_owner"],
        )
        assert reconcile.call_args.kwargs["lifecycle_owner"].startswith("latex-None:")
        completed = [call for call in mock_publish.call_args_list if call.args[1] == "job.completed"]
        assert completed[-1].args[2]["pdf_job_id"] == job_id
        assert completed[-1].args[2]["cached"] is True
        mock_job_result.assert_called_once_with(job_id, cached)

    def test_ordinary_cache_hit_strips_prior_auto_fit_metadata(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        job_id = str(uuid.uuid4())
        cached = {
            "success": True,
            "job_id": job_id,
            "pdf_job_id": job_id,
            "page_count": 1,
            "auto_fit": True,
            "fit_succeeded": True,
            "fit_intensity": 50,
            "fit_attempts": 2,
            "fitted_latex": VALID_LATEX,
        }
        redis = MagicMock()
        redis.exists.return_value = 0
        redis.get.return_value = base64.b64encode(b"%PDF-1.4")
        with (
            patch("app.workers.latex_worker.restore_compile_cache", return_value=cached),
            patch("app.workers.latex_worker.get_worker_redis", return_value=redis),
            patch("app.workers.latex_worker.reconcile_compilation_record"),
        ):
            result = lw.compile_latex_task(
                VALID_LATEX,
                job_id=job_id,
                user_id="123e4567-e89b-42d3-a456-426614174099",
            )

        assert "auto_fit" not in result
        assert "fitted_latex" not in result
        mock_job_result.assert_called_once_with(job_id, result)


# ── submit_latex_compilation helper ──────────────────────────────────────────


class TestSubmitLatexCompilation:
    def test_dispatches_to_latex_queue(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.compile_latex_task, "apply_async") as mock_async:
            lw.submit_latex_compilation(VALID_LATEX, job_id=job_id)
        _, kwargs = mock_async.call_args
        assert kwargs["queue"] == "latex"

    def test_returns_job_id(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.compile_latex_task, "apply_async"):
            result = lw.submit_latex_compilation(VALID_LATEX, job_id=job_id)
        assert result == job_id

    def test_passes_job_id_to_kwargs(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.compile_latex_task, "apply_async") as mock_async:
            lw.submit_latex_compilation(VALID_LATEX, job_id=job_id)
        _, kwargs = mock_async.call_args
        assert kwargs["kwargs"]["job_id"] == job_id

    def test_uses_provided_priority(self):
        job_id = str(uuid.uuid4())
        with patch.object(lw.compile_latex_task, "apply_async") as mock_async:
            lw.submit_latex_compilation(VALID_LATEX, job_id=job_id, priority=7)
        _, kwargs = mock_async.call_args
        assert kwargs["priority"] == 7


# ---------------------------------------------------------------------------
# Regression tests — prevent known bugs from recurring
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("mock_cancelled", "mock_job_result", "mock_publish", "mock_validate_ok")
class TestLatexWorkerRegressions:
    """
    Named regression tests for bugs fixed in the latex worker.
    Each test describes WHY the contract exists.
    """

    def test_failure_result_contains_success_false(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        """
        Regression: when the subprocess exits non-zero, publish_job_result must
        receive a dict that includes success=False.

        Previously the failure branch built {"error": error_msg} without
        "success", causing KeyError in callers that assumed the same schema as
        successful results.
        """
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert result.get("success") is False, "failure result must include success=False"

    def test_failure_result_contains_job_id(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """
        Regression: the failure result dict must include job_id so that
        publish_job_result can be called as publish_job_result(result["job_id"], result).
        """
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=job_id)

        assert result.get("job_id") == job_id, "failure result must include job_id"


# ── Artifact caching & Compilation reconciliation ─────────────────────────────


class TestCacheCompileOutput:
    """cache_compile_output must persist artifacts before job_dir is removed."""

    def test_caches_pdf_and_synctex(self, tmp_path):
        import base64
        import gzip

        job_id = str(uuid.uuid4())
        (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.7 fake")
        (tmp_path / "resume.synctex.gz").write_bytes(gzip.compress(b"SyncTeX data"))
        redis_mock = MagicMock()
        redis_mock.exists.return_value = 0
        redis_mock.eval.return_value = 1

        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            pdf_bytes = lw.cache_compile_output(job_id, tmp_path)

        assert pdf_bytes == b"%PDF-1.7 fake"
        eval_calls = [call.args for call in redis_mock.eval.call_args_list]
        assert any(
            f"latexy:job:{job_id}:pdf" in args
            and base64.b64encode(b"%PDF-1.7 fake").decode() in args
            for args in eval_calls
        )
        assert any(
            f"latexy:job:{job_id}:synctex" in args and "SyncTeX data" in args
            for args in eval_calls
        )

    def test_missing_pdf_returns_none(self, tmp_path):
        redis_mock = MagicMock()
        redis_mock.exists.return_value = 0
        redis_mock.eval.return_value = 1
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            assert lw.cache_compile_output(str(uuid.uuid4()), tmp_path) is None

    def test_cache_compile_log_stores_log(self):
        job_id = str(uuid.uuid4())
        redis_mock = MagicMock()
        redis_mock.exists.return_value = 0
        redis_mock.eval.return_value = 1
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            lw.cache_compile_log(job_id, "line one\nline two")
        args = redis_mock.eval.call_args.args
        assert f"latexy:job:{job_id}:log" in args
        assert "line one\nline two" in args
        assert args[-1] == 86400


class TestReconcileCompilationRecord:
    """
    Regression: the Compilation row was only ever moved out of "processing" by
    GET /jobs/{id}/result, an endpoint the frontend never calls — so share links,
    one-click apply and the dashboard success rate were permanently dead.
    """

    def _patched_update(self):
        from unittest.mock import AsyncMock

        return patch("app.workers.latex_worker._update_compilation_record", new=AsyncMock())

    def test_success_passes_pdf_bytes_and_marks_completed(self):
        job_id = str(uuid.uuid4())
        with self._patched_update() as mock_update:
            lw.reconcile_compilation_record(job_id, success=True, compilation_time=1.5, pdf_bytes=b"%PDF-1.7")

        kwargs = mock_update.await_args.kwargs
        assert kwargs["status"] == "completed"
        assert kwargs["pdf_bytes"] == b"%PDF-1.7"
        assert kwargs["compilation_time"] == 1.5

    def test_failure_marks_failed_and_drops_pdf_bytes(self):
        job_id = str(uuid.uuid4())
        with self._patched_update() as mock_update:
            lw.reconcile_compilation_record(
                job_id,
                success=False,
                error_message="! Undefined control sequence.",
                pdf_bytes=b"%PDF-1.7",
            )

        kwargs = mock_update.await_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["pdf_bytes"] is None
        assert kwargs["error_message"] == "! Undefined control sequence."

    def test_explicit_status_overrides_derived_one(self):
        with self._patched_update() as mock_update:
            lw.reconcile_compilation_record(
                str(uuid.uuid4()),
                success=False,
                status="cancelled",
                error_message="cancelled",
            )
        assert mock_update.await_args.kwargs["status"] == "cancelled"

    def test_error_message_truncated_to_column_width(self):
        with self._patched_update() as mock_update:
            lw.reconcile_compilation_record(str(uuid.uuid4()), success=False, error_message="x" * 900)
        assert len(mock_update.await_args.kwargs["error_message"]) == 500

    def test_successful_compile_reconciles_row(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        job_id = str(uuid.uuid4())
        with patch("app.workers.latex_worker.reconcile_compilation_record") as mock_reconcile:
            lw.compile_latex_task(VALID_LATEX, job_id=job_id)

        assert mock_reconcile.call_args.args[0] == job_id
        assert mock_reconcile.call_args.kwargs["success"] is True

    def test_cancelled_compile_reconciles_row_as_cancelled(self, mock_publish, mock_job_result, mock_validate_ok):
        """
        DELETE /jobs/{id} is a shipped endpoint: the cancel branch used to return
        without reconciling, wedging the row at "processing" forever, and without
        caching the log so GET /logs/{id} 404'd.
        """
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.is_cancelled", return_value=True),
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["partial output\n"])),
            patch("app.workers.latex_worker.reconcile_compilation_record") as mock_reconcile,
            patch("app.workers.latex_worker.cache_compile_log") as mock_cache_log,
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=job_id)

        assert mock_reconcile.called, "cancel branch must reconcile the Compilation row"
        assert mock_reconcile.call_args.args[0] == job_id
        assert mock_reconcile.call_args.kwargs["status"] == "cancelled"
        assert mock_reconcile.call_args.kwargs["success"] is False
        assert mock_cache_log.call_args.args[0] == job_id
        assert "partial output" in mock_cache_log.call_args.args[1]

    def test_invalid_watermark_reconciles_row(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with patch("app.workers.latex_worker.reconcile_compilation_record") as mock_reconcile:
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()), watermark="bad;watermark$")

        assert mock_reconcile.called, "invalid-watermark branch must reconcile the row"
        assert mock_reconcile.call_args.kwargs["success"] is False
        assert mock_reconcile.call_args.kwargs["error_message"] == "Invalid watermark text"

    def test_failed_compile_reconciles_row(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        job_id = str(uuid.uuid4())
        with (
            patch(
                "app.workers.latex_worker.subprocess.Popen",
                return_value=_make_popen(1, ["! Undefined control sequence.\n"]),
            ),
            patch("app.workers.latex_worker.reconcile_compilation_record") as mock_reconcile,
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=job_id)

        assert mock_reconcile.call_args.kwargs["success"] is False
        assert mock_reconcile.call_args.kwargs["error_message"] == "! Undefined control sequence."


class TestUpdateCompilationRecord:
    """
    Direct tests for the guarded terminal update and durable PDF persistence.

    Ordering matters: a completed row must not be committed until the PDF upload
    and ``pdf_path`` update both succeed. Compile paths with no Compilation row
    (anonymous /jobs/submit, /jobs/compile-watermarked, the anonymous-share
    redaction compile) must not upload at all.
    """

    @staticmethod
    def _session_factory(rowcounts: list, *, status: str = "processing", pdf_path: str | None = None):
        from unittest.mock import AsyncMock

        session = MagicMock()
        lookup = MagicMock()
        lookup.scalar_one_or_none.return_value = (
            SimpleNamespace(status=status, pdf_path=pdf_path) if status is not None else None
        )
        session.execute = AsyncMock(
            side_effect=[lookup, *[MagicMock(rowcount=rc) for rc in rowcounts]]
        )
        # _update_compilation_record uses the production AsyncSession.scalar
        # contract to acquire the durable arbiter before Compilation. Keep the
        # legacy-row unit doubles awaitable instead of masking that boundary
        # with a synchronous MagicMock.
        session.scalar = AsyncMock(return_value=None)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        class _Factory:
            def __call__(self):
                return self

            async def __aenter__(self_inner):
                return session

            async def __aexit__(self_inner, *exc):
                return False

        factory = _Factory()
        return factory, session

    async def test_no_row_skips_upload_and_returns_false(self):
        factory, session = self._session_factory([], status=None)
        with patch("app.services.storage_service.upload_bytes") as mock_upload:
            updated = await lw._update_compilation_record(
                job_id=str(uuid.uuid4()),
                status="completed",
                compilation_time=1.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                session_factory=factory,
            )

        assert updated == lw.CompilationPersistenceOutcome.NO_ROW
        assert not mock_upload.called, "must not orphan a MinIO object with no owning row"
        assert session.execute.await_count == 1, "must not run an UPDATE or upload"

    async def test_row_updated_uploads_then_records_pdf_path(self):
        job_id = str(uuid.uuid4())
        factory, session = self._session_factory([1])
        lifecycle_redis = MagicMock()
        lifecycle_redis.hget.side_effect = lambda key, field: {
            "status": "running",
            "owner": "owner-a",
            "lease_until": "9999999999",
        }.get(field)
        with (
            patch("app.services.storage_service.upload_bytes") as mock_upload,
            patch("app.workers.latex_worker.get_worker_redis", return_value=lifecycle_redis),
        ):
            updated = await lw._update_compilation_record(
                job_id=job_id,
                status="completed",
                compilation_time=2.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                lifecycle_owner="owner-a",
                session_factory=factory,
            )

        assert updated == lw.CompilationPersistenceOutcome.SUCCESS
        from app.services.storage_service import compilation_pdf_key

        assert mock_upload.call_args.args[0] == compilation_pdf_key(job_id, "owner-a")
        assert session.execute.await_count == 2, "terminal UPDATE must follow the upload"

    async def test_terminal_values_are_written(self):
        factory, session = self._session_factory([1])
        await lw._update_compilation_record(
            job_id=str(uuid.uuid4()),
            status="cancelled",
            compilation_time=0.5,
            pdf_bytes=None,
            error_message="cancelled",
            session_factory=factory,
        )

        stmt = session.execute.await_args_list[1].args[0]
        written = {col.name for col, _ in stmt._values.items()}
        params = stmt.compile().params
        assert params["status"] == "cancelled"
        assert params["error_message"] == "cancelled"
        assert "pdf_size" not in written, "pdf_size must not be blanked when there is no PDF"
        assert "pdf_path" not in written

    async def test_failed_upload_marks_row_failed(self):
        factory, session = self._session_factory([1])
        lifecycle_redis = MagicMock()
        lifecycle_redis.hget.side_effect = lambda key, field: {
            "status": "running",
            "owner": "owner-a",
            "lease_until": "9999999999",
        }.get(field)
        with (
            patch("app.services.storage_service.upload_bytes", side_effect=RuntimeError("minio down")),
            patch("app.workers.latex_worker.get_worker_redis", return_value=lifecycle_redis),
        ):
            updated = await lw._update_compilation_record(
                job_id=str(uuid.uuid4()),
                status="completed",
                compilation_time=1.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                lifecycle_owner="owner-a",
                session_factory=factory,
            )

        assert updated == lw.CompilationPersistenceOutcome.STORAGE_FAILURE
        assert session.execute.await_count == 2, "upload failure must persist a visible failed row"
        stmt = session.execute.await_args_list[1].args[0]
        assert stmt.compile().params["status"] == "failed"
        assert stmt.compile().params["error_message"] == "Compiled PDF storage failed"

    async def test_existing_completed_path_is_idempotent_without_reupload(self):
        factory, session = self._session_factory(
            [], status="completed", pdf_path="compilations/job/resume.pdf"
        )
        with patch("app.services.storage_service.upload_bytes") as mock_upload:
            updated = await lw._update_compilation_record(
                job_id="job",
                status="completed",
                compilation_time=1.0,
                pdf_bytes=b"%PDF-1.7",
                error_message=None,
                session_factory=factory,
            )

        assert updated == lw.CompilationPersistenceOutcome.SUCCESS
        mock_upload.assert_not_called()
        assert session.execute.await_count == 1

    async def test_completed_without_pdf_bytes_is_failed(self):
        factory, session = self._session_factory([1])
        updated = await lw._update_compilation_record(
            job_id="missing-pdf",
            status="completed",
            compilation_time=1.0,
            pdf_bytes=None,
            error_message=None,
            session_factory=factory,
        )

        assert updated == lw.CompilationPersistenceOutcome.STORAGE_FAILURE
        stmt = session.execute.await_args_list[1].args[0]
        assert stmt.compile().params["status"] == "failed"


@pytest.mark.asyncio
class TestDurableReconcileBoundary:
    """Legacy failure reconciliation must honor durable arbiter ownership."""

    @pytest.fixture(autouse=True)
    async def _cleanup(self, db_session_factory):
        yield
        async with db_session_factory() as session:
            await session.execute(
                delete(JobFinalization).where(JobFinalization.job_id.like("test_reconcile_%"))
            )
            await session.execute(
                delete(Compilation).where(Compilation.job_id.like("test_reconcile_%"))
            )
            await session.commit()

    @staticmethod
    def _job_id() -> str:
        return f"test_reconcile_{uuid.uuid4().hex}"

    async def _seed(self, db_session_factory, *, owner: str | None, epoch: int, state: str = "pending"):
        job_id = self._job_id()
        async with db_session_factory() as session:
            session.add(
                Compilation(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    status="processing",
                )
            )
            session.add(
                JobFinalization(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    owner_token=owner,
                    owner_epoch=epoch,
                    state=state,
                    terminal_result=state if state in {"failed", "cancelled"} else None,
                    result_payload=(
                        {"success": False, "job_id": job_id, "cancelled": state == "cancelled"}
                        if state in {"failed", "cancelled"}
                        else None
                    ),
                    lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                )
            )
            await session.commit()
        return job_id

    async def _read(self, db_session_factory, job_id: str):
        async with db_session_factory() as session:
            compilation = await session.scalar(
                select(Compilation).where(Compilation.job_id == job_id)
            )
            finalization = await session.scalar(
                select(JobFinalization).where(JobFinalization.job_id == job_id)
            )
            return compilation, finalization

    async def test_stale_owner_cannot_mutate_live_compilation(self, db_session_factory):
        job_id = await self._seed(db_session_factory, owner="replacement", epoch=2)
        outcome = await lw._update_compilation_record(
            job_id=job_id,
            status="failed",
            compilation_time=None,
            pdf_bytes=None,
            error_message="stale",
            lifecycle_owner="old-worker",
            lifecycle_epoch=1,
            session_factory=db_session_factory,
        )
        compilation, finalization = await self._read(db_session_factory, job_id)
        assert outcome is lw.CompilationPersistenceOutcome.STORAGE_FAILURE
        assert compilation.status == "processing"
        assert finalization.state == "pending"

    async def test_absent_owner_cannot_mutate_arbiter_backed_compilation(self, db_session_factory):
        job_id = await self._seed(db_session_factory, owner="replacement", epoch=2)
        outcome = await lw._update_compilation_record(
            job_id=job_id,
            status="failed",
            compilation_time=None,
            pdf_bytes=None,
            error_message="unguarded",
            session_factory=db_session_factory,
        )
        compilation, finalization = await self._read(db_session_factory, job_id)
        assert outcome is lw.CompilationPersistenceOutcome.STORAGE_FAILURE
        assert compilation.status == "processing"
        assert finalization.state == "pending"

    async def test_old_epoch_cannot_mutate_current_owner_compilation(self, db_session_factory):
        job_id = await self._seed(db_session_factory, owner="worker", epoch=4)
        outcome = await lw._update_compilation_record(
            job_id=job_id,
            status="failed",
            compilation_time=None,
            pdf_bytes=None,
            error_message="old epoch",
            lifecycle_owner="worker",
            lifecycle_epoch=3,
            session_factory=db_session_factory,
        )
        compilation, finalization = await self._read(db_session_factory, job_id)
        assert outcome is lw.CompilationPersistenceOutcome.STORAGE_FAILURE
        assert compilation.status == "processing"
        assert finalization.state == "pending"

    async def test_current_owner_commits_canonical_failure_with_compilation(self, db_session_factory):
        job_id = await self._seed(db_session_factory, owner="worker", epoch=4)
        outcome = await lw._update_compilation_record(
            job_id=job_id,
            status="failed",
            compilation_time=1.25,
            pdf_bytes=None,
            error_message="provider details must not become recovery payload",
            lifecycle_owner="worker",
            lifecycle_epoch=4,
            terminal_result={"success": False, "job_id": job_id, "error_code": "worker_failed"},
            session_factory=db_session_factory,
        )
        compilation, finalization = await self._read(db_session_factory, job_id)
        assert outcome is lw.CompilationPersistenceOutcome.SUCCESS
        assert compilation.status == "failed"
        assert finalization.state == "failed"
        assert finalization.terminal_result == "failed"
        assert finalization.result_payload == {
            "job_id": job_id,
            "success": False,
            "recovery_complete": True,
            "pdf_job_id": None,
            "tokens_used": None,
            "page_count": None,
            "slide_count": None,
            "pdf_size": None,
            "compilation_time": None,
            "optimization_time": None,
            "ats_score": None,
            "is_beamer": None,
            "cancelled": None,
            "error_code": "worker_failed",
        }

    @pytest.mark.parametrize("state,expected_status", [("failed", "failed"), ("cancelled", "cancelled")])
    async def test_existing_terminal_evidence_reconciles_without_owner(
        self, db_session_factory, state, expected_status
    ):
        job_id = await self._seed(db_session_factory, owner=None, epoch=0, state=state)
        outcome = await lw._update_compilation_record(
            job_id=job_id,
            status="failed",
            compilation_time=None,
            pdf_bytes=None,
            error_message=None,
            session_factory=db_session_factory,
        )
        compilation, finalization = await self._read(db_session_factory, job_id)
        assert outcome is lw.CompilationPersistenceOutcome.SUCCESS
        assert compilation.status == expected_status
        assert finalization.state == state


def test_saved_reference_library_is_materialized_as_fixed_sidecar(tmp_path):
    from app.workers.latex_worker import write_reference_library

    assert write_reference_library(tmp_path, SAMPLE_BIBTEX := "@article{x, title={X}}")
    assert (tmp_path / "references.bib").read_text() == SAMPLE_BIBTEX


@pytest.mark.parametrize("value", [None, "", "bad\x00bib"])
def test_invalid_reference_library_is_not_materialized(tmp_path, value):
    from app.workers.latex_worker import write_reference_library

    assert write_reference_library(tmp_path, value) is False
    assert not (tmp_path / "references.bib").exists()

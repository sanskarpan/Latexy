"""
Unit tests for app.workers.latex_worker — synchronous Celery task tests.

All external I/O (subprocess, Redis) is mocked.
Tests use Celery eager mode: tasks run synchronously in the same process.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

import app.workers.latex_worker as lw

# ── Celery eager mode ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _celery_eager():
    from app.core.celery_app import celery_app
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


# ── Test helpers ──────────────────────────────────────────────────────────────

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
Hello World
\end{document}
"""


def _make_popen(returncode: int = 0, lines: list | None = None) -> MagicMock:
    """Build a mock subprocess.Popen result."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(lines if lines is not None else ["This is pdflatex output\n"])
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
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_text"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345)),
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

    def test_success_returns_success_true(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["success"] is True

    def test_success_returns_pdf_job_id(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        job_id = str(uuid.uuid4())
        result = lw.compile_latex_task(VALID_LATEX, job_id=job_id)
        assert result["pdf_job_id"] == job_id

    def test_job_started_emitted_first(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert types[0] == "job.started"

    def test_job_started_stage_is_latex_compilation(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        started = [c for c in mock_publish.call_args_list if c.args[1] == "job.started"]
        assert started[0].args[2]["stage"] == "latex_compilation"

    def test_log_line_emitted_for_each_stdout_line(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        lines = ["Line 1\n", "Line 2\n", "Line 3\n"]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, lines)),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
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
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["source"] == "pdflatex"

    def test_error_line_detected(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """Lines containing 'error' keyword should have is_error=True."""
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["! LaTeX Error: undefined\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
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
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
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
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert log_events[0].args[2]["is_error"] is True

    def test_job_completed_emitted(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.completed" in types

    def test_job_completed_has_pdf_job_id(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        job_id = str(uuid.uuid4())
        lw.compile_latex_task(VALID_LATEX, job_id=job_id)
        completed = [c for c in mock_publish.call_args_list if c.args[1] == "job.completed"]
        assert completed[0].args[2]["pdf_job_id"] == job_id

    def test_job_result_stored(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success):
        lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert mock_job_result.call_count == 1

    def test_empty_log_lines_skipped(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        """Empty lines from stdout should not produce log.line events."""
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["\n", "\n", "Real line\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        log_events = [c for c in mock_publish.call_args_list if c.args[1] == "log.line"]
        assert len(log_events) == 1


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

    def test_nonzero_exit_code_returns_success_false(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["error\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["success"] is False

    def test_nonzero_exit_code_error_code_is_latex_error(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
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


# ── Timeout ───────────────────────────────────────────────────────────────────

class TestLatexTimeout:

    def test_timeout_kills_process(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        mock_proc = _make_popen(0, ["slow output\n", "more output\n"])
        # Simulate time advancing past timeout on second iteration
        time_calls = [0.0, 0.0, 9999.0]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=mock_proc),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.time.time", side_effect=lambda: time_calls.pop(0) if time_calls else 9999.0),
            patch("app.workers.latex_worker.settings") as ms,
        ):
            ms.COMPILE_TIMEOUT = 30
            ms.TEMP_DIR = __import__("pathlib").Path("/tmp/latexy_test")
            ms.LATEX_DOCKER_IMAGE = "texlive/texlive:latest"
            ms.ALLOWED_LATEX_COMPILERS = ["pdflatex", "xelatex", "lualatex"]
            ms.DEFAULT_LATEX_COMPILER = "pdflatex"
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))

        assert mock_proc.kill.called

    def test_timeout_emits_job_failed_with_timeout_code(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        time_calls = [0.0, 0.0, 9999.0]
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["output\n", "output2\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.time.time", side_effect=lambda: time_calls.pop(0) if time_calls else 9999.0),
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

    def test_subprocess_exception_emits_job_failed(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=OSError("Docker not found")),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            lw.compile_latex_task.apply(args=[VALID_LATEX], kwargs={"job_id": job_id})

        types = [c.args[1] for c in mock_publish.call_args_list]
        assert "job.failed" in types

    def test_subprocess_exception_error_code_is_internal(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", side_effect=OSError("Docker error")),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            lw.compile_latex_task.apply(args=[VALID_LATEX], kwargs={"job_id": job_id})

        failed = [c for c in mock_publish.call_args_list if c.args[1] == "job.failed"]
        assert failed[-1].args[2]["error_code"] == "internal"


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
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=54321)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] == 2

    def test_page_count_in_job_completed_event(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, [self.PAGE_COUNT_LINE])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=54321)),
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        completed = [c for c in mock_publish.call_args_list if c.args[1] == "job.completed"]
        assert completed[0].args[2]["page_count"] == 2

    def test_page_count_none_when_not_in_logs(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Normal pdflatex output\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=999)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] is None

    def test_single_page_extracted(self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok):
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, [self.SINGLE_PAGE_LINE])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345)),
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
            patch("pathlib.Path.stat", return_value=MagicMock(st_size=3000)),
        ):
            result = lw.compile_latex_task(VALID_LATEX, job_id=str(uuid.uuid4()))
        assert result["page_count"] == 3


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

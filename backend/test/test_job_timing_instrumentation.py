"""
Tests for the job-pipeline timing instrumentation added for #1281
("Compile latency: 37s median -> target <10s").

Covers:
  - compute_queue_wait_seconds / consume_cold_start_seconds (latex_worker.py),
    which are shared by both compile_latex_task and orchestrator's
    optimize_and_compile_task.
  - compile_latex_task emits a single structured "compile_task_timing" log
    line per completion, carrying every phase as a separate field.
  - JsonFormatter actually serializes those fields instead of silently
    dropping them (it only emits keys on an explicit allowlist).

All external I/O (subprocess, Redis, DB) is mocked — no real compile happens.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

import app.workers.latex_worker as lw
from app.core.logging import JsonFormatter

# ── Celery eager mode (matches test_latex_worker.py) ──────────────────────────


@pytest.fixture(autouse=True)
def _celery_eager():
    from app.core.celery_app import celery_app
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
Hello World
\end{document}
"""


def _make_popen(returncode: int = 0, lines: list | None = None) -> MagicMock:
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(lines if lines is not None else ["Compilation OK\n"])
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
    with (
        patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(0, ["Compilation OK\n"])) as m,
        patch("app.workers.latex_worker.subprocess.run", return_value=MagicMock(returncode=0, stdout="Hello World\n")),
        patch("app.workers.latex_worker.shutil.which", return_value="/usr/bin/pdftotext"),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.write_text"),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.stat", return_value=MagicMock(st_size=12345)),
    ):
        yield m


# ── compute_queue_wait_seconds ─────────────────────────────────────────────────


class TestComputeQueueWaitSeconds:

    def test_returns_none_when_meta_missing(self):
        redis_mock = MagicMock()
        redis_mock.get.return_value = None
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            assert lw.compute_queue_wait_seconds(str(uuid.uuid4())) is None

    def test_returns_none_when_redis_raises(self):
        with patch(
            "app.workers.latex_worker.get_worker_redis",
            side_effect=RuntimeError("Worker Redis not initialized"),
        ):
            assert lw.compute_queue_wait_seconds(str(uuid.uuid4())) is None

    def test_returns_none_when_submitted_at_missing_from_meta(self):
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps({"job_id": "x", "job_type": "latex_compilation"})
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            assert lw.compute_queue_wait_seconds(str(uuid.uuid4())) is None

    def test_computes_elapsed_since_submission(self):
        submitted_at = time.time() - 5.0
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps({"submitted_at": submitted_at})
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            wait = lw.compute_queue_wait_seconds(str(uuid.uuid4()))
        assert wait is not None
        assert wait == pytest.approx(5.0, abs=0.5)

    def test_never_returns_negative(self):
        """A submitted_at slightly in the future (clock skew) must clamp to 0, not go negative."""
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps({"submitted_at": time.time() + 10})
        with patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock):
            wait = lw.compute_queue_wait_seconds(str(uuid.uuid4()))
        assert wait == 0.0


# ── consume_cold_start_seconds ─────────────────────────────────────────────────


class TestConsumeColdStartSeconds:

    @pytest.fixture(autouse=True)
    def _reset_process_markers(self, monkeypatch):
        """Isolate each test from the module-level 'first task in this process'
        state, which is otherwise shared (and mutated) by every other test that
        exercises compile_latex_task in this process."""
        monkeypatch.setattr(lw, "_first_task_seen", False)
        monkeypatch.setattr(lw, "_PROCESS_STARTED_AT", time.monotonic() - 3.0)
        yield

    def test_first_call_returns_elapsed_since_process_start(self):
        elapsed = lw.consume_cold_start_seconds()
        assert elapsed is not None
        assert elapsed == pytest.approx(3.0, abs=0.5)

    def test_second_call_returns_none(self):
        first = lw.consume_cold_start_seconds()
        second = lw.consume_cold_start_seconds()
        assert first is not None
        assert second is None

    def test_marks_seen_even_if_never_read(self):
        """Just calling it once (a task started) is enough to consume the marker,
        matching every real call site — none of them call it twice."""
        lw.consume_cold_start_seconds()
        assert lw._first_task_seen is True


# ── compile_latex_task emits a structured timing line ─────────────────────────


class TestCompileTaskTimingLog:

    def test_success_emits_compile_task_timing_with_all_phases(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success
    ):
        job_id = str(uuid.uuid4())
        with patch("app.workers.latex_worker.logger") as mock_logger:
            lw.compile_latex_task(VALID_LATEX, job_id=job_id, compiler="pdflatex")
            timing_calls = [
                c for c in mock_logger.info.call_args_list
                if c.args and c.args[0] == "compile_task_timing"
            ]

        assert len(timing_calls) == 1, "exactly one timing line per task completion"
        extra = timing_calls[0].kwargs["extra"]

        assert extra["job_id"] == job_id
        assert extra["compiler"] == "pdflatex"
        assert extra["outcome"] == "success"
        # queue_wait_seconds / cold_start_seconds are legitimately None here (no
        # job meta seeded, cold-start marker likely already consumed by other
        # tests in this process) — the contract is that the KEY is present, not
        # that it's non-null on every run.
        for key in (
            "queue_wait_seconds", "cold_start_seconds",
            "compile_subprocess_seconds", "reporting_seconds", "total_task_seconds",
        ):
            assert key in extra, f"missing timing field: {key}"

        # The phases we can always compute must be real non-negative numbers.
        assert isinstance(extra["compile_subprocess_seconds"], float)
        assert extra["compile_subprocess_seconds"] >= 0
        assert isinstance(extra["reporting_seconds"], float)
        assert extra["reporting_seconds"] >= 0
        assert isinstance(extra["total_task_seconds"], float)
        assert extra["total_task_seconds"] >= extra["compile_subprocess_seconds"]

    def test_compile_error_emits_timing_with_compile_error_outcome(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok
    ):
        job_id = str(uuid.uuid4())
        with (
            patch("app.workers.latex_worker.subprocess.Popen", return_value=_make_popen(1, ["! Undefined control sequence\n"])),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.logger") as mock_logger,
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=job_id)
            timing_calls = [
                c for c in mock_logger.info.call_args_list
                if c.args and c.args[0] == "compile_task_timing"
            ]

        assert len(timing_calls) == 1
        assert timing_calls[0].kwargs["extra"]["outcome"] == "compile_error"

    def test_queue_wait_and_cold_start_flow_through_when_available(
        self, mock_publish, mock_job_result, mock_cancelled, mock_validate_ok, mock_popen_success, monkeypatch
    ):
        """End-to-end: seed a real :meta key and a fresh cold-start marker, and
        confirm both concrete numbers make it into the logged extra dict."""
        job_id = str(uuid.uuid4())
        submitted_at = time.time() - 2.0
        redis_mock = MagicMock()
        redis_mock.get.return_value = json.dumps({"submitted_at": submitted_at})

        monkeypatch.setattr(lw, "_first_task_seen", False)
        monkeypatch.setattr(lw, "_PROCESS_STARTED_AT", time.monotonic() - 1.5)

        with (
            patch("app.workers.latex_worker.get_worker_redis", return_value=redis_mock),
            patch("app.workers.latex_worker.logger") as mock_logger,
        ):
            lw.compile_latex_task(VALID_LATEX, job_id=job_id)
            timing_calls = [
                c for c in mock_logger.info.call_args_list
                if c.args and c.args[0] == "compile_task_timing"
            ]

        extra = timing_calls[0].kwargs["extra"]
        assert extra["queue_wait_seconds"] == pytest.approx(2.0, abs=0.5)
        assert extra["cold_start_seconds"] == pytest.approx(1.5, abs=0.5)


# ── JsonFormatter actually serializes the new fields ───────────────────────────


class TestJsonFormatterTimingFields:

    def _format(self, **extra) -> dict:
        record = logging.LogRecord(
            name="app.workers.latex_worker",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="compile_task_timing",
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return json.loads(JsonFormatter().format(record))

    def test_all_timing_fields_survive_formatting(self):
        payload = self._format(
            job_id="job-1",
            task_id="task-1",
            compiler="pdflatex",
            outcome="success",
            queue_wait_seconds=8.2,
            cold_start_seconds=None,
            compile_subprocess_seconds=15.5,
            reporting_seconds=0.3,
            total_task_seconds=15.9,
            optimization_seconds=None,
            ats_scoring_seconds=None,
        )
        assert payload["job_id"] == "job-1"
        assert payload["compiler"] == "pdflatex"
        assert payload["outcome"] == "success"
        assert payload["queue_wait_seconds"] == 8.2
        assert payload["compile_subprocess_seconds"] == 15.5
        assert payload["reporting_seconds"] == 0.3
        assert payload["total_task_seconds"] == 15.9
        # None values are the "not applicable this call" case (e.g. cold_start_seconds
        # on a warm container) and must not appear as literal nulls in every line.
        assert "cold_start_seconds" not in payload
        assert "optimization_seconds" not in payload
        assert "ats_scoring_seconds" not in payload

    def test_unset_timing_fields_are_absent_not_null(self):
        """A log call that never set these attrs (e.g. an unrelated log line)
        must not gain spurious timing keys."""
        payload = self._format()
        for key in (
            "queue_wait_seconds", "cold_start_seconds", "compiler", "outcome",
            "compile_subprocess_seconds", "reporting_seconds", "total_task_seconds",
        ):
            assert key not in payload

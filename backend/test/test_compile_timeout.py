"""
Tests for Feature 11: Compile Timeout per Plan.

Covers:
  - get_compile_timeout()        — returns correct seconds per plan
  - compile_latex_task           — emits compile_timeout error_code when deadline exceeded
  - compile_latex_task           — SoftTimeLimitExceeded → compile_timeout event
  - submit_latex_compilation()   — passes correct time_limit to apply_async
  - submit_optimize_and_compile()— passes correct time_limit to apply_async
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from app.core.config import get_compile_timeout, settings
from app.workers.latex_worker import compile_latex_task, submit_latex_compilation
from app.workers.orchestrator import submit_optimize_and_compile

# ---------------------------------------------------------------------------
# 11A — get_compile_timeout helper
# ---------------------------------------------------------------------------


class TestGetCompileTimeout:
    def test_free_plan_returns_30(self):
        assert get_compile_timeout("free") == settings.COMPILE_TIMEOUT_FREE

    def test_basic_plan_returns_120(self):
        assert get_compile_timeout("basic") == settings.COMPILE_TIMEOUT_BASIC

    def test_pro_plan_returns_240(self):
        assert get_compile_timeout("pro") == settings.COMPILE_TIMEOUT_PRO

    def test_byok_plan_returns_240(self):
        assert get_compile_timeout("byok") == settings.COMPILE_TIMEOUT_BYOK

    def test_unknown_plan_falls_back_to_free(self):
        assert get_compile_timeout("enterprise") == settings.COMPILE_TIMEOUT_FREE
        assert get_compile_timeout("") == settings.COMPILE_TIMEOUT_FREE

    def test_free_le_basic_le_pro(self):
        """Timeout tiers should increase with plan level."""
        assert get_compile_timeout("free") <= get_compile_timeout("basic")
        assert get_compile_timeout("basic") <= get_compile_timeout("pro")


# ---------------------------------------------------------------------------
# 11B — compile_latex_task emits compile_timeout on deadline breach
# ---------------------------------------------------------------------------

_VALID_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


def _make_mock_task():
    """Return a mock Celery task self object."""
    mock_self = MagicMock()
    mock_self.request.id = "test-task-id"
    mock_self.request.retries = 0
    mock_self.max_retries = 3
    return mock_self


class TestCompileLatexTaskTimeout:
    """Unit tests for timeout handling inside compile_latex_task.

    Note: Celery bound tasks (bind=True) inject `self` automatically.
    Call compile_latex_task(...) directly with keyword args — no mock_self needed.
    """

    @staticmethod
    def _common_patches():
        """Context managers shared by all task unit tests."""
        return [
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.publish_event"),
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
        ]

    def test_timeout_emits_compile_timeout_error_code(self):
        """When compilation exceeds timeout, error_code must be 'compile_timeout'."""
        def _one_log_line():
            yield "This is pdflatex output\n"

        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.subprocess.Popen") as mock_popen,
            patch("app.workers.latex_worker.publish_event") as mock_publish,
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            # First time.time() call → start_time; second → timeout check exceeds limit
            patch("app.workers.latex_worker.time.time", side_effect=[0.0, 999.0]),
        ):
            mock_proc = MagicMock()
            mock_proc.stdout = _one_log_line()
            mock_popen.return_value = mock_proc

            result = compile_latex_task(
                latex_content=_VALID_LATEX,
                job_id="test-job-timeout",
                user_plan="free",
                timeout_seconds=1,
            )

            assert result["success"] is False
            assert result["error"] == "compile_timeout"

            failed_calls = [
                c for c in mock_publish.call_args_list if c.args[1] == "job.failed"
            ]
            assert len(failed_calls) == 1
            payload = failed_calls[0].args[2]
            assert payload["error_code"] == "compile_timeout"
            assert "upgrade_message" in payload
            assert payload["user_plan"] == "free"

    def test_timeout_message_includes_plan_limit(self):
        """Error message should mention the timeout duration."""
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.subprocess.Popen") as mock_popen,
            patch("app.workers.latex_worker.publish_event") as mock_publish,
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            patch("app.workers.latex_worker.time.time", side_effect=[0.0, 9999.0]),
        ):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["log line\n"])
            mock_popen.return_value = mock_proc

            compile_latex_task(
                latex_content=_VALID_LATEX,
                job_id="test-job-msg",
                user_plan="pro",
                timeout_seconds=30,
            )

            failed_calls = [
                c for c in mock_publish.call_args_list if c.args[1] == "job.failed"
            ]
            assert len(failed_calls) == 1
            payload = failed_calls[0].args[2]
            # Message must mention the timeout value
            assert "30" in payload["error_message"] or "timed out" in payload["error_message"]
            assert payload["user_plan"] == "pro"

    def test_soft_time_limit_exceeded_emits_compile_timeout(self):
        """SoftTimeLimitExceeded must emit compile_timeout error_code."""
        from celery.exceptions import SoftTimeLimitExceeded

        class _SoftLimitStdout:
            """Raising SoftTimeLimitExceeded on iteration simulates Celery's signal."""
            def __iter__(self):
                raise SoftTimeLimitExceeded()

        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.subprocess.Popen") as mock_popen,
            patch("app.workers.latex_worker.publish_event") as mock_publish,
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
        ):
            mock_proc = MagicMock()
            mock_proc.stdout = _SoftLimitStdout()
            mock_popen.return_value = mock_proc

            result = compile_latex_task(
                latex_content=_VALID_LATEX,
                job_id="test-job-soft-limit",
                user_plan="basic",
                timeout_seconds=120,
            )

            assert result["success"] is False
            assert result["error"] == "compile_timeout"

            failed_calls = [
                c for c in mock_publish.call_args_list if c.args[1] == "job.failed"
            ]
            assert len(failed_calls) == 1
            payload = failed_calls[0].args[2]
            assert payload["error_code"] == "compile_timeout"
            assert payload["user_plan"] == "basic"

    def test_explicit_timeout_seconds_overrides_plan_default(self):
        """timeout_seconds kwarg should take precedence over the plan-derived timeout."""
        with (
            patch("app.workers.latex_worker.latex_service.validate_latex_content", return_value=True),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.workers.latex_worker.subprocess.Popen") as mock_popen,
            patch("app.workers.latex_worker.publish_event") as mock_publish,
            patch("app.workers.latex_worker.publish_job_result"),
            patch("app.workers.latex_worker.is_cancelled", return_value=False),
            # start_time=0, loop check=200 → 200 > 60 → triggers timeout
            patch("app.workers.latex_worker.time.time", side_effect=[0.0, 200.0]),
        ):
            mock_proc = MagicMock()
            mock_proc.stdout = iter(["line\n"])
            mock_popen.return_value = mock_proc

            result = compile_latex_task(
                latex_content=_VALID_LATEX,
                job_id="test-job-explicit-timeout",
                user_plan="pro",   # pro = 240s by default
                timeout_seconds=60,  # override to 60s
            )

            assert result["success"] is False
            assert result["error"] == "compile_timeout"

            failed_calls = [
                c for c in mock_publish.call_args_list if c.args[1] == "job.failed"
            ]
            payload = failed_calls[0].args[2]
            assert "60" in payload["error_message"]


# ---------------------------------------------------------------------------
# 11C — submit_latex_compilation passes time_limit to apply_async
# ---------------------------------------------------------------------------


class TestSubmitLatexCompilationTimeLimits:
    def test_free_plan_time_limit(self):
        """submit_latex_compilation with free plan passes time_limit=60, soft_time_limit=45."""
        with patch("app.workers.latex_worker.compile_latex_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_latex_compilation(
                latex_content=_VALID_LATEX,
                job_id="test-job-free",
                user_plan="free",
            )

            _, kwargs = mock_apply.call_args
            assert kwargs["time_limit"] == settings.COMPILE_TIMEOUT_FREE + 30
            assert kwargs["soft_time_limit"] == settings.COMPILE_TIMEOUT_FREE + 15

    def test_pro_plan_time_limit(self):
        """Pro plan should get time_limit=270, soft_time_limit=255."""
        with patch("app.workers.latex_worker.compile_latex_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_latex_compilation(
                latex_content=_VALID_LATEX,
                job_id="test-job-pro",
                user_plan="pro",
            )

            _, kwargs = mock_apply.call_args
            assert kwargs["time_limit"] == settings.COMPILE_TIMEOUT_PRO + 30
            assert kwargs["soft_time_limit"] == settings.COMPILE_TIMEOUT_PRO + 15

    def test_timeout_seconds_override_passes_through(self):
        """Explicit timeout_seconds overrides plan default in apply_async."""
        with patch("app.workers.latex_worker.compile_latex_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_latex_compilation(
                latex_content=_VALID_LATEX,
                job_id="test-job-override",
                user_plan="free",
                timeout_seconds=90,
            )

            _, kwargs = mock_apply.call_args
            assert kwargs["time_limit"] == 90 + 30
            assert kwargs["soft_time_limit"] == 90 + 15

            # Also verify it's passed into the task kwargs
            task_kwargs = kwargs["kwargs"]
            assert task_kwargs["timeout_seconds"] == 90


# ---------------------------------------------------------------------------
# 11D — submit_optimize_and_compile passes time_limit to apply_async
# ---------------------------------------------------------------------------


class TestSubmitOptimizeCompileTimeLimits:
    def test_free_plan_task_time_limit(self):
        """Orchestrator submit for free plan: time_limit = COMPILE_FREE + 180."""
        with patch("app.workers.orchestrator.optimize_and_compile_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_optimize_and_compile(
                latex_content=_VALID_LATEX,
                job_description="software engineer",
                job_id="orch-free",
                user_plan="free",
            )

            _, kwargs = mock_apply.call_args
            expected_limit = settings.COMPILE_TIMEOUT_FREE + 180
            assert kwargs["time_limit"] == expected_limit
            assert kwargs["soft_time_limit"] == expected_limit - 30

    def test_pro_plan_task_time_limit(self):
        """Orchestrator submit for pro plan: time_limit = COMPILE_PRO + 180."""
        with patch("app.workers.orchestrator.optimize_and_compile_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_optimize_and_compile(
                latex_content=_VALID_LATEX,
                job_description="software engineer",
                job_id="orch-pro",
                user_plan="pro",
            )

            _, kwargs = mock_apply.call_args
            expected_limit = settings.COMPILE_TIMEOUT_PRO + 180
            assert kwargs["time_limit"] == expected_limit
            assert kwargs["soft_time_limit"] == expected_limit - 30

    def test_timeout_seconds_passed_into_task_kwargs(self):
        """timeout_seconds kwarg must be forwarded into task kwargs for per-plan enforcement."""
        with patch("app.workers.orchestrator.optimize_and_compile_task") as mock_task:
            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            submit_optimize_and_compile(
                latex_content=_VALID_LATEX,
                job_description="job",
                job_id="orch-timeout",
                user_plan="basic",
            )

            _, kwargs = mock_apply.call_args
            task_kwargs = kwargs["kwargs"]
            assert task_kwargs["timeout_seconds"] == settings.COMPILE_TIMEOUT_BASIC

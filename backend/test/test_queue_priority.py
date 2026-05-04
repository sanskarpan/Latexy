"""Tests for Feature 34 — Compile Queue Priority."""

from unittest.mock import MagicMock, patch

from app.core.celery_app import (
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_LOW,
    TASK_PRIORITY_NORMAL,
    get_task_priority,
)

# Canonical patch path for the feature flag service singleton
_FLAG_PATCH = "app.services.feature_flag_service.feature_flag_service.sync_get_flag"


# ── get_task_priority unit tests ──────────────────────────────────────────────


class TestGetTaskPriority:
    """Unit tests for the plan → priority mapping."""

    def test_free_plan_returns_low_priority(self):
        """free plan maps to TASK_PRIORITY_LOW (1)."""
        with patch(_FLAG_PATCH, return_value=True):
            assert get_task_priority("free") == TASK_PRIORITY_LOW

    def test_pro_plan_returns_high_priority(self):
        """pro plan maps to TASK_PRIORITY_HIGH (9)."""
        with patch(_FLAG_PATCH, return_value=True):
            assert get_task_priority("pro") == TASK_PRIORITY_HIGH

    def test_byok_plan_returns_high_priority(self):
        """byok plan maps to TASK_PRIORITY_HIGH (9)."""
        with patch(_FLAG_PATCH, return_value=True):
            assert get_task_priority("byok") == TASK_PRIORITY_HIGH

    def test_basic_plan_returns_normal_priority(self):
        """basic plan maps to TASK_PRIORITY_NORMAL (5)."""
        with patch(_FLAG_PATCH, return_value=True):
            assert get_task_priority("basic") == TASK_PRIORITY_NORMAL

    def test_unknown_plan_falls_back_to_normal(self):
        """Unrecognised plan string falls back to TASK_PRIORITY_NORMAL."""
        with patch(_FLAG_PATCH, return_value=True):
            assert get_task_priority("enterprise") == TASK_PRIORITY_NORMAL
            assert get_task_priority("") == TASK_PRIORITY_NORMAL

    def test_flag_disabled_gives_everyone_high_priority(self):
        """When task_priority feature flag is off, all plans get TASK_PRIORITY_HIGH."""
        with patch(_FLAG_PATCH, return_value=False):
            assert get_task_priority("free") == TASK_PRIORITY_HIGH
            assert get_task_priority("pro") == TASK_PRIORITY_HIGH

    def test_flag_service_exception_uses_mapping(self):
        """If feature_flag_service raises, fall through to normal priority mapping."""
        with patch(_FLAG_PATCH, side_effect=Exception("redis down")):
            assert get_task_priority("free") == TASK_PRIORITY_LOW
            assert get_task_priority("pro") == TASK_PRIORITY_HIGH


# ── Worker submission priority pass-through tests ─────────────────────────────


class TestSubmitLatexPriority:
    """Verify submit_latex_compilation passes priority to apply_async."""

    def test_free_plan_passes_low_priority_to_apply_async(self):
        from app.workers.latex_worker import submit_latex_compilation

        mock_task = MagicMock()
        with (
            patch("app.workers.latex_worker.compile_latex_task", mock_task),
            patch(_FLAG_PATCH, return_value=True),
        ):
            submit_latex_compilation(
                latex_content=r"\documentclass{article}",
                job_id="test-job-1",
                user_plan="free",
            )

        call_kwargs = mock_task.apply_async.call_args
        assert call_kwargs.kwargs["priority"] == TASK_PRIORITY_LOW

    def test_pro_plan_passes_high_priority_to_apply_async(self):
        from app.workers.latex_worker import submit_latex_compilation

        mock_task = MagicMock()
        with (
            patch("app.workers.latex_worker.compile_latex_task", mock_task),
            patch(_FLAG_PATCH, return_value=True),
        ):
            submit_latex_compilation(
                latex_content=r"\documentclass{article}",
                job_id="test-job-2",
                user_plan="pro",
            )

        call_kwargs = mock_task.apply_async.call_args
        assert call_kwargs.kwargs["priority"] == TASK_PRIORITY_HIGH

    def test_explicit_priority_overrides_plan(self):
        """Caller can override computed priority by passing priority= directly."""
        from app.workers.latex_worker import submit_latex_compilation

        mock_task = MagicMock()
        with patch("app.workers.latex_worker.compile_latex_task", mock_task):
            submit_latex_compilation(
                latex_content=r"\documentclass{article}",
                job_id="test-job-3",
                user_plan="free",
                priority=TASK_PRIORITY_HIGH,  # explicit override
            )

        call_kwargs = mock_task.apply_async.call_args
        assert call_kwargs.kwargs["priority"] == TASK_PRIORITY_HIGH


# ── Broker transport options test ─────────────────────────────────────────────


class TestBrokerTransportOptions:
    """Verify the Celery app is configured to respect Redis priority ordering."""

    def test_broker_transport_options_configured(self):
        from app.core.celery_app import celery_app

        opts = celery_app.conf.broker_transport_options
        assert opts is not None, "broker_transport_options must be set for Redis priority to work"
        assert "priority_steps" in opts
        assert opts["queue_order_strategy"] == "priority"

    def test_task_queue_max_priority_set(self):
        from app.core.celery_app import celery_app

        assert celery_app.conf.task_queue_max_priority == 9

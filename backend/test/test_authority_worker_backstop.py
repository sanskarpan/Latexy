"""No-mutation coverage for the handed-authority admission backstop."""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import Mock, patch

import pytest

from app.core import modal_dispatch
from app.core.redis_authority import AuthorityAdmissionBlocked
from app.workers import job_lifecycle, quota_refund


def _blocked():
    raise AuthorityAdmissionBlocked()


def test_admit_worker_blocks_before_legacy_redis_fast_path():
    redis = Mock()
    with patch("app.core.redis_authority.require_active_authority_sync", side_effect=_blocked):
        with pytest.raises(AuthorityAdmissionBlocked):
            job_lifecycle.admit_worker(redis, "legacy-unmetered", "owner", None)
    redis.exists.assert_not_called()
    redis.eval.assert_not_called()
    redis.hget.assert_not_called()


def test_refund_and_receipt_cleanup_leave_redis_untouched_when_frozen():
    redis = Mock()
    with (
        patch.object(quota_refund, "require_active_authority_sync", side_effect=_blocked),
        patch.object(quota_refund, "get_worker_redis", return_value=redis) as redis_factory,
    ):
        assert quota_refund.refund_quota_once(
            "frozen-job",
            {"dimension": "compilations", "user_id": "u", "period": "202610", "cost": 1},
            expected_dimension="compilations",
        ) is False
        quota_refund.clear_quota_refund_receipt("frozen-job")
    redis_factory.assert_not_called()
    redis.eval.assert_not_called()
    redis.delete.assert_not_called()
    redis.set.assert_not_called()


def test_modal_spawn_checks_authority_before_lazy_provider_import():
    with (
        patch.object(modal_dispatch, "_require_active_authority", side_effect=_blocked),
        patch.dict("sys.modules", {"modal": None}),
    ):
        with pytest.raises(AuthorityAdmissionBlocked):
            modal_dispatch.spawn("run_latex_task", {"job_id": "blocked"})


def test_modal_async_submission_checks_authority_before_calling_submission():
    submission = Mock()
    with patch.object(modal_dispatch, "_require_active_authority", side_effect=_blocked):
        with pytest.raises(AuthorityAdmissionBlocked):
            asyncio.run(modal_dispatch.submit_async(submission, "payload"))
    submission.assert_not_called()


def test_celery_apply_apply_async_and_direct_run_are_guarded(monkeypatch):
    from app.core import celery_app as celery_module

    side_effect = _blocked
    monkeypatch.setattr(celery_module, "_require_active_authority", side_effect)

    class ExampleTask(celery_module.PrimaryAuthorityTask):
        name = "test.authority.backstop"

        def run(self, *args, **kwargs):
            raise AssertionError("task body must not run")

    task = ExampleTask()
    assert getattr(task.run, "__wrapped__", None) is not None
    for call in (
        lambda: task.apply_async(args=("payload",)),
        lambda: task.apply(args=("payload",)),
        lambda: task.run("payload"),
    ):
        with pytest.raises(AuthorityAdmissionBlocked):
            call()


def test_registered_tasks_and_all_public_entrypoints_are_guarded(monkeypatch):
    from celery.signals import task_failure, task_postrun, task_prerun

    from app.core import celery_app as celery_module

    # Import the configured task modules under the isolated test settings; no
    # task is executed and optional provider credentials remain disabled.
    for module_name in celery_module.celery_app.conf.include:
        importlib.import_module(module_name)
    registered = [
        ("app.workers.latex_worker", "compile_latex_task"),
        ("app.workers.llm_worker", "optimize_resume_task"),
        ("app.workers.email_worker", "send_job_completion_email"),
        ("app.workers.cleanup_worker", "cleanup_expired_jobs_task"),
        ("app.workers.ats_worker", "score_resume_ats_task"),
        ("app.workers.orchestrator", "optimize_and_compile_task"),
        ("app.workers.auto_save_worker", "record_auto_save_checkpoint"),
        ("app.workers.cover_letter_worker", "generate_cover_letter_task"),
        ("app.workers.interview_prep_worker", "generate_interview_prep_task"),
        ("app.workers.converter_worker", "convert_document_task"),
        ("app.workers.github_import_worker", "import_github_projects_task"),
        ("app.workers.tracker_notification_worker", "send_tracker_notifications"),
        ("app.core.celery_app", "sample_queue_depths"),
    ]
    tasks = [getattr(importlib.import_module(module_name), attr) for module_name, attr in registered]
    for task in tasks:
        assert isinstance(task, celery_module.PrimaryAuthorityTask)
        assert getattr(task.run, "_latexy_primary_authority_guard", False)

    monkeypatch.setattr(celery_module, "_require_active_authority", _blocked)
    signals = []
    receivers = []

    def record_signal(*args, **kwargs):
        signals.append((args, kwargs))

    for signal in (task_prerun, task_postrun, task_failure):
        signal.connect(record_signal, weak=False)
        receivers.append(signal)
    try:
        for task in tasks:
            for call in (
                lambda task=task: task.apply(args=("payload",)),
                lambda task=task: task.delay("payload"),
                lambda task=task: task.run("payload"),
                lambda task=task: task("payload"),
            ):
                with pytest.raises(AuthorityAdmissionBlocked):
                    call()
        with pytest.raises(AuthorityAdmissionBlocked):
            celery_module.celery_app.send_task("app.workers.email_worker.send_job_completion_email")
    finally:
        for signal in receivers:
            signal.disconnect(record_signal)
    assert signals == []


def test_worker_and_child_startup_abort_before_redis_initialization(monkeypatch):
    from app.core import celery_app as celery_module

    monkeypatch.setattr(celery_module, "_require_active_authority", _blocked)
    prepare = Mock()
    monkeypatch.setattr("app.core.worker_runtime.prepare_worker_runtime", prepare)
    init_redis = Mock()
    monkeypatch.setattr("app.workers.event_publisher.initialize_worker_redis", init_redis)
    with pytest.raises(celery_module.WorkerTerminate):
        celery_module.prepare_worker_parent()
    with pytest.raises(celery_module.WorkerTerminate):
        celery_module.init_worker_process()
    with pytest.raises(celery_module.WorkerTerminate):
        celery_module.prepare_beat()
    prepare.assert_not_called()
    init_redis.assert_not_called()

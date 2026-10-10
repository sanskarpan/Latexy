"""Direct-worker later-pass terminal outcomes use the first-pass lifecycle contract.

All processes, watchdogs, persistence and queue calls are local test doubles.
"""

import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.render_engine import backend, passes
from app.services.render_engine.backend import RendererBackend
from app.workers import latex_worker as worker


@pytest.mark.parametrize("reason", ["cancelled", "timeout", "error"])
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("owned", [True, False])
@pytest.mark.parametrize("user_plan", ["free", "pro"])
def test_later_pass_terminal_outcomes_preserve_lifecycle(
    tmp_path, monkeypatch, reason, accepted, owned, user_plan,
):
    job_id = "direct-convergence-terminal"
    processes = []
    session = SimpleNamespace(close=Mock())
    queue = SimpleNamespace(exists=lambda _: owned)
    admission = Mock(return_value=True)
    result_publication = Mock(return_value=accepted)
    events = Mock(return_value=True)
    reconcile = Mock()
    refund = Mock()
    cache_log = Mock()
    cache_output = Mock()
    finalize = Mock()
    metrics = Mock()

    monkeypatch.setattr(worker.settings, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(backend, "resolve_backend", lambda _: RendererBackend("native", "test-assets", None))
    monkeypatch.setattr(worker, "assert_local_engine_allowed", lambda _: None)
    monkeypatch.setattr(worker, "compute_queue_wait_seconds", lambda _: None)
    monkeypatch.setattr(worker, "get_worker_redis", lambda: queue)
    monkeypatch.setattr(worker, "admit_worker", admission)
    monkeypatch.setattr(worker, "current_owner_epoch", lambda _: 42)
    monkeypatch.setattr(worker, "is_cancelled", lambda _: False)
    monkeypatch.setattr(worker, "compile_cache_key", lambda *_: None)
    monkeypatch.setattr(worker, "restore_compile_cache", lambda *_: None)
    monkeypatch.setattr(worker, "publish_job_result", result_publication)
    monkeypatch.setattr(worker, "publish_event", events)
    monkeypatch.setattr(worker, "reconcile_compilation_record", reconcile)
    monkeypatch.setattr(worker, "_refund_compile_quota_once", refund)
    monkeypatch.setattr(worker, "cache_compile_log", cache_log)
    monkeypatch.setattr(worker, "cache_compile_output", cache_output)
    monkeypatch.setattr(worker, "commit_latex_finalization", finalize)
    monkeypatch.setattr(worker, "record_compile", metrics)
    monkeypatch.setattr(worker, "find_recorder_read_escape", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(passes, "find_recorder_read_escape", lambda *_args, **_kwargs: None)

    def start(_command, **_kwargs):
        number = len(processes) + 1
        log = (
            b"First pass complete\nRerun to get cross-references right\n"
            if number == 1 else b"Second pass diagnostic\n"
        )
        proc = SimpleNamespace(
            stdout=io.BytesIO(log), returncode=0 if number == 1 else 1,
            renderer_session=session, wait=Mock(), kill=Mock(), poll=lambda: 0,
        )
        processes.append(proc)
        return proc

    class Watchdog:
        def __init__(self, proc, **_kwargs):
            self.proc = proc
            self.reason = reason if len(processes) == 2 and reason != "error" else None

        def start(self):
            if self.reason:
                self.proc.kill()
            return self

        def stop(self):
            return self.reason

    monkeypatch.setattr(backend, "start_engine_process", start)
    monkeypatch.setattr(worker, "ProcessWatchdog", Watchdog)
    monkeypatch.setattr(passes, "ProcessWatchdog", Watchdog)
    receipt = {"test": "quota-receipt"}
    result = worker.compile_latex_task.run(
        r"\documentclass{article}\begin{document}Example\end{document}",
        job_id=job_id, compiler="pdflatex", user_plan=user_plan,
        timeout_seconds=30, quota_refund=receipt,
    )

    assert len(processes) == 2, "Exercise the real convergence branch after a successful first pass"
    assert result["success"] is False
    result_publication.assert_called_once_with(job_id, result)
    terminal_events = [call.args for call in events.call_args_list if call.args[1] in {
        "job.failed", "job.cancelled", "job.completed", "job.retrying",
    }]
    assert len(terminal_events) == int(accepted)
    if reason == "cancelled":
        assert result == {"success": False, "job_id": job_id, "cancelled": True}
        if accepted:
            assert terminal_events == [(job_id, "job.cancelled", {})]
        cache_log.assert_called_once_with(
            job_id, "Compilation cancelled before engine output could be validated.",
        )
        assert reconcile.call_args.kwargs["status"] == "cancelled"
        assert reconcile.call_args.kwargs["error_message"] == "cancelled"
        metrics.assert_not_called()
    else:
        expected_error = "compile_timeout" if reason == "timeout" else "Auxiliary compiler pass failed"
        assert result == {"success": False, "job_id": job_id, "error": expected_error}
        assert reconcile.call_args.kwargs["error_message"] == expected_error
        assert reconcile.call_args.kwargs.get("status", "failed") == "failed"
        cache_log.assert_not_called()
        if accepted:
            assert terminal_events[0][1] == "job.failed"
            payload = terminal_events[0][2]
            assert payload["error_code"] == ("compile_timeout" if reason == "timeout" else "render_pass_failed")
            assert payload["retryable"] is False
            if reason == "timeout":
                assert payload["user_plan"] == user_plan
                assert payload["timeout_seconds"] == 30
                assert payload["upgrade_message"] == (
                    "Upgrade to Pro for a 4-minute compile timeout" if user_plan == "free" else None
                )
        if reason == "timeout":
            metrics.assert_called_once()
            assert metrics.call_args.args == ("error",)

    reconcile.assert_called_once()
    persisted = reconcile.call_args.kwargs
    assert persisted["success"] is False
    assert persisted["terminal_result"] == result
    assert persisted["lifecycle_owner"] == (admission.call_args.args[2] if owned else None)
    assert persisted["lifecycle_epoch"] == (42 if owned else None)
    if accepted:
        refund.assert_called_once_with(job_id, receipt)
    else:
        refund.assert_not_called()
    cache_output.assert_not_called()
    finalize.assert_not_called()
    if reason != "error":
        processes[1].kill.assert_called_once()
        assert all(call.args[2].get("line") != "Second pass diagnostic"
                   for call in events.call_args_list if call.args[1] == "log.line")
    assert all(proc.stdout.closed for proc in processes)
    session.close.assert_called_once()
    assert not (tmp_path / job_id).exists()

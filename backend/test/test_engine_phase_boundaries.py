"""Measure initialization, queue and source work without changing execution."""
import ast
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.core import engine_observability as telemetry
from app.core import worker_runtime
from app.core.celery_app import celery_app  # noqa: F401 — initialize task registration first
from app.workers import latex_worker, llm_worker, orchestrator


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_phase_timer_finishes_once_before_later_cleanup(outcome):
    with patch.object(telemetry.time, "perf_counter", side_effect=[10., 10.75]), \
         patch.object(telemetry, "record_phase") as record:
        timer = telemetry.PhaseTimer("source_prepare")
        timer.finish(outcome)
        timer.finish("error")
    record.assert_called_once_with("source_prepare", .75, outcome)


def test_direct_slow_observation_emits_same_bounded_diagnostics_as_span():
    with patch.object(telemetry.ENGINE_PHASE_SECONDS, "labels") as labels, \
         patch.object(telemetry.logger, "info") as log:
        telemetry.record_phase("queue_wait", 2.5)
    labels.assert_called_once_with(phase="queue_wait", outcome="success")
    assert log.call_args.kwargs["extra"] == {
        "phase": "queue_wait", "outcome": "success", "latency_seconds": 2.5,
    }


@pytest.mark.parametrize("phase,seconds,outcome", [
    ("unknown", 3, "success"), ("queue_wait", float("nan"), "success"),
    ("queue_wait", 3, "unknown"), ("queue_wait", .2, "success"),
])
def test_invalid_or_fast_observations_do_not_emit_slow_logs(phase, seconds, outcome):
    with patch.object(telemetry.logger, "info") as log:
        telemetry.record_phase(phase, seconds, outcome)
    log.assert_not_called()


def test_native_preparation_is_measured_once_per_cold_configuration(monkeypatch):
    from app.database.connection import Base

    monkeypatch.setattr(worker_runtime, "import_module", Mock())
    monkeypatch.setattr(Base.registry, "configure", Mock())
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        with patch.object(telemetry, "record_phase") as record:
            worker_runtime.prepare_worker_runtime(False)
            worker_runtime.prepare_worker_runtime(False)
        assert record.call_count == 1
        assert record.call_args.args[0] == "worker_initialization"
        assert record.call_args.args[1] >= 0
        assert record.call_args.args[2] == "success"
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()


def test_failed_preparation_is_measured_and_can_retry(monkeypatch):
    from app.database.connection import Base

    imported = Mock(side_effect=ImportError("synthetic missing dependency"))
    monkeypatch.setattr(worker_runtime, "import_module", imported)
    monkeypatch.setattr(Base.registry, "configure", Mock())
    worker_runtime.prepare_worker_runtime.cache_clear()
    try:
        with patch.object(telemetry, "record_phase") as record:
            with pytest.raises(ImportError):
                worker_runtime.prepare_worker_runtime(False)
            imported.side_effect = None
            worker_runtime.prepare_worker_runtime(False)
        assert [call.args[2] for call in record.call_args_list] == ["error", "success"]
        assert all(call.args[0] == "worker_initialization" for call in record.call_args_list)
    finally:
        worker_runtime.prepare_worker_runtime.cache_clear()


@pytest.mark.parametrize("submitted,expected", [(95, 5.), (105, 0.)])
def test_queue_observation_uses_existing_elapsed_and_skew_clamp(monkeypatch, submitted, expected):
    redis = Mock()
    redis.get.return_value = json.dumps({"submitted_at": submitted})
    monkeypatch.setattr(latex_worker, "get_worker_redis", lambda: redis)
    monkeypatch.setattr(latex_worker.time, "time", lambda: 100.)
    with patch.object(latex_worker, "record_phase") as record:
        assert latex_worker.compute_queue_wait_seconds("synthetic-job") == expected
    record.assert_called_once_with("queue_wait", expected)


def test_missing_queue_timestamp_does_not_fabricate_observation(monkeypatch):
    redis = Mock()
    redis.get.return_value = "{}"
    monkeypatch.setattr(latex_worker, "get_worker_redis", lambda: redis)
    with patch.object(latex_worker, "record_phase") as record:
        assert latex_worker.compute_queue_wait_seconds("synthetic-job") is None
    record.assert_not_called()


@pytest.mark.parametrize("wrapper_name,module,task_name", [
    ("run_latex_task", latex_worker, "compile_latex_task"),
    ("run_orchestrator_task", orchestrator, "optimize_and_compile_task"),
    ("run_llm_task", llm_worker, "optimize_resume_task"),
])
def test_modal_initialization_is_inside_existing_trace_before_task(monkeypatch, wrapper_name, module, task_name):
    from app.core import tracing

    tree = ast.parse((Path(__file__).resolve().parents[1] / "modal_app.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == wrapper_name)
    function.decorator_list = []
    events = []

    @contextmanager
    def traced(_carrier):
        events.append("trace-start")
        try:
            yield
        finally:
            events.append("trace-end")

    monkeypatch.setattr(tracing, "worker_trace", traced)
    task = Mock()
    task.apply.side_effect = lambda **kwargs: events.append(("task", kwargs))
    monkeypatch.setattr(module, task_name, task)
    namespace = {"_init_worker_redis": lambda: events.append("initialize")}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "modal_app.py", "exec"), namespace)
    payload = {"job_id": "synthetic-job", "_trace_context": {"traceparent": "synthetic"}}
    namespace[wrapper_name](payload)
    assert events == ["trace-start", "initialize", ("task", {"kwargs": {"job_id": "synthetic-job"}, "throw": False}), "trace-end"]
    assert "_trace_context" in payload


@pytest.mark.parametrize("valid", [True, False])
def test_combined_source_phase_stops_before_cached_output(monkeypatch, valid):
    from types import SimpleNamespace

    from app.services.render_engine import backend

    monkeypatch.setattr(orchestrator, "publish_event", Mock())
    monkeypatch.setattr(orchestrator.latex_service, "validate_latex_content", lambda _source: valid)
    monkeypatch.setattr(backend, "resolve_backend", lambda _compiler: SimpleNamespace(engine_fingerprint="synthetic"))
    monkeypatch.setattr(orchestrator, "compile_cache_key", lambda *_args: None)
    monkeypatch.setattr(orchestrator, "restore_compile_cache", lambda *_args: {"page_count": 1, "_pdf_bytes": b"%PDF-synthetic"})
    with patch.object(telemetry, "record_phase") as record:
        result = orchestrator._run_latex_stage("synthetic-job", "synthetic source")
    assert result[0] is valid
    phases = [call.args for call in record.call_args_list if call.args[0] == "source_prepare"]
    assert len(phases) == 1
    assert phases[0][2] == ("success" if valid else "error")


@pytest.mark.parametrize("valid", [True, False])
def test_direct_source_phase_records_once_on_cache_or_early_return(monkeypatch, valid):
    from types import SimpleNamespace

    from app.services.render_engine import backend

    redis = Mock()
    redis.get.return_value = None
    redis.exists.return_value = False
    monkeypatch.setattr(latex_worker, "get_worker_redis", lambda: redis)
    monkeypatch.setattr(latex_worker, "admit_worker", lambda *_args: True)
    monkeypatch.setattr(latex_worker, "publish_event", Mock())
    monkeypatch.setattr(latex_worker, "publish_job_result", Mock(return_value=True))
    monkeypatch.setattr(latex_worker, "reconcile_compilation_record", Mock())
    monkeypatch.setattr(latex_worker, "_refund_compile_quota_once", Mock())
    monkeypatch.setattr(latex_worker.latex_service, "validate_latex_content", lambda _source: valid)
    monkeypatch.setattr(backend, "resolve_backend", lambda _compiler: SimpleNamespace(engine_fingerprint="synthetic"))
    monkeypatch.setattr(latex_worker, "compile_cache_key", lambda *_args: None)
    monkeypatch.setattr(latex_worker, "restore_compile_cache", lambda *_args: {"success": True, "page_count": 1, "_pdf_bytes": b"%PDF-synthetic"})
    with patch.object(telemetry, "record_phase") as record:
        result = latex_worker.compile_latex_task("synthetic source", job_id="synthetic-job")
    assert result["success"] is valid
    phases = [call.args for call in record.call_args_list if call.args[0] == "source_prepare"]
    assert len(phases) == 1
    assert phases[0][2] == ("success" if valid else "error")

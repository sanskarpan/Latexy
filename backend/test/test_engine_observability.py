"""Phase telemetry remains bounded and does not alter failures/cancellation."""
import asyncio
from unittest.mock import patch

import pytest

from app.core import tracing
from app.core.engine_observability import ENGINE_PHASE_SECONDS, engine_span, record_phase


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), -1, True, "1", None])
def test_invalid_phase_duration_does_not_create_metric(seconds):
    with patch.object(ENGINE_PHASE_SECONDS, "labels") as labels:
        record_phase("admission", seconds)
        labels.assert_not_called()


def test_arbitrary_labels_never_enter_phase_metrics():
    with patch.object(ENGINE_PHASE_SECONDS, "labels") as labels:
        record_phase("resume/private-job-id", 1)
        record_phase("admission", 1, "private-provider-error")
        labels.assert_not_called()


def test_monotonic_span_preserves_exception_without_diagnostics():
    with patch("app.core.engine_observability.record_phase") as record:
        with pytest.raises(ValueError, match="private"):
            with engine_span("patch_validation"):
                raise ValueError("private source")
        assert record.call_args.args[0] == "patch_validation"
        assert record.call_args.args[1] >= 0
        assert record.call_args.args[2] == "error"


def test_cancelled_span_preserves_cancellation():
    with patch("app.core.engine_observability.record_phase") as record:
        with pytest.raises(asyncio.CancelledError):
            with engine_span("dispatch_call"):
                raise asyncio.CancelledError()
        assert record.call_args.args[2] == "cancelled"


def test_slow_phase_logs_only_fixed_phase_outcome_and_duration():
    with patch("app.core.engine_observability.time.perf_counter", side_effect=[10, 11]), \
         patch("app.core.engine_observability.logger.info") as log:
        with pytest.raises(ValueError):
            with engine_span("cache_lookup"):
                raise ValueError("private source")
    assert log.call_args.kwargs["extra"] == {"phase": "cache_lookup", "outcome": "error", "latency_seconds": 1}
    assert "private" not in str(log.call_args)


def test_worker_trace_drops_baggage_and_detaches_on_error(monkeypatch):
    from opentelemetry import context
    monkeypatch.setattr(tracing, "HAS_OTEL", True)
    monkeypatch.setattr(tracing.settings, "OTEL_ENABLED", True)
    carrier = {"traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
               "tracestate": "safe=value", "baggage": "private=resume", "source": "private"}
    with patch.object(tracing, "extract_trace_context", return_value="context") as extract, \
         patch.object(context, "attach", return_value="token") as attach, \
         patch.object(context, "detach") as detach:
        with pytest.raises(ValueError):
            with tracing.worker_trace(carrier):
                raise ValueError("failure")
        extract.assert_called_once_with({"traceparent": carrier["traceparent"], "tracestate": "safe=value"})
        attach.assert_called_once_with("context")
        detach.assert_called_once_with("token")

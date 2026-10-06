"""OpenTelemetry error spans never export caller/provider exception text."""

from __future__ import annotations

import pytest

from app.core import tracing


def _memory_provider():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.mark.skipif(not tracing.HAS_OTEL, reason="OpenTelemetry is optional")
def test_traced_context_preserves_raise_but_redacts_exception_event(monkeypatch):
    provider, exporter = _memory_provider()
    secret = "SECRET_PROVIDER_RESPONSE"
    monkeypatch.setattr(tracing.settings, "OTEL_ENABLED", True)
    monkeypatch.setattr(tracing.trace, "get_tracer", provider.get_tracer)

    with pytest.raises(ValueError, match=secret):
        with tracing.traced("privacy.test", operation="safe"):
            raise ValueError(secret)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.description == "operation failed"
    assert secret not in repr(span.attributes)
    assert secret not in repr(span.events)


@pytest.mark.skipif(not tracing.HAS_OTEL, reason="OpenTelemetry is optional")
def test_real_celery_instrumentation_failure_span_is_redacted(monkeypatch):
    from celery import Celery
    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    provider, exporter = _memory_provider()
    secret = "SECRET_CELERY_EXCEPTION"
    app = Celery("otel_privacy", broker="memory://", backend="cache+memory://")

    @app.task(name="otel_privacy.fail")
    def fail():
        raise ValueError(secret)

    monkeypatch.setattr(tracing.settings, "OTEL_ENABLED", True)
    tracing._install_celery_privacy_guards()
    instrumentor = CeleryInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    try:
        result = fail.apply(throw=False)
    finally:
        instrumentor.uninstrument()

    assert result.failed()
    spans = exporter.get_finished_spans()
    assert spans
    task_span = next(span for span in spans if span.name.endswith("otel_privacy.fail"))
    assert task_span.status.description == "task failed"
    assert secret not in repr(task_span.attributes)
    assert secret not in repr(task_span.events)

"""
OpenTelemetry setup and helpers.

All opentelemetry imports are wrapped in a try/except so that the module
loads cleanly in environments where the otel packages are not installed
(e.g. the test venv).  When HAS_OTEL is False every public function is a
no-op and current_trace_context() returns an empty dict.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Status, StatusCode, format_span_id, format_trace_id

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

from .config import settings

logger = logging.getLogger(__name__)

_provider_initialized = False
_fastapi_instrumented = False
_celery_instrumented = False
_redis_instrumented = False
_httpx_instrumented = False
_sqlalchemy_instrumented_engines: set[int] = set()


def _parse_resource_attributes() -> Dict[str, str]:
    attributes: Dict[str, str] = {}
    for entry in (settings.OTEL_RESOURCE_ATTRIBUTES or "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        attributes[key.strip()] = value.strip()
    return attributes


def _parse_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for entry in (settings.OTEL_EXPORTER_OTLP_HEADERS or "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers


def setup_telemetry(component: str) -> None:
    """Initialize tracing provider and shared instrumentors for this process."""
    global _provider_initialized, _redis_instrumented

    if not HAS_OTEL or _provider_initialized or not settings.OTEL_ENABLED:
        return

    resource = Resource.create(
        {
            "service.name": f"{settings.OTEL_SERVICE_NAME}-{component}",
            "deployment.environment": settings.normalized_environment,
            **_parse_resource_attributes(),
        }
    )
    provider = TracerProvider(resource=resource)

    exporter_mode = (settings.OTEL_EXPORTER_MODE or "none").strip().lower()
    if exporter_mode == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter_mode == "otlp" and settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                    headers=_parse_headers(),
                )
            )
        )

    trace.set_tracer_provider(provider)

    if not _redis_instrumented:
        RedisInstrumentor().instrument()
        _redis_instrumented = True

    # Outbound HTTP (LLM providers, scraper, embeddings) — optional package, so
    # guard independently: a missing instrumentor must not disable all tracing.
    global _httpx_instrumented
    if not _httpx_instrumented:
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            _httpx_instrumented = True
        except Exception as exc:  # pragma: no cover - optional dep
            logger.debug("httpx instrumentation unavailable", extra={"error_type": type(exc).__name__})

    _provider_initialized = True
    logger.info(
        "telemetry_initialized",
        extra={
            "component": component,
            "otel_mode": exporter_mode,
            "otel_endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT or None,
        },
    )


def instrument_fastapi(app) -> None:
    """Instrument the FastAPI app once."""
    global _fastapi_instrumented
    if not HAS_OTEL or _fastapi_instrumented or not settings.OTEL_ENABLED:
        return
    FastAPIInstrumentor.instrument_app(app)
    _fastapi_instrumented = True


def instrument_celery() -> None:
    """Instrument Celery once for producer/consumer spans."""
    global _celery_instrumented
    _install_celery_privacy_guards()
    if not HAS_OTEL or _celery_instrumented or not settings.OTEL_ENABLED:
        return
    CeleryInstrumentor().instrument()
    _celery_instrumented = True


def _install_celery_privacy_guards() -> None:
    """Keep OpenTelemetry Celery failure spans free of caller-controlled text."""
    if not HAS_OTEL:
        return

    from opentelemetry.instrumentation import celery as celery_instrumentation

    instrumentor = celery_instrumentation.CeleryInstrumentor
    if getattr(instrumentor, "_latexy_privacy_guard", False):
        return

    def safe_trace_failure(*args, **kwargs):
        task = celery_instrumentation.utils.retrieve_task_from_sender(kwargs)
        task_id = celery_instrumentation.utils.retrieve_task_id(kwargs)
        if task is None or task_id is None:
            return
        ctx = celery_instrumentation.utils.retrieve_context(task, task_id)
        if ctx is None:
            return
        span, _, _ = ctx
        if span.is_recording():
            span.set_status(Status(status_code=StatusCode.ERROR, description="task failed"))

    def safe_trace_retry(*args, **kwargs):
        task = celery_instrumentation.utils.retrieve_task_from_sender(kwargs)
        task_id = celery_instrumentation.utils.retrieve_task_id_from_request(kwargs)
        if task is None or task_id is None:
            return
        ctx = celery_instrumentation.utils.retrieve_context(task, task_id)
        if ctx is None:
            return
        span, _, _ = ctx
        if span.is_recording():
            # Preserve a retry span marker without serializing the exception
            # or provider message carried by ``reason``.
            span.set_attribute("celery.retry", True)

    instrumentor._trace_failure = staticmethod(safe_trace_failure)
    instrumentor._trace_retry = staticmethod(safe_trace_retry)
    instrumentor._latexy_privacy_guard = True


def instrument_sqlalchemy(engine) -> None:
    """Instrument a SQLAlchemy engine once."""
    if not HAS_OTEL or not settings.OTEL_ENABLED:
        return
    identity = id(engine)
    if identity in _sqlalchemy_instrumented_engines:
        return
    SQLAlchemyInstrumentor().instrument(engine=engine)
    _sqlalchemy_instrumented_engines.add(identity)


def current_trace_context() -> dict[str, str]:
    """Return current trace identifiers for log enrichment."""
    if not HAS_OTEL:
        return {}
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return {}
    return {
        "trace_id": format_trace_id(context.trace_id),
        "span_id": format_span_id(context.span_id),
    }


@contextmanager
def traced(name: str, **attributes: Any):
    """Context manager creating a custom span (no-op when OTEL is disabled).

    Usage:
        with traced("llm.optimize", model="gpt-4o-mini"):
            ...
    """
    if not HAS_OTEL or not settings.OTEL_ENABLED:
        yield None
        return
    tracer = trace.get_tracer("latexy")
    span = tracer.start_span(name)
    try:
        # ``start_as_current_span`` records exception objects and formats their
        # messages by default.  Activate the span with both error hooks off;
        # the sanitized status below preserves failure observability without
        # exporting source, prompts, credentials, or provider diagnostics.
        with trace.use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
            for key, value in attributes.items():
                if value is not None:
                    try:
                        span.set_attribute(key, value)
                    except Exception:  # pragma: no cover - defensive
                        pass
            try:
                yield span
            except Exception:
                if span.is_recording():
                    span.set_status(Status(status_code=StatusCode.ERROR, description="operation failed"))
                raise
    finally:
        span.end()


def set_span_attributes(**attributes: Any) -> None:
    """Attach attributes to the current span (no-op when OTEL is disabled)."""
    if not HAS_OTEL or not settings.OTEL_ENABLED:
        return
    span = trace.get_current_span()
    for key, value in attributes.items():
        if value is not None:
            try:
                span.set_attribute(key, value)
            except Exception:  # pragma: no cover - defensive
                pass


def inject_trace_context(carrier: dict) -> dict:
    """Inject the current trace context into a carrier dict (for Modal .spawn payloads)."""
    if not HAS_OTEL or not settings.OTEL_ENABLED:
        return carrier
    try:
        from opentelemetry.propagate import inject

        inject(carrier)
    except Exception:  # pragma: no cover - defensive
        pass
    return carrier


def extract_trace_context(carrier: dict):
    """Extract a trace context from a carrier dict (for Modal worker entrypoints)."""
    if not HAS_OTEL or not settings.OTEL_ENABLED:
        return None
    try:
        from opentelemetry.propagate import extract

        return extract(carrier or {})
    except Exception:  # pragma: no cover - defensive
        return None

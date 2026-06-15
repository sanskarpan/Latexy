"""
OpenTelemetry setup and helpers.

All opentelemetry imports are wrapped in a try/except so that the module
loads cleanly in environments where the otel packages are not installed
(e.g. the test venv).  When HAS_OTEL is False every public function is a
no-op and current_trace_context() returns an empty dict.
"""

from __future__ import annotations

import logging
from typing import Dict

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
    from opentelemetry.trace import format_span_id, format_trace_id

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

from .config import settings

logger = logging.getLogger(__name__)

_provider_initialized = False
_fastapi_instrumented = False
_celery_instrumented = False
_redis_instrumented = False
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
    if not HAS_OTEL or _celery_instrumented or not settings.OTEL_ENABLED:
        return
    CeleryInstrumentor().instrument()
    _celery_instrumented = True


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

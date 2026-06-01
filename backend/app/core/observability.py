"""
Observability helpers for request/task context and Prometheus metrics.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_route_path: ContextVar[str | None] = ContextVar("route_path", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
_task_name: ContextVar[str | None] = ContextVar("task_name", default=None)
_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)
_queue_name: ContextVar[str | None] = ContextVar("queue_name", default=None)

HTTP_REQUESTS_TOTAL = Counter(
    "latexy_http_requests_total",
    "Total HTTP requests served by the backend.",
    ["method", "route", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "latexy_http_request_duration_seconds",
    "Latency of HTTP requests served by the backend.",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
CELERY_TASKS_TOTAL = Counter(
    "latexy_celery_tasks_total",
    "Total Celery task executions by task and outcome.",
    ["task_name", "queue", "status"],
)
CELERY_TASK_DURATION_SECONDS = Histogram(
    "latexy_celery_task_duration_seconds",
    "Latency of Celery task executions.",
    ["task_name", "queue"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)
FRONTEND_TELEMETRY_EVENTS_TOTAL = Counter(
    "latexy_frontend_telemetry_events_total",
    "Total frontend telemetry events ingested by the backend.",
    ["kind", "name", "route"],
)
FRONTEND_WEB_VITAL_VALUE = Histogram(
    "latexy_frontend_web_vital_value",
    "Distribution of frontend web vital values by metric and route.",
    ["name", "route"],
    buckets=(1, 10, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)


def _set_if_provided(var: ContextVar[str | None], value: str | None) -> Token[str | None] | None:
    if value is None:
        return None
    return var.set(value)


def set_request_context(request_id: str, route_path: str | None = None) -> list[tuple[ContextVar[str | None], Token[str | None]]]:
    """Set request-scoped context values and return reset tokens."""
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = [(_request_id, _request_id.set(request_id))]
    route_token = _set_if_provided(_route_path, route_path)
    if route_token is not None:
        tokens.append((_route_path, route_token))
    return tokens


def set_route_path(route_path: str | None) -> Token[str | None] | None:
    """Set the normalized route path in context."""
    return _set_if_provided(_route_path, route_path)


def route_path_var() -> ContextVar[str | None]:
    """Return the route-path context variable for reset handling."""
    return _route_path


def set_task_context(
    task_id: str,
    task_name: str,
    queue_name: str | None = None,
    job_id: str | None = None,
) -> list[tuple[ContextVar[str | None], Token[str | None]]]:
    """Set Celery task-scoped context values and return reset tokens."""
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = [
        (_task_id, _task_id.set(task_id)),
        (_task_name, _task_name.set(task_name)),
    ]
    queue_token = _set_if_provided(_queue_name, queue_name)
    if queue_token is not None:
        tokens.append((_queue_name, queue_token))
    job_token = _set_if_provided(_job_id, job_id)
    if job_token is not None:
        tokens.append((_job_id, job_token))
    return tokens


def reset_context(tokens: list[tuple[ContextVar[str | None], Token[str | None]]]) -> None:
    """Reset a list of context variable tokens in reverse order."""
    for var, token in reversed(tokens):
        var.reset(token)


def get_log_context() -> dict[str, str]:
    """Return the current request/task context for structured logging."""
    context: dict[str, str] = {}
    values = {
        "request_id": _request_id.get(),
        "route": _route_path.get(),
        "task_id": _task_id.get(),
        "task_name": _task_name.get(),
        "job_id": _job_id.get(),
        "queue": _queue_name.get(),
    }
    for key, value in values.items():
        if value:
            context[key] = value
    return context


def normalize_route_path(route: Any, fallback_path: str) -> str:
    """Prefer the route template over the concrete request path for metrics."""
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else fallback_path


def record_http_request(method: str, route_path: str, status_code: int, duration_seconds: float) -> None:
    """Record HTTP request counters and latency."""
    status = str(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route_path, status_code=status).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route_path).observe(duration_seconds)


def record_celery_task(task_name: str, queue_name: str, status: str, duration_seconds: float) -> None:
    """Record Celery task counters and latency."""
    CELERY_TASKS_TOTAL.labels(task_name=task_name, queue=queue_name, status=status).inc()
    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name, queue=queue_name).observe(duration_seconds)


def record_frontend_event(kind: str, name: str, route: str, value: float | None = None) -> None:
    """Record ingested frontend telemetry."""
    normalized_route = route or "/unknown"
    FRONTEND_TELEMETRY_EVENTS_TOTAL.labels(kind=kind, name=name, route=normalized_route).inc()
    if kind == "web_vital" and value is not None:
        FRONTEND_WEB_VITAL_VALUE.labels(name=name, route=normalized_route).observe(value)


def request_timer() -> float:
    """Return a high-resolution monotonic timestamp for request timing."""
    return perf_counter()


def elapsed_seconds(start_time: float) -> float:
    """Return elapsed wall-clock seconds since a timer start."""
    return perf_counter() - start_time


def metrics_payload() -> bytes:
    """Return the Prometheus text exposition payload."""
    return generate_latest()


def metrics_content_type() -> str:
    """Return the Prometheus metrics content type."""
    return CONTENT_TYPE_LATEST

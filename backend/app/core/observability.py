"""
Observability helpers for request/task context and Prometheus metrics.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

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

# ── LLM / AI metrics ─────────────────────────────────────────────────────────
# Labelled by provider TYPE and model only (never per-key/per-user) to avoid
# cardinality blow-up and PII leakage.
LLM_REQUESTS_TOTAL = Counter(
    "latexy_llm_requests_total",
    "Total LLM calls by provider, model and outcome.",
    ["provider", "model", "status"],
)
LLM_LATENCY_SECONDS = Histogram(
    "latexy_llm_latency_seconds",
    "LLM operation latency by provider, model and phase (prompt_build|provider_call|total).",
    ["provider", "model", "phase"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 40, 60, 120),
)
LLM_TOKENS_TOTAL = Counter(
    "latexy_llm_tokens_total",
    "Total tokens consumed by LLM calls.",
    ["provider", "model", "kind"],  # kind: prompt|completion|total
)
LLM_COST_USD_TOTAL = Counter(
    "latexy_llm_cost_usd_total",
    "Estimated LLM spend in USD.",
    ["provider", "model"],
)

# ── LaTeX compile metrics ────────────────────────────────────────────────────
COMPILES_TOTAL = Counter(
    "latexy_compiles_total",
    "Total LaTeX compilations by outcome.",
    ["status"],
)
COMPILE_DURATION_SECONDS = Histogram(
    "latexy_compile_duration_seconds",
    "LaTeX compilation duration.",
    ["status"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
COMPILE_PDF_BYTES = Histogram(
    "latexy_compile_pdf_bytes",
    "Size of produced PDFs in bytes.",
    buckets=(1_000, 10_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 5_000_000),
)
COMPILE_PAGES = Histogram(
    "latexy_compile_pages",
    "Page count of produced PDFs.",
    buckets=(1, 2, 3, 4, 5, 8, 12, 20),
)

# ── ATS scoring metrics ──────────────────────────────────────────────────────
ATS_SCORES_TOTAL = Counter(
    "latexy_ats_scores_total",
    "Total ATS scoring runs by scorer and outcome.",
    ["scorer", "status"],
)
ATS_SCORE_DURATION_SECONDS = Histogram(
    "latexy_ats_score_duration_seconds",
    "ATS scoring duration by scorer.",
    ["scorer"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

# ── Business metrics ─────────────────────────────────────────────────────────
JOBS_SUBMITTED_TOTAL = Counter(
    "latexy_jobs_submitted_total",
    "Jobs submitted to the async queue by type and authentication state.",
    ["job_type", "auth"],  # auth: user|anonymous
)
TRIAL_USES_TOTAL = Counter(
    "latexy_trial_uses_total",
    "Anonymous trial uses recorded by outcome.",
    ["outcome"],  # allowed|limit_exceeded|cooldown|blocked
)
BUSINESS_EVENTS_TOTAL = Counter(
    "latexy_business_events_total",
    "Business lifecycle events (signups, subscription changes, etc.).",
    ["event", "detail"],
)

# ── Infrastructure gauges ────────────────────────────────────────────────────
CELERY_QUEUE_DEPTH = Gauge(
    "latexy_celery_queue_depth",
    "Number of pending messages in each Celery queue.",
    ["queue"],
)
DB_POOL_CONNECTIONS = Gauge(
    "latexy_db_pool_connections",
    "SQLAlchemy async engine connection-pool state.",
    ["state"],  # size|checked_out|overflow
)
REDIS_COMMANDS_TOTAL = Counter(
    "latexy_redis_commands_total",
    "Redis commands observed by the application clients.",
    ["role", "status"],  # role: queue|cache; status: success|error
)
REDIS_PROVIDER_ERRORS_TOTAL = Counter(
    "latexy_redis_provider_errors_total",
    "Redis provider errors grouped into actionable, low-cardinality classes.",
    ["role", "kind"],
)
REDIS_DEPENDENCY_UP = Gauge(
    "latexy_redis_dependency_up",
    "Whether the latest Redis command for a dependency role succeeded.",
    ["role"],
)
REDIS_PROVIDER_EXHAUSTED = Gauge(
    "latexy_redis_provider_exhausted",
    "Whether the Redis provider has reported hard request-quota exhaustion.",
    ["role"],
)
REDIS_PROVIDER_MONTHLY_REQUESTS = Gauge(
    "latexy_redis_provider_monthly_requests",
    "Provider-reported Redis requests in the current billing month.",
)
REDIS_PROVIDER_REQUEST_LIMIT = Gauge(
    "latexy_redis_provider_request_limit",
    "Provider-reported Redis request limit for the current billing month.",
)
REDIS_PROVIDER_REQUEST_UTILIZATION = Gauge(
    "latexy_redis_provider_request_utilization_ratio",
    "Provider-reported monthly Redis requests divided by the request limit.",
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


def classify_redis_error(exc: BaseException) -> str:
    """Map provider/client errors to stable alert labels without leaking details."""
    message = str(exc).lower()
    if "max requests limit exceeded" in message or "request quota" in message:
        return "request_quota_exhausted"
    if "max commands per second" in message or "throttl" in message:
        return "throttled"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if any(marker in message for marker in (
        "connection refused",
        "connection reset",
        "connection closed",
        "name or service not known",
        "nodename nor servname provided",
    )):
        return "connection"
    return "other"


def record_redis_command(role: str, error: BaseException | None = None) -> str | None:
    """Record one Redis command and return its error class, if any.

    This is deliberately local Prometheus instrumentation; it never performs an
    extra Redis operation merely to count an operation, which would accelerate a
    request-capped provider toward exhaustion.
    """
    normalized_role = role if role in {"queue", "cache"} else "unknown"
    if error is None:
        REDIS_COMMANDS_TOTAL.labels(role=normalized_role, status="success").inc()
        REDIS_DEPENDENCY_UP.labels(role=normalized_role).set(1)
        REDIS_PROVIDER_EXHAUSTED.labels(role=normalized_role).set(0)
        return None

    kind = classify_redis_error(error)
    REDIS_COMMANDS_TOTAL.labels(role=normalized_role, status="error").inc()
    REDIS_PROVIDER_ERRORS_TOTAL.labels(role=normalized_role, kind=kind).inc()
    if kind in {"request_quota_exhausted", "timeout", "connection"}:
        REDIS_DEPENDENCY_UP.labels(role=normalized_role).set(0)
    if kind == "request_quota_exhausted":
        REDIS_PROVIDER_EXHAUSTED.labels(role=normalized_role).set(1)
    return kind


def set_redis_capacity_metrics(monthly_requests: int, request_limit: int) -> None:
    """Publish provider-level capacity data obtained from the management API."""
    requests = max(0, int(monthly_requests))
    limit = max(0, int(request_limit))
    REDIS_PROVIDER_MONTHLY_REQUESTS.set(requests)
    REDIS_PROVIDER_REQUEST_LIMIT.set(limit)
    REDIS_PROVIDER_REQUEST_UTILIZATION.set(requests / limit if limit else 0)


def _as_number(value: Any) -> float | None:
    """Coerce a value to float, or None if it is not a real finite number.

    Guards the metric layer against non-numeric inputs (e.g. mock usage objects,
    a provider returning an unexpected usage payload) so instrumentation can
    never raise into a request/task path.
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):  # NaN/inf
        return None
    return numeric


def record_llm_call(
    provider: str,
    model: str,
    status: str,
    *,
    total_seconds: float | None = None,
    prompt_build_seconds: float | None = None,
    provider_call_seconds: float | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Record a single LLM call: outcome, phase latencies, tokens and cost."""
    provider = provider or "unknown"
    model = model or "unknown"
    LLM_REQUESTS_TOTAL.labels(provider=provider, model=model, status=status).inc()
    for phase, seconds in (
        ("total", _as_number(total_seconds)),
        ("prompt_build", _as_number(prompt_build_seconds)),
        ("provider_call", _as_number(provider_call_seconds)),
    ):
        if seconds is not None:
            LLM_LATENCY_SECONDS.labels(provider=provider, model=model, phase=phase).observe(max(0.0, seconds))
    for kind, tokens in (
        ("prompt", _as_number(prompt_tokens)),
        ("completion", _as_number(completion_tokens)),
        ("total", _as_number(total_tokens)),
    ):
        if tokens and tokens > 0:
            LLM_TOKENS_TOTAL.labels(provider=provider, model=model, kind=kind).inc(tokens)
    cost = _as_number(cost_usd)
    if cost and cost > 0:
        LLM_COST_USD_TOTAL.labels(provider=provider, model=model).inc(cost)


def record_compile(status: str, duration_seconds: float | None = None, pdf_bytes: int | None = None, pages: int | None = None) -> None:
    """Record a LaTeX compilation outcome and artifact metrics."""
    COMPILES_TOTAL.labels(status=status).inc()
    duration = _as_number(duration_seconds)
    if duration is not None:
        COMPILE_DURATION_SECONDS.labels(status=status).observe(max(0.0, duration))
    size = _as_number(pdf_bytes)
    if size and size > 0:
        COMPILE_PDF_BYTES.observe(size)
    page_count = _as_number(pages)
    if page_count and page_count > 0:
        COMPILE_PAGES.observe(page_count)


def record_ats_score(scorer: str, status: str, duration_seconds: float | None = None) -> None:
    """Record an ATS scoring run."""
    ATS_SCORES_TOTAL.labels(scorer=scorer, status=status).inc()
    if duration_seconds is not None:
        ATS_SCORE_DURATION_SECONDS.labels(scorer=scorer).observe(max(0.0, duration_seconds))


def record_job_submitted(job_type: str, authenticated: bool) -> None:
    """Record a job submission for product KPIs."""
    JOBS_SUBMITTED_TOTAL.labels(job_type=job_type or "unknown", auth="user" if authenticated else "anonymous").inc()


def record_trial_use(outcome: str) -> None:
    """Record an anonymous trial-use outcome."""
    TRIAL_USES_TOTAL.labels(outcome=outcome or "unknown").inc()


def record_business_event(event: str, detail: str = "") -> None:
    """Record a business lifecycle event (signup, subscription change, ...)."""
    BUSINESS_EVENTS_TOTAL.labels(event=event, detail=detail or "none").inc()


def set_queue_depth(queue: str, depth: int) -> None:
    """Set the current pending-message depth for a Celery queue."""
    CELERY_QUEUE_DEPTH.labels(queue=queue).set(depth)


def set_db_pool_stats(size: int, checked_out: int, overflow: int) -> None:
    """Publish SQLAlchemy connection-pool saturation."""
    DB_POOL_CONNECTIONS.labels(state="size").set(size)
    DB_POOL_CONNECTIONS.labels(state="checked_out").set(checked_out)
    DB_POOL_CONNECTIONS.labels(state="overflow").set(overflow)


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

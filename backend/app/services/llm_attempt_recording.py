"""Privacy-safe recording helpers for per-attempt LLM latency telemetry.

Call sites pass bounded identifiers and an optional exception; this module
normalizes both into the small allowlisted vocabularies enforced by the
``llm_call_attempts`` table. Raw exception messages, prompts, documents, user
identifiers and API keys are never persisted.

``record_llm_attempt`` is the async, transaction-joining entry point used by
tests and request-scoped code. ``record_llm_attempt_best_effort`` is the
fire-and-forget bridge for synchronous Celery workers: telemetry must never
change a job's terminal outcome, so every persistence failure is swallowed and
logged without payload details.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from typing import Any

from ..core.config import PLAN_FAMILY_ALIASES
from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

STATUSES = frozenset({"success", "error", "timeout", "cancelled"})
RETRY_REASONS = frozenset(
    {
        "none",
        "timeout",
        "rate_limit",
        "connection",
        "provider_error",
        "empty_output",
        "truncated",
        "invalid_response",
        "cancelled",
        "unknown",
    }
)
ERROR_CLASSES = frozenset(
    {
        "timeout",
        "rate_limit",
        "connection",
        "provider_error",
        "invalid_response",
        "cancelled",
        "unknown",
    }
)

_DEFAULT = "unknown"
_MAX_PROVIDER = 64
_MAX_MODEL = 160
_MAX_FEATURE = 120
_MAX_PLAN = 50


def _text(value: Any, limit: int, default: str = _DEFAULT) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized[:limit]


def _finite_ms(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return round(number, 3)


def run_reference(run_id: Any) -> str | None:
    """Return a stable opaque reference, never the original job/user id."""
    if run_id is None:
        return None
    candidate = str(run_id).strip()
    if not candidate:
        return None
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:32]


def classify_exception(
    exc: BaseException | None,
    *,
    status: str | None = None,
) -> tuple[str, str | None, str]:
    """Map an exception to (status, error_class, retry_reason) allowlists.

    Only the exception type name and a few generic substrings are inspected;
    the message itself never leaves this function.
    """
    if status in STATUSES and exc is None:
        return status, None, "none"
    if exc is None:
        return (status if status in STATUSES else "error"), None, "none"

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if status == "cancelled" or "cancel" in name:
        return "cancelled", "cancelled", "cancelled"
    if (
        "softtimelimit" in name
        or "timeout" in name
        or "timed out" in message
        or "deadline" in message
    ):
        return "timeout", "timeout", "timeout"
    if "ratelimit" in name or "rate limit" in message or "too many requests" in message:
        return "error", "rate_limit", "rate_limit"
    if any(
        marker in name
        for marker in ("connection", "connect", "network", "transport")
    ):
        return "error", "connection", "connection"
    if any(
        marker in name
        for marker in ("jsondecode", "validation", "parse", "valueerror")
    ):
        return "error", "invalid_response", "invalid_response"
    return "error", "provider_error", "provider_error"


def _retry_reason(value: Any) -> str:
    normalized = _text(value, 64, "none")
    return normalized if normalized in RETRY_REASONS else "none"


def _error_class(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _text(value, 64, "unknown")
    return normalized if normalized in ERROR_CLASSES else "unknown"


def _plan(value: Any) -> str:
    normalized = _text(value, _MAX_PLAN, _DEFAULT)
    if normalized == _DEFAULT:
        return normalized
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)


def build_attempt(
    *,
    provider: Any,
    model: Any,
    feature: Any,
    plan: Any,
    run_id: Any = None,
    run_ref: Any = None,
    attempt_number: Any = 1,
    status: Any = "success",
    retry_reason: Any = None,
    error_class: Any = None,
    latency_ms: Any = None,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    """Normalize arbitrary caller input into a safe row payload."""
    normalized_status, inferred_class, inferred_reason = classify_exception(
        exc, status=str(status) if status is not None else None
    )
    if normalized_status == "success":
        reason = "none"
    elif retry_reason is not None:
        reason = _retry_reason(retry_reason)
    else:
        reason = inferred_reason
    return {
        "provider": _text(provider, _MAX_PROVIDER, "unknown"),
        "model": _text(model, _MAX_MODEL, "unknown"),
        "feature": _text(feature, _MAX_FEATURE, "unknown"),
        "plan": _plan(plan),
        "run_ref": run_reference(run_ref if run_ref is not None else run_id),
        "attempt_number": max(1, int(attempt_number)) if isinstance(attempt_number, int) else 1,
        "status": normalized_status,
        "retry_reason": reason,
        "error_class": _error_class(error_class) if error_class is not None else inferred_class,
        "latency_ms": _finite_ms(latency_ms),
    }


async def record_llm_attempt(db: Any, **kwargs: Any) -> models.LLMCallAttempt:
    """Add one attempt row to the caller's transaction."""
    payload = build_attempt(**kwargs)
    row = models.LLMCallAttempt(**payload)
    db.add(row)
    await db.flush()
    return row


async def _write_best_effort(payload: dict[str, Any]) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from ..utils.db_url import resolve_database_url

    database_url = resolve_database_url()
    if not database_url:
        return
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            session.add(models.LLMCallAttempt(**payload))
            await session.commit()
    finally:
        await engine.dispose()


def record_llm_attempt_best_effort(**kwargs: Any) -> None:
    """Persist an attempt from a synchronous worker without ever failing it."""
    try:
        payload = build_attempt(**kwargs)
        asyncio.run(_write_best_effort(payload))
    except RuntimeError:
        # Already inside an event loop (e.g. an async test/route): skip rather
        # than block the loop or spawn a competing engine.
        logger.debug("llm_attempt_record_skipped_running_loop")
    except Exception as exc:
        logger.warning(
            "llm_attempt_record_failed",
            extra={"error_type": type(exc).__name__},
        )

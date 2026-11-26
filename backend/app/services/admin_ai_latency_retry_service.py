"""Admin-only AI latency percentiles and retry rates.

The source of truth is the append-only ``llm_call_attempts`` ledger: one row per
provider attempt, written by the LLM workers through the privacy-safe recorder.
Percentiles use PostgreSQL ``percentile_cont`` over the same filtered rows that
produce the attempt/status/retry totals, so every dimension reconciles to the
reported call counts.

The response is aggregate-only. No prompts, document content, raw provider
errors, run references, user identifiers or per-row records are returned. Small
groups remain visible for early regression detection but are marked ``sparse``
rather than being presented as representative; the ledger deliberately stores
no user dimension, so a distinct-user suppression rule cannot be applied and is
reported as such.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models

LLMCallAttempt = models.LLMCallAttempt

SPARSE_BUCKET_SAMPLES = 5
MAX_BREAKDOWN_GROUPS = 50
DURATION_UNIT = "milliseconds"

STATUS_FILTERS = {
    "successes": LLMCallAttempt.status == "success",
    "errors": LLMCallAttempt.status == "error",
    "timeouts": LLMCallAttempt.status == "timeout",
    "cancelled": LLMCallAttempt.status == "cancelled",
}
RETRIED_CONDITION = LLMCallAttempt.retry_reason != "none"

RETRY_REASON_LABELS = {
    "timeout": "Timeout",
    "rate_limit": "Rate limit",
    "connection": "Connection",
    "provider_error": "Provider error",
    "empty_output": "Empty output",
    "truncated": "Truncated output",
    "invalid_response": "Invalid response",
    "cancelled": "Cancelled",
    "unknown": "Unknown",
}

DIMENSIONS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("provider", (LLMCallAttempt.provider,)),
    ("model", (LLMCallAttempt.provider, LLMCallAttempt.model)),
    ("feature", (LLMCallAttempt.feature,)),
    ("plan", (LLMCallAttempt.plan,)),
)


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _number(value: Any) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    return round(number, 3) if math.isfinite(number) else None


def _rate(value: int, total: int) -> float:
    return round(value / total * 100, 2) if total else 0.0


def _normalize_filter(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized[:limit] if normalized else None


def _normalize_plan(value: Optional[str]) -> Optional[str]:
    normalized = _normalize_filter(value, 50)
    if normalized is None:
        return None
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)


def _percentile(quantile: float):
    return func.percentile_cont(quantile).within_group(LLMCallAttempt.latency_ms)


def _metric_columns() -> list[Any]:
    return [
        func.count().label("attempts"),
        func.count(func.distinct(LLMCallAttempt.run_ref)).label("runs"),
        *[
            func.count().filter(condition).label(name)
            for name, condition in STATUS_FILTERS.items()
        ],
        func.count()
        .filter(LLMCallAttempt.status == "success", LLMCallAttempt.attempt_number == 1)
        .label("first_attempt_successes"),
        func.count().filter(RETRIED_CONDITION).label("retried_attempts"),
        func.count(LLMCallAttempt.latency_ms).label("latency_samples"),
        _percentile(0.5).label("p50"),
        _percentile(0.95).label("p95"),
        _percentile(0.99).label("p99"),
        func.avg(LLMCallAttempt.latency_ms).label("mean"),
        func.max(LLMCallAttempt.latency_ms).label("max"),
    ]


def _summary(row: Any, sparse_threshold: int) -> dict[str, Any]:
    attempts = int(row.attempts or 0)
    successes = int(row.successes or 0)
    errors = int(row.errors or 0)
    timeouts = int(row.timeouts or 0)
    cancelled = int(row.cancelled or 0)
    retried = int(row.retried_attempts or 0)
    failures = errors + timeouts + cancelled
    retry_rate = _rate(retried, attempts)
    success_rate = _rate(successes, attempts)
    error_rate = _rate(errors, attempts)
    timeout_rate = _rate(timeouts, attempts)
    failure_rate = _rate(failures, attempts)
    return {
        "attempts": attempts,
        "runs": int(row.runs or 0),
        "successes": successes,
        "errors": errors,
        "timeouts": timeouts,
        "cancelled": cancelled,
        "retried_attempts": retried,
        "first_attempt_successes": int(row.first_attempt_successes or 0),
        "retry_rate": retry_rate,
        "success_rate": success_rate,
        "error_rate": error_rate,
        "timeout_rate": timeout_rate,
        "failure_rate": failure_rate,
        "retry_rate_pct": retry_rate,
        "success_rate_pct": success_rate,
        "error_rate_pct": error_rate,
        "timeout_rate_pct": timeout_rate,
        "failure_rate_pct": failure_rate,
        "first_attempt_success_rate_pct": _rate(
            int(row.first_attempt_successes or 0), attempts
        ),
        "latency_samples": int(row.latency_samples or 0),
        "p50_ms": _number(row.p50),
        "p95_ms": _number(row.p95),
        "p99_ms": _number(row.p99),
        "mean_ms": _number(row.mean),
        "max_ms": _number(row.max),
        "sparse": attempts < sparse_threshold,
        "sample_status": "insufficient_samples" if attempts < sparse_threshold else "ok",
    }


def _base_filters(
    start: datetime,
    end: datetime,
    plan: Optional[str],
    provider: Optional[str],
    model: Optional[str],
    feature: Optional[str],
) -> tuple[Any, ...]:
    filters: list[Any] = [
        LLMCallAttempt.occurred_at >= start,
        LLMCallAttempt.occurred_at < end,
    ]
    if plan is not None:
        filters.append(LLMCallAttempt.plan == plan)
    if provider is not None:
        filters.append(LLMCallAttempt.provider == provider)
    if model is not None:
        filters.append(LLMCallAttempt.model == model)
    if feature is not None:
        filters.append(LLMCallAttempt.feature == feature)
    return tuple(filters)


def _bucket_labels(columns: tuple[Any, ...], row: Any) -> tuple[str, str, dict[str, Any]]:
    if len(columns) == 2:
        provider = str(row[0])
        model = str(row[1])
        return f"{provider}/{model}", f"{provider}/{model}", {
            "provider": provider,
            "model": model,
        }
    value = str(row[0])
    return value, value, {}


async def _dimension_buckets(
    db: AsyncSession,
    dimension: str,
    columns: tuple[Any, ...],
    filters: tuple[Any, ...],
    sparse_threshold: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total_groups = int(
        (
            await db.execute(
                select(func.count()).select_from(
                    select(*columns).where(*filters).group_by(*columns).subquery()
                )
            )
        ).scalar()
        or 0
    )
    rows = (
        await db.execute(
            select(*columns, *_metric_columns())
            .where(*filters)
            .group_by(*columns)
            .order_by(func.count().desc(), *columns)
            .limit(MAX_BREAKDOWN_GROUPS + 1)
        )
    ).all()
    truncated = len(rows) > MAX_BREAKDOWN_GROUPS
    rows = rows[:MAX_BREAKDOWN_GROUPS]

    buckets: list[dict[str, Any]] = []
    returned_attempts = 0
    for row in rows:
        value, label, extra = _bucket_labels(columns, row)
        summary = _summary(row, sparse_threshold)
        returned_attempts += summary["attempts"]
        buckets.append(
            {
                "dimension": dimension,
                "value": value,
                "label": label,
                **extra,
                **summary,
            }
        )

    buckets.sort(key=lambda bucket: (-bucket["attempts"], bucket["label"]))
    total_attempts = int(
        (await db.execute(select(func.count()).select_from(LLMCallAttempt).where(*filters))).scalar()
        or 0
    )
    metadata = {
        "groups": total_groups,
        "returned_groups": len(buckets),
        "returned_attempts": returned_attempts,
        "truncated_groups": max(0, total_groups - len(buckets)),
        "truncated_attempts": max(0, total_attempts - returned_attempts),
        "truncated": truncated,
        "max_groups": MAX_BREAKDOWN_GROUPS,
    }
    return buckets, metadata


async def _retry_reason_rows(
    db: AsyncSession, filters: tuple[Any, ...], total_attempts: int
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                LLMCallAttempt.retry_reason,
                func.count().label("attempts"),
                func.count(func.distinct(LLMCallAttempt.run_ref)).label("runs"),
            )
            .where(*filters, RETRIED_CONDITION)
            .group_by(LLMCallAttempt.retry_reason)
            .order_by(func.count().desc(), LLMCallAttempt.retry_reason)
        )
    ).all()
    return [
        {
            "reason": str(row.retry_reason),
            "label": RETRY_REASON_LABELS.get(str(row.retry_reason), "Other"),
            "attempts": int(row.attempts or 0),
            "runs": int(row.runs or 0),
            "share_pct": _rate(int(row.attempts or 0), total_attempts),
        }
        for row in rows
    ]


async def _status_rows(
    db: AsyncSession, filters: tuple[Any, ...], total_attempts: int
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                LLMCallAttempt.status,
                func.count().label("attempts"),
                func.count(func.distinct(LLMCallAttempt.run_ref)).label("runs"),
            )
            .where(*filters)
            .group_by(LLMCallAttempt.status)
            .order_by(func.count().desc(), LLMCallAttempt.status)
        )
    ).all()
    return [
        {
            "status": str(row.status),
            "attempts": int(row.attempts or 0),
            "runs": int(row.runs or 0),
            "share_pct": _rate(int(row.attempts or 0), total_attempts),
        }
        for row in rows
    ]


async def _missing_dimensions(
    db: AsyncSession, filters: tuple[Any, ...]
) -> dict[str, int]:
    row = (
        await db.execute(
            select(
                func.count()
                .filter(LLMCallAttempt.provider == "unknown")
                .label("provider"),
                func.count()
                .filter(
                    or_(
                        LLMCallAttempt.provider == "unknown",
                        LLMCallAttempt.model == "unknown",
                    )
                )
                .label("model"),
                func.count()
                .filter(LLMCallAttempt.feature == "unknown")
                .label("feature"),
                func.count()
                .filter(LLMCallAttempt.plan == "unknown")
                .label("plan"),
            ).where(*filters)
        )
    ).one()
    return {
        "provider": int(row.provider or 0),
        "model": int(row.model or 0),
        "feature": int(row.feature or 0),
        "plan": int(row.plan or 0),
    }


async def ai_latency_retry_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: Optional[str] = None,
    feature: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    sparse_threshold: int = SPARSE_BUCKET_SAMPLES,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return p50/p95/p99 latency, retry rate and timeout/error rates."""
    days = max(1, min(int(days), 365))
    sparse_threshold = max(1, min(int(sparse_threshold), 1000))
    now = _utc(now)
    today = now.date()
    start_day = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)

    plan_filter = _normalize_plan(plan)
    feature_filter = _normalize_filter(feature, 120)
    provider_filter = _normalize_filter(provider, 64)
    model_filter = _normalize_filter(model, 160)
    filters = _base_filters(
        start_at,
        end_at,
        plan_filter,
        provider_filter,
        model_filter,
        feature_filter,
    )

    overall_row = (
        await db.execute(select(*_metric_columns()).where(*filters))
    ).one()
    overall = _summary(overall_row, sparse_threshold)

    buckets: dict[str, list[dict[str, Any]]] = {}
    cardinality: dict[str, dict[str, Any]] = {}
    for dimension, columns in DIMENSIONS:
        dimension_rows, metadata = await _dimension_buckets(
            db, dimension, columns, filters, sparse_threshold
        )
        buckets[dimension] = dimension_rows
        cardinality[dimension] = metadata

    retry_reasons = await _retry_reason_rows(db, filters, overall["attempts"])
    statuses = await _status_rows(db, filters, overall["attempts"])
    missing_dimensions = await _missing_dimensions(db, filters)

    retry_reason_attempts = sum(row["attempts"] for row in retry_reasons)
    status_attempts = sum(row["attempts"] for row in statuses)
    dimension_attempts = {
        dimension: cardinality[dimension]["returned_attempts"]
        + cardinality[dimension]["truncated_attempts"]
        for dimension in buckets
    }
    dimension_reconciled = {
        dimension: (
            cardinality[dimension]["returned_attempts"]
            + cardinality[dimension]["truncated_attempts"]
            == overall["attempts"]
        )
        for dimension in buckets
    }

    return {
        "days": days,
        "window": {"start": start_at.isoformat(), "end": end_at.isoformat()},
        "filters": {
            "plan": plan_filter,
            "feature": feature_filter,
            "provider": provider_filter,
            "model": model_filter,
        },
        "duration_unit": DURATION_UNIT,
        "sparse_threshold": sparse_threshold,
        "max_groups": MAX_BREAKDOWN_GROUPS,
        "overall": overall,
        "by_provider": buckets["provider"],
        "by_model": buckets["model"],
        "by_feature": buckets["feature"],
        "by_plan": buckets["plan"],
        "retry_reasons": retry_reasons,
        "statuses": statuses,
        "missing_dimensions": missing_dimensions,
        "cardinality": cardinality,
        "totals": {
            "attempts": overall["attempts"],
            "runs": overall["runs"],
            "latency_samples": overall["latency_samples"],
            "retried_attempts": overall["retried_attempts"],
            "errors": overall["errors"],
            "timeouts": overall["timeouts"],
            "successes": overall["successes"],
        },
        "reconciliation": {
            "total_attempts": overall["attempts"],
            "dimension_attempts": dimension_attempts,
            "dimension_reconciled": dimension_reconciled,
            "retry_reason_attempts": retry_reason_attempts,
            "retried_attempts": overall["retried_attempts"],
            "retry_reasons_reconcile": retry_reason_attempts
            == overall["retried_attempts"],
            "status_attempts": status_attempts,
            "statuses_reconcile": status_attempts == overall["attempts"],
            "all_dimensions_reconcile": all(dimension_reconciled.values()),
            "note": (
                "Each attempt belongs to exactly one provider, model, feature and "
                "plan bucket. Truncated high-cardinality groups are counted in "
                "truncated_attempts so totals still reconcile to raw attempts."
            ),
        },
        "suppression": {
            "minimum_group_size": sparse_threshold,
            "user_dimension_included": False,
            "user_suppression_applicable": False,
            "suppressed_groups": 0,
            "rule": (
                "The ledger stores no user dimension, so five-distinct-user "
                "suppression cannot be evaluated; responses are aggregate-only and "
                "groups below the sample threshold are explicitly marked sparse."
            ),
        },
        "privacy": {
            "aggregate_only": True,
            "per_user_rows": False,
            "per_row_records": False,
            "content_fields_read": [],
            "fields_excluded": [
                "prompts",
                "documents and LaTeX",
                "job descriptions",
                "raw provider errors",
                "API keys",
                "user identifiers",
                "run references",
            ],
        },
        "generated_at": now.isoformat(),
    }

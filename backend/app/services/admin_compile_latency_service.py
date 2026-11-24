"""Admin compile-latency percentiles by plan, compiler and template.

The rollup reads only persisted aggregate dimensions on ``compilations``:
plan family, compiler and selected template id. It never reads résumé source,
document content or compile error text. Percentiles use PostgreSQL's
``percentile_cont`` (linear interpolation) so values reconcile to the same raw
completed compilation rows counted in ``totals``.

Buckets smaller than ``SPARSE_BUCKET_SAMPLES`` are still returned — an operator
needs to see early regressions — but are explicitly marked ``sparse`` so the UI
does not present them as statistically representative.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models

Compilation = models.Compilation

SPARSE_BUCKET_SAMPLES = 20
SLOWEST_BUCKET_LIMIT = 10
DURATION_UNIT = "seconds"


def _timed_condition():
    """Successful compiles with a finite, non-negative reported duration."""
    return and_(
        Compilation.compilation_time.is_not(None),
        Compilation.compilation_time >= 0,
    )


def _percentile(quantile: float):
    return func.percentile_cont(quantile).within_group(Compilation.compilation_time)


def _seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    return round(number, 3) if math.isfinite(number) else None


def _summary(row: Any, sparse_threshold: int) -> dict[str, Any]:
    samples = int(row.samples or 0)
    return {
        "samples": samples,
        "p50_seconds": _seconds(row.p50),
        "p95_seconds": _seconds(row.p95),
        "p99_seconds": _seconds(row.p99),
        "mean_seconds": _seconds(row.mean),
        "max_seconds": _seconds(row.max),
        "sparse": samples < sparse_threshold,
        "sample_status": "insufficient_samples" if samples < sparse_threshold else "ok",
    }


def _normalize_plan(plan: Optional[str]) -> Optional[str]:
    if not plan:
        return None
    normalized = plan.strip().lower()
    if not normalized:
        return None
    return resolve_plan_family(normalized) if normalized in PLAN_FAMILY_ALIASES else normalized


def _normalize_compiler(compiler: Optional[str]) -> Optional[str]:
    if not compiler:
        return None
    normalized = compiler.strip().lower()
    return normalized or None


def _normalize_template(template: Optional[str]) -> Optional[str]:
    if not template:
        return None
    normalized = template.strip()
    if not normalized:
        return None
    try:
        return str(uuid.UUID(normalized))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("template must be a valid UUID") from exc


async def _dimension_buckets(
    db: AsyncSession,
    column,
    filters: tuple[Any, ...],
    sparse_threshold: int,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(
                column.label("value"),
                func.count().label("samples"),
                _percentile(0.5).label("p50"),
                _percentile(0.95).label("p95"),
                _percentile(0.99).label("p99"),
                func.avg(Compilation.compilation_time).label("mean"),
                func.max(Compilation.compilation_time).label("max"),
            )
            .where(*filters, column.is_not(None))
            .group_by(column)
        )
    ).all()
    buckets = [
        {"value": str(row.value), "label": str(row.value), **_summary(row, sparse_threshold)}
        for row in rows
        if row.value is not None
    ]
    buckets.sort(key=lambda bucket: (-bucket["samples"], bucket["value"]))
    return buckets


async def compile_latency_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: Optional[str] = None,
    compiler: Optional[str] = None,
    template: Optional[str] = None,
    sparse_threshold: int = SPARSE_BUCKET_SAMPLES,
) -> dict[str, Any]:
    """Return p50/p95/p99 compile latency and reconciliation totals."""
    days = max(1, min(int(days), 365))
    sparse_threshold = max(1, min(int(sparse_threshold), 1000))
    plan_value = _normalize_plan(plan)
    compiler_value = _normalize_compiler(compiler)
    template_value = _normalize_template(template)

    now = datetime.now(timezone.utc)
    today = now.date()
    start_day = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)

    base_filters: list[Any] = [
        Compilation.status == "completed",
        Compilation.created_at >= start_at,
        Compilation.created_at < end_at,
    ]
    if plan_value is not None:
        base_filters.append(Compilation.plan_family == plan_value)
    if compiler_value is not None:
        base_filters.append(Compilation.compiler == compiler_value)
    if template_value is not None:
        base_filters.append(Compilation.template_id == template_value)
    filters_tuple = tuple(base_filters)
    timed_filters = (*filters_tuple, _timed_condition())

    overall_row = (
        await db.execute(
            select(
                func.count().label("samples"),
                _percentile(0.5).label("p50"),
                _percentile(0.95).label("p95"),
                _percentile(0.99).label("p99"),
                func.avg(Compilation.compilation_time).label("mean"),
                func.max(Compilation.compilation_time).label("max"),
            ).where(*timed_filters)
        )
    ).one()

    totals_row = (
        await db.execute(
            select(
                func.count().label("completed"),
                func.count().filter(_timed_condition()).label("timed"),
                func.count()
                .filter(Compilation.plan_family.is_(None), _timed_condition())
                .label("missing_plan"),
                func.count()
                .filter(Compilation.compiler.is_(None), _timed_condition())
                .label("missing_compiler"),
                func.count()
                .filter(Compilation.template_id.is_(None), _timed_condition())
                .label("missing_template"),
            ).where(*filters_tuple)
        )
    ).one()

    by_plan, by_compiler, by_template = [
        await _dimension_buckets(db, column, timed_filters, sparse_threshold)
        for column in (
            Compilation.plan_family,
            Compilation.compiler,
            Compilation.template_id,
        )
    ]

    slowest: list[dict[str, Any]] = []
    for dimension, buckets in (
        ("plan", by_plan),
        ("compiler", by_compiler),
        ("template", by_template),
    ):
        for bucket in buckets:
            slowest.append({"dimension": dimension, **bucket})
    slowest.sort(
        key=lambda bucket: (
            -(bucket["p95_seconds"] if bucket["p95_seconds"] is not None else -1.0),
            -(bucket["p99_seconds"] if bucket["p99_seconds"] is not None else -1.0),
            -bucket["samples"],
            bucket["dimension"],
            bucket["value"],
        )
    )

    missing_dimensions = {
        "plan": int(totals_row.missing_plan or 0),
        "compiler": int(totals_row.missing_compiler or 0),
        "template": int(totals_row.missing_template or 0),
    }

    return {
        "days": days,
        "window": {"start": start_at.isoformat(), "end": end_at.isoformat()},
        "filters": {
            "plan": plan_value,
            "compiler": compiler_value,
            "template": template_value,
        },
        "duration_unit": DURATION_UNIT,
        "sparse_threshold": sparse_threshold,
        "slowest_limit": SLOWEST_BUCKET_LIMIT,
        "overall": _summary(overall_row, sparse_threshold),
        "by_plan": by_plan,
        "by_compiler": by_compiler,
        "by_template": by_template,
        "slowest": slowest[:SLOWEST_BUCKET_LIMIT],
        "missing_dimensions": missing_dimensions,
        "totals": {
            "completed_compilations": int(totals_row.completed or 0),
            "timed_compilations": int(totals_row.timed or 0),
            "missing_dimension_fields": sum(missing_dimensions.values()),
        },
        "generated_at": now.isoformat(),
    }

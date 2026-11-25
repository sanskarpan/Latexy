"""Admin compile-error taxonomy, top errors and daily trend.

The service reads only aggregate compilation rows: status, the persisted
allowlisted ``error_class``, template id/name and timestamps. It never selects
``error_message``, document content, user identifiers or raw compiler logs.

Every class bucket is derived from the same bounded failed-compilation scope,
so ``totals.class_total`` reconciles to ``totals.failed_compilations`` even
when legacy rows predate the taxonomy and are reported as ``unknown``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models
from .compile_error_taxonomy import (
    ALLOWED_COMPILE_ERROR_CLASSES,
    COMPILE_ERROR_CLASSES,
    DEFAULT_COMPILE_ERROR_CLASS,
)

Compilation = models.Compilation
ResumeTemplate = models.ResumeTemplate

CLASS_LABELS: dict[str, str] = {
    "syntax": "Syntax",
    "missing_package": "Missing package",
    "timeout": "Timeout",
    "engine": "Engine",
    "storage": "Storage",
    "pdf_limit": "PDF limit",
    "unknown": "Unknown",
}
TOP_ERROR_LIMIT = 8
AFFECTED_TEMPLATE_LIMIT = 5
SPARSE_SAMPLE_SIZE = 5


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def _share(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


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


def _normalize_error_class(error_class: Optional[str]) -> Optional[str]:
    if not error_class:
        return None
    normalized = error_class.strip().lower()
    if not normalized:
        return None
    if normalized not in ALLOWED_COMPILE_ERROR_CLASSES:
        allowed = ", ".join(COMPILE_ERROR_CLASSES)
        raise ValueError(f"error_class must be one of: {allowed}")
    return normalized


def _window(days: int) -> tuple[datetime, datetime, date, int]:
    days = max(1, min(int(days), 365))
    now = datetime.now(timezone.utc)
    today = now.date()
    start_day = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_at, end_at, start_day, days


def _template_href(template_id: str) -> str:
    # Admin links open the public catalog preview, never a "use template"
    # action that would create a document for the operator.
    return f"/templates?preview={template_id}"


async def compile_error_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: Optional[str] = None,
    compiler: Optional[str] = None,
    template: Optional[str] = None,
    error_class: Optional[str] = None,
) -> dict[str, Any]:
    """Return top compile errors, affected templates and a daily trend."""

    start_at, end_at, start_day, days = _window(days)
    plan_value = _normalize_plan(plan)
    compiler_value = _normalize_compiler(compiler)
    template_value = _normalize_template(template)
    selected_class = _normalize_error_class(error_class)

    base_filters: list[Any] = [
        Compilation.status == "failed",
        Compilation.created_at >= start_at,
        Compilation.created_at < end_at,
    ]
    if plan_value is not None:
        base_filters.append(Compilation.plan_family == plan_value)
    if compiler_value is not None:
        base_filters.append(Compilation.compiler == compiler_value)
    if template_value is not None:
        base_filters.append(Compilation.template_id == template_value)

    class_expr = func.coalesce(Compilation.error_class, DEFAULT_COMPILE_ERROR_CLASS).label("error_class")

    class_rows = (
        await db.execute(
            select(
                class_expr,
                func.count().label("count"),
                func.max(Compilation.created_at).label("latest_at"),
            )
            .where(*base_filters)
            .group_by(class_expr)
        )
    ).all()

    total_failed = int(await db.scalar(select(func.count()).select_from(Compilation).where(*base_filters)) or 0)

    template_rows = (
        await db.execute(
            select(
                class_expr,
                Compilation.template_id.label("template_id"),
                ResumeTemplate.name.label("template_name"),
                func.count().label("count"),
                func.max(Compilation.created_at).label("latest_at"),
            )
            .outerjoin(ResumeTemplate, ResumeTemplate.id == Compilation.template_id)
            .where(*base_filters, Compilation.template_id.is_not(None))
            .group_by(class_expr, Compilation.template_id, ResumeTemplate.name)
        )
    ).all()

    templates_by_class: dict[str, list[dict[str, Any]]] = {}
    template_totals_by_class: dict[str, int] = {}
    all_template_ids: set[str] = set()
    for row in template_rows:
        key = str(row.error_class or DEFAULT_COMPILE_ERROR_CLASS)
        template_id = str(row.template_id)
        count = int(row.count or 0)
        template_name = row.template_name if isinstance(row.template_name, str) else None
        templates_by_class.setdefault(key, []).append(
            {
                "template_id": template_id,
                "template_name": template_name,
                "count": count,
                "latest_at": _iso(row.latest_at),
                "href": _template_href(template_id),
                "sparse": count < SPARSE_SAMPLE_SIZE,
            }
        )
        template_totals_by_class[key] = template_totals_by_class.get(key, 0) + count
        all_template_ids.add(template_id)

    for entries in templates_by_class.values():
        entries.sort(key=lambda item: (-item["count"], item["template_id"]))
        del entries[AFFECTED_TEMPLATE_LIMIT:]

    class_counts: dict[str, int] = {
        str(row.error_class or DEFAULT_COMPILE_ERROR_CLASS): int(row.count or 0) for row in class_rows
    }
    class_latest: dict[str, Optional[datetime]] = {
        str(row.error_class or DEFAULT_COMPILE_ERROR_CLASS): row.latest_at for row in class_rows
    }
    class_total = sum(class_counts.values())

    top_errors: list[dict[str, Any]] = []
    for key in COMPILE_ERROR_CLASSES:
        count = class_counts.get(key, 0)
        if count <= 0:
            continue
        if selected_class is not None and key != selected_class:
            continue
        top_errors.append(
            {
                "error_class": key,
                "label": CLASS_LABELS[key],
                "count": count,
                "share": _share(count, total_failed),
                "latest_at": _iso(class_latest.get(key)),
                "affected_templates": templates_by_class.get(key, []),
                "unattributed_templates": max(0, count - template_totals_by_class.get(key, 0)),
                "sparse": count < SPARSE_SAMPLE_SIZE,
            }
        )
    top_errors.sort(key=lambda item: (-item["count"], item["error_class"]))
    top_errors = top_errors[:TOP_ERROR_LIMIT]

    day_expr = func.date_trunc("day", Compilation.created_at).label("day")
    trend_rows = (
        await db.execute(
            select(
                day_expr,
                class_expr,
                func.count().label("count"),
            )
            .where(*base_filters)
            .group_by(day_expr, class_expr)
        )
    ).all()

    trend_by_day: dict[date, dict[str, int]] = {}
    for row in trend_rows:
        day = row.day.date() if isinstance(row.day, datetime) else row.day
        key = str(row.error_class or DEFAULT_COMPILE_ERROR_CLASS)
        bucket = trend_by_day.setdefault(day, {})
        bucket[key] = bucket.get(key, 0) + int(row.count or 0)

    trend: list[dict[str, Any]] = []
    for offset in range(days):
        current_day = start_day + timedelta(days=offset)
        by_class = trend_by_day.get(current_day, {})
        trend.append(
            {
                "date": current_day.isoformat(),
                "failed_compilations": sum(by_class.values()),
                "by_class": by_class,
            }
        )

    return {
        "days": days,
        "window": {"start": start_at.isoformat(), "end": end_at.isoformat()},
        "filters": {
            "plan": plan_value,
            "compiler": compiler_value,
            "template": template_value,
            "error_class": selected_class,
        },
        "classes": [
            {
                "error_class": key,
                "label": CLASS_LABELS[key],
                "count": class_counts.get(key, 0),
                "share": _share(class_counts.get(key, 0), total_failed),
                "sparse": class_counts.get(key, 0) < SPARSE_SAMPLE_SIZE,
            }
            for key in COMPILE_ERROR_CLASSES
        ],
        "top_errors": top_errors,
        "trend": trend,
        "totals": {
            "failed_compilations": total_failed,
            "classified_compilations": sum(count for key, count in class_counts.items() if key != "unknown"),
            "unknown_compilations": class_counts.get("unknown", 0),
            "class_total": class_total,
            "reconciled": class_total == total_failed,
            "classes_with_errors": sum(1 for count in class_counts.values() if count > 0),
            "templates_with_errors": len(all_template_ids),
        },
        "suppression": {
            "minimum_sample_size": SPARSE_SAMPLE_SIZE,
            "user_dimension_included": False,
            "detail": (
                "Only aggregate compile rows and public template metadata are returned; no per-user cohort is selected."
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

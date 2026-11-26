"""Admin-only document complexity and failure-class distributions.

The report reads only persisted aggregate metadata on ``compilations``:
status, plan family, compiler, template id/name, bounded page/section counts,
compile duration, the allowlisted error class and the row owner for cohort
counting. It never selects LaTeX source, PDF bytes/text, ``error_message`` or
any other document content.

Five distinct users are required before any distribution or segment is shown.
Anonymised/device-scoped compilations are counted separately and excluded
from user-cohort segments so a single guest cannot become a visible cohort.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from statistics import fmean
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family
from ..database import models
from .admin_compile_error_service import CLASS_LABELS
from .compile_complexity import (
    LATENCY_BUCKETS,
    OVERFLOW_PAGE_THRESHOLDS,
    PAGE_BUCKETS,
    SECTION_BUCKETS,
    finite_seconds,
    latency_bucket,
    normalize_page_count,
    normalize_section_count,
    page_bucket,
    section_bucket,
)
from .compile_error_taxonomy import COMPILE_ERROR_CLASSES, DEFAULT_COMPILE_ERROR_CLASS

Compilation = models.Compilation
ResumeTemplate = models.ResumeTemplate

MIN_GROUP_USERS = 5
SPARSE_SAMPLE_SIZE = 5
MAX_SEGMENT_ROWS = 25
MAX_RANGE_DAYS = 365
PRESET_DAYS = (7, 30, 90)


def _share(count: int, total: int) -> float:
    return round(count / total, 4) if total > 0 else 0.0


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 2) if total > 0 else 0.0


def _round(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    return round(number, 2) if math.isfinite(number) else None


def _mean(values: list[float] | list[int]) -> Optional[float]:
    return _round(fmean(values)) if values else None


def _percentile(values: list[float] | list[int], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return _round(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return _round(ordered[lower])
    weight = position - lower
    return _round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


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


def _window(days: int) -> tuple[datetime, datetime, date, int]:
    days = max(1, min(int(days), MAX_RANGE_DAYS))
    now = datetime.now(timezone.utc)
    today = now.date()
    start_day = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_at, end_at, start_day, days


def _bucket_rows(
    specs: tuple[tuple[Any, Optional[Any], str], ...],
    counts: Counter,
    total: int,
) -> list[dict[str, Any]]:
    return [
        {
            "bucket": label,
            "lower_bound": lower,
            "upper_bound": upper,
            "count": int(counts.get(label, 0)),
            "pct": _pct(int(counts.get(label, 0)), total),
        }
        for lower, upper, label in specs
    ]


@dataclass
class _Group:
    users: set[str] = field(default_factory=set)
    compilations: int = 0
    completed: int = 0
    failed: int = 0
    other: int = 0
    pages: list[int] = field(default_factory=list)
    page_missing: int = 0
    sections: list[int] = field(default_factory=list)
    section_missing: int = 0
    latencies: list[float] = field(default_factory=list)
    latency_missing: int = 0
    class_counts: Counter = field(default_factory=Counter)
    page_buckets: Counter = field(default_factory=Counter)
    section_buckets: Counter = field(default_factory=Counter)
    latency_buckets: Counter = field(default_factory=Counter)

    def add(self, row: Any) -> None:
        self.compilations += 1
        if row.user_id:
            self.users.add(str(row.user_id))

        status = str(row.status or "").strip().lower()
        if status == "completed":
            self.completed += 1
            page_count = normalize_page_count(row.page_count)
            if page_count is None:
                self.page_missing += 1
            else:
                self.pages.append(page_count)
                bucket = page_bucket(page_count)
                if bucket is not None:
                    self.page_buckets[bucket] += 1

            duration = finite_seconds(row.compilation_time)
            if duration is None:
                self.latency_missing += 1
            else:
                self.latencies.append(duration)
                bucket = latency_bucket(duration)
                if bucket is not None:
                    self.latency_buckets[bucket] += 1
        elif status == "failed":
            self.failed += 1
            error_class = str(row.error_class or DEFAULT_COMPILE_ERROR_CLASS)
            if error_class not in COMPILE_ERROR_CLASSES:
                error_class = DEFAULT_COMPILE_ERROR_CLASS
            self.class_counts[error_class] += 1
        else:
            self.other += 1

        section_count = normalize_section_count(row.section_count)
        if section_count is None:
            self.section_missing += 1
        else:
            self.sections.append(section_count)
            bucket = section_bucket(section_count)
            if bucket is not None:
                self.section_buckets[bucket] += 1


def _page_summary(group: _Group) -> dict[str, Any]:
    total = len(group.pages)
    return {
        "samples": total,
        "missing": group.page_missing,
        "mean": _mean(group.pages),
        "p50": _percentile(group.pages, 0.5),
        "p90": _percentile(group.pages, 0.9),
        "p95": _percentile(group.pages, 0.95),
        "p99": _percentile(group.pages, 0.99),
        "max": max(group.pages) if group.pages else None,
        "buckets": _bucket_rows(PAGE_BUCKETS, group.page_buckets, total),
    }


def _section_summary(group: _Group) -> dict[str, Any]:
    total = len(group.sections)
    return {
        "samples": total,
        "missing": group.section_missing,
        "mean": _mean(group.sections),
        "p50": _percentile(group.sections, 0.5),
        "p90": _percentile(group.sections, 0.9),
        "p95": _percentile(group.sections, 0.95),
        "p99": _percentile(group.sections, 0.99),
        "max": max(group.sections) if group.sections else None,
        "buckets": _bucket_rows(SECTION_BUCKETS, group.section_buckets, total),
    }


def _latency_summary(group: _Group) -> dict[str, Any]:
    total = len(group.latencies)
    return {
        "samples": total,
        "missing": group.latency_missing,
        "mean_seconds": _mean(group.latencies),
        "p50_seconds": _percentile(group.latencies, 0.5),
        "p95_seconds": _percentile(group.latencies, 0.95),
        "p99_seconds": _percentile(group.latencies, 0.99),
        "max_seconds": max(group.latencies) if group.latencies else None,
        "buckets": _bucket_rows(LATENCY_BUCKETS, group.latency_buckets, total),
    }


def _failure_summary(group: _Group) -> dict[str, Any]:
    class_total = sum(int(group.class_counts.get(key, 0)) for key in COMPILE_ERROR_CLASSES)
    return {
        "failed_compilations": group.failed,
        "class_total": class_total,
        "reconciled": class_total == group.failed,
        "classes": [
            {
                "error_class": key,
                "label": CLASS_LABELS.get(key, key.replace("_", " ").title()),
                "count": int(group.class_counts.get(key, 0)),
                "share": _share(int(group.class_counts.get(key, 0)), group.failed),
                "sparse": int(group.class_counts.get(key, 0)) < SPARSE_SAMPLE_SIZE,
            }
            for key in COMPILE_ERROR_CLASSES
        ],
    }


def _overflow_summary(group: _Group) -> dict[str, Any]:
    total = len(group.pages)
    return {
        "page_samples": total,
        "max_pages": max(group.pages) if group.pages else None,
        "thresholds": [
            {
                "pages": threshold,
                "label": f">{threshold} pages",
                "count": sum(1 for page in group.pages if page > threshold),
                "share": _share(sum(1 for page in group.pages if page > threshold), total),
            }
            for threshold in OVERFLOW_PAGE_THRESHOLDS
        ],
        "pdf_limit_failures": int(group.class_counts.get("pdf_limit", 0)),
    }


def _summarize(group: _Group, dimension: Optional[str] = None, value: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "users": len(group.users),
        "compilations": group.compilations,
        "completed_compilations": group.completed,
        "failed_compilations": group.failed,
        "other_compilations": group.other,
        "page_count": _page_summary(group),
        "sections": _section_summary(group),
        "latency": _latency_summary(group),
        "failure_classes": _failure_summary(group),
        "overflow": _overflow_summary(group),
        "sparse": len(group.users) < MIN_GROUP_USERS,
    }
    if dimension is not None:
        payload = {"dimension": dimension, "value": value, **payload}
    return payload


def _totals(group: _Group) -> dict[str, Any]:
    return {
        "compilations": group.compilations,
        "completed_compilations": group.completed,
        "failed_compilations": group.failed,
        "other_compilations": group.other,
        "distinct_users": len(group.users),
        "page_count_samples": len(group.pages),
        "page_count_missing": group.page_missing,
        "section_count_samples": len(group.sections),
        "section_count_missing": group.section_missing,
        "latency_samples": len(group.latencies),
        "latency_missing": group.latency_missing,
    }


def _dimension_labels(
    groups: dict[str, _Group],
    names: Optional[dict[str, Optional[str]]] = None,
) -> dict[str, str]:
    labels: dict[str, str] = {}
    for key in groups:
        if key == "unknown":
            labels[key] = "Unknown"
        elif key == "untemplated":
            labels[key] = "Untemplated"
        elif names and names.get(key):
            labels[key] = str(names[key])
        else:
            labels[key] = key
    return labels


def _segment_rows(
    groups: dict[str, _Group],
    dimension: str,
    labels: dict[str, str],
) -> tuple[list[dict[str, Any]], int, int]:
    hidden = 0
    visible: list[dict[str, Any]] = []
    for value, group in groups.items():
        if len(group.users) < MIN_GROUP_USERS:
            hidden += 1
            continue
        payload = _summarize(group, dimension, value)
        payload["label"] = labels.get(value, value)
        visible.append(payload)
    visible.sort(key=lambda item: (-int(item["compilations"]), str(item["value"])))
    omitted = max(0, len(visible) - MAX_SEGMENT_ROWS)
    return visible[:MAX_SEGMENT_ROWS], hidden, omitted


async def document_complexity_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    plan: Optional[str] = None,
    compiler: Optional[str] = None,
    template: Optional[str] = None,
) -> dict[str, Any]:
    """Return aggregate page/latency/error-class distributions and segments."""
    start_at, end_at, _start_day, days = _window(days)
    plan_value = _normalize_plan(plan)
    compiler_value = _normalize_compiler(compiler)
    template_value = _normalize_template(template)

    base_filters: list[Any] = [
        Compilation.created_at >= start_at,
        Compilation.created_at < end_at,
    ]
    if plan_value is not None:
        base_filters.append(Compilation.plan_family == plan_value)
    if compiler_value is not None:
        base_filters.append(Compilation.compiler == compiler_value)
    if template_value is not None:
        base_filters.append(Compilation.template_id == template_value)

    anonymous_excluded = int(
        await db.scalar(
            select(func.count()).select_from(Compilation).where(*base_filters, Compilation.user_id.is_(None))
        )
        or 0
    )

    rows = (
        await db.execute(
            select(
                Compilation.status,
                Compilation.plan_family,
                Compilation.compiler,
                Compilation.template_id,
                ResumeTemplate.name.label("template_name"),
                Compilation.page_count,
                Compilation.section_count,
                Compilation.compilation_time,
                Compilation.error_class,
                Compilation.created_at,
                Compilation.user_id,
            )
            .outerjoin(ResumeTemplate, ResumeTemplate.id == Compilation.template_id)
            .where(*base_filters, Compilation.user_id.is_not(None))
        )
    ).all()

    overall = _Group()
    by_plan: dict[str, _Group] = defaultdict(_Group)
    by_compiler: dict[str, _Group] = defaultdict(_Group)
    by_template: dict[str, _Group] = defaultdict(_Group)
    template_names: dict[str, Optional[str]] = {}
    missing_dimensions = {"plan": 0, "compiler": 0, "template": 0}

    for row in rows:
        overall.add(row)

        plan_key = str(row.plan_family) if row.plan_family else "unknown"
        compiler_key = str(row.compiler) if row.compiler else "unknown"
        template_key = str(row.template_id) if row.template_id else "untemplated"

        by_plan[plan_key].add(row)
        by_compiler[compiler_key].add(row)
        by_template[template_key].add(row)

        if not row.plan_family:
            missing_dimensions["plan"] += 1
        if not row.compiler:
            missing_dimensions["compiler"] += 1
        if not row.template_id:
            missing_dimensions["template"] += 1
        elif str(row.template_id) not in template_names:
            template_names[str(row.template_id)] = row.template_name if isinstance(row.template_name, str) else None

    filtered_suppressed = overall.compilations > 0 and len(overall.users) < MIN_GROUP_USERS

    plan_labels = _dimension_labels(by_plan)
    compiler_labels = _dimension_labels(by_compiler)
    template_labels = _dimension_labels(by_template, template_names)

    if filtered_suppressed:
        summary = _summarize(_Group())
        totals = _totals(_Group())
        plan_rows: list[dict[str, Any]] = []
        compiler_rows: list[dict[str, Any]] = []
        template_rows: list[dict[str, Any]] = []
        hidden_by_dimension = {
            "plan": len(by_plan),
            "compiler": len(by_compiler),
            "template": len(by_template),
        }
        omitted_by_dimension = {"plan": 0, "compiler": 0, "template": 0}
    else:
        summary = _summarize(overall)
        totals = _totals(overall)
        plan_rows, plan_hidden, plan_omitted = _segment_rows(by_plan, "plan", plan_labels)
        compiler_rows, compiler_hidden, compiler_omitted = _segment_rows(by_compiler, "compiler", compiler_labels)
        template_rows, template_hidden, template_omitted = _segment_rows(by_template, "template", template_labels)
        hidden_by_dimension = {
            "plan": plan_hidden,
            "compiler": compiler_hidden,
            "template": template_hidden,
        }
        omitted_by_dimension = {
            "plan": plan_omitted,
            "compiler": compiler_omitted,
            "template": template_omitted,
        }

    return {
        "days": days,
        "presets": list(PRESET_DAYS),
        "window": {"start": start_at.isoformat(), "end": end_at.isoformat()},
        "timezone": "UTC",
        "filters": {
            "plan": plan_value,
            "compiler": compiler_value,
            "template": template_value,
        },
        "minimum_users": MIN_GROUP_USERS,
        "suppressed": filtered_suppressed,
        "suppression": {
            "minimum_users": MIN_GROUP_USERS,
            "rule": (
                "Hide breakdown rows with fewer than 5 distinct users; suppress all "
                "metrics when the filtered selection has fewer than 5 distinct users."
            ),
            "filtered_suppressed": filtered_suppressed,
            "hidden_by_dimension": hidden_by_dimension,
            "by_dimension": hidden_by_dimension,
        },
        "totals": totals,
        "page_count": summary["page_count"],
        "sections": summary["sections"],
        "latency": summary["latency"],
        "failure_classes": summary["failure_classes"],
        "overflow": summary["overflow"],
        "by_plan": plan_rows,
        "by_compiler": compiler_rows,
        "by_template": template_rows,
        "segmentation": {
            "dimensions": ["plan", "compiler", "template"],
            "maximum_segment_rows": MAX_SEGMENT_ROWS,
            "omitted_by_dimension": omitted_by_dimension,
        },
        "missing_dimensions": missing_dimensions,
        "reconciliation": {
            "source_rows": overall.compilations,
            "authenticated_compilations": overall.compilations,
            "completed_compilations": overall.completed,
            "failed_compilations": overall.failed,
            "other_compilations": overall.other,
            "reconciled": overall.compilations == overall.completed + overall.failed + overall.other,
            "anonymous_excluded": anonymous_excluded,
            "failure_classes_reconciled": summary["failure_classes"]["reconciled"],
            "hidden_by_suppression": filtered_suppressed,
        },
        "privacy": {
            "aggregate_only": True,
            "per_user_rows": False,
            "content_fields_read": [
                "compilations.status",
                "compilations.plan_family",
                "compilations.compiler",
                "compilations.template_id",
                "compilations.page_count",
                "compilations.section_count",
                "compilations.compilation_time",
                "compilations.error_class",
                "compilations.created_at",
                "compilations.user_id (distinct cohort counting only)",
            ],
            "content_fields_excluded": [
                "LaTeX source",
                "PDF bytes and extracted text",
                "compile error messages and raw logs",
                "resume/document titles and content",
                "user identities, emails and per-user rows",
            ],
        },
        "notes": [
            "Page-count and latency distributions cover successful compilations only.",
            "Section counts are bounded counts derived from submitted source at admission; no source text is stored.",
            "Failure classes are mutually exclusive and reconcile to failed compilations; legacy rows fall back to unknown.",
            "Anonymised/device-scoped compilations are excluded from user-cohort segments and reported separately.",
            "Segment rows under 5 distinct users are hidden and segment cardinality is capped.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["document_complexity_snapshot"]

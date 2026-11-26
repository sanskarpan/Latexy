"""Admin template catalog performance, aggregate-only.

The report combines two server-owned sources:

* ``compilations`` — authoritative successful/failed compile outcomes already
  attributed to a template id and plan family at admission.
* ``usage_analytics`` — allowlisted template view, select, use and export events
  written to the existing JSON metadata column.

Only aggregate counts leave this module. It never reads résumé content,
template source, error text, IP addresses or user agents, and never returns a
user id or per-user template history. Template rows with fewer than
``MIN_TEMPLATE_USERS`` distinct users are omitted entirely; the response reports
only how many rows were suppressed.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES
from ..database import models
from .template_analytics_service import (
    EXPORT_TEMPLATE_EVENT,
    TEMPLATE_EVENT_ACTIONS,
    normalize_template_id,
)

Compilation = models.Compilation
ResumeTemplate = models.ResumeTemplate
UsageAnalytics = models.UsageAnalytics

MIN_TEMPLATE_USERS = 5
MAX_RANGE_DAYS = 365
CSV_COLUMNS = (
    "rank",
    "template_id",
    "template_name",
    "category",
    "deleted",
    "users",
    "views",
    "selects",
    "uses",
    "exports",
    "compile_success",
    "compile_failed",
    "compile_attempts",
    "success_rate",
    "last_used_at",
)

_EVENT_FACETS = {
    "template_view": "views",
    "template_select": "selects",
    "template_use": "uses",
    EXPORT_TEMPLATE_EVENT: "exports",
}


def _as_date(value: date | str | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date range must use YYYY-MM-DD") from exc


def _resolve_range(
    *,
    days: int,
    start_date: date | str | None,
    end_date: date | str | None,
) -> tuple[date, date, datetime, datetime]:
    """Return inclusive day bounds plus the UTC half-open event range."""
    today = datetime.now(timezone.utc).date()
    start_day = _as_date(start_date)
    end_day = _as_date(end_date)
    if start_day is None and end_day is None:
        end_day = today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif start_day is None:
        end_day = end_day or today
        start_day = end_day - timedelta(days=max(1, int(days)) - 1)
    elif end_day is None:
        end_day = today

    assert start_day is not None and end_day is not None
    if start_day > end_day:
        raise ValueError("start_date must be on or before end_date")
    if (end_day - start_day).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"date range cannot exceed {MAX_RANGE_DAYS} days")

    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, end_day, start_at, end_at


def _split_csv(value: str | None) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _plan_bucket(value: str | None) -> str:
    normalized = (value or "free").strip().lower()
    if not normalized:
        return "free"
    return PLAN_FAMILY_ALIASES.get(normalized, normalized)


def _plan_values(plan: str | None) -> list[str]:
    values = {_plan_bucket(item) for item in _split_csv(plan)}
    return sorted(values)


def _normalize_template_filter(value: str | None) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return str(uuid.UUID(normalized))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("template must be a valid UUID") from exc


def _day_key(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _empty_trend_day() -> dict[str, int]:
    return {
        "views": 0,
        "selects": 0,
        "uses": 0,
        "exports": 0,
        "compile_success": 0,
        "compile_failed": 0,
    }


def _safe_csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formula prefixes in admin-authored labels."""
    if not isinstance(value, str):
        return value
    if value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return f"'{value}"
    return value


class AdminTemplatePerformanceService:
    async def template_performance(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        plan: str | None = None,
        template: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), MAX_RANGE_DAYS))
        start_day, end_day, start_at, end_at = _resolve_range(days=days, start_date=start_date, end_date=end_date)
        plans = _plan_values(plan)
        template_filter = _normalize_template_filter(template)
        selected_range_days = (end_day - start_day).days + 1

        event_template_expr = UsageAnalytics.event_metadata["template_id"].as_string()
        event_plan_expr = UsageAnalytics.event_metadata["plan"].as_string()
        event_conditions: list[Any] = [
            UsageAnalytics.created_at >= start_at,
            UsageAnalytics.created_at < end_at,
            UsageAnalytics.action.in_(sorted(TEMPLATE_EVENT_ACTIONS)),
            event_template_expr.is_not(None),
        ]
        if plans:
            event_conditions.append(event_plan_expr.in_(plans))
        if template_filter:
            event_conditions.append(event_template_expr == template_filter)

        compile_conditions: list[Any] = [
            Compilation.created_at >= start_at,
            Compilation.created_at < end_at,
            Compilation.template_id.is_not(None),
        ]
        if plans:
            compile_conditions.append(Compilation.plan_family.in_(plans))
        if template_filter:
            compile_conditions.append(Compilation.template_id == template_filter)

        event_rows = (
            await db.execute(
                select(
                    event_template_expr.label("template_id"),
                    UsageAnalytics.action.label("action"),
                    func.count(UsageAnalytics.id).label("events"),
                    func.max(UsageAnalytics.created_at).label("last_at"),
                )
                .where(*event_conditions)
                .group_by(event_template_expr, UsageAnalytics.action)
            )
        ).all()

        event_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "views": 0,
                "selects": 0,
                "uses": 0,
                "exports": 0,
                "last_at": None,
            }
        )
        for row in event_rows:
            canonical_id = normalize_template_id(row.template_id)
            if canonical_id is None:
                continue
            stat = event_stats[canonical_id]
            facet = _EVENT_FACETS.get(str(row.action))
            if facet is not None:
                stat[facet] += int(row.events or 0)
            last_at = row.last_at
            if last_at is not None and (stat["last_at"] is None or last_at > stat["last_at"]):
                stat["last_at"] = last_at

        compile_rows = (
            await db.execute(
                select(
                    Compilation.template_id.label("template_id"),
                    func.count(Compilation.id).label("attempts"),
                    func.count().filter(func.lower(Compilation.status) == "completed").label("success"),
                    func.count().filter(func.lower(Compilation.status) == "failed").label("failed"),
                    func.max(Compilation.created_at).label("last_at"),
                )
                .where(*compile_conditions)
                .group_by(Compilation.template_id)
            )
        ).all()

        compile_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "attempts": 0,
                "compile_success": 0,
                "compile_failed": 0,
                "last_at": None,
            }
        )
        for row in compile_rows:
            canonical_id = normalize_template_id(row.template_id)
            if canonical_id is None:
                continue
            stat = compile_stats[canonical_id]
            stat["attempts"] += int(row.attempts or 0)
            stat["compile_success"] += int(row.success or 0)
            stat["compile_failed"] += int(row.failed or 0)
            last_at = row.last_at
            if last_at is not None and (stat["last_at"] is None or last_at > stat["last_at"]):
                stat["last_at"] = last_at

        # Union both sources before counting distinct users so a user who viewed
        # and compiled the same template is not counted twice.
        compile_user_template = func.lower(cast(Compilation.template_id, Text))
        event_user_select = select(
            event_template_expr.label("template_id"),
            UsageAnalytics.user_id.label("user_id"),
        ).where(*event_conditions, UsageAnalytics.user_id.is_not(None))
        compile_user_select = select(
            compile_user_template.label("template_id"),
            Compilation.user_id.label("user_id"),
        ).where(*compile_conditions, Compilation.user_id.is_not(None))
        user_union = event_user_select.union(compile_user_select).subquery("template_users")
        user_rows = (
            await db.execute(
                select(
                    user_union.c.template_id,
                    func.count(func.distinct(user_union.c.user_id)).label("users"),
                ).group_by(user_union.c.template_id)
            )
        ).all()
        user_counts: dict[str, int] = {}
        for row in user_rows:
            canonical_id = normalize_template_id(row.template_id)
            if canonical_id is not None:
                user_counts[canonical_id] = int(row.users or 0)

        # Build the complete requested day range so charts never jump gaps.
        trend_map: dict[date, dict[str, int]] = {
            start_day + timedelta(days=offset): _empty_trend_day() for offset in range(selected_range_days)
        }
        event_day_rows = (
            await db.execute(
                select(
                    func.date(UsageAnalytics.created_at).label("day"),
                    UsageAnalytics.action.label("action"),
                    func.count(UsageAnalytics.id).label("events"),
                )
                .where(*event_conditions)
                .group_by(func.date(UsageAnalytics.created_at), UsageAnalytics.action)
            )
        ).all()
        for row in event_day_rows:
            day = _day_key(row.day)
            facet = _EVENT_FACETS.get(str(row.action))
            if day in trend_map and facet is not None:
                trend_map[day][facet] += int(row.events or 0)

        compile_day_rows = (
            await db.execute(
                select(
                    func.date(Compilation.created_at).label("day"),
                    func.count().filter(func.lower(Compilation.status) == "completed").label("success"),
                    func.count().filter(func.lower(Compilation.status) == "failed").label("failed"),
                )
                .where(*compile_conditions)
                .group_by(func.date(Compilation.created_at))
            )
        ).all()
        for row in compile_day_rows:
            day = _day_key(row.day)
            if day in trend_map:
                trend_map[day]["compile_success"] += int(row.success or 0)
                trend_map[day]["compile_failed"] += int(row.failed or 0)

        # Unattributed rows are reported only as a reconciliation residual; they
        # never appear as a template ranking row.
        unattributed_row = (
            await db.execute(
                select(
                    func.count().filter(func.lower(Compilation.status) == "completed").label("success"),
                    func.count().filter(func.lower(Compilation.status) == "failed").label("failed"),
                ).where(
                    Compilation.created_at >= start_at,
                    Compilation.created_at < end_at,
                    Compilation.template_id.is_(None),
                    *([Compilation.plan_family.in_(plans)] if plans else []),
                )
            )
        ).one()

        all_ids = sorted(set(event_stats) | set(compile_stats))
        metadata_by_id: dict[str, ResumeTemplate] = {}
        if all_ids:
            template_rows = (
                await db.execute(
                    select(
                        ResumeTemplate.id,
                        ResumeTemplate.name,
                        ResumeTemplate.category,
                        ResumeTemplate.is_active,
                    ).where(ResumeTemplate.id.in_(all_ids))
                )
            ).all()
            metadata_by_id = {str(row.id): row for row in template_rows}

        ranking: list[dict[str, Any]] = []
        suppressed_templates = 0
        attributed_success = 0
        attributed_failed = 0
        for template_id in all_ids:
            events = event_stats.get(template_id, {})
            compiles = compile_stats.get(template_id, {})
            compile_success = int(compiles.get("compile_success", 0))
            compile_failed = int(compiles.get("compile_failed", 0))
            attributed_success += compile_success
            attributed_failed += compile_failed

            users = user_counts.get(template_id, 0)
            if users < MIN_TEMPLATE_USERS:
                suppressed_templates += 1
                continue

            metadata = metadata_by_id.get(template_id)
            views = int(events.get("views", 0))
            selects = int(events.get("selects", 0))
            uses = int(events.get("uses", 0))
            exports = int(events.get("exports", 0))
            finished = compile_success + compile_failed
            last_at = events.get("last_at") or compiles.get("last_at")
            ranking.append(
                {
                    "rank": 0,
                    "template_id": template_id,
                    "template_name": str(metadata.name) if metadata is not None else None,
                    "category": str(metadata.category) if metadata is not None else None,
                    "deleted": metadata is None,
                    "active": bool(metadata.is_active) if metadata is not None else False,
                    "users": users,
                    "views": views,
                    "selects": selects,
                    "uses": uses,
                    "exports": exports,
                    "usage_events": views + selects + uses + exports,
                    "compile_success": compile_success,
                    "compile_failed": compile_failed,
                    "compile_attempts": int(compiles.get("attempts", 0)),
                    "success_rate": (round(compile_success / finished * 100, 2) if finished else 0.0),
                    "last_used_at": _iso(last_at),
                }
            )

        ranking.sort(
            key=lambda row: (
                -row["exports"],
                -row["compile_success"],
                -row["usage_events"],
                -row["views"],
                row["template_name"] or row["template_id"],
            )
        )
        for index, row in enumerate(ranking, start=1):
            row["rank"] = index

        ranked_success = sum(row["compile_success"] for row in ranking)
        ranked_failed = sum(row["compile_failed"] for row in ranking)
        suppressed_success = max(0, attributed_success - ranked_success)
        suppressed_failed = max(0, attributed_failed - ranked_failed)
        unattributed_success = int(unattributed_row.success or 0)
        unattributed_failed = int(unattributed_row.failed or 0)

        trend = [{"date": day.isoformat(), **values} for day, values in sorted(trend_map.items())]

        def _sum(field: str) -> int:
            return sum(int(row[field]) for row in ranking)

        return {
            "days": selected_range_days,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "timezone": "UTC",
            "date_range": {
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "days": selected_range_days,
                "timezone": "UTC",
            },
            "filters": {
                "days": selected_range_days,
                "start_date": start_day.isoformat(),
                "end_date": end_day.isoformat(),
                "plan": plans or None,
                "template": template_filter,
                "timezone": "UTC",
            },
            "minimum_users": MIN_TEMPLATE_USERS,
            "candidate_templates": len(all_ids),
            "suppressed": bool(all_ids) and not ranking,
            "suppressed_templates": suppressed_templates,
            "ranking": ranking,
            "trend": trend,
            "totals": {
                "templates": len(ranking),
                "suppressed_templates": suppressed_templates,
                "views": _sum("views"),
                "selects": _sum("selects"),
                "uses": _sum("uses"),
                "exports": _sum("exports"),
                "usage_events": _sum("usage_events"),
                "compile_success": ranked_success,
                "compile_failed": ranked_failed,
                "compile_attempts": _sum("compile_attempts"),
            },
            "reconciliation": {
                "source": "compilations",
                "attributed_compile_success": attributed_success,
                "attributed_compile_failed": attributed_failed,
                "ranked_compile_success": ranked_success,
                "ranked_compile_failed": ranked_failed,
                "suppressed_compile_success": suppressed_success,
                "suppressed_compile_failed": suppressed_failed,
                "unattributed_compile_success": unattributed_success,
                "unattributed_compile_failed": unattributed_failed,
                "compilation_success": attributed_success + unattributed_success,
                "compilation_failed": attributed_failed + unattributed_failed,
                "reconciled": (
                    ranked_success + suppressed_success == attributed_success
                    and ranked_failed + suppressed_failed == attributed_failed
                ),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_csv(self, result: dict[str, Any]) -> str:
        """Render the already-suppressed ranking as aggregate-only CSV."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in result.get("ranking", []):
            writer.writerow([_safe_csv_cell(row.get(column)) for column in CSV_COLUMNS])
        return buffer.getvalue()


admin_template_performance_service = AdminTemplatePerformanceService()

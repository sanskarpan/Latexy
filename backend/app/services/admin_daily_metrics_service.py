"""Daily aggregate rollup for admin analytics (issue #2181).

This service owns the ``admin_daily_metrics`` rollup table and the admin
read path that prefers it. Every value is a global daily count or a minor-unit
revenue/refund amount derived from ``users``, ``compilations``,
``optimizations``, ``usage_analytics``, ``payments`` and ``payment_refunds``.
No user id, email, document content, prompt, token, IP address, user agent or
provider payload is copied into the rollup or returned by an endpoint.

Refresh semantics
-----------------
* One upsert per UTC day with ``ON CONFLICT (metric_date) DO UPDATE`` keeps the
  operation idempotent (a duplicate run cannot create a second row for a day).
* A transaction-scoped advisory lock makes overlapping Celery Beat ticks skip
  instead of racing. PostgreSQL's unique key remains the final backstop.
* The whole trailing window is recomputed in one transaction, so a failure
  rolls back and leaves the previous snapshot readable.
* ``statement_timeout`` caps a runaway refresh. Failures are logged with only
  the exception class, never database text that could contain row data.

Read semantics
--------------
The admin report uses the rollup only when its last successful refresh is
within :data:`STALE_AFTER_SECONDS` and it covers the requested start date.
Otherwise it reads the base tables (with the same shape) and labels the
payload ``source="base_tables"`` plus a fallback reason.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

AdminDailyMetric = models.AdminDailyMetric

# Beat cadence must stay inside the 5-15 minute window required by #2181.
REFRESH_INTERVAL_SECONDS = 600
# Three missed ticks still serve the snapshot; beyond that the API falls back.
STALE_AFTER_SECONDS = 1800
# Recompute a bounded trailing window on every tick. 90 days matches the
# largest dashboard range while keeping each refresh's scan volume fixed.
DEFAULT_REFRESH_DAYS = 90
MAX_REFRESH_DAYS = 366
MAX_REPORT_DAYS = 365
MAX_REFRESH_MS = 120_000
MIN_COHORT_USERS = 5

# Stable application-wide key for pg_try_advisory_xact_lock. The lock is
# transaction scoped and released on commit/rollback or connection loss.
REFRESH_LOCK_KEY = 0x21_81_DA1

_AGGREGATE_CTE = """
WITH date_series AS (
    SELECT generate_series(
        CAST(:start_day AS date),
        CAST(:end_day AS date),
        INTERVAL '1 day'
    )::date AS metric_date
),
users_daily AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS new_users
    FROM users
    WHERE created_at >= :start_at AND created_at < :end_at
    GROUP BY 1
),
compilations_daily AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS compilations,
           (COUNT(*) FILTER (WHERE status = 'completed'))::bigint AS completed_compilations,
           (COUNT(*) FILTER (WHERE status = 'failed'))::bigint AS failed_compilations
    FROM compilations
    WHERE created_at >= :start_at AND created_at < :end_at
    GROUP BY 1
),
optimizations_daily AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS optimizations
    FROM optimizations
    WHERE created_at >= :start_at AND created_at < :end_at
    GROUP BY 1
),
events_daily AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS usage_events,
           COUNT(DISTINCT user_id)::bigint AS active_users
    FROM usage_analytics
    WHERE created_at >= :start_at AND created_at < :end_at
    GROUP BY 1
),
payments_daily AS (
    SELECT (created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS payments_count,
           COALESCE(SUM(amount), 0)::bigint AS gross_revenue_minor
    FROM payments
    WHERE created_at >= :start_at AND created_at < :end_at
      AND currency = 'INR'
      AND status IN ('paid', 'captured', 'partially_refunded', 'refunded')
    GROUP BY 1
),
refunds_daily AS (
    SELECT (p.created_at AT TIME ZONE 'UTC')::date AS metric_date,
           COUNT(*)::bigint AS refunds_count,
           COALESCE(SUM(r.amount), 0)::bigint AS refund_amount_minor
    FROM payment_refunds r
    JOIN payments p ON p.id = r.payment_id
    WHERE p.created_at >= :start_at AND p.created_at < :end_at
      AND p.currency = 'INR'
      AND r.status = 'succeeded'
    GROUP BY 1
)
"""

_AGGREGATE_SELECT = """
SELECT
    d.metric_date,
    COALESCE(u.new_users, 0)::bigint AS new_users,
    COALESCE(e.active_users, 0)::bigint AS active_users,
    COALESCE(e.usage_events, 0)::bigint AS usage_events,
    COALESCE(c.compilations, 0)::bigint AS compilations,
    COALESCE(c.completed_compilations, 0)::bigint AS completed_compilations,
    COALESCE(c.failed_compilations, 0)::bigint AS failed_compilations,
    COALESCE(o.optimizations, 0)::bigint AS optimizations,
    COALESCE(p.payments_count, 0)::bigint AS payments_count,
    COALESCE(p.gross_revenue_minor, 0)::bigint AS gross_revenue_minor,
    COALESCE(r.refunds_count, 0)::bigint AS refunds_count,
    COALESCE(r.refund_amount_minor, 0)::bigint AS refund_amount_minor
FROM date_series d
LEFT JOIN users_daily u ON u.metric_date = d.metric_date
LEFT JOIN compilations_daily c ON c.metric_date = d.metric_date
LEFT JOIN optimizations_daily o ON o.metric_date = d.metric_date
LEFT JOIN events_daily e ON e.metric_date = d.metric_date
LEFT JOIN payments_daily p ON p.metric_date = d.metric_date
LEFT JOIN refunds_daily r ON r.metric_date = d.metric_date
ORDER BY d.metric_date
"""

_AGGREGATE_SELECT_WITH_REFRESHED_AT = _AGGREGATE_SELECT.replace(
    "    COALESCE(r.refund_amount_minor, 0)::bigint AS refund_amount_minor\n",
    "    COALESCE(r.refund_amount_minor, 0)::bigint AS refund_amount_minor,\n"
    "    CAST(:refreshed_at AS timestamptz) AS refreshed_at\n",
)

_UPSERT_SQL = (
    _AGGREGATE_CTE
    + """
INSERT INTO admin_daily_metrics (
    metric_date, new_users, active_users, usage_events, compilations,
    completed_compilations, failed_compilations, optimizations,
    payments_count, gross_revenue_minor, refunds_count,
    refund_amount_minor, refreshed_at
)
"""
    + _AGGREGATE_SELECT_WITH_REFRESHED_AT
    + """
ON CONFLICT (metric_date) DO UPDATE SET
    new_users = EXCLUDED.new_users,
    active_users = EXCLUDED.active_users,
    usage_events = EXCLUDED.usage_events,
    compilations = EXCLUDED.compilations,
    completed_compilations = EXCLUDED.completed_compilations,
    failed_compilations = EXCLUDED.failed_compilations,
    optimizations = EXCLUDED.optimizations,
    payments_count = EXCLUDED.payments_count,
    gross_revenue_minor = EXCLUDED.gross_revenue_minor,
    refunds_count = EXCLUDED.refunds_count,
    refund_amount_minor = EXCLUDED.refund_amount_minor,
    refreshed_at = EXCLUDED.refreshed_at
"""
)

_BASE_SERIES_SQL = _AGGREGATE_CTE + _AGGREGATE_SELECT


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _window(days: int, now: datetime | None = None) -> tuple[date, date, datetime, datetime, int]:
    """Return inclusive start/end dates and the exclusive UTC timestamp range."""
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _as_utc(now)
    period_days = max(1, min(int(days), MAX_REPORT_DAYS))
    end_day = now.date()
    start_day = end_day - timedelta(days=period_days - 1)
    start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start_day, end_day, start_at, end_at, period_days


def _revenue_inr(minor: int | None) -> float:
    return round(int(minor or 0) / 100, 2)


def _point(day: date, row: Any) -> dict[str, Any]:
    active_users = int(row.active_users or 0)
    gross = int(row.gross_revenue_minor or 0)
    refunds = int(row.refund_amount_minor or 0)
    return {
        "date": day.isoformat(),
        "new_users": int(row.new_users or 0),
        "active_users": active_users,
        "compilations": int(row.compilations or 0),
        "completed_compilations": int(row.completed_compilations or 0),
        "failed_compilations": int(row.failed_compilations or 0),
        "optimizations": int(row.optimizations or 0),
        "events": int(row.usage_events or 0),
        "gross_revenue_inr": _revenue_inr(gross),
        "refunds_inr": _revenue_inr(refunds),
        "revenue_inr": _revenue_inr(gross - refunds),
        "payments_count": int(row.payments_count or 0),
        "refunds_count": int(row.refunds_count or 0),
        "sparse": 0 < active_users < MIN_COHORT_USERS,
    }


def _empty_point(day: date) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "new_users": 0,
        "active_users": 0,
        "compilations": 0,
        "completed_compilations": 0,
        "failed_compilations": 0,
        "optimizations": 0,
        "events": 0,
        "gross_revenue_inr": 0.0,
        "refunds_inr": 0.0,
        "revenue_inr": 0.0,
        "payments_count": 0,
        "refunds_count": 0,
        "sparse": False,
    }


async def _perform_upsert(
    db: AsyncSession,
    *,
    start_day: date,
    end_day: date,
    start_at: datetime,
    end_at: datetime,
    refreshed_at: datetime,
) -> int:
    """Upsert the inclusive day range; returns rows inserted or updated."""
    result = await db.execute(
        text(_UPSERT_SQL),
        {
            "start_day": start_day,
            "end_day": end_day,
            "start_at": start_at,
            "end_at": end_at,
            "refreshed_at": refreshed_at,
        },
    )
    return int(result.rowcount or 0)


async def refresh_daily_metrics(
    db: AsyncSession,
    *,
    days: int = DEFAULT_REFRESH_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Recompute the trailing window and upsert one row per UTC day.

    The caller gets a structured result instead of an exception so a Celery
    task cannot crash the beat schedule. A failed or skipped run performs no
    write (the transaction rolls back or was never started), leaving the prior
    snapshot readable.
    """
    refresh_days = max(1, min(int(days), MAX_REFRESH_DAYS))
    start_day, end_day, start_at, end_at, _ = _window(refresh_days, now)
    refreshed_at = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    started = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "status": "refreshed",
        "days": refresh_days,
        "start_date": start_day.isoformat(),
        "end_date": end_day.isoformat(),
    }

    try:
        lock_result = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
            {"lock_key": REFRESH_LOCK_KEY},
        )
        if not bool(lock_result.scalar()):
            await db.rollback()
            logger.info(
                "daily_metrics_refresh_skipped",
                extra={"reason": "lock_not_acquired", "days": refresh_days},
            )
            return {
                **payload,
                "status": "skipped",
                "reason": "lock_not_acquired",
                "rows": 0,
                "duration_ms": int(
                    (datetime.now(timezone.utc) - started).total_seconds() * 1000
                ),
            }

        # SET LOCAL applies only to this transaction and is reset on commit.
        # The timeout is an integer constant owned by this module, never input.
        await db.execute(
            text(f"SET LOCAL statement_timeout = '{int(MAX_REFRESH_MS)}ms'")
        )
        rows = await _perform_upsert(
            db,
            start_day=start_day,
            end_day=end_day,
            start_at=start_at,
            end_at=end_at,
            refreshed_at=refreshed_at,
        )
        await db.commit()
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        logger.info(
            "daily_metrics_refresh_completed",
            extra={
                "days": refresh_days,
                "rows": rows,
                "duration_ms": duration_ms,
            },
        )
        return {
            **payload,
            "rows": rows,
            "duration_ms": duration_ms,
            "refreshed_at": refreshed_at.isoformat(),
        }
    except Exception as exc:  # noqa: BLE001 — the scheduled task must survive
        await db.rollback()
        duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        logger.warning(
            "daily_metrics_refresh_failed",
            extra={
                "error_type": type(exc).__name__,
                "days": refresh_days,
                "duration_ms": duration_ms,
            },
        )
        return {
            **payload,
            "status": "failed",
            "reason": "refresh_failed",
            "error_type": type(exc).__name__,
            "rows": 0,
            "duration_ms": duration_ms,
        }


async def daily_metrics_freshness(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Describe the last successful snapshot without reading any base table."""
    if now is None:
        now = datetime.now(timezone.utc)
    else:
        now = _as_utc(now)

    result = await db.execute(
        select(
            func.max(AdminDailyMetric.refreshed_at),
            func.count(AdminDailyMetric.metric_date),
            func.min(AdminDailyMetric.metric_date),
            func.max(AdminDailyMetric.metric_date),
        )
    )
    last_refreshed_at, row_count, coverage_start, coverage_end = result.one()

    payload: dict[str, Any] = {
        "fresh": False,
        "last_refreshed_at": None,
        "age_seconds": None,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        "coverage_start": coverage_start.isoformat() if coverage_start else None,
        "coverage_end": coverage_end.isoformat() if coverage_end else None,
        "rollup_rows": int(row_count or 0),
        "reason": "no_rollup",
    }
    if last_refreshed_at is None:
        return payload

    last_refreshed_at = _as_utc(last_refreshed_at)
    age_seconds = max(0, int((now - last_refreshed_at).total_seconds()))
    payload.update(
        last_refreshed_at=last_refreshed_at.isoformat(),
        age_seconds=age_seconds,
        fresh=age_seconds <= STALE_AFTER_SECONDS,
        reason="fresh" if age_seconds <= STALE_AFTER_SECONDS else "stale",
    )
    return payload


async def _series_from_rollup(
    db: AsyncSession,
    *,
    start_day: date,
    end_day: date,
) -> dict[date, Any]:
    rows = (
        await db.execute(
            select(AdminDailyMetric)
            .where(
                AdminDailyMetric.metric_date >= start_day,
                AdminDailyMetric.metric_date <= end_day,
            )
            .order_by(AdminDailyMetric.metric_date)
        )
    ).scalars().all()
    return {row.metric_date: row for row in rows}


async def _series_from_base_tables(
    db: AsyncSession,
    *,
    start_day: date,
    end_day: date,
    start_at: datetime,
    end_at: datetime,
) -> dict[date, Any]:
    rows = (
        await db.execute(
            text(_BASE_SERIES_SQL),
            {
                "start_day": start_day,
                "end_day": end_day,
                "start_at": start_at,
                "end_at": end_at,
            },
        )
    ).all()
    return {row.metric_date: row for row in rows}


async def daily_series(
    db: AsyncSession,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the daily series and the freshness/source descriptor.

    The rollup is used only when it is recent enough and covers the requested
    window. Otherwise the base tables are queried so the admin view never
    silently serves a truncated or outdated snapshot.
    """
    start_day, end_day, start_at, end_at, period_days = _window(days, now)
    freshness = await daily_metrics_freshness(db, now=now)
    coverage_start = (
        date.fromisoformat(freshness["coverage_start"])
        if freshness["coverage_start"]
        else None
    )
    coverage_end = (
        date.fromisoformat(freshness["coverage_end"])
        if freshness["coverage_end"]
        else None
    )
    use_rollup = bool(
        freshness["fresh"]
        and coverage_start is not None
        and coverage_start <= start_day
        and coverage_end is not None
        and coverage_end >= end_day
    )

    if use_rollup:
        row_map = await _series_from_rollup(
            db,
            start_day=start_day,
            end_day=end_day,
        )
        source = "rollup"
        reason = freshness["reason"]
        fallback_reason = None
    else:
        row_map = await _series_from_base_tables(
            db,
            start_day=start_day,
            end_day=end_day,
            start_at=start_at,
            end_at=end_at,
        )
        source = "base_tables"
        reason = (
            freshness["reason"]
            if not freshness["fresh"]
            else "insufficient_coverage"
        )
        fallback_reason = reason

    series = [
        _point(day, row_map[day]) if day in row_map else _empty_point(day)
        for day in (start_day + timedelta(days=offset) for offset in range(period_days))
    ]
    descriptor = {
        **freshness,
        "reason": reason,
        "source": source,
        "fallback_reason": fallback_reason,
    }
    return series, descriptor


def _totals(series: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "new_users": sum(point["new_users"] for point in series),
        "compilations": sum(point["compilations"] for point in series),
        "completed_compilations": sum(point["completed_compilations"] for point in series),
        "failed_compilations": sum(point["failed_compilations"] for point in series),
        "optimizations": sum(point["optimizations"] for point in series),
        "events": sum(point["events"] for point in series),
        "active_user_days": sum(point["active_users"] for point in series),
        "peak_active_users": max((point["active_users"] for point in series), default=0),
        "payments_count": sum(point["payments_count"] for point in series),
        "refunds_count": sum(point["refunds_count"] for point in series),
        "gross_revenue_inr": round(
            sum(point["gross_revenue_inr"] for point in series), 2
        ),
        "refunds_inr": round(sum(point["refunds_inr"] for point in series), 2),
        "revenue_inr": round(sum(point["revenue_inr"] for point in series), 2),
        "sparse_days": sum(1 for point in series if point["sparse"]),
    }


async def daily_metrics_report(
    db: AsyncSession,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Admin payload: daily rollup series, freshness, totals and privacy notes."""
    start_day, end_day, start_at, end_at, period_days = _window(days, now)
    series, freshness = await daily_series(db, days=period_days, now=now)
    generated_at = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    end_at = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=timezone.utc)

    return {
        "days": period_days,
        "window": {
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "timezone": "UTC",
        },
        "source": freshness["source"],
        "freshness": freshness,
        "rollup": {
            "table": "admin_daily_metrics",
            "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
            "stale_after_seconds": STALE_AFTER_SECONDS,
            "default_refresh_days": DEFAULT_REFRESH_DAYS,
            "max_refresh_ms": MAX_REFRESH_MS,
        },
        "minimum_cohort_users": MIN_COHORT_USERS,
        "suppression": {
            "minimum_users": MIN_COHORT_USERS,
            "cohort_rows_returned": 0,
            "rule": (
                "Daily totals are global aggregates only; no per-user or cohort "
                "rows are returned. Days with fewer than 5 distinct active users "
                "are flagged as sparse."
            ),
            "sparse_days": sum(1 for point in series if point["sparse"]),
        },
        "series": series,
        "totals": _totals(series),
        "privacy": {
            "aggregate_only": True,
            "per_user_rows": False,
            "content_fields_read": [
                "users.created_at",
                "compilations.created_at",
                "compilations.status",
                "optimizations.created_at",
                "usage_analytics.created_at",
                "usage_analytics.user_id (distinct daily count only)",
                "payments.created_at",
                "payments.amount",
                "payments.currency",
                "payments.status",
                "payment_refunds.status",
                "payment_refunds.amount",
            ],
            "content_fields_excluded": [
                "user identities, emails and names",
                "resume/document titles and content",
                "LaTeX source, PDF bytes and extracted text",
                "prompts, model responses and provider payloads",
                "tokens, API keys and credentials",
                "IP addresses and user agents",
            ],
        },
        "notes": [
            "Days are UTC calendar days; empty days are returned as zeros.",
            "The rollup is refreshed every 10 minutes and is considered fresh for 30 minutes.",
            "If the rollup is stale or does not cover the window, the payload is computed from base tables and labelled accordingly.",
            "Revenue and refunds cover INR payments only; refunds are bucketed by the original payment date.",
        ],
        "generated_at": generated_at.isoformat(),
    }


__all__ = [
    "DEFAULT_REFRESH_DAYS",
    "MAX_REFRESH_DAYS",
    "MIN_COHORT_USERS",
    "REFRESH_INTERVAL_SECONDS",
    "REFRESH_LOCK_KEY",
    "STALE_AFTER_SECONDS",
    "daily_metrics_freshness",
    "daily_metrics_report",
    "daily_series",
    "refresh_daily_metrics",
]

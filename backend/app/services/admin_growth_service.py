"""Activation, retention, AI-cost, and dimension-filtered analytics."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.redis import cache_manager
from ..database import models

User = models.User
Resume = models.Resume
Compilation = models.Compilation
Optimization = models.Optimization
UsageAnalytics = models.UsageAnalytics
Payment = models.Payment
PaymentRefund = models.PaymentRefund

ACTIVATION_STEPS = (
    ("signup", "Signup"),
    ("first_resume", "First résumé"),
    ("first_compile", "First compile"),
    ("first_export", "First export"),
    ("first_optimize", "First AI optimize"),
    ("first_paid", "First paid"),
)
ACTIVATION_WINDOWS = (7, 30, 90)
ACTIVATION_EVENT_KEYS = tuple(key for key, _label in ACTIVATION_STEPS if key != "signup")
ACTIVATION_SOURCES = {
    "signup": ("users.created_at", "Account creation; anonymous trials are excluded."),
    "first_resume": ("resumes.created_at", "First résumé created by the account."),
    "first_compile": ("compilations.status = completed", "First successful compilation."),
    "first_export": (
        "usage_analytics.action = export",
        "First server-recorded export; PostHog is not required.",
    ),
    "first_optimize": ("optimizations.created_at", "First AI optimization run."),
    "first_paid": ("payments.status in paid/captured/partially_refunded/refunded", "First settled payment."),
}

MIN_SEGMENT_SIZE = 5
TIMESERIES_METRICS = frozenset(
    {"events", "compilations", "optimizations", "revenue", "new_users", "active_users"}
)
TIMESERIES_DIMENSIONS = frozenset({"plan", "provider", "feature", "signup_cohort"})
TIMESERIES_CACHE_TTL_SECONDS = 60
MAX_BREAKDOWN_GROUPS = 50


def _day(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _month_label(value: datetime | date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return the UTC [start, end) bounds for a strict YYYY-MM label."""
    if not isinstance(month, str) or re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month) is None:
        raise ValueError("signup cohort must use the YYYY-MM format")
    year = int(month[:4])
    month_number = int(month[5:])
    start = datetime(year, month_number, 1, tzinfo=timezone.utc)
    if month_number == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
    return start, end


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


async def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        cached = await cache_manager.get(key)
    except Exception:
        return None
    return cached if isinstance(cached, dict) else None


async def _cache_set(key: str, value: dict[str, Any]) -> None:
    try:
        await cache_manager.set(key, value, ttl=TIMESERIES_CACHE_TTL_SECONDS)
    except Exception:
        pass


async def _provider_map(db: AsyncSession, user_ids: Iterable[str]) -> dict[str, str]:
    """Best-effort Better Auth provider map; unknown users stay unlabelled."""
    ids = [str(item) for item in user_ids]
    if not ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    text('SELECT "userId", "providerId" FROM account WHERE "userId" = ANY(:ids)'),
                    {"ids": ids},
                )
            ).all()
        result: dict[str, str] = {}
        for user_id, provider in rows:
            if user_id and provider and user_id not in result:
                result[user_id] = str(provider)
        return result
    except Exception as exc:
        raise RuntimeError("Auth provider lookup failed") from exc


async def _provider_user_ids(db: AsyncSession, provider: str) -> list[str]:
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    text('SELECT "userId" FROM account WHERE "providerId" = :provider'),
                    {"provider": provider},
                )
            ).all()
        return [str(row[0]) for row in rows if row[0]]
    except Exception as exc:
        raise RuntimeError("Auth provider lookup failed") from exc


async def _first_events(
    db: AsyncSession, user_ids: list[str]
) -> dict[str, dict[str, datetime | None]]:
    if not user_ids:
        return {}
    first: dict[str, dict[str, datetime | None]] = {
        user_id: {
            "first_resume": None,
            "first_compile": None,
            "first_export": None,
            "first_optimize": None,
            "first_paid": None,
        }
        for user_id in user_ids
    }

    async def _assign(key: str, rows) -> None:
        for user_id, timestamp in rows:
            if user_id and str(user_id) in first:
                first[str(user_id)][key] = timestamp

    await _assign(
        "first_resume",
        (
            await db.execute(
                select(Resume.user_id, func.min(Resume.created_at))
                .where(Resume.user_id.in_(user_ids))
                .group_by(Resume.user_id)
            )
        ).all(),
    )
    await _assign(
        "first_compile",
        (
            await db.execute(
                select(Compilation.user_id, func.min(Compilation.created_at))
                .where(Compilation.user_id.in_(user_ids), Compilation.status == "completed")
                .group_by(Compilation.user_id)
            )
        ).all(),
    )
    await _assign(
        "first_export",
        (
            await db.execute(
                select(UsageAnalytics.user_id, func.min(UsageAnalytics.created_at))
                .where(
                    UsageAnalytics.user_id.in_(user_ids),
                    UsageAnalytics.action.ilike("%export%"),
                )
                .group_by(UsageAnalytics.user_id)
            )
        ).all(),
    )
    await _assign(
        "first_optimize",
        (
            await db.execute(
                select(Optimization.user_id, func.min(Optimization.created_at))
                .where(Optimization.user_id.in_(user_ids))
                .group_by(Optimization.user_id)
            )
        ).all(),
    )
    await _assign(
        "first_paid",
        (
            await db.execute(
                select(Payment.user_id, func.min(Payment.created_at))
                .where(
                    Payment.user_id.in_(user_ids),
                    Payment.status.in_(("paid", "partially_refunded", "refunded", "captured")),
                )
                .group_by(Payment.user_id)
            )
        ).all(),
    )
    return first


class AdminGrowthService:
    async def activation(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        plan: str | None = None,
        provider: str | None = None,
        activation_window_days: int = 30,
    ) -> dict[str, Any]:
        days = max(1, min(days, 365))
        activation_window_days = max(1, min(activation_window_days, 365))
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        stmt = select(User.id, User.subscription_plan, User.created_at).where(User.created_at >= start)
        if plan:
            stmt = stmt.where(User.subscription_plan == plan)
        users = (await db.execute(stmt)).all()
        providers = await _provider_map(db, [row[0] for row in users])
        if provider:
            users = [row for row in users if providers.get(str(row[0])) == provider]
        user_ids = [str(row[0]) for row in users]
        first = await _first_events(db, user_ids)
        signup_times = {str(user_id): created_at for user_id, _plan_id, created_at in users if created_at}
        cohort_ids = set(signup_times)

        def _reached_for_window(window_days: int) -> dict[str, set[str]]:
            reached: dict[str, set[str]] = {key: set() for key, _label in ACTIVATION_STEPS}
            reached["signup"] = set(cohort_ids)
            for user_id in cohort_ids:
                signup_at = signup_times[user_id]
                deadline = signup_at + timedelta(days=window_days)
                for key in ACTIVATION_EVENT_KEYS:
                    timestamp = first.get(user_id, {}).get(key)
                    if timestamp is not None and signup_at <= timestamp <= deadline:
                        reached[key].add(user_id)
            return reached

        primary_reached = _reached_for_window(activation_window_days)
        window_reached = {window: _reached_for_window(window) for window in ACTIVATION_WINDOWS}
        cohort_size = len(cohort_ids)

        def _event_time(user_id: str, key: str) -> datetime | None:
            if key == "signup":
                return signup_times.get(user_id)
            return first.get(user_id, {}).get(key)

        def _build_steps(reached: dict[str, set[str]]) -> list[dict[str, Any]]:
            steps: list[dict[str, Any]] = []
            previous_key = "signup"
            previous_set = reached["signup"]
            for key, label in ACTIVATION_STEPS:
                current = reached[key]
                if key == "signup":
                    steps.append(
                        {
                            "key": key,
                            "label": label,
                            "count": len(current),
                            "from_previous": 100.0,
                            "from_signup": 100.0,
                            "drop_off": 0,
                            "drop_off_pct": 0.0,
                            "median_seconds_from_previous": None,
                            "median_days_from_previous": None,
                        }
                    )
                    previous_key = key
                    previous_set = current
                    continue

                numerator = len(current & previous_set)
                drop_off = len(previous_set - current)
                gaps = [
                    (end - start_time).total_seconds()
                    for user_id in current & previous_set
                    if (start_time := _event_time(user_id, previous_key)) is not None
                    and (end := _event_time(user_id, key)) is not None
                    and end >= start_time
                ]
                median_seconds = _median(gaps)
                steps.append(
                    {
                        "key": key,
                        "label": label,
                        "count": len(current),
                        "from_previous": _pct(numerator, len(previous_set)),
                        "from_signup": _pct(len(current), cohort_size),
                        "drop_off": drop_off,
                        "drop_off_pct": _pct(drop_off, len(previous_set)),
                        "median_seconds_from_previous": (
                            round(median_seconds, 2) if median_seconds is not None else None
                        ),
                        "median_days_from_previous": (
                            round(median_seconds / 86_400, 2) if median_seconds is not None else None
                        ),
                    }
                )
                previous_key = key
                previous_set = current
            return steps

        def _segment(label: str, ids: list[str]) -> dict[str, Any]:
            id_set = set(ids)
            return {
                "label": label,
                "users": len(ids),
                "steps": {key: len(primary_reached[key] & id_set) for key, _label in ACTIVATION_STEPS},
                "windows": {
                    str(window): {
                        key: len(window_reached[window][key] & id_set) for key, _label in ACTIVATION_STEPS
                    }
                    for window in ACTIVATION_WINDOWS
                },
            }

        def _segment_rows(grouped: dict[str, list[str]]) -> tuple[list[dict[str, Any]], int]:
            visible: list[dict[str, Any]] = []
            hidden = 0
            for label, ids in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
                if len(ids) < MIN_SEGMENT_SIZE:
                    hidden += 1
                    continue
                visible.append(_segment(label, ids))
            return visible, hidden

        by_plan: dict[str, list[str]] = defaultdict(list)
        by_provider: dict[str, list[str]] = defaultdict(list)
        by_signup_cohort: dict[str, list[str]] = defaultdict(list)
        for user_id, plan_id, created_at in users:
            uid = str(user_id)
            by_plan[plan_id or "free"].append(uid)
            by_provider[providers.get(uid, "unknown")].append(uid)
            if created_at is not None:
                by_signup_cohort[_month_label(created_at)].append(uid)

        plan_rows, hidden_plan = _segment_rows(by_plan)
        provider_rows, hidden_provider = _segment_rows(by_provider)
        cohort_rows, hidden_cohort = _segment_rows(by_signup_cohort)

        reconciliation = {
            "signup": {"source": ACTIVATION_SOURCES["signup"][0], "users": cohort_size},
        }
        for key in ACTIVATION_EVENT_KEYS:
            reconciliation[key] = {
                "source": ACTIVATION_SOURCES[key][0],
                "users": sum(1 for user_id in cohort_ids if first.get(user_id, {}).get(key) is not None),
            }

        return {
            "period_days": days,
            "activation_window_days": activation_window_days,
            "cohort_size": cohort_size,
            "steps": _build_steps(primary_reached),
            "windows": {
                str(window): {
                    "window_days": window,
                    "cohort_size": cohort_size,
                    "steps": _build_steps(window_reached[window]),
                }
                for window in ACTIVATION_WINDOWS
            },
            "by_plan": plan_rows,
            "by_provider": provider_rows,
            "by_signup_cohort": cohort_rows,
            "suppressed_segments": {
                "plan": hidden_plan,
                "provider": hidden_provider,
                "signup_cohort": hidden_cohort,
            },
            "minimum_segment_size": MIN_SEGMENT_SIZE,
            "milestone_definitions": [
                {"key": key, "label": label, "source": ACTIVATION_SOURCES[key][0], "definition": ACTIVATION_SOURCES[key][1]}
                for key, label in ACTIVATION_STEPS
            ],
            "reconciliation": reconciliation,
            "generated_at": now.isoformat(),
        }

    async def retention(
        self,
        db: AsyncSession,
        *,
        weeks: int = 8,
        signup_month: str | None = None,
    ) -> dict[str, Any]:
        weeks = max(1, min(weeks, 26))
        now = datetime.now(timezone.utc)
        cohort_bounds = _month_bounds(signup_month) if signup_month else None
        if cohort_bounds is not None:
            user_start, month_end = cohort_bounds
            user_end = min(month_end, now)
            activity_start = user_start
            activity_end = min(now, user_end + timedelta(days=max(weeks * 7, 14)))
        else:
            user_start = now - timedelta(days=weeks * 7)
            user_end = now
            activity_start = user_start
            activity_end = now

        users = (
            await db.execute(
                select(User.id, User.created_at).where(
                    User.created_at >= user_start,
                    User.created_at <= user_end,
                )
            )
        ).all()
        user_ids = [str(row[0]) for row in users]
        signup = {str(user_id): created_at for user_id, created_at in users if created_at}
        active: dict[str, set[date]] = defaultdict(set)
        if user_ids:
            day_exprs = [
                select(UsageAnalytics.user_id, func.date_trunc("day", UsageAnalytics.created_at))
                .where(
                    UsageAnalytics.user_id.in_(user_ids),
                    UsageAnalytics.created_at >= activity_start,
                    UsageAnalytics.created_at <= activity_end,
                )
                .distinct(),
                select(Compilation.user_id, func.date_trunc("day", Compilation.created_at))
                .where(
                    Compilation.user_id.in_(user_ids),
                    Compilation.status == "completed",
                    Compilation.created_at >= activity_start,
                    Compilation.created_at <= activity_end,
                )
                .distinct(),
                select(Optimization.user_id, func.date_trunc("day", Optimization.created_at))
                .where(
                    Optimization.user_id.in_(user_ids),
                    Optimization.created_at >= activity_start,
                    Optimization.created_at <= activity_end,
                )
                .distinct(),
                select(Resume.user_id, func.date_trunc("day", Resume.updated_at))
                .where(
                    Resume.user_id.in_(user_ids),
                    Resume.updated_at >= activity_start,
                    Resume.updated_at <= activity_end,
                )
                .distinct(),
            ]
            for stmt in day_exprs:
                for user_id, timestamp in (await db.execute(stmt)).all():
                    day = _day(timestamp)
                    if user_id and day is not None:
                        active[str(user_id)].add(day)

        def _cell(ids: list[str], retained: int, denominator: int) -> dict[str, Any]:
            return {
                "count": retained,
                "eligible": denominator,
                "numerator": retained,
                "denominator": denominator,
                "cohort_size": len(ids),
                "rate": _pct(retained, denominator) if denominator >= MIN_SEGMENT_SIZE else None,
            }

        def _day_cell(ids: list[str], offset: int) -> dict[str, Any]:
            eligible = [user_id for user_id in ids if signup[user_id] + timedelta(days=offset) <= now]
            retained = sum(
                1
                for user_id in eligible
                if (signup[user_id].date() + timedelta(days=offset)) in active.get(user_id, set())
            )
            return _cell(ids, retained, len(eligible))

        def _range_cell(ids: list[str], start_offset: int, end_offset: int) -> dict[str, Any]:
            eligible = [
                user_id for user_id in ids if signup[user_id] + timedelta(days=end_offset) <= now
            ]
            retained = 0
            for user_id in eligible:
                base = signup[user_id].date()
                first_day = base + timedelta(days=start_offset)
                last_day = base + timedelta(days=end_offset)
                if any(first_day <= activity_day <= last_day for activity_day in active.get(user_id, set())):
                    retained += 1
            return _cell(ids, retained, len(eligible))

        def _w2_plus_cell(ids: list[str]) -> dict[str, Any]:
            eligible = [user_id for user_id in ids if signup[user_id] + timedelta(days=14) <= now]
            retained = sum(
                1
                for user_id in eligible
                if any(
                    activity_day >= signup[user_id].date() + timedelta(days=14)
                    for activity_day in active.get(user_id, set())
                )
            )
            return _cell(ids, retained, len(eligible))

        def _weekly_curve(ids: list[str]) -> list[dict[str, Any]]:
            return [
                {
                    "week": week,
                    **_range_cell(ids, week * 7, week * 7 + 6),
                }
                for week in range(1, weeks + 1)
            ]

        def _cohort_cells(ids: list[str]) -> dict[str, Any]:
            return {
                "d1": _day_cell(ids, 1),
                "d7": _day_cell(ids, 7),
                "d30": _day_cell(ids, 30),
                "w1": _range_cell(ids, 7, 13),
                "w2_plus": _w2_plus_cell(ids),
                "weekly": _weekly_curve(ids),
            }

        def _point(label: str, cell: dict[str, Any]) -> dict[str, Any]:
            return {
                "cohort": label,
                "cohort_size": cell["cohort_size"],
                "numerator": cell["numerator"],
                "denominator": cell["denominator"],
                "rate": cell["rate"],
            }

        def _aggregate(cells: list[dict[str, Any]]) -> dict[str, Any]:
            numerator = sum(cell["numerator"] for cell in cells)
            denominator = sum(cell["denominator"] for cell in cells)
            cohort_size = sum(cell["cohort_size"] for cell in cells)
            return {
                "numerator": numerator,
                "denominator": denominator,
                "cohort_size": cohort_size,
                "count": numerator,
                "eligible": denominator,
                "rate": _pct(numerator, denominator) if denominator >= MIN_SEGMENT_SIZE else None,
            }

        weekly_groups: dict[date, list[str]] = defaultdict(list)
        monthly_groups: dict[str, list[str]] = defaultdict(list)
        for user_id, created_at in signup.items():
            cohort_day = _day(created_at)
            if cohort_day is None:
                continue
            monday = cohort_day - timedelta(days=cohort_day.weekday())
            weekly_groups[monday].append(user_id)
            monthly_groups[_month_label(created_at)].append(user_id)

        weekly_rows: list[dict[str, Any]] = []
        hidden_weekly = 0
        for week_start, ids in sorted(weekly_groups.items()):
            if len(ids) < MIN_SEGMENT_SIZE:
                hidden_weekly += 1
                continue
            weekly_rows.append(
                {
                    "week_start": week_start.isoformat(),
                    "cohort_size": len(ids),
                    **_cohort_cells(ids),
                }
            )

        monthly_rows: list[dict[str, Any]] = []
        hidden_monthly = 0
        for month, ids in sorted(monthly_groups.items()):
            if len(ids) < MIN_SEGMENT_SIZE:
                hidden_monthly += 1
                continue
            monthly_rows.append(
                {
                    "signup_month": month,
                    "cohort_size": len(ids),
                    **_cohort_cells(ids),
                }
            )

        measure_cells = {
            key: [row[key] for row in weekly_rows]
            for key in ("d1", "d7", "d30", "w1", "w2_plus")
        }
        curves = {
            key: [_point(row["week_start"], row[key]) for row in weekly_rows]
            for key in measure_cells
        }
        curves["weekly"] = [
            {
                "week": week,
                **_aggregate([row["weekly"][week - 1] for row in weekly_rows]),
            }
            for week in range(1, weeks + 1)
            if weekly_rows
        ]

        overall = {
            "cohort_size": sum(row["cohort_size"] for row in weekly_rows),
            **{key: _aggregate(cells) for key, cells in measure_cells.items()},
            "weekly": curves["weekly"],
        }

        signup_month_expr = func.date_trunc("month", User.created_at).label("month")
        available_months = (
            await db.execute(
                select(signup_month_expr, func.count(User.id))
                .where(User.created_at >= now - timedelta(days=365))
                .group_by(signup_month_expr)
                .order_by(signup_month_expr)
            )
        ).all()
        available_signup_months = [
            {"month": _month_label(month), "users": int(count)}
            for month, count in available_months
            if month is not None and int(count) >= MIN_SEGMENT_SIZE
        ]

        return {
            "weeks": weeks,
            "signup_month": signup_month,
            "available_signup_months": available_signup_months,
            "cohorts": weekly_rows,
            "monthly": monthly_rows,
            "curves": curves,
            "overall": overall,
            "minimum_cohort_size": MIN_SEGMENT_SIZE,
            "hidden_weekly_cohorts": hidden_weekly,
            "hidden_monthly_cohorts": hidden_monthly,
            "activity_definition": (
                "Any first-party usage event, completed compile, optimization, or résumé edit/update."
            ),
            "period": {"start": user_start.isoformat(), "end": user_end.isoformat()},
            "generated_at": now.isoformat(),
        }

    def _price_info(self, provider: str, model: str) -> tuple[float, bool]:
        key = f"{provider}:{model}"
        price = settings.RESUME_ENGINE_MODEL_PRICING.get(key)
        if not price:
            # Compatible providers must be explicitly priced. The boolean makes
            # the fallback visible in the report instead of silently claiming
            # the configured price table was used.
            return 3.0, True
        input_price = float(price.get("input_per_million", 1.0))
        output_price = float(price.get("output_per_million", 3.0))
        return (input_price + output_price) / 2, False

    def _price_per_million(self, provider: str, model: str) -> float:
        return self._price_info(provider, model)[0]

    async def ai_cost(self, db: AsyncSession, *, days: int = 30) -> dict[str, Any]:
        days = max(1, min(days, 365))
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = (
            await db.execute(
                select(
                    Optimization.user_id,
                    Optimization.provider,
                    Optimization.model,
                    Optimization.tokens_used,
                    Optimization.created_at,
                    User.subscription_plan,
                )
                .outerjoin(User, User.id == Optimization.user_id)
                .where(
                    Optimization.created_at >= start,
                    Optimization.tokens_used.is_not(None),
                    Optimization.tokens_used > 0,
                )
            )
        ).all()
        # Cap and outlier alerts are month-to-date, independent of the selected
        # display range. A 7-day view must not hide spend from the rest of the
        # month.
        month_rows = (
            await db.execute(
                select(
                    Optimization.user_id,
                    Optimization.provider,
                    Optimization.model,
                    Optimization.tokens_used,
                    Optimization.created_at,
                ).where(
                    Optimization.created_at >= month_start,
                    Optimization.tokens_used.is_not(None),
                    Optimization.tokens_used > 0,
                )
            )
        ).all()

        total_cost = 0.0
        total_tokens = 0
        by_model: dict[tuple[str, str], dict[str, Any]] = {}
        by_plan: dict[str, dict[str, Any]] = {}
        by_day: dict[str, dict[str, Any]] = {}
        per_user: dict[str, dict[str, Any]] = {}
        daily_user_cost: dict[tuple[str, str], float] = defaultdict(float)
        for user_id, provider, model, tokens, created_at, plan in rows:
            tokens = int(tokens or 0)
            rate, fallback = self._price_info(provider or "unknown", model or "unknown")
            cost = tokens / 1_000_000 * rate
            total_cost += cost
            total_tokens += tokens
            model_bucket = by_model.setdefault(
                (provider or "unknown", model or "unknown"),
                {"provider": provider or "unknown", "model": model or "unknown", "runs": 0, "tokens": 0,
                 "cost_usd": 0.0, "fallback_price": fallback},
            )
            model_bucket["runs"] += 1
            model_bucket["tokens"] += tokens
            model_bucket["cost_usd"] += cost
            model_bucket["fallback_price"] = model_bucket["fallback_price"] or fallback
            plan_label = plan or "free"
            plan_bucket = by_plan.setdefault(
                plan_label, {"plan": plan_label, "runs": 0, "tokens": 0, "cost_usd": 0.0}
            )
            plan_bucket["runs"] += 1
            plan_bucket["tokens"] += tokens
            plan_bucket["cost_usd"] += cost
            if created_at:
                day_key = created_at.date().isoformat()
                day_bucket = by_day.setdefault(day_key, {"date": day_key, "runs": 0, "tokens": 0, "cost_usd": 0.0})
                day_bucket["runs"] += 1
                day_bucket["tokens"] += tokens
                day_bucket["cost_usd"] += cost
            if user_id:
                user_bucket = per_user.setdefault(
                    str(user_id), {"user_id": str(user_id), "plan": plan or "free", "runs": 0, "tokens": 0, "cost_usd": 0.0}
                )
                user_bucket["runs"] += 1
                user_bucket["tokens"] += tokens
                user_bucket["cost_usd"] += cost

        revenue_rows = (
            await db.execute(
                select(User.subscription_plan, func.coalesce(func.sum(Payment.amount), 0))
                .join(User, User.id == Payment.user_id)
                .where(
                    Payment.created_at >= start,
                    Payment.currency == "INR",
                    Payment.status.in_(("paid", "partially_refunded", "captured", "refunded")),
                )
                .group_by(User.subscription_plan)
            )
        ).all()
        refund_rows = (
            await db.execute(
                select(User.subscription_plan, func.coalesce(func.sum(PaymentRefund.amount), 0))
                .join(Payment, Payment.id == PaymentRefund.payment_id)
                .join(User, User.id == Payment.user_id)
                .where(
                    Payment.created_at >= start,
                    Payment.currency == "INR",
                    PaymentRefund.status == "succeeded",
                )
                .group_by(User.subscription_plan)
            )
        ).all()
        refund_by_plan = {plan or "free": int(amount or 0) for plan, amount in refund_rows}
        inr_rate = settings.ADMIN_AI_COST_USD_INR_RATE
        margin_by_plan = []
        for plan_id, amount in revenue_rows:
            label = plan_id or "free"
            cost = by_plan.get(label, {}).get("cost_usd", 0.0)
            revenue_inr = int(amount or 0) / 100
            refund_inr = refund_by_plan.get(label, 0) / 100
            margin_by_plan.append(
                {
                    "plan": label,
                    "revenue_inr": round(revenue_inr - refund_inr, 2),
                    "ai_cost_inr": round(cost * inr_rate, 2),
                    "ai_cost_usd": round(cost, 2),
                    "gross_margin_inr": round(revenue_inr - refund_inr - cost * inr_rate, 2),
                    "estimated": True,
                }
            )

        monthly_cost = 0.0
        for user_id, provider, model, tokens, created_at in month_rows:
            if not created_at:
                continue
            unit_rate = self._price_per_million(provider or "unknown", model or "unknown")
            cost = int(tokens or 0) / 1_000_000 * unit_rate
            monthly_cost += cost
            if user_id:
                daily_user_cost[(str(user_id), created_at.date().isoformat())] += cost
        alerts = []
        cap = float(settings.ADMIN_AI_MONTHLY_SPEND_CAP_USD or 0)
        if cap > 0 and monthly_cost >= cap:
            alerts.append(
                {
                    "severity": "critical" if monthly_cost >= cap * 1.1 else "warning",
                    "code": "ai_monthly_cap",
                    "message": f"Estimated AI spend ${monthly_cost:.2f} has reached the ${cap:.2f} monthly cap.",
                    "value": round(monthly_cost, 2),
                    "threshold": cap,
                }
            )
        user_threshold = float(settings.ADMIN_AI_USER_DAILY_COST_ALERT_USD or 0)
        if user_threshold > 0:
            for (user_id, day_key), cost in sorted(daily_user_cost.items(), key=lambda item: -item[1])[:10]:
                if cost >= user_threshold:
                    alerts.append(
                        {
                            "severity": "warning",
                            "code": "ai_user_daily_outlier",
                            "message": f"User {user_id[:8]}… estimated ${cost:.2f} on {day_key}.",
                            "value": round(cost, 2),
                            "threshold": user_threshold,
                            "user_id": user_id,
                            "date": day_key,
                        }
                    )

        return {
            "period_days": days,
            "generated_at": now.isoformat(),
            "estimated": True,
            "price_note": "Cost uses total tokens and a blended per-million rate because the input/output split is unavailable. Rows marked fallback_price=true use the $3/M estimate because that provider:model has no configured price.",
            "usd_inr_rate": inr_rate,
            "monthly_spend_cap_usd": cap or None,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 2),
            "total_cost_inr": round(total_cost * inr_rate, 2),
            "optimizations": sum(item["runs"] for item in by_model.values()),
            "by_model": sorted(
                ({**item, "cost_usd": round(item["cost_usd"], 2)} for item in by_model.values()),
                key=lambda item: -item["cost_usd"],
            ),
            "by_plan": sorted(
                ({**item, "cost_usd": round(item["cost_usd"], 2)} for item in by_plan.values()),
                key=lambda item: -item["cost_usd"],
            ),
            "by_day": [
                {**item, "cost_usd": round(item["cost_usd"], 4)}
                for item in sorted(by_day.values(), key=lambda item: item["date"])
            ],
            "top_users": sorted(
                ({**item, "cost_usd": round(item["cost_usd"], 4)} for item in per_user.values()),
                key=lambda item: -item["cost_usd"],
            )[:20],
            "margin_by_plan": sorted(margin_by_plan, key=lambda item: -item["gross_margin_inr"]),
            "alerts": alerts,
        }

    async def timeseries(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        metric: str = "events",
        dimension: str | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        if metric not in TIMESERIES_METRICS:
            raise ValueError(f"Unsupported metric {metric!r}")
        if dimension is not None and dimension not in TIMESERIES_DIMENSIONS:
            raise ValueError(f"Unsupported dimension {dimension!r}")
        if dimension == "feature" and metric != "events":
            raise ValueError("Feature filters are only supported for the events metric")
        if dimension is None:
            value = None
        if value is not None:
            value = value.strip() or None
        if dimension == "signup_cohort" and value:
            _month_bounds(value)

        now = datetime.now(timezone.utc)
        today = now.date()
        start_day = today - timedelta(days=days - 1)
        start_at = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc)
        zero_value: int | float = 0.0 if metric == "revenue" else 0

        cache_payload = {
            "days": days,
            "metric": metric,
            "dimension": dimension,
            "value": value,
            "start": start_day.isoformat(),
            "end": today.isoformat(),
        }
        cache_key = (
            "admin:analytics:timeseries:v2:"
            + hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode("utf-8")).hexdigest()
        )
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        def _points() -> list[dict[str, Any]]:
            return [
                {"date": (start_day + timedelta(days=offset)).isoformat(), "value": zero_value}
                for offset in range(days)
            ]

        def _response(
            *,
            points: list[dict[str, Any]],
            breakdown: list[dict[str, Any]],
            total: int | float,
            suppressed: bool = False,
            suppressed_groups: int = 0,
        ) -> dict[str, Any]:
            return {
                "metric": metric,
                "dimension": dimension,
                "value": value,
                "days": days,
                "start_date": start_day.isoformat(),
                "end_date": today.isoformat(),
                "points": points,
                "breakdown": breakdown,
                "total": total,
                "suppressed": suppressed,
                "suppressed_groups": suppressed_groups,
                "minimum_group_size": MIN_SEGMENT_SIZE,
                "filters": {
                    "days": days,
                    "metric": metric,
                    "dimension": dimension,
                    "value": value,
                    "start_date": start_day.isoformat(),
                    "end_date": today.isoformat(),
                    "timezone": "UTC",
                },
                "generated_at": now.isoformat(),
            }

        provider_ids: list[str] | None = None
        cohort_bounds: tuple[datetime, datetime] | None = None
        if dimension and value:
            if dimension == "plan":
                audience_count = (
                    await db.execute(
                        select(func.count(User.id)).where(User.subscription_plan == value)
                    )
                ).scalar_one()
            elif dimension == "provider":
                provider_ids = await _provider_user_ids(db, value)
                audience_count = len(provider_ids)
            elif dimension == "signup_cohort":
                cohort_bounds = _month_bounds(value)
                audience_count = (
                    await db.execute(
                        select(func.count(User.id)).where(
                            User.created_at >= cohort_bounds[0],
                            User.created_at < cohort_bounds[1],
                        )
                    )
                ).scalar_one()
            else:
                audience_count = (
                    await db.execute(
                        select(func.count(func.distinct(UsageAnalytics.user_id))).where(
                            UsageAnalytics.action == value,
                            UsageAnalytics.user_id.is_not(None),
                            UsageAnalytics.created_at >= start_at,
                            UsageAnalytics.created_at < end_at,
                        )
                    )
                ).scalar_one()
            if int(audience_count) == 0:
                response = _response(points=_points(), breakdown=[], total=zero_value)
                await _cache_set(cache_key, response)
                return response
            if int(audience_count) < MIN_SEGMENT_SIZE:
                response = _response(
                    points=_points(),
                    breakdown=[],
                    total=zero_value,
                    suppressed=True,
                    suppressed_groups=1,
                )
                await _cache_set(cache_key, response)
                return response

        def _audience_condition(column):
            if dimension == "provider" and provider_ids is not None:
                return column.in_(provider_ids)
            if dimension == "signup_cohort" and cohort_bounds is not None:
                return column.in_(
                    select(User.id).where(
                        User.created_at >= cohort_bounds[0],
                        User.created_at < cohort_bounds[1],
                    )
                )
            if dimension == "plan" and value:
                return column.in_(select(User.id).where(User.subscription_plan == value))
            return None

        user_filters = [User.created_at >= start_at, User.created_at < end_at]
        if dimension == "plan" and value:
            user_filters.append(User.subscription_plan == value)
        elif dimension == "provider" and provider_ids is not None:
            user_filters.append(User.id.in_(provider_ids))
        elif dimension == "signup_cohort" and cohort_bounds is not None:
            user_filters.extend(
                [User.created_at >= cohort_bounds[0], User.created_at < cohort_bounds[1]]
            )

        if metric == "new_users":
            time_col = User.created_at
            metric_col = func.count(User.id)
            series_filters = list(user_filters)
        elif metric == "active_users":
            time_col = UsageAnalytics.created_at
            metric_col = func.count(func.distinct(UsageAnalytics.user_id))
            series_filters = [
                UsageAnalytics.created_at >= start_at,
                UsageAnalytics.created_at < end_at,
                UsageAnalytics.user_id.is_not(None),
            ]
            audience = _audience_condition(UsageAnalytics.user_id)
            if audience is not None:
                series_filters.append(audience)
        elif metric == "events":
            time_col = UsageAnalytics.created_at
            metric_col = func.count(UsageAnalytics.id)
            series_filters = [
                UsageAnalytics.created_at >= start_at,
                UsageAnalytics.created_at < end_at,
            ]
            if dimension == "feature" and value:
                series_filters.append(UsageAnalytics.action == value)
            audience = _audience_condition(UsageAnalytics.user_id)
            if audience is not None:
                series_filters.append(audience)
        elif metric == "compilations":
            time_col = Compilation.created_at
            metric_col = func.count(Compilation.id)
            series_filters = [
                Compilation.created_at >= start_at,
                Compilation.created_at < end_at,
                Compilation.status == "completed",
            ]
            audience = _audience_condition(Compilation.user_id)
            if audience is not None:
                series_filters.append(audience)
        elif metric == "optimizations":
            time_col = Optimization.created_at
            metric_col = func.count(Optimization.id)
            series_filters = [
                Optimization.created_at >= start_at,
                Optimization.created_at < end_at,
            ]
            audience = _audience_condition(Optimization.user_id)
            if audience is not None:
                series_filters.append(audience)
        else:
            time_col = Payment.created_at
            metric_col = func.coalesce(func.sum(Payment.amount), 0)
            series_filters = [
                Payment.created_at >= start_at,
                Payment.created_at < end_at,
                Payment.currency == "INR",
                Payment.status.in_(("paid", "partially_refunded", "captured", "refunded")),
            ]
            audience = _audience_condition(Payment.user_id)
            if audience is not None:
                series_filters.append(audience)

        day_expr = func.date_trunc("day", time_col).label("day")
        rows = (
            await db.execute(
                select(day_expr, metric_col.label("value"))
                .where(*series_filters)
                .group_by(day_expr)
                .order_by(day_expr)
            )
        ).all()
        series: dict[date, int | float] = {}
        for row in rows:
            row_day = _day(row.day)
            if row_day is None:
                continue
            raw = int(row.value or 0)
            series[row_day] = round(raw / 100, 2) if metric == "revenue" else raw

        points = []
        for offset in range(days):
            point_day = start_day + timedelta(days=offset)
            points.append({"date": point_day.isoformat(), "value": series.get(point_day, zero_value)})

        if metric == "active_users":
            total = int(
                (
                    await db.execute(
                        select(func.count(func.distinct(UsageAnalytics.user_id))).where(*series_filters)
                    )
                ).scalar_one()
                or 0
            )
        else:
            total = round(sum(point["value"] for point in points), 2) if metric == "revenue" else sum(
                point["value"] for point in points
            )

        breakdown: list[dict[str, Any]] = []
        suppressed_groups = 0

        def _append_group(label: str, amount: int | float, users: int) -> None:
            nonlocal suppressed_groups
            if users < MIN_SEGMENT_SIZE:
                suppressed_groups += 1
                return
            normalized = round(amount / 100, 2) if metric == "revenue" else amount
            breakdown.append({"label": label, "value": normalized, "users": users})

        if dimension in {"plan", "signup_cohort"}:
            if metric == "new_users":
                label_expr = (
                    User.subscription_plan
                    if dimension == "plan"
                    else func.date_trunc("month", User.created_at)
                )
                group_rows = (
                    await db.execute(
                        select(label_expr, func.count(User.id))
                        .select_from(User)
                        .where(*user_filters)
                        .group_by(label_expr)
                    )
                ).all()
                for label, amount in group_rows:
                    value_int = int(amount or 0)
                    if dimension == "plan":
                        normalized_label = label or "free"
                    else:
                        normalized_label = _month_label(label) if label is not None else "unknown"
                    _append_group(normalized_label, value_int, value_int)
            else:
                if metric == "active_users":
                    label_expr = (
                        User.subscription_plan
                        if dimension == "plan"
                        else func.date_trunc("month", User.created_at)
                    )
                    metric_expr = func.count(func.distinct(UsageAnalytics.user_id))
                    user_column = UsageAnalytics.user_id
                    breakdown_model = UsageAnalytics
                elif metric == "events":
                    label_expr = (
                        User.subscription_plan
                        if dimension == "plan"
                        else func.date_trunc("month", User.created_at)
                    )
                    metric_expr = func.count(UsageAnalytics.id)
                    user_column = UsageAnalytics.user_id
                    breakdown_model = UsageAnalytics
                elif metric == "compilations":
                    label_expr = (
                        User.subscription_plan
                        if dimension == "plan"
                        else func.date_trunc("month", User.created_at)
                    )
                    metric_expr = func.count(Compilation.id)
                    user_column = Compilation.user_id
                    breakdown_model = Compilation
                elif metric == "optimizations":
                    label_expr = (
                        User.subscription_plan
                        if dimension == "plan"
                        else func.date_trunc("month", User.created_at)
                    )
                    metric_expr = func.count(Optimization.id)
                    user_column = Optimization.user_id
                    breakdown_model = Optimization
                else:
                    label_expr = (
                        User.subscription_plan
                        if dimension == "plan"
                        else func.date_trunc("month", User.created_at)
                    )
                    metric_expr = func.coalesce(func.sum(Payment.amount), 0)
                    user_column = Payment.user_id
                    breakdown_model = Payment
                group_rows = (
                    await db.execute(
                        select(
                            label_expr,
                            metric_expr,
                            func.count(func.distinct(user_column)),
                        )
                        .select_from(breakdown_model)
                        .join(User, User.id == user_column)
                        .where(*series_filters)
                        .group_by(label_expr)
                    )
                ).all()
                for label, amount, users in group_rows:
                    if dimension == "plan":
                        normalized_label = label or "free"
                    else:
                        normalized_label = _month_label(label) if label is not None else "unknown"
                    _append_group(normalized_label, int(amount or 0), int(users or 0))
        elif dimension == "provider":
            if metric == "new_users":
                user_rows = (await db.execute(select(User.id).where(*user_filters))).all()
                grouped_ids = [str(row[0]) for row in user_rows if row[0]]
                providers = await _provider_map(db, grouped_ids)
                counts: dict[str, int] = defaultdict(int)
                for user_id in grouped_ids:
                    counts[value or providers.get(user_id, "unknown")] += 1
                for label, amount in counts.items():
                    _append_group(label, amount, amount)
            else:
                if metric == "active_users":
                    metric_expr = func.count(func.distinct(UsageAnalytics.user_id))
                    user_column = UsageAnalytics.user_id
                elif metric == "events":
                    metric_expr = func.count(UsageAnalytics.id)
                    user_column = UsageAnalytics.user_id
                elif metric == "compilations":
                    metric_expr = func.count(Compilation.id)
                    user_column = Compilation.user_id
                elif metric == "optimizations":
                    metric_expr = func.count(Optimization.id)
                    user_column = Optimization.user_id
                else:
                    metric_expr = func.coalesce(func.sum(Payment.amount), 0)
                    user_column = Payment.user_id
                grouped = (
                    await db.execute(
                        select(user_column, metric_expr)
                        .where(*series_filters)
                        .group_by(user_column)
                    )
                ).all()
                grouped_ids = [str(user_id) for user_id, _amount in grouped if user_id]
                providers = await _provider_map(db, grouped_ids)
                values: dict[str, int] = defaultdict(int)
                users: dict[str, int] = defaultdict(int)
                for user_id, amount in grouped:
                    if not user_id:
                        continue
                    label = value or providers.get(str(user_id), "unknown")
                    values[label] += int(amount or 0)
                    users[label] += 1
                for label, amount in values.items():
                    _append_group(label, amount, users[label])
        elif dimension == "feature" and metric == "events":
            group_rows = (
                await db.execute(
                    select(
                        UsageAnalytics.action,
                        func.count(UsageAnalytics.id),
                        func.count(func.distinct(UsageAnalytics.user_id)),
                    )
                    .where(*series_filters)
                    .group_by(UsageAnalytics.action)
                )
            ).all()
            for label, amount, users in group_rows:
                _append_group(str(label), int(amount or 0), int(users or 0))

        breakdown.sort(key=lambda item: (-item["value"], item["label"]))
        response = _response(
            points=points,
            breakdown=breakdown[:MAX_BREAKDOWN_GROUPS],
            total=total,
            suppressed_groups=suppressed_groups,
        )
        await _cache_set(cache_key, response)
        return response


admin_growth_service = AdminGrowthService()

"""Activation, retention, AI-cost, and dimension-filtered analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

User = models.User
Resume = models.Resume
Compilation = models.Compilation
Optimization = models.Optimization
UsageAnalytics = models.UsageAnalytics
Payment = models.Payment

ACTIVATION_STEPS = (
    ("signup", "Signup"),
    ("first_resume", "First résumé"),
    ("first_compile", "First compile"),
    ("first_export", "First export"),
    ("first_optimize", "First AI optimize"),
    ("first_paid", "First paid"),
)


def _day(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


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
        start = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = select(User.id, User.subscription_plan, User.created_at).where(User.created_at >= start)
        if plan:
            stmt = stmt.where(User.subscription_plan == plan)
        users = (await db.execute(stmt)).all()
        providers = await _provider_map(db, [row[0] for row in users])
        if provider:
            users = [row for row in users if providers.get(str(row[0])) == provider]
        user_ids = [str(row[0]) for row in users]
        first = await _first_events(db, user_ids)

        reached: dict[str, set[str]] = {key: set() for key, _label in ACTIVATION_STEPS}
        reached["signup"] = set(user_ids)
        signup_times = {str(user_id): created_at for user_id, _plan_id, created_at in users}
        for user_id in user_ids:
            signup_at = signup_times.get(user_id)
            if signup_at is None:
                continue
            deadline = signup_at + timedelta(days=activation_window_days)
            for key in ("first_resume", "first_compile", "first_export", "first_optimize", "first_paid"):
                timestamp = first.get(user_id, {}).get(key)
                if timestamp is not None and signup_at <= timestamp <= deadline:
                    reached[key].add(user_id)

        steps = []
        previous_set = reached["signup"]
        for key, label in ACTIVATION_STEPS:
            count = len(reached[key])
            denominator = len(previous_set)
            numerator = len(reached[key] & previous_set)
            steps.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                    "from_previous": _pct(numerator, denominator),
                    "from_signup": _pct(count, len(reached["signup"])),
                }
            )
            previous_set = reached[key]

        def _segment_rows(grouped: dict[str, list[str]]) -> list[dict[str, Any]]:
            return [
                {
                    "label": label,
                    "users": len(ids),
                    "steps": {key: len(reached[key] & set(ids)) for key, _label in ACTIVATION_STEPS},
                }
                for label, ids in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
            ]

        by_plan: dict[str, list[str]] = defaultdict(list)
        by_provider: dict[str, list[str]] = defaultdict(list)
        for user_id, plan_id, _created_at in users:
            by_plan[plan_id or "free"].append(str(user_id))
            by_provider[providers.get(str(user_id), "unknown")].append(str(user_id))

        return {
            "period_days": days,
            "activation_window_days": activation_window_days,
            "cohort_size": len(user_ids),
            "steps": steps,
            "by_plan": _segment_rows(by_plan),
            "by_provider": _segment_rows(by_provider),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def retention(self, db: AsyncSession, *, weeks: int = 8) -> dict[str, Any]:
        weeks = max(1, min(weeks, 26))
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=weeks * 7)
        users = (
            await db.execute(
                select(User.id, User.created_at).where(User.created_at >= start, User.created_at <= now)
            )
        ).all()
        user_ids = [str(row[0]) for row in users]
        signup = {str(user_id): created_at for user_id, created_at in users}
        active: dict[str, set[date]] = defaultdict(set)
        if user_ids:
            day_exprs = [
                select(UsageAnalytics.user_id, func.date_trunc("day", UsageAnalytics.created_at))
                .where(UsageAnalytics.user_id.in_(user_ids), UsageAnalytics.created_at >= start)
                .distinct(),
                select(Compilation.user_id, func.date_trunc("day", Compilation.created_at))
                .where(
                    Compilation.user_id.in_(user_ids),
                    Compilation.status == "completed",
                    Compilation.created_at >= start,
                )
                .distinct(),
                select(Optimization.user_id, func.date_trunc("day", Optimization.created_at))
                .where(Optimization.user_id.in_(user_ids), Optimization.created_at >= start)
                .distinct(),
            ]
            for stmt in day_exprs:
                for user_id, timestamp in (await db.execute(stmt)).all():
                    day = _day(timestamp)
                    if user_id and day is not None:
                        active[str(user_id)].add(day)

        cohorts: dict[date, list[str]] = defaultdict(list)
        for user_id in user_ids:
            created = signup.get(user_id)
            if created is None:
                continue
            cohort_day = _day(created)
            if cohort_day is None:
                continue
            monday = cohort_day - timedelta(days=cohort_day.weekday())
            cohorts[monday].append(user_id)

        def _retention_cell(ids: list[str], offset: int) -> dict[str, Any]:
            eligible = [
                user_id
                for user_id in ids
                if signup[user_id] <= now - timedelta(days=offset)
            ]
            retained = sum(
                1
                for user_id in eligible
                if (signup[user_id].date() + timedelta(days=offset)) in active.get(user_id, set())
            )
            return {
                "count": retained,
                "eligible": len(eligible),
                "rate": _pct(retained, len(eligible)) if len(eligible) >= 5 else None,
            }

        rows = []
        totals = {offset: {"count": 0, "eligible": 0} for offset in (1, 7, 30)}
        total_users = 0
        for week_start, ids in sorted(cohorts.items()):
            size = len(ids)
            total_users += size
            cells = {offset: _retention_cell(ids, offset) for offset in (1, 7, 30)}
            for offset, cell in cells.items():
                totals[offset]["count"] += cell["count"]
                totals[offset]["eligible"] += cell["eligible"]
            rows.append(
                {
                    "week_start": week_start.isoformat(),
                    "cohort_size": size,
                    "d1": cells[1],
                    "d7": cells[7],
                    "d30": cells[30],
                }
            )
        return {
            "weeks": weeks,
            "cohorts": rows,
            "overall": {
                "cohort_size": total_users,
                "d1": {
                    **totals[1],
                    "rate": _pct(totals[1]["count"], totals[1]["eligible"]) if totals[1]["eligible"] >= 5 else None,
                },
                "d7": {
                    **totals[7],
                    "rate": _pct(totals[7]["count"], totals[7]["eligible"]) if totals[7]["eligible"] >= 5 else None,
                },
                "d30": {
                    **totals[30],
                    "rate": _pct(totals[30]["count"], totals[30]["eligible"]) if totals[30]["eligible"] >= 5 else None,
                },
            },
            "minimum_cohort_size": 5,
            "generated_at": now.isoformat(),
        }

    async def ai_cost(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        plan: str | None = None,
        feature: str | None = None,
        persona: str | None = None,
        invoice_total_minor: int | None = None,
        invoice_reference: str | None = None,
    ) -> dict[str, Any]:
        from .admin_ai_cost_service import ai_cost_snapshot

        return await ai_cost_snapshot(
            db,
            days=days,
            plan=plan,
            feature=feature,
            persona=persona,
            invoice_total_minor=invoice_total_minor,
            invoice_reference=invoice_reference,
        )

    async def timeseries(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        metric: str = "events",
        dimension: str | None = None,
        value: str | None = None,
    ) -> dict[str, Any]:
        days = max(1, min(days, 365))
        start = datetime.now(timezone.utc) - timedelta(days=days)
        metric = metric if metric in {"events", "compilations", "optimizations", "revenue"} else "events"
        dimension = dimension if dimension in {"plan", "provider", "feature"} else None
        if dimension == "feature" and metric != "events":
            raise ValueError("Feature filters are only supported for the events metric")

        provider_ids: list[str] | None = None
        if dimension == "provider" and value:
            provider_ids = await _provider_user_ids(db, value)
            if not provider_ids:
                return {"metric": metric, "dimension": dimension, "value": value, "points": [], "breakdown": [], "total": 0}

        if metric == "events":
            model, time_col = UsageAnalytics, UsageAnalytics.created_at
            metric_col = func.count(UsageAnalytics.id)
            join_user = True
        elif metric == "compilations":
            model, time_col = Compilation, Compilation.created_at
            metric_col = func.count(Compilation.id)
            join_user = True
        elif metric == "optimizations":
            model, time_col = Optimization, Optimization.created_at
            metric_col = func.count(Optimization.id)
            join_user = True
        else:
            model, time_col = Payment, Payment.created_at
            metric_col = func.coalesce(func.sum(Payment.amount), 0)
            join_user = True

        filters = [time_col >= start]
        if metric == "compilations":
            filters.append(Compilation.status == "completed")
        if metric == "revenue":
            filters.extend(
                [
                    Payment.currency == "INR",
                    Payment.status.in_(("paid", "partially_refunded", "captured", "refunded")),
                ]
            )
        if dimension == "plan" and value and metric != "events":
            filters.append(User.subscription_plan == value)
        if dimension == "plan" and value and metric == "events":
            filters.append(UsageAnalytics.user_id.in_(select(User.id).where(User.subscription_plan == value)))
        if dimension == "feature" and value and metric == "events":
            filters.append(UsageAnalytics.action == value)
        if provider_ids is not None:
            filters.append(model.user_id.in_(provider_ids))

        day_expr = func.date_trunc("day", time_col).label("day")
        stmt = select(day_expr, metric_col.label("value"))
        if join_user and metric != "events":
            stmt = stmt.join(User, User.id == model.user_id)
        elif metric == "events" and dimension == "plan" and value:
            pass
        for condition in filters:
            stmt = stmt.where(condition)
        stmt = stmt.group_by(day_expr).order_by(day_expr)
        rows = (await db.execute(stmt)).all()
        if metric == "revenue":
            points = [{"date": row.day.date().isoformat(), "value": round(int(row.value or 0) / 100, 2)} for row in rows if row.day]
        else:
            points = [{"date": row.day.date().isoformat(), "value": int(row.value or 0)} for row in rows if row.day]

        breakdown: list[dict[str, Any]] = []
        if dimension == "plan":
            plan_expr = User.subscription_plan
            breakdown_stmt = select(plan_expr, func.count() if metric != "revenue" else func.coalesce(func.sum(Payment.amount), 0))
            if metric == "events":
                breakdown_stmt = select(plan_expr, func.count(UsageAnalytics.id)).join(
                    User, User.id == UsageAnalytics.user_id
                )
            else:
                breakdown_stmt = breakdown_stmt.join(User, User.id == model.user_id)
            for condition in filters:
                breakdown_stmt = breakdown_stmt.where(condition)
            breakdown_stmt = breakdown_stmt.group_by(plan_expr)
            for label, amount in (await db.execute(breakdown_stmt)).all():
                breakdown.append({
                    "label": label or "free",
                    "value": round(int(amount or 0) / 100, 2) if metric == "revenue" else int(amount or 0),
                })
        elif dimension == "feature" and metric == "events":
            stmt = select(UsageAnalytics.action, func.count(UsageAnalytics.id)).where(*filters).group_by(UsageAnalytics.action)
            for label, amount in (await db.execute(stmt)).all():
                breakdown.append({"label": label, "value": int(amount or 0)})
        elif dimension == "provider":
            if metric == "events":
                grouped = (
                    await db.execute(select(UsageAnalytics.user_id, func.count(UsageAnalytics.id)).where(*filters).group_by(UsageAnalytics.user_id))
                ).all()
            else:
                grouped = (
                    await db.execute(
                        select(model.user_id, metric_col.label("value"))
                        .where(*filters)
                        .group_by(model.user_id)
                    )
                ).all()
            # Resolve providers only for users that actually contributed to the
            # grouped result. A filter match is labelled with the requested
            # provider even when the account has other linked identities.
            grouped_ids = [str(user_id) for user_id, _amount in grouped if user_id]
            providers = await _provider_map(db, grouped_ids)
            provider_counts: dict[str, int] = defaultdict(int)
            for user_id, amount in grouped:
                label = value if value else providers.get(str(user_id), "unknown")
                normalized = round(int(amount or 0) / 100, 2) if metric == "revenue" else int(amount or 0)
                provider_counts[label] += normalized
            breakdown = [{"label": key, "value": val} for key, val in sorted(provider_counts.items(), key=lambda item: -item[1])]

        return {
            "metric": metric,
            "dimension": dimension,
            "value": value,
            "points": points,
            "breakdown": sorted(breakdown, key=lambda item: -item["value"]),
            "total": round(sum(point["value"] for point in points), 2) if metric == "revenue" else sum(point["value"] for point in points),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


admin_growth_service = AdminGrowthService()

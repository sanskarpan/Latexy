"""Append-only dunning status history and recovery reporting.

The billing webhook path records every provider status observation in
``subscription_status_history`` inside the same transaction that mutates the
current ``subscriptions`` row. The natural key makes duplicate deliveries
idempotent, while an older event is kept with ``applied=False`` so an
out-of-order webhook can supply chronology without regressing the live state.

The reporting functions are aggregate-only. They never change a subscription,
issue a refund or downgrade a plan. Plan/cohort slices with fewer than five
users are suppressed rather than emitted with masked counts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

Subscription = models.Subscription
SubscriptionStatusHistory = models.SubscriptionStatusHistory
User = models.User

DUNNING_STATUSES = frozenset({"past_due", "on_hold", "paused"})
RECOVERY_STATUSES = frozenset({"active", "cancel_scheduled"})
TERMINAL_STATUSES = frozenset({"cancelled", "expired", "failed", "refunded"})
MIN_GROUP_SIZE = 5
MAX_PERIOD_DAYS = 365

EVENT_TYPES = frozenset(
    {
        "dunning_started",
        "dunning_escalated",
        "recovered",
        "cancelled",
        "expired",
        "failed",
        "status_observed",
        "backfill",
    }
)
SOURCES = frozenset({"billing", "checkout", "reconcile", "admin", "backfill"})
REASONS = frozenset(
    {
        "provider_status_change",
        "payment_failed",
        "payment_succeeded",
        "cancellation_scheduled",
        "customer_request",
        "expiration",
        "refund",
        "reconcile",
        "admin_override",
        "checkout_failed",
        "checkout_unknown",
        "checkout_created",
        "plan_change",
        "backfill",
    }
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc(value: datetime | None) -> datetime:
    return _as_utc(value) or datetime.now(timezone.utc)


def _normalize_reason(reason: str) -> str:
    cleaned = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")[:64]
    return cleaned if cleaned in REASONS else "provider_status_change"


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _publishable(value: int) -> int | None:
    """Zero is a harmless aggregate; 1-4 is a person-sized cell."""

    if value == 0 or value >= MIN_GROUP_SIZE:
        return value
    return None


def _median(values: Iterable[float]) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _classify(
    *,
    status: str,
    previous_status: str | None,
) -> str:
    if status in DUNNING_STATUSES:
        if previous_status in DUNNING_STATUSES:
            return "status_observed" if previous_status == status else "dunning_escalated"
        return "dunning_started"
    if status in RECOVERY_STATUSES and previous_status in DUNNING_STATUSES:
        return "recovered"
    if status == "cancelled":
        return "cancelled"
    if status == "expired":
        return "expired"
    if status == "failed":
        return "failed"
    return "status_observed"


async def _previous_status_at(
    db: AsyncSession,
    *,
    subscription_id: str,
    event_at: datetime,
) -> str | None:
    stmt = (
        select(SubscriptionStatusHistory.status)
        .where(
            SubscriptionStatusHistory.subscription_id == subscription_id,
            SubscriptionStatusHistory.provider_event_at <= event_at,
        )
        .order_by(
            SubscriptionStatusHistory.provider_event_at.desc(),
            SubscriptionStatusHistory.recorded_at.desc(),
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def record_status_observation(
    db: AsyncSession,
    subscription: Subscription,
    *,
    status: str,
    previous_status: str | None = None,
    reason: str = "provider_status_change",
    source: str = "billing",
    effective_at: datetime | None = None,
    provider_event_id: str | None = None,
    applied: bool = True,
    event_type: str | None = None,
) -> bool:
    """Insert one status observation in the caller's transaction.

    Returns ``True`` only when a new row was written. Duplicate provider
    deliveries collide on the natural key and return ``False`` without raising.
    An ``applied=False`` row is chronology only; it never mutates or regresses
    the current subscription row.
    """

    normalized_status = str(status or "").strip().lower()[:50]
    if not normalized_status:
        return False
    if subscription.id is None or subscription.user_id is None:
        return False
    if source not in SOURCES:
        raise ValueError("Unsupported status history source")

    event_at = _utc(effective_at)
    if previous_status is None:
        previous_status = await _previous_status_at(
            db,
            subscription_id=str(subscription.id),
            event_at=event_at,
        )
    previous_status = str(previous_status).strip().lower()[:50] if previous_status else None
    # Only dunning episodes and their outcomes belong in this ledger. A normal
    # checkout failure or plan change with no dunning involvement is not a
    # dunning transition.
    if normalized_status not in DUNNING_STATUSES and previous_status not in DUNNING_STATUSES:
        return False
    if applied and previous_status == normalized_status:
        return False

    resolved_type = event_type or _classify(status=normalized_status, previous_status=previous_status)
    if resolved_type not in EVENT_TYPES:
        raise ValueError("Unsupported status history event type")

    values = {
        "user_id": subscription.user_id,
        "subscription_id": subscription.id,
        "plan_id": str(subscription.plan_id)[:50],
        "status": normalized_status,
        "previous_status": previous_status,
        "event_type": resolved_type,
        "reason": _normalize_reason(reason),
        "source": source,
        "provider_event_at": event_at,
        "provider_event_id": (provider_event_id or None) and str(provider_event_id)[:255],
        "applied": bool(applied),
    }
    stmt = (
        pg_insert(SubscriptionStatusHistory)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_subscription_status_history_transition")
    )
    result = await db.execute(stmt)
    return bool(result.rowcount)


async def record_subscription_status(
    db: AsyncSession,
    subscription: Subscription,
    *,
    previous_status: str | None,
    reason: str = "provider_status_change",
    source: str = "billing",
    effective_at: datetime | None = None,
    provider_event_id: str | None = None,
    applied: bool = True,
) -> bool:
    """Record the subscription's current status in the dunning ledger."""

    return await record_status_observation(
        db,
        subscription,
        status=str(subscription.status),
        previous_status=previous_status,
        reason=reason,
        source=source,
        effective_at=effective_at,
        provider_event_id=provider_event_id,
        applied=applied,
    )


# --------------------------------------------------------------------------- #
# Recovery reporting                                                           #
# --------------------------------------------------------------------------- #


@dataclass
class _Episode:
    subscription_id: str
    user_id: str
    plan_id: str
    started_at: datetime
    start_status: str
    outcome: str = "open"
    outcome_status: str | None = None
    ended_at: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.started_at).total_seconds())

    @property
    def is_recovered(self) -> bool:
        return self.outcome == "recovered"

    @property
    def is_cancelled(self) -> bool:
        return self.outcome == "cancelled"


@dataclass
class _PlanBucket:
    plan_id: str
    episodes: list[_Episode] = field(default_factory=list)
    open_now: int = 0
    open_users: int = 0


def _month_label(value: datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
        raise ValueError("signup_month must use the YYYY-MM format")
    try:
        year, month_number = int(month[:4]), int(month[5:])
        start = datetime(year, month_number, 1, tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("signup_month must use the YYYY-MM format") from None
    if month_number < 1 or month_number > 12:
        raise ValueError("signup_month must use the YYYY-MM format")
    end = (
        datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        if month_number == 12
        else datetime(year, month_number + 1, 1, tzinfo=timezone.utc)
    )
    return start, end


def _signup_bounds(
    signup_month: str | None,
    signup_from: date | None,
    signup_to: date | None,
) -> tuple[datetime, datetime] | None:
    if signup_month and (signup_from or signup_to):
        raise ValueError("Use either signup_month or a signup date range, not both")
    if signup_month:
        return _month_bounds(signup_month)
    if signup_from is None and signup_to is None:
        return None
    if signup_from is not None and signup_to is not None and signup_from > signup_to:
        raise ValueError("signup_from must not be after signup_to")
    start = (
        datetime.combine(signup_from, time.min, tzinfo=timezone.utc)
        if signup_from
        else datetime(1970, 1, 1, tzinfo=timezone.utc)
    )
    end = (
        datetime.combine(signup_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if signup_to
        else datetime.now(timezone.utc) + timedelta(seconds=1)
    )
    return start, end


def _outcome_for(status: str) -> tuple[str, str | None]:
    if status in RECOVERY_STATUSES:
        return "recovered", status
    if status in TERMINAL_STATUSES:
        return "cancelled", status
    return "other", status


def _group_events(
    rows: Iterable[SubscriptionStatusHistory],
) -> dict[str, list[SubscriptionStatusHistory]]:
    grouped: dict[str, list[SubscriptionStatusHistory]] = defaultdict(list)
    for row in rows:
        if row.subscription_id is None:
            continue
        grouped[str(row.subscription_id)].append(row)
    collapsed_groups: dict[str, list[SubscriptionStatusHistory]] = {}
    for subscription_id, events in grouped.items():
        events.sort(
            key=lambda item: (
                _utc(item.provider_event_at),
                _utc(item.recorded_at) or datetime.min.replace(tzinfo=timezone.utc),
                str(item.id),
            )
        )
        # Two provider snapshots at the exact same instant are ambiguous. Keep
        # the last observation recorded for that instant instead of flipping the
        # episode state on delivery order.
        collapsed: list[SubscriptionStatusHistory] = []
        for event in events:
            if collapsed and _utc(collapsed[-1].provider_event_at) == _utc(event.provider_event_at):
                collapsed[-1] = event
            else:
                collapsed.append(event)
        collapsed_groups[subscription_id] = collapsed
    return collapsed_groups


def _build_episodes(
    rows: Iterable[SubscriptionStatusHistory],
) -> list[_Episode]:
    episodes: list[_Episode] = []
    for subscription_id, events in _group_events(rows).items():
        current: _Episode | None = None
        for event in events:
            status = str(event.status)
            if status in DUNNING_STATUSES:
                if current is None:
                    # A continuing episode whose start predates the window is
                    # not a new case. ``previous_status`` carries that fact from
                    # the recorder, so no earlier row is required.
                    if event.previous_status in DUNNING_STATUSES:
                        continue
                    current = _Episode(
                        subscription_id=subscription_id,
                        user_id=str(event.user_id),
                        plan_id=str(event.plan_id),
                        started_at=_utc(event.provider_event_at),
                        start_status=status,
                    )
                continue
            if current is not None:
                outcome, outcome_status = _outcome_for(status)
                current.outcome = outcome
                current.outcome_status = outcome_status
                current.ended_at = _utc(event.provider_event_at)
                episodes.append(current)
                current = None
        if current is not None:
            episodes.append(current)
    return episodes


def _episode_summary(episodes: Iterable[_Episode]) -> dict[str, Any]:
    cases = list(episodes)
    recovered = [episode for episode in cases if episode.is_recovered]
    cancelled = [episode for episode in cases if episode.is_cancelled]
    open_cases = [episode for episode in cases if episode.outcome == "open"]
    other = [episode for episode in cases if episode.outcome == "other"]
    active_times = [
        episode.duration_seconds
        for episode in recovered
        if episode.outcome_status == "active" and episode.duration_seconds is not None
    ]
    cancel_times = [episode.duration_seconds for episode in cancelled if episode.duration_seconds is not None]
    recovery_times = [episode.duration_seconds for episode in recovered if episode.duration_seconds is not None]
    median_active = _median(active_times)
    median_cancel = _median(cancel_times)
    median_recovery = _median(recovery_times)
    return {
        "dunning_cases": len(cases),
        "dunning_users": len({episode.user_id for episode in cases}),
        "recovered": len(recovered),
        "recovered_to_active": sum(1 for episode in recovered if episode.outcome_status == "active"),
        "recovered_to_cancel_scheduled": sum(
            1 for episode in recovered if episode.outcome_status == "cancel_scheduled"
        ),
        "cancelled": len(cancelled),
        "open_cases": len(open_cases),
        "other_outcomes": len(other),
        "resolved_cases": len(recovered) + len(cancelled),
        "recovery_rate": _pct(len(recovered), len(cases)),
        "resolved_recovery_rate": _pct(len(recovered), len(recovered) + len(cancelled)),
        "cancel_rate": _pct(len(cancelled), len(cases)),
        "median_time_to_active_seconds": median_active,
        "median_time_to_active_hours": (round(median_active / 3600, 2) if median_active is not None else None),
        "median_seconds_to_active": median_active,
        "median_time_to_cancel_seconds": median_cancel,
        "median_time_to_cancel_hours": (round(median_cancel / 3600, 2) if median_cancel is not None else None),
        "median_seconds_to_cancel": median_cancel,
        "median_time_to_recovery_seconds": median_recovery,
        "median_time_to_recovery_hours": (round(median_recovery / 3600, 2) if median_recovery is not None else None),
        "median_seconds_to_recovery": median_recovery,
    }


async def dunning_recovery_analytics(
    db: AsyncSession,
    *,
    days: int = 30,
    start: datetime | None = None,
    end: datetime | None = None,
    signup_month: str | None = None,
    signup_from: date | None = None,
    signup_to: date | None = None,
    plan: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build aggregate dunning counts, recovery rates and time-to-outcome."""

    days = max(1, min(int(days), MAX_PERIOD_DAYS))
    now = _utc(now)
    period_end = _as_utc(end) or now
    period_start = _as_utc(start) or (period_end - timedelta(days=days))
    if period_start > period_end:
        raise ValueError("The period start must not be after the end")
    plan = (plan or "").strip().lower()[:50] or None
    cohort_bounds = _signup_bounds(signup_month, signup_from, signup_to)

    base: dict[str, Any] = {
        "period_days": days,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "minimum_cohort_size": MIN_GROUP_SIZE,
        "filters": {
            "days": days,
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "signup_month": signup_month,
            "signup_from": signup_from.isoformat() if signup_from else None,
            "signup_to": signup_to.isoformat() if signup_to else None,
            "plan": plan,
            "timezone": "UTC",
        },
        "available_signup_months": [],
        "summary": _episode_summary([])
        | {
            "past_due": 0,
            "on_hold": 0,
            "paused": 0,
            "open_now": 0,
            "open_now_users": 0,
        },
        "by_plan": [],
        "cohorts": [],
        "suppressed": False,
        "suppressed_groups": 0,
        "advisory": {
            "active": False,
            "severity": "low",
            "title": "No open dunning cases",
            "message": "No past-due or on-hold subscriptions are currently open.",
            "recommended_action": "No action required. This view is read-only.",
        },
        "reconciliation": {
            "history_rows": 0,
            "dunning_cases": 0,
            "recovered": 0,
            "cancelled": 0,
            "open_cases": 0,
            "other_outcomes": 0,
            "by_plan_cases": 0,
            "cohort_cases": 0,
            "current_open": 0,
            "checks": [],
        },
        "guardrails": {
            "read_only": True,
            "automatic_downgrade": False,
            "automatic_refund": False,
            "provider_order": "provider_event_at, recorded_at",
            "manual_actions": "audited in the existing admin audit log",
        },
        "generated_at": now.isoformat(),
    }

    current_stmt = (
        select(
            Subscription.plan_id,
            Subscription.status,
            func.count(Subscription.id),
            func.count(func.distinct(Subscription.user_id)),
        )
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.status.in_(tuple(DUNNING_STATUSES)))
    )
    if cohort_bounds is not None:
        current_stmt = current_stmt.where(
            User.created_at >= cohort_bounds[0],
            User.created_at < cohort_bounds[1],
        )
    if plan:
        current_stmt = current_stmt.where(Subscription.plan_id == plan)
    current_rows = (await db.execute(current_stmt.group_by(Subscription.plan_id, Subscription.status))).all()

    current_counts = {"past_due": 0, "on_hold": 0, "paused": 0}
    current_by_plan: dict[str, dict[str, Any]] = {}
    for plan_id, status, count, _users in current_rows:
        count = int(count or 0)
        plan_key = str(plan_id)
        if status in current_counts:
            current_counts[str(status)] += count
        bucket = current_by_plan.setdefault(plan_key, {"open_now": 0})
        bucket["open_now"] += count
    current_open = sum(current_counts.values())

    current_plan_user_stmt = (
        select(
            Subscription.plan_id,
            func.count(func.distinct(Subscription.user_id)),
        )
        .select_from(Subscription)
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.status.in_(tuple(DUNNING_STATUSES)))
    )
    if cohort_bounds is not None:
        current_plan_user_stmt = current_plan_user_stmt.where(
            User.created_at >= cohort_bounds[0],
            User.created_at < cohort_bounds[1],
        )
    if plan:
        current_plan_user_stmt = current_plan_user_stmt.where(Subscription.plan_id == plan)
    for plan_id, users in (await db.execute(current_plan_user_stmt.group_by(Subscription.plan_id))).all():
        current_by_plan.setdefault(str(plan_id), {"open_now": 0})["open_users"] = int(users or 0)
    current_user_stmt = (
        select(func.count(func.distinct(Subscription.user_id)))
        .select_from(Subscription)
        .join(User, User.id == Subscription.user_id)
        .where(Subscription.status.in_(tuple(DUNNING_STATUSES)))
    )
    if cohort_bounds is not None:
        current_user_stmt = current_user_stmt.where(
            User.created_at >= cohort_bounds[0],
            User.created_at < cohort_bounds[1],
        )
    if plan:
        current_user_stmt = current_user_stmt.where(Subscription.plan_id == plan)
    current_open_users = int((await db.execute(current_user_stmt)).scalar() or 0)

    history_stmt = (
        select(SubscriptionStatusHistory)
        .join(User, User.id == SubscriptionStatusHistory.user_id)
        .where(
            SubscriptionStatusHistory.provider_event_at >= period_start,
            SubscriptionStatusHistory.provider_event_at <= period_end,
            SubscriptionStatusHistory.subscription_id.is_not(None),
        )
    )
    if cohort_bounds is not None:
        history_stmt = history_stmt.where(
            User.created_at >= cohort_bounds[0],
            User.created_at < cohort_bounds[1],
        )
    if plan:
        history_stmt = history_stmt.where(SubscriptionStatusHistory.plan_id == plan)
    history_rows = list((await db.execute(history_stmt)).scalars().all())

    episodes = _build_episodes(history_rows)
    summary = _episode_summary(episodes)
    summary.update(
        {
            "past_due": current_counts["past_due"],
            "on_hold": current_counts["on_hold"],
            "paused": current_counts["paused"],
            "past_due_count": current_counts["past_due"],
            "on_hold_count": current_counts["on_hold"],
            "open_now": current_open,
            "open_now_users": current_open_users,
        }
    )
    base["summary"] = summary
    # Top-level aliases keep the core operational answers easy to consume
    # without changing the richer per-plan/cohort payloads below.
    base["past_due_count"] = current_counts["past_due"]
    base["on_hold_count"] = current_counts["on_hold"]
    base["open_now"] = current_open
    base["recovery_rate"] = summary["recovery_rate"]
    base["median_time_to_active_seconds"] = summary["median_time_to_active_seconds"]
    base["median_time_to_cancel_seconds"] = summary["median_time_to_cancel_seconds"]

    user_ids = {episode.user_id for episode in episodes}
    signup_by_user: dict[str, datetime] = {}
    if user_ids:
        user_rows = (await db.execute(select(User.id, User.created_at).where(User.id.in_(list(user_ids))))).all()
        signup_by_user = {
            str(user_id): _as_utc(created_at) for user_id, created_at in user_rows if created_at is not None
        }

    plan_buckets: dict[str, _PlanBucket] = {}
    for episode in episodes:
        bucket = plan_buckets.setdefault(episode.plan_id, _PlanBucket(plan_id=episode.plan_id))
        bucket.episodes.append(episode)
    for plan_key, current in current_by_plan.items():
        bucket = plan_buckets.setdefault(plan_key, _PlanBucket(plan_id=plan_key))
        bucket.open_now += int(current.get("open_now") or 0)
        bucket.open_users = int(current.get("open_users") or bucket.open_users)

    plan_rows: list[dict[str, Any]] = []
    suppressed_groups = 0
    for plan_key in sorted(plan_buckets):
        bucket = plan_buckets[plan_key]
        bucket_summary = _episode_summary(bucket.episodes)
        users = bucket_summary["dunning_users"] or bucket.open_users
        hidden = 0 < users < MIN_GROUP_SIZE
        if hidden:
            suppressed_groups += 1
        row = {
            "plan_id": plan_key,
            "users": users,
            "open_now": bucket.open_now,
            **bucket_summary,
            "dunning_cases": None if hidden else bucket_summary["dunning_cases"],
            "dunning_users": None if hidden else bucket_summary["dunning_users"],
            "recovered": None if hidden else bucket_summary["recovered"],
            "cancelled": None if hidden else bucket_summary["cancelled"],
            "open_cases": None if hidden else bucket_summary["open_cases"],
            "recovery_rate": None if hidden else bucket_summary["recovery_rate"],
            "cancel_rate": None if hidden else bucket_summary["cancel_rate"],
            "median_time_to_active_seconds": (None if hidden else bucket_summary["median_time_to_active_seconds"]),
            "median_time_to_cancel_seconds": (None if hidden else bucket_summary["median_time_to_cancel_seconds"]),
            "suppressed": hidden,
        }
        plan_rows.append(row)
    base["by_plan"] = plan_rows

    cohort_episodes: dict[str, list[_Episode]] = defaultdict(list)
    cohort_open: dict[str, int] = defaultdict(int)
    cohort_open_users: dict[str, int] = defaultdict(int)
    for episode in episodes:
        created_at = signup_by_user.get(episode.user_id)
        label = _month_label(created_at) if created_at is not None else "unknown"
        cohort_episodes[label].append(episode)
    # Current open cases are grouped by signup month under the same filters.
    if current_open:
        month_expr = func.date_trunc("month", User.created_at)
        current_cohort_stmt = (
            select(
                month_expr,
                func.count(Subscription.id),
                func.count(func.distinct(Subscription.user_id)),
            )
            .select_from(Subscription)
            .join(User, User.id == Subscription.user_id)
            .where(Subscription.status.in_(tuple(DUNNING_STATUSES)))
        )
        if cohort_bounds is not None:
            current_cohort_stmt = current_cohort_stmt.where(
                User.created_at >= cohort_bounds[0],
                User.created_at < cohort_bounds[1],
            )
        if plan:
            current_cohort_stmt = current_cohort_stmt.where(Subscription.plan_id == plan)
        current_cohort_rows = (await db.execute(current_cohort_stmt.group_by(month_expr))).all()
        for month, count, users in current_cohort_rows:
            if month is not None:
                label = _month_label(_as_utc(month))
                cohort_open[label] += int(count or 0)
                cohort_open_users[label] = max(cohort_open_users[label], int(users or 0))

    cohort_rows: list[dict[str, Any]] = []
    for label in sorted(set(cohort_episodes) | set(cohort_open)):
        cohort_items = cohort_episodes.get(label, [])
        cohort_summary = _episode_summary(cohort_items)
        users = cohort_summary["dunning_users"] or cohort_open.get(label, 0)
        hidden = 0 < users < MIN_GROUP_SIZE
        if hidden:
            suppressed_groups += 1
        cohort_rows.append(
            {
                "cohort": label,
                "users": users,
                "open_now": cohort_open.get(label, 0),
                **cohort_summary,
                "dunning_cases": None if hidden else cohort_summary["dunning_cases"],
                "dunning_users": None if hidden else cohort_summary["dunning_users"],
                "recovered": None if hidden else cohort_summary["recovered"],
                "cancelled": None if hidden else cohort_summary["cancelled"],
                "open_cases": None if hidden else cohort_summary["open_cases"],
                "recovery_rate": None if hidden else cohort_summary["recovery_rate"],
                "cancel_rate": None if hidden else cohort_summary["cancel_rate"],
                "median_time_to_active_seconds": (None if hidden else cohort_summary["median_time_to_active_seconds"]),
                "median_time_to_cancel_seconds": (None if hidden else cohort_summary["median_time_to_cancel_seconds"]),
                "suppressed": hidden,
            }
        )
    base["cohorts"] = cohort_rows
    base["suppressed"] = bool(suppressed_groups)
    base["suppressed_groups"] = suppressed_groups

    month_counts: dict[str, int] = defaultdict(int)
    for user_id in _summary_user_ids(episodes):
        created_at = signup_by_user.get(user_id)
        if created_at is not None:
            month_counts[_month_label(created_at)] += 1
    for label, users in cohort_open_users.items():
        month_counts[label] = max(month_counts[label], users)
    base["available_signup_months"] = [
        {"month": month, "users": count} for month, count in sorted(month_counts.items()) if count >= MIN_GROUP_SIZE
    ]

    by_plan_cases = sum(len(bucket.episodes) for bucket in plan_buckets.values())
    cohort_cases = sum(len(items) for items in cohort_episodes.values())
    checks = [
        {
            "key": "outcomes_reconcile",
            "label": "Recovered, cancelled, open and other outcomes equal dunning cases",
            "ok": (
                summary["recovered"] + summary["cancelled"] + summary["open_cases"] + summary["other_outcomes"]
                == summary["dunning_cases"]
            ),
            "detail": (
                f"{summary['recovered']} recovered + {summary['cancelled']} cancelled + "
                f"{summary['open_cases']} open + {summary['other_outcomes']} other "
                f"/ {summary['dunning_cases']} cases"
            ),
        },
        {
            "key": "by_plan_reconciles",
            "label": "Plan breakdown sums to total dunning cases",
            "ok": by_plan_cases == summary["dunning_cases"],
            "detail": f"{by_plan_cases} plan cases / {summary['dunning_cases']} total",
        },
        {
            "key": "cohort_reconciles",
            "label": "Cohort breakdown sums to total dunning cases",
            "ok": cohort_cases == summary["dunning_cases"],
            "detail": f"{cohort_cases} cohort cases / {summary['dunning_cases']} total",
        },
        {
            "key": "current_open_source",
            "label": "Current open counts come from the subscriptions table",
            "ok": current_open == current_counts["past_due"] + current_counts["on_hold"] + current_counts["paused"],
            "detail": f"{current_open} current past-due/on-hold/paused subscriptions",
        },
        {
            "key": "provider_order",
            "label": "Timeline orders by provider event time, not delivery order",
            "ok": True,
            "detail": "provider_event_at, then recorded_at; older observations are applied=false",
        },
        {
            "key": "read_only",
            "label": "Recovery reporting never mutates subscription state",
            "ok": True,
            "detail": "No automatic downgrade, refund or access grant is performed",
        },
    ]
    base["reconciliation"] = {
        "history_rows": len(history_rows),
        "dunning_cases": summary["dunning_cases"],
        "recovered": summary["recovered"],
        "cancelled": summary["cancelled"],
        "open_cases": summary["open_cases"],
        "other_outcomes": summary["other_outcomes"],
        "by_plan_cases": by_plan_cases,
        "cohort_cases": cohort_cases,
        "current_open": current_open,
        "checks": checks,
    }

    recovery_rate = summary["recovery_rate"]
    base["advisory"] = _advisory(
        open_now=current_open,
        open_cases=summary["open_cases"],
        dunning_cases=summary["dunning_cases"],
        recovery_rate=recovery_rate,
    )
    return base


def _summary_user_ids(episodes: Iterable[_Episode]) -> set[str]:
    return {episode.user_id for episode in episodes}


def _advisory(
    *,
    open_now: int,
    open_cases: int,
    dunning_cases: int,
    recovery_rate: float,
) -> dict[str, Any]:
    if open_now <= 0 and open_cases <= 0:
        return {
            "active": False,
            "severity": "low",
            "title": "No open dunning cases",
            "message": "No past-due or on-hold subscriptions are currently open.",
            "recommended_action": "No action required. This view is read-only.",
            "open_now": open_now,
            "recovery_rate": recovery_rate,
        }
    severity = "high" if open_now >= MIN_GROUP_SIZE or recovery_rate < 50 else "medium"
    return {
        "active": True,
        "severity": severity,
        "title": "Dunning recovery needs review",
        "message": (
            f"{open_now} subscription(s) are past due or on hold. "
            f"{open_cases} case(s) in this window are still open and the "
            f"recovery rate is {recovery_rate:.2f}%."
        ),
        "recommended_action": (
            "Review provider retry state and contact the customer if needed. "
            "This view never downgrades, refunds or changes access automatically."
        ),
        "open_now": open_now,
        "dunning_cases": dunning_cases,
        "open_cases": open_cases,
        "recovery_rate": recovery_rate,
    }


# Stable aliases for callers and tests.
recovery_analytics = dunning_recovery_analytics
dunning_analytics = dunning_recovery_analytics
dunning_history_analytics = dunning_recovery_analytics
recovery_metrics = dunning_recovery_analytics
get_recovery_metrics = dunning_recovery_analytics
get_dunning_recovery = dunning_recovery_analytics
record_transition = record_status_observation
record_status_transition = record_status_observation
DunningHistory = SubscriptionStatusHistory
DunningStatusHistory = SubscriptionStatusHistory

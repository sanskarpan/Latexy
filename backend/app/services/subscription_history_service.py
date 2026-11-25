"""Append-only subscription transitions and plan-movement/churn analytics.

The history ledger is the only source of plan movements and churn. Provider
webhook logs, PostHog events and admin audit rows are never parsed into
financial metrics.

Writes happen inside the caller's billing transaction through
``record_subscription_transition``. The insert is an ``ON CONFLICT DO NOTHING``
statement keyed by ``(subscription_id, effective_at, plan_id, status)``; a
duplicate webhook, replay or reconciliation therefore records one transition,
not two. ``record_subscription_transition`` also skips a write when the locked
subscription already has the requested state, which covers no-op lifecycle
events.

Reads are aggregate-only. No email, name, document, provider payload or user
detail leaves the database; cohort rows below five subscribers are suppressed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_plan_config, settings
from ..database import models

User = models.User
Subscription = models.Subscription
SubscriptionHistory = models.SubscriptionHistory

PAID_STATUSES = frozenset({"active", "cancel_scheduled", "past_due", "on_hold", "paused"})
TERMINAL_STATUSES = frozenset({"cancelled", "expired", "failed", "refunded"})
MIN_SEGMENT_SIZE = 5
MAX_PERIOD_DAYS = 365

EVENT_TYPES = frozenset(
    {
        "subscription_created",
        "plan_changed",
        "status_changed",
        "activated",
        "renewed",
        "period_updated",
        "cancellation_scheduled",
        "cancelled",
        "expired",
        "payment_failed",
        "refunded",
        "checkout_failed",
        "checkout_unknown",
        "admin_override",
        "backfill",
    }
)
SOURCES = frozenset({"billing", "checkout", "reconcile", "admin", "backfill"})
REASONS = frozenset(
    {
        "checkout_created",
        "checkout_failed",
        "checkout_unknown",
        "payment_succeeded",
        "plan_change",
        "provider_status_change",
        "customer_request",
        "cancellation_scheduled",
        "payment_failed",
        "expiration",
        "refund",
        "reconcile",
        "admin_override",
        "backfill",
    }
)


@dataclass(frozen=True)
class SubscriptionState:
    plan_id: str
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _utc(value: datetime | None) -> datetime:
    return _as_utc(value) or datetime.now(timezone.utc)


def snapshot(subscription: Subscription) -> SubscriptionState:
    """Capture the mutable fields that define a subscription transition."""

    return SubscriptionState(
        plan_id=str(subscription.plan_id),
        status=str(subscription.status),
        current_period_start=_as_utc(subscription.current_period_start),
        current_period_end=_as_utc(subscription.current_period_end),
    )


def classify_transition(
    before: SubscriptionState | None, after: SubscriptionState
) -> str:
    """Derive the allowlisted event type from a before/after snapshot."""

    if before is None:
        return "subscription_created"
    # Terminal/scheduled cancellation is the primary fact even when the same
    # provider event also changed the plan; previous_plan_id still preserves the
    # movement for upgrade/downgrade analytics.
    if after.status == "cancelled":
        return "cancelled"
    if after.status == "expired":
        return "expired"
    if after.status == "failed":
        return "payment_failed"
    if after.status == "refunded":
        return "refunded"
    if after.status == "cancel_scheduled":
        return "cancellation_scheduled"
    if before.plan_id != after.plan_id:
        return "plan_changed"
    if before.status != after.status:
        if after.status == "active" and before.status in {"checkout_pending", "checkout_unknown"}:
            return "activated"
        if after.status == "active" and before.status in TERMINAL_STATUSES:
            return "activated"
        return "status_changed"
    if before.current_period_end != after.current_period_end:
        return "renewed" if after.status in PAID_STATUSES else "period_updated"
    return "status_changed"


def _normalize_reason(reason: str) -> str:
    cleaned = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")[:64]
    return cleaned if cleaned in REASONS else "provider_status_change"


async def record_subscription_transition(
    db: AsyncSession,
    subscription: Subscription,
    before: SubscriptionState | None,
    *,
    reason: str,
    source: str = "billing",
    effective_at: datetime | None = None,
    event_type: str | None = None,
) -> bool:
    """Insert one history row in the caller's transaction.

    Returns ``True`` only when a new row was written. A no-op state change and a
    duplicate natural key both return ``False`` without raising, so webhook
    retries cannot poison or roll back the billing transaction.
    """

    after = snapshot(subscription)
    if before is not None and before == after:
        return False
    if source not in SOURCES:
        raise ValueError("Unsupported subscription history source")
    resolved_type = event_type or classify_transition(before, after)
    if resolved_type not in EVENT_TYPES:
        raise ValueError("Unsupported subscription history event type")
    effective_at = _utc(effective_at)
    if subscription.id is None:
        raise ValueError("A subscription transition requires a persisted subscription")

    values = {
        "user_id": subscription.user_id,
        "subscription_id": subscription.id,
        "plan_id": after.plan_id,
        "previous_plan_id": before.plan_id if before else None,
        "status": after.status,
        "previous_status": before.status if before else None,
        "current_period_start": after.current_period_start,
        "current_period_end": after.current_period_end,
        "event_type": resolved_type,
        "reason": _normalize_reason(reason),
        "source": source,
        "effective_at": effective_at,
    }
    stmt = (
        pg_insert(SubscriptionHistory)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_subscription_history_transition")
    )
    result = await db.execute(stmt)
    return bool(result.rowcount)


def record_created_subscription(
    db: AsyncSession,
    subscription: Subscription,
    *,
    effective_at: datetime | None = None,
    reason: str = "checkout_created",
    source: str = "checkout",
) -> bool:
    """Record the checkout row without inventing a previous state."""

    return record_subscription_transition(
        db,
        subscription,
        None,
        reason=reason,
        source=source,
        effective_at=effective_at,
        event_type="subscription_created",
    )


# --------------------------------------------------------------------------- #
# Analytics                                                                    #
# --------------------------------------------------------------------------- #


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _month_label(value: datetime | date) -> str:
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


def _monthly_amount_minor(plan_id: str | None, quoted_amount: int | None) -> int:
    config = get_plan_config(plan_id) or {}
    is_annual = str(config.get("interval") or "").lower() in {"year", "annual"}
    if type(quoted_amount) is int and quoted_amount >= 0 and not is_annual:
        return quoted_amount
    if type(config.get("monthly_equivalent_price")) is int:
        return int(config["monthly_equivalent_price"])
    amount = int(config.get("price") or 0)
    return round(amount / 12) if is_annual else amount


def _plan_rank(plan_id: str | None) -> int:
    return max(0, _monthly_amount_minor(plan_id, None))


def movement_direction(
    previous_plan_id: str | None, plan_id: str | None
) -> str | None:
    if not previous_plan_id or not plan_id or previous_plan_id == plan_id:
        return None
    before, after = _plan_rank(previous_plan_id), _plan_rank(plan_id)
    if after > before:
        return "upgrade"
    if after < before:
        return "downgrade"
    return "lateral"


def _is_active(state: SubscriptionState | None, as_of: datetime) -> bool:
    if state is None or state.status not in PAID_STATUSES:
        return False
    return state.current_period_end is None or state.current_period_end >= as_of


def _state_from_row(row: SubscriptionHistory) -> SubscriptionState:
    return SubscriptionState(
        plan_id=str(row.plan_id),
        status=str(row.status),
        current_period_start=_as_utc(row.current_period_start),
        current_period_end=_as_utc(row.current_period_end),
    )


async def _latest_before(
    db: AsyncSession,
    user_ids: list[str],
    cutoff: datetime,
    *,
    inclusive: bool,
) -> dict[str, SubscriptionState]:
    if not user_ids:
        return {}
    condition = (
        SubscriptionHistory.effective_at <= cutoff
        if inclusive
        else SubscriptionHistory.effective_at < cutoff
    )
    stmt = (
        select(SubscriptionHistory)
        .where(
            SubscriptionHistory.user_id.in_(user_ids),
            SubscriptionHistory.subscription_id.is_not(None),
            condition,
        )
        .distinct(SubscriptionHistory.subscription_id)
        .order_by(
            SubscriptionHistory.subscription_id,
            SubscriptionHistory.effective_at.desc(),
            SubscriptionHistory.recorded_at.desc(),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {str(row.subscription_id): _state_from_row(row) for row in rows}


def _empty_bundle() -> dict[str, Any]:
    return {
        "active_at_start": 0,
        "active_at_end": 0,
        "plan_mix_total": 0,
        "upgrades": 0,
        "downgrades": 0,
        "lateral_moves": 0,
        "movement_total": 0,
        "cancellations": 0,
        "cancellation_scheduled": 0,
        "expired": 0,
        "payment_failed": 0,
        "refunded": 0,
        "churn_count": 0,
        "churn_rate": None,
        "new_paid": 0,
        "reactivations": 0,
        "mrr_minor": 0,
        "mrr": 0.0,
    }


def _bundle(
    *,
    subscription_ids: set[str],
    user_by_subscription: Mapping[str, str],
    start_states: Mapping[str, SubscriptionState],
    end_states: Mapping[str, SubscriptionState],
    window_events: Iterable[SubscriptionHistory],
    period_start: datetime,
    period_end: datetime,
    amounts: Mapping[str, int | None],
    currency: str,
) -> dict[str, Any]:
    result = _empty_bundle()
    if not subscription_ids:
        return result

    active_start = {
        sid
        for sid in subscription_ids
        if _is_active(start_states.get(sid), period_start)
    }
    active_end = {
        sid for sid in subscription_ids if _is_active(end_states.get(sid), period_end)
    }
    result["active_at_start"] = len(active_start)
    result["active_at_end"] = len(active_end)
    result["plan_mix_total"] = len(active_end)

    upgrade_counts: dict[tuple[str, str], int] = defaultdict(int)
    upgrade_users: dict[tuple[str, str], set[str]] = defaultdict(set)
    downgrade_counts: dict[tuple[str, str], int] = defaultdict(int)
    downgrade_users: dict[tuple[str, str], set[str]] = defaultdict(set)
    lateral_counts: dict[tuple[str, str], int] = defaultdict(int)
    lateral_users: dict[tuple[str, str], set[str]] = defaultdict(set)
    cancelled: set[str] = set()
    cancellation_scheduled: set[str] = set()
    expired: set[str] = set()
    payment_failed: set[str] = set()
    refunded: set[str] = set()
    reactivated: set[str] = set()

    for event in window_events:
        sid = str(event.subscription_id) if event.subscription_id else ""
        if not sid or sid not in subscription_ids:
            continue
        if event.event_type == "backfill":
            continue
        if event.previous_plan_id and event.previous_plan_id != event.plan_id:
            direction = movement_direction(event.previous_plan_id, event.plan_id)
            pair = (str(event.previous_plan_id), str(event.plan_id))
            user_id = str(event.user_id)
            if direction == "upgrade":
                upgrade_counts[pair] += 1
                upgrade_users[pair].add(user_id)
            elif direction == "downgrade":
                downgrade_counts[pair] += 1
                downgrade_users[pair].add(user_id)
            elif direction == "lateral":
                lateral_counts[pair] += 1
                lateral_users[pair].add(user_id)
        if event.event_type == "cancelled":
            cancelled.add(sid)
        elif event.event_type == "cancellation_scheduled":
            cancellation_scheduled.add(sid)
        elif event.event_type == "expired":
            expired.add(sid)
        elif event.event_type == "payment_failed":
            payment_failed.add(sid)
        elif event.event_type == "refunded":
            refunded.add(sid)
        elif event.event_type == "activated" and event.previous_status in TERMINAL_STATUSES:
            reactivated.add(sid)

    result["upgrades"] = sum(upgrade_counts.values())
    result["downgrades"] = sum(downgrade_counts.values())
    result["lateral_moves"] = sum(lateral_counts.values())
    result["movement_total"] = (
        result["upgrades"] + result["downgrades"] + result["lateral_moves"]
    )
    result["cancellations"] = len(cancelled)
    result["cancellation_scheduled"] = len(cancellation_scheduled)
    result["expired"] = len(expired)
    result["payment_failed"] = len(payment_failed)
    result["refunded"] = len(refunded)
    result["reactivations"] = len(reactivated)

    churn_ids = {
        sid
        for sid in active_start
        if end_states.get(sid) is not None
        and end_states[sid].status in TERMINAL_STATUSES
    }
    result["churn_count"] = len(churn_ids)
    result["churn_rate"] = (
        _pct(len(churn_ids), len(active_start))
        if len(active_start) >= MIN_SEGMENT_SIZE
        else None
    )
    result["new_paid"] = len({sid for sid in active_end if sid not in active_start})

    result["_active_start"] = active_start
    result["_active_end"] = active_end
    result["_end_states"] = dict(end_states)
    result["_upgrade_counts"] = upgrade_counts
    result["_upgrade_users"] = upgrade_users
    result["_downgrade_counts"] = downgrade_counts
    result["_downgrade_users"] = downgrade_users
    result["_lateral_counts"] = lateral_counts
    result["_lateral_users"] = lateral_users
    result["_churn_ids"] = churn_ids
    result["_cancelled"] = cancelled
    result["_cancellation_scheduled"] = cancellation_scheduled
    result["_expired"] = expired
    result["_payment_failed"] = payment_failed
    result["_refunded"] = refunded
    result["_user_by_subscription"] = dict(user_by_subscription)
    result["_amounts"] = dict(amounts)
    result["_currency"] = currency
    return result


def _plan_mix(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    active_end: set[str] = bundle["_active_end"]
    users_by_plan: dict[str, set[str]] = defaultdict(set)
    for sid in active_end:
        state = bundle["_end_states"].get(sid) if "_end_states" in bundle else None
        plan_id = state.plan_id if state else "unknown"
        users_by_plan[plan_id].add(bundle["_user_by_subscription"].get(sid, ""))
        bucket = grouped.setdefault(
            plan_id,
            {"plan_id": plan_id, "subscriptions": 0, "users": 0, "mrr_minor": 0},
        )
        bucket["subscriptions"] += 1
        bucket["mrr_minor"] += _monthly_amount_minor(
            plan_id, bundle["_amounts"].get(sid)
        )
    total = sum(bucket["subscriptions"] for bucket in grouped.values())
    rows: list[dict[str, Any]] = []
    for plan_id, bucket in grouped.items():
        bucket["users"] = len(users_by_plan[plan_id] - {""})
        bucket["share_pct"] = _pct(bucket["subscriptions"], total)
        bucket["mrr"] = round(bucket["mrr_minor"] / 100, 2)
        bucket["currency"] = bundle["_currency"]
        rows.append(bucket)
    rows.sort(key=lambda row: (-row["subscriptions"], row["plan_id"]))
    return rows


def _movement_rows(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for direction, counts_key, users_key in (
        ("upgrade", "_upgrade_counts", "_upgrade_users"),
        ("downgrade", "_downgrade_counts", "_downgrade_users"),
        ("lateral", "_lateral_counts", "_lateral_users"),
    ):
        for pair, count in bundle[counts_key].items():
            from_plan, to_plan = pair
            rows.append(
                {
                    "direction": direction,
                    "from_plan": from_plan,
                    "to_plan": to_plan,
                    "count": count,
                    "users": len(bundle[users_key][pair]),
                }
            )
    order = {"upgrade": 0, "downgrade": 1, "lateral": 2}
    rows.sort(key=lambda row: (order[row["direction"]], -row["count"], row["from_plan"], row["to_plan"]))
    return rows


def _churn_rows(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"reason": "cancelled", "count": len(bundle["_cancelled"]), "users": len(bundle["_cancelled"])},
        {
            "reason": "cancellation_scheduled",
            "count": len(bundle["_cancellation_scheduled"]),
            "users": len(bundle["_cancellation_scheduled"]),
        },
        {"reason": "expired", "count": len(bundle["_expired"]), "users": len(bundle["_expired"])},
        {
            "reason": "payment_failed",
            "count": len(bundle["_payment_failed"]),
            "users": len(bundle["_payment_failed"]),
        },
        {"reason": "refunded", "count": len(bundle["_refunded"]), "users": len(bundle["_refunded"])},
    ]


def _public_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in bundle.items()
        if not key.startswith("_")
    }


def _checks(
    *,
    bundle: Mapping[str, Any],
    total_history_rows: int,
    backfill_rows: int,
    movement_rows_total: int,
    current_active_subscriptions: int,
) -> dict[str, Any]:
    checks = [
        {
            "key": "plan_mix_total",
            "label": "Plan mix equals active subscriptions at period end",
            "ok": bundle["plan_mix_total"] == bundle["active_at_end"],
            "detail": f"{bundle['plan_mix_total']} plan-mix rows / {bundle['active_at_end']} active",
        },
        {
            "key": "movement_total",
            "label": "Upgrade, downgrade and lateral counts equal movement rows",
            "ok": bundle["movement_total"] == movement_rows_total,
            "detail": f"{bundle['movement_total']} transitions / {movement_rows_total} grouped rows",
        },
        {
            "key": "churn_denominator",
            "label": "Churn count never exceeds active subscriptions at period start",
            "ok": bundle["churn_count"] <= bundle["active_at_start"],
            "detail": f"{bundle['churn_count']} churned / {bundle['active_at_start']} active at start",
        },
        {
            "key": "history_source",
            "label": "Movement and churn use subscription history, not logs",
            "ok": True,
            "detail": f"{total_history_rows} transitions in window; {backfill_rows} backfill snapshots excluded",
        },
    ]
    return {
        "history_rows": total_history_rows,
        "backfill_rows": backfill_rows,
        "movement_total_reconciles": bundle["movement_total"] == movement_rows_total,
        "churn_reconciles": bundle["churn_count"] <= bundle["active_at_start"],
        "plan_mix_total_matches_active_at_end": bundle["plan_mix_total"]
        == bundle["active_at_end"],
        "current_active_subscriptions": current_active_subscriptions,
        "plan_mix_matches_current": current_active_subscriptions
        == bundle["active_at_end"],
        "checks": checks,
    }


async def subscription_analytics(
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
    """Build aggregate plan-mix, movement and churn metrics by signup cohort."""

    days = max(1, min(int(days), MAX_PERIOD_DAYS))
    now = _utc(now)
    period_end = _as_utc(end) or now
    period_start = _as_utc(start) or (period_end - timedelta(days=days))
    if period_start > period_end:
        raise ValueError("The period start must not be after the end")
    plan = (plan or "").strip().lower() or None
    currency = str(settings.BILLING_CURRENCY or "INR").upper()
    cohort_bounds = _signup_bounds(signup_month, signup_from, signup_to)

    user_stmt = select(User.id, User.created_at)
    if cohort_bounds is not None:
        user_stmt = user_stmt.where(
            User.created_at >= cohort_bounds[0],
            User.created_at < cohort_bounds[1],
        )
    if plan:
        user_stmt = user_stmt.where(User.subscription_plan == plan)
    user_rows = (await db.execute(user_stmt)).all()
    user_ids = [str(row[0]) for row in user_rows]
    signup_by_user = {
        str(row[0]): _as_utc(row[1]) for row in user_rows if row[1] is not None
    }

    base: dict[str, Any] = {
        "period_days": days,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "currency": currency,
        "minor_unit": "paise" if currency == "INR" else "minor_units",
        "minimum_cohort_size": MIN_SEGMENT_SIZE,
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
        "summary": _empty_bundle(),
        "plan_mix": [],
        "movements": [],
        "churn": [],
        "cohorts": [],
        "suppressed": False,
        "suppressed_cohorts": 0,
        "generated_at": now.isoformat(),
        "reconciliation": {
            "history_rows": 0,
            "backfill_rows": 0,
            "movement_total_reconciles": True,
            "churn_reconciles": True,
            "plan_mix_total_matches_active_at_end": True,
            "current_active_subscriptions": 0,
            "plan_mix_matches_current": True,
            "checks": [],
        },
    }

    available_month = func.date_trunc("month", User.created_at).label("month")
    available_stmt = select(available_month, func.count(User.id)).where(
        User.created_at >= now - timedelta(days=MAX_PERIOD_DAYS)
    )
    if plan:
        available_stmt = available_stmt.where(User.subscription_plan == plan)
    available_rows = (
        await db.execute(
            available_stmt.group_by(available_month).order_by(available_month)
        )
    ).all()
    base["available_signup_months"] = [
        {"month": _month_label(month), "users": int(count)}
        for month, count in available_rows
        if month is not None and int(count) >= MIN_SEGMENT_SIZE
    ]

    if not user_ids:
        return base

    start_states = await _latest_before(db, user_ids, period_start, inclusive=False)
    end_states = await _latest_before(db, user_ids, period_end, inclusive=True)

    window_stmt = select(SubscriptionHistory).where(
        SubscriptionHistory.user_id.in_(user_ids),
        SubscriptionHistory.subscription_id.is_not(None),
        SubscriptionHistory.effective_at >= period_start,
        SubscriptionHistory.effective_at <= period_end,
    )
    window_events = list((await db.execute(window_stmt)).scalars().all())

    subscription_ids: set[str] = set(start_states) | set(end_states)
    for event in window_events:
        if event.subscription_id:
            subscription_ids.add(str(event.subscription_id))
    # A subscription is in the audience only when its user is in the filtered
    # signup cohort. History user_id already enforces that.
    subscription_owner = {
        str(event.subscription_id): str(event.user_id)
        for event in window_events
        if event.subscription_id
    }

    # Fill owners for subscriptions that only appear in start/end snapshots.
    if subscription_ids:
        owner_stmt = select(Subscription.id, Subscription.user_id).where(
            Subscription.id.in_(list(subscription_ids))
        )
        for sid, owner in (await db.execute(owner_stmt)).all():
            subscription_owner.setdefault(str(sid), str(owner))

    amount_rows = (
        await db.execute(
            select(Subscription.id, Subscription.quoted_amount).where(
                Subscription.id.in_(list(subscription_ids))
            )
        )
    ).all() if subscription_ids else []
    amounts = {str(sid): amount for sid, amount in amount_rows}

    subscriber_user_ids = {
        owner for owner in subscription_owner.values() if owner in signup_by_user
    }
    if len(subscriber_user_ids) < MIN_SEGMENT_SIZE:
        base["suppressed"] = True
        base["suppressed_cohorts"] = 1
        return base

    aggregate = _bundle(
        subscription_ids=subscription_ids,
        user_by_subscription=subscription_owner,
        start_states=start_states,
        end_states=end_states,
        window_events=window_events,
        period_start=period_start,
        period_end=period_end,
        amounts=amounts,
        currency=currency,
    )
    plan_mix_rows = _plan_mix(aggregate)
    movement_rows = _movement_rows(aggregate)
    churn_rows = _churn_rows(aggregate)

    current_rows = (
        await db.execute(
            select(Subscription.id, Subscription.plan_id, Subscription.status, Subscription.current_period_end)
            .where(
                Subscription.user_id.in_(user_ids),
                Subscription.status.in_(PAID_STATUSES),
            )
        )
    ).all()
    current_active_subscriptions = sum(
        1
        for _sid, _plan_id, status, period_end_value in current_rows
        if status in PAID_STATUSES
        and (period_end_value is None or _as_utc(period_end_value) >= now)
    )

    backfill_rows = sum(1 for event in window_events if event.event_type == "backfill")
    summary = _public_bundle(aggregate)
    summary["mrr_minor"] = sum(row["mrr_minor"] for row in plan_mix_rows)
    summary["mrr"] = round(summary["mrr_minor"] / 100, 2)
    base["summary"] = summary
    base["plan_mix"] = plan_mix_rows
    base["movements"] = movement_rows
    base["churn"] = churn_rows
    base["reconciliation"] = _checks(
        bundle=aggregate,
        total_history_rows=len(window_events),
        backfill_rows=backfill_rows,
        movement_rows_total=sum(row["count"] for row in movement_rows),
        current_active_subscriptions=current_active_subscriptions,
    )

    # Cohort rows are computed from the same ledger state so their totals
    # reconcile with the summary. A cohort with fewer than five subscribers is
    # omitted entirely, never emitted with masked counts.
    cohort_subscriptions: dict[str, set[str]] = defaultdict(set)
    cohort_users: dict[str, set[str]] = defaultdict(set)
    for sid, owner in subscription_owner.items():
        created_at = signup_by_user.get(owner)
        if created_at is None:
            continue
        label = _month_label(created_at)
        cohort_subscriptions[label].add(sid)
        cohort_users[label].add(owner)
    for label in sorted(cohort_subscriptions):
        if len(cohort_users[label]) < MIN_SEGMENT_SIZE:
            base["suppressed_cohorts"] += 1
            continue
        cohort_bundle = _bundle(
            subscription_ids=cohort_subscriptions[label],
            user_by_subscription=subscription_owner,
            start_states=start_states,
            end_states=end_states,
            window_events=[
                event
                for event in window_events
                if str(event.user_id) in cohort_users[label]
            ],
            period_start=period_start,
            period_end=period_end,
            amounts=amounts,
            currency=currency,
        )
        cohort_plan_mix = _plan_mix(cohort_bundle)
        cohort_summary = _public_bundle(cohort_bundle)
        cohort_summary["mrr_minor"] = sum(
            row["mrr_minor"] for row in cohort_plan_mix
        )
        cohort_summary["mrr"] = round(cohort_summary["mrr_minor"] / 100, 2)
        base["cohorts"].append(
            {
                "cohort": label,
                "users": len(cohort_users[label]),
                **cohort_summary,
                "plan_mix": [
                    {
                        "plan_id": row["plan_id"],
                        "subscriptions": row["subscriptions"],
                        "currency": row["currency"],
                    }
                    for row in cohort_plan_mix
                ],
            }
        )

    return base


class SubscriptionHistoryService:
    """Shared facade for billing writes and the admin analytics route."""

    record_transition = staticmethod(record_subscription_transition)
    record_created = staticmethod(record_created_subscription)
    classify_transition = staticmethod(classify_transition)
    snapshot = staticmethod(snapshot)
    subscription_analytics = staticmethod(subscription_analytics)


subscription_history_service = SubscriptionHistoryService()

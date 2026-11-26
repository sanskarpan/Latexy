"""Admin-only coupon and student-verification performance analytics.

The report reads the existing ``coupon_codes``, ``coupon_redemptions``,
``subscriptions`` and ``payments`` tables plus first-party lifecycle rows in
``usage_analytics``.  It does not need a schema migration.

Every response is aggregate-only.  Student emails, verification tokens, account
ids, IP addresses, user agents, documents and event metadata never leave this
module.  Coupon/student segments below five distinct users are suppressed, and
review flags are advisory only: ``automated_action`` is always ``none``.
"""

from __future__ import annotations

import inspect
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import resolve_plan_family
from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

CouponCode = models.CouponCode
CouponRedemption = models.CouponRedemption
Payment = models.Payment
Subscription = models.Subscription
UsageAnalytics = models.UsageAnalytics

MIN_SEGMENT_SIZE = 5
MAX_RANGE_DAYS = 365
MAX_EVENT_ROWS = 50_000
MAX_COUPON_ROWS = 100
MAX_REVIEW_FLAGS = 50
MAX_RESOURCE_IDS_PER_QUERY = 500

EVENT_RESOURCE_TYPE = "revenue_lifecycle"
COUPON_RESERVED = "coupon_reserved"
COUPON_REDEEMED = "coupon_redeemed"
COUPON_RELEASED = "coupon_released"
STUDENT_REQUESTED = "student_verification_requested"
STUDENT_VERIFIED = "student_verification_verified"
STUDENT_PAID = "student_verification_paid"
STUDENT_FAILED = "student_verification_failed"

COUPON_EVENTS = (COUPON_RESERVED, COUPON_REDEEMED, COUPON_RELEASED)
STUDENT_EVENTS = (STUDENT_REQUESTED, STUDENT_VERIFIED, STUDENT_PAID, STUDENT_FAILED)

PAID_SUBSCRIPTION_STATUSES = frozenset({"active", "cancel_scheduled", "past_due", "on_hold", "paused"})
SETTLED_PAYMENT_STATUSES = frozenset({"paid", "captured", "partially_refunded", "refunded", "succeeded"})

# Only server-selected failure reasons are persisted or returned.
SAFE_FAILURE_REASONS = frozenset(
    {
        "expired_or_invalid",
        "in_progress",
        "admission_denied",
        "checkout_failed",
        "verification_failed",
        "already_used",
        "unknown",
    }
)

FAILURE_LABELS = {
    "expired_or_invalid": "Expired or invalid token",
    "in_progress": "Verification already in progress",
    "admission_denied": "Purchase admission denied",
    "checkout_failed": "Checkout creation failed",
    "verification_failed": "Verification failed",
    "already_used": "Token already used",
    "unknown": "Other failure",
}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _resolve_period(
    *,
    days: int,
    start: datetime | None,
    end: datetime | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, int]:
    if type(days) is not int or days < 1 or days > MAX_RANGE_DAYS:
        raise ValueError(f"The period must be between 1 and {MAX_RANGE_DAYS} days")
    generated_at = _as_utc(now) or datetime.now(timezone.utc)
    period_end = _as_utc(end) or generated_at
    period_start = _as_utc(start) or (period_end - timedelta(days=days))
    if period_start > period_end:
        raise ValueError("The period start must not be after the end")
    effective_days = max(1, int((period_end - period_start).total_seconds() // 86_400))
    return period_start, period_end, effective_days


def _chunks(values: Sequence[str], size: int = MAX_RESOURCE_IDS_PER_QUERY) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _coupon_matches_plan(coupon: CouponCode | None, plan: str | None) -> bool:
    if plan is None:
        return True
    applicable = {str(value).strip().lower() for value in (getattr(coupon, "applicable_plans", None) or []) if value}
    if not applicable:
        return True
    return plan in applicable or resolve_plan_family(plan) in applicable


def _event_plan(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("plan_id")
    return str(value).strip().lower() if value else None


def _event_coupon_id(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("coupon_id")
    return str(value) if value else None


def _safe_reason(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return "unknown"
    reason = str(metadata.get("reason") or "").strip().lower()
    return reason if reason in SAFE_FAILURE_REASONS else "unknown"


async def record_event(
    db: AsyncSession,
    *,
    action: str,
    user_id: str | None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
    allow_anonymous: bool = False,
) -> None:
    """Persist one first-party lifecycle event without schema changes.

    Analytics must never block the billing outcome, so callers on success paths
    add the row to their existing transaction.  Failure paths pass ``commit`` so
    the event survives an otherwise read-only early return.  Expired/invalid
    verification links have no resolvable account, so those aggregate-only
    failure events may be anonymous.
    """

    if not user_id and not allow_anonymous:
        return
    payload = {
        key: value
        for key, value in (metadata or {}).items()
        if value is not None and key in {"coupon_id", "plan_id", "reason", "surface"}
    }
    try:
        added = db.add(
            UsageAnalytics(
                user_id=str(user_id) if user_id else None,
                action=action,
                resource_type=EVENT_RESOURCE_TYPE,
                event_metadata=payload,
            )
        )
        if inspect.isawaitable(added):
            await added
        if commit:
            await db.commit()
    except Exception as exc:
        # Analytics is never allowed to change a billing outcome.
        logger.warning(
            "Revenue lifecycle event persistence failed (%s)",
            type(exc).__name__,
        )
        if commit:
            try:
                await db.rollback()
            except Exception:
                pass


async def record_coupon_reserved(
    db: AsyncSession, *, user_id: str | None, coupon_id: str | None, plan_id: str | None
) -> None:
    await record_event(
        db,
        action=COUPON_RESERVED,
        user_id=user_id,
        metadata={"coupon_id": coupon_id, "plan_id": plan_id},
    )


async def record_coupon_redemption_status(
    db: AsyncSession, *, user_id: str | None, coupon_id: str | None, status: str
) -> None:
    action = COUPON_REDEEMED if status == "redeemed" else COUPON_RELEASED
    await record_event(
        db,
        action=action,
        user_id=user_id,
        metadata={"coupon_id": coupon_id},
    )


async def record_student_requested(db: AsyncSession, *, user_id: str | None, plan_id: str = "student") -> None:
    await record_event(
        db,
        action=STUDENT_REQUESTED,
        user_id=user_id,
        metadata={"plan_id": plan_id},
        commit=True,
    )


async def record_student_verified(db: AsyncSession, *, user_id: str | None, plan_id: str = "student") -> None:
    await record_event(
        db,
        action=STUDENT_VERIFIED,
        user_id=user_id,
        metadata={"plan_id": plan_id},
        commit=True,
    )


async def record_student_paid(db: AsyncSession, *, user_id: str | None, plan_id: str = "student") -> None:
    await record_event(
        db,
        action=STUDENT_PAID,
        user_id=user_id,
        metadata={"plan_id": plan_id},
        commit=True,
    )


async def record_student_failure(db: AsyncSession, *, user_id: str | None, reason: str) -> None:
    await record_event(
        db,
        action=STUDENT_FAILED,
        user_id=user_id,
        metadata={
            "plan_id": "student",
            "reason": reason if reason in SAFE_FAILURE_REASONS else "unknown",
        },
        commit=True,
        allow_anonymous=True,
    )


def _empty_coupon_bucket() -> dict[str, Any]:
    return {
        "reservations": 0,
        "redemptions": 0,
        "released": 0,
        "expired_redemptions": 0,
        "paid_redemptions": 0,
        "unlinked_redemptions": 0,
        "users": set(),
        "reserve_events": 0,
        "redeem_events": 0,
        "release_events": 0,
        "event_users": set(),
        "repeated_reservation_events": 0,
    }


def _student_empty() -> dict[str, Any]:
    return {
        "applicable": True,
        "requested_users": 0,
        "verified_users": 0,
        "paid_users": 0,
        "steps": [],
        "conversion": {
            "requested_to_verified": 0.0,
            "verified_to_paid": 0.0,
            "requested_to_paid": 0.0,
        },
        "failures": {
            "total_events": 0,
            "distinct_users": 0,
            "by_reason": [],
            "repeated_failure_users": None,
            "repeated_failure_users_suppressed": False,
        },
        "by_plan": [],
        "suppressed_segments": 0,
        "review_flags": [],
        "reconciliation": {
            "requested_at_least_verified": True,
            "verified_at_least_paid": True,
            "paid_without_verification": 0,
            "checks": [],
        },
    }


async def _coupon_section(
    db: AsyncSession,
    *,
    period_start: datetime,
    period_end: datetime,
    plan: str | None,
) -> dict[str, Any]:
    coupon_rows = list((await db.execute(select(CouponCode))).scalars().all())
    coupons = {str(coupon.id): coupon for coupon in coupon_rows}
    now = period_end

    redemption_rows = (
        await db.execute(
            select(
                CouponRedemption.id,
                CouponRedemption.coupon_id,
                CouponRedemption.user_id,
                CouponRedemption.subscription_id,
                CouponRedemption.status,
                CouponRedemption.redeemed_at,
                Subscription.created_at.label("subscription_created_at"),
                Subscription.status.label("subscription_status"),
                Subscription.plan_id.label("subscription_plan_id"),
            )
            .outerjoin(Subscription, CouponRedemption.subscription_id == Subscription.id)
            .where(
                or_(
                    and_(
                        CouponRedemption.redeemed_at >= period_start,
                        CouponRedemption.redeemed_at < period_end,
                    ),
                    and_(
                        CouponRedemption.redeemed_at.is_(None),
                        Subscription.created_at >= period_start,
                        Subscription.created_at < period_end,
                    ),
                )
            )
        )
    ).all()

    buckets: dict[str, dict[str, Any]] = defaultdict(_empty_coupon_bucket)
    sub_ids: set[str] = set()
    included_rows: list[Any] = []
    for row in redemption_rows:
        coupon_id = str(row.coupon_id) if row.coupon_id else None
        coupon = coupons.get(coupon_id) if coupon_id else None
        if plan is not None and not _coupon_matches_plan(coupon, plan):
            continue
        if plan is not None and row.subscription_plan_id and resolve_plan_family(str(row.subscription_plan_id)) != plan:
            continue
        included_rows.append(row)
        bucket = buckets[coupon_id or "unattributed"]
        if row.user_id:
            bucket["users"].add(str(row.user_id))
        status = str(row.status or "").lower()
        if status == "reserved":
            bucket["reservations"] += 1
        elif status == "redeemed":
            bucket["redemptions"] += 1
            if not row.subscription_id:
                bucket["unlinked_redemptions"] += 1
        elif status == "released":
            bucket["released"] += 1
        if row.subscription_id:
            sub_ids.add(str(row.subscription_id))
        expiry = _as_utc(getattr(coupon, "expires_at", None))
        redeemed_at = _as_utc(row.redeemed_at)
        if status == "redeemed" and expiry and redeemed_at and redeemed_at > expiry:
            bucket["expired_redemptions"] += 1

    paid_subscription_ids: set[str] = set()
    for chunk in _chunks(sorted(sub_ids)):
        paid_rows = (
            await db.execute(
                select(Payment.subscription_id).where(
                    Payment.subscription_id.in_(chunk),
                    Payment.status.in_(tuple(SETTLED_PAYMENT_STATUSES)),
                )
            )
        ).all()
        paid_subscription_ids.update(str(row[0]) for row in paid_rows if row[0])
    for row in included_rows:
        if str(row.status or "").lower() == "redeemed" and row.subscription_id:
            if (
                str(row.subscription_status or "").lower() in PAID_SUBSCRIPTION_STATUSES
                or str(row.subscription_id) in paid_subscription_ids
            ):
                coupon_id = str(row.coupon_id) if row.coupon_id else "unattributed"
                if coupon_id in buckets:
                    buckets[coupon_id]["paid_redemptions"] += 1

    event_rows = (
        await db.execute(
            select(
                UsageAnalytics.user_id,
                UsageAnalytics.action,
                UsageAnalytics.event_metadata,
                UsageAnalytics.created_at,
            )
            .where(
                UsageAnalytics.action.in_(COUPON_EVENTS),
                UsageAnalytics.created_at >= period_start,
                UsageAnalytics.created_at < period_end,
            )
            .order_by(UsageAnalytics.created_at.asc())
            .limit(MAX_EVENT_ROWS)
        )
    ).all()

    reserve_by_coupon_user: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    event_totals = {"reserved": 0, "redeemed": 0, "released": 0, "users": set()}
    for row in event_rows:
        coupon_id = _event_coupon_id(row.event_metadata)
        coupon = coupons.get(coupon_id) if coupon_id else None
        if plan is not None and coupon is not None and not _coupon_matches_plan(coupon, plan):
            continue
        event_plan = _event_plan(row.event_metadata)
        if plan is not None and event_plan is not None and resolve_plan_family(event_plan) != plan:
            continue
        key = coupon_id or "unattributed"
        bucket = buckets[key]
        if row.user_id:
            bucket["event_users"].add(str(row.user_id))
            event_totals["users"].add(str(row.user_id))
        if row.action == COUPON_RESERVED:
            bucket["reserve_events"] += 1
            event_totals["reserved"] += 1
            if row.user_id and coupon_id:
                reserve_by_coupon_user[coupon_id][str(row.user_id)] += 1
        elif row.action == COUPON_REDEEMED:
            bucket["redeem_events"] += 1
            event_totals["redeemed"] += 1
        elif row.action == COUPON_RELEASED:
            bucket["release_events"] += 1
            event_totals["released"] += 1

    repeated_by_coupon: dict[str, tuple[int, int]] = {}
    for coupon_id, users in reserve_by_coupon_user.items():
        repeated_users = sum(1 for count in users.values() if count > 1)
        repeated_events = sum(count - 1 for count in users.values() if count > 1)
        repeated_by_coupon[coupon_id] = (repeated_users, repeated_events)
        buckets[coupon_id]["repeated_reservation_events"] = repeated_events

    active_coupons = 0
    expired_coupons = 0
    exhausted_coupons = 0
    used_count_total = 0
    capacity_total = 0
    for coupon in coupon_rows:
        used_count = max(0, int(coupon.used_count or 0))
        used_count_total += used_count
        expiry = _as_utc(coupon.expires_at)
        expired = expiry is not None and expiry <= now
        exhausted = coupon.max_uses is not None and used_count >= int(coupon.max_uses)
        if expired:
            expired_coupons += 1
        elif exhausted:
            exhausted_coupons += 1
        else:
            active_coupons += 1
        if coupon.max_uses is not None:
            capacity_total += max(0, int(coupon.max_uses))

    totals = {
        "coupons": len(coupon_rows),
        "active_coupons": active_coupons,
        "expired_coupons": expired_coupons,
        "exhausted_coupons": exhausted_coupons,
        "reservations": sum(bucket["reservations"] for bucket in buckets.values()),
        "redemptions": sum(bucket["redemptions"] for bucket in buckets.values()),
        "released": sum(bucket["released"] for bucket in buckets.values()),
        "paid_redemptions": sum(bucket["paid_redemptions"] for bucket in buckets.values()),
        "unlinked_redemptions": sum(bucket["unlinked_redemptions"] for bucket in buckets.values()),
        "expired_redemptions": sum(bucket["expired_redemptions"] for bucket in buckets.values()),
        "repeated_reservation_events": sum(repeated for _users, repeated in repeated_by_coupon.values()),
        "repeated_reservation_users": sum(users for users, _events in repeated_by_coupon.values()),
        "used_count_total": used_count_total,
        "capacity_total": capacity_total,
    }
    redemption_denominator = totals["reservations"] + totals["redemptions"] + totals["released"]
    totals["redemption_rate_pct"] = _pct(totals["redemptions"], redemption_denominator)
    totals["conversion_pct"] = _pct(totals["paid_redemptions"], totals["redemptions"])
    totals["capacity_used_pct"] = _pct(used_count_total, capacity_total)
    totals["distinct_users"] = (
        len(set().union(*(bucket["users"] | bucket["event_users"] for bucket in buckets.values()))) if buckets else 0
    )

    by_coupon: list[dict[str, Any]] = []
    suppressed_coupons = 0
    for coupon_id, bucket in buckets.items():
        distinct_users = len(bucket["users"] | bucket["event_users"])
        has_activity = any(
            bucket[key]
            for key in (
                "reservations",
                "redemptions",
                "released",
                "reserve_events",
                "redeem_events",
                "release_events",
            )
        )
        if not has_activity:
            continue
        if distinct_users < MIN_SEGMENT_SIZE:
            suppressed_coupons += 1
            continue
        coupon = coupons.get(coupon_id)
        redemption_denominator = bucket["reservations"] + bucket["redemptions"] + bucket["released"]
        repeated_users, repeated_events = repeated_by_coupon.get(coupon_id, (0, 0))
        by_coupon.append(
            {
                "coupon_id": coupon_id,
                "code": coupon.code if coupon is not None else None,
                "discount_percent": int(coupon.discount_percent) if coupon is not None else None,
                "applicable_plans": list(coupon.applicable_plans or []) if coupon is not None else [],
                "distinct_users": distinct_users,
                "reservations": bucket["reservations"],
                "redemptions": bucket["redemptions"],
                "released": bucket["released"],
                "paid_redemptions": bucket["paid_redemptions"],
                "expired_redemptions": bucket["expired_redemptions"],
                "repeated_reservation_users": repeated_users,
                "repeated_reservation_events": repeated_events,
                "redemption_rate_pct": _pct(bucket["redemptions"], redemption_denominator),
                "conversion_pct": _pct(bucket["paid_redemptions"], bucket["redemptions"]),
            }
        )
    by_coupon.sort(key=lambda item: (-item["redemptions"], -item["distinct_users"], str(item["code"] or "")))

    all_status_rows = (
        await db.execute(
            select(CouponRedemption.status, func.count(CouponRedemption.id)).group_by(CouponRedemption.status)
        )
    ).all()
    all_status_counts = {str(status or ""): int(count) for status, count in all_status_rows}
    active_redemptions = all_status_counts.get("reserved", 0) + all_status_counts.get("redeemed", 0)
    missing_subscription_count = int(
        await db.scalar(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.status == "redeemed",
                CouponRedemption.subscription_id.is_(None),
            )
        )
        or 0
    )
    used_count_difference = used_count_total - active_redemptions

    checks = [
        {
            "key": "redemptions_linked_to_subscriptions",
            "label": "Every redeemed coupon is linked to a subscription",
            "ok": missing_subscription_count == 0,
            "expected": 0,
            "actual": missing_subscription_count,
            "difference": missing_subscription_count,
        },
        {
            "key": "used_count_matches_active_redemptions",
            "label": "Coupon used_count equals reserved plus redeemed redemptions",
            "ok": used_count_difference == 0,
            "expected": active_redemptions,
            "actual": used_count_total,
            "difference": used_count_difference,
        },
    ]
    reconciliation = {
        "balanced": all(check["ok"] for check in checks),
        "redemption_rows": sum(all_status_counts.values()),
        "reserved_rows": all_status_counts.get("reserved", 0),
        "redeemed_rows": all_status_counts.get("redeemed", 0),
        "released_rows": all_status_counts.get("released", 0),
        "active_redemptions": active_redemptions,
        "used_count_total": used_count_total,
        "used_count_difference": used_count_difference,
        "missing_subscription_count": missing_subscription_count,
        "window_unlinked_redemptions": totals["unlinked_redemptions"],
        "checks": checks,
    }

    review_flags: list[dict[str, Any]] = []
    suppressed_review_flags = 0

    def add_flag(
        *,
        flag_id: str,
        kind: str,
        severity: str,
        title: str,
        detail: str,
        affected_count: int,
        coupon_id: str | None = None,
        coupon_code: str | None = None,
    ) -> None:
        review_flags.append(
            {
                "flag_id": flag_id,
                "kind": kind,
                "severity": severity,
                "title": title,
                "detail": detail,
                "coupon_id": coupon_id,
                "coupon_code": coupon_code,
                "affected_count": affected_count,
                "requires_human_review": True,
                "automated_action": "none",
            }
        )

    if totals["unlinked_redemptions"] > 0:
        add_flag(
            flag_id="coupon:unlinked-redemptions",
            kind="unlinked_redemption",
            severity="high",
            title="Coupon redemptions without a subscription",
            detail=(
                "Redeemed coupon rows in this period have no linked subscription. "
                "Review the billing ledger before treating the redemption as converted."
            ),
            affected_count=totals["unlinked_redemptions"],
        )
    if not reconciliation["balanced"]:
        add_flag(
            flag_id="coupon:reconciliation",
            kind="redemption_reconciliation",
            severity="high",
            title="Coupon redemption ledger does not reconcile",
            detail=(
                "Coupon used_count or subscription links disagree with the redemption ledger. "
                "Review the affected coupon rows; no account action is automated."
            ),
            affected_count=max(
                1,
                abs(reconciliation["used_count_difference"]) + reconciliation["missing_subscription_count"],
            ),
        )

    for row in by_coupon:
        coupon_id = str(row["coupon_id"])
        coupon_code = row["code"]
        repeated_users = int(row["repeated_reservation_users"] or 0)
        if row["expired_redemptions"] > 0:
            add_flag(
                flag_id=f"coupon:{coupon_id}:expired-redemption",
                kind="expired_coupon_redemption",
                severity="high",
                title="Coupon redeemed after expiry",
                detail=("Redemptions were recorded after this coupon's expiry. This is an advisory review flag only."),
                affected_count=int(row["expired_redemptions"]),
                coupon_id=coupon_id,
                coupon_code=coupon_code,
            )
        if repeated_users >= MIN_SEGMENT_SIZE:
            add_flag(
                flag_id=f"coupon:{coupon_id}:repeated-reservations",
                kind="suspicious_reuse",
                severity="medium",
                title="Repeated coupon reservations",
                detail=(
                    "Multiple accounts repeatedly reserved this coupon after prior releases. "
                    "Review the aggregate pattern; no user is punished automatically."
                ),
                affected_count=repeated_users,
                coupon_id=coupon_id,
                coupon_code=coupon_code,
            )
        elif repeated_users > 0:
            suppressed_review_flags += 1

    for coupon_id, bucket in buckets.items():
        distinct_users = len(bucket["users"] | bucket["event_users"])
        repeated_users = repeated_by_coupon.get(coupon_id, (0, 0))[0]
        if distinct_users < MIN_SEGMENT_SIZE and (bucket["expired_redemptions"] > 0 or repeated_users > 0):
            suppressed_review_flags += 1

    # Keep small segments private without hiding the aggregate review signal.
    if totals["expired_redemptions"] > 0 and not any(
        flag["kind"] == "expired_coupon_redemption" for flag in review_flags
    ):
        add_flag(
            flag_id="coupon:expired-redemptions",
            kind="expired_coupon_redemption",
            severity="high",
            title="Expired coupon redemptions in this period",
            detail=(
                "One or more small coupon segments redeemed after expiry. "
                "The per-coupon detail is suppressed; review the aggregate signal only."
            ),
            affected_count=totals["expired_redemptions"],
        )
    if totals["repeated_reservation_users"] > 0 and not any(
        flag["kind"] == "suspicious_reuse" for flag in review_flags
    ):
        add_flag(
            flag_id="coupon:repeated-reservations",
            kind="suspicious_reuse",
            severity="medium",
            title="Repeated coupon reservations in this period",
            detail=(
                "Repeated reservations occurred in small coupon segments. "
                "The per-coupon detail is suppressed; no user is punished automatically."
            ),
            affected_count=totals["repeated_reservation_users"],
        )

    return {
        "totals": totals,
        "by_coupon": by_coupon[:MAX_COUPON_ROWS],
        "suppressed_coupons": suppressed_coupons,
        "review_flags": review_flags[:MAX_REVIEW_FLAGS],
        "suppressed_review_flags": suppressed_review_flags,
        "reconciliation": reconciliation,
    }


async def _student_section(
    db: AsyncSession,
    *,
    period_start: datetime,
    period_end: datetime,
    plan: str | None,
) -> dict[str, Any]:
    base = _student_empty()
    if plan is not None and plan != "student":
        base["applicable"] = False
        return base

    window_rows = (
        await db.execute(
            select(
                UsageAnalytics.user_id,
                UsageAnalytics.action,
                UsageAnalytics.event_metadata,
                UsageAnalytics.created_at,
            )
            .where(
                UsageAnalytics.action.in_(STUDENT_EVENTS),
                UsageAnalytics.created_at >= period_start,
                UsageAnalytics.created_at < period_end,
            )
            .order_by(UsageAnalytics.created_at.asc())
            .limit(MAX_EVENT_ROWS)
        )
    ).all()
    filtered_window = []
    for row in window_rows:
        event_plan = _event_plan(row.event_metadata)
        if plan is not None and event_plan is not None and event_plan != plan:
            continue
        filtered_window.append(row)

    cohort_ids = {str(row.user_id) for row in filtered_window if row.user_id}
    timeline_by_user: dict[str, list[Any]] = defaultdict(list)
    if cohort_ids:
        timeline_rows = (
            await db.execute(
                select(
                    UsageAnalytics.user_id,
                    UsageAnalytics.action,
                    UsageAnalytics.event_metadata,
                    UsageAnalytics.created_at,
                )
                .where(
                    UsageAnalytics.action.in_(STUDENT_EVENTS),
                    UsageAnalytics.user_id.in_(sorted(cohort_ids)),
                    UsageAnalytics.created_at < period_end,
                )
                .order_by(UsageAnalytics.created_at.asc())
                .limit(MAX_EVENT_ROWS)
            )
        ).all()
        for row in timeline_rows:
            if row.user_id:
                timeline_by_user[str(row.user_id)].append(row)

    requested_users = 0
    verified_users = 0
    paid_users = 0
    paid_without_verification = 0
    plan_users: dict[str, set[str]] = defaultdict(set)
    for user_id in cohort_ids:
        timeline = timeline_by_user.get(user_id, [])
        request_event = next((row for row in timeline if row.action == STUDENT_REQUESTED), None)
        if request_event is None:
            continue
        requested_users += 1
        request_at = _as_utc(request_event.created_at)
        verify_event = next(
            (
                row
                for row in timeline
                if row.action == STUDENT_VERIFIED
                and request_at is not None
                and (_as_utc(row.created_at) or request_at) >= request_at
            ),
            None,
        )
        if verify_event is not None:
            verified_users += 1
            verify_at = _as_utc(verify_event.created_at)
            paid_event = next(
                (
                    row
                    for row in timeline
                    if row.action == STUDENT_PAID
                    and verify_at is not None
                    and (_as_utc(row.created_at) or verify_at) >= verify_at
                ),
                None,
            )
            if paid_event is not None:
                paid_users += 1
            event_plan = _event_plan(request_event.event_metadata) or "student"
            plan_users[event_plan].add(user_id)
        else:
            paid_event = next((row for row in timeline if row.action == STUDENT_PAID), None)
            if paid_event is not None:
                paid_without_verification += 1

    failure_rows = [row for row in filtered_window if row.action == STUDENT_FAILED]
    reason_counts: dict[str, int] = defaultdict(int)
    failure_users: dict[str, int] = defaultdict(int)
    for row in failure_rows:
        reason_counts[_safe_reason(row.event_metadata)] += 1
        if row.user_id:
            failure_users[str(row.user_id)] += 1
    repeated_failure_users = sum(1 for count in failure_users.values() if count > 1)
    repeated_failure_suppressed = 0 < repeated_failure_users < MIN_SEGMENT_SIZE

    steps = [
        {
            "key": "student_requested",
            "label": "Verification requested",
            "count": requested_users,
            "from_previous": 100.0 if requested_users else 0.0,
            "from_start": 100.0 if requested_users else 0.0,
        },
        {
            "key": "student_verified",
            "label": "Email verified",
            "count": verified_users,
            "from_previous": _pct(verified_users, requested_users),
            "from_start": _pct(verified_users, requested_users),
        },
        {
            "key": "student_paid",
            "label": "Paid",
            "count": paid_users,
            "from_previous": _pct(paid_users, verified_users),
            "from_start": _pct(paid_users, requested_users),
        },
    ]

    by_plan: list[dict[str, Any]] = []
    suppressed_segments = 0
    for plan_id, users in sorted(plan_users.items()):
        if len(users) < MIN_SEGMENT_SIZE:
            suppressed_segments += 1
            continue
        by_plan.append(
            {
                "plan_id": plan_id,
                "users": len(users),
                "conversion_pct": _pct(paid_users if plan_id == "student" else 0, len(users)),
            }
        )

    review_flags: list[dict[str, Any]] = []
    expired_count = reason_counts.get("expired_or_invalid", 0)
    reused_count = reason_counts.get("already_used", 0)
    if expired_count:
        review_flags.append(
            {
                "flag_id": "student:expired-or-invalid-tokens",
                "kind": "expired_or_invalid_token",
                "severity": "medium",
                "title": "Expired or invalid student verification links",
                "detail": (
                    "Verification links were invalid or past their 24-hour lifetime. "
                    "This is advisory; no account is blocked or punished automatically."
                ),
                "affected_count": expired_count,
                "requires_human_review": True,
                "automated_action": "none",
            }
        )
    if reused_count:
        review_flags.append(
            {
                "flag_id": "student:reused-tokens",
                "kind": "reused_token",
                "severity": "high",
                "title": "Reused student verification links",
                "detail": (
                    "A verification link was presented after it had already been used. "
                    "Review the aggregate pattern; no automatic punishment is applied."
                ),
                "affected_count": reused_count,
                "requires_human_review": True,
                "automated_action": "none",
            }
        )
    if repeated_failure_users and not repeated_failure_suppressed:
        review_flags.append(
            {
                "flag_id": "student:repeated-failures",
                "kind": "repeated_student_failures",
                "severity": "medium",
                "title": "Repeated student verification failures",
                "detail": (
                    "Several accounts failed verification more than once in this period. "
                    "Review the aggregate pattern with support; no automated action is taken."
                ),
                "affected_count": repeated_failure_users,
                "requires_human_review": True,
                "automated_action": "none",
            }
        )

    checks = [
        {
            "key": "requested_at_least_verified",
            "label": "Requested users are at least verified users",
            "ok": requested_users >= verified_users,
            "expected": requested_users,
            "actual": verified_users,
            "difference": verified_users - requested_users,
        },
        {
            "key": "verified_at_least_paid",
            "label": "Verified users are at least paid users",
            "ok": verified_users >= paid_users,
            "expected": verified_users,
            "actual": paid_users,
            "difference": paid_users - verified_users,
        },
        {
            "key": "paid_without_verification",
            "label": "No paid student subscription bypassed verification",
            "ok": paid_without_verification == 0,
            "expected": 0,
            "actual": paid_without_verification,
            "difference": paid_without_verification,
        },
    ]

    return {
        "applicable": True,
        "requested_users": requested_users,
        "verified_users": verified_users,
        "paid_users": paid_users,
        "steps": steps,
        "conversion": {
            "requested_to_verified": _pct(verified_users, requested_users),
            "verified_to_paid": _pct(paid_users, verified_users),
            "requested_to_paid": _pct(paid_users, requested_users),
        },
        "failures": {
            "total_events": len(failure_rows),
            "distinct_users": len(failure_users),
            "by_reason": [
                {
                    "reason": reason,
                    "label": FAILURE_LABELS.get(reason, "Other failure"),
                    "count": count,
                }
                for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "repeated_failure_users": (None if repeated_failure_suppressed else repeated_failure_users),
            "repeated_failure_users_suppressed": repeated_failure_suppressed,
        },
        "by_plan": by_plan,
        "suppressed_segments": suppressed_segments,
        "review_flags": review_flags,
        "reconciliation": {
            "requested_at_least_verified": requested_users >= verified_users,
            "verified_at_least_paid": verified_users >= paid_users,
            "paid_without_verification": paid_without_verification,
            "checks": checks,
        },
    }


async def coupon_student_performance(
    db: AsyncSession,
    *,
    days: int = 30,
    start: datetime | None = None,
    end: datetime | None = None,
    plan: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the Revenue coupon/student-performance report.

    ``plan`` filters coupon applicability and redemption/student events by the
    concrete plan family.  The default window is the trailing ``days`` days.
    """

    period_start, period_end, effective_days = _resolve_period(days=days, start=start, end=end, now=now)
    plan_value = (plan or "").strip().lower() or None
    generated_at = datetime.now(timezone.utc)

    coupon = await _coupon_section(db, period_start=period_start, period_end=period_end, plan=plan_value)
    student = await _student_section(db, period_start=period_start, period_end=period_end, plan=plan_value)

    review_flags = coupon["review_flags"] + student["review_flags"]
    review_flags.sort(
        key=lambda item: (
            0 if item.get("severity") == "high" else 1,
            item.get("kind", ""),
            item.get("flag_id", ""),
        )
    )

    return {
        "generated_at": generated_at.isoformat(),
        "period": {
            "days": effective_days,
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "timezone": "UTC",
        },
        "filters": {
            "days": days,
            "start": _as_utc(start).isoformat() if start else None,
            "end": _as_utc(end).isoformat() if end else None,
            "plan": plan_value,
            "timezone": "UTC",
        },
        "minimum_segment_size": MIN_SEGMENT_SIZE,
        "coupon": coupon,
        "student": student,
        "review_flags": review_flags[:MAX_REVIEW_FLAGS],
        "suppressed_review_flags": coupon["suppressed_review_flags"]
        + (1 if student["failures"]["repeated_failure_users_suppressed"] else 0),
        "privacy": {
            "aggregate_only": True,
            "student_emails_returned": False,
            "verification_tokens_returned": False,
            "account_ids_returned": False,
            "documents_returned": False,
            "event_metadata_returned": False,
            "minimum_segment_size": MIN_SEGMENT_SIZE,
        },
        "definitions": {
            "redemption_rate": "Redeemed coupon rows divided by reserved, redeemed and released rows in the period.",
            "coupon_conversion": "Redeemed coupon rows linked to a paid subscription divided by redeemed rows in the period.",
            "student_funnel": "Distinct users with a first-party request, verify and paid lifecycle event in order.",
            "suspicious_reuse": "An account repeatedly reserving the same coupon after a release; advisory review only.",
            "sensitive_reuse": "Expired or already-used verification links and expired coupon redemptions are review signals.",
        },
        "notes": [
            "Aggregate-only: student email addresses, verification tokens, account ids, IP addresses, user agents and documents are never returned.",
            "Coupon and student segments with fewer than five distinct users are suppressed.",
            "Abuse flags require human review. No account is blocked, refunded, downgraded or otherwise punished automatically.",
            "Redemptions are reconciled to the subscriptions ledger and coupon used_count; mismatches are surfaced for review rather than corrected.",
            "Lifecycle events are stored in the existing usage_analytics JSONB table; this report requires no migration.",
        ],
    }


coupon_student_analytics_service = type(
    "CouponStudentAnalyticsService",
    (),
    {"performance": staticmethod(coupon_student_performance)},
)()

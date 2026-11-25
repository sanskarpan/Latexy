"""Admin revenue analytics: MRR normalization, refunds, chargebacks and reconciliation.

All amounts are integer minor units. Every query is aggregate-only, excludes
test-mode provider rows, and never selects customer identifiers, payment
credentials or document content.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_plan_config, settings
from ..database import models

Payment = models.Payment
PaymentRefund = models.PaymentRefund
Subscription = models.Subscription
BillingWebhookEvent = models.BillingWebhookEvent

SETTLED_PAYMENT_STATUSES = ("paid", "partially_refunded", "captured", "refunded", "succeeded")
DISPUTE_EVENT_MARKERS = ("dispute", "chargeback")
MAX_SERIES_BUCKETS = 400
MAX_CHARGEBACK_ITEMS = 25

# Provider labels or identifiers that can only describe non-production traffic.
# Webhook events, subscriptions, payments and refunds use the same markers so a
# test-mode row cannot leak into revenue through a second table.
TEST_PROVIDER_MARKERS = ("test", "sandbox", "mock")


def _coalesced_lower(column):
    return func.lower(func.coalesce(column, ""))


def _live_provider_clause(column):
    lowered = _coalesced_lower(column)
    return and_(*(~lowered.like(f"%{marker}%") for marker in TEST_PROVIDER_MARKERS))


def _live_plan_clause(column):
    lowered = _coalesced_lower(column)
    return and_(~lowered.like("test%"), ~lowered.like("sandbox%"), ~lowered.like("mock%"))


def _live_identifier_clause(column):
    return ~_coalesced_lower(column).like("test%")


def live_provider_clause(column):
    """Public helper for adjacent admin queries that must share test-mode policy."""
    return _live_provider_clause(column)


def _looks_like_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def _live_subscription_ids():
    return select(Subscription.id).where(
        _live_provider_clause(Subscription.provider),
        _live_plan_clause(Subscription.plan_id),
        _live_identifier_clause(Subscription.provider_subscription_id),
    )


def _payment_filters(start: datetime, end: datetime, currency: str) -> list[Any]:
    return [
        Payment.created_at >= start,
        Payment.created_at <= end,
        Payment.status.in_(SETTLED_PAYMENT_STATUSES),
        _live_provider_clause(Payment.provider),
        _live_identifier_clause(Payment.provider_payment_id),
        func.upper(func.coalesce(Payment.currency, currency)) == currency,
        or_(Payment.subscription_id.is_(None), Payment.subscription_id.in_(_live_subscription_ids())),
    ]


def _refund_filters(start: datetime, end: datetime, currency: str, *, status: str | None = None) -> list[Any]:
    filters = [
        PaymentRefund.created_at >= start,
        PaymentRefund.created_at <= end,
        _live_provider_clause(PaymentRefund.provider),
        _live_identifier_clause(PaymentRefund.provider_refund_id),
        _live_provider_clause(Payment.provider),
        _live_identifier_clause(Payment.provider_payment_id),
        func.upper(func.coalesce(PaymentRefund.currency, Payment.currency, currency)) == currency,
        func.upper(func.coalesce(Payment.currency, currency)) == currency,
        or_(Payment.subscription_id.is_(None), Payment.subscription_id.in_(_live_subscription_ids())),
    ]
    if status is not None:
        filters.append(PaymentRefund.status == status)
    return filters


def plan_interval(plan_id: str | None) -> str:
    config = get_plan_config(plan_id) or {}
    interval = str(config.get("interval") or "month").strip().lower()
    return interval if interval in {"week", "month", "year", "lifetime"} else "month"


def monthly_amount(plan_id: str | None, quoted_amount: int | None) -> int:
    """Normalize one subscription quote to a monthly minor-unit amount.

    Annual quotes are divided by 12, weekly quotes use 52/12 weeks per month,
    and lifetime purchases are excluded from MRR because they are not
    recurring. A provider quote wins over catalog pricing so discounts and
    grandfathering are reflected; the catalog's ``monthly_equivalent_price`` is
    the fallback for annual rows without a stored quote.
    """
    config = get_plan_config(plan_id) or {}
    interval = plan_interval(plan_id)
    if interval == "lifetime":
        return 0
    monthly_equivalent = config.get("monthly_equivalent_price")
    quoted = quoted_amount if type(quoted_amount) is int and quoted_amount >= 0 else None
    if quoted is not None and quoted > 0:
        amount = float(quoted)
    elif type(monthly_equivalent) is int:
        return max(0, int(monthly_equivalent))
    else:
        amount = float(config.get("price") or 0)
    if interval == "year":
        amount = amount / 12
    elif interval == "week":
        amount = amount * 52 / 12
    return max(0, int(round(amount)))


def _to_minor_float(amount_minor: int) -> float:
    return round(int(amount_minor) / 100, 2)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _bucket_key(value: datetime, granularity: str) -> str:
    value = _as_utc(value) or datetime.now(timezone.utc)
    if granularity == "month":
        return value.strftime("%Y-%m")
    return value.date().isoformat()


def _bucket_label(key: str, granularity: str) -> str:
    if granularity == "month":
        try:
            parsed = datetime.strptime(key, "%Y-%m")
        except ValueError:
            return key
        return parsed.strftime("%b %Y")
    try:
        parsed_date = date.fromisoformat(key)
    except ValueError:
        return key
    return parsed_date.strftime("%b %d")


def _iter_buckets(start: datetime, end: datetime, granularity: str) -> list[str]:
    buckets: list[str] = []
    if granularity == "month":
        cursor = date(start.year, start.month, 1)
        last = date(end.year, end.month, 1)
        while cursor <= last and len(buckets) < MAX_SERIES_BUCKETS:
            buckets.append(cursor.strftime("%Y-%m"))
            cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
        return buckets
    cursor = start.date()
    last = end.date()
    while cursor <= last and len(buckets) < MAX_SERIES_BUCKETS:
        buckets.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return buckets


def _dispute_status(event_type: str) -> str:
    suffix = str(event_type or "").lower().rsplit(".", 1)[-1].replace("-", "_")
    if suffix in {"lost", "expired", "accepted"}:
        return "lost"
    if suffix in {"won", "reversed", "reversal"}:
        return "won"
    if suffix in {"opened", "open", "created", "needs_response", "warning_needs_response", "under_review", "challenged", "pending"}:
        return "open"
    if suffix in {"closed", "resolved", "cancelled", "canceled"}:
        return "resolved"
    return suffix[:32] or "unknown"


def _dispute_is_open(status: str) -> bool:
    return status == "open"


def _dispute_is_resolved(status: str) -> bool:
    return status in {"won", "lost", "resolved"}


async def _chargeback_data(
    db: AsyncSession,
    *,
    start: datetime,
    end: datetime,
    currency: str,
) -> dict[str, Any]:
    lowered = _coalesced_lower(BillingWebhookEvent.event_type)
    filters = [
        BillingWebhookEvent.received_at >= start,
        BillingWebhookEvent.received_at <= end,
        _live_provider_clause(BillingWebhookEvent.provider),
        _live_identifier_clause(BillingWebhookEvent.event_id),
        or_(*(lowered.like(f"%{marker}%") for marker in DISPUTE_EVENT_MARKERS)),
    ]
    rows = (
        await db.execute(
            select(
                BillingWebhookEvent.id,
                BillingWebhookEvent.event_type,
                BillingWebhookEvent.event_resource_id,
                BillingWebhookEvent.received_at,
                BillingWebhookEvent.event_at,
            )
            .where(*filters)
            .order_by(BillingWebhookEvent.received_at.asc(), BillingWebhookEvent.id.asc())
        )
    ).all()

    resource_ids = {row.event_resource_id for row in rows if row.event_resource_id}
    local_payment_ids = [value for value in resource_ids if _looks_like_uuid(value)]
    payments: dict[str, Any] = {}
    test_mode_resources: set[str] = set()
    if resource_ids:
        match_conditions = [Payment.provider_payment_id.in_(resource_ids)]
        if local_payment_ids:
            match_conditions.append(Payment.id.in_(local_payment_ids))
        payment_rows = (
            await db.execute(
                select(
                    Payment.provider,
                    Payment.provider_payment_id,
                    Payment.id,
                    Payment.amount,
                    Payment.currency,
                    Subscription.plan_id,
                )
                .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
                .where(or_(*match_conditions))
            )
        ).all()
        for payment_row in payment_rows:
            provider_value = str(payment_row.provider or "").lower()
            identifier_value = str(payment_row.provider_payment_id or "").lower()
            plan_value = str(payment_row.plan_id or "").lower()
            is_test = (
                any(marker in provider_value for marker in TEST_PROVIDER_MARKERS)
                or identifier_value.startswith("test")
                or plan_value.startswith(("test", "sandbox", "mock"))
            )
            keys = {
                key
                for key in (payment_row.provider_payment_id, str(payment_row.id))
                if key
            }
            if is_test:
                test_mode_resources.update(keys)
            else:
                for key in keys:
                    payments[key] = payment_row

    latest_by_resource: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    for row in rows:
        if row.event_resource_id in test_mode_resources:
            continue
        payment = payments.get(row.event_resource_id) if row.event_resource_id else None
        payment_currency = str(getattr(payment, "currency", "") or "").upper()
        amount_minor = (
            int(payment.amount)
            if payment is not None and payment_currency == currency
            else None
        )
        status = _dispute_status(row.event_type)
        received_at = _as_utc(row.received_at)
        item = {
            "id": row.id,
            "event_type": row.event_type,
            "status": status,
            "amount_minor": amount_minor,
            "currency": currency if amount_minor is not None else None,
            "payment_id": str(payment.id) if payment is not None else None,
            "payment_linked": payment is not None,
            "bucket": _bucket_key(received_at or datetime.now(timezone.utc), "day"),
            "event_at": row.event_at.isoformat() if row.event_at else None,
            "received_at": received_at.isoformat() if received_at else None,
        }
        items.append(item)
        dedupe_key = row.event_resource_id or f"event:{row.id}"
        current = latest_by_resource.get(dedupe_key)
        if current is None or (received_at or datetime.min.replace(tzinfo=timezone.utc)) >= (
            current["_received_at"] or datetime.min.replace(tzinfo=timezone.utc)
        ):
            latest_by_resource[dedupe_key] = {**item, "_received_at": received_at}

    unique_items = list(latest_by_resource.values())
    total_minor = sum(int(item["amount_minor"] or 0) for item in unique_items)
    open_minor = sum(int(item["amount_minor"] or 0) for item in unique_items if _dispute_is_open(item["status"]))
    resolved_minor = sum(
        int(item["amount_minor"] or 0) for item in unique_items if _dispute_is_resolved(item["status"])
    )
    lost_minor = sum(int(item["amount_minor"] or 0) for item in unique_items if item["status"] == "lost")
    won_minor = sum(int(item["amount_minor"] or 0) for item in unique_items if item["status"] == "won")

    by_status: dict[str, dict[str, Any]] = {}
    for item in unique_items:
        bucket = by_status.setdefault(
            item["status"],
            {"status": item["status"], "count": 0, "amount_minor": 0, "events": 0},
        )
        bucket["count"] += 1
        bucket["amount_minor"] += int(item["amount_minor"] or 0)
    for item in items:
        status_bucket = by_status.setdefault(
            item["status"],
            {"status": item["status"], "count": 0, "amount_minor": 0, "events": 0},
        )
        status_bucket["events"] += 1

    series_minor: dict[str, int] = defaultdict(int)
    series_count: dict[str, int] = defaultdict(int)
    for item in unique_items:
        if item["amount_minor"] is not None:
            series_minor[item["bucket"]] += int(item["amount_minor"])
        series_count[item["bucket"]] += 1

    return {
        "currency": currency,
        "total_minor": total_minor,
        "total": _to_minor_float(total_minor),
        "count": len(unique_items),
        "events_count": len(items),
        "open_count": sum(1 for item in unique_items if _dispute_is_open(item["status"])),
        "resolved_count": sum(1 for item in unique_items if _dispute_is_resolved(item["status"])),
        "lost_count": sum(1 for item in unique_items if item["status"] == "lost"),
        "won_count": sum(1 for item in unique_items if item["status"] == "won"),
        "open_minor": open_minor,
        "resolved_minor": resolved_minor,
        "lost_minor": lost_minor,
        "won_minor": won_minor,
        "unlinked_count": sum(1 for item in unique_items if not item["payment_linked"]),
        "amount_unavailable_count": sum(1 for item in unique_items if item["amount_minor"] is None),
        "by_status": sorted(by_status.values(), key=lambda item: (-item["amount_minor"], item["status"])),
        "items": sorted(items, key=lambda item: (item["received_at"] or "", item["id"]), reverse=True)[
            :MAX_CHARGEBACK_ITEMS
        ],
        "_series_minor": dict(series_minor),
        "_series_count": dict(series_count),
    }


def _empty_series_point(bucket: str, granularity: str) -> dict[str, Any]:
    return {
        "bucket": bucket,
        "label": _bucket_label(bucket, granularity),
        "gross_revenue_minor": 0,
        "refunds_minor": 0,
        "chargebacks_minor": 0,
        "net_revenue_minor": 0,
        "net_revenue_after_chargebacks_minor": 0,
        "payments_count": 0,
        "refunds_count": 0,
        "chargebacks_count": 0,
    }


def _series_rows(
    rows: Iterable[Any],
    *,
    bucket_index: dict[str, dict[str, Any]],
    granularity: str,
    amount_field: str,
    count_field: str,
    amount_index: int,
    count_index: int,
) -> None:
    for row in rows:
        key = _bucket_key(row[0], granularity)
        point = bucket_index.get(key)
        if point is None:
            continue
        point[amount_field] += int(row[amount_index] or 0)
        point[count_field] += int(row[count_index] or 0)


async def revenue_analytics(
    db: AsyncSession,
    *,
    period_start: datetime,
    period_end: datetime,
    currency: str | None = None,
    granularity: str = "day",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the revenue view shared by the admin billing summary and tests."""
    currency = (currency or settings.BILLING_CURRENCY or "INR").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("Currency must be a three-letter ISO code")
    granularity = str(granularity or "day").strip().lower()
    granularity = {"daily": "day", "monthly": "month"}.get(granularity, granularity)
    if granularity not in {"day", "month"}:
        raise ValueError("Granularity must be day or month")
    now = _as_utc(now) or datetime.now(timezone.utc)

    subscription_filters = [
        Subscription.status.in_(("cancel_scheduled", "active", "past_due", "on_hold", "paused")),
        _live_provider_clause(Subscription.provider),
        _live_plan_clause(Subscription.plan_id),
        _live_identifier_clause(Subscription.provider_subscription_id),
    ]
    subscription_rows = (
        await db.execute(
            select(
                Subscription.plan_id,
                Subscription.quoted_amount,
                Subscription.current_period_end,
                Subscription.status,
            ).where(*subscription_filters)
        )
    ).all()

    # Preserve the control room's paid-status definition of "active": a paused
    # or past-due subscription still carries contracted MRR until it expires or
    # is cancelled. ``past_due_subscriptions`` remains a separate risk count.
    active_rows = [
        row
        for row in subscription_rows
        if row.status in ("cancel_scheduled", "active", "past_due", "on_hold", "paused")
        and (row.current_period_end is None or _as_utc(row.current_period_end) >= now)
    ]
    past_due = sum(1 for row in subscription_rows if row.status in {"past_due", "on_hold"})
    active_count = len(active_rows)
    recurring_count = sum(1 for row in active_rows if plan_interval(row.plan_id) != "lifetime")

    interval_buckets: dict[str, dict[str, Any]] = {}
    mrr_minor = 0
    active_plan_rows: dict[str, dict[str, Any]] = {}
    for row in active_rows:
        amount = monthly_amount(row.plan_id, row.quoted_amount)
        interval = plan_interval(row.plan_id)
        mrr_minor += amount
        interval_bucket = interval_buckets.setdefault(
            interval, {"interval": interval, "subscriptions": 0, "mrr_minor": 0}
        )
        interval_bucket["subscriptions"] += 1
        interval_bucket["mrr_minor"] += amount
        plan_bucket = active_plan_rows.setdefault(
            row.plan_id,
            {"plan_id": row.plan_id, "subscriptions": 0, "mrr_minor": 0, "interval": interval},
        )
        plan_bucket["subscriptions"] += 1
        plan_bucket["mrr_minor"] += amount

    gross_minor, payments_count = (
        await db.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(Payment.id),
            ).where(*_payment_filters(period_start, period_end, currency))
        )
    ).one()
    gross_minor = int(gross_minor)
    payments_count = int(payments_count)

    refund_rows = (
        await db.execute(
            select(
                PaymentRefund.status,
                func.count(PaymentRefund.id),
                func.coalesce(func.sum(func.coalesce(PaymentRefund.amount, 0)), 0),
            )
            .join(Payment, Payment.id == PaymentRefund.payment_id)
            .where(*_refund_filters(period_start, period_end, currency))
            .group_by(PaymentRefund.status)
        )
    ).all()
    refund_by_status: list[dict[str, Any]] = []
    refunded_minor = 0
    refunds_count = 0
    for status, count, amount in refund_rows:
        amount_minor = int(amount or 0)
        refund_by_status.append(
            {"status": status, "count": int(count), "amount_minor": amount_minor}
        )
        if status == "succeeded":
            refunded_minor += amount_minor
            refunds_count += int(count)
    refund_by_status.sort(key=lambda item: (-item["amount_minor"], item["status"]))
    net_minor = gross_minor - refunded_minor

    recent_refund_rows = (
        await db.execute(
            select(
                PaymentRefund.id,
                PaymentRefund.payment_id,
                PaymentRefund.amount,
                PaymentRefund.currency,
                PaymentRefund.status,
                PaymentRefund.created_at,
            )
            .join(Payment, Payment.id == PaymentRefund.payment_id)
            .where(*_refund_filters(period_start, period_end, currency))
            .order_by(PaymentRefund.created_at.desc(), PaymentRefund.id.desc())
            .limit(10)
        )
    ).all()
    recent_refunds = [
        {
            "id": row.id,
            "payment_id": row.payment_id,
            "amount_minor": int(row.amount or 0),
            "currency": row.currency or currency,
            "status": row.status,
            "created_at": _as_utc(row.created_at).isoformat() if row.created_at else None,
        }
        for row in recent_refund_rows
    ]

    chargebacks = await _chargeback_data(
        db, start=period_start, end=period_end, currency=currency
    )
    chargebacks_minor = int(chargebacks["total_minor"])
    net_after_chargebacks_minor = net_minor - chargebacks_minor

    payment_bucket = func.date_trunc(granularity, Payment.created_at)
    payment_series = (
        await db.execute(
            select(
                payment_bucket,
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(Payment.id),
            )
            .where(*_payment_filters(period_start, period_end, currency))
            .group_by(payment_bucket)
            .order_by(payment_bucket)
        )
    ).all()
    refund_bucket = func.date_trunc(granularity, PaymentRefund.created_at)
    refund_series = (
        await db.execute(
            select(
                refund_bucket,
                func.coalesce(func.sum(func.coalesce(PaymentRefund.amount, 0)), 0),
                func.count(PaymentRefund.id),
            )
            .join(Payment, Payment.id == PaymentRefund.payment_id)
            .where(*_refund_filters(period_start, period_end, currency, status="succeeded"))
            .group_by(refund_bucket)
            .order_by(refund_bucket)
        )
    ).all()
    buckets = _iter_buckets(period_start, period_end, granularity)
    bucket_index = {bucket: _empty_series_point(bucket, granularity) for bucket in buckets}
    _series_rows(
        payment_series,
        bucket_index=bucket_index,
        granularity=granularity,
        amount_field="gross_revenue_minor",
        count_field="payments_count",
        amount_index=1,
        count_index=2,
    )
    _series_rows(
        refund_series,
        bucket_index=bucket_index,
        granularity=granularity,
        amount_field="refunds_minor",
        count_field="refunds_count",
        amount_index=1,
        count_index=2,
    )
    for bucket, amount in chargebacks["_series_minor"].items():
        key = bucket if granularity == "day" else bucket[:7]
        point = bucket_index.get(key)
        if point is not None:
            point["chargebacks_minor"] += int(amount)
    for bucket, count in chargebacks["_series_count"].items():
        key = bucket if granularity == "day" else bucket[:7]
        point = bucket_index.get(key)
        if point is not None:
            point["chargebacks_count"] += int(count)
    revenue_series = list(bucket_index.values())
    for point in revenue_series:
        point["net_revenue_minor"] = (
            point["gross_revenue_minor"] - point["refunds_minor"]
        )
        point["net_revenue_after_chargebacks_minor"] = (
            point["net_revenue_minor"] - point["chargebacks_minor"]
        )

    plan_expression = func.coalesce(Subscription.plan_id, "unattributed")
    plan_payment_rows = (
        await db.execute(
            select(
                plan_expression,
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(Payment.id),
            )
            .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
            .where(*_payment_filters(period_start, period_end, currency))
            .group_by(plan_expression)
        )
    ).all()
    plan_refund_rows = (
        await db.execute(
            select(
                plan_expression,
                func.coalesce(func.sum(func.coalesce(PaymentRefund.amount, 0)), 0),
                func.count(PaymentRefund.id),
            )
            .join(Payment, Payment.id == PaymentRefund.payment_id)
            .outerjoin(Subscription, Payment.subscription_id == Subscription.id)
            .where(*_refund_filters(period_start, period_end, currency, status="succeeded"))
            .group_by(plan_expression)
        )
    ).all()
    plan_mix: dict[str, dict[str, Any]] = {}
    for plan_id, active_bucket in active_plan_rows.items():
        plan_mix[plan_id] = {
            "plan_id": plan_id,
            "subscriptions": active_bucket["subscriptions"],
            "mrr_minor": active_bucket["mrr_minor"],
            "interval": active_bucket["interval"],
            "revenue_minor": 0,
            "refunded_minor": 0,
            "payments_count": 0,
            "refunds_count": 0,
        }
    for plan_id, revenue, count in plan_payment_rows:
        key = str(plan_id or "unattributed")
        bucket = plan_mix.setdefault(
            key,
            {
                "plan_id": key,
                "subscriptions": 0,
                "mrr_minor": 0,
                "interval": plan_interval(key) if key != "unattributed" else "unknown",
                "revenue_minor": 0,
                "refunded_minor": 0,
                "payments_count": 0,
                "refunds_count": 0,
            },
        )
        bucket["revenue_minor"] += int(revenue or 0)
        bucket["payments_count"] += int(count or 0)
    for plan_id, refunded, count in plan_refund_rows:
        key = str(plan_id or "unattributed")
        bucket = plan_mix.setdefault(
            key,
            {
                "plan_id": key,
                "subscriptions": 0,
                "mrr_minor": 0,
                "interval": plan_interval(key) if key != "unattributed" else "unknown",
                "revenue_minor": 0,
                "refunded_minor": 0,
                "payments_count": 0,
                "refunds_count": 0,
            },
        )
        bucket["refunded_minor"] += int(refunded or 0)
        bucket["refunds_count"] += int(count or 0)
    for bucket in plan_mix.values():
        bucket["net_revenue_minor"] = bucket["revenue_minor"] - bucket["refunded_minor"]
    attributed_revenue = sum(bucket["revenue_minor"] for bucket in plan_mix.values())
    attributed_refunds = sum(bucket["refunded_minor"] for bucket in plan_mix.values())
    attributed_net = sum(bucket["net_revenue_minor"] for bucket in plan_mix.values())
    for bucket in plan_mix.values():
        bucket["mrr"] = _to_minor_float(bucket["mrr_minor"])
        bucket["revenue"] = _to_minor_float(bucket["revenue_minor"])
        bucket["refunded"] = _to_minor_float(bucket["refunded_minor"])
        bucket["net_revenue"] = _to_minor_float(bucket["net_revenue_minor"])
        bucket["share_percent"] = (
            round(bucket["revenue_minor"] * 100 / gross_minor, 2) if gross_minor else 0.0
        )
    plan_mix_rows = sorted(
        plan_mix.values(),
        key=lambda item: (-item["mrr_minor"], -item["revenue_minor"], item["plan_id"]),
    )

    refund_view = {
        "currency": currency,
        "total_minor": refunded_minor,
        "total": _to_minor_float(refunded_minor),
        "count": refunds_count,
        "succeeded_minor": refunded_minor,
        "succeeded": _to_minor_float(refunded_minor),
        "succeeded_count": refunds_count,
        "failed_minor": next(
            (item["amount_minor"] for item in refund_by_status if item["status"] == "failed"), 0
        ),
        "failed_count": next(
            (item["count"] for item in refund_by_status if item["status"] == "failed"), 0
        ),
        "pending_minor": next(
            (item["amount_minor"] for item in refund_by_status if item["status"] in {"pending", "processing"}),
            0,
        ),
        "pending_count": sum(
            item["count"] for item in refund_by_status if item["status"] in {"pending", "processing"}
        ),
        "by_status": refund_by_status,
        "recent": recent_refunds,
    }
    public_chargebacks = {
        key: value for key, value in chargebacks.items() if not key.startswith("_")
    }

    checks = [
        {
            "key": "net_revenue_after_refunds",
            "label": "Net revenue equals settled payments minus succeeded refunds",
            "ok": net_minor == gross_minor - refunded_minor,
            "expected_minor": gross_minor - refunded_minor,
            "actual_minor": net_minor,
            "difference_minor": net_minor - (gross_minor - refunded_minor),
        },
        {
            "key": "refund_applied_once",
            "label": "Succeeded refunds are counted once and failed refunds are excluded",
            "ok": refund_view["succeeded_minor"] == refunded_minor,
            "expected_minor": refunded_minor,
            "actual_minor": refund_view["succeeded_minor"],
            "difference_minor": refund_view["succeeded_minor"] - refunded_minor,
        },
        {
            "key": "plan_mix_revenue",
            "label": "Plan-mix revenue reconciles to settled payments",
            "ok": attributed_revenue == gross_minor,
            "expected_minor": gross_minor,
            "actual_minor": attributed_revenue,
            "difference_minor": attributed_revenue - gross_minor,
        },
        {
            "key": "plan_mix_refunds",
            "label": "Plan-mix refunds reconcile to succeeded refunds",
            "ok": attributed_refunds == refunded_minor,
            "expected_minor": refunded_minor,
            "actual_minor": attributed_refunds,
            "difference_minor": attributed_refunds - refunded_minor,
        },
        {
            "key": "plan_mix_net",
            "label": "Plan-mix net revenue reconciles to net revenue",
            "ok": attributed_net == net_minor,
            "expected_minor": net_minor,
            "actual_minor": attributed_net,
            "difference_minor": attributed_net - net_minor,
        },
        {
            "key": "chargeback_events",
            "label": "Chargeback/dispute amounts reconcile to linked payments",
            "ok": chargebacks_minor == public_chargebacks["total_minor"],
            "expected_minor": public_chargebacks["total_minor"],
            "actual_minor": chargebacks_minor,
            "difference_minor": chargebacks_minor - public_chargebacks["total_minor"],
        },
    ]
    reconciliation = {
        "currency": currency,
        "gross_from_payments_minor": gross_minor,
        "refunded_from_payment_refunds_minor": refunded_minor,
        "net_revenue_minor": net_minor,
        "expected_net_minor": gross_minor - refunded_minor,
        "difference_minor": net_minor - (gross_minor - refunded_minor),
        "balanced": all(check["ok"] for check in checks),
        "payments_count": payments_count,
        "refunds_count": refunds_count,
        "chargebacks_from_events_minor": chargebacks_minor,
        "net_after_chargebacks_minor": net_after_chargebacks_minor,
        "plan_mix_attributed_revenue_minor": attributed_revenue,
        "plan_mix_attributed_refunds_minor": attributed_refunds,
        "plan_mix_attributed_net_minor": attributed_net,
        "plan_mix_revenue_difference_minor": attributed_revenue - gross_minor,
        "test_mode_excluded": True,
        "test_mode_policy": (
            "Rows whose provider contains test/sandbox/mock, or whose provider "
            "identifier is test-prefixed, are excluded from every total."
        ),
        "checks": checks,
    }

    return {
        "currency": currency,
        "granularity": granularity,
        "active_subscriptions": active_count,
        "active_recurring_subscriptions": recurring_count,
        "past_due_subscriptions": past_due,
        "mrr_minor": mrr_minor,
        "arr_minor": mrr_minor * 12,
        "arpu_minor": int(round(mrr_minor / active_count)) if active_count else 0,
        "mrr_normalization": {
            "basis": "active_subscriptions",
            "annual_divisor": 12,
            "weekly_weeks_per_month": round(52 / 12, 4),
            "lifetime_policy": "excluded_from_mrr",
            "active_subscriptions": active_count,
            "recurring_subscriptions": recurring_count,
            "by_interval": sorted(
                (
                    {**bucket, "mrr": _to_minor_float(bucket["mrr_minor"])}
                    for bucket in interval_buckets.values()
                ),
                key=lambda item: item["interval"],
            ),
        },
        "gross_revenue_minor": gross_minor,
        "payments_count": payments_count,
        "refunded_minor": refunded_minor,
        "refunds_count": refunds_count,
        "net_revenue_minor": net_minor,
        "chargebacks_minor": chargebacks_minor,
        "chargebacks_count": int(public_chargebacks["count"]),
        "net_revenue_after_chargebacks_minor": net_after_chargebacks_minor,
        "revenue_series": revenue_series,
        "refund_view": refund_view,
        "chargeback_view": public_chargebacks,
        "plan_mix": plan_mix_rows,
        "reconciliation": reconciliation,
    }

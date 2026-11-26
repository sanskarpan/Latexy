"""Aggregate weekly/lifetime plan health, retention and advisory risk flags.

The report is read-only. It is derived from the existing ``subscriptions``,
``payments``, ``payment_refunds``, ``subscription_history`` and
``billing_webhook_events`` tables; no migration or new ledger is introduced.
Every value is aggregate-only: customer ids are used inside this module to count
distinct cohort members, but are never selected into the response, logged, or
returned to the browser. Monthly cohorts with fewer than five distinct users are
dropped rather than published.

Risk flags are advisory. This module never refunds, downgrades, cancels, grants
or otherwise mutates billing state, and its alert signals explicitly require
human review.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models
from .admin_revenue_service import live_provider_clause

Payment = models.Payment
PaymentRefund = models.PaymentRefund
Subscription = models.Subscription
SubscriptionHistory = models.SubscriptionHistory
BillingWebhookEvent = models.BillingWebhookEvent

PLANS = ("weekly", "lifetime")
MIN_COHORT_SIZE = 5
MAX_SCANNED_ROWS = 100_000
COHORT_MONTHS = 12
MAX_ALERT_SIGNALS = 6
RUNBOOK_URL = "https://github.com/sanskarpan/Latexy/blob/main/docs/ADMIN_CONTROL_ROOM.md"

ACTIVE_SUBSCRIPTION_STATUSES = ("active", "cancel_scheduled", "past_due", "on_hold", "paused")
SETTLED_PAYMENT_STATUSES = ("paid", "partially_refunded", "captured", "refunded", "succeeded")
NON_ACQUISITION_STATUSES = ("checkout_pending", "checkout_unknown", "created", "pending", "failed")
DISPUTE_EVENT_MARKERS = ("dispute", "chargeback")

# Rates are arithmetic aggregates. The five-user floor applies to published
# cohorts (below), where a count of one is person-sized; transaction totals and
# their rates remain visible so operators can reconcile them with the ledger.
LIFETIME_REFUND_RATE_WARN_PCT = 10.0
WEEKLY_CHURN_WARN_PCT = 25.0
WEEKLY_RENEWAL_LOW_PCT = 60.0
REFUND_AMOUNT_RATE_WARN_PCT = 10.0
CHARGEBACK_RATE_WARN_PCT = 2.0
MIN_RATE_SAMPLE = 5


@dataclass(frozen=True)
class SubscriptionRow:
    id: str
    user_id: str
    plan_id: str
    status: str
    created_at: datetime
    cancelled_at: datetime | None
    current_period_end: datetime | None


@dataclass(frozen=True)
class PaymentRow:
    plan_id: str
    subscription_id: str | None
    amount: int
    status: str
    created_at: datetime


@dataclass(frozen=True)
class RefundRow:
    plan_id: str
    subscription_id: str | None
    amount: int
    status: str
    created_at: datetime


@dataclass(frozen=True)
class RenewalEventRow:
    plan_id: str
    subscription_id: str
    effective_at: datetime


@dataclass(frozen=True)
class ChargebackRow:
    plan_id: str
    status: str
    amount: int | None
    received_at: datetime


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _pct(value: int | float, total: int | float) -> float:
    return round((float(value) / float(total)) * 100, 2) if total else 0.0


def _minor_to_amount(minor: int) -> float:
    return round(int(minor) / 100, 2)


def _live_identifier_clause(column):
    return ~func.lower(func.coalesce(column, "")).like("test%")


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
    value = _as_utc(value)
    return value is not None and start <= value < end


def _is_active(row: SubscriptionRow, now: datetime) -> bool:
    if row.status not in ACTIVE_SUBSCRIPTION_STATUSES:
        return False
    period_end = _as_utc(row.current_period_end)
    return period_end is None or period_end >= now


def _month_key(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m")


def _shift_month(value: datetime, delta: int) -> datetime:
    index = value.year * 12 + (value.month - 1) + delta
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=timezone.utc)


def _month_bounds(now: datetime, months: int) -> list[str]:
    current = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    return [_shift_month(current, -offset).strftime("%Y-%m") for offset in range(months)]


def _cohort_rows(
    subscriptions: Iterable[SubscriptionRow],
    *,
    plan_id: str,
    now: datetime,
) -> dict[str, Any]:
    allowed_months = set(_month_bounds(now, COHORT_MONTHS))
    buckets: dict[str, list[SubscriptionRow]] = defaultdict(list)
    for row in subscriptions:
        created = _as_utc(row.created_at)
        if row.plan_id != plan_id or created is None:
            continue
        key = _month_key(created)
        if key in allowed_months:
            buckets[key].append(row)

    cohorts: list[dict[str, Any]] = []
    suppressed = 0
    for key in sorted(buckets, reverse=True):
        rows = buckets[key]
        users = {row.user_id for row in rows}
        if len(users) < MIN_COHORT_SIZE:
            suppressed += 1
            continue
        active = sum(1 for row in rows if _is_active(row, now))
        cohorts.append(
            {
                "cohort": key,
                "users": len(users),
                "subscriptions": len(rows),
                "active_subscriptions": active,
                "retained_pct": _pct(active, len(rows)),
            }
        )

    total_subscriptions = sum(item["subscriptions"] for item in cohorts)
    retained = sum(item["active_subscriptions"] for item in cohorts)
    return {
        "months": COHORT_MONTHS,
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "cohorts": cohorts,
        "suppressed_cohorts": suppressed,
        "tracked_subscriptions": total_subscriptions,
        "retained_subscriptions": retained,
        "retention_pct": _pct(retained, total_subscriptions),
    }


def _status_counts(rows: Iterable[SubscriptionRow]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.status] += 1
    return [
        {"status": status, "count": count}
        for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _risk_flag(
    *,
    code: str,
    plan_id: str,
    severity: str,
    title: str,
    detail: str,
    metric: str,
    value: int | float,
    threshold: int | float,
    sample_size: int,
) -> dict[str, Any]:
    return {
        "code": code,
        "plan_id": plan_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "metric": metric,
        "value": value,
        "threshold": threshold,
        "sample_size": sample_size,
        "advisory": True,
        "requires_human_review": True,
        "auto_action": "none",
    }


def _plan_risk_flags(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    plan_id = metrics["plan_id"]
    revenue = metrics["revenue"]
    refunds = metrics["refunds"]
    chargebacks = metrics["chargebacks"]
    flags: list[dict[str, Any]] = []

    if plan_id == "lifetime":
        sales = metrics["lifetime_sales"]
        rate = metrics["lifetime_refund_rate_pct"]
        if sales >= MIN_RATE_SAMPLE and rate >= LIFETIME_REFUND_RATE_WARN_PCT:
            flags.append(
                _risk_flag(
                    code="lifetime_refund_rate_high",
                    plan_id=plan_id,
                    severity="high",
                    title="Lifetime refund rate is above the advisory threshold",
                    detail=(
                        f"{metrics['lifetime_refunds']} refunded lifetime purchases of "
                        f"{sales} settled lifetime purchases ({rate:.2f}%). Review the "
                        "refund reasons before changing pricing or access policy."
                    ),
                    metric="lifetime_refund_rate_pct",
                    value=rate,
                    threshold=LIFETIME_REFUND_RATE_WARN_PCT,
                    sample_size=sales,
                )
            )

    if plan_id == "weekly":
        decisions = metrics["renewal"]["renewals"] + metrics["renewal"]["cancellations"]
        if decisions >= MIN_RATE_SAMPLE and metrics["renewal"]["renewal_rate_pct"] < WEEKLY_RENEWAL_LOW_PCT:
            flags.append(
                _risk_flag(
                    code="weekly_renewal_rate_low",
                    plan_id=plan_id,
                    severity="medium",
                    title="Weekly renewal rate is below the advisory threshold",
                    detail=(
                        f"{metrics['renewal']['renewals']} renewals and "
                        f"{metrics['renewal']['cancellations']} cancellations in the window "
                        f"({metrics['renewal']['renewal_rate_pct']:.2f}% renewal)."
                    ),
                    metric="weekly_renewal_rate_pct",
                    value=metrics["renewal"]["renewal_rate_pct"],
                    threshold=WEEKLY_RENEWAL_LOW_PCT,
                    sample_size=decisions,
                )
            )
        base = metrics["active_subscriptions"] + metrics["renewal"]["cancellations"]
        if base >= MIN_RATE_SAMPLE and metrics["renewal"]["churn_rate_pct"] >= WEEKLY_CHURN_WARN_PCT:
            flags.append(
                _risk_flag(
                    code="weekly_churn_rate_high",
                    plan_id=plan_id,
                    severity="high",
                    title="Weekly churn is above the advisory threshold",
                    detail=(
                        f"{metrics['renewal']['cancellations']} weekly cancellations against "
                        f"{metrics['active_subscriptions']} active subscriptions "
                        f"({metrics['renewal']['churn_rate_pct']:.2f}% churn)."
                    ),
                    metric="weekly_churn_rate_pct",
                    value=metrics["renewal"]["churn_rate_pct"],
                    threshold=WEEKLY_CHURN_WARN_PCT,
                    sample_size=base,
                )
            )

    if (
        revenue["gross_minor"] > 0
        and revenue["payments_count"] >= MIN_RATE_SAMPLE
        and refunds["amount_rate_pct"] >= REFUND_AMOUNT_RATE_WARN_PCT
    ):
        flags.append(
            _risk_flag(
                code="refund_amount_rate_high",
                plan_id=plan_id,
                severity="high",
                title="Refunded amount is elevated for this plan",
                detail=(
                    f"Refunds are {refunds['amount_rate_pct']:.2f}% of gross plan revenue in "
                    "the window. Verify the underlying refunds; no automatic action was taken."
                ),
                metric="refund_amount_rate_pct",
                value=refunds["amount_rate_pct"],
                threshold=REFUND_AMOUNT_RATE_WARN_PCT,
                sample_size=revenue["payments_count"],
            )
        )

    if chargebacks["open_count"] > 0:
        flags.append(
            _risk_flag(
                code="chargebacks_open",
                plan_id=plan_id,
                severity="high",
                title="Open chargeback or dispute needs human review",
                detail=(
                    f"{chargebacks['open_count']} open dispute event(s) linked to this plan. "
                    "Follow the provider dispute runbook; this view never moves money."
                ),
                metric="open_chargebacks",
                value=chargebacks["open_count"],
                threshold=0,
                sample_size=max(chargebacks["count"], 1),
            )
        )

    if (
        revenue["gross_minor"] > 0
        and revenue["payments_count"] >= MIN_RATE_SAMPLE
        and chargebacks["count"] > 0
        and chargebacks["amount_rate_pct"] >= CHARGEBACK_RATE_WARN_PCT
    ):
        flags.append(
            _risk_flag(
                code="chargeback_rate_high",
                plan_id=plan_id,
                severity="high",
                title="Chargeback amount is above the advisory threshold",
                detail=(
                    f"Chargebacks are {chargebacks['amount_rate_pct']:.2f}% of gross plan "
                    "revenue in the window. Review provider evidence and account history."
                ),
                metric="chargeback_rate_pct",
                value=chargebacks["amount_rate_pct"],
                threshold=CHARGEBACK_RATE_WARN_PCT,
                sample_size=revenue["payments_count"],
            )
        )

    return flags


def build_plan_health(
    *,
    subscriptions: Iterable[SubscriptionRow],
    payments: Iterable[PaymentRow],
    refunds: Iterable[RefundRow],
    renewal_events: Iterable[RenewalEventRow],
    chargebacks: Iterable[ChargebackRow],
    lifetime_sales: int,
    lifetime_refunds: int,
    now: datetime,
    window_days: int,
    currency: str,
    rows_truncated: bool = False,
    unlinked_chargebacks: int = 0,
) -> dict[str, Any]:
    """Assemble the aggregate-only plan health response."""

    now = _as_utc(now) or datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    subs = list(subscriptions)
    payment_rows = list(payments)
    refund_rows = list(refunds)
    renewals = list(renewal_events)
    chargeback_rows = list(chargebacks)

    plan_payloads: dict[str, Any] = {}
    all_flags: list[dict[str, Any]] = []
    for plan_id in PLANS:
        plan_subs = [row for row in subs if row.plan_id == plan_id]
        active = [row for row in plan_subs if _is_active(row, now)]
        created = [
            row
            for row in plan_subs
            if _in_window(row.created_at, start, now) and row.status not in NON_ACQUISITION_STATUSES
        ]
        cancelled = [row for row in plan_subs if _in_window(row.cancelled_at, start, now)]

        plan_payments = [
            row
            for row in payment_rows
            if row.plan_id == plan_id
            and row.status in SETTLED_PAYMENT_STATUSES
            and _in_window(row.created_at, start, now)
        ]
        gross_minor = sum(int(row.amount or 0) for row in plan_payments)

        plan_refunds = [row for row in refund_rows if row.plan_id == plan_id and _in_window(row.created_at, start, now)]
        succeeded_refunds = [row for row in plan_refunds if row.status == "succeeded"]
        refunded_minor = sum(int(row.amount or 0) for row in succeeded_refunds)
        net_minor = gross_minor - refunded_minor
        refund_amount_rate = _pct(refunded_minor, gross_minor)

        plan_chargebacks = [row for row in chargeback_rows if row.plan_id == plan_id]
        chargeback_amount = sum(int(row.amount or 0) for row in plan_chargebacks)
        open_chargebacks = sum(1 for row in plan_chargebacks if row.status == "open")

        plan_renewal_events = [
            row for row in renewals if row.plan_id == plan_id and _in_window(row.effective_at, start, now)
        ]
        renewal_subscriptions = {row.subscription_id for row in plan_renewal_events}
        cancellation_count = len(cancelled)
        renewal_decisions = len(renewal_subscriptions) + cancellation_count
        renewal_rate = _pct(len(renewal_subscriptions), renewal_decisions)
        churn_base = len(active) + cancellation_count
        churn_rate = _pct(cancellation_count, churn_base)

        metrics: dict[str, Any] = {
            "plan_id": plan_id,
            "interval": "week" if plan_id == "weekly" else "lifetime",
            "active_subscriptions": len(active),
            "past_due_subscriptions": sum(1 for row in active if row.status in {"past_due", "on_hold"}),
            "new_subscriptions": len(created),
            "cancelled_subscriptions": cancellation_count,
            "refunded_subscriptions": sum(1 for row in plan_subs if row.status == "refunded"),
            "by_status": _status_counts(plan_subs),
            "revenue": {
                "currency": currency,
                "gross_minor": gross_minor,
                "gross": _minor_to_amount(gross_minor),
                "refunded_minor": refunded_minor,
                "refunded": _minor_to_amount(refunded_minor),
                "net_minor": net_minor,
                "net": _minor_to_amount(net_minor),
                "payments_count": len(plan_payments),
            },
            "refunds": {
                "currency": currency,
                "count": len(succeeded_refunds),
                "amount_minor": refunded_minor,
                "amount": _minor_to_amount(refunded_minor),
                "amount_rate_pct": refund_amount_rate,
                "by_status": [
                    {"status": status, "count": count}
                    for status, count in sorted(
                        (
                            (status, sum(1 for row in plan_refunds if row.status == status))
                            for status in {row.status for row in plan_refunds}
                        ),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
            },
            "chargebacks": {
                "currency": currency,
                "count": len(plan_chargebacks),
                "open_count": open_chargebacks,
                "amount_minor": chargeback_amount,
                "amount": _minor_to_amount(chargeback_amount),
                "amount_rate_pct": _pct(chargeback_amount, gross_minor),
            },
            "renewal": {
                "renewals": len(renewal_subscriptions),
                "cancellations": cancellation_count,
                "renewal_rate_pct": renewal_rate,
                "churn_rate_pct": churn_rate,
            },
            "retention": _cohort_rows(subs, plan_id=plan_id, now=now),
        }
        if plan_id == "lifetime":
            metrics["lifetime_sales"] = int(lifetime_sales)
            metrics["lifetime_refunds"] = int(lifetime_refunds)
            metrics["lifetime_refund_rate_pct"] = _pct(lifetime_refunds, lifetime_sales)
        else:
            metrics["lifetime_sales"] = None
            metrics["lifetime_refunds"] = None
            metrics["lifetime_refund_rate_pct"] = None

        flags = _plan_risk_flags(metrics)
        metrics["risk_flags"] = flags
        all_flags.extend(flags)
        plan_payloads[plan_id] = metrics

    checks: list[dict[str, Any]] = []
    for plan_id, metrics in plan_payloads.items():
        revenue = metrics["revenue"]
        expected_net = revenue["gross_minor"] - revenue["refunded_minor"]
        checks.extend(
            [
                {
                    "key": f"{plan_id}.net_revenue",
                    "ok": revenue["net_minor"] == expected_net,
                    "expected_minor": expected_net,
                    "actual_minor": revenue["net_minor"],
                },
                {
                    "key": f"{plan_id}.active_not_negative",
                    "ok": metrics["active_subscriptions"] >= 0,
                    "expected_minor": None,
                    "actual_minor": None,
                },
            ]
        )
        retention = metrics["retention"]
        if retention["tracked_subscriptions"]:
            checks.append(
                {
                    "key": f"{plan_id}.cohort_retention",
                    "ok": retention["retained_subscriptions"] <= retention["tracked_subscriptions"],
                    "expected_minor": None,
                    "actual_minor": None,
                }
            )

    return {
        "generated_at": now.isoformat(),
        "window_days": window_days,
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "currency": currency,
        "plans": plan_payloads,
        "risk_flags": all_flags,
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "advisory": {
            "flags_are_advisory": True,
            "requires_human_review": True,
            "automatic_refund": False,
            "automatic_downgrade": False,
            "automatic_cancellation": False,
            "automatic_grant": False,
            "customer_identifiers_included": False,
        },
        "reconciliation": {
            "balanced": all(check["ok"] for check in checks),
            "checks": checks,
            "scanned_subscriptions": len(subs),
            "scanned_payments": len(payment_rows),
            "scanned_refunds": len(refund_rows),
            "rows_truncated": rows_truncated,
            "unlinked_chargebacks": unlinked_chargebacks,
        },
        "notes": [
            "Weekly and lifetime counts come from subscriptions; revenue and refunds "
            "are joined to those subscriptions so the totals reconcile to the billing ledger.",
            "Lifetime refund rate is refunded lifetime purchases divided by settled "
            "lifetime purchases. A fully refunded lifetime subscription is terminal and "
            "is excluded from active access.",
            "Weekly renewals come from the append-only subscription_history ledger. "
            "Churn compares window cancellations with the current active base.",
            "Monthly cohorts with fewer than five distinct users are suppressed and not "
            "returned. No email, name, account id, provider payload or document content "
            "is selected by this report.",
            "Risk flags are advisory only and require human review. This view never "
            "refunds, downgrades, cancels or grants access automatically.",
        ],
    }


async def _fetch_subscriptions(db: AsyncSession) -> tuple[list[SubscriptionRow], bool]:
    stmt = (
        select(
            Subscription.id,
            Subscription.user_id,
            Subscription.plan_id,
            Subscription.status,
            Subscription.created_at,
            Subscription.cancelled_at,
            Subscription.current_period_end,
        )
        .where(
            Subscription.plan_id.in_(PLANS),
            live_provider_clause(Subscription.provider),
            _live_identifier_clause(Subscription.provider_subscription_id),
        )
        .order_by(Subscription.created_at.asc())
        .limit(MAX_SCANNED_ROWS + 1)
    )
    fetched = (await db.execute(stmt)).all()
    truncated = len(fetched) > MAX_SCANNED_ROWS
    rows = [
        SubscriptionRow(
            id=str(row.id),
            user_id=str(row.user_id),
            plan_id=row.plan_id,
            status=row.status,
            created_at=row.created_at,
            cancelled_at=row.cancelled_at,
            current_period_end=row.current_period_end,
        )
        for row in fetched[:MAX_SCANNED_ROWS]
    ]
    return rows, truncated


async def _fetch_payments(db: AsyncSession, *, start: datetime, now: datetime, currency: str) -> list[PaymentRow]:
    stmt = (
        select(
            Subscription.plan_id,
            Payment.subscription_id,
            Payment.amount,
            Payment.status,
            Payment.created_at,
        )
        .join(Subscription, Subscription.id == Payment.subscription_id)
        .where(
            Payment.created_at >= start,
            Payment.created_at < now,
            Payment.status.in_(SETTLED_PAYMENT_STATUSES),
            Subscription.plan_id.in_(PLANS),
            func.upper(func.coalesce(Payment.currency, currency)) == currency,
            live_provider_clause(Payment.provider),
            live_provider_clause(Subscription.provider),
            _live_identifier_clause(Payment.provider_payment_id),
            _live_identifier_clause(Subscription.provider_subscription_id),
        )
        .order_by(Payment.created_at.asc())
        .limit(MAX_SCANNED_ROWS)
    )
    return [
        PaymentRow(
            plan_id=row.plan_id,
            subscription_id=str(row.subscription_id) if row.subscription_id else None,
            amount=int(row.amount or 0),
            status=row.status,
            created_at=row.created_at,
        )
        for row in (await db.execute(stmt)).all()
    ]


async def _fetch_refunds(db: AsyncSession, *, start: datetime, now: datetime, currency: str) -> list[RefundRow]:
    stmt = (
        select(
            Subscription.plan_id,
            Payment.subscription_id,
            PaymentRefund.amount,
            PaymentRefund.status,
            PaymentRefund.created_at,
        )
        .join(Payment, Payment.id == PaymentRefund.payment_id)
        .join(Subscription, Subscription.id == Payment.subscription_id)
        .where(
            PaymentRefund.created_at >= start,
            PaymentRefund.created_at < now,
            Subscription.plan_id.in_(PLANS),
            func.upper(func.coalesce(PaymentRefund.currency, Payment.currency, currency)) == currency,
            func.upper(func.coalesce(Payment.currency, currency)) == currency,
            live_provider_clause(PaymentRefund.provider),
            live_provider_clause(Payment.provider),
            live_provider_clause(Subscription.provider),
            _live_identifier_clause(PaymentRefund.provider_refund_id),
            _live_identifier_clause(Payment.provider_payment_id),
            _live_identifier_clause(Subscription.provider_subscription_id),
        )
        .order_by(PaymentRefund.created_at.asc())
        .limit(MAX_SCANNED_ROWS)
    )
    return [
        RefundRow(
            plan_id=row.plan_id,
            subscription_id=str(row.subscription_id) if row.subscription_id else None,
            amount=int(row.amount or 0),
            status=row.status,
            created_at=row.created_at,
        )
        for row in (await db.execute(stmt)).all()
    ]


async def _fetch_lifetime_totals(db: AsyncSession, *, currency: str) -> tuple[int, int]:
    paid = int(
        (
            await db.execute(
                select(func.count(func.distinct(Payment.subscription_id)))
                .join(Subscription, Subscription.id == Payment.subscription_id)
                .where(
                    Subscription.plan_id == "lifetime",
                    Payment.status.in_(SETTLED_PAYMENT_STATUSES),
                    func.upper(func.coalesce(Payment.currency, currency)) == currency,
                    live_provider_clause(Payment.provider),
                    live_provider_clause(Subscription.provider),
                    _live_identifier_clause(Payment.provider_payment_id),
                    _live_identifier_clause(Subscription.provider_subscription_id),
                )
            )
        ).scalar()
        or 0
    )
    refunded = int(
        (
            await db.execute(
                select(func.count(func.distinct(Payment.subscription_id)))
                .select_from(PaymentRefund)
                .join(Payment, Payment.id == PaymentRefund.payment_id)
                .join(Subscription, Subscription.id == Payment.subscription_id)
                .where(
                    PaymentRefund.status == "succeeded",
                    Subscription.plan_id == "lifetime",
                    func.upper(func.coalesce(PaymentRefund.currency, Payment.currency, currency)) == currency,
                    func.upper(func.coalesce(Payment.currency, currency)) == currency,
                    live_provider_clause(PaymentRefund.provider),
                    live_provider_clause(Payment.provider),
                    live_provider_clause(Subscription.provider),
                    _live_identifier_clause(PaymentRefund.provider_refund_id),
                    _live_identifier_clause(Payment.provider_payment_id),
                    _live_identifier_clause(Subscription.provider_subscription_id),
                )
            )
        ).scalar()
        or 0
    )
    return paid, refunded


async def _fetch_renewals(db: AsyncSession, *, start: datetime, now: datetime) -> list[RenewalEventRow]:
    stmt = (
        select(
            SubscriptionHistory.plan_id,
            SubscriptionHistory.subscription_id,
            SubscriptionHistory.effective_at,
        )
        .where(
            SubscriptionHistory.plan_id == "weekly",
            SubscriptionHistory.event_type.in_(("renewed", "period_updated")),
            SubscriptionHistory.effective_at >= start,
            SubscriptionHistory.effective_at < now,
        )
        .limit(MAX_SCANNED_ROWS)
    )
    return [
        RenewalEventRow(
            plan_id=row.plan_id,
            subscription_id=str(row.subscription_id) if row.subscription_id else "",
            effective_at=row.effective_at,
        )
        for row in (await db.execute(stmt)).all()
        if row.subscription_id is not None
    ]


def _dispute_status(event_type: str) -> str:
    suffix = str(event_type or "").lower().rsplit(".", 1)[-1].replace("-", "_")
    if suffix in {"lost", "expired", "accepted"}:
        return "lost"
    if suffix in {"won", "reversed", "reversal"}:
        return "won"
    if suffix in {
        "opened",
        "open",
        "created",
        "needs_response",
        "warning_needs_response",
        "under_review",
        "challenged",
        "pending",
    }:
        return "open"
    if suffix in {"closed", "resolved", "cancelled", "canceled"}:
        return "resolved"
    return suffix[:32] or "unknown"


async def _fetch_chargebacks(
    db: AsyncSession, *, start: datetime, now: datetime, currency: str
) -> tuple[list[ChargebackRow], int]:
    lowered = func.lower(func.coalesce(BillingWebhookEvent.event_type, ""))
    rows = (
        await db.execute(
            select(
                BillingWebhookEvent.id,
                BillingWebhookEvent.event_type,
                BillingWebhookEvent.event_resource_id,
                BillingWebhookEvent.received_at,
            )
            .where(
                BillingWebhookEvent.received_at >= start,
                BillingWebhookEvent.received_at < now,
                live_provider_clause(BillingWebhookEvent.provider),
                _live_identifier_clause(BillingWebhookEvent.event_id),
                or_(*(lowered.like(f"%{marker}%") for marker in DISPUTE_EVENT_MARKERS)),
            )
            .order_by(BillingWebhookEvent.received_at.asc(), BillingWebhookEvent.id.asc())
            .limit(MAX_SCANNED_ROWS)
        )
    ).all()

    resource_ids = {row.event_resource_id for row in rows if row.event_resource_id}
    payments_by_key: dict[str, Any] = {}
    subscriptions_by_key: dict[str, Any] = {}
    if resource_ids:
        uuid_resources = []
        for value in resource_ids:
            try:
                from uuid import UUID

                UUID(str(value))
                uuid_resources.append(value)
            except (TypeError, ValueError):
                continue
        payment_conditions = [Payment.provider_payment_id.in_(resource_ids)]
        if uuid_resources:
            payment_conditions.append(Payment.id.in_(uuid_resources))
        payment_rows = (
            await db.execute(
                select(
                    Payment.id,
                    Payment.provider_payment_id,
                    Payment.amount,
                    Payment.currency,
                    Payment.subscription_id,
                    Subscription.plan_id,
                )
                .join(Subscription, Subscription.id == Payment.subscription_id)
                .where(
                    or_(*payment_conditions),
                    Subscription.plan_id.in_(PLANS),
                    live_provider_clause(Payment.provider),
                    live_provider_clause(Subscription.provider),
                    _live_identifier_clause(Payment.provider_payment_id),
                    _live_identifier_clause(Subscription.provider_subscription_id),
                )
            )
        ).all()
        for row in payment_rows:
            for key in (str(row.provider_payment_id) if row.provider_payment_id else None, str(row.id)):
                if key:
                    payments_by_key[key] = row
        subscription_rows = (
            await db.execute(
                select(Subscription.id, Subscription.plan_id).where(
                    Subscription.id.in_([value for value in resource_ids if value in uuid_resources]),
                    Subscription.plan_id.in_(PLANS),
                    live_provider_clause(Subscription.provider),
                    _live_identifier_clause(Subscription.provider_subscription_id),
                )
            )
        ).all()
        for row in subscription_rows:
            subscriptions_by_key[str(row.id)] = row

    latest: dict[str, dict[str, Any]] = {}
    unlinked = 0
    for row in rows:
        resource = row.event_resource_id or ""
        payment = payments_by_key.get(resource)
        subscription = subscriptions_by_key.get(resource)
        plan_id = payment.plan_id if payment is not None else (subscription.plan_id if subscription else None)
        received = _as_utc(row.received_at) or now
        item = {
            "resource": resource or f"event:{row.id}",
            "plan_id": plan_id,
            "status": _dispute_status(row.event_type),
            "amount": (
                int(payment.amount) if payment is not None and str(payment.currency or "").upper() == currency else None
            ),
            "received_at": received,
        }
        if plan_id is None:
            unlinked += 1
            continue
        current = latest.get(item["resource"])
        if current is None or item["received_at"] >= current["received_at"]:
            latest[item["resource"]] = item

    return (
        [
            ChargebackRow(
                plan_id=item["plan_id"],
                status=item["status"],
                amount=item["amount"],
                received_at=item["received_at"],
            )
            for item in latest.values()
        ],
        unlinked,
    )


async def plan_health_snapshot(
    db: AsyncSession,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return aggregate weekly/lifetime plan health for the admin view."""

    generated_at = _as_utc(now) or datetime.now(timezone.utc)
    window_days = max(1, min(int(days), 365))
    start = generated_at - timedelta(days=window_days)
    currency = (settings.BILLING_CURRENCY or "INR").strip().upper()

    subscriptions, truncated = await _fetch_subscriptions(db)
    payments = await _fetch_payments(db, start=start, now=generated_at, currency=currency)
    refunds = await _fetch_refunds(db, start=start, now=generated_at, currency=currency)
    lifetime_sales, lifetime_refunds = await _fetch_lifetime_totals(db, currency=currency)
    renewals = await _fetch_renewals(db, start=start, now=generated_at)
    chargebacks, unlinked = await _fetch_chargebacks(db, start=start, now=generated_at, currency=currency)

    return build_plan_health(
        subscriptions=subscriptions,
        payments=payments,
        refunds=refunds,
        renewal_events=renewals,
        chargebacks=chargebacks,
        lifetime_sales=lifetime_sales,
        lifetime_refunds=lifetime_refunds,
        now=generated_at,
        window_days=window_days,
        currency=currency,
        rows_truncated=truncated,
        unlinked_chargebacks=unlinked,
    )


async def collect_alert_signals(
    db: AsyncSession,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return advisory plan-health alert signals; never mutates billing state."""

    snapshot = await plan_health_snapshot(db, now=now)
    signals: list[dict[str, Any]] = []
    for flag in snapshot["risk_flags"]:
        if flag["severity"] not in {"critical", "high"}:
            continue
        if flag["sample_size"] < MIN_RATE_SAMPLE and flag["code"] != "chargebacks_open":
            continue
        signals.append(
            {
                "kind": "billing.plan_health",
                "severity": flag["severity"],
                "owner": "Billing",
                "title": flag["title"],
                "dedupe_key": f"billing.plan_health.{flag['plan_id']}.{flag['code']}",
                "payload": {
                    "plan_id": flag["plan_id"],
                    "code": flag["code"],
                    "metric": flag["metric"],
                    "value": flag["value"],
                    "threshold": flag["threshold"],
                    "sample_size": flag["sample_size"],
                    "advisory": True,
                    "requires_human_review": True,
                    "auto_action": "none",
                },
                "runbook_url": RUNBOOK_URL,
            }
        )
    return signals[:MAX_ALERT_SIGNALS]

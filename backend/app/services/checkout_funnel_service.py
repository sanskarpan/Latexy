"""Server-authoritative checkout funnel and normalized failure reasons.

The funnel is derived from first-party checkout intents (``subscriptions``)
and the ``payments`` and ``billing_webhook_events`` rows linked to those
intents. It never reads a document, a customer email, a provider payload, or a
provider credential, and every response is aggregate-only.

Counts reconcile by construction:

* ``started`` counts every local checkout intent created in the window.
* ``completed`` counts intents where the provider issued a checkout session or
  subscription identifier (or a payment already settled).
* ``paid`` counts intents with a settled payment or a paid subscription state.
* Every started intent that has not paid is assigned exactly one failure
  bucket, so ``started == paid + failures.total``.

Duplicate webhook deliveries share the provider's unique ``event_id`` and are
deduplicated per checkout intent; paid conversion is counted per intent, not
per payment row, so a duplicated payment event cannot double-count.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..database import models

Subscription = models.Subscription
Payment = models.Payment
BillingWebhookEvent = models.BillingWebhookEvent

MIN_SEGMENT_SIZE = 5
ABANDONMENT_HOURS = 24
MAX_RESOURCE_IDS_PER_QUERY = 500

# Mirrors payment_service.PAID_SUBSCRIPTION_STATUSES while keeping this
# read-only service independent of provider construction.
PAID_SUBSCRIPTION_STATUSES = frozenset({"active", "cancel_scheduled", "past_due", "on_hold", "paused"})
SETTLED_PAYMENT_STATUSES = frozenset({"paid", "captured", "partially_refunded", "refunded", "succeeded"})
FAILED_PAYMENT_STATUSES = frozenset({"failed", "cancelled", "declined", "error"})
FAILURE_EVENT_TYPES = frozenset({"payment.failed", "payment.cancelled", "subscription.failed"})

_PRODUCT_KEYS = (
    "BASIC_MONTHLY",
    "BASIC_ANNUAL",
    "PRO_MONTHLY",
    "PRO_ANNUAL",
    "BYOK_MONTHLY",
    "BYOK_ANNUAL",
    "STUDENT",
    "TEAM",
    "WEEKLY",
    "LIFETIME",
)

FAILURE_BUCKETS: tuple[tuple[str, str, str], ...] = (
    (
        "provider_declined",
        "Provider declined",
        "The payment provider declined the charge, cancelled the payment, or ended the subscription.",
    ),
    (
        "validation",
        "Validation",
        "A quote, plan, amount, currency, product, or ownership check rejected the checkout before the provider accepted it.",
    ),
    (
        "abandoned",
        "Abandoned",
        "The checkout was created but no payment settled before the abandonment window.",
    ),
    (
        "unavailable",
        "Provider unavailable",
        "The provider was unreachable, timed out, or returned a transient server error.",
    ),
    (
        "unknown",
        "Unknown",
        "The checkout is still in progress or ended without enough first-party evidence to classify it.",
    ),
)

# Provider lookup/transient failures take precedence over the generic
# "invalid" wording because ``invalid_checkout_session`` is an availability
# outcome in payment_service, not a buyer validation error.
_UNAVAILABLE_RE = re.compile(
    r"provider[_ ]unavailable|invalid[_ ]checkout[_ ]session|time(?:d)?[ _-]?out|timeout|network|"
    r"connection|bad gateway|service unavailable|gateway timeout|temporar|try again|"
    r"provider lookup failed|\b5\d\d\b|overload|unreachable",
    re.IGNORECASE,
)
_VALIDATION_RE = re.compile(
    r"validat|does not match|mismatch|invalid|unsupported|not configured|missing|required|ownership|"
    r"amount|currency|tax|plan|product|coupon|metadata|customer|checkout session",
    re.IGNORECASE,
)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _pct(value: int, total: int) -> float:
    return round((value / total) * 100, 2) if total else 0.0


def _currency(value: str | None) -> str:
    candidate = (value or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", candidate):
        return candidate
    fallback = (settings.BILLING_CURRENCY or "INR").strip().upper()
    return fallback if re.fullmatch(r"[A-Z]{3}", fallback) else "INR"


def _chunks(values: Sequence[str], size: int = MAX_RESOURCE_IDS_PER_QUERY) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _other_mode_product_ids() -> frozenset[str]:
    """Configured product IDs that belong to the inactive billing mode.

    Production runs in live mode; rows created against sandbox products must
    never inflate live revenue funnels (and a test-mode environment should not
    mix live products into its local analytics). Empty configuration means
    there is nothing to exclude.
    """
    other_mode = "LIVE" if settings.normalized_dodo_mode == "test" else "TEST"
    values = {
        str(getattr(settings, f"DODO_{other_mode}_PRODUCT_{key}", "") or "").strip()
        for key in _PRODUCT_KEYS
    }
    return frozenset(value for value in values if value)


@dataclass
class _PaymentSignal:
    provider_payment_id: str | None
    status: str
    amount_minor: int
    currency: str | None
    created_at: datetime | None


@dataclass
class _WebhookSignal:
    event_key: str
    event_type: str
    status: str
    last_error: str | None
    last_reconcile_error: str | None


@dataclass
class _Attempt:
    id: str
    plan_id: str
    status: str
    created_at: datetime
    provider_checkout_session_id: str | None
    provider_subscription_id: str | None
    provider_product_id: str | None
    payments: list[_PaymentSignal] = field(default_factory=list)
    webhooks: list[_WebhookSignal] = field(default_factory=list)
    _webhook_keys: set[str] = field(default_factory=set)

    def add_webhook(self, signal: _WebhookSignal) -> None:
        if signal.event_key in self._webhook_keys:
            return
        self._webhook_keys.add(signal.event_key)
        self.webhooks.append(signal)

    @property
    def completed(self) -> bool:
        return bool(
            self.provider_checkout_session_id
            or self.provider_subscription_id
            or self.paid
        )

    @property
    def paid(self) -> bool:
        if self.status in PAID_SUBSCRIPTION_STATUSES:
            return True
        return any(payment.status in SETTLED_PAYMENT_STATUSES for payment in self.payments)


def classify_failure(
    *,
    status: str,
    has_completed_checkout: bool,
    age_seconds: float,
    webhook_types: Iterable[str] = (),
    error_texts: Iterable[str] = (),
    has_failed_payment: bool = False,
) -> str:
    """Map every unpaid checkout to exactly one normalized failure bucket.

    ``has_failed_payment`` is an explicit provider decline. Otherwise the
    most specific webhook evidence wins: transient availability outcomes,
    then deterministic validation/ownership mismatches, then a failed or
    cancelled provider event. A local intent that failed before the provider
    issued a checkout is a validation outcome; one that failed after the
    provider accepted the checkout is a provider decline. Attempts with no
    evidence are abandoned once past the abandonment window, otherwise
    unknown (still in progress or unclassified).
    """

    if has_failed_payment:
        return "provider_declined"

    text = " ".join(value for value in error_texts if value).strip()
    if text and _UNAVAILABLE_RE.search(text):
        return "unavailable"
    if text and _VALIDATION_RE.search(text):
        return "validation"

    types = {str(event_type or "").strip().lower() for event_type in webhook_types}
    if any(event_type in FAILURE_EVENT_TYPES or event_type.endswith((".failed", ".cancelled")) for event_type in types):
        return "provider_declined"

    normalized_status = (status or "").strip().lower()
    if normalized_status == "checkout_unknown":
        return "unavailable"
    if normalized_status == "failed":
        return "provider_declined" if has_completed_checkout else "validation"
    if age_seconds >= ABANDONMENT_HOURS * 3_600:
        return "abandoned"
    return "unknown"


class CheckoutFunnelService:
    async def funnel(
        self,
        db: AsyncSession,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if type(days) is not int or days < 1 or days > 365:
            raise ValueError("The checkout funnel range must be between 1 and 365 days")

        generated_at = datetime.now(timezone.utc)
        period_end = _as_utc(now) or generated_at
        period_start = period_end - timedelta(days=days)

        rows = (
            await db.execute(
                select(
                    Subscription.id,
                    Subscription.plan_id,
                    Subscription.status,
                    Subscription.created_at,
                    Subscription.provider_checkout_session_id,
                    Subscription.provider_subscription_id,
                    Subscription.provider_product_id,
                )
                .where(
                    Subscription.created_at >= period_start,
                    Subscription.created_at <= period_end,
                )
                .order_by(Subscription.created_at.asc())
            )
        ).all()

        excluded_products = _other_mode_product_ids()
        excluded_attempts = 0
        attempts: list[_Attempt] = []
        for row in rows:
            if row.provider_product_id and row.provider_product_id in excluded_products:
                excluded_attempts += 1
                continue
            created_at = _as_utc(row.created_at) or period_end
            attempts.append(
                _Attempt(
                    id=str(row.id),
                    plan_id=str(row.plan_id or "unknown"),
                    status=str(row.status or "").strip().lower(),
                    created_at=created_at,
                    provider_checkout_session_id=row.provider_checkout_session_id,
                    provider_subscription_id=row.provider_subscription_id,
                    provider_product_id=row.provider_product_id,
                )
            )

        await self._attach_payments(db, attempts)
        await self._attach_webhooks(db, attempts, period_start=period_start, period_end=period_end)

        started = len(attempts)
        completed = 0
        paid = 0
        completed_not_paid = 0
        bucket_counts = {key: 0 for key, _label, _description in FAILURE_BUCKETS}
        plan_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"started": 0, "completed": 0, "paid": 0, "failed": 0}
        )
        amount_by_currency: dict[str, dict[str, int]] = defaultdict(
            lambda: {"amount_minor": 0, "checkouts": 0}
        )

        for attempt in attempts:
            attempt_paid = attempt.paid
            attempt_completed = attempt.completed
            stats = plan_stats[attempt.plan_id]
            stats["started"] += 1

            if attempt_completed:
                completed += 1
                stats["completed"] += 1

            if attempt_paid:
                paid += 1
                stats["paid"] += 1
                first_settled = self._first_settled_payment(attempt)
                if first_settled is not None:
                    currency = _currency(first_settled.currency)
                    amount_minor = max(0, int(first_settled.amount_minor or 0))
                    amount_by_currency[currency]["amount_minor"] += amount_minor
                    amount_by_currency[currency]["checkouts"] += 1
                continue

            if attempt_completed:
                completed_not_paid += 1
            stats["failed"] += 1
            bucket = classify_failure(
                status=attempt.status,
                has_completed_checkout=attempt_completed,
                age_seconds=max(0.0, (period_end - attempt.created_at).total_seconds()),
                webhook_types=[signal.event_type for signal in attempt.webhooks],
                error_texts=[
                    value
                    for signal in attempt.webhooks
                    for value in (signal.last_error, signal.last_reconcile_error)
                    if value
                ],
                has_failed_payment=any(
                    payment.status in FAILED_PAYMENT_STATUSES for payment in attempt.payments
                ),
            )
            bucket_counts[bucket] += 1

        failure_total = started - paid
        failure_sum = sum(bucket_counts.values())
        buckets = [
            {
                "bucket": key,
                "label": label,
                "description": description,
                "count": bucket_counts[key],
                "share": _pct(bucket_counts[key], failure_total),
            }
            for key, label, description in FAILURE_BUCKETS
        ]

        step_labels = (
            ("checkout_started", "Checkout started"),
            ("checkout_completed", "Provider checkout created"),
            ("checkout_paid", "Paid"),
        )
        counts = (started, completed, paid)
        steps: list[dict[str, Any]] = []
        previous = started
        for index, ((key, label), count) in enumerate(zip(step_labels, counts)):
            if index == 0:
                drop_off = 0
                drop_off_pct = 0.0
                from_previous = 100.0 if started else 0.0
            else:
                drop_off = max(previous - count, 0)
                drop_off_pct = _pct(drop_off, previous)
                from_previous = _pct(count, previous)
            steps.append(
                {
                    "key": key,
                    "label": label,
                    "count": count,
                    "from_previous": from_previous,
                    "from_start": _pct(count, started),
                    "drop_off": drop_off,
                    "drop_off_pct": drop_off_pct,
                }
            )
            previous = count

        segments = []
        suppressed_segments = 0
        for plan_id, stats in sorted(plan_stats.items()):
            if stats["started"] < MIN_SEGMENT_SIZE:
                suppressed_segments += 1
                continue
            segments.append(
                {
                    "plan_id": plan_id,
                    "started": stats["started"],
                    "completed": stats["completed"],
                    "paid": stats["paid"],
                    "failed": stats["failed"],
                    "conversion_pct": _pct(stats["paid"], stats["started"]),
                }
            )

        return {
            "range_days": days,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "generated_at": generated_at.isoformat(),
            "billing_mode": settings.normalized_dodo_mode,
            "currency": _currency(settings.BILLING_CURRENCY),
            "minimum_segment_size": MIN_SEGMENT_SIZE,
            "abandonment_hours": ABANDONMENT_HOURS,
            "steps": steps,
            "conversion": {
                "started_to_completed": _pct(completed, started),
                "completed_to_paid": _pct(paid, completed),
                "started_to_paid": _pct(paid, started),
            },
            "failures": {
                "total": failure_total,
                "buckets": buckets,
            },
            "reconciliation": {
                "started": started,
                "completed": completed,
                "paid": paid,
                "failed": failure_total,
                "completed_not_paid": completed_not_paid,
                "failure_bucket_sum": failure_sum,
                "started_equals_paid_plus_failed": started == paid + failure_total,
                "completed_at_least_paid": completed >= paid,
                "failure_buckets_match": failure_sum == failure_total,
            },
            "paid_amounts": [
                {
                    "currency": currency,
                    "amount_minor": values["amount_minor"],
                    "checkouts": values["checkouts"],
                }
                for currency, values in sorted(
                    amount_by_currency.items(),
                    key=lambda item: (-item[1]["amount_minor"], item[0]),
                )
            ],
            "by_plan": segments,
            "suppressed_segments": suppressed_segments,
            "excluded_other_mode_attempts": excluded_attempts,
            "definitions": {
                "started": "A local checkout intent was created for a signed-in purchase request.",
                "completed": "The provider issued a checkout session or subscription identifier, or a payment settled.",
                "paid": "A settled payment exists or the subscription is in a paid state.",
                "failures": "Every started checkout without a settled payment is assigned exactly one failure bucket.",
            },
            "notes": [
                "Counts are first-party rows only; duplicate provider webhook deliveries and payment rows are deduplicated per checkout intent.",
                "Failure reasons cover every started checkout that has not settled a payment; no raw provider errors are returned.",
                "Segments with fewer than 5 started checkouts are suppressed; no user, document, or provider secret is returned.",
                "Replay links are built client-side by the consent/masking-safe replay helpers; document, share, portfolio, and editor surfaces are excluded.",
            ],
        }

    @staticmethod
    def _first_settled_payment(attempt: _Attempt) -> _PaymentSignal | None:
        settled = [
            payment for payment in attempt.payments if payment.status in SETTLED_PAYMENT_STATUSES
        ]
        if not settled:
            return None
        return min(
            settled,
            key=lambda payment: (
                _as_utc(payment.created_at) or datetime.min.replace(tzinfo=timezone.utc),
                payment.provider_payment_id or "",
            ),
        )

    @staticmethod
    async def _attach_payments(db: AsyncSession, attempts: list[_Attempt]) -> None:
        if not attempts:
            return
        by_id = {attempt.id: attempt for attempt in attempts}
        ids = list(by_id)
        for chunk in _chunks(ids):
            rows = (
                await db.execute(
                    select(
                        Payment.subscription_id,
                        Payment.provider_payment_id,
                        Payment.status,
                        Payment.amount,
                        Payment.currency,
                        Payment.created_at,
                    ).where(Payment.subscription_id.in_(chunk))
                )
            ).all()
            for row in rows:
                attempt = by_id.get(str(row.subscription_id))
                if attempt is None:
                    continue
                attempt.payments.append(
                    _PaymentSignal(
                        provider_payment_id=row.provider_payment_id,
                        status=str(row.status or "").strip().lower(),
                        amount_minor=int(row.amount or 0),
                        currency=row.currency,
                        created_at=_as_utc(row.created_at),
                    )
                )

    @staticmethod
    async def _attach_webhooks(
        db: AsyncSession,
        attempts: list[_Attempt],
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> None:
        if not attempts:
            return

        resource_map: dict[str, list[_Attempt]] = defaultdict(list)
        seen_resources: set[str] = set()
        for attempt in attempts:
            for resource_id in (
                attempt.id,
                attempt.provider_checkout_session_id,
                attempt.provider_subscription_id,
                *[payment.provider_payment_id for payment in attempt.payments],
            ):
                if not resource_id or resource_id in seen_resources:
                    continue
                seen_resources.add(resource_id)
                resource_map[resource_id].append(attempt)

        # Bound the scan by receipt time; the checkout cohort cannot have a
        # webhook older than its own window, and this avoids one unindexed
        # resource-id scan per 500-intent chunk.
        rows = (
            await db.execute(
                select(
                    BillingWebhookEvent.id,
                    BillingWebhookEvent.event_id,
                    BillingWebhookEvent.event_type,
                    BillingWebhookEvent.event_resource_id,
                    BillingWebhookEvent.status,
                    BillingWebhookEvent.last_error,
                    BillingWebhookEvent.last_reconcile_error,
                ).where(
                    BillingWebhookEvent.provider == "dodo",
                    BillingWebhookEvent.received_at >= period_start,
                    BillingWebhookEvent.received_at <= period_end,
                    or_(
                        BillingWebhookEvent.status == "failed",
                        BillingWebhookEvent.event_type.in_(tuple(FAILURE_EVENT_TYPES)),
                        BillingWebhookEvent.event_type.like("%.failed"),
                        BillingWebhookEvent.event_type.like("%.cancelled"),
                        BillingWebhookEvent.last_error.is_not(None),
                        BillingWebhookEvent.last_reconcile_error.is_not(None),
                    ),
                )
            )
        ).all()
        for row in rows:
            for attempt in resource_map.get(str(row.event_resource_id), ()):
                attempt.add_webhook(
                    _WebhookSignal(
                        event_key=str(row.event_id or row.id),
                        event_type=str(row.event_type or "").strip().lower(),
                        status=str(row.status or "").strip().lower(),
                        last_error=row.last_error,
                        last_reconcile_error=row.last_reconcile_error,
                    )
                )


checkout_funnel_service = CheckoutFunnelService()

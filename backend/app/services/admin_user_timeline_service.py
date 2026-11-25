"""Per-user subscription and payment timeline for the User 360 view.

The timeline composes only allowlisted billing and operator-action rows:
subscription history, subscriptions, payments, refunds, billing webhook
receipts, admin plan changes and feature entitlement changes. It never
reads resume content, prompts, provider payloads, webhook errors, credentials
or tokens.

Support sees the billing ledger it can already read on User 360. Raw webhook
receipts and admin-audit transitions stay admin-only, so this endpoint cannot
become a second audit-log or control-room surface for support.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models

DEFAULT_TIMELINE_LIMIT = 20
MAX_TIMELINE_LIMIT = 100

ADMIN_ONLY_KINDS = frozenset({"webhook", "plan_change", "entitlement_change"})
PLAN_CHANGE_ACTION = "user.plan.change"
ENTITLEMENT_ACTIONS = (
    "user.feature.grant",
    "user.feature.revoke",
)
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9_.:@-]{1,255}$")


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _sort_at(value: datetime | None) -> datetime:
    return _as_utc(value) or datetime.min.replace(tzinfo=timezone.utc)


def _safe_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:limit] if cleaned else None


def _safe_reference(value: Any) -> str | None:
    text = _safe_text(value, limit=255)
    return text if text and _SAFE_REFERENCE.fullmatch(text) else None


def _reason_code(value: Any) -> str | None:
    text = _safe_text(value, limit=64)
    return text if text and _REASON_CODE.fullmatch(text) else None


def _bounded_page(limit: int, offset: int) -> tuple[int, int]:
    cleaned_limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_TIMELINE_LIMIT
    cleaned_offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0
    return (
        max(1, min(cleaned_limit, MAX_TIMELINE_LIMIT)),
        max(0, cleaned_offset),
    )


def _currency(value: Any) -> str:
    text = _safe_text(value, limit=3)
    return text.upper() if text else "UNKNOWN"


def _money_by_currency(
    rows: Iterable[tuple[int | None, Any]],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for amount, currency in rows:
        key = _currency(currency)
        bucket = buckets.setdefault(key, {"currency": key, "count": 0, "amount_minor": 0})
        bucket["count"] += 1
        bucket["amount_minor"] += int(amount or 0)
    return sorted(buckets.values(), key=lambda row: row["currency"])


def _status_totals(
    rows: Iterable[tuple[Any, int | None]],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for status, amount in rows:
        key = _safe_text(status, limit=24) or "unknown"
        bucket = buckets.setdefault(key, {"status": key, "count": 0, "amount_minor": 0})
        bucket["count"] += 1
        bucket["amount_minor"] += int(amount or 0)
    return sorted(buckets.values(), key=lambda row: row["status"])


def _payment_summary(status: str | None, amount: int | None, currency: str | None) -> str:
    parts = ["Payment"]
    if status:
        parts.append(status)
    if amount is not None:
        parts.append(f"{amount / 100:.2f} {_currency(currency)}")
    return " · ".join(parts)


def _refund_summary(status: str | None, amount: int | None, currency: str | None) -> str:
    parts = ["Refund"]
    if status:
        parts.append(status)
    if amount is not None:
        parts.append(f"{amount / 100:.2f} {_currency(currency)}")
    return " · ".join(parts)


def _history_summary(row: models.SubscriptionHistory) -> str:
    event = (_safe_text(row.event_type, limit=32) or "subscription change").replace("_", " ")
    if row.previous_plan_id and row.previous_plan_id != row.plan_id:
        return f"{event} · {row.previous_plan_id} → {row.plan_id}"
    return f"{event} · {row.plan_id}"


def _webhook_source(event_type: str | None) -> str:
    text = event_type or ""
    if text.startswith("payment."):
        return "payment"
    if text.startswith("subscription."):
        return "subscription"
    if text.startswith("refund."):
        return "refund"
    return "webhook"


def _webhook_clause(prefix: str, resource_ids: set[str]) -> Any | None:
    if not resource_ids:
        return None
    return and_(
        models.BillingWebhookEvent.event_type.like(f"{prefix}.%"),
        models.BillingWebhookEvent.event_resource_id.in_(sorted(resource_ids)),
    )


def _audit_details(row: models.AdminAuditLog) -> dict[str, Any]:
    """Project only bounded identifiers and booleans from a curated audit row."""
    metadata = row.event_metadata if isinstance(row.event_metadata, dict) else {}
    before = row.before_state if isinstance(row.before_state, dict) else {}
    after = row.after_state if isinstance(row.after_state, dict) else {}
    action = row.action
    details: dict[str, Any] = {}
    if action == PLAN_CHANGE_ACTION:
        details = {
            "before_plan": _safe_text(before.get("subscription_plan"), limit=50),
            "after_plan": _safe_text(after.get("subscription_plan"), limit=50),
            "before_status": _safe_text(before.get("subscription_status"), limit=50),
            "after_status": _safe_text(after.get("subscription_status"), limit=50),
        }
    elif action in {"user.feature.grant", "user.feature.revoke"}:
        details = {
            "feature_key": _safe_text(metadata.get("feature_key"), limit=120),
            "before_override": before.get("override") if isinstance(before.get("override"), bool) else None,
            "after_override": after.get("override") if isinstance(after.get("override"), bool) else None,
        }
    return details


def _audit_summary(row: models.AdminAuditLog) -> str:
    action = row.action
    details = _audit_details(row)
    if action == PLAN_CHANGE_ACTION:
        before = details.get("before_plan") or "unknown"
        after = details.get("after_plan") or "unknown"
        return f"Plan change · {before} → {after}"
    if action in {"user.feature.grant", "user.feature.revoke"}:
        feature = details.get("feature_key") or "feature"
        verb = "granted" if action.endswith("grant") else "revoked"
        return f"Entitlement {verb} · {feature}"
    return f"Trial change · {action.rsplit('.', 1)[-1].replace('_', ' ')}"


async def build_subscription_timeline(
    db: AsyncSession,
    *,
    user_id: str,
    actor_role: str,
    limit: int = DEFAULT_TIMELINE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Return one chronological page plus totals over all visible source rows.

    Items are newest-first. ``total`` always describes every visible source row,
    not just the returned page, and the money totals are summed from the same
    rows so a caller can reconcile them directly.
    """
    page_limit, page_offset = _bounded_page(limit, offset)
    is_admin = actor_role == "admin"

    subscriptions: Sequence[models.Subscription] = (
        (await db.execute(select(models.Subscription).where(models.Subscription.user_id == user_id))).scalars().all()
    )
    history: Sequence[models.SubscriptionHistory] = (
        (await db.execute(select(models.SubscriptionHistory).where(models.SubscriptionHistory.user_id == user_id)))
        .scalars()
        .all()
    )
    payments: Sequence[models.Payment] = (
        (await db.execute(select(models.Payment).where(models.Payment.user_id == user_id))).scalars().all()
    )
    refunds: Sequence[models.PaymentRefund] = (
        (
            await db.execute(
                select(models.PaymentRefund)
                .join(models.Payment, models.Payment.id == models.PaymentRefund.payment_id)
                .where(models.Payment.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )

    webhooks: Sequence[models.BillingWebhookEvent] = []
    audits: Sequence[models.AdminAuditLog] = []
    if is_admin:
        payment_resource_ids = {value for row in payments for value in (row.id, row.provider_payment_id) if value}
        subscription_resource_ids = {
            value for row in subscriptions for value in (row.id, row.provider_subscription_id) if value
        }
        refund_resource_ids = {value for row in refunds for value in (row.id, row.provider_refund_id) if value}
        clauses = [
            clause
            for clause in (
                _webhook_clause("payment", payment_resource_ids),
                _webhook_clause("subscription", subscription_resource_ids),
                _webhook_clause("refund", refund_resource_ids),
            )
            if clause is not None
        ]
        if clauses:
            webhooks = (
                (
                    await db.execute(
                        select(models.BillingWebhookEvent)
                        .where(or_(*clauses))
                        .order_by(models.BillingWebhookEvent.received_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        audits = (
            (
                await db.execute(
                    select(models.AdminAuditLog).where(
                        models.AdminAuditLog.target_type == "user",
                        models.AdminAuditLog.target_id == user_id,
                        models.AdminAuditLog.action.in_((PLAN_CHANGE_ACTION, *ENTITLEMENT_ACTIONS)),
                    )
                )
            )
            .scalars()
            .all()
        )

    events: list[tuple[datetime, str, str, dict[str, Any]]] = []

    for row in history:
        events.append(
            (
                _sort_at(row.effective_at),
                "subscription_history",
                row.id,
                {
                    "id": f"subscription_history:{row.id}",
                    "kind": "subscription_history",
                    "occurred_at": _iso(row.effective_at),
                    "summary": _history_summary(row),
                    "event_type": _safe_text(row.event_type, limit=32),
                    "source": _safe_text(row.source, limit=24),
                    "status": _safe_text(row.status, limit=50),
                    "previous_status": _safe_text(row.previous_status, limit=50),
                    "plan_id": _safe_text(row.plan_id, limit=50),
                    "previous_plan_id": _safe_text(row.previous_plan_id, limit=50),
                    "current_period_start": _iso(row.current_period_start),
                    "current_period_end": _iso(row.current_period_end),
                    "reason_code": _reason_code(row.reason),
                    "amount_minor": None,
                    "currency": None,
                    "provider": None,
                    "reference": None,
                    "admin_only": False,
                },
            )
        )

    for row in subscriptions:
        events.append(
            (
                _sort_at(row.created_at),
                "subscription",
                row.id,
                {
                    "id": f"subscription:{row.id}",
                    "kind": "subscription",
                    "occurred_at": _iso(row.created_at),
                    "summary": f"Subscription {_safe_text(row.status, limit=50) or 'unknown'} · {row.plan_id}",
                    "event_type": "subscription",
                    "source": "billing",
                    "status": _safe_text(row.status, limit=50),
                    "previous_status": None,
                    "plan_id": _safe_text(row.plan_id, limit=50),
                    "previous_plan_id": None,
                    "current_period_start": _iso(row.current_period_start),
                    "current_period_end": _iso(row.current_period_end),
                    "reason_code": None,
                    "amount_minor": int(row.quoted_amount) if row.quoted_amount is not None else None,
                    "currency": None,
                    "provider": _safe_text(row.provider, limit=32),
                    "reference": _safe_reference(row.provider_subscription_id),
                    "admin_only": False,
                },
            )
        )

    for row in payments:
        events.append(
            (
                _sort_at(row.created_at),
                "payment",
                row.id,
                {
                    "id": f"payment:{row.id}",
                    "kind": "payment",
                    "occurred_at": _iso(row.created_at),
                    "summary": _payment_summary(row.status, row.amount, row.currency),
                    "event_type": "payment",
                    "source": "billing",
                    "status": _safe_text(row.status, limit=50),
                    "previous_status": None,
                    "plan_id": None,
                    "previous_plan_id": None,
                    "current_period_start": None,
                    "current_period_end": None,
                    "reason_code": None,
                    "amount_minor": int(row.amount) if row.amount is not None else None,
                    "currency": _currency(row.currency),
                    "provider": _safe_text(row.provider, limit=32),
                    "reference": _safe_reference(row.provider_payment_id),
                    "subscription_id": row.subscription_id,
                    "payment_method": _safe_text(row.payment_method, limit=50),
                    "admin_only": False,
                },
            )
        )

    for row in refunds:
        events.append(
            (
                _sort_at(row.created_at),
                "refund",
                row.id,
                {
                    "id": f"refund:{row.id}",
                    "kind": "refund",
                    "occurred_at": _iso(row.created_at),
                    "summary": _refund_summary(row.status, row.amount, row.currency),
                    "event_type": "refund",
                    "source": "billing",
                    "status": _safe_text(row.status, limit=24),
                    "previous_status": None,
                    "plan_id": None,
                    "previous_plan_id": None,
                    "current_period_start": None,
                    "current_period_end": None,
                    "reason_code": None,
                    "amount_minor": int(row.amount) if row.amount is not None else None,
                    "currency": _currency(row.currency),
                    "provider": _safe_text(row.provider, limit=32),
                    "reference": _safe_reference(row.provider_refund_id),
                    "payment_id": row.payment_id,
                    "admin_only": False,
                },
            )
        )

    for row in webhooks:
        event_at = row.event_at or row.received_at
        events.append(
            (
                _sort_at(event_at),
                "webhook",
                row.id,
                {
                    "id": f"webhook:{row.id}",
                    "kind": "webhook",
                    "occurred_at": _iso(event_at),
                    "summary": f"{_safe_text(row.event_type, limit=120) or 'webhook'} · {row.status}",
                    "event_type": _safe_text(row.event_type, limit=120),
                    "source": _webhook_source(row.event_type),
                    "status": _safe_text(row.status, limit=24),
                    "previous_status": None,
                    "plan_id": None,
                    "previous_plan_id": None,
                    "current_period_start": None,
                    "current_period_end": None,
                    "reason_code": None,
                    "amount_minor": None,
                    "currency": None,
                    "provider": _safe_text(row.provider, limit=32),
                    "reference": _safe_reference(row.event_id),
                    "admin_only": True,
                },
            )
        )

    for row in audits:
        kind = "plan_change" if row.action == PLAN_CHANGE_ACTION else "entitlement_change"
        details = _audit_details(row)
        events.append(
            (
                _sort_at(row.created_at),
                kind,
                row.id,
                {
                    "id": f"{kind}:{row.id}",
                    "kind": kind,
                    "occurred_at": _iso(row.created_at),
                    "summary": _audit_summary(row),
                    "event_type": row.action,
                    "source": "admin",
                    "status": None,
                    "previous_status": details.get("before_status"),
                    "plan_id": details.get("after_plan"),
                    "previous_plan_id": details.get("before_plan"),
                    "current_period_start": None,
                    "current_period_end": None,
                    "reason_code": None,
                    "amount_minor": None,
                    "currency": None,
                    "provider": None,
                    "reference": None,
                    "admin_only": True,
                    "details": details,
                },
            )
        )

    events.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    items = [row[3] for row in events]
    total = len(items)
    page_items = items[page_offset : page_offset + page_limit]

    kind_counts: dict[str, int] = {}
    for item in items:
        kind_counts[item["kind"]] = kind_counts.get(item["kind"], 0) + 1
    sources = {
        "subscription_history": len(history),
        "subscriptions": len(subscriptions),
        "payments": len(payments),
        "refunds": len(refunds),
        "webhooks": len(webhooks),
        "plan_changes": sum(1 for row in audits if row.action == PLAN_CHANGE_ACTION),
        "entitlement_changes": sum(1 for row in audits if row.action != PLAN_CHANGE_ACTION),
    }
    payment_total = sum(int(row.amount or 0) for row in payments)
    paid_total = sum(
        int(row.amount or 0)
        for row in payments
        if (_safe_text(row.status, limit=50) or "").lower() in {"paid", "captured", "succeeded", "partially_refunded"}
    )
    refund_total = sum(int(row.amount or 0) for row in refunds)
    succeeded_refund_total = sum(
        int(row.amount or 0)
        for row in refunds
        if (_safe_text(row.status, limit=24) or "").lower() in {"succeeded", "completed", "processed", "refunded"}
    )

    return {
        "items": page_items,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
        "has_more": page_offset + len(page_items) < total,
        "next_offset": page_offset + len(page_items) if page_offset + len(page_items) < total else None,
        "order": "desc",
        "viewer_role": actor_role,
        "restricted_kinds": sorted(ADMIN_ONLY_KINDS) if not is_admin else [],
        "counts": kind_counts,
        "sources": sources,
        "totals": {
            "payments": {
                "count": len(payments),
                "total_minor": payment_total,
                "paid_minor": paid_total,
                "by_status": _status_totals((row.status, row.amount) for row in payments),
                "by_currency": _money_by_currency((row.amount, row.currency) for row in payments),
            },
            "refunds": {
                "count": len(refunds),
                "total_minor": refund_total,
                "succeeded_minor": succeeded_refund_total,
                "by_status": _status_totals((row.status, row.amount) for row in refunds),
                "by_currency": _money_by_currency((row.amount, row.currency) for row in refunds),
            },
            # Both reconcile directly to the source rows: gross/refunded/net use
            # every recorded row; settled_net only counts settled statuses.
            "payment_count": len(payments),
            "payment_total_minor": payment_total,
            "refund_count": len(refunds),
            "refund_total_minor": refund_total,
            "gross_minor": payment_total,
            "refunded_minor": refund_total,
            "net_minor": payment_total - refund_total,
            "settled_net_minor": paid_total - succeeded_refund_total,
        },
    }

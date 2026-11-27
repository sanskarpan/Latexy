"""Admin billing control-room queries and safe operational actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.redis import get_redis_client
from ..database import models
from . import admin_approval_service
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_revenue_service import live_provider_clause, monthly_amount, revenue_analytics
from .payment_service import payment_service

Payment = models.Payment
Subscription = models.Subscription
BillingWebhookEvent = models.BillingWebhookEvent
PaymentRefund = models.PaymentRefund
AdminRefundRequest = models.AdminRefundRequest
User = models.User


# Kept as an alias for existing imports/tests; normalization lives with the
# revenue analytics so MRR, ARPU and plan mix always share one policy.
_monthly_amount = monthly_amount


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _webhook_prefix(event_type: str) -> str:
    if event_type.startswith("payment."):
        return "payment"
    if event_type.startswith("subscription."):
        return "subscription"
    if event_type.startswith("refund."):
        return "refund"
    return "unknown"


def _webhook_row(row: BillingWebhookEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "provider": row.provider,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "event_resource_id": row.event_resource_id,
        "status": row.status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "event_at": row.event_at.isoformat() if row.event_at else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "acknowledged_by": row.acknowledged_by,
        "acknowledgement_note": row.acknowledgement_note,
        "reconcile_attempts": row.reconcile_attempts,
        "last_reconcile_at": row.last_reconcile_at.isoformat() if row.last_reconcile_at else None,
        "last_reconcile_error": row.last_reconcile_error,
        "last_reconcile_outcome": row.last_reconcile_outcome,
    }


def _refund_row(row: AdminRefundRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "payment_id": row.payment_id,
        "status": row.status,
        "request_kind": row.request_kind or "refund",
        "amount": row.amount,
        "currency": row.currency,
        "provider_item_id": row.provider_item_id,
        "tax_inclusive": bool(row.tax_inclusive),
        "reason": row.reason,
        "evidence": row.evidence,
        "decision_note": row.decision_note,
        "requested_by": row.requested_by,
        "requested_email": row.requested_email,
        "approved_by": row.approved_by,
        "approved_email": row.approved_email,
        "executed_by": row.executed_by,
        "provider_refund_id": row.provider_refund_id,
        "last_error": row.last_error,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _local_links(db: AsyncSession, rows: Iterable[BillingWebhookEvent]) -> dict[str, dict[str, Any]]:
    """Resolve local ledger links for a bounded page without N+1 queries."""
    items = list(rows)
    payment_ids = {r.event_resource_id for r in items if r.event_type.startswith("payment.") and r.event_resource_id}
    subscription_ids = {
        r.event_resource_id for r in items if r.event_type.startswith("subscription.") and r.event_resource_id
    }
    refund_ids = {r.event_resource_id for r in items if r.event_type.startswith("refund.") and r.event_resource_id}

    payments = (
        await db.execute(
            select(
                Payment.provider_payment_id,
                Payment.id,
                Payment.subscription_id,
                Payment.user_id,
                Payment.amount,
                Payment.currency,
                Payment.status,
            ).where(
                Payment.provider == "dodo", Payment.provider_payment_id.in_(payment_ids)
            )
        )
    ).all() if payment_ids else []
    subscriptions = (
        await db.execute(
            select(
                Subscription.provider_subscription_id,
                Subscription.id,
                Subscription.user_id,
                Subscription.plan_id,
                Subscription.quoted_amount,
                Subscription.status,
                Subscription.current_period_end,
            ).where(
                Subscription.provider == "dodo", Subscription.provider_subscription_id.in_(subscription_ids)
            )
        )
    ).all() if subscription_ids else []
    refunds = (
        await db.execute(
            select(
                PaymentRefund.provider_refund_id,
                PaymentRefund.id,
                PaymentRefund.payment_id,
                PaymentRefund.amount,
                PaymentRefund.currency,
                PaymentRefund.status,
            ).where(
                PaymentRefund.provider == "dodo", PaymentRefund.provider_refund_id.in_(refund_ids)
            )
        )
    ).all() if refund_ids else []

    result: dict[str, dict[str, Any]] = {}
    for provider_id, local_id, subscription_id, user_id, amount, currency, status in payments:
        result[f"payment:{provider_id}"] = {
            "linked": True, "local_type": "payment", "local_id": local_id,
            "subscription_id": subscription_id, "user_id": user_id,
            "amount_minor": amount, "currency": currency, "status": status,
        }
    for provider_id, local_id, user_id, plan_id, amount, status, period_end in subscriptions:
        result[f"subscription:{provider_id}"] = {
            "linked": True, "local_type": "subscription", "local_id": local_id, "user_id": user_id,
            "plan_id": plan_id, "amount_minor": amount, "status": status,
            "current_period_end": period_end.isoformat() if period_end else None,
        }
    for provider_id, local_id, payment_id, amount, currency, status in refunds:
        result[f"refund:{provider_id}"] = {
            "linked": True, "local_type": "refund", "local_id": local_id, "payment_id": payment_id,
            "amount_minor": amount, "currency": currency, "status": status,
        }
    for row in items:
        prefix = _webhook_prefix(row.event_type)
        key = f"{prefix}:{row.event_resource_id}"
        if key not in result:
            result[key] = {"linked": False, "local_type": prefix, "local_id": None, "status": None}
    return result


def _reconciliation_diagnosis(
    row: BillingWebhookEvent, link: dict[str, Any]
) -> tuple[str, str, str | None]:
    """Return (mismatch_reason, suggested_action, link_status) from bounded local state."""
    linked = bool(link.get("linked"))
    local_type = str(link.get("local_type") or _webhook_prefix(row.event_type))
    status = str(link.get("status") or "").lower() or None
    if not linked:
        reason = (
            f"No local {local_type} intent is linked to provider resource "
            f"{row.event_resource_id or '(missing)'}."
        )
        action = "Review the provider event; acknowledge only if it is provider-side traffic."
        return reason, action, None
    if local_type == "payment":
        if status in {"paid", "partially_refunded", "captured", "succeeded"}:
            return (
                "The local payment is already settled; this failure is likely a duplicate or out-of-order event.",
                "Replay to prove idempotency, then acknowledge.",
                status,
            )
        if status == "refunded":
            return (
                "The local payment is already fully refunded.",
                "Verify the provider settlement, then acknowledge instead of replaying.",
                status,
            )
        if status in {"failed", "cancelled"}:
            return (
                f"The local payment is terminal ({status}).",
                "Review the provider state; replay only if the provider now reports a recoverable state.",
                status,
            )
        return (
            f"The local payment is still {status or 'in an unknown state'}.",
            "Replay the provider resource to reconcile the ledger, or acknowledge after review.",
            status,
        )
    if local_type == "subscription":
        if status in {"active", "cancel_scheduled", "past_due", "on_hold", "paused"}:
            return (
                f"The local subscription already records {status}; the failed event may be stale or out of order.",
                "Replay to confirm idempotency, or acknowledge the stale event.",
                status,
            )
        if status in {"cancelled", "expired", "failed", "refunded"}:
            return (
                f"The local subscription is terminal ({status}).",
                "Verify the provider subscription before acknowledging or replaying.",
                status,
            )
        return (
            f"The local subscription is {status or 'in an unknown state'}.",
            "Replay the provider resource to reconcile the subscription.",
            status,
        )
    if local_type == "refund":
        if status == "succeeded":
            return (
                "The local refund is already settled; the failed event is likely a duplicate.",
                "Acknowledge after verifying the settled refund; replay is idempotent but unnecessary.",
                status,
            )
        if status == "failed":
            return (
                "The local refund is marked failed.",
                "Replay the provider refund before any new attempt; never resubmit blindly.",
                status,
            )
        return (
            f"The local refund is still {status or 'in an unknown state'}.",
            "Replay the provider refund to reconcile the ledger.",
            status,
        )
    return (
        row.last_error or "The failed event is not linked to a supported local billing record.",
        "Review the provider event and acknowledge or replay if it maps to a local record.",
        status,
    )


class AdminBillingService:
    async def summary(
        self,
        db: AsyncSession,
        days: int = 30,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        currency: str | None = None,
        granularity: str = "day",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        period_end = _as_utc(end) or now
        period_start = _as_utc(start) or (period_end - timedelta(days=days))
        if period_start > period_end:
            raise ValueError("The summary start must not be after the end")
        if start is not None and end is not None:
            window_seconds = max(0, int((period_end - period_start).total_seconds()))
            period_days = max(1, (window_seconds + 86_399) // 86_400)
        else:
            period_days = days
        analytics = await revenue_analytics(
            db,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            granularity=granularity,
            now=now,
        )
        open_refunds = int(
            (
                await db.execute(
                    select(func.count()).select_from(AdminRefundRequest).where(
                        AdminRefundRequest.status.in_(("pending", "approved", "executing"))
                    )
                )
            ).scalar_one()
        )
        live_webhooks = live_provider_clause(BillingWebhookEvent.provider)
        unacknowledged_failures = int(
            (
                await db.execute(
                    select(func.count()).select_from(BillingWebhookEvent).where(
                        BillingWebhookEvent.status == "failed",
                        BillingWebhookEvent.acknowledged_at.is_(None),
                        live_webhooks,
                    )
                )
            ).scalar_one()
        )
        webhook_24h = int(
            (
                await db.execute(
                    select(func.count()).select_from(BillingWebhookEvent).where(
                        BillingWebhookEvent.received_at >= now - timedelta(hours=24),
                        live_webhooks,
                    )
                )
            ).scalar_one()
        )
        webhook_failed_24h = int(
            (
                await db.execute(
                    select(func.count()).select_from(BillingWebhookEvent).where(
                        BillingWebhookEvent.status == "failed",
                        BillingWebhookEvent.received_at >= now - timedelta(hours=24),
                        live_webhooks,
                    )
                )
            ).scalar_one()
        )
        recent_refunds = (
            await db.execute(
                select(AdminRefundRequest).order_by(AdminRefundRequest.requested_at.desc()).limit(8)
            )
        ).scalars().all()
        mrr_minor = int(analytics["mrr_minor"])
        arpu_minor = int(analytics["arpu_minor"])
        net_minor = int(analytics["net_revenue_minor"])
        response = {
            "period_days": period_days,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "generated_at": now.isoformat(),
            **analytics,
            "mrr": round(mrr_minor / 100, 2),
            "arr": round(mrr_minor * 12 / 100, 2),
            "arpu": round(arpu_minor / 100, 2),
            "gross_revenue": round(int(analytics["gross_revenue_minor"]) / 100, 2),
            "refunded": round(int(analytics["refunded_minor"]) / 100, 2),
            "refunds": round(int(analytics["refunded_minor"]) / 100, 2),
            "refunds_minor": int(analytics["refunded_minor"]),
            "net_revenue": round(net_minor / 100, 2),
            "chargebacks": round(int(analytics["chargebacks_minor"]) / 100, 2),
            "net_revenue_after_chargebacks": round(
                int(analytics["net_revenue_after_chargebacks_minor"]) / 100, 2
            ),
            "open_refund_requests": open_refunds,
            "unacknowledged_webhook_failures": unacknowledged_failures,
            "webhooks_24h": webhook_24h,
            "webhook_failures_24h": webhook_failed_24h,
            "recent_refund_requests": [_refund_row(row) for row in recent_refunds],
        }
        return response

    async def list_webhooks(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        event_type: str | None = None,
        acknowledged: bool | None = None,
        received_after: datetime | None = None,
        received_before: datetime | None = None,
        dead_letter: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = []
        after = _as_utc(received_after)
        before = _as_utc(received_before)
        if after is not None and before is not None and after > before:
            raise ValueError("received_after must not be later than received_before")
        if status:
            filters.append(BillingWebhookEvent.status == status)
        if event_type:
            filters.append(BillingWebhookEvent.event_type == event_type)
        if acknowledged is True:
            filters.append(BillingWebhookEvent.acknowledged_at.is_not(None))
        elif acknowledged is False:
            filters.append(BillingWebhookEvent.acknowledged_at.is_(None))
        if after is not None:
            filters.append(BillingWebhookEvent.received_at >= after)
        if before is not None:
            filters.append(BillingWebhookEvent.received_at <= before)
        if dead_letter is True:
            filters.append(BillingWebhookEvent.status == "failed")
            filters.append(BillingWebhookEvent.acknowledged_at.is_(None))
        elif dead_letter is False:
            filters.append(
                or_(
                    BillingWebhookEvent.status != "failed",
                    BillingWebhookEvent.acknowledged_at.is_not(None),
                )
            )
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(
                or_(
                    BillingWebhookEvent.event_id.ilike(pattern),
                    BillingWebhookEvent.event_type.ilike(pattern),
                    BillingWebhookEvent.event_resource_id.ilike(pattern),
                    BillingWebhookEvent.last_error.ilike(pattern),
                )
            )
        base = select(BillingWebhookEvent)
        count_stmt = select(func.count()).select_from(BillingWebhookEvent)
        for condition in filters:
            base = base.where(condition)
            count_stmt = count_stmt.where(condition)
        total = int((await db.execute(count_stmt)).scalar_one())
        rows = list(
            (
                await db.execute(
                    base.order_by(BillingWebhookEvent.received_at.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
        )
        links = await _local_links(db, rows)
        result = []
        for row in rows:
            prefix = _webhook_prefix(row.event_type)
            item = _webhook_row(row)
            item["local_link"] = links.get(f"{prefix}:{row.event_resource_id}", {
                "linked": False, "local_type": prefix, "local_id": None, "status": None,
            })
            result.append(item)
        return result, total

    async def list_reconciliation(
        self,
        db: AsyncSession,
        *,
        received_after: datetime | None = None,
        received_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one row per unresolved failed webhook, joined to local intents.

        Resolved events drop off as soon as they are acknowledged or replayed
        successfully. The event table's unique ``(provider, event_id)`` key means
        the queue can never duplicate one provider event; multiple distinct
        failures for the same resource remain separate rows so out-of-order
        delivery is visible.
        """
        after = _as_utc(received_after)
        before = _as_utc(received_before)
        if after is not None and before is not None and after > before:
            raise ValueError("received_after must not be later than received_before")
        filters = [
            BillingWebhookEvent.status == "failed",
            BillingWebhookEvent.acknowledged_at.is_(None),
        ]
        if after is not None:
            filters.append(BillingWebhookEvent.received_at >= after)
        if before is not None:
            filters.append(BillingWebhookEvent.received_at <= before)
        count_stmt = select(func.count()).select_from(BillingWebhookEvent)
        base = select(BillingWebhookEvent)
        for condition in filters:
            count_stmt = count_stmt.where(condition)
            base = base.where(condition)
        total = int((await db.execute(count_stmt)).scalar_one())
        rows = list(
            (
                await db.execute(
                    base.order_by(
                        BillingWebhookEvent.received_at.desc(),
                        BillingWebhookEvent.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
        )
        links = await _local_links(db, rows)
        now = datetime.now(timezone.utc)
        items: list[dict[str, Any]] = []
        for row in rows:
            prefix = _webhook_prefix(row.event_type)
            link = links.get(f"{prefix}:{row.event_resource_id}", {
                "linked": False, "local_type": prefix, "local_id": None, "status": None,
            })
            mismatch_reason, suggested_action, link_status = _reconciliation_diagnosis(row, link)
            received_at = _as_utc(row.received_at)
            age_seconds = max(0, int((now - received_at).total_seconds())) if received_at else None
            item = _webhook_row(row)
            item.update(
                {
                    "local_link": link,
                    "link_status": link_status,
                    "amount_minor": link.get("amount_minor"),
                    "currency": link.get("currency"),
                    "age_seconds": age_seconds,
                    "age_hours": round(age_seconds / 3600, 1) if age_seconds is not None else None,
                    "mismatch_reason": mismatch_reason,
                    "suggested_action": suggested_action,
                    "can_replay": bool(
                        row.event_resource_id and prefix in {"payment", "subscription", "refund"}
                    ),
                }
            )
            items.append(item)
        return items, total

    async def acknowledge_webhook(
        self,
        db: AsyncSession,
        *,
        event_id: str,
        actor: AdminActor,
        note: str,
        request=None,
    ) -> dict[str, Any]:
        row = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == event_id).with_for_update()
        )
        if row is None:
            raise KeyError("Webhook event not found")
        if row.status != "failed":
            raise ValueError("Only failed/dead-letter webhook events can be acknowledged")
        before = {
            "status": row.status,
            "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
            "acknowledgement_note": row.acknowledgement_note,
        }
        row.acknowledged_at = datetime.now(timezone.utc)
        row.acknowledged_by = actor.user_id[:36]
        row.acknowledgement_note = " ".join(note.split())[:1000]
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.webhook.acknowledge",
            target_type="billing_webhook",
            target_id=row.id,
            reason=row.acknowledgement_note,
            before=before,
            after={
                "status": row.status,
                "acknowledged_at": row.acknowledged_at.isoformat(),
                "acknowledgement_note": row.acknowledgement_note,
            },
            metadata={"event_type": row.event_type, "event_id": row.event_id},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        return _webhook_row(row)

    async def reconcile_webhook(
        self,
        db: AsyncSession,
        *,
        event_id: str,
        actor: AdminActor,
        note: str | None,
        request=None,
    ) -> dict[str, Any]:
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == event_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError("Webhook event not found")
        if row.status == "processed":
            return {"status": "processed", "message": "Event already reconciled.", "event": _webhook_row(row)}
        if not row.event_resource_id:
            raise ValueError("This event has no provider resource to reconcile")

        user_id: str | None = None
        local_type: str | None = None
        if row.event_type.startswith("payment."):
            payment = await db.scalar(
                select(Payment).where(
                    Payment.provider == "dodo", Payment.provider_payment_id == row.event_resource_id
                )
            )
            if payment and payment.subscription_id:
                sub = await db.get(Subscription, payment.subscription_id)
                user_id = sub.user_id if sub else None
                local_type = "payment"
        elif row.event_type.startswith("subscription."):
            sub = await db.scalar(
                select(Subscription).where(
                    Subscription.provider == "dodo",
                    Subscription.provider_subscription_id == row.event_resource_id,
                )
            )
            if sub:
                user_id = sub.user_id
                local_type = "subscription"
        elif row.event_type.startswith("refund."):
            refund = await db.scalar(
                select(PaymentRefund).where(
                    PaymentRefund.provider == "dodo",
                    PaymentRefund.provider_refund_id == row.event_resource_id,
                )
            )
            if refund:
                payment = await db.get(Payment, refund.payment_id)
                if payment and payment.subscription_id:
                    sub = await db.get(Subscription, payment.subscription_id)
                    user_id = sub.user_id if sub else None
                local_type = "refund"

        before = {"status": row.status, "last_reconcile_outcome": row.last_reconcile_outcome}
        if user_id is None:
            row.reconcile_attempts = int(row.reconcile_attempts or 0) + 1
            row.last_reconcile_at = datetime.now(timezone.utc)
            row.last_reconcile_outcome = "no_local_intent"
            row.last_reconcile_error = (
                "No local checkout intent is linked to this provider resource. "
                "Review the provider event and acknowledge it if it is provider-side only."
            )
            await record_admin_audit(
                db,
                actor=actor,
                action="billing.webhook.reconcile",
                target_type="billing_webhook",
                target_id=row.id,
                reason=note,
                before=before,
                after={
                    "status": row.status,
                    "last_reconcile_outcome": row.last_reconcile_outcome,
                },
                metadata={
                    "event_type": row.event_type,
                    "event_id": row.event_id,
                    "local_type": local_type,
                    "local_intent": False,
                },
                request=request,
            )
            await db.commit()
            return {
                "status": "no_local_intent",
                "message": row.last_reconcile_error,
                "event": _webhook_row(row),
            }

        try:
            result = await payment_service.reconcile_checkout(db, user_id)
        except Exception as exc:
            result = {"success": False, "status": "unavailable", "message": type(exc).__name__}
        # reconcile_checkout may commit or roll back its own transaction.
        row = await db.scalar(
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == event_id).with_for_update()
        )
        if row is None:
            raise KeyError("Webhook event disappeared during reconciliation")
        # The helper may roll back; record the attempt only after re-locking so
        # the durable counter reflects a linked-path attempt too.
        row.reconcile_attempts = int(row.reconcile_attempts or 0) + 1
        row.last_reconcile_at = datetime.now(timezone.utc)
        if result.get("success"):
            row.status = "processed"
            row.processed_at = datetime.now(timezone.utc)
            row.last_reconcile_outcome = "reconciled"
            row.last_reconcile_error = None
        else:
            row.last_reconcile_outcome = "provider_pending" if result.get("status") == "pending" else "reconcile_failed"
            row.last_reconcile_error = str(result.get("message") or result.get("status") or "reconcile_failed")[:1000]
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.webhook.reconcile",
            target_type="billing_webhook",
            target_id=row.id,
            reason=note,
            before=before,
            after={
                "status": row.status,
                "last_reconcile_outcome": row.last_reconcile_outcome,
            },
            metadata={
                "event_type": row.event_type,
                "event_id": row.event_id,
                "local_type": local_type,
                "local_intent": True,
                "provider_status": result.get("status"),
            },
            request=request,
        )
        await db.commit()
        return {
            "status": row.last_reconcile_outcome,
            "message": row.last_reconcile_error or "Provider state reconciled.",
            "provider_result": result,
            "event": _webhook_row(row),
        }

    async def replay_webhook(
        self,
        db: AsyncSession,
        *,
        event_id: str,
        actor: AdminActor,
        reason: str,
        request=None,
    ) -> dict[str, Any]:
        """Re-fetch the provider resource and run the normal idempotent handler.

        ``payload_sha256`` proves receipt integrity, not replayability: the raw
        signed payload is deliberately not persisted. The provider's current
        resource is therefore the only authoritative replay input, and the
        operation stays idempotent through the existing payment/refund handlers.
        """
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == event_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError("Webhook event not found")
        if row.status == "processed":
            return {
                "status": "already_processed",
                "replayed": False,
                "message": "This event is already processed; no provider call was made.",
                "event": _webhook_row(row),
            }
        if not row.event_resource_id:
            raise ValueError("This event has no provider resource to replay")
        prefix = _webhook_prefix(row.event_type)
        if prefix == "unknown":
            raise ValueError("This event type cannot be replayed from the provider")
        if not payment_service.is_service_available() or not payment_service.provider.available:
            raise ValueError("The payment provider is not configured; no replay was attempted")

        cleaned_reason = " ".join(reason.split())[:1000]
        if not cleaned_reason:
            raise ValueError("A replay reason is required")
        before = {
            "status": row.status,
            "last_error": row.last_error,
            "reconcile_attempts": row.reconcile_attempts,
        }
        try:
            result = await payment_service.replay_provider_event(
                db, event_type=row.event_type, resource_id=row.event_resource_id
            )
        except Exception as exc:
            await db.rollback()
            result = {
                "success": False,
                "status": "provider_unavailable",
                "error": f"Provider replay failed ({type(exc).__name__})",
            }

        # The handler commits and releases our lock, so always re-lock the
        # durable inbox row before recording the audited replay outcome.
        row = await db.scalar(
            select(BillingWebhookEvent)
            .where(BillingWebhookEvent.id == event_id)
            .with_for_update()
        )
        if row is None:
            raise KeyError("Webhook event disappeared during replay")
        now = datetime.now(timezone.utc)
        row.reconcile_attempts = int(row.reconcile_attempts or 0) + 1
        row.last_reconcile_at = now
        replayed = bool(result.get("success"))
        provider_status = result.get("status")
        if replayed:
            row.status = "processed"
            row.processed_at = now
            row.last_error = None
            row.last_reconcile_outcome = "replayed"
            row.last_reconcile_error = None
            message = "Provider resource replayed through the normal idempotent handler."
        else:
            outcome = str(provider_status or "replay_failed")
            row.last_reconcile_outcome = "replay_failed" if outcome not in {
                "unavailable", "provider_unavailable"
            } else outcome
            row.last_reconcile_error = str(
                result.get("error") or result.get("message") or "Replay did not complete"
            )[:1000]
            message = row.last_reconcile_error
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.webhook.replay",
            target_type="billing_webhook",
            target_id=row.id,
            reason=cleaned_reason,
            before=before,
            after={
                "status": row.status,
                "last_reconcile_outcome": row.last_reconcile_outcome,
                "reconcile_attempts": row.reconcile_attempts,
            },
            metadata={
                "event_type": row.event_type,
                "event_id": row.event_id,
                "provider_status": provider_status,
                "replayed": replayed,
            },
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        return {
            "status": row.last_reconcile_outcome,
            "replayed": replayed,
            "message": message,
            "event": _webhook_row(row),
        }

    async def allow_webhook_replay(self, actor_user_id: str, event_id: str) -> bool:
        """Bounded per-admin, per-event replay limiter; fails open on Redis outage."""
        try:
            redis = await get_redis_client()
            key = f"ratelimit:admin:billing:webhook-replay:{actor_user_id}:{event_id}"
            count = await redis.eval(
                """
                local n = redis.call('INCR', KEYS[1])
                if n == 1 then
                  redis.call('EXPIRE', KEYS[1], ARGV[1])
                end
                return n
                """,
                1,
                key,
                300,
            )
            return int(count) <= 5
        except Exception:
            return True

    async def list_refund_requests(
        self, db: AsyncSession, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        base = select(AdminRefundRequest)
        count_stmt = select(func.count()).select_from(AdminRefundRequest)
        if status:
            base = base.where(AdminRefundRequest.status == status)
            count_stmt = count_stmt.where(AdminRefundRequest.status == status)
        total = int((await db.execute(count_stmt)).scalar_one())
        rows = (
            await db.execute(
                base.order_by(AdminRefundRequest.requested_at.desc()).limit(limit).offset(offset)
            )
        ).scalars().all()
        return [_refund_row(row) for row in rows], total

    async def get_refund_request(self, db: AsyncSession, request_id: str) -> AdminRefundRequest | None:
        return await db.scalar(
            select(AdminRefundRequest)
            .where(AdminRefundRequest.id == request_id)
            .with_for_update()
        )

    async def create_refund_request(
        self,
        db: AsyncSession,
        *,
        payment_id: str | None = None,
        provider_payment_id: str | None = None,
        request_kind: str = "refund",
        amount: int | None,
        provider_item_id: str | None,
        tax_inclusive: bool,
        reason: str,
        evidence: str | None = None,
        actor: AdminActor,
        request=None,
    ) -> dict[str, Any]:
        if bool(payment_id) == bool(provider_payment_id):
            raise ValueError("Provide exactly one of payment_id or provider_payment_id")
        if request_kind not in {"refund", "goodwill"}:
            raise ValueError("Refund kind must be refund or goodwill")

        if payment_id:
            payment = await db.scalar(
                select(Payment).where(Payment.id == payment_id).with_for_update()
            )
        else:
            cleaned_provider_payment_id = str(provider_payment_id or "").strip()
            if not cleaned_provider_payment_id:
                raise ValueError("A Dodo payment ID is required")
            payment = await db.scalar(
                select(Payment)
                .where(
                    Payment.provider == "dodo",
                    Payment.provider_payment_id == cleaned_provider_payment_id,
                )
                .with_for_update()
            )
        if payment is None:
            raise KeyError("Payment not found")
        if payment.provider != "dodo":
            raise ValueError("Only Dodo payments can be refunded from this console")
        if payment.status in {"refunded", "failed", "cancelled"}:
            raise ValueError("This payment cannot be refunded")
        if payment.status not in {"paid", "partially_refunded", "captured", "succeeded"}:
            raise ValueError("Only settled payments can be refunded")
        open_row = await db.scalar(
            select(AdminRefundRequest).where(
                AdminRefundRequest.payment_id == payment.id,
                AdminRefundRequest.status.in_(("pending", "approved", "executing")),
            )
        )
        if open_row is not None:
            raise ValueError("An open refund request already exists for this payment")
        already_refunded = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                        PaymentRefund.payment_id == payment.id,
                        PaymentRefund.status == "succeeded",
                    )
                )
            ).scalar_one()
        )
        remaining = max(0, int(payment.amount) - already_refunded)
        if remaining <= 0:
            raise ValueError("This payment has already been fully refunded")
        if amount is None and already_refunded > 0:
            raise ValueError(
                "This payment was partially refunded; specify the remaining amount and provider line-item ID"
            )
        cleaned_item_id = str(provider_item_id or "").strip() or None
        if amount is None and cleaned_item_id is not None:
            raise ValueError("A full refund must not include a provider line-item ID")
        if amount is not None:
            if type(amount) is not int or amount <= 0:
                raise ValueError("Refund amount must be a positive integer")
            if amount > remaining:
                raise ValueError("Refund amount cannot exceed the unrefunded payment balance")
            if not cleaned_item_id:
                raise ValueError("A partial refund requires the provider line-item ID")
        cleaned_reason = " ".join(reason.split())[:1000]
        if not cleaned_reason:
            raise ValueError("A refund reason is required")
        cleaned_evidence = " ".join((evidence or "").split())[:2000] or None
        row = AdminRefundRequest(
            payment_id=payment.id,
            status="pending",
            request_kind=request_kind,
            amount=amount,
            currency=payment.currency or "INR",
            provider_item_id=cleaned_item_id,
            tax_inclusive=bool(tax_inclusive),
            reason=cleaned_reason,
            evidence=cleaned_evidence,
            requested_by=actor.user_id[:36],
            requested_email=actor.email[:255] if actor.email else None,
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise ValueError("An open refund request already exists for this payment") from None
        await admin_approval_service.create_request(
            db,
            request_type="refund",
            payload={
                "refund_request_id": row.id,
                "payment_id": row.payment_id,
                "request_kind": row.request_kind,
                "amount": row.amount,
                "currency": row.currency,
                "evidence": row.evidence,
            },
            reason=cleaned_reason,
            actor=actor,
            resource_type="refund_request",
            resource_id=row.id,
            expires_in=timedelta(days=7),
            request=request,
            commit=False,
        )
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.refund.requested",
            target_type="refund_request",
            target_id=row.id,
            reason=cleaned_reason,
            before=None,
            after={
                "status": row.status,
                "request_kind": row.request_kind,
                "payment_id": row.payment_id,
                "amount": row.amount,
                "currency": row.currency,
                "has_evidence": row.evidence is not None,
            },
            metadata={
                "provider_payment_id": payment.provider_payment_id,
                "request_kind": row.request_kind,
            },
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        return _refund_row(row)

    async def decide_refund_request(
        self,
        db: AsyncSession,
        *,
        request_id: str,
        decision: str,
        note: str,
        actor: AdminActor,
        request=None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("Decision must be approve or reject")
        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request not found")
        if row.status != "pending":
            raise ValueError("Only pending refund requests can be decided")
        if row.requested_by == actor.user_id:
            raise PermissionError("A different admin must approve or reject this refund request")
        cleaned_note = " ".join((note or "").split())[:1000]
        # Mirror the decision into the shared two-person queue. The approval
        # row enforces expiry and separation of duties before the refund moves.
        await admin_approval_service.sync_decision(
            db,
            request_type="refund",
            resource_id=row.id,
            decision=decision,
            note=cleaned_note,
            actor=actor,
            request=request,
        )
        before = {
            "status": row.status,
            "approved_by": row.approved_by,
            "request_kind": row.request_kind,
        }
        if decision == "approve":
            row.status = "approved"
            row.approved_by = actor.user_id[:36]
            row.approved_email = actor.email[:255] if actor.email else None
        else:
            row.status = "rejected"
            row.approved_by = actor.user_id[:36]
            row.approved_email = actor.email[:255] if actor.email else None
        row.decision_note = cleaned_note or None
        row.decided_at = datetime.now(timezone.utc)
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.refund.approved" if decision == "approve" else "billing.refund.rejected",
            target_type="refund_request",
            target_id=row.id,
            reason=cleaned_note,
            before=before,
            after={"status": row.status, "approved_by": row.approved_by},
            metadata={"payment_id": row.payment_id, "amount": row.amount},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        return _refund_row(row)

    async def execute_refund_request(
        self,
        db: AsyncSession,
        *,
        request_id: str,
        actor: AdminActor,
        note: str,
        request=None,
    ) -> dict[str, Any]:
        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request not found")
        if row.status != "approved":
            # A failed attempt may have reached the provider even when the
            # response was lost. Never guess by resubmitting; the operator must
            # reconcile with Dodo before creating a new request.
            raise ValueError(
                "Only an approved refund can be executed. A failed attempt must be reconciled with Dodo first."
            )
        payment = await db.get(Payment, row.payment_id)
        if payment is None or not payment.provider_payment_id:
            raise ValueError("The payment has no provider identifier")
        if payment.provider != "dodo":
            raise ValueError("Only Dodo payments can be refunded from this console")
        already_refunded = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                        PaymentRefund.payment_id == payment.id,
                        PaymentRefund.status == "succeeded",
                    )
                )
            ).scalar_one()
        )
        remaining = max(0, int(payment.amount) - already_refunded)
        if remaining <= 0:
            raise ValueError("This payment has already been fully refunded")
        if row.amount is None and already_refunded > 0:
            raise ValueError(
                "This payment was partially refunded after approval; specify the remaining amount and item ID"
            )
        if row.amount is not None and row.amount > remaining:
            raise ValueError("The approved refund now exceeds the remaining payment balance")
        if not payment_service.is_service_available():
            raise ValueError("Billing is unavailable; no refund was attempted")
        if not payment_service.provider.available:
            raise ValueError("The payment provider is not configured; no refund was attempted")

        # Bind the provider side effect to an unexpired, approved request. A
        # replayed or stale approval fails before anything reaches Dodo.
        await admin_approval_service.sync_execution_start(
            db,
            request_type="refund",
            resource_id=row.id,
            actor=actor,
            note=note,
            request=request,
        )
        before = {
            "status": row.status,
            "provider_refund_id": row.provider_refund_id,
            "request_kind": row.request_kind,
        }
        row.status = "executing"
        row.executed_by = actor.user_id[:36]
        row.last_error = None
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.refund.execution_started",
            target_type="refund_request",
            target_id=row.id,
            reason=note,
            before=before,
            after={
                "status": row.status,
                "request_kind": row.request_kind,
                "payment_id": row.payment_id,
                "amount": row.amount,
            },
            metadata={
                "provider_payment_id": payment.provider_payment_id,
                "request_kind": row.request_kind,
            },
            request=request,
        )
        await db.commit()

        provider_refund_id: str | None = None
        provider_error: str | None = None
        ledger_error: str | None = None
        provider_status = "pending"
        refund_amount = row.amount if row.amount is not None else remaining
        try:
            result = await payment_service.provider.create_refund(
                payment.provider_payment_id,
                amount=row.amount,
                reason=row.reason,
                item_id=row.provider_item_id,
                tax_inclusive=bool(row.tax_inclusive),
            )
            resource = payment_service._provider_resource(result)
            provider_refund_id = str(resource.get("refund_id") or resource.get("id") or "") or None
            if provider_refund_id is None:
                provider_error = "Provider accepted the request without returning a refund identifier"
            else:
                raw_status = str(resource.get("status") or "").lower()
                if raw_status in {"succeeded", "processed", "completed"}:
                    provider_status = "succeeded"
                elif raw_status in {"failed", "cancelled"}:
                    provider_status = "failed"
                else:
                    provider_status = "pending"
                # Write the local receipt before declaring success. The webhook
                # path may race; the provider refund identifier is idempotent.
                ledger = await payment_service._handle_refund_event(
                    db,
                    f"refund.{provider_status}",
                    {
                        "refund_id": provider_refund_id,
                        "payment_id": payment.provider_payment_id,
                        "amount": refund_amount,
                        "currency": payment.currency or "INR",
                        "status": provider_status,
                        "reason": row.reason,
                    },
                )
                if not ledger.get("success"):
                    ledger_error = str(ledger.get("error") or "Local refund ledger update failed")
        except Exception as exc:
            provider_error = f"{type(exc).__name__}: provider refund request failed"

        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request disappeared during execution")
        if provider_error:
            row.status = "failed"
            row.last_error = provider_error[:1000]
            action = "billing.refund.execution_failed"
        elif ledger_error:
            # The provider may have accepted the refund. Never invite a resubmit:
            # keep the identifier and require reconciliation with Dodo.
            row.status = "failed"
            row.provider_refund_id = provider_refund_id
            row.last_error = f"Provider refund accepted but local ledger update failed: {ledger_error}"[:1000]
            action = "billing.refund.ledger_reconciliation_required"
        elif provider_status == "succeeded":
            row.status = "executed"
            row.provider_refund_id = provider_refund_id
            row.executed_at = datetime.now(timezone.utc)
            row.last_error = None
            action = "billing.refund.executed"
        elif provider_status == "failed":
            row.status = "failed"
            row.provider_refund_id = provider_refund_id
            row.last_error = "Provider reported the refund as failed"
            action = "billing.refund.execution_failed"
        else:
            row.status = "executing"
            row.provider_refund_id = provider_refund_id
            row.last_error = None
            action = "billing.refund.execution_pending"
        await record_admin_audit(
            db,
            actor=actor,
            action=action,
            target_type="refund_request",
            target_id=row.id,
            reason=note,
            before={"status": "executing"},
            after={
                "status": row.status,
                "provider_refund_id": row.provider_refund_id,
                "last_error": row.last_error,
            },
            metadata={
                "payment_id": row.payment_id,
                "amount": row.amount,
                "request_kind": row.request_kind,
            },
            request=request,
        )
        if row.status == "executed":
            await admin_approval_service.sync_execution(
                db,
                request_type="refund",
                resource_id=row.id,
                actor=actor,
                result={"status": "executed", "provider_refund_id": row.provider_refund_id},
                note=note,
                request=request,
            )
        elif row.status == "failed":
            await admin_approval_service.sync_execution(
                db,
                request_type="refund",
                resource_id=row.id,
                actor=actor,
                failed=True,
                note=note,
                request=request,
            )
        await db.commit()
        await db.refresh(row)
        return _refund_row(row)

    async def reconcile_refund_request(
        self,
        db: AsyncSession,
        *,
        request_id: str,
        actor: AdminActor,
        note: str | None,
        request=None,
    ) -> dict[str, Any]:
        """Re-read a stuck provider refund and reconcile the local ledger.

        A failed or still-executing request may have reached Dodo even when the
        original response was lost. Only the provider's authenticated refund
        read is authoritative here; reconciliation never resubmits a refund.
        """
        row = await db.scalar(select(AdminRefundRequest).where(AdminRefundRequest.id == request_id))
        if row is None:
            raise KeyError("Refund request not found")
        if row.status not in {"executing", "failed"}:
            raise ValueError("Only an executing or failed refund request can be reconciled")
        provider_refund_id = str(row.provider_refund_id or "").strip()
        if not provider_refund_id:
            raise ValueError("This refund request has no provider refund identifier to reconcile")
        payment = await db.get(Payment, row.payment_id)
        if payment is None or not payment.provider_payment_id:
            raise ValueError("The payment has no provider identifier")
        if payment.provider != "dodo":
            raise ValueError("Only Dodo payments can be reconciled from this console")
        provider_payment_id = payment.provider_payment_id
        payment_amount = int(payment.amount)
        currency = row.currency or payment.currency or "INR"
        reason = row.reason
        requested_amount = row.amount

        try:
            provider_result = await payment_service.provider.get_refund(provider_refund_id)
        except Exception as exc:
            raise ValueError(
                f"Dodo refund lookup failed ({type(exc).__name__}); no local changes were made"
            ) from exc
        resource = payment_service._provider_resource(provider_result)
        if not isinstance(resource, dict):
            raise ValueError("Dodo returned an unreadable refund response; no local changes were made")
        returned_payment_id = str(resource.get("payment_id") or "").strip()
        if returned_payment_id and returned_payment_id != provider_payment_id:
            raise ValueError("Dodo returned a refund for a different payment; no local changes were made")
        raw_status = str(resource.get("status") or "").lower()
        if raw_status in {"succeeded", "processed", "completed"}:
            provider_status = "succeeded"
        elif raw_status in {"failed", "cancelled"}:
            provider_status = "failed"
        else:
            provider_status = "pending"

        # Re-lock only for the local write so the provider read never holds the
        # request row while waiting on Dodo. Reject concurrent changes instead
        # of overwriting a settlement that landed while we were reading.
        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request disappeared during reconciliation")
        if row.status not in {"executing", "failed"} or str(row.provider_refund_id or "").strip() != provider_refund_id:
            raise ValueError("Refund request changed while reconciling with Dodo; refresh and review it again")
        before = {"status": row.status, "provider_refund_id": row.provider_refund_id}

        already_refunded = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                        PaymentRefund.payment_id == row.payment_id,
                        PaymentRefund.status == "succeeded",
                        PaymentRefund.provider_refund_id != provider_refund_id,
                    )
                )
            ).scalar_one()
        )
        refund_amount = requested_amount if requested_amount is not None else max(0, payment_amount - already_refunded)

        ledger_error: str | None = None
        try:
            ledger = await payment_service._handle_refund_event(
                db,
                f"refund.{provider_status}",
                {
                    "refund_id": provider_refund_id,
                    "payment_id": provider_payment_id,
                    "amount": refund_amount,
                    "currency": currency,
                    "status": provider_status,
                    "reason": reason,
                },
            )
            if not ledger.get("success"):
                ledger_error = str(ledger.get("error") or "Local refund ledger update failed")
        except Exception as exc:
            ledger_error = f"{type(exc).__name__}: local refund ledger update failed"
            await db.rollback()

        # _handle_refund_event commits and may settle the request itself. Always
        # re-read under a fresh lock before applying the final audited state.
        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request disappeared during reconciliation")
        if ledger_error:
            # The provider may have accepted or settled the refund. Keep the
            # request out of `executed`, retain the provider receipt, and send
            # the operator back through reconciliation instead of resubmission.
            row.status = "failed"
            row.last_error = (
                f"Dodo reports the refund as {provider_status}, but the local refund ledger update failed: "
                f"{ledger_error}. Reconcile with Dodo again before any new attempt; do not resubmit."
            )[:1000]
        elif provider_status == "succeeded":
            row.status = "executed"
            row.executed_at = datetime.now(timezone.utc)
            row.last_error = None
        elif provider_status == "failed":
            row.status = "failed"
            row.last_error = "Provider reported the refund as failed"
        else:
            row.status = "executing"
            row.last_error = None
        await record_admin_audit(
            db,
            actor=actor,
            action="billing.refund.reconciled",
            target_type="refund_request",
            target_id=row.id,
            reason=note,
            before=before,
            after={
                "status": row.status,
                "provider_refund_id": row.provider_refund_id,
                "last_error": row.last_error,
            },
            metadata={
                "payment_id": row.payment_id,
                "amount": row.amount if row.amount is not None else refund_amount,
                "provider_status": provider_status,
                "ledger_written": ledger_error is None,
            },
            request=request,
        )
        if row.status == "executed":
            await admin_approval_service.sync_execution(
                db,
                request_type="refund",
                resource_id=row.id,
                actor=actor,
                result={"status": "executed", "provider_refund_id": row.provider_refund_id},
                note=note,
                request=request,
            )
        elif row.status == "failed":
            await admin_approval_service.sync_execution(
                db,
                request_type="refund",
                resource_id=row.id,
                actor=actor,
                failed=True,
                note=note,
                request=request,
            )
        await db.commit()
        await db.refresh(row)
        return _refund_row(row)


admin_billing_service = AdminBillingService()

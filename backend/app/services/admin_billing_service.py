"""Admin billing control-room queries and safe operational actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_plan_config
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .payment_service import PAID_SUBSCRIPTION_STATUSES, payment_service

Payment = models.Payment
Subscription = models.Subscription
BillingWebhookEvent = models.BillingWebhookEvent
PaymentRefund = models.PaymentRefund
AdminRefundRequest = models.AdminRefundRequest
User = models.User


def _monthly_amount(plan_id: str | None, quoted_amount: int | None) -> int:
    config = get_plan_config(plan_id) or {}
    if type(quoted_amount) is int and quoted_amount >= 0:
        amount = quoted_amount
    elif type(config.get("monthly_equivalent_price")) is int:
        amount = int(config["monthly_equivalent_price"])
    else:
        amount = int(config.get("price") or 0)
        if str(config.get("interval") or "").lower() == "year":
            amount = round(amount / 12)
    return max(0, amount)


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
        "amount": row.amount,
        "currency": row.currency,
        "provider_item_id": row.provider_item_id,
        "tax_inclusive": bool(row.tax_inclusive),
        "reason": row.reason,
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
            select(Payment.provider_payment_id, Payment.id, Payment.subscription_id).where(
                Payment.provider == "dodo", Payment.provider_payment_id.in_(payment_ids)
            )
        )
    ).all() if payment_ids else []
    subscriptions = (
        await db.execute(
            select(Subscription.provider_subscription_id, Subscription.id, Subscription.user_id).where(
                Subscription.provider == "dodo", Subscription.provider_subscription_id.in_(subscription_ids)
            )
        )
    ).all() if subscription_ids else []
    refunds = (
        await db.execute(
            select(PaymentRefund.provider_refund_id, PaymentRefund.id, PaymentRefund.payment_id).where(
                PaymentRefund.provider == "dodo", PaymentRefund.provider_refund_id.in_(refund_ids)
            )
        )
    ).all() if refund_ids else []

    result: dict[str, dict[str, Any]] = {}
    for provider_id, local_id, subscription_id in payments:
        result[f"payment:{provider_id}"] = {
            "linked": True, "local_type": "payment", "local_id": local_id,
            "subscription_id": subscription_id,
        }
    for provider_id, local_id, user_id in subscriptions:
        result[f"subscription:{provider_id}"] = {
            "linked": True, "local_type": "subscription", "local_id": local_id, "user_id": user_id,
        }
    for provider_id, local_id, payment_id in refunds:
        result[f"refund:{provider_id}"] = {
            "linked": True, "local_type": "refund", "local_id": local_id, "payment_id": payment_id,
        }
    for row in items:
        prefix = "payment" if row.event_type.startswith("payment.") else (
            "subscription" if row.event_type.startswith("subscription.") else (
                "refund" if row.event_type.startswith("refund.") else "unknown"
            )
        )
        key = f"{prefix}:{row.event_resource_id}"
        if key not in result:
            result[key] = {"linked": False, "local_type": prefix, "local_id": None}
    return result


class AdminBillingService:
    async def summary(self, db: AsyncSession, days: int = 30) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=days)
        active_rows = (
            await db.execute(
                select(Subscription.plan_id, Subscription.quoted_amount, Subscription.current_period_end).where(
                    Subscription.status.in_(PAID_SUBSCRIPTION_STATUSES)
                )
            )
        ).all()
        active_count = sum(
            1
            for plan_id, _amount, period_end in active_rows
            if period_end is None or period_end >= now
        )
        past_due = int(
            (
                await db.execute(
                    select(func.count()).select_from(Subscription).where(
                        Subscription.status.in_(("past_due", "on_hold"))
                    )
                )
            ).scalar_one()
        )
        mrr_paise = sum(
            _monthly_amount(plan_id, amount)
            for plan_id, amount, period_end in active_rows
            if period_end is None or period_end >= now
        )
        plan_mix: dict[str, dict[str, Any]] = {}
        for plan_id, amount, period_end in active_rows:
            if period_end is not None and period_end < now:
                continue
            bucket = plan_mix.setdefault(plan_id, {"plan_id": plan_id, "subscriptions": 0, "mrr": 0})
            bucket["subscriptions"] += 1
            bucket["mrr"] += _monthly_amount(plan_id, amount)
        for bucket in plan_mix.values():
            bucket["mrr"] = round(bucket["mrr"] / 100, 2)

        gross = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(Payment.amount), 0)).where(
                        Payment.created_at >= period_start,
                        Payment.status.in_(("paid", "partially_refunded", "captured", "refunded")),
                    )
                )
            ).scalar_one()
        )
        refunded = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                        PaymentRefund.created_at >= period_start,
                        PaymentRefund.status == "succeeded",
                    )
                )
            ).scalar_one()
        )
        open_refunds = int(
            (
                await db.execute(
                    select(func.count()).select_from(AdminRefundRequest).where(
                        AdminRefundRequest.status.in_(("pending", "approved"))
                    )
                )
            ).scalar_one()
        )
        unacknowledged_failures = int(
            (
                await db.execute(
                    select(func.count()).select_from(BillingWebhookEvent).where(
                        BillingWebhookEvent.status == "failed",
                        BillingWebhookEvent.acknowledged_at.is_(None),
                    )
                )
            ).scalar_one()
        )
        webhook_24h = int(
            (
                await db.execute(
                    select(func.count()).select_from(BillingWebhookEvent).where(
                        BillingWebhookEvent.received_at >= now - timedelta(hours=24)
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
                    )
                )
            ).scalar_one()
        )
        recent_refunds = (
            await db.execute(
                select(AdminRefundRequest).order_by(AdminRefundRequest.requested_at.desc()).limit(8)
            )
        ).scalars().all()
        return {
            "period_days": days,
            "generated_at": now.isoformat(),
            "currency": "INR",
            "mrr": round(mrr_paise / 100, 2),
            "arr": round(mrr_paise * 12 / 100, 2),
            "active_subscriptions": active_count,
            "past_due_subscriptions": past_due,
            "gross_revenue": round(gross / 100, 2),
            "refunded": round(refunded / 100, 2),
            "net_revenue": round((gross - refunded) / 100, 2),
            "open_refund_requests": open_refunds,
            "unacknowledged_webhook_failures": unacknowledged_failures,
            "webhooks_24h": webhook_24h,
            "webhook_failures_24h": webhook_failed_24h,
            "plan_mix": sorted(plan_mix.values(), key=lambda item: (-item["mrr"], item["plan_id"])),
            "recent_refund_requests": [_refund_row(row) for row in recent_refunds],
        }

    async def list_webhooks(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        event_type: str | None = None,
        acknowledged: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        filters = []
        if status:
            filters.append(BillingWebhookEvent.status == status)
        if event_type:
            filters.append(BillingWebhookEvent.event_type == event_type)
        if acknowledged is True:
            filters.append(BillingWebhookEvent.acknowledged_at.is_not(None))
        elif acknowledged is False:
            filters.append(BillingWebhookEvent.acknowledged_at.is_(None))
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
            prefix = "payment" if row.event_type.startswith("payment.") else (
                "subscription" if row.event_type.startswith("subscription.") else (
                    "refund" if row.event_type.startswith("refund.") else "unknown"
                )
            )
            item = _webhook_row(row)
            item["local_link"] = links.get(f"{prefix}:{row.event_resource_id}", {
                "linked": False, "local_type": prefix, "local_id": None,
            })
            result.append(item)
        return result, total

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
        if row.status == "processed":
            raise ValueError("Processed webhook events do not need acknowledgement")
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
            select(BillingWebhookEvent).where(BillingWebhookEvent.id == event_id)
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

        row.reconcile_attempts = int(row.reconcile_attempts or 0) + 1
        row.last_reconcile_at = datetime.now(timezone.utc)
        before = {"status": row.status, "last_reconcile_outcome": row.last_reconcile_outcome}
        if user_id is None:
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
        payment_id: str,
        amount: int | None,
        provider_item_id: str | None,
        tax_inclusive: bool,
        reason: str,
        actor: AdminActor,
        request=None,
    ) -> dict[str, Any]:
        payment = await db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None:
            raise KeyError("Payment not found")
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
        if amount is not None:
            if type(amount) is not int or amount <= 0:
                raise ValueError("Refund amount must be a positive integer")
            if amount > remaining:
                raise ValueError("Refund amount cannot exceed the unrefunded payment balance")
            if not provider_item_id:
                raise ValueError("A partial refund requires the provider line-item ID")
        cleaned_reason = " ".join(reason.split())[:1000]
        if not cleaned_reason:
            raise ValueError("A refund reason is required")
        row = AdminRefundRequest(
            payment_id=payment.id,
            status="pending",
            amount=amount,
            currency=payment.currency or "INR",
            provider_item_id=provider_item_id,
            tax_inclusive=bool(tax_inclusive),
            reason=cleaned_reason,
            requested_by=actor.user_id[:36],
            requested_email=actor.email[:255] if actor.email else None,
        )
        db.add(row)
        await db.flush()
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
                "payment_id": row.payment_id,
                "amount": row.amount,
                "currency": row.currency,
            },
            metadata={"provider_payment_id": payment.provider_payment_id},
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
        before = {"status": row.status, "approved_by": row.approved_by}
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
            action=f"billing.refund.{decision}d",
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
        if row.status not in {"approved", "failed"}:
            raise ValueError("Only an approved or retryable failed refund can be executed")
        payment = await db.get(Payment, row.payment_id)
        if payment is None or not payment.provider_payment_id:
            raise ValueError("The payment has no provider identifier")
        if not payment_service.is_service_available():
            raise ValueError("Billing is unavailable; no refund was attempted")
        if not payment_service.provider.available:
            raise ValueError("The payment provider is not configured; no refund was attempted")

        before = {"status": row.status, "provider_refund_id": row.provider_refund_id}
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
            after={"status": row.status, "payment_id": row.payment_id, "amount": row.amount},
            metadata={"provider_payment_id": payment.provider_payment_id},
            request=request,
        )
        await db.commit()

        provider_refund_id: str | None = None
        provider_error: str | None = None
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
        except Exception as exc:
            provider_error = f"{type(exc).__name__}: provider refund request failed"

        row = await self.get_refund_request(db, request_id)
        if row is None:
            raise KeyError("Refund request disappeared during execution")
        if provider_error:
            row.status = "failed"
            row.last_error = provider_error[:1000]
            action = "billing.refund.execution_failed"
        else:
            row.status = "executed"
            row.provider_refund_id = provider_refund_id
            row.executed_at = datetime.now(timezone.utc)
            row.last_error = None
            action = "billing.refund.executed"
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
            metadata={"payment_id": row.payment_id, "amount": row.amount},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        return _refund_row(row)


admin_billing_service = AdminBillingService()

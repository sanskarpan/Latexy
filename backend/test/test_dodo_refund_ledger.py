"""Immutable settled-refund ledger behavior."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.payment_service as payment_service_module
from app.services.payment_service import PaymentService


@pytest.mark.asyncio
async def test_settled_refund_duplicate_is_idempotent_and_amount_conflict_is_rejected(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, intent_id = str(uuid.uuid4()), str(uuid.uuid4())
    payment_id = f"pay_refund_ledger_{uuid.uuid4().hex}"
    refund_id = f"ref_refund_ledger_{uuid.uuid4().hex}"
    await db_session.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Refund Ledger Test', true, 'pro', 'active', false)"
    ), {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"})
    await db_session.execute(text(
        "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, current_period_start) "
        "VALUES (:id, :user_id, 'dodo', 'pro', 'active', NOW())"
    ), {"id": intent_id, "user_id": user_id})
    await db_session.execute(text(
        "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, amount, currency, status) "
        "VALUES (:id, :user_id, :subscription_id, 'dodo', :payment_id, 59900, 'INR', 'paid')"
    ), {"id": str(uuid.uuid4()), "user_id": user_id, "subscription_id": intent_id, "payment_id": payment_id})
    await db_session.commit()
    reverse_paid_payment = AsyncMock()
    monkeypatch.setattr(payment_service_module.referral_service, "reverse_paid_payment", reverse_paid_payment)
    service = PaymentService()
    succeeded = {
        "refund_id": refund_id,
        "payment_id": payment_id,
        "amount": 59900,
        "currency": "INR",
        "status": "succeeded",
    }

    first = await service._handle_refund_event(db_session, "refund.succeeded", succeeded)
    reversal_count_after_first_settlement = reverse_paid_payment.await_count
    duplicate = await service._handle_refund_event(db_session, "refund.succeeded", succeeded)
    older_failure = await service._handle_refund_event(
        db_session, "refund.failed", {**succeeded, "status": "failed"},
    )
    conflicting = await service._handle_refund_event(
        db_session, "refund.succeeded", {**succeeded, "amount": 30000},
    )

    assert first == {"success": True}
    assert duplicate == {"success": True}
    assert older_failure == {"success": True}
    assert conflicting == {
        "success": False,
        "error": "Settled refund details do not match the existing refund",
    }
    assert reverse_paid_payment.await_count == reversal_count_after_first_settlement
    refund = (await db_session.execute(text(
        "SELECT amount, currency, status FROM payment_refunds WHERE provider_refund_id=:refund_id"
    ), {"refund_id": refund_id})).one()
    assert tuple(refund) == (59900, "INR", "succeeded")
    assert await db_session.scalar(text(
        "SELECT status FROM payments WHERE provider_payment_id=:payment_id"
    ), {"payment_id": payment_id}) == "refunded"

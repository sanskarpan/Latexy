"""Billing regressions for interleaved checkout and provider lifecycle events."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.dodo_provider import DodoAPIError
from app.services.payment_service import PaymentService


async def _user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Billing interleaving', true, 'free', 'inactive', false)"
    ), {"id": user_id, "email": f"test_{uuid.uuid4().hex}@example.com"})
    await db.commit()
    return user_id


async def _intent(db: AsyncSession, user_id: str, *, paid: bool = False) -> str:
    intent_id = str(uuid.uuid4())
    await db.execute(text(
        "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
        "provider_checkout_session_id, provider_customer_id, provider_product_id, quoted_amount, "
        "quoted_tax_inclusive, discount_percent, plan_id, status, current_period_start, current_period_end) "
        "VALUES (:id, :user_id, 'dodo', :sub_id, :session_id, :customer_id, 'p_test_pro', "
        "59900, true, 0, 'pro', :status, NOW(), :period_end)"
    ), {"id": intent_id, "user_id": user_id, "sub_id": f"sub_{intent_id}",
        "session_id": f"sess_{intent_id}", "customer_id": f"cus_{intent_id}",
        "status": "active" if paid else "checkout_pending",
        "period_end": datetime.now(timezone.utc) + timedelta(days=30)})
    await db.execute(text(
        "UPDATE users SET subscription_id=:intent_id, subscription_plan=:plan, subscription_status=:status WHERE id=:id"
    ), {"intent_id": intent_id, "id": user_id, "plan": "pro" if paid else "free",
        "status": "active" if paid else "checkout_pending"})
    await db.commit()
    return intent_id


def _payment(user_id: str, intent_id: str) -> dict:
    return {
        "payload_type": "Payment", "payment_id": f"pay_{intent_id}", "status": "succeeded",
        "currency": "INR", "total_amount": 59900, "tax": 0,
        "customer": {"customer_id": f"cus_{intent_id}"},
        "checkout_session_id": f"sess_{intent_id}", "subscription_id": f"sub_{intent_id}",
        "metadata": {"latexy_intent_id": intent_id, "latexy_user_id": user_id,
                     "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"},
        "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
    }


def _service(monkeypatch: pytest.MonkeyPatch) -> PaymentService:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    service = PaymentService()
    monkeypatch.setattr(service, "is_available", lambda: True)
    monkeypatch.setattr(service, "_acquire_checkout_lock", AsyncMock(return_value="checkout-lease"))
    monkeypatch.setattr(service, "_release_checkout_lock", AsyncMock())
    return service


@pytest.mark.asyncio
async def test_checkout_rechecks_durable_intent_after_acquiring_lease(
    db_session: AsyncSession, db_session_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user(db_session)
    service = _service(monkeypatch)
    created_intent = None

    async def delayed_lease(_user_id: str) -> str:
        nonlocal created_intent
        # Another request commits after this request's optimistic read but
        # before its lease is granted. Its payable checkout must block us.
        async with db_session_factory() as concurrent:
            created_intent = await _intent(concurrent, user_id)
        return "checkout-lease"

    monkeypatch.setattr(service, "_acquire_checkout_lock", delayed_lease)
    checkout = AsyncMock(return_value={"session_id": "sess_second", "checkout_url": "https://checkout.dodopayments.com/test"})
    monkeypatch.setattr(service.provider, "create_checkout_session", checkout)
    result = await service.create_subscription(db_session, user_id, "pro", "test@example.com", "Test")

    assert result["success"] is False
    checkout.assert_not_awaited()
    assert await db_session.scalar(text("SELECT COUNT(*) FROM subscriptions WHERE user_id=:id"), {"id": user_id}) == 1
    assert await db_session.scalar(text("SELECT subscription_id FROM users WHERE id=:id"), {"id": user_id}) == created_intent


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["success", "provider_error", "unexpected_error"])
async def test_early_payment_webhook_survives_checkout_response_or_error(
    db_session: AsyncSession, db_session_factory, monkeypatch: pytest.MonkeyPatch, response: str,
) -> None:
    user_id = await _user(db_session)
    service = _service(monkeypatch)
    intent_id = None

    async def create_checkout(payload: dict) -> dict:
        nonlocal intent_id
        intent_id = payload["metadata"]["latexy_intent_id"]
        async with db_session_factory() as webhook_db:
            result = await service._handle_payment_succeeded(
                webhook_db, _payment(user_id, intent_id), {"timestamp": datetime.now(timezone.utc).isoformat()},
            )
            assert result == {"success": True}
        if response == "provider_error":
            raise DodoAPIError(503, "provider_unavailable")
        if response == "unexpected_error":
            raise RuntimeError("checkout response interrupted")
        return {"session_id": f"sess_{intent_id}", "checkout_url": "https://checkout.dodopayments.com/test"}

    monkeypatch.setattr(service.provider, "create_checkout_session", create_checkout)
    await service.create_subscription(db_session, user_id, "pro", "test@example.com", "Test")

    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "active"
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("pro", "active", intent_id)
    assert await db_session.scalar(text("SELECT COUNT(*) FROM payments WHERE subscription_id=:id"), {"id": intent_id}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("current_status", ["active", "paused", "past_due", "on_hold"])
async def test_older_initial_payment_respects_newer_lifecycle_state(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, current_status: str,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id)
    service = _service(monkeypatch)
    newer = datetime.now(timezone.utc)
    period_end = newer + timedelta(days=30)
    lifecycle = await service._handle_subscription_event(
        db_session, f"subscription.{current_status}",
        {"subscription_id": f"sub_{intent_id}", "product_id": "p_test_pro", "status": current_status,
         "customer": {"customer_id": f"cus_{intent_id}"}, "next_billing_date": period_end.isoformat()},
        {"timestamp": newer.isoformat()},
    )
    payment = await service._handle_payment_succeeded(
        db_session, _payment(user_id, intent_id), {"timestamp": (newer - timedelta(seconds=1)).isoformat()},
    )

    assert lifecycle == payment == {"success": True}
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert user.subscription_plan == ("pro" if current_status == "active" else "free")
    assert user.subscription_status == current_status
    row = (await db_session.execute(text(
        "SELECT status, provider_event_at FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})).one()
    assert row.status == current_status
    assert row.provider_event_at == newer


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["customer", "user", "intent"])
async def test_explicit_payment_owner_mismatch_never_mutates_ledger(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mismatch: str,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id)
    service = _service(monkeypatch)
    data = _payment(user_id, intent_id)
    if mismatch == "customer":
        data["customer"]["customer_id"] = "cus_other"
    else:
        data["metadata"][f"latexy_{mismatch}_id"] = str(uuid.uuid4())

    result = await service._handle_payment_succeeded(db_session, data, {"timestamp": datetime.now(timezone.utc).isoformat()})

    assert result["success"] is False
    assert await db_session.scalar(text("SELECT COUNT(*) FROM payments WHERE subscription_id=:id"), {"id": intent_id}) == 0
    assert await db_session.scalar(text("SELECT provider_customer_id FROM subscriptions WHERE id=:id"), {"id": intent_id}) == f"cus_{intent_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type,current_status", [
    ("subscription.paused", "active"),
    ("subscription.past_due", "active"),
    ("subscription.cancelled", "active"),
    ("subscription.failed", "past_due"),
    ("subscription.renewed", "paused"),
])
async def test_delayed_event_uses_current_payload_status(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, event_type: str, current_status: str,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id, paid=True)
    service = _service(monkeypatch)
    result = await service._handle_subscription_event(
        db_session, event_type,
        {"subscription_id": f"sub_{intent_id}", "product_id": "p_test_pro", "status": current_status,
         "customer": {"customer_id": f"cus_{intent_id}"},
         "past_due_ends_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert result == {"success": True}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == current_status
    assert await db_session.scalar(text("SELECT subscription_status FROM users WHERE id=:id"), {"id": user_id}) == current_status
    assert await db_session.scalar(text("SELECT subscription_plan FROM users WHERE id=:id"), {"id": user_id}) == "pro"


@pytest.mark.asyncio
async def test_provider_updated_synchronizes_scheduled_cancellation_and_undo(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id, paid=True)
    service = _service(monkeypatch)
    now = datetime.now(timezone.utc)
    for index, scheduled in enumerate((True, False)):
        result = await service._handle_subscription_event(
            db_session, "subscription.updated",
            {"subscription_id": f"sub_{intent_id}", "product_id": "p_test_pro", "status": "active",
             "customer": {"customer_id": f"cus_{intent_id}"}, "cancel_at_next_billing_date": scheduled},
            {"timestamp": (now + timedelta(seconds=index)).isoformat()},
        )
        assert result == {"success": True}
        expected = "cancel_scheduled" if scheduled else "active"
        assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == expected
        assert await db_session.scalar(text("SELECT subscription_status FROM users WHERE id=:id"), {"id": user_id}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ["active", "cancel_scheduled", "paused", "on_hold", "past_due"])
async def test_scheduling_cancellation_does_not_restore_suspended_access(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, initial_status: str,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id, paid=True)
    await db_session.execute(text("UPDATE subscriptions SET status=:status WHERE id=:id"),
                             {"status": initial_status, "id": intent_id})
    await db_session.execute(text("UPDATE users SET subscription_status=:status WHERE id=:id"),
                             {"status": initial_status, "id": user_id})
    await db_session.commit()
    service = _service(monkeypatch)
    monkeypatch.setattr(service.provider, "update_subscription", AsyncMock(return_value={"cancel_at_next_billing_date": True}))

    result = await service.cancel_subscription(db_session, user_id)

    assert result["success"] is True
    expected_status = "cancel_scheduled" if initial_status == "active" else initial_status
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == expected_status
    assert await db_session.scalar(text("SELECT subscription_status FROM users WHERE id=:id"), {"id": user_id}) == expected_status


@pytest.mark.asyncio
async def test_terminal_webhook_during_cancellation_cannot_be_overwritten(
    db_session: AsyncSession, db_session_factory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id, paid=True)
    service = _service(monkeypatch)

    async def update_subscription(_subscription_id: str, _payload: dict) -> dict:
        async with db_session_factory() as concurrent:
            await concurrent.execute(text("UPDATE subscriptions SET status='cancelled' WHERE id=:id"), {"id": intent_id})
            await concurrent.execute(text(
                "UPDATE users SET subscription_status='cancelled', subscription_plan='free', subscription_id=NULL WHERE id=:id"
            ), {"id": user_id})
            await concurrent.commit()
        return {"cancel_at_next_billing_date": True}

    monkeypatch.setattr(service.provider, "update_subscription", update_subscription)
    result = await service.cancel_subscription(db_session, user_id)

    assert result["success"] is True
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("free", "cancelled", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["checkout_pending", "checkout_unknown", "created", "pending"])
async def test_free_downgrade_cannot_abandon_a_still_payable_hosted_checkout(db_session, monkeypatch, status):
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id)
    await db_session.execute(text(
        "UPDATE subscriptions SET status=:status,provider_subscription_id=NULL WHERE id=:id"
    ), {"status": status, "id": intent_id})
    await db_session.commit()
    service = _service(monkeypatch)
    cancel = AsyncMock()
    monkeypatch.setattr(service.provider, "update_subscription", cancel)
    result = await service.create_subscription(db_session, user_id, "free", "test@example.com", "Test")
    assert result["success"] is False
    cancel.assert_not_awaited()
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == status
    assert await db_session.scalar(text("SELECT subscription_id FROM users WHERE id=:id"), {"id": user_id}) == intent_id
    create = AsyncMock()
    monkeypatch.setattr(service.provider, "create_checkout_session", create)
    retry = await service.create_subscription(db_session, user_id, "pro", "test@example.com", "Test")
    assert retry["success"] is False
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_free_downgrade_requires_confirmed_provider_cancellation(db_session, monkeypatch):
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id)
    service = _service(monkeypatch)
    monkeypatch.setattr(service.provider, "update_subscription", AsyncMock(return_value={"status": "active"}))
    result = await service.create_subscription(db_session, user_id, "free", "test@example.com", "Test")
    assert result["success"] is False
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "checkout_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_mandate_id", [None, "sub_historical_mandate"])
async def test_read_only_history_guard_ignores_rows_without_a_mandate(db_session, monkeypatch, historical_mandate_id):
    user_id = await _user(db_session)
    if historical_mandate_id:
        historical_mandate_id = f"{historical_mandate_id}_{uuid.uuid4().hex}"
    await db_session.execute(text(
        "INSERT INTO subscriptions (id,user_id,provider,provider_subscription_id,plan_id,status) "
        "VALUES (:id,:uid,'razorpay',:pid,:plan,'active')"
    ), {"id": str(uuid.uuid4()), "uid": user_id, "pid": historical_mandate_id,
        "plan": "pro" if historical_mandate_id else "free"})
    await db_session.commit()
    service = _service(monkeypatch)
    create = AsyncMock(return_value={
        "session_id": f"sess_{uuid.uuid4().hex}",
        "checkout_url": "https://checkout.dodopayments.com/fixture",
    })
    monkeypatch.setattr(service.provider, "create_checkout_session", create)
    result = await service.create_subscription(db_session, user_id, "pro", "test@example.com", "Test")
    assert result["success"] is (historical_mandate_id is None)
    assert create.await_count == (1 if historical_mandate_id is None else 0)


@pytest.mark.asyncio
async def test_existing_dodo_cancellation_works_when_new_checkout_disabled(db_session, monkeypatch):
    user_id = await _user(db_session)
    intent_id = await _intent(db_session, user_id, paid=True)
    monkeypatch.setattr(settings, "BILLING_MODE", "disabled")
    monkeypatch.setattr(settings, "DODO_TEST_API_KEY", "test-servicing-key")
    service = PaymentService()
    cancel = AsyncMock(return_value={"cancel_at_next_billing_date": True})
    monkeypatch.setattr(service.provider, "update_subscription", cancel)
    assert not service.is_available()
    result = await service.cancel_subscription(db_session, user_id)
    assert result["success"] is True
    cancel.assert_awaited_once_with(f"sub_{intent_id}", {"cancel_at_next_billing_date": True})
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancel_scheduled"

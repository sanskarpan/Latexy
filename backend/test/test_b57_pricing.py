"""Focused contract tests for B57 pricing SKUs.

These tests intentionally use no real Razorpay credentials or commercial
prices. A zero operator amount means the SKU is not exposed or purchasable.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_plan_config, is_b57_sku_configured, settings
from app.services.payment_service import PaymentService


def test_b57_skus_are_hidden_without_operator_configuration(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_PLAN_WEEKLY", "")
    monkeypatch.setattr(settings, "RAZORPAY_WEEKLY_AMOUNT", 0)
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 0)

    assert not is_b57_sku_configured("weekly")
    assert not is_b57_sku_configured("lifetime")
    assert get_plan_config("lifetime")["price"] == 0


def test_b57_prices_are_operator_configured_minor_units(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_PLAN_WEEKLY", "plan_weekly_approved")
    monkeypatch.setattr(settings, "RAZORPAY_WEEKLY_AMOUNT", 1300)
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 14900)

    assert is_b57_sku_configured("weekly")
    assert is_b57_sku_configured("lifetime")
    assert get_plan_config("weekly")["price"] == 1300
    assert get_plan_config("lifetime")["price"] == 14900


def test_weekly_period_is_seven_days():
    service = PaymentService.__new__(PaymentService)
    assert service._period_delta_for_plan("weekly").days == 7


def test_lifetime_response_never_contains_a_recurring_subscription_url():
    response = PaymentService._lifetime_order_response(
        {"id": "order_approved", "amount": 14900, "currency": "INR"},
        "user-1",
    )
    assert response["checkout_type"] == "one_time"
    assert response["order_id"] == "order_approved"
    assert response["amount"] == 14900
    assert "short_url" not in response


@pytest.mark.asyncio
async def test_subscription_plan_payload_includes_canonical_ids(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_PLAN_WEEKLY", "plan_weekly_approved")
    monkeypatch.setattr(settings, "RAZORPAY_WEEKLY_AMOUNT", 1300)
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 14900)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service._base_status = {"available": True}

    plans = await service.get_subscription_plans()

    assert plans["free"]["id"] == "free"
    assert plans["weekly"]["id"] == "weekly"
    assert plans["lifetime"]["id"] == "lifetime"


@pytest.mark.asyncio
async def test_lifetime_checkout_is_unavailable_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 0)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service._base_status = {"message": "Billing is available."}
    result = await service._create_lifetime_order(None, "user-1", "ignored@example.com", "Ignored")
    assert result["success"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_student_checkout_does_not_send_verification_when_billing_unavailable():
    service = PaymentService.__new__(PaymentService)
    service.client = None
    service._base_status = {"message": "Billing is unavailable."}

    result = await service.create_subscription(
        db=None,
        user_id="user-1",
        plan_id="student",
        customer_email="user@example.com",
        customer_name="User",
        student_email="student@example.edu",
    )

    assert result == {"success": False, "error": "Billing is unavailable."}


@pytest.mark.asyncio
async def test_student_verification_token_cannot_create_two_checkouts():
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service._base_status = {"message": "Billing is available."}
    token = "student-token"
    token_key = f"student_plan_verify:{token}"
    store = {
        token_key: '{"user_id":"user-1","customer_email":"user@example.com",'
        '"customer_name":"User"}',
    }

    async def set_key(key, value, nx=False, ex=None):
        if nx and key in store:
            return None
        store[key] = value
        return True

    async def get_key(key):
        return store.get(key)

    async def delete_key(key):
        store.pop(key, None)

    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(side_effect=set_key)
    fake_redis.get = AsyncMock(side_effect=get_key)
    fake_redis.delete = AsyncMock(side_effect=delete_key)
    create = AsyncMock(return_value={"success": True, "subscription_id": "sub_student"})

    with (
        patch("app.services.payment_service.get_redis_cache_client", new=AsyncMock(return_value=fake_redis)),
        patch.object(service, "_acquire_checkout_lock", new=AsyncMock(return_value=True)),
        patch.object(service, "_release_checkout_lock", new=AsyncMock()),
        patch.object(service, "_get_live_provider_subscription", new=AsyncMock(return_value=None)),
        patch.object(service, "_create_paid_subscription", new=create),
    ):
        first = await service.verify_student_subscription(None, token)
        second = await service.verify_student_subscription(None, token)

    assert first["success"] is True
    assert second == {"success": False, "error": "Student verification link is invalid or expired"}
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifetime_checkout_rejects_coupons_instead_of_charging_full_price(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 14900)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service._base_status = {"message": "Billing is available."}

    result = await service.create_subscription(
        db=None,
        user_id="user-1",
        plan_id="lifetime",
        customer_email="user@example.com",
        customer_name="User",
        coupon_code="SAVE20",
    )

    assert result == {
        "success": False,
        "error": "Coupons cannot be applied to the Lifetime plan.",
    }


@pytest.mark.asyncio
async def test_weekly_checkout_rejects_coupons_before_creating_subscription(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_PLAN_WEEKLY", "plan_weekly_approved")
    monkeypatch.setattr(settings, "RAZORPAY_WEEKLY_AMOUNT", 1300)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service._base_status = {"message": "Billing is available."}

    result = await service.create_subscription(
        db=None,
        user_id="user-1",
        plan_id="weekly",
        customer_email="user@example.com",
        customer_name="User",
        billing_period="weekly",
        coupon_code="SAVE20",
    )

    assert result == {
        "success": False,
        "error": "Coupons cannot be applied to the Weekly plan.",
    }
    service.client.subscription.create.assert_not_called()


async def _add_paid_entitlement(
    db: AsyncSession,
    *,
    plan_id: str = "lifetime",
    amount: int = 14900,
) -> tuple[str, str, str]:
    user_id = str(uuid.uuid4())
    subscription_id = str(uuid.uuid4())
    payment_id = f"pay_b57_{uuid.uuid4().hex}"
    provider_id = (
        f"order_b57_{uuid.uuid4().hex}" if plan_id == "lifetime"
        else f"sub_b57_{uuid.uuid4().hex}"
    )
    await db.execute(
        text(
            "INSERT INTO users "
            "(id, email, name, email_verified, subscription_plan, subscription_status, "
            " trial_used, subscription_id) "
            "VALUES (:id, :email, 'B57', true, :plan, 'active', false, :provider_id)"
        ),
        {
            "id": user_id,
            "email": f"b57-{user_id}@example.com",
            "plan": plan_id,
            "provider_id": provider_id,
        },
    )
    await db.execute(
        text(
            "INSERT INTO subscriptions "
            "(id, user_id, razorpay_subscription_id, plan_id, status) "
            "VALUES (:id, :user_id, :provider_id, :plan, 'active')"
        ),
        {
            "id": subscription_id,
            "user_id": user_id,
            "provider_id": provider_id,
            "plan": plan_id,
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments "
            "(id, user_id, subscription_id, razorpay_payment_id, amount, currency, status) "
            "VALUES (:id, :user_id, :subscription_id, :payment_id, :amount, 'INR', 'paid')"
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "subscription_id": subscription_id,
            "payment_id": payment_id,
            "amount": amount,
        },
    )
    await db.commit()
    return user_id, subscription_id, payment_id


async def _add_free_user(db: AsyncSession) -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users "
            "(id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'B57 Recovery', true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": f"b57-recovery-{user_id}@example.com"},
    )
    await db.commit()
    return user_id


@pytest.mark.asyncio
async def test_unknown_lifetime_order_recovers_from_server_authored_provider_notes(
    db_session: AsyncSession, monkeypatch
):
    user_id = await _add_free_user(db_session)
    order_id = f"order_recovery_{uuid.uuid4().hex}"
    payment_id = f"pay_recovery_{uuid.uuid4().hex}"
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 14900)

    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service.client.order.fetch.return_value = {
        "id": order_id,
        "amount": 14900,
        "currency": "INR",
        "notes": {"user_id": user_id, "plan_id": "lifetime"},
    }
    with patch(
        "app.services.payment_service.referral_service.qualify_paid_payment",
        new=AsyncMock(return_value={"status": "ignored"}),
    ):
        result = await service._handle_lifetime_payment_captured(
            db_session,
            {
                "payment": {"entity": {"id": payment_id, "order_id": order_id, "amount": 14900, "currency": "INR"}},
                "order": {"entity": {"id": order_id, "amount": 14900, "currency": "INR"}},
            },
        )

    assert result == {"success": True, "message": "Lifetime plan activated"}
    state = (
        await db_session.execute(
            text(
                "SELECT u.subscription_plan, u.subscription_id, s.status, p.razorpay_payment_id "
                "FROM users u JOIN subscriptions s ON s.user_id = u.id "
                "JOIN payments p ON p.subscription_id = s.id WHERE u.id = :uid"
            ),
            {"uid": user_id},
        )
    ).one()
    assert state == ("lifetime", order_id, "active", payment_id)


@pytest.mark.asyncio
async def test_partial_refund_does_not_revoke_entitlement(db_session: AsyncSession):
    user_id, subscription_id, payment_id = await _add_paid_entitlement(db_session)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()

    result = await service._handle_lifetime_refund(
        db_session,
        {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "currency": "INR",
                    "status": "captured",
                    "refund_status": "partial",
                    "amount_refunded": 1000,
                }
            },
            "refund": {
                "entity": {
                    "payment_id": payment_id,
                    "amount": 1000,
                    "currency": "INR",
                    "status": "processed",
                }
            },
        },
    )

    assert result == {"success": True, "message": "Partial or pending refund recorded"}
    state = (
        await db_session.execute(
            text(
                "SELECT u.subscription_plan, u.subscription_status, s.status, p.status "
                "FROM users u JOIN subscriptions s ON s.user_id = u.id "
                "JOIN payments p ON p.subscription_id = s.id "
                "WHERE u.id = :user_id AND s.id = :subscription_id"
            ),
            {"user_id": user_id, "subscription_id": subscription_id},
        )
    ).one()
    assert state == ("lifetime", "active", "active", "partially_refunded")


@pytest.mark.asyncio
async def test_verified_full_refund_revokes_entitlement(db_session: AsyncSession):
    user_id, subscription_id, payment_id = await _add_paid_entitlement(db_session)
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()

    with patch(
        "app.services.payment_service.referral_service.reverse_paid_payment",
        new=AsyncMock(return_value={"status": "ignored"}),
    ):
        result = await service._handle_lifetime_refund(
            db_session,
            {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "currency": "INR",
                        "status": "refunded",
                        "refund_status": "full",
                        "amount_refunded": 14900,
                    }
                }
            },
        )

    assert result == {"success": True, "message": "Entitlement revoked after refund"}
    state = (
        await db_session.execute(
            text(
                "SELECT u.subscription_plan, u.subscription_status, u.subscription_id, "
                "s.status, p.status FROM users u "
                "JOIN subscriptions s ON s.user_id = u.id "
                "JOIN payments p ON p.subscription_id = s.id "
                "WHERE u.id = :user_id AND s.id = :subscription_id"
            ),
            {"user_id": user_id, "subscription_id": subscription_id},
        )
    ).one()
    assert state == ("free", "refunded", None, "refunded", "refunded")


@pytest.mark.asyncio
async def test_late_payment_failure_does_not_revoke_captured_lifetime_order(
    db_session: AsyncSession,
):
    user_id, subscription_id, _payment_id = await _add_paid_entitlement(db_session)
    service = PaymentService.__new__(PaymentService)
    order_id = await db_session.scalar(
        text("SELECT razorpay_subscription_id FROM subscriptions WHERE id = :id"),
        {"id": subscription_id},
    )
    await db_session.rollback()

    result = await service._handle_lifetime_payment_failed(
        db_session,
        {"payment": {"entity": {"order_id": order_id}}},
    )

    assert result == {"success": True, "message": "Lifetime payment failed"}
    state = (
        await db_session.execute(
            text(
                "SELECT u.subscription_plan, u.subscription_status, u.subscription_id, "
                "s.status FROM users u JOIN subscriptions s ON s.user_id = u.id "
                "WHERE u.id = :user_id AND s.id = :subscription_id"
            ),
            {"user_id": user_id, "subscription_id": subscription_id},
        )
    ).one()
    assert state == ("lifetime", "active", order_id, "active")

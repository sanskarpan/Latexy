"""Focused contract tests for Dodo's signed webhook and REST adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.dodo_provider import DodoAPIError, DodoProvider
from app.services.payment_service import PaymentService


def _signed_headers(
    payload: bytes,
    secret: bytes,
    *,
    timestamp: int | None = None,
    webhook_id: str = "evt_test_001",
) -> dict[str, str]:
    sent_at = str(timestamp if timestamp is not None else int(time.time()))
    key = base64.b64encode(secret).decode()
    digest = hmac.new(secret, webhook_id.encode() + b"." + sent_at.encode() + b"." + payload, hashlib.sha256).digest()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": sent_at,
        "webhook-signature": f"v1,{base64.b64encode(digest).decode()}",
    }


def test_dodo_webhook_signature_accepts_exact_raw_body(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = b"dodo-webhook-test-secret"
    payload = json.dumps({"type": "payment.succeeded"}).encode()
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "whsec_" + base64.b64encode(secret).decode())

    assert PaymentService._verify_webhook_signature(payload, _signed_headers(payload, secret))
    assert not PaymentService._verify_webhook_signature(payload + b" ", _signed_headers(payload, secret))


def test_dodo_webhook_signature_rejects_stale_or_incomplete_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = b"dodo-webhook-test-secret"
    payload = b"{}"
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "whsec_" + base64.b64encode(secret).decode())
    stale = _signed_headers(payload, secret, timestamp=int(time.time()) - 600)

    assert not PaymentService._verify_webhook_signature(payload, stale)
    assert not PaymentService._verify_webhook_signature(payload, {"webhook-id": "evt_only"})


@pytest.mark.asyncio
async def test_signed_non_object_envelope_is_rejected_without_webhook_crash(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"dodo-webhook-envelope-test"
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "whsec_" + base64.b64encode(secret).decode())
    payload = b"null"

    result = await PaymentService().handle_webhook(
        db_session, payload, _signed_headers(payload, secret, webhook_id="evt_non_object_envelope"),
    )

    assert result == {"success": False, "retryable": False, "error": "Invalid webhook envelope"}


@pytest.mark.asyncio
@pytest.mark.parametrize("customer", [[], "customer", 7])
async def test_webhook_rejects_non_object_customer_shape(
    db_session: AsyncSession, customer: object,
) -> None:
    result = await PaymentService()._process_webhook_event(
        db_session, "subscription.paused",
        {"payload_type": "Subscription", "customer": customer}, {},
    )

    assert result == {"success": False, "error": "Invalid webhook customer"}


@pytest.mark.asyncio
async def test_dodo_checkout_adapter_posts_to_configured_api(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    import app.services.dodo_provider as provider_module

    requests: list[tuple[str, str, dict]] = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, *, headers, json):
            requests.append((method, str(url), {"headers": headers, "json": json}))
            return httpx.Response(200, json={"session_id": "sess_1", "checkout_url": "https://checkout.example/sess_1"})

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    adapter = DodoProvider(api_key="test_api_key", base_url="https://test.dodopayments.com/")
    payload = {"product_cart": [{"product_id": "p_test_1", "quantity": 1}], "metadata": {"latexy_intent_id": "local-1"}}

    response = await adapter.create_checkout_session(payload)

    assert response["session_id"] == "sess_1"
    assert requests[0][0:2] == ("POST", "https://test.dodopayments.com/checkouts")
    assert requests[0][2]["headers"]["Authorization"] == "Bearer test_api_key"
    assert requests[0][2]["json"] == payload


def test_provider_error_does_not_echo_response_body() -> None:
    from app.services.dodo_provider import DodoAPIError

    error = DodoAPIError(401, "invalid_api_key")
    assert "401" in str(error)
    assert "invalid_api_key" in str(error)
    assert "secret" not in str(error).lower()


@pytest.mark.asyncio
async def test_signed_dodo_payment_grants_once_and_deduplicates(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"dodo-webhook-integration-secret"
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "whsec_" + base64.b64encode(secret).decode())
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id = str(uuid.uuid4()), str(uuid.uuid4())
    checkout_id = f"sess_test_{intent_id}"
    payment_id = f"pay_test_{intent_id}"
    event_id = f"evt_test_{intent_id}"
    provider_subscription_id = f"sub_test_{intent_id}"
    await db_session.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Dodo Billing Test', true, 'free', 'inactive', false)"
    ), {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"})
    await db_session.execute(text(
        "INSERT INTO subscriptions (id, user_id, provider, provider_checkout_session_id, provider_product_id, "
        "quoted_amount, discount_percent, plan_id, status, current_period_start) "
        "VALUES (:id, :user_id, 'dodo', :checkout_id, 'p_test_pro', 59900, 0, 'pro', 'checkout_pending', NOW())"
    ), {"id": intent_id, "user_id": user_id, "checkout_id": checkout_id})
    await db_session.commit()

    raw_payload = json.dumps({
        "business_id": "biz_test",
        "type": "payment.succeeded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "payload_type": "Payment",
            "payment_id": payment_id,
            "status": "succeeded",
            "currency": "INR",
            "total_amount": 59900,
            "tax": 5490,
            "customer": {"customer_id": f"cus_test_{intent_id}"},
            "metadata": {"latexy_intent_id": intent_id, "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"},
            "checkout_session_id": checkout_id,
            "subscription_id": provider_subscription_id,
            "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
        },
    }).encode()
    headers = _signed_headers(raw_payload, secret, webhook_id=event_id)
    service = PaymentService()

    first = await service.handle_webhook(db_session, raw_payload, headers)
    second = await service.handle_webhook(db_session, raw_payload, headers)

    assert first == {"success": True}
    assert second == {"success": True, "duplicate": True}
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("pro", "active", intent_id)
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider='dodo' AND provider_payment_id=:payment_id"
    ), {"payment_id": payment_id}) == 1
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM billing_webhook_events WHERE provider='dodo' AND event_id=:event_id AND status='processed'"
    ), {"event_id": event_id}) == 1


async def _insert_test_intent(
    db: AsyncSession,
    *,
    status: str = "checkout_pending",
    period_end: datetime | None = None,
) -> tuple[str, str, str, str]:
    user_id, intent_id = str(uuid.uuid4()), str(uuid.uuid4())
    checkout_id, subscription_id = f"sess_test_{intent_id}", f"sub_test_{intent_id}"
    await db.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Dodo Billing Test', true, 'free', 'inactive', false)"
    ), {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"})
    await db.execute(text(
        "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, provider_checkout_session_id, "
        "provider_product_id, quoted_amount, quoted_tax_inclusive, discount_percent, plan_id, status, current_period_start, current_period_end) "
        "VALUES (:id, :user_id, 'dodo', :subscription_id, :checkout_id, 'p_test_pro', 59900, true, 0, 'pro', "
        ":status, NOW(), :period_end)"
    ), {"id": intent_id, "user_id": user_id, "subscription_id": subscription_id,
        "checkout_id": checkout_id, "status": status, "period_end": period_end})
    await db.commit()
    return user_id, intent_id, checkout_id, subscription_id


async def _insert_test_coupon(db: AsyncSession, code: str | None = None) -> tuple[str, str]:
    coupon_id = str(uuid.uuid4())
    code = code or f"TEST{uuid.uuid4().hex[:12].upper()}"
    await db.execute(text(
        "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, max_uses, used_count) "
        "VALUES (:id, :code, 20, ARRAY['pro'], 10, 0)"
    ), {"id": coupon_id, "code": code})
    await db.commit()
    return coupon_id, code


def _provider_discount_fixture(code: str, **overrides: object) -> dict[str, object]:
    return {
        "code": code,
        "type": "percentage",
        "amount": 2000,
        "subscription_cycles": None,
        "restricted_to": [],
        "currency_options": [],
        "starts_at": None,
        "expires_at": None,
        "usage_limit": None,
        "times_used": 0,
        "customer_eligibility": "any",
        "per_customer_usage_limit": None,
        "preserve_on_plan_change": True,
        **overrides,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_error", "expected_intent_status", "expected_redemption_status", "expected_uses"),
    [
        (DodoAPIError(400, "invalid_discount"), "failed", "released", 0),
        (DodoAPIError(503, "provider_unavailable"), "checkout_unknown", "reserved", 1),
    ],
)
async def test_checkout_failure_releases_only_definitive_coupon_reservations(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    provider_error: DodoAPIError,
    expected_intent_status: str,
    expected_redemption_status: str,
    expected_uses: int,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id = str(uuid.uuid4())
    await db_session.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Coupon Billing Test', true, 'free', 'inactive', false)"
    ), {"id": user_id, "email": f"coupon_{user_id.replace('-', '')}@example.com"})
    coupon_id, coupon_code = await _insert_test_coupon(db_session)
    service = PaymentService()
    monkeypatch.setattr(service, "is_available", lambda: True)
    monkeypatch.setattr(service, "_acquire_checkout_lock", AsyncMock(return_value="lock-token"))
    monkeypatch.setattr(service, "_release_checkout_lock", AsyncMock())
    monkeypatch.setattr(service.provider, "get_discount_by_code", AsyncMock(
        return_value=_provider_discount_fixture(coupon_code),
    ))
    monkeypatch.setattr(service.provider, "create_checkout_session", AsyncMock(side_effect=provider_error))

    result = await service.create_subscription(
        db_session, user_id, "pro", f"coupon_{user_id}@example.com", "Coupon Billing Test",
        coupon_code=coupon_code,
    )

    assert result["success"] is False
    intent = (await db_session.execute(text(
        "SELECT id, status FROM subscriptions WHERE user_id=:user_id AND provider='dodo'"
    ), {"user_id": user_id})).one()
    redemption = (await db_session.execute(text(
        "SELECT status FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id})).one()
    assert intent.status == expected_intent_status
    assert redemption.status == expected_redemption_status
    assert await db_session.scalar(text(
        "SELECT used_count FROM coupon_codes WHERE id=:coupon_id"
    ), {"coupon_id": coupon_id}) == expected_uses


@pytest.mark.asyncio
async def test_incompatible_provider_coupon_fails_before_reservation_or_checkout(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id = str(uuid.uuid4())
    await db_session.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
        "VALUES (:id, :email, 'Coupon Gate Test', true, 'free', 'inactive', false)"
    ), {"id": user_id, "email": f"coupon_gate_{user_id.replace('-', '')}@example.com"})
    coupon_id, coupon_code = await _insert_test_coupon(db_session)
    service = PaymentService()
    monkeypatch.setattr(service, "is_available", lambda: True)
    monkeypatch.setattr(service, "_acquire_checkout_lock", AsyncMock(return_value="lock-token"))
    release_lock = AsyncMock()
    monkeypatch.setattr(service, "_release_checkout_lock", release_lock)
    provider_lookup = AsyncMock(return_value=_provider_discount_fixture(coupon_code, amount=1500))
    create_checkout = AsyncMock(return_value={"session_id": "unexpected", "checkout_url": "https://example.com"})
    monkeypatch.setattr(service.provider, "get_discount_by_code", provider_lookup)
    monkeypatch.setattr(service.provider, "create_checkout_session", create_checkout)

    result = await service.create_subscription(
        db_session, user_id, "pro", f"coupon_gate_{user_id}@example.com", "Coupon Gate Test",
        coupon_code=coupon_code,
    )

    assert result["success"] is False
    assert provider_lookup.await_count == 1
    assert create_checkout.await_count == 0
    assert release_lock.await_count == 1
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM subscriptions WHERE user_id=:user_id AND provider='dodo'"
    ), {"user_id": user_id}) == 0
    assert await db_session.scalar(text(
        "SELECT used_count FROM coupon_codes WHERE id=:coupon_id"
    ), {"coupon_id": coupon_id}) == 0
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id}) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"subscription_cycles": 3},
        {"expires_at": "2027-01-01T00:00:00Z"},
        {"starts_at": "2027-01-01T00:00:00Z"},
        {"restricted_to": ["p_other"]},
        {"currency_options": {"INR": {"maximum_discount_amount": 1000}}},
        {"customer_eligibility": "first_time"},
        {"per_customer_usage_limit": 1},
        {"usage_limit": 5, "times_used": 5},
        {"preserve_on_plan_change": False},
    ],
)
def test_provider_coupon_gate_rejects_recurring_or_eligibility_mismatches(changes: dict[str, object]) -> None:
    service = PaymentService()
    discount = _provider_discount_fixture("SAVE20", **changes)

    error = service._provider_coupon_compatibility_error(
        discount, code="SAVE20", discount_percent=20, product_id="p_test_pro",
    )

    assert error


@pytest.mark.asyncio
async def test_free_downgrade_releases_coupon_for_cancelled_pending_checkout(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, intent_id, _, subscription_id = await _insert_test_intent(db_session)
    coupon_id, coupon_code = await _insert_test_coupon(db_session)
    await db_session.execute(text(
        "UPDATE users SET subscription_status='checkout_pending', subscription_id=:intent_id WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    assert await PaymentService()._reserve_coupon(db_session, coupon_code, "pro", user_id, intent_id) == (True, "")
    await db_session.commit()
    service = PaymentService()
    monkeypatch.setattr(service.provider, "update_subscription", AsyncMock(return_value={"status": "cancelled"}))

    result = await service.create_subscription(db_session, user_id, "free", "unused@example.com", "Test User")

    assert result["success"] is True
    assert await db_session.scalar(text(
        "SELECT status FROM subscriptions WHERE id=:intent_id"
    ), {"intent_id": intent_id}) == "cancelled"
    assert await db_session.scalar(text(
        "SELECT status FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id}) == "released"
    assert await db_session.scalar(text(
        "SELECT used_count FROM coupon_codes WHERE id=:coupon_id"
    ), {"coupon_id": coupon_id}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    ["payment.failed", "payment.cancelled"],
)
async def test_payment_attempt_failure_keeps_checkout_recoverable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, _ = await _insert_test_intent(db_session)
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='pro', subscription_status='checkout_pending', subscription_id=:intent_id "
        "WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    await db_session.commit()

    result = await PaymentService()._process_webhook_event(
        db_session,
        event_type,
        {"payload_type": "Payment", "metadata": {"latexy_intent_id": intent_id},
         "checkout_session_id": checkout_id},
        {},
    )

    assert result == {"success": True}
    row = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:user_id"
    ), {"user_id": user_id})).one()
    assert tuple(row) == ("pro", "checkout_pending", intent_id)
    assert await db_session.scalar(text(
        "SELECT status FROM subscriptions WHERE id=:intent_id"
    ), {"intent_id": intent_id}) == "checkout_pending"


@pytest.mark.asyncio
async def test_payment_failed_is_retryable_and_success_redeems_coupon_once(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(db_session)
    coupon_id, coupon_code = await _insert_test_coupon(db_session)
    await db_session.execute(text(
        "UPDATE subscriptions SET discount_percent=20 WHERE id=:intent_id"
    ), {"intent_id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_status='checkout_pending', subscription_id=:intent_id WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    assert await PaymentService()._reserve_coupon(db_session, coupon_code, "pro", user_id, intent_id) == (True, "")
    await db_session.commit()
    service = PaymentService()

    failed = await service._process_webhook_event(
        db_session, "payment.failed",
        {"payload_type": "Payment", "metadata": {"latexy_intent_id": intent_id},
         "checkout_session_id": checkout_id}, {},
    )
    intent_status = await db_session.scalar(text(
        "SELECT status FROM subscriptions WHERE id=:intent_id"
    ), {"intent_id": intent_id})
    user_status = await db_session.scalar(text(
        "SELECT subscription_status FROM users WHERE id=:user_id"
    ), {"user_id": user_id})
    assert failed == {"success": True}
    assert intent_status == "checkout_pending"
    assert user_status == "checkout_pending"

    succeeded = await service._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_retry_{intent_id}", "status": "succeeded",
         "currency": "INR", "total_amount": 47920, "tax": 4404,
         "customer": {"customer_id": f"cus_test_{intent_id}"},
         "checkout_session_id": checkout_id, "subscription_id": subscription_id,
         "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
         "metadata": {"latexy_intent_id": intent_id, "latexy_user_id": user_id,
                      "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"}},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert succeeded == {"success": True}
    redemption = (await db_session.execute(text(
        "SELECT status, subscription_id FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id})).one()
    assert redemption.status == "redeemed"
    assert str(redemption.subscription_id) == intent_id
    assert await db_session.scalar(text(
        "SELECT used_count FROM coupon_codes WHERE id=:coupon_id"
    ), {"coupon_id": coupon_id}) == 1
    assert await db_session.scalar(text(
        "SELECT subscription_status FROM users WHERE id=:user_id"
    ), {"user_id": user_id}) == "active"


@pytest.mark.asyncio
async def test_stale_success_is_recorded_without_reopening_newer_past_due_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(db_session, status="past_due")
    newer_event = datetime.now(timezone.utc) + timedelta(minutes=1)
    older_event = newer_event - timedelta(days=1)
    await db_session.execute(text(
        "UPDATE subscriptions SET provider_event_at=:newer WHERE id=:intent_id"
    ), {"newer": newer_event, "intent_id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='pro', subscription_status='past_due', subscription_id=:intent_id "
        "WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    await db_session.commit()

    result = await PaymentService()._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_stale_{intent_id}", "status": "succeeded",
         "currency": "INR", "total_amount": 59900, "tax": 5490,
         "customer": {"customer_id": f"cus_test_{intent_id}"},
         "checkout_session_id": checkout_id, "subscription_id": subscription_id,
         "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
         "metadata": {"latexy_intent_id": intent_id, "latexy_user_id": user_id,
                      "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"}},
        {"timestamp": older_event.isoformat()},
    )

    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:user_id"
    ), {"user_id": user_id})).one()
    intent = (await db_session.execute(text(
        "SELECT status, provider_event_at FROM subscriptions WHERE id=:intent_id"
    ), {"intent_id": intent_id})).one()
    assert result == {"success": True}
    assert tuple(user) == ("pro", "past_due", intent_id)
    assert intent.status == "past_due"
    assert intent.provider_event_at.replace(tzinfo=timezone.utc) == newer_event
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id AND status='paid'"
    ), {"payment_id": f"pay_stale_{intent_id}"}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_event", ["subscription.failed", "subscription.cancelled"])
async def test_terminal_subscription_event_releases_coupon_and_late_success_stays_unentitled(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    terminal_event: str,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(db_session)
    coupon_id, coupon_code = await _insert_test_coupon(db_session)
    await db_session.execute(text(
        "UPDATE subscriptions SET discount_percent=20 WHERE id=:intent_id"
    ), {"intent_id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_status='checkout_pending', subscription_id=:intent_id WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    assert await PaymentService()._reserve_coupon(db_session, coupon_code, "pro", user_id, intent_id) == (True, "")
    await db_session.commit()
    service = PaymentService()

    closed = await service._handle_subscription_event(
        db_session, terminal_event,
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "failed" if terminal_event.endswith("failed") else "cancelled",
         "cancel_at_next_billing_date": False},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )
    late_payment = await service._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_late_{intent_id}", "status": "succeeded",
         "currency": "INR", "total_amount": 47920, "tax": 4404,
         "checkout_session_id": checkout_id, "subscription_id": subscription_id,
         "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
         "metadata": {"latexy_intent_id": intent_id, "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"}},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert closed == {"success": True}
    assert late_payment == {"success": True}
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:user_id"
    ), {"user_id": user_id})).one()
    assert tuple(user) == ("free", "failed" if terminal_event.endswith("failed") else "cancelled", None)
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id AND status='paid'"
    ), {"payment_id": f"pay_late_{intent_id}"}) == 1
    assert await db_session.scalar(text(
        "SELECT status FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id}) == "released"
    assert await db_session.scalar(text(
        "SELECT used_count FROM coupon_codes WHERE id=:coupon_id"
    ), {"coupon_id": coupon_id}) == 0


@pytest.mark.asyncio
async def test_cancelled_unused_checkout_late_success_is_ledgered_without_entitlement(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(db_session, status="cancelled")
    service = PaymentService()
    payload = {
        "payload_type": "Payment", "payment_id": f"pay_late_{intent_id}", "status": "succeeded",
        "currency": "INR", "total_amount": 59900, "tax": 0,
        "checkout_session_id": checkout_id, "subscription_id": subscription_id,
        "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
        "metadata": {"latexy_intent_id": intent_id, "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"},
    }
    timestamp = {"timestamp": datetime.now(timezone.utc).isoformat()}
    bad_quote = await service._handle_payment_succeeded(
        db_session, {**payload, "total_amount": 59899}, timestamp,
    )
    assert bad_quote["success"] is False
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"
    ), {"payment_id": f"pay_late_{intent_id}"}) == 0

    result = await service._handle_payment_succeeded(db_session, payload, timestamp)

    assert result == {"success": True}
    payment = (await db_session.execute(text(
        "SELECT user_id, subscription_id, amount, currency, status FROM payments WHERE provider_payment_id=:payment_id"
    ), {"payment_id": f"pay_late_{intent_id}"})).one()
    assert (str(payment[0]), str(payment[1]), *tuple(payment[2:])) == (user_id, intent_id, 59900, "INR", "paid")
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:user_id"
    ), {"user_id": user_id})).one()
    assert tuple(user) == ("free", "inactive", None)
    intent = (await db_session.execute(text(
        "SELECT status, current_period_end FROM subscriptions WHERE id=:intent_id"
    ), {"intent_id": intent_id})).one()
    assert tuple(intent) == ("cancelled", None)


@pytest.mark.asyncio
async def test_dodo_renewal_uses_provider_period_end_without_extending_twice(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(
        db_session, status="active", period_end=datetime(2026, 10, 7, tzinfo=timezone.utc),
    )
    renewal_end = datetime(2026, 11, 7, tzinfo=timezone.utc)
    service = PaymentService()
    subscription_result = await service._handle_subscription_event(
        db_session,
        "subscription.renewed",
        {"payload_type": "Subscription", "subscription_id": subscription_id, "status": "active",
         "product_id": "p_test_pro", "next_billing_date": renewal_end.isoformat()},
        {"timestamp": "2026-10-07T12:00:00+00:00"},
    )
    payment_result = await service._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_test_{intent_id}", "status": "succeeded",
         "currency": "INR", "total_amount": 59900, "tax": 5490,
         "checkout_session_id": checkout_id, "subscription_id": subscription_id,
         "metadata": {"latexy_intent_id": intent_id, "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"},
         "product_cart": [{"product_id": "p_test_pro", "quantity": 1}]},
        {"timestamp": "2026-10-07T12:00:01+00:00"},
    )

    assert subscription_result == {"success": True}
    assert payment_result == {"success": True}
    actual_end = await db_session.scalar(text(
        "SELECT current_period_end FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})
    if actual_end.tzinfo is None:
        actual_end = actual_end.replace(tzinfo=timezone.utc)
    assert actual_end == renewal_end


@pytest.mark.asyncio
async def test_dodo_recurring_payment_without_product_cart_verifies_provider_subscription(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(
        db_session, status="active",
    )
    customer_id = f"cus_test_{intent_id}"
    await db_session.execute(text(
        "UPDATE subscriptions SET provider_customer_id=:customer_id WHERE id=:intent_id"
    ), {"customer_id": customer_id, "intent_id": intent_id})
    await db_session.commit()
    service = PaymentService()
    get_subscription_calls: list[str] = []

    async def get_subscription(provider_subscription_id: str) -> dict:
        get_subscription_calls.append(provider_subscription_id)
        return {
            "subscription_id": subscription_id,
            "product_id": "p_test_pro",
            "quantity": 1,
            "customer": {"customer_id": customer_id},
        }

    monkeypatch.setattr(service.provider, "get_subscription", get_subscription)
    result = await service._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_test_{intent_id}",
         "status": "succeeded", "currency": "INR", "total_amount": 59900, "tax": 5490,
         "customer": {"customer_id": customer_id}, "checkout_session_id": checkout_id,
         "subscription_id": subscription_id, "product_cart": None,
         "metadata": {"latexy_intent_id": intent_id, "latexy_user_id": user_id,
                      "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"}},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert result == {"success": True}
    assert get_subscription_calls == [subscription_id]
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider='dodo' AND provider_payment_id=:payment_id"
    ), {"payment_id": f"pay_test_{intent_id}"}) == 1


@pytest.mark.asyncio
async def test_dodo_subscription_events_reject_mismatched_identity_and_sync_configured_plan(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_BASIC_MONTHLY", "p_test_basic")
    user_id, intent_id, _, subscription_id = await _insert_test_intent(db_session, status="active")
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='pro', subscription_status='active', subscription_id=:intent_id "
        "WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    await db_session.commit()
    service = PaymentService()

    wrong_subscription = await service._handle_subscription_event(
        db_session, "subscription.paused",
        {"payload_type": "Subscription", "subscription_id": f"sub_other_{intent_id}",
         "product_id": "p_test_pro", "status": "paused"},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )
    wrong_product = await service._handle_subscription_event(
        db_session, "subscription.paused",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_unconfigured", "status": "paused"},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )
    changed_plan = await service._handle_subscription_event(
        db_session, "subscription.plan_changed",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_basic", "status": "active", "currency": "INR",
         "tax_inclusive": True, "recurring_pre_tax_amount": 29900,
         "next_billing_date": "2026-11-07T00:00:00+00:00"},
        {"timestamp": "2026-10-07T12:00:00+00:00"},
    )

    assert wrong_subscription["success"] is False
    assert wrong_product["success"] is False
    assert changed_plan == {"success": True}
    subscription = (await db_session.execute(text(
        "SELECT plan_id, provider_product_id, quoted_amount FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})).one()
    assert tuple(subscription) == ("basic", "p_test_basic", 29900)
    assert await db_session.scalar(text(
        "SELECT subscription_plan FROM users WHERE id=:id"
    ), {"id": user_id}) == "basic"


@pytest.mark.asyncio
async def test_newer_subscription_updated_pause_syncs_user_before_older_paused_event(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, _, subscription_id = await _insert_test_intent(db_session, status="active")
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='pro', subscription_status='active', subscription_id=:intent_id "
        "WHERE id=:user_id"
    ), {"intent_id": intent_id, "user_id": user_id})
    await db_session.commit()
    service = PaymentService()
    newer_timestamp = datetime.now(timezone.utc)

    updated = await service._handle_subscription_event(
        db_session, "subscription.updated",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "paused"},
        {"timestamp": newer_timestamp.isoformat()},
    )
    older_paused = await service._handle_subscription_event(
        db_session, "subscription.paused",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "paused"},
        {"timestamp": (newer_timestamp - timedelta(seconds=1)).isoformat()},
    )

    state = (await db_session.execute(text(
        "SELECT s.status, u.subscription_status FROM subscriptions s JOIN users u ON u.id=s.user_id "
        "WHERE s.id=:intent_id"
    ), {"intent_id": intent_id})).one()
    assert updated == {"success": True}
    assert older_paused == {"success": True}
    assert tuple(state) == ("paused", "paused")


@pytest.mark.asyncio
@pytest.mark.parametrize("recover_from", ["past_due", "on_hold", "paused"])
async def test_active_subscription_recovery_syncs_status_for_existing_paid_user(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    recover_from: str,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, _, subscription_id = await _insert_test_intent(db_session, status=recover_from)
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='pro', subscription_status=:status, subscription_id=:intent_id "
        "WHERE id=:user_id"
    ), {"status": recover_from, "intent_id": intent_id, "user_id": user_id})
    await db_session.commit()

    result = await PaymentService()._handle_subscription_event(
        db_session, "subscription.active",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "active",
         "next_billing_date": "2026-11-07T00:00:00+00:00"},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status FROM users WHERE id=:user_id"
    ), {"user_id": user_id})).one()
    assert result == {"success": True}
    assert tuple(user) == ("pro", "active")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("total_amount", "tax", "tax_inclusive_flag"),
    [(59900, -1, "true"), (59900, 59901, "true"), (59899, 0, "true"), (59900, 0, "false")],
)
async def test_dodo_payment_rejects_invalid_tax_or_underpayment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    total_amount: int,
    tax: int,
    tax_inclusive_flag: str,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _insert_test_intent(db_session)
    service = PaymentService()
    result = await service._handle_payment_succeeded(
        db_session,
        {"payload_type": "Payment", "payment_id": f"pay_test_{intent_id}", "status": "succeeded",
         "currency": "INR", "total_amount": total_amount, "tax": tax,
         "checkout_session_id": checkout_id, "subscription_id": subscription_id,
         "metadata": {"latexy_intent_id": intent_id, "latexy_plan_id": "pro",
                      "latexy_tax_inclusive": tax_inclusive_flag},
         "product_cart": [{"product_id": "p_test_pro", "quantity": 1}]},
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert result["success"] is False
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"
    ), {"payment_id": f"pay_test_{intent_id}"}) == 0
    user = (await db_session.execute(text(
        "SELECT subscription_plan FROM users WHERE id=:id"
    ), {"id": user_id})).scalar_one()
    assert user == "free"


@pytest.mark.asyncio
async def test_dodo_refund_rejects_amount_overrun_and_currency_mismatch(
    db_session: AsyncSession,
) -> None:
    user_id, intent_id, _, _ = await _insert_test_intent(db_session, status="active")
    payment_id = f"pay_test_{intent_id}"
    await db_session.execute(text(
        "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, amount, currency, status) "
        "VALUES (:id, :user_id, :subscription_id, 'dodo', :payment_id, 59900, 'INR', 'paid')"
    ), {"id": str(uuid.uuid4()), "user_id": user_id, "subscription_id": intent_id, "payment_id": payment_id})
    await db_session.commit()
    service = PaymentService()

    over_refund = await service._handle_refund_event(
        db_session, "refund.succeeded",
        {"refund_id": f"ref_over_{intent_id}", "payment_id": payment_id, "amount": 59901,
         "currency": "INR", "status": "succeeded"},
    )
    partial_refund = await service._handle_refund_event(
        db_session, "refund.succeeded",
        {"refund_id": f"ref_partial_{intent_id}", "payment_id": payment_id, "amount": 30000,
         "currency": "INR", "status": "succeeded"},
    )
    cumulative_over_refund = await service._handle_refund_event(
        db_session, "refund.succeeded",
        {"refund_id": f"ref_cumulative_{intent_id}", "payment_id": payment_id, "amount": 30000,
         "currency": "INR", "status": "succeeded"},
    )
    wrong_currency = await service._handle_refund_event(
        db_session, "refund.succeeded",
        {"refund_id": f"ref_currency_{intent_id}", "payment_id": payment_id, "amount": 100,
         "currency": "USD", "status": "succeeded"},
    )
    refund_regression = await service._handle_refund_event(
        db_session, "refund.failed",
        {"refund_id": f"ref_partial_{intent_id}", "payment_id": payment_id, "amount": 30000,
         "currency": "INR", "status": "failed"},
    )

    assert over_refund["success"] is False
    assert partial_refund["success"] is True
    assert cumulative_over_refund["success"] is False
    assert wrong_currency["success"] is False
    assert refund_regression == {"success": True}
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payment_refunds WHERE provider='dodo' AND payment_id IN "
        "(SELECT id FROM payments WHERE provider_payment_id=:payment_id)"
    ), {"payment_id": payment_id}) == 1
    assert await db_session.scalar(text(
        "SELECT status FROM payment_refunds WHERE provider='dodo' AND provider_refund_id=:refund_id"
    ), {"refund_id": f"ref_partial_{intent_id}"}) == "succeeded"
    assert await db_session.scalar(text(
        "SELECT status FROM payments WHERE provider_payment_id=:payment_id"
    ), {"payment_id": payment_id}) == "partially_refunded"

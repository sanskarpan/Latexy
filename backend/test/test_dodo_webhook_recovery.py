"""Durable Dodo webhook replay and malformed-event regression coverage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.services.payment_service import PaymentService


def _signed_headers(payload: bytes, secret: bytes, webhook_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hmac.new(
        secret,
        webhook_id.encode() + b"." + timestamp.encode() + b"." + payload,
        hashlib.sha256,
    ).digest()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{base64.b64encode(digest).decode()}",
    }


async def _create_checkout_intent(db: AsyncSession) -> tuple[str, str, str, str]:
    user_id, intent_id = str(uuid.uuid4()), str(uuid.uuid4())
    checkout_id, subscription_id = f"sess_test_{intent_id}", f"sub_test_{intent_id}"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Dodo recovery test', true, 'free', 'checkout_pending', false)"
        ),
        {"id": user_id, "email": f"test_{user_id.replace('-', '')}@example.com"},
    )
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "provider_checkout_session_id, provider_product_id, quoted_amount, quoted_tax_inclusive, "
            "discount_percent, plan_id, status, current_period_start) "
            "VALUES (:id, :user_id, 'dodo', :subscription_id, :checkout_id, 'p_test_pro', "
            "59900, true, 0, 'pro', 'checkout_pending', NOW())"
        ),
        {
            "id": intent_id,
            "user_id": user_id,
            "subscription_id": subscription_id,
            "checkout_id": checkout_id,
        },
    )
    await db.commit()
    return user_id, intent_id, checkout_id, subscription_id


def _payment_payload(
    user_id: str,
    intent_id: str,
    checkout_id: str,
    subscription_id: str,
    payment_id: str,
) -> bytes:
    return json.dumps(
        {
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
                "metadata": {
                    "latexy_intent_id": intent_id,
                    "latexy_user_id": user_id,
                    "latexy_plan_id": "pro",
                    "latexy_tax_inclusive": "true",
                },
                "checkout_session_id": checkout_id,
                "subscription_id": subscription_id,
                "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
            },
        }
    ).encode()


@pytest.fixture(autouse=True)
def configure_signed_test_webhooks(monkeypatch: pytest.MonkeyPatch) -> bytes:
    secret = b"dodo-webhook-recovery-test-secret"
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "whsec_" + base64.b64encode(secret).decode())
    monkeypatch.setattr(settings, "DODO_TEST_BUSINESS_ID", "biz_test")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    return secret


@pytest.mark.asyncio
async def test_webhook_failure_log_does_not_include_untrusted_event_type(
    configure_signed_test_webhooks: bytes,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event_type = "payment.succeeded\r\nFORGED: admin authorized refund"
    payload = json.dumps({"business_id": "biz_test", "type": event_type, "data": {}}).encode()

    class FakeSession:
        event: Any = None

        async def scalar(self, *_args: Any) -> Any:
            return self.event

        def add(self, event: Any) -> None:
            self.event = event

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    async def fail_processing(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("synthetic processing failure")

    monkeypatch.setattr(PaymentService, "_process_webhook_event", fail_processing)

    with caplog.at_level(logging.ERROR, logger="app.services.payment_service"):
        result = await PaymentService().handle_webhook(
            FakeSession(), payload,
            _signed_headers(payload, configure_signed_test_webhooks, f"evt_log_{uuid.uuid4().hex}"),
        )

    assert result == {"success": False, "retryable": True, "error": "Webhook processing failed"}
    assert "Dodo webhook processing failed" in caplog.text
    assert "FORGED" not in caplog.text
    assert "event_type" not in caplog.records[-1].__dict__
    assert caplog.records[-1].error_type == "ValueError"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("envelope", "expected_error"),
    [
        ({"data": {}}, "Missing webhook fields"),
        ({"type": "payment.succeeded"}, "Missing webhook fields"),
    ],
)
async def test_signed_webhook_rejects_missing_type_or_data(
    db_session: AsyncSession,
    configure_signed_test_webhooks: bytes,
    envelope: dict[str, Any],
    expected_error: str,
) -> None:
    payload = json.dumps(envelope).encode()
    result = await PaymentService().handle_webhook(
        db_session,
        payload,
        _signed_headers(payload, configure_signed_test_webhooks, f"evt_missing_{uuid.uuid4().hex}"),
    )

    assert result == {"success": False, "retryable": False, "error": expected_error}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["payment_id", "status", "currency", "total_amount"])
async def test_signed_success_event_with_missing_payment_field_never_grants_access(
    db_session: AsyncSession,
    configure_signed_test_webhooks: bytes,
    monkeypatch: pytest.MonkeyPatch,
    missing_field: str,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _create_checkout_intent(db_session)
    payload = json.loads(
        _payment_payload(user_id, intent_id, checkout_id, subscription_id, f"pay_missing_{intent_id}")
    )
    payload["data"].pop(missing_field)
    raw_payload = json.dumps(payload).encode()

    result = await PaymentService().handle_webhook(
        db_session,
        raw_payload,
        _signed_headers(raw_payload, configure_signed_test_webhooks, f"evt_missing_payment_{uuid.uuid4().hex}"),
    )

    assert result["success"] is False
    assert result["retryable"] is True
    assert await db_session.scalar(
        text("SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"),
        {"payment_id": f"pay_missing_{intent_id}"},
    ) == 0
    user = (
        await db_session.execute(
            text("SELECT subscription_plan, subscription_status FROM users WHERE id=:user_id"),
            {"user_id": user_id},
        )
    ).one()
    assert tuple(user) == ("free", "checkout_pending")


@pytest.mark.asyncio
async def test_same_webhook_id_with_different_valid_signature_is_rejected(
    db_session: AsyncSession,
    configure_signed_test_webhooks: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _create_checkout_intent(db_session)
    payment_id = f"pay_replay_{intent_id}"
    first_payload = _payment_payload(user_id, intent_id, checkout_id, subscription_id, payment_id)
    event_id = f"evt_collision_{uuid.uuid4().hex}"
    service = PaymentService()

    first = await service.handle_webhook(
        db_session, first_payload, _signed_headers(first_payload, configure_signed_test_webhooks, event_id)
    )
    changed_envelope = json.loads(first_payload)
    changed_envelope["data"]["total_amount"] = 59899
    changed_payload = json.dumps(changed_envelope).encode()
    collision = await service.handle_webhook(
        db_session, changed_payload, _signed_headers(changed_payload, configure_signed_test_webhooks, event_id)
    )

    assert first == {"success": True}
    assert collision == {"success": False, "retryable": False, "error": "Webhook ID payload mismatch"}
    assert await db_session.scalar(
        text("SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"),
        {"payment_id": payment_id},
    ) == 1


@pytest.mark.asyncio
async def test_distinct_webhook_ids_for_same_payment_do_not_duplicate_payment_or_entitlement(
    db_session: AsyncSession,
    configure_signed_test_webhooks: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    user_id, intent_id, checkout_id, subscription_id = await _create_checkout_intent(db_session)
    payment_id = f"pay_duplicate_{intent_id}"
    payload = _payment_payload(user_id, intent_id, checkout_id, subscription_id, payment_id)
    service = PaymentService()

    first = await service.handle_webhook(
        db_session,
        payload,
        _signed_headers(payload, configure_signed_test_webhooks, f"evt_first_{uuid.uuid4().hex}"),
    )
    second = await service.handle_webhook(
        db_session,
        payload,
        _signed_headers(payload, configure_signed_test_webhooks, f"evt_second_{uuid.uuid4().hex}"),
    )

    assert first == {"success": True}
    assert second == {"success": True}
    assert await db_session.scalar(
        text("SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"),
        {"payment_id": payment_id},
    ) == 1
    assert await db_session.scalar(
        text("SELECT COUNT(*) FROM billing_webhook_events WHERE event_type='payment.succeeded' AND status='processed'")
    ) >= 2
    user = (
        await db_session.execute(
            text("SELECT subscription_plan, subscription_status FROM users WHERE id=:user_id"),
            {"user_id": user_id},
        )
    ).one()
    assert tuple(user) == ("pro", "active")


@pytest.mark.asyncio
async def test_redelivery_after_process_interruption_recovers_durable_inbox_event(
    db_session_factory: async_sessionmaker[AsyncSession],
    configure_signed_test_webhooks: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")
    async with db_session_factory() as setup_db:
        user_id, intent_id, checkout_id, subscription_id = await _create_checkout_intent(setup_db)
    payload = _payment_payload(user_id, intent_id, checkout_id, subscription_id, f"pay_restart_{intent_id}")
    event_id = f"evt_restart_{uuid.uuid4().hex}"
    headers = _signed_headers(payload, configure_signed_test_webhooks, event_id)

    class SimulatedProcessInterruption(BaseException):
        pass

    class InterruptAfterInboxCommit(PaymentService):
        async def _process_webhook_event(self, db, event_type, data, envelope):
            raise SimulatedProcessInterruption()

    async with db_session_factory() as crashed_session:
        with pytest.raises(SimulatedProcessInterruption):
            await InterruptAfterInboxCommit().handle_webhook(crashed_session, payload, headers)

    async with db_session_factory() as restarted_session:
        inbox_state = await restarted_session.scalar(
            text("SELECT status FROM billing_webhook_events WHERE provider='dodo' AND event_id=:event_id"),
            {"event_id": event_id},
        )
        assert inbox_state == "processing"
        redelivery = await PaymentService().handle_webhook(restarted_session, payload, headers)
        assert redelivery == {"success": True}
        assert await restarted_session.scalar(
            text("SELECT status FROM billing_webhook_events WHERE provider='dodo' AND event_id=:event_id"),
            {"event_id": event_id},
        ) == "processed"
        assert await restarted_session.scalar(
            text("SELECT COUNT(*) FROM payments WHERE provider_payment_id=:payment_id"),
            {"payment_id": f"pay_restart_{intent_id}"},
        ) == 1

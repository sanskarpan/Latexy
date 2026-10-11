"""Owner-scoped authenticated Dodo checkout recovery regressions."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.dodo_provider import DodoAPIError
from app.services.payment_service import PaymentService


async def _insert_pending_checkout(db: AsyncSession) -> tuple[str, str, str, str]:
    user_id, intent_id = str(uuid.uuid4()), str(uuid.uuid4())
    checkout_id, subscription_id = f"sess_test_{intent_id}", f"sub_test_{intent_id}"
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db.execute(text(
        "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, "
        "subscription_id, trial_used) VALUES (:id, :email, 'Dodo Reconcile Test', true, 'free', "
        "'checkout_pending', :intent_id, false)"
    ), {"id": user_id, "email": email, "intent_id": intent_id})
    await db.execute(text(
        "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
        "provider_checkout_session_id, provider_product_id, quoted_amount, quoted_tax_inclusive, "
        "discount_percent, plan_id, status, current_period_start) "
        "VALUES (:id, :user_id, 'dodo', :subscription_id, :checkout_id, 'p_test_pro', "
        "59900, true, 0, 'pro', 'checkout_pending', NOW())"
    ), {"id": intent_id, "user_id": user_id, "subscription_id": subscription_id, "checkout_id": checkout_id})
    await db.commit()
    return user_id, intent_id, checkout_id, subscription_id


def _provider_state(
    user_id: str,
    intent_id: str,
    checkout_id: str,
    subscription_id: str,
    *,
    payment_status: str = "succeeded",
    subscription_status: str = "active",
) -> dict[str, dict[str, Any]]:
    email = f"test_{user_id.replace('-', '')}@example.com"
    metadata = {
        "latexy_intent_id": intent_id,
        "latexy_user_id": user_id,
        "latexy_plan_id": "pro",
        "latexy_tax_inclusive": "true",
    }
    payment_id = f"pay_test_{intent_id}"
    customer = {"customer_id": f"cus_test_{intent_id}", "email": email}
    return {
        "checkout": {
            "id": checkout_id,
            "customer_email": email,
            "payment_id": payment_id,
            "payment_status": payment_status,
        },
        "payment": {
            "payment_id": payment_id,
            "status": payment_status,
            "currency": "INR",
            "total_amount": 59900,
            "tax": 5490,
            "customer": dict(customer),
            "metadata": dict(metadata),
            "checkout_session_id": checkout_id,
            "subscription_ids": [subscription_id],
            "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "subscription": {
            "subscription_id": subscription_id,
            "status": subscription_status,
            "currency": "INR",
            "product_id": "p_test_pro",
            "quantity": 1,
            "tax_inclusive": True,
            "customer": dict(customer),
            "metadata": dict(metadata),
            "next_billing_date": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
    }


class FakeProvider:
    available = True

    def __init__(self, state: dict[str, dict[str, Any]]):
        self.state = state
        self.calls: list[tuple[str, str]] = []

    async def get_checkout_session(self, session_id: str) -> dict[str, Any]:
        self.calls.append(("checkout", session_id))
        return self.state["checkout"]

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        self.calls.append(("payment", payment_id))
        return self.state["payment"]

    async def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        self.calls.append(("subscription", subscription_id))
        return self.state["subscription"]


def _stub_reconcile_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PaymentService, "_acquire_reconcile_lock", AsyncMock(return_value="lock-token"))
    monkeypatch.setattr(PaymentService, "_release_reconcile_lock", AsyncMock())
    monkeypatch.setattr(PaymentService, "_acquire_reconcile_cooldown", AsyncMock(return_value=True))


def _configure_test_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DODO_MODE", "test")
    monkeypatch.setattr(settings, "DODO_TEST_API_KEY", "test-api-key")
    monkeypatch.setattr(settings, "DODO_TEST_WEBHOOK_KEY", "test-webhook-key")
    monkeypatch.setattr(settings, "DODO_TEST_BUSINESS_ID", "biz_test")
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "p_test_pro")


@pytest.mark.asyncio
async def test_reconcile_uses_only_owner_current_intent_and_is_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    provider = FakeProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))
    service = PaymentService(provider=provider)  # type: ignore[arg-type]

    result = await service.reconcile_checkout(db_session, user_id)
    duplicate = await service.reconcile_checkout(db_session, user_id)

    assert result == {
        "success": True,
        "status": "reconciled",
        "subscriptionId": subscription_id,
        "planId": "pro",
        "currentPeriodEnd": provider.state["subscription"]["next_billing_date"],
        "message": "Subscription restored from the provider's current payment state.",
    }
    assert duplicate["success"] is True
    assert duplicate["status"] == "reconciled"
    assert len(provider.calls) == 3
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider='dodo' AND provider_payment_id=:payment_id"
    ), {"payment_id": provider.state["payment"]["payment_id"]}) == 1
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("pro", "active", intent_id)
    intent = (await db_session.execute(text(
        "SELECT status, provider_subscription_id, current_period_end FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})).one()
    assert intent.status == "active"
    assert intent.provider_subscription_id == subscription_id
    assert intent.current_period_end.replace(tzinfo=timezone.utc).isoformat() == provider.state["subscription"]["next_billing_date"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tax", [5490, None])
async def test_reconcile_accepts_null_recurring_payment_cart_from_verified_subscription(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, tax: int | None,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    # Keep the fixture's real local metadata/session bindings while modeling
    # Dodo's actual successful recurring-payment response shape.
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    state["payment"]["product_cart"] = None
    state["payment"]["tax"] = tax
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is True
    assert provider.calls == [
        ("checkout", checkout_id),
        ("payment", state["payment"]["payment_id"]),
        ("subscription", subscription_id),
    ]
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"
    ), {"id": state["payment"]["payment_id"]}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: state["subscription"].update(product_id="p_test_other"),
        lambda state: state["subscription"]["customer"].update(customer_id="cus_other"),
        lambda state: state["subscription"]["metadata"].update(latexy_user_id=str(uuid.uuid4())),
        lambda state: state["subscription"].update(quantity=2),
    ],
)
async def test_null_payment_cart_still_requires_matching_subscription_product_and_owner(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mutation,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    state["payment"]["product_cart"] = None
    mutation(state)
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["status"] == "unavailable"
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"
    ), {"id": state["payment"]["payment_id"]}) == 0


@pytest.mark.asyncio
async def test_reconcile_rejects_empty_payment_cart(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    state["payment"]["product_cart"] = []
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["status"] == "unavailable"
    assert provider.calls == [("checkout", checkout_id), ("payment", state["payment"]["payment_id"])]
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"
    ), {"id": state["payment"]["payment_id"]}) == 0


@pytest.mark.asyncio
async def test_active_lifecycle_without_paid_ledger_or_entitlement_is_reconciled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    await db_session.execute(text("UPDATE subscriptions SET status='active' WHERE id=:id"), {"id": intent_id})
    await db_session.commit()
    _stub_reconcile_lock(monkeypatch)
    provider = FakeProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is True
    assert provider.calls == [
        ("checkout", checkout_id),
        ("payment", provider.state["payment"]["payment_id"]),
        ("subscription", subscription_id),
    ]
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"
    ), {"id": provider.state["payment"]["payment_id"]}) == 1
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("pro", "active")


@pytest.mark.asyncio
async def test_locked_reconciliation_refreshes_stale_terminal_intent_from_database(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.models import Subscription

    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    stale_intent = await db_session.get(Subscription, intent_id)
    assert stale_intent is not None and stale_intent.status == "checkout_pending"
    await db_session.execute(text("UPDATE subscriptions SET status='cancelled' WHERE id=:id"), {"id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='free', subscription_status='cancelled', subscription_id=NULL WHERE id=:id"
    ), {"id": user_id})
    await db_session.commit()
    _stub_reconcile_lock(monkeypatch)
    provider = FakeProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["status"] == "closed"
    assert provider.calls == []
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"


@pytest.mark.asyncio
async def test_payment_handler_refreshes_stale_intent_before_granting_access(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.models import Subscription

    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    stale_intent = await db_session.get(Subscription, intent_id)
    assert stale_intent is not None and stale_intent.status == "checkout_pending"
    await db_session.execute(text("UPDATE subscriptions SET status='cancelled' WHERE id=:id"), {"id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='free', subscription_status='cancelled', subscription_id=NULL WHERE id=:id"
    ), {"id": user_id})
    await db_session.commit()

    result = await PaymentService()._handle_payment_succeeded(
        db_session,
        {
            "payload_type": "Payment", "payment_id": f"pay_stale_recovery_{intent_id}", "status": "succeeded",
            "currency": "INR", "total_amount": 59900, "tax": 5490,
            "customer": {"customer_id": f"cus_test_{intent_id}"},
            "metadata": {"latexy_intent_id": intent_id, "latexy_user_id": user_id,
                         "latexy_plan_id": "pro", "latexy_tax_inclusive": "true"},
            "checkout_session_id": checkout_id, "subscription_id": subscription_id,
            "product_cart": [{"product_id": "p_test_pro", "quantity": 1}],
        },
        {"timestamp": datetime.now(timezone.utc).isoformat()},
    )

    assert result == {"success": True}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"
    assert await db_session.scalar(text("SELECT subscription_plan FROM users WHERE id=:id"), {"id": user_id}) == "free"
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"
    ), {"id": f"pay_stale_recovery_{intent_id}"}) == 1


@pytest.mark.asyncio
async def test_lifecycle_handler_refreshes_stale_intent_before_terminal_guard(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.database.models import Subscription

    _configure_test_billing(monkeypatch)
    user_id, intent_id, _, subscription_id = await _insert_pending_checkout(db_session)
    stale_intent = await db_session.get(Subscription, intent_id)
    assert stale_intent is not None and stale_intent.status == "checkout_pending"
    customer_id = f"cus_test_{intent_id}"
    await db_session.execute(text(
        "UPDATE subscriptions SET status='cancelled', provider_customer_id=:customer_id WHERE id=:id"
    ), {"customer_id": customer_id, "id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='free', subscription_status='cancelled', subscription_id=NULL WHERE id=:id"
    ), {"id": user_id})
    await db_session.commit()

    result = await PaymentService()._handle_subscription_event(
        db_session,
        "subscription.updated",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "active", "customer": {"customer_id": customer_id}},
        {"timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
    )

    assert result == {"success": True}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("free", "cancelled", None)


@pytest.mark.asyncio
async def test_local_cancel_scheduled_status_survives_successful_reconciliation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    await db_session.execute(text("UPDATE subscriptions SET status='cancel_scheduled' WHERE id=:id"), {"id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_status='cancel_scheduled' WHERE id=:id"
    ), {"id": user_id})
    await db_session.commit()
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is True
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancel_scheduled"
    assert await db_session.scalar(text("SELECT subscription_status FROM users WHERE id=:id"), {"id": user_id}) == "cancel_scheduled"


@pytest.mark.asyncio
async def test_newer_pause_webhook_during_common_handler_survives_recovery_relock(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    service = PaymentService(provider=FakeProvider(state))  # type: ignore[arg-type]
    original_handler = service._handle_payment_succeeded
    newer_period_end = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    async def settle_then_pause(db, payment_data, envelope, *, current_state_verified=False):
        result = await original_handler(
            db, payment_data, envelope, current_state_verified=current_state_verified,
        )
        await service._handle_subscription_event(
            db,
                "subscription.updated",
                {"payload_type": "Subscription", "subscription_id": subscription_id,
                 "product_id": "p_test_pro", "status": "paused",
                 "customer": {"customer_id": state["subscription"]["customer"]["customer_id"]},
                 "next_billing_date": newer_period_end},
                {"timestamp": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
        )
        return result

    monkeypatch.setattr(service, "_handle_payment_succeeded", settle_then_pause)

    result = await service.reconcile_checkout(db_session, user_id)

    assert result["success"] is True
    intent = (await db_session.execute(text(
        "SELECT status, current_period_end FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})).one()
    assert intent.status == "paused"
    assert intent.current_period_end.replace(tzinfo=timezone.utc).isoformat() == newer_period_end
    assert await db_session.scalar(text(
        "SELECT subscription_status FROM users WHERE id=:id"
    ), {"id": user_id}) == "paused"


@pytest.mark.asyncio
async def test_local_pause_without_event_timestamp_survives_recovery_relock(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    service = PaymentService(provider=FakeProvider(state))  # type: ignore[arg-type]
    original_handler = service._handle_payment_succeeded
    local_period_end = datetime.now(timezone.utc) + timedelta(days=5)

    async def settle_then_apply_local_pause(db, payment_data, envelope, *, current_state_verified=False):
        result = await original_handler(
            db, payment_data, envelope, current_state_verified=current_state_verified,
        )
        await db.execute(text(
            "UPDATE subscriptions SET status='paused', provider_event_at=NULL, current_period_end=:period_end "
            "WHERE id=:intent_id"
        ), {"period_end": local_period_end, "intent_id": intent_id})
        await db.execute(text(
            "UPDATE users SET subscription_status='paused' WHERE id=:user_id"
        ), {"user_id": user_id})
        await db.commit()
        return result

    monkeypatch.setattr(service, "_handle_payment_succeeded", settle_then_apply_local_pause)

    result = await service.reconcile_checkout(db_session, user_id)

    assert result["success"] is True
    intent = (await db_session.execute(text(
        "SELECT status, provider_event_at, current_period_end FROM subscriptions WHERE id=:id"
    ), {"id": intent_id})).one()
    assert intent.status == "paused"
    assert intent.provider_event_at is None
    assert intent.current_period_end.replace(tzinfo=timezone.utc) == local_period_end
    assert await db_session.scalar(text(
        "SELECT subscription_status FROM users WHERE id=:id"
    ), {"id": user_id}) == "paused"


@pytest.mark.asyncio
async def test_reconciliation_lock_and_cooldown_failures_are_bounded_and_fail_closed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    provider = FakeProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))
    service = PaymentService(provider=provider)  # type: ignore[arg-type]

    async def redis_error(_service, _user_id: str):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(PaymentService, "_acquire_reconcile_lock", redis_error)
    lock_error = await service.reconcile_checkout(db_session, user_id)
    assert lock_error["status"] == "unavailable"
    assert provider.calls == []

    _stub_reconcile_lock(monkeypatch)
    monkeypatch.setattr(PaymentService, "_acquire_reconcile_cooldown", AsyncMock(return_value=False))
    cooled_down = await service.reconcile_checkout(db_session, user_id)
    assert cooled_down["success"] is False
    assert cooled_down["status"] == "pending"
    assert provider.calls == []


@pytest.mark.asyncio
async def test_reconciliation_uses_long_lease_and_separate_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.payment_service as payment_service_module

    calls: list[tuple[Any, ...]] = []

    class FakeRedis:
        async def set(self, key: str, value: str, **kwargs: Any) -> bool:
            calls.append((key, value, kwargs))
            return True

    async def redis_client() -> FakeRedis:
        return FakeRedis()

    monkeypatch.setattr(payment_service_module, "get_redis_cache_client", redis_client)
    service = PaymentService()

    token = await service._acquire_reconcile_lock("owner")
    cooldown = await service._acquire_reconcile_cooldown("owner")

    assert token
    assert cooldown is True
    assert calls[0][2] == {"nx": True, "ex": 75}
    assert calls[1][2] == {"nx": True, "ex": 20}


@pytest.mark.asyncio
async def test_reconcile_cannot_read_another_users_checkout(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    owner_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    other_id, other_intent_id, other_checkout_id, other_subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    other_state = _provider_state(other_id, other_intent_id, other_checkout_id, other_subscription_id)
    provider = FakeProvider(other_state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, other_id)  # type: ignore[arg-type]

    assert result["success"] is True
    assert provider.calls[0] == ("checkout", other_state["checkout"]["id"])
    assert all(call[1] != checkout_id for call in provider.calls)
    assert await db_session.scalar(text(
        "SELECT status FROM subscriptions WHERE id=:id"
    ), {"id": intent_id}) == "checkout_pending"


@pytest.mark.asyncio
async def test_reconcile_route_requires_auth_and_does_not_accept_provider_identifiers(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/subscription/reconcile",
        json={"checkout_session_id": "provider-chosen", "payment_id": "provider-chosen"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_reconcile_route_ignores_client_provider_identifiers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.routes as routes_module

    captured: list[tuple[Any, ...]] = []

    async def reconcile(_db, owner_id: str) -> dict[str, Any]:
        captured.append((owner_id,))
        return {"success": False, "status": "closed", "message": "No pending checkout was found."}

    monkeypatch.setattr(routes_module.feature_flag_service, "get_flag", AsyncMock(return_value=True))
    monkeypatch.setattr(routes_module.payment_service, "reconcile_checkout", reconcile)
    response = await client.post(
        "/subscription/reconcile",
        headers=auth_headers,
        json={"checkout_session_id": "attacker-session", "payment_id": "attacker-payment"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert len(captured) == 1
    assert captured[0][0] not in {"attacker-session", "attacker-payment"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda state, user_id: state["payment"]["metadata"].update(latexy_user_id=str(uuid.uuid4())),
        lambda state, user_id: state["payment"]["metadata"].update(latexy_intent_id=str(uuid.uuid4())),
        lambda state, user_id: state["payment"]["metadata"].update(latexy_plan_id="basic"),
        lambda state, user_id: state["subscription"]["metadata"].update(latexy_user_id=str(uuid.uuid4())),
        lambda state, user_id: state["subscription"]["customer"].update(email="other@example.com"),
        lambda state, user_id: state["payment"]["customer"].update(email="other@example.com"),
        lambda state, user_id: state["subscription"].update(quantity=2),
        lambda state, user_id: state["subscription"].update(subscription_id=f"sub_other_{uuid.uuid4().hex}"),
        lambda state, user_id: state["checkout"].update(id=f"sess_other_{uuid.uuid4().hex}"),
        lambda state, user_id: state["payment"].update(total_amount=59899),
        lambda state, user_id: state["payment"].update(currency="USD"),
        lambda state, user_id: state["subscription"].update(tax_inclusive=False),
        lambda state, user_id: state["subscription"].update(status="cancelled"),
    ],
)
async def test_reconcile_rejects_forged_or_mismatched_provider_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    mutation(state, user_id)
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["status"] == "unavailable"
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE provider='dodo' AND provider_payment_id=:payment_id"
    ), {"payment_id": state["payment"]["payment_id"]}) == 0
    assert await db_session.scalar(text(
        "SELECT status FROM subscriptions WHERE id=:id"
    ), {"id": intent_id}) == "checkout_pending"
    assert await db_session.scalar(text(
        "SELECT subscription_plan FROM users WHERE id=:id"
    ), {"id": user_id}) == "free"


@pytest.mark.asyncio
async def test_reconcile_keeps_checkout_pending_when_provider_read_times_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)

    class TimeoutProvider(FakeProvider):
        async def get_payment(self, payment_id: str) -> dict[str, Any]:
            self.calls.append(("payment", payment_id))
            raise DodoAPIError(503, "provider_unavailable")

    provider = TimeoutProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))
    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result == {
        "success": False,
        "status": "unavailable",
        "message": "Payment status could not be checked yet.",
    }
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "checkout_pending"
    assert await db_session.scalar(text("SELECT subscription_plan FROM users WHERE id=:id"), {"id": user_id}) == "free"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_status", ["processing", "requires_customer_action"])
async def test_reconcile_leaves_nonterminal_payment_pending(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    provider_status: str,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id, payment_status=provider_status)
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result["success"] is False
    assert result["status"] == "pending"
    assert provider.calls == [("checkout", checkout_id), ("payment", state["payment"]["payment_id"])]
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "checkout_pending"
    assert await db_session.scalar(text("SELECT COUNT(*) FROM payments WHERE provider_payment_id=:id"), {"id": state["payment"]["payment_id"]}) == 0


@pytest.mark.asyncio
async def test_verified_failed_checkout_closes_intent_and_releases_coupon(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    coupon_id, coupon_code = f"{uuid.uuid4()}", f"RECON{uuid.uuid4().hex[:10].upper()}"
    await db_session.execute(text(
        "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, max_uses, used_count) "
        "VALUES (:id, :code, 10, ARRAY['pro'], 10, 1)"
    ), {"id": coupon_id, "code": coupon_code})
    await db_session.execute(text(
        "UPDATE subscriptions SET discount_percent=10 WHERE id=:id"
    ), {"id": intent_id})
    await db_session.execute(text(
        "INSERT INTO coupon_redemptions (id, coupon_id, user_id, subscription_id, status) "
        "VALUES (:id, :coupon_id, :user_id, :intent_id, 'reserved')"
    ), {"id": str(uuid.uuid4()), "coupon_id": coupon_id, "user_id": user_id, "intent_id": intent_id})
    await db_session.commit()
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(
        user_id, intent_id, checkout_id, subscription_id,
        payment_status="failed", subscription_status="failed",
    )
    provider = FakeProvider(state)

    result = await PaymentService(provider=provider).reconcile_checkout(db_session, user_id)  # type: ignore[arg-type]

    assert result == {"success": False, "status": "closed", "message": "The provider confirmed this checkout failed."}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "failed"
    assert await db_session.scalar(text(
        "SELECT status FROM coupon_redemptions WHERE coupon_id=:coupon_id AND user_id=:user_id"
    ), {"coupon_id": coupon_id, "user_id": user_id}) == "released"
    assert await db_session.scalar(text("SELECT used_count FROM coupon_codes WHERE id=:id"), {"id": coupon_id}) == 0
    assert await db_session.scalar(text("SELECT subscription_id FROM users WHERE id=:id"), {"id": user_id}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "event_status"),
    [
        ("subscription.updated", "active"),
        ("subscription.paused", "paused"),
        ("subscription.past_due", "past_due"),
    ],
)
async def test_newer_subscription_events_cannot_resurrect_terminal_intent(
    db_session: AsyncSession,
    event_type: str,
    event_status: str,
) -> None:
    user_id, intent_id, _, subscription_id = await _insert_pending_checkout(db_session)
    await db_session.execute(text(
        "UPDATE subscriptions SET status='cancelled', provider_customer_id=:customer_id WHERE id=:id"
    ), {"customer_id": f"cus_test_{intent_id}", "id": intent_id})
    await db_session.execute(text(
        "UPDATE users SET subscription_plan='free', subscription_status='cancelled', subscription_id=NULL WHERE id=:id"
    ), {"id": user_id})
    await db_session.commit()
    result = await PaymentService()._handle_subscription_event(
        db_session,
        event_type,
        {
            "payload_type": "Subscription",
            "subscription_id": subscription_id,
            "product_id": "p_test_pro",
            "status": event_status,
            "customer": {"customer_id": f"cus_test_{intent_id}"},
        },
        {"timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
    )

    assert result == {"success": True}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("free", "cancelled", None)


@pytest.mark.asyncio
async def test_late_subscription_webhook_after_recovery_cannot_resurrect_cancelled_access(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_test_billing(monkeypatch)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    service = PaymentService(provider=FakeProvider(state))  # type: ignore[arg-type]
    recovered = await service.reconcile_checkout(db_session, user_id)
    assert recovered["success"] is True
    customer_id = state["subscription"]["customer"]["customer_id"]

    cancelled = await service._handle_subscription_event(
        db_session,
        "subscription.cancelled",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "cancelled", "cancel_at_next_billing_date": False,
         "customer": {"customer_id": customer_id}},
        {"timestamp": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()},
    )
    late_active = await service._handle_subscription_event(
        db_session,
        "subscription.updated",
        {"payload_type": "Subscription", "subscription_id": subscription_id,
         "product_id": "p_test_pro", "status": "active", "customer": {"customer_id": customer_id}},
        {"timestamp": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()},
    )

    assert cancelled == {"success": True}
    assert late_active == {"success": True}
    assert await db_session.scalar(text("SELECT status FROM subscriptions WHERE id=:id"), {"id": intent_id}) == "cancelled"
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == ("free", "cancelled", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [None, "missing_cart", "wrong_product", "wrong_amount", "wrong_customer", "recurring"])
async def test_lifetime_reconciliation_requires_verified_one_time_payment(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, mutation: str | None,
) -> None:
    _configure_test_billing(monkeypatch)
    monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_LIFETIME", "p_test_lifetime")
    monkeypatch.setattr(settings, "LIFETIME_AMOUNT_MINOR", 59900)
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    await db_session.execute(text(
        "UPDATE subscriptions SET plan_id='lifetime', provider_product_id='p_test_lifetime', "
        "provider_subscription_id=NULL WHERE id=:id"
    ), {"id": intent_id})
    await db_session.commit()
    _stub_reconcile_lock(monkeypatch)
    state = _provider_state(user_id, intent_id, checkout_id, subscription_id)
    state["payment"]["metadata"]["latexy_plan_id"] = "lifetime"
    state["payment"]["product_cart"] = [{"product_id": "p_test_lifetime", "quantity": 1}]
    state["payment"]["subscription_ids"] = []
    state["payment"]["subscription_id"] = None
    state["payment"]["tax"] = None
    if mutation == "missing_cart":
        state["payment"]["product_cart"] = None
    elif mutation == "wrong_product":
        state["payment"]["product_cart"][0]["product_id"] = "p_test_other"
    elif mutation == "wrong_amount":
        state["payment"]["total_amount"] = 1
    elif mutation == "wrong_customer":
        state["payment"]["customer"]["email"] = "other@example.com"
    elif mutation == "recurring":
        state["payment"]["subscription_ids"] = [subscription_id]
    provider = FakeProvider(state)
    service = PaymentService(provider=provider)  # type: ignore[arg-type]

    result = await service.reconcile_checkout(db_session, user_id)

    assert result["success"] is (mutation is None)
    assert provider.calls == [("checkout", checkout_id), ("payment", state["payment"]["payment_id"])]
    user = (await db_session.execute(text(
        "SELECT subscription_plan, subscription_status FROM users WHERE id=:id"
    ), {"id": user_id})).one()
    assert tuple(user) == (("lifetime", "active") if mutation is None else ("free", "checkout_pending"))
    if mutation is None:
        assert result["subscriptionId"] is None
        assert result["currentPeriodEnd"] is None
        again = await service.reconcile_checkout(db_session, user_id)
        assert again["success"] is True
        assert len(provider.calls) == 2
    assert await db_session.scalar(text(
        "SELECT COUNT(*) FROM payments WHERE subscription_id=:id"
    ), {"id": intent_id}) == (1 if mutation is None else 0)


@pytest.mark.asyncio
async def test_existing_dodo_recovery_works_when_new_checkout_disabled(db_session, monkeypatch):
    _configure_test_billing(monkeypatch)
    monkeypatch.setattr(settings, "BILLING_MODE", "disabled")
    user_id, intent_id, checkout_id, subscription_id = await _insert_pending_checkout(db_session)
    _stub_reconcile_lock(monkeypatch)
    provider = FakeProvider(_provider_state(user_id, intent_id, checkout_id, subscription_id))
    service = PaymentService(provider=provider)
    assert not service.is_available()
    result = await service.reconcile_checkout(db_session, user_id)
    assert result["success"] is True
    assert result["status"] == "reconciled"
    assert len(provider.calls) == 3

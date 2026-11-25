"""Checkout funnel counts, failure buckets, ranges, and admin access."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.checkout_funnel_service import checkout_funnel_service, classify_failure

NOW = datetime.now(timezone.utc)


def _anchor(year: int) -> datetime:
    """A future, isolated anchor so shared-database activity cannot overlap."""
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=uuid.uuid4().int % (300 * 86_400)
    )


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "pro",
    created_at: datetime | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"checkout_funnel_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, created_at) "
            "VALUES (:id, :email, 'Checkout Funnel User', :role, true, :plan, 'active', false, :created)"
        ),
        {
            "id": user_id,
            "email": email,
            "role": role,
            "plan": plan,
            "created": created_at or NOW,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"checkout_funnel_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": NOW + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _insert_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    status: str,
    created_at: datetime,
    plan_id: str = "pro",
    checkout_session_id: str | None = None,
    provider_subscription_id: str | None = None,
    provider_product_id: str | None = None,
) -> str:
    subscription_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "provider_checkout_session_id, provider_product_id, plan_id, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :checkout, :product, :plan, :status, :created)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": provider_subscription_id,
            "checkout": checkout_session_id,
            "product": provider_product_id,
            "plan": plan_id,
            "status": status,
            "created": created_at,
        },
    )
    await db.commit()
    return subscription_id


async def _insert_payment(
    db: AsyncSession,
    *,
    user_id: str,
    subscription_id: str | None,
    status: str = "paid",
    amount: int = 59900,
    currency: str = "INR",
    created_at: datetime | None = None,
    provider_payment_id: str | None = None,
) -> str:
    payment_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, 'dodo', :provider_payment, :amount, :currency, :status, :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "sub": subscription_id,
            "provider_payment": provider_payment_id or f"pay_{uuid.uuid4().hex[:16]}",
            "amount": amount,
            "currency": currency,
            "status": status,
            "created": created_at or NOW,
        },
    )
    await db.commit()
    return payment_id


async def _insert_webhook(
    db: AsyncSession,
    *,
    event_type: str,
    resource_id: str,
    status: str = "failed",
    last_error: str | None = None,
    provider_event_id: str | None = None,
    received_at: datetime | None = None,
) -> str:
    webhook_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events (id, provider, event_id, event_type, "
            "event_resource_id, payload_sha256, status, attempts, last_error, received_at) "
            "VALUES (:id, 'dodo', :event_id, :event_type, :resource, :digest, :status, 1, :error, :received)"
        ),
        {
            "id": webhook_id,
            "event_id": provider_event_id or f"evt_{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "resource": resource_id,
            "digest": "a" * 64,
            "status": status,
            "error": last_error,
            "received": received_at or NOW,
        },
    )
    await db.commit()
    return webhook_id


def _buckets(body: dict) -> dict[str, int]:
    return {item["bucket"]: item["count"] for item in body["failures"]["buckets"]}


def _amount(body: dict, currency: str) -> int:
    return sum(
        item["amount_minor"] for item in body["paid_amounts"] if item["currency"] == currency
    )


async def _delete_user_data(db: AsyncSession, user_id: str) -> None:
    """Remove a test user and every linked row so repeated runs stay isolated."""
    await db.execute(
        text(
            "DELETE FROM billing_webhook_events WHERE event_resource_id IN ("
            "SELECT id::text FROM subscriptions WHERE user_id = :uid "
            "UNION SELECT provider_subscription_id FROM subscriptions "
            "WHERE user_id = :uid AND provider_subscription_id IS NOT NULL "
            "UNION SELECT provider_checkout_session_id FROM subscriptions "
            "WHERE user_id = :uid AND provider_checkout_session_id IS NOT NULL "
            "UNION SELECT provider_payment_id FROM payments "
            "WHERE user_id = :uid AND provider_payment_id IS NOT NULL)"
        ),
        {"uid": user_id},
    )
    await db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    await db.commit()


@pytest.fixture
async def funnel_user(db_session: AsyncSession):
    user_id, _ = await _create_user(db_session)
    try:
        yield user_id
    finally:
        await _delete_user_data(db_session, user_id)


class TestCheckoutFunnel:
    async def test_counts_reconcile_and_duplicate_webhooks_do_not_double_count(
        self, db_session: AsyncSession, funnel_user: str
    ):
        user_id = funnel_user
        now = _anchor(2035)

        # Paid attempt: two settled payment rows and duplicate successful
        # webhook deliveries for the same checkout still count as one paid
        # checkout and one first payment amount.
        paid_subscription = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="active",
            created_at=now - timedelta(days=1),
            checkout_session_id=f"chk_{uuid.uuid4().hex[:12]}",
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        )
        first_provider_payment_id = f"pay_{uuid.uuid4().hex[:16]}"
        second_provider_payment_id = f"pay_{uuid.uuid4().hex[:16]}"
        await _insert_payment(
            db_session,
            user_id=user_id,
            subscription_id=paid_subscription,
            amount=59900,
            created_at=now - timedelta(hours=20),
            provider_payment_id=first_provider_payment_id,
        )
        await _insert_payment(
            db_session,
            user_id=user_id,
            subscription_id=paid_subscription,
            amount=59900,
            created_at=now - timedelta(hours=19),
            provider_payment_id=second_provider_payment_id,
        )
        for provider_payment_id in (first_provider_payment_id, second_provider_payment_id):
            for _ in range(2):
                await _insert_webhook(
                    db_session,
                    event_type="payment.succeeded",
                    resource_id=provider_payment_id,
                    status="processed",
                    received_at=now - timedelta(hours=18),
                )

        # Completed but unpaid: one abandoned checkout.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(days=2),
            checkout_session_id=f"chk_{uuid.uuid4().hex[:12]}",
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        )

        # Local failure before a provider session existed.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="failed",
            created_at=now - timedelta(days=1),
        )

        # One declined checkout, with duplicate failed webhook deliveries.
        declined_subscription = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(days=1),
        )
        for _ in range(3):
            await _insert_webhook(
                db_session,
                event_type="subscription.failed",
                resource_id=declined_subscription,
                received_at=now - timedelta(hours=22),
            )

        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(minutes=5),
        )

        after = await checkout_funnel_service.funnel(db_session, days=7, now=now)
        assert after["reconciliation"]["started"] == 5
        assert after["reconciliation"]["completed"] == 2
        assert after["reconciliation"]["paid"] == 1
        assert after["failures"]["total"] == 4
        assert _amount(after, "INR") == 59900

        buckets = _buckets(after)
        assert buckets["abandoned"] == 1
        assert buckets["validation"] == 1
        assert buckets["provider_declined"] == 1
        assert buckets["unknown"] == 1
        assert buckets["unavailable"] == 0

        reconciliation = after["reconciliation"]
        assert reconciliation["started_equals_paid_plus_failed"] is True
        assert reconciliation["completed_at_least_paid"] is True
        assert reconciliation["failure_buckets_match"] is True
        assert reconciliation["started"] == reconciliation["paid"] + reconciliation["failed"]

    async def test_every_failure_has_one_normalized_bucket(
        self, db_session: AsyncSession, funnel_user: str
    ):
        user_id = funnel_user
        now = _anchor(2036)

        # provider_declined: a provider subscription existed but the provider
        # failed it.
        declined_subscription = await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(days=1),
            checkout_session_id=f"chk_{uuid.uuid4().hex[:12]}",
            provider_subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        )
        await _insert_webhook(
            db_session,
            event_type="subscription.failed",
            resource_id=declined_subscription,
            last_error="subscription declined by provider",
            received_at=now - timedelta(hours=23),
        )
        # validation: local failure before a provider session existed.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="failed",
            created_at=now - timedelta(days=2),
        )
        # abandoned: provider checkout existed but no payment settled.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(days=2),
            checkout_session_id=f"chk_{uuid.uuid4().hex[:12]}",
        )
        # unavailable: provider outcome unknown after a timeout.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_unknown",
            created_at=now - timedelta(days=1),
        )
        # unknown: recent in-progress checkout without enough evidence.
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_pending",
            created_at=now - timedelta(minutes=5),
        )

        after = await checkout_funnel_service.funnel(db_session, days=7, now=now)
        buckets = _buckets(after)
        for bucket in ("provider_declined", "validation", "abandoned", "unavailable", "unknown"):
            assert buckets[bucket] == 1, bucket
        assert after["failures"]["total"] == 5
        assert after["reconciliation"]["failure_buckets_match"] is True
        assert after["failures"]["total"] == sum(buckets.values())

    async def test_range_filters_select_the_right_cohort(
        self, client: AsyncClient, db_session: AsyncSession, funnel_user: str
    ):
        user_id = funnel_user
        now = _anchor(2037)

        for offset_days in (2, 20, 60):
            await _insert_subscription(
                db_session,
                user_id=user_id,
                status="checkout_unknown",
                created_at=now - timedelta(days=offset_days),
            )

        results = {
            days: await checkout_funnel_service.funnel(db_session, days=days, now=now)
            for days in (7, 30, 90)
        }
        assert {days: body["reconciliation"]["started"] for days, body in results.items()} == {
            7: 1,
            30: 2,
            90: 3,
        }
        # The HTTP route accepts the same range and echoes it.
        admin_headers = await _headers(db_session)
        response = await client.get("/admin/billing/checkout-funnel?days=30", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["range_days"] == 30

    async def test_non_admin_and_support_are_forbidden(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(db_session, role="user")
        user_headers = await _session_headers(db_session, user_id)
        support_headers = await _headers(db_session, role="support")

        assert (
            await client.get("/admin/billing/checkout-funnel", headers=user_headers)
        ).status_code == 403
        assert (
            await client.get("/admin/billing/checkout-funnel", headers=support_headers)
        ).status_code == 403
        assert (await client.get("/admin/billing/checkout-funnel")).status_code == 401

    async def test_other_billing_mode_products_are_excluded(
        self, db_session: AsyncSession, funnel_user: str, monkeypatch
    ):
        monkeypatch.setattr(settings, "DODO_MODE", "live")
        monkeypatch.setattr(settings, "DODO_LIVE_PRODUCT_PRO_MONTHLY", "prod_checkout_live")
        monkeypatch.setattr(settings, "DODO_TEST_PRODUCT_PRO_MONTHLY", "prod_checkout_test")
        user_id = funnel_user
        now = _anchor(2038)

        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_unknown",
            created_at=now - timedelta(days=1),
            provider_product_id="prod_checkout_live",
        )
        await _insert_subscription(
            db_session,
            user_id=user_id,
            status="checkout_unknown",
            created_at=now - timedelta(days=1),
            provider_product_id="prod_checkout_test",
        )

        after = await checkout_funnel_service.funnel(db_session, days=7, now=now)
        assert after["billing_mode"] == "live"
        assert after["reconciliation"]["started"] == 1
        assert after["excluded_other_mode_attempts"] == 1


def test_failure_classifier_covers_every_bucket():
    assert (
        classify_failure(
            status="checkout_pending",
            has_completed_checkout=True,
            age_seconds=60,
            has_failed_payment=True,
        )
        == "provider_declined"
    )
    assert (
        classify_failure(
            status="failed",
            has_completed_checkout=False,
            age_seconds=60,
        )
        == "validation"
    )
    assert (
        classify_failure(
            status="checkout_pending",
            has_completed_checkout=True,
            age_seconds=25 * 3_600,
        )
        == "abandoned"
    )
    assert (
        classify_failure(
            status="checkout_unknown",
            has_completed_checkout=False,
            age_seconds=60,
        )
        == "unavailable"
    )
    assert (
        classify_failure(
            status="checkout_pending",
            has_completed_checkout=False,
            age_seconds=60,
        )
        == "unknown"
    )
    assert (
        classify_failure(
            status="checkout_pending",
            has_completed_checkout=True,
            age_seconds=60,
            error_texts=["provider unavailable after timeout"],
        )
        == "unavailable"
    )
    assert (
        classify_failure(
            status="failed",
            has_completed_checkout=True,
            age_seconds=60,
            error_texts=["Paid amount does not match the configured plan price"],
        )
        == "validation"
    )
    assert (
        classify_failure(
            status="checkout_pending",
            has_completed_checkout=True,
            age_seconds=60,
            webhook_types=["payment.failed"],
        )
        == "provider_declined"
    )

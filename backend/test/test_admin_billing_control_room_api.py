"""Billing control room: ARPU, dead letters, replay, and reconciliation queue."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.payment_service import payment_service
from test.test_admin_control_room_api import _create_paid_subscription, _create_user, _headers


def _historical_anchor() -> datetime:
    """Unique-but-deterministic timestamp so shared test databases do not overlap."""
    return datetime(1990, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=uuid.uuid4().int % (20 * 365 * 86_400)
    )


async def _insert_webhook_event(
    db: AsyncSession,
    *,
    event_type: str = "payment.succeeded",
    resource_id: str | None = None,
    status: str = "failed",
    received_at: datetime | None = None,
    last_error: str = "provider reconciliation failed",
) -> tuple[str, str]:
    event_id = str(uuid.uuid4())
    provider_event = f"evt_{uuid.uuid4().hex[:16]}"
    resource_id = resource_id or f"pay_{uuid.uuid4().hex[:12]}"
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events "
            "(id, provider, event_id, event_type, event_resource_id, payload_sha256, status, attempts, "
            "last_error, received_at) "
            "VALUES (:id, 'dodo', :event_id, :event_type, :resource, :digest, :status, 2, :error, :received)"
        ),
        {
            "id": event_id,
            "event_id": provider_event,
            "event_type": event_type,
            "resource": resource_id,
            "digest": "a" * 64,
            "status": status,
            "error": last_error,
            "received": received_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return event_id, resource_id


async def _create_pending_checkout(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
    plan: str = "pro",
    amount: int = 59900,
    product_id: str = "prod_control_room",
) -> tuple[str, str, str]:
    subscription_id = str(uuid.uuid4())
    provider_subscription_id = f"sub_{uuid.uuid4().hex[:12]}"
    provider_payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    checkout_id = f"chk_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "provider_checkout_session_id, provider_product_id, provider_customer_id, "
            "quoted_amount, quoted_tax_inclusive, plan_id, status, current_period_start, current_period_end) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :checkout, :product, NULL, "
            ":amount, true, :plan, 'checkout_pending', :start, :end)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": provider_subscription_id,
            "checkout": checkout_id,
            "product": product_id,
            "amount": amount,
            "plan": plan,
            "start": now - timedelta(minutes=5),
            "end": now + timedelta(days=30),
        },
    )
    await db.execute(text("UPDATE users SET subscription_id = :sub WHERE id = :uid"), {
        "sub": subscription_id,
        "uid": user_id,
    })
    await db.commit()
    return subscription_id, provider_subscription_id, provider_payment_id


def _provider_payment(
    *,
    payment_id: str,
    subscription_id: str,
    checkout_id: str,
    intent_id: str,
    user_id: str,
    email: str,
    product_id: str,
    amount: int,
    status: str = "succeeded",
) -> dict:
    return {
        "payment_id": payment_id,
        "status": status,
        "currency": "INR",
        "total_amount": amount,
        "tax": 0,
        "customer": {"customer_id": "cust_control_room", "email": email},
        "metadata": {
            "latexy_intent_id": intent_id,
            "latexy_user_id": user_id,
            "latexy_plan_id": "pro",
            "latexy_tax_inclusive": "true",
        },
        "checkout_session_id": checkout_id,
        "subscription_id": subscription_id,
        "product_cart": [{"product_id": product_id, "quantity": 1}],
        "payment_method": "card",
    }


class TestBillingSummaryArpu:
    async def test_arpu_and_minor_units_reconcile(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        await db_session.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
                "plan_id, status, current_period_start, current_period_end, quoted_amount) "
                "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'active', :start, :end, 59900)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
                "start": datetime.now(timezone.utc) - timedelta(days=2),
                "end": datetime.now(timezone.utc) + timedelta(days=28),
            },
        )
        await db_session.commit()

        response = await client.get("/admin/billing/summary?days=30", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["active_subscriptions"] >= 1
        assert body["mrr_minor"] == round(body["mrr"] * 100)
        assert body["arr_minor"] == body["mrr_minor"] * 12
        assert body["net_revenue_minor"] == body["gross_revenue_minor"] - body["refunded_minor"]
        expected_arpu_minor = (
            round(body["mrr_minor"] / body["active_subscriptions"])
            if body["active_subscriptions"]
            else 0
        )
        assert body["arpu_minor"] == expected_arpu_minor
        assert body["arpu"] == round(expected_arpu_minor / 100, 2)
        assert body["period_start"] < body["period_end"]

    async def test_explicit_date_window_bounds_revenue(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        # A random historical second keeps parallel/repeated test runs from
        # sharing a revenue window; the baseline diff then isolates this row.
        occurred_at = datetime(1995, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds=uuid.uuid4().int % (10 * 365 * 86_400)
        )
        start = occurred_at - timedelta(seconds=1)
        end = occurred_at + timedelta(seconds=1)
        params = {"start": start.isoformat(), "end": end.isoformat()}
        baseline = await client.get(
            "/admin/billing/summary", params=params, headers=admin_headers
        )
        assert baseline.status_code == 200

        await db_session.execute(
            text(
                "INSERT INTO payments (id, user_id, provider, provider_payment_id, amount, currency, "
                "status, created_at) VALUES (:id, :uid, 'dodo', :provider_payment, 123456, 'INR', "
                "'paid', :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
                "created": occurred_at,
            },
        )
        await db_session.commit()

        response = await client.get(
            "/admin/billing/summary", params=params, headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["gross_revenue_minor"] - baseline.json()["gross_revenue_minor"] == 123456
        assert body["refunded_minor"] == baseline.json()["refunded_minor"]
        assert (
            body["net_revenue_minor"] - baseline.json()["net_revenue_minor"] == 123456
        )
        assert body["payments_count"] - baseline.json()["payments_count"] == 1
        assert datetime.fromisoformat(body["period_start"]) == start
        assert datetime.fromisoformat(body["period_end"]) == end

    async def test_summary_rejects_inverted_window(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _headers(db_session)
        response = await client.get(
            "/admin/billing/summary?start=2026-01-02T00:00:00Z&end=2026-01-01T00:00:00Z",
            headers=admin_headers,
        )
        assert response.status_code == 422


class TestWebhookFilters:
    async def test_received_window_dead_letter_and_counts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        anchor = _historical_anchor()
        first_id, _ = await _insert_webhook_event(
            db_session, received_at=anchor, status="failed"
        )
        second_id, _ = await _insert_webhook_event(
            db_session, received_at=anchor + timedelta(hours=1), status="failed"
        )
        await _insert_webhook_event(
            db_session, received_at=anchor + timedelta(hours=1), status="processed"
        )

        window = {
            "received_after": (anchor - timedelta(seconds=1)).isoformat(),
            "received_before": (anchor + timedelta(hours=1, seconds=1)).isoformat(),
            "dead_letter": "true",
            "limit": 50,
        }
        listed = await client.get(
            "/admin/billing/webhooks", params=window, headers=admin_headers
        )
        assert listed.status_code == 200
        body = listed.json()
        ids = {row["id"] for row in body["items"]}
        assert ids == {first_id, second_id}
        assert body["total"] == 2
        assert len(body["items"]) == body["total"]
        assert all(row["status"] == "failed" and row["acknowledged_at"] is None for row in body["items"])

        only_one = await client.get(
            "/admin/billing/webhooks",
            params={**window, "limit": 1, "offset": 1},
            headers=admin_headers,
        )
        assert only_one.status_code == 200
        assert only_one.json()["total"] == 2
        assert len(only_one.json()["items"]) == 1

        non_dead = await client.get(
            "/admin/billing/webhooks",
            params={**window, "dead_letter": "false"},
            headers=admin_headers,
        )
        assert non_dead.status_code == 200
        assert non_dead.json()["total"] == 1

        invalid = await client.get(
            "/admin/billing/webhooks",
            params={
                "received_after": "2026-01-02T00:00:00Z",
                "received_before": "2026-01-01T00:00:00Z",
            },
            headers=admin_headers,
        )
        assert invalid.status_code == 422


class TestWebhookReplay:
    async def test_replay_requires_admin_confirmation_and_is_idempotent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        admin_headers = await _headers(db_session)
        support_headers = await _headers(db_session, "support")
        user_id, email = await _create_user(db_session)
        subscription_id, provider_subscription_id, payment_id = await _create_pending_checkout(
            db_session, user_id=user_id, email=email
        )
        subscription_product = (
            await db_session.execute(
                text("SELECT provider_product_id, provider_checkout_session_id FROM subscriptions WHERE id = :id"),
                {"id": subscription_id},
            )
        ).one()
        event_id, _ = await _insert_webhook_event(
            db_session, resource_id=payment_id, event_type="payment.succeeded"
        )

        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(type(payment_service.provider), "available", property(lambda _self: True))
        get_payment = AsyncMock(
            return_value=_provider_payment(
                payment_id=payment_id,
                subscription_id=provider_subscription_id,
                checkout_id=subscription_product.provider_checkout_session_id,
                intent_id=subscription_id,
                user_id=user_id,
                email=email,
                product_id=subscription_product.provider_product_id,
                amount=59900,
            )
        )
        monkeypatch.setattr(payment_service.provider, "get_payment", get_payment)

        forbidden = await client.post(
            f"/admin/billing/webhooks/{event_id}/replay",
            json={"reason": "Support cannot replay", "confirm": True},
            headers=support_headers,
        )
        assert forbidden.status_code == 403

        missing_confirmation = await client.post(
            f"/admin/billing/webhooks/{event_id}/replay",
            json={"reason": "Forgot to confirm"},
            headers=admin_headers,
        )
        assert missing_confirmation.status_code == 422
        get_payment.assert_not_awaited()

        replayed = await client.post(
            f"/admin/billing/webhooks/{event_id}/replay",
            json={"reason": "Checked the provider payment state", "confirm": True},
            headers=admin_headers,
        )
        assert replayed.status_code == 200
        body = replayed.json()
        assert body["replayed"] is True
        assert body["status"] == "replayed"
        assert body["event"]["status"] == "processed"
        get_payment.assert_awaited_once_with(payment_id)

        payment_row = (
            await db_session.execute(
                text("SELECT amount, currency, status FROM payments WHERE provider_payment_id = :pid"),
                {"pid": payment_id},
            )
        ).one()
        assert tuple(payment_row) == (59900, "INR", "paid")
        user_row = (
            await db_session.execute(
                text("SELECT subscription_plan, subscription_status, subscription_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).one()
        assert tuple(user_row) == ("pro", "active", subscription_id)

        second = await client.post(
            f"/admin/billing/webhooks/{event_id}/replay",
            json={"reason": "Replay the same processed event", "confirm": True},
            headers=admin_headers,
        )
        assert second.status_code == 200
        assert second.json()["replayed"] is False
        assert second.json()["status"] == "already_processed"
        get_payment.assert_awaited_once_with(payment_id)

        audit = await client.get(
            f"/admin/audit?action=billing.webhook.replay&target_id={event_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["reason"] == "Checked the provider payment state"

    async def test_replay_payment_failure_marks_processed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        payment_id = f"pay_{uuid.uuid4().hex[:12]}"
        event_id, _ = await _insert_webhook_event(
            db_session, resource_id=payment_id, event_type="payment.failed"
        )
        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(type(payment_service.provider), "available", property(lambda _self: True))
        get_payment = AsyncMock(return_value={"payment_id": payment_id, "status": "failed"})
        monkeypatch.setattr(payment_service.provider, "get_payment", get_payment)

        replayed = await client.post(
            f"/admin/billing/reconciliation/{event_id}/replay",
            json={"reason": "Provider confirms the failed charge", "confirmed": True},
            headers=admin_headers,
        )
        assert replayed.status_code == 200
        assert replayed.json()["replayed"] is True
        assert replayed.json()["event"]["status"] == "processed"


class TestReconciliationQueue:
    async def test_queue_is_one_row_per_failed_event_and_resolves(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(
            db_session, user_id=user_id
        )
        provider_payment_id = (
            await db_session.execute(
                text("SELECT provider_payment_id FROM payments WHERE id = :id"),
                {"id": payment_id},
            )
        ).scalar_one()
        anchor = _historical_anchor()
        older_id, _ = await _insert_webhook_event(
            db_session,
            event_type="payment.succeeded",
            resource_id=provider_payment_id,
            received_at=anchor,
            last_error="out-of-order duplicate delivery",
        )
        newer_id, _ = await _insert_webhook_event(
            db_session,
            event_type="payment.succeeded",
            resource_id=provider_payment_id,
            received_at=anchor + timedelta(minutes=5),
            last_error="duplicate delivery",
        )
        unrelated_id, _ = await _insert_webhook_event(
            db_session,
            event_type="payment.succeeded",
            resource_id=f"pay_{uuid.uuid4().hex[:12]}",
            received_at=anchor + timedelta(minutes=10),
            last_error="no local intent",
        )
        window = {
            "received_after": (anchor - timedelta(seconds=1)).isoformat(),
            "received_before": (anchor + timedelta(minutes=11)).isoformat(),
            "limit": 50,
        }
        response = await client.get(
            "/admin/billing/reconciliation", params=window, headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        ids = [row["id"] for row in body["items"]]
        assert body["total"] == 3
        assert sorted(ids) == sorted([older_id, newer_id, unrelated_id])
        assert len(ids) == len(set(ids))
        assert ids[0] == unrelated_id  # newest received_at first
        assert ids[-1] == older_id

        duplicate_rows = [row for row in body["items"] if row["id"] in {older_id, newer_id}]
        assert len(duplicate_rows) == 2
        assert all(row["event_resource_id"] == provider_payment_id for row in duplicate_rows)
        assert all(row["amount_minor"] == 59900 for row in duplicate_rows)
        assert all(row["currency"] == "INR" for row in duplicate_rows)
        assert all(row["mismatch_reason"] for row in body["items"])
        assert all(row["suggested_action"] for row in body["items"])
        assert all(row["age_seconds"] is not None for row in body["items"])
        assert {row["id"] for row in duplicate_rows} == {older_id, newer_id}

        # Acknowledging requires a reason and drops the row immediately.
        missing_reason = await client.post(
            f"/admin/billing/reconciliation/{older_id}/acknowledge",
            json={},
            headers=admin_headers,
        )
        assert missing_reason.status_code == 422
        ack = await client.post(
            f"/admin/billing/reconciliation/{older_id}/acknowledge",
            json={"reason": "Verified as a duplicate provider delivery"},
            headers=admin_headers,
        )
        assert ack.status_code == 200
        after_ack = await client.get(
            "/admin/billing/reconciliation", params=window, headers=admin_headers
        )
        assert after_ack.status_code == 200
        remaining = {row["id"] for row in after_ack.json()["items"]}
        assert older_id not in remaining
        assert newer_id in remaining
        assert after_ack.json()["total"] == 2

        audit = await client.get(
            f"/admin/audit?action=billing.webhook.acknowledge&target_id={older_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        assert audit.json()["items"][0]["reason"] == "Verified as a duplicate provider delivery"

    async def test_processed_and_acknowledged_events_drop_off(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        anchor = _historical_anchor()
        failed_id, _ = await _insert_webhook_event(db_session, received_at=anchor)
        processed_id, _ = await _insert_webhook_event(
            db_session, received_at=anchor + timedelta(minutes=1), status="processed"
        )
        ack_id, _ = await _insert_webhook_event(
            db_session, received_at=anchor + timedelta(minutes=2), status="failed"
        )
        await db_session.execute(
            text(
                "UPDATE billing_webhook_events SET acknowledged_at = NOW(), "
                "acknowledged_by = 'test-admin', acknowledgement_note = 'already handled' "
                "WHERE id = :id"
            ),
            {"id": ack_id},
        )
        await db_session.commit()
        window = {
            "received_after": (anchor - timedelta(seconds=1)).isoformat(),
            "received_before": (anchor + timedelta(minutes=3)).isoformat(),
            "limit": 50,
        }
        response = await client.get(
            "/admin/billing/reconciliation", params=window, headers=admin_headers
        )
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()["items"]}
        assert ids == {failed_id}
        assert processed_id not in ids
        assert ack_id not in ids

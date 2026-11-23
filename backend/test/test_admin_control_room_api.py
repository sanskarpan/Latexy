"""Admin control room: audit, billing webhooks, refunds, and User 360."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_user_service
from app.services.admin_billing_service import _monthly_amount
from app.services.payment_service import payment_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    status: str = "active",
    email: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    if email is None:
        email = f"control_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, :plan, :status, false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Control Room User",
            "role": role,
            "plan": plan,
            "status": status,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"control_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _create_paid_subscription(
    db: AsyncSession,
    *,
    user_id: str,
    plan: str = "pro",
    amount: int = 59900,
    currency: str = "INR",
) -> tuple[str, str]:
    subscription_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, quoted_amount) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, :plan, 'active', :start, :end, :amount)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
            "plan": plan,
            "start": now - timedelta(days=2),
            "end": now + timedelta(days=28),
            "amount": amount,
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, subscription_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, :sub, 'dodo', :provider_payment, :amount, :currency, 'paid', :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "sub": subscription_id,
            "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
            "amount": amount,
            "currency": currency,
            "created": now,
        },
    )
    await db.commit()
    return subscription_id, payment_id


class TestAuditLog:
    async def test_role_change_writes_audit_and_is_immutable(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        target_id, _ = await _create_user(db_session)

        response = await client.patch(
            f"/admin/users/{target_id}/role",
            json={"role": "support"},
            headers=admin_headers,
        )
        assert response.status_code == 200

        audit = await client.get(
            f"/admin/audit?action=user.role.change&target_id={target_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        body = audit.json()
        assert body["total"] >= 1
        assert body["items"][0]["target_id"] == target_id
        assert body["items"][0]["before"] == {"role": "user"}
        assert body["items"][0]["after"] == {"role": "support"}

        with pytest.raises(Exception):
            await db_session.execute(
                text("UPDATE admin_audit_log SET reason = 'rewritten' WHERE target_id = :tid"),
                {"tid": target_id},
            )
            await db_session.commit()
        await db_session.rollback()

    async def test_audit_endpoint_rejects_non_admin(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        support_headers = await _headers(db_session, "support")
        response = await client.get("/admin/audit", headers=support_headers)
        assert response.status_code == 403


class TestBillingSummary:
    def test_annual_mrr_uses_monthly_equivalent(self):
        assert _monthly_amount("pro_annual", 575000) == 47917
        assert _monthly_amount("pro", 59900) == 59900

    async def test_summary_mrr_and_refunds(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _headers(db_session)
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)
        await db_session.execute(
            text(
                "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
                "amount, currency, status, reason, created_at) "
                "VALUES (:id, :payment, 'dodo', :refund, 1000, 'INR', 'succeeded', 'goodwill', :created)"
            ),
            {
                "id": str(uuid.uuid4()),
                "payment": payment_id,
                "refund": f"ref_{uuid.uuid4().hex[:12]}",
                "created": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        response = await client.get("/admin/billing/summary?days=30", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["active_subscriptions"] >= 1
        assert body["mrr"] >= 599
        assert body["refunded"] >= 10
        assert body["net_revenue"] >= 589


class TestBillingWebhooks:
    async def _insert_event(
        self,
        db: AsyncSession,
        *,
        event_type: str = "payment.succeeded",
        resource_id: str | None = None,
        status: str = "failed",
    ) -> tuple[str, str]:
        event_id = str(uuid.uuid4())
        provider_event = f"evt_{uuid.uuid4().hex[:16]}"
        resource_id = resource_id or f"pay_{uuid.uuid4().hex[:12]}"
        await db.execute(
            text(
                "INSERT INTO billing_webhook_events "
                "(id, provider, event_id, event_type, event_resource_id, payload_sha256, status, attempts, last_error) "
                "VALUES (:id, 'dodo', :event_id, :event_type, :resource, :digest, :status, 2, 'no local intent')"
            ),
            {
                "id": event_id,
                "event_id": provider_event,
                "event_type": event_type,
                "resource": resource_id,
                "digest": "a" * 64,
                "status": status,
            },
        )
        await db.commit()
        return event_id, resource_id

    async def test_filter_acknowledge_and_reconcile(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        event_id, _ = await self._insert_event(db_session)

        listed = await client.get(
            "/admin/billing/webhooks?status=failed&acknowledged=false",
            headers=admin_headers,
        )
        assert listed.status_code == 200
        assert any(row["id"] == event_id for row in listed.json()["items"])

        ack = await client.post(
            f"/admin/billing/webhooks/{event_id}/acknowledge",
            json={"note": "Verified as provider-side test traffic"},
            headers=admin_headers,
        )
        assert ack.status_code == 200
        assert ack.json()["acknowledged_at"] is not None

        unack = await client.get(
            "/admin/billing/webhooks?status=failed&acknowledged=false",
            headers=admin_headers,
        )
        assert all(row["id"] != event_id for row in unack.json()["items"])

        reconcile = await client.post(
            f"/admin/billing/webhooks/{event_id}/reconcile",
            json={"note": "Check local checkout intent"},
            headers=admin_headers,
        )
        assert reconcile.status_code == 200
        assert reconcile.json()["status"] == "no_local_intent"
        assert reconcile.json()["event"]["reconcile_attempts"] == 1

        audit = await client.get(
            f"/admin/audit?target_type=billing_webhook&target_id={event_id}",
            headers=admin_headers,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert "billing.webhook.acknowledge" in actions
        assert "billing.webhook.reconcile" in actions

    async def test_processed_event_cannot_be_acknowledged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session)
        event_id, _ = await self._insert_event(db_session, status="processed")
        response = await client.post(
            f"/admin/billing/webhooks/{event_id}/acknowledge",
            json={"note": "Should not be allowed"},
            headers=admin_headers,
        )
        assert response.status_code == 422


class TestRefundWorkflow:
    async def test_dual_control_and_provider_execution(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        admin_a = await _headers(db_session, "admin")
        admin_b = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)

        created = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Customer requested cancellation"},
            headers=admin_a,
        )
        assert created.status_code == 200
        request_id = created.json()["id"]
        assert created.json()["status"] == "pending"

        duplicate = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Duplicate request"},
            headers=admin_a,
        )
        assert duplicate.status_code == 422

        self_approval = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Trying to self-approve"},
            headers=admin_a,
        )
        assert self_approval.status_code == 409

        approved = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Verified payment and customer request"},
            headers=admin_b,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(
            type(payment_service.provider),
            "available",
            property(lambda _self: True),
        )
        refund_id = f"ref_test_{uuid.uuid4().hex[:10]}"
        create_refund = AsyncMock(return_value={"id": refund_id, "status": "pending"})
        monkeypatch.setattr(payment_service.provider, "create_refund", create_refund)

        executed = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Submit approved refund"},
            headers=admin_b,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "executing"
        assert executed.json()["provider_refund_id"] == refund_id
        create_refund.assert_awaited_once()

        refund_row = (
            await db_session.execute(
                text(
                    "SELECT provider, amount, status FROM payment_refunds "
                    "WHERE provider_refund_id = :refund_id"
                ),
                {"refund_id": refund_id},
            )
        ).one()
        assert tuple(refund_row) == ("dodo", 59900, "pending")
        payment_status = (
            await db_session.execute(text("SELECT status FROM payments WHERE id = :id"), {"id": payment_id})
        ).scalar_one()
        assert payment_status == "paid"

        audit = await client.get(
            f"/admin/audit?target_type=refund_request&target_id={request_id}",
            headers=admin_b,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert "billing.refund.requested" in actions
        assert "billing.refund.approved" in actions
        assert "billing.refund.execution_pending" in actions

    async def test_successful_provider_execution_writes_ledger(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        admin_a = await _headers(db_session, "admin")
        admin_b = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)

        created = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Provider success test"},
            headers=admin_a,
        )
        request_id = created.json()["id"]
        approved = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Approved for provider success test"},
            headers=admin_b,
        )
        assert approved.status_code == 200

        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(type(payment_service.provider), "available", property(lambda _self: True))
        refund_id = f"ref_test_success_{uuid.uuid4().hex[:10]}"
        monkeypatch.setattr(
            payment_service.provider,
            "create_refund",
            AsyncMock(return_value={"id": refund_id, "status": "succeeded"}),
        )

        executed = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Submit approved refund"},
            headers=admin_b,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "executed"

        refund_row = (
            await db_session.execute(
                text(
                    "SELECT provider, amount, status FROM payment_refunds "
                    "WHERE provider_refund_id = :refund_id"
                ),
                {"refund_id": refund_id},
            )
        ).one()
        assert tuple(refund_row) == ("dodo", 59900, "succeeded")
        payment_status = (
            await db_session.execute(text("SELECT status FROM payments WHERE id = :id"), {"id": payment_id})
        ).scalar_one()
        assert payment_status == "refunded"

    async def test_legacy_provider_refund_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)
        await db_session.execute(
            text("UPDATE payments SET provider = 'razorpay' WHERE id = :id"), {"id": payment_id}
        )
        await db_session.commit()

        response = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Legacy provider test"},
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert "Dodo" in response.json()["detail"]

    async def test_failed_provider_refund_cannot_be_resubmitted(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        admin_a = await _headers(db_session, "admin")
        admin_b = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)

        created = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": "Provider failure test"},
            headers=admin_a,
        )
        request_id = created.json()["id"]
        approved = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Approved for provider failure test"},
            headers=admin_b,
        )
        assert approved.status_code == 200

        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(type(payment_service.provider), "available", property(lambda _self: True))
        failing = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        monkeypatch.setattr(payment_service.provider, "create_refund", failing)

        first = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Attempt once"},
            headers=admin_b,
        )
        assert first.status_code == 200
        assert first.json()["status"] == "failed"

        second = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Must not resubmit an unknown outcome"},
            headers=admin_b,
        )
        assert second.status_code == 422
        failing.assert_awaited_once()

    async def _create_executing_refund(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        *,
        reason: str,
    ) -> tuple[str, str, str, dict[str, str]]:
        admin_a = await _headers(db_session, "admin")
        admin_b = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        _, payment_id = await _create_paid_subscription(db_session, user_id=user_id)
        created = await client.post(
            "/admin/billing/refunds",
            json={"payment_id": payment_id, "reason": reason},
            headers=admin_a,
        )
        assert created.status_code == 200
        request_id = created.json()["id"]
        approved = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": f"Approved: {reason}"},
            headers=admin_b,
        )
        assert approved.status_code == 200

        monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
        monkeypatch.setattr(type(payment_service.provider), "available", property(lambda _self: True))
        refund_id = f"ref_test_reconcile_{uuid.uuid4().hex}"
        monkeypatch.setattr(
            payment_service.provider,
            "create_refund",
            AsyncMock(return_value={"id": refund_id, "status": "pending"}),
        )
        executed = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Start provider refund"},
            headers=admin_b,
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "executing"
        assert executed.json()["provider_refund_id"] == refund_id
        return request_id, refund_id, payment_id, admin_b

    async def test_reconcile_succeeded_provider_settles_stuck_refund(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        request_id, refund_id, payment_id, admin_headers = await self._create_executing_refund(
            client, db_session, monkeypatch, reason="Stuck refund success reconciliation"
        )
        get_refund = AsyncMock(return_value={"id": refund_id, "status": "succeeded"})
        monkeypatch.setattr(payment_service.provider, "get_refund", get_refund)

        reconciled = await client.post(
            f"/admin/billing/refunds/{request_id}/reconcile",
            json={"note": "Checked the refund in the Dodo dashboard"},
            headers=admin_headers,
        )
        assert reconciled.status_code == 200
        body = reconciled.json()
        assert body["status"] == "executed"
        assert body["provider_refund_id"] == refund_id
        assert body["last_error"] is None
        assert body["executed_at"] is not None
        get_refund.assert_awaited_once_with(refund_id)

        refund_row = (
            await db_session.execute(
                text(
                    "SELECT provider, amount, status FROM payment_refunds "
                    "WHERE provider_refund_id = :refund_id"
                ),
                {"refund_id": refund_id},
            )
        ).one()
        assert tuple(refund_row) == ("dodo", 59900, "succeeded")
        payment_status = (
            await db_session.execute(text("SELECT status FROM payments WHERE id = :id"), {"id": payment_id})
        ).scalar_one()
        assert payment_status == "refunded"

        audit = await client.get(
            f"/admin/audit?action=billing.refund.reconciled&target_id={request_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 1
        assert audit.json()["items"][0]["after"]["status"] == "executed"

    async def test_reconcile_pending_provider_keeps_request_executing(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        request_id, refund_id, payment_id, admin_headers = await self._create_executing_refund(
            client, db_session, monkeypatch, reason="Stuck refund pending reconciliation"
        )
        get_refund = AsyncMock(return_value={"id": refund_id, "status": "processing"})
        monkeypatch.setattr(payment_service.provider, "get_refund", get_refund)

        reconciled = await client.post(
            f"/admin/billing/refunds/{request_id}/reconcile",
            json={"note": "Dodo still shows the refund as processing"},
            headers=admin_headers,
        )
        assert reconciled.status_code == 200
        body = reconciled.json()
        assert body["status"] == "executing"
        assert body["provider_refund_id"] == refund_id
        assert body["last_error"] is None
        get_refund.assert_awaited_once_with(refund_id)

        refund_row = (
            await db_session.execute(
                text(
                    "SELECT provider, amount, status FROM payment_refunds "
                    "WHERE provider_refund_id = :refund_id"
                ),
                {"refund_id": refund_id},
            )
        ).one()
        assert tuple(refund_row) == ("dodo", 59900, "pending")
        payment_status = (
            await db_session.execute(text("SELECT status FROM payments WHERE id = :id"), {"id": payment_id})
        ).scalar_one()
        assert payment_status == "paid"


class TestUser360:
    async def _seed_user_data(
        self, db: AsyncSession, user_id: str
    ) -> None:
        resume_id = str(uuid.uuid4())
        await db.execute(
            text(
                "INSERT INTO resumes (id, user_id, title, latex_content) "
                "VALUES (:id, :uid, 'Private Resume Title', 'TOP SECRET LATEX')"
            ),
            {"id": resume_id, "uid": user_id},
        )
        await db.execute(
            text(
                "INSERT INTO usage_analytics (id, user_id, action, resource_type, event_metadata) "
                "VALUES (:id, :uid, 'compile', 'resume', :metadata)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": user_id,
                "metadata": '{"job_description": "secret", "feature": "compile"}',
            },
        )
        await db.execute(
            text(
                'INSERT INTO passkey (id, "userId", "publicKey", "credentialID", counter, "deviceType", "backedUp") '
                "VALUES (:id, :uid, 'pk', :cred, 0, 'singleDevice', false)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "cred": f"cred_{uuid.uuid4().hex}"},
        )
        await db.execute(
            text(
                "INSERT INTO user_api_keys (id, user_id, provider, encrypted_key, key_name, is_active) "
                "VALUES (:id, :uid, 'openai', 'encrypted', 'Support test', true)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id},
        )
        await db.execute(
            text(
                "INSERT INTO developer_api_keys (id, user_id, key_hash, key_prefix, name, is_active) "
                "VALUES (:id, :uid, :hash, 'lx_test', 'Support test', true)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "hash": uuid.uuid4().hex},
        )
        await db.commit()

    async def test_masked_360_no_document_content_and_reveal_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        support_id, support_email = await _create_user(db_session, role="support")
        support_headers = await _session_headers(db_session, support_id)
        user_id, email = await _create_user(db_session)
        await self._seed_user_data(db_session, user_id)
        await _session_headers(db_session, user_id)

        support_view = await client.get(f"/admin/users/{user_id}/360", headers=support_headers)
        assert support_view.status_code == 200
        body = support_view.json()
        assert body["user"]["email"] != email
        assert "*" in body["user"]["email"]
        assert body["user"]["pii_masked"] is True
        assert "TOP SECRET LATEX" not in support_view.text
        assert body["recent_admin_actions"] == []
        assert body["security"]["passkey_count"] == 1
        assert len(body["security"]["passkeys"]) == 1
        assert len(body["security"]["byok_keys"]) == 1
        assert len(body["security"]["developer_keys"]) == 1
        assert len(body["production"]["recent_resumes"]) == 1

        admin_view = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert admin_view.status_code == 200
        assert admin_view.json()["user"]["email"] != email
        assert admin_view.json()["user"]["pii_masked"] is True
        assert email not in admin_view.text

        support_list = await client.get(
            f"/admin/users?q={email}", headers=support_headers
        )
        assert support_list.status_code == 200
        assert support_list.json()["users"][0]["email"] != email
        assert support_list.json()["users"][0]["pii_masked"] is True

        admin_list = await client.get(f"/admin/users?q={email}", headers=admin_headers)
        assert admin_list.status_code == 200
        assert admin_list.json()["users"][0]["email"] != email
        assert admin_list.json()["users"][0]["pii_masked"] is True
        assert email not in admin_list.text

        support_reveal = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "Support should not reveal"},
            headers=support_headers,
        )
        assert support_reveal.status_code == 403

        reveal = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "Ticket 1234 contact customer"},
            headers=admin_headers,
        )
        assert reveal.status_code == 200
        revealed = reveal.json()
        assert revealed["field"] == "email"
        assert revealed["value"] == email
        assert "name" not in revealed
        assert revealed["value"] != "Control Room User"

        reveal_name = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "name", "reason": "Ticket 1234 confirm account holder"},
            headers=admin_headers,
        )
        assert reveal_name.status_code == 200
        assert reveal_name.json() == {"field": "name", "value": "Control Room User"}

        audit = await client.get(
            f"/admin/audit?action=user.pii.reveal&target_id={user_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        assert audit.json()["total"] == 2
        reasons = {row["reason"] for row in audit.json()["items"]}
        assert reasons == {
            "Ticket 1234 contact customer",
            "Ticket 1234 confirm account holder",
        }
        fields = {row["metadata"]["field"] for row in audit.json()["items"]}
        assert fields == {"email", "name"}
        assert email not in audit.text
        assert "Control Room User" not in audit.text

    async def test_reveal_field_and_reason_validation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)

        missing_field = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"reason": "Ticket 1234"},
            headers=admin_headers,
        )
        assert missing_field.status_code == 422

        bad_field = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "address", "reason": "Ticket 1234"},
            headers=admin_headers,
        )
        assert bad_field.status_code == 422

        short_reason = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "x"},
            headers=admin_headers,
        )
        assert short_reason.status_code == 422

        missing_reason = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email"},
            headers=admin_headers,
        )
        assert missing_reason.status_code == 422

        legacy_alias = await client.post(
            f"/admin/users/{user_id}/pii/reveal",
            json={"field": "email", "reason": "Legacy client ticket"},
            headers=admin_headers,
        )
        assert legacy_alias.status_code == 200
        assert legacy_alias.json()["field"] == "email"

    async def test_reveal_is_rate_limited_per_admin_target_field(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, email = await _create_user(db_session)
        other_id, _ = await _create_user(db_session)

        for _ in range(5):
            allowed = await client.post(
                f"/admin/users/{user_id}/reveal-pii",
                json={"field": "email", "reason": "Ticket 1234 repeated lookup"},
                headers=admin_headers,
            )
            assert allowed.status_code == 200

        limited = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "email", "reason": "Ticket 1234 repeated lookup"},
            headers=admin_headers,
        )
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

        # A different field or target has an independent budget.
        other_field = await client.post(
            f"/admin/users/{user_id}/reveal-pii",
            json={"field": "name", "reason": "Ticket 1234 name lookup"},
            headers=admin_headers,
        )
        assert other_field.status_code == 200
        other_target = await client.post(
            f"/admin/users/{other_id}/reveal-pii",
            json={"field": "email", "reason": "Ticket 5678 other account"},
            headers=admin_headers,
        )
        assert other_target.status_code == 200


    async def test_user_360_cache_is_masked_and_invalidated(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        class FakeCache:
            def __init__(self):
                self.values: dict[str, object] = {}
                self.ttls: dict[str, int] = {}

            async def get(self, key: str):
                return self.values.get(key)

            async def set(self, key: str, value, ttl: int = 3600):
                self.values[key] = value
                self.ttls[key] = ttl

            async def delete(self, key: str):
                self.values.pop(key, None)

        fake = FakeCache()
        monkeypatch.setattr(admin_user_service, "cache_manager", fake)
        admin_headers = await _headers(db_session, "admin")
        user_id, email = await _create_user(db_session)
        await self._seed_user_data(db_session, user_id)

        first = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert first.status_code == 200
        assert fake.values
        cached = next(iter(fake.values.values()))
        assert isinstance(cached, dict)
        assert cached["user"]["pii_masked"] is True
        assert email not in json.dumps(cached)
        assert all(ttl == admin_user_service.USER_360_CACHE_TTL for ttl in fake.ttls.values())

        second = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert second.status_code == 200
        assert second.json() == first.json()

        changed = await client.post(
            f"/admin/users/{user_id}/plan",
            json={"plan": "pro", "status": "comped", "reason": "Cache invalidation test"},
            headers=admin_headers,
        )
        assert changed.status_code == 200
        assert fake.values == {}

        refreshed = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["subscription_plan"] == "pro"

    async def test_support_actions_audited_and_sessions_revoked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        await _session_headers(db_session, user_id)
        await self._seed_user_data(db_session, user_id)

        reset = await client.post(
            f"/admin/users/{user_id}/quota/reset",
            json={"reason": "Customer hit a stuck counter", "dimension": "compilations"},
            headers=admin_headers,
        )
        assert reset.status_code == 200
        assert reset.json()["dimensions"] == ["compilations"]

        revoke = await client.post(
            f"/admin/users/{user_id}/sessions/revoke",
            json={"reason": "Account takeover report"},
            headers=admin_headers,
        )
        assert revoke.status_code == 200
        assert revoke.json()["revoked_sessions"] >= 1

        key_revoke = await client.post(
            f"/admin/users/{user_id}/api-keys/revoke",
            json={"reason": "Lost device", "scope": "all"},
            headers=admin_headers,
        )
        assert key_revoke.status_code == 200
        assert key_revoke.json()["revoked_byok_keys"] == 1
        assert key_revoke.json()["revoked_developer_keys"] == 1

        audit = await client.get(
            f"/admin/audit?target_type=user&target_id={user_id}",
            headers=admin_headers,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert "user.quota.reset.started" in actions
        assert "user.quota.reset.completed" in actions
        assert "user.sessions.revoke" in actions
        assert "user.api_keys.revoke" in actions

    async def test_plan_change_requires_reason_and_is_audited(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)

        missing_reason = await client.post(
            f"/admin/users/{user_id}/plan",
            json={"plan": "pro", "status": "comped"},
            headers=admin_headers,
        )
        assert missing_reason.status_code == 422

        changed = await client.post(
            f"/admin/users/{user_id}/plan",
            json={"plan": "pro", "status": "comped", "reason": "Support comp for outage"},
            headers=admin_headers,
        )
        assert changed.status_code == 200
        assert changed.json()["subscription_plan"] == "pro"

        audit = await client.get(
            f"/admin/audit?action=user.plan.change&target_id={user_id}",
            headers=admin_headers,
        )
        assert audit.json()["total"] == 1


class TestIndividualCredentialRevoke:
    async def _seed_credentials(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, str]:
        session_id = str(uuid.uuid4())
        passkey_id = str(uuid.uuid4())
        byok_id = str(uuid.uuid4())
        developer_id = str(uuid.uuid4())
        await db.execute(
            text(
                'INSERT INTO session (id, "userId", "expiresAt", token, "userAgent") '
                "VALUES (:id, :uid, :exp, :token, :agent)"
            ),
            {
                "id": session_id,
                "uid": user_id,
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
                "token": f"secret_session_token_{session_id}",
                "agent": "Pytest Browser",
            },
        )
        await db.execute(
            text(
                'INSERT INTO passkey (id, name, "userId", "publicKey", "credentialID", counter, '
                '"deviceType", "backedUp") '
                "VALUES (:id, 'Laptop key', :uid, :public_key, :credential_id, 3, 'singleDevice', false)"
            ),
            {
                "id": passkey_id,
                "uid": user_id,
                "public_key": f"secret_public_key_{passkey_id}",
                "credential_id": f"secret_credential_{passkey_id}",
            },
        )
        await db.execute(
            text(
                "INSERT INTO user_api_keys (id, user_id, provider, encrypted_key, key_name, is_active) "
                "VALUES (:id, :uid, 'openai', :secret, 'Laptop BYOK', true)"
            ),
            {"id": byok_id, "uid": user_id, "secret": f"secret_encrypted_{byok_id}"},
        )
        await db.execute(
            text(
                "INSERT INTO developer_api_keys (id, user_id, key_hash, key_prefix, name, is_active) "
                "VALUES (:id, :uid, :secret, :prefix, 'CI key', true)"
            ),
            {
                "id": developer_id,
                "uid": user_id,
                "secret": f"secret_hash_{developer_id}",
                "prefix": "lx_sk_prefixonly",
            },
        )
        await db.commit()
        return {
            "session_id": session_id,
            "passkey_id": passkey_id,
            "byok_id": byok_id,
            "developer_id": developer_id,
        }

    async def test_cross_user_denial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        owner_id, _ = await _create_user(db_session)
        other_id, _ = await _create_user(db_session)
        ids = await self._seed_credentials(db_session, owner_id)

        cases = [
            ("sessions", ids["session_id"]),
            ("passkeys", ids["passkey_id"]),
            ("byok-keys", ids["byok_id"]),
            ("developer-keys", ids["developer_id"]),
        ]
        for segment, credential_id in cases:
            denied = await client.post(
                f"/admin/users/{other_id}/{segment}/{credential_id}/revoke",
                json={"reason": "Cross account cleanup attempt"},
                headers=admin_headers,
            )
            assert denied.status_code == 404, (segment, denied.text)

        session_count = (
            await db_session.execute(
                text('SELECT count(*) FROM session WHERE "userId" = :uid'),
                {"uid": owner_id},
            )
        ).scalar_one()
        passkey_count = (
            await db_session.execute(
                text('SELECT count(*) FROM passkey WHERE "userId" = :uid'),
                {"uid": owner_id},
            )
        ).scalar_one()
        byok_active = (
            await db_session.execute(
                text("SELECT is_active FROM user_api_keys WHERE id = :id"),
                {"id": ids["byok_id"]},
            )
        ).scalar_one()
        developer_active = (
            await db_session.execute(
                text("SELECT is_active FROM developer_api_keys WHERE id = :id"),
                {"id": ids["developer_id"]},
            )
        ).scalar_one()
        assert session_count == 1
        assert passkey_count == 1
        assert byok_active is True
        assert developer_active is True

    async def test_individual_revoke_is_idempotent_and_audited(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        ids = await self._seed_credentials(db_session, user_id)

        cases = [
            ("sessions", ids["session_id"], "session"),
            ("passkeys", ids["passkey_id"], "passkey"),
            ("byok-keys", ids["byok_id"], "byok"),
            ("developer-keys", ids["developer_id"], "developer"),
        ]
        for segment, credential_id, kind in cases:
            first = await client.post(
                f"/admin/users/{user_id}/{segment}/{credential_id}/revoke",
                json={"reason": "Lost device ticket 9001"},
                headers=admin_headers,
            )
            assert first.status_code == 200, (segment, first.text)
            assert first.json()["revoked"] is True
            assert first.json()["kind"] == kind
            assert first.json()["item_id"] == credential_id

            second = await client.post(
                f"/admin/users/{user_id}/{segment}/{credential_id}/revoke",
                json={"reason": "Lost device ticket 9001"},
                headers=admin_headers,
            )
            assert second.status_code == 200, (segment, second.text)
            assert second.json()["revoked"] is False
            assert second.json()["already_revoked"] is True

        assert (
            await db_session.execute(
                text('SELECT count(*) FROM session WHERE "userId" = :uid'),
                {"uid": user_id},
            )
        ).scalar_one() == 0
        assert (
            await db_session.execute(
                text('SELECT count(*) FROM passkey WHERE "userId" = :uid'),
                {"uid": user_id},
            )
        ).scalar_one() == 0
        assert (
            await db_session.execute(
                text("SELECT bool_or(is_active) FROM user_api_keys WHERE user_id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one() is False
        assert (
            await db_session.execute(
                text("SELECT bool_or(is_active) FROM developer_api_keys WHERE user_id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one() is False

        audit = await client.get(
            f"/admin/audit?target_type=user&target_id={user_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        rows = [row for row in audit.json()["items"] if row["action"].startswith("user.")]
        by_action = {row["action"]: row for row in rows}
        expected = {
            "user.session.revoke": ("session", ids["session_id"]),
            "user.passkey.revoke": ("passkey", ids["passkey_id"]),
            "user.byok_key.revoke": ("byok", ids["byok_id"]),
            "user.developer_key.revoke": ("developer", ids["developer_id"]),
        }
        for action, (kind, item_id) in expected.items():
            assert action in by_action
            row = by_action[action]
            assert row["reason"] == "Lost device ticket 9001"
            assert row["metadata"]["kind"] == kind
            assert row["metadata"]["item_id"] == item_id
            assert row["request_id"]
            assert row["ip_address"]

    async def test_revoke_requires_admin_and_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        support_id, _ = await _create_user(db_session, role="support")
        support_headers = await _session_headers(db_session, support_id)
        user_id, _ = await _create_user(db_session)
        ids = await self._seed_credentials(db_session, user_id)

        support_attempt = await client.post(
            f"/admin/users/{user_id}/sessions/{ids['session_id']}/revoke",
            json={"reason": "Support should not mutate"},
            headers=support_headers,
        )
        assert support_attempt.status_code == 403

        missing_reason = await client.post(
            f"/admin/users/{user_id}/sessions/{ids['session_id']}/revoke",
            json={},
            headers=admin_headers,
        )
        assert missing_reason.status_code == 422

        short_reason = await client.post(
            f"/admin/users/{user_id}/passkeys/{ids['passkey_id']}/revoke",
            json={"reason": "x"},
            headers=admin_headers,
        )
        assert short_reason.status_code == 422

    async def test_revoked_session_token_is_rejected_immediately(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        ids = await self._seed_credentials(db_session, user_id)
        user_headers = {
            "Authorization": f"Bearer secret_session_token_{ids['session_id']}",
        }

        before = await client.get("/me", headers=user_headers)
        assert before.status_code == 200

        revoked = await client.post(
            f"/admin/users/{user_id}/sessions/{ids['session_id']}/revoke",
            json={"reason": "Stolen laptop ticket 9010"},
            headers=admin_headers,
        )
        assert revoked.status_code == 200

        after = await client.get("/me", headers=user_headers)
        assert after.status_code == 401

    async def test_security_listing_does_not_leak_secrets(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _headers(db_session, "admin")
        user_id, _ = await _create_user(db_session)
        ids = await self._seed_credentials(db_session, user_id)

        response = await client.get(f"/admin/users/{user_id}/360", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        security = body["security"]

        assert security["sessions"][0]["id"] == ids["session_id"]
        assert "token" not in security["sessions"][0]
        assert security["passkeys"][0]["id"] == ids["passkey_id"]
        assert "public_key" not in security["passkeys"][0]
        assert "credential_id" not in security["passkeys"][0]
        assert security["byok_keys"][0]["id"] == ids["byok_id"]
        assert "encrypted_key" not in security["byok_keys"][0]
        assert security["developer_keys"][0]["prefix"] == "lx_sk_prefixonly"
        assert "key_hash" not in security["developer_keys"][0]

        dumped = json.dumps(body)
        assert "secret_session_token_" not in dumped
        assert "secret_public_key_" not in dumped
        assert "secret_credential_" not in dumped
        assert "secret_encrypted_" not in dumped
        assert "secret_hash_" not in dumped


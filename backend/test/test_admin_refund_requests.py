"""Refund and goodwill requests: bounds, maker-checker, execution, audit, RBAC."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin_approval_service import normalize_payload, payload_hash
from app.services.payment_service import payment_service


async def _create_user(db: AsyncSession, *, role: str = "admin") -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"refund_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Refund Test User', :role, true, 'pro', 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role},
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"refund_sess_{uuid.uuid4().hex}"
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


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    user_id, _ = await _create_user(db)
    return await _session_headers(db, user_id)


async def _create_paid_payment(
    db: AsyncSession,
    *,
    amount: int = 59900,
    currency: str = "INR",
) -> tuple[str, str]:
    user_id, _ = await _create_user(db, role="user")
    subscription_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    provider_payment_id = f"pay_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end, quoted_amount) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'active', :start, :end, :amount)"
        ),
        {
            "id": subscription_id,
            "uid": user_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
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
            "provider_payment": provider_payment_id,
            "amount": amount,
            "currency": currency,
            "created": now,
        },
    )
    await db.commit()
    return payment_id, provider_payment_id


async def _insert_succeeded_refund(
    db: AsyncSession, payment_id: str, *, amount: int, reason: str = "goodwill"
) -> None:
    await db.execute(
        text(
            "INSERT INTO payment_refunds (id, payment_id, provider, provider_refund_id, "
            "amount, currency, status, reason, created_at) "
            "VALUES (:id, :payment, 'dodo', :refund, :amount, 'INR', 'succeeded', :reason, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "payment": payment_id,
            "refund": f"ref_{uuid.uuid4().hex[:16]}",
            "amount": amount,
            "reason": reason,
            "created": datetime.now(timezone.utc),
        },
    )
    await db.commit()


def _enable_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payment_service, "is_service_available", lambda: True)
    monkeypatch.setattr(
        type(payment_service.provider), "available", property(lambda _self: True)
    )


async def _create_request(
    client: AsyncClient,
    payment_id: str,
    headers: dict[str, str],
    **overrides,
):
    body = {"payment_id": payment_id, "reason": "Customer refund request", **overrides}
    return await client.post("/admin/billing/refunds", json=body, headers=headers)


async def _create_approved_request(
    client: AsyncClient,
    payment_id: str,
    requester: dict[str, str],
    approver: dict[str, str],
    **overrides,
) -> str:
    created = await _create_request(client, payment_id, requester, **overrides)
    assert created.status_code == 200, created.text
    request_id = created.json()["id"]
    approved = await client.post(
        f"/admin/billing/refunds/{request_id}/approve",
        json={"note": "Approved after payment review"},
        headers=approver,
    )
    assert approved.status_code == 200, approved.text
    return request_id


def test_legacy_refund_payload_hash_survives_the_new_fields():
    legacy = {
        "refund_request_id": str(uuid.uuid4()),
        "payment_id": str(uuid.uuid4()),
        "amount": 1000,
        "currency": "INR",
    }
    normalized = normalize_payload("refund", legacy)
    assert "request_kind" not in normalized
    assert "evidence" not in normalized
    assert payload_hash("refund", legacy) == payload_hash("refund", dict(legacy))

    goodwill = {
        **legacy,
        "request_kind": "goodwill",
        "evidence": "  Ticket 4412  ",
    }
    normalized_goodwill = normalize_payload("refund", goodwill)
    assert normalized_goodwill["request_kind"] == "goodwill"
    assert normalized_goodwill["evidence"] == "Ticket 4412"


class TestRefundRequestCreation:
    async def test_amount_bounds_and_partial_item_requirement(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)

        zero = await _create_request(client, payment_id, admin, amount=0)
        assert zero.status_code == 422
        negative = await _create_request(client, payment_id, admin, amount=-100)
        assert negative.status_code == 422
        too_much = await _create_request(client, payment_id, admin, amount=60000)
        assert too_much.status_code == 422
        assert "cannot exceed" in too_much.json()["detail"]
        no_item = await _create_request(client, payment_id, admin, amount=1000)
        assert no_item.status_code == 422
        assert "line-item" in no_item.json()["detail"]
        full_with_item = await _create_request(
            client, payment_id, admin, provider_item_id="item_123"
        )
        assert full_with_item.status_code == 422
        assert "must not include" in full_with_item.json()["detail"]

        partial = await _create_request(
            client, payment_id, admin, amount=1000, provider_item_id="item_123"
        )
        assert partial.status_code == 200, partial.text
        body = partial.json()
        assert body["status"] == "pending"
        assert body["request_kind"] == "refund"
        assert body["amount"] == 1000

        duplicate = await _create_request(client, payment_id, admin, amount=1000, provider_item_id="item_123")
        assert duplicate.status_code == 422
        assert "open refund request" in duplicate.json()["detail"]

    async def test_already_refunded_and_partial_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin = await _admin_headers(db_session)

        refunded_payment, _ = await _create_paid_payment(db_session)
        await _insert_succeeded_refund(db_session, refunded_payment, amount=59900)
        full = await _create_request(client, refunded_payment, admin)
        assert full.status_code == 422
        assert "fully refunded" in full.json()["detail"]

        partial_payment, _ = await _create_paid_payment(db_session)
        await _insert_succeeded_refund(db_session, partial_payment, amount=10000)
        implicit_full = await _create_request(client, partial_payment, admin)
        assert implicit_full.status_code == 422
        assert "partially refunded" in implicit_full.json()["detail"]
        over_remaining = await _create_request(
            client, partial_payment, admin, amount=50000, provider_item_id="item_456"
        )
        assert over_remaining.status_code == 422
        assert "cannot exceed" in over_remaining.json()["detail"]
        remaining = await _create_request(
            client, partial_payment, admin, amount=49900, provider_item_id="item_456"
        )
        assert remaining.status_code == 200, remaining.text
        assert remaining.json()["amount"] == 49900

    async def test_provider_payment_lookup_and_identifier_validation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin = await _admin_headers(db_session)
        payment_id, provider_payment_id = await _create_paid_payment(db_session)

        by_provider = await client.post(
            "/admin/billing/refunds",
            json={
                "provider_payment_id": provider_payment_id,
                "reason": "Provider receipt lookup",
            },
            headers=admin,
        )
        assert by_provider.status_code == 200, by_provider.text
        assert by_provider.json()["payment_id"] == payment_id

        unknown = await client.post(
            "/admin/billing/refunds",
            json={"provider_payment_id": "pay_does_not_exist", "reason": "Unknown provider payment"},
            headers=admin,
        )
        assert unknown.status_code == 404

        both = await client.post(
            "/admin/billing/refunds",
            json={
                "payment_id": payment_id,
                "provider_payment_id": provider_payment_id,
                "reason": "Ambiguous lookup",
            },
            headers=admin,
        )
        assert both.status_code == 422
        neither = await client.post(
            "/admin/billing/refunds",
            json={"reason": "Missing payment identifier"},
            headers=admin,
        )
        assert neither.status_code == 422

        legacy_payment, legacy_provider_payment = await _create_paid_payment(db_session)
        await db_session.execute(
            text("UPDATE payments SET provider = 'razorpay' WHERE id = :id"),
            {"id": legacy_payment},
        )
        await db_session.commit()
        legacy = await _create_request(client, legacy_payment, admin)
        assert legacy.status_code == 422
        assert "Dodo" in legacy.json()["detail"]
        legacy_lookup = await client.post(
            "/admin/billing/refunds",
            json={
                "provider_payment_id": legacy_provider_payment,
                "reason": "Legacy provider lookup",
            },
            headers=admin,
        )
        assert legacy_lookup.status_code == 404


class TestRefundApproval:
    async def test_goodwill_request_records_evidence_and_full_audit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        requester = await _admin_headers(db_session)
        approver = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)
        evidence = "Ticket #4412; duplicate charge confirmed in the bank statement."

        created = await _create_request(
            client,
            payment_id,
            requester,
            request_kind="goodwill",
            evidence=evidence,
        )
        assert created.status_code == 200, created.text
        request_id = created.json()["id"]
        assert created.json()["request_kind"] == "goodwill"
        assert created.json()["evidence"] == evidence

        queue = await client.get(
            "/admin/approvals",
            params={"status": "pending", "request_type": "refund"},
            headers=approver,
        )
        assert queue.status_code == 200, queue.text
        item = next(row for row in queue.json()["items"] if row["resource_id"] == request_id)
        assert item["payload"]["request_kind"] == "goodwill"
        assert item["payload"]["evidence"] == evidence

        self_approval = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Approving my own request"},
            headers=requester,
        )
        assert self_approval.status_code == 409

        approved = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Goodwill approved after evidence review"},
            headers=approver,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["approved_by"]

        audit = await client.get(
            f"/admin/audit?target_type=refund_request&target_id={request_id}",
            headers=approver,
        )
        assert audit.status_code == 200
        items = {row["action"]: row for row in audit.json()["items"]}
        assert items["billing.refund.requested"]["after"]["request_kind"] == "goodwill"
        assert items["billing.refund.requested"]["after"]["has_evidence"] is True
        assert items["billing.refund.approved"]["after"]["status"] == "approved"
        assert items["billing.refund.requested"]["actor_user_id"] != items["billing.refund.approved"]["actor_user_id"]

    async def test_rejection_is_terminal_and_cannot_be_approved(self, client: AsyncClient, db_session: AsyncSession):
        requester = await _admin_headers(db_session)
        approver = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)
        created = await _create_request(client, payment_id, requester)
        request_id = created.json()["id"]

        rejected = await client.post(
            f"/admin/billing/refunds/{request_id}/reject",
            json={"note": "Policy does not permit this refund"},
            headers=approver,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

        approve_after = await client.post(
            f"/admin/billing/refunds/{request_id}/approve",
            json={"note": "Cannot reverse the rejection"},
            headers=approver,
        )
        assert approve_after.status_code == 422

        audit = await client.get(
            f"/admin/audit?target_type=refund_request&target_id={request_id}",
            headers=approver,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert "billing.refund.rejected" in actions


class TestRefundExecution:
    async def test_successful_execution_is_idempotent_and_audited(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        requester = await _admin_headers(db_session)
        approver = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)
        request_id = await _create_approved_request(client, payment_id, requester, approver)

        _enable_provider(monkeypatch)
        refund_id = f"ref_test_{uuid.uuid4().hex[:12]}"
        create_refund = AsyncMock(return_value={"id": refund_id, "status": "succeeded"})
        monkeypatch.setattr(payment_service.provider, "create_refund", create_refund)

        executed = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Submit approved refund once"},
            headers=approver,
        )
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "executed"
        assert body["provider_refund_id"] == refund_id
        assert body["executed_by"]

        replay = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "A replay must not call the provider again"},
            headers=approver,
        )
        assert replay.status_code == 422
        create_refund.assert_awaited_once()

        refund_count = (
            await db_session.execute(
                text("SELECT count(*) FROM payment_refunds WHERE payment_id = :id"),
                {"id": payment_id},
            )
        ).scalar_one()
        assert refund_count == 1
        payment_status = (
            await db_session.execute(
                text("SELECT status FROM payments WHERE id = :id"), {"id": payment_id}
            )
        ).scalar_one()
        assert payment_status == "refunded"

        audit = await client.get(
            f"/admin/audit?target_type=refund_request&target_id={request_id}",
            headers=approver,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert {
            "billing.refund.requested",
            "billing.refund.approved",
            "billing.refund.execution_started",
            "billing.refund.executed",
        } <= actions

    async def test_provider_failure_is_surfaced_without_leaking_payload(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        requester = await _admin_headers(db_session)
        approver = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)
        request_id = await _create_approved_request(client, payment_id, requester, approver)

        _enable_provider(monkeypatch)
        failing = AsyncMock(
            side_effect=RuntimeError("provider rejected card 4242424242424242 secret_payload")
        )
        monkeypatch.setattr(payment_service.provider, "create_refund", failing)

        failed = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Provider failure attempt"},
            headers=approver,
        )
        assert failed.status_code == 200, failed.text
        body = failed.json()
        assert body["status"] == "failed"
        assert "RuntimeError" in body["last_error"]
        assert "4242" not in body["last_error"]
        assert "secret_payload" not in body["last_error"]
        assert body["provider_refund_id"] is None

        retry = await client.post(
            f"/admin/billing/refunds/{request_id}/execute",
            json={"note": "Do not blindly resubmit"},
            headers=approver,
        )
        assert retry.status_code == 422
        failing.assert_awaited_once()

        audit = await client.get(
            f"/admin/audit?target_type=refund_request&target_id={request_id}",
            headers=approver,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert "billing.refund.execution_failed" in actions

    async def test_response_never_exposes_card_or_provider_payload(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin = await _admin_headers(db_session)
        payment_id, _ = await _create_paid_payment(db_session)
        created = await _create_request(client, payment_id, admin)
        assert created.status_code == 200
        serialized = json.dumps(created.json())
        for forbidden in ("card", "last4", "cvv", "payment_method", "payload", "client_secret"):
            assert forbidden not in serialized.lower()


class TestRefundAuthorization:
    async def test_refund_endpoints_reject_non_admins(self, client: AsyncClient, db_session: AsyncSession):
        user_id, _ = await _create_user(db_session, role="user")
        user_headers = await _session_headers(db_session, user_id)
        support_id, _ = await _create_user(db_session, role="support")
        support_headers = await _session_headers(db_session, support_id)
        payment_id, _ = await _create_paid_payment(db_session)
        body = {"payment_id": payment_id, "reason": "Unauthorized attempt"}

        for headers in (user_headers, support_headers):
            assert (await client.get("/admin/billing/refunds", headers=headers)).status_code == 403
            assert (await client.post("/admin/billing/refunds", json=body, headers=headers)).status_code == 403
            assert (
                await client.post(
                    f"/admin/billing/refunds/{uuid.uuid4()}/approve",
                    json={"note": "Unauthorized approval"},
                    headers=headers,
                )
            ).status_code == 403
            assert (
                await client.post(
                    f"/admin/billing/refunds/{uuid.uuid4()}/reject",
                    json={"note": "Unauthorized rejection"},
                    headers=headers,
                )
            ).status_code == 403
            assert (
                await client.post(
                    f"/admin/billing/refunds/{uuid.uuid4()}/execute",
                    json={"note": "Unauthorized execution"},
                    headers=headers,
                )
            ).status_code == 403
            assert (
                await client.post(
                    f"/admin/billing/refunds/{uuid.uuid4()}/reconcile",
                    json={"note": "Unauthorized reconciliation"},
                    headers=headers,
                )
            ).status_code == 403

        anonymous = await client.get("/admin/billing/refunds")
        assert anonymous.status_code == 401

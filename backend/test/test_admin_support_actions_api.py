"""Admin support actions: verification, password reset and payment receipts.

The security contract under test: admin-only access, target eligibility, an
actor+target cooldown, honest provider failures, append-only audit rows, and
no token or one-time link in a response, audit row or application log.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import admin_support_action_service as support_actions
from app.services.dodo_provider import DodoAPIError
from app.services.email_service import EmailSendResult


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    email_verified: bool = True,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_support_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, :verified, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Support Action User",
            "role": role,
            "verified": email_verified,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_support_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> tuple[str, dict[str, str]]:
    user_id, _ = await _create_user(db, role=role)
    return user_id, await _session_headers(db, user_id)


async def _credential_account(db: AsyncSession, user_id: str, email: str) -> None:
    await db.execute(
        text(
            'INSERT INTO account (id, "userId", "accountId", "providerId", password) '
            "VALUES (:id, :uid, :account, 'credential', 'hashed')"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "account": email},
    )
    await db.commit()


async def _paid_payment(
    db: AsyncSession,
    *,
    user_id: str,
    status: str = "paid",
    provider_payment_id: str | None = None,
) -> str:
    payment_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider, 99900, 'INR', :status, :created)"
        ),
        {
            "id": payment_id,
            "uid": user_id,
            "provider": provider_payment_id or f"pay_{uuid.uuid4().hex[:12]}",
            "status": status,
            "created": datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return payment_id


def _capture_email(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: EmailSendResult | None = None,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        captured.append(kwargs)
        return result or EmailSendResult(accepted=True, status_code=200)

    monkeypatch.setattr(support_actions.email_service, "send_email_with_receipt", fake_send)
    return captured


class FakeProvider:
    available = True

    def __init__(self, payload: Any = None, error: Exception | None = None):
        self.payload = payload if payload is not None else {"items": []}
        self.error = error
        self.calls: list[str] = []

    async def get_payment_line_items(self, payment_id: str) -> Any:
        self.calls.append(payment_id)
        if self.error is not None:
            raise self.error
        return self.payload


async def _audit_items(client: AsyncClient, headers: dict[str, str], target_id: str) -> list[dict[str, Any]]:
    response = await client.get(
        "/admin/audit",
        params={"target_type": "user", "target_id": target_id, "limit": 50},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["items"]


class TestAdminSupportAccess:
    async def test_support_and_users_cannot_trigger_actions_or_receipt_lookup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        target_id, _ = await _create_user(db_session, email_verified=False)
        payment_id = await _paid_payment(db_session, user_id=target_id)

        _, support_headers = await _headers(db_session, "support")
        _, user_headers = await _headers(db_session, "user")
        unknown_id = str(uuid.uuid4())

        for headers in (support_headers, user_headers):
            verification = await client.post(
                f"/admin/users/{target_id}/support/resend-verification",
                json={"reason": "Customer request", "confirm": True},
                headers=headers,
            )
            assert verification.status_code == 403
            reset = await client.post(
                f"/admin/users/{target_id}/support/password-reset",
                json={"reason": "Customer request", "confirm": True},
                headers=headers,
            )
            assert reset.status_code == 403
            receipt = await client.post(
                f"/admin/users/{target_id}/support/resend-receipt",
                json={
                    "payment_id": payment_id,
                    "reason": "Customer request",
                    "confirm": True,
                },
                headers=headers,
            )
            assert receipt.status_code == 403
            lookup = await client.get(
                f"/admin/users/{target_id}/payments/{payment_id}/receipt",
                headers=headers,
            )
            assert lookup.status_code == 403
            # A forbidden admin surface must never disclose whether an
            # arbitrary target exists, even when the id is fabricated.
            unknown = await client.post(
                f"/admin/users/{unknown_id}/support/password-reset",
                json={"reason": "Customer request", "confirm": True},
                headers=headers,
            )
            assert unknown.status_code == 403
            assert "not found" not in unknown.text.lower()

        anonymous = await client.post(
            f"/admin/users/{unknown_id}/support/password-reset",
            json={"reason": "Customer request", "confirm": True},
        )
        assert anonymous.status_code in {401, 403}
        assert "not found" not in anonymous.text.lower()

    async def test_missing_confirmation_and_reason_are_rejected(self, client: AsyncClient, db_session: AsyncSession):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session, email_verified=False)

        missing_confirm = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Customer request"},
            headers=admin_headers,
        )
        assert missing_confirm.status_code == 422

        short_reason = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "x", "confirm": True},
            headers=admin_headers,
        )
        assert short_reason.status_code == 422


class TestVerificationEmail:
    async def test_sends_better_auth_token_without_leaking_it_and_audits(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.DEBUG)
        admin_id, admin_headers = await _headers(db_session)
        target_id, email = await _create_user(db_session, email_verified=False)
        captured = _capture_email(monkeypatch)

        response = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Ticket 1234 — verify after domain change", "confirm": True},
            headers=admin_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "verification_email"
        assert body["delivery"] == "accepted"
        assert body["target_user_id"] == target_id
        assert "token" not in response.text.lower()
        assert "/api/auth/" not in response.text
        assert len(captured) == 1
        sent = captured[0]
        assert sent["to"] == email
        assert sent["idempotency_key"].startswith("admin-support-")
        match = re.search(r"token=([^&\"]+)", sent["html_body"])
        assert match is not None
        token = match.group(1)
        claims = jwt.decode(token, settings.BETTER_AUTH_SECRET, algorithms=["HS256"])
        assert claims["email"] == email.lower()
        assert claims["exp"] > claims["iat"]

        audit = await _audit_items(client, admin_headers, target_id)
        actions = [row["action"] for row in audit]
        assert actions.count("user.verification_email.send.started") == 1
        assert actions.count("user.verification_email.send.completed") == 1
        started = next(row for row in audit if row["action"] == "user.verification_email.send.started")
        completed = next(row for row in audit if row["action"] == "user.verification_email.send.completed")
        assert started["actor_user_id"] == admin_id
        assert completed["reason"] == "Ticket 1234 — verify after domain change"
        assert completed["metadata"]["result"] == "accepted"
        serialized = response.text + str(audit)
        assert token not in serialized
        assert "/api/auth/verify-email" not in serialized
        assert token not in caplog.text

    async def test_already_verified_and_missing_target_are_409_404(self, client: AsyncClient, db_session: AsyncSession):
        _, admin_headers = await _headers(db_session)
        verified_id, _ = await _create_user(db_session, email_verified=True)

        verified = await client.post(
            f"/admin/users/{verified_id}/support/resend-verification",
            json={"reason": "Customer request", "confirm": True},
            headers=admin_headers,
        )
        assert verified.status_code == 409

        missing = await client.post(
            f"/admin/users/{uuid.uuid4()}/support/resend-verification",
            json={"reason": "Customer request", "confirm": True},
            headers=admin_headers,
        )
        assert missing.status_code == 404

    async def test_cooldown_is_per_actor_and_target(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, first_admin = await _headers(db_session)
        _, second_admin = await _headers(db_session)
        target_id, _ = await _create_user(db_session, email_verified=False)
        captured = _capture_email(monkeypatch)

        first = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Customer request", "confirm": True},
            headers=first_admin,
        )
        assert first.status_code == 200

        blocked = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Customer request again", "confirm": True},
            headers=first_admin,
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        assert "wait" in blocked.json()["detail"].lower()
        assert len(captured) == 1

        # A different operator has an independent actor+target window.
        other_actor = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Second operator follow-up", "confirm": True},
            headers=second_admin,
        )
        assert other_actor.status_code == 200
        assert len(captured) == 2

        audit = await _audit_items(client, first_admin, target_id)
        started = [row for row in audit if row["action"] == "user.verification_email.send.started"]
        assert len(started) == 2

    async def test_provider_failure_is_honest_and_audited_without_link_leak(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session, email_verified=False)
        _capture_email(
            monkeypatch,
            result=EmailSendResult(accepted=False, transient=False, status_code=422),
        )

        response = await client.post(
            f"/admin/users/{target_id}/support/resend-verification",
            json={"reason": "Customer request", "confirm": True},
            headers=admin_headers,
        )

        assert response.status_code == 502
        assert "did not accept" in response.json()["detail"].lower()
        assert "token" not in response.text.lower()
        assert "/api/auth/" not in response.text
        audit = await _audit_items(client, admin_headers, target_id)
        failed = [row for row in audit if row["action"] == "user.verification_email.send.failed"]
        assert len(failed) == 1
        assert failed[0]["metadata"]["result"] == "provider_error"
        assert failed[0]["metadata"]["retryable"] is False
        assert "/api/auth/" not in str(audit)


class TestPasswordReset:
    async def test_issues_better_auth_reset_row_and_supersedes_old_links(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        _, admin_headers = await _headers(db_session)
        target_id, email = await _create_user(db_session)
        await _credential_account(db_session, target_id, email)
        await db_session.execute(
            text(
                'INSERT INTO verification (id, identifier, value, "expiresAt") '
                "VALUES (:id, 'reset-password:old-token', :uid, :exp)"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": target_id,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )
        await db_session.commit()
        captured = _capture_email(monkeypatch)

        response = await client.post(
            f"/admin/users/{target_id}/support/password-reset",
            json={"reason": "Ticket 4321 — locked out", "confirm": True},
            headers=admin_headers,
        )

        assert response.status_code == 200
        assert response.json()["action"] == "password_reset"
        assert "token" not in response.text.lower()
        assert "/api/auth/" not in response.text
        match = re.search(r"/api/auth/reset-password/([^?\"]+)", captured[0]["html_body"])
        assert match is not None
        token = match.group(1)
        row = (
            await db_session.execute(
                text('SELECT value, "expiresAt" FROM verification WHERE identifier = :identifier'),
                {"identifier": f"reset-password:{token}"},
            )
        ).one_or_none()
        assert row is not None
        assert str(row[0]) == target_id
        assert row[1] > datetime.now(timezone.utc)
        old = (
            await db_session.execute(text("SELECT 1 FROM verification WHERE identifier = 'reset-password:old-token'"))
        ).first()
        assert old is None

        audit = await _audit_items(client, admin_headers, target_id)
        serialized = str(audit) + response.text
        assert token not in serialized
        assert "/api/auth/reset-password" not in serialized
        actions = [row["action"] for row in audit]
        assert "user.password_reset.send.completed" in actions

    async def test_provider_failure_invalidates_unused_reset_token(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, admin_headers = await _headers(db_session)
        target_id, email = await _create_user(db_session)
        await _credential_account(db_session, target_id, email)
        _capture_email(
            monkeypatch,
            result=EmailSendResult(accepted=False, transient=True, status_code=503),
        )

        response = await client.post(
            f"/admin/users/{target_id}/support/password-reset",
            json={"reason": "Customer request", "confirm": True},
            headers=admin_headers,
        )

        assert response.status_code == 503
        remaining = (
            await db_session.execute(
                text("SELECT count(*) FROM verification WHERE value = :uid AND identifier LIKE 'reset-password:%'"),
                {"uid": target_id},
            )
        ).scalar_one()
        assert remaining == 0
        audit = await _audit_items(client, admin_headers, target_id)
        assert any(row["action"] == "user.password_reset.send.failed" for row in audit)

    async def test_social_only_account_is_not_eligible(self, client: AsyncClient, db_session: AsyncSession):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session)

        response = await client.post(
            f"/admin/users/{target_id}/support/password-reset",
            json={"reason": "Customer request", "confirm": True},
            headers=admin_headers,
        )
        assert response.status_code == 409
        assert "password" in response.json()["detail"].lower()


class TestPaymentReceipt:
    async def test_lookup_and_send_provider_line_items_without_customer_pii(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, admin_headers = await _headers(db_session)
        target_id, email = await _create_user(db_session)
        payment_id = await _paid_payment(db_session, user_id=target_id)
        provider = FakeProvider(
            {
                "items": [
                    {
                        "description": "Pro monthly",
                        "quantity": 1,
                        "amount": 99900,
                        "currency": "INR",
                    }
                ]
            }
        )
        monkeypatch.setattr(support_actions.payment_service, "provider", provider)
        captured = _capture_email(monkeypatch)

        lookup = await client.get(
            f"/admin/users/{target_id}/payments/{payment_id}/receipt",
            headers=admin_headers,
        )
        assert lookup.status_code == 200
        receipt = lookup.json()
        assert receipt["line_items_source"] == "provider"
        assert receipt["line_items_available"] is True
        assert len(receipt["line_items"]) == 1
        assert receipt["line_items"][0]["description"] == "Pro monthly"
        assert receipt["amount_minor"] == 99900
        assert email not in lookup.text
        assert "customer" not in lookup.text.lower()

        sent = await client.post(
            f"/admin/users/{target_id}/support/resend-receipt",
            json={
                "payment_id": payment_id,
                "reason": "Ticket 7890 — customer needs a receipt",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert sent.status_code == 200
        body = sent.json()
        assert body["action"] == "payment_receipt"
        assert body["line_items_count"] == 1
        assert body["line_items_source"] == "provider"
        assert len(captured) == 1
        assert captured[0]["to"] == email
        assert "Pro monthly" in captured[0]["html_body"]
        assert "INR 999.00" in captured[0]["html_body"]
        assert "token" not in sent.text.lower()

        audit = await _audit_items(client, admin_headers, target_id)
        completed = [row for row in audit if row["action"] == "user.payment_receipt.send.completed"]
        assert len(completed) == 1
        assert completed[0]["metadata"]["payment_id"] == payment_id
        assert completed[0]["metadata"]["line_items_count"] == 1
        assert email not in str(audit)

    async def test_provider_failure_blocks_send_and_is_audited(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session)
        payment_id = await _paid_payment(db_session, user_id=target_id)
        provider = FakeProvider(error=DodoAPIError(500, "provider_error"))
        monkeypatch.setattr(support_actions.payment_service, "provider", provider)
        captured = _capture_email(monkeypatch)

        response = await client.post(
            f"/admin/users/{target_id}/support/resend-receipt",
            json={
                "payment_id": payment_id,
                "reason": "Customer request",
                "confirm": True,
            },
            headers=admin_headers,
        )

        assert response.status_code == 503
        assert "provider" in response.json()["detail"].lower()
        assert captured == []
        audit = await _audit_items(client, admin_headers, target_id)
        failed = [row for row in audit if row["action"] == "user.payment_receipt.send.failed"]
        assert len(failed) == 1
        assert failed[0]["metadata"]["result"] == "provider_error"
        assert failed[0]["metadata"]["payment_id"] == payment_id

    async def test_provider_without_line_items_still_sends_ledger_receipt(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session)
        payment_id = await _paid_payment(db_session, user_id=target_id)
        provider = FakeProvider(error=DodoAPIError(404, "not_found"))
        monkeypatch.setattr(support_actions.payment_service, "provider", provider)
        captured = _capture_email(monkeypatch)

        response = await client.post(
            f"/admin/users/{target_id}/support/resend-receipt",
            json={
                "payment_id": payment_id,
                "reason": "Customer request",
                "confirm": True,
            },
            headers=admin_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["line_items_count"] == 0
        assert body["line_items_state"] == "not_exposed"
        assert body["line_items_source"] == "local"
        assert len(captured) == 1
        assert "did not expose itemised lines" in captured[0]["html_body"]

    async def test_missing_or_foreign_payment_is_404_and_unsettled_is_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, admin_headers = await _headers(db_session)
        target_id, _ = await _create_user(db_session)
        other_id, _ = await _create_user(db_session)
        foreign_payment = await _paid_payment(db_session, user_id=other_id)
        pending_payment = await _paid_payment(db_session, user_id=target_id, status="pending")

        missing = await client.get(
            f"/admin/users/{target_id}/payments/{uuid.uuid4()}/receipt",
            headers=admin_headers,
        )
        assert missing.status_code == 404

        foreign = await client.post(
            f"/admin/users/{target_id}/support/resend-receipt",
            json={
                "payment_id": foreign_payment,
                "reason": "Customer request",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert foreign.status_code == 404

        unsettled = await client.post(
            f"/admin/users/{target_id}/support/resend-receipt",
            json={
                "payment_id": pending_payment,
                "reason": "Customer request",
                "confirm": True,
            },
            headers=admin_headers,
        )
        assert unsettled.status_code == 409

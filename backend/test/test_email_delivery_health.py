"""Resend delivery/bounce/complaint monitoring (F7 / #2117)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services.email_health_service import recipient_digest

PREFIX = "test_email_health_"
SECRET = "whsec_" + base64.b64encode(
    b"0123456789abcdef0123456789abcdef"
).decode("ascii")


@pytest.fixture(autouse=True)
async def _clean_email_health_rows(db_session: AsyncSession):
    async def clean() -> None:
        await db_session.execute(
            text(
                "DELETE FROM email_recipient_suppressions "
                "WHERE source_event_id LIKE :prefix"
            ),
            {"prefix": f"{PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM email_delivery_events WHERE provider_event_id LIKE :prefix"),
            {"prefix": f"{PREFIX}%"},
        )
        await db_session.execute(
            text(
                "DELETE FROM document_email_deliveries WHERE user_id IN "
                "(SELECT id FROM users WHERE email LIKE :email)"
            ),
            {"email": f"{PREFIX}%"},
        )
        await db_session.execute(
            text("DELETE FROM users WHERE email LIKE :email"),
            {"email": f"{PREFIX}%"},
        )
        await db_session.commit()

    await clean()
    yield
    await clean()


async def _create_user(
    db: AsyncSession, *, role: str = "user", email: str | None = None
) -> str:
    user_id = str(uuid.uuid4())
    db.add(
        models.User(
            id=user_id,
            email=email or f"{PREFIX}{user_id.replace('-', '')}@example.com",
            name="Email Health User",
            role=role,
            email_verified=True,
            subscription_plan="free",
            subscription_status="inactive",
            trial_used=True,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_email_health_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc).replace(year=2099),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> dict[str, str]:
    admin_id = await _create_user(db, role="admin")
    return await _session_headers(db, admin_id)


async def _delivery_with_message_id(
    db: AsyncSession, *, provider_message_id: str, recipient: str = "owner@example.com"
) -> models.DocumentEmailDelivery:
    user_id = await _create_user(db)
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content) "
            "VALUES (:id, :user_id, 'Email Health Resume', '\\documentclass{article}')"
        ),
        {"id": resume_id, "user_id": user_id},
    )
    now = datetime.now(timezone.utc)
    delivery = models.DocumentEmailDelivery(
        id=str(uuid.uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        recipient_email=recipient,
        idempotency_key=f"{PREFIX}delivery:{uuid.uuid4().hex}",
        provider="resend",
        status="accepted",
        provider_message_id=provider_message_id,
        attempts=1,
        next_attempt_at=now,
        accepted_at=now,
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return delivery


def _event_payload(
    event_type: str,
    *,
    email_id: str | None = None,
    recipient: str = "owner@example.com",
    bounce: dict[str, Any] | None = None,
    origin: str | None = None,
) -> bytes:
    data: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "subject": "Private subject that must not leak",
    }
    if email_id is not None:
        data["email_id"] = email_id
    if recipient:
        data["to"] = [recipient]
        data["email"] = recipient
    if bounce:
        data["bounce"] = bounce
    if origin:
        data["origin"] = origin
        data["id"] = str(uuid.uuid4())
        data["source_id"] = email_id
    return json.dumps(
        {
            "type": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
    ).encode("utf-8")


def _signed_headers(
    payload: bytes,
    *,
    event_id: str | None = None,
    timestamp: int | None = None,
    secret: str = SECRET,
) -> dict[str, str]:
    webhook_id = event_id or f"{PREFIX}{uuid.uuid4().hex}"
    signed_at = str(timestamp if timestamp is not None else int(time.time()))
    key = secret.removeprefix("whsec_")
    signing_key = base64.b64decode(key + "=" * (-len(key) % 4))
    message = webhook_id.encode() + b"." + signed_at.encode() + b"." + payload
    signature = base64.b64encode(
        hmac.new(signing_key, message, hashlib.sha256).digest()
    ).decode()
    return {
        "svix-id": webhook_id,
        "svix-timestamp": signed_at,
        "svix-signature": f"v1,{signature}",
        "content-type": "application/json",
    }


async def _post_event(
    client: AsyncClient, payload: bytes, headers: dict[str, str]
) -> Any:
    return await client.post("/webhooks/resend", content=payload, headers=headers)


async def _event_count(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count(models.EmailDeliveryEvent.id)).where(
                    models.EmailDeliveryEvent.provider_event_id.like(f"{PREFIX}%")
                )
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
class TestResendWebhook:
    async def test_rejects_invalid_signature_without_persisting(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload("email.delivered", email_id=str(uuid.uuid4()))
        headers = _signed_headers(payload)
        headers["svix-signature"] = "v1,not-a-valid-signature"

        response = await _post_event(client, payload, headers)

        assert response.status_code == 400
        assert await _event_count(db_session) == 0

    async def test_fails_closed_when_secret_is_not_configured(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(email_health_service.settings, "RESEND_WEBHOOK_SECRET", "")
        payload = _event_payload("email.delivered", email_id=str(uuid.uuid4()))
        headers = _signed_headers(payload)

        response = await _post_event(client, payload, headers)

        assert response.status_code == 503
        assert await _event_count(db_session) == 0

    async def test_delivered_event_maps_to_provider_message_id(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        message_id = f"re_{uuid.uuid4().hex}"
        delivery = await _delivery_with_message_id(
            db_session, provider_message_id=message_id
        )
        payload = _event_payload("email.delivered", email_id=message_id)
        headers = _signed_headers(payload)

        response = await _post_event(client, payload, headers)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "processed"
        event = (
            await db_session.execute(
                select(models.EmailDeliveryEvent).where(
                    models.EmailDeliveryEvent.provider_event_id == headers["svix-id"]
                )
            )
        ).scalar_one()
        assert event.event_type == "email.delivered"
        assert event.provider_message_id == message_id
        assert event.delivery_id == delivery.id
        assert event.recipient_hash == recipient_digest("owner@example.com")
        assert event.recipient_hash != "owner@example.com"
        assert not hasattr(event, "recipient_email")

    async def test_duplicate_webhook_id_is_idempotent(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload("email.delivered", email_id=f"re_{uuid.uuid4().hex}")
        headers = _signed_headers(payload)

        first = await _post_event(client, payload, headers)
        second = await _post_event(client, payload, headers)

        assert first.status_code == 200
        assert first.json()["status"] == "processed"
        assert second.status_code == 200
        assert second.json()["status"] == "duplicate"
        assert await _event_count(db_session) == 1

    async def test_unknown_event_is_acknowledged_without_failure(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload("domain.created")
        headers = _signed_headers(payload)

        response = await _post_event(client, payload, headers)

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        event = (
            await db_session.execute(
                select(models.EmailDeliveryEvent).where(
                    models.EmailDeliveryEvent.provider_event_id == headers["svix-id"]
                )
            )
        ).scalar_one()
        assert event.event_type == "unknown"

    async def test_old_timestamp_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload("email.delivered", email_id=f"re_{uuid.uuid4().hex}")
        headers = _signed_headers(payload, timestamp=int(time.time()) - 3600)

        response = await _post_event(client, payload, headers)

        assert response.status_code == 400
        assert await _event_count(db_session) == 0

    async def test_complaint_suppresses_recipient_and_blocks_future_sends(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload(
            "email.complained",
            email_id=f"re_{uuid.uuid4().hex}",
            recipient="complained@example.com",
        )
        response = await _post_event(client, payload, _signed_headers(payload))

        assert response.status_code == 200
        assert await email_health_service.is_recipient_suppressed(
            db_session, "COMPLAINED@example.com"
        )
        assert not await email_health_service.is_recipient_suppressed(
            db_session, "clean@example.com"
        )
        suppression = (
            await db_session.execute(
                select(models.EmailRecipientSuppression).where(
                    models.EmailRecipientSuppression.recipient_hash
                    == recipient_digest("complained@example.com")
                )
            )
        ).scalar_one()
        assert suppression.reason == "complaint"
        assert suppression.recipient_hash != "complained@example.com"

    async def test_suppression_removed_clears_local_suppression(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        email = "removed@example.com"
        added = _event_payload("suppression.added", recipient=email, origin="manual")
        removed = _event_payload("suppression.removed", recipient=email)

        assert (
            await _post_event(client, added, _signed_headers(added))
        ).status_code == 200
        assert await email_health_service.is_recipient_suppressed(db_session, email)

        assert (
            await _post_event(client, removed, _signed_headers(removed))
        ).status_code == 200
        assert not await email_health_service.is_recipient_suppressed(db_session, email)


@pytest.mark.asyncio
class TestEmailHealthAdminView:
    async def test_rates_recent_failures_and_suppression_status(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        for index in range(5):
            payload = _event_payload(
                "email.delivered",
                email_id=f"re_{uuid.uuid4().hex}",
                recipient=f"delivered-{index}@example.com",
            )
            assert (
                await _post_event(client, payload, _signed_headers(payload))
            ).status_code == 200
        for event_type, recipient in (
            ("email.bounced", "bounced@example.com"),
            ("email.complained", "complained@example.com"),
        ):
            bounce = (
                {"type": "Permanent", "subType": "General"}
                if event_type == "email.bounced"
                else None
            )
            payload = _event_payload(
                event_type,
                email_id=f"re_{uuid.uuid4().hex}",
                recipient=recipient,
                bounce=bounce,
            )
            assert (
                await _post_event(client, payload, _signed_headers(payload))
            ).status_code == 200

        headers = await _admin_headers(db_session)
        response = await client.get("/admin/email/health?days=30", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"]["events"]["delivered"] == 5
        assert body["summary"]["events"]["bounced"] == 1
        assert body["summary"]["events"]["complained"] == 1
        assert body["summary"]["attempted"] == 7
        assert body["summary"]["bounce_rate_pct"] == pytest.approx(14.29)
        assert body["summary"]["complaint_rate_pct"] == pytest.approx(14.29)
        assert body["summary"]["rates_withheld"] is False
        assert body["suppression"]["active_recipients"] >= 2
        assert body["suppression"]["added_in_period"] >= 2
        assert body["recent_failures"]
        assert all(
            set(item)
            == {
                "event_type",
                "occurred_at",
                "bounce_type",
                "bounce_subtype",
                "retryable",
                "delivery_mapped",
                "delivery_status",
            }
            for item in body["recent_failures"]
        )

    async def test_rates_are_withheld_below_five_outcomes(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        payload = _event_payload("email.delivered", email_id=f"re_{uuid.uuid4().hex}")
        assert (await _post_event(client, payload, _signed_headers(payload))).status_code == 200

        headers = await _admin_headers(db_session)
        response = await client.get("/admin/email/health?days=30", headers=headers)

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["attempted"] == 1
        assert summary["rates_withheld"] is True
        assert summary["bounce_rate_pct"] is None
        assert summary["complaint_rate_pct"] is None
        assert response.json()["minimum_rate_sample"] == 5

    async def test_endpoint_is_admin_only_and_contains_no_recipient_pii(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        from app.services import email_health_service

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        recipient = "private.recipient@example.com"
        payload = _event_payload(
            "email.bounced",
            email_id=f"re_{uuid.uuid4().hex}",
            recipient=recipient,
            bounce={"type": "Permanent", "subType": "MailboxFull"},
        )
        assert (await _post_event(client, payload, _signed_headers(payload))).status_code == 200

        non_admin = await _create_user(db_session)
        forbidden = await client.get(
            "/admin/email/health?days=30",
            headers=await _session_headers(db_session, non_admin),
        )
        assert forbidden.status_code == 403

        admin = await _admin_headers(db_session)
        response = await client.get("/admin/email/health?days=30", headers=admin)
        assert response.status_code == 200
        text_body = response.text.lower()
        assert recipient not in text_body
        assert "example.com" not in text_body
        assert "private subject" not in text_body
        assert "recipient_hash" not in text_body
        assert "provider_message_id" not in text_body
        assert "webhook-signature" not in text_body

    async def test_rejects_invalid_day_window(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        response = await client.get("/admin/email/health?days=0", headers=headers)
        assert response.status_code == 422


class TestTransientRetryClassification:
    @pytest.mark.asyncio
    async def test_resend_message_id_is_returned_for_delivery_mapping(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.email_service import EmailService

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "re_provider_message"}
        with (
            patch("app.services.email_service.settings") as email_settings,
            patch("httpx.AsyncClient") as client_class,
        ):
            email_settings.EMAIL_ENABLED = True
            email_settings.EMAIL_PROVIDER = "resend"
            email_settings.RESEND_API_KEY = "re_test_key"
            email_settings.EMAIL_FROM = "noreply@latexy.io"
            email_settings.EMAIL_FROM_NAME = "Latexy"
            client = AsyncMock()
            client.post = AsyncMock(return_value=response)
            client_class.return_value.__aenter__ = AsyncMock(return_value=client)
            client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            receipt = await EmailService().send_email_with_receipt(
                "owner@example.com", "Subject", "<p>Body</p>"
            )

        assert receipt.accepted is True
        assert receipt.transient is False
        assert receipt.provider_message_id == "re_provider_message"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "expected_transient"),
        [(503, True), (429, True), (422, False), (400, False)],
    )
    async def test_only_retryable_provider_statuses_are_transient(
        self, status_code: int, expected_transient: bool
    ):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.email_service import EmailService

        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"id": "re_test"}
        with (
            patch("app.services.email_service.settings") as email_settings,
            patch("httpx.AsyncClient") as client_class,
        ):
            email_settings.EMAIL_ENABLED = True
            email_settings.EMAIL_PROVIDER = "resend"
            email_settings.RESEND_API_KEY = "re_test_key"
            email_settings.EMAIL_FROM = "noreply@latexy.io"
            email_settings.EMAIL_FROM_NAME = "Latexy"
            client = AsyncMock()
            client.post = AsyncMock(return_value=response)
            client_class.return_value.__aenter__ = AsyncMock(return_value=client)
            client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            receipt = await EmailService().send_email_with_receipt(
                "owner@example.com", "Subject", "<p>Body</p>"
            )

        assert receipt.accepted is (status_code in {200, 201})
        assert receipt.transient is expected_transient
        assert receipt.status_code == status_code


@pytest.mark.asyncio
class TestDocumentDeliveryRetryPolicy:
    async def test_permanent_provider_rejection_exhausts_retries(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        from unittest.mock import AsyncMock, patch

        from app.services.email_service import EmailSendResult
        from test.test_document_delivery import _resume_with_compilation, _user_id

        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        receipt = EmailSendResult(accepted=False, transient=False, status_code=422)
        with (
            patch("app.services.storage_service.download_bytes", return_value=b"%PDF-1.7"),
            patch(
                "app.api.document_delivery_routes.email_service.send_email_with_receipt",
                new=AsyncMock(return_value=receipt),
            ),
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )

        assert response.status_code == 503
        delivery = (
            await db_session.execute(
                select(models.DocumentEmailDelivery).where(
                    models.DocumentEmailDelivery.resume_id == resume_id
                )
            )
        ).scalar_one()
        assert delivery.status == "failed"
        assert delivery.attempts >= 1
        assert delivery.last_error == "provider_rejected"

    async def test_suppressed_recipient_blocks_document_delivery(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession, monkeypatch
    ):
        from unittest.mock import patch

        from app.services import email_health_service
        from test.test_document_delivery import _resume_with_compilation, _user_id

        monkeypatch.setattr(
            email_health_service.settings, "RESEND_WEBHOOK_SECRET", SECRET
        )
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        email = str(
            (
                await db_session.execute(
                    text("SELECT email FROM users WHERE id = :uid"), {"uid": user_id}
                )
            ).scalar_one()
        )
        payload = _event_payload(
            "email.complained", email_id=f"re_{uuid.uuid4().hex}", recipient=email
        )
        assert (await _post_event(client, payload, _signed_headers(payload))).status_code == 200

        with patch("app.services.storage_service.download_bytes") as download:
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )

        assert response.status_code == 422
        assert "cannot receive document emails" in response.json()["detail"]
        download.assert_not_called()

    async def test_transient_provider_failure_remains_retryable(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        from unittest.mock import AsyncMock, patch

        from app.services.email_service import EmailSendResult
        from test.test_document_delivery import _resume_with_compilation, _user_id

        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        receipt = EmailSendResult(accepted=False, transient=True, status_code=503)
        with (
            patch("app.services.storage_service.download_bytes", return_value=b"%PDF-1.7"),
            patch(
                "app.api.document_delivery_routes.email_service.send_email_with_receipt",
                new=AsyncMock(return_value=receipt),
            ),
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )

        assert response.status_code == 503
        delivery = (
            await db_session.execute(
                select(models.DocumentEmailDelivery).where(
                    models.DocumentEmailDelivery.resume_id == resume_id
                )
            )
        ).scalar_one()
        assert delivery.status == "pending"
        assert delivery.last_error == "provider_transient"


class TestMigration:
    def test_revision_is_chained_after_trial_attribution(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "alembic/versions/0087_email_delivery_events.py"
        )
        spec = importlib.util.spec_from_file_location("email_delivery_events_migration", path)
        migration = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(migration)

        assert migration.revision == "0087_email_delivery_events"
        assert migration.down_revision == "0086_trial_attribution"
        source = path.read_text()
        assert "email_delivery_events" in source
        assert "email_recipient_suppressions" in source
        assert "drop_table" in source

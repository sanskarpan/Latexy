"""B50d: authenticated delivery of an owned compiled PDF."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request


def _rate_request(*, host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/export/resume/email",
            "headers": raw_headers,
            "client": (host, 54321),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


async def _user_id(db: AsyncSession, headers: dict) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    result = await db.execute(
        text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
    )
    return str(result.scalar_one())


async def _resume_with_compilation(
    db: AsyncSession, user_id: str, *, pdf_size: int = 128
) -> str:
    resume_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content) "
            "VALUES (:id, :user_id, 'Delivery Resume', '\\documentclass{article}')"
        ),
        {"id": resume_id, "user_id": user_id},
    )
    await db.execute(
        text(
            "INSERT INTO compilations "
            "(id, user_id, resume_id, job_id, status, pdf_path, pdf_size) "
            "VALUES (:id, :user_id, :resume_id, :job_id, 'completed', :pdf_path, :pdf_size)"
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "resume_id": resume_id,
            "job_id": str(uuid.uuid4()),
            "pdf_path": "compilations/owned/resume.pdf",
            "pdf_size": pdf_size,
        },
    )
    await db.commit()
    return resume_id


@pytest.mark.asyncio
class TestDocumentDeliveryRateLimit:
    async def test_first_delivery_sets_one_hour_ttl(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.return_value = [1, 1]
        with (
            patch(
                "app.core.redis.get_redis_cache_client",
                new=AsyncMock(return_value=redis),
            ),
        ):
            await document_delivery_routes._check_delivery_rate_limit(
                _rate_request(), "user-1"
            )

        redis.eval.assert_awaited_once()
        args = redis.eval.await_args.args
        assert args[0] == document_delivery_routes._LUA_INCR_EXPIRE_PAIR
        assert "redis.call('INCR', KEYS[1])" in args[0]
        assert "redis.call('INCR', KEYS[2])" in args[0]
        assert "redis.call('EXPIRE', KEYS[1], ARGV[1])" in args[0]
        assert "redis.call('EXPIRE', KEYS[2], ARGV[1])" in args[0]
        user_key = f"cache:ratelimit:document-email:user:{hashlib.sha256(b'user-1').hexdigest()[:32]}"
        ip_key = f"cache:ratelimit:document-email:ip:{hashlib.sha256(b'ip:127.0.0.1').hexdigest()[:32]}"
        assert args[1:] == (
            2,
            user_key,
            ip_key,
            3600,
            3,
        )

    async def test_fourth_delivery_is_rejected_after_three_allowed(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.side_effect = [[1, 1], [2, 2], [3, 3], [4, 4]]
        with (
            patch(
                "app.core.redis.get_redis_cache_client",
                new=AsyncMock(return_value=redis),
            ),
        ):
            for _ in range(3):
                await document_delivery_routes._check_delivery_rate_limit(
                    _rate_request(), "user-1"
                )
            with pytest.raises(HTTPException) as caught:
                await document_delivery_routes._check_delivery_rate_limit(
                    _rate_request(), "user-1"
                )

        assert caught.value.status_code == 429
        assert caught.value.detail == "Too many document emails; please try again later"
        assert redis.eval.await_count == 4

    async def test_redis_outage_returns_service_unavailable(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.side_effect = RuntimeError("redis unavailable")
        with (
            patch(
                "app.core.redis.get_redis_cache_client",
                new=AsyncMock(return_value=redis),
            ),
        ):
            with pytest.raises(HTTPException) as caught:
                await document_delivery_routes._check_delivery_rate_limit(
                    _rate_request(), "user-1"
                )

        assert caught.value.status_code == 503
        assert caught.value.detail == "Email delivery is temporarily unavailable"
        redis.eval.assert_awaited_once()

    async def test_same_user_shares_limit_across_session_tokens(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.side_effect = [[1, 1], [2, 2], [3, 3], [4, 4]]
        with patch("app.core.redis.get_redis_cache_client", new=AsyncMock(return_value=redis)):
            for index in range(4):
                request = _rate_request(
                    headers={"Authorization": f"Bearer token-{index % 2}"}
                )
                if index == 3:
                    with pytest.raises(HTTPException) as caught:
                        await document_delivery_routes._check_delivery_rate_limit(
                            request, "user-1"
                        )
                    assert caught.value.status_code == 429
                else:
                    await document_delivery_routes._check_delivery_rate_limit(
                        request, "user-1"
                    )

        assert redis.eval.await_count == 4
        assert redis.eval.await_args_list[0].args[2] == redis.eval.await_args_list[1].args[2]

    async def test_different_users_have_distinct_primary_buckets(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.return_value = [1, 1]
        with patch("app.core.redis.get_redis_cache_client", new=AsyncMock(return_value=redis)):
            await document_delivery_routes._check_delivery_rate_limit(_rate_request(), "user-1")
            await document_delivery_routes._check_delivery_rate_limit(_rate_request(), "user-2")

        assert redis.eval.await_args_list[0].args[2] != redis.eval.await_args_list[1].args[2]

    async def test_untrusted_forwarded_ip_cannot_rotate_the_ip_bucket(self):
        from app.api import document_delivery_routes

        redis = AsyncMock()
        redis.eval.return_value = [1, 1]
        with (
            patch("app.core.redis.get_redis_cache_client", new=AsyncMock(return_value=redis)),
            patch("app.middleware.rate_limiting.settings.TRUST_PROXY_HEADERS", False),
        ):
            await document_delivery_routes._check_delivery_rate_limit(
                _rate_request(host="198.51.100.9", headers={"X-Forwarded-For": "1.2.3.4"}),
                "user-1",
            )
            await document_delivery_routes._check_delivery_rate_limit(
                _rate_request(host="198.51.100.9", headers={"X-Forwarded-For": "5.6.7.8"}),
                "user-2",
            )

        expected = f"cache:ratelimit:document-email:ip:{hashlib.sha256(b'ip:198.51.100.9').hexdigest()[:32]}"
        assert redis.eval.await_args_list[0].args[3] == expected
        assert redis.eval.await_args_list[1].args[3] == expected

    async def test_atomic_pair_limiter_rejects_only_fourth_concurrent_delivery(self):
        from app.api import document_delivery_routes

        class AtomicRedis:
            def __init__(self):
                self.counts: dict[str, int] = {}
                self.lock = asyncio.Lock()

            async def eval(self, script, key_count, user_key, ip_key, window, limit):
                assert script == document_delivery_routes._LUA_INCR_EXPIRE_PAIR
                assert key_count == 2 and window == 3600 and limit == 3
                async with self.lock:
                    self.counts[user_key] = self.counts.get(user_key, 0) + 1
                    if self.counts[user_key] > limit:
                        return [self.counts[user_key], 0]
                    self.counts[ip_key] = self.counts.get(ip_key, 0) + 1
                    return [self.counts[user_key], self.counts[ip_key]]

        redis = AtomicRedis()
        with patch("app.core.redis.get_redis_cache_client", new=AsyncMock(return_value=redis)):
            results = await asyncio.gather(
                *(document_delivery_routes._check_delivery_rate_limit(_rate_request(), "user-1") for _ in range(4)),
                return_exceptions=True,
            )

            assert sum(isinstance(result, HTTPException) and result.status_code == 429 for result in results) == 1

            # Retries already denied by the user bucket must not burn the shared
            # IP allowance and lock out unrelated accounts behind the same NAT.
            for _ in range(3):
                with pytest.raises(HTTPException):
                    await document_delivery_routes._check_delivery_rate_limit(_rate_request(), "user-1")
            await document_delivery_routes._check_delivery_rate_limit(_rate_request(), "user-2")
        ip_key = next(key for key in redis.counts if key.startswith("cache:ratelimit:document-email:ip:"))
        assert redis.counts[ip_key] == 4


@pytest.mark.asyncio
class TestDocumentDelivery:
    async def test_resend_attachment_is_encoded_without_exposing_content_in_logs(self):
        from app.services.email_service import EmailAttachment, EmailService

        response = type("Response", (), {"status_code": 200})()
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

            sent = await EmailService().send_email(
                to="owner@example.com",
                subject="Your compiled resume from Latexy",
                html_body="<p>Attached</p>",
                attachments=(EmailAttachment("resume.pdf", b"%PDF-1.7 bytes", "application/pdf"),),
            )

        assert sent is True
        payload = client.post.call_args.kwargs["json"]
        assert payload["attachments"] == [
            {"filename": "resume.pdf", "content": base64.b64encode(b"%PDF-1.7 bytes").decode("ascii")}
        ]

    async def test_sends_only_owned_compiled_pdf_to_verified_account_email(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        pdf = b"%PDF-1.7 owned bytes"

        with (
            patch("app.services.storage_service.download_bytes", return_value=pdf),
            patch(
                "app.api.document_delivery_routes.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as send_email,
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "status": "accepted",
            "recipient": "verified_account_email",
            "retry_behavior": "provider_idempotent",
        }
        send_email.assert_awaited_once()
        call = send_email.call_args.kwargs
        assert call["to"].endswith("@example.com")
        assert call["subject"] == "Your compiled resume from Latexy"
        assert call["attachments"][0].filename == "resume.pdf"
        assert call["attachments"][0].content == pdf
        assert call["attachments"][0].content_type == "application/pdf"

    async def test_rejects_other_users_resume_without_sending(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict, db_session: AsyncSession
    ):
        owner_id = await _user_id(db_session, auth_headers2)
        resume_id = await _resume_with_compilation(db_session, owner_id)
        with patch(
            "app.api.document_delivery_routes.email_service.send_email",
            new=AsyncMock(return_value=True),
        ) as send_email:
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )
        assert response.status_code == 404
        send_email.assert_not_awaited()

    async def test_unverified_account_cannot_use_delivery_as_a_mail_relay(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        await db_session.execute(
            text("UPDATE users SET email_verified = false WHERE id = :user_id"),
            {"user_id": user_id},
        )
        await db_session.commit()
        with (
            patch("app.services.storage_service.download_bytes") as download,
            patch(
                "app.api.document_delivery_routes.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as send_email,
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )
        assert response.status_code == 422
        download.assert_not_called()
        send_email.assert_not_awaited()

    async def test_requires_empty_contract_and_does_not_accept_recipient_override(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        response = await client.post(
            f"/export/{resume_id}/email",
            headers=auth_headers,
            json={"recipient_email": "attacker@example.com"},
        )
        assert response.status_code == 422

    async def test_provider_failure_is_truthfully_reported(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        with (
            patch("app.services.storage_service.download_bytes", return_value=b"%PDF-1.7"),
            patch(
                "app.api.document_delivery_routes.email_service.send_email",
                new=AsyncMock(return_value=False),
            ),
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )
        assert response.status_code == 503
        assert response.json()["detail"] == "Email provider did not accept the document; please retry"

    async def test_rejects_non_pdf_artifact_without_sending(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id)
        with (
            patch("app.services.storage_service.download_bytes", return_value=b"not a pdf"),
            patch(
                "app.api.document_delivery_routes.email_service.send_email",
                new=AsyncMock(return_value=True),
            ) as send_email,
        ):
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )
        assert response.status_code == 422
        assert response.json()["detail"] == "Compiled artifact is not a PDF"
        send_email.assert_not_awaited()

    async def test_oversized_compilation_is_rejected_before_storage_fetch(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _resume_with_compilation(db_session, user_id, pdf_size=8 * 1024 * 1024 + 1)
        with patch("app.services.storage_service.download_bytes") as download:
            response = await client.post(
                f"/export/{resume_id}/email", headers=auth_headers, json={}
            )
        assert response.status_code == 413
        download.assert_not_called()

"""Focused backend tests for the Google Drive export slice."""

from __future__ import annotations

import asyncio
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import User
from app.services.encryption_service import encryption_service
from app.services.google_drive_service import (
    GOOGLE_DRIVE_SCOPE,
    GoogleDriveProviderError,
    GoogleDriveService,
)


def _http_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload)


async def _user_id(db: AsyncSession, headers: dict) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    result = await db.execute(
        text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
    )
    return str(result.scalar_one())


async def _owned_resume_with_pdf(db: AsyncSession, user_id: str) -> str:
    from uuid import uuid4

    resume_id = str(uuid4())
    await db.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content) "
            "VALUES (:id, :user_id, 'Drive Resume', '\\documentclass{article}')"
        ),
        {"id": resume_id, "user_id": user_id},
    )
    await db.execute(
        text(
            "INSERT INTO compilations "
            "(id, user_id, resume_id, job_id, status, pdf_path, pdf_size) "
            "VALUES (:id, :user_id, :resume_id, :job_id, 'completed', :pdf_path, 32)"
        ),
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "resume_id": resume_id,
            "job_id": str(uuid4()),
            "pdf_path": "compilations/drive/resume.pdf",
        },
    )
    await db.commit()
    return resume_id


async def _set_drive_grant(db: AsyncSession, user_id: str) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one()
    user.user_metadata = {
        "google_drive_oauth": {
            "access_token": encryption_service.encrypt("access-token"),
            "refresh_token": encryption_service.encrypt("refresh-token"),
            "scopes": [GOOGLE_DRIVE_SCOPE],
        }
    }
    await db.commit()
    return user


class TestGoogleDriveService:
    @pytest.mark.asyncio
    async def test_upload_creates_file_with_drive_file_metadata(self):
        service = GoogleDriveService()
        client = AsyncMock()
        client.get = AsyncMock(return_value=_http_response(200, {"files": []}))
        client.post = AsyncMock(return_value=_http_response(200, {"id": "drive-file-1"}))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.google_drive_service.httpx.AsyncClient", return_value=client):
            result = await service.upload_pdf(
                "access-token",
                filename="Latexy resume abc.pdf",
                pdf_bytes=b"%PDF-1.7 test",
                resume_key="resume-abc",
            )

        assert result == "created"
        lookup = client.get.call_args
        assert lookup.kwargs["headers"] == {"Authorization": "Bearer access-token"}
        assert "latexy_resume_id" in lookup.kwargs["params"]["q"]
        assert "'root' in parents" not in lookup.kwargs["params"]["q"]
        upload = client.post.call_args
        assert upload.kwargs["params"] == {"uploadType": "multipart"}
        assert b"application/pdf" in upload.kwargs["content"]
        assert b"%PDF-1.7 test" in upload.kwargs["content"]
        assert b"resume-abc" in upload.kwargs["content"]

    @pytest.mark.asyncio
    async def test_upload_updates_existing_file_for_retry_idempotency(self):
        service = GoogleDriveService()
        client = AsyncMock()
        client.get = AsyncMock(return_value=_http_response(200, {"files": [{"id": "drive-file-1"}]}))
        client.patch = AsyncMock(return_value=_http_response(200, {"id": "drive-file-1"}))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.google_drive_service.httpx.AsyncClient", return_value=client):
            result = await service.upload_pdf(
                "access-token",
                filename="Latexy resume abc.pdf",
                pdf_bytes=b"%PDF-1.7 retry",
                resume_key="resume-abc",
            )

        assert result == "updated"
        client.post.assert_not_awaited()
        assert client.patch.call_args.args[0].endswith("/drive-file-1")

    @pytest.mark.asyncio
    async def test_revoke_uses_request_body_so_token_is_not_in_url(self):
        service = GoogleDriveService()
        client = AsyncMock()
        client.post = AsyncMock(return_value=_http_response(200, {}))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.google_drive_service.httpx.AsyncClient", return_value=client):
            await service.revoke_token("secret-access-token")

        assert client.post.call_args.kwargs["data"] == {"token": "secret-access-token"}
        assert "params" not in client.post.call_args.kwargs

    @pytest.mark.asyncio
    async def test_upload_rejects_ambiguous_duplicate_files(self):
        service = GoogleDriveService()
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=_http_response(200, {"files": [{"id": "one"}, {"id": "two"}]})
        )
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.google_drive_service.httpx.AsyncClient", return_value=client):
            with pytest.raises(GoogleDriveProviderError) as caught:
                await service.upload_pdf(
                    "access-token",
                    filename="Latexy resume abc.pdf",
                    pdf_bytes=b"%PDF-1.7 duplicate",
                    resume_key="resume-abc",
                )

        assert caught.value.status_code == 409
        client.post.assert_not_awaited()
        client.patch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exchange_requires_provider_access_token(self):
        service = GoogleDriveService()
        client = AsyncMock()
        client.post = AsyncMock(return_value=_http_response(200, {"scope": GOOGLE_DRIVE_SCOPE}))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.google_drive_service.httpx.AsyncClient", return_value=client):
            with pytest.raises(GoogleDriveProviderError):
                await service.exchange_code(
                    "code",
                    client_id="client",
                    client_secret="secret",
                    redirect_uri="http://localhost/callback",
                )


class TestGoogleDriveRoutes:
    @pytest.mark.asyncio
    async def test_export_lock_is_atomic_and_token_checked(self):
        from app.api import google_drive_routes

        redis = AsyncMock()
        redis.set.return_value = True
        redis.eval.return_value = 1
        with (
            patch.object(google_drive_routes, "get_redis_cache_client", new=AsyncMock(return_value=redis)),
            patch.object(google_drive_routes.secrets, "token_urlsafe", return_value="lock-token"),
        ):
            key, token = await google_drive_routes._acquire_export_lock("user-1", "resume-1")
            await google_drive_routes._release_export_lock(key, token)

        assert key == "latexy:google-drive:export:user-1:resume-1"
        assert token == "lock-token"
        redis.set.assert_awaited_once_with(key, "lock-token", nx=True, ex=180)
        release_args = redis.eval.await_args.args
        assert release_args[0] == google_drive_routes._RELEASE_EXPORT_LOCK
        assert release_args[1:] == (1, key, "lock-token")

    @pytest.mark.asyncio
    async def test_concurrent_export_claim_allows_only_one_creator(self):
        from app.api import google_drive_routes

        class AtomicFakeRedis:
            def __init__(self):
                self.values = {}

            async def set(self, key, value, *, nx, ex):
                assert nx is True
                assert ex == 180
                if key in self.values:
                    return False
                self.values[key] = value
                return True

            async def eval(self, _script, _keys, key, token):
                if self.values.get(key) == token:
                    del self.values[key]
                    return 1
                return 0

        redis = AtomicFakeRedis()
        with patch.object(google_drive_routes, "get_redis_cache_client", new=AsyncMock(return_value=redis)):
            results = await asyncio.gather(
                google_drive_routes._acquire_export_lock("user-1", "resume-1"),
                google_drive_routes._acquire_export_lock("user-1", "resume-1"),
                return_exceptions=True,
            )

        assert sum(isinstance(result, tuple) for result in results) == 1
        rejected = next(result for result in results if isinstance(result, HTTPException))
        assert rejected.status_code == 409

    @pytest.mark.asyncio
    async def test_export_lock_outage_fails_closed(self):
        from app.api import google_drive_routes

        with patch.object(
            google_drive_routes,
            "get_redis_cache_client",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes._acquire_export_lock("user-1", "resume-1")

        assert caught.value.status_code == 503

    @pytest.mark.asyncio
    async def test_connect_requests_only_drive_file_scope(self):
        from app.api import google_drive_routes

        with (
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_ID", "client-id"),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_SECRET", "client-secret"),
            patch.object(settings, "GOOGLE_DRIVE_REDIRECT_URI", "http://localhost/callback"),
            patch.object(google_drive_routes.cache_manager, "set", new=AsyncMock()) as cache_set,
            patch.object(google_drive_routes.secrets, "token_urlsafe", return_value="state-1"),
        ):
            response = await google_drive_routes.google_drive_connect("user-1")

        assert "drive.file" in response.authorization_url
        assert "drive.readonly" not in response.authorization_url
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(response.authorization_url).query)
        assert query["redirect_uri"] == ["http://localhost/callback"]
        assert query["scope"] == [GOOGLE_DRIVE_SCOPE]
        cache_set.assert_awaited_once_with(
            "gdrive:oauth:state-1", {"user_id": "user-1"}, ttl=600
        )

    @pytest.mark.asyncio
    async def test_callback_binds_completion_ticket_to_original_user(self):
        from app.api import google_drive_routes

        with (
            patch.object(
                google_drive_routes.cache_manager,
                "get",
                new=AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"}),
            ),
            patch.object(
                google_drive_routes.cache_manager,
                "pop",
                new=AsyncMock(return_value={"user_id": "owner-1"}),
            ),
            patch.object(google_drive_routes.cache_manager, "set", new=AsyncMock()) as cache_set,
            patch.object(google_drive_routes.secrets, "token_urlsafe", return_value="ticket-1"),
        ):
            response = await google_drive_routes.google_drive_callback(
                code="code-1", state="state-1", error=None
            )

        assert response.status_code in (302, 307)
        assert "google_drive=complete" in response.headers["location"]
        cache_set.assert_awaited_once_with(
            "gdrive:complete:ticket-1",
            {"user_id": "owner-1", "code": "code-1"},
            ttl=300,
        )

    @pytest.mark.asyncio
    async def test_callback_ticket_is_single_use(self):
        from app.api import google_drive_routes

        pop = AsyncMock(side_effect=[{"user_id": "owner-1"}, None])
        with (
            patch.object(google_drive_routes.cache_manager, "pop", new=pop),
            patch.object(google_drive_routes.cache_manager, "set", new=AsyncMock()),
            patch.object(google_drive_routes.secrets, "token_urlsafe", return_value="ticket-1"),
        ):
            first = await google_drive_routes.google_drive_callback(
                code="code-1", state="state-1", error=None
            )
            second = await google_drive_routes.google_drive_callback(
                code="code-1", state="state-1", error=None
            )

        assert "google_drive=complete" in first.headers["location"]
        assert "reason=invalid_state" in second.headers["location"]
        assert pop.await_count == 2

    @pytest.mark.asyncio
    async def test_reconnect_preserves_existing_encrypted_refresh_token(self):
        from app.api import google_drive_routes

        user = User(id="owner-1", email="owner@example.com")
        encrypted_refresh = encryption_service.encrypt("old-refresh")
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("old-access"),
                "refresh_token": encrypted_refresh,
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = result
        with (
            patch.object(
                google_drive_routes.cache_manager,
                "get",
                new=AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"}),
            ),
            patch.object(
                google_drive_routes.cache_manager,
                "pop",
                new=AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"}),
            ),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_ID", "client-id"),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_SECRET", "client-secret"),
            patch.object(settings, "GOOGLE_DRIVE_REDIRECT_URI", "http://localhost/callback"),
            patch.object(
                google_drive_routes.google_drive_service,
                "exchange_code",
                new=AsyncMock(return_value={"access_token": "new-access", "scope": GOOGLE_DRIVE_SCOPE}),
            ),
        ):
            response = await google_drive_routes.google_drive_complete(
                google_drive_routes.GoogleDriveOAuthCompleteRequest(ticket="ticket-1"),
                db,
                "owner-1",
            )

        assert response["success"] is True
        stored = user.user_metadata["google_drive_oauth"]["refresh_token"]
        assert stored == encrypted_refresh
        assert encryption_service.decrypt(stored) == "old-refresh"
        assert encryption_service.decrypt(user.user_metadata["google_drive_oauth"]["access_token"]) == "new-access"
        assert "old-refresh" not in str(response)
        assert "new-access" not in str(response)

    @pytest.mark.asyncio
    async def test_complete_rejects_insufficient_scope_before_persisting(self):
        from app.api import google_drive_routes

        db = AsyncMock()
        with (
            patch.object(
                google_drive_routes.cache_manager,
                "get",
                new=AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"}),
            ),
            patch.object(
                google_drive_routes.cache_manager,
                "pop",
                new=AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"}),
            ),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_ID", "client-id"),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_SECRET", "client-secret"),
            patch.object(settings, "GOOGLE_DRIVE_REDIRECT_URI", "http://localhost/callback"),
            patch.object(
                google_drive_routes.google_drive_service,
                "exchange_code",
                new=AsyncMock(return_value={"access_token": "new-access", "scope": "https://www.googleapis.com/auth/drive.readonly"}),
            ),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes.google_drive_complete(
                    google_drive_routes.GoogleDriveOAuthCompleteRequest(ticket="ticket-1"),
                    db,
                    "owner-1",
                )

        assert caught.value.status_code == 502
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_rejects_cross_user_ticket_without_exchange(self):
        from app.api import google_drive_routes

        db = AsyncMock()
        exchange = AsyncMock()
        cache_get = AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"})
        cache_pop = AsyncMock()
        with (
            patch.object(google_drive_routes.cache_manager, "get", new=cache_get),
            patch.object(google_drive_routes.cache_manager, "pop", new=cache_pop),
            patch.object(google_drive_routes.google_drive_service, "exchange_code", new=exchange),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes.google_drive_complete(
                    google_drive_routes.GoogleDriveOAuthCompleteRequest(ticket="ticket-1"),
                    db,
                    "different-user",
                )

        assert caught.value.status_code == 403
        exchange.assert_not_awaited()
        cache_pop.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_unconfigured_does_not_consume_ticket(self):
        from app.api import google_drive_routes

        db = AsyncMock()
        exchange = AsyncMock()
        cache_get = AsyncMock(return_value={"user_id": "owner-1", "code": "code-1"})
        cache_pop = AsyncMock()
        with (
            patch.object(google_drive_routes.cache_manager, "get", new=cache_get),
            patch.object(google_drive_routes.cache_manager, "pop", new=cache_pop),
            patch.object(google_drive_routes.google_drive_service, "exchange_code", new=exchange),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_ID", ""),
            patch.object(settings, "GOOGLE_DRIVE_CLIENT_SECRET", "client-secret"),
            patch.object(settings, "GOOGLE_DRIVE_REDIRECT_URI", "http://localhost/callback"),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes.google_drive_complete(
                    google_drive_routes.GoogleDriveOAuthCompleteRequest(ticket="ticket-1"),
                    db,
                    "owner-1",
                )

        assert caught.value.status_code == 503
        cache_pop.assert_not_awaited()
        exchange.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_export_refreshes_once_after_expired_access_token(self):
        from app.api import google_drive_routes

        user = User(id="owner-1", email="owner@example.com")
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("old-access"),
                "refresh_token": encryption_service.encrypt("refresh"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        operation = AsyncMock(
            side_effect=[GoogleDriveProviderError("upload", 401), "updated"]
        )
        refresh = AsyncMock(return_value="new-access")
        with patch.object(google_drive_routes, "_refresh_drive_token", new=refresh):
            result = await google_drive_routes._run_with_drive_token(user, AsyncMock(), operation)

        assert result == "updated"
        assert [call.args[0] for call in operation.await_args_list] == ["old-access", "new-access"]
        refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_status_requires_recorded_drive_file_scope(self):
        from app.api import google_drive_routes

        user = User(id="owner-1", email="owner@example.com")
        user.user_metadata = {
            "google_drive_oauth": {"access_token": encryption_service.encrypt("access")}
        }
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = result

        response = await google_drive_routes.google_drive_status(db, "owner-1")

        assert response.connected is False
        assert response.scope is None

    @pytest.mark.asyncio
    async def test_refresh_provider_outage_is_truthful_and_does_not_commit(self):
        from app.api import google_drive_routes

        user = User(id="owner-1", email="owner@example.com")
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("access"),
                "refresh_token": encryption_service.encrypt("refresh"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        db = AsyncMock()
        with patch.object(
            google_drive_routes.google_drive_service,
            "refresh_access_token",
            new=AsyncMock(side_effect=GoogleDriveProviderError("refresh", 503)),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes._refresh_drive_token(user, db)

        assert caught.value.status_code == 503
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_clears_invalid_grant_but_surfaces_outage(self):
        from app.api import google_drive_routes

        user = User(id="owner-1", email="owner@example.com")
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("access"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = result
        with patch.object(
            google_drive_routes.google_drive_service,
            "revoke_token",
            new=AsyncMock(side_effect=GoogleDriveProviderError("revoke", 400)),
        ):
            response = await google_drive_routes.google_drive_disconnect(db, "owner-1")
        assert response["success"] is True
        assert "google_drive_oauth" not in user.user_metadata
        db.commit.assert_awaited_once()

        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("access"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        db.commit.reset_mock()
        with patch.object(
            google_drive_routes.google_drive_service,
            "revoke_token",
            new=AsyncMock(side_effect=GoogleDriveProviderError("revoke", None)),
        ):
            with pytest.raises(HTTPException) as caught:
                await google_drive_routes.google_drive_disconnect(db, "owner-1")
        assert caught.value.status_code == 503
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_export_is_owned_and_retry_safe(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _owned_resume_with_pdf(db_session, user_id)
        user_result = await db_session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one()
        user.user_metadata = {
            "google_drive_oauth": {
                "access_token": encryption_service.encrypt("access-token"),
                "refresh_token": encryption_service.encrypt("refresh-token"),
                "scopes": [GOOGLE_DRIVE_SCOPE],
            }
        }
        await db_session.commit()

        with (
            patch("app.services.storage_service.download_bytes", return_value=b"%PDF-1.7 owned"),
            patch(
                "app.api.google_drive_routes.google_drive_service.upload_pdf",
                new=AsyncMock(return_value="created"),
            ) as upload,
            patch(
                "app.services.entitlement_service.entitlement_service.has_feature",
                new=AsyncMock(return_value=True),
            ),
        ):
            response = await client.post(
                f"/google-drive/resumes/{resume_id}/export", headers=auth_headers, json={}
            )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "success": True,
            "provider": "google_drive",
            "action": "created",
            "retry_behavior": "same_file_for_resume",
        }
        upload.assert_awaited_once()
        assert upload.call_args.kwargs["resume_key"] == resume_id
        assert upload.call_args.kwargs["pdf_bytes"].startswith(b"%PDF-")

    @pytest.mark.asyncio
    async def test_export_without_connection_does_not_call_provider(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _owned_resume_with_pdf(db_session, user_id)
        with (
            patch(
                "app.api.google_drive_routes.google_drive_service.upload_pdf",
                new=AsyncMock(),
            ) as upload,
            patch(
                "app.services.entitlement_service.entitlement_service.has_feature",
                new=AsyncMock(return_value=True),
            ),
        ):
            response = await client.post(
                f"/google-drive/resumes/{resume_id}/export", headers=auth_headers, json={}
            )
        assert response.status_code == 400, response.text
        upload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_export_uses_eight_mib_bound_and_export_neutral_error(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        from app.api.google_drive_routes import MAX_DRIVE_PDF_BYTES

        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _owned_resume_with_pdf(db_session, user_id)
        await db_session.execute(
            text("UPDATE compilations SET pdf_size = :size WHERE resume_id = :resume_id"),
            {"size": MAX_DRIVE_PDF_BYTES + 1, "resume_id": resume_id},
        )
        await db_session.commit()
        await _set_drive_grant(db_session, user_id)

        with (
            patch("app.services.storage_service.download_bytes") as download,
            patch(
                "app.api.google_drive_routes.google_drive_service.upload_pdf",
                new=AsyncMock(),
            ) as upload,
            patch(
                "app.services.entitlement_service.entitlement_service.has_feature",
                new=AsyncMock(return_value=True),
            ),
        ):
            response = await client.post(
                f"/google-drive/resumes/{resume_id}/export", headers=auth_headers, json={}
            )

        assert MAX_DRIVE_PDF_BYTES == 8 * 1024 * 1024
        assert response.status_code == 413, response.text
        assert response.json()["detail"] == "Compiled PDF is too large to export"
        assert "email" not in response.json()["detail"].lower()
        download.assert_not_called()
        upload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_export_rejects_resume_owned_by_another_user(
        self,
        client: AsyncClient,
        auth_headers: dict,
        auth_headers2: dict,
        db_session: AsyncSession,
    ):
        owner_id = await _user_id(db_session, auth_headers2)
        resume_id = await _owned_resume_with_pdf(db_session, owner_id)
        user_id = await _user_id(db_session, auth_headers)
        await _set_drive_grant(db_session, user_id)
        with (
            patch(
                "app.api.google_drive_routes.google_drive_service.upload_pdf",
                new=AsyncMock(),
            ) as upload,
            patch(
                "app.services.entitlement_service.entitlement_service.has_feature",
                new=AsyncMock(return_value=True),
            ),
        ):
            response = await client.post(
                f"/google-drive/resumes/{resume_id}/export", headers=auth_headers, json={}
            )
        assert response.status_code == 404
        upload.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status_code", "detail"),
        [
            (422, "No completed PDF is available"),
            (422, "Compiled artifact is not a PDF"),
        ],
    )
    async def test_export_does_not_upload_when_artifact_is_invalid(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        status_code: int,
        detail: str,
    ):
        user_id = await _user_id(db_session, auth_headers)
        resume_id = await _owned_resume_with_pdf(db_session, user_id)
        await _set_drive_grant(db_session, user_id)
        with (
            patch(
                "app.api.google_drive_routes._owned_compiled_pdf",
                side_effect=HTTPException(status_code=status_code, detail=detail),
            ),
            patch(
                "app.api.google_drive_routes.google_drive_service.upload_pdf",
                new=AsyncMock(),
            ) as upload,
            patch(
                "app.services.entitlement_service.entitlement_service.has_feature",
                new=AsyncMock(return_value=True),
            ),
        ):
            response = await client.post(
                f"/google-drive/resumes/{resume_id}/export", headers=auth_headers, json={}
            )
        assert response.status_code == status_code
        assert response.json()["detail"] == detail
        upload.assert_not_awaited()

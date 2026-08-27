"""Tests for Dropbox sync (Feature 77)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.services.dropbox_sync_service import DropboxSyncService

# ── DropboxSyncService unit tests ─────────────────────────────────────────────


class TestDropboxSyncService:
    """Unit tests for the sync service using mocked httpx."""

    @pytest.fixture()
    def service(self):
        return DropboxSyncService()

    @pytest.mark.asyncio
    async def test_upload_file_sends_correct_headers(self, service):
        """upload_file POSTs to the content endpoint with Dropbox-API-Arg header."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"name": "abc.tex", "path_display": "/Latexy/abc.tex"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("app.services.dropbox_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.upload_file("tok", "/Latexy/abc.tex", "\\documentclass{article}")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        # Verify the Dropbox-API-Arg header is set
        assert "Dropbox-API-Arg" in call_kwargs[1]["headers"]
        # Verify body is the encoded latex content
        assert call_kwargs[1]["content"] == b"\\documentclass{article}"
        assert result["name"] == "abc.tex"

    @pytest.mark.asyncio
    async def test_upload_file_uses_overwrite_mode(self, service):
        """upload_file specifies mode=overwrite in the API arg."""
        import json

        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("app.services.dropbox_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await service.upload_file("tok", "/Latexy/abc.tex", "content")

        call_kwargs = mock_client.post.call_args
        api_arg = json.loads(call_kwargs[1]["headers"]["Dropbox-API-Arg"])
        assert api_arg["mode"] == "overwrite"
        assert api_arg["path"] == "/Latexy/abc.tex"
        assert api_arg["autorename"] is False

    @pytest.mark.asyncio
    async def test_download_file_returns_text(self, service):
        """download_file returns the response body as text."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "\\documentclass{article}\\begin{document}Hello\\end{document}"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("app.services.dropbox_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            content = await service.download_file("tok", "/Latexy/abc.tex")

        assert content == "\\documentclass{article}\\begin{document}Hello\\end{document}"

    @pytest.mark.asyncio
    async def test_get_account_returns_parsed_json(self, service):
        """get_account returns the parsed JSON from /users/get_current_account."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "account_id": "dbid:AAH123",
            "name": {"display_name": "Test User"},
            "email": "test@example.com",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with patch("app.services.dropbox_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            account = await service.get_account("tok")

        assert account["account_id"] == "dbid:AAH123"
        assert account["name"]["display_name"] == "Test User"


# ── Endpoint tests (via TestClient with dependency overrides) ─────────────────


@pytest.fixture()
def authed_client():
    """Create a TestClient with auth dependency overridden to a fixed user ID."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.auth_middleware import get_current_user_required

    app.dependency_overrides[get_current_user_required] = lambda: "test-user-id"
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_current_user_required, None)


class TestDropboxEndpoints:
    """Integration-style tests for Dropbox route handlers."""

    def test_connect_without_config_returns_503(self, authed_client):
        """POST /dropbox/connect returns 503 when Dropbox is not configured."""
        original_key = settings.DROPBOX_APP_KEY
        original_secret = settings.DROPBOX_APP_SECRET
        try:
            settings.DROPBOX_APP_KEY = ""
            settings.DROPBOX_APP_SECRET = ""
            resp = authed_client.post("/dropbox/connect")
            assert resp.status_code == 503
        finally:
            settings.DROPBOX_APP_KEY = original_key
            settings.DROPBOX_APP_SECRET = original_secret

    def test_callback_only_issues_completion_ticket(self, authed_client):
        """The public callback must not exchange or store Dropbox credentials."""
        with (
            patch("app.api.dropbox_routes.cache_manager") as mock_cache,
            patch("app.api.dropbox_routes.secrets.token_urlsafe", return_value="ticket-1"),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cache.pop = AsyncMock(return_value={"user_id": "test-user-id"})
            mock_cache.set = AsyncMock()
            resp = authed_client.get(
                "/dropbox/callback?code=victim-code&state=valid",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "dropbox=complete" in resp.headers["location"]
        assert "ticket=ticket-1" in resp.headers["location"]
        mock_cache.pop.assert_awaited_once_with("dbx:oauth:valid")
        mock_cache.set.assert_awaited_once_with(
            "dbx:complete:ticket-1",
            {"user_id": "test-user-id", "code": "victim-code"},
            ttl=300,
        )
        mock_http.assert_not_called()

    def test_complete_rejects_cross_user_and_replay(self, authed_client):
        """A mismatched Dropbox grant is consumed before exchange and cannot replay."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch("app.api.dropbox_routes.cache_manager") as mock_cache,
                patch("httpx.AsyncClient") as mock_http,
            ):
                mock_cache.pop = AsyncMock(
                    side_effect=[
                        {"user_id": "attacker-user", "code": "victim-code"},
                        None,
                    ]
                )
                first = authed_client.post(
                    "/dropbox/complete", json={"ticket": "one-time-ticket"}
                )
                replay = authed_client.post(
                    "/dropbox/complete", json={"ticket": "one-time-ticket"}
                )

            assert first.status_code == 403
            assert replay.status_code == 400
            assert mock_cache.pop.await_count == 2
            mock_http.assert_not_called()
            mock_db.execute.assert_not_called()
            mock_db.commit.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_callback_denial_without_code_is_friendly(self, authed_client):
        with patch("app.api.dropbox_routes.cache_manager") as mock_cache:
            mock_cache.pop = AsyncMock(return_value={"user_id": "test-user-id"})
            resp = authed_client.get(
                "/dropbox/callback?error=access_denied&state=valid",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "access_denied" in resp.headers["location"]
        mock_cache.set.assert_not_called()

    def test_status_unauthenticated_returns_401(self):
        """GET /dropbox/status without auth returns 401."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.middleware.auth_middleware import get_current_user_required

        app.dependency_overrides.pop(get_current_user_required, None)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/dropbox/status")
        assert resp.status_code == 401

    def test_enable_sync_without_token_returns_400(self, authed_client):
        """Enable sync when user has no Dropbox token returns 400."""
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.dropbox_access_token = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.post("/dropbox/resumes/fake-resume-id/enable")
            assert resp.status_code == 400
            assert "not connected" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_disconnect_clears_tokens_and_disables_resumes(self, authed_client):
        """DELETE /dropbox/disconnect clears Dropbox fields on user and disables resume sync."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.delete("/dropbox/disconnect")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            # Should have executed 2 updates: one on users, one on resumes
            assert mock_db.execute.call_count >= 2
        finally:
            app.dependency_overrides.pop(get_db, None)


# ── Lazy token refresh + retry (Feature 77 hardening) ─────────────────────────


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    resp = MagicMock()
    resp.status_code = code
    return httpx.HTTPStatusError(str(code), request=MagicMock(), response=resp)


@pytest.mark.asyncio
class TestDropboxTokenRetry:
    def _user(self):
        from app.services.encryption_service import encryption_service
        user = MagicMock()
        user.id = "user-1"
        user.dropbox_access_token = encryption_service.encrypt("old-access")
        user.dropbox_refresh_token = encryption_service.encrypt("refresh-tok")
        return user

    async def test_no_refresh_on_success(self):
        """When the op succeeds, the token is never refreshed (no extra round-trip)."""
        from app.api import dropbox_routes

        user = self._user()
        db = AsyncMock()
        op = AsyncMock(return_value="ok")

        with patch.object(
            dropbox_routes.dropbox_sync_service, "refresh_access_token", new=AsyncMock()
        ) as refresh:
            result = await dropbox_routes._run_with_dropbox_token(user, db, op)

        assert result == "ok"
        op.assert_awaited_once()
        refresh.assert_not_awaited()

    async def test_refreshes_and_retries_on_401(self):
        """A 401 triggers a single refresh + persist + retry."""
        from app.api import dropbox_routes

        user = self._user()
        db = AsyncMock()
        op = AsyncMock(side_effect=[_http_status_error(401), "ok-after-refresh"])

        with patch.object(
            dropbox_routes.dropbox_sync_service,
            "refresh_access_token",
            new=AsyncMock(return_value="new-access"),
        ):
            result = await dropbox_routes._run_with_dropbox_token(user, db, op)

        assert result == "ok-after-refresh"
        assert op.await_count == 2
        # New access token persisted back to the user row.
        db.execute.assert_awaited()
        db.commit.assert_awaited()
        # Second op call used the freshly refreshed token.
        second_token = op.await_args_list[1].args[0]
        assert second_token == "new-access"

    async def test_non_401_error_not_retried(self):
        """A non-401 (e.g. 409 path-not-found) propagates without a refresh."""
        from app.api import dropbox_routes

        user = self._user()
        db = AsyncMock()
        op = AsyncMock(side_effect=_http_status_error(409))

        with patch.object(
            dropbox_routes.dropbox_sync_service, "refresh_access_token", new=AsyncMock()
        ) as refresh:
            with pytest.raises(httpx.HTTPStatusError):
                await dropbox_routes._run_with_dropbox_token(user, db, op)

        op.assert_awaited_once()
        refresh.assert_not_awaited()

    async def test_refresh_without_refresh_token_raises_401(self):
        """A 401 with no stored refresh token surfaces a reconnect (401)."""
        from fastapi import HTTPException

        from app.api import dropbox_routes

        user = self._user()
        user.dropbox_refresh_token = None
        db = AsyncMock()
        op = AsyncMock(side_effect=_http_status_error(401))

        with pytest.raises(HTTPException) as exc:
            await dropbox_routes._run_with_dropbox_token(user, db, op)
        assert exc.value.status_code == 401

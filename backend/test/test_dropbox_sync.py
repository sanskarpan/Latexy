"""Tests for Dropbox sync (Feature 77)."""

from unittest.mock import AsyncMock, MagicMock, patch

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
        """GET /dropbox/connect returns 503 when Dropbox is not configured."""
        original_key = settings.DROPBOX_APP_KEY
        original_secret = settings.DROPBOX_APP_SECRET
        try:
            settings.DROPBOX_APP_KEY = ""
            settings.DROPBOX_APP_SECRET = ""
            resp = authed_client.get("/dropbox/connect", follow_redirects=False)
            assert resp.status_code == 503
        finally:
            settings.DROPBOX_APP_KEY = original_key
            settings.DROPBOX_APP_SECRET = original_secret

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

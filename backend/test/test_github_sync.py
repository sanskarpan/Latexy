"""Tests for GitHub sync (Feature 37)."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.services.github_sync_service import GitHubSyncService

# ── GitHubSyncService unit tests ─────────────────────────────────────────────


class TestGitHubSyncService:
    """Tests for the sync service using mocked httpx."""

    @pytest.fixture()
    def service(self):
        return GitHubSyncService()

    @pytest.mark.asyncio
    async def test_ensure_repo_already_exists(self, service):
        """If repo already exists (200), no creation call is made."""
        mock_resp_get = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp_get

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await service.ensure_repo("tok", "user", "latexy-resumes")

        mock_client.get.assert_called_once()
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_repo_creates_new(self, service):
        """If repo doesn't exist (404), a POST is made to create it."""
        mock_resp_get = MagicMock(status_code=404)
        mock_resp_post = MagicMock(status_code=201)
        mock_resp_post.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp_get
        mock_client.post.return_value = mock_resp_post

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await service.ensure_repo("tok", "user", "latexy-resumes")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["json"]["private"] is True

    @pytest.mark.asyncio
    async def test_ensure_repo_422_name_exists_is_success(self, service):
        """A 422 whose body says the name already exists is treated as success."""
        mock_resp_get = MagicMock(status_code=404)
        mock_resp_post = MagicMock(status_code=422)
        mock_resp_post.json.return_value = {
            "message": "Repository creation failed.",
            "errors": [
                {"resource": "Repository", "field": "name",
                 "message": "name already exists on this account"}
            ],
        }
        mock_resp_post.raise_for_status = MagicMock(
            side_effect=AssertionError("raise_for_status must not be called for name-exists")
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp_get
        mock_client.post.return_value = mock_resp_post

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await service.ensure_repo("tok", "user", "latexy-resumes")

    @pytest.mark.asyncio
    async def test_ensure_repo_422_other_reason_raises(self, service):
        """A 422 for a non-collision reason (e.g. invalid name) is a real failure."""
        mock_resp_get = MagicMock(status_code=404)
        mock_resp_post = MagicMock(status_code=422)
        mock_resp_post.json.return_value = {
            "message": "Repository creation failed.",
            "errors": [
                {"resource": "Repository", "field": "name", "message": "is invalid"}
            ],
        }
        mock_resp_post.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("422", request=MagicMock(), response=mock_resp_post)
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp_get
        mock_client.post.return_value = mock_resp_post

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await service.ensure_repo("tok", "user", "bad name!")

    @pytest.mark.asyncio
    async def test_push_file_creates_new(self, service):
        """Push to a file that doesn't exist yet (no sha)."""
        mock_get_resp = MagicMock(status_code=404)
        mock_put_resp = MagicMock(status_code=201)
        mock_put_resp.raise_for_status = MagicMock()
        mock_put_resp.json.return_value = {"commit": {"html_url": "https://github.com/..."}}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_get_resp
        mock_client.put.return_value = mock_put_resp

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.push_file("tok", "user", "repo", "f.tex", "hello", "msg")

        mock_client.put.assert_called_once()
        put_kwargs = mock_client.put.call_args[1]
        assert "sha" not in put_kwargs["json"]
        assert put_kwargs["json"]["content"] == base64.b64encode(b"hello").decode("ascii")
        assert result["commit"]["html_url"] == "https://github.com/..."

    @pytest.mark.asyncio
    async def test_push_file_updates_existing(self, service):
        """Push to an existing file includes sha for update."""
        mock_get_resp = MagicMock(status_code=200)
        mock_get_resp.json.return_value = {"sha": "abc123"}
        mock_put_resp = MagicMock(status_code=200)
        mock_put_resp.raise_for_status = MagicMock()
        mock_put_resp.json.return_value = {"commit": {"html_url": "https://github.com/..."}}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_get_resp
        mock_client.put.return_value = mock_put_resp

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await service.push_file("tok", "user", "repo", "f.tex", "hi", "msg")

        put_kwargs = mock_client.put.call_args[1]
        assert put_kwargs["json"]["sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_pull_file_returns_decoded(self, service):
        """Pull decodes base64 file content."""
        encoded = base64.b64encode(b"\\documentclass{article}").decode("ascii")
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"content": encoded}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            content = await service.pull_file("tok", "user", "repo", "f.tex")

        assert content == "\\documentclass{article}"

    @pytest.mark.asyncio
    async def test_get_github_user(self, service):
        """get_github_user returns parsed JSON."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"login": "testuser", "id": 12345}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            user = await service.get_github_user("tok")

        assert user["login"] == "testuser"


# ── Endpoint tests (via TestClient with dependency overrides) ────────────────


@pytest.fixture()
def authed_client():
    """Create a TestClient with auth dependency overridden."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.auth_middleware import get_current_user_required

    app.dependency_overrides[get_current_user_required] = lambda: "test-user-id"
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.pop(get_current_user_required, None)


class TestGitHubEndpoints:
    """Integration-style tests for GitHub route handlers."""

    def test_connect_without_config_returns_503(self, authed_client):
        """GET /github/connect returns 503 when GitHub not configured."""
        original_id = settings.GITHUB_CLIENT_ID
        original_secret = settings.GITHUB_CLIENT_SECRET
        try:
            settings.GITHUB_CLIENT_ID = ""
            settings.GITHUB_CLIENT_SECRET = ""
            resp = authed_client.get("/github/connect", follow_redirects=False)
            assert resp.status_code == 503
        finally:
            settings.GITHUB_CLIENT_ID = original_id
            settings.GITHUB_CLIENT_SECRET = original_secret

    def test_status_unauthenticated_returns_401(self):
        """GET /github/status without auth returns 401."""
        from fastapi.testclient import TestClient

        from app.main import app

        # Ensure no override
        from app.middleware.auth_middleware import get_current_user_required
        app.dependency_overrides.pop(get_current_user_required, None)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/github/status")
        assert resp.status_code == 401

    def test_enable_sync_without_token_returns_400(self, authed_client):
        """Enable sync when user has no GitHub token returns 400."""
        from app.database.connection import get_db
        from app.main import app

        # Mock db to return a user without github token
        mock_user = MagicMock()
        mock_user.github_access_token = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.post(
                "/github/resumes/fake-id/enable",
                json={"repo_name": "test-repo"},
            )
            assert resp.status_code == 400
            assert "not connected" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_callback_empty_username_redirects_with_error(self, authed_client):
        """A profile with no login must not connect; redirect to settings with an error."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        token_resp = MagicMock()
        token_resp.raise_for_status = MagicMock()
        token_resp.json.return_value = {"access_token": "gho_abc"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=token_resp)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch("app.api.github_routes.cache_manager") as mock_cache,
                patch("httpx.AsyncClient") as MockClient,
                patch(
                    "app.api.github_routes.github_sync_service.get_github_user",
                    new=AsyncMock(return_value={"login": ""}),
                ),
            ):
                mock_cache.get = AsyncMock(return_value="test-user-id")
                mock_cache.delete = AsyncMock()
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = authed_client.get(
                    "/github/callback?code=abc&state=xyz", follow_redirects=False
                )

            assert resp.status_code in (302, 307)
            location = resp.headers.get("location", "")
            assert "github=error" in location
            assert "no_username" in location
            # Token must NOT be persisted
            mock_db.commit.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_callback_invalid_state_redirects_with_error(self, authed_client):
        """An expired/invalid state redirects to settings instead of raising JSON 400."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with patch("app.api.github_routes.cache_manager") as mock_cache:
                mock_cache.get = AsyncMock(return_value=None)
                resp = authed_client.get(
                    "/github/callback?code=abc&state=stale", follow_redirects=False
                )
            assert resp.status_code in (302, 307)
            assert "github=error" in resp.headers.get("location", "")
            assert "invalid_state" in resp.headers.get("location", "")
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_disconnect_clears_token(self, authed_client):
        """DELETE /github/disconnect clears github fields."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.delete("/github/disconnect")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            # Verify update calls were made (2 updates: users + resumes)
            assert mock_db.execute.call_count >= 2
        finally:
            app.dependency_overrides.pop(get_db, None)

"""Tests for GitHub sync (Feature 37)."""

import base64
import urllib.parse
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

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [204, 404])
    async def test_revoke_oauth_grant_is_idempotent(self, service, status_code):
        mock_response = MagicMock(status_code=status_code)
        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_response

        with patch("app.services.github_sync_service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            await service.revoke_oauth_grant("oauth-token", "client-id", "client-secret")

        _, kwargs = mock_client.delete.call_args
        assert kwargs["auth"] == ("client-id", "client-secret")
        assert kwargs["json"] == {"access_token": "oauth-token"}
        assert mock_response.raise_for_status.call_count == 0


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

    @pytest.mark.asyncio
    async def test_connect_returns_authorization_url_and_binds_state(self):
        """OAuth starts through an authenticated JSON request, not a bare redirect."""
        from app.api.github_routes import github_connect

        original_id = settings.GITHUB_CLIENT_ID
        original_secret = settings.GITHUB_CLIENT_SECRET
        try:
            settings.GITHUB_CLIENT_ID = "client-id"
            settings.GITHUB_CLIENT_SECRET = "client-secret"
            with (
                patch("app.api.github_routes.cache_manager") as mock_cache,
                patch("app.api.github_routes.secrets.token_urlsafe", return_value="state-nonce"),
            ):
                mock_cache.set = AsyncMock()
                result = await github_connect(user_id="test-user-id")

            assert result.authorization_url.startswith(
                "https://github.com/login/oauth/authorize?"
            )
            assert "state=state-nonce" in result.authorization_url
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(result.authorization_url).query)
            assert "scope" not in query
            mock_cache.set.assert_awaited_once_with(
                "gh:oauth:state-nonce",
                {
                    "user_id": "test-user-id",
                    "purpose": "import",
                    "return_to": None,
                },
                ttl=600,
            )
        finally:
            settings.GITHUB_CLIENT_ID = original_id
            settings.GITHUB_CLIENT_SECRET = original_secret

    @pytest.mark.asyncio
    async def test_connect_requests_repo_scope_only_for_private_sync(self):
        from app.api.github_routes import github_connect

        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "client-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "client-secret"),
            patch("app.api.github_routes.cache_manager") as mock_cache,
            patch("app.api.github_routes.secrets.token_urlsafe", return_value="state-nonce"),
        ):
            mock_cache.set = AsyncMock()
            result = await github_connect(
                purpose="sync",
                return_to="/workspace/resume-1/edit?import=github",
                user_id="test-user-id",
            )

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(result.authorization_url).query)
        assert query["scope"] == ["repo"]
        mock_cache.set.assert_awaited_once_with(
            "gh:oauth:state-nonce",
            {
                "user_id": "test-user-id",
                "purpose": "sync",
                "return_to": "/workspace/resume-1/edit?import=github",
            },
            ttl=600,
        )

    @pytest.mark.asyncio
    async def test_connect_drops_cross_origin_return_path(self):
        from app.api.github_routes import github_connect

        with (
            patch.object(settings, "GITHUB_CLIENT_ID", "client-id"),
            patch.object(settings, "GITHUB_CLIENT_SECRET", "client-secret"),
            patch("app.api.github_routes.cache_manager") as mock_cache,
        ):
            mock_cache.set = AsyncMock()
            await github_connect(
                return_to="//evil.example/steal",
                user_id="test-user-id",
            )

        payload = mock_cache.set.await_args.args[1]
        assert payload["return_to"] is None

    @pytest.mark.asyncio
    async def test_cache_pop_uses_atomic_getdel(self):
        """One-time OAuth records are consumed with Redis GETDEL."""
        from app.core import redis as redis_module

        original = redis_module.redis_cache_client
        mock_redis = AsyncMock()
        mock_redis.getdel = AsyncMock(
            return_value='{"user_id":"test-user-id","code":"provider-code"}'
        )
        redis_module.redis_cache_client = mock_redis
        try:
            result = await redis_module.cache_manager.pop("gh:complete:ticket")
        finally:
            redis_module.redis_cache_client = original

        assert result == {"user_id": "test-user-id", "code": "provider-code"}
        mock_redis.getdel.assert_awaited_once_with("cache:gh:complete:ticket")

    def test_connect_without_config_returns_503(self, authed_client):
        """POST /github/connect returns 503 when GitHub is not configured."""
        original_id = settings.GITHUB_CLIENT_ID
        original_secret = settings.GITHUB_CLIENT_SECRET
        try:
            settings.GITHUB_CLIENT_ID = ""
            settings.GITHUB_CLIENT_SECRET = ""
            resp = authed_client.post("/github/connect")
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

    def test_complete_empty_username_fails_without_persisting(self, authed_client):
        """A profile with no login must not persist a half-connected account."""
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
                mock_cache.pop = AsyncMock(
                    return_value={"user_id": "test-user-id", "code": "abc"}
                )
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                resp = authed_client.post("/github/complete", json={"ticket": "ticket-1"})

            assert resp.status_code == 502
            assert "username" in resp.json()["detail"].lower()
            # Token must NOT be persisted
            mock_db.commit.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_complete_records_actual_import_only_grant(self, authed_client):
        """The token response, not the requested scope, defines capabilities."""
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.user_metadata = {"mendeley_name": "Keep me"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        token_resp = MagicMock()
        token_resp.raise_for_status = MagicMock()
        token_resp.json.return_value = {
            "access_token": "oauth-token",
            "scope": "",
        }
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=token_resp)

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch("app.api.github_routes.cache_manager") as mock_cache,
                patch("app.api.github_routes.httpx.AsyncClient") as MockClient,
                patch(
                    "app.api.github_routes.github_sync_service.get_github_user",
                    new=AsyncMock(return_value={"login": "octocat"}),
                ),
                patch(
                    "app.api.github_routes.encryption_service.encrypt",
                    return_value="encrypted-token",
                ),
            ):
                mock_cache.pop = AsyncMock(
                    return_value={
                        "user_id": "test-user-id",
                        "code": "provider-code",
                        "purpose": "import",
                    }
                )
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                resp = authed_client.post(
                    "/github/complete",
                    json={"ticket": "ticket-1"},
                )

            assert resp.status_code == 200
            assert mock_user.github_access_token == "encrypted-token"
            assert mock_user.github_username == "octocat"
            assert mock_user.user_metadata == {
                "mendeley_name": "Keep me",
                "github_oauth": {"scopes": [], "purpose": "import"},
            }
            mock_db.commit.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_status_exposes_import_and_private_sync_capabilities(self, authed_client):
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.github_access_token = "encrypted-token"
        mock_user.github_username = "octocat"
        mock_user.user_metadata = {
            "github_oauth": {"scopes": [], "purpose": "import"}
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.get("/github/status")
            assert resp.status_code == 200
            assert resp.json() == {
                "connected": True,
                "username": "octocat",
                "public_import": True,
                "private_sync": False,
            }
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_enable_sync_rejects_import_only_grant(self, authed_client):
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.github_access_token = "encrypted-token"
        mock_user.user_metadata = {
            "github_oauth": {"scopes": [], "purpose": "import"}
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = authed_client.post(
                "/github/resumes/resume-1/enable",
                json={"repo_name": "latexy-resumes"},
            )
            assert resp.status_code == 403
            assert "private github sync permission" in resp.json()["detail"].lower()
            assert mock_db.execute.await_count == 1
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
                mock_cache.pop = AsyncMock(return_value=None)
                resp = authed_client.get(
                    "/github/callback?code=abc&state=stale", follow_redirects=False
                )
            assert resp.status_code in (302, 307)
            assert "github=error" in resp.headers.get("location", "")
            assert "invalid_state" in resp.headers.get("location", "")
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_callback_denial_without_code_redirects_with_friendly_error(self, authed_client):
        """Provider denial must not fall through to FastAPI's raw 422 response."""
        with patch("app.api.github_routes.cache_manager") as mock_cache:
            mock_cache.pop = AsyncMock(return_value={"user_id": "test-user-id"})
            resp = authed_client.get(
                "/github/callback?error=access_denied&state=valid",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "github=error" in resp.headers["location"]
        assert "access_denied" in resp.headers["location"]
        mock_cache.set.assert_not_called()

    def test_callback_only_issues_completion_ticket(self, authed_client):
        """The public callback stores a ticket but never exchanges or persists a token."""
        with (
            patch("app.api.github_routes.cache_manager") as mock_cache,
            patch("app.api.github_routes.secrets.token_urlsafe", return_value="complete-ticket"),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_cache.pop = AsyncMock(return_value={"user_id": "test-user-id"})
            mock_cache.set = AsyncMock()
            resp = authed_client.get(
                "/github/callback?code=provider-code&state=valid",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "github=complete" in resp.headers["location"]
        assert "ticket=complete-ticket" in resp.headers["location"]
        mock_cache.pop.assert_awaited_once_with("gh:oauth:valid")
        mock_cache.set.assert_awaited_once_with(
            "gh:complete:complete-ticket",
            {
                "user_id": "test-user-id",
                "code": "provider-code",
                "purpose": "import",
                "return_to": None,
            },
            ttl=300,
        )
        mock_http.assert_not_called()

    def test_complete_rejects_cross_user_ticket_before_exchange(self, authed_client):
        """A victim browser cannot attach its GitHub grant to the attacker's account."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch("app.api.github_routes.cache_manager") as mock_cache,
                patch("httpx.AsyncClient") as mock_http,
            ):
                mock_cache.pop = AsyncMock(
                    return_value={"user_id": "attacker-user", "code": "victim-code"}
                )
                resp = authed_client.post(
                    "/github/complete", json={"ticket": "stolen-ticket"}
                )

            assert resp.status_code == 403
            assert "different user" in resp.json()["detail"].lower()
            mock_cache.pop.assert_awaited_once_with("gh:complete:stolen-ticket")
            mock_http.assert_not_called()
            mock_db.execute.assert_not_called()
            mock_db.commit.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_complete_ticket_is_single_use(self, authed_client):
        """An atomically consumed completion ticket cannot be replayed."""
        from app.database.connection import get_db
        from app.main import app

        mock_db = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch("app.api.github_routes.cache_manager") as mock_cache,
                patch("httpx.AsyncClient") as mock_http,
            ):
                mock_cache.pop = AsyncMock(
                    side_effect=[
                        {"user_id": "other-user", "code": "provider-code"},
                        None,
                    ]
                )
                first = authed_client.post(
                    "/github/complete", json={"ticket": "one-time-ticket"}
                )
                replay = authed_client.post(
                    "/github/complete", json={"ticket": "one-time-ticket"}
                )

            assert first.status_code == 403
            assert replay.status_code == 400
            assert "invalid or expired" in replay.json()["detail"].lower()
            assert mock_cache.pop.await_count == 2
            mock_http.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_disconnect_revokes_grant_before_clearing_token(self, authed_client):
        """DELETE /github/disconnect revokes upstream and clears local fields."""
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.github_access_token = "encrypted-token"
        mock_user.github_username = "octocat"
        mock_user.user_metadata = {
            "github_oauth": {"scopes": ["repo"], "purpose": "sync"},
            "mendeley_name": "Keep me",
        }
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch(
                    "app.api.github_routes.encryption_service.decrypt",
                    return_value="oauth-token",
                ),
                patch(
                    "app.api.github_routes.github_sync_service.revoke_oauth_grant",
                    new=AsyncMock(),
                ) as revoke,
            ):
                resp = authed_client.delete("/github/disconnect")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            revoke.assert_awaited_once_with(
                "oauth-token",
                settings.GITHUB_CLIENT_ID,
                settings.GITHUB_CLIENT_SECRET,
            )
            assert mock_user.github_access_token is None
            assert mock_user.github_username is None
            assert mock_user.user_metadata == {"mendeley_name": "Keep me"}
            assert mock_db.execute.call_count >= 2
            mock_db.commit.assert_awaited_once()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_disconnect_keeps_local_token_when_revocation_fails(self, authed_client):
        from app.database.connection import get_db
        from app.main import app

        mock_user = MagicMock()
        mock_user.github_access_token = "encrypted-token"
        mock_user.github_username = "octocat"
        mock_user.user_metadata = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with (
                patch(
                    "app.api.github_routes.encryption_service.decrypt",
                    return_value="oauth-token",
                ),
                patch(
                    "app.api.github_routes.github_sync_service.revoke_oauth_grant",
                    new=AsyncMock(side_effect=httpx.ConnectError("offline")),
                ),
            ):
                resp = authed_client.delete("/github/disconnect")

            assert resp.status_code == 502
            assert "nothing was disconnected" in resp.json()["detail"]
            assert mock_user.github_access_token == "encrypted-token"
            mock_db.commit.assert_not_awaited()
        finally:
            app.dependency_overrides.pop(get_db, None)

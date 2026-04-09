"""Tests for Feature 42 — Zotero / Mendeley Reference Import."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"

SAMPLE_BIBTEX = """\
@article{smith2020,
  title={Example Article},
  author={Smith, John},
  year={2020},
  journal={Nature},
}

@book{jones2019,
  title={A Great Book},
  author={Jones, Alice},
  year={2019},
  publisher={Springer},
}
"""


async def _get_user(db_session: AsyncSession, auth_headers: dict) -> User:
    """Retrieve the User row matching the auth Bearer token."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    result = await db_session.execute(
        text('SELECT "userId" FROM session WHERE token = :token'),
        {"token": token},
    )
    user_id = result.scalar_one()
    user_result = await db_session.execute(select(User).where(User.id == user_id))
    return user_result.scalar_one()


async def _create_resume(
    client: AsyncClient, auth_headers: dict, title: str = "Test Resume"
) -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit tests — OAuth 1.0a helpers (no DB / network)
# ---------------------------------------------------------------------------


def test_oauth1_signature_is_deterministic():
    """Same inputs → same HMAC-SHA1 signature."""
    from app.api.zotero_routes import _oauth1_signature

    params = {
        "oauth_nonce": "abc",
        "oauth_timestamp": "1234567890",
        "oauth_consumer_key": "key",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_version": "1.0",
    }
    sig1 = _oauth1_signature(
        "POST",
        "https://www.zotero.org/oauth/request",
        params,
        {"oauth_callback": "http://localhost/callback"},
        "consumer_secret",
        "",
    )
    sig2 = _oauth1_signature(
        "POST",
        "https://www.zotero.org/oauth/request",
        params,
        {"oauth_callback": "http://localhost/callback"},
        "consumer_secret",
        "",
    )
    assert sig1 == sig2
    assert len(sig1) > 10


def test_oauth1_different_secrets_differ():
    from app.api.zotero_routes import _oauth1_signature

    params = {
        "oauth_nonce": "abc",
        "oauth_timestamp": "111",
        "oauth_consumer_key": "k",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_version": "1.0",
    }
    sig1 = _oauth1_signature("POST", "https://example.com", params, {}, "secret1", "")
    sig2 = _oauth1_signature("POST", "https://example.com", params, {}, "secret2", "")
    assert sig1 != sig2


def test_oauth1_header_contains_required_fields():
    from app.api.zotero_routes import _oauth1_header

    header = _oauth1_header(
        "POST",
        "https://www.zotero.org/oauth/request",
        "my_consumer_key",
        "my_consumer_secret",
    )
    assert header.startswith("OAuth ")
    assert "oauth_consumer_key" in header
    assert "oauth_signature" in header
    assert "oauth_timestamp" in header
    assert "oauth_nonce" in header


def test_bibtex_entry_count_heuristic():
    count = SAMPLE_BIBTEX.count("\n@") + (1 if SAMPLE_BIBTEX.startswith("@") else 0)
    assert count == 2


# ---------------------------------------------------------------------------
# Zotero status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestZoteroStatus:
    async def test_status_not_connected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/zotero/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["username"] is None

    async def test_status_connected(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok123"),
            "zotero_user_id": "42",
            "zotero_username": "testuser",
        }
        await db_session.commit()

        resp = await client.get("/zotero/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["username"] == "testuser"


# ---------------------------------------------------------------------------
# Zotero connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestZoteroConnect:
    async def test_connect_returns_503_when_unconfigured(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch("app.api.zotero_routes.settings") as mock_settings:
            mock_settings.ZOTERO_CLIENT_KEY = ""
            mock_settings.ZOTERO_CLIENT_SECRET = ""
            resp = await client.get(
                "/zotero/connect", headers=auth_headers, follow_redirects=False
            )
        assert resp.status_code == 503

    async def test_connect_redirects_to_zotero(
        self, client: AsyncClient, auth_headers: dict
    ):
        mock_resp = MagicMock()
        mock_resp.text = "oauth_token=reqtok&oauth_token_secret=reqsec"
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("app.api.zotero_routes.settings") as mock_settings,
            patch("app.api.zotero_routes.cache_manager") as mock_cache,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.ZOTERO_CLIENT_KEY = "key"
            mock_settings.ZOTERO_CLIENT_SECRET = "secret"
            mock_settings.ZOTERO_REDIRECT_URI = "http://localhost/cb"
            mock_cache.set = AsyncMock()
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.get(
                "/zotero/connect", headers=auth_headers, follow_redirects=False
            )

        assert resp.status_code in (302, 307)
        assert "zotero.org/oauth/authorize" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Zotero import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestZoteroImport:
    async def test_import_without_token_returns_401(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/zotero/import",
            json={"resume_id": "00000000-0000-0000-0000-000000000000"},
            headers=auth_headers,
        )
        assert resp.status_code == 401
        assert "not connected" in resp.json()["detail"].lower()

    async def test_import_stores_bibtex_in_resume(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("api_key_123"),
            "zotero_user_id": "999",
            "zotero_username": "testuser",
        }
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BIBTEX
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/zotero/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["entries_count"] == 2
        assert "@article" in data["bibtex"]

        # Verify stored in resume.metadata via GET
        get_resp = await client.get(f"/resumes/{resume['id']}", headers=auth_headers)
        assert get_resp.status_code == 200
        meta = get_resp.json().get("metadata") or {}
        assert "bibtex" in meta

    async def test_import_zotero_api_error_returns_502(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok"),
            "zotero_user_id": "1",
        }
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=error_resp
            )
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=error_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/zotero/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 502

    async def test_import_invalid_token_returns_401(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("expired_tok"),
            "zotero_user_id": "1",
        }
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        forbidden_resp = MagicMock()
        forbidden_resp.status_code = 403
        forbidden_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=forbidden_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/zotero/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 401

    async def test_import_wrong_resume_returns_404(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok"),
            "zotero_user_id": "1",
        }
        await db_session.commit()

        resp = await client.post(
            "/zotero/import",
            json={"resume_id": "00000000-0000-0000-0000-000000000099"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_import_with_collection_uses_collection_url(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok"),
            "zotero_user_id": "999",
        }
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_BIBTEX
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        captured_urls: list[str] = []

        async def fake_get(url: str, **kwargs):
            captured_urls.append(url)
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = fake_get
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/zotero/import",
                json={"resume_id": resume["id"], "collection_key": "ABCD1234"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert any("collections/ABCD1234" in u for u in captured_urls)

    async def test_collection_key_too_long_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """collection_key > 20 chars → Pydantic 422."""
        resp = await client.post(
            "/zotero/import",
            json={
                "resume_id": "00000000-0000-0000-0000-000000000000",
                "collection_key": "X" * 21,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Zotero disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestZoteroDisconnect:
    async def test_disconnect_clears_token(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok"),
            "zotero_user_id": "1",
            "zotero_username": "u",
        }
        await db_session.commit()

        resp = await client.delete("/zotero/disconnect", headers=auth_headers)
        assert resp.status_code == 200

        status_resp = await client.get("/zotero/status", headers=auth_headers)
        assert status_resp.json()["connected"] is False


# ---------------------------------------------------------------------------
# Zotero collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestZoteroCollections:
    async def test_collections_without_token_returns_401(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get("/zotero/collections", headers=auth_headers)
        assert resp.status_code == 401

    async def test_collections_returns_list(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "zotero_token": encryption_service.encrypt("tok"),
            "zotero_user_id": "999",
        }
        await db_session.commit()

        api_resp = [
            {"key": "COL1", "data": {"name": "My Papers"}},
            {"key": "COL2", "data": {"name": "Books"}},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=api_resp)
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.get("/zotero/collections", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["collections"]) == 2
        assert data["collections"][0]["key"] == "COL1"


# ---------------------------------------------------------------------------
# Mendeley status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMendeleyStatus:
    async def test_status_not_connected(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/mendeley/status", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["connected"] is False

    async def test_status_connected(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "mendeley_token": encryption_service.encrypt("mtok"),
            "mendeley_name": "Alice Scholar",
        }
        await db_session.commit()

        resp = await client.get("/mendeley/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["name"] == "Alice Scholar"


# ---------------------------------------------------------------------------
# Mendeley connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMendeleyConnect:
    async def test_connect_returns_503_when_unconfigured(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch("app.api.mendeley_routes.settings") as mock_settings:
            mock_settings.MENDELEY_CLIENT_ID = ""
            mock_settings.MENDELEY_CLIENT_SECRET = ""
            resp = await client.get(
                "/mendeley/connect", headers=auth_headers, follow_redirects=False
            )
        assert resp.status_code == 503

    async def test_connect_redirects_to_mendeley(
        self, client: AsyncClient, auth_headers: dict
    ):
        with (
            patch("app.api.mendeley_routes.settings") as mock_settings,
            patch("app.api.mendeley_routes.cache_manager") as mock_cache,
        ):
            mock_settings.MENDELEY_CLIENT_ID = "mid"
            mock_settings.MENDELEY_CLIENT_SECRET = "msec"
            mock_settings.MENDELEY_REDIRECT_URI = "http://localhost/cb"
            mock_cache.set = AsyncMock()
            resp = await client.get(
                "/mendeley/connect", headers=auth_headers, follow_redirects=False
            )

        assert resp.status_code in (302, 307)
        assert "mendeley.com/oauth/authorize" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Mendeley import
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMendeleyImport:
    async def test_import_without_token_returns_401(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/mendeley/import",
            json={"resume_id": "00000000-0000-0000-0000-000000000000"},
            headers=auth_headers,
        )
        assert resp.status_code == 401

    async def test_import_stores_bibtex(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {"mendeley_token": encryption_service.encrypt("mtoken")}
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        probe_resp = MagicMock()
        probe_resp.status_code = 200

        bibtex_resp = MagicMock()
        bibtex_resp.text = SAMPLE_BIBTEX
        bibtex_resp.status_code = 200
        bibtex_resp.raise_for_status = MagicMock()
        bibtex_resp.headers = {}

        async def fake_get(url: str, **kwargs):
            if "profiles/me" in url:
                return probe_resp
            return bibtex_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = fake_get
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/mendeley/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert "@article" in data["bibtex"]

    async def test_mendeley_api_error_returns_502(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {"mendeley_token": encryption_service.encrypt("mtoken")}
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        probe_resp = MagicMock()
        probe_resp.status_code = 200

        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=error_resp
            )
        )

        async def fake_get(url: str, **kwargs):
            if "profiles/me" in url:
                return probe_resp
            return error_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = fake_get
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/mendeley/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 502

    async def test_mendeley_expired_token_without_refresh_returns_401(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        """Expired access token, no refresh_token stored → 401."""
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "mendeley_token": encryption_service.encrypt("expired"),
            # no mendeley_refresh_token
        }
        await db_session.commit()

        resume = await _create_resume(client, auth_headers)

        probe_resp = MagicMock()
        probe_resp.status_code = 401  # token invalid

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=probe_resp)
            mock_client_cls.return_value = mock_instance

            resp = await client.post(
                "/mendeley/import",
                json={"resume_id": resume["id"]},
                headers=auth_headers,
            )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Mendeley disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMendeleyDisconnect:
    async def test_disconnect_clears_token(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        from app.services.encryption_service import encryption_service

        user = await _get_user(db_session, auth_headers)
        user.user_metadata = {
            "mendeley_token": encryption_service.encrypt("tok"),
            "mendeley_name": "Alice",
        }
        await db_session.commit()

        resp = await client.delete("/mendeley/disconnect", headers=auth_headers)
        assert resp.status_code == 200

        status_resp = await client.get("/mendeley/status", headers=auth_headers)
        assert status_resp.json()["connected"] is False

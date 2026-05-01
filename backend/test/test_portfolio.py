"""
Tests for Features 67 & 68 — Portfolio and Portfolio Site Generation.

Coverage map:
  ── Service unit tests (TestPortfolioGeneratorUnit) ──────────────────────────
  67U-01  PortfolioGenerator._render produces valid HTML with user name
  67U-02  _render falls back to username when user.name is None
  67U-03  _render includes resume title in output
  67U-04  _render with unknown theme falls back to minimal template

  ── HTTP integration tests (TestPortfolioEndpoints) ──────────────────────────
  67I-01  GET /portfolio/{username} with portfolio_enabled=False → 404
  67I-02  GET /portfolio/{username} with enabled portfolio → 200 + user data
  67I-03  GET /portfolio/check-username — available username → available=True
  67I-04  GET /portfolio/check-username — taken username → available=False
  67I-05  GET /portfolio/check-username — too short (1 char) → 422
  67I-06  GET /portfolio/check-username — special chars (@) → 422
  67I-07  POST /portfolio/setup — valid data → 200, portfolio configured
  67I-08  POST /portfolio/setup — duplicate username → 409
  67I-09  POST /portfolio/setup — invalid username (spaces) → 422
  67I-10  POST /portfolio/setup — invalid theme → 422
  67I-11  GET /portfolio/resolve-domain — registered domain → username returned
  67I-12  GET /portfolio/resolve-domain — unknown domain → username=None

  ── Portfolio generator endpoint (TestGeneratePortfolioEndpoint) ─────────────
  68I-01  POST /resumes/{resume_id}/generate-portfolio — resume not found → 404
  68I-02  POST /resumes/{resume_id}/generate-portfolio — valid → 200 + portfolio_url
  68I-03  POST /resumes/{resume_id}/generate-portfolio — no auth → 401

  ── Authentication tests (TestPortfolioAuth) ─────────────────────────────────
  67A-01  GET /portfolio/{username} — no auth → 200 (public endpoint)
  67A-02  POST /portfolio/setup — no auth → 401
  67A-03  POST /portfolio/setup — valid auth → 200
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from conftest import _insert_session
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.portfolio_generator import PortfolioGenerator

# ── Shared constants ───────────────────────────────────────────────────────────

VALID_USERNAME = f"testuser{uuid.uuid4().hex[:6]}"


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def test_user(db_session: AsyncSession) -> dict[str, str]:
    """Create a minimal user row and return its id + email."""
    user_id = str(uuid.uuid4())
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db_session.execute(
        text(
            "INSERT INTO users "
            "(id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Portfolio Test User', true, 'free', 'active', false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )
    await db_session.commit()
    return {"id": user_id, "email": email}


@pytest.fixture
async def portfolio_auth_headers(
    db_session: AsyncSession, test_user: dict[str, str]
) -> dict[str, str]:
    """Valid Bearer token for the test_user."""
    token = await _insert_session(db_session, test_user["id"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def portfolio_user(db_session: AsyncSession, test_user: dict[str, str]) -> dict[str, str]:
    """Create a user with portfolio enabled and a distinct username."""
    username = f"pf_{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(
            "UPDATE users SET public_username = :uname, portfolio_enabled = true, "
            "portfolio_theme = 'minimal', portfolio_tagline = 'Test tagline' "
            "WHERE id = :uid"
        ),
        {"uname": username, "uid": test_user["id"]},
    )
    await db_session.commit()
    return {**test_user, "username": username}


@pytest.fixture
async def test_resume(db_session: AsyncSession, test_user: dict[str, str]) -> dict[str, str]:
    """Create a minimal resume row and return its id."""
    resume_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO resumes (id, user_id, title, latex_content, is_template) "
            "VALUES (:id, :uid, 'Test Resume', '\\\\documentclass{article}', false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": resume_id, "uid": test_user["id"]},
    )
    await db_session.commit()
    return {"id": resume_id, "user_id": test_user["id"]}


# ── Patch helper for MinIO ────────────────────────────────────────────────────


def _patch_minio():
    """Patch storage_service calls so tests don't need MinIO."""
    return patch(
        "app.services.portfolio_generator.storage_service.upload_bytes",
        return_value=None,
    ), patch(
        "app.services.portfolio_generator.storage_service.generate_presigned_url",
        return_value="https://minio.test/portfolio/user/resume/index.html",
    )


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestPortfolioGeneratorUnit:
    """67U-xx — direct service tests, no HTTP, no database."""

    def _make_user(self, *, name: str | None = "Alice Smith", username: str = "alice") -> MagicMock:
        u = MagicMock()
        u.name = name
        u.public_username = username
        u.portfolio_tagline = "Building things"
        u.portfolio_theme = "minimal"
        return u

    def _make_resume(self, title: str = "My Resume") -> MagicMock:
        from datetime import datetime, timezone
        r = MagicMock()
        r.title = title
        r.id = str(uuid.uuid4())
        r.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
        return r

    # 67U-01 ─────────────────────────────────────────────────────────────────
    def test_render_contains_user_name(self) -> None:
        """_render produces HTML that includes the user's display name."""
        gen = PortfolioGenerator()
        html = gen._render(self._make_resume(), self._make_user(), "minimal")
        assert "Alice Smith" in html

    # 67U-02 ─────────────────────────────────────────────────────────────────
    def test_render_falls_back_to_username_when_name_none(self) -> None:
        """_render falls back to username when user.name is None."""
        gen = PortfolioGenerator()
        user = self._make_user(name=None, username="alice")
        html = gen._render(self._make_resume(), user, "minimal")
        assert "alice" in html

    # 67U-03 ─────────────────────────────────────────────────────────────────
    def test_render_includes_resume_title(self) -> None:
        """_render includes the resume title in the HTML."""
        gen = PortfolioGenerator()
        html = gen._render(self._make_resume("My Awesome Resume"), self._make_user(), "minimal")
        assert "My Awesome Resume" in html

    # 67U-04 ─────────────────────────────────────────────────────────────────
    def test_render_unknown_theme_falls_back_to_minimal(self) -> None:
        """_render with an unknown theme name falls back to minimal.html.j2."""
        gen = PortfolioGenerator()
        # Should not raise even with an unknown theme
        html = gen._render(self._make_resume(), self._make_user(), "nonexistent_theme_xyz")
        assert "<!DOCTYPE html>" in html


# ── HTTP integration tests ─────────────────────────────────────────────────────


class TestPortfolioEndpoints:
    """67I-xx — end-to-end HTTP tests against the ASGI app."""

    # 67I-01 ─────────────────────────────────────────────────────────────────
    async def test_get_portfolio_disabled_returns_404(
        self, client: AsyncClient, test_user: dict[str, str], db_session: AsyncSession
    ) -> None:
        """GET /portfolio/{username} with portfolio_enabled=False → 404."""
        username = f"disabled_{uuid.uuid4().hex[:8]}"
        await db_session.execute(
            text(
                "UPDATE users SET public_username = :uname, portfolio_enabled = false "
                "WHERE id = :uid"
            ),
            {"uname": username, "uid": test_user["id"]},
        )
        await db_session.commit()

        resp = await client.get(f"/portfolio/{username}")
        assert resp.status_code == 404

    # 67I-02 ─────────────────────────────────────────────────────────────────
    async def test_get_portfolio_enabled_returns_200(
        self, client: AsyncClient, portfolio_user: dict[str, str]
    ) -> None:
        """GET /portfolio/{username} with enabled portfolio → 200 + user data."""
        resp = await client.get(f"/portfolio/{portfolio_user['username']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == portfolio_user["username"]
        assert "resumes" in data

    # 67I-03 ─────────────────────────────────────────────────────────────────
    async def test_check_username_available(self, client: AsyncClient) -> None:
        """GET /portfolio/check-username — fresh username → available=True."""
        username = f"fresh_{uuid.uuid4().hex[:10]}"
        resp = await client.get(f"/portfolio/check-username?username={username}")
        assert resp.status_code == 200
        assert resp.json()["available"] is True

    # 67I-04 ─────────────────────────────────────────────────────────────────
    async def test_check_username_taken(
        self, client: AsyncClient, portfolio_user: dict[str, str]
    ) -> None:
        """GET /portfolio/check-username — already registered username → available=False."""
        resp = await client.get(
            f"/portfolio/check-username?username={portfolio_user['username']}"
        )
        assert resp.status_code == 200
        assert resp.json()["available"] is False

    # 67I-05 ─────────────────────────────────────────────────────────────────
    async def test_check_username_too_short_returns_422(self, client: AsyncClient) -> None:
        """GET /portfolio/check-username — 1-char username → 422."""
        resp = await client.get("/portfolio/check-username?username=a")
        assert resp.status_code == 422

    # 67I-06 ─────────────────────────────────────────────────────────────────
    async def test_check_username_special_chars_returns_422(self, client: AsyncClient) -> None:
        """GET /portfolio/check-username — username with @ → 422."""
        resp = await client.get("/portfolio/check-username?username=bad@user")
        assert resp.status_code == 422

    # 67I-07 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_valid(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
    ) -> None:
        """POST /portfolio/setup — valid data → 200 with portfolio_url."""
        username = f"setup_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/portfolio/setup",
            json={"public_username": username, "portfolio_enabled": True, "theme": "minimal"},
            headers=portfolio_auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["public_username"] == username
        assert data["portfolio_url"] == f"/u/{username}"

    # 67I-08 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_duplicate_username_returns_409(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
        portfolio_user: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """POST /portfolio/setup — username already taken by another user → 409."""
        # Create a second user
        other_id = str(uuid.uuid4())
        other_email = f"test_{other_id.replace('-', '')}@example.com"
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, "
                "subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other User', true, 'free', 'active', false)"
            ),
            {"id": other_id, "email": other_email},
        )
        other_token = await _insert_session(db_session, other_id)
        await db_session.commit()

        resp = await client.post(
            "/portfolio/setup",
            json={
                "public_username": portfolio_user["username"],
                "portfolio_enabled": True,
                "theme": "minimal",
            },
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 409

    # 67I-09 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_spaces_in_username_returns_422(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
    ) -> None:
        """POST /portfolio/setup — username with spaces → 422."""
        resp = await client.post(
            "/portfolio/setup",
            json={"public_username": "bad user name", "portfolio_enabled": True},
            headers=portfolio_auth_headers,
        )
        assert resp.status_code == 422

    # 67I-10 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_invalid_theme_returns_422(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
    ) -> None:
        """POST /portfolio/setup — invalid theme value → 422."""
        username = f"themed_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/portfolio/setup",
            json={
                "public_username": username,
                "portfolio_enabled": True,
                "theme": "rainbow_unicorn",
            },
            headers=portfolio_auth_headers,
        )
        assert resp.status_code == 422

    # 67I-11 ─────────────────────────────────────────────────────────────────
    async def test_resolve_domain_registered(
        self,
        client: AsyncClient,
        portfolio_user: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """GET /portfolio/resolve-domain — domain registered for enabled user → username."""
        domain = f"test{uuid.uuid4().hex[:6]}.example.com"
        await db_session.execute(
            text(
                "UPDATE users SET portfolio_custom_domain = :domain WHERE id = :uid"
            ),
            {"domain": domain, "uid": portfolio_user["id"]},
        )
        await db_session.commit()

        resp = await client.get(f"/portfolio/resolve-domain?domain={domain}")
        assert resp.status_code == 200
        assert resp.json()["username"] == portfolio_user["username"]

    # 67I-12 ─────────────────────────────────────────────────────────────────
    async def test_resolve_domain_unknown(self, client: AsyncClient) -> None:
        """GET /portfolio/resolve-domain — unknown domain → username=None."""
        resp = await client.get("/portfolio/resolve-domain?domain=unknown-domain.test")
        assert resp.status_code == 200
        assert resp.json()["username"] is None


# ── Portfolio generator endpoint ──────────────────────────────────────────────


class TestGeneratePortfolioEndpoint:
    """68I-xx — POST /resumes/{resume_id}/generate-portfolio."""

    # 68I-01 ─────────────────────────────────────────────────────────────────
    async def test_generate_portfolio_not_found_returns_404(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
    ) -> None:
        """Non-existent resume_id → 404."""
        fake_id = str(uuid.uuid4())
        with patch(
            "app.services.portfolio_generator.storage_service.upload_bytes",
            return_value=None,
        ):
            resp = await client.post(
                f"/resumes/{fake_id}/generate-portfolio",
                headers=portfolio_auth_headers,
            )
        assert resp.status_code == 404

    # 68I-02 ─────────────────────────────────────────────────────────────────
    async def test_generate_portfolio_valid_returns_url(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
        test_resume: dict[str, str],
    ) -> None:
        """Valid resume + auth → 200 with portfolio_url."""
        upload_patch, presign_patch = _patch_minio()
        with upload_patch, presign_patch:
            resp = await client.post(
                f"/resumes/{test_resume['id']}/generate-portfolio",
                headers=portfolio_auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio_url" in data
        assert data["portfolio_url"]

    # 68I-03 ─────────────────────────────────────────────────────────────────
    async def test_generate_portfolio_no_auth_returns_401(
        self,
        client: AsyncClient,
        test_resume: dict[str, str],
    ) -> None:
        """No auth header → 401."""
        resp = await client.post(f"/resumes/{test_resume['id']}/generate-portfolio")
        assert resp.status_code == 401


# ── Authentication tests ──────────────────────────────────────────────────────


class TestPortfolioAuth:
    """67A-xx — auth behaviour on portfolio endpoints."""

    # 67A-01 ─────────────────────────────────────────────────────────────────
    async def test_get_portfolio_no_auth_is_public(
        self,
        client: AsyncClient,
        portfolio_user: dict[str, str],
    ) -> None:
        """Public portfolio page accessible without any auth token."""
        resp = await client.get(f"/portfolio/{portfolio_user['username']}")
        assert resp.status_code == 200

    # 67A-02 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_no_auth_returns_401(self, client: AsyncClient) -> None:
        """POST /portfolio/setup without auth → 401."""
        resp = await client.post(
            "/portfolio/setup",
            json={"public_username": "anon_user", "portfolio_enabled": True},
        )
        assert resp.status_code == 401

    # 67A-03 ─────────────────────────────────────────────────────────────────
    async def test_setup_portfolio_with_valid_auth_returns_200(
        self,
        client: AsyncClient,
        portfolio_auth_headers: dict[str, str],
    ) -> None:
        """POST /portfolio/setup with valid auth → 200."""
        username = f"auth_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/portfolio/setup",
            json={"public_username": username, "portfolio_enabled": True, "theme": "dark"},
            headers=portfolio_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["theme"] == "dark"

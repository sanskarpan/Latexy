"""
GAP-002 — Extended auth middleware tests.

Covers:
  1. require_admin() blocks non-admin users (HTTP 403)
  2. require_admin() allows the ADMIN_EMAIL user
  3. require_admin() does NOT allow legacy JWT with is_admin=true (AUTH-001 fix)
  4. Optional auth returns None for unauthenticated requests
  5. Required auth returns 401 for unauthenticated requests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_JWT_SECRET = "test_jwt_secret_32chars_minimum_!"  # matches conftest.py override


def _make_jwt(
    user_id: str,
    secret: str = _JWT_SECRET,
    is_admin: bool = False,
    role: str | None = None,
    expired: bool = False,
) -> str:
    exp_delta = timedelta(hours=-1) if expired else timedelta(hours=1)
    payload: dict = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + exp_delta,
    }
    if is_admin:
        payload["is_admin"] = True
    if role:
        payload["role"] = role
    return pyjwt.encode(payload, secret, algorithm="HS256")


async def _create_user(db: AsyncSession, email: str | None = None) -> tuple[str, str]:
    """Insert a user row; return (user_id, email)."""
    user_id = str(uuid.uuid4())
    if email is None:
        email = f"test_{user_id.replace('-','')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Admin Test', true, 'pro', 'active', false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": user_id, "email": email},
    )
    await db.commit()
    return user_id, email


async def _create_session(db: AsyncSession, user_id: str) -> str:
    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


# ─────────────────────────────────────────────────────────────────────────────
# 1–3: require_admin() behaviour
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestRequireAdmin:
    """Tests for the require_admin FastAPI dependency via /admin/feature-flags."""

    # ── 1. Non-admin is blocked with 403 ────────────────────────────────────

    async def test_non_admin_user_gets_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A fully-authenticated user whose email is not ADMIN_EMAIL gets 403."""
        user_id, _ = await _create_user(db_session)
        token = await _create_session(db_session, user_id)

        with patch("app.middleware.auth_middleware.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "admin@latexy.com"  # set but does not match
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 403

    # ── 2. ADMIN_EMAIL user is allowed ──────────────────────────────────────

    async def test_admin_email_user_gets_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A user whose email matches ADMIN_EMAIL gets 200 from the admin endpoint."""
        admin_email = f"test_admin_{uuid.uuid4().hex[:8]}@latexy.com"
        user_id, _ = await _create_user(db_session, email=admin_email)
        token = await _create_session(db_session, user_id)

        with patch("app.middleware.auth_middleware.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = admin_email
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

    # ── 3. Legacy JWT with is_admin=true does NOT bypass ADMIN_EMAIL (AUTH-001) ──

    async def test_jwt_is_admin_does_not_bypass_admin_email_gate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        A legacy JWT carrying is_admin=true must NOT grant admin access.
        The require_admin dependency enforces email-based gate only (AUTH-001).
        """
        # This user is NOT in the DB — simulate a JWT-only user
        attacker_id = str(uuid.uuid4())
        jwt_token = _make_jwt(attacker_id, is_admin=True)

        # ADMIN_EMAIL is set to a completely different address
        with patch("app.middleware.auth_middleware.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "real_admin@latexy.com"
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        # Must be 403 — JWT is_admin claim must not be honoured
        assert resp.status_code == 403

    # ── Extra: no ADMIN_EMAIL configured → 403 even for admin ───────────────

    async def test_unconfigured_admin_email_blocks_everyone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """If ADMIN_EMAIL is not configured, require_admin raises 403 for all users."""
        user_id, _ = await _create_user(db_session)
        token = await _create_session(db_session, user_id)

        with patch("app.middleware.auth_middleware.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = ""  # not configured
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 403

    # ── Extra: unauthenticated request to admin endpoint returns 401 ─────────

    async def test_unauthenticated_admin_request_returns_401(
        self, client: AsyncClient
    ):
        """No credentials → require_admin should raise 401 before checking email."""
        resp = await client.get("/admin/feature-flags")
        assert resp.status_code == 401

    # ── Extra: DB failure during email lookup returns 503, not 403 ───────────

    async def test_email_lookup_db_failure_returns_503(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        A transient DB error while checking the admin email must surface as 503,
        not masquerade as a 403 'Admin privileges required'.
        """
        user_id, _ = await _create_user(db_session)
        token = await _create_session(db_session, user_id)

        real_execute = AsyncSession.execute

        async def _flaky_execute(self, statement, *args, **kwargs):
            # Fail only the admin email lookup; let session validation succeed.
            if "email_verified FROM users" in str(statement):
                raise RuntimeError("simulated DB outage")
            return await real_execute(self, statement, *args, **kwargs)

        with patch("app.middleware.auth_middleware.settings") as mock_settings, patch.object(
            AsyncSession, "execute", _flaky_execute
        ):
            mock_settings.ADMIN_EMAIL = "admin@latexy.com"
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 503

    # ── Extra: JWT with role=admin does NOT bypass ADMIN_EMAIL gate ──────────

    async def test_jwt_role_admin_does_not_bypass_gate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        A legacy JWT with role='admin' must also not bypass the ADMIN_EMAIL check.
        """
        attacker_id = str(uuid.uuid4())
        jwt_token = _make_jwt(attacker_id, role="admin")

        with patch("app.middleware.auth_middleware.settings") as mock_settings:
            mock_settings.ADMIN_EMAIL = "real_admin@latexy.com"
            mock_settings.JWT_SECRET_KEY = _JWT_SECRET
            mock_settings.BETTER_AUTH_SECRET = "test_secret_key_32chars_minimum_!"

            resp = await client.get(
                "/admin/feature-flags",
                headers={"Authorization": f"Bearer {jwt_token}"},
            )

        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 4–5: Optional vs required auth
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestOptionalVsRequiredAuth:
    """Optional auth returns None for unknown tokens; required auth raises 401."""

    # ── 4. Optional auth — unauthenticated request returns None (200 response) ─

    async def test_optional_auth_unauthenticated_returns_200(self, client: AsyncClient):
        """
        Endpoints using get_current_user_optional (e.g., GET /jobs/) must return
        200 for requests with no credentials — they treat the caller as anonymous.
        """
        resp = await client.get("/jobs/")
        assert resp.status_code == 200

    async def test_optional_auth_invalid_token_returns_200(self, client: AsyncClient):
        """
        An unrecognisable bearer token is silently ignored by optional-auth
        endpoints; the request is treated as anonymous (not rejected).
        """
        resp = await client.get(
            "/jobs/",
            headers={"Authorization": "Bearer completely_invalid_token"},
        )
        assert resp.status_code == 200

    # ── 5. Required auth — unauthenticated request returns 401 ──────────────

    async def test_required_auth_unauthenticated_returns_401(self, client: AsyncClient):
        """
        Endpoints using get_current_user_required (e.g., GET /resumes/) must
        return 401 when no valid credentials are supplied.
        """
        resp = await client.get("/resumes/")
        assert resp.status_code == 401

    async def test_required_auth_invalid_token_returns_401(self, client: AsyncClient):
        """
        An invalid bearer token on a required-auth endpoint must yield 401.
        """
        resp = await client.get(
            "/resumes/",
            headers={"Authorization": "Bearer not_a_real_token"},
        )
        assert resp.status_code == 401

    async def test_required_auth_valid_session_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A valid Better Auth session token satisfies required auth (200, not 401)."""
        user_id, _ = await _create_user(db_session)
        token = await _create_session(db_session, user_id)

        resp = await client.get(
            "/resumes/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_required_auth_valid_jwt_returns_200(self, client: AsyncClient, monkeypatch):
        """A valid legacy JWT satisfies required auth ONLY when the migration flag is on."""
        import app.middleware.auth_middleware as am
        monkeypatch.setattr(am.settings, "LEGACY_JWT_ENABLED", True, raising=False)
        user_id = str(uuid.uuid4())
        jwt_token = _make_jwt(user_id)

        resp = await client.get(
            "/resumes/",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 200

    async def test_legacy_jwt_rejected_when_flag_disabled(self, client: AsyncClient):
        """With the migration flag off (default), a legacy JWT must NOT authenticate."""
        jwt_token = _make_jwt(str(uuid.uuid4()))
        resp = await client.get(
            "/resumes/",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert resp.status_code == 401

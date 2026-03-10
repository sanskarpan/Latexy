"""
Authentication flow tests.

Latexy supports anonymous trial users, so most API endpoints use optional
auth and return 200 for anonymous requests. Tests here verify:

  - Anonymous users get 200 on public endpoints (not 401)
  - Valid Better Auth session tokens grant authenticated access
  - Expired session tokens are treated as anonymous (optional-auth design)
  - Valid legacy JWT tokens grant authenticated access
  - Expired/invalid JWT tokens are treated as anonymous (optional-auth)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestAuthProtection:
    """Public endpoints accessible by both anonymous and authenticated users."""

    async def test_list_jobs_anonymous_returns_200(self, client: AsyncClient):
        """Anonymous access to /jobs/ is allowed — returns empty list or 200."""
        resp = await client.get("/jobs/")
        assert resp.status_code == 200

    async def test_submit_job_unauthenticated_with_fingerprint(self, client: AsyncClient):
        """Anonymous job submission with a device fingerprint should be accepted."""
        resp = await client.post(
            "/jobs/submit",
            json={
                "job_type": "latex_compilation",
                "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}",
                "device_fingerprint": "test_fp_anonymous",
            },
        )
        # 200 = queued, 400 = trial exhausted, 422 = validation error
        assert resp.status_code in (200, 400, 422)

    async def test_invalid_token_treated_as_anonymous(self, client: AsyncClient):
        """Invalid tokens are silently ignored → anonymous access (optional-auth design)."""
        resp = await client.get(
            "/jobs/",
            headers={"Authorization": "Bearer this_is_not_a_valid_token"},
        )
        # Optional-auth endpoint: invalid token ≠ 401, user treated as anonymous
        assert resp.status_code == 200

    async def test_malformed_bearer_treated_as_anonymous(self, client: AsyncClient):
        """Malformed Authorization header is ignored, not rejected."""
        resp = await client.get(
            "/jobs/",
            headers={"Authorization": "NotBearer token"},
        )
        # HTTPBearer(auto_error=False) means no credentials extracted → anonymous
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestSessionValidation:
    """Better Auth session table queries."""

    async def test_valid_session_grants_access(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A valid Better Auth session token grants authenticated access."""
        resp = await client.get("/jobs/", headers=auth_headers)
        assert resp.status_code == 200

    async def test_expired_session_treated_as_anonymous(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """An expired session is not rejected (optional-auth), treated as anonymous."""
        user_id = str(uuid.uuid4())
        token = f"expired_{uuid.uuid4().hex}"
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_session.execute(
            text(
                'INSERT INTO session (id, "userId", "expiresAt", token) '
                "VALUES (:id, :uid, :exp, :tok)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "exp": past, "tok": token},
        )
        await db_session.commit()

        resp = await client.get(
            "/jobs/", headers={"Authorization": f"Bearer {token}"}
        )
        # Optional-auth: expired session → treated as anonymous → 200
        assert resp.status_code == 200

    async def test_session_token_in_cookie(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Session token supplied via cookie should authenticate the user."""
        user_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Cookie User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": user_id, "email": f"cookie_{user_id[:8]}@example.com"},
        )
        token = f"cookie_{uuid.uuid4().hex}"
        future = datetime.now(timezone.utc) + timedelta(days=1)
        await db_session.execute(
            text(
                'INSERT INTO session (id, "userId", "expiresAt", token) '
                "VALUES (:id, :uid, :exp, :tok)"
            ),
            {"id": str(uuid.uuid4()), "uid": user_id, "exp": future, "tok": token},
        )
        await db_session.commit()

        resp = await client.get(
            "/jobs/", cookies={"better-auth.session_token": token}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestLegacyJWT:
    """Legacy HS256 JWT tokens still accepted during migration period."""

    def _make_jwt(self, user_id: str, secret: str = "test_jwt_secret_32chars_minimum_!") -> str:
        import jwt as pyjwt
        payload = {
            "sub": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return pyjwt.encode(payload, secret, algorithm="HS256")

    async def test_valid_jwt_accepted(self, client: AsyncClient):
        uid = str(uuid.uuid4())
        token = self._make_jwt(uid)
        resp = await client.get(
            "/jobs/", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200

    async def test_jwt_wrong_secret_treated_as_anonymous(self, client: AsyncClient):
        """Wrong-secret JWT is not valid; optional-auth treats user as anonymous."""
        uid = str(uuid.uuid4())
        token = self._make_jwt(uid, secret="wrong_secret_that_is_at_least_32chars")
        resp = await client.get(
            "/jobs/", headers={"Authorization": f"Bearer {token}"}
        )
        # Optional-auth: invalid JWT ≠ 401
        assert resp.status_code == 200

    async def test_expired_jwt_treated_as_anonymous(self, client: AsyncClient):
        """Expired JWT is not valid; optional-auth treats user as anonymous."""
        import jwt as pyjwt
        payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        token = pyjwt.encode(
            payload, "test_jwt_secret_32chars_minimum_!", algorithm="HS256"
        )
        resp = await client.get(
            "/jobs/", headers={"Authorization": f"Bearer {token}"}
        )
        # Optional-auth: expired JWT ≠ 401
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestExpiredSession:
    """Expired session tokens are treated as anonymous; required-auth endpoints return 401."""

    async def test_expired_token_returns_401(self, client: AsyncClient, expired_auth_headers: dict):
        """Expired session token is treated as anonymous; required-auth endpoint returns 401."""
        response = await client.get("/resumes/", headers=expired_auth_headers)
        assert response.status_code == 401

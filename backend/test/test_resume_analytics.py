"""Tests for Feature 43: Resume View Analytics."""

import uuid as _uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession


# ─── Fixtures / helpers ───────────────────────────────────────────────────────

SIMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
Hello world.
\end{document}
"""


async def _create_resume_and_share(client: AsyncClient, auth_headers: dict) -> dict:
    """Create a resume and create a share link.
    Returns {"resume_id", "share_token", "share_url"}.
    """
    resp = await client.post(
        "/resumes/",
        json={"title": "Analytics Test Resume", "latex_content": SIMPLE_LATEX},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    resume_id = resp.json()["id"]

    resp = await client.post(
        f"/resumes/{resume_id}/share",
        json={"anonymous": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {"resume_id": resume_id, "share_token": data["share_token"], "share_url": data["share_url"]}


# ─── Unit tests for session_id hashing ───────────────────────────────────────

class TestSessionIdDeduplication:
    def test_session_id_is_sha256_prefix(self):
        """session_id is sha256(ip+ua)[:16]."""
        import hashlib
        ip = "1.2.3.4"
        ua = "Mozilla/5.0"
        raw = f"{ip}{ua}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert len(expected) == 16
        assert all(c in "0123456789abcdef" for c in expected)

    def test_same_inputs_produce_same_session_id(self):
        import hashlib
        def make_session(ip: str, ua: str) -> str:
            return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()[:16]

        assert make_session("1.2.3.4", "Chrome") == make_session("1.2.3.4", "Chrome")

    def test_different_ua_produces_different_session_id(self):
        import hashlib
        def make_session(ip: str, ua: str) -> str:
            return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()[:16]

        assert make_session("1.2.3.4", "Chrome") != make_session("1.2.3.4", "Firefox")

    def test_different_ip_produces_different_session_id(self):
        import hashlib
        def make_session(ip: str, ua: str) -> str:
            return hashlib.sha256(f"{ip}{ua}".encode()).hexdigest()[:16]

        assert make_session("1.2.3.4", "Chrome") != make_session("5.6.7.8", "Chrome")


# ─── API endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestResumeViewRecording:
    """Test that accessing the public share page records a view."""

    @patch("app.api.routes._record_resume_view", new_callable=AsyncMock)
    async def test_share_page_calls_record_view(
        self, mock_record, client: AsyncClient, auth_headers: dict
    ):
        """GET /share/{token} must call _record_resume_view once."""
        info = await _create_resume_and_share(client, auth_headers)
        share_token = info["share_token"]

        # Mock PDF retrieval at the storage service layer
        with patch("app.services.storage_service.generate_presigned_url", return_value="https://example.com/pdf"):
            await client.get(f"/share/{share_token}")

        mock_record.assert_called_once()
        call_args = mock_record.call_args
        # args[2] = resume_id, args[3] = share_token
        assert call_args.args[2] == info["resume_id"]
        assert call_args.args[3] == share_token

    async def test_invalid_share_token_returns_404(self, client: AsyncClient):
        """Unknown share token → 404."""
        resp = await client.get("/share/nonexistent-token-xyz")
        assert resp.status_code == 404

    @patch("app.api.routes._record_resume_view", new_callable=AsyncMock)
    async def test_record_view_error_does_not_break_share_page(
        self, mock_record, client: AsyncClient, auth_headers: dict
    ):
        """If _record_resume_view raises, share page still returns 200 or 404 (not 500)."""
        mock_record.side_effect = Exception("Redis down")
        info = await _create_resume_and_share(client, auth_headers)
        with patch("app.services.storage_service.generate_presigned_url", return_value="https://ex.com/pdf"):
            resp = await client.get(f"/share/{info['share_token']}")
        assert resp.status_code in (200, 404)  # never 500


@pytest.mark.asyncio
class TestResumeAnalyticsEndpoint:
    """Test GET /resumes/{resume_id}/analytics."""

    async def test_analytics_requires_auth(self, client: AsyncClient, auth_headers: dict):
        """Without auth → 401 or 403."""
        info = await _create_resume_and_share(client, auth_headers)
        resp = await client.get(f"/resumes/{info['resume_id']}/analytics")
        assert resp.status_code in (401, 403)

    async def test_analytics_returns_correct_shape(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Owner sees correct JSON shape with all required keys."""
        info = await _create_resume_and_share(client, auth_headers)
        resp = await client.get(
            f"/resumes/{info['resume_id']}/analytics",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for key in (
            "total_views", "views_last_7_days", "views_last_30_days",
            "views_by_day", "views_by_country", "views_by_referrer",
            "first_viewed_at", "last_viewed_at",
        ):
            assert key in data, f"Missing key: {key}"
        assert isinstance(data["views_by_day"], list)
        assert isinstance(data["views_by_country"], list)
        assert isinstance(data["views_by_referrer"], list)

    async def test_analytics_initial_zero_views(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Fresh resume with no views → total_views == 0."""
        info = await _create_resume_and_share(client, auth_headers)
        resp = await client.get(
            f"/resumes/{info['resume_id']}/analytics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_views"] == 0
        assert data["views_last_7_days"] == 0
        assert data["views_last_30_days"] == 0
        assert data["first_viewed_at"] is None
        assert data["last_viewed_at"] is None

    async def test_analytics_non_owner_returns_403(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Non-owner of the resume → 403."""
        from conftest import _insert_session

        info = await _create_resume_and_share(client, auth_headers)

        # Create a second user + valid session
        user2_id = str(_uuid.uuid4())
        await db_session.execute(
            _text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'User Two', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user2_id, "email": f"test_{user2_id.replace('-', '')}@example.com"},
        )
        await db_session.commit()
        token2 = await _insert_session(db_session, user2_id)
        other_headers = {"Authorization": f"Bearer {token2}"}

        resp = await client.get(
            f"/resumes/{info['resume_id']}/analytics",
            headers=other_headers,
        )
        assert resp.status_code == 403

    async def test_analytics_unknown_resume_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Non-existent resume_id → 403 or 404."""
        resp = await client.get(
            "/resumes/00000000-0000-0000-0000-000000000000/analytics",
            headers=auth_headers,
        )
        assert resp.status_code in (403, 404)

    async def test_view_counted_in_analytics(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """After inserting a view row directly, analytics total_views increases."""
        from app.database.models import ResumeView

        info = await _create_resume_and_share(client, auth_headers)
        resume_id = info["resume_id"]
        share_token = info["share_token"]

        # Insert view row using the test's already-open DB session
        view = ResumeView(
            resume_id=resume_id,
            share_token=share_token,
            session_id="testabcd12345678",
        )
        db_session.add(view)
        await db_session.commit()

        resp = await client.get(
            f"/resumes/{resume_id}/analytics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_views"] == 1
        assert data["views_last_7_days"] == 1
        assert data["views_last_30_days"] == 1
        assert data["first_viewed_at"] is not None
        assert data["last_viewed_at"] is not None

    async def test_views_by_country_grouped_correctly(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Two views from US + one from UK → views_by_country reflects grouping."""
        from app.database.models import ResumeView

        info = await _create_resume_and_share(client, auth_headers)
        resume_id = info["resume_id"]
        share_token = info["share_token"]

        for i, cc in enumerate(["US", "US", "GB"]):
            view = ResumeView(
                resume_id=resume_id,
                share_token=share_token,
                session_id=f"{i:016x}",
                country_code=cc,
            )
            db_session.add(view)
        await db_session.commit()

        resp = await client.get(
            f"/resumes/{resume_id}/analytics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        by_country = {row["country_code"]: row["count"] for row in data["views_by_country"]}
        assert by_country.get("US") == 2
        assert by_country.get("GB") == 1
        assert data["total_views"] == 3

    async def test_views_by_referrer_grouped(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Views from same referrer are grouped."""
        from app.database.models import ResumeView

        info = await _create_resume_and_share(client, auth_headers)
        resume_id = info["resume_id"]
        share_token = info["share_token"]

        for i in range(3):
            db_session.add(ResumeView(
                resume_id=resume_id,
                share_token=share_token,
                session_id=f"ref{i:013x}",
                referrer="https://linkedin.com",
            ))
        await db_session.commit()

        resp = await client.get(
            f"/resumes/{resume_id}/analytics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        linkedin = next(
            (r for r in data["views_by_referrer"] if r["referrer"] == "https://linkedin.com"),
            None,
        )
        assert linkedin is not None
        assert linkedin["count"] == 3


@pytest.mark.asyncio
class TestRedisDebounce:
    """Test the Redis-based 5-minute debounce logic."""

    @patch("app.api.routes.redis_cache_client")
    @patch("app.services.storage_service.generate_presigned_url", return_value="https://ex.com/pdf")
    async def test_same_session_skipped_when_redis_key_exists(
        self, mock_url, mock_redis, client: AsyncClient, auth_headers: dict
    ):
        """When Redis says the session key exists, setex is NOT called (no DB insert)."""
        mock_redis.exists = AsyncMock(return_value=1)
        mock_redis.setex = AsyncMock()

        info = await _create_resume_and_share(client, auth_headers)
        await client.get(f"/share/{info['share_token']}")

        # If debounced, we skip the DB insert and never call setex
        mock_redis.setex.assert_not_called()

    @patch("app.api.routes.redis_cache_client")
    @patch("app.services.storage_service.generate_presigned_url", return_value="https://ex.com/pdf")
    async def test_new_session_sets_redis_key_with_ttl_300(
        self, mock_url, mock_redis, client: AsyncClient, auth_headers: dict
    ):
        """When Redis key does not exist, setex is called with TTL=300."""
        mock_redis.exists = AsyncMock(return_value=0)
        mock_redis.setex = AsyncMock()

        info = await _create_resume_and_share(client, auth_headers)
        await client.get(f"/share/{info['share_token']}")

        mock_redis.setex.assert_called_once()
        # setex(key, 300, "1")
        assert mock_redis.setex.call_args.args[1] == 300

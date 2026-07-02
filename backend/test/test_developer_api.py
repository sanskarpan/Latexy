from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DeveloperAPIKey
from app.services.ats_scoring_service import ATSScoreResult


async def _ensure_developer_api_schema(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS developer_api_keys (
              id UUID PRIMARY KEY,
              user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              key_hash TEXT NOT NULL UNIQUE,
              key_prefix VARCHAR(32) NOT NULL,
              name VARCHAR(100) NOT NULL,
              last_used_at TIMESTAMPTZ,
              request_count INTEGER NOT NULL DEFAULT 0,
              is_active BOOLEAN NOT NULL DEFAULT TRUE,
              scopes TEXT[] NOT NULL DEFAULT '{"compile","optimize","ats","export"}',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await db.commit()


async def _create_user(db: AsyncSession, plan: str = "free") -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            """
            INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used)
            VALUES (:id, :email, 'Developer API Test', true, :plan, 'active', false)
            """
        ),
        {"id": user_id, "email": email, "plan": plan},
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


async def _create_key(client: AsyncClient, session_token: str, name: str = "My App") -> dict:
    response = await client.post(
        "/developer/keys",
        json={"name": name},
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert response.status_code == 201
    return response.json()


class TestRateLimitFailClosed:
    async def test_consume_rate_limit_fails_closed_on_redis_error(self):
        """When Redis is unavailable, the limiter denies (fails closed), not open."""
        from app.services.developer_key_service import developer_key_service

        with patch(
            "app.services.developer_key_service.get_redis_cache_client",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            result = await developer_key_service.consume_rate_limit("user-1", "free")

        assert result["allowed"] is False
        assert result.get("unavailable") is True


class TestDeveloperAPI:
    async def test_create_key_returns_full_key_once_and_stores_only_hash(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)

        created = await _create_key(client, session_token)
        assert created["full_key"].startswith("lx_sk_")
        assert created["key_prefix"].startswith("lx_sk_")

        listed = await client.get(
            "/developer/keys",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert listed.status_code == 200
        first = listed.json()[0]
        assert "full_key" not in first
        assert first["name"] == "My App"

        row = (
            await db_session.execute(
                select(DeveloperAPIKey).where(DeveloperAPIKey.user_id == user_id)
            )
        ).scalar_one()
        assert row.key_hash == hashlib.sha256(created["full_key"].encode("utf-8")).hexdigest()
        assert row.key_hash != created["full_key"]

    async def test_rate_limit_blocks_eleventh_free_request(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="free")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Free key")
        api_key = created["full_key"]

        fake_score = ATSScoreResult(
            overall_score=82.0,
            category_scores={"keywords": 80.0},
            recommendations=["Add metrics"],
            warnings=[],
            strengths=["Clear structure"],
            detailed_analysis={},
            processing_time=0.02,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        with patch(
            "app.api.public_api_routes.ats_scoring_service.score_resume",
            new=AsyncMock(return_value=fake_score),
        ):
            for _ in range(10):
                response = await client.post(
                    "/api/v1/ats/score",
                    json={
                        "latex_content": r"\documentclass{article}\begin{document}Python engineer\end{document}",
                        "job_description": "FastAPI developer",
                    },
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                assert response.status_code == 200

            blocked = await client.post(
                "/api/v1/ats/score",
                json={
                    "latex_content": r"\documentclass{article}\begin{document}Python engineer\end{document}",
                    "job_description": "FastAPI developer",
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            assert blocked.status_code == 429

    async def test_revoked_key_is_no_longer_valid_for_public_api(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Revoked key")

        revoke = await client.delete(
            f"/developer/keys/{created['id']}",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert revoke.status_code == 204

        response = await client.post(
            "/api/v1/ats/score",
            json={
                "latex_content": r"\documentclass{article}\begin{document}Python engineer\end{document}",
                "job_description": "FastAPI developer",
            },
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 401

    async def test_user_cannot_revoke_another_users_key(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        owner_id, _ = await _create_user(db_session, plan="pro")
        owner_session = await _create_session(db_session, owner_id)
        key = await _create_key(client, owner_session, name="Owner key")

        other_id, _ = await _create_user(db_session, plan="pro")
        other_session = await _create_session(db_session, other_id)

        response = await client.delete(
            f"/developer/keys/{key['id']}",
            headers={"Authorization": f"Bearer {other_session}"},
        )
        assert response.status_code == 404

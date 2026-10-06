from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Compilation, DeveloperAPIKey, JobFinalization
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
    @pytest.mark.parametrize("terminal_state", ["completed", "failed", "cancelled"])
    async def test_terminal_decision_overrides_existing_processing_cache(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        terminal_state: str,
    ):
        from app.core.redis import get_redis_client

        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Partial publication key")
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                job_id=job_id,
                user_id=user_id,
                state=terminal_state,
                terminal_result=terminal_state,
                result_payload={"success": terminal_state == "completed", "optimized_latex": "canonical"},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db_session.commit()
        redis = await get_redis_client()
        for suffix, value in {
            "meta": {"job_id": job_id, "user_id": user_id},
            "state": {"status": "processing", "percent": 90},
            "result": {"success": True, "optimized_latex": "stale"},
        }.items():
            await redis.set(f"latexy:job:{job_id}:{suffix}", json.dumps(value), ex=60)
        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == terminal_state
        if terminal_state == "completed":
            assert body["result"]["optimized_latex"] == "canonical"
        else:
            assert body["result"] is None
            assert body["error"] == ("Job cancelled" if terminal_state == "cancelled" else "Job failed")

    async def test_terminal_result_recovers_after_redis_expiry_for_exact_owner(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Recovery key")
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                job_id=job_id,
                user_id=user_id,
                owner_token="latex-worker-recovery",
                owner_epoch=1,
                state="completed",
                terminal_result="completed",
                result_payload={"success": True, "optimized_latex": "\\section{Recovered}"},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["result"]["optimized_latex"] == "\\section{Recovered}"

    async def test_terminal_recovery_does_not_cross_users_or_expiry(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        owner_id, _ = await _create_user(db_session, plan="pro")
        owner_session = await _create_session(db_session, owner_id)
        owner_key = await _create_key(client, owner_session, name="Owner recovery key")
        other_id, _ = await _create_user(db_session, plan="pro")
        other_session = await _create_session(db_session, other_id)
        other_key = await _create_key(client, other_session, name="Other recovery key")

        live_job = str(uuid.uuid4())
        expired_job = str(uuid.uuid4())
        anonymous_job = str(uuid.uuid4())
        db_session.add_all(
            [
                JobFinalization(
                    job_id=live_job,
                    user_id=owner_id,
                    owner_token="latex-worker-live",
                    owner_epoch=1,
                    state="completed",
                    terminal_result="completed",
                    result_payload={"success": True, "optimized_latex": "owned"},
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                JobFinalization(
                    job_id=expired_job,
                    user_id=owner_id,
                    owner_token="latex-worker-expired",
                    owner_epoch=1,
                    state="completed",
                    terminal_result="completed",
                    result_payload={"success": True, "optimized_latex": "expired"},
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                ),
                JobFinalization(
                    job_id=anonymous_job,
                    user_id=None,
                    owner_token="latex-worker-anonymous",
                    owner_epoch=1,
                    state="completed",
                    terminal_result="completed",
                    result_payload={"success": True, "optimized_latex": "anonymous"},
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
            ]
        )
        await db_session.commit()

        owner_response = await client.get(
            f"/api/v1/jobs/{live_job}",
            headers={"Authorization": f"Bearer {owner_key['full_key']}"},
        )
        assert owner_response.status_code == 200
        other_response = await client.get(
            f"/api/v1/jobs/{live_job}",
            headers={"Authorization": f"Bearer {other_key['full_key']}"},
        )
        assert other_response.status_code == 404
        expired_response = await client.get(
            f"/api/v1/jobs/{expired_job}",
            headers={"Authorization": f"Bearer {owner_key['full_key']}"},
        )
        assert expired_response.status_code == 404
        anonymous_response = await client.get(
            f"/api/v1/jobs/{anonymous_job}",
            headers={"Authorization": f"Bearer {owner_key['full_key']}"},
        )
        assert anonymous_response.status_code == 404

    async def test_failed_terminal_recovery_returns_generic_error_only(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Failed recovery key")
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                job_id=job_id,
                user_id=user_id,
                owner_token="latex-worker-failed",
                owner_epoch=1,
                state="fenced",
                terminal_result="failed",
                failure_code="provider_failure",
                result_payload={"success": False, "error": "secret provider diagnostic"},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["result"] is None
        assert body["error"] == "Job failed"
        assert "secret" not in response.text

    @pytest.mark.parametrize("terminal_state", ["fenced", "failed", "cancelled"])
    async def test_failed_recovery_never_resurrects_compilation_pdf(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        terminal_state: str,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Fenced PDF key")
        job_id = str(uuid.uuid4())
        pdf_path = f"compilation/{job_id}/stale-owner/pdf"
        db_session.add_all(
            [
                JobFinalization(
                    job_id=job_id,
                    user_id=user_id,
                    owner_token="stale-owner",
                    owner_epoch=1,
                    state=terminal_state,
                    terminal_result="failed",
                    result_payload={"success": False},
                    pdf_path=pdf_path,
                    pdf_size=12,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                Compilation(
                    job_id=job_id,
                    user_id=user_id,
                    status="completed",
                    pdf_path=pdf_path,
                    pdf_size=12,
                ),
            ]
        )
        await db_session.commit()

        from app.services.job_result_recovery import recover_terminal_job

        recovered = await recover_terminal_job(db_session, job_id=job_id, user_id=user_id)
        assert recovered is not None
        assert recovered["pdf_path"] is None
        assert recovered["pdf_size"] is None
        response = await client.get(
            f"/api/v1/jobs/{job_id}/pdf",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 404

    async def test_completed_recovery_without_durable_pdf_does_not_advertise_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="No PDF key")
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                job_id=job_id,
                user_id=user_id,
                owner_token="latex-worker-no-pdf",
                owner_epoch=1,
                state="completed",
                terminal_result="completed",
                result_payload={"success": True, "pdf_job_id": job_id},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        assert response.json()["pdf_url"] is None

    async def test_completed_recovery_with_live_redis_pdf_advertises_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        import base64

        from app.core.redis import get_redis_client

        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Live recovery PDF key")
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                job_id=job_id,
                user_id=user_id,
                owner_token="latex-worker-live-pdf",
                owner_epoch=1,
                state="completed",
                terminal_result="completed",
                result_payload={"success": True, "pdf_job_id": job_id},
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db_session.commit()
        redis = await get_redis_client()
        await redis.set(f"latexy:job:{job_id}:pdf", base64.b64encode(b"%PDF-1.7 live"), ex=60)
        # Neither state nor result is cached: the decision comes from the DB,
        # but this Redis-only artifact is still within its own retention TTL.
        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        assert response.json()["pdf_url"] == f"/api/v1/jobs/{job_id}/pdf"
        download = await client.get(
            f"/api/v1/jobs/{job_id}/pdf",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert download.status_code == 200
        assert download.content == b"%PDF-1.7 live"

    async def test_redis_result_without_live_pdf_does_not_advertise_url(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        from app.core.redis import get_redis_client

        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="Expired PDF cache key")
        job_id = str(uuid.uuid4())
        redis = await get_redis_client()
        await redis.set(
            f"latexy:job:{job_id}:meta",
            json.dumps({"job_id": job_id, "user_id": user_id}),
            ex=60,
        )
        await redis.set(
            f"latexy:job:{job_id}:state",
            json.dumps({"status": "completed"}),
            ex=60,
        )
        await redis.set(
            f"latexy:job:{job_id}:result",
            json.dumps({"success": True, "pdf_job_id": job_id}),
            ex=60,
        )
        await redis.delete(f"latexy:job:{job_id}:pdf")

        response = await client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {created['full_key']}"},
        )
        assert response.status_code == 200
        assert response.json()["pdf_url"] is None

    async def test_pdf_recovery_uses_persisted_user_owned_object(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        await _ensure_developer_api_schema(db_session)
        user_id, _ = await _create_user(db_session, plan="pro")
        session_token = await _create_session(db_session, user_id)
        created = await _create_key(client, session_token, name="PDF recovery key")
        job_id = str(uuid.uuid4())
        pdf_path = f"compilation/{job_id}/owner-token/pdf"
        db_session.add_all(
            [
                JobFinalization(
                    job_id=job_id,
                    user_id=user_id,
                    owner_token="latex-worker-pdf",
                    owner_epoch=1,
                    state="completed",
                    terminal_result="completed",
                    result_payload={"success": True, "pdf_job_id": job_id},
                    pdf_path=pdf_path,
                    pdf_size=12,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                Compilation(
                    job_id=job_id,
                    user_id=user_id,
                    status="completed",
                    pdf_path=pdf_path,
                    pdf_size=12,
                ),
            ]
        )
        await db_session.commit()

        with patch(
            "app.services.storage_service.download_bytes",
            return_value=b"%PDF-1.7 durable",
        ):
            response = await client.get(
                f"/api/v1/jobs/{job_id}/pdf",
                headers={"Authorization": f"Bearer {created['full_key']}"},
            )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

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

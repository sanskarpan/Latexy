"""
Tests for Document Version History / Checkpoint endpoints.

Covers:
  - POST /{resume_id}/checkpoints       — create manual checkpoint
  - GET /{resume_id}/checkpoints         — list checkpoints
  - GET /{resume_id}/checkpoints/{id}/content — get checkpoint content
  - DELETE /{resume_id}/checkpoints/{id} — delete checkpoint
  - Ownership enforcement (cross-user 404)
  - Max 20 manual checkpoint limit
  - Cannot delete non-checkpoint optimization records
  - Auto-save worker _do_auto_save (dedup + pruning) — direct async tests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Optimization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"
_LATEX_V2 = r"\documentclass{article}\begin{document}Updated\end{document}"


async def _create_resume(client: AsyncClient, auth_headers: dict) -> str:
    """Create a resume via the API and return its id."""
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": "Checkpoint Test", "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _get_user_id(db_session: AsyncSession, auth_headers: dict) -> str:
    """Extract user_id from the session token in auth_headers."""
    token = auth_headers["Authorization"].replace("Bearer ", "")
    result = await db_session.execute(
        text('SELECT "userId" FROM session WHERE token = :tok'),
        {"tok": token},
    )
    row = result.one()
    return row[0]


# ---------------------------------------------------------------------------
# POST /resumes/{resume_id}/checkpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateCheckpoint:
    async def test_create_returns_201(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Before rewrite"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Before rewrite"
        assert "id" in data
        assert "created_at" in data

    async def test_create_stores_current_latex(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Snapshot"},
        )
        cp_id = resp.json()["id"]

        # Fetch content via API
        content_resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert content_resp.status_code == 200
        data = content_resp.json()
        assert data["optimized_latex"] == _LATEX
        assert data["checkpoint_label"] == "Snapshot"

    async def test_create_empty_label_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": ""},
        )
        assert resp.status_code == 422  # validation error

    async def test_create_label_too_long_rejected(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "X" * 101},
        )
        assert resp.status_code == 422

    async def test_create_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            f"/resumes/{uuid.uuid4()}/checkpoints",
            json={"label": "test"},
        )
        assert resp.status_code == 401

    async def test_create_wrong_resume_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            f"/resumes/{uuid.uuid4()}/checkpoints",
            headers=auth_headers,
            json={"label": "Ghost"},
        )
        assert resp.status_code == 404

    async def test_max_20_manual_checkpoints(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        # Create 20 manual checkpoints
        for i in range(20):
            resp = await client.post(
                f"/resumes/{resume_id}/checkpoints",
                headers=auth_headers,
                json={"label": f"CP {i}"},
            )
            assert resp.status_code == 201, f"Failed on checkpoint {i}: {resp.text}"

        # 21st should fail
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "One too many"},
        )
        assert resp.status_code == 400
        assert "Maximum 20" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /resumes/{resume_id}/checkpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListCheckpoints:
    async def test_list_empty(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_create(
        self, client: AsyncClient, auth_headers: dict
    ):
        import asyncio

        resume_id = await _create_resume(client, auth_headers)
        await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Alpha"},
        )
        await asyncio.sleep(0.05)  # ensure distinct created_at timestamps
        await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Beta"},
        )

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints", headers=auth_headers
        )
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 2
        # Newest first
        assert entries[0]["checkpoint_label"] == "Beta"
        assert entries[1]["checkpoint_label"] == "Alpha"
        # Schema check
        assert entries[0]["is_checkpoint"] is True
        assert entries[0]["is_auto_save"] is False
        assert "changes_count" in entries[0]

    async def test_list_includes_optimizations(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """List should include regular optimization records (not just checkpoints)."""
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        # Insert a regular optimization record directly
        opt = Optimization(
            id=str(uuid.uuid4()),
            user_id=user_id,
            resume_id=resume_id,
            original_latex=_LATEX,
            optimized_latex=_LATEX_V2,
            job_description="Software Engineer",
            provider="openai",
            model="gpt-4o-mini",
            ats_score=82.5,
            is_checkpoint=False,
            is_auto_save=False,
        )
        db_session.add(opt)
        await db_session.commit()

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints", headers=auth_headers
        )
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["is_checkpoint"] is False
        assert entries[0]["ats_score"] == 82.5

    async def test_list_pagination(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        for i in range(5):
            await client.post(
                f"/resumes/{resume_id}/checkpoints",
                headers=auth_headers,
                json={"label": f"P{i}"},
            )

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints?limit=2&offset=0",
            headers=auth_headers,
        )
        assert len(resp.json()) == 2

        resp2 = await client.get(
            f"/resumes/{resume_id}/checkpoints?limit=2&offset=2",
            headers=auth_headers,
        )
        assert len(resp2.json()) == 2

        resp3 = await client.get(
            f"/resumes/{resume_id}/checkpoints?limit=2&offset=4",
            headers=auth_headers,
        )
        assert len(resp3.json()) == 1

    async def test_list_wrong_resume_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get(
            f"/resumes/{uuid.uuid4()}/checkpoints", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_list_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/resumes/{uuid.uuid4()}/checkpoints")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /resumes/{resume_id}/checkpoints/{checkpoint_id}/content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetCheckpointContent:
    async def test_get_content(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        create_resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Content test"},
        )
        cp_id = create_resp.json()["id"]

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["original_latex"] == _LATEX
        assert data["optimized_latex"] == _LATEX
        assert data["checkpoint_label"] == "Content test"

    async def test_content_nonexistent_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{uuid.uuid4()}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_content_wrong_resume_404(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Checkpoint exists but resume_id doesn't match."""
        resume_id = await _create_resume(client, auth_headers)
        create_resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Mismatch"},
        )
        cp_id = create_resp.json()["id"]

        # Use a different (non-existent) resume_id
        resp = await client.get(
            f"/resumes/{uuid.uuid4()}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /resumes/{resume_id}/checkpoints/{checkpoint_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteCheckpoint:
    async def test_delete_checkpoint(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        create_resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "To delete"},
        )
        cp_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{cp_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cannot_delete_non_checkpoint_optimization(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Regular optimization records (is_checkpoint=False) cannot be deleted."""
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        opt = Optimization(
            id=str(uuid.uuid4()),
            user_id=user_id,
            resume_id=resume_id,
            original_latex=_LATEX,
            optimized_latex=_LATEX_V2,
            job_description="",
            provider="openai",
            model="gpt-4o",
            is_checkpoint=False,
            is_auto_save=False,
        )
        db_session.add(opt)
        await db_session.commit()

        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{opt.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "manual checkpoint" in resp.json()["detail"].lower()

    async def test_cannot_delete_auto_save_checkpoint(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Auto-save checkpoints (is_checkpoint=True, is_auto_save=True) cannot be deleted."""
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        auto_cp = Optimization(
            id=str(uuid.uuid4()),
            user_id=user_id,
            resume_id=resume_id,
            original_latex=_LATEX,
            optimized_latex=_LATEX,
            job_description="",
            provider="auto_save",
            model="auto",
            is_checkpoint=True,
            is_auto_save=True,
            checkpoint_label="Auto-save test",
        )
        db_session.add(auto_cp)
        await db_session.commit()

        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{auto_cp.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "manual checkpoint" in resp.json()["detail"].lower()

    async def test_delete_unauthenticated(self, client: AsyncClient):
        resp = await client.delete(
            f"/resumes/{uuid.uuid4()}/checkpoints/{uuid.uuid4()}"
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cross-user ownership enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOwnershipEnforcement:
    async def test_other_user_cannot_see_checkpoints(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        """A second user cannot list or access another user's checkpoints."""
        resume_id = await _create_resume(client, auth_headers)
        await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Private"},
        )

        # Create a second user + session
        user2_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'User 2', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": user2_id, "email": f"test_{user2_id[:8]}@example.com"},
        )
        await db_session.commit()

        from conftest import _insert_session

        token2 = await _insert_session(db_session, user2_id)
        headers2 = {"Authorization": f"Bearer {token2}"}

        # User2 cannot see user1's resume checkpoints
        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints", headers=headers2
        )
        assert resp.status_code == 404  # resume not found for user2


# ---------------------------------------------------------------------------
# Auto-save worker — direct async function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAutoSaveWorker:
    """Test the _do_auto_save function directly (no Celery broker needed)."""

    async def test_auto_save_creates_record(
        self, db_session: AsyncSession, db_session_factory, auth_headers: dict, client: AsyncClient
    ):
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        from app.workers.auto_save_worker import _do_auto_save

        await _do_auto_save(resume_id, user_id, _LATEX, session_factory=db_session_factory)

        result = await db_session.execute(
            select(Optimization).where(
                Optimization.resume_id == resume_id,
                Optimization.is_auto_save.is_(True),
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].is_checkpoint is True
        assert rows[0].is_auto_save is True
        assert rows[0].optimized_latex == _LATEX

    async def test_auto_save_dedup_within_5_min(
        self, db_session: AsyncSession, db_session_factory, auth_headers: dict, client: AsyncClient
    ):
        """Second auto-save within 5 minutes should be skipped."""
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        from app.workers.auto_save_worker import _do_auto_save

        await _do_auto_save(resume_id, user_id, _LATEX, session_factory=db_session_factory)
        await _do_auto_save(resume_id, user_id, _LATEX_V2, session_factory=db_session_factory)  # should be deduped

        result = await db_session.execute(
            select(Optimization).where(
                Optimization.resume_id == resume_id,
                Optimization.is_auto_save.is_(True),
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1  # only first was saved

    async def test_auto_save_pruning(
        self, db_session: AsyncSession, db_session_factory, auth_headers: dict, client: AsyncClient
    ):
        """Auto-save should prune to keep only 20 records."""
        resume_id = await _create_resume(client, auth_headers)
        user_id = await _get_user_id(db_session, auth_headers)

        # Manually insert 21 auto-save records with timestamps > 5 min apart
        now = datetime.now(timezone.utc)
        for i in range(21):
            cp = Optimization(
                id=str(uuid.uuid4()),
                user_id=user_id,
                resume_id=resume_id,
                original_latex=_LATEX,
                optimized_latex=_LATEX,
                job_description="",
                provider="auto_save",
                model="auto",
                is_checkpoint=True,
                is_auto_save=True,
                checkpoint_label=f"Auto {i}",
                created_at=now - timedelta(minutes=10 * (21 - i)),
            )
            db_session.add(cp)
        await db_session.commit()

        from app.workers.auto_save_worker import _do_auto_save

        await _do_auto_save(resume_id, user_id, _LATEX_V2, session_factory=db_session_factory)

        # Use a fresh query since _do_auto_save committed via its own session
        result = await db_session.execute(
            select(Optimization).where(
                Optimization.resume_id == resume_id,
                Optimization.is_auto_save.is_(True),
            )
        )
        rows = result.scalars().all()
        # Should be exactly 20 after pruning (21 existed + 1 new = 22, pruned to 20)
        assert len(rows) == 20

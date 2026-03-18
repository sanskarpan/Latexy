"""Tests for compilation / checkpoint history diff endpoints.

Covers:
  - GET /resumes/{resume_id}/checkpoints                          — list checkpoints
  - POST /resumes/{resume_id}/checkpoints                         — create checkpoint
  - GET /resumes/{resume_id}/checkpoints/{checkpoint_id}/content  — fetch content
  - DELETE /resumes/{resume_id}/checkpoints/{checkpoint_id}       — delete checkpoint
  - 404 for wrong resume_id or wrong user
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── helpers ──────────────────────────────────────────────────────────────────

async def _create_resume(client: AsyncClient, headers: dict, title: str = "HR") -> str:
    resp = await client.post(
        "/resumes/",
        headers=headers,
        json={"title": title, "latex_content": r"\documentclass{article}\begin{document}Hi\end{document}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_checkpoint(
    client: AsyncClient, headers: dict, resume_id: str, label: str = "v1"
) -> str:
    resp = await client.post(
        f"/resumes/{resume_id}/checkpoints",
        headers=headers,
        json={"label": label},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _make_second_headers(db_session: AsyncSession) -> dict:
    """Create an independent second user and return their auth headers."""
    from sqlalchemy import text as _text

    uid = str(uuid.uuid4())
    token = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    await db_session.execute(
        _text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Other User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
        ),
        {"id": uid, "email": f"other_{uid[:8]}@example.com"},
    )
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db_session.execute(
        _text(
            'INSERT INTO session (id, "userId", token, "expiresAt") '
            "VALUES (:sid, :uid, :tok, :exp) ON CONFLICT DO NOTHING"
        ),
        {"sid": session_id, "uid": uid, "tok": token, "exp": expires_at},
    )
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


# ── list checkpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestListCheckpoints:
    async def test_empty_list(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.get(f"/resumes/{resume_id}/checkpoints", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_after_create(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        await _create_checkpoint(client, auth_headers, resume_id, label="snap1")

        resp = await client.get(f"/resumes/{resume_id}/checkpoints", headers=auth_headers)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["checkpoint_label"] == "snap1"
        assert entries[0]["is_checkpoint"] is True

    async def test_list_requires_auth(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.get(f"/resumes/{resume_id}/checkpoints")
        assert resp.status_code == 401

    async def test_list_wrong_resume_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get(f"/resumes/{uuid.uuid4()}/checkpoints", headers=auth_headers)
        assert resp.status_code == 404


# ── create checkpoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCreateCheckpoint:
    async def test_create_basic(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={"label": "Before interview"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "created_at" in data
        assert data["label"] == "Before interview"

    async def test_create_with_label_required(self, client: AsyncClient, auth_headers: dict):
        """label is required; omitting it returns 422."""
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 422

    async def test_create_requires_auth(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            json={"label": "x"},
        )
        assert resp.status_code == 401

    async def test_create_for_wrong_resume_returns_404(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            f"/resumes/{uuid.uuid4()}/checkpoints",
            headers=auth_headers,
            json={"label": "x"},
        )
        assert resp.status_code == 404

    async def test_cannot_create_for_other_users_resume(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        other_headers = await _make_second_headers(db_session)
        resume_id = await _create_resume(client, auth_headers)

        resp = await client.post(
            f"/resumes/{resume_id}/checkpoints",
            headers=other_headers,
            json={"label": "steal"},
        )
        assert resp.status_code == 404


# ── get checkpoint content ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGetCheckpointContent:
    async def test_fetch_own_checkpoint(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id, label="for-diff")

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "original_latex" in data
        assert "optimized_latex" in data
        assert data["checkpoint_label"] == "for-diff"

    async def test_content_has_latex(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        data = resp.json()
        # Both fields should be non-empty strings (contain the resume latex)
        assert isinstance(data["optimized_latex"], str)
        assert len(data["optimized_latex"]) > 0

    async def test_content_wrong_resume_id_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """checkpoint_id exists but resume_id doesn't match → 404."""
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        wrong_resume_id = str(uuid.uuid4())
        resp = await client.get(
            f"/resumes/{wrong_resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_content_nonexistent_checkpoint_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{uuid.uuid4()}/content",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_content_other_users_checkpoint_returns_404(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """Another user cannot access checkpoint content even with a valid checkpoint_id."""
        other_headers = await _make_second_headers(db_session)

        # Owner creates a resume + checkpoint
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        # Other user attempts to fetch it
        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=other_headers,
        )
        assert resp.status_code == 404

    async def test_content_requires_auth(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content"
        )
        assert resp.status_code == 401


# ── delete checkpoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDeleteCheckpoint:
    async def test_delete_own_checkpoint(self, client: AsyncClient, auth_headers: dict):
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{cp_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Confirm it's gone
        content_resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert content_resp.status_code == 404

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resume_id = await _create_resume(client, auth_headers)
        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{uuid.uuid4()}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_delete_other_users_checkpoint_returns_404(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        other_headers = await _make_second_headers(db_session)
        resume_id = await _create_resume(client, auth_headers)
        cp_id = await _create_checkpoint(client, auth_headers, resume_id)

        resp = await client.delete(
            f"/resumes/{resume_id}/checkpoints/{cp_id}",
            headers=other_headers,
        )
        assert resp.status_code == 404

        # Original owner's checkpoint should still exist
        content_resp = await client.get(
            f"/resumes/{resume_id}/checkpoints/{cp_id}/content",
            headers=auth_headers,
        )
        assert content_resp.status_code == 200

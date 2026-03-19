"""Tests for Feature 17: Interview Question Generator."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def resume_id(auth_headers: dict, client: AsyncClient) -> str:
    """Create a test resume and return its ID."""
    resp = await client.post(
        "/resumes/",
        json={
            "title": "Test Resume for Interview Prep",
            "latex_content": r"\documentclass{article}\begin{document}Software Engineer with 5 years experience\end{document}",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def prep_id(auth_headers: dict, client: AsyncClient, resume_id: str) -> str:
    """Create an interview prep record manually (without running the worker) and return its id."""
    resp = await client.post(
        "/interview-prep/generate",
        json={
            "resume_id": resume_id,
            "job_description": "Software Engineer at Acme Corp. Python, FastAPI, PostgreSQL required.",
            "company_name": "Acme Corp",
            "role_title": "Software Engineer",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["prep_id"]


# ---------------------------------------------------------------------------
# POST /interview-prep/generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_creates_record(client: AsyncClient, auth_headers: dict, resume_id: str):
    resp = await client.post(
        "/interview-prep/generate",
        json={"resume_id": resume_id, "job_description": "Backend engineer role"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert "job_id" in data
    assert "prep_id" in data


@pytest.mark.asyncio
async def test_generate_requires_auth(client: AsyncClient, resume_id: str):
    resp = await client.post(
        "/interview-prep/generate",
        json={"resume_id": resume_id},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_generate_invalid_resume(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/interview-prep/generate",
        json={"resume_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_optional_fields(client: AsyncClient, auth_headers: dict, resume_id: str):
    """Generate with no job description (optional) should succeed."""
    resp = await client.post(
        "/interview-prep/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True


# ---------------------------------------------------------------------------
# GET /interview-prep/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prep(client: AsyncClient, auth_headers: dict, prep_id: str):
    resp = await client.get(f"/interview-prep/{prep_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == prep_id
    assert "questions" in data
    assert isinstance(data["questions"], list)


@pytest.mark.asyncio
async def test_get_prep_requires_auth(client: AsyncClient, prep_id: str):
    resp = await client.get(f"/interview-prep/{prep_id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_prep_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/interview-prep/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_access_another_users_prep(
    client: AsyncClient,
    auth_headers: dict,
    prep_id: str,
    db_session: AsyncSession,
):
    """A different user cannot access another user's prep session."""
    user_id2 = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'User 2', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
        ),
        {"id": user_id2, "email": f"test_{user_id2.replace('-', '')}@example.com"},
    )
    await db_session.commit()
    token = f"test_sess_{uuid.uuid4().hex}"
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db_session.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id2, "exp": expires_at, "tok": token},
    )
    await db_session.commit()
    headers2 = {"Authorization": f"Bearer {token}"}

    resp = await client.get(f"/interview-prep/{prep_id}", headers=headers2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /resumes/{resume_id}/interview-prep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_prep_sessions(client: AsyncClient, auth_headers: dict, resume_id: str):
    # Create two sessions
    for _ in range(2):
        await client.post(
            "/interview-prep/generate",
            json={"resume_id": resume_id},
            headers=auth_headers,
        )
    resp = await client.get(f"/resumes/{resume_id}/interview-prep", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_list_prep_requires_auth(client: AsyncClient, resume_id: str):
    resp = await client.get(f"/resumes/{resume_id}/interview-prep")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_prep_invalid_resume(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/resumes/00000000-0000-0000-0000-000000000000/interview-prep",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_prep_descending_order(client: AsyncClient, auth_headers: dict, resume_id: str):
    """Sessions should be returned newest first."""
    for _ in range(3):
        await client.post(
            "/interview-prep/generate",
            json={"resume_id": resume_id},
            headers=auth_headers,
        )
    resp = await client.get(f"/resumes/{resume_id}/interview-prep", headers=auth_headers)
    data = resp.json()
    assert len(data) >= 3
    # Timestamps should be in descending order
    timestamps = [d["created_at"] for d in data]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# DELETE /interview-prep/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_prep(client: AsyncClient, auth_headers: dict, prep_id: str):
    resp = await client.delete(f"/interview-prep/{prep_id}", headers=auth_headers)
    assert resp.status_code == 204
    # Should now return 404
    get_resp = await client.get(f"/interview-prep/{prep_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_prep_requires_auth(client: AsyncClient, prep_id: str):
    resp = await client.delete(f"/interview-prep/{prep_id}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_prep_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.delete(
        "/interview-prep/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404

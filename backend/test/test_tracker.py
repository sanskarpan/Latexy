"""Tests for Job Application Tracker routes."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_payload():
    return {
        "company_name": "Acme Corp",
        "role_title": "Software Engineer",
        "status": "applied",
        "job_url": "https://acme.example.com/jobs/123",
        "notes": "Referred by Alice",
    }


async def _make_auth_headers(db_session: AsyncSession) -> dict:
    """Create a fresh user + session and return auth headers."""
    user_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Test User 2', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
        ),
        {"id": user_id, "email": f"test2_{user_id.replace('-', '')}@example.com"},
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
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auth_headers2(db_session: AsyncSession) -> dict:
    return await _make_auth_headers(db_session)


# ---------------------------------------------------------------------------
# POST /tracker/applications — create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_application(client: AsyncClient, auth_headers: dict, app_payload):
    resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["company_name"] == "Acme Corp"
    assert data["role_title"] == "Software Engineer"
    assert data["status"] == "applied"
    assert data["job_url"] == "https://acme.example.com/jobs/123"
    assert data["notes"] == "Referred by Alice"
    assert data["id"] is not None
    assert "company_logo_url" in data
    assert "logo.clearbit.com" in (data["company_logo_url"] or "")


@pytest.mark.asyncio
async def test_create_application_requires_auth(client: AsyncClient, app_payload):
    resp = await client.post("/tracker/applications", json=app_payload)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_application_invalid_status(client: AsyncClient, auth_headers: dict, app_payload):
    payload = {**app_payload, "status": "flying"}
    resp = await client.post("/tracker/applications", json=payload, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_application_default_status(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/tracker/applications",
        json={"company_name": "Beta Inc", "role_title": "DevOps"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "applied"


@pytest.mark.asyncio
async def test_create_application_with_invalid_resume_id(client: AsyncClient, auth_headers: dict, app_payload):
    payload = {**app_payload, "resume_id": "00000000-0000-0000-0000-000000000000"}
    resp = await client.post("/tracker/applications", json=payload, headers=auth_headers)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /tracker/applications — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_applications_grouped(client: AsyncClient, auth_headers: dict, app_payload):
    await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    resp = await client.get("/tracker/applications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "by_status" in data
    assert "applied" in data["by_status"]
    assert any(a["company_name"] == "Acme Corp" for a in data["by_status"]["applied"])


@pytest.mark.asyncio
async def test_list_applications_flat(client: AsyncClient, auth_headers: dict, app_payload):
    await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    resp = await client.get("/tracker/applications?flat=true", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(a["company_name"] == "Acme Corp" for a in data)


@pytest.mark.asyncio
async def test_list_applications_status_filter(client: AsyncClient, auth_headers: dict, app_payload):
    await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    await client.post(
        "/tracker/applications",
        json={"company_name": "Filtered Co", "role_title": "PM", "status": "offer"},
        headers=auth_headers,
    )
    resp = await client.get("/tracker/applications?status=offer", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "by_status" in data
    assert any(a["company_name"] == "Filtered Co" for a in data["by_status"]["offer"])


@pytest.mark.asyncio
async def test_list_applications_requires_auth(client: AsyncClient):
    resp = await client.get("/tracker/applications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_users_cannot_see_each_others_applications(
    client: AsyncClient,
    auth_headers: dict,
    auth_headers2: dict,
    app_payload,
):
    await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    resp = await client.get("/tracker/applications?flat=true", headers=auth_headers2)
    assert resp.status_code == 200
    data = resp.json()
    assert not any(a["company_name"] == "Acme Corp" for a in data)


# ---------------------------------------------------------------------------
# GET /tracker/applications/{id} — single
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_application(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.get(f"/tracker/applications/{app_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == app_id


@pytest.mark.asyncio
async def test_get_application_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get(
        "/tracker/applications/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_get_another_users_application(
    client: AsyncClient,
    auth_headers: dict,
    auth_headers2: dict,
    app_payload,
):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.get(f"/tracker/applications/{app_id}", headers=auth_headers2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /tracker/applications/{id} — full update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_application(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.put(
        f"/tracker/applications/{app_id}",
        json={"status": "phone_screen", "notes": "Called by recruiter"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "phone_screen"
    assert data["notes"] == "Called by recruiter"


@pytest.mark.asyncio
async def test_update_application_invalid_status(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.put(
        f"/tracker/applications/{app_id}",
        json={"status": "limbo"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /tracker/applications/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_application(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/tracker/applications/{app_id}", headers=auth_headers)
    assert del_resp.status_code == 204
    get_resp = await client.get(f"/tracker/applications/{app_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_from_list(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    await client.delete(f"/tracker/applications/{app_id}", headers=auth_headers)
    list_resp = await client.get("/tracker/applications?flat=true", headers=auth_headers)
    assert not any(a["id"] == app_id for a in list_resp.json())


@pytest.mark.asyncio
async def test_cannot_delete_another_users_application(
    client: AsyncClient,
    auth_headers: dict,
    auth_headers2: dict,
    app_payload,
):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.delete(f"/tracker/applications/{app_id}", headers=auth_headers2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /tracker/applications/{id}/status — quick status update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_status(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/tracker/applications/{app_id}/status",
        json={"status": "technical"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "technical"


@pytest.mark.asyncio
async def test_patch_status_invalid(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    resp = await client.patch(
        f"/tracker/applications/{app_id}/status",
        json={"status": "hacking"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_status_reflects_in_list(client: AsyncClient, auth_headers: dict, app_payload):
    create_resp = await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    app_id = create_resp.json()["id"]
    await client.patch(
        f"/tracker/applications/{app_id}/status",
        json={"status": "offer"},
        headers=auth_headers,
    )
    list_resp = await client.get("/tracker/applications", headers=auth_headers)
    data = list_resp.json()
    assert any(a["id"] == app_id for a in data["by_status"]["offer"])


# ---------------------------------------------------------------------------
# GET /tracker/stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_empty(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/tracker/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_applications"] == 0
    assert data["response_rate"] == 0.0
    assert data["offer_rate"] == 0.0
    assert data["avg_ats_score"] is None


@pytest.mark.asyncio
async def test_stats_response_rate_zero_when_all_applied(
    client: AsyncClient, auth_headers: dict, app_payload
):
    await client.post("/tracker/applications", json=app_payload, headers=auth_headers)
    await client.post(
        "/tracker/applications",
        json={"company_name": "Beta", "role_title": "Dev"},
        headers=auth_headers,
    )
    resp = await client.get("/tracker/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_applications"] == 2
    assert data["response_rate"] == 0.0


@pytest.mark.asyncio
async def test_stats_counts_by_status(client: AsyncClient, auth_headers: dict):
    for s in ["applied", "offer", "phone_screen", "rejected"]:
        await client.post(
            "/tracker/applications",
            json={"company_name": f"Co {s}", "role_title": "Dev", "status": s},
            headers=auth_headers,
        )
    resp = await client.get("/tracker/stats", headers=auth_headers)
    data = resp.json()
    assert data["total_applications"] == 4
    assert data["by_status"]["applied"] == 1
    assert data["by_status"]["offer"] == 1
    assert data["by_status"]["phone_screen"] == 1
    assert data["by_status"]["rejected"] == 1


@pytest.mark.asyncio
async def test_stats_offer_rate(client: AsyncClient, auth_headers: dict):
    await client.post(
        "/tracker/applications",
        json={"company_name": "A", "role_title": "Dev", "status": "offer"},
        headers=auth_headers,
    )
    await client.post(
        "/tracker/applications",
        json={"company_name": "B", "role_title": "Dev", "status": "rejected"},
        headers=auth_headers,
    )
    resp = await client.get("/tracker/stats", headers=auth_headers)
    data = resp.json()
    assert data["offer_rate"] == 0.5


@pytest.mark.asyncio
async def test_stats_requires_auth(client: AsyncClient):
    resp = await client.get("/tracker/stats")
    assert resp.status_code == 401

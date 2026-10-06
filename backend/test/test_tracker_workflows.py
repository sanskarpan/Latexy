"""Integration coverage for the deeper application-tracker workflows."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tracker_workflow_routes import TrackSavedJobRequest


@pytest.fixture
async def auth_headers2(db_session: AsyncSession) -> dict:
    user_id = str(uuid4())
    token = f"test_sess_{uuid4().hex}"
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used) VALUES "
            "(:id, :email, 'Workflow User', true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": f"workflow_{uuid4().hex}@example.com"},
    )
    await db_session.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :token)'),
        {
            "id": str(uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "token": token,
        },
    )
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


async def _application(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/tracker/applications",
        json={"company_name": "Acme", "role_title": "Engineer"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_saved_job_crud_and_atomic_conversion(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/tracker/saved-jobs",
        json={
            "company_name": "Example Labs",
            "role_title": "Platform Engineer",
            "job_url": "https://jobs.example.com/platform",
            "notes": "Follow up with hiring manager",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    saved_id = created.json()["id"]

    updated = await client.put(
        f"/tracker/saved-jobs/{saved_id}",
        json={"role_title": "Senior Platform Engineer"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["role_title"] == "Senior Platform Engineer"

    tracked = await client.post(f"/tracker/saved-jobs/{saved_id}/track", json={}, headers=auth_headers)
    assert tracked.status_code == 201
    assert tracked.json()["saved_job_deleted"] is True

    saved = await client.get("/tracker/saved-jobs", headers=auth_headers)
    assert all(item["id"] != saved_id for item in saved.json())
    application = await client.get(f"/tracker/applications/{tracked.json()['application_id']}", headers=auth_headers)
    assert application.json()["role_title"] == "Senior Platform Engineer"
    repeated = await client.post(f"/tracker/saved-jobs/{saved_id}/track", json={}, headers=auth_headers)
    assert repeated.status_code == 404


@pytest.mark.asyncio
async def test_saved_jobs_validate_urls_and_support_bulk_unsave(client: AsyncClient, auth_headers: dict):
    invalid = await client.post(
        "/tracker/saved-jobs",
        json={"company_name": "Bad", "role_title": "Job", "job_url": "javascript:alert(1)"},
        headers=auth_headers,
    )
    assert invalid.status_code == 422

    ids = []
    for suffix in ("One", "Two"):
        response = await client.post(
            "/tracker/saved-jobs",
            json={"company_name": suffix, "role_title": "Engineer"},
            headers=auth_headers,
        )
        ids.append(response.json()["id"])
    deleted = await client.delete(
        "/tracker/saved-jobs", params=[("ids", item_id) for item_id in ids], headers=auth_headers
    )
    assert deleted.status_code == 204
    assert (await client.get("/tracker/saved-jobs", headers=auth_headers)).json() == []


def test_track_saved_job_normalizes_blank_and_rejects_invalid_resume_ids():
    assert TrackSavedJobRequest(resume_id="   ").resume_id is None
    valid = str(uuid4()).upper()
    assert TrackSavedJobRequest(resume_id=f"  {valid} ").resume_id == valid.lower()
    with pytest.raises(ValueError):
        TrackSavedJobRequest(resume_id="not-a-uuid")


@pytest.mark.asyncio
async def test_alerts_store_user_supplied_search_without_fetching(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    response = await client.post(
        "/tracker/alerts",
        json={
            "query": "staff backend engineer",
            "company_name": "Example Labs",
            "location": "Remote",
            "source_url": "https://jobs.example.com/search?q=backend",
            "frequency": "weekly",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    alert = response.json()
    assert alert["last_notified_at"] is None

    await db_session.execute(
        text(
            "UPDATE job_alerts SET delivery_claimed_at = NOW(), "
            "delivery_claim_token = 'in-flight', delivery_last_error = 'send_failed' WHERE id = :id"
        ),
        {"id": alert["id"]},
    )
    await db_session.commit()

    paused = await client.put(f"/tracker/alerts/{alert['id']}", json={"active": False}, headers=auth_headers)
    assert paused.status_code == 200
    assert paused.json()["active"] is False
    claim = (
        await db_session.execute(
            text(
                "SELECT delivery_claimed_at, delivery_claim_token, delivery_last_error "
                "FROM job_alerts WHERE id = :id"
            ),
            {"id": alert["id"]},
        )
    ).one()
    assert claim == (None, None, None)
    assert (await client.get("/tracker/alerts", headers=auth_headers)).json()[0]["query"] == ("staff backend engineer")
    blank_url = await client.post(
        "/tracker/alerts",
        json={"query": "backend", "source_url": "   "},
        headers=auth_headers,
    )
    assert blank_url.status_code == 422
    null_url = await client.put(f"/tracker/alerts/{alert['id']}", json={"source_url": None}, headers=auth_headers)
    assert null_url.status_code == 422


@pytest.mark.asyncio
async def test_reminders_require_future_offset_timestamp(client: AsyncClient, auth_headers: dict):
    app_id = await _application(client, auth_headers)
    naive = await client.post(
        f"/tracker/applications/{app_id}/reminders",
        json={"remind_at": "2027-01-01T09:00:00"},
        headers=auth_headers,
    )
    assert naive.status_code == 422

    remind_at = datetime.now(timezone.utc) + timedelta(days=2)
    created = await client.post(
        f"/tracker/applications/{app_id}/reminders",
        json={"remind_at": remind_at.isoformat(), "note": "Send portfolio"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    reminder_id = created.json()["id"]
    listed = await client.get(f"/tracker/applications/{app_id}/reminders", headers=auth_headers)
    assert listed.json()[0]["note"] == "Send portfolio"
    updated = await client.put(
        f"/tracker/applications/{app_id}/reminders/{reminder_id}",
        json={"note": "Send updated portfolio"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["note"] == "Send updated portfolio"
    assert (
        await client.delete(f"/tracker/applications/{app_id}/reminders/{reminder_id}", headers=auth_headers)
    ).status_code == 204


@pytest.mark.asyncio
async def test_sent_reminder_requires_explicit_future_time_to_rearm(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    app_id = await _application(client, auth_headers)
    created = await client.post(
        f"/tracker/applications/{app_id}/reminders",
        json={"remind_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        headers=auth_headers,
    )
    reminder_id = created.json()["id"]
    await db_session.execute(
        text(
            "UPDATE application_reminders SET sent_at = NOW(), delivery_claimed_at = NOW(), "
            "delivery_claim_token = 'in-flight', delivery_last_error = 'send_failed' WHERE id = :id"
        ),
        {"id": reminder_id},
    )
    await db_session.commit()

    note_only = await client.put(
        f"/tracker/applications/{app_id}/reminders/{reminder_id}",
        json={"note": "Do not accidentally resend"},
        headers=auth_headers,
    )
    assert note_only.status_code == 422
    rearmed = await client.put(
        f"/tracker/applications/{app_id}/reminders/{reminder_id}",
        json={"remind_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
        headers=auth_headers,
    )
    assert rearmed.status_code == 200
    assert rearmed.json()["sent_at"] is None
    claim = (
        await db_session.execute(
            text(
                "SELECT delivery_claimed_at, delivery_claim_token, delivery_last_error "
                "FROM application_reminders WHERE id = :id"
            ),
            {"id": reminder_id},
        )
    ).one()
    assert claim == (None, None, None)


@pytest.mark.asyncio
async def test_stale_applications_exclude_terminal_statuses(
    client: AsyncClient, auth_headers: dict, db_session: AsyncSession
):
    stale_id = await _application(client, auth_headers)
    terminal_id = await _application(client, auth_headers)
    old = datetime.now(timezone.utc) - timedelta(days=20)
    await db_session.execute(
        text("UPDATE job_applications SET updated_at = :old WHERE id IN (:one, :two)"),
        {"old": old, "one": stale_id, "two": terminal_id},
    )
    await db_session.commit()
    await client.patch(
        f"/tracker/applications/{terminal_id}/status",
        json={"status": "rejected"},
        headers=auth_headers,
    )
    response = await client.get("/tracker/stale-applications?days=14", headers=auth_headers)
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [stale_id]
    assert response.json()[0]["days_since_update"] >= 19


@pytest.mark.asyncio
async def test_interview_crud_and_authenticated_ics_export(client: AsyncClient, auth_headers: dict):
    app_id = await _application(client, auth_headers)
    created = await client.post(
        f"/tracker/applications/{app_id}/interviews",
        json={
            "round_name": "Technical; Round",
            "interview_format": "video",
            "starts_at": "2026-10-10T15:00:00+05:30",
            "duration_minutes": 45,
            "timezone": "Asia/Kolkata",
            "location": "https://meet.example.com/room,one",
            "interviewers": ["Ada", "Grace"],
            "notes": "Bring\nquestions",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    interview_id = created.json()["id"]

    exported = await client.get(
        f"/tracker/applications/{app_id}/interviews/{interview_id}.ics",
        headers=auth_headers,
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/calendar")
    assert "DTSTART:20261010T093000Z" in exported.text
    assert "SUMMARY:Technical\\; Round" in exported.text
    assert "LOCATION:https://meet.example.com/room\\,one" in exported.text
    assert "Bring\\nquestions" in exported.text
    assert all(len(line.encode("utf-8")) <= 75 for line in exported.text.split("\r\n"))
    assert (await client.get(f"/tracker/applications/{app_id}/interviews/{interview_id}.ics")).status_code == 401

    updated = await client.put(
        f"/tracker/applications/{app_id}/interviews/{interview_id}",
        json={"interview_format": "onsite"},
        headers=auth_headers,
    )
    assert updated.json()["interview_format"] == "onsite"


@pytest.mark.asyncio
async def test_company_and_contact_crm_crud(client: AsyncClient, auth_headers: dict):
    company = await client.post(
        "/tracker/companies",
        json={"name": "Example Labs", "website": "https://example.com"},
        headers=auth_headers,
    )
    assert company.status_code == 201
    company_id = company.json()["id"]
    duplicate = await client.post("/tracker/companies", json={"name": "Example Labs"}, headers=auth_headers)
    assert duplicate.status_code == 409

    contact = await client.post(
        "/tracker/contacts",
        json={
            "company_id": company_id,
            "name": "Taylor Recruiter",
            "email": "taylor@example.com",
            "linkedin_url": "https://www.linkedin.com/in/taylor",
        },
        headers=auth_headers,
    )
    assert contact.status_code == 201
    contact_id = contact.json()["id"]
    assert (await client.get("/tracker/contacts", headers=auth_headers)).json()[0]["company_id"] == company_id

    detached = await client.put(f"/tracker/contacts/{contact_id}", json={"company_id": None}, headers=auth_headers)
    assert detached.status_code == 200
    assert detached.json()["company_id"] is None


@pytest.mark.asyncio
async def test_workflow_resources_are_not_visible_to_another_application_owner(
    client: AsyncClient, auth_headers: dict, auth_headers2: dict
):
    app_id = await _application(client, auth_headers)
    remind_at = datetime.now(timezone.utc) + timedelta(days=1)
    denied = await client.post(
        f"/tracker/applications/{app_id}/reminders",
        json={"remind_at": remind_at.isoformat()},
        headers=auth_headers2,
    )
    assert denied.status_code == 404

    company = await client.post("/tracker/companies", json={"name": "Private Co"}, headers=auth_headers)
    invalid_link = await client.post(
        "/tracker/contacts",
        json={"company_id": company.json()["id"], "name": "Cross tenant"},
        headers=auth_headers2,
    )
    assert invalid_link.status_code == 404

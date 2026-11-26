"""Admin incident timeline: authorization, transitions, filters, audit and PII."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import admin_operations_service


async def _create_user(db: AsyncSession, *, role: str = "user") -> str:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Incident User', :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": f"incident_{user_id.replace('-', '')}@example.com",
            "role": role,
        },
    )
    await db.commit()
    return user_id


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"incident_sess_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    return await _session_headers(db, await _create_user(db, role=role))


@pytest.fixture(autouse=True)
async def _clean_incidents(db_session: AsyncSession):
    admin_operations_service.reset_admin_operations_cache()
    await db_session.execute(text("DELETE FROM admin_incidents"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM admin_incidents"))
    await db_session.commit()
    admin_operations_service.reset_admin_operations_cache()


def _payload(**overrides):
    body = {
        "summary": "Compiler workers are not draining the queue",
        "severity": "high",
        "services": ["API", "worker"],
        "owner": "Platform",
        "links": ["https://status.example.com/incidents/42"],
    }
    body.update(overrides)
    return body


async def _create_incident(
    client: AsyncClient,
    headers: dict[str, str],
    **overrides,
) -> dict:
    response = await client.post(
        "/admin/operations/incidents",
        json=_payload(**overrides),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _audit_rows(db: AsyncSession, target_id: str) -> list[dict]:
    return (
        await db.execute(
            text(
                "SELECT action, target_id, reason, before, after "
                "FROM admin_audit_log "
                "WHERE target_type = 'admin_incident' AND target_id = :target_id "
                "ORDER BY created_at ASC"
            ),
            {"target_id": target_id},
        )
    ).mappings().all()


async def test_incident_surfaces_are_admin_only(client: AsyncClient, db_session: AsyncSession):
    unauthenticated = await client.get("/admin/operations/incidents")
    assert unauthenticated.status_code == 401

    support_headers = await _headers(db_session, "support")
    forbidden = await client.get("/admin/operations/incidents", headers=support_headers)
    assert forbidden.status_code == 403
    forbidden_create = await client.post(
        "/admin/operations/incidents",
        json=_payload(),
        headers=support_headers,
    )
    assert forbidden_create.status_code == 403

    admin_headers = await _headers(db_session, "admin")
    allowed = await client.get("/admin/operations/incidents", headers=admin_headers)
    assert allowed.status_code == 200


async def test_open_resolve_and_reopen_transitions_are_audited(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _headers(db_session)
    incident = await _create_incident(
        client,
        headers,
        title="Worker queue stall",
        deploy_sha="abc1234",
        deploy_url="https://deploy.example.com/releases/abc1234",
    )
    incident_id = incident["id"]
    assert incident["status"] == "open"
    assert incident["ended_at"] is None
    assert incident["services"] == ["api", "worker"]
    assert incident["deploy_sha"] == "abc1234"
    assert incident["deploy_url"] == "https://deploy.example.com/releases/abc1234"

    opened = await _audit_rows(db_session, incident_id)
    assert [row["action"] for row in opened] == ["admin.incident.open"]
    assert opened[0]["after"]["status"] == "open"

    resolved = await client.post(
        f"/admin/operations/incidents/{incident_id}/resolve",
        json={"reason": "Queue depth returned to baseline"},
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    resolved_body = resolved.json()
    assert resolved_body["status"] == "resolved"
    assert resolved_body["ended_at"] is not None
    assert resolved_body["duration_seconds"] >= 0

    resolved_again = await client.post(
        f"/admin/operations/incidents/{incident_id}/resolve",
        json={},
        headers=headers,
    )
    assert resolved_again.status_code == 422

    reopened = await client.post(
        f"/admin/operations/incidents/{incident_id}/reopen",
        json={"reason": "Queue stalled again after recovery"},
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "open"
    assert reopened.json()["ended_at"] is None

    rows = await _audit_rows(db_session, incident_id)
    assert [row["action"] for row in rows] == [
        "admin.incident.open",
        "admin.incident.resolve",
        "admin.incident.reopen",
    ]
    assert rows[1]["before"]["status"] == "open"
    assert rows[1]["after"]["status"] == "resolved"
    assert rows[2]["before"]["status"] == "resolved"
    assert rows[2]["after"]["status"] == "open"


async def test_timeline_filters_by_service_severity_status_and_date(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _headers(db_session)
    now = datetime.now(timezone.utc)
    old = await _create_incident(
        client,
        headers,
        summary="Old API incident",
        severity="high",
        services=["api"],
        started_at=(now - timedelta(days=10)).isoformat(),
    )
    recent = await _create_incident(
        client,
        headers,
        summary="Recent worker incident",
        severity="low",
        services=["worker"],
        started_at=(now - timedelta(days=2)).isoformat(),
    )
    resolved = await _create_incident(
        client,
        headers,
        summary="Resolved critical API incident",
        severity="critical",
        services=["api", "billing"],
        started_at=(now - timedelta(days=3)).isoformat(),
    )
    resolve_response = await client.post(
        f"/admin/operations/incidents/{resolved['id']}/resolve",
        json={"ended_at": (now - timedelta(days=1)).isoformat()},
        headers=headers,
    )
    assert resolve_response.status_code == 200, resolve_response.text

    by_service = await client.get(
        "/admin/operations/incidents",
        params={"service": "api"},
        headers=headers,
    )
    assert by_service.status_code == 200
    assert {item["id"] for item in by_service.json()["items"]} == {old["id"], resolved["id"]}

    by_severity = await client.get(
        "/admin/operations/incidents",
        params={"severity": "critical"},
        headers=headers,
    )
    assert [item["id"] for item in by_severity.json()["items"]] == [resolved["id"]]

    active_only = await client.get(
        "/admin/operations/incidents",
        params={"status": "active"},
        headers=headers,
    )
    assert {item["id"] for item in active_only.json()["items"]} == {old["id"], recent["id"]}

    resolved_only = await client.get(
        "/admin/operations/incidents",
        params={"status": "resolved"},
        headers=headers,
    )
    assert [item["id"] for item in resolved_only.json()["items"]] == [resolved["id"]]

    by_date = await client.get(
        "/admin/operations/incidents",
        params={
            "start_date": (now - timedelta(days=4)).isoformat(),
            "end_date": (now - timedelta(days=1, hours=12)).isoformat(),
        },
        headers=headers,
    )
    assert by_date.status_code == 200, by_date.text
    ids = {item["id"] for item in by_date.json()["items"]}
    assert recent["id"] in ids
    assert resolved["id"] in ids
    assert old["id"] not in ids

    timeline = await client.get(
        "/admin/operations/incidents/timeline",
        params={"service": "api", "state": "active"},
        headers=headers,
    )
    assert timeline.status_code == 200, timeline.text
    assert [item["id"] for item in timeline.json()["items"]] == [old["id"]]


async def test_active_incidents_join_the_needs_attention_queue(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _headers(db_session)
    incident = await _create_incident(
        client,
        headers,
        title="Redis failover in progress",
        severity="medium",
        services=["redis"],
    )

    attention = await client.get("/admin/operations/attention", headers=headers)
    assert attention.status_code == 200
    body = attention.json()
    incident_items = [item for item in body["items"] if item["key"].startswith("incidents.")]
    assert [(item["key"], item["title"]) for item in incident_items] == [
        (f"incidents.{incident['id']}", "Redis failover in progress")
    ]
    assert incident_items[0]["severity"] == "medium"
    assert incident_items[0]["href"].startswith("/admin?tab=operations")
    source = next(source for source in body["sources"] if source["key"] == "incidents.active")
    assert source["status"] == "ok"
    assert source["count"] == 1

    resolved = await client.post(
        f"/admin/operations/incidents/{incident['id']}/resolve",
        json={},
        headers=headers,
    )
    assert resolved.status_code == 200

    attention_after = await client.get("/admin/operations/attention", headers=headers)
    assert attention_after.status_code == 200
    after_body = attention_after.json()
    assert not [item for item in after_body["items"] if item["key"].startswith("incidents.")]
    after_source = next(
        source for source in after_body["sources"] if source["key"] == "incidents.active"
    )
    assert after_source["count"] == 0


@pytest.mark.parametrize(
    "summary",
    [
        "Customer jane@example.com cannot compile",
        "Call the customer on +1 415-555-0123",
        "Authorization: Bearer abcdefghijklmnop",
        "Customer SSN 123-45-6789",
        "Pasted resume: \\documentclass{article}",
    ],
)
async def test_incident_text_rejects_direct_identifiers_and_secrets(
    client: AsyncClient, db_session: AsyncSession, summary: str
):
    headers = await _headers(db_session)
    response = await client.post(
        "/admin/operations/incidents",
        json=_payload(summary=summary),
        headers=headers,
    )
    assert response.status_code == 422
    assert "jane@example.com" not in response.text
    assert "415-555-0123" not in response.text
    assert "abcdefghijklmnop" not in response.text


async def test_links_reject_embedded_credentials(client: AsyncClient, db_session: AsyncSession):
    headers = await _headers(db_session)
    response = await client.post(
        "/admin/operations/incidents",
        json=_payload(links=["https://operator:secret@example.com/incident"]),
        headers=headers,
    )
    assert response.status_code == 422
    assert "secret" not in response.text


async def test_related_alert_correlation_and_deploy_marker(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _headers(db_session)
    dedupe_key = f"test.incident.{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    alert = models.AdminAlert(
        kind="test.incident",
        severity="high",
        owner="Platform",
        title="Test correlated alert",
        dedupe_key=dedupe_key,
        payload={"count": 2},
        state="open",
        occurrence_count=2,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(alert)
    await db_session.commit()

    incident = await _create_incident(
        client,
        headers,
        deploy_sha="deadbeef",
        related_alert_keys=[dedupe_key, "billing.unknown_rule"],
    )
    assert [row["title"] for row in incident["related_alerts"]] == ["Test correlated alert"]
    assert incident["related_alert_keys"] == [dedupe_key, "billing.unknown_rule"]
    assert incident["deploy_sha"] == "deadbeef"

    detail = await client.get(
        f"/admin/operations/incidents/{incident['id']}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["related_alerts"][0]["dedupe_key"] == dedupe_key

    listing = await client.get("/admin/operations/incidents", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["related_alerts"][0]["title"] == "Test correlated alert"


async def test_update_and_delete_are_audited(client: AsyncClient, db_session: AsyncSession):
    headers = await _headers(db_session)
    incident = await _create_incident(client, headers)

    updated = await client.patch(
        f"/admin/operations/incidents/{incident['id']}",
        json={
            "summary": "Workers recovered after a queue restart",
            "severity": "medium",
            "services": ["worker"],
            "owner": "SRE",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["severity"] == "medium"
    assert body["services"] == ["worker"]
    assert body["owner"] == "SRE"

    no_changes = await client.patch(
        f"/admin/operations/incidents/{incident['id']}",
        json={},
        headers=headers,
    )
    assert no_changes.status_code == 422

    deleted = await client.delete(
        f"/admin/operations/incidents/{incident['id']}",
        params={"reason": "Duplicate entry"},
        headers=headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "id": incident["id"]}

    missing = await client.get(
        f"/admin/operations/incidents/{incident['id']}",
        headers=headers,
    )
    assert missing.status_code == 404

    rows = await _audit_rows(db_session, incident["id"])
    assert [row["action"] for row in rows] == [
        "admin.incident.open",
        "admin.incident.update",
        "admin.incident.delete",
    ]
    assert rows[1]["before"]["severity"] == "high"
    assert rows[1]["after"]["severity"] == "medium"
    assert rows[2]["before"]["severity"] == "medium"


def test_incident_migration_declares_isolated_revision():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0088_admin_incidents.py"
    spec = importlib.util.spec_from_file_location("admin_incidents_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "0088_admin_incidents"
    assert migration.down_revision == "0087_email_delivery_events"
    source = path.read_text()
    assert '"admin_incidents"' in source
    assert "drop_table" in source

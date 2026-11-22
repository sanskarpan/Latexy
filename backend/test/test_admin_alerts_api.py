"""Durable admin alerts: evaluation, filtering, ack and snooze."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import admin_alert_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"alert_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Alert User', :role, true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": email, "role": role},
    )
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"alert_sess_{uuid.uuid4().hex}"
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
    return {"Authorization": f"Bearer {token}"}


async def _headers(db: AsyncSession, role: str = "admin") -> dict[str, str]:
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


async def _clear_conditions(db: AsyncSession) -> None:
    await db.execute(
        text("UPDATE billing_webhook_events SET acknowledged_at = now() WHERE status = 'failed'")
    )
    await db.execute(text("UPDATE payments SET status = 'paid' WHERE status = 'failed'"))
    await db.execute(
        text("UPDATE subscriptions SET status = 'active' WHERE status IN ('past_due', 'on_hold')")
    )
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    await db.execute(
        text(
            "UPDATE compilations SET status = 'completed' "
            "WHERE status IN ('queued', 'pending', 'processing', 'running') AND created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    await db.execute(
        text(
            "UPDATE job_finalizations SET state = 'completed' "
            "WHERE state IN ('pending', 'committing') AND created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    await db.execute(
        text(
            "UPDATE tenants SET domain_verified_at = now() "
            "WHERE custom_domain IS NOT NULL AND domain_verified_at IS NULL"
        )
    )


async def _clear_signals(db: AsyncSession) -> None:
    await db.execute(text("DELETE FROM admin_alerts"))
    await _clear_conditions(db)


async def _seed_failures(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    user_id, _ = await _create_user(db)
    await db.execute(
        text(
            "INSERT INTO billing_webhook_events "
            "(id, provider, event_id, event_type, payload_sha256, status, attempts, received_at) "
            "VALUES (:id, 'dodo', :event_id, 'payment.failed', :sha, 'failed', 1, :received)"
        ),
        {
            "id": str(uuid.uuid4()),
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sha": "b" * 64,
            "received": now - timedelta(minutes=10),
        },
    )
    await db.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_payment, 59900, 'INR', 'failed', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
            "created": now - timedelta(minutes=10),
        },
    )
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end) "
            "VALUES (:id, :uid, 'dodo', :provider_sub, 'pro', 'past_due', :start, :end)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_sub": f"sub_{uuid.uuid4().hex[:12]}",
            "start": now - timedelta(days=2),
            "end": now + timedelta(days=28),
        },
    )
    await db.execute(
        text(
            "INSERT INTO compilations (id, job_id, status, created_at) "
            "VALUES (:id, :job_id, 'processing', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "job_id": f"job_{uuid.uuid4().hex}",
            "created": now - timedelta(minutes=40),
        },
    )
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, custom_domain, name, owner_id) "
            "VALUES (:id, :slug, :domain, 'Alert Tenant', :owner)"
        ),
        {
            "id": str(uuid.uuid4()),
            "slug": f"alert-{uuid.uuid4().hex[:10]}",
            "domain": f"{uuid.uuid4().hex[:10]}.example.com",
            "owner": user_id,
        },
    )


async def test_alert_evaluation_deduplicates_and_resolves(db_session: AsyncSession):
    await _clear_signals(db_session)
    await _seed_failures(db_session)

    now = datetime.now(timezone.utc)
    first = await admin_alert_service.evaluate_alerts(db_session, now=now)
    assert first["opened"] >= 4

    rows = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, state, occurrence_count FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert {row.dedupe_key for row in rows} == {
        "billing.webhook_failures",
        "billing.failed_payments",
        "billing.past_due",
        "jobs.stuck",
        "domains.unverified",
    }
    assert all(row.state == "open" for row in rows)

    second = await admin_alert_service.evaluate_alerts(db_session, now=now + timedelta(minutes=1))
    assert second["updated"] >= 4
    rows = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, occurrence_count FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert all(row.occurrence_count == 2 for row in rows)

    await _clear_conditions(db_session)
    resolved = await admin_alert_service.evaluate_alerts(db_session, now=now + timedelta(minutes=2))
    assert resolved["resolved"] >= 4
    states = (
        await db_session.execute(
            text(
                "SELECT dedupe_key, state FROM admin_alerts "
                "WHERE dedupe_key IN ('billing.webhook_failures', 'billing.failed_payments', "
                "'billing.past_due', 'jobs.stuck', 'domains.unverified')"
            )
        )
    ).all()
    assert all(row.state == "resolved" for row in states)


async def test_alert_actions_are_admin_only_and_audited(
    client: AsyncClient, db_session: AsyncSession
):
    await db_session.execute(text("DELETE FROM admin_alerts WHERE dedupe_key LIKE 'test.alert.%'"))
    now = datetime.now(timezone.utc)
    alert = models.AdminAlert(
        kind="test.alert",
        severity="high",
        owner="Platform",
        title="Test alert",
        dedupe_key=f"test.alert.{uuid.uuid4().hex}",
        payload={"count": 1},
        state="open",
        occurrence_count=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(alert)
    await db_session.commit()
    alert_id = alert.id

    unauthenticated = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed"},
    )
    assert unauthenticated.status_code == 401

    support_headers = await _headers(db_session, "support")
    forbidden = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed"},
        headers=support_headers,
    )
    assert forbidden.status_code == 403

    admin_headers = await _headers(db_session, "admin")
    acknowledged = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "acknowledged", "reason": "reviewed provider state"},
        headers=admin_headers,
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "acknowledged"

    audit = await client.get(
        f"/admin/audit?action=admin.alert.acknowledge&target_id={alert_id}",
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1

    snoozed = await client.patch(
        f"/admin/alerts/{alert_id}",
        json={"state": "snoozed", "reason": "waiting for provider", "snooze_minutes": 60},
        headers=admin_headers,
    )
    assert snoozed.status_code == 200
    body = snoozed.json()
    assert body["state"] == "snoozed"
    assert body["snooze_until"] is not None

    listed = await client.get("/admin/alerts?state=active", headers=admin_headers)
    assert listed.status_code == 200
    assert any(item["id"] == alert_id for item in listed.json()["items"])

    await db_session.execute(text("DELETE FROM admin_alerts WHERE id = :id"), {"id": alert_id})
    await db_session.commit()

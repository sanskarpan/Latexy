"""Admin operations attention queue and health aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import admin_operations_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    email: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    if email is None:
        email = f"ops_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Operations User",
            "role": role,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"ops_sess_{uuid.uuid4().hex}"
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
    user_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, user_id)


@pytest.fixture(autouse=True)
def _clear_health_cache():
    admin_operations_service.reset_admin_operations_cache()
    yield
    admin_operations_service.reset_admin_operations_cache()


async def test_attention_requires_admin(client: AsyncClient):
    response = await client.get("/admin/operations/attention")
    assert response.status_code == 401


async def test_attention_is_admin_only(client: AsyncClient, db_session: AsyncSession):
    headers = await _headers(db_session, "support")
    response = await client.get("/admin/operations/attention", headers=headers)
    assert response.status_code == 403


async def test_attention_aggregates_failures_without_pii(
    client: AsyncClient, db_session: AsyncSession
):
    admin_headers = await _headers(db_session, "admin")
    user_id, email = await _create_user(db_session)

    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO billing_webhook_events "
            "(id, provider, event_id, event_type, payload_sha256, status, attempts, received_at) "
            "VALUES (:id, 'dodo', :event_id, 'payment.failed', :sha, 'failed', 1, :received)"
        ),
        {
            "id": str(uuid.uuid4()),
            "event_id": f"evt_{uuid.uuid4().hex}",
            "sha": "a" * 64,
            "received": now - timedelta(hours=2),
        },
    )
    await db_session.execute(
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
    await db_session.execute(
        text(
            "INSERT INTO payments (id, user_id, provider, provider_payment_id, "
            "amount, currency, status, created_at) "
            "VALUES (:id, :uid, 'dodo', :provider_payment, 59900, 'INR', 'failed', :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "provider_payment": f"pay_{uuid.uuid4().hex[:12]}",
            "created": now - timedelta(hours=3),
        },
    )
    await db_session.execute(
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
    await db_session.commit()

    response = await client.get("/admin/operations/attention", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    keys = {item["key"] for item in body["items"]}
    assert {"billing.webhooks", "billing.subscriptions", "billing.payments", "jobs.stuck"} <= keys

    webhook = next(item for item in body["items"] if item["key"] == "billing.webhooks")
    assert webhook["count"] >= 1
    assert webhook["severity"] == "critical"
    assert webhook["owner"] == "Billing"
    assert webhook["href"].startswith("/admin?tab=billing")
    assert email not in response.text
    assert "provider_payment" not in response.text
    assert all(source["status"] in {"ok", "partial", "unavailable"} for source in body["sources"])
    domains = next(source for source in body["sources"] if source["key"] == "domains.custom")
    assert domains["status"] == "partial"
    assert "expiry metadata is not configured" in domains["detail"]


async def test_health_survives_one_failed_probe_and_hides_details(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    admin_headers = await _headers(db_session, "admin")
    monkeypatch.setattr(
        admin_operations_service,
        "_probe_database",
        AsyncMock(return_value=("healthy", None)),
    )
    monkeypatch.setattr(
        admin_operations_service,
        "_probe_redis",
        AsyncMock(return_value=("healthy", None)),
    )
    monkeypatch.setattr(
        admin_operations_service,
        "_probe_redis_cache",
        AsyncMock(return_value=("healthy", None)),
    )

    async def _failed_storage():
        raise RuntimeError("upstream-secret-sentinel")

    monkeypatch.setattr(admin_operations_service, "_probe_storage", _failed_storage)
    monkeypatch.setattr(
        admin_operations_service,
        "_probe_capacity",
        AsyncMock(return_value=("healthy", None, {"provider": "upstash", "configured": True})),
    )

    response = await client.get("/admin/operations/health", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"degraded", "unhealthy"}
    assert body["sections"]["database"]["status"] == "healthy"
    assert body["sections"]["storage"]["status"] == "unhealthy"
    assert "upstream-secret-sentinel" not in response.text
    assert {"capacity", "billing", "job_queue", "compilations"} <= set(body["sections"])

    # The second request is served from the short-lived cache.
    cached = await client.get("/admin/operations/health", headers=admin_headers)
    assert cached.status_code == 200
    assert cached.json()["generated_at"] == body["generated_at"]

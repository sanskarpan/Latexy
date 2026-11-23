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
        email = f"test_ops_{user_id.replace('-', '')}@example.com"
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


async def _create_tenant(
    db: AsyncSession,
    *,
    owner_id: str,
    slug: str,
    domain_verified_at: datetime | None,
    domain_expires_at: datetime | None,
    certificate_expires_at: datetime | None,
) -> str:
    tenant_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO tenants "
            "(id, slug, custom_domain, domain_verified_at, domain_expires_at, "
            "domain_certificate_expires_at, name, owner_id) "
            "VALUES (:id, :slug, :domain, :verified, :expires, :certificate, :name, :owner)"
        ),
        {
            "id": tenant_id,
            "slug": f"{slug}_{tenant_id.replace('-', '')[:10]}",
            "domain": f"{slug}-{tenant_id.replace('-', '')[:8]}.example.com",
            "verified": domain_verified_at,
            "expires": domain_expires_at,
            "certificate": certificate_expires_at,
            "name": "Operations Tenant",
            "owner": owner_id,
        },
    )
    await db.commit()
    return tenant_id


@pytest.fixture(autouse=True)
def _clear_health_cache():
    admin_operations_service.reset_admin_operations_cache()
    yield
    admin_operations_service.reset_admin_operations_cache()


@pytest.fixture
async def clean_domain_tenants(db_session: AsyncSession):
    """Domain tests assert exact coverage; other suites may leave tenants behind."""
    await db_session.execute(text("DELETE FROM tenants WHERE custom_domain IS NOT NULL"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM tenants WHERE custom_domain IS NOT NULL"))
    await db_session.commit()


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
    assert "webhook_status=failed" in webhook["href"]
    assert "acknowledged=false" in webhook["href"]
    subscriptions = next(item for item in body["items"] if item["key"] == "billing.subscriptions")
    assert "subscription_status=past_due" in subscriptions["href"]
    payments = next(item for item in body["items"] if item["key"] == "billing.payments")
    assert "payment_status=failed" in payments["href"]
    stuck = next(item for item in body["items"] if item["key"] == "jobs.stuck")
    assert "job_status=processing" in stuck["href"]
    assert "#admin-job-queue" in stuck["href"]
    assert email not in response.text
    assert "provider_payment" not in response.text
    assert all(source["status"] in {"ok", "partial", "unavailable"} for source in body["sources"])
    domains = next(source for source in body["sources"] if source["key"] == "domains.custom")
    assert domains["status"] in {"ok", "partial"}
    assert domains["metadata_status"] in {"complete", "partial", "unknown"}


async def test_attention_reports_expiring_domains_with_filtered_links(
    client: AsyncClient, db_session: AsyncSession, clean_domain_tenants
):
    admin_headers = await _headers(db_session, "admin")
    owner_id, _ = await _create_user(db_session)
    now = datetime.now(timezone.utc)
    await _create_tenant(
        db_session,
        owner_id=owner_id,
        slug="expiring",
        domain_verified_at=now - timedelta(days=30),
        domain_expires_at=now + timedelta(days=10),
        certificate_expires_at=now + timedelta(days=5),
    )
    await _create_tenant(
        db_session,
        owner_id=owner_id,
        slug="farfuture",
        domain_verified_at=now - timedelta(days=30),
        domain_expires_at=now + timedelta(days=120),
        certificate_expires_at=now + timedelta(days=200),
    )

    response = await client.get("/admin/operations/attention", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    items = {item["key"]: item for item in body["items"]}
    assert items["domains.expiry"]["count"] == 1
    assert items["domains.expiry"]["severity"] == "high"
    assert items["domains.expiry"]["owner"] == "Growth"
    assert items["domains.expiry"]["days_until_expiry"] == 10
    assert "domain_status=expiring" in items["domains.expiry"]["href"]
    assert "domain_window=30" in items["domains.expiry"]["href"]
    assert "tab=customers" in items["domains.expiry"]["href"]
    assert items["domains.certificate_expiry"]["count"] == 1
    assert items["domains.certificate_expiry"]["severity"] == "critical"
    assert items["domains.certificate_expiry"]["days_until_expiry"] == 5
    assert "domain_certificate=expiring" in items["domains.certificate_expiry"]["href"]
    assert "domains.verification" not in items

    source = next(source for source in body["sources"] if source["key"] == "domains.custom")
    assert source["status"] == "ok"
    assert source["metadata_status"] == "complete"
    assert source["count"] == 2
    assert source["domain_expiring"] == 1
    assert source["certificate_expiring"] == 1
    assert source["unknown_domain_expiry"] == 0
    assert "example.com" not in response.text


async def test_attention_domain_unknown_and_unverified_metadata_is_partial(
    client: AsyncClient, db_session: AsyncSession, clean_domain_tenants
):
    admin_headers = await _headers(db_session, "admin")
    owner_id, _ = await _create_user(db_session)
    now = datetime.now(timezone.utc)
    await _create_tenant(
        db_session,
        owner_id=owner_id,
        slug="unknownmeta",
        domain_verified_at=now - timedelta(days=5),
        domain_expires_at=None,
        certificate_expires_at=None,
    )
    await _create_tenant(
        db_session,
        owner_id=owner_id,
        slug="unverified",
        domain_verified_at=None,
        domain_expires_at=now + timedelta(days=20),
        certificate_expires_at=now + timedelta(days=20),
    )

    response = await client.get("/admin/operations/attention", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    source = next(source for source in body["sources"] if source["key"] == "domains.custom")
    assert source["status"] == "partial"
    assert source["metadata_status"] == "partial"
    assert source["unverified"] == 1
    assert source["unknown_domain_expiry"] == 1
    assert source["unknown_certificate_expiry"] == 1
    assert "unknown expiry metadata" in source["detail"]
    assert "unverified" in source["detail"]
    items = {item["key"]: item for item in body["items"]}
    assert items["domains.verification"]["count"] == 1
    assert "domain_status=unverified" in items["domains.verification"]["href"]
    assert items["domains.expiry"]["count"] == 1
    assert items["domains.expiry"]["metadata_status"] == "partial"
    assert body["partial"] is True


async def test_attention_all_unknown_domain_metadata_is_explicit(
    client: AsyncClient, db_session: AsyncSession, clean_domain_tenants
):
    admin_headers = await _headers(db_session, "admin")
    owner_id, _ = await _create_user(db_session)
    now = datetime.now(timezone.utc)
    await _create_tenant(
        db_session,
        owner_id=owner_id,
        slug="allunknown",
        domain_verified_at=now - timedelta(days=5),
        domain_expires_at=None,
        certificate_expires_at=None,
    )

    response = await client.get("/admin/operations/attention", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    source = next(source for source in body["sources"] if source["key"] == "domains.custom")
    assert source["status"] == "partial"
    assert source["metadata_status"] == "unknown"
    assert "expiry metadata is not configured" in source["detail"]
    assert not any(item["key"] in {"domains.expiry", "domains.certificate_expiry"} for item in body["items"])


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

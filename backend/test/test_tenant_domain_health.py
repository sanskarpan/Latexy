"""Tenant custom-domain verification history and health.

The backend tests exercise both sides of the contract:

* ``domain_health_payload`` stays aggregate/allowlisted and never emits TXT
  values, DNS payloads or certificate material.
* The real route records every verification attempt, keeps history after a
  domain is removed, scopes reads to the tenant and enforces owner/admin RBAC.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tenant_domain_health_service import (
    domain_health_payload,
    record_domain_event,
)


def _uid() -> str:
    return str(uuid.uuid4())


def _domain() -> str:
    return f"test-{uuid.uuid4().hex[:12]}.example.edu"


def _event(
    domain: str = "health.example.edu",
    event_type: str = "verified",
    checked_at: datetime | None = None,
    error_class: str | None = None,
    event_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=event_id or _uid(),
        tenant_id=_uid(),
        domain=domain,
        event_type=event_type,
        error_class=error_class,
        checked_at=checked_at or datetime.now(timezone.utc),
    )


def _tenant(
    *,
    domain: str | None = "health.example.edu",
    verified_at: datetime | None = None,
    domain_expires_at: datetime | None = None,
    certificate_expires_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=_uid(),
        custom_domain=domain,
        domain_verified_at=verified_at,
        domain_expires_at=domain_expires_at,
        domain_certificate_expires_at=certificate_expires_at,
    )


def _dns_context(txt_value: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"Answer": [{"type": 16, "data": f'"{txt_value}"'}]}
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


async def _user_id(db_session: AsyncSession, headers: dict) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    row = await db_session.execute(
        text('SELECT u.id FROM users u JOIN session s ON s."userId"::uuid = u.id WHERE s.token = :token'),
        {"token": token},
    )
    return str(row.scalar_one())


async def _insert_tenant(
    db_session: AsyncSession,
    *,
    owner_id: str,
    domain: str | None = "health.example.edu",
    verified_at: datetime | None = None,
    domain_expires_at: datetime | None = None,
    certificate_expires_at: datetime | None = None,
) -> str:
    tenant_id = _uid()
    await db_session.execute(
        text(
            "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members, "
            "custom_domain, domain_verified_at, domain_expires_at, "
            "domain_certificate_expires_at) "
            "VALUES (:id, :slug, 'Domain Health Test', :owner, 'agency', 50, "
            ":domain, :verified_at, :domain_expires, :certificate_expires)"
        ),
        {
            "id": tenant_id,
            "slug": f"test-{uuid.uuid4().hex[:12]}",
            "owner": owner_id,
            "domain": domain,
            "verified_at": verified_at,
            "domain_expires": domain_expires_at,
            "certificate_expires": certificate_expires_at,
        },
    )
    await db_session.commit()
    return tenant_id


async def _add_member(db_session: AsyncSession, *, tenant_id: str, user_id: str, role: str) -> None:
    await db_session.execute(
        text("INSERT INTO tenant_members (tenant_id, user_id, role) VALUES (:tenant, :user, :role)"),
        {"tenant": tenant_id, "user": user_id, "role": role},
    )
    await db_session.commit()


async def _insert_event(
    db_session: AsyncSession,
    *,
    tenant_id: str,
    domain: str,
    event_type: str,
    checked_at: datetime,
    error_class: str | None = None,
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO tenant_domain_events "
            "(tenant_id, domain, event_type, error_class, checked_at) "
            "VALUES (:tenant, :domain, :event_type, :error_class, :checked_at)"
        ),
        {
            "tenant": tenant_id,
            "domain": domain,
            "event_type": event_type,
            "error_class": error_class,
            "checked_at": checked_at,
        },
    )
    await db_session.commit()


# ── Pure health payload ──────────────────────────────────────────────────────


def test_stale_verification_warns_without_inventing_expiry_data():
    now = datetime.now(timezone.utc)
    tenant = _tenant(verified_at=now - timedelta(days=45))
    payload = domain_health_payload(
        tenant,
        [_event(checked_at=now - timedelta(days=45))],
        now=now,
    )

    assert payload["status"] == "stale"
    assert payload["verification_age_days"] == 45
    assert [warning["code"] for warning in payload["warnings"]] == ["verification_stale"]
    assert payload["expiry"]["domain_state"] == "unknown"
    assert payload["expiry"]["certificate_state"] == "unknown"
    assert all(
        warning["code"] not in {"domain_expired", "domain_expiring", "certificate_expired", "certificate_expiring"}
        for warning in payload["warnings"]
    )


def test_failed_recheck_is_unhealthy_and_keeps_earlier_verification_visible():
    now = datetime.now(timezone.utc)
    tenant = _tenant(verified_at=now - timedelta(days=2))
    payload = domain_health_payload(
        tenant,
        [
            _event(event_type="error", checked_at=now, error_class="dns_unavailable"),
            _event(event_type="verified", checked_at=now - timedelta(days=2)),
        ],
        now=now,
    )

    assert payload["status"] == "unhealthy"
    assert payload["verified"] is True
    assert payload["last_checked_at"] == now
    assert payload["last_success_at"] == now - timedelta(days=2)
    warning = payload["warnings"][0]
    assert warning["code"] == "verification_unhealthy"
    assert warning["error_class"] == "dns_unavailable"


def test_unverified_domain_reports_txt_missing_without_echoing_the_txt_value():
    now = datetime.now(timezone.utc)
    tenant = _tenant(verified_at=None)
    payload = domain_health_payload(
        tenant,
        [
            _event(
                event_type="failed",
                checked_at=now,
                error_class="txt_missing",
            )
        ],
        now=now,
    )

    assert payload["status"] == "unverified"
    assert payload["warnings"][0]["code"] == "verification_unverified"
    assert payload["warnings"][0]["error_class"] == "txt_missing"
    assert "latexy-verify" not in repr(payload)


def test_expiry_warnings_are_emitted_only_for_known_metadata():
    now = datetime.now(timezone.utc)
    tenant = _tenant(
        verified_at=now,
        domain_expires_at=now + timedelta(days=5),
        certificate_expires_at=now - timedelta(days=1),
    )
    payload = domain_health_payload(tenant, [_event(checked_at=now)], now=now)

    codes = {warning["code"] for warning in payload["warnings"]}
    assert codes == {"domain_expiring", "certificate_expired"}
    assert payload["expiry"]["domain_state"] == "expiring"
    assert payload["expiry"]["certificate_state"] == "expired"
    assert payload["expiry"]["domain_days_until_expiry"] == 5


def test_history_is_kept_after_the_domain_is_removed():
    now = datetime.now(timezone.utc)
    tenant = _tenant(domain=None, verified_at=None)
    payload = domain_health_payload(
        tenant,
        [
            _event(event_type="removed", checked_at=now),
            _event(event_type="verified", checked_at=now - timedelta(days=90)),
        ],
        now=now,
    )

    assert payload["status"] == "not_configured"
    assert payload["domain"] is None
    assert payload["verified"] is False
    assert payload["verification_age_days"] is None
    assert [entry["event_type"] for entry in payload["history"]] == [
        "removed",
        "verified",
    ]
    assert payload["expiry"]["domain_state"] == "unknown"


def test_record_event_rejects_unknown_outcomes_and_error_classes():
    db = MagicMock()
    with pytest.raises(ValueError):
        record_domain_event(
            db,
            tenant_id=_uid(),
            domain="health.example.edu",
            event_type="granted",
        )
    with pytest.raises(ValueError):
        record_domain_event(
            db,
            tenant_id=_uid(),
            domain="health.example.edu",
            event_type="failed",
            error_class="provider_stacktrace",
        )
    db.add.assert_not_called()


# ── Route integration ────────────────────────────────────────────────────────


class TestDomainHealthRoutes:
    async def test_verify_records_every_attempt_and_health_omits_txt_values(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
    ):
        owner_id = await _user_id(db_session, auth_headers)
        domain = _domain()
        tenant_id = await _insert_tenant(db_session, owner_id=owner_id, domain=domain)

        with patch(
            "app.api.tenant_routes.guarded_async_client",
            return_value=_dns_context(f"latexy-verify={tenant_id}"),
        ):
            verified = await client.post(f"/tenants/{tenant_id}/domain/verify", headers=auth_headers)
        assert verified.status_code == 200, verified.text
        assert verified.json()["verified"] is True

        with patch(
            "app.api.tenant_routes.guarded_async_client",
            return_value=_dns_context("latexy-verify=someone-else"),
        ):
            failed = await client.post(f"/tenants/{tenant_id}/domain/verify", headers=auth_headers)
        assert failed.status_code == 200, failed.text
        assert failed.json()["verified"] is False

        health = await client.get(f"/tenants/{tenant_id}/domain/health", headers=auth_headers)
        assert health.status_code == 200, health.text
        body = health.json()
        assert body["status"] == "unverified"
        assert body["domain"] == domain
        assert body["last_checked_at"] is not None
        assert [entry["event_type"] for entry in body["history"]] == [
            "failed",
            "verified",
        ]
        assert body["history"][0]["error_class"] == "txt_missing"
        assert "latexy-verify" not in health.text

    async def test_history_and_health_are_tenant_scoped_and_owner_admin_only(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
    ):
        owner_a = await _user_id(db_session, auth_headers)
        user_b = await _user_id(db_session, auth_headers2)
        domain_a, domain_b = _domain(), _domain()
        tenant_a = await _insert_tenant(db_session, owner_id=owner_a, domain=domain_a)
        tenant_b = await _insert_tenant(
            db_session,
            owner_id=user_b,
            domain=domain_b,
            verified_at=datetime.now(timezone.utc),
        )
        await _insert_event(
            db_session,
            tenant_id=tenant_b,
            domain=domain_b,
            event_type="verified",
            checked_at=datetime.now(timezone.utc),
        )

        foreign = await client.get(f"/tenants/{tenant_a}/domain/health", headers=auth_headers2)
        assert foreign.status_code == 403

        await _add_member(db_session, tenant_id=tenant_a, user_id=user_b, role="member")
        member = await client.get(f"/tenants/{tenant_a}/domain/health", headers=auth_headers2)
        assert member.status_code == 403

        await db_session.execute(
            text("UPDATE tenant_members SET role = 'admin' WHERE tenant_id = :tenant AND user_id = :user"),
            {"tenant": tenant_a, "user": user_b},
        )
        await db_session.commit()
        admin = await client.get(f"/tenants/{tenant_a}/domain/health", headers=auth_headers2)
        assert admin.status_code == 200, admin.text
        assert admin.json()["history"] == []

        owner = await client.get(f"/tenants/{tenant_b}/domain/health", headers=auth_headers2)
        assert owner.status_code == 200
        assert owner.json()["domain"] == domain_b

    async def test_domain_removal_keeps_history_and_reports_not_configured(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
    ):
        owner_id = await _user_id(db_session, auth_headers)
        verified_at = datetime.now(timezone.utc) - timedelta(days=3)
        domain = _domain()
        tenant_id = await _insert_tenant(
            db_session,
            owner_id=owner_id,
            domain=domain,
            verified_at=verified_at,
            domain_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )
        await _insert_event(
            db_session,
            tenant_id=tenant_id,
            domain=domain,
            event_type="verified",
            checked_at=verified_at,
        )

        removed = await client.patch(
            f"/tenants/{tenant_id}",
            headers=auth_headers,
            json={"custom_domain": None},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["custom_domain"] is None

        health = await client.get(f"/tenants/{tenant_id}/domain/health", headers=auth_headers)
        assert health.status_code == 200, health.text
        body = health.json()
        assert body["status"] == "not_configured"
        assert body["domain"] is None
        assert body["verified"] is False
        assert [entry["event_type"] for entry in body["history"]] == [
            "removed",
            "verified",
        ]
        assert body["history"][0]["domain"] == domain
        assert body["expiry"]["domain_expires_at"] is None
        assert body["expiry"]["domain_state"] == "unknown"

        rows = await db_session.execute(
            text("SELECT event_type FROM tenant_domain_events WHERE tenant_id = :tenant ORDER BY checked_at"),
            {"tenant": tenant_id},
        )
        assert [row[0] for row in rows.all()] == ["verified", "removed"]

    async def test_health_surfaces_stale_unhealthy_and_expiry_warnings(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
    ):
        owner_id = await _user_id(db_session, auth_headers)
        now = datetime.now(timezone.utc)
        domain = _domain()
        tenant_id = await _insert_tenant(
            db_session,
            owner_id=owner_id,
            domain=domain,
            verified_at=now - timedelta(days=40),
        )
        await _insert_event(
            db_session,
            tenant_id=tenant_id,
            domain=domain,
            event_type="verified",
            checked_at=now - timedelta(days=40),
        )

        stale = await client.get(f"/tenants/{tenant_id}/domain/health", headers=auth_headers)
        assert stale.status_code == 200, stale.text
        assert stale.json()["status"] == "stale"
        assert stale.json()["warnings"][0]["code"] == "verification_stale"

        await db_session.execute(
            text(
                "UPDATE tenants SET domain_expires_at = :domain_expires, "
                "domain_certificate_expires_at = :certificate_expires "
                "WHERE id = :tenant"
            ),
            {
                "tenant": tenant_id,
                "domain_expires": now + timedelta(days=7),
                "certificate_expires": now - timedelta(days=1),
            },
        )
        await _insert_event(
            db_session,
            tenant_id=tenant_id,
            domain=domain,
            event_type="error",
            checked_at=now,
            error_class="dns_unavailable",
        )
        await db_session.commit()

        unhealthy = await client.get(f"/tenants/{tenant_id}/domain/health", headers=auth_headers)
        assert unhealthy.status_code == 200, unhealthy.text
        body = unhealthy.json()
        assert body["status"] == "unhealthy"
        codes = {warning["code"] for warning in body["warnings"]}
        assert "verification_unhealthy" in codes
        assert "domain_expiring" in codes
        assert "certificate_expired" in codes
        assert body["expiry"]["domain_state"] == "expiring"
        assert body["expiry"]["certificate_state"] == "expired"

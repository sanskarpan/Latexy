"""Tenant billing/seat utilization: math, thresholds, audit and privacy."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_cache_client
from app.database.models import UsageAnalytics
from app.services.tenant_billing_service import (
    MIN_CONVERSION_COHORT,
    SUBSCRIPTION_UNAVAILABLE_REASON,
    TEAM_SEAT_UNAVAILABLE_REASON,
    UPGRADE_CTA_THRESHOLD_PERCENT,
    UPGRADE_INTENT_ACTION,
    build_upgrade_prompt,
    compute_invite_conversion,
    compute_seat_usage,
)
from test.test_admin_control_plane_api import _create_session, _create_user


def _uid() -> str:
    return str(uuid.uuid4())


async def _create_tenant(
    db: AsyncSession,
    owner_id: str,
    *,
    plan_id: str = "agency",
    max_members: int = 50,
    active: bool = True,
) -> str:
    tenant_id = _uid()
    await db.execute(
        text(
            "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members, active) "
            "VALUES (:id, :slug, :name, :owner, :plan, :max_members, :active)"
        ),
        {
            "id": tenant_id,
            "slug": f"test-billing-{tenant_id.replace('-', '')[:20]}",
            "name": "Test billing tenant",
            "owner": owner_id,
            "plan": plan_id,
            "max_members": max_members,
            "active": active,
        },
    )
    await db.execute(
        text(
            "INSERT INTO tenant_members (tenant_id, user_id, role) "
            "VALUES (:tenant, :user, 'admin')"
        ),
        {"tenant": tenant_id, "user": owner_id},
    )
    await db.commit()
    return tenant_id


async def _add_member(
    db: AsyncSession, tenant_id: str, user_id: str, role: str = "member"
) -> None:
    await db.execute(
        text(
            "INSERT INTO tenant_members (tenant_id, user_id, role) "
            "VALUES (:tenant, :user, :role)"
        ),
        {"tenant": tenant_id, "user": user_id, "role": role},
    )
    await db.commit()


async def _set_seat_limit(db: AsyncSession, tenant_id: str, max_members: int) -> None:
    await db.execute(
        text("UPDATE tenants SET max_members = :max_members WHERE id = :id"),
        {"id": tenant_id, "max_members": max_members},
    )
    await db.commit()


async def _set_user_subscription(
    db: AsyncSession, user_id: str, *, plan_id: str = "team", status: str = "active"
) -> str:
    subscription_id = _uid()
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, provider, provider_subscription_id, "
            "plan_id, status, current_period_start, current_period_end) "
            "VALUES (:id, :user, 'dodo', :provider_sub, :plan, :status, :start, :end)"
        ),
        {
            "id": subscription_id,
            "user": user_id,
            "provider_sub": f"test_sub_{uuid.uuid4().hex[:16]}",
            "plan": plan_id,
            "status": status,
            "start": datetime.now(timezone.utc) - timedelta(days=2),
            "end": datetime.now(timezone.utc) + timedelta(days=28),
        },
    )
    await db.commit()
    return subscription_id


async def _put_invite(tenant_id: str, email: str) -> tuple[object, str]:
    token = secrets.token_urlsafe(16)
    redis = await get_redis_cache_client()
    await redis.set(
        f"tenant_invite:{token}",
        json.dumps(
            {
                "tenant_id": tenant_id,
                "role": "member",
                "email": email,
                "cohort_id": None,
            },
            separators=(",", ":"),
        ),
        ex=600,
    )
    return redis, token


@pytest.fixture
async def billing_context(db_session: AsyncSession):
    """Owner/admin/member/outsider plus a tenant with enough members for stats."""

    owner_id, owner_email = await _create_user(
        db_session, plan="team", name="Billing Owner"
    )
    admin_id, admin_email = await _create_user(db_session, name="Billing Admin")
    member_ids: list[str] = []
    member_emails: list[str] = []
    for index in range(3):
        member_id, member_email = await _create_user(
            db_session, name=f"Billing Member {index}"
        )
        member_ids.append(member_id)
        member_emails.append(member_email)
    outsider_id, outsider_email = await _create_user(
        db_session, name="Billing Outsider"
    )

    tenant_id = await _create_tenant(db_session, owner_id)
    await _add_member(db_session, tenant_id, admin_id, "admin")
    for member_id in member_ids:
        await _add_member(db_session, tenant_id, member_id, "member")

    headers = {
        "owner": {"Authorization": f"Bearer {await _create_session(db_session, owner_id)}"},
        "admin": {"Authorization": f"Bearer {await _create_session(db_session, admin_id)}"},
        "member": {"Authorization": f"Bearer {await _create_session(db_session, member_ids[0])}"},
        "outsider": {"Authorization": f"Bearer {await _create_session(db_session, outsider_id)}"},
    }
    redis_keys: list[str] = []
    yield {
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "admin_id": admin_id,
        "member_ids": member_ids,
        "outsider_id": outsider_id,
        "owner_email": owner_email,
        "admin_email": admin_email,
        "member_emails": member_emails,
        "outsider_email": outsider_email,
        "headers": headers,
        "redis_keys": redis_keys,
    }

    redis = await get_redis_cache_client()
    for key in redis_keys:
        await redis.delete(key)


# ── Pure seat arithmetic ─────────────────────────────────────────────────────


def test_seat_math_uses_active_plus_pending_invites():
    seats = compute_seat_usage(active=3, invited=2, max_seats=50)

    assert seats == {
        "active": 3,
        "invited": 2,
        "available": 45,
        "used": 5,
        "max": 50,
        "utilization_percent": 10.0,
        "over_capacity": 0,
        "invited_available": True,
        "invited_reason": None,
        "basis": "active_and_invited",
    }
    assert seats["active"] + seats["invited"] + seats["available"] == seats["max"]


def test_seat_math_marks_over_capacity_and_invitation_outage():
    over = compute_seat_usage(active=49, invited=3, max_seats=50)
    assert over["used"] == 52
    assert over["available"] == 0
    assert over["over_capacity"] == 2

    degraded = compute_seat_usage(active=3, invited=None, max_seats=50)
    assert degraded["invited"] is None
    assert degraded["used"] == 3
    assert degraded["available"] == 47
    assert degraded["invited_available"] is False
    assert degraded["basis"] == "active_only"
    assert degraded["invited_reason"] == "invitation_store_unavailable"


def test_invite_conversion_suppresses_small_cohorts_and_unavailable_store():
    suppressed = compute_invite_conversion(accepted_members=2, invited=1)
    assert suppressed["available"] is False
    assert suppressed["reason"] == "suppressed_small_cohort"
    assert suppressed["accepted"] is None
    assert suppressed["invited"] is None
    assert suppressed["minimum_cohort_size"] == MIN_CONVERSION_COHORT

    published = compute_invite_conversion(accepted_members=5, invited=1)
    assert published["available"] is True
    assert published["accepted"] == 5
    assert published["invited"] == 1
    assert published["conversion_percent"] == 83.33

    unavailable = compute_invite_conversion(accepted_members=5, invited=None)
    assert unavailable["available"] is False
    assert unavailable["reason"] == "invitation_store_unavailable"


def test_upgrade_threshold_target_and_server_side_reasons():
    below = build_upgrade_prompt(
        plan_id="agency", used_seats=39, max_seats=50, tenant_active=True
    )
    assert below["cta_visible"] is False
    assert below["reason"] == "below_threshold"
    assert below["threshold_percent"] == UPGRADE_CTA_THRESHOLD_PERCENT

    at_threshold = build_upgrade_prompt(
        plan_id="agency", used_seats=40, max_seats=50, tenant_active=True
    )
    assert at_threshold["cta_visible"] is True
    assert at_threshold["threshold_seats"] == 40
    assert at_threshold["target_plan_id"] == "university"
    assert at_threshold["cta_label"] == "Upgrade to University"
    assert at_threshold["reason"] == "seat_threshold_reached"

    top_plan = build_upgrade_prompt(
        plan_id="university", used_seats=200, max_seats=200, tenant_active=True
    )
    assert top_plan["cta_visible"] is False
    assert top_plan["target_plan_id"] is None
    assert top_plan["reason"] == "no_higher_tenant_plan"

    inactive = build_upgrade_prompt(
        plan_id="agency", used_seats=50, max_seats=50, tenant_active=False
    )
    assert inactive["cta_visible"] is False
    assert inactive["reason"] == "tenant_inactive"


# ── Read-only billing view ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_billing_view_is_owner_admin_only_and_tenant_isolated(
    client: AsyncClient, billing_context: dict
):
    tenant_id = billing_context["tenant_id"]

    owner = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["owner"]
    )
    assert owner.status_code == 200, owner.text
    admin = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["admin"]
    )
    assert admin.status_code == 200, admin.text

    member = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["member"]
    )
    assert member.status_code == 403
    outsider = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["outsider"]
    )
    assert outsider.status_code == 403
    assert outsider.json()["detail"] == "Access denied: owner or admin required"


@pytest.mark.asyncio
async def test_billing_view_reports_plan_seats_and_explicit_unavailable_links(
    client: AsyncClient, billing_context: dict
):
    response = await client.get(
        f"/tenants/{billing_context['tenant_id']}/billing",
        headers=billing_context["headers"]["owner"],
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["plan"] == {
        "plan_id": "agency",
        "name": "Agency",
        "max_seats": 50,
        "tenant_status": "active",
        "status_source": "tenant_record",
    }
    assert body["seats"]["active"] == 5
    assert body["seats"]["invited"] == 0
    assert body["seats"]["available"] == 45
    assert body["seats"]["used"] == 5
    assert body["seats"]["utilization_percent"] == 10.0

    # No guessed subscription link: an owner-owned subscription is not exposed.
    assert body["subscription"]["available"] is False
    assert body["subscription"]["status"] is None
    assert body["subscription"]["renewal_at"] is None
    assert body["subscription"]["reason"] == SUBSCRIPTION_UNAVAILABLE_REASON
    assert body["mapping"]["subscription"]["status"] == "unavailable"
    assert body["mapping"]["subscription"]["reason"] == SUBSCRIPTION_UNAVAILABLE_REASON
    assert body["mapping"]["team_seats"]["status"] == "unavailable"
    assert body["mapping"]["team_seats"]["reason"] == TEAM_SEAT_UNAVAILABLE_REASON


@pytest.mark.asyncio
async def test_pending_invites_and_conversion_are_aggregate_only(
    client: AsyncClient, billing_context: dict, db_session: AsyncSession
):
    tenant_id = billing_context["tenant_id"]
    target_email = "invitee-" + uuid.uuid4().hex[:8] + "@example.com"
    redis, token = await _put_invite(tenant_id, target_email)
    billing_context["redis_keys"].append(f"tenant_invite:{token}")
    try:
        response = await client.get(
            f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["owner"]
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # 5 active members, 1 pending invite.
        assert body["seats"]["active"] == 5
        assert body["seats"]["invited"] == 1
        assert body["seats"]["used"] == 6
        assert body["seats"]["available"] == 44

        # 4 accepted invitees (owner excluded) + 1 pending = cohort of 5.
        assert body["invite_conversion"]["available"] is True
        assert body["invite_conversion"]["accepted"] == 4
        assert body["invite_conversion"]["invited"] == 1
        assert body["invite_conversion"]["conversion_percent"] == 80.0
        assert body["invite_conversion"]["minimum_cohort_size"] == MIN_CONVERSION_COHORT

        raw = response.text
        assert target_email not in raw
        assert billing_context["owner_email"] not in raw
        assert billing_context["admin_email"] not in raw
        for email in billing_context["member_emails"]:
            assert email not in raw
        for forbidden in (
            "member_email",
            "user_id",
            "provider_subscription_id",
            "provider_customer_id",
            "card_number",
            "payment_method",
        ):
            assert forbidden not in raw
    finally:
        await redis.delete(f"tenant_invite:{token}")


@pytest.mark.asyncio
async def test_small_invite_cohort_conversion_is_suppressed_without_subtraction(
    client: AsyncClient, billing_context: dict, db_session: AsyncSession
):
    tenant_id = billing_context["tenant_id"]
    # Drop to the owner + admin + one member, so accepted invitees = 2 and
    # pending = 1 keeps the cohort below the five-user floor.
    await db_session.execute(
        text(
            "DELETE FROM tenant_members WHERE tenant_id = :tenant AND user_id = ANY(:users)"
        ),
        {"tenant": tenant_id, "users": billing_context["member_ids"][1:]},
    )
    await db_session.commit()

    redis, token = await _put_invite(tenant_id, f"invitee-{uuid.uuid4().hex[:8]}@example.com")
    billing_context["redis_keys"].append(f"tenant_invite:{token}")
    try:
        response = await client.get(
            f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["owner"]
        )
        assert response.status_code == 200, response.text
        conversion = response.json()["invite_conversion"]
        assert conversion["available"] is False
        assert conversion["reason"] == "suppressed_small_cohort"
        assert conversion["accepted"] is None
        assert conversion["invited"] is None
        assert conversion["conversion_percent"] is None
    finally:
        await redis.delete(f"tenant_invite:{token}")


@pytest.mark.asyncio
async def test_invitation_store_failure_does_not_block_billing_or_management(
    client: AsyncClient, billing_context: dict, monkeypatch
):
    tenant_id = billing_context["tenant_id"]
    monkeypatch.setattr(
        "app.services.tenant_billing_service.get_redis_cache_client",
        AsyncMock(side_effect=RuntimeError("redis down")),
    )

    billing = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["owner"]
    )
    assert billing.status_code == 200, billing.text
    seats = billing.json()["seats"]
    assert seats["invited"] is None
    assert seats["invited_available"] is False
    assert seats["basis"] == "active_only"
    assert seats["active"] == 5

    # Tenant management remains available while the billing sub-view degrades.
    members = await client.get(
        f"/tenants/{tenant_id}/members", headers=billing_context["headers"]["owner"]
    )
    assert members.status_code == 200
    assert len(members.json()) == 5


# ── Upgrade CTA audit ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upgrade_cta_click_is_audited_without_billing_credentials(
    client: AsyncClient, billing_context: dict, db_session: AsyncSession
):
    tenant_id = billing_context["tenant_id"]
    await _set_seat_limit(db_session, tenant_id, 5)

    billing = await client.get(
        f"/tenants/{tenant_id}/billing", headers=billing_context["headers"]["owner"]
    )
    assert billing.status_code == 200, billing.text
    upgrade = billing.json()["upgrade"]
    assert upgrade["cta_visible"] is True
    assert upgrade["target_plan_id"] == "university"
    assert upgrade["utilization_percent"] == 100.0

    click = await client.post(
        f"/tenants/{tenant_id}/billing/upgrade-intent",
        headers=billing_context["headers"]["owner"],
        json={"target_plan_id": "university"},
    )
    assert click.status_code == 200, click.text
    body = click.json()
    assert body["recorded"] is True
    assert body["action"] == UPGRADE_INTENT_ACTION
    assert body["target_plan_id"] == "university"
    assert body["tenant_id"] == tenant_id

    rows = (
        await db_session.execute(
            select(UsageAnalytics).where(
                UsageAnalytics.action == UPGRADE_INTENT_ACTION,
                UsageAnalytics.event_metadata["tenant_id"].as_string() == tenant_id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    audit = rows[0]
    assert audit.user_id == billing_context["owner_id"]
    assert audit.resource_type == "tenant"
    assert audit.device_fingerprint is None
    assert audit.ip_address is None
    assert audit.user_agent is None
    assert audit.event_metadata == {
        "event_version": 1,
        "tenant_id": tenant_id,
        "plan_id": "agency",
        "target_plan_id": "university",
        "max_seats": 5,
        "used_seats": 5,
        "active_seats": 5,
        "invited_seats": 0,
        "utilization_percent": 100.0,
        "threshold_percent": 80,
        "seat_basis": "active_and_invited",
        "source": "tenant_billing_view",
    }
    serialized = json.dumps(audit.event_metadata)
    for email in (
        billing_context["owner_email"],
        billing_context["admin_email"],
        *billing_context["member_emails"],
    ):
        assert email not in serialized

    # A client cannot smuggle card/payment fields through the audited action.
    rejected = await client.post(
        f"/tenants/{tenant_id}/billing/upgrade-intent",
        headers=billing_context["headers"]["owner"],
        json={"card_number": "4242424242424242", "cvc": "123"},
    )
    assert rejected.status_code == 422
    count = (
        await db_session.execute(
            select(UsageAnalytics).where(
                UsageAnalytics.action == UPGRADE_INTENT_ACTION,
                UsageAnalytics.event_metadata["tenant_id"].as_string() == tenant_id,
            )
        )
    ).scalars().all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_upgrade_intent_requires_threshold_and_owner_or_admin(
    client: AsyncClient, billing_context: dict, db_session: AsyncSession
):
    tenant_id = billing_context["tenant_id"]

    below = await client.post(
        f"/tenants/{tenant_id}/billing/upgrade-intent",
        headers=billing_context["headers"]["owner"],
        json={},
    )
    assert below.status_code == 409

    outsider = await client.post(
        f"/tenants/{tenant_id}/billing/upgrade-intent",
        headers=billing_context["headers"]["outsider"],
        json={},
    )
    assert outsider.status_code == 403

    member = await client.post(
        f"/tenants/{tenant_id}/billing/upgrade-intent",
        headers=billing_context["headers"]["member"],
        json={},
    )
    assert member.status_code == 403

    no_audit = (
        await db_session.execute(
            select(UsageAnalytics).where(
                UsageAnalytics.action == UPGRADE_INTENT_ACTION,
                UsageAnalytics.event_metadata["tenant_id"].as_string() == tenant_id,
            )
        )
    ).scalars().all()
    assert no_audit == []


# ── No migration / no guessed link ──────────────────────────────────────────


def test_tenant_billing_adds_no_migration_or_new_tables():
    backend = Path(__file__).resolve().parent.parent
    service = (backend / "app" / "services" / "tenant_billing_service.py").read_text(
        encoding="utf-8"
    )
    router = (backend / "app" / "api" / "tenant_billing_routes.py").read_text(
        encoding="utf-8"
    )
    for source in (service, router):
        assert "alembic" not in source.lower()
        assert "create_table" not in source
        assert "add_column" not in source

    versions = backend / "alembic" / "versions"
    assert not any(
        "tenant_billing" in path.read_text(encoding="utf-8").lower()
        for path in versions.glob("*.py")
    )

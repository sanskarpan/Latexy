"""Real PostgreSQL/Redis tenant admission and recovery through HTTP routes.

Runs in ordinary Backend Tests with its existing disposable services, without an
opt-in skip. DNS verification is seeded as prior state; no DNS, email or other
external-provider acceptance is claimed.
"""
import os
from test.test_admin_control_plane_api import _create_session, _create_user
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text

from app.core.config import settings
from app.core.redis import get_redis_cache_client
from app.database.models import Tenant, TenantMember, User, Workspace
from app.middleware.tenant_middleware import invalidate_tenant_cache
from app.services.entitlement_service import entitlement_service

_CASE_FEATURES = {
    "test_f10_denial_preserves_invitation_and_membership_removal_then_recovers": "f10",
    "test_f11_denial_preserves_verified_domain_and_allows_removal_then_new_admission": "f11",
}


async def _switch(db, axis, key, enabled):
    if axis == "global":
        await entitlement_service.set_kill_switch(key, enabled, db)
    elif axis == "role":
        await entitlement_service.set_role_cell("user", key, enabled, db)
    else:
        await entitlement_service.set_matrix_cell("team", key, enabled, db)


async def _invite(client, context, account):
    response = await client.post(
        f"/tenants/{context['tenant_id']}/members/invite",
        headers=context["owner"]["headers"], json={"email": account["email"], "role": "member"},
    )
    assert response.status_code == 201, response.text
    token = parse_qs(urlsplit(response.json()["invite_preview_url"]).query)["token"][0]
    context["invitation_tokens"].append(token)
    return token


async def _membership(db, tenant_id):
    rows = await db.execute(select(TenantMember.user_id, TenantMember.role).where(TenantMember.tenant_id == tenant_id))
    return dict(rows.all())


async def _tenant_state(db, tenant_id):
    row = (await db.execute(select(
        Tenant.custom_domain, Tenant.domain_verified_at, Tenant.active, Tenant.name,
    ).where(Tenant.id == tenant_id))).one()
    return tuple(row)


@pytest.fixture
async def tenant_context(client, db_session, monkeypatch, request, axis):
    """Restore the selected policy cell; remove only owned rows/cache keys."""
    assert settings.REDIS_CACHE_URL == os.environ["TEST_REDIS_CACHE_URL"]
    assert urlsplit(settings.REDIS_CACHE_URL).path == "/14"
    monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    key = _CASE_FEATURES[request.function.__name__]
    state = await entitlement_service.get_state()
    if axis == "global":
        original_enabled = state["kill_switches"][key]
    elif axis == "role":
        original_enabled = state["role_matrix"]["user"][key]
    else:
        original_enabled = state["matrix"]["team"][key]
    context = {"invitation_tokens": [], "domains": set()}
    accounts = []
    try:
        # Other policy cells remain untouched; normal CI seeds their baseline.
        if not original_enabled:
            await _switch(db_session, axis, key, True)
        for label in ("owner", "member", "invitee"):
            user_id, email = await _create_user(db_session, role="user", plan="team", name=f"Tenant policy {label}")
            accounts.append(user_id)
            token = await _create_session(db_session, user_id)
            context[label] = {"id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}
        context["slug"] = "test-policy-" + uuid4().hex[:16]
        created = await client.post("/tenants", headers=context["owner"]["headers"], json={
            "name": "Tenant policy acceptance", "slug": context["slug"],
        })
        assert created.status_code == 201, created.text
        context["tenant_id"] = created.json()["id"]
        token = await _invite(client, context, context["member"])
        accepted = await client.post(f"/tenants/invitations/{token}/accept", headers=context["member"]["headers"])
        assert accepted.status_code == 200, accepted.text
        yield context
    finally:
        try:
            await db_session.rollback()
            if accounts:
                await db_session.execute(text('DELETE FROM session WHERE "userId" = ANY(:ids)'), {"ids": accounts})
                await db_session.execute(delete(User).where(User.id.in_(accounts)))
                await db_session.commit()
        finally:
            try:
                redis = await get_redis_cache_client()
                for token in context["invitation_tokens"]:
                    await redis.delete(f"tenant_invite:{token}")
                if "slug" in context:
                    await invalidate_tenant_cache(slug=context["slug"])
                for domain in context["domains"]:
                    await invalidate_tenant_cache(slug=context["slug"], previous_domain=domain)
            finally:
                # Policy restoration must still run if row/cache cleanup fails.
                await db_session.rollback()
                await _switch(db_session, axis, key, original_enabled)


@pytest.mark.parametrize("axis", ["global", "role", "plan_family"])
async def test_f10_denial_preserves_invitation_and_membership_removal_then_recovers(
    client, db_session, tenant_context, axis,
):
    context = tenant_context
    tenant_id, owner, member, invitee = (context[key] for key in ("tenant_id", "owner", "member", "invitee"))
    token = await _invite(client, context, invitee)
    redis = await get_redis_cache_client()
    invitation = await redis.get(f"tenant_invite:{token}")
    assert invitation is not None and await redis.ttl(f"tenant_invite:{token}") > 0
    original_state = await _tenant_state(db_session, tenant_id)
    original_members = await _membership(db_session, tenant_id)
    assert original_members == {owner["id"]: "admin", member["id"]: "member"}

    await _switch(db_session, axis, "f10", False)
    features = await client.get("/config/entitlements", headers=invitee["headers"])
    assert features.status_code == 200 and features.json()["features"]["f10"] is False
    denied = await client.post(f"/tenants/invitations/{token}/accept", headers=invitee["headers"])
    assert denied.status_code == 403 and "f10" in denied.text
    assert await redis.get(f"tenant_invite:{token}") == invitation
    assert await redis.ttl(f"tenant_invite:{token}") > 0
    assert await _membership(db_session, tenant_id) == original_members
    assert await _tenant_state(db_session, tenant_id) == original_state

    blocked_invite = await client.post(f"/tenants/{tenant_id}/members/invite", headers=owner["headers"], json={"email": invitee["email"]})
    assert blocked_invite.status_code == 403 and "f10" in blocked_invite.text
    blocked_cohort = await client.post(f"/tenants/{tenant_id}/cohorts", headers=owner["headers"], json={"name": "Blocked cohort"})
    assert blocked_cohort.status_code == 403 and "f10" in blocked_cohort.text
    assert await db_session.scalar(select(func.count()).select_from(Workspace).where(Workspace.tenant_id == tenant_id)) == 0
    members = await client.get(f"/tenants/{tenant_id}/members", headers=owner["headers"])
    assert members.status_code == 200 and {row["user_id"] for row in members.json()} == set(original_members)
    removed = await client.delete(f"/tenants/{tenant_id}/members/{member['id']}", headers=owner["headers"])
    assert removed.status_code == 204, removed.text
    assert await _membership(db_session, tenant_id) == {owner["id"]: "admin"}
    assert await _tenant_state(db_session, tenant_id) == original_state

    await _switch(db_session, axis, "f10", True)
    accepted = await client.post(f"/tenants/invitations/{token}/accept", headers=invitee["headers"])
    assert accepted.status_code == 200 and accepted.json()["user_id"] == invitee["id"]
    assert await redis.get(f"tenant_invite:{token}") is None
    assert await _membership(db_session, tenant_id) == {owner["id"]: "admin", invitee["id"]: "member"}
    replay = await client.post(f"/tenants/invitations/{token}/accept", headers=invitee["headers"])
    assert replay.status_code == 404


@pytest.mark.parametrize("axis", ["global", "role", "plan_family"])
async def test_f11_denial_preserves_verified_domain_and_allows_removal_then_new_admission(
    client, db_session, tenant_context, axis,
):
    context = tenant_context
    tenant_id, owner = context["tenant_id"], context["owner"]
    domain, replacement = ("test-" + uuid4().hex + ".example.test" for _ in range(2))
    context["domains"].update((domain, replacement))
    assigned = await client.patch(f"/tenants/{tenant_id}", headers=owner["headers"], json={"custom_domain": domain})
    assert assigned.status_code == 200, assigned.text
    # Simulate an already-verified hostname without contacting DNS/TLS providers.
    await db_session.execute(text("UPDATE tenants SET domain_verified_at=CURRENT_TIMESTAMP WHERE id=:id"), {"id": tenant_id})
    await db_session.commit()
    original_state = await _tenant_state(db_session, tenant_id)
    original_members = await _membership(db_session, tenant_id)
    resolved = await client.get("/tenants/resolve-host", params={"host": domain})
    assert resolved.status_code == 200 and resolved.json()["tenant"]["id"] == tenant_id

    await _switch(db_session, axis, "f11", False)
    features = await client.get("/config/entitlements", headers=owner["headers"])
    assert features.status_code == 200 and features.json()["features"]["f11"] is False
    denied = await client.patch(f"/tenants/{tenant_id}", headers=owner["headers"], json={"custom_domain": replacement})
    assert denied.status_code == 403 and "f11" in denied.text
    assert await _tenant_state(db_session, tenant_id) == original_state
    assert await _membership(db_session, tenant_id) == original_members
    listed = await client.get("/tenants/my", headers=owner["headers"])
    assert listed.status_code == 200
    owned = next(row for row in listed.json() if row["id"] == tenant_id)
    assert owned["custom_domain"] == domain and owned["domain_verified"] is True

    removed = await client.patch(f"/tenants/{tenant_id}", headers=owner["headers"], json={"custom_domain": None})
    assert removed.status_code == 200 and removed.json()["custom_domain"] is None
    assert removed.json()["domain_verified"] is False
    assert (await _tenant_state(db_session, tenant_id))[:2] == (None, None)
    after_removal = await client.get("/tenants/resolve-host", params={"host": domain})
    assert after_removal.status_code == 200 and after_removal.json()["tenant"] is None
    assert await _membership(db_session, tenant_id) == original_members

    await _switch(db_session, axis, "f11", True)
    recovered = await client.patch(f"/tenants/{tenant_id}", headers=owner["headers"], json={"custom_domain": replacement})
    assert recovered.status_code == 200 and recovered.json()["custom_domain"] == replacement
    assert recovered.json()["domain_verified"] is False
    unverified = await client.get("/tenants/resolve-host", params={"host": replacement})
    assert unverified.status_code == 200 and unverified.json()["tenant"] is None
    assert await _membership(db_session, tenant_id) == original_members

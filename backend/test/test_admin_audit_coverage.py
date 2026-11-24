"""Audit coverage and flag/entitlement history tests (#2134, #2135).

The append-only audit log and UI shipped in #2178. These tests close the two
remaining acceptance gaps: every mutating admin route must have an audit path,
and every flag/kill-switch/plan-cell/role-cell mutation must produce exactly one
immutable history row with before/after values.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import (
    admin_alert_routes,
    admin_billing_reconciliation_routes,
    admin_control_routes,
    admin_operations_routes,
    admin_routes,
    plan_catalog_routes,
)

from ._entitlement_reset import reset_entitlements_baseline

# ── Route coverage ───────────────────────────────────────────────────────────

AUDITED_SERVICE_CALLS = (
    "admin_user_service.",
    "admin_billing_service.",
    "admin_alert_service.",
    "plan_catalog_service.",
    "entitlement_service.set_",
)

# POST endpoints that are read-only previews, not mutations.
READ_ONLY_POSTS = {("/admin/alerts/dry-run", "POST")}

# Endpoints that delegate to a local helper which performs the audit write.
AUDITED_HELPERS = {
    ("/admin/users/{user_id}/reveal-pii", "POST"): "admin_user_service.reveal_user_pii",
    ("/admin/users/{user_id}/pii/reveal", "POST"): "admin_user_service.reveal_user_pii",
    ("/admin/billing/reconciliation/{event_id}/replay", "POST"): "admin_billing_service.replay_webhook",
    ("/admin/billing/webhooks/{event_id}/replay", "POST"): "admin_billing_service.replay_webhook",
    ("/admin/users/{user_id}/api-keys/revoke", "POST"): "admin_user_service.revoke_user_api_keys",
}

ADMIN_ROUTERS = (
    admin_routes.router,
    admin_control_routes.router,
    admin_alert_routes.router,
    admin_billing_reconciliation_routes.router,
    admin_operations_routes.router,
    plan_catalog_routes.router,
)


def _mutating_admin_routes() -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    for router in ADMIN_ROUTERS:
        for route in router.routes:
            path = getattr(route, "path", "")
            methods = set(getattr(route, "methods", None) or set())
            for method in sorted(methods & {"POST", "PUT", "PATCH", "DELETE"}):
                if path.startswith("/admin/"):
                    rows.append((path, method, route.endpoint))
    return rows


def test_every_mutating_admin_route_has_audit_evidence():
    missing: list[tuple[str, str, str]] = []
    for path, method, endpoint in _mutating_admin_routes():
        if (path, method) in READ_ONLY_POSTS:
            continue
        source = inspect.getsource(endpoint)
        covered = (
            "record_admin_audit" in source
            or any(call in source for call in AUDITED_SERVICE_CALLS)
            or (path, method) in AUDITED_HELPERS
        )
        if not covered:
            missing.append((path, method, endpoint.__name__))
    assert not missing, f"Mutating admin routes without audit evidence: {missing}"


def test_audit_helper_allowlist_has_no_stale_entries():
    routes = {(path, method) for path, method, _ in _mutating_admin_routes()}
    stale = set(AUDITED_HELPERS) - routes
    assert not stale, f"Stale audit helper entries: {sorted(stale)}"


# ── Mutation history rows ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def _reset():
    yield
    await reset_entitlements_baseline()


async def _admin_headers(db: AsyncSession) -> dict:
    user_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, 'admin', true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": f"audit_{user_id.replace('-', '')}@example.com", "name": "Audit Admin"},
    )
    token = f"audit_sess_{uuid.uuid4().hex}"
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


async def _history(
    client: AsyncClient, headers: dict, *, action: str, target_id: str
) -> list[dict]:
    resp = await client.get(
        "/admin/audit",
        params={"action": action, "target_id": target_id, "limit": 50},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _baseline(db: AsyncSession) -> None:
    """Normalize the four editable states so the mutation is a real true->false change."""
    from app.services.entitlement_service import entitlement_service
    from app.services.feature_flag_service import feature_flag_service

    await feature_flag_service.update_flag("upgrade_ctas", True, db, commit=False)
    await entitlement_service.set_kill_switch("cover_letters", True, db, commit=False)
    await entitlement_service.set_matrix_cell("free", "cover_letters", True, db, commit=False)
    await entitlement_service.set_role_cell("support", "b03", True, db, commit=False)
    await db.commit()


@pytest.mark.parametrize(
    ("action", "target_id", "method", "path", "payload"),
    [
        (
            "feature_flag.update",
            "upgrade_ctas",
            "PATCH",
            "/admin/feature-flags/upgrade_ctas",
            {"enabled": False},
        ),
        (
            "entitlement.kill_switch.update",
            "cover_letters",
            "PATCH",
            "/admin/entitlements/kill-switch/cover_letters",
            {"enabled": False},
        ),
        (
            "entitlement.matrix.update",
            "free:cover_letters",
            "PATCH",
            "/admin/entitlements/matrix",
            {"plan_family": "free", "feature_key": "cover_letters", "enabled": False},
        ),
        (
            "entitlement.role.update",
            "support:b03",
            "PATCH",
            "/admin/entitlements/roles",
            {"role": "support", "feature_key": "b03", "enabled": False},
        ),
    ],
)
async def test_mutation_writes_exactly_one_history_row(
    client: AsyncClient,
    db_session: AsyncSession,
    action: str,
    target_id: str,
    method: str,
    path: str,
    payload: dict,
):
    headers = await _admin_headers(db_session)
    await _baseline(db_session)
    before = await _history(client, headers, action=action, target_id=target_id)

    resp = await client.request(method, path, json=payload, headers=headers)
    assert resp.status_code == 200, resp.text

    after = await _history(client, headers, action=action, target_id=target_id)
    assert len(after) == len(before) + 1, (before, after)
    row = after[0]
    assert row["action"] == action
    assert row["target_id"] == target_id
    assert row["before"] == {"enabled": True}
    assert row["after"] == {"enabled": False}
    assert row["reason"] is None or isinstance(row["reason"], str)
    assert "authorization" not in str(row).lower()
    assert "password" not in str(row).lower()

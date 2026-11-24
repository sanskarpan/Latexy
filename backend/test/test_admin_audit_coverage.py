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
from app.database.models import AdminAuditLog
from app.services.admin_audit_service import AdminActor, record_admin_audit

from ._entitlement_reset import reset_entitlements_baseline

REASON = "Disable during incident 2135"

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
        "/admin/change-history",
        params={"action": action, "target_id": target_id, "limit": 50},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["read_only"] is True
    assert set(body["target_types"]) == {
        "feature_flag",
        "feature_key",
        "plan_feature",
        "role_feature",
    }
    return body["items"]


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
            {"enabled": False, "reason": REASON},
        ),
        (
            "entitlement.kill_switch.update",
            "cover_letters",
            "PATCH",
            "/admin/entitlements/kill-switch/cover_letters",
            {"enabled": False, "reason": REASON},
        ),
        (
            "entitlement.matrix.update",
            "free:cover_letters",
            "PATCH",
            "/admin/entitlements/matrix",
            {
                "plan_family": "free",
                "feature_key": "cover_letters",
                "enabled": False,
                "reason": REASON,
            },
        ),
        (
            "entitlement.role.update",
            "support:b03",
            "PATCH",
            "/admin/entitlements/roles",
            {"role": "support", "feature_key": "b03", "enabled": False, "reason": REASON},
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
    assert row["reason"] == REASON
    assert "authorization" not in str(row).lower()
    assert "password" not in str(row).lower()


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PATCH", "/admin/feature-flags/upgrade_ctas", {"enabled": False}),
        ("PATCH", "/admin/entitlements/kill-switch/cover_letters", {"enabled": False}),
        (
            "PATCH",
            "/admin/entitlements/matrix",
            {"plan_family": "free", "feature_key": "cover_letters", "enabled": False},
        ),
        (
            "PATCH",
            "/admin/entitlements/roles",
            {"role": "support", "feature_key": "b03", "enabled": False},
        ),
    ],
)
@pytest.mark.parametrize("reason", [None, "  x  ", "x" * 1001])
async def test_mutation_rejects_missing_or_out_of_bounds_reason(
    client: AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    payload: dict,
    reason: str | None,
):
    headers = await _admin_headers(db_session)
    body = dict(payload)
    if reason is not None:
        body["reason"] = reason
    resp = await client.request(method, path, json=body, headers=headers)
    assert resp.status_code == 422, resp.text


async def test_reason_is_trimmed_before_persisting(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    await _baseline(db_session)
    resp = await client.patch(
        "/admin/feature-flags/upgrade_ctas",
        json={"enabled": False, "reason": f"  {REASON}  "},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = await _history(
        client, headers, action="feature_flag.update", target_id="upgrade_ctas"
    )
    assert rows[0]["reason"] == REASON


async def test_change_history_is_admin_only(
    client: AsyncClient, db_session: AsyncSession, auth_headers: dict
):
    anonymous = await client.get("/admin/change-history")
    assert anonymous.status_code == 401
    forbidden = await client.get("/admin/change-history", headers=auth_headers)
    assert forbidden.status_code == 403


async def test_change_history_allowlists_targets_and_filters(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    actor_id = str(uuid.uuid4())
    actor = AdminActor(user_id=actor_id, email="history-admin@example.com", role="admin")
    feature_key = f"audit_key_{uuid.uuid4().hex}"
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    rows = [
        ("feature_flag", feature_key),
        ("feature_key", feature_key),
        ("plan_feature", f"free:{feature_key}"),
        ("role_feature", f"support:{feature_key}"),
        ("user", feature_key),  # same target text, but not flag/entitlement history
    ]
    for index, (target_type, target_id) in enumerate(rows):
        db_session.add(
            AdminAuditLog(
                id=str(uuid.uuid4()),
                actor_user_id=actor_id,
                actor_email=actor.email,
                action="entitlement.matrix.update",
                target_type=target_type,
                target_id=target_id,
                reason=REASON,
                before_state={"enabled": True},
                after_state={"enabled": False},
                created_at=start + timedelta(seconds=index),
            )
        )
    await db_session.commit()

    filtered = await client.get(
        "/admin/change-history",
        params={
            "key": feature_key,
            "actor_user_id": actor_id,
            "action": "entitlement.matrix.update",
        },
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    assert body["total"] == 4
    assert {item["target_type"] for item in body["items"]} == {
        "feature_flag",
        "feature_key",
        "plan_feature",
        "role_feature",
    }
    assert body["filters"] == {
        "key": feature_key,
        "target_id": None,
        "actor_user_id": actor_id,
        "action": "entitlement.matrix.update",
        "created_after": None,
        "created_before": None,
    }

    exact = await client.get(
        "/admin/change-history",
        params={"target_id": f"free:{feature_key}"},
        headers=headers,
    )
    assert exact.status_code == 200
    assert exact.json()["total"] == 1
    assert exact.json()["items"][0]["target_id"] == f"free:{feature_key}"

    windowed = await client.get(
        "/admin/change-history",
        params={
            "key": feature_key,
            "created_after": (start + timedelta(seconds=2)).isoformat(),
            "created_before": (start + timedelta(seconds=3)).isoformat(),
        },
        headers=headers,
    )
    assert windowed.status_code == 200
    assert {item["target_id"] for item in windowed.json()["items"]} == {
        f"free:{feature_key}",
        f"support:{feature_key}",
    }

    first = await client.get(
        "/admin/change-history",
        params={"key": feature_key, "limit": 2},
        headers=headers,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["has_more"] is True
    assert first_body["next_cursor"]
    second = await client.get(
        "/admin/change-history",
        params={"key": feature_key, "limit": 2, "cursor": first_body["next_cursor"]},
        headers=headers,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["has_more"] is False
    assert {item["id"] for item in first_body["items"]}.isdisjoint(
        {item["id"] for item in second_body["items"]}
    )

    assert (
        await client.get("/admin/change-history", params={"limit": 0}, headers=headers)
    ).status_code == 422
    assert (
        await client.get("/admin/change-history", params={"limit": 201}, headers=headers)
    ).status_code == 422
    bad_cursor = await client.get(
        "/admin/change-history", params={"cursor": "not-a-real-cursor"}, headers=headers
    )
    assert bad_cursor.status_code == 400


async def test_change_history_never_returns_sensitive_diff_values(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    target_id = f"audit_safe_{uuid.uuid4().hex}"
    actor = AdminActor(
        user_id=str(uuid.uuid4()), email="safe-admin@example.com", role="admin"
    )
    await record_admin_audit(
        db_session,
        actor=actor,
        action="feature_flag.update",
        target_type="feature_flag",
        target_id=target_id,
        reason="Exercise redaction",
        before={
            "enabled": True,
            "authorization": "Bearer super-secret-token",
            "password": "old-password-value",
        },
        after={
            "enabled": False,
            "authorization": "Bearer other-secret-token",
            "password": "new-password-value",
        },
    )
    await db_session.commit()

    resp = await client.get(
        "/admin/change-history", params={"target_id": target_id}, headers=headers
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["before"] == {"enabled": True}
    assert item["after"] == {"enabled": False}
    serialized = resp.text
    for secret in ("super-secret-token", "other-secret-token", "old-password-value", "new-password-value"):
        assert secret not in serialized

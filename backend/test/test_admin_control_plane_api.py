"""Admin Control Plane API tests (entitlements + users/roles + config).

Auth model: users now carry an RBAC ``role`` column. ``require_admin`` grants
access when ``role == 'admin'``, so these tests create admin users directly with
role='admin' (no ADMIN_EMAIL patching needed). Non-admin users get 403.

GLOBAL STATE: mutations here toggle kill-switches / matrix cells in the shared
test DB + Redis blob + cache. The autouse ``_reset`` fixture restores the
all-enabled baseline AFTER every test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from _entitlement_reset import reset_entitlements_baseline
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
async def _reset():
    yield
    await reset_entitlements_baseline()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    name: str = "CP User",
    email: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    if email is None:
        email = f"test_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, :plan, 'active', false)"
        ),
        {"id": user_id, "email": email, "name": name, "role": role, "plan": plan},
    )
    await db.commit()
    return user_id, email


async def _create_session(db: AsyncSession, user_id: str) -> str:
    token = f"test_sess_{uuid.uuid4().hex}"
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token) '
            "VALUES (:id, :uid, :exp, :tok)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return token


async def _admin_headers(db: AsyncSession) -> dict:
    user_id, _ = await _create_user(db, role="admin", name="Admin User")
    token = await _create_session(db, user_id)
    return {"Authorization": f"Bearer {token}"}


async def _user_headers(db: AsyncSession, role: str = "user") -> tuple[str, dict]:
    user_id, _ = await _create_user(db, role=role)
    token = await _create_session(db, user_id)
    return user_id, {"Authorization": f"Bearer {token}"}


# ── GET /admin/entitlements ──────────────────────────────────────────────────

class TestGetEntitlements:

    async def test_non_admin_403(self, client: AsyncClient, db_session: AsyncSession):
        _, headers = await _user_headers(db_session)
        resp = await client.get("/admin/entitlements", headers=headers)
        assert resp.status_code == 403

    async def test_admin_200_shape(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.get("/admin/entitlements", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"registry", "kill_switches", "matrix", "plan_families"}
        assert body["plan_families"] == ["free", "basic", "pro", "byok", "team"]
        assert len(body["registry"]) == 27


# ── PATCH /admin/entitlements/kill-switch/{key} ──────────────────────────────

class TestKillSwitch:

    async def test_toggle_reflected_in_get(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)

        resp = await client.patch(
            "/admin/entitlements/kill-switch/cover_letters",
            json={"enabled": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["kill_switches"]["cover_letters"] is False

        # Confirmed via a subsequent GET.
        get_resp = await client.get("/admin/entitlements", headers=headers)
        assert get_resp.json()["kill_switches"]["cover_letters"] is False

    async def test_non_gateable_key_404(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.patch(
            "/admin/entitlements/kill-switch/compile",  # non-gateable
            json={"enabled": False},
            headers=headers,
        )
        assert resp.status_code == 404

    async def test_unknown_key_404(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.patch(
            "/admin/entitlements/kill-switch/no_such_key",
            json={"enabled": False},
            headers=headers,
        )
        assert resp.status_code == 404


# ── PATCH /admin/entitlements/matrix ─────────────────────────────────────────

class TestMatrix:

    async def test_toggle_cell(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.patch(
            "/admin/entitlements/matrix",
            json={"plan_family": "free", "feature_key": "cover_letters", "enabled": False},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["matrix"]["free"]["cover_letters"] is False
        # Other families unaffected.
        assert resp.json()["matrix"]["pro"]["cover_letters"] is True

    async def test_invalid_family_400(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.patch(
            "/admin/entitlements/matrix",
            json={"plan_family": "platinum", "feature_key": "cover_letters", "enabled": False},
            headers=headers,
        )
        assert resp.status_code == 400

    async def test_non_gateable_key_404(self, client: AsyncClient, db_session: AsyncSession):
        headers = await _admin_headers(db_session)
        resp = await client.patch(
            "/admin/entitlements/matrix",
            json={"plan_family": "free", "feature_key": "compile", "enabled": False},
            headers=headers,
        )
        assert resp.status_code == 404


# ── GET /admin/users ─────────────────────────────────────────────────────────

class TestListUsers:

    async def test_returns_created_users_with_role(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_headers = await _admin_headers(db_session)
        target_id, target_email = await _create_user(db_session, role="support")

        resp = await client.get("/admin/users?limit=200", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "users" in body and "total" in body
        found = {u["id"]: u for u in body["users"]}
        assert target_id in found
        assert found[target_id]["role"] == "support"
        assert found[target_id]["email"] == target_email

    async def test_search_filters(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        unique = uuid.uuid4().hex[:10]
        target_id, _ = await _create_user(
            db_session, name=f"Zephyr {unique}", email=f"test_{unique}@example.com"
        )

        resp = await client.get(f"/admin/users?q={unique}", headers=admin_headers)
        assert resp.status_code == 200
        ids = [u["id"] for u in resp.json()["users"]]
        assert target_id in ids
        # A non-matching query should not return the target.
        resp2 = await client.get("/admin/users?q=no_such_substring_xyzzy", headers=admin_headers)
        assert target_id not in [u["id"] for u in resp2.json()["users"]]

    async def test_pagination_bounds(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        # limit within bounds
        ok = await client.get("/admin/users?limit=1&offset=0", headers=admin_headers)
        assert ok.status_code == 200
        assert len(ok.json()["users"]) <= 1
        # limit above max (200) → 422 validation error
        too_big = await client.get("/admin/users?limit=500", headers=admin_headers)
        assert too_big.status_code == 422
        # negative offset → 422
        neg = await client.get("/admin/users?offset=-1", headers=admin_headers)
        assert neg.status_code == 422

    async def test_non_admin_403(self, client: AsyncClient, db_session: AsyncSession):
        _, headers = await _user_headers(db_session)
        resp = await client.get("/admin/users", headers=headers)
        assert resp.status_code == 403


# ── PATCH /admin/users/{id}/role ─────────────────────────────────────────────

class TestUpdateRole:

    async def test_change_role(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session, role="user")

        resp = await client.patch(
            f"/admin/users/{target_id}/role",
            json={"role": "support"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "support"

    async def test_invalid_role_400(self, client: AsyncClient, db_session: AsyncSession):
        admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session, role="user")
        resp = await client.patch(
            f"/admin/users/{target_id}/role",
            json={"role": "superuser"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_last_admin_guard_409(self, client: AsyncClient, db_session: AsyncSession):
        """Demoting the only admin returns 409.

        Guarantee there is exactly ONE admin: demote every pre-existing admin to
        'user' first (via a second admin), then attempt to demote the last one.
        """
        # Two admins so we can safely clear any other admins in the shared DB.
        admin_a_id, _ = await _create_user(db_session, role="admin", name="Admin A")
        token_a = await _create_session(db_session, admin_a_id)
        headers_a = {"Authorization": f"Bearer {token_a}"}

        admin_b_id, _ = await _create_user(db_session, role="admin", name="Admin B")

        # Demote all admins EXCEPT admin_a to 'user' so admin_a is the last admin.
        await db_session.execute(
            text("UPDATE users SET role = 'user' WHERE role = 'admin' AND id != :keep"),
            {"keep": admin_a_id},
        )
        await db_session.commit()
        # admin_b was just demoted in the DB; irrelevant now.
        assert admin_b_id  # referenced

        # Now demoting admin_a (the last admin) must 409.
        resp = await client.patch(
            f"/admin/users/{admin_a_id}/role",
            json={"role": "user"},
            headers=headers_a,
        )
        assert resp.status_code == 409

        # Restore admin_a so teardown / other tests are unaffected.
        await db_session.execute(
            text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": admin_a_id}
        )
        await db_session.commit()

    async def test_non_admin_403(self, client: AsyncClient, db_session: AsyncSession):
        _, headers = await _user_headers(db_session)
        target_id, _ = await _create_user(db_session, role="user")
        resp = await client.patch(
            f"/admin/users/{target_id}/role",
            json={"role": "admin"},
            headers=headers,
        )
        assert resp.status_code == 403


# ── GET /config/entitlements (auth optional) ─────────────────────────────────

class TestConfigEntitlements:

    async def test_authed_user(self, client: AsyncClient, db_session: AsyncSession):
        _, headers = await _user_headers(db_session)
        resp = await client.get("/config/entitlements", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "features" in body
        assert len(body["features"]) == 27
        assert body["features"]["compile"] is True

    async def test_anonymous(self, client: AsyncClient):
        resp = await client.get("/config/entitlements")
        assert resp.status_code == 200
        body = resp.json()
        assert "features" in body
        assert len(body["features"]) == 27

    async def test_anonymous_reflects_free_matrix_disable(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.services.entitlement_service import entitlement_service

        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)
        resp = await client.get("/config/entitlements")
        assert resp.status_code == 200
        assert resp.json()["features"]["cover_letters"] is False


# ── require_role factory (optional coverage) ─────────────────────────────────

class TestRequireRole:

    async def test_require_role_support_admin_route_behaviour(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A 'support' user is granted admin-plane read via the role path only if
        role=='admin'; here we assert a support user is still blocked from an
        admin-only route (require_admin requires role=='admin')."""
        _, headers = await _user_headers(db_session, role="support")
        resp = await client.get("/admin/entitlements", headers=headers)
        # support is NOT admin → 403 on the admin-only route.
        assert resp.status_code == 403

"""Per-user feature, trial and quota support actions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_plan_quota_window
from app.services import admin_user_service
from app.services.entitlement_service import _current_period, entitlement_service


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    plan: str = "free",
    status: str = "active",
    metadata: dict | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_actions_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used, user_metadata) "
            "VALUES (:id, :email, :name, :role, true, :plan, :status, false, CAST(:metadata AS jsonb))"
        ),
        {
            "id": user_id,
            "email": email,
            "name": "Support Actions User",
            "role": role,
            "plan": plan,
            "status": status,
            "metadata": json.dumps(metadata or {}),
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"actions_sess_{uuid.uuid4().hex}"
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


async def _admin_headers(db: AsyncSession) -> tuple[str, dict[str, str]]:
    admin_id, _ = await _create_user(db, role="admin")
    return admin_id, await _session_headers(db, admin_id)


async def _metadata(db: AsyncSession, user_id: str) -> dict | None:
    return (
        await db.execute(text("SELECT user_metadata FROM users WHERE id = :id"), {"id": user_id})
    ).scalar_one()


class TestFeatureOverrides:
    async def test_unknown_feature_and_missing_confirmation_are_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session)

        unknown = await client.post(
            f"/admin/users/{target_id}/features/grant",
            json={"feature_key": "definitely_not_a_feature", "reason": "Ticket test", "confirm": True},
            headers=admin_headers,
        )
        assert unknown.status_code == 422

        missing_confirm = await client.post(
            f"/admin/users/{target_id}/features/grant",
            json={"feature_key": "exports", "reason": "Ticket test"},
            headers=admin_headers,
        )
        assert missing_confirm.status_code == 422

        false_confirm = await client.post(
            f"/admin/users/{target_id}/features/revoke",
            json={"feature_key": "exports", "reason": "Ticket test", "confirm": False},
            headers=admin_headers,
        )
        assert false_confirm.status_code == 422

    async def test_self_target_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_id, admin_headers = await _admin_headers(db_session)
        response = await client.post(
            f"/admin/users/{admin_id}/features/grant",
            json={"feature_key": "exports", "reason": "Self grant", "confirm": True},
            headers=admin_headers,
        )
        assert response.status_code == 409

    async def test_grant_revoke_are_idempotent_audited_and_effective(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session)

        first_revoke = await client.post(
            f"/admin/users/{target_id}/features/revoke",
            json={"feature_key": "exports", "reason": "Plan dispute", "confirm": True},
            headers=admin_headers,
        )
        assert first_revoke.status_code == 200
        revoked = first_revoke.json()
        assert revoked["changed"] is True
        assert revoked["effective"] is False
        assert revoked["after"]["override"] is False

        second_revoke = await client.post(
            f"/admin/users/{target_id}/features/revoke",
            json={"feature_key": "exports", "reason": "Plan dispute", "confirm": True},
            headers=admin_headers,
        )
        assert second_revoke.status_code == 200
        assert second_revoke.json()["changed"] is False

        grant = await client.post(
            f"/admin/users/{target_id}/features/grant",
            json={"feature_key": "exports", "reason": "Service recovery", "confirm": True},
            headers=admin_headers,
        )
        assert grant.status_code == 200
        granted = grant.json()
        assert granted["changed"] is True
        assert granted["effective"] is True
        assert granted["features"]["exports"] is True

        second_grant = await client.post(
            f"/admin/users/{target_id}/features/grant",
            json={"feature_key": "exports", "reason": "Service recovery", "confirm": True},
            headers=admin_headers,
        )
        assert second_grant.status_code == 200
        assert second_grant.json()["changed"] is False

        metadata = await _metadata(db_session, target_id)
        assert metadata["entitlement_overrides"]["exports"]["enabled"] is True

        audit = await client.get(
            f"/admin/audit?target_type=user&target_id={target_id}",
            headers=admin_headers,
        )
        assert audit.status_code == 200
        actions = [(row["action"], row["before"], row["after"]) for row in audit.json()["items"]]
        assert ("user.feature.revoke", {"feature_key": "exports", "override": None},
                {"feature_key": "exports", "override": False}) in actions
        assert ("user.feature.grant", {"feature_key": "exports", "override": False},
                {"feature_key": "exports", "override": True}) in actions
        assert sum(1 for action, _, _ in actions if action == "user.feature.revoke") == 1
        assert sum(1 for action, _, _ in actions if action == "user.feature.grant") == 1
        assert await entitlement_service.has_feature("exports", user=target_id) is True

    async def test_feature_override_invalidates_360_and_entitlement_caches(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        class FakeCache:
            def __init__(self):
                self.values: dict[str, object] = {}

            async def get(self, key: str):
                return self.values.get(key)

            async def set(self, key: str, value, ttl: int = 3600):
                self.values[key] = value

            async def delete(self, key: str):
                self.values.pop(key, None)

        fake = FakeCache()
        monkeypatch.setattr(admin_user_service, "cache_manager", fake)
        monkeypatch.setattr(
            "app.services.entitlement_service._cache",
            ({"legacy": True}, 10**9),
        )
        _, admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session)

        view = await client.get(f"/admin/users/{target_id}/360", headers=admin_headers)
        assert view.status_code == 200
        assert fake.values

        grant = await client.post(
            f"/admin/users/{target_id}/features/grant",
            json={"feature_key": "exports", "reason": "Cache propagation", "confirm": True},
            headers=admin_headers,
        )
        assert grant.status_code == 200
        assert fake.values == {}
        from app.services import entitlement_service as entitlement_module

        assert entitlement_module._cache is None


class TestTrialAndQuotaActions:
    async def test_trial_extension_and_eligibility_are_audited(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session)

        extended = await client.post(
            f"/admin/users/{target_id}/trial/extend",
            json={"days": 7, "reason": "Support extension", "confirm": True},
            headers=admin_headers,
        )
        assert extended.status_code == 200
        body = extended.json()
        assert body["changed"] is True
        assert body["trial"]["eligible"] is True
        assert body["trial"]["extended_until"] is not None

        repeated = await client.post(
            f"/admin/users/{target_id}/trial/eligibility",
            json={"eligible": True, "reason": "Already eligible", "confirm": True},
            headers=admin_headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["changed"] is False

        ineligible = await client.post(
            f"/admin/users/{target_id}/trial/eligibility",
            json={"eligible": False, "reason": "Abuse review", "confirm": True},
            headers=admin_headers,
        )
        assert ineligible.status_code == 200
        assert ineligible.json()["trial"]["eligible"] is False

        audit = await client.get(
            f"/admin/audit?target_type=user&target_id={target_id}",
            headers=admin_headers,
        )
        actions = {row["action"] for row in audit.json()["items"]}
        assert {"user.trial.extend", "user.trial.eligibility"} <= actions

    async def test_quota_reset_targets_only_user_dimension_and_window(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, admin_headers = await _admin_headers(db_session)
        target_id, _ = await _create_user(db_session)
        other_id, _ = await _create_user(db_session)

        from app.core.redis import get_redis_cache_client

        redis = await get_redis_cache_client()
        compile_period = _current_period(get_plan_quota_window("free", "compilations"))
        optimize_period = _current_period(get_plan_quota_window("free", "optimizations"))
        target_compile = f"latexy:quota:compilations:{target_id}:{compile_period}"
        target_optimize = f"latexy:quota:optimizations:{target_id}:{optimize_period}"
        other_compile = f"latexy:quota:compilations:{other_id}:{compile_period}"
        previous_target = f"latexy:quota:compilations:{target_id}:199901"
        await redis.set(target_compile, 5)
        await redis.set(target_optimize, 4)
        await redis.set(other_compile, 3)
        await redis.set(previous_target, 2)

        response = await client.post(
            f"/admin/users/{target_id}/quota/reset",
            json={"reason": "Stuck meter", "dimension": "compilations", "confirm": True},
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["dimensions"] == ["compilations"]
        assert body["deleted_keys"] == 1
        assert body["results"][0]["dimension"] == "compilations"
        assert body["results"][0]["before_used"] == 5
        assert body["results"][0]["after_used"] == 0
        assert body["results"][0]["window"] == "day"
        assert body["quota"]["dimensions"]["compilations"]["used"] == 0

        assert await redis.get(target_compile) is None
        assert int(await redis.get(target_optimize)) == 4
        assert int(await redis.get(other_compile)) == 3
        assert int(await redis.get(previous_target)) == 2

        audit = await client.get(
            f"/admin/audit?target_type=user&target_id={target_id}",
            headers=admin_headers,
        )
        completed = [
            row for row in audit.json()["items"] if row["action"] == "user.quota.reset.completed"
        ]
        assert completed
        assert completed[0]["after"]["deleted_keys"] == 1

        await redis.delete(target_optimize, other_compile, previous_target)

    async def test_quota_reset_rejects_self_target_and_false_confirmation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        admin_id, admin_headers = await _admin_headers(db_session)
        self_target = await client.post(
            f"/admin/users/{admin_id}/quota/reset",
            json={"reason": "Self reset", "dimension": "compilations", "confirm": True},
            headers=admin_headers,
        )
        assert self_target.status_code == 409

        target_id, _ = await _create_user(db_session)
        false_confirm = await client.post(
            f"/admin/users/{target_id}/quota/reset",
            json={"reason": "No confirmation", "dimension": "compilations", "confirm": False},
            headers=admin_headers,
        )
        assert false_confirm.status_code == 422

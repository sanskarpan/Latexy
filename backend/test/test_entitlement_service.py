"""EntitlementService resolution tests (Admin Control Plane).

Exercises ``entitlement_service`` directly (async). Uses lightweight user-like
objects (role/subscription_plan attributes) so we avoid DB round-trips where the
service reads attributes directly.

GLOBAL STATE: these tests toggle kill-switches / matrix cells that live in the
shared test DB + Redis blob + in-process cache. The autouse ``_reset`` fixture
restores the all-enabled baseline AFTER every test so no other test in the whole
suite ever observes a disabled feature.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from _entitlement_reset import reset_entitlements_baseline
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_plan_quota
from app.core.feature_registry import FEATURE_REGISTRY, PLAN_FAMILIES, gateable_keys
from app.database.models import User
from app.services.entitlement_service import (
    REDIS_BLOB_KEY,
    entitlement_service,
)

# ── Isolation: reset the all-enabled baseline after every test ───────────────

@pytest.fixture(autouse=True)
async def _reset():
    yield
    await reset_entitlements_baseline()


# ── User-like helpers ────────────────────────────────────────────────────────

def _user(role: str | None = None, plan: str | None = "free"):
    """A minimal user-like object exposing role + subscription_plan."""
    return SimpleNamespace(role=role, subscription_plan=plan)


FREE_USER = None  # sentinel replaced per-test via _user()


# ── has_feature: trivial / bypass paths ──────────────────────────────────────

class TestHasFeatureTrivial:

    async def test_non_gateable_key_always_true(self):
        assert await entitlement_service.has_feature("compile", user=_user(plan="free")) is True

    async def test_unknown_key_always_true(self):
        assert await entitlement_service.has_feature("no_such_feature", user=_user()) is True

    async def test_admin_role_true_even_when_disabled(self, db_session: AsyncSession):
        await entitlement_service.set_kill_switch("cover_letters", False, db_session)
        admin = _user(role="admin", plan="free")
        assert await entitlement_service.has_feature("cover_letters", user=admin) is True

    async def test_support_role_true_even_when_disabled(self, db_session: AsyncSession):
        await entitlement_service.set_kill_switch("cover_letters", False, db_session)
        support = _user(role="support", plan="free")
        assert await entitlement_service.has_feature("cover_letters", user=support) is True

    async def test_anonymous_uses_free_family(self, db_session: AsyncSession):
        # Disable cover_letters only for the free family → anonymous (None) blocked.
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)
        assert await entitlement_service.has_feature("cover_letters", user=None) is False


# ── has_feature: kill-switch + matrix ────────────────────────────────────────

class TestHasFeatureToggles:

    async def test_kill_switch_disables_then_reenables(self, db_session: AsyncSession):
        free = _user(plan="free")

        await entitlement_service.set_kill_switch("cover_letters", False, db_session)
        assert await entitlement_service.has_feature("cover_letters", user=free) is False

        await entitlement_service.set_kill_switch("cover_letters", True, db_session)
        assert await entitlement_service.has_feature("cover_letters", user=free) is True

    async def test_matrix_cell_only_affects_that_family(self, db_session: AsyncSession):
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)

        free = _user(plan="free")
        pro = _user(plan="pro")

        assert await entitlement_service.has_feature("cover_letters", user=free) is False
        # Only the free family was disabled → a pro user is unaffected.
        assert await entitlement_service.has_feature("cover_letters", user=pro) is True

    async def test_default_all_enabled_for_free_user(self):
        free = _user(plan="free")
        for key in gateable_keys():
            assert await entitlement_service.has_feature(key, user=free) is True, key


# ── effective_features + get_state shapes ────────────────────────────────────

class TestEffectiveFeaturesAndState:

    async def test_effective_features_contains_the_complete_registry(self):
        free = _user(plan="free")
        eff = await entitlement_service.effective_features(free)
        assert set(eff.keys()) == {f.key for f in FEATURE_REGISTRY}
        assert len(eff) == len(FEATURE_REGISTRY)
        # Non-gateable always True.
        assert eff["compile"] is True

    async def test_effective_features_reflect_disable(self, db_session: AsyncSession):
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)
        free = _user(plan="free")
        eff = await entitlement_service.effective_features(free)
        assert eff["cover_letters"] is False
        assert eff["compile"] is True  # non-gateable unaffected

    @pytest.mark.parametrize("ending_status", ["past_due", "cancel_scheduled"])
    async def test_billing_status_gates_paid_features_and_quota_after_grace(
        self, db_session: AsyncSession, ending_status: str,
    ):
        user_id, subscription_id = str(uuid.uuid4()), str(uuid.uuid4())
        await db_session.execute(text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, "
            "subscription_id, trial_used) VALUES (:id, :email, 'Billing Entitlement', true, 'pro', 'on_hold', :sub_id, false)"
        ), {"id": user_id, "email": f"entitlement_{user_id.replace('-', '')}@example.com", "sub_id": subscription_id})
        future = datetime.now(timezone.utc) + timedelta(days=2)
        await db_session.execute(text(
            "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, current_period_end) "
            "VALUES (:id, :user_id, 'dodo', 'pro', 'on_hold', :period_end)"
        ), {"id": subscription_id, "user_id": user_id, "period_end": future})
        await db_session.commit()
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)

        user = await db_session.get(User, user_id)
        held_features = await entitlement_service.effective_features(user)
        held_quota = await entitlement_service.quota_snapshot(user_id, "pro")
        assert held_features["cover_letters"] is False
        assert await entitlement_service.has_feature("cover_letters", user=user) is False
        assert held_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("free", "compilations")

        await db_session.execute(text(
            "UPDATE users SET subscription_status='paused' WHERE id=:user_id"
        ), {"user_id": user_id})
        await db_session.execute(text(
            "UPDATE subscriptions SET status='paused' WHERE id=:sub_id"
        ), {"sub_id": subscription_id})
        await db_session.commit()
        user = await db_session.get(User, user_id, populate_existing=True)
        assert await entitlement_service.has_feature("cover_letters", user=user) is False

        # Reproduce a denormalized user row that missed the newer provider
        # lifecycle event; the linked Dodo subscription must still gate access.
        await db_session.execute(text(
            "UPDATE users SET subscription_status='active' WHERE id=:user_id"
        ), {"user_id": user_id})
        await db_session.commit()
        user = await db_session.get(User, user_id, populate_existing=True)
        stale_user_quota = await entitlement_service.quota_snapshot(user_id, "pro")
        assert await entitlement_service.has_feature("cover_letters", user=user) is False
        assert stale_user_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("free", "compilations")

        await db_session.execute(text(
            "UPDATE users SET subscription_status=:status WHERE id=:user_id"
        ), {"user_id": user_id, "status": ending_status})
        await db_session.execute(text(
            "UPDATE subscriptions SET status=:status, current_period_end=:period_end WHERE id=:sub_id"
        ), {"period_end": future, "sub_id": subscription_id, "status": ending_status})
        await db_session.commit()
        user = await db_session.get(User, user_id, populate_existing=True)
        grace_features = await entitlement_service.effective_features(user)
        grace_quota = await entitlement_service.quota_snapshot(user_id, "pro")
        assert grace_features["cover_letters"] is True
        assert await entitlement_service.has_feature("cover_letters", user=user_id) is True
        assert grace_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("pro", "compilations")

        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.execute(text(
            "UPDATE subscriptions SET current_period_end=:period_end WHERE id=:sub_id"
        ), {"period_end": expired, "sub_id": subscription_id})
        await db_session.commit()
        user = await db_session.get(User, user_id, populate_existing=True)
        expired_features = await entitlement_service.effective_features(user)
        expired_quota = await entitlement_service.quota_snapshot(user_id, "pro")
        assert expired_features["cover_letters"] is False
        assert await entitlement_service.has_feature("cover_letters", user=user) is False
        assert expired_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("free", "compilations")

        # Missing term evidence also fails closed, including a missing intent.
        await db_session.execute(text(
            "UPDATE subscriptions SET current_period_end=NULL WHERE id=:sub_id"
        ), {"sub_id": subscription_id})
        await db_session.commit()
        assert await entitlement_service.has_feature("cover_letters", user=user_id) is False
        await db_session.execute(text(
            "UPDATE users SET subscription_id=NULL WHERE id=:user_id"
        ), {"user_id": user_id})
        await db_session.commit()
        assert await entitlement_service.has_feature("cover_letters", user=user_id) is False

    @pytest.mark.parametrize("ending_status", ["past_due", "cancel_scheduled"])
    async def test_team_member_access_tracks_owner_subscription_without_revoking_seat(
        self, db_session: AsyncSession, ending_status: str,
    ):
        owner_id, member_id, subscription_id, seat_id = (str(uuid.uuid4()) for _ in range(4))
        await db_session.execute(text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, "
            "subscription_id, trial_used) VALUES (:id, :email, 'Team Owner', true, 'team', 'active', :sub_id, false)"
        ), {"id": owner_id, "email": f"owner_{owner_id.replace('-', '')}@example.com", "sub_id": subscription_id})
        await db_session.execute(text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Team Member', true, 'team_member', 'active', false)"
        ), {"id": member_id, "email": f"member_{member_id.replace('-', '')}@example.com"})
        await db_session.execute(text(
            "INSERT INTO subscriptions (id, user_id, provider, plan_id, status, current_period_end) "
            "VALUES (:id, :owner_id, 'dodo', 'team', 'active', :period_end)"
        ), {"id": subscription_id, "owner_id": owner_id,
            "period_end": datetime.now(timezone.utc) + timedelta(days=20)})
        await db_session.execute(text(
            "INSERT INTO team_seats (id, owner_user_id, member_email, member_user_id, status) "
            "VALUES (:id, :owner_id, :email, :member_id, 'active')"
        ), {"id": seat_id, "owner_id": owner_id,
            "email": f"member_{member_id.replace('-', '')}@example.com", "member_id": member_id})
        await db_session.commit()
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)

        member = await db_session.get(User, member_id)
        active_features = await entitlement_service.effective_features(member)
        assert active_features["cover_letters"] is True
        assert await entitlement_service.has_feature("cover_letters", user=member) is True
        assert (await entitlement_service.quota_snapshot(member_id, "team_member"))["dimensions"]["compilations"]["limit"] == get_plan_quota("team", "compilations")

        # A newer owner-subscription event gates members even if their denormalized
        # user row is still active. The seat remains active so recovery is reversible.
        await db_session.execute(text(
            "UPDATE subscriptions SET status='paused' WHERE id=:sub_id"
        ), {"sub_id": subscription_id})
        await db_session.commit()
        member = await db_session.get(User, member_id, populate_existing=True)
        paused_features = await entitlement_service.effective_features(member)
        paused_quota = await entitlement_service.quota_snapshot(member_id, "team_member")
        assert paused_features["cover_letters"] is False
        assert await entitlement_service.has_feature("cover_letters", user=member) is False
        assert paused_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("free", "compilations")
        assert await db_session.scalar(text(
            "SELECT status FROM team_seats WHERE id=:seat_id"
        ), {"seat_id": seat_id}) == "active"

        future = datetime.now(timezone.utc) + timedelta(days=2)
        await db_session.execute(text(
            "UPDATE subscriptions SET status=:status, current_period_end=:period_end WHERE id=:sub_id"
        ), {"period_end": future, "sub_id": subscription_id, "status": ending_status})
        await db_session.commit()
        member = await db_session.get(User, member_id, populate_existing=True)
        assert await entitlement_service.has_feature("cover_letters", user=member) is True

        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.execute(text(
            "UPDATE subscriptions SET current_period_end=:period_end WHERE id=:sub_id"
        ), {"period_end": expired, "sub_id": subscription_id})
        await db_session.commit()
        member = await db_session.get(User, member_id, populate_existing=True)
        assert await entitlement_service.has_feature("cover_letters", user=member) is False
        assert await db_session.scalar(text(
            "SELECT status FROM team_seats WHERE id=:seat_id"
        ), {"seat_id": seat_id}) == "active"
        expired_quota = await entitlement_service.quota_snapshot(member_id, "team_member")
        assert expired_quota["dimensions"]["compilations"]["limit"] == get_plan_quota("free", "compilations")
        await db_session.execute(text(
            "UPDATE subscriptions SET current_period_end=NULL WHERE id=:sub_id"
        ), {"sub_id": subscription_id})
        await db_session.commit()
        assert await entitlement_service.has_feature("cover_letters", user=member) is False

    async def test_get_state_shape(self, db_session: AsyncSession):
        state = await entitlement_service.get_state(db_session)
        assert set(state.keys()) == {"registry", "kill_switches", "matrix", "plan_families"}
        assert state["plan_families"] == list(PLAN_FAMILIES)

        gateable = set(gateable_keys())
        # kill_switches: one entry per gateable feature, all True at baseline.
        assert set(state["kill_switches"].keys()) == gateable
        assert all(v is True for v in state["kill_switches"].values())

        # matrix: family → gateable-key → bool.
        assert set(state["matrix"].keys()) == set(PLAN_FAMILIES)
        for family in PLAN_FAMILIES:
            assert set(state["matrix"][family].keys()) == gateable

        # registry entries carry the expected fields.
        assert len(state["registry"]) == len(FEATURE_REGISTRY)
        sample = state["registry"][0]
        assert set(sample.keys()) == {"key", "label", "category", "gateable"}


# ── sync_has_feature (worker path via Redis blob) ────────────────────────────

class TestSyncHasFeature:

    async def test_sync_reads_blob_disabled_kill(self, db_session: AsyncSession):
        # set_kill_switch pushes a fresh blob to Redis.
        await entitlement_service.set_kill_switch("cover_letters", False, db_session)
        assert entitlement_service.sync_has_feature("cover_letters", "free") is False

    async def test_sync_reads_blob_enabled(self, db_session: AsyncSession):
        # Any set_* pushes the blob; baseline is all-enabled.
        await entitlement_service.set_kill_switch("cover_letters", True, db_session)
        assert entitlement_service.sync_has_feature("cover_letters", "free") is True

    async def test_sync_matrix_family_scoped(self, db_session: AsyncSession):
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)
        assert entitlement_service.sync_has_feature("cover_letters", "free") is False
        assert entitlement_service.sync_has_feature("cover_letters", "pro") is True

    async def test_sync_non_gateable_always_true(self):
        assert entitlement_service.sync_has_feature("compile", "free") is True

    async def test_sync_fail_open_when_blob_missing(self):
        # Delete the Redis blob so there is nothing to read → fail open (True).
        import redis as _redis

        from app.core.config import settings

        r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(REDIS_BLOB_KEY)
        r.close()

        assert entitlement_service.sync_has_feature("cover_letters", "free") is True


# ── Regression: has_feature must NOT touch the caller's request session ──────

class TestSessionIsolationRegression:

    async def test_has_feature_does_not_rollback_caller_session(
        self, db_session: AsyncSession
    ):
        """A pending object in the passed session must survive a has_feature call.

        Guards the regression where entitlement reads on the request session
        rolled back the caller's in-flight transaction.
        """
        user_id = str(uuid.uuid4())
        email = f"test_{user_id.replace('-', '')}@example.com"
        # Add a pending row on the caller's session (not yet committed).
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, "
                "subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Pending User', true, 'free', 'active', false)"
            ),
            {"id": user_id, "email": email},
        )

        # Call has_feature WITH the caller's session — it must be ignored/untouched.
        result = await entitlement_service.has_feature(
            "cover_letters", user=_user(plan="free"), db=db_session
        )
        assert result is True

        # The pending object must still be visible in this session (no rollback).
        row = (
            await db_session.execute(
                text("SELECT id FROM users WHERE id = :id"), {"id": user_id}
            )
        ).fetchone()
        assert row is not None
        assert str(row[0]) == user_id
        # db_session fixture rolls back on teardown → row never persists globally.

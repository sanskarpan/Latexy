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
from types import SimpleNamespace

import pytest
from _entitlement_reset import reset_entitlements_baseline
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.feature_registry import FEATURE_REGISTRY, PLAN_FAMILIES, gateable_keys
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

    async def test_effective_features_all_29_keys(self):
        free = _user(plan="free")
        eff = await entitlement_service.effective_features(free)
        assert set(eff.keys()) == {f.key for f in FEATURE_REGISTRY}
        assert len(eff) == 29
        # Non-gateable always True.
        assert eff["compile"] is True

    async def test_effective_features_reflect_disable(self, db_session: AsyncSession):
        await entitlement_service.set_matrix_cell("free", "cover_letters", False, db_session)
        free = _user(plan="free")
        eff = await entitlement_service.effective_features(free)
        assert eff["cover_letters"] is False
        assert eff["compile"] is True  # non-gateable unaffected

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
        assert len(state["registry"]) == 29
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

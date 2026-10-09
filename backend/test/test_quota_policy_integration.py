"""Real DB/Redis quota edits: no reset, no retroactive refund rewrites."""
import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, select
from test_plan_catalog_integration import headers

from app.core.redis import get_redis_cache_client
from app.database.connection import get_async_db_session
from app.database.models import PlanQuotaOverride, PlanQuotaRevision
from app.services.entitlement_service import _current_period, entitlement_service
from app.services.quota_policy_service import QuotaPolicyConflict, quota_policy_service, resolve_quota_policy


@pytest.fixture(autouse=True)
async def clear_quota_overrides(db_session):
    await db_session.execute(delete(PlanQuotaRevision))
    await db_session.execute(delete(PlanQuotaOverride))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(PlanQuotaRevision))
    await db_session.execute(delete(PlanQuotaOverride))
    await db_session.commit()


async def test_quota_api_and_public_display_share_new_limit(client, db_session):
    _, auth = await headers(db_session)
    response = await client.patch("/admin/plan-catalog/free/quotas/compilations", json={"version": 1, "limit": 17}, headers=auth)
    assert response.status_code == 200, response.text
    quota = response.json()["plans"]["free"]["quotas"]["compilations"]
    assert quota == {"limit": 17, "window": "day", "version": 2, "source": "admin_override"}
    public = await client.get("/subscription/plans")
    assert public.status_code == 200
    assert public.json()["plans"]["free"]["features"]["compilations"] == "17 / day"
    assert await resolve_quota_policy("free", "compilations") == (17, "day")
    _, user_auth = await headers(db_session, "user")
    forbidden = await client.patch("/admin/plan-catalog/free/quotas/compilations", json={"version": 2, "limit": None}, headers=user_auth)
    assert forbidden.status_code == 403
    invalid = await client.patch("/admin/plan-catalog/free/quotas/money", json={"version": 1, "limit": 0}, headers=auth)
    assert invalid.status_code == 404
    rejected = await client.patch("/admin/plan-catalog/free/quotas/compilations", json={"version": 2, "limit": 8, "window": "month"}, headers=auth)
    assert rejected.status_code == 422


async def test_limit_raise_lower_unlimited_keeps_same_counter_and_refunds(db_session):
    admin_id, _ = await headers(db_session)
    user_id = str(uuid4())
    key = f"latexy:quota:compilations:{user_id}:{_current_period('day')}"
    redis = await get_redis_cache_client()
    await quota_policy_service.update(db_session, "free", "compilations", limit=2, version=1, admin_id=admin_id)
    first = await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
    second = await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
    assert first.allowed and second.allowed
    assert int(await redis.get(key)) == 2
    await quota_policy_service.update(db_session, "free", "compilations", limit=1, version=2, admin_id=admin_id)
    denied = await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
    assert not denied.allowed
    assert int(await redis.get(key)) == 2
    await quota_policy_service.update(db_session, "free", "compilations", limit=4, version=3, admin_id=admin_id)
    third = await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
    assert third.allowed and third.used == 3
    await entitlement_service.refund_quota(first)
    await entitlement_service.refund_quota(first)
    assert int(await redis.get(key)) == 2  # old receipt refunds exactly once
    await quota_policy_service.update(db_session, "free", "compilations", limit=None, version=4, admin_id=admin_id)
    fourth = await entitlement_service.consume_quota("compilations", user_id=user_id, plan="free")
    assert fourth.allowed and fourth.limit is None and fourth.used == 3
    assert fourth.period == first.period and fourth.window == "day"
    snapshot = await entitlement_service.quota_snapshot(user_id, "free")
    assert snapshot["dimensions"]["compilations"]["limit"] is None
    assert snapshot["dimensions"]["compilations"]["used"] == 3


async def test_concurrent_quota_edits_have_one_winner(db_session):
    admin_id, _ = await headers(db_session)

    async def change(limit):
        async with get_async_db_session() as db:
            await quota_policy_service.update(db, "free", "optimizations", limit=limit, version=1, admin_id=admin_id)
        return limit

    results = await asyncio.gather(change(8), change(9), return_exceptions=True)
    assert sum(isinstance(result, QuotaPolicyConflict) for result in results) == 1
    winner = next(result for result in results if isinstance(result, int))
    assert await resolve_quota_policy("free", "optimizations") == (winner, "month")
    revisions = (await db_session.execute(select(PlanQuotaRevision))).scalars().all()
    assert len(revisions) == 1 and revisions[0].version == 2


async def test_quota_migration_roundtrip_preserves_limit_and_audit(db_session):
    admin_id, _ = await headers(db_session)
    await quota_policy_service.update(db_session, "pro_annual", "ai_assists", limit=0, version=1, admin_id=admin_id)
    path = Path(__file__).parents[1] / "alembic/versions/0062_plan_quotas.py"
    spec = importlib.util.spec_from_file_location("quota_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def roundtrip(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()

    await (await db_session.connection()).run_sync(roundtrip)
    row = (await db_session.execute(select(PlanQuotaOverride))).scalar_one()
    assert row.limit_value == 0 and row.version == 2 and row.sku == "pro_annual"
    audit = (await db_session.execute(select(PlanQuotaRevision))).scalar_one()
    assert audit.limit_value == 0 and audit.changed_by == admin_id

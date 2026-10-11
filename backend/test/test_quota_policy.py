"""Pure quota policy contract: strict edits and exact-SKU resolution."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.api.plan_catalog_routes import PlanQuotaUpdate
from app.services.quota_policy_service import (
    MAX_QUOTA_LIMIT,
    QuotaPolicyConflict,
    QuotaPolicyService,
    canonical_quota_sku,
    format_quota_policy,
    resolve_quota_policy,
)


@pytest.mark.parametrize("limit", [-1, 1.5, True, "10", MAX_QUOTA_LIMIT + 1])
def test_invalid_limits_rejected(limit):
    with pytest.raises(ValidationError):
        PlanQuotaUpdate.model_validate({"version": 1, "limit": limit})


@pytest.mark.parametrize("payload", [{"version": 1}, {"version": 1, "limit": 10, "window": "day"}, {"version": True, "limit": 10}])
def test_missing_limit_and_window_changes_rejected(payload):
    with pytest.raises(ValidationError):
        PlanQuotaUpdate.model_validate(payload)


@pytest.mark.parametrize("limit", [0, 10, MAX_QUOTA_LIMIT, None])
def test_valid_limits_and_unlimited(limit):
    assert PlanQuotaUpdate(version=1, limit=limit).limit == limit


def test_overrides_are_exact_sku_and_never_inherited_from_paid_family():
    service = QuotaPolicyService()
    rows = {("pro", "compilations"): SimpleNamespace(limit_value=15, version=4)}
    assert service.catalog_policy("pro", rows)["compilations"] == {"limit": 15, "window": "month", "version": 4, "source": "admin_override"}
    assert service.catalog_policy("pro_annual", rows)["compilations"]["limit"] is None
    assert service.catalog_policy("student", rows)["compilations"]["limit"] is None
    assert service.catalog_policy("free", rows)["compilations"]["window"] == "day"
    assert canonical_quota_sku("team_member") == "team"
    assert canonical_quota_sku("basic_monthly") == "basic"


@pytest.mark.asyncio
async def test_unknown_quota_or_plan_rejected_before_storage():
    with pytest.raises(KeyError):
        await resolve_quota_policy("free", "unknown")
    with pytest.raises(KeyError):
        await QuotaPolicyService().resolve("platinum")


@pytest.mark.asyncio
async def test_storage_outage_cannot_fall_back_to_unlimited(monkeypatch):
    @asynccontextmanager
    async def unavailable():
        raise RuntimeError("database down")
        yield

    monkeypatch.setattr("app.services.quota_policy_service.get_async_db_session", unavailable)
    with pytest.raises(RuntimeError, match="database down"):
        await QuotaPolicyService().resolve("pro")


@pytest.mark.asyncio
async def test_batched_resolver_reads_once(monkeypatch):
    result = MagicMock()
    result.scalars.return_value.all.return_value = [SimpleNamespace(sku="free", dimension="compilations", limit_value=25, version=2)]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr("app.services.quota_policy_service.get_async_db_session", session)
    policies = await QuotaPolicyService().resolve("free")
    assert policies["compilations"] == {"limit": 25, "window": "day"}
    assert policies["optimizations"] == {"limit": 3, "window": "month"}
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_quota_edit_rollback():
    row = SimpleNamespace(sku="free", dimension="compilations", limit_value=12, version=3)
    result = MagicMock()
    result.scalar_one.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    with pytest.raises(QuotaPolicyConflict):
        await QuotaPolicyService().update(db, "free", "compilations", limit=40, version=2, admin_id="admin")
    assert row.limit_value == 12
    assert row.version == 3
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


def test_formatting_preserves_fixed_windows_and_explicit_unlimited():
    assert format_quota_policy({"limit": 25, "window": "day"}) == "25 / day"
    assert format_quota_policy({"limit": 0, "window": "month"}) == "0"
    assert format_quota_policy({"limit": None, "window": "month"}) == "unlimited"


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", ["free", "pro"])
async def test_policy_outage_denies_even_unlimited_before_counter_mutation(monkeypatch, plan):
    from fastapi import HTTPException

    from app.services.entitlement_service import EntitlementService

    monkeypatch.setattr(
        "app.services.quota_policy_service.resolve_quota_policy",
        AsyncMock(side_effect=RuntimeError("database down")),
    )
    redis = AsyncMock()
    monkeypatch.setattr("app.core.redis.get_redis_cache_client", redis)
    service = EntitlementService()
    ticket = await service.consume_quota("compilations", user_id="test-owner", plan=plan)
    assert not ticket.allowed and ticket.unavailable
    with pytest.raises(HTTPException) as denied:
        await service.enforce_quota("compilations", user_id="test-owner", plan=plan)
    assert denied.value.status_code == 503
    redis.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_outage_snapshot_preserves_reads_without_claiming_unlimited(monkeypatch):
    from app.services.entitlement_service import EntitlementService

    monkeypatch.setattr(
        "app.services.quota_policy_service.quota_policy_service.resolve",
        AsyncMock(side_effect=RuntimeError("database down")),
    )
    monkeypatch.setattr("app.core.redis.get_redis_cache_client", AsyncMock(side_effect=RuntimeError("offline")))
    snapshot = await EntitlementService().quota_snapshot("test-owner", "pro")
    assert snapshot["policy_available"] is False
    assert all(policy["limit"] == 0 and not policy["policy_available"] for policy in snapshot["dimensions"].values())

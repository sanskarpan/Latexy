"""Catalog policy tests require no provider calls, Redis or live payments."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.plan_catalog_routes import PlanCatalogUpdate, get_plan_catalog, update_plan_catalog
from app.core.config import PLAN_QUOTAS, get_plan_config, settings
from app.core.feature_registry import FEATURE_REGISTRY, PLAN_MATRIX_KEYS
from app.services.plan_catalog_service import CatalogConflict, PlanCatalogService


@pytest.fixture(autouse=True)
def no_quota_overrides(monkeypatch):
    monkeypatch.setattr("app.services.plan_catalog_service.quota_policy_service.catalog_overrides", AsyncMock(return_value={}))


def state():
    keys = [feature.key for feature in FEATURE_REGISTRY if feature.gateable]
    return {
        "registry": [{"key": feature.key, "label": feature.label, "gateable": feature.gateable} for feature in FEATURE_REGISTRY],
        "kill_switches": dict.fromkeys(keys, True),
        "matrix": {family: dict.fromkeys(keys, True) for family in PLAN_MATRIX_KEYS},
    }


def catalog_row(service, sku="pro", **changes):
    return SimpleNamespace(**(service.defaults(sku) | {"updated_at": datetime.now(timezone.utc)} | changes))


def db_with_row(row):
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    result.scalar_one.return_value = row
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_public_and_admin_share_names_prices_order_and_capabilities(monkeypatch):
    service = PlanCatalogService()
    row = catalog_row(service, name="Pro for applications", description="Reviewed copy", display_order=50)
    entitlements = state()
    entitlements["matrix"]["pro"]["developer_api"] = False
    monkeypatch.setattr(service, "_rows", AsyncMock(return_value={"pro": row}))
    with patch("app.services.plan_catalog_service.entitlement_service.get_state", AsyncMock(return_value=entitlements)):
        public = await service.list_plans(MagicMock(), provider_available=True)
        admin = await service.list_plans(MagicMock(), provider_available=True, public=False)
    for field in ("name", "description", "price", "currency", "features", "capabilities", "display_order"):
        assert public["pro"][field] == admin["pro"][field]
    assert public["pro"]["features"]["apiAccess"] is False
    assert "provider_plan_id" not in public["pro"]
    assert "i04" not in public["pro"]["capability_labels"]  # admin access is not a purchasable capability
    assert admin["pro"]["commercial_fields_read_only"] is True
    assert public["free"]["features"]["apiAccess"] is True
    assert public["free"]["features"]["apiDailyLimit"] == settings.DEV_API_DAILY_LIMIT_FREE == 10
    assert public["free"]["features"]["compilations"] == "10 / day"


@pytest.mark.asyncio
async def test_catalog_honors_sku_and_parent_restrictions(monkeypatch):
    service = PlanCatalogService()
    entitlements = state()
    entitlements["matrix"]["pro_annual"]["developer_api"] = False
    entitlements["kill_switches"]["byok"] = False
    monkeypatch.setattr(service, "_rows", AsyncMock(return_value={}))
    with patch("app.services.plan_catalog_service.entitlement_service.get_state", AsyncMock(return_value=entitlements)):
        plans = await service.list_plans(MagicMock(), provider_available=True)
    assert plans["pro"]["features"]["apiAccess"] is True
    assert plans["pro_annual"]["features"]["apiAccess"] is False
    assert plans["byok"]["features"]["customModels"] is False
    for feature in FEATURE_REGISTRY:
        if feature.parent_key == "byok":
            assert plans["byok"]["capabilities"][feature.key] is False


@pytest.mark.asyncio
async def test_pricing_summary_honors_granular_child_controls(monkeypatch):
    service = PlanCatalogService()
    entitlements = state()
    entitlements["matrix"]["free"]["h09"] = False
    entitlements["matrix"]["pro"]["d01"] = False
    entitlements["matrix"]["byok"]["d25"] = False
    monkeypatch.setattr(service, "_rows", AsyncMock(return_value={}))
    with patch("app.services.plan_catalog_service.entitlement_service.get_state", AsyncMock(return_value=entitlements)):
        plans = await service.list_plans(MagicMock(), provider_available=True)
    assert plans["free"]["features"]["apiAccess"] is False
    assert plans["pro"]["features"]["optimizations"] == "Unavailable"
    assert plans["byok"]["features"]["customModels"] is False


@pytest.mark.asyncio
async def test_hidden_offer_is_not_public_but_admin_can_review_it(monkeypatch):
    service = PlanCatalogService()
    monkeypatch.setattr(service, "_rows", AsyncMock(return_value={"pro": catalog_row(service, visible=False)}))
    with patch("app.services.plan_catalog_service.entitlement_service.get_state", AsyncMock(return_value=state())):
        public = await service.list_plans(MagicMock(), provider_available=True)
        admin = await service.list_plans(MagicMock(), provider_available=True, public=False)
    assert "pro" not in public
    assert "pro" in admin


@pytest.mark.asyncio
async def test_disabled_offer_remains_readable_and_existing_subscriptions_untouched(monkeypatch):
    service = PlanCatalogService()
    row = catalog_row(service, purchase_enabled=False)
    monkeypatch.setattr(service, "_rows", AsyncMock(return_value={"pro": row}))
    original = deepcopy(settings.SUBSCRIPTION_PLANS)
    quota_original = deepcopy(PLAN_QUOTAS)
    db = db_with_row(row)
    with patch("app.services.plan_catalog_service.entitlement_service.get_state", AsyncMock(return_value=state())):
        plans = await service.list_plans(db, provider_available=True)
    assert plans["pro"]["purchasable"] is False
    assert plans["pro"]["capabilities"]["developer_api"] is True
    with pytest.raises(HTTPException) as exc:
        await service.require_new_purchase(db, "pro")
    assert exc.value.status_code == 409
    assert settings.SUBSCRIPTION_PLANS == original
    assert PLAN_QUOTAS == quota_original
    assert get_plan_config("pro")["price"] == plans["pro"]["price"]
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_sku_rejected_before_database_or_provider_access():
    db = db_with_row(None)
    with pytest.raises(HTTPException) as exc:
        await PlanCatalogService().require_new_purchase(db, "pro_fake")
    assert exc.value.status_code == 400
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("field", ["price", "currency", "plan_family", "provider_plan_id", "features", "quotas", "interval", "id"])
def test_commercial_and_entitlement_overrides_are_rejected(field):
    with pytest.raises(ValidationError):
        PlanCatalogUpdate.model_validate({"version": 1, field: "changed"})


@pytest.mark.parametrize("payload", [{"version": 1, "name": " "}, {"version": 1, "purchase_enabled": "false"}, {"version": 1, "display_order": -1}, {"version": 1.5, "name": "New"}])
def test_invalid_catalog_values_rejected(payload):
    with pytest.raises(ValidationError):
        PlanCatalogUpdate.model_validate(payload)


@pytest.mark.asyncio
async def test_null_and_empty_updates_rejected():
    with pytest.raises(HTTPException) as exc:
        await update_plan_catalog("pro", PlanCatalogUpdate(version=1, name=None), MagicMock(), "admin")
    assert exc.value.status_code == 422
    with pytest.raises(ValueError):
        await PlanCatalogService().update(MagicMock(), "pro", {}, version=1, admin_id="admin")


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["visible", "purchase_enabled"])
async def test_free_fallback_cannot_be_disabled(field):
    db = db_with_row(None)
    with pytest.raises(ValueError):
        await PlanCatalogService().update(db, "free", {field: False}, version=1, admin_id="admin")
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_is_versioned_audited_and_never_changes_price():
    service = PlanCatalogService()
    row = catalog_row(service)
    db = db_with_row(row)
    before = get_plan_config("pro")
    await service.update(db, "pro", {"name": "Professional", "purchase_enabled": False}, version=1, admin_id="admin")
    assert row.version == 2
    assert row.name == "Professional"
    assert not row.purchase_enabled
    revision = db.add.call_args.args[0]
    assert revision.version == 2
    assert revision.snapshot["purchase_enabled"] is False
    assert get_plan_config("pro") == before
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_admin_edit_does_not_overwrite_newer_version():
    service = PlanCatalogService()
    row = catalog_row(service, version=3)
    db = db_with_row(row)
    with pytest.raises(CatalogConflict):
        await service.update(db, "pro", {"name": "Stale"}, version=2, admin_id="admin")
    assert row.name == "Pro"
    assert row.version == 3
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_optional_provider_prices_stay_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEEKLY_AMOUNT", 0)
    monkeypatch.setattr(settings, "RAZORPAY_LIFETIME_AMOUNT", 0)
    service = PlanCatalogService()
    public = await service.list_plans(None, provider_available=True)
    admin = await service.list_plans(None, provider_available=True, public=False)
    assert "weekly" not in public and "lifetime" not in public
    assert not admin["weekly"]["purchasable"]
    assert not admin["lifetime"]["purchasable"]


def test_catalog_guard_only_covers_new_checkout_not_subscription_lifecycle():
    source = (Path(__file__).parents[1] / "app/api/routes.py").read_text()
    assert 'require_new_purchase(db, concrete_sku)' in source
    assert 'require_new_purchase(db, "student")' in source
    payments = (Path(__file__).parents[1] / "app/services/payment_service.py").read_text()
    assert "require_new_purchase" not in payments


def test_catalog_admin_routes_always_require_admin():
    for endpoint in (get_plan_catalog, update_plan_catalog):
        dependencies = [value.default for value in __import__("inspect").signature(endpoint).parameters.values()]
        assert any(getattr(value, "dependency", None).__name__ == "require_admin" for value in dependencies if getattr(value, "dependency", None))


@pytest.mark.asyncio
async def test_current_subscription_display_includes_retired_sku(monkeypatch):
    from contextlib import asynccontextmanager

    service = PlanCatalogService()

    @asynccontextmanager
    async def isolated_session():
        yield MagicMock()

    monkeypatch.setattr("app.services.plan_catalog_service.get_async_db_session", isolated_session)
    monkeypatch.setattr(service, "list_plans", AsyncMock(return_value={"pro": {"name": "Professional", "features": {"apiAccess": True, "apiDailyLimit": 1000}}}))
    display = await service.current_subscription_display("pro")
    assert display["name"] == "Professional"
    assert display["features"]["apiAccess"] is True
    assert service.list_plans.call_args.kwargs["public"] is False


@pytest.mark.asyncio
async def test_catalog_outage_preserves_current_subscription_recovery(monkeypatch):
    from contextlib import asynccontextmanager

    service = PlanCatalogService()

    @asynccontextmanager
    async def broken_session():
        raise RuntimeError("catalog database temporarily unavailable")
        yield

    monkeypatch.setattr("app.services.plan_catalog_service.get_async_db_session", broken_session)
    display = await service.current_subscription_display("pro")
    assert display["name"] == "Pro"
    assert display["features"]["availabilityUnknown"] is True
    assert display["features"]["apiAccess"] is False
    assert display["features"]["optimizations"] == "Unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("sku", ["student", "team"])
async def test_commercial_capability_uses_target_sku(sku, monkeypatch):
    db = db_with_row(None)
    gate = AsyncMock(return_value=False)
    monkeypatch.setattr("app.services.plan_catalog_service.entitlement_service.has_feature", gate)
    with pytest.raises(HTTPException) as exc:
        await PlanCatalogService().require_new_purchase(db, sku)
    assert exc.value.status_code == 403
    assert gate.call_args.args[0] == "i02"
    assert gate.call_args.kwargs["user"].subscription_plan == sku

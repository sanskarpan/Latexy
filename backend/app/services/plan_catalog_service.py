"""Admin merchandising for stable billing SKUs, never a payment ledger.

Merchandising controls presentation and NEW purchase availability. Numeric
limits come from the separately versioned quota policy; provider prices,
SKU/family identities, subscriptions, renewals and refunds retain their existing
authorities. Disabling a SKU does not revoke an existing entitlement.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import (
    get_developer_api_daily_limit,
    get_plan_config,
    get_razorpay_plan_id,
    is_b57_sku_configured,
    settings,
)
from ..core.errors import error_body
from ..core.feature_registry import PLAN_SKU_ALIASES
from ..core.logging import get_logger
from ..database.connection import get_async_db_session
from ..database.models import PlanCatalog, PlanCatalogRevision
from .entitlement_service import entitlement_service
from .quota_policy_service import format_quota_policy, quota_policy_service

logger = get_logger(__name__)

EDITABLE_FIELDS = frozenset({"name", "description", "visible", "purchase_enabled", "display_order"})
_DEFAULT_DESCRIPTIONS = {
    "free": "Start with a free account. No payment required.",
    "basic": "For an active job search.",
    "basic_annual": "Basic, billed annually.",
    "pro": "For higher-volume resume work.",
    "pro_annual": "Pro, billed annually.",
    "byok": "Bring your own AI provider key.",
    "byok_annual": "Bring your own key, billed annually.",
    "student": "Student offer with verified email eligibility.",
    "team": "For teams working together.",
    "weekly": "A plan with weekly billing.",
    "lifetime": "A plan with a one-time payment.",
}


class CatalogConflict(ValueError):
    """A concurrent admin edit must be reviewed before saving again."""


class PlanCatalogService:
    def defaults(self, sku: str) -> dict[str, Any]:
        if sku not in settings.SUBSCRIPTION_PLANS:
            raise KeyError(sku)
        return {
            "sku": sku,
            "name": get_plan_config(sku)["name"],
            "description": _DEFAULT_DESCRIPTIONS.get(sku, ""),
            "visible": True,
            "purchase_enabled": True,
            "display_order": list(settings.SUBSCRIPTION_PLANS).index(sku),
            "version": 1,
        }

    async def _rows(self, db: AsyncSession) -> dict[str, PlanCatalog]:
        result = await db.execute(select(PlanCatalog))
        return {row.sku: row for row in result.scalars().all()}

    @staticmethod
    def _presentation(row: PlanCatalog | None, default: dict) -> dict:
        if row is None:
            return default
        return {key: getattr(row, key) for key in (*EDITABLE_FIELDS, "sku", "version")}

    async def list_plans(
        self, db: AsyncSession | None, *, provider_available: bool, public: bool = True
    ) -> dict[str, dict]:
        # Optional db only preserves the existing offline service-inspection
        # interface. HTTP handlers always supply a DB; DB errors fail closed.
        rows = await self._rows(db) if db is not None else {}
        state = await entitlement_service.get_state(db) if db is not None else None
        quota_overrides = await quota_policy_service.catalog_overrides(db) if db is not None else {}
        plans = {}
        for sku in settings.SUBSCRIPTION_PLANS:
            config = get_plan_config(sku)
            presentation = self._presentation(rows.get(sku), self.defaults(sku))
            if public and not presentation["visible"]:
                continue
            configured = (
                is_b57_sku_configured(sku) if sku in {"weekly", "lifetime"}
                else bool(get_razorpay_plan_id(sku)) if sku.endswith("_annual")
                else True
            )
            # Never market an unconfigured optional offer as a zero-price plan.
            if public and sku in {"weekly", "lifetime"} and not (configured and provider_available):
                continue
            capabilities = {}
            if state is not None:
                blob = {"kill": state["kill_switches"], "matrix": state["matrix"]}
                capabilities = {
                    feature["key"]: entitlement_service._decide(blob, feature["key"], sku)
                    for feature in state["registry"]
                }
            features = deepcopy(config["features"])
            quotas = quota_policy_service.catalog_policy(sku, quota_overrides)
            features.update({dimension: format_quota_policy(policy) for dimension, policy in quotas.items()})
            api_limit = get_developer_api_daily_limit(sku)
            features["apiAccess"] = capabilities.get("h09", capabilities.get("developer_api", True)) and api_limit > 0
            features["apiDailyLimit"] = api_limit
            if "customModels" in features:
                features["customModels"] = capabilities.get("d25", capabilities.get("byok", True))
            if not capabilities.get("d01", capabilities.get("llm_optimize", True)):
                features["optimizations"] = "Unavailable"
            if not capabilities.get("ai_writing", True):
                features["ai_assists"] = "Unavailable"
            purchasable = bool(presentation["purchase_enabled"] and configured and (sku == "free" or provider_available))
            plan = {
                **config, **presentation, "id": sku, "features": features,
                "capabilities": capabilities,
                "capability_labels": {feature["key"]: feature["label"] for feature in state["registry"] if feature["gateable"] or feature["key"] == "compile"} if state else {},
                "quotas": quotas,
                "purchasable": purchasable,
                "configured": configured,
                "unavailable_reason": (
                    None if purchasable else "Sales paused" if not presentation["purchase_enabled"]
                    else "Not configured" if not configured else "Billing unavailable"
                ),
            }
            if not public:
                plan.update({
                    "provider_plan_id": get_razorpay_plan_id(sku) or None,
                    "commercial_fields_read_only": True,
                    "quota_fields_read_only": False,
                    "quota_windows_read_only": True,
                    "developer_api_daily_limit_read_only": True,
                    "updated_at": rows[sku].updated_at.isoformat() if sku in rows and rows[sku].updated_at else None,
                })
            plans[sku] = plan
        return dict(sorted(plans.items(), key=lambda item: (item[1]["display_order"], item[0])))

    async def current_subscription_display(self, plan_id: str | None) -> dict:
        """Shared current copy without making billing recovery depend on this DB.

        Reads use a dedicated session: a catalog failure cannot invalidate the
        caller's subscription/history transaction. No subscription is mutated.
        """
        normalized = (plan_id or "free").strip().lower()
        sku = PLAN_SKU_ALIASES.get(normalized, normalized)
        config = get_plan_config(sku)
        try:
            async with get_async_db_session() as db:
                plans = await self.list_plans(db, provider_available=False, public=False)
            plan = plans[sku]
            return {"name": plan["name"], "features": plan["features"]}
        except Exception:
            logger.warning("Current catalog display unavailable; keeping subscription recovery available", exc_info=True)
            features = deepcopy(config.get("features", {}))
            features.update({
                "apiAccess": False, "customModels": False, "prioritySupport": False,
                "compilations": "Unavailable", "optimizations": "Unavailable", "ai_assists": "Unavailable", "availabilityUnknown": True,
            })
            return {"name": config.get("name", "Unknown"), "features": features}

    async def require_new_purchase(self, db: AsyncSession, sku: str) -> None:
        """Check sale availability only. Never used for renewals or cancellation."""
        if sku not in settings.SUBSCRIPTION_PLANS:
            raise HTTPException(status_code=400, detail="Invalid plan selected")
        result = await db.execute(select(PlanCatalog).where(PlanCatalog.sku == sku))
        row = result.scalar_one_or_none()
        if row is not None and not row.purchase_enabled:
            raise HTTPException(status_code=409, detail="This plan is no longer available for new purchases. Your existing subscription is unchanged.")
        if sku in {"student", "team"} and not await entitlement_service.has_feature(
            "i02", user=SimpleNamespace(role="user", subscription_plan=sku),
        ):
            # Purchase availability belongs to the target SKU. The purchaser's
            # current free family must not block upgrading to an allowed offer.
            raise HTTPException(status_code=403, detail=error_body(
                "feature_disabled", "Student and team purchases are currently unavailable for this plan.", None,
            ))

    async def update(self, db: AsyncSession, sku: str, changes: dict, *, version: int, admin_id: str) -> None:
        default = self.defaults(sku)  # Reject unknown IDs; never invent a new billing SKU.
        if not changes or set(changes) - EDITABLE_FIELDS:
            raise ValueError("Only catalog presentation and new-purchase availability can be edited")
        if sku == "free" and (changes.get("visible") is False or changes.get("purchase_enabled") is False):
            raise ValueError("The free fallback must remain visible and available")
        # Insert/lock ensures optimistic version checks are atomic even when two
        # admins both edit a SKU that has not had a catalog row yet.
        await db.execute(insert(PlanCatalog).values(**default).on_conflict_do_nothing(index_elements=["sku"]))
        result = await db.execute(select(PlanCatalog).where(PlanCatalog.sku == sku).with_for_update())
        row = result.scalar_one()
        if row.version != version:
            await db.rollback()
            raise CatalogConflict("This plan changed. Reload the catalog and review before saving again.")
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_by = admin_id
        db.add(PlanCatalogRevision(
            sku=sku, version=row.version, changed_by=admin_id,
            snapshot={key: getattr(row, key) for key in EDITABLE_FIELDS},
        ))
        await db.commit()


plan_catalog_service = PlanCatalogService()

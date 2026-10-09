"""Admin-only catalog edits. Commercial identities remain operator-managed."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin
from ..services.feature_flag_service import feature_flag_service
from ..services.payment_service import payment_service
from ..services.plan_catalog_service import CatalogConflict, plan_catalog_service
from ..services.quota_policy_service import MAX_QUOTA_LIMIT, QuotaPolicyConflict, quota_policy_service

router = APIRouter()


class PlanCatalogUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, strict=True)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    visible: StrictBool | None = None
    purchase_enabled: StrictBool | None = None
    display_order: int | None = Field(default=None, ge=0, le=1000, strict=True)


@router.get("/admin/plan-catalog")
async def get_plan_catalog(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)) -> dict:
    billing_enabled = await feature_flag_service.get_flag("billing", db)
    return {
        "plans": await plan_catalog_service.list_plans(db, provider_available=payment_service.is_available() and billing_enabled, public=False),
        "editable_fields": sorted(["name", "description", "visible", "purchase_enabled", "display_order"]),
        "pricing_policy": "Prices, currency, billing intervals, provider IDs and SKU families are immutable here. Price changes require an operator-reviewed new configured SKU/version. Existing subscriptions, renewals and refunds are unchanged.",
        "quota_policy": "Compile, optimization and AI-assist limits apply to new admissions for everyone on this exact SKU, including existing subscribers. Changes keep the current usage and reset window; they never reset counters or refunds. Developer API daily limits remain operator-configured. Boolean capability access is managed in the entitlement matrix.",
    }


@router.patch("/admin/plan-catalog/{sku}")
async def update_plan_catalog(
    sku: str, body: PlanCatalogUpdate, db: AsyncSession = Depends(get_db), admin_id: str = Depends(require_admin)
) -> dict:
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Catalog values cannot be null")
    try:
        await plan_catalog_service.update(db, sku, changes, version=body.version, admin_id=admin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown plan SKU")
    except CatalogConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await get_plan_catalog(db, admin_id)


class PlanQuotaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, strict=True)
    limit: Annotated[int, Field(ge=0, le=MAX_QUOTA_LIMIT, strict=True)] | None


@router.patch("/admin/plan-catalog/{sku}/quotas/{dimension}")
async def update_plan_quota(
    sku: str, dimension: str, body: PlanQuotaUpdate,
    db: AsyncSession = Depends(get_db), admin_id: str = Depends(require_admin),
) -> dict:
    try:
        await quota_policy_service.update(db, sku, dimension, limit=body.limit, version=body.version, admin_id=admin_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown plan SKU or quota dimension")
    except QuotaPolicyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await get_plan_catalog(db, admin_id)

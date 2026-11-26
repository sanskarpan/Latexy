"""Owner/admin tenant billing and seat-utilization routes.

Read-only by default.  The only mutation is an audited upgrade-intent click; no
card, payment method, provider credential or subscription is created here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import Tenant
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.tenant_billing_service import (
    build_tenant_billing_snapshot,
    record_upgrade_intent,
)
from .tenant_routes import _require_tenant_owner_or_admin

router = APIRouter(prefix="/tenants", tags=["tenant-billing"])


class TenantBillingPlan(BaseModel):
    plan_id: str
    name: str
    max_seats: int
    tenant_status: Literal["active", "inactive"]
    status_source: Literal["tenant_record"]


class TenantSeatUsage(BaseModel):
    active: int
    invited: Optional[int]
    available: int
    used: int
    max: int
    utilization_percent: float
    over_capacity: int
    invited_available: bool
    invited_reason: Optional[str] = None
    basis: Literal["active_and_invited", "active_only"]


class TenantInviteConversion(BaseModel):
    available: bool
    reason: Optional[str] = None
    minimum_cohort_size: int
    accepted: Optional[int] = None
    invited: Optional[int] = None
    conversion_percent: Optional[float] = None


class TenantSubscriptionView(BaseModel):
    available: bool
    status: Optional[str] = None
    renewal_at: Optional[datetime] = None
    reason: Optional[str] = None
    detail: Optional[str] = None


class TenantUpgradePrompt(BaseModel):
    cta_visible: bool
    threshold_percent: int
    threshold_seats: int
    utilization_percent: float
    target_plan_id: Optional[str] = None
    target_plan_name: Optional[str] = None
    cta_label: Optional[str] = None
    reason: str


class TenantBillingMapping(BaseModel):
    seats: dict[str, Any]
    subscription: dict[str, Any]
    team_seats: dict[str, Any]


class TenantBillingResponse(BaseModel):
    tenant_id: str
    generated_at: datetime
    plan: TenantBillingPlan
    seats: TenantSeatUsage
    invite_conversion: TenantInviteConversion
    subscription: TenantSubscriptionView
    upgrade: TenantUpgradePrompt
    mapping: TenantBillingMapping


class TenantUpgradeIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_plan_id: Optional[str] = Field(default=None, max_length=50)


class TenantUpgradeIntentResponse(BaseModel):
    recorded: bool
    action: str
    tenant_id: str
    target_plan_id: Optional[str] = None
    target_plan_name: Optional[str] = None
    threshold_percent: int
    utilization_percent: float
    message: str


@router.get("/{tenant_id}/billing", response_model=TenantBillingResponse)
async def get_tenant_billing(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantBillingResponse:
    """Return tenant-scoped seat utilization and honest billing availability."""

    tenant: Tenant = await _require_tenant_owner_or_admin(
        tenant_id, user_id, db, lock=False
    )
    snapshot = await build_tenant_billing_snapshot(db, tenant)
    return TenantBillingResponse(**snapshot)


@router.post(
    "/{tenant_id}/billing/upgrade-intent",
    response_model=TenantUpgradeIntentResponse,
)
async def record_tenant_upgrade_intent(
    tenant_id: str,
    body: Optional[TenantUpgradeIntentRequest] = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> TenantUpgradeIntentResponse:
    """Audit one upgrade CTA click. Billing provider calls are never made."""

    tenant: Tenant = await _require_tenant_owner_or_admin(
        tenant_id, user_id, db, lock=False
    )
    # The target is intentionally ignored beyond schema validation: the server
    # re-derives the only valid target plan from tenant-owned facts.
    _ = body
    try:
        result = await record_upgrade_intent(
            db, tenant, actor_user_id=user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The upgrade request could not be recorded",
        ) from exc
    return TenantUpgradeIntentResponse(**result)

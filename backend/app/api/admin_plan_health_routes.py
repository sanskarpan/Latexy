"""Admin-only aggregate weekly/lifetime plan-health surface.

Read-only: no subscription, payment, refund or entitlement is mutated. Risk
flags are advisory and must be reviewed by a human; no customer identifier is
selected into the response.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_plan_health_service import plan_health_snapshot

router = APIRouter()


@router.get("/admin/analytics/plan-health")
async def get_admin_plan_health(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate weekly/lifetime counts, revenue, retention and risk flags."""

    return await plan_health_snapshot(db, days=days)

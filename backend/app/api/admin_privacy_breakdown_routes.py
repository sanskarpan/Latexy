"""Admin-only privacy-safe device/browser/OS/country breakdown read surface.

The route is read-only and aggregate-only. It never returns a raw IP, a full
user-agent string, an account id, a city/region, or a per-user location
history. The service applies the five-session/signup cohort suppression.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.admin_privacy_breakdown_service import (
    admin_privacy_breakdown_service,
)

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


@router.get("/privacy-breakdowns")
async def get_admin_privacy_breakdowns(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Sessions/page views and signups by device, browser, OS and country."""

    try:
        return await admin_privacy_breakdown_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

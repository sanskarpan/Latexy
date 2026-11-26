"""Admin-only team-seat utilization and invite-to-active analytics (issue #2110).

Read-only and aggregate-only. The endpoint requires an admin actor, reads the
existing team_seats/tenants/subscriptions tables, and never returns an invitee
email, an invitee account id, an invite token or another tenant's seats.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_team_seat_service import admin_team_seat_service

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


@router.get("/team-seats")
async def get_admin_team_seat_utilization(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    owner_id: str | None = Query(default=None, max_length=64),
    tenant_id: str | None = Query(default=None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate seat states, conversion, aging, utilization and tenant caps."""

    try:
        return await admin_team_seat_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            owner_id=owner_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

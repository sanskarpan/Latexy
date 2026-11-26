"""Admin-only editor mode adoption, compile outcomes and SyncTeX usage (issue #2077)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.editor_mode_analytics_service import editor_mode_analytics_service

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


@router.get("/editor-modes")
async def get_admin_editor_modes(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    plan: Optional[str] = Query(None, max_length=32),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate mode adoption, compile success/latency and tool usage."""

    try:
        return await editor_mode_analytics_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

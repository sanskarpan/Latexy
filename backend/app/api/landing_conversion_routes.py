"""Admin landing-conversion read surface.

The route is read-only and aggregate-only. It never returns a path, query
string, share token, account id, device fingerprint, email, or document content.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.landing_conversion_service import landing_conversion_service

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])


@router.get("/landing-conversion")
async def get_admin_landing_conversion(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Landing visits and same-device conversion by page, variant, and device."""

    return await landing_conversion_service.snapshot(db, days=days)

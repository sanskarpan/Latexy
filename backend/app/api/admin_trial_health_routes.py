"""Admin-only aggregate trial-health surface.

The response is aggregate-only: it contains no raw device fingerprint, IP,
account id, email, token or document field. The route is read-only and does
not call ``trial_service`` enforcement or mutate trial state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.trial_health_service import snapshot

router = APIRouter()


@router.get("/admin/analytics/trial-health")
async def get_admin_trial_health(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return 7/30/90-day trial starts, abuse signals and conversions."""

    return await snapshot(db)

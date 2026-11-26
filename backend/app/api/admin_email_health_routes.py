"""Admin-only aggregate email delivery health.

The view never selects recipient addresses, subjects, provider payloads or
document content. It exposes counts, rates (with five-outcome suppression),
bounded bounce labels, recent failure metadata and current suppression state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.email_health_service import email_health

router = APIRouter(prefix="/admin/email", tags=["admin", "email"])


@router.get("/health")
async def get_admin_email_health(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Bounce/complaint rates, recent failures and suppression status."""
    return await email_health(db, days=days)

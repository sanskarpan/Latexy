"""Admin-only checkout funnel and failure-reason endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.checkout_funnel_service import checkout_funnel_service

router = APIRouter()
logger = get_logger(__name__)


@router.get("/admin/billing/checkout-funnel")
async def get_admin_checkout_funnel(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate checkout conversion and normalized failure buckets."""

    try:
        return await checkout_funnel_service.funnel(db, days=days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

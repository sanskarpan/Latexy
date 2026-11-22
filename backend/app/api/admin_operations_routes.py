"""Admin-only operational visibility: attention queue and health aggregate."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_operations_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()


@router.get("/admin/operations/attention")
async def get_admin_attention(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await admin_operations_service.get_attention(db)


@router.get("/admin/operations/health")
async def get_admin_operations_health(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await admin_operations_service.get_health(db)

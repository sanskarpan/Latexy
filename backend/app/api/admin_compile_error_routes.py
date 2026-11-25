"""Admin-only compile-error taxonomy: top errors, affected templates, trend."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_compile_error_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()


@router.get("/admin/analytics/compile-errors")
async def get_admin_compile_errors(
    days: int = Query(30, ge=1, le=365),
    plan: Optional[str] = Query(None, max_length=50),
    compiler: Optional[str] = Query(None, max_length=32),
    template: Optional[str] = Query(None, max_length=64),
    error_class: Optional[str] = Query(None, max_length=32),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate compile-error classes, templates and daily trend."""
    try:
        return await admin_compile_error_service.compile_error_snapshot(
            db,
            days=days,
            plan=plan,
            compiler=compiler,
            template=template,
            error_class=error_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

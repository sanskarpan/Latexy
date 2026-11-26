"""Admin-only document complexity and compile failure-class distributions."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_document_complexity_service import document_complexity_snapshot

router = APIRouter()


@router.get("/admin/analytics/document-complexity")
async def get_admin_document_complexity(
    days: int = Query(30, ge=1, le=365),
    plan: Optional[str] = Query(None, max_length=50),
    compiler: Optional[str] = Query(None, max_length=32),
    template: Optional[str] = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate page/section/latency/error-class distributions.

    Only bounded metadata counts are returned; document content and compile
    error text never leave the database through this endpoint.
    """
    try:
        return await document_complexity_snapshot(
            db,
            days=days,
            plan=plan,
            compiler=compiler,
            template=template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

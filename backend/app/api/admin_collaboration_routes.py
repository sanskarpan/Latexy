"""Admin-only aggregate collaboration usage analytics (C10 / #2080).

Kept in a dedicated router so the collaboration read surface cannot grow any
mutation or document-content endpoints. Every response is aggregate-only; the
service never selects comment text, reviewer labels, emails or document bodies.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_collaboration_analytics_service import (
    admin_collaboration_analytics_service,
)

router = APIRouter()


@router.get("/admin/analytics/collaboration")
async def get_admin_collaboration_analytics(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    tenant_id: Optional[str] = Query(None, max_length=36),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate collaboration metrics with tenant and cohort drill-down."""
    try:
        return await admin_collaboration_analytics_service.collaboration_usage(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

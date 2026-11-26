"""Admin-only coupon and student-verification performance endpoint.

The route is read-only and requires the full admin gate.  It returns aggregates
only and never exposes a student email, verification token, account id, IP
address, user agent, document or raw event metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.coupon_student_analytics_service import (
    coupon_student_analytics_service,
)

router = APIRouter(tags=["admin-revenue"])
logger = get_logger(__name__)


@router.get("/admin/revenue/coupon-student-performance")
@router.get("/admin/billing/coupon-student-performance", include_in_schema=False)
async def get_coupon_student_performance(
    days: int = Query(30, ge=1, le=365),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    plan: Optional[str] = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Redemption, conversion, expiry, abuse-review and student funnel metrics."""

    try:
        return await coupon_student_analytics_service.performance(db, days=days, start=start, end=end, plan=plan)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

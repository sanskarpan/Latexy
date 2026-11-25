"""Admin product analytics: feature adoption matrix by plan, role, and cohort."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_feature_adoption_service import admin_feature_adoption_service

router = APIRouter()


@router.get("/admin/analytics/feature-adoption")
async def get_admin_feature_adoption(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=300),
    role: Optional[str] = Query(None, max_length=120),
    cohort: Optional[str] = Query(None, max_length=300),
    feature: Optional[str] = Query(None, max_length=120),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate registry feature adoption by plan, account role and signup cohort."""
    try:
        return await admin_feature_adoption_service.feature_adoption(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
            role=role,
            cohort=cohort,
            feature=feature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

"""Admin-only adoption and cross-sell report for career-adjacent features."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_career_adoption_service import admin_career_adoption_service

router = APIRouter()


async def _load_report(
    *,
    days: int,
    start_date: Optional[date],
    end_date: Optional[date],
    plan: Optional[str],
    cohort: Optional[str],
    db: AsyncSession,
) -> dict[str, Any]:
    try:
        return await admin_career_adoption_service.adoption_report(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
            cohort=cohort,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/analytics/career-adoption")
async def get_admin_career_adoption(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=300),
    cohort: Optional[str] = Query(None, max_length=300),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate cover-letter, interview-prep and career-path adoption.

    Returns distinct users, runs, repeat use and post-optimization cross-sell by
    plan and signup cohort.  Only counts leave the endpoint; generated content
    and per-user identifiers are never returned.
    """
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        cohort=cohort,
        db=db,
    )


@router.get(
    "/admin/analytics/career-feature-adoption",
    include_in_schema=False,
)
async def get_admin_career_feature_adoption(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=300),
    cohort: Optional[str] = Query(None, max_length=300),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Compatibility alias for operators with an existing bookmark."""
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        plan=plan,
        cohort=cohort,
        db=db,
    )

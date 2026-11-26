"""Admin-only ATS score distribution and before/after improvement report."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_ats_score_service import admin_ats_score_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()


async def _load_report(
    *,
    days: int,
    start_date: Optional[date],
    end_date: Optional[date],
    industry: Optional[str],
    profile: Optional[str],
    plan: Optional[str],
    db: AsyncSession,
) -> dict[str, Any]:
    try:
        return await admin_ats_score_service.distribution_report(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            industry=industry,
            profile=profile,
            plan=plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/analytics/ats-score-distribution")
async def get_admin_ats_score_distribution(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    industry: Optional[str] = Query(None, max_length=1000),
    profile: Optional[str] = Query(None, max_length=1000),
    plan: Optional[str] = Query(None, max_length=500),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate ATS score buckets and before/after improvement.

    Only numeric scores and bounded classification keys are returned. Resume
    content, job descriptions and user identities are never exposed.
    """
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        industry=industry,
        profile=profile,
        plan=plan,
        db=db,
    )


@router.get(
    "/admin/analytics/ats-scores",
    include_in_schema=False,
)
async def get_admin_ats_scores_alias(
    days: int = Query(30, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    industry: Optional[str] = Query(None, max_length=1000),
    profile: Optional[str] = Query(None, max_length=1000),
    plan: Optional[str] = Query(None, max_length=500),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Compatibility alias for operators with an existing bookmark."""
    return await _load_report(
        days=days,
        start_date=start_date,
        end_date=end_date,
        industry=industry,
        profile=profile,
        plan=plan,
        db=db,
    )

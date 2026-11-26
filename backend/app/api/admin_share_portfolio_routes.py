"""Admin-only public share and portfolio performance analytics (issue #2082).

Every endpoint is read-only and aggregate-only. Responses contain no raw IP,
viewer identifier, user-agent, email, name, share token, or document text.
Cohorts smaller than five distinct hashed viewers are suppressed by the
service. Mutations are not exposed here, so there is no audit write path.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.share_portfolio_analytics_service import (
    aggregate,
    normalize_resume_id,
    portfolio_breakdown,
    resume_breakdown,
)

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

_PLAN_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,49}$"
_PORTFOLIO_PATTERN = r"^[A-Za-z0-9_-]{3,30}$"


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get("/share-portfolio")
async def get_admin_share_portfolio(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    plan: str | None = Query(default=None, max_length=50, pattern=_PLAN_PATTERN),
    portfolio: str | None = Query(
        default=None, min_length=1, max_length=30, pattern=_PORTFOLIO_PATTERN
    ),
    resume_id: str | None = Query(default=None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate share views and the portfolio view -> contact -> signup funnel."""

    try:
        return await aggregate(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
            portfolio=portfolio,
            resume_id=resume_id,
        )
    except (LookupError, ValueError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover - _raise_http always raises


@router.get("/share-portfolio/resumes/{resume_id}")
async def get_admin_share_portfolio_resume(
    resume_id: str,
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    plan: str | None = Query(default=None, max_length=50, pattern=_PLAN_PATTERN),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Per-resume share drill-down with the same privacy boundaries."""

    from ..database.models import Resume

    try:
        canonical_resume_id = normalize_resume_id(resume_id)
    except ValueError as exc:
        _raise_http(exc)
        raise  # pragma: no cover - _raise_http always raises
    if canonical_resume_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="resume_id must be a UUID",
        )
    exists = await db.scalar(
        select(Resume.id).where(Resume.id == canonical_resume_id)
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resume not found"
        )
    try:
        return await resume_breakdown(
            db,
            resume_id=canonical_resume_id,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
        )
    except (LookupError, ValueError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover - _raise_http always raises


@router.get("/share-portfolio/portfolios/{username}")
async def get_admin_share_portfolio_portfolio(
    username: str,
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    plan: str | None = Query(default=None, max_length=50, pattern=_PLAN_PATTERN),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Per-portfolio share and funnel drill-down."""

    try:
        return await portfolio_breakdown(
            db,
            username=username,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
        )
    except (LookupError, ValueError) as exc:
        _raise_http(exc)
        raise  # pragma: no cover - _raise_http always raises

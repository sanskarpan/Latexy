"""Admin-only dunning and recovery reporting.

The endpoint is read-only. It returns aggregate counts, recovery rates and
median time-to-outcome from the append-only
``subscription_status_history`` ledger plus the current subscription snapshot.
It never downgrades, refunds or grants access, and it never returns an account
identifier, email, document or provider payload.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.dunning_history_service import dunning_recovery_analytics

router = APIRouter()


async def _report(
    *,
    db: AsyncSession,
    days: int,
    start: datetime | None,
    end: datetime | None,
    signup_month: str | None,
    signup_from: date | None,
    signup_to: date | None,
    plan: str | None,
) -> dict[str, Any]:
    try:
        return await dunning_recovery_analytics(
            db,
            days=days,
            start=start,
            end=end,
            signup_month=signup_month,
            signup_from=signup_from,
            signup_to=signup_to,
            plan=plan,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/admin/billing/dunning-recovery")
@router.get("/admin/billing/dunning/recovery", include_in_schema=False)
@router.get("/admin/billing/dunning", include_in_schema=False)
@router.get("/admin/subscriptions/dunning", include_in_schema=False)
@router.get("/admin/analytics/dunning-recovery", include_in_schema=False)
@router.get("/admin/dunning/recovery", include_in_schema=False)
@router.get("/admin/dunning", include_in_schema=False)
async def get_admin_dunning_recovery(
    days: int = Query(30, ge=1, le=365),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    signup_month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    signup_from: Optional[date] = Query(None),
    signup_to: Optional[date] = Query(None),
    plan: Optional[str] = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Past-due/on-hold counts, recovery rate and median time to outcome."""

    return await _report(
        db=db,
        days=days,
        start=start,
        end=end,
        signup_month=signup_month,
        signup_from=signup_from,
        signup_to=signup_to,
        plan=plan,
    )

"""Admin-only subscription history analytics.

The endpoint reads only the append-only ``subscription_history`` ledger and the
current ``subscriptions`` table. It never parses webhook logs, PostHog events or
admin audit rows for financial metrics, and it returns aggregates only.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.subscription_history_service import subscription_history_service

router = APIRouter()


@router.get("/admin/subscriptions/analytics")
async def get_admin_subscription_analytics(
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
    """Plan mix, plan movement, cancellations and churn by signup cohort."""

    try:
        return await subscription_history_service.subscription_analytics(
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

"""Admin-only daily metrics rollup and refresh-freshness payload (issue #2181).

Read-only, aggregate-only. The service returns global daily counts and INR
minor-unit totals; no user ids, documents, prompts, tokens, raw IPs, user
agents or provider payloads can be selected through this route.

There is intentionally no manual refresh or mutation endpoint: the scheduled
worker owns writes, so an admin request cannot trigger an unbounded recompute.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_daily_metrics_service import daily_metrics_report

router = APIRouter()


@router.get("/admin/analytics/daily-metrics")
async def get_admin_daily_metrics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return the daily rollup, freshness/source, totals and suppression notes."""
    return await daily_metrics_report(db, days=days)

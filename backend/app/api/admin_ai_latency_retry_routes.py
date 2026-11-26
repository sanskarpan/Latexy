"""Admin-only AI latency and retry report.

Aggregate-only p50/p95/p99 latency, retry rate and timeout/error rate for the
7/30/90-day windows used by the admin analytics surface. The handler is
protected by the same admin actor guard as every other analytics endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_ai_latency_retry_service import ai_latency_retry_snapshot
from ..services.admin_audit_service import AdminActor

router = APIRouter()


@router.get("/admin/analytics/ai-latency-retry")
async def get_admin_ai_latency_retry(
    days: int = Query(30, ge=1, le=365),
    plan: Optional[str] = Query(None, max_length=50),
    feature: Optional[str] = Query(None, max_length=120),
    provider: Optional[str] = Query(None, max_length=64),
    model: Optional[str] = Query(None, max_length=160),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate LLM latency percentiles and retry/error rates."""
    try:
        return await ai_latency_retry_snapshot(
            db,
            days=days,
            plan=plan,
            feature=feature,
            provider=provider,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

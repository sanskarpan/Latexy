"""Admin-only integration adoption and failure analytics (issue #2081).

Read-only and aggregate-only. Every response comes from the integration
analytics service, which suppresses cohorts below five users and never returns
OAuth tokens, refresh tokens, emails, filenames, account handles, provider error
bodies, IP addresses, or user-agent strings.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.integration_analytics_service import snapshot

router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

_PLAN_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,49}$"
_PROVIDER_PATTERN = r"^(github|dropbox|google_drive|zotero|mendeley)$"


@router.get("/integrations")
async def get_admin_integrations(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    plan: str | None = Query(default=None, max_length=50, pattern=_PLAN_PATTERN),
    provider: str | None = Query(default=None, max_length=32, pattern=_PROVIDER_PATTERN),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate integration adoption, OAuth conversion and sync health."""

    try:
        return await snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            plan=plan,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

"""Admin-only live activity feed endpoint.

The route is a thin validation layer over
:mod:`app.services.admin_activity_service`. It is intentionally separate from
``analytics_routes.py`` so the live-feed cursor contract can evolve without
touching the broader analytics payload.

Access is restricted to admin actors. Responses are aggregate-safe projections:
typed category, opaque event/entity id, event name, timestamp and an optional
internal deep link. No user ids, metadata values, document content, prompts,
emails, IP addresses or payment credentials are returned.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_activity_service
from ..services.admin_audit_service import AdminActor

router = APIRouter(prefix="/admin/analytics", tags=["admin-activity"])

ActivityCategory = Literal["signup", "payment", "compile", "optimize", "error"]


class AdminActivityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: ActivityCategory
    event: str
    created_at: str
    href: str | None


class AdminActivityFeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AdminActivityEvent]
    next_cursor: str | None
    has_more: bool
    mode: Literal["live", "fallback"]
    degraded: bool
    detail: str | None
    generated_at: str


@router.get("/activity", response_model=AdminActivityFeedResponse)
async def get_admin_activity_feed(
    response: Response,
    cursor: str | None = Query(
        default=None,
        max_length=admin_activity_service.MAX_CURSOR_LENGTH,
        description="Opaque cursor returned by the previous page.",
    ),
    limit: int = Query(
        default=admin_activity_service.DEFAULT_ACTIVITY_LIMIT,
        ge=1,
        le=admin_activity_service.MAX_ACTIVITY_LIMIT,
    ),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict:
    """Return a bounded, redacted activity page for the admin Analytics tab."""

    response.headers["Cache-Control"] = "no-store"
    try:
        return await admin_activity_service.get_activity_feed(
            db,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None

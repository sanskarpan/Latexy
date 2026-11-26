"""First-party consent choice capture and admin consent reporting (issue #2138).

The capture route is intentionally unauthenticated: a visitor must be able to
record a denial or withdrawal without signing in, and the record must not depend
on PostHog being configured or loaded. The request model forbids unknown fields,
so a client cannot smuggle an email, name, document text, replay payload, IP
address, or user agent into the consent row.

The admin route is read-only, aggregate-only, and admin-only. It never returns an
account id, anonymous id, session id, email, name, document text, or replay
payload. Counts with a cohort of 1-4 are suppressed.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.consent_analytics_service import consent_analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

ConsentDecision = Literal["granted", "denied", "withdrawn"]
ConsentSurface = Literal[
    "banner",
    "privacy_choices",
    "privacy_page",
    "settings",
    "footer",
    "other",
    "unknown",
]


class ConsentEventRequest(BaseModel):
    """Only allowlisted consent fields; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    decision: ConsentDecision
    surface: ConsentSurface = "unknown"
    anonymous_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    event_id: str | None = Field(default=None, max_length=128)


@router.post("/consent", status_code=status.HTTP_202_ACCEPTED)
async def record_consent_event(
    payload: ConsentEventRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist one privacy-safe analytics consent choice.

    No IP address or user agent is read from the request. The server timestamp
    is authoritative; the client cannot supply a time, account id, or metadata.
    """

    try:
        return await consent_analytics_service.record_event(
            db,
            decision=payload.decision,
            surface=payload.surface,
            anonymous_id=payload.anonymous_id,
            session_id=payload.session_id,
            event_id=payload.event_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@admin_router.get("/consent")
async def get_admin_consent_analytics(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Grant/deny/withdraw counts by day and surface with replay coverage."""

    try:
        return await consent_analytics_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

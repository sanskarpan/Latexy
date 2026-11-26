"""Onboarding step analytics ingestion and admin reporting (issue #2074).

The capture route is authenticated because onboarding is an account flow. It
also requires a current first-party analytics grant for the opaque browser id
supplied with the event, so a denial or withdrawal stops capture server-side.
The request model forbids unknown fields; a client cannot smuggle form contents,
a name, an email, document text, IP address, user agent, or free-form metadata
into the stored JSONB.

The admin route is read-only, aggregate-only, and admin-only. It returns no
account id, event id, anonymous id, email, name, document text, or free-form
event metadata. Cohorts of 1-4 accounts are suppressed.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.onboarding_analytics_service import (
    DEFAULT_FLOW_VERSION,
    MAX_DURATION_MS,
    ConsentRequiredError,
    onboarding_analytics_service,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

OnboardingEventAction = Literal[
    "onboarding_step_viewed",
    "onboarding_step_completed",
    "onboarding_step_skipped",
]
OnboardingStepKey = Literal["welcome", "how-it-works", "features", "get-started"]
CompletionSource = Literal[
    "next",
    "cta",
    "link",
    "skip",
    "escape",
    "backdrop",
    "close",
    "unknown",
]


class OnboardingStepEventRequest(BaseModel):
    """Exactly the client fields this event family accepts."""

    model_config = ConfigDict(extra="forbid")

    action: OnboardingEventAction
    step_key: OnboardingStepKey
    flow_version: str = Field(
        default=DEFAULT_FLOW_VERSION,
        min_length=1,
        max_length=16,
        pattern=r"^v[0-9]{1,3}(?:\.[0-9]{1,3})?$",
    )
    duration_ms: int | None = Field(default=None, ge=0, le=MAX_DURATION_MS)
    completion_source: CompletionSource | None = None
    event_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    anonymous_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


@router.post("/onboarding/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_onboarding_event(
    payload: OnboardingStepEventRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Record one privacy-safe onboarding step event for the signed-in account."""

    try:
        return await onboarding_analytics_service.record_event(
            db,
            user_id=user_id,
            action=payload.action,
            step_key=payload.step_key,
            flow_version=payload.flow_version,
            duration_ms=payload.duration_ms,
            completion_source=payload.completion_source,
            event_id=payload.event_id,
            anonymous_id=payload.anonymous_id,
        )
    except ConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analytics consent is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@admin_router.get("/onboarding")
async def get_admin_onboarding_analytics(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    flow_version: str | None = Query(
        default=None,
        min_length=1,
        max_length=16,
        pattern=r"^v[0-9]{1,3}(?:\.[0-9]{1,3})?$",
    ),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Per-step views, completions, skips, drop-off, time and plan/provider segments."""

    try:
        return await onboarding_analytics_service.snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
            flow_version=flow_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

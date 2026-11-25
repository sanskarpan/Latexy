"""Consented trial attribution claim and the admin cohort read surface.

The claim route accepts only explicit consent and an opaque device fingerprint;
campaign values are read from the server-stored landing row keyed by the
HttpOnly first-party visitor cookie. The admin route is aggregate-only and
never selects an email, name, raw fingerprint, IP, user-agent, token or
document identifier.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.traffic_source_service import VISITOR_COOKIE_NAME, is_valid_visitor_id
from ..services.trial_attribution_service import claim_trial_attribution, snapshot

router = APIRouter(prefix="/analytics/trial", tags=["analytics"])
admin_router = APIRouter()


class TrialAttributionClaimRequest(BaseModel):
    """Explicit consent plus the opaque device key used by the anonymous trial."""

    model_config = ConfigDict(extra="forbid")

    device_fingerprint: str = Field(min_length=1, max_length=255)
    consent_granted: bool = False


def _request_visitor_id(request: Request) -> str | None:
    value = request.cookies.get(VISITOR_COOKIE_NAME)
    return value if is_valid_visitor_id(value) else None


@router.post("/claim", status_code=status.HTTP_202_ACCEPTED)
async def claim_trial_attribution_endpoint(
    payload: TrialAttributionClaimRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Link the current account to its anonymous trial and paid subscription."""

    return await claim_trial_attribution(
        db,
        user_id=user_id,
        device_fingerprint=payload.device_fingerprint,
        consent_granted=payload.consent_granted,
        visitor_id=_request_visitor_id(request),
    )


@admin_router.get("/admin/analytics/trial-attribution")
async def get_admin_trial_attribution(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate trial-start -> signup -> paid cohorts by source, plan and month."""

    try:
        return await snapshot(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

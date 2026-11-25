"""Traffic-source capture and admin aggregation endpoints.

The public capture endpoint accepts only the five allowlisted UTM keys, a
sanitized landing path and an external referrer host. The values are validated
again in :mod:`app.services.traffic_source_service` because this route is
unauthenticated. The claim endpoint reads a server-issued HttpOnly visitor
cookie; it never accepts a client-supplied campaign value at signup time.

The admin route is a dedicated router (``/admin/analytics/traffic-sources``)
and returns aggregate-only rows. It never selects email, name, IP, user-agent,
token, or document columns.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.traffic_source_service import (
    UTM_MAX_LENGTH,
    UTM_PATTERN,
    VISITOR_COOKIE_MAX_AGE,
    VISITOR_COOKIE_NAME,
    aggregate,
    capture_landing,
    claim_signup,
    is_valid_visitor_id,
    new_visitor_id,
)

router = APIRouter(prefix="/analytics/traffic", tags=["analytics"])
admin_router = APIRouter()

_UTM_PATTERN = UTM_PATTERN.pattern


class LandingCaptureRequest(BaseModel):
    """Only allowlisted attribution fields; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    landing_path: str = Field(default="/", max_length=512)
    referrer: str | None = Field(default=None, max_length=2048)
    session_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
    )
    utm_source: str | None = Field(default=None, max_length=UTM_MAX_LENGTH, pattern=_UTM_PATTERN)
    utm_medium: str | None = Field(default=None, max_length=UTM_MAX_LENGTH, pattern=_UTM_PATTERN)
    utm_campaign: str | None = Field(default=None, max_length=UTM_MAX_LENGTH, pattern=_UTM_PATTERN)
    utm_content: str | None = Field(default=None, max_length=UTM_MAX_LENGTH, pattern=_UTM_PATTERN)
    utm_term: str | None = Field(default=None, max_length=UTM_MAX_LENGTH, pattern=_UTM_PATTERN)


def _request_visitor_id(request: Request) -> str | None:
    value = request.cookies.get(VISITOR_COOKIE_NAME)
    return value if is_valid_visitor_id(value) else None


def _set_visitor_cookie(response: Response, request: Request, visitor_id: str) -> None:
    response.set_cookie(
        VISITOR_COOKIE_NAME,
        visitor_id,
        max_age=VISITOR_COOKIE_MAX_AGE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


@router.post("/landing", status_code=status.HTTP_202_ACCEPTED)
async def record_traffic_landing(
    payload: LandingCaptureRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist one first-party landing event before URL query sanitization."""

<<<<<<< HEAD
    existing_visitor_id = _request_visitor_id(request)
    visitor_id = existing_visitor_id or new_visitor_id()
=======
    visitor_id = _request_visitor_id(request) or new_visitor_id()
>>>>>>> origin/t3/trial-to-paid-cohort-attribution
    utm = {
        "utm_source": payload.utm_source,
        "utm_medium": payload.utm_medium,
        "utm_campaign": payload.utm_campaign,
        "utm_content": payload.utm_content,
        "utm_term": payload.utm_term,
    }
    try:
        result = await capture_landing(
            db,
            visitor_id=visitor_id,
            session_id=payload.session_id,
            utm=utm,
            landing_path=payload.landing_path,
            referrer=payload.referrer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

<<<<<<< HEAD
    # Only a server-generated UUID is ever written back as a cookie. An existing
    # client cookie is validated for lookup but never echoed into Set-Cookie.
    if existing_visitor_id is None:
        _set_visitor_cookie(response, request, visitor_id)
=======
    _set_visitor_cookie(response, request, visitor_id)
>>>>>>> origin/t3/trial-to-paid-cohort-attribution
    return result


@router.post("/claim", status_code=status.HTTP_202_ACCEPTED)
async def claim_traffic_attribution(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Attach the server-stored first-touch landing to the signed-in account."""

    try:
        return await claim_signup(
            db,
            user_id=user_id,
            visitor_id=_request_visitor_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@admin_router.get("/admin/analytics/traffic-sources")
async def get_admin_traffic_sources(
    days: int = Query(30, ge=1, le=366),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate sessions, signups, and paid conversion by traffic source."""

    try:
        return await aggregate(
            db,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

"""Consent-gated public portfolio performance capture (issue #2082).

These endpoints write only to the existing ``usage_analytics`` JSONB store, so
no schema migration is required. They accept a single allowlisted field -- the
visitor's analytics-consent attestation -- and derive the viewer key, referrer
host, and country on the server. No raw IP address or user-agent is persisted,
and no document content, contact message, email, or name can enter analytics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required
from ..services.share_portfolio_analytics_service import (
    PORTFOLIO_CONTACT_ACTION,
    PORTFOLIO_VIEW_ACTION,
    claim_portfolio_signup,
    record_portfolio_event,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_USERNAME_PATTERN = r"^[A-Za-z0-9_-]{3,30}$"


class PortfolioAnalyticsConsentRequest(BaseModel):
    """Only the explicit consent attestation is accepted from the caller."""

    model_config = ConfigDict(extra="forbid")

    analytics_consent: bool = False


@router.post(
    "/analytics/claim-signup",
    status_code=status.HTTP_202_ACCEPTED,
)
async def claim_portfolio_signup_attribution(
    request: Request,
    payload: PortfolioAnalyticsConsentRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Link this new account to its consent-gated portfolio visit, once."""

    try:
        return await claim_portfolio_signup(
            db,
            user_id=user_id,
            request=request,
            analytics_consent=payload.analytics_consent,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/{username}/analytics/view",
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_portfolio_view(
    request: Request,
    payload: PortfolioAnalyticsConsentRequest,
    username: str = Path(
        ..., min_length=3, max_length=30, pattern=_USERNAME_PATTERN
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record one consent-gated portfolio page view."""

    try:
        return await record_portfolio_event(
            db,
            action=PORTFOLIO_VIEW_ACTION,
            username=username,
            request=request,
            analytics_consent=payload.analytics_consent,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(
    "/{username}/analytics/contact",
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_portfolio_contact(
    request: Request,
    payload: PortfolioAnalyticsConsentRequest,
    username: str = Path(
        ..., min_length=3, max_length=30, pattern=_USERNAME_PATTERN
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record one consent-gated contact-form submission for the funnel."""

    try:
        return await record_portfolio_event(
            db,
            action=PORTFOLIO_CONTACT_ACTION,
            username=username,
            request=request,
            analytics_consent=payload.analytics_consent,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

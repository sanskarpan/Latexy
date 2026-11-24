"""Signup funnel telemetry endpoints.

Provider attribution for accounts is resolved from server-owned auth state. The
two anonymous endpoints accept only the six-value allowlist (Pydantic rejects
anything else) and store no user identity, email, token or free-form text, so a
caller cannot attach a provider to an account.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import (
    get_current_user_optional,
    get_current_user_required,
)
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.signup_funnel_service import signup_funnel_service

logger = get_logger(__name__)

router = APIRouter(prefix="/analytics/signup", tags=["analytics"])

AuthProvider = Literal["email", "google", "github", "oidc", "passkey", "unknown"]
OAuthFailureCode = Literal[
    "access_denied",
    "account_not_linked",
    "callback_failed",
    "provider_error",
    "state_mismatch",
    "unknown",
]


class SignupStartedRequest(BaseModel):
    # Anonymous attempt label only. Authenticated requests ignore it and derive
    # the provider from the server-owned account rows instead.
    provider: Optional[AuthProvider] = None


class OAuthFailureRequest(BaseModel):
    provider: AuthProvider
    failure_code: Optional[OAuthFailureCode] = None


class SignupMilestonesResponse(BaseModel):
    provider: str
    email_verified: bool
    recorded: list[str]


@router.post("/started", status_code=status.HTTP_202_ACCEPTED)
async def record_signup_started(
    payload: SignupStartedRequest | None = None,
    user_id: Optional[str] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Record a signup attempt without accepting account attribution."""

    provider = await signup_funnel_service.record_signup_started(
        db,
        user_id=user_id,
        provider=payload.provider if payload else None,
    )
    return {"recorded": "signup_started", "provider": provider}


@router.post("/oauth-failure", status_code=status.HTTP_202_ACCEPTED)
async def record_oauth_failure(
    payload: OAuthFailureRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Count an OAuth failure by allowlisted provider, never by identity."""

    provider = await signup_funnel_service.record_oauth_failure(
        db,
        provider=payload.provider,
        failure_code=payload.failure_code,
    )
    return {"recorded": "oauth_failure", "provider": provider}


@router.post("/milestones", response_model=SignupMilestonesResponse)
async def record_signup_milestones(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> SignupMilestonesResponse:
    """Idempotently record completion and verification for the session user."""

    try:
        result = await signup_funnel_service.record_signup_milestones(db, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SignupMilestonesResponse(**result)

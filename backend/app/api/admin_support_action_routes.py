"""Admin-only support delivery actions for one customer.

Kept separate from ``admin_control_routes`` so the existing billing/User 360
surface stays stable. Every mutation here requires a reason, an explicit
confirmation, an admin actor, and writes append-only audit rows. Tokens and
one-time links never appear in a response, audit row or log.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_support_action_service as support_actions
from ..services.admin_audit_service import AdminActor

router = APIRouter()
logger = get_logger(__name__)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class SupportEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    confirm: Literal[True]


class SupportReceiptRequest(SupportEmailRequest):
    payment_id: str = Field(min_length=1, max_length=255)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        message = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, support_actions.SupportActionNotEligible):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, support_actions.SupportActionCooldown):
        return HTTPException(
            status_code=429,
            detail="A support email was sent recently; wait before trying again",
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, support_actions.SupportActionProviderError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, support_actions.SupportActionUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    logger.error("Admin support action failed", extra={"error_type": type(exc).__name__})
    return HTTPException(status_code=503, detail="The support action could not be completed")


@router.get("/admin/users/{user_id}/payments/{payment_id}/receipt")
async def get_admin_payment_receipt(
    user_id: str,
    payment_id: str,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Normalised receipt lookup by local or provider payment id."""
    try:
        return await support_actions.get_payment_receipt(db, user_id=user_id, payment_id=payment_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/support/resend-verification")
async def resend_admin_verification_email(
    user_id: str,
    body: SupportEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await support_actions.resend_verification_email(
            db,
            user_id=user_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/support/password-reset")
async def send_admin_password_reset(
    user_id: str,
    body: SupportEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await support_actions.send_password_reset_email(
            db,
            user_id=user_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/users/{user_id}/support/resend-receipt")
async def resend_admin_payment_receipt(
    user_id: str,
    body: SupportReceiptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await support_actions.resend_payment_receipt(
            db,
            user_id=user_id,
            payment_id=body.payment_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc

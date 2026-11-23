"""Billing reconciliation queue and safe provider replay endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_billing_service import admin_billing_service

router = APIRouter()
logger = get_logger(__name__)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ReplayWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    # ``confirm`` is the preferred spelling; ``confirmed`` keeps clients that
    # already use the past-tense form from bypassing the safety prompt.
    confirm: bool = False
    confirmed: bool = False

    @model_validator(mode="after")
    def _require_confirmation(self):
        if not (self.confirm or self.confirmed):
            raise ValueError("Replay confirmation is required")
        return self


class AcknowledgeReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[Reason] = None
    note: Optional[Reason] = None

    @model_validator(mode="after")
    def _require_reason(self):
        if not (self.reason or self.note):
            raise ValueError("An acknowledgement reason is required")
        return self

    @property
    def text(self) -> str:
        return self.reason or self.note or ""


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        message = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    logger.error("Admin billing reconciliation action failed", extra={"error_type": type(exc).__name__})
    return HTTPException(status_code=503, detail="The admin action could not be completed")


async def _replay(
    *,
    event_id: str,
    body: ReplayWebhookRequest,
    request: Request,
    db: AsyncSession,
    actor: AdminActor,
) -> dict[str, Any]:
    if not await admin_billing_service.allow_webhook_replay(actor.user_id, event_id):
        raise HTTPException(
            status_code=429,
            detail="Too many replay attempts for this event; wait before trying again",
        )
    try:
        return await admin_billing_service.replay_webhook(
            db,
            event_id=event_id,
            actor=actor,
            reason=body.reason,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/admin/billing/reconciliation")
async def list_admin_billing_reconciliation(
    received_after: Optional[datetime] = Query(None),
    received_before: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        items, total = await admin_billing_service.list_reconciliation(
            db,
            received_after=received_after,
            received_before=received_before,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/admin/billing/reconciliation/{event_id}/acknowledge")
async def acknowledge_admin_billing_reconciliation(
    event_id: str,
    body: AcknowledgeReconciliationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_billing_service.acknowledge_webhook(
            db,
            event_id=event_id,
            actor=actor,
            note=body.text,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/billing/reconciliation/{event_id}/replay")
async def replay_admin_billing_reconciliation(
    event_id: str,
    body: ReplayWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _replay(event_id=event_id, body=body, request=request, db=db, actor=actor)


@router.post("/admin/billing/webhooks/{event_id}/replay")
async def replay_admin_billing_webhook(
    event_id: str,
    body: ReplayWebhookRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _replay(event_id=event_id, body=body, request=request, db=db, actor=actor)

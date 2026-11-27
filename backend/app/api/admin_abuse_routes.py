"""Admin-only abuse-signal review queue.

The surface is intentionally narrow: an explicit scan materialises aggregate
signals, one reviewer can acknowledge or dismiss an item, and only a
two-person-approved action can change device enforcement state. No endpoint
returns a raw fingerprint, IP address, account identifier, email, document or
provider payload.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_abuse_service
from ..services.admin_abuse_service import AbuseReviewError
from ..services.admin_approval_service import ApprovalError
from ..services.admin_audit_service import AdminActor

router = APIRouter()

Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
]
Note = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
]
ApprovalId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)
]


class AbuseScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: Literal[7, 30, 90] = 30
    reason: Reason
    confirm: bool


class AbuseAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: Optional[str] = Field(default=None, max_length=36)
    reason: Reason
    confirm: bool


class AbuseDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "dismiss", "action"]
    action: Optional[Literal["block", "unblock", "whitelist"]] = None
    reason: Reason
    confirm: bool
    approval_id: Optional[ApprovalId] = None
    note: Optional[Note] = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AbuseReviewError):
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details:
            detail.update(exc.details)
        return HTTPException(status_code=exc.status_code, detail=detail)
    if isinstance(exc, ApprovalError):
        detail = {"code": exc.code, "message": str(exc)}
        if exc.details:
            detail.update(exc.details)
        return HTTPException(status_code=exc.status_code, detail=detail)
    if isinstance(exc, KeyError):
        message = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=404, detail=message)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="The abuse-review action failed")


@router.get("/admin/abuse/queue")
async def list_abuse_queue(
    status: Optional[str] = Query(default="open", max_length=16),
    severity: Optional[str] = Query(default=None, max_length=16),
    signal_type: Optional[str] = Query(default=None, max_length=32),
    assigned_to: Optional[str] = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """List queue items. ``status=all`` returns every state."""
    effective_status = None if status in {None, "", "all"} else status
    effective_assignee = actor.user_id if assigned_to == "me" else assigned_to
    try:
        return await admin_abuse_service.list_queue(
            db,
            status=effective_status,
            severity=severity or None,
            signal_type=signal_type or None,
            assigned_to=effective_assignee,
            limit=limit,
            offset=offset,
        )
    except AbuseReviewError as exc:
        raise _http_error(exc) from None


@router.get("/admin/abuse/queue/{item_id}")
async def get_abuse_queue_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    item = await admin_abuse_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Abuse-review item not found")
    return admin_abuse_service.signal_summary(item)


@router.post("/admin/abuse/queue/scan")
async def scan_abuse_signals(
    body: AbuseScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Materialise aggregate signals. This never enforces or punishes."""
    try:
        return await admin_abuse_service.scan_signals(
            db,
            window_days=body.window_days,
            reason=body.reason,
            confirm=body.confirm,
            actor=actor,
            request=request,
        )
    except AbuseReviewError as exc:
        await db.rollback()
        raise _http_error(exc) from None


@router.post("/admin/abuse/queue/{item_id}/assign")
async def assign_abuse_queue_item(
    item_id: str,
    body: AbuseAssignRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_abuse_service.assign_item(
            db,
            item_id=item_id,
            assignee_id=body.assignee_id,
            reason=body.reason,
            confirm=body.confirm,
            actor=actor,
            request=request,
        )
    except AbuseReviewError as exc:
        await db.rollback()
        raise _http_error(exc) from None


@router.post("/admin/abuse/queue/{item_id}/decision")
async def decide_abuse_queue_item(
    item_id: str,
    body: AbuseDecisionRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Acknowledge, dismiss, or request/execute a two-person-approved action."""
    try:
        result = await admin_abuse_service.decide(
            db,
            item_id=item_id,
            decision=body.decision,
            action=body.action,
            reason=body.reason,
            confirm=body.confirm,
            actor=actor,
            approval_id=body.approval_id,
            note=body.note,
            request=request,
        )
    except AbuseReviewError as exc:
        await db.rollback()
        raise _http_error(exc) from None
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc) from None
    if result.get("approval_required"):
        response.status_code = 202
    return result

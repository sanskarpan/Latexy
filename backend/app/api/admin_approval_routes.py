"""Admin approval queue and approved bulk-entitlement execution.

Every mutation here is admin-only and requires the shared two-person approval
workflow. The queue exposes only bounded action metadata; it never returns
documents, prompts, emails, tokens, raw request metadata or provider payloads.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_approval_service, gdpr_service
from ..services.admin_abuse_service import AbuseReviewError
from ..services.admin_approval_service import (
    ApprovalError,
    approval_summary,
)
from ..services.admin_audit_service import AdminActor
from ..services.admin_billing_service import admin_billing_service
from ..services.entitlement_service import entitlement_service

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
ApprovalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)]


class ApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: Literal["role_escalation", "bulk_entitlement_change", "impersonation"]
    payload: dict[str, Any]
    reason: Reason
    expires_in_hours: Optional[int] = Field(default=24, ge=1, le=720)


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note


class ApprovalCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ApprovalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[Note] = None


class BulkEntitlementChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["plan", "role", "kill_switch"]
    plan_family: Optional[str] = Field(default=None, max_length=50)
    role: Optional[str] = Field(default=None, max_length=32)
    feature_key: str = Field(min_length=1, max_length=120)
    enabled: bool


class BulkEntitlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: ApprovalId
    changes: list[BulkEntitlementChange] = Field(min_length=1, max_length=50)
    note: Optional[Note] = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ApprovalError):
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.details:
            detail.update(exc.details)
        return HTTPException(status_code=exc.status_code, detail=detail)
    if isinstance(exc, gdpr_service.GdprError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )
    if isinstance(exc, AbuseReviewError):
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
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
    return HTTPException(status_code=500, detail="The approval action failed")


def _bulk_changes(body: BulkEntitlementRequest) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in change.model_dump().items()
            if value is not None
        }
        for change in body.changes
    ]


@router.get("/admin/approvals")
async def list_admin_approvals(
    status: Optional[str] = Query(default="pending", max_length=24),
    request_type: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Pending queue by default; ``status=all`` returns every state."""
    effective_status = None if status in {None, "", "all"} else status
    try:
        items, total, counts = await admin_approval_service.list_requests(
            db,
            status=effective_status,
            request_type=request_type or None,
            limit=limit,
            offset=offset,
        )
    except ApprovalError as exc:
        raise _http_error(exc) from None
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "counts": counts,
        "pending_by_type": await admin_approval_service.pending_counts(db),
    }


@router.get("/admin/approvals/{approval_id}")
async def get_admin_approval(
    approval_id: str,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    row = await admin_approval_service.get_request(db, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval_summary(row)


@router.post("/admin/approvals", status_code=201)
async def create_admin_approval(
    body: ApprovalCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Request a second-admin approval. The payload is hashed, never trusted later."""
    resource_type: str | None
    resource_id: str | None
    if body.request_type == "role_escalation":
        target_user_id = str(body.payload.get("target_user_id") or "")
        target = await db.scalar(select(User).where(User.id == target_user_id))
        if target is None:
            raise HTTPException(status_code=404, detail="Target user not found")
        if target.id == actor.user_id:
            raise HTTPException(status_code=409, detail="You cannot request a role change for yourself")
        if target.role != body.payload.get("previous_role"):
            raise HTTPException(
                status_code=409,
                detail="The target's current role does not match the requested previous_role",
            )
        resource_type, resource_id = "user", target.id
    elif body.request_type == "impersonation":
        target_user_id = str(body.payload.get("target_user_id") or "")
        target = await db.scalar(select(User).where(User.id == target_user_id))
        if target is None:
            raise HTTPException(status_code=404, detail="Target user not found")
        if target.id == actor.user_id:
            raise HTTPException(status_code=409, detail="You cannot request view-as for yourself")
        resource_type, resource_id = "user", target.id
    else:
        resource_type, resource_id = "entitlement_bulk", None
    try:
        row = await admin_approval_service.create_request(
            db,
            request_type=body.request_type,
            payload=body.payload,
            reason=body.reason,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            expires_in=timedelta(hours=body.expires_in_hours or 24),
            request=request,
        )
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc) from None
    return approval_summary(row)


async def _decide_refund(
    *,
    row,
    decision: str,
    note: str,
    actor: AdminActor,
    request: Request,
    db: AsyncSession,
) -> None:
    if row.resource_type != "refund_request" or not row.resource_id:
        raise HTTPException(status_code=409, detail="Refund approval has no refund request")
    await admin_billing_service.decide_refund_request(
        db,
        request_id=row.resource_id,
        decision=decision,
        note=note,
        actor=actor,
        request=request,
    )


async def _decide_deletion(
    *,
    row,
    decision: str,
    note: str,
    actor: AdminActor,
    request: Request,
    db: AsyncSession,
) -> None:
    if row.resource_type != "gdpr_request" or not row.resource_id:
        raise HTTPException(status_code=409, detail="Deletion approval has no GDPR request")
    await gdpr_service.review_request(
        db,
        request_id=row.resource_id,
        decision="approved" if decision == "approve" else "rejected",
        note=note,
        actor=actor,
        request=request,
    )


@router.post("/admin/approvals/{approval_id}/approve")
async def approve_admin_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    row = await admin_approval_service.get_request(db, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    try:
        if row.request_type == "refund":
            await _decide_refund(
                row=row, decision="approve", note=body.note, actor=actor, request=request, db=db
            )
        elif row.request_type == "account_deletion":
            await _decide_deletion(
                row=row, decision="approve", note=body.note, actor=actor, request=request, db=db
            )
        else:
            row = await admin_approval_service.decide(
                db,
                approval_id=approval_id,
                decision="approve",
                note=body.note,
                actor=actor,
                request=request,
            )
    except Exception as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    refreshed = await admin_approval_service.get_request(db, approval_id)
    return approval_summary(refreshed or row)


@router.post("/admin/approvals/{approval_id}/reject")
async def reject_admin_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    row = await admin_approval_service.get_request(db, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    try:
        if row.request_type == "refund":
            await _decide_refund(
                row=row, decision="reject", note=body.note, actor=actor, request=request, db=db
            )
        elif row.request_type == "account_deletion":
            await _decide_deletion(
                row=row, decision="reject", note=body.note, actor=actor, request=request, db=db
            )
        else:
            row = await admin_approval_service.decide(
                db,
                approval_id=approval_id,
                decision="reject",
                note=body.note,
                actor=actor,
                request=request,
            )
    except Exception as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    refreshed = await admin_approval_service.get_request(db, approval_id)
    return approval_summary(refreshed or row)


@router.post("/admin/approvals/{approval_id}/cancel")
async def cancel_admin_approval(
    approval_id: str,
    body: ApprovalCancelRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    row = await admin_approval_service.get_request(db, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if row.request_type in {"refund", "account_deletion"}:
        raise HTTPException(
            status_code=409,
            detail="Cancel this request through its originating workflow",
        )
    try:
        row = await admin_approval_service.cancel(
            db, approval_id=approval_id, reason=body.reason, actor=actor, request=request
        )
    except ApprovalError as exc:
        await db.rollback()
        raise _http_error(exc) from None
    return approval_summary(row)


@router.post("/admin/approvals/{approval_id}/execute")
async def execute_admin_approval(
    approval_id: str,
    request: Request,
    body: ApprovalExecuteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Execute an approved action once. The approval id is the idempotency key."""
    row = await admin_approval_service.get_request(db, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    note = body.note if body else None
    try:
        if row.request_type == "bulk_entitlement_change":
            changes = list((row.payload or {}).get("changes") or [])
            row = await admin_approval_service.execute_bulk_approval(
                db,
                approval_id=approval_id,
                changes=changes,
                actor=actor,
                note=note,
                request=request,
            )
        elif row.request_type == "refund":
            if row.resource_type != "refund_request" or not row.resource_id:
                raise HTTPException(status_code=409, detail="Refund approval has no refund request")
            await admin_approval_service.require_approved(
                db,
                approval_id=approval_id,
                request_type="refund",
                payload=row.payload,
                actor=actor,
                resource_type="refund_request",
                resource_id=row.resource_id,
                request=request,
            )
            await admin_billing_service.execute_refund_request(
                db,
                request_id=row.resource_id,
                actor=actor,
                note=note or "",
                request=request,
            )
            refreshed = await admin_approval_service.get_request(db, approval_id)
            return approval_summary(refreshed or row)
        elif row.request_type == "account_deletion":
            if row.resource_type != "gdpr_request" or not row.resource_id:
                raise HTTPException(status_code=409, detail="Deletion approval has no GDPR request")
            await gdpr_service.execute_deletion(
                db,
                request_id=row.resource_id,
                actor=actor,
                note=note,
                request=request,
            )
            refreshed = await admin_approval_service.get_request(db, approval_id)
            return approval_summary(refreshed or row)
        elif row.request_type == "role_escalation":
            payload = dict(row.payload or {})
            row, _user = await admin_approval_service.execute_role_escalation(
                db,
                approval_id=approval_id,
                target_user_id=str(payload.get("target_user_id") or ""),
                previous_role=str(payload.get("previous_role") or ""),
                new_role=str(payload.get("new_role") or ""),
                actor=actor,
                note=note,
                request=request,
            )
        elif row.request_type == "abuse_review_action":
            from ..services import admin_abuse_service

            await admin_abuse_service.execute_approved_action(
                db,
                approval_id=approval_id,
                actor=actor,
                note=note,
                request=request,
            )
            refreshed = await admin_approval_service.get_request(db, approval_id)
            return approval_summary(refreshed or row)
        else:
            raise HTTPException(
                status_code=409,
                detail="No impersonation/view-as surface is enabled; this approval cannot execute",
            )
    except Exception as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return approval_summary(row)


@router.post("/admin/entitlements/bulk")
async def bulk_update_entitlements(
    body: BulkEntitlementRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Apply an approved multi-cell entitlement change atomically."""
    try:
        row = await admin_approval_service.execute_bulk_approval(
            db,
            approval_id=body.approval_id,
            changes=_bulk_changes(body),
            actor=actor,
            note=body.note,
            request=request,
        )
    except Exception as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    return {
        "approval": approval_summary(row),
        "entitlements": await entitlement_service.get_state(db),
    }

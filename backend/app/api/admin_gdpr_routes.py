"""Admin legal-review queue for GDPR deletion requests and legal holds.

Review and execution are deliberately separate: approving a deletion does not
run it, and execution requires an approved review plus no active legal hold.
Every mutation writes an append-only admin audit row with actor, target user,
request id and request context.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import gdpr_service
from ..services.admin_audit_service import AdminActor

router = APIRouter(prefix="/admin/gdpr", tags=["admin", "gdpr"])

ReviewNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
HoldReason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
ExecuteNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    note: ReviewNote


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: ExecuteNote | None = None


class LegalHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    reason: HoldReason


class LegalHoldReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: HoldReason


def _http_error(exc: gdpr_service.GdprError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if isinstance(exc, gdpr_service.GdprLegalHoldBlocked):
        detail["request"] = exc.request_payload
    return HTTPException(status_code=exc.status_code, detail=detail)


@router.get("/requests")
async def list_gdpr_requests(
    status: str | None = Query(default=None, max_length=24),
    request_type: Literal["export", "deletion"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await gdpr_service.list_admin_requests(
        db,
        status=status,
        request_type=request_type,
        limit=limit,
        offset=offset,
    )


@router.post("/requests/{request_id}/review")
async def review_gdpr_request(
    request_id: UUID,
    body: ReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await gdpr_service.review_request(
            db,
            request_id=str(request_id),
            decision=body.decision,
            note=body.note,
            actor=actor,
            request=request,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.post("/requests/{request_id}/execute")
async def execute_gdpr_deletion(
    request_id: UUID,
    request: Request,
    body: ExecuteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await gdpr_service.execute_deletion(
            db,
            request_id=str(request_id),
            actor=actor,
            note=body.note if body else None,
            request=request,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.get("/legal-holds")
async def list_gdpr_legal_holds(
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    items = await gdpr_service.list_legal_holds(db, active_only=active_only, limit=limit)
    return {"items": items, "total": len(items)}


@router.post("/legal-holds", status_code=201)
async def place_gdpr_legal_hold(
    body: LegalHoldRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await gdpr_service.place_legal_hold(
            db,
            user_id=str(body.user_id),
            reason=body.reason,
            actor=actor,
            request=request,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None


@router.post("/legal-holds/{hold_id}/release")
async def release_gdpr_legal_hold(
    hold_id: UUID,
    body: LegalHoldReleaseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await gdpr_service.release_legal_hold(
            db,
            hold_id=str(hold_id),
            reason=body.reason,
            actor=actor,
            request=request,
        )
    except gdpr_service.GdprError as exc:
        raise _http_error(exc) from None

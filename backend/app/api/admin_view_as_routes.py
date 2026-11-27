"""Audited read-only view-as-user request, start, snapshot and end endpoints.

All routes are admin-only. A preview is gated by the shared two-person approval
workflow, is bound to one explicit target and expires within 15 minutes. The
opaque token is returned once at start and is only accepted by the snapshot
route; ``app.middleware.view_as_guard`` refuses every write that presents it.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_view_as_service
from ..services.admin_approval_service import ApprovalError
from ..services.admin_audit_service import AdminActor
from ..services.admin_user_timeline_service import DEFAULT_TIMELINE_LIMIT, MAX_TIMELINE_LIMIT

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
ApprovalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)]
SessionId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=64)]


class ViewAsRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1, max_length=64)
    reason: Reason
    expires_in_minutes: int = Field(
        default=admin_view_as_service.VIEW_AS_DEFAULT_MINUTES,
        ge=admin_view_as_service.VIEW_AS_MIN_MINUTES,
        le=admin_view_as_service.VIEW_AS_MAX_MINUTES,
    )


class ViewAsStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: ApprovalId
    note: Optional[Note] = None


class ViewAsEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, admin_view_as_service.ViewAsError):
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
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
    return HTTPException(status_code=503, detail="The view-as action could not be completed")


@router.post("/admin/view-as/requests", status_code=201)
async def create_admin_view_as_request(
    body: ViewAsRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Request a second-admin approval for one read-only target preview."""
    try:
        return await admin_view_as_service.request_view_as(
            db,
            target_user_id=body.target_user_id,
            reason=body.reason,
            expires_in_minutes=body.expires_in_minutes,
            actor=actor,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/admin/view-as/sessions")
async def list_admin_view_as_sessions(
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """List this admin's own preview sessions; tokens are never returned."""
    return await admin_view_as_service.list_sessions(db, actor=actor, limit=limit)


@router.post("/admin/view-as/sessions", status_code=201)
async def start_admin_view_as_session(
    body: ViewAsStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Consume one approved request and return the opaque preview token once."""
    try:
        return await admin_view_as_service.start_view_as(
            db,
            approval_id=body.approval_id,
            note=body.note,
            actor=actor,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/admin/view-as/sessions/{session_id}")
async def get_admin_view_as_snapshot(
    session_id: SessionId,
    request: Request,
    token: Optional[str] = Header(default=None, alias="X-View-As-Token"),
    timeline_limit: int = Query(DEFAULT_TIMELINE_LIMIT, ge=1, le=MAX_TIMELINE_LIMIT),
    timeline_offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return the bounded read-only snapshot unlocked by this session's token."""
    try:
        return await admin_view_as_service.build_snapshot(
            db,
            session_id=session_id,
            token=token or "",
            actor=actor,
            timeline_limit=timeline_limit,
            timeline_offset=timeline_offset,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/admin/view-as/sessions/{session_id}/end")
async def end_admin_view_as_session(
    session_id: SessionId,
    body: ViewAsEndRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """End the preview immediately and write the closing audit row."""
    try:
        return await admin_view_as_service.end_view_as(
            db,
            session_id=session_id,
            reason=body.reason,
            actor=actor,
            request=request,
        )
    except Exception as exc:
        raise _http_error(exc) from exc

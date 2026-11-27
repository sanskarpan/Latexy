"""Admin-only error feed and threshold alert evaluation (#2166)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import error_tracking_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ErrorAlertEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    confirm: bool = False
    dry_run: bool = False


@router.get("/admin/analytics/errors")
async def get_admin_error_feed(
    days: int = Query(default=7, ge=1, le=90),
    source: Optional[Literal["frontend", "backend"]] = Query(default=None),
    route: Optional[str] = Query(default=None, max_length=128),
    error_class: Optional[str] = Query(default=None, max_length=80),
    limit: int = Query(default=25, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate error groups and the current alert configuration.

    The response never contains exception messages, stacks, user identifiers,
    emails, tokens or document content.
    """
    try:
        return await error_tracking_service.error_feed(
            db,
            days=days,
            source=source,
            route=route,
            error_class=error_class,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/admin/analytics/errors/evaluate")
async def evaluate_admin_error_alerts(
    body: ErrorAlertEvaluationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Preview or dispatch threshold alerts for aggregate error groups.

    A real dispatch requires an explicit ``confirm`` and a reason. Preview mode
    never sends a message, changes alert state or writes an audit row.
    """
    if not body.dry_run and not body.confirm:
        raise HTTPException(status_code=422, detail="confirm is required to dispatch error alerts")
    try:
        return await error_tracking_service.evaluate_error_alerts(
            db,
            actor=actor,
            reason=body.reason,
            request=request,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

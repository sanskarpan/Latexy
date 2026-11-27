"""Admin-only template health status and audited re-verification."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services.admin_audit_service import AdminActor
from ..services.admin_template_health_service import admin_template_health_service

router = APIRouter()

Reason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=1000),
]
RequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=80),
]


class TemplateHealthRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    confirm: Literal[True]
    request_id: RequestId = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    visual_test: Literal["pass", "fail", "unknown"] = "unknown"
    # Optional CI attestations.  The service validates the exact SHA/run-id
    # shape again; arbitrary URLs or free-form evidence are never accepted.
    commit_sha: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    ci_run_id: Optional[str] = Field(default=None, pattern=r"^[0-9]{1,32}$")


@router.get("/admin/templates/health")
async def get_admin_template_health(
    stale_after_hours: int = Query(72, ge=1, le=720),
    include_inactive: bool = Query(False),
    status: Optional[Literal["pass", "fail", "unknown"]] = Query(None),
    template: Optional[str] = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Per-template pass/fail/unknown status with CI evidence links."""
    try:
        return await admin_template_health_service.health_report(
            db,
            stale_after_hours=stale_after_hours,
            include_inactive=include_inactive,
            status=status,
            template=template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/admin/templates/{template_id}/health/retry")
async def retry_admin_template_health(
    template_id: str,
    body: TemplateHealthRetryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Re-run bounded asset/compile checks; audit and idempotently persist."""
    try:
        return await admin_template_health_service.retry_check(
            db,
            template_id=template_id,
            actor=actor,
            reason=body.reason,
            request_id=body.request_id,
            visual_test=body.visual_test,
            commit_sha=body.commit_sha,
            ci_run_id=body.ci_run_id,
            request=request,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

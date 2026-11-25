"""Admin-only stuck-job diagnosis and audited retry/cancel/fence routes."""

from __future__ import annotations

from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_stuck_jobs_service
from ..services.admin_audit_service import AdminActor
from ..services.admin_stuck_jobs_service import StuckJobConflict

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
JobId = Annotated[str, Path(min_length=1, max_length=255)]


class StuckJobActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    confirm: bool
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )

    @field_validator("confirm")
    @classmethod
    def validate_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value


def _raise_action_error(exc: StuckJobConflict) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


def _idempotency_key(body: StuckJobActionRequest, header_value: str | None) -> str | None:
    return body.idempotency_key or header_value


@router.get("/admin/operations/stuck-jobs")
@router.get("/admin/operations/jobs/stuck")
@router.get("/admin/jobs/stuck")
async def list_admin_stuck_jobs(
    min_age_minutes: int = Query(
        default=admin_stuck_jobs_service.DEFAULT_MIN_AGE_MINUTES,
        ge=1,
        le=admin_stuck_jobs_service.MAX_MIN_AGE_MINUTES,
    ),
    limit: int = Query(default=50, ge=1, le=admin_stuck_jobs_service.MAX_ITEMS),
    status: str | None = Query(default=None, max_length=64),
    job_id: str | None = Query(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """List per-job queued/processing/stale diagnosis with safe context only."""
    return await admin_stuck_jobs_service.list_stuck_jobs(
        db,
        min_age_minutes=min_age_minutes,
        limit=limit,
        status_filter=status,
        job_id_filter=job_id,
    )


@router.post("/admin/operations/stuck-jobs/{job_id}/retry")
@router.post("/admin/operations/jobs/{job_id}/retry")
@router.post("/admin/jobs/{job_id}/retry")
async def retry_admin_stuck_job(
    job_id: JobId,
    body: StuckJobActionRequest,
    request: Request,
    idempotency_header: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Fence the stuck original and create a linked replacement job."""
    try:
        return await admin_stuck_jobs_service.retry_stuck_job(
            db,
            job_id=job_id,
            actor=actor,
            reason=body.reason,
            request=request,
            idempotency_key=_idempotency_key(body, idempotency_header),
        )
    except StuckJobConflict as exc:
        _raise_action_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/admin/operations/stuck-jobs/{job_id}/requeue")
@router.post("/admin/operations/jobs/{job_id}/requeue")
@router.post("/admin/jobs/{job_id}/requeue")
async def requeue_admin_stuck_job(
    job_id: JobId,
    body: StuckJobActionRequest,
    request: Request,
    idempotency_header: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Explicit requeue alias for retry; the original is always fenced first."""
    try:
        return await admin_stuck_jobs_service.retry_stuck_job(
            db,
            job_id=job_id,
            actor=actor,
            reason=body.reason,
            request=request,
            idempotency_key=_idempotency_key(body, idempotency_header),
        )
    except StuckJobConflict as exc:
        _raise_action_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/admin/operations/stuck-jobs/{job_id}/cancel")
@router.post("/admin/operations/jobs/{job_id}/cancel")
@router.post("/admin/jobs/{job_id}/cancel")
async def cancel_admin_stuck_job(
    job_id: JobId,
    body: StuckJobActionRequest,
    request: Request,
    idempotency_header: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Durably cancel one stuck job through the finalization arbiter."""
    try:
        return await admin_stuck_jobs_service.cancel_stuck_job(
            db,
            job_id=job_id,
            actor=actor,
            reason=body.reason,
            request=request,
            idempotency_key=_idempotency_key(body, idempotency_header),
        )
    except StuckJobConflict as exc:
        _raise_action_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/admin/operations/stuck-jobs/{job_id}/fence")
@router.post("/admin/operations/jobs/{job_id}/fence")
@router.post("/admin/jobs/{job_id}/fence")
async def fence_admin_stuck_job(
    job_id: JobId,
    body: StuckJobActionRequest,
    request: Request,
    idempotency_header: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Durably fence a stale worker and record a non-revivable tombstone."""
    try:
        return await admin_stuck_jobs_service.fence_stuck_job(
            db,
            job_id=job_id,
            actor=actor,
            reason=body.reason,
            request=request,
            idempotency_key=_idempotency_key(body, idempotency_header),
        )
    except StuckJobConflict as exc:
        _raise_action_error(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

"""Admin-only retention policy, preview and guarded purge endpoints.

Only aggregate counts and class-level policy metadata cross this boundary. No
per-user history, document content, object bytes, export token or provider
payload is returned. A purge is one bounded page and writes an append-only
admin audit row plus a persisted run record.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_retention_service
from ..services.admin_audit_service import AdminActor

router = APIRouter(tags=["admin", "retention"])

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
DataClass = Annotated[str, Path(min_length=1, max_length=32)]


class PolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_hours: int = Field(ge=1, le=87600)
    schedule_hours: int = Field(ge=1, le=8760)
    enabled: bool = True
    expected_version: int = Field(ge=1)
    reason: Reason
    confirm: Literal[True]


class DryRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    limit: int = Field(default=200, ge=1, le=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    confirm: Literal[True]
    limit: int = Field(default=200, ge=1, le=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


def _http_error(exc: admin_retention_service.RetentionError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/admin/operations/retention")
async def get_retention_overview(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Configured vs effective windows, boundary counts and run history."""
    return await admin_retention_service.get_overview(db)


@router.patch("/admin/operations/retention/{data_class}")
async def update_retention_policy(
    data_class: DataClass,
    body: PolicyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Version and audit a class policy change with optimistic concurrency."""
    try:
        return await admin_retention_service.update_policy(
            db,
            data_class=data_class,
            retention_hours=body.retention_hours,
            schedule_hours=body.schedule_hours,
            enabled=body.enabled,
            expected_version=body.expected_version,
            reason=body.reason,
            confirm=body.confirm is True,
            actor=actor,
            request=request,
        )
    except admin_retention_service.RetentionError as exc:
        raise _http_error(exc) from None


@router.post("/admin/operations/retention/{data_class}/dry-run")
async def preview_retention_class(
    data_class: DataClass,
    body: DryRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Count what would be touched without deleting or scrubbing anything."""
    try:
        return await admin_retention_service.execute_run(
            db,
            data_class=data_class,
            dry_run=True,
            reason=body.reason,
            confirm=False,
            limit=body.limit,
            idempotency_key=body.idempotency_key,
            actor=actor,
            request=request,
        )
    except admin_retention_service.RetentionError as exc:
        raise _http_error(exc) from None


@router.post("/admin/operations/retention/{data_class}/purge")
async def purge_retention_class(
    data_class: DataClass,
    body: PurgeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
    idempotency_header: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
) -> dict[str, Any]:
    """Delete or scrub one bounded page after explicit confirmation."""
    idempotency_key = body.idempotency_key or idempotency_header
    if idempotency_header is not None and len(idempotency_header.strip()) < 8:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_idempotency_key", "message": "Idempotency-Key is too short"},
        )
    try:
        return await admin_retention_service.execute_run(
            db,
            data_class=data_class,
            dry_run=False,
            reason=body.reason,
            confirm=body.confirm is True,
            limit=body.limit,
            idempotency_key=idempotency_key.strip() if idempotency_key else None,
            actor=actor,
            request=request,
        )
    except admin_retention_service.RetentionError as exc:
        raise _http_error(exc) from None

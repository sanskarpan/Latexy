"""Admin-only PDF artifact lifecycle report and guarded orphan cleanup.

Kept separate from ``admin_control_routes`` and ``admin_operations_routes`` so
the existing operations surface stays stable. Every mutating action requires an
admin actor, a reason and an explicit confirmation, and writes one append-only
audit row. Object bytes are never read by this API.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import artifact_lifecycle_service
from ..services.admin_audit_service import AdminActor, record_admin_audit

router = APIRouter()
logger = get_logger(__name__)

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


class ArtifactCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Reason
    dry_run: bool = True
    confirm: Literal[True] | None = None
    cursor: str | None = Field(default=None, max_length=1000)
    limit: int = Field(default=100, ge=1, le=200)
    min_age_hours: int = Field(default=1, ge=1, le=168)

    @model_validator(mode="after")
    def _require_confirmation_for_deletes(self):
        if not self.dry_run and self.confirm is not True:
            raise ValueError("Cleanup confirmation is required for a real deletion")
        return self


@router.get("/admin/operations/artifacts/lifecycle")
async def get_artifact_lifecycle(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Aggregate-only manifest/storage lifecycle report."""
    return await artifact_lifecycle_service.get_lifecycle_report(db)


@router.post("/admin/operations/artifacts/cleanup")
async def run_artifact_cleanup(
    body: ArtifactCleanupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Dry-run or delete one bounded page of strictly unreferenced objects."""
    try:
        result = await artifact_lifecycle_service.run_cleanup(
            db,
            cursor=body.cursor,
            limit=body.limit,
            dry_run=body.dry_run,
            min_age_hours=body.min_age_hours,
        )
    except artifact_lifecycle_service.ArtifactCleanupRefused as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error(
            "Artifact cleanup failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail={"code": "artifact_cleanup_unavailable", "message": "Cleanup could not be completed"},
        ) from exc

    await record_admin_audit(
        db,
        actor=actor,
        action=(
            "artifact.cleanup.dry_run"
            if body.dry_run
            else "artifact.cleanup.run"
        ),
        target_type="render_artifact",
        target_id=None,
        reason=body.reason,
        before=None,
        after={
            "dry_run": bool(body.dry_run),
            "scanned": result.get("scanned", {}),
            "candidates": result.get("candidates", {}),
            "deleted": result.get("deleted", {}),
            "failed": result.get("failed", {}),
        },
        metadata={
            "cursor_present": bool(body.cursor),
            "limit": body.limit,
            "min_age_hours": body.min_age_hours,
        },
        request=request,
        commit=False,
    )
    await db.commit()
    return result

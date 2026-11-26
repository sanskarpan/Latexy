"""Feature-flag exposure ingestion and aggregate outcome reporting (issue #2157).

Capture is authenticated and requires a current first-party analytics grant for
the opaque browser id, so a denial or withdrawal stops storage server-side. The
request model forbids unknown fields: no email, name, document text, prompt,
token, IP address, user agent, provider payload or free-form metadata can reach
the JSONB row.

The admin route is read-only, aggregate-only and admin-only. It returns exposed
and control counts, distinct-subject sample sizes, outcome and guardrail metrics
for 7- and 30-day lookbacks, and the metric definitions. Groups with fewer than
five subjects are suppressed.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.flag_exposure_service import (
    OPERATIONAL_FLAG_ORDER,
    ConsentRequiredError,
    flag_exposure_service,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin/analytics", tags=["admin-analytics"])

OperationalFlagKey = Literal[
    "trial_limits",
    "deep_analysis_trial",
    "compile_timeouts",
    "task_priority",
    "billing",
    "upgrade_ctas",
]

_SAFE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class FlagExposureItem(BaseModel):
    """One evaluated operational flag; no variant or client state is trusted."""

    model_config = ConfigDict(extra="forbid")

    key: OperationalFlagKey
    enabled: bool


class FlagExposureRequest(BaseModel):
    """Exactly the fields the exposure event family accepts."""

    model_config = ConfigDict(extra="forbid")

    anonymous_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=_SAFE_IDENTIFIER,
    )
    flags: list[FlagExposureItem] = Field(
        min_length=1,
        max_length=len(OPERATIONAL_FLAG_ORDER),
    )


@router.post("/flag-exposure", status_code=status.HTTP_202_ACCEPTED)
async def ingest_flag_exposure(
    payload: FlagExposureRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Record consent-covered flag evaluations for the signed-in account."""

    try:
        return await flag_exposure_service.record_exposures(
            db,
            user_id=user_id,
            anonymous_id=payload.anonymous_id,
            flags=[item.model_dump() for item in payload.flags],
        )
    except ConsentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analytics consent is required",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@admin_router.get("/flag-exposure")
async def get_admin_flag_exposure(
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Exposed/control counts, outcome joins and guardrails for every flag."""

    return await flag_exposure_service.report(db)

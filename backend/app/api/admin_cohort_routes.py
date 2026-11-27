"""Cohort sync administration and consent-gated flag evaluation (issue #2165).

All admin routes are admin-only, aggregate-only and audited. They never return a
member account id, email, name, document, prompt, token, IP address, user agent,
PostHog payload or free-form provider error. Mutations require a reason and an
explicit ``confirm=true``.

The evaluation route is authenticated and requires a current first-party
analytics grant for the supplied opaque browser id. Without it every result is
``enabled=false`` and no exposure is stored.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..middleware.capability_router import CapabilityRouter as APIRouter
from ..services.admin_audit_service import AdminActor
from ..services.cohort_sync_service import (
    MAX_EVALUATED_FLAGS,
    MAX_SYNC_MEMBERS,
    CohortError,
    cohort_sync_service,
)

router = APIRouter(prefix="/analytics", tags=["cohorts"])
admin_router = APIRouter(prefix="/admin/cohorts", tags=["admin-cohorts"])

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]

_SAFE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class CohortCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    tenant_id: Optional[str] = Field(default=None, max_length=36)
    posthog_cohort_id: Optional[str] = Field(default=None, max_length=64)
    minimum_size: int = Field(default=5, ge=5, le=100_000)
    stale_after_seconds: int = Field(default=86_400, ge=300, le=604_800)
    reason: Reason
    confirm: Literal[True]


class CohortFlagMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_key: str = Field(min_length=1, max_length=100)
    reason: Reason
    confirm: Literal[True]


class CohortSyncRequest(BaseModel):
    """One connector-reported PostHog cohort sync result.

    Either a member snapshot or a bounded failure code is accepted. Provider
    error text is deliberately not part of the contract.
    """

    model_config = ConfigDict(extra="forbid")

    members: list[str] = Field(default_factory=list, max_length=MAX_SYNC_MEMBERS)
    error_code: Optional[str] = Field(default=None, max_length=64)
    posthog_cohort_id: Optional[str] = Field(default=None, max_length=64)
    reason: Reason
    confirm: Literal[True]

    @model_validator(mode="after")
    def _one_result_shape(self) -> "CohortSyncRequest":
        if self.error_code is not None and self.members:
            raise ValueError("members and error_code are mutually exclusive")
        return self


class CohortEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anonymous_id: str = Field(min_length=1, max_length=128, pattern=_SAFE_IDENTIFIER)
    flag_keys: list[str] = Field(min_length=1, max_length=MAX_EVALUATED_FLAGS)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, CohortError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail="The cohort action failed")


@router.post("/cohorts/evaluate")
async def evaluate_cohort_flags(
    body: CohortEvaluationRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Return fail-closed results for the signed-in subject and record exposure."""

    try:
        return await cohort_sync_service.evaluate_flags(
            db,
            user_id=user_id,
            anonymous_id=body.anonymous_id,
            flag_keys=body.flag_keys,
        )
    except CohortError as exc:
        raise _http_error(exc) from None


@admin_router.get("")
async def list_feature_cohorts(
    tenant_id: Optional[str] = Query(default=None, max_length=36),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Cohort size, sync state, bounded error code and mapped flags."""

    try:
        return await cohort_sync_service.list_cohorts(db, tenant_id=tenant_id)
    except CohortError as exc:
        raise _http_error(exc) from None


@admin_router.post("", status_code=201)
async def create_feature_cohort(
    body: CohortCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await cohort_sync_service.create_cohort(
            db,
            actor=actor,
            key=body.key,
            name=body.name,
            description=body.description,
            tenant_id=body.tenant_id,
            posthog_cohort_id=body.posthog_cohort_id,
            minimum_size=body.minimum_size,
            stale_after_seconds=body.stale_after_seconds,
            reason=body.reason,
            request=request,
        )
    except CohortError as exc:
        raise _http_error(exc) from None


@admin_router.post("/{cohort_id}/mappings", status_code=201)
async def map_cohort_flag(
    cohort_id: str,
    body: CohortFlagMappingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await cohort_sync_service.map_flag(
            db,
            actor=actor,
            cohort_id=cohort_id,
            flag_key=body.flag_key,
            reason=body.reason,
            request=request,
        )
    except CohortError as exc:
        raise _http_error(exc) from None


@admin_router.delete("/{cohort_id}/mappings/{flag_key}")
async def unmap_cohort_flag(
    cohort_id: str,
    flag_key: str,
    request: Request,
    reason: Reason = Query(),
    confirm: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    if confirm is not True:
        raise HTTPException(status_code=422, detail="confirm=true is required")
    try:
        return await cohort_sync_service.unmap_flag(
            db,
            actor=actor,
            cohort_id=cohort_id,
            flag_key=flag_key,
            reason=reason,
            request=request,
        )
    except CohortError as exc:
        raise _http_error(exc) from None


@admin_router.post("/{cohort_id}/sync")
async def sync_feature_cohort(
    cohort_id: str,
    body: CohortSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Receive a consent-filtered PostHog snapshot or a bounded failure code."""

    try:
        return await cohort_sync_service.sync_members(
            db,
            actor=actor,
            cohort_id=cohort_id,
            reason=body.reason,
            members=body.members,
            error_code=body.error_code,
            posthog_cohort_id=body.posthog_cohort_id,
            request=request,
        )
    except CohortError as exc:
        raise _http_error(exc) from None

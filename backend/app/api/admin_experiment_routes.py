"""Pre-registered A/B experiment registry, assignment and results (issue #2158).

Capture is authenticated and requires a current first-party analytics grant for
the opaque browser id, so a denial or withdrawal stops assignment and exposure
server-side. The request models forbid unknown fields: no email, name, document
text, prompt, token, IP address, user agent, provider payload or free-form
metadata can reach an experiment row.

Every admin route is gated by ``require_admin_actor``. Creation, start and stop
require a reason and ``confirm: true`` and write an append-only audit row in the
same transaction as the change. Results are aggregate-only; no assignment id,
account id or per-user history is returned.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_required, require_admin_actor
from ..services import admin_experiments_service as service
from ..services.admin_audit_service import AdminActor
from ..services.flag_exposure_service import ConsentRequiredError

router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin/experiments", tags=["admin-experiments"])

ExperimentKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    ),
]
VariantKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]{0,31}$",
    ),
]
VariantLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
ExperimentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
Hypothesis = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=20, max_length=4000)
]
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)
]
AnonymousId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]

PrimaryMetric = Literal[
    "activation",
    "compile_success",
    "checkout_started",
    "retention_7d",
]
GuardrailMetric = Literal["compile_error_rate", "checkout_abandonment_rate"]
OperationalFlagKey = Literal[
    "trial_limits",
    "deep_analysis_trial",
    "compile_timeouts",
    "task_priority",
    "billing",
    "upgrade_ctas",
]
ExperimentStatus = Literal["preregistered", "running", "stopped"]


class ExperimentVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: VariantKey
    label: VariantLabel
    weight: int = Field(ge=1, le=100)
    flag_enabled: bool | None = None


class ExperimentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: ExperimentKey
    name: ExperimentName
    hypothesis: Hypothesis
    primary_metric: PrimaryMetric
    guardrail_metrics: list[GuardrailMetric] = Field(min_length=1, max_length=2)
    variants: list[ExperimentVariantInput] = Field(min_length=2, max_length=4)
    flag_key: OperationalFlagKey | None = None
    posthog_insight_url: str | None = Field(default=None, max_length=500)
    minimum_sample_per_variant: int = Field(default=100, ge=5, le=1_000_000)
    reason: Reason
    confirm: Literal[True]


class ExperimentTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    confirm: Literal[True]


class ExperimentStopRequest(ExperimentTransitionRequest):
    revert_assignments: bool = True


class ExperimentAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anonymous_id: AnonymousId
    experiment_keys: list[ExperimentKey] | None = Field(default=None, max_length=10)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        detail = str(exc.args[0]) if exc.args else "Experiment not found"
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if isinstance(exc, ConsentRequiredError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analytics consent is required",
        )
    if isinstance(exc, service.ExperimentError):
        return HTTPException(status_code=exc.status_code, detail=exc.message)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="The experiment request could not be validated",
    )


@router.post("/experiments/assignment", status_code=status.HTTP_202_ACCEPTED)
async def record_experiment_assignment(
    payload: ExperimentAssignmentRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, Any]:
    """Assign the signed-in subject and record a consent-covered exposure."""

    try:
        return await service.record_assignments(
            db,
            user_id=user_id,
            anonymous_id=payload.anonymous_id,
            experiment_keys=payload.experiment_keys,
        )
    except (service.ExperimentError, ConsentRequiredError) as exc:
        await db.rollback()
        raise _http(exc) from None
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None


@admin_router.get("/catalog")
async def get_admin_experiment_catalog(
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return the allowlisted metrics, flags, statuses and claim policy."""

    return service.experiment_catalog()


@admin_router.get("")
async def list_admin_experiments(
    status_filter: ExperimentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """List registrations with suppressed aggregate sample sizes only."""

    try:
        return await service.list_experiments(
            db, status=status_filter, limit=limit, offset=offset
        )
    except service.ExperimentError as exc:
        raise _http(exc) from None


@admin_router.post("", status_code=status.HTTP_201_CREATED)
async def create_admin_experiment(
    payload: ExperimentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Pre-register an immutable experiment before any exposure occurs."""

    try:
        return await service.create_experiment(
            db,
            actor=actor,
            experiment_key=payload.key,
            name=payload.name,
            hypothesis=payload.hypothesis,
            primary_metric=payload.primary_metric,
            guardrail_metrics=list(payload.guardrail_metrics),
            variants=[item.model_dump() for item in payload.variants],
            flag_key=payload.flag_key,
            posthog_insight_url=payload.posthog_insight_url,
            minimum_sample_per_variant=payload.minimum_sample_per_variant,
            reason=payload.reason,
            request=request,
        )
    except (service.ExperimentError, ConsentRequiredError) as exc:
        await db.rollback()
        raise _http(exc) from None
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None


@admin_router.get("/{experiment_id}")
async def get_admin_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return one pre-registration with its suppressed aggregate sample."""

    try:
        return await service.get_experiment_detail(db, experiment_id=experiment_id)
    except (service.ExperimentError, KeyError) as exc:
        raise _http(exc) from None


@admin_router.get("/{experiment_id}/results")
async def get_admin_experiment_results(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return aggregate variant lifts, confidence and the fixed-horizon guard."""

    try:
        return await service.experiment_results(db, experiment_id=experiment_id)
    except (service.ExperimentError, KeyError) as exc:
        raise _http(exc) from None


@admin_router.post("/{experiment_id}/start")
async def start_admin_experiment(
    experiment_id: str,
    payload: ExperimentTransitionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Start assignment once; a stopped experiment cannot be restarted."""

    try:
        return await service.start_experiment(
            db,
            experiment_id=experiment_id,
            actor=actor,
            reason=payload.reason,
            confirm=payload.confirm,
            request=request,
        )
    except (service.ExperimentError, KeyError) as exc:
        await db.rollback()
        raise _http(exc) from None


@admin_router.post("/{experiment_id}/revert")
async def revert_admin_experiment_assignments(
    experiment_id: str,
    payload: ExperimentTransitionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Revert remaining assignments only after the experiment is stopped."""

    try:
        return await service.revert_experiment_assignments(
            db,
            experiment_id=experiment_id,
            actor=actor,
            reason=payload.reason,
            confirm=payload.confirm,
            request=request,
        )
    except (service.ExperimentError, KeyError) as exc:
        await db.rollback()
        raise _http(exc) from None


@admin_router.post("/{experiment_id}/stop")
async def stop_admin_experiment(
    experiment_id: str,
    payload: ExperimentStopRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Stop assignment and revert open assignments without changing flags."""

    try:
        return await service.stop_experiment(
            db,
            experiment_id=experiment_id,
            actor=actor,
            reason=payload.reason,
            confirm=payload.confirm,
            revert_assignments=payload.revert_assignments,
            request=request,
        )
    except (service.ExperimentError, KeyError) as exc:
        await db.rollback()
        raise _http(exc) from None

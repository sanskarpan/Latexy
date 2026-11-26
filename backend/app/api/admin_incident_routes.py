"""Admin-only incident timeline CRUD and state transitions.

The canonical paths live under ``/admin/operations`` because incidents belong to
the Operations view. ``/admin/incidents`` is kept as a stable alias for callers
that use the table name directly; both surfaces share the same admin gate,
validation and audit path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_incident_service
from ..services.admin_audit_service import AdminActor

router = APIRouter()

IncidentSeverity = Literal["critical", "high", "medium", "low"]
IncidentStatus = Literal["open", "resolved", "active"]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
IncidentTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
IncidentSummary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
IncidentOwner = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
IncidentService = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: IncidentTitle | None = None
    summary: IncidentSummary
    severity: IncidentSeverity
    services: list[IncidentService] = Field(
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices("services", "affected_services"),
    )
    owner: IncidentOwner
    links: list[str] = Field(default_factory=list, max_length=20)
    related_alert_keys: list[str] = Field(default_factory=list, max_length=20)
    deploy_sha: str | None = None
    deploy_url: str | None = None
    started_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("started_at", "start_at", "start"),
    )
    reason: Reason | None = None


class IncidentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: IncidentTitle | None = None
    summary: IncidentSummary | None = None
    severity: IncidentSeverity | None = None
    services: list[IncidentService] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices("services", "affected_services"),
    )
    owner: IncidentOwner | None = None
    links: list[str] | None = Field(default=None, max_length=20)
    related_alert_keys: list[str] | None = Field(default=None, max_length=20)
    deploy_sha: str | None = None
    deploy_url: str | None = None
    started_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("started_at", "start_at", "start"),
    )
    status: IncidentStatus | None = None
    reason: Reason | None = None


class IncidentTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    reason: Reason | None = None
    ended_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("ended_at", "end_at", "end"),
    )


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


def _not_found(exc: KeyError) -> HTTPException:
    detail = str(exc.args[0]) if exc.args else "Incident not found"
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def _list_incidents(
    *,
    service: str | None,
    services: list[str] | None,
    severity: str | None,
    status_value: str | None,
    state_value: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> dict[str, Any]:
    try:
        return await admin_incident_service.list_incidents(
            db,
            service=service,
            services=services,
            severity=severity,
            status=status_value or state_value,
            start_date=start_date or start,
            end_date=end_date or end,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.get("/admin/operations/incidents")
@router.get("/admin/incidents", include_in_schema=False)
async def list_admin_incidents(
    service: str | None = Query(default=None, max_length=40),
    services: list[str] | None = Query(default=None),
    severity: IncidentSeverity | None = Query(default=None),
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    state: IncidentStatus | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    start: datetime | None = Query(default=None, include_in_schema=False),
    end: datetime | None = Query(default=None, include_in_schema=False),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _list_incidents(
        service=service,
        services=services,
        severity=severity,
        status_value=status_filter,
        state_value=state,
        start_date=start_date,
        end_date=end_date,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        db=db,
    )


@router.get("/admin/operations/incidents/timeline")
@router.get("/admin/incidents/timeline", include_in_schema=False)
async def get_admin_incident_timeline(
    service: str | None = Query(default=None, max_length=40),
    services: list[str] | None = Query(default=None),
    severity: IncidentSeverity | None = Query(default=None),
    status_filter: IncidentStatus | None = Query(default=None, alias="status"),
    state: IncidentStatus | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _list_incidents(
        service=service,
        services=services,
        severity=severity,
        status_value=status_filter,
        state_value=state,
        start_date=start_date,
        end_date=end_date,
        start=None,
        end=None,
        limit=limit,
        offset=offset,
        db=db,
    )


@router.get("/admin/operations/incidents/{incident_id}")
@router.get("/admin/incidents/{incident_id}", include_in_schema=False)
async def get_admin_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_incident_service.get_incident(db, str(incident_id))
    except KeyError as exc:
        raise _not_found(exc) from None


@router.post(
    "/admin/operations/incidents",
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/admin/incidents",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_admin_incident(
    body: IncidentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_incident_service.create_incident(
            db,
            actor=actor,
            request=request,
            title=body.title,
            summary=body.summary,
            severity=body.severity,
            services=body.services,
            owner=body.owner,
            links=body.links,
            related_alert_keys=body.related_alert_keys,
            deploy_sha=body.deploy_sha,
            deploy_url=body.deploy_url,
            started_at=body.started_at,
            reason=body.reason,
        )
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.patch("/admin/operations/incidents/{incident_id}")
@router.put(
    "/admin/operations/incidents/{incident_id}",
    include_in_schema=False,
)
@router.patch("/admin/incidents/{incident_id}", include_in_schema=False)
@router.put("/admin/incidents/{incident_id}", include_in_schema=False)
async def update_admin_incident(
    incident_id: UUID,
    body: IncidentUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    changes = body.model_dump(
        exclude_unset=True,
        exclude={"status", "reason"},
    )
    target_status = "open" if body.status == "active" else body.status
    try:
        if target_status in {"open", "resolved"}:
            return await admin_incident_service.transition_incident(
                db,
                incident_id=str(incident_id),
                actor=actor,
                request=request,
                target_status=target_status,
                reason=body.reason,
            )
        if not changes:
            raise ValueError("No incident changes were supplied")
        return await admin_incident_service.update_incident(
            db,
            incident_id=str(incident_id),
            actor=actor,
            request=request,
            changes=changes,
            reason=body.reason,
        )
    except KeyError as exc:
        raise _not_found(exc) from None
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/admin/operations/incidents/{incident_id}/resolve")
@router.post("/admin/incidents/{incident_id}/resolve", include_in_schema=False)
async def resolve_admin_incident(
    incident_id: UUID,
    request: Request,
    body: IncidentTransitionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_incident_service.transition_incident(
            db,
            incident_id=str(incident_id),
            actor=actor,
            request=request,
            target_status="resolved",
            reason=body.reason if body else None,
            ended_at=body.ended_at if body else None,
        )
    except KeyError as exc:
        raise _not_found(exc) from None
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/admin/operations/incidents/{incident_id}/reopen")
@router.post(
    "/admin/operations/incidents/{incident_id}/open",
    include_in_schema=False,
)
@router.post("/admin/incidents/{incident_id}/reopen", include_in_schema=False)
@router.post("/admin/incidents/{incident_id}/open", include_in_schema=False)
async def reopen_admin_incident(
    incident_id: UUID,
    request: Request,
    body: IncidentTransitionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_incident_service.transition_incident(
            db,
            incident_id=str(incident_id),
            actor=actor,
            request=request,
            target_status="open",
            reason=body.reason if body else None,
        )
    except KeyError as exc:
        raise _not_found(exc) from None
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.delete("/admin/operations/incidents/{incident_id}")
@router.delete("/admin/incidents/{incident_id}", include_in_schema=False)
async def delete_admin_incident(
    incident_id: UUID,
    request: Request,
    reason: Reason | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    try:
        return await admin_incident_service.delete_incident(
            db,
            incident_id=str(incident_id),
            actor=actor,
            request=request,
            reason=reason,
        )
    except KeyError as exc:
        raise _not_found(exc) from None
    except ValueError as exc:
        raise _unprocessable(exc) from None

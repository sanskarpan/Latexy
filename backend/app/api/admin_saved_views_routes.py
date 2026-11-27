"""Admin-only saved views and cohort segment CRUD.

Every endpoint is gated by ``require_admin_actor``. The canonical table names
are ``admin_saved_views`` and ``admin_segments`` (issue #2183); the
``/admin/saved-segments`` aliases keep the G11 wording (issue #2132) callable
without a second persistence model.

Validation, ownership, optimistic concurrency, five-user suppression and audit
all live in :mod:`app.services.admin_saved_views_service`. This module only
adapts HTTP shapes and maps domain failures to stable status codes.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_actor
from ..services import admin_saved_views_service as service
from ..services.admin_audit_service import AdminActor

router = APIRouter()

ViewScope = Literal[
    "analytics",
    "operations",
    "quality",
    "billing",
    "subscriptions",
    "email",
    "growth",
    "customers",
]
Visibility = Literal["all", "owned", "shared"]
GroupBy = Literal["plan", "role", "verified"]
ViewName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
SegmentDescription = Annotated[str, StringConstraints(max_length=280)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=280)]


class SortInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=40)
    direction: Literal["asc", "desc"] = "desc"


class SavedViewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ViewName
    scope: ViewScope
    filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list, max_length=20)
    sort: SortInput | None = None
    range_days: int | None = Field(default=None, ge=1, le=365)
    shared: bool = False
    is_default: bool = False
    reason: Reason | None = None


class SavedViewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: ViewName | None = None
    scope: ViewScope | None = None
    filters: dict[str, Any] | None = None
    columns: list[str] | None = Field(default=None, max_length=20)
    sort: SortInput | None = None
    range_days: int | None = Field(default=None, ge=1, le=365)
    shared: bool | None = None
    is_default: bool | None = None
    reason: Reason | None = None


class SegmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ViewName
    description: SegmentDescription | None = None
    definition: dict[str, Any]
    shared: bool = False
    reason: Reason | None = None


class SegmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: ViewName | None = None
    description: SegmentDescription | None = None
    definition: dict[str, Any] | None = None
    shared: bool | None = None
    reason: Reason | None = None


class SegmentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    group_by: GroupBy | None = None


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.DuplicateNameError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.VersionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.ViewPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, KeyError):
        detail = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if isinstance(exc, service.SavedViewsError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="The saved-view request could not be validated",
    )


async def _run(db: AsyncSession, awaitable: Any) -> Any:
    try:
        return await awaitable
    except (service.SavedViewsError, service.DuplicateNameError,
            service.VersionConflictError, KeyError,
            service.ViewPermissionError) as exc:
        await db.rollback()
        raise _http(exc) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A saved view or segment with this name already exists",
        ) from None


def _changes(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


@router.get("/admin/saved-views/catalog")
async def get_saved_view_catalog(
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    """Return the allowlisted scopes, filters, columns and sort keys."""
    return service.view_scope_catalog()


@router.get("/admin/saved-views")
async def list_saved_views(
    scope: ViewScope | None = Query(default=None),
    visibility: Visibility = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.list_saved_views(
            db,
            actor=actor,
            scope=scope,
            visibility=visibility,
            limit=limit,
            offset=offset,
        ),
    )


@router.post(
    "/admin/saved-views",
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_view(
    body: SavedViewCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.create_saved_view(
            db,
            actor=actor,
            name=body.name,
            scope=body.scope,
            filters=body.filters,
            columns=body.columns,
            sort=body.sort.model_dump() if body.sort else None,
            range_days=body.range_days,
            shared=body.shared,
            is_default=body.is_default,
            request=request,
        ),
    )


@router.get("/admin/saved-views/{view_id}")
async def get_saved_view(
    view_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db, service.get_saved_view(db, actor=actor, view_id=str(view_id))
    )


@router.patch("/admin/saved-views/{view_id}")
async def update_saved_view(
    view_id: UUID,
    body: SavedViewUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.update_saved_view(
            db,
            actor=actor,
            view_id=str(view_id),
            expected_version=body.expected_version,
            changes=_changes(body),
            request=request,
        ),
    )


@router.delete("/admin/saved-views/{view_id}")
async def delete_saved_view(
    view_id: UUID,
    request: Request,
    version: int = Query(ge=1),
    confirm: bool = Query(default=False),
    reason: Reason = Query(),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deletion requires confirm=true",
        )
    return await _run(
        db,
        service.delete_saved_view(
            db,
            actor=actor,
            view_id=str(view_id),
            expected_version=version,
            reason=reason,
            request=request,
        ),
    )


# --------------------------------------------------------------------------- #
#  Segments                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/admin/segments/fields")
@router.get("/admin/saved-segments/fields", include_in_schema=False)
async def get_segment_fields(
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return service.segment_field_catalog()


@router.post("/admin/segments/preview")
@router.post("/admin/saved-segments/preview", include_in_schema=False)
async def preview_segment_definition(
    body: SegmentPreviewRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.preview_segment(
            db, definition=body.definition, group_by=body.group_by
        ),
    )


@router.get("/admin/segments")
@router.get("/admin/saved-segments", include_in_schema=False)
async def list_segments(
    visibility: Visibility = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.list_segments(
            db, actor=actor, visibility=visibility, limit=limit, offset=offset
        ),
    )


@router.post(
    "/admin/segments",
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/admin/saved-segments",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def create_segment(
    body: SegmentCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.create_segment(
            db,
            actor=actor,
            name=body.name,
            description=body.description,
            definition=body.definition,
            shared=body.shared,
            request=request,
        ),
    )


@router.get("/admin/segments/{segment_id}")
@router.get("/admin/saved-segments/{segment_id}", include_in_schema=False)
async def get_segment(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db, service.get_segment(db, actor=actor, segment_id=str(segment_id))
    )


@router.get("/admin/segments/{segment_id}/preview")
@router.get(
    "/admin/saved-segments/{segment_id}/preview", include_in_schema=False
)
async def preview_saved_segment(
    segment_id: UUID,
    group_by: GroupBy | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.preview_saved_segment(
            db, actor=actor, segment_id=str(segment_id), group_by=group_by
        ),
    )


@router.patch("/admin/segments/{segment_id}")
@router.patch("/admin/saved-segments/{segment_id}", include_in_schema=False)
async def update_segment(
    segment_id: UUID,
    body: SegmentUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    return await _run(
        db,
        service.update_segment(
            db,
            actor=actor,
            segment_id=str(segment_id),
            expected_version=body.expected_version,
            changes=_changes(body),
            request=request,
        ),
    )


@router.delete("/admin/segments/{segment_id}")
@router.delete("/admin/saved-segments/{segment_id}", include_in_schema=False)
async def delete_segment(
    segment_id: UUID,
    request: Request,
    version: int = Query(ge=1),
    confirm: bool = Query(default=False),
    reason: Reason = Query(),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_actor),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Deletion requires confirm=true",
        )
    return await _run(
        db,
        service.delete_segment(
            db,
            actor=actor,
            segment_id=str(segment_id),
            expected_version=version,
            reason=reason,
            request=request,
        ),
    )


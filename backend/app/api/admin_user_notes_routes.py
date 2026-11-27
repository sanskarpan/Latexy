"""Internal user notes, tags and support-timeline HTTP surface.

Every endpoint is gated by ``require_admin_or_support``; a customer session can
never reach this router. Validation, visibility, author-or-admin edit rules,
optimistic concurrency, soft deletes and audit live in
:mod:`app.services.admin_user_notes_service`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..middleware.auth_middleware import require_admin_or_support
from ..services import admin_user_notes_service as service
from ..services.admin_audit_service import AdminActor

router = APIRouter()

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=4000)]
TagValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Visibility = Literal["internal", "admin_only"]
TimelineKind = Literal[
    "note",
    "role_change",
    "entitlement_change",
    "trial_change",
    "quota_change",
    "credential_revocation",
    "support_action",
    "pii_reveal",
    "plan_change",
    "refund",
    "refund_request",
    "subscription",
    "payment",
    "approval",
]


class NoteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: NoteBody
    tags: list[TagValue] = Field(default_factory=list, max_length=8)
    visibility: Visibility = "internal"
    reason: Reason


class NoteUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    body: NoteBody | None = None
    tags: list[TagValue] | None = Field(default=None, max_length=8)
    visibility: Visibility | None = None
    reason: Reason
    confirm: Literal[True]


class NoteDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: Reason
    confirm: Literal[True]


class TagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: TagValue
    reason: Reason


class TagDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason
    confirm: Literal[True]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, service.NotePermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, service.NoteVersionConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.NoteLegalHoldBlocked):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.DuplicateTagError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, service.NoteConfirmationRequired):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, service.NotesError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, KeyError):
        detail = str(exc.args[0]) if exc.args else "Not found"
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="The internal note request could not be validated",
    )


async def _run(db: AsyncSession, awaitable: Any) -> Any:
    try:
        return await awaitable
    except (
        service.NotesError,
        service.NotePermissionError,
        service.NoteVersionConflict,
        service.NoteLegalHoldBlocked,
        service.DuplicateTagError,
        service.NoteConfirmationRequired,
        KeyError,
    ) as exc:
        await db.rollback()
        raise _http(exc) from None
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That internal row conflicts with an existing change",
        ) from None


@router.get("/admin/users/{user_id}/notes")
async def list_admin_user_notes(
    user_id: UUID,
    tag: str | None = Query(default=None, min_length=1, max_length=32),
    author_user_id: UUID | None = Query(default=None),
    visibility: Visibility | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=service.DEFAULT_PAGE_SIZE, ge=1, le=service.MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.list_notes(
            db,
            actor=actor,
            target_user_id=str(user_id),
            tag=tag,
            author_user_id=str(author_user_id) if author_user_id else None,
            visibility=visibility,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        ),
    )


@router.post(
    "/admin/users/{user_id}/notes",
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_user_note(
    user_id: UUID,
    body: NoteCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.create_note(
            db,
            actor=actor,
            target_user_id=str(user_id),
            body=body.body,
            tags=body.tags,
            visibility=body.visibility,
            reason=body.reason,
            request=request,
        ),
    )


@router.patch("/admin/users/{user_id}/notes/{note_id}")
async def update_admin_user_note(
    user_id: UUID,
    note_id: UUID,
    body: NoteUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    return await _run(
        db,
        service.update_note(
            db,
            actor=actor,
            target_user_id=str(user_id),
            note_id=str(note_id),
            expected_version=body.expected_version,
            changes=changes,
            reason=body.reason,
            request=request,
        ),
    )


@router.delete("/admin/users/{user_id}/notes/{note_id}")
async def delete_admin_user_note(
    user_id: UUID,
    note_id: UUID,
    body: NoteDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.delete_note(
            db,
            actor=actor,
            target_user_id=str(user_id),
            note_id=str(note_id),
            reason=body.reason,
            confirm=body.confirm,
            expected_version=body.expected_version,
            request=request,
        ),
    )


@router.get("/admin/users/{user_id}/tags")
async def list_admin_user_tags(
    user_id: UUID,
    include_removed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.list_tags(
            db,
            actor=actor,
            target_user_id=str(user_id),
            include_removed=include_removed,
        ),
    )


@router.post(
    "/admin/users/{user_id}/tags",
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_user_tag(
    user_id: UUID,
    body: TagCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    payload, created = await _run(
        db,
        service.create_tag(
            db,
            actor=actor,
            target_user_id=str(user_id),
            tag=body.tag,
            reason=body.reason,
            request=request,
        ),
    )
    payload["created"] = created
    return payload


@router.delete("/admin/users/{user_id}/tags/{tag_id}")
async def remove_admin_user_tag(
    user_id: UUID,
    tag_id: UUID,
    body: TagDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.remove_tag(
            db,
            actor=actor,
            target_user_id=str(user_id),
            tag_id=str(tag_id),
            reason=body.reason,
            confirm=body.confirm,
            request=request,
        ),
    )


@router.get("/admin/users/{user_id}/support-timeline")
async def get_admin_user_support_timeline(
    user_id: UUID,
    kind: list[TimelineKind] | None = Query(default=None),
    limit: int = Query(default=service.DEFAULT_TIMELINE_LIMIT, ge=1, le=service.MAX_TIMELINE_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    actor: AdminActor = Depends(require_admin_or_support),
) -> dict[str, Any]:
    return await _run(
        db,
        service.build_support_timeline(
            db,
            actor=actor,
            target_user_id=str(user_id),
            limit=limit,
            offset=offset,
            kinds=kind or None,
        ),
    )

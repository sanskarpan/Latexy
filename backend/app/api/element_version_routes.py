"""User-owned immutable history for individual resume elements (B52).

The API records what a user saved and how it was produced.  It intentionally
does not infer interview causation: tracker statuses are returned only for an
application the user explicitly linked to a snapshot.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import JobApplication, Resume, ResumeElementVersion
from ..middleware.auth_middleware import get_current_user_required
from ..utils.uuid_guard import ensure_uuid

router = APIRouter(prefix="/resumes", tags=["resume-element-versions"])

MAX_CONTENT_BYTES = 20_000
MAX_PROVENANCE_BYTES = 4_096
MAX_VERSIONS_PER_ELEMENT = 500
MAX_VERSIONS_PER_RESUME = 5_000
_ELEMENT_KEY_RE = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"


class ElementVersionCreateRequest(BaseModel):
    element_key: str = Field(..., min_length=1, max_length=200, pattern=_ELEMENT_KEY_RE)
    element_type: Literal["bullet", "paragraph", "equation", "figure", "other"] = "bullet"
    content: str = Field(..., min_length=1, max_length=20_000)
    source: Literal["manual", "ai", "import", "restore", "fork"] = "manual"
    operation: Literal["create", "edit", "restore", "fork"] = "create"
    provenance: Dict[str, Any] = Field(default_factory=dict)
    parent_version_id: Optional[UUID] = None
    expected_head_version_id: Optional[UUID] = None
    application_id: Optional[UUID] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @field_validator("content")
    @classmethod
    def _content_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("content exceeds the 20,000-byte limit")
        if not value.strip():
            raise ValueError("content must not be blank")
        return value

    @field_validator("provenance")
    @classmethod
    def _provenance_safe(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if len(value) > 12:
            raise ValueError("provenance may contain at most 12 fields")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                raise ValueError("provenance keys must be short strings")
            if not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError("provenance values must be scalar")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("provenance numbers must be finite")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_PROVENANCE_BYTES:
            raise ValueError("provenance exceeds the 4,096-byte limit")
        return value


class ElementVersionResponse(BaseModel):
    id: str
    resume_id: str
    element_key: str
    element_type: str
    content: str
    content_hash: str
    parent_version_id: Optional[str]
    root_version_id: str
    operation: str
    source: str
    provenance: Dict[str, Any]
    application_id: Optional[str]
    created_at: datetime
    tracker_evidence: Optional[Dict[str, Any]] = None


class ElementVersionPage(BaseModel):
    items: List[ElementVersionResponse]
    next_cursor: Optional[str] = None


class ElementVersionActionRequest(BaseModel):
    expected_head_version_id: Optional[UUID] = None
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=100)


async def _owned_resume(db: AsyncSession, resume_id: str, user_id: str) -> Resume:
    ensure_uuid(resume_id, "Resume not found")
    row = (
        await db.execute(select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return row


async def _lock_owned_resume(db: AsyncSession, resume_id: str, user_id: str) -> Resume:
    """Lock the aggregate root so an empty history has a lockable row too."""
    ensure_uuid(resume_id, "Resume not found")
    row = (
        await db.execute(
            select(Resume)
            .where(Resume.id == resume_id, Resume.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return row


def _encode_cursor(created_at: datetime, version_id: str) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": version_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor timestamp must include a timezone")
        version_id = str(UUID(payload["id"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid version history cursor") from exc
    return created_at, version_id


async def _linked_application(
    db: AsyncSession,
    application_id: Optional[str],
    resume_id: str,
    user_id: str,
    *,
    strict: bool = True,
) -> Optional[JobApplication]:
    if not application_id:
        return None
    app = (
        await db.execute(
            select(JobApplication).where(
                JobApplication.id == application_id,
                JobApplication.user_id == user_id,
                JobApplication.resume_id == resume_id,
            )
        )
    ).scalar_one_or_none()
    if app is None:
        if not strict:
            return None
        raise HTTPException(status_code=400, detail="Application is not owned by you or is linked to another resume")
    return app


def _tracker_evidence(app: Optional[JobApplication]) -> Optional[Dict[str, Any]]:
    if app is None:
        return None
    return {
        "application_id": str(app.id),
        "company_name": app.company_name,
        "role_title": app.role_title,
        "status": app.status,
        "applied_at": app.applied_at,
        "source": "user_tracker",
        "interpretation": "User-recorded tracker status; this does not establish that this version caused an interview or offer.",
    }


async def _response(db: AsyncSession, row: ResumeElementVersion, user_id: str) -> ElementVersionResponse:
    # Historical rows remain readable if the user later edits/moves the
    # tracker record; only current matching linkage is shown as evidence.
    app = await _linked_application(db, row.application_id, str(row.resume_id), user_id, strict=False)
    return ElementVersionResponse(
        id=str(row.id),
        resume_id=str(row.resume_id),
        element_key=row.element_key,
        element_type=row.element_type,
        content=row.content,
        content_hash=row.content_hash,
        parent_version_id=str(row.parent_version_id) if row.parent_version_id else None,
        root_version_id=str(row.root_version_id),
        operation=row.operation,
        source=row.source,
        provenance=dict(row.provenance or {}),
        application_id=str(row.application_id) if row.application_id else None,
        created_at=row.created_at,
        tracker_evidence=_tracker_evidence(app),
    )


async def _head(
    db: AsyncSession, resume_id: str, element_key: str, user_id: str, *, lock: bool = False
) -> Optional[ResumeElementVersion]:
    stmt = (
        select(ResumeElementVersion)
        .where(
            ResumeElementVersion.resume_id == resume_id,
            ResumeElementVersion.user_id == user_id,
            ResumeElementVersion.element_key == element_key,
        )
        .order_by(ResumeElementVersion.created_at.desc(), ResumeElementVersion.id.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _parent_for_request(
    db: AsyncSession, body: ElementVersionCreateRequest, resume_id: str, user_id: str
) -> Optional[ResumeElementVersion]:
    if body.parent_version_id is None:
        return None
    parent = (
        await db.execute(
            select(ResumeElementVersion).where(
                ResumeElementVersion.id == str(body.parent_version_id),
                ResumeElementVersion.resume_id == resume_id,
                ResumeElementVersion.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent version not found")
    if body.operation != "fork" and parent.element_key != body.element_key:
        raise HTTPException(status_code=422, detail="A non-fork version must keep its parent's element identity")
    return parent


def _same_snapshot_request(
    existing: ResumeElementVersion,
    body: ElementVersionCreateRequest,
    resume_id: str,
) -> bool:
    """Compare every client-controlled semantic field on an idempotent replay.

    Idempotency keys are request identities, not content de-duplication keys.
    Comparing the complete snapshot payload prevents a retry with altered
    provenance or tracker evidence from silently replaying the old row.
    """
    expected_parent = str(body.parent_version_id) if body.parent_version_id else None
    if expected_parent is None and body.operation == "edit" and body.expected_head_version_id:
        expected_parent = str(body.expected_head_version_id)
    # A create has no head by contract.  Include this in replay matching so a
    # malformed retry cannot bypass the create/edit state-machine check.
    if body.operation == "create" and body.expected_head_version_id is not None:
        return False
    return (
        existing.resume_id == resume_id
        and existing.element_key == body.element_key
        and existing.element_type == body.element_type
        and existing.content_hash == hashlib.sha256(body.content.encode("utf-8")).hexdigest()
        and existing.operation == body.operation
        and existing.source == body.source
        and dict(existing.provenance or {}) == dict(body.provenance)
        and (str(existing.application_id) if existing.application_id else None)
        == (str(body.application_id) if body.application_id else None)
        and (str(existing.parent_version_id) if existing.parent_version_id else None) == expected_parent
    )


async def _create(
    db: AsyncSession,
    body: ElementVersionCreateRequest,
    resume_id: str,
    user_id: str,
) -> ResumeElementVersion:
    # Resume is the aggregate root. Lock it before idempotency/head/count
    # checks so both empty-history writes and writers sharing an old head are
    # serialized by the same row lock.
    await _lock_owned_resume(db, resume_id, user_id)

    # Replay is safe and does not consume another history slot.
    if body.idempotency_key:
        existing = (
            await db.execute(
                select(ResumeElementVersion).where(
                    ResumeElementVersion.user_id == user_id,
                    ResumeElementVersion.idempotency_key == body.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            if not _same_snapshot_request(existing, body, resume_id):
                raise HTTPException(status_code=409, detail="Idempotency key was used for a different snapshot")
            return existing

    head = await _head(db, resume_id, body.element_key, user_id, lock=True)
    expected_operation = "create" if head is None else "edit"
    if body.operation in {"create", "edit"} and body.operation != expected_operation:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_element_operation", "message": "Empty history requires create; existing history requires edit."},
        )
    if body.expected_head_version_id is not None and (head is None or str(head.id) != str(body.expected_head_version_id)):
        raise HTTPException(
            status_code=409,
            detail={"code": "element_version_changed", "message": "This element changed; refresh its history and retry."},
        )
    if head is not None and body.expected_head_version_id is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "element_version_changed", "message": "Provide the current head version before saving this element."},
        )
    count = (
        await db.execute(
            select(ResumeElementVersion.id)
            .where(
                ResumeElementVersion.resume_id == resume_id,
                ResumeElementVersion.user_id == user_id,
                ResumeElementVersion.element_key == body.element_key,
            )
            .limit(MAX_VERSIONS_PER_ELEMENT + 1)
        )
    ).fetchall()
    if len(count) >= MAX_VERSIONS_PER_ELEMENT:
        raise HTTPException(status_code=429, detail="This element has reached its 500-version history limit")
    total = (
        await db.execute(
            select(ResumeElementVersion.id)
            .where(
                ResumeElementVersion.resume_id == resume_id,
                ResumeElementVersion.user_id == user_id,
            )
            .limit(MAX_VERSIONS_PER_RESUME + 1)
        )
    ).fetchall()
    if len(total) >= MAX_VERSIONS_PER_RESUME:
        raise HTTPException(status_code=429, detail="This resume has reached its 5,000-version history limit")

    parent = await _parent_for_request(db, body, resume_id, user_id)
    if body.operation != "fork" and parent is not None and (head is None or str(parent.id) != str(head.id)):
        raise HTTPException(status_code=409, detail="Parent version must be the current element head")
    now = datetime.now(timezone.utc)
    version_id = str(uuid4())
    row = ResumeElementVersion(
        id=version_id,
        user_id=user_id,
        resume_id=resume_id,
        element_key=body.element_key,
        element_type=body.element_type,
        content=body.content,
        content_hash=hashlib.sha256(body.content.encode("utf-8")).hexdigest(),
        parent_version_id=str(parent.id) if parent else (str(head.id) if head else None),
        root_version_id=(
            version_id
            if body.operation == "fork"
            else str(parent.root_version_id) if parent else (str(head.root_version_id) if head else version_id)
        ),
        operation=body.operation,
        source=body.source,
        provenance=dict(body.provenance),
        application_id=str(body.application_id) if body.application_id else None,
        idempotency_key=body.idempotency_key,
        created_at=now,
    )
    await _linked_application(db, row.application_id, resume_id, user_id)
    db.add(row)
    return row


async def _commit_or_replay(
    db: AsyncSession, row: ResumeElementVersion, user_id: str
) -> ResumeElementVersion:
    """Commit once, replaying a concurrent idempotent insert if needed."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not row.idempotency_key:
            raise
        existing = (
            await db.execute(
                select(ResumeElementVersion).where(
                    ResumeElementVersion.user_id == user_id,
                    ResumeElementVersion.idempotency_key == row.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        if (
            existing.resume_id != row.resume_id
            or existing.element_key != row.element_key
            or existing.element_type != row.element_type
            or existing.content_hash != row.content_hash
            or existing.operation != row.operation
            or existing.source != row.source
            or dict(existing.provenance or {}) != dict(row.provenance or {})
            or (str(existing.application_id) if existing.application_id else None)
            != (str(row.application_id) if row.application_id else None)
            or (str(existing.parent_version_id) if existing.parent_version_id else None)
            != (str(row.parent_version_id) if row.parent_version_id else None)
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was used for a different snapshot")
        return existing
    return row


@router.post(
    "/{resume_id}/element-versions",
    response_model=ElementVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_element_version(
    resume_id: str,
    body: ElementVersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    await _owned_resume(db, resume_id, user_id)
    if body.operation not in {"create", "edit"} or body.source not in {"manual", "ai", "import"}:
        raise HTTPException(status_code=422, detail="Use the restore or fork action endpoint for those operations")
    row = await _create(db, body, resume_id, user_id)
    row = await _commit_or_replay(db, row, user_id)
    return await _response(db, row, user_id)


@router.get("/{resume_id}/element-versions", response_model=ElementVersionPage)
async def list_element_versions(
    resume_id: str,
    element_key: str = Query(..., min_length=1, max_length=200, pattern=_ELEMENT_KEY_RE),
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = Query(None, max_length=500),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    await _owned_resume(db, resume_id, user_id)
    stmt = (
        select(ResumeElementVersion)
        .where(
            ResumeElementVersion.resume_id == resume_id,
            ResumeElementVersion.user_id == user_id,
            ResumeElementVersion.element_key == element_key,
        )
        .order_by(ResumeElementVersion.created_at.desc(), ResumeElementVersion.id.desc())
        .limit(limit + 1)
    )
    if cursor:
        cursor_at, cursor_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                ResumeElementVersion.created_at < cursor_at,
                and_(ResumeElementVersion.created_at == cursor_at, ResumeElementVersion.id < cursor_id),
            )
        )
    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows.pop()
        # Cursor is the final item returned, so the next page starts strictly
        # after it. Using the excluded look-ahead row would skip that item.
        last_returned = rows[-1]
        next_cursor = _encode_cursor(last_returned.created_at, str(last_returned.id))
    return ElementVersionPage(
        items=[await _response(db, row, user_id) for row in rows],
        next_cursor=next_cursor,
    )


async def _action(
    resume_id: str,
    version_id: UUID,
    operation: Literal["restore", "fork"],
    body: ElementVersionActionRequest,
    db: AsyncSession,
    user_id: str,
):
    # Lock the aggregate before reading source/head so restore/fork shares the
    # same serialization boundary as ordinary saves.
    await _lock_owned_resume(db, resume_id, user_id)
    # Idempotent action retries must be resolved before checking the now-new
    # head.  Restore changes the head by design, and fork allocates its key at
    # first execution, so neither can be reconstructed safely after a retry.
    if body.idempotency_key:
        existing = (
            await db.execute(
                select(ResumeElementVersion).where(
                    ResumeElementVersion.user_id == user_id,
                    ResumeElementVersion.idempotency_key == body.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing:
            provenance = dict(existing.provenance or {})
            if (
                existing.resume_id != resume_id
                or existing.operation != operation
                or existing.source != operation
                or provenance.get("from_version_id") != str(version_id)
                or provenance.get("expected_head_version_id")
                != (str(body.expected_head_version_id) if body.expected_head_version_id else None)
            ):
                raise HTTPException(status_code=409, detail="Idempotency key was used for a different snapshot")
            return await _response(db, existing, user_id)
    source = (
        await db.execute(
            select(ResumeElementVersion).where(
                ResumeElementVersion.id == str(version_id),
                ResumeElementVersion.resume_id == resume_id,
                ResumeElementVersion.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Element version not found")
    head = await _head(db, resume_id, source.element_key, user_id, lock=True)
    if body.expected_head_version_id is None or head is None or str(head.id) != str(body.expected_head_version_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "element_version_changed", "message": "Refresh the element history before restoring or forking."},
        )
    key = source.element_key if operation == "restore" else f"fork-{uuid4()}"
    create_body = ElementVersionCreateRequest(
        element_key=key,
        element_type=source.element_type,
        content=source.content,
        source=operation,
        operation=operation,
        provenance={
            "from_version_id": str(source.id),
            "expected_head_version_id": str(body.expected_head_version_id),
        },
        # Restores append to the current head. Forks branch from the selected
        # historical source while creating a new root lineage.
        parent_version_id=head.id if operation == "restore" else source.id,
        expected_head_version_id=str(head.id) if operation == "restore" else None,
        application_id=UUID(str(source.application_id)) if source.application_id else None,
        idempotency_key=body.idempotency_key,
    )
    row = await _create(db, create_body, resume_id, user_id)
    row = await _commit_or_replay(db, row, user_id)
    return await _response(db, row, user_id)


@router.post("/{resume_id}/element-versions/{version_id}/restore", response_model=ElementVersionResponse)
async def restore_element_version(
    resume_id: str,
    version_id: UUID,
    body: ElementVersionActionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    return await _action(resume_id, version_id, "restore", body, db, user_id)


@router.post("/{resume_id}/element-versions/{version_id}/fork", response_model=ElementVersionResponse)
async def fork_element_version(
    resume_id: str,
    version_id: UUID,
    body: ElementVersionActionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    return await _action(resume_id, version_id, "fork", body, db, user_id)

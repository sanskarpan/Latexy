"""Internal user notes, tags and the merged User 360 support timeline.

This module is operator-only. It stores free-text notes and small tags against
a target account and composes a support-facing chronology from those rows plus
allowlisted admin-audit transitions, two-person approvals (admin only), billing
milestones and refunds.

Privacy boundary
----------------
* Notes and tags are never returned from a customer-facing route.
* Note bodies are bounded and rejected when they look like customer
  identifiers, credentials, document content or executable markup. This keeps
  free-text notes from becoming a shadow PII store while still allowing
  operational context such as ticket numbers and next steps.
* Audit snapshots for note create/edit/delete store only a SHA-256 and length,
  never the note body. Timeline events never include the body; the dedicated
  notes list is the only read surface that returns it.
* Support may read internal notes and internal timeline events. Administrator
  only notes, two-person approvals and PII-reveal audit events are restricted
  to admins. Support can edit or delete only notes/tags it authored; an admin
  may manage any internal row.

Writes require a reason, are audited in the same transaction and use optimistic
concurrency. Deletes are soft. The retention policy keeps soft-deleted notes
for review and never purges automatically.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit

MAX_NOTE_BODY = 4000
MAX_NOTE_TAGS = 8
MAX_TAG_LENGTH = 32
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_TIMELINE_LIMIT = 100
DEFAULT_TIMELINE_LIMIT = 20
MAX_TIMELINE_SOURCE_ROWS = 500

NOTE_VISIBILITIES = ("internal", "admin_only")
NOTE_RETENTION_DAYS = 730

TIMELINE_KINDS = (
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
)
ADMIN_ONLY_KINDS = frozenset({"approval", "pii_reveal"})

_RETENTION = {
    "soft_delete": True,
    "automatic_purge": False,
    "default_retention_days": NOTE_RETENTION_DAYS,
    "policy": (
        "Soft-deleted internal notes are retained for support review. No worker "
        "purges them automatically; any purge must be explicit, reason-bearing "
        "and admin-only."
    ),
}

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._\-]{12,}|sk_(?:live|test)_[a-z0-9]{8,}|"
    r"ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"xox[baprs]-[a-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"api[_-]?key\s*[:=]\s*\S{8,}|password\s*[:=]\s*\S{4,})"
)
_DOCUMENT_RE = re.compile(
    r"\\(?:documentclass|begin\s*\{\s*(?:document|resume|coverletter)|section\s*\{)",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|img|svg|style|link|meta|form|input)\b",
    re.IGNORECASE,
)
_PHONE_SHAPE_RE = re.compile(r"[+\d][\d\s().-]{7,}\d")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9_.:@-]{1,255}$")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
_MULTI_BLANK_LINES = re.compile(r"\n{4,}")


class NotesError(ValueError):
    """Validation failure mapped to HTTP 422 by the route layer."""

    code = "admin_user_note_invalid"


class NotePermissionError(PermissionError):
    """The actor may not read or mutate this internal row."""

    code = "admin_user_note_forbidden"


class NoteVersionConflict(RuntimeError):
    """The caller's optimistic-concurrency token is stale."""

    code = "admin_user_note_version_conflict"


class NoteConfirmationRequired(NotesError):
    """A destructive mutation was not explicitly confirmed."""

    code = "admin_user_note_confirmation_required"


class NoteLegalHoldBlocked(RuntimeError):
    """A legal hold blocks hiding an internal note or tag."""

    code = "admin_user_note_legal_hold"


class DuplicateTagError(ValueError):
    """An active tag already exists for this target user."""

    code = "admin_user_tag_duplicate"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


def _uuid(value: Any, *, label: str = "id") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise KeyError(f"{label} not found") from None


def _bounded_page(limit: int, offset: int, *, maximum: int = MAX_PAGE_SIZE) -> tuple[int, int]:
    cleaned_limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_PAGE_SIZE
    cleaned_offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0
    return max(1, min(cleaned_limit, maximum)), max(0, cleaned_offset)


def _clean_reason(value: Any) -> str:
    cleaned = " ".join(str(value or "").split())[:1000]
    if len(cleaned) < 3:
        raise NotesError("A reason of at least 3 characters is required")
    return cleaned


def _reject_free_text_risks(text: str, *, field: str) -> None:
    if _EMAIL_RE.search(text):
        raise NotesError(f"{field} must not contain email addresses")
    if _SSN_RE.search(text):
        raise NotesError(f"{field} must not contain national identifiers")
    if _SECRET_RE.search(text):
        raise NotesError(f"{field} must not contain credentials or secrets")
    if _DOCUMENT_RE.search(text):
        raise NotesError(f"{field} must not contain document content")
    if _HTML_TAG_RE.search(text):
        raise NotesError(f"{field} must not contain executable markup")
    if len(re.sub(r"\D", "", text)) >= 9 and _PHONE_SHAPE_RE.search(text):
        raise NotesError(f"{field} must not contain customer phone numbers")


def _clean_body(value: Any) -> str:
    if not isinstance(value, str):
        raise NotesError("body must be text")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    text = _MULTI_BLANK_LINES.sub("\n\n\n", text)
    if not 3 <= len(text) <= MAX_NOTE_BODY:
        raise NotesError(f"body must be 3-{MAX_NOTE_BODY} characters")
    _reject_free_text_risks(text, field="body")
    return text


def _clean_tag(value: Any) -> str:
    if not isinstance(value, str):
        raise NotesError("tag must be text")
    tag = value.strip().lower()
    if not 1 <= len(tag) <= MAX_TAG_LENGTH or not _TAG_RE.fullmatch(tag):
        raise NotesError(
            "tag must start with a letter or digit and contain only a-z, 0-9, _ or -"
        )
    _reject_free_text_risks(tag, field="tag")
    return tag


def _clean_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise NotesError("tags must be a list")
    cleaned: list[str] = []
    for raw in value:
        tag = _clean_tag(raw)
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_NOTE_TAGS:
        raise NotesError(f"a note may have at most {MAX_NOTE_TAGS} tags")
    return cleaned


def _clean_visibility(value: Any, *, actor: AdminActor) -> str:
    visibility = value or "internal"
    if visibility not in NOTE_VISIBILITIES:
        raise NotesError("visibility must be internal or admin_only")
    if actor.role != "admin" and visibility == "admin_only":
        raise NotePermissionError("Only an admin may create or change an admin-only note")
    return visibility


def _require_internal(actor: AdminActor) -> None:
    if actor.role not in {"admin", "support"}:
        raise NotePermissionError("Internal notes require an admin or support account")


def _can_manage(row: models.AdminUserNote, actor: AdminActor) -> bool:
    if actor.role == "admin":
        return True
    return (
        actor.role == "support"
        and str(row.author_user_id or "") == actor.user_id
        and row.visibility == "internal"
    )


def _visible(row: models.AdminUserNote, actor: AdminActor) -> bool:
    if actor.role == "admin":
        return True
    return row.visibility == "internal" and row.deleted_at is None


def _tag_can_manage(row: models.AdminUserTag, actor: AdminActor) -> bool:
    if actor.role == "admin":
        return True
    return actor.role == "support" and str(row.created_by or "") == actor.user_id


async def _ensure_user(db: AsyncSession, target_user_id: str) -> str:
    user_id = _uuid(target_user_id, label="User")
    exists = await db.scalar(select(models.User.id).where(models.User.id == user_id))
    if exists is None:
        raise KeyError("User not found")
    return user_id


async def _assert_no_legal_hold(db: AsyncSession, *, user_id: str) -> None:
    """A legal hold must keep internal evidence visible to reviewers."""
    held = await db.scalar(
        select(models.GdprLegalHold.id)
        .where(
            models.GdprLegalHold.user_id == user_id,
            models.GdprLegalHold.active.is_(True),
        )
        .limit(1)
    )
    if held is not None:
        raise NoteLegalHoldBlocked(
            "This account is under an active legal hold; notes and tags cannot be hidden"
        )


def _body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _note_audit_snapshot(row: models.AdminUserNote) -> dict[str, Any]:
    """Return the only note fields safe to persist in the audit log."""
    return {
        "note_id": str(row.id),
        "target_user_id": str(row.target_user_id),
        "visibility": row.visibility,
        "tags": list(row.tags or []),
        "version": int(row.version),
        "note_length": len(row.body or ""),
        "note_digest": _body_digest(row.body or ""),
        "edited_at": _iso(row.edited_at),
        "deleted_at": _iso(row.deleted_at),
    }


def _tag_snapshot(row: models.AdminUserTag) -> dict[str, Any]:
    return {
        "tag_id": str(row.id),
        "target_user_id": str(row.target_user_id),
        "tag": row.tag,
        "created_at": _iso(row.created_at),
        "removed_at": _iso(row.removed_at),
    }


def note_payload(row: models.AdminUserNote, actor: AdminActor) -> dict[str, Any]:
    can_manage = _visible(row, actor) and _can_manage(row, actor) and row.deleted_at is None
    return {
        "id": str(row.id),
        "target_user_id": str(row.target_user_id),
        "author_user_id": str(row.author_user_id) if row.author_user_id else None,
        "author_role": row.author_role,
        "body": row.body,
        "tags": list(row.tags or []),
        "visibility": row.visibility,
        "version": int(row.version),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "edited_at": _iso(row.edited_at),
        "updated_by": str(row.updated_by) if row.updated_by else None,
        "deleted_at": _iso(row.deleted_at),
        "deleted_by": str(row.deleted_by) if row.deleted_by else None,
        "delete_reason": row.delete_reason,
        "can_edit": bool(can_manage),
        "can_delete": bool(can_manage),
        "admin_only": row.visibility == "admin_only",
    }


def tag_payload(row: models.AdminUserTag, actor: AdminActor) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "target_user_id": str(row.target_user_id),
        "tag": row.tag,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_by_role": row.created_by_role,
        "created_at": _iso(row.created_at),
        "removed_at": _iso(row.removed_at),
        "removed_by": str(row.removed_by) if row.removed_by else None,
        "remove_reason": row.remove_reason,
        "can_remove": row.removed_at is None and _tag_can_manage(row, actor),
    }


async def _available_tags(db: AsyncSession, *, target_user_id: str, actor: AdminActor) -> list[str]:
    note_rows = (
        await db.execute(
            select(models.AdminUserNote.tags).where(
                models.AdminUserNote.target_user_id == target_user_id,
                models.AdminUserNote.deleted_at.is_(None),
                *(() if actor.role == "admin" else (models.AdminUserNote.visibility == "internal",)),
            )
        )
    ).scalars().all()
    tag_rows = (
        await db.execute(
            select(models.AdminUserTag.tag).where(
                models.AdminUserTag.target_user_id == target_user_id,
                models.AdminUserTag.removed_at.is_(None),
            )
        )
    ).scalars().all()
    values: set[str] = {str(tag) for tag in tag_rows}
    for row_tags in note_rows:
        if isinstance(row_tags, list):
            values.update(str(tag) for tag in row_tags if isinstance(tag, str))
    return sorted(values)[:100]


async def list_notes(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    tag: str | None = None,
    author_user_id: str | None = None,
    visibility: str | None = None,
    include_deleted: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    _require_internal(actor)
    user_id = await _ensure_user(db, target_user_id)
    if include_deleted and actor.role != "admin":
        raise NotePermissionError("Only an admin may inspect soft-deleted notes")
    conditions: list[Any] = [models.AdminUserNote.target_user_id == user_id]
    if actor.role != "admin":
        conditions.append(models.AdminUserNote.visibility == "internal")
        if visibility == "admin_only":
            raise NotePermissionError("Administrator-only notes are not visible to support")
    if visibility is not None:
        if visibility not in NOTE_VISIBILITIES:
            raise NotesError("visibility must be internal or admin_only")
        if actor.role == "admin":
            conditions.append(models.AdminUserNote.visibility == visibility)
    if not include_deleted:
        conditions.append(models.AdminUserNote.deleted_at.is_(None))
    if tag is not None:
        conditions.append(models.AdminUserNote.tags.contains([_clean_tag(tag)]))
    if author_user_id is not None:
        conditions.append(
            models.AdminUserNote.author_user_id == _uuid(author_user_id, label="Author")
        )
    page_limit, page_offset = _bounded_page(limit, offset)
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(models.AdminUserNote)
                .where(*conditions)
            )
        ).scalar_one()
    )
    rows = (
        await db.execute(
            select(models.AdminUserNote)
            .where(*conditions)
            .order_by(
                models.AdminUserNote.created_at.desc(),
                models.AdminUserNote.id.desc(),
            )
            .limit(page_limit)
            .offset(page_offset)
        )
    ).scalars().all()
    items = [
        note_payload(row, actor)
        for row in rows
        if row.deleted_at is None or actor.role == "admin"
    ]
    return {
        "items": items,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
        "has_more": page_offset + len(items) < total,
        "next_offset": page_offset + len(items) if page_offset + len(items) < total else None,
        "viewer_role": actor.role,
        "available_tags": await _available_tags(db, target_user_id=user_id, actor=actor),
        "retention": dict(_RETENTION),
    }


async def create_note(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    body: str,
    tags: Sequence[str] | None,
    visibility: str | None,
    reason: str,
    request: Any = None,
) -> dict[str, Any]:
    _require_internal(actor)
    user_id = await _ensure_user(db, target_user_id)
    cleaned_reason = _clean_reason(reason)
    cleaned_body = _clean_body(body)
    cleaned_tags = _clean_tags(tags)
    cleaned_visibility = _clean_visibility(visibility, actor=actor)
    row = models.AdminUserNote(
        target_user_id=user_id,
        author_user_id=actor.user_id,
        author_role=actor.role,
        body=cleaned_body,
        tags=cleaned_tags,
        visibility=cleaned_visibility,
    )
    db.add(row)
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.user_note.create",
        target_type="admin_user_note",
        target_id=str(row.id),
        reason=cleaned_reason,
        after=_note_audit_snapshot(row),
        metadata={
            "target_user_id": user_id,
            "visibility": cleaned_visibility,
            "note_digest": _body_digest(cleaned_body),
            "note_length": len(cleaned_body),
            "tags": cleaned_tags,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return note_payload(row, actor)


async def _load_note(
    db: AsyncSession, *, target_user_id: str, note_id: str
) -> models.AdminUserNote:
    user_id = _uuid(target_user_id, label="User")
    canonical_note_id = _uuid(note_id, label="Note")
    row = (
        await db.execute(
            select(models.AdminUserNote)
            .where(
                models.AdminUserNote.id == canonical_note_id,
                models.AdminUserNote.target_user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError("Note not found")
    return row


async def update_note(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    note_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
    reason: str,
    request: Any = None,
) -> dict[str, Any]:
    _require_internal(actor)
    row = await _load_note(db, target_user_id=target_user_id, note_id=note_id)
    if not _visible(row, actor) or not _can_manage(row, actor):
        raise KeyError("Note not found")
    if row.deleted_at is not None:
        raise KeyError("Note not found")
    if int(expected_version) != int(row.version):
        raise NoteVersionConflict("Note changed elsewhere; reload before retrying")
    changed_fields = sorted(
        field
        for field in set(changes) - {"reason", "confirm", "expected_version"}
        if changes.get(field) is not None
    )
    if not changed_fields:
        raise NotesError("No note changes were supplied")
    before = _note_audit_snapshot(row)
    if "body" in changes and changes["body"] is not None:
        row.body = _clean_body(changes["body"])
    if "tags" in changes and changes["tags"] is not None:
        row.tags = _clean_tags(changes["tags"])
    if "visibility" in changes and changes["visibility"] is not None:
        row.visibility = _clean_visibility(changes["visibility"], actor=actor)
    row.version = int(row.version) + 1
    row.updated_by = actor.user_id
    row.edited_at = _now()
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.user_note.update",
        target_type="admin_user_note",
        target_id=str(row.id),
        reason=_clean_reason(reason),
        before=before,
        after=_note_audit_snapshot(row),
        metadata={
            "target_user_id": str(row.target_user_id),
            "changed_fields": changed_fields,
            "note_digest": _body_digest(row.body),
            "note_length": len(row.body),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return note_payload(row, actor)


async def delete_note(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    note_id: str,
    reason: str,
    confirm: bool,
    expected_version: int | None = None,
    request: Any = None,
) -> dict[str, Any]:
    _require_internal(actor)
    if confirm is not True:
        raise NoteConfirmationRequired("Deleting a note requires explicit confirmation")
    row = await _load_note(db, target_user_id=target_user_id, note_id=note_id)
    if not _visible(row, actor) or not _can_manage(row, actor):
        raise KeyError("Note not found")
    if row.deleted_at is not None:
        payload = note_payload(row, actor)
        payload["already_deleted"] = True
        return payload
    if expected_version is not None and int(expected_version) != int(row.version):
        raise NoteVersionConflict("Note changed elsewhere; reload before retrying")
    await _assert_no_legal_hold(db, user_id=str(row.target_user_id))
    before = _note_audit_snapshot(row)
    row.deleted_at = _now()
    row.deleted_by = actor.user_id
    row.delete_reason = _clean_reason(reason)
    row.updated_by = actor.user_id
    row.version = int(row.version) + 1
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.user_note.delete",
        target_type="admin_user_note",
        target_id=str(row.id),
        reason=row.delete_reason,
        before=before,
        after=_note_audit_snapshot(row),
        metadata={
            "target_user_id": str(row.target_user_id),
            "soft_delete": True,
            "note_digest": _body_digest(row.body),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    payload = note_payload(row, actor)
    payload["already_deleted"] = False
    return payload


async def list_tags(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    include_removed: bool = False,
) -> dict[str, Any]:
    _require_internal(actor)
    user_id = await _ensure_user(db, target_user_id)
    if include_removed and actor.role != "admin":
        raise NotePermissionError("Only an admin may inspect removed tags")
    conditions: list[Any] = [models.AdminUserTag.target_user_id == user_id]
    if not include_removed:
        conditions.append(models.AdminUserTag.removed_at.is_(None))
    rows = (
        await db.execute(
            select(models.AdminUserTag)
            .where(*conditions)
            .order_by(models.AdminUserTag.created_at.desc(), models.AdminUserTag.id.desc())
            .limit(MAX_PAGE_SIZE)
        )
    ).scalars().all()
    return {
        "items": [tag_payload(row, actor) for row in rows],
        "total": len(rows),
        "limit": MAX_PAGE_SIZE,
        "offset": 0,
        "viewer_role": actor.role,
        "retention": dict(_RETENTION),
    }


async def create_tag(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    tag: str,
    reason: str,
    request: Any = None,
) -> tuple[dict[str, Any], bool]:
    _require_internal(actor)
    user_id = await _ensure_user(db, target_user_id)
    cleaned_reason = _clean_reason(reason)
    cleaned_tag = _clean_tag(tag)
    existing = (
        await db.execute(
            select(models.AdminUserTag)
            .where(
                models.AdminUserTag.target_user_id == user_id,
                models.AdminUserTag.tag == cleaned_tag,
                models.AdminUserTag.removed_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return tag_payload(existing, actor), False
    row = models.AdminUserTag(
        target_user_id=user_id,
        tag=cleaned_tag,
        created_by=actor.user_id,
        created_by_role=actor.role,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise DuplicateTagError("This tag is already active for the user") from exc
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.user_tag.create",
        target_type="admin_user_tag",
        target_id=str(row.id),
        reason=cleaned_reason,
        after=_tag_snapshot(row),
        metadata={"target_user_id": user_id, "tag": cleaned_tag},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return tag_payload(row, actor), True


async def remove_tag(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    tag_id: str,
    reason: str,
    confirm: bool,
    request: Any = None,
) -> dict[str, Any]:
    _require_internal(actor)
    if confirm is not True:
        raise NoteConfirmationRequired("Removing a tag requires explicit confirmation")
    user_id = _uuid(target_user_id, label="User")
    canonical_tag_id = _uuid(tag_id, label="Tag")
    row = (
        await db.execute(
            select(models.AdminUserTag)
            .where(
                models.AdminUserTag.id == canonical_tag_id,
                models.AdminUserTag.target_user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or not _tag_can_manage(row, actor):
        raise KeyError("Tag not found")
    if row.removed_at is not None:
        payload = tag_payload(row, actor)
        payload["already_removed"] = True
        return payload
    await _assert_no_legal_hold(db, user_id=str(row.target_user_id))
    cleaned_reason = _clean_reason(reason)
    before = _tag_snapshot(row)
    row.removed_at = _now()
    row.removed_by = actor.user_id
    row.remove_reason = cleaned_reason
    await db.flush()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.user_tag.remove",
        target_type="admin_user_tag",
        target_id=str(row.id),
        reason=cleaned_reason,
        before=before,
        after=_tag_snapshot(row),
        metadata={"target_user_id": user_id, "tag": row.tag},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    payload = tag_payload(row, actor)
    payload["already_removed"] = False
    return payload


# ---------------------------------------------------------------------------
#  Merged support timeline
# ---------------------------------------------------------------------------

_ACTION_RULES: dict[str, tuple[str, str]] = {
    "user.role.change": ("role_change", "Role change"),
    "user.feature.grant": ("entitlement_change", "Entitlement granted"),
    "user.feature.revoke": ("entitlement_change", "Entitlement revoked"),
    "user.trial.extend": ("trial_change", "Trial extended"),
    "user.trial.eligibility": ("trial_change", "Trial eligibility changed"),
    "user.trial.reset": ("trial_change", "Trial reset"),
    "user.plan.change": ("plan_change", "Plan changed"),
    "user.quota.reset.completed": ("quota_change", "Quota counters reset"),
    "user.quota.reset.failed": ("quota_change", "Quota reset failed"),
    "user.sessions.revoke": ("credential_revocation", "Sessions revoked"),
    "user.session.revoke": ("credential_revocation", "Session revoked"),
    "user.passkeys.revoke": ("credential_revocation", "Passkeys revoked"),
    "user.passkey.revoke": ("credential_revocation", "Passkey revoked"),
    "user.api_keys.revoke": ("credential_revocation", "API keys deactivated"),
    "user.byok_key.revoke": ("credential_revocation", "BYOK key deactivated"),
    "user.developer_key.revoke": ("credential_revocation", "Developer key deactivated"),
    "user.pii.reveal": ("pii_reveal", "PII field revealed"),
    "user.verification_email.send.completed": ("support_action", "Verification email sent"),
    "user.verification_email.send.failed": ("support_action", "Verification email failed"),
    "user.password_reset.send.completed": ("support_action", "Password reset email sent"),
    "user.password_reset.send.failed": ("support_action", "Password reset email failed"),
    "user.payment_receipt.send.completed": ("support_action", "Payment receipt sent"),
    "user.payment_receipt.send.failed": ("support_action", "Payment receipt failed"),
}

_CREDENTIAL_ACTION_LABELS = {
    "user.sessions.revoke": "all sessions",
    "user.session.revoke": "one session",
    "user.passkeys.revoke": "all passkeys",
    "user.passkey.revoke": "one passkey",
    "user.api_keys.revoke": "all API keys",
    "user.byok_key.revoke": "one BYOK key",
    "user.developer_key.revoke": "one developer key",
}


def _safe_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned[:limit] if cleaned else None


def _safe_label(value: Any) -> str | None:
    text = _safe_text(value, limit=120)
    return text if text and _SAFE_LABEL.fullmatch(text) else None


def _safe_reference(value: Any) -> str | None:
    text = _safe_text(value, limit=255)
    return text if text and _SAFE_REFERENCE.fullmatch(text) else None


def _safe_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _event_sort_at(value: datetime | None) -> datetime:
    return _utc(value) or datetime.min.replace(tzinfo=timezone.utc)


def _money_summary(prefix: str, status: Any, amount: Any, currency: Any) -> str:
    parts = [prefix]
    clean_status = _safe_text(status, limit=32)
    if clean_status:
        parts.append(clean_status)
    if amount is not None:
        parts.append(f"{int(amount) / 100:.2f} {(_safe_text(currency, limit=3) or 'UNKNOWN').upper()}")
    return " - ".join(parts)


def _history_summary(row: models.SubscriptionHistory) -> str:
    event = (_safe_text(row.event_type, limit=32) or "subscription change").replace("_", " ")
    if row.previous_plan_id and row.previous_plan_id != row.plan_id:
        return f"{event} - {row.previous_plan_id} to {row.plan_id}"
    return f"{event} - {row.plan_id}"


def _audit_event(row: models.AdminAuditLog) -> tuple[str, dict[str, Any]] | None:
    rule = _ACTION_RULES.get(row.action)
    if rule is None:
        return None
    kind, summary = rule
    before = _safe_mapping(row.before_state)
    after = _safe_mapping(row.after_state)
    metadata = _safe_mapping(row.event_metadata)
    details: dict[str, Any] = {}
    if kind == "role_change":
        previous = _safe_label(before.get("role"))
        current = _safe_label(after.get("role"))
        if previous or current:
            summary = f"Role changed - {previous or 'unknown'} to {current or 'unknown'}"
            details.update({"previous_role": previous, "new_role": current})
    elif kind == "entitlement_change":
        feature = _safe_label(metadata.get("feature_key"))
        override = after.get("override")
        if feature:
            summary = f"{summary} - {feature}"
            details["feature_key"] = feature
        if isinstance(override, bool):
            details["enabled"] = override
    elif kind == "trial_change":
        extended_until = _safe_text(after.get("extended_until"), limit=40)
        eligible = after.get("eligible")
        if extended_until:
            summary = f"{summary} - until {extended_until}"
        if isinstance(eligible, bool):
            summary = f"{summary} - {'eligible' if eligible else 'ineligible'}"
            details["eligible"] = eligible
    elif kind == "plan_change":
        previous = _safe_label(before.get("subscription_plan"))
        current = _safe_label(after.get("subscription_plan"))
        if previous or current:
            summary = f"Plan changed - {previous or 'unknown'} to {current or 'unknown'}"
            details.update({"previous_plan": previous, "new_plan": current})
    elif kind == "quota_change":
        dimensions = before.get("dimensions")
        if isinstance(dimensions, list):
            details["dimensions"] = [
                value for value in (_safe_label(item) for item in dimensions[:8]) if value
            ]
    elif kind == "credential_revocation":
        scope = _CREDENTIAL_ACTION_LABELS.get(row.action)
        if scope:
            details["scope"] = scope
    elif kind == "pii_reveal":
        field = _safe_label(metadata.get("field") or before.get("field"))
        if field in {"email", "name"}:
            summary = f"{field.title()} revealed"
            details["field"] = field
    elif kind == "support_action":
        result = _safe_label(after.get("result"))
        if result:
            details["result"] = result
        if row.action.endswith(".failed"):
            details["failed"] = True
    return kind, {
        "id": f"{kind}:{row.id}",
        "kind": kind,
        "occurred_at": _iso(row.created_at),
        "summary": summary,
        "event_type": row.action,
        "source": "admin",
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "actor_role": None,
        "status": None,
        "amount_minor": None,
        "currency": None,
        "reference": None,
        "admin_only": kind in ADMIN_ONLY_KINDS,
        "details": details,
    }


def _note_event(row: models.AdminUserNote, *, edited: bool) -> dict[str, Any]:
    at = row.edited_at if edited else row.created_at
    actor_user_id = row.updated_by or row.author_user_id
    actor_role = row.author_role
    if edited and actor_user_id and str(actor_user_id) != str(row.author_user_id or ""):
        actor_role = "admin"
    return {
        "id": f"note:{row.id}:{'edited' if edited else 'created'}",
        "kind": "note",
        "occurred_at": _iso(at),
        "summary": "Internal note edited" if edited else "Internal note added",
        "event_type": "admin.user_note.update" if edited else "admin.user_note.create",
        "source": "note",
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_role": actor_role,
        "status": None,
        "amount_minor": None,
        "currency": None,
        "reference": None,
        "admin_only": row.visibility == "admin_only",
        "details": {
            "note_id": str(row.id),
            "visibility": row.visibility,
            "tags": list(row.tags or []),
            "version": int(row.version),
        },
    }


async def build_support_timeline(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    limit: int = DEFAULT_TIMELINE_LIMIT,
    offset: int = 0,
    kinds: Sequence[str] | None = None,
) -> dict[str, Any]:
    _require_internal(actor)
    user_id = await _ensure_user(db, target_user_id)
    requested = list(kinds) if kinds else []
    if requested:
        unknown = sorted(set(requested) - set(TIMELINE_KINDS))
        if unknown:
            raise NotesError("Unknown timeline kind")
    selected = set(requested) if requested else None
    page_limit, page_offset = _bounded_page(limit, offset, maximum=MAX_TIMELINE_LIMIT)

    note_conditions: list[Any] = [
        models.AdminUserNote.target_user_id == user_id,
        models.AdminUserNote.deleted_at.is_(None),
    ]
    if actor.role != "admin":
        note_conditions.append(models.AdminUserNote.visibility == "internal")
    notes = (
        await db.execute(
            select(models.AdminUserNote)
            .where(*note_conditions)
            .order_by(models.AdminUserNote.created_at.desc())
            .limit(MAX_TIMELINE_SOURCE_ROWS)
        )
    ).scalars().all()

    audits = (
        await db.execute(
            select(models.AdminAuditLog)
            .where(
                models.AdminAuditLog.target_type == "user",
                models.AdminAuditLog.target_id == user_id,
                models.AdminAuditLog.action.in_(tuple(_ACTION_RULES)),
            )
            .order_by(models.AdminAuditLog.created_at.desc())
            .limit(MAX_TIMELINE_SOURCE_ROWS)
        )
    ).scalars().all()
    audit_projected = [
        (row, projected)
        for row in audits
        if (projected := _audit_event(row)) is not None
    ]

    payments = (
        await db.execute(
            select(models.Payment)
            .where(models.Payment.user_id == user_id)
            .order_by(models.Payment.created_at.desc())
            .limit(MAX_TIMELINE_SOURCE_ROWS)
        )
    ).scalars().all()
    payment_ids = [row.id for row in payments]
    refunds: Sequence[models.PaymentRefund] = []
    if payment_ids:
        refunds = (
            await db.execute(
                select(models.PaymentRefund)
                .where(models.PaymentRefund.payment_id.in_(payment_ids))
                .order_by(models.PaymentRefund.created_at.desc())
                .limit(MAX_TIMELINE_SOURCE_ROWS)
            )
        ).scalars().all()
    refund_requests = (
        await db.execute(
            select(models.AdminRefundRequest)
            .join(models.Payment, models.Payment.id == models.AdminRefundRequest.payment_id)
            .where(models.Payment.user_id == user_id)
            .order_by(models.AdminRefundRequest.requested_at.desc())
            .limit(MAX_TIMELINE_SOURCE_ROWS)
        )
    ).scalars().all()
    histories = (
        await db.execute(
            select(models.SubscriptionHistory)
            .where(models.SubscriptionHistory.user_id == user_id)
            .order_by(models.SubscriptionHistory.effective_at.desc())
            .limit(MAX_TIMELINE_SOURCE_ROWS)
        )
    ).scalars().all()

    approvals: Sequence[models.AdminApproval] = []
    if actor.role == "admin":
        refund_request_ids = [str(row.id) for row in refund_requests]
        clauses = [
            and_(
                models.AdminApproval.resource_type == "user",
                models.AdminApproval.resource_id == user_id,
            ),
            models.AdminApproval.payload["target_user_id"].astext == user_id,
        ]
        if refund_request_ids:
            clauses.append(
                and_(
                    models.AdminApproval.resource_type == "refund_request",
                    models.AdminApproval.resource_id.in_(refund_request_ids),
                )
            )
        approvals = (
            await db.execute(
                select(models.AdminApproval)
                .where(or_(*clauses))
                .order_by(models.AdminApproval.requested_at.desc())
                .limit(MAX_TIMELINE_SOURCE_ROWS)
            )
        ).scalars().all()

    events: list[tuple[datetime, str, str, dict[str, Any]]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: dict[str, Any], *, source_id: str, suffix: str = "") -> None:
        occurred = item.get("occurred_at")
        if not occurred:
            return
        key = (item["kind"], source_id, suffix)
        if key in seen:
            return
        seen.add(key)
        try:
            occurred_at = datetime.fromisoformat(str(occurred))
        except ValueError:
            return
        events.append((_event_sort_at(occurred_at), item["kind"], item["id"], item))

    for row in notes:
        add(_note_event(row, edited=False), source_id=str(row.id), suffix="created")
        if row.edited_at is not None:
            add(_note_event(row, edited=True), source_id=str(row.id), suffix="edited")

    for row, projected in audit_projected:
        _kind, item = projected
        add(item, source_id=str(row.id))

    for row in histories:
        item = {
            "id": f"subscription:{row.id}",
            "kind": "subscription",
            "occurred_at": _iso(row.effective_at or row.recorded_at),
            "summary": _history_summary(row),
            "event_type": _safe_text(row.event_type, limit=32),
            "source": "billing",
            "actor_user_id": None,
            "actor_role": None,
            "status": _safe_text(row.status, limit=50),
            "amount_minor": None,
            "currency": None,
            "reference": None,
            "admin_only": False,
            "details": {
                "plan_id": _safe_label(row.plan_id),
                "previous_plan_id": _safe_label(row.previous_plan_id),
                "status": _safe_text(row.status, limit=50),
                "previous_status": _safe_text(row.previous_status, limit=50),
            },
        }
        add(item, source_id=str(row.id))

    for row in payments:
        item = {
            "id": f"payment:{row.id}",
            "kind": "payment",
            "occurred_at": _iso(row.created_at),
            "summary": _money_summary("Payment", row.status, row.amount, row.currency),
            "event_type": "payment",
            "source": "billing",
            "actor_user_id": None,
            "actor_role": None,
            "status": _safe_text(row.status, limit=50),
            "amount_minor": int(row.amount) if row.amount is not None else None,
            "currency": _safe_text(row.currency, limit=3),
            "reference": _safe_reference(row.provider_payment_id),
            "admin_only": False,
            "details": {"payment_method": _safe_text(row.payment_method, limit=50)},
        }
        add(item, source_id=str(row.id))

    for row in refunds:
        item = {
            "id": f"refund:{row.id}",
            "kind": "refund",
            "occurred_at": _iso(row.created_at),
            "summary": _money_summary("Refund", row.status, row.amount, row.currency),
            "event_type": "refund",
            "source": "billing",
            "actor_user_id": None,
            "actor_role": None,
            "status": _safe_text(row.status, limit=24),
            "amount_minor": int(row.amount) if row.amount is not None else None,
            "currency": _safe_text(row.currency, limit=3),
            "reference": _safe_reference(row.provider_refund_id),
            "admin_only": False,
            "details": {"payment_id": str(row.payment_id)},
        }
        add(item, source_id=str(row.id))

    for row in refund_requests:
        latest = row.executed_at or row.decided_at or row.requested_at
        item = {
            "id": f"refund_request:{row.id}",
            "kind": "refund_request",
            "occurred_at": _iso(latest),
            "summary": f"Refund request {_safe_text(row.status, limit=24) or 'updated'}",
            "event_type": "refund_request",
            "source": "billing",
            "actor_user_id": str(row.requested_by) if row.requested_by else None,
            "actor_role": None,
            "status": _safe_text(row.status, limit=24),
            "amount_minor": int(row.amount) if row.amount is not None else None,
            "currency": _safe_text(row.currency, limit=3),
            "reference": None,
            "admin_only": False,
            "details": {
                "requested_at": _iso(row.requested_at),
                "decided_at": _iso(row.decided_at),
                "executed_at": _iso(row.executed_at),
            },
        }
        add(item, source_id=str(row.id))

    for row in approvals:
        request_type = _safe_label(row.request_type) or "approval"
        base_details = {"request_type": request_type, "approval_id": str(row.id)}
        add(
            {
                "id": f"approval:{row.id}:requested",
                "kind": "approval",
                "occurred_at": _iso(row.requested_at),
                "summary": f"Approval requested - {request_type.replace('_', ' ')}",
                "event_type": "approval.requested",
                "source": "approval",
                "actor_user_id": str(row.requested_by) if row.requested_by else None,
                "actor_role": "admin",
                "status": "requested",
                "amount_minor": None,
                "currency": None,
                "reference": None,
                "admin_only": True,
                "details": dict(base_details),
            },
            source_id=str(row.id),
            suffix="requested",
        )
        if row.decided_at is not None:
            decision = "approved" if row.approved_by else (_safe_text(row.status, limit=24) or "decided")
            add(
                {
                    "id": f"approval:{row.id}:decided",
                    "kind": "approval",
                    "occurred_at": _iso(row.decided_at),
                    "summary": f"Approval {decision} - {request_type.replace('_', ' ')}",
                    "event_type": "approval.decided",
                    "source": "approval",
                    "actor_user_id": str(row.approved_by) if row.approved_by else None,
                    "actor_role": "admin",
                    "status": decision,
                    "amount_minor": None,
                    "currency": None,
                    "reference": None,
                    "admin_only": True,
                    "details": dict(base_details),
                },
                source_id=str(row.id),
                suffix="decided",
            )
        if row.executed_at is not None:
            add(
                {
                    "id": f"approval:{row.id}:executed",
                    "kind": "approval",
                    "occurred_at": _iso(row.executed_at),
                    "summary": f"Approval executed - {request_type.replace('_', ' ')}",
                    "event_type": "approval.executed",
                    "source": "approval",
                    "actor_user_id": str(row.executed_by) if row.executed_by else None,
                    "actor_role": "admin",
                    "status": "executed",
                    "amount_minor": None,
                    "currency": None,
                    "reference": None,
                    "admin_only": True,
                    "details": dict(base_details),
                },
                source_id=str(row.id),
                suffix="executed",
            )

    visible = [row for row in events if actor.role == "admin" or not row[3]["admin_only"]]
    counts: dict[str, int] = {}
    for _occurred, kind, _id, _item in visible:
        counts[kind] = counts.get(kind, 0) + 1
    filtered = [
        row for row in visible if selected is None or row[1] in selected
    ]
    filtered.sort(key=lambda row: (row[0], row[2]), reverse=True)
    total = len(filtered)
    page = [row[3] for row in filtered[page_offset : page_offset + page_limit]]
    visible_audits = sum(
        1
        for _row, projected in audit_projected
        if actor.role == "admin" or not projected[1]["admin_only"]
    )
    sources = {
        "notes": len(notes),
        "admin_actions": visible_audits,
        "payments": len(payments),
        "refunds": len(refunds),
        "refund_requests": len(refund_requests),
        "subscription_history": len(histories),
        "approvals": len(approvals) if actor.role == "admin" else 0,
    }
    return {
        "items": page,
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
        "has_more": page_offset + len(page) < total,
        "next_offset": page_offset + len(page) if page_offset + len(page) < total else None,
        "order": "desc",
        "viewer_role": actor.role,
        "restricted_kinds": sorted(ADMIN_ONLY_KINDS) if actor.role != "admin" else [],
        "kinds": list(TIMELINE_KINDS),
        "counts": counts,
        "sources": sources,
        "retention": dict(_RETENTION),
    }


async def build_user_support_bundle(
    db: AsyncSession,
    *,
    actor: AdminActor,
    target_user_id: str,
    note_limit: int = 10,
    timeline_limit: int = 10,
) -> dict[str, Any]:
    """Compose the live support block attached to one User 360 payload."""
    notes = await list_notes(
        db,
        actor=actor,
        target_user_id=target_user_id,
        limit=note_limit,
        offset=0,
    )
    tags = await list_tags(db, actor=actor, target_user_id=target_user_id)
    timeline = await build_support_timeline(
        db,
        actor=actor,
        target_user_id=target_user_id,
        limit=timeline_limit,
        offset=0,
    )
    return {
        "notes": notes["items"],
        "note_count": notes["total"],
        "available_tags": notes["available_tags"],
        "tags": tags["items"],
        "timeline": timeline,
        "retention": dict(_RETENTION),
    }

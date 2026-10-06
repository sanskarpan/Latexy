"""Team workspace routes (Feature 66)."""

import re
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import (
    Compilation,
    RecruiterNote,
    Resume,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..utils.bounded_io import MAX_COMPILED_PDF_BYTES, BoundedReadError, decode_base64_bounded
from ..utils.file_utils import get_job_files
from ..utils.uuid_guard import ensure_uuid

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

VALID_ROLES = frozenset({"editor", "viewer"})
_MAX_WORKSPACE_PDF_BYTES = 20 * 1024 * 1024

# ── Schemas ──────────────────────────────────────────────────────────────────


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class MemberResponse(BaseModel):
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: str
    invited_at: Optional[str] = None
    joined_at: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    plan_id: str
    max_members: int
    member_count: int = 0
    resume_count: int = 0
    created_at: str


class WorkspaceDetailResponse(WorkspaceResponse):
    members: List[MemberResponse] = []


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteRequest(BaseModel):
    email: str = Field(..., max_length=255)
    role: str = Field(default="editor")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v.lower()


class RoleUpdateRequest(BaseModel):
    role: str


class ResumeInWorkspace(BaseModel):
    id: str
    title: str
    owner_id: str
    shared_by: Optional[str] = None
    shared_at: str
    # These legacy timestamps are only written when the resume owner accesses
    # their own submission. Keep the names for API compatibility, but make the
    # actor/source explicit so consumers cannot present them as reviewer or
    # employer activity.
    opened_at: Optional[str] = None
    opened_actor: Optional[Literal["candidate"]] = None
    opened_source: Optional[Literal["candidate_self"]] = None
    downloaded_at: Optional[str] = None
    downloaded_actor: Optional[Literal["candidate"]] = None
    downloaded_source: Optional[Literal["candidate_self"]] = None


class RecruiterNoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class RecruiterNoteUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class RecruiterNoteResponse(BaseModel):
    id: str
    workspace_id: str
    resume_id: str
    author_id: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    content: str
    created_at: str
    updated_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_workspace_or_404(workspace_id: str, db: AsyncSession) -> Workspace:
    ensure_uuid(workspace_id, "Workspace not found")
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


async def _require_member(
    workspace: Workspace, user_id: str, db: AsyncSession
) -> WorkspaceMember:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")
    return member


async def _require_owner(workspace: Workspace, user_id: str) -> None:
    if workspace.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the workspace owner can perform this action")


async def _require_editor(
    workspace: Workspace, user_id: str, db: AsyncSession
) -> WorkspaceMember:
    """Require a role that may contribute workspace content."""
    member = await _require_member(workspace, user_id, db)
    if member.role not in {"owner", "editor"}:
        raise HTTPException(
            status_code=403,
            detail="Workspace viewers cannot create or edit recruiter notes",
        )
    return member


def _ws_to_response(
    ws: Workspace, member_count: int = 0, resume_count: int = 0
) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        owner_id=ws.owner_id,
        plan_id=ws.plan_id,
        max_members=ws.max_members,
        member_count=member_count,
        resume_count=resume_count,
        created_at=ws.created_at.isoformat(),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=201,
    dependencies=[Depends(require_feature("team_workspaces"))],
)
async def create_workspace(
    body: WorkspaceCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Create a workspace. Owner is auto-added as member with role 'owner'."""
    ws = Workspace(name=body.name, owner_id=user_id)
    db.add(ws)
    await db.flush()  # populate ws.id before inserting member

    member = WorkspaceMember(
        workspace_id=ws.id,
        user_id=user_id,
        role="owner",
        joined_at=datetime.now(timezone.utc),
    )
    db.add(member)
    await db.commit()
    await db.refresh(ws)
    return _ws_to_response(ws, member_count=1)


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List all workspaces the current user belongs to."""
    id_result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    )
    ws_ids = [row[0] for row in id_result.fetchall()]
    if not ws_ids:
        return []

    ws_result = await db.execute(select(Workspace).where(Workspace.id.in_(ws_ids)))
    workspaces = ws_result.scalars().all()

    # Batch member counts keyed by workspace_id
    mc_result = await db.execute(
        select(WorkspaceMember.workspace_id, func.count())
        .where(WorkspaceMember.workspace_id.in_(ws_ids))
        .group_by(WorkspaceMember.workspace_id)
    )
    member_counts = {row[0]: row[1] for row in mc_result.all()}

    # Batch resume counts keyed by workspace_id
    rc_result = await db.execute(
        select(WorkspaceResume.workspace_id, func.count())
        .where(WorkspaceResume.workspace_id.in_(ws_ids))
        .group_by(WorkspaceResume.workspace_id)
    )
    resume_counts = {row[0]: row[1] for row in rc_result.all()}

    return [
        _ws_to_response(
            ws,
            member_count=member_counts.get(ws.id, 0),
            resume_count=resume_counts.get(ws.id, 0),
        )
        for ws in workspaces
    ]


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace(
    workspace_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get workspace details including member list."""
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_member(ws, user_id, db)

    members_result = await db.execute(
        select(WorkspaceMember, User)
        .join(User, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    members = [
        MemberResponse(
            user_id=m.user_id,
            email=u.email,
            name=u.name,
            role=m.role,
            invited_at=m.invited_at.isoformat() if m.invited_at else None,
            joined_at=m.joined_at.isoformat() if m.joined_at else None,
        )
        for m, u in members_result.fetchall()
    ]

    wr_result = await db.execute(
        select(func.count()).where(WorkspaceResume.workspace_id == workspace_id)
    )
    resume_count = wr_result.scalar_one()

    return WorkspaceDetailResponse(
        id=ws.id,
        name=ws.name,
        owner_id=ws.owner_id,
        plan_id=ws.plan_id,
        max_members=ws.max_members,
        member_count=len(members),
        resume_count=resume_count,
        created_at=ws.created_at.isoformat(),
        members=members,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Update workspace name (owner only)."""
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(ws, user_id)
    ws.name = body.name
    await db.commit()
    await db.refresh(ws)
    return _ws_to_response(ws)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete workspace and all its members/resumes (owner only)."""
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(ws, user_id)
    await db.delete(ws)
    await db.commit()


@router.post("/{workspace_id}/members/invite", response_model=MemberResponse, status_code=201)
async def invite_member(
    workspace_id: str,
    body: InviteRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user by email (owner only). Resolves email to existing account."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="role must be 'editor' or 'viewer'")

    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(ws, user_id)

    # Lock the workspace row to serialize concurrent invites (prevents TOCTOU on max_members)
    await db.execute(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
    )

    # Enforce max_members limit
    count_result = await db.execute(
        select(func.count()).where(WorkspaceMember.workspace_id == workspace_id)
    )
    if count_result.scalar_one() >= ws.max_members:
        raise HTTPException(
            status_code=422,
            detail=f"Workspace has reached the member limit ({ws.max_members})",
        )

    # Resolve email → user
    user_result = await db.execute(select(User).where(User.email == body.email))
    target = user_result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="No account found with that email address")

    # Check not already a member
    existing = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member of this workspace")

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target.id,
        role=body.role,
        invited_by=user_id,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(member)
    try:
        await db.commit()
    except IntegrityError as exc:
        # The membership pre-check is advisory; a concurrent invite may win the
        # primary-key race between SELECT and INSERT. Keep that conflict a
        # stable client error instead of leaking a 500.
        await db.rollback()
        raise HTTPException(status_code=409, detail="User is already a member of this workspace") from exc
    logger.info("Workspace %s: invited user %s with role %s", workspace_id, target.id, body.role)

    return MemberResponse(
        user_id=target.id,
        email=target.email,
        name=target.name,
        role=body.role,
        invited_at=member.invited_at.isoformat() if member.invited_at else None,
        joined_at=member.joined_at.isoformat() if member.joined_at else None,
    )


@router.delete("/{workspace_id}/members/{target_user_id}", status_code=204)
async def remove_member(
    workspace_id: str,
    target_user_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member (owner only; cannot remove the owner)."""
    ensure_uuid(target_user_id, "Member not found")
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(ws, user_id)

    if target_user_id == ws.owner_id:
        raise HTTPException(status_code=422, detail="Cannot remove the workspace owner")

    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(member)
    await db.commit()


@router.patch("/{workspace_id}/members/{target_user_id}/role", response_model=MemberResponse)
async def update_member_role(
    workspace_id: str,
    target_user_id: str,
    body: RoleUpdateRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role (owner only)."""
    ensure_uuid(target_user_id, "Member not found")
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="role must be 'editor' or 'viewer'")

    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_owner(ws, user_id)

    if target_user_id == ws.owner_id:
        raise HTTPException(status_code=422, detail="Cannot change the owner's role")

    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    member.role = body.role
    await db.commit()

    u_result = await db.execute(select(User).where(User.id == target_user_id))
    u = u_result.scalar_one_or_none()

    return MemberResponse(
        user_id=member.user_id,
        email=u.email if u else None,
        name=u.name if u else None,
        role=member.role,
        invited_at=member.invited_at.isoformat() if member.invited_at else None,
        joined_at=member.joined_at.isoformat() if member.joined_at else None,
    )


@router.post(
    "/{workspace_id}/resumes/{resume_id}",
    response_model=ResumeInWorkspace,
    status_code=201,
)
async def add_resume_to_workspace(
    workspace_id: str,
    resume_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly submit one of the caller's resumes to a workspace."""
    ensure_uuid(resume_id, "Resume not found or not owned by you")
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_member(ws, user_id, db)

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or not owned by you")

    existing = await db.execute(
        select(WorkspaceResume).where(
            WorkspaceResume.workspace_id == workspace_id,
            WorkspaceResume.resume_id == resume_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Resume is already in this workspace")

    wr = WorkspaceResume(workspace_id=workspace_id, resume_id=resume_id, shared_by=user_id)
    db.add(wr)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Two tabs can submit the same resume concurrently; the composite
        # primary key is authoritative when both pass the pre-check.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Resume is already in this workspace") from exc
    await db.refresh(wr)

    return ResumeInWorkspace(
        id=resume.id,
        title=resume.title,
        owner_id=resume.user_id,
        shared_by=wr.shared_by,
        shared_at=wr.shared_at.isoformat(),
        opened_at=None,
        opened_actor=None,
        opened_source=None,
        downloaded_at=None,
        downloaded_actor=None,
        downloaded_source=None,
    )


@router.delete("/{workspace_id}/resumes/{resume_id}", status_code=204)
async def remove_resume_from_workspace(
    workspace_id: str,
    resume_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Remove a submitted resume (workspace owner or resume owner)."""
    ensure_uuid(resume_id, "Resume not found in workspace")
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_member(ws, user_id, db)

    result = await db.execute(
        select(WorkspaceResume, Resume)
        .join(Resume, Resume.id == WorkspaceResume.resume_id)
        .where(
            WorkspaceResume.workspace_id == workspace_id,
            WorkspaceResume.resume_id == resume_id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found in workspace")
    wr, resume = row
    if user_id not in {ws.owner_id, resume.user_id}:
        raise HTTPException(status_code=403, detail="Only the workspace or resume owner can remove it")

    await db.delete(wr)
    await db.commit()


@router.get("/{workspace_id}/resumes", response_model=List[ResumeInWorkspace])
async def list_workspace_resumes(
    workspace_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List all resumes in this workspace (any member can view)."""
    ws = await _get_workspace_or_404(workspace_id, db)
    member = await _require_member(ws, user_id, db)

    query = (
        select(WorkspaceResume, Resume)
        .join(Resume, WorkspaceResume.resume_id == Resume.id)
        .where(WorkspaceResume.workspace_id == workspace_id)
    )
    # Career-centre students opt in by submitting a resume, but should not see
    # other students' submissions. Tenant cohort admins retain the full roster.
    if ws.tenant_id and member.role == "viewer":
        query = query.where(Resume.user_id == user_id)
    result = await db.execute(query)
    rows = result.fetchall()
    changed = False
    for workspace_resume, resume in rows:
        # ``opened_at`` is a legacy field. It records candidate self-activity
        # only; a member/reviewer reading this list must never create it.
        if resume.user_id == user_id and workspace_resume.opened_at is None:
            workspace_resume.opened_at = datetime.now(timezone.utc)
            changed = True
    if changed:
        await db.commit()
    return [
        ResumeInWorkspace(
            id=r.id,
            title=r.title,
            owner_id=r.user_id,
            shared_by=wr.shared_by,
            shared_at=wr.shared_at.isoformat(),
            opened_at=wr.opened_at.isoformat() if wr.opened_at else None,
            opened_actor="candidate" if wr.opened_at else None,
            opened_source="candidate_self" if wr.opened_at else None,
            downloaded_at=wr.downloaded_at.isoformat() if wr.downloaded_at else None,
            downloaded_actor="candidate" if wr.downloaded_at else None,
            downloaded_source="candidate_self" if wr.downloaded_at else None,
        )
        for wr, r in rows
    ]


@router.get("/{workspace_id}/resumes/{resume_id}/download")
async def download_workspace_resume(
    workspace_id: str,
    resume_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Download the latest submitted PDF after explicit workspace authorization."""
    ensure_uuid(resume_id, "Resume not found in workspace")
    ws = await _get_workspace_or_404(workspace_id, db)
    member = await _require_member(ws, user_id, db)
    row_result = await db.execute(
        select(WorkspaceResume, Resume)
        .join(Resume, Resume.id == WorkspaceResume.resume_id)
        .where(
            WorkspaceResume.workspace_id == workspace_id,
            WorkspaceResume.resume_id == resume_id,
        )
    )
    row = row_result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found in workspace")
    workspace_resume, resume = row
    # Tenant-backed cohort viewers can submit and retrieve their own resume,
    # but must not use a guessed resume_id to download another student's
    # submission. Keep this boundary aligned with list_workspace_resumes,
    # which hides classmates' submissions from the same role.
    if ws.tenant_id and member.role == "viewer" and resume.user_id != user_id:
        raise HTTPException(status_code=404, detail="Resume not found in workspace")
    compilation_result = await db.execute(
        select(Compilation)
        .where(
            Compilation.resume_id == resume_id,
            Compilation.status == "completed",
        )
        .order_by(Compilation.created_at.desc())
        .limit(1)
    )
    compilation = compilation_result.scalar_one_or_none()
    if not compilation:
        raise HTTPException(status_code=404, detail="No compiled PDF is available")

    async def record_student_download() -> None:
        # Keep this milestone explicitly candidate-only. A workspace member's
        # PDF download is not ATS/employer telemetry and is not persisted here.
        if resume.user_id == user_id and workspace_resume.downloaded_at is None:
            workspace_resume.downloaded_at = datetime.now(timezone.utc)
            await db.commit()

    stored_pdf: bytes | None = None
    if compilation.pdf_path:
        try:
            from ..services.storage_service import download_bytes

            stored_pdf = await run_in_threadpool(
                download_bytes, compilation.pdf_path, _MAX_WORKSPACE_PDF_BYTES
            )
        except Exception as exc:
            logger.warning(
                "Workspace PDF storage lookup failed",
                extra={"error_type": type(exc).__name__},
            )
    if stored_pdf:
        await record_student_download()
        return Response(
            stored_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{resume_id}.pdf"'},
        )
    encoded = None
    try:
        redis = await get_redis_client()
        encoded = await redis.get(f"latexy:job:{compilation.job_id}:pdf")
    except Exception as exc:
        logger.warning(
            "Workspace PDF cache lookup failed",
            extra={"error_type": type(exc).__name__},
        )
    if encoded:
        try:
            decoded = decode_base64_bounded(encoded, MAX_COMPILED_PDF_BYTES)
        except BoundedReadError:
            decoded = None
        if decoded:
            await record_student_download()
            return Response(
                decoded,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{resume_id}.pdf"'},
            )
    try:
        _, local_pdf, _ = get_job_files(str(compilation.job_id))
    except HTTPException:
        local_pdf = None
    if local_pdf is not None and local_pdf.is_file():
        if local_pdf.stat().st_size > MAX_COMPILED_PDF_BYTES:
            raise HTTPException(status_code=413, detail="Compiled PDF is too large")
        await record_student_download()
        return FileResponse(local_pdf, media_type="application/pdf", filename=f"{resume_id}.pdf")
    raise HTTPException(status_code=404, detail="PDF is no longer available; ask the student to recompile")


# ── Recruiter Notes (Feature 73) ─────────────────────────────────────────────


def _note_to_response(note: RecruiterNote, author: Optional[User] = None) -> RecruiterNoteResponse:
    return RecruiterNoteResponse(
        id=note.id,
        workspace_id=note.workspace_id,
        resume_id=note.resume_id,
        author_id=note.author_id,
        author_name=author.name if author else None,
        author_email=author.email if author else None,
        content=note.content,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat(),
    )


async def _require_resume_in_workspace(workspace_id: str, resume_id: str, db: AsyncSession) -> None:
    ensure_uuid(resume_id, "Resume not found in workspace")
    result = await db.execute(
        select(WorkspaceResume).where(
            WorkspaceResume.workspace_id == workspace_id,
            WorkspaceResume.resume_id == resume_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found in workspace")


@router.post(
    "/{workspace_id}/resumes/{resume_id}/notes",
    response_model=RecruiterNoteResponse,
    status_code=201,
)
async def create_recruiter_note(
    workspace_id: str,
    resume_id: str,
    body: RecruiterNoteCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Create a recruiter note on a workspace resume (owner or editor)."""
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_editor(ws, user_id, db)
    await _require_resume_in_workspace(workspace_id, resume_id, db)

    note = RecruiterNote(
        workspace_id=workspace_id,
        resume_id=resume_id,
        author_id=user_id,
        content=body.content,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    return _note_to_response(note, author)


@router.get(
    "/{workspace_id}/resumes/{resume_id}/notes",
    response_model=List[RecruiterNoteResponse],
)
async def list_recruiter_notes(
    workspace_id: str,
    resume_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List internal recruiter notes (workspace owner/editor only)."""
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_editor(ws, user_id, db)
    await _require_resume_in_workspace(workspace_id, resume_id, db)

    result = await db.execute(
        select(RecruiterNote, User)
        .join(User, RecruiterNote.author_id == User.id)
        .where(
            RecruiterNote.workspace_id == workspace_id,
            RecruiterNote.resume_id == resume_id,
        )
        .order_by(RecruiterNote.created_at)
    )
    return [_note_to_response(n, u) for n, u in result.fetchall()]


@router.patch(
    "/{workspace_id}/resumes/{resume_id}/notes/{note_id}",
    response_model=RecruiterNoteResponse,
)
async def update_recruiter_note(
    workspace_id: str,
    resume_id: str,
    note_id: str,
    body: RecruiterNoteUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Edit a recruiter note (author only)."""
    ensure_uuid(resume_id, "Resume not found in workspace")
    ensure_uuid(note_id, "Note not found")
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_editor(ws, user_id, db)

    note_result = await db.execute(
        select(RecruiterNote).where(
            RecruiterNote.id == note_id,
            RecruiterNote.workspace_id == workspace_id,
            RecruiterNote.resume_id == resume_id,
        )
    )
    note = note_result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.author_id != user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own notes")

    note.content = body.content
    await db.commit()
    await db.refresh(note)

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    return _note_to_response(note, author)


@router.delete(
    "/{workspace_id}/resumes/{resume_id}/notes/{note_id}",
    status_code=204,
)
async def delete_recruiter_note(
    workspace_id: str,
    resume_id: str,
    note_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete a recruiter note (author or workspace owner)."""
    ensure_uuid(resume_id, "Resume not found in workspace")
    ensure_uuid(note_id, "Note not found")
    ws = await _get_workspace_or_404(workspace_id, db)
    await _require_editor(ws, user_id, db)

    note_result = await db.execute(
        select(RecruiterNote).where(
            RecruiterNote.id == note_id,
            RecruiterNote.workspace_id == workspace_id,
            RecruiterNote.resume_id == resume_id,
        )
    )
    note = note_result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.author_id != user_id and ws.owner_id != user_id:
        raise HTTPException(status_code=403, detail="You cannot delete this note")

    await db.delete(note)
    await db.commit()

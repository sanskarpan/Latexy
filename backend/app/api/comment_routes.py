"""Resume collaboration comment routes (Feature 74)."""

import uuid
from collections import defaultdict
from typing import Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import (
    Resume,
    ResumeCollaborator,
    ResumeComment,
    ResumeCommentMention,
    TenantMember,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..utils.uuid_guard import ensure_uuid

logger = get_logger(__name__)

router = APIRouter(prefix="/resumes/{resume_id}/comments", tags=["comments"])

# ── Schemas ───────────────────────────────────────────────────────────────────


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    workspace_id: Optional[str] = None
    line_number: Optional[int] = Field(default=None, ge=1)
    section_tag: Optional[str] = Field(default=None, max_length=100)
    mentioned_user_ids: Optional[List[str]] = Field(default=None, max_length=50)


class CommentUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    mentioned_user_ids: Optional[List[str]] = Field(default=None, max_length=50)


class CommentMention(BaseModel):
    user_id: str
    display_name: str


class CommentMentionParticipant(CommentMention):
    email: Optional[str] = None


class CommentResponse(BaseModel):
    id: str
    resume_id: str
    workspace_id: Optional[str] = None
    author_id: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    content: str
    line_number: Optional[int] = None
    section_tag: Optional[str] = None
    resolved: bool
    created_at: str
    updated_at: str
    mentions: List[CommentMention] = Field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_resume_or_404(resume_id: str, db: AsyncSession) -> Resume:
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


async def _check_workspace_membership(
    workspace_id: str, user_id: str, db: AsyncSession
) -> WorkspaceMember:
    """Return membership or raise 403 without exposing workspace details."""
    ensure_uuid(workspace_id, "Workspace not found")
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")
    return member


async def _assert_resume_in_workspace(
    resume_id: str, workspace_id: str, db: AsyncSession
) -> None:
    """Raise 404 if the resume is not shared into the given workspace."""
    result = await db.execute(
        select(WorkspaceResume).where(
            WorkspaceResume.workspace_id == workspace_id,
            WorkspaceResume.resume_id == resume_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume is not shared into this workspace")


async def _assert_workspace_access(
    resume_id: str, workspace_id: str, user_id: str, db: AsyncSession
) -> None:
    """Caller must be a workspace member AND the resume must be shared into that workspace."""
    member = await _check_workspace_membership(workspace_id, user_id, db)
    await _assert_resume_in_workspace(resume_id, workspace_id, db)
    # Tenant viewers are scoped to their own submitted resume. Workspace
    # editors/owners and tenant admins retain cohort-review access.
    workspace_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = workspace_result.scalar_one_or_none()
    if workspace and workspace.tenant_id and member.role == "viewer":
        resume_result = await db.execute(select(Resume.user_id).where(Resume.id == resume_id))
        resume_owner_id = resume_result.scalar_one_or_none()
        tenant_role = await db.scalar(
            select(TenantMember.role).where(
                TenantMember.tenant_id == workspace.tenant_id,
                TenantMember.user_id == user_id,
            )
        )
        if resume_owner_id != user_id and tenant_role not in {"admin", "owner"}:
            raise HTTPException(status_code=403, detail="You do not have access to this resume")


async def _assert_can_comment(
    resume: Resume, workspace_id: Optional[str], user_id: str, db: AsyncSession
) -> None:
    """Require write access to the selected personal/workspace comment thread."""
    if workspace_id:
        member = await _check_workspace_membership(workspace_id, user_id, db)
        if member.role not in {"owner", "editor"}:
            raise HTTPException(status_code=403, detail="This workspace member has read-only access")
        await _assert_resume_in_workspace(resume.id, workspace_id, db)
    elif resume.user_id != user_id:
        role = await _personal_collaborator_role(resume.id, user_id, db)
        if role not in {"editor", "commenter"}:
            raise HTTPException(status_code=403, detail="You cannot comment on this resume")


async def _personal_collaborator_role(
    resume_id: str, user_id: str, db: AsyncSession
) -> Optional[str]:
    result = await db.execute(
        select(ResumeCollaborator.role).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _assert_can_view_personal_comments(
    resume: Resume, user_id: str, db: AsyncSession
) -> None:
    if resume.user_id == user_id:
        return
    if await _personal_collaborator_role(resume.id, user_id, db) not in {
        "editor",
        "commenter",
        "viewer",
    }:
        raise HTTPException(status_code=403, detail="You do not have access to this resume")


async def _assert_current_comment_access(
    comment: ResumeComment, user_id: str, db: AsyncSession
) -> None:
    """Recheck live access before mutating an existing comment."""
    if comment.workspace_id:
        resume = await _get_resume_or_404(comment.resume_id, db)
        await _assert_can_comment(resume, comment.workspace_id, user_id, db)
        return

    resume = await _get_resume_or_404(comment.resume_id, db)
    await _assert_can_comment(resume, None, user_id, db)


def _comment_to_response(
    comment: ResumeComment,
    author: Optional[User] = None,
    mentions: Iterable[CommentMention] = (),
) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        resume_id=comment.resume_id,
        workspace_id=comment.workspace_id,
        author_id=comment.author_id,
        author_name=author.name if author else None,
        author_email=author.email if author else None,
        content=comment.content,
        line_number=comment.line_number,
        section_tag=comment.section_tag,
        resolved=comment.resolved,
        created_at=comment.created_at.isoformat(),
        updated_at=comment.updated_at.isoformat(),
        mentions=list(mentions),
    )


def _normalize_mention_ids(values: Optional[List[str]]) -> Optional[List[str]]:
    """Canonicalize stable picker IDs and reject ambiguous/free-form values."""
    if values is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            user_id = str(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(status_code=422, detail="mentioned_user_ids must contain UUIDs") from None
        if user_id not in seen:
            normalized.append(user_id)
            seen.add(user_id)
    return normalized


async def _allowed_mention_users(
    resume: Resume, workspace_id: Optional[str], db: AsyncSession
) -> list[User]:
    """Return only users explicitly scoped to this resume/thread."""
    if workspace_id:
        workspace_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = workspace_result.scalar_one_or_none()
        member_result = await db.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id
            )
        )
        members = member_result.all()
        member_ids = {member_id for member_id, _role in members}
        allowed_ids = {member_id for member_id, role in members if role in {"owner", "editor"}}
        if resume.user_id in member_ids:
            allowed_ids.add(resume.user_id)
        if workspace and workspace.tenant_id:
            admin_result = await db.execute(
                select(TenantMember.user_id).where(
                    TenantMember.tenant_id == workspace.tenant_id,
                    TenantMember.role.in_({"admin", "owner"}),
                )
            )
            allowed_ids.update(set(admin_result.scalars().all()) & member_ids)
        else:
            allowed_ids.update(user_id for user_id, _role in members)
    else:
        allowed_ids = {resume.user_id}
        collab_result = await db.execute(
            select(ResumeCollaborator.user_id).where(ResumeCollaborator.resume_id == resume.id)
        )
        allowed_ids.update(collab_result.scalars().all())
    users_result = await db.execute(select(User).where(User.id.in_(allowed_ids)))
    users_by_id = {user.id: user for user in users_result.scalars().all()}
    # Keep deterministic ordering and never return users outside the scope.
    return [users_by_id[user_id] for user_id in sorted(allowed_ids) if user_id in users_by_id]


async def _resolve_mention_ids(
    resume: Resume,
    workspace_id: Optional[str],
    values: Optional[List[str]],
    author_id: Optional[str],
    db: AsyncSession,
) -> Optional[List[str]]:
    normalized = _normalize_mention_ids(values)
    if normalized is None:
        return None
    allowed = {user.id for user in await _allowed_mention_users(resume, workspace_id, db)}
    if any(user_id not in allowed for user_id in normalized):
        # Deliberately do not distinguish a missing user from an unrelated user.
        raise HTTPException(status_code=403, detail="Mentioned users must have access to this resume")
    # Self mentions are useful in the editor but must never create a self-email.
    return [user_id for user_id in normalized if user_id != author_id]


async def _comment_mentions(
    comment_ids: Iterable[str], db: AsyncSession
) -> dict[str, list[CommentMention]]:
    ids = list(comment_ids)
    if not ids:
        return {}
    result = await db.execute(
        select(ResumeCommentMention, User)
        .join(User, User.id == ResumeCommentMention.mentioned_user_id)
        .where(ResumeCommentMention.comment_id.in_(ids))
        .order_by(ResumeCommentMention.created_at)
    )
    mentions: dict[str, list[CommentMention]] = defaultdict(list)
    for mention, user in result.all():
        mentions[mention.comment_id].append(
            CommentMention(
                user_id=mention.mentioned_user_id,
                display_name=user.name or user.email,
            )
        )
    return mentions


async def _enqueue_mention_emails(comment_id: str, db: AsyncSession) -> None:
    """Queue after commit; a queue outage never rolls back comment creation."""
    from ..workers.email_worker import submit_comment_mention_email

    result = await db.execute(
        select(ResumeCommentMention.id).where(
            ResumeCommentMention.comment_id == comment_id,
            ResumeCommentMention.delivery_sent_at.is_(None),
        )
    )
    for mention_id in result.scalars().all():
        submit_comment_mention_email(str(mention_id))


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=CommentResponse,
    status_code=201,
    dependencies=[Depends(require_feature("collaboration"))],
)
async def add_comment(
    resume_id: str,
    body: CommentCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a resume. Must own the resume (personal) or be workspace member."""
    resume = await _get_resume_or_404(resume_id, db)
    await _assert_can_comment(resume, body.workspace_id, user_id, db)
    mention_ids = await _resolve_mention_ids(
        resume, body.workspace_id, body.mentioned_user_ids, user_id, db
    )

    comment = ResumeComment(
        resume_id=resume_id,
        workspace_id=body.workspace_id,
        author_id=user_id,
        content=body.content,
        line_number=body.line_number,
        section_tag=body.section_tag,
    )
    db.add(comment)
    await db.flush()
    for mentioned_user_id in mention_ids or []:
        db.add(
            ResumeCommentMention(
                comment_id=comment.id,
                resume_id=resume.id,
                mentioned_user_id=mentioned_user_id,
            )
        )
    await db.commit()
    await db.refresh(comment)
    await _enqueue_mention_emails(comment.id, db)

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    mentions = await _comment_mentions([comment.id], db)
    return _comment_to_response(comment, author, mentions.get(comment.id, []))


@router.get("", response_model=List[CommentResponse])
async def list_comments(
    resume_id: str,
    workspace_id: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List comments on a resume, optionally filtered by workspace_id."""
    resume = await _get_resume_or_404(resume_id, db)

    # Access check
    if workspace_id:
        await _assert_workspace_access(resume_id, workspace_id, user_id, db)
    else:
        await _assert_can_view_personal_comments(resume, user_id, db)

    query = (
        select(ResumeComment, User)
        .join(User, ResumeComment.author_id == User.id)
        .where(ResumeComment.resume_id == resume_id)
    )
    if workspace_id:
        query = query.where(ResumeComment.workspace_id == workspace_id)
    else:
        query = query.where(ResumeComment.workspace_id.is_(None))

    result = await db.execute(query.order_by(ResumeComment.created_at))
    rows = result.fetchall()
    mentions = await _comment_mentions((comment.id for comment, _ in rows), db)
    return [_comment_to_response(c, u, mentions.get(c.id, [])) for c, u in rows]


@router.get("/participants", response_model=List[CommentMentionParticipant])
async def list_comment_participants(
    resume_id: str,
    workspace_id: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """List only owner/collaborators (or members of a shared workspace) for @ picker."""
    resume = await _get_resume_or_404(resume_id, db)
    # The picker exposes notification-bearing identities, so it is a write
    # capability rather than a read capability. In particular, workspace
    # viewers may read the thread but must not enumerate participants.
    await _assert_can_comment(resume, workspace_id, user_id, db)
    users = await _allowed_mention_users(resume, workspace_id, db)
    return [
        CommentMentionParticipant(user_id=user.id, display_name=user.name or user.email, email=user.email)
        for user in users
    ]


@router.patch("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    resume_id: str,
    comment_id: str,
    body: CommentUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Edit a comment (author only)."""
    ensure_uuid(resume_id, "Resume not found")
    ensure_uuid(comment_id, "Comment not found")
    result = await db.execute(
        select(ResumeComment).where(
            ResumeComment.id == comment_id,
            ResumeComment.resume_id == resume_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await _assert_current_comment_access(comment, user_id, db)
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own comments")

    comment.content = body.content
    new_mentions: list[ResumeCommentMention] = []
    if body.mentioned_user_ids is not None:
        resume = await _get_resume_or_404(comment.resume_id, db)
        mention_ids = await _resolve_mention_ids(
            resume, comment.workspace_id, body.mentioned_user_ids, user_id, db
        )
        current_result = await db.execute(
            select(ResumeCommentMention).where(ResumeCommentMention.comment_id == comment.id)
        )
        current = {mention.mentioned_user_id: mention for mention in current_result.scalars().all()}
        requested = set(mention_ids or [])
        for mentioned_user_id, mention in current.items():
            if mentioned_user_id not in requested:
                await db.delete(mention)
        await db.flush()
        for mentioned_user_id in requested - current.keys():
            mention = ResumeCommentMention(
                comment_id=comment.id,
                resume_id=comment.resume_id,
                mentioned_user_id=mentioned_user_id,
            )
            db.add(mention)
            new_mentions.append(mention)
    await db.commit()
    await db.refresh(comment)
    for mention in new_mentions:
        await db.refresh(mention)
        from ..workers.email_worker import submit_comment_mention_email

        submit_comment_mention_email(str(mention.id))

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    mentions = await _comment_mentions([comment.id], db)
    return _comment_to_response(comment, author, mentions.get(comment.id, []))


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    resume_id: str,
    comment_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete a comment (author only)."""
    ensure_uuid(resume_id, "Resume not found")
    ensure_uuid(comment_id, "Comment not found")
    result = await db.execute(
        select(ResumeComment).where(
            ResumeComment.id == comment_id,
            ResumeComment.resume_id == resume_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await _assert_current_comment_access(comment, user_id, db)
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")

    await db.delete(comment)
    await db.commit()


@router.patch("/{comment_id}/resolve", response_model=CommentResponse)
async def resolve_comment(
    resume_id: str,
    comment_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Mark a comment resolved/unresolved (resume owner or comment author)."""
    ensure_uuid(comment_id, "Comment not found")
    resume = await _get_resume_or_404(resume_id, db)

    result = await db.execute(
        select(ResumeComment).where(
            ResumeComment.id == comment_id,
            ResumeComment.resume_id == resume_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await _assert_current_comment_access(comment, user_id, db)

    # Only the resume owner or the comment author may resolve
    if user_id != resume.user_id and user_id != comment.author_id:
        raise HTTPException(status_code=403, detail="You cannot resolve this comment")

    comment.resolved = not comment.resolved
    await db.commit()
    await db.refresh(comment)

    u_result = await db.execute(select(User).where(User.id == comment.author_id))
    author = u_result.scalar_one_or_none()
    mentions = await _comment_mentions([comment.id], db)
    return _comment_to_response(comment, author, mentions.get(comment.id, []))

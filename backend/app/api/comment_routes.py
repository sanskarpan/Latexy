"""Resume collaboration comment routes (Feature 74)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Resume, ResumeComment, User, WorkspaceMember
from ..middleware.auth_middleware import get_current_user_required

logger = get_logger(__name__)

router = APIRouter(prefix="/resumes/{resume_id}/comments", tags=["comments"])

# ── Schemas ───────────────────────────────────────────────────────────────────


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    workspace_id: Optional[str] = None
    line_number: Optional[int] = Field(default=None, ge=1)
    section_tag: Optional[str] = Field(default=None, max_length=100)


class CommentUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


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


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_resume_or_404(resume_id: str, db: AsyncSession) -> Resume:
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


async def _check_workspace_membership(workspace_id: str, user_id: str, db: AsyncSession) -> None:
    """Raise 403 if user is not a member of the given workspace."""
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")


async def _assert_can_comment(
    resume: Resume, workspace_id: Optional[str], user_id: str, db: AsyncSession
) -> None:
    """Commenter must own the resume (personal) or be a workspace member (workspace-scoped)."""
    if workspace_id:
        await _check_workspace_membership(workspace_id, user_id, db)
    elif resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this resume")


def _comment_to_response(comment: ResumeComment, author: Optional[User] = None) -> CommentResponse:
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
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=CommentResponse, status_code=201)
async def add_comment(
    resume_id: str,
    body: CommentCreate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a resume. Must own the resume (personal) or be workspace member."""
    resume = await _get_resume_or_404(resume_id, db)
    await _assert_can_comment(resume, body.workspace_id, user_id, db)

    comment = ResumeComment(
        resume_id=resume_id,
        workspace_id=body.workspace_id,
        author_id=user_id,
        content=body.content,
        line_number=body.line_number,
        section_tag=body.section_tag,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    return _comment_to_response(comment, author)


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
        await _check_workspace_membership(workspace_id, user_id, db)
    elif resume.user_id != user_id:
        raise HTTPException(status_code=403, detail="You do not have access to this resume")

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
    return [_comment_to_response(c, u) for c, u in result.fetchall()]


@router.patch("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    resume_id: str,
    comment_id: str,
    body: CommentUpdate,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Edit a comment (author only)."""
    result = await db.execute(
        select(ResumeComment).where(
            ResumeComment.id == comment_id,
            ResumeComment.resume_id == resume_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.author_id != user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own comments")

    comment.content = body.content
    await db.commit()
    await db.refresh(comment)

    u_result = await db.execute(select(User).where(User.id == user_id))
    author = u_result.scalar_one_or_none()
    return _comment_to_response(comment, author)


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    resume_id: str,
    comment_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete a comment (author only)."""
    result = await db.execute(
        select(ResumeComment).where(
            ResumeComment.id == comment_id,
            ResumeComment.resume_id == resume_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
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

    # Only the resume owner or the comment author may resolve
    if user_id != resume.user_id and user_id != comment.author_id:
        raise HTTPException(status_code=403, detail="You cannot resolve this comment")

    comment.resolved = not comment.resolved
    await db.commit()
    await db.refresh(comment)

    u_result = await db.execute(select(User).where(User.id == comment.author_id))
    author = u_result.scalar_one_or_none()
    return _comment_to_response(comment, author)

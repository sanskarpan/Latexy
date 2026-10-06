"""Anonymous peer/mentor review comments for share links (B51d / #1392).

Review links are deliberately a separate capability from authenticated
collaboration comments.  A reviewer gets only a live share token, one resume,
and a pseudonymous browser label; no account, workspace, or participant data is
ever loaded on the public path.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import secrets
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import redis as redis_core
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import (
    Resume,
    ResumeCollaborator,
    ResumeReviewComment,
    Workspace,
    WorkspaceMember,
    WorkspaceResume,
)
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.rate_limiting import client_ip_id
from ..utils.uuid_guard import ensure_uuid

logger = get_logger(__name__)

router = APIRouter(tags=["peer-review"])

_REVIEW_COOKIE = "latexy_review_id"
_MAX_TOKEN_LENGTH = 200
_MAX_COMMENT_LENGTH = 4_000
_MAX_COMMENT_BYTES = 16 * 1024
_MAX_SECTION_LENGTH = 100
_MAX_SECTION_BYTES = 512
_TOKEN_LIMIT = 20
_IP_LIMIT = 60
_MAX_COMMENTS_PER_CAPABILITY = 500
_MAX_AUTHENTICATED_LIST = 1_000
_RATE_WINDOW_SECONDS = 3_600
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_~-]{16,200}$")
_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

# Increment the token bucket first, then the IP bucket, atomically.  A token
# which has exceeded its budget does not consume the shared IP budget; this is
# important when many reviewers are behind one NAT. Redis errors fail closed on
# this anonymous write endpoint because accepting an unmetered public writer is
# a high-risk failure mode.
_REVIEW_RATE_LUA = """
local token_count = redis.call('INCR', KEYS[1])
if token_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
if token_count > tonumber(ARGV[2]) then return {0, token_count, 0} end
local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
if ip_count > tonumber(ARGV[3]) then return {0, token_count, ip_count} end
return {1, token_count, ip_count}
"""


class ReviewCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=_MAX_COMMENT_LENGTH)
    line_number: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    section_tag: Optional[str] = Field(default=None, max_length=_MAX_SECTION_LENGTH)
    # Document anchors are normalized to the rendered page: x/y are in the
    # closed interval [0, 1], with (0, 0) at the page's top-left corner.
    # The API does not own the viewer's rendered PDF bytes, so it can enforce
    # safe bounds but not the exact page count. The client only creates anchors
    # after react-pdf has loaded a real page and the response path drops any
    # marker whose page is outside that loaded document.
    page_number: Optional[int] = Field(default=None, ge=1, le=10_000)
    x: Optional[float] = Field(default=None, ge=0, le=1)
    y: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_anchor(self) -> "ReviewCommentCreate":
        anchor = (self.page_number, self.x, self.y)
        if any(value is not None for value in anchor) and not all(value is not None for value in anchor):
            raise ValueError("page_number, x, and y must be supplied together")
        if any(value is not None and not math.isfinite(value) for value in (self.x, self.y)):
            raise ValueError("anchor coordinates must be finite")
        return self

    @field_validator("content", "section_tag")
    @classmethod
    def _reject_control_chars(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if any(
            unicodedata.category(char) in {"Cc", "Cs"} and char not in "\t\n\r"
            for char in value
        ):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        try:
            if len(value.encode("utf-8")) > _MAX_COMMENT_BYTES:
                raise ValueError("content is too large")
        except UnicodeEncodeError as exc:
            raise ValueError("content contains invalid Unicode") from exc
        return value

    @field_validator("section_tag")
    @classmethod
    def _validate_section_tag(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            if len(value.encode("utf-8")) > _MAX_SECTION_BYTES:
                raise ValueError("section_tag is too large")
        except UnicodeEncodeError as exc:
            raise ValueError("section_tag contains invalid Unicode") from exc
        return value


class ReviewCommentResponse(BaseModel):
    id: str
    reviewer_label: str
    content: str
    line_number: Optional[int] = None
    section_tag: Optional[str] = None
    page_number: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    resolved: bool
    created_at: str
    updated_at: str


class ReviewCommentCreateResponse(ReviewCommentResponse):
    reviewer_label: str


def _not_found() -> HTTPException:
    # Keep unknown, revoked, non-review, and malformed capabilities
    # indistinguishable to prevent share-token/review-mode enumeration.
    return HTTPException(status_code=404, detail="Review link not found or has been revoked")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _review_resume(token: str, db: AsyncSession) -> tuple[Resume, str]:
    if len(token) > _MAX_TOKEN_LENGTH or not _TOKEN_RE.fullmatch(token):
        raise _not_found()
    result = await db.execute(select(Resume).where(Resume.share_token == token))
    resume = result.scalar_one_or_none()
    if not resume or not bool((resume.resume_settings or {}).get("share_review_comments", False)):
        raise _not_found()
    return resume, _token_hash(token)


def _reviewer_identity(request: Request, response: Response, token: str) -> str:
    identity = request.cookies.get(_REVIEW_COOKIE, "")
    if not _COOKIE_RE.fullmatch(identity):
        identity = secrets.token_urlsafe(24)
        response.set_cookie(
            _REVIEW_COOKIE,
            identity,
            max_age=365 * 24 * 3600,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
    # The token participates in the label so a rotated link gets a fresh label.
    return f"Reviewer {hashlib.sha256(f'{token}:{identity}'.encode()).hexdigest()[:6].upper()}"


def _response(comment: ResumeReviewComment) -> ReviewCommentResponse:
    return ReviewCommentResponse(
        id=str(comment.id),
        reviewer_label=comment.reviewer_label,
        content=comment.content,
        line_number=comment.line_number,
        section_tag=comment.section_tag,
        page_number=comment.page_number,
        x=comment.x,
        y=comment.y,
        resolved=bool(comment.resolved),
        created_at=comment.created_at.isoformat(),
        updated_at=comment.updated_at.isoformat(),
    )


async def _check_review_rate_limit(request: Request, token_hash: str) -> None:
    client = redis_core.redis_cache_client
    if client is None:
        raise HTTPException(status_code=503, detail="Review comments are temporarily unavailable")
    # Hash both dimensions; neither raw share tokens nor client addresses belong
    # in Redis keys or logs. client_ip_id only trusts proxy headers under the
    # repository's explicit TRUST_PROXY_HEADERS setting.
    ip_hash = hashlib.sha256(client_ip_id(request).encode("utf-8")).hexdigest()
    token_key = f"review_comments:token:{token_hash}"
    ip_key = f"review_comments:ip:{ip_hash}"
    try:
        counts = await asyncio.wait_for(
            client.eval(
                _REVIEW_RATE_LUA,
                2,
                token_key,
                ip_key,
                _RATE_WINDOW_SECONDS,
                _TOKEN_LIMIT,
                _IP_LIMIT,
            ),
            timeout=1.5,
        )
    except Exception as exc:
        logger.warning("Anonymous review rate limiter unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Review comments are temporarily unavailable") from None
    if not counts or int(counts[0]) != 1:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many review comments",
            headers={"Retry-After": str(_RATE_WINDOW_SECONDS)},
        )


@router.get("/share/{share_token}/review-comments", response_model=list[ReviewCommentResponse])
async def list_public_review_comments(
    share_token: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """List only comments bound to the currently live review capability."""
    _resume, token_hash = await _review_resume(share_token, db)
    # Initialize a pseudonymous reviewer cookie even for read-only visitors;
    # it lets a later comment receive the same privacy-preserving label.
    _reviewer_identity(request, response, share_token)
    result = await db.execute(
        select(ResumeReviewComment)
        .where(ResumeReviewComment.resume_id == _resume.id, ResumeReviewComment.share_token_hash == token_hash)
        .order_by(ResumeReviewComment.created_at, ResumeReviewComment.id)
        .limit(_MAX_COMMENTS_PER_CAPABILITY)
    )
    return [_response(comment) for comment in result.scalars().all()]


@router.post(
    "/share/{share_token}/review-comments",
    response_model=ReviewCommentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_public_review_comment(
    share_token: str,
    body: ReviewCommentCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Create one bounded, pseudonymous comment without an account."""
    resume, token_hash = await _review_resume(share_token, db)
    await _check_review_rate_limit(request, token_hash)
    # Redis metering is intentionally outside the transaction, but the
    # capability must be revalidated after that await. A share revoke/rotate
    # that wins this row lock invalidates the old token before insertion.
    locked_resume = await db.scalar(
        select(Resume)
        .where(Resume.id == resume.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        not locked_resume
        or locked_resume.share_token != share_token
        or not bool((locked_resume.resume_settings or {}).get("share_review_comments", False))
    ):
        raise _not_found()
    resume = locked_resume
    count = await db.scalar(
        select(func.count(ResumeReviewComment.id)).where(
            ResumeReviewComment.resume_id == resume.id,
            ResumeReviewComment.share_token_hash == token_hash,
        )
    )
    if (count or 0) >= _MAX_COMMENTS_PER_CAPABILITY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="This review link has reached its comment limit",
        )
    label = _reviewer_identity(request, response, share_token)
    comment = ResumeReviewComment(
        resume_id=resume.id,
        share_token_hash=token_hash,
        reviewer_label=label,
        # Persist exact plain text. Clients must render this as a text node;
        # pre-escaping here would corrupt literal entities for every viewer.
        content=body.content,
        line_number=body.line_number,
        section_tag=body.section_tag,
        page_number=body.page_number,
        x=body.x,
        y=body.y,
    )
    db.add(comment)
    try:
        await db.commit()
        await db.refresh(comment)
    except Exception:
        await db.rollback()
        raise
    return _response(comment)


async def _authenticated_review_resume(resume_id: str, user_id: str, db: AsyncSession) -> Resume:
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id == user_id:
        return resume
    # Personal collaborators may see review feedback. Workspace access is
    # checked below so an institution's candidate/viewer cohort boundary is
    # applied consistently with the rest of the workspace API.
    collab = await db.scalar(
        select(ResumeCollaborator.role).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == user_id,
        )
    )
    if collab in {"editor", "commenter", "viewer"}:
        return resume

    workspace_rows = await db.execute(
        select(WorkspaceMember.role, Workspace.tenant_id)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .join(WorkspaceResume, WorkspaceResume.workspace_id == Workspace.id)
        .where(
            WorkspaceResume.resume_id == resume_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    for role, tenant_id in workspace_rows.all():
        if role in {"owner", "editor"}:
            return resume
        # In a tenant-backed cohort, viewers may only review their own
        # submission. The owner case was handled above; do not infer access
        # from TenantMember membership alone.
        if role == "viewer" and tenant_id is None:
            return resume

    raise HTTPException(status_code=403, detail="You do not have access to this resume")


async def _assert_can_resolve_review_comment(resume_id: str, user_id: str, db: AsyncSession) -> Resume:
    """Lock the capability rows and re-check resolve authority immediately before mutation.

    The initial access check is intentionally separate from this one because a
    collaborator can be revoked while a request is waiting on other database
    work.  Locking the resume and membership rows gives revocation and resolve
    a deterministic commit order: a revoked editor cannot commit after the
    revocation transaction wins.
    """
    resume = await db.scalar(
        select(Resume)
        .where(Resume.id == resume_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    if resume.user_id == user_id:
        return resume

    collaborator = await db.scalar(
        select(ResumeCollaborator)
        .where(ResumeCollaborator.resume_id == resume_id, ResumeCollaborator.user_id == user_id)
        .with_for_update()
    )
    workspace_membership = await db.scalar(
        select(WorkspaceMember)
        .join(WorkspaceResume, WorkspaceResume.workspace_id == WorkspaceMember.workspace_id)
        .where(
            WorkspaceResume.resume_id == resume_id,
            WorkspaceMember.user_id == user_id,
        )
        .with_for_update()
    )
    if (collaborator and collaborator.role == "editor") or (
        workspace_membership and workspace_membership.role in {"owner", "editor"}
    ):
        return resume
    raise HTTPException(status_code=403, detail="Only the owner or an editor can resolve review comments")


class ReviewCommentResolve(BaseModel):
    resolved: bool


@router.get("/resumes/{resume_id}/review-comments", response_model=list[ReviewCommentResponse])
async def list_authenticated_review_comments(
    resume_id: str,
    response: Response,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Return a bounded history so old rotated capabilities cannot exhaust the UI."""
    resume = await _authenticated_review_resume(resume_id, user_id, db)
    result = await db.execute(
        select(ResumeReviewComment)
        .where(ResumeReviewComment.resume_id == resume.id)
        # Take the newest bounded window, then restore chronological order for
        # the UI. Ascending+LIMIT would permanently hide new feedback after a
        # resume accumulates enough history across rotated share links.
        .order_by(ResumeReviewComment.created_at.desc(), ResumeReviewComment.id.desc())
        .limit(_MAX_AUTHENTICATED_LIST + 1)
    )
    comments = result.scalars().all()
    if len(comments) > _MAX_AUTHENTICATED_LIST:
        response.headers["X-Review-Comments-Truncated"] = "true"
        comments = comments[:_MAX_AUTHENTICATED_LIST]
    comments = list(reversed(comments))
    return [_response(comment) for comment in comments]


@router.patch("/resumes/{resume_id}/review-comments/{comment_id}/resolve", response_model=ReviewCommentResponse)
async def resolve_authenticated_review_comment(
    resume_id: str,
    comment_id: str,
    body: ReviewCommentResolve,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    # Re-check under row locks immediately before loading/mutating the
    # comment. This closes the revoke-vs-resolve authorization TOCTOU window.
    resume = await _assert_can_resolve_review_comment(resume_id, user_id, db)
    ensure_uuid(comment_id, "Comment not found")
    result = await db.execute(
        select(ResumeReviewComment).where(
            ResumeReviewComment.id == comment_id,
            ResumeReviewComment.resume_id == resume.id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Explicit assignment makes retries and concurrent duplicate requests
    # idempotent; a toggle would make the final state depend on arrival order.
    comment.resolved = body.resolved
    await db.commit()
    await db.refresh(comment)
    return _response(comment)

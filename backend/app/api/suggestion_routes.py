"""Server-authoritative suggesting-mode decisions.

Proposal payloads are ephemeral Yjs awareness state, but accepting a proposal
is a persisted document mutation. This endpoint is the authority for that
mutation: it locks the resume row, checks the expected source, computes the
unique context-matched replacement, and commits the decision and new content
in one transaction. A decision row makes a successful request idempotently
replayable during the bounded collaboration replay lifetime, even after a
browser crash.
"""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.connection import get_db
from ..database.models import Resume, ResumeCollaborator, ResumeSuggestionDecision
from ..middleware.auth_middleware import get_current_user_required
from ..utils.uuid_guard import ensure_uuid

router = APIRouter(prefix="/resumes", tags=["suggestions"])

MAX_LATEX_CONTENT_LEN = 1_000_000
MAX_LATEX_CONTENT_BYTES = 4_000_000
MAX_SUGGESTION_TEXT_LEN = 2_000
MAX_CONTEXT_LEN = 48
MAX_SUGGESTION_ID_LEN = 512
_RESOLVER_ROLES = frozenset({"owner", "editor"})
_DOCUMENT_READ_ROLES = frozenset({"owner", "editor", "commenter", "viewer"})
# Rejected/conflicted rows have no document mutation to recover, so their
# payloads can be bounded. Accepted IDs are retained as compact tombstones
# indefinitely: deleting an accepted ID would let a replayed ephemeral
# proposal apply its replacement a second time. Only the newest accepted
# decisions retain their full post-decision source for crash recovery.
MAX_STORED_DECISIONS_PER_RESUME = 20
MAX_DECISIONS_PER_USER_RESUME_PER_HOUR = 100
# Awareness proposals are short-lived collaboration state. Keep compact
# accepted idempotency tombstones for a bounded period covering reconnects and
# delayed browser retries; after this window the ephemeral proposal itself is
# no longer valid and its tombstone can be removed.
ACCEPTED_TOMBSTONE_RETENTION_DAYS = 30


class SuggestionDecisionRequest(BaseModel):
    suggestion_id: str = Field(..., min_length=1, max_length=MAX_SUGGESTION_ID_LEN)
    status: Literal["accepted", "rejected", "conflicted"]
    # The expected source is a CAS token and never trusted as the current DB
    # value until it is compared under the resume row lock.
    expected_content: str = Field(..., max_length=MAX_LATEX_CONTENT_LEN)
    original_text: str = Field(..., max_length=MAX_SUGGESTION_TEXT_LEN)
    replacement_text: str = Field(..., max_length=MAX_SUGGESTION_TEXT_LEN)
    prefix: str = Field(default="", max_length=MAX_CONTEXT_LEN)
    suffix: str = Field(default="", max_length=MAX_CONTEXT_LEN)

    @field_validator("expected_content", mode="after")
    @classmethod
    def _valid_expected_utf8(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("expected_content must contain valid Unicode text") from exc
        if len(encoded) > MAX_LATEX_CONTENT_BYTES:
            raise ValueError("expected_content exceeds the byte limit")
        return value

    @field_validator("original_text", "replacement_text", "prefix", "suffix", mode="after")
    @classmethod
    def _valid_utf8_fields(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("suggestion text must contain valid Unicode text") from exc
        if len(encoded) > 16_384:
            raise ValueError("suggestion text exceeds the byte limit")
        return value


class SuggestionDecisionResponse(BaseModel):
    suggestion_id: str
    status: Literal["accepted", "rejected", "conflicted"]
    decided_by_role: Literal["owner", "editor"]
    decided_at: datetime
    # Exact post-decision source for recent accepted outcomes. Older accepted
    # rows return the current authoritative source alongside their tombstone;
    # rejected/conflicted rows intentionally store no document copy.
    latex_content: str
    replayed: bool = False
    # False means the idempotency tombstone survived retention, but its old
    # 1MB result was compacted. Callers must use the returned current source
    # (or GET the resume) and must not interpret an empty payload as a source.
    replay_available: bool = True


def _resolve_unique(source: str, original: str, prefix: str, suffix: str) -> Optional[tuple[int, int]]:
    """Resolve one exact occurrence with nearby context, matching the client."""
    candidates: list[tuple[int, int]] = []
    cursor = 0
    while cursor <= len(source):
        found = source.find(original, cursor)
        if found < 0:
            break
        before = source[max(0, found - len(prefix)) : found]
        after = source[found + len(original) : found + len(original) + len(suffix)]
        prefix_match = 0
        while (
            prefix_match < len(before)
            and prefix_match < len(prefix)
            and before[-1 - prefix_match] == prefix[-1 - prefix_match]
        ):
            prefix_match += 1
        suffix_match = 0
        while (
            suffix_match < len(after)
            and suffix_match < len(suffix)
            and after[suffix_match] == suffix[suffix_match]
        ):
            suffix_match += 1
        candidates.append((found, prefix_match + suffix_match))
        cursor = found + max(1, len(original))
    if not candidates:
        return None
    best_score = max(score for _, score in candidates)
    best = [start for start, score in candidates if score == best_score]
    # One exact occurrence is already unambiguous even when the selection is
    # the whole document and therefore has no surrounding context. Context is
    # needed only to distinguish multiple occurrences.
    return (best[0], best[0] + len(original)) if len(best) == 1 else None


async def _access_role(db: AsyncSession, resume_id: str, user_id: str) -> str:
    ensure_uuid(resume_id, "Resume not found")
    row = (
        await db.execute(
            select(Resume.user_id, ResumeCollaborator.role)
            .outerjoin(
                ResumeCollaborator,
                and_(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == user_id,
                ),
            )
            .where(Resume.id == resume_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    owner_id, collaborator_role = row
    if owner_id == user_id:
        return "owner"
    if collaborator_role in _RESOLVER_ROLES:
        return "editor"
    raise HTTPException(status_code=403, detail="Only owners and editors can decide suggestions")


async def _read_access_role(db: AsyncSession, resume_id: str, user_id: str) -> str:
    """Authorize decision reads for every collaborator who can read the document."""
    ensure_uuid(resume_id, "Resume not found")
    row = (
        await db.execute(
            select(Resume.user_id, ResumeCollaborator.role)
            .outerjoin(
                ResumeCollaborator,
                and_(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == user_id,
                ),
            )
            .where(Resume.id == resume_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    owner_id, collaborator_role = row
    if owner_id == user_id:
        return "owner"
    if collaborator_role in _DOCUMENT_READ_ROLES:
        return str(collaborator_role)
    # Do not reveal that a non-collaborator's resume exists.
    raise HTTPException(status_code=404, detail="Resume not found")


def _response(
    decision: ResumeSuggestionDecision,
    *,
    replayed: bool,
    fallback_content: str = "",
) -> SuggestionDecisionResponse:
    replay_available = decision.status != "accepted" or bool(decision.result_content)
    return SuggestionDecisionResponse(
        suggestion_id=decision.suggestion_id,
        status=decision.status,
        decided_by_role=decision.decided_by_role,
        decided_at=decision.created_at,
        latex_content=decision.result_content or fallback_content,
        replayed=replayed,
        replay_available=replay_available,
    )


@router.post("/{resume_id}/suggestion-decisions", response_model=SuggestionDecisionResponse)
async def decide_suggestion(
    resume_id: str,
    body: SuggestionDecisionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> SuggestionDecisionResponse:
    """Atomically accept/reject one suggestion and return its exact result."""
    role = await _access_role(db, resume_id, user_id)
    if body.status == "accepted" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can accept suggestions")
    if body.status == "conflicted" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can mark conflicts")
    if body.status == "rejected" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can reject suggestions")

    # Lock the single resume row. Every accepted suggestion on a resume is
    # serialized here, including two requests from separate API workers.
    resume = (
        await db.execute(select(Resume).where(Resume.id == resume_id).with_for_update())
    ).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Re-check after acquiring the resume lock. A collaborator can be revoked
    # while the initial permission query is in flight; never commit a decision
    # based solely on that stale authorization result.
    role = await _access_role(db, resume_id, user_id)
    if body.status == "accepted" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can accept suggestions")
    if body.status == "conflicted" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can mark conflicts")
    if body.status == "rejected" and role not in _RESOLVER_ROLES:
        raise HTTPException(status_code=403, detail="Only owners and editors can reject suggestions")

    existing = (
        await db.execute(
            select(ResumeSuggestionDecision).where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.suggestion_id == body.suggestion_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # The first committed outcome wins. Ignore later conflicting payloads
        # and return the exact committed source for crash recovery.
        return _response(existing, replayed=True, fallback_content=resume.latex_content)

    # Cap unique decision IDs as well as payload size. Replays of an existing
    # ID return above and remain idempotent; only new rows consume the quota.
    rate_window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_count = (
        await db.execute(
            select(func.count())
            .select_from(ResumeSuggestionDecision)
            .where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.decided_by_user_id == user_id,
                ResumeSuggestionDecision.created_at >= rate_window_start,
            )
        )
    ).scalar_one()
    if recent_count >= MAX_DECISIONS_PER_USER_RESUME_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "suggestion_decision_rate_limited",
                "message": "Too many suggestion decisions for this document; retry later.",
            },
            headers={"Retry-After": "3600"},
        )

    if resume.latex_content != body.expected_content:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_changed",
                "message": "The document changed before this suggestion was decided; it remains pending.",
            },
        )

    result_content = resume.latex_content if body.status == "accepted" else ""
    if body.status == "accepted":
        if not body.original_text:
            raise HTTPException(status_code=422, detail="original_text is required for acceptance")
        resolved = _resolve_unique(resume.latex_content, body.original_text, body.prefix, body.suffix)
        if resolved is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "suggestion_conflicted",
                    "message": "The original text or nearby context is no longer unique; the suggestion remains pending.",
                },
            )
        start, end = resolved
        result_content = resume.latex_content[:start] + body.replacement_text + resume.latex_content[end:]
        if len(result_content) > MAX_LATEX_CONTENT_LEN:
            raise HTTPException(status_code=422, detail="The accepted document exceeds the content limit")
        try:
            result_bytes = len(result_content.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise HTTPException(status_code=422, detail="The accepted document contains invalid Unicode") from exc
        if result_bytes > MAX_LATEX_CONTENT_BYTES:
            raise HTTPException(status_code=422, detail="The accepted document exceeds the byte limit")
        resume.latex_content = result_content
        resume.updated_at = datetime.now(timezone.utc)

    digest = sha256(body.expected_content.encode("utf-8")).hexdigest()
    decision = ResumeSuggestionDecision(
        resume_id=resume_id,
        suggestion_id=body.suggestion_id,
        status=body.status,
        decided_by_user_id=user_id,
        decided_by_role=role,
        expected_content_sha256=digest,
        result_content=result_content,
    )
    db.add(decision)
    await db.flush()
    # Keep full-document replay storage bounded. The resume row lock serializes
    # this compaction with every other decision for the same document. Recent
    # rejected/conflicted rows remain through the rate-limit window so the
    # database count cannot be pruned below the abuse quota. Accepted rows
    # retain compact idempotency tombstones for the proposal replay lifetime,
    # while only the newest accepted decisions retain their full source.
    retention_cutoff = datetime.now(timezone.utc) - timedelta(days=ACCEPTED_TOMBSTONE_RETENTION_DAYS)
    expired_nonaccepted_ids = (
        await db.execute(
            select(ResumeSuggestionDecision.id)
            .where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.status != "accepted",
                ResumeSuggestionDecision.created_at < rate_window_start,
            )
        )
    ).scalars().all()
    if expired_nonaccepted_ids:
        await db.execute(
            delete(ResumeSuggestionDecision).where(ResumeSuggestionDecision.id.in_(expired_nonaccepted_ids))
        )
    expired_accepted_ids = (
        await db.execute(
            select(ResumeSuggestionDecision.id)
            .where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.status == "accepted",
                ResumeSuggestionDecision.created_at < retention_cutoff,
            )
        )
    ).scalars().all()
    if expired_accepted_ids:
        await db.execute(
            delete(ResumeSuggestionDecision).where(ResumeSuggestionDecision.id.in_(expired_accepted_ids))
        )
    stale_accepted_ids = (
        await db.execute(
            select(ResumeSuggestionDecision.id)
            .where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.status == "accepted",
            )
            .order_by(
                ResumeSuggestionDecision.created_at.desc(),
                ResumeSuggestionDecision.id.desc(),
            )
            .offset(MAX_STORED_DECISIONS_PER_RESUME)
        )
    ).scalars().all()
    if stale_accepted_ids:
        await db.execute(
            update(ResumeSuggestionDecision)
            .where(ResumeSuggestionDecision.id.in_(stale_accepted_ids))
            .values(result_content="")
        )
    await db.commit()
    await db.refresh(decision)
    return _response(decision, replayed=False)


@router.get("/{resume_id}/suggestion-decisions/{suggestion_id}", response_model=SuggestionDecisionResponse)
async def get_suggestion_decision(
    resume_id: str,
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> SuggestionDecisionResponse:
    """Validate a Y.Map notification against the persisted decision log."""
    await _read_access_role(db, resume_id, user_id)
    decision = (
        await db.execute(
            select(ResumeSuggestionDecision).where(
                ResumeSuggestionDecision.resume_id == resume_id,
                ResumeSuggestionDecision.suggestion_id == suggestion_id,
            )
        )
    ).scalar_one_or_none()
    if decision is None:
        raise HTTPException(status_code=404, detail="Suggestion decision not found")
    current_content = (
        await db.execute(select(Resume.latex_content).where(Resume.id == resume_id))
    ).scalar_one()
    return _response(decision, replayed=True, fallback_content=current_content)

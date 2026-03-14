"""Cover letter generation and management API routes."""

import json
import time
import uuid
from datetime import datetime
from typing import List, Optional

import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import CoverLetter, Resume
from ..middleware.auth_middleware import get_current_user_required
from ..workers.cover_letter_worker import submit_cover_letter_generation

logger = get_logger(__name__)

router = APIRouter(prefix="/cover-letters", tags=["cover-letters"])

_JOB_TTL = 86400  # 24 hours


# ------------------------------------------------------------------ #
#  Schemas                                                             #
# ------------------------------------------------------------------ #

class GenerateCoverLetterRequest(BaseModel):
    resume_id: str
    job_description: str = Field(..., min_length=10, max_length=10_000)
    company_name: Optional[str] = Field(None, max_length=255)
    role_title: Optional[str] = Field(None, max_length=255)
    tone: str = Field("formal", pattern=r"^(formal|conversational|enthusiastic)$")
    length_preference: str = Field(
        "3_paragraphs", pattern=r"^(3_paragraphs|4_paragraphs|detailed)$"
    )


class GenerateCoverLetterResponse(BaseModel):
    success: bool
    job_id: str
    cover_letter_id: str
    message: str


class CoverLetterResponse(BaseModel):
    id: str
    user_id: Optional[str]
    resume_id: str
    job_description: Optional[str]
    company_name: Optional[str]
    role_title: Optional[str]
    tone: str
    length_preference: str
    latex_content: Optional[str]
    pdf_path: Optional[str]
    generation_job_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CoverLetterListItem(CoverLetterResponse):
    resume_title: str = ""

    class Config:
        from_attributes = True


class PaginatedCoverLettersResponse(BaseModel):
    cover_letters: List[CoverLetterListItem]
    total: int
    page: int
    limit: int
    pages: int


class CoverLetterStatsResponse(BaseModel):
    total: int


class UpdateCoverLetterRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

async def _write_initial_redis_state(
    job_id: str,
    job_type: str,
    user_id: Optional[str],
    estimated_seconds: int,
) -> None:
    """Write initial job.queued state to Redis (same pattern as job_routes)."""
    r = await get_redis_client()

    state = {
        "status": "queued",
        "stage": "",
        "percent": 0,
        "last_updated": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:state", _JOB_TTL, json.dumps(state))

    meta = {
        "job_id": job_id,
        "user_id": user_id,
        "job_type": job_type,
        "submitted_at": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:meta", _JOB_TTL, json.dumps(meta))

    event_id = str(uuid.uuid4())
    seq_key = f"latexy:job:{job_id}:seq"
    seq = await r.incr(seq_key)
    await r.expire(seq_key, _JOB_TTL)

    event = {
        "event_id": event_id,
        "job_id": job_id,
        "timestamp": time.time(),
        "sequence": seq,
        "type": "job.queued",
        "job_type": job_type,
        "user_id": user_id,
        "estimated_seconds": estimated_seconds,
    }
    payload_json = json.dumps(event)

    stream_key = f"latexy:stream:{job_id}"
    entry_id = await r.xadd(
        stream_key,
        {
            "payload": payload_json,
            "type": "job.queued",
            "sequence": str(seq),
            "event_id": event_id,
        },
        maxlen=10000,
        approximate=True,
    )
    await r.expire(stream_key, _JOB_TTL)

    ws_message = json.dumps({"type": "event", "event": event, "stream_id": entry_id})
    await r.publish(f"latexy:events:{job_id}", ws_message)


async def _verify_resume_ownership(
    db: AsyncSession, resume_id: str, user_id: str
) -> Resume:
    """Verify the resume exists and belongs to the user. Returns the resume."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found or not owned by you",
        )
    return resume


async def _verify_cover_letter_ownership(
    db: AsyncSession, cover_letter_id: str, user_id: str
) -> CoverLetter:
    """Verify the cover letter exists and belongs to the user."""
    result = await db.execute(
        select(CoverLetter).where(
            CoverLetter.id == cover_letter_id, CoverLetter.user_id == user_id
        )
    )
    cl = result.scalar_one_or_none()
    if not cl:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cover letter not found or not owned by you",
        )
    return cl


# ------------------------------------------------------------------ #
#  Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get("/", response_model=PaginatedCoverLettersResponse)
async def list_cover_letters(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=255),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all cover letters for the authenticated user with pagination."""
    base_filter = CoverLetter.user_id == user_id
    if search:
        search_filter = or_(
            CoverLetter.company_name.ilike(f"%{search}%"),
            CoverLetter.role_title.ilike(f"%{search}%"),
        )
        base_filter = base_filter & search_filter

    # Count
    count_result = await db.execute(
        select(sa_func.count()).select_from(CoverLetter).where(base_filter)
    )
    total = count_result.scalar() or 0
    pages = max(1, math.ceil(total / limit))

    # Fetch with resume join
    result = await db.execute(
        select(CoverLetter)
        .options(joinedload(CoverLetter.resume))
        .where(base_filter)
        .order_by(CoverLetter.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = result.unique().scalars().all()

    items = []
    for cl in rows:
        item = CoverLetterListItem.model_validate(cl)
        item.resume_title = cl.resume.title if cl.resume else ""
        items.append(item)

    return PaginatedCoverLettersResponse(
        cover_letters=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


@router.get("/stats", response_model=CoverLetterStatsResponse)
async def get_cover_letter_stats(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Get cover letter count for the authenticated user."""
    result = await db.execute(
        select(sa_func.count()).select_from(CoverLetter).where(CoverLetter.user_id == user_id)
    )
    total = result.scalar() or 0
    return CoverLetterStatsResponse(total=total)


@router.post("/generate", response_model=GenerateCoverLetterResponse)
async def generate_cover_letter(
    request: GenerateCoverLetterRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Generate a cover letter for a resume using AI."""
    resume = await _verify_resume_ownership(db, request.resume_id, user_id)

    job_id = str(uuid.uuid4())
    cover_letter_id = str(uuid.uuid4())

    # Create cover letter DB record (latex_content filled by worker on completion)
    cl = CoverLetter(
        id=cover_letter_id,
        user_id=user_id,
        resume_id=request.resume_id,
        job_description=request.job_description,
        company_name=request.company_name,
        role_title=request.role_title,
        tone=request.tone,
        length_preference=request.length_preference,
        generation_job_id=job_id,
    )
    db.add(cl)
    await db.commit()

    # Write initial Redis state for WebSocket streaming
    await _write_initial_redis_state(
        job_id, "cover_letter_generation", user_id, estimated_seconds=60
    )

    # Submit Celery task
    submit_cover_letter_generation(
        resume_latex=resume.latex_content,
        job_description=request.job_description,
        job_id=job_id,
        user_id=user_id,
        cover_letter_id=cover_letter_id,
        company_name=request.company_name,
        role_title=request.role_title,
        tone=request.tone,
        length_preference=request.length_preference,
        user_plan="free",
    )

    return GenerateCoverLetterResponse(
        success=True,
        job_id=job_id,
        cover_letter_id=cover_letter_id,
        message="Cover letter generation started",
    )


@router.get("/{cover_letter_id}", response_model=CoverLetterResponse)
async def get_cover_letter(
    cover_letter_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Get a cover letter by ID."""
    cl = await _verify_cover_letter_ownership(db, cover_letter_id, user_id)
    return cl


@router.put("/{cover_letter_id}", response_model=CoverLetterResponse)
async def update_cover_letter(
    cover_letter_id: str,
    body: UpdateCoverLetterRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Update a cover letter's LaTeX content (after manual editing)."""
    cl = await _verify_cover_letter_ownership(db, cover_letter_id, user_id)
    cl.latex_content = body.latex_content
    await db.commit()
    await db.refresh(cl)
    return cl


@router.delete("/{cover_letter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cover_letter(
    cover_letter_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Delete a cover letter."""
    cl = await _verify_cover_letter_ownership(db, cover_letter_id, user_id)
    await db.delete(cl)
    await db.commit()


@router.get(
    "/resume/{resume_id}",
    response_model=List[CoverLetterResponse],
)
async def list_resume_cover_letters(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all cover letters for a resume."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(CoverLetter)
        .where(CoverLetter.resume_id == resume_id, CoverLetter.user_id == user_id)
        .order_by(CoverLetter.created_at.desc())
    )
    return list(result.scalars().all())

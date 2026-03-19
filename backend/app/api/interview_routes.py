"""Interview preparation API routes."""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import InterviewPrep, Resume
from ..middleware.auth_middleware import get_current_user_required
from ..workers.interview_prep_worker import submit_interview_prep_generation

logger = get_logger(__name__)

router = APIRouter(prefix="/interview-prep", tags=["interview-prep"])


# ------------------------------------------------------------------ #
#  Schemas                                                             #
# ------------------------------------------------------------------ #


class GenerateInterviewPrepRequest(BaseModel):
    resume_id: str
    job_description: Optional[str] = Field(None, max_length=20_000)
    company_name: Optional[str] = Field(None, max_length=255)
    role_title: Optional[str] = Field(None, max_length=255)


class GenerateInterviewPrepResponse(BaseModel):
    success: bool
    job_id: str
    prep_id: str
    message: str


class InterviewQuestion(BaseModel):
    category: str
    question: str
    what_interviewer_assesses: str
    star_hint: Optional[str] = None


class InterviewPrepResponse(BaseModel):
    id: str
    user_id: Optional[str]
    resume_id: str
    job_description: Optional[str]
    company_name: Optional[str]
    role_title: Optional[str]
    questions: List[Dict]
    generation_job_id: Optional[str]
    created_at: str
    updated_at: str


def _serialize(prep: InterviewPrep) -> dict:
    return {
        "id": prep.id,
        "user_id": prep.user_id,
        "resume_id": prep.resume_id,
        "job_description": prep.job_description,
        "company_name": prep.company_name,
        "role_title": prep.role_title,
        "questions": prep.questions or [],
        "generation_job_id": prep.generation_job_id,
        "created_at": prep.created_at.isoformat() if prep.created_at else None,
        "updated_at": prep.updated_at.isoformat() if prep.updated_at else None,
    }


# ------------------------------------------------------------------ #
#  Endpoints                                                           #
# ------------------------------------------------------------------ #


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_interview_prep(
    body: GenerateInterviewPrepRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> GenerateInterviewPrepResponse:
    """Start interview question generation for a resume."""
    # Verify resume ownership
    result = await db.execute(
        select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    job_id = str(uuid.uuid4())
    prep_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    prep = InterviewPrep(
        id=prep_id,
        user_id=user_id,
        resume_id=body.resume_id,
        job_description=body.job_description,
        company_name=body.company_name,
        role_title=body.role_title,
        questions=[],
        generation_job_id=job_id,
        created_at=now,
        updated_at=now,
    )
    db.add(prep)
    await db.commit()

    submit_interview_prep_generation(
        resume_latex=resume.latex_content,
        prep_id=prep_id,
        job_id=job_id,
        user_id=user_id,
        resume_id=body.resume_id,
        job_description=body.job_description,
        company_name=body.company_name,
        role_title=body.role_title,
    )

    return GenerateInterviewPrepResponse(
        success=True,
        job_id=job_id,
        prep_id=prep_id,
        message="Interview question generation started",
    )


@router.get("/{prep_id}", response_model=InterviewPrepResponse)
async def get_interview_prep(
    prep_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific interview prep session."""
    result = await db.execute(
        select(InterviewPrep).where(
            InterviewPrep.id == prep_id,
            InterviewPrep.user_id == user_id,
        )
    )
    prep = result.scalar_one_or_none()
    if not prep:
        raise HTTPException(status_code=404, detail="Interview prep not found")
    return _serialize(prep)


@router.delete("/{prep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_prep(
    prep_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete an interview prep session."""
    result = await db.execute(
        select(InterviewPrep).where(
            InterviewPrep.id == prep_id,
            InterviewPrep.user_id == user_id,
        )
    )
    prep = result.scalar_one_or_none()
    if not prep:
        raise HTTPException(status_code=404, detail="Interview prep not found")
    await db.delete(prep)
    await db.commit()


# ------------------------------------------------------------------ #
#  Resume-scoped endpoint (separate router prefix)                    #
# ------------------------------------------------------------------ #

resume_interview_router = APIRouter(prefix="/resumes", tags=["interview-prep"])


@resume_interview_router.get("/{resume_id}/interview-prep")
async def list_resume_interview_prep(
    resume_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> List[dict]:
    """List all interview prep sessions for a resume, newest first."""
    # Verify resume ownership
    res_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if not res_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found")

    result = await db.execute(
        select(InterviewPrep)
        .where(InterviewPrep.resume_id == resume_id, InterviewPrep.user_id == user_id)
        .order_by(InterviewPrep.created_at.desc())
    )
    preps = result.scalars().all()
    return [_serialize(p) for p in preps]

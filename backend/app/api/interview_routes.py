"""Interview preparation API routes."""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

import openai
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import InterviewPrep, Resume
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..services.entitlement_service import entitlement_service
from ..utils.uuid_guard import ensure_uuid
from ..workers.interview_prep_worker import submit_interview_prep_generation
from .ai_routes import _charge_ai_assist, _meter_identity, _resolve_ai_api_key

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


class SimulationAnswer(BaseModel):
    question_index: int = Field(..., ge=0, le=49)
    answer: str = Field(..., min_length=20, max_length=1200)


class EvaluateSimulationRequest(BaseModel):
    mode: Literal["coach", "mock"]
    answers: list[SimulationAnswer] = Field(..., min_length=1, max_length=15)

    @model_validator(mode="after")
    def validate_answers(self):
        indexes = [answer.question_index for answer in self.answers]
        if len(indexes) != len(set(indexes)):
            raise ValueError("question indexes must be unique")
        if sum(len(answer.answer) for answer in self.answers) > 18_000:
            raise ValueError("answers contain too much text")
        return self


class SimulationQuestionFeedback(BaseModel):
    question_index: int
    score: int = Field(..., ge=0, le=100)
    strengths: list[str] = Field(..., min_length=1, max_length=3)
    improvements: list[str] = Field(..., min_length=1, max_length=3)
    suggested_outline: list[str] = Field(..., min_length=1, max_length=5)

    @field_validator("strengths", "improvements", "suggested_outline")
    @classmethod
    def validate_feedback_text(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 500 for value in normalized):
            raise ValueError("feedback items must contain 1 to 500 characters")
        return normalized


class EvaluateSimulationResponse(BaseModel):
    mode: Literal["coach", "mock"]
    feedback: list[SimulationQuestionFeedback]
    average_score: int = Field(..., ge=0, le=100)
    overall_feedback: str = Field(..., max_length=1000)


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


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_feature("interview_prep"))],
)
async def generate_interview_prep(
    body: GenerateInterviewPrepRequest,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> GenerateInterviewPrepResponse:
    """Start interview question generation for a resume."""
    ensure_uuid(body.resume_id, "Resume not found")
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

    # Enqueue the generation task. If the broker is unavailable the committed
    # row would otherwise be orphaned forever with questions=[]; delete it and
    # surface the failure to the caller.
    try:
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
    except Exception as exc:
        logger.error(
            "Failed to enqueue interview prep %s",
            prep_id,
            extra={"error_type": type(exc).__name__},
        )
        await db.delete(prep)
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Interview prep generation is temporarily unavailable. Please try again.",
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
    ensure_uuid(prep_id, "Interview prep not found")
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


@router.post(
    "/{prep_id}/simulate",
    response_model=EvaluateSimulationResponse,
    dependencies=[Depends(require_feature("interview_prep"))],
)
async def evaluate_interview_simulation(
    prep_id: str,
    body: EvaluateSimulationRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate transient text answers in Coach or Mock mode."""
    ensure_uuid(prep_id, "Interview prep not found")
    result = await db.execute(
        select(InterviewPrep).where(
            InterviewPrep.id == prep_id,
            InterviewPrep.user_id == user_id,
        )
    )
    prep = result.scalar_one_or_none()
    if not prep:
        raise HTTPException(status_code=404, detail="Interview prep not found")
    questions = prep.questions or []
    evaluation_input = []
    for answer in body.answers:
        if answer.question_index >= len(questions):
            raise HTTPException(status_code=422, detail="Question index is outside this session")
        question = questions[answer.question_index]
        if not isinstance(question, dict) or not question.get("question"):
            raise HTTPException(
                status_code=502, detail="This interview session contains an invalid question"
            )
        evaluation_input.append(
            {
                "question_index": answer.question_index,
                "question": question.get("question", ""),
                "assessment": question.get("what_interviewer_assesses", ""),
                "recommended_outline": question.get("ideal_response_outline", []),
                "answer": answer.answer,
            }
        )

    resolved = await _resolve_ai_api_key(
        db, user_id, _meter_identity(http_request, user_id)
    )
    if not resolved:
        raise HTTPException(
            status_code=503,
            detail="Interview simulation is temporarily unavailable. Configure an OpenAI key and retry.",
        )
    quota_ticket = await _charge_ai_assist(db, user_id, resolved)
    try:
        client = openai.AsyncOpenAI(api_key=resolved.key)
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Evaluate text-only interview practice answers. Be specific, constructive, and "
                        "grounded only in the supplied question, rubric, and answer. Do not infer hiring "
                        "outcomes or endorse unverifiable claims. Return JSON with feedback entries containing "
                        "question_index, integer score 0-100, strengths, improvements, and suggested_outline; "
                        "also return overall_feedback. Use one to three concise strengths/improvements and one "
                        "to five outline points per answer."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"mode": body.mode, "answers": evaluation_input}, ensure_ascii=False
                    ),
                },
            ],
            max_tokens=5000,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("response is not an object")
        raw_feedback = parsed.get("feedback")
        if not isinstance(raw_feedback, list):
            raise ValueError("feedback is not a list")
        feedback = [SimulationQuestionFeedback.model_validate(item) for item in raw_feedback]
        expected_indexes = [answer.question_index for answer in body.answers]
        if [item.question_index for item in feedback] != expected_indexes:
            raise ValueError("feedback does not match submitted answers")
        overall = parsed.get("overall_feedback")
        if not isinstance(overall, str) or not overall.strip():
            raise ValueError("overall feedback is missing")
        average = round(sum(item.score for item in feedback) / len(feedback))
        return EvaluateSimulationResponse(
            mode=body.mode,
            feedback=feedback,
            average_score=average,
            overall_feedback=overall.strip(),
        )
    except Exception as exc:
        if quota_ticket is not None:
            await entitlement_service.refund_quota(quota_ticket)
        logger.error("Interview simulation evaluation failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(
            status_code=502,
            detail="AI provider could not evaluate this practice session. Please retry.",
        ) from exc


@router.delete("/{prep_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_prep(
    prep_id: str,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
):
    """Delete an interview prep session."""
    # Same guard as the fetch route above: a non-UUID segment would raise
    # asyncpg DataError -> 500 rather than a 404.
    ensure_uuid(prep_id, "Interview prep not found")
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
    ensure_uuid(resume_id, "Resume not found")
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

from typing import Any, Dict, List, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func

from ..core.config import settings
from ..database.connection import get_db
from ..database.models import Resume, Optimization
from ..middleware.auth_middleware import get_current_user_required
from pydantic import BaseModel, Field
from datetime import datetime

router = APIRouter(prefix="/resumes", tags=["resumes"])

# --- Schemas ---

class ResumeBase(BaseModel):
    title: str
    latex_content: str
    is_template: bool = False
    tags: Optional[List[str]] = None

class ResumeCreate(ResumeBase):
    pass

class ResumeUpdate(BaseModel):
    title: Optional[str] = None
    latex_content: Optional[str] = None
    is_template: Optional[bool] = None
    tags: Optional[List[str]] = None

class ResumeResponse(ResumeBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ResumeStats(BaseModel):
    total_resumes: int
    total_templates: int
    last_updated: Optional[datetime]

# --- Endpoints ---

@router.get("/stats", response_model=ResumeStats)
async def get_resume_stats(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get high-level stats about user's resumes."""
    total = await db.execute(
        select(func.count(Resume.id)).where(Resume.user_id == user_id)
    )
    templates = await db.execute(
        select(func.count(Resume.id)).where(Resume.user_id == user_id, Resume.is_template == True)
    )
    latest = await db.execute(
        select(func.max(Resume.updated_at)).where(Resume.user_id == user_id)
    )
    
    return {
        "total_resumes": total.scalar() or 0,
        "total_templates": templates.scalar() or 0,
        "last_updated": latest.scalar()
    }

@router.post("/", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def create_resume(
    resume_in: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Create a new resume for the authenticated user."""
    resume = Resume(
        id=str(uuid4()),
        user_id=user_id,
        **resume_in.model_dump()
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    if settings.OPENAI_API_KEY:
        try:
            from ..workers.ats_worker import embed_resume_task
            embed_resume_task.apply_async(
                kwargs={"resume_id": str(resume.id), "latex_content": resume.latex_content,
                        "user_id": user_id},
                queue="ats", priority=1,
            )
        except Exception:
            pass  # Embedding is best-effort

    return resume

@router.get("/", response_model=List[ResumeResponse])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """List all resumes belonging to the authenticated user."""
    result = await db.execute(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.updated_at.desc())
    )
    return result.scalars().all()

@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get a specific resume by ID."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

@router.put("/{resume_id}", response_model=ResumeResponse)
async def update_resume(
    resume_id: str,
    resume_in: ResumeUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Update an existing resume."""
    # Check ownership first
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    update_data = resume_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(resume, key, value)
    
    resume.updated_at = datetime.now()
    await db.commit()
    await db.refresh(resume)

    if settings.OPENAI_API_KEY and update_data.get("latex_content"):
        try:
            from ..workers.ats_worker import embed_resume_task
            embed_resume_task.apply_async(
                kwargs={"resume_id": str(resume.id), "latex_content": resume.latex_content,
                        "user_id": user_id},
                queue="ats", priority=1,
            )
        except Exception:
            pass  # Embedding is best-effort

    return resume

@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Delete a resume."""
    result = await db.execute(
        delete(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Resume not found")
    await db.commit()
    return None


# ── Optimization history ──────────────────────────────────────────────────

class RecordOptimizationRequest(BaseModel):
    original_latex: str
    optimized_latex: str
    changes_made: Optional[List[Dict[str, Any]]] = None
    ats_score: Optional[float] = None
    tokens_used: Optional[int] = None
    job_description: Optional[str] = None


class OptimizationHistoryEntry(BaseModel):
    id: str
    created_at: datetime
    ats_score: Optional[float]
    changes_count: int
    tokens_used: Optional[int]


class RestoreOptimizationResponse(BaseModel):
    success: bool
    latex_content: str


@router.post("/{resume_id}/record-optimization", status_code=status.HTTP_201_CREATED)
async def record_optimization(
    resume_id: str,
    body: RecordOptimizationRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Save an optimization record after a successful AI job."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Resume not found")

    opt = Optimization(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        original_latex=body.original_latex,
        optimized_latex=body.optimized_latex,
        job_description=body.job_description or "",
        provider="openai",
        model="gpt-4o",
        tokens_used=body.tokens_used,
        ats_score=body.ats_score,
        changes_made=body.changes_made or [],
    )
    db.add(opt)
    await db.commit()
    return {"success": True, "id": opt.id}


@router.get("/{resume_id}/optimization-history", response_model=List[OptimizationHistoryEntry])
async def get_optimization_history(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return the 20 most recent optimization records for a resume."""
    result = await db.execute(
        select(Optimization)
        .where(Optimization.resume_id == resume_id, Optimization.user_id == user_id)
        .order_by(Optimization.created_at.desc())
        .limit(20)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "ats_score": r.ats_score if isinstance(r.ats_score, float) else None,
            "changes_count": len(r.changes_made) if isinstance(r.changes_made, list) else 0,
            "tokens_used": r.tokens_used,
        }
        for r in rows
    ]


@router.post(
    "/{resume_id}/restore-optimization/{opt_id}",
    response_model=RestoreOptimizationResponse,
)
async def restore_optimization(
    resume_id: str,
    opt_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Restore a resume to a previously optimized version."""
    # Verify ownership of resume
    res_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = res_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Fetch the optimization record
    opt_result = await db.execute(
        select(Optimization).where(
            Optimization.id == opt_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    opt = opt_result.scalar_one_or_none()
    if not opt:
        raise HTTPException(status_code=404, detail="Optimization record not found")

    resume.latex_content = opt.optimized_latex
    resume.updated_at = datetime.now()
    await db.commit()
    return {"success": True, "latex_content": opt.optimized_latex}

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Optimization, Resume, UsageAnalytics
from ..middleware.auth_middleware import get_current_user_required

logger = get_logger(__name__)

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
    parent_resume_id: Optional[str] = None
    variant_count: int = 0
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
        select(func.count(Resume.id)).where(Resume.user_id == user_id, Resume.is_template)
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
        except Exception as exc:
            logger.warning(f"Failed to enqueue embedding for resume {resume.id}: {exc}")

    return resume

def _variant_count_subquery():
    """Correlated subquery counting direct child variants of each resume."""
    from sqlalchemy.orm import aliased
    ChildResume = aliased(Resume)
    return (
        select(func.count(ChildResume.id))
        .where(ChildResume.parent_resume_id == Resume.id)
        .correlate(Resume)
        .scalar_subquery()
        .label("variant_count")
    )


@router.get("/")
async def list_resumes(
    page: int = 1,
    limit: int = 20,
    parent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """List resumes belonging to the authenticated user with pagination."""
    page = max(1, page)
    limit = max(1, min(limit, 100))
    offset = (page - 1) * limit

    filters = [Resume.user_id == user_id]
    if parent_id is not None:
        filters.append(Resume.parent_resume_id == parent_id)

    count_result = await db.execute(
        select(func.count(Resume.id)).where(*filters)
    )
    total = count_result.scalar() or 0

    variant_count_sq = _variant_count_subquery()
    result = await db.execute(
        select(Resume, variant_count_sq)
        .where(*filters)
        .order_by(Resume.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    resumes_out = []
    for resume, vc in rows:
        d = ResumeResponse.model_validate(resume).model_dump()
        d["variant_count"] = vc or 0
        resumes_out.append(d)

    return {
        "resumes": resumes_out,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }

@router.get("/{resume_id}", response_model=ResumeResponse)
async def get_resume(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get a specific resume by ID."""
    variant_count_sq = _variant_count_subquery()
    result = await db.execute(
        select(Resume, variant_count_sq)
        .where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found")
    resume, vc = row
    resp = ResumeResponse.model_validate(resume)
    resp.variant_count = vc or 0
    return resp

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
        except Exception as exc:
            logger.warning(f"Failed to enqueue embedding for resume {resume.id}: {exc}")

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


# ── Variant / Fork system ─────────────────────────────────────────────────

class ForkResumeRequest(BaseModel):
    title: Optional[str] = None


class DiffWithParentResponse(BaseModel):
    parent_latex: str
    parent_title: str
    variant_latex: str
    variant_title: str


@router.post("/{resume_id}/fork", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def fork_resume(
    resume_id: str,
    body: ForkResumeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Create a variant (fork) of an existing resume."""
    parent = await _verify_resume_ownership(db, resume_id, user_id)

    variant_title = body.title or f"{parent.title} — Variant"
    variant = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=variant_title,
        latex_content=parent.latex_content,
        is_template=False,
        tags=list(parent.tags) if parent.tags else None,
        parent_resume_id=parent.id,
    )
    db.add(variant)

    # Record analytics event
    analytics = UsageAnalytics(
        id=str(uuid4()),
        user_id=user_id,
        action="resume_forked",
        resource_type="resume",
        event_metadata={"parent_resume_id": parent.id, "variant_resume_id": variant.id},
    )
    db.add(analytics)

    await db.commit()
    await db.refresh(variant)

    # Fire-and-forget embedding task
    if settings.OPENAI_API_KEY:
        try:
            from ..workers.ats_worker import embed_resume_task
            embed_resume_task.apply_async(
                kwargs={"resume_id": str(variant.id), "latex_content": variant.latex_content,
                        "user_id": user_id},
                queue="ats", priority=1,
            )
        except Exception as exc:
            logger.warning(f"Failed to enqueue embedding for variant {variant.id}: {exc}")

    resp = ResumeResponse.model_validate(variant)
    resp.variant_count = 0
    return resp


@router.get("/{resume_id}/variants", response_model=List[ResumeResponse])
async def list_variants(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """List all direct child variants of a resume."""
    await _verify_resume_ownership(db, resume_id, user_id)

    variant_count_sq = _variant_count_subquery()
    result = await db.execute(
        select(Resume, variant_count_sq)
        .where(Resume.parent_resume_id == resume_id, Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
    )
    rows = result.all()

    out = []
    for resume, vc in rows:
        d = ResumeResponse.model_validate(resume)
        d.variant_count = vc or 0
        out.append(d)
    return out


@router.get("/{resume_id}/diff-with-parent", response_model=DiffWithParentResponse)
async def diff_with_parent(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get diff data between a variant and its parent resume."""
    variant = await _verify_resume_ownership(db, resume_id, user_id)

    if not variant.parent_resume_id:
        raise HTTPException(status_code=400, detail="This resume has no parent")

    # Fetch parent (must be owned by same user)
    result = await db.execute(
        select(Resume).where(Resume.id == variant.parent_resume_id, Resume.user_id == user_id)
    )
    parent = result.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=400, detail="Parent resume not found")

    return DiffWithParentResponse(
        parent_latex=parent.latex_content,
        parent_title=parent.title,
        variant_latex=variant.latex_content,
        variant_title=variant.title,
    )


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
    try:
        result = await db.execute(
            select(Optimization)
            .where(Optimization.resume_id == resume_id, Optimization.user_id == user_id)
            .order_by(Optimization.created_at.desc())
            .limit(20)
        )
        rows = result.scalars().all()
    except Exception as exc:
        logger.warning(f"DB error fetching optimization history for resume {resume_id}: {exc}")
        return []
    try:
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "ats_score": float(r.ats_score) if r.ats_score is not None else None,
                "changes_count": len(r.changes_made) if isinstance(r.changes_made, list) else 0,
                "tokens_used": r.tokens_used,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning(f"Error serializing optimization history for resume {resume_id}: {exc}")
        return []


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


# ── Checkpoints (version history) ────────────────────────────────────────

class CreateCheckpointRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)


class CheckpointEntry(BaseModel):
    id: str
    created_at: datetime
    checkpoint_label: Optional[str] = None
    is_checkpoint: bool
    is_auto_save: bool
    optimization_level: Optional[str] = None
    ats_score: Optional[float] = None
    changes_count: int
    has_content: bool = True


class CheckpointContentResponse(BaseModel):
    original_latex: str
    optimized_latex: str
    checkpoint_label: Optional[str] = None


async def _verify_resume_ownership(
    db: AsyncSession, resume_id: str, user_id: str
) -> Resume:
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


@router.post("/{resume_id}/checkpoints", status_code=status.HTTP_201_CREATED)
async def create_checkpoint(
    resume_id: str,
    body: CreateCheckpointRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Create a manual checkpoint (named snapshot) of the current resume content."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)

    # Enforce max 20 manual checkpoints per resume
    count_result = await db.execute(
        select(func.count(Optimization.id)).where(
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
            Optimization.is_checkpoint.is_(True),
            Optimization.is_auto_save.is_(False),
        )
    )
    if (count_result.scalar() or 0) >= 20:
        raise HTTPException(
            status_code=400,
            detail="Maximum 20 manual checkpoints per resume. Delete older ones first.",
        )

    cp = Optimization(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        original_latex=resume.latex_content,
        optimized_latex=resume.latex_content,
        job_description="",
        provider="checkpoint",
        model="manual",
        is_checkpoint=True,
        is_auto_save=False,
        checkpoint_label=body.label,
    )
    db.add(cp)
    await db.commit()
    await db.refresh(cp)

    return {"id": cp.id, "created_at": cp.created_at, "label": cp.checkpoint_label}


@router.get("/{resume_id}/checkpoints", response_model=List[CheckpointEntry])
async def list_checkpoints(
    resume_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all checkpoints + auto-saves + optimizations for a resume (newest first)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization)
        .where(Optimization.resume_id == resume_id, Optimization.user_id == user_id)
        .order_by(Optimization.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()

    return [
        CheckpointEntry(
            id=r.id,
            created_at=r.created_at,
            checkpoint_label=r.checkpoint_label,
            is_checkpoint=r.is_checkpoint,
            is_auto_save=r.is_auto_save,
            optimization_level=(
                r.model if not r.is_checkpoint else None
            ),
            ats_score=float(r.ats_score) if r.ats_score is not None else None,
            changes_count=len(r.changes_made) if isinstance(r.changes_made, list) else 0,
            has_content=True,
        )
        for r in rows
    ]


@router.get("/{resume_id}/checkpoints/{checkpoint_id}/content", response_model=CheckpointContentResponse)
async def get_checkpoint_content(
    resume_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Fetch the full LaTeX content of a specific checkpoint/optimization."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization).where(
            Optimization.id == checkpoint_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return CheckpointContentResponse(
        original_latex=cp.original_latex,
        optimized_latex=cp.optimized_latex,
        checkpoint_label=cp.checkpoint_label,
    )


@router.delete("/{resume_id}/checkpoints/{checkpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checkpoint(
    resume_id: str,
    checkpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Delete a manual checkpoint. Only is_checkpoint=True entries can be deleted."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(Optimization).where(
            Optimization.id == checkpoint_id,
            Optimization.resume_id == resume_id,
            Optimization.user_id == user_id,
        )
    )
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    if not cp.is_checkpoint or cp.is_auto_save:
        raise HTTPException(
            status_code=400,
            detail="Only manual checkpoint entries can be deleted. Auto-saves and optimization records are preserved for history.",
        )

    await db.delete(cp)
    await db.commit()
    return None

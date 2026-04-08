import io
import os as _os
import re
import secrets
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from jinja2 import Environment as _JinjaEnv
from jinja2 import FileSystemLoader as _JinjaFSL
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Optimization, Resume, ResumeCollaborator, UsageAnalytics
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
    # resume_settings is the ORM attribute; we expose it as "metadata" in JSON
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias="resume_settings")
    share_token: Optional[str] = None
    share_url: Optional[str] = None
    # GitHub sync (Feature 37)
    github_sync_enabled: bool = False
    github_repo_name: Optional[str] = None
    github_last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode='after')
    def _compute_share_url(self) -> 'ResumeResponse':
        if self.share_token and not self.share_url:
            self.share_url = f"{settings.FRONTEND_URL}/r/{self.share_token}"
        return self

    # Freshness (Feature 48) — computed from updated_at, never read from ORM/mock
    @computed_field
    @property
    def days_since_updated(self) -> int:
        now = datetime.now(timezone.utc)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).days

    @computed_field
    @property
    def freshness_status(self) -> str:
        days = self.days_since_updated
        return "fresh" if days < 30 else "stale" if days < 90 else "very_stale"


ALLOWED_LATEXMK_FLAGS = [
    "--shell-escape",
    "--synctex=1",
    "--file-line-error",
    "--interaction=nonstopmode",
    "--halt-on-error",
]


class ResumeSettingsUpdate(BaseModel):
    compiler: Optional[str] = None
    custom_flags: Optional[str] = None  # kept for backward compat
    texlive_version: Optional[str] = None
    main_file: Optional[str] = None
    latexmk_flags: Optional[List[str]] = None
    extra_packages: Optional[List[str]] = None

    @field_validator("texlive_version")
    @classmethod
    def validate_texlive_version(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("2022", "2023", "2024"):
            raise ValueError("texlive_version must be one of: 2022, 2023, 2024")
        return v

    @field_validator("main_file")
    @classmethod
    def validate_main_file(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^[a-zA-Z0-9_-]+\.tex$", v):
            raise ValueError("main_file must match [a-zA-Z0-9_-]+.tex (no path separators)")
        return v

    @field_validator("latexmk_flags")
    @classmethod
    def validate_latexmk_flags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for flag in v:
                if flag not in ALLOWED_LATEXMK_FLAGS:
                    raise ValueError(
                        f"Flag {flag!r} is not in the allowed list: {ALLOWED_LATEXMK_FLAGS}"
                    )
        return v

    @field_validator("extra_packages")
    @classmethod
    def validate_extra_packages(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            for pkg in v:
                if len(pkg) > 50:
                    raise ValueError(f"Package name too long: {pkg!r} (max 50 chars)")
                if not re.match(r"^[a-zA-Z0-9-]+$", pkg):
                    raise ValueError(
                        f"Invalid package name {pkg!r}: only alphanumeric and hyphens allowed"
                    )
        return v

class ResumeStats(BaseModel):
    total_resumes: int
    total_templates: int
    last_updated: Optional[datetime]
    avg_ats_score: Optional[float] = None
    best_ats_score: Optional[float] = None
    optimized_count: int = 0


# --- Search schemas ---

class SearchMatch(BaseModel):
    line_number: int
    line_content: str
    context_before: List[str]
    context_after: List[str]
    highlight_start: int
    highlight_end: int

class ResumeSearchResult(BaseModel):
    resume_id: str
    resume_title: str
    updated_at: datetime
    matches: List[SearchMatch]

class SearchResponse(BaseModel):
    results: List[ResumeSearchResult]
    total_resumes_matched: int
    query: str

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
    ats_avg = await db.execute(
        select(func.avg(Optimization.ats_score)).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )
    ats_max = await db.execute(
        select(func.max(Optimization.ats_score)).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )
    opt_count = await db.execute(
        select(func.count(func.distinct(Optimization.resume_id))).where(
            Optimization.user_id == user_id,
            Optimization.ats_score.is_not(None),
        )
    )

    avg_val = ats_avg.scalar()
    max_val = ats_max.scalar()
    return {
        "total_resumes": total.scalar() or 0,
        "total_templates": templates.scalar() or 0,
        "last_updated": latest.scalar(),
        "avg_ats_score": round(float(avg_val), 1) if avg_val is not None else None,
        "best_ats_score": round(float(max_val), 1) if max_val is not None else None,
        "optimized_count": opt_count.scalar() or 0,
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

def _extract_search_matches(
    latex_content: Optional[str],
    query: str,
    context_lines: int = 2,
    max_matches: int = 5,
) -> List[SearchMatch]:
    if not latex_content:
        return []
    lines = latex_content.split("\n")
    q_lower = query.lower()
    matches: List[SearchMatch] = []
    for i, line in enumerate(lines):
        idx = line.lower().find(q_lower)
        if idx == -1:
            continue
        matches.append(SearchMatch(
            line_number=i + 1,
            line_content=line,
            context_before=lines[max(0, i - context_lines):i],
            context_after=lines[i + 1:i + 1 + context_lines],
            highlight_start=idx,
            highlight_end=idx + len(query),
        ))
        if len(matches) >= max_matches:
            break
    return matches


@router.get("/search", response_model=SearchResponse)
async def search_resumes(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Full-text search across all user resumes (title + LaTeX content)."""
    from sqlalchemy import or_

    where_clause = (
        Resume.user_id == user_id,
        Resume.is_template == False,  # noqa: E712
        or_(
            Resume.title.ilike(f"%{q}%"),
            Resume.latex_content.ilike(f"%{q}%"),
        ),
    )

    count_stmt = select(func.count()).select_from(Resume).where(*where_clause)
    total: int = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(Resume)
        .where(*where_clause)
        .order_by(Resume.updated_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    results = []
    for resume in rows:
        matches = _extract_search_matches(resume.latex_content, q)
        # If no latex match but title matched, still return with empty matches list
        results.append(ResumeSearchResult(
            resume_id=str(resume.id),
            resume_title=resume.title,
            updated_at=resume.updated_at,
            matches=matches[:3],
        ))

    return SearchResponse(
        results=results,
        total_resumes_matched=total,
        query=q,
    )


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

    resume.updated_at = datetime.now(timezone.utc)
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


@router.patch("/{resume_id}/settings", response_model=ResumeResponse)
async def update_resume_settings(
    resume_id: str,
    body: ResumeSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Update per-resume settings (compiler preference, custom flags, etc.)."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Validate compiler if provided
    if body.compiler is not None:
        if body.compiler not in settings.ALLOWED_LATEX_COMPILERS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid compiler '{body.compiler}'. Allowed: {settings.ALLOWED_LATEX_COMPILERS}",
            )

    # Merge into existing settings
    current_meta = dict(resume.resume_settings or {})
    if body.compiler is not None:
        current_meta["compiler"] = body.compiler
    if body.custom_flags is not None:
        current_meta["custom_flags"] = body.custom_flags
    if body.texlive_version is not None:
        current_meta["texlive_version"] = body.texlive_version
    if body.main_file is not None:
        current_meta["main_file"] = body.main_file
    if body.latexmk_flags is not None:
        current_meta["latexmk_flags"] = body.latexmk_flags
    if body.extra_packages is not None:
        current_meta["extra_packages"] = body.extra_packages

    resume.resume_settings = current_meta
    resume.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resume)

    resp = ResumeResponse.model_validate(resume)
    resp.variant_count = 0
    return resp


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


# ── Quick Tailor ──────────────────────────────────────────────────────────────

class QuickTailorRequest(BaseModel):
    job_description: str = Field(..., min_length=10, max_length=10000)
    company_name: Optional[str] = Field(None, max_length=200)
    role_title: Optional[str] = Field(None, max_length=200)


class QuickTailorResponse(BaseModel):
    fork_id: str
    job_id: str


@router.post(
    "/{resume_id}/quick-tailor",
    response_model=QuickTailorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def quick_tailor_resume(
    resume_id: str,
    body: QuickTailorRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Fork the resume and kick off an aggressive optimization tailored to the job description."""
    parent = await _verify_resume_ownership(db, resume_id, user_id)

    label = body.role_title or body.company_name or "Tailored"
    fork_title = f"{parent.title} — {label}"

    fork = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=fork_title,
        latex_content=parent.latex_content,
        is_template=False,
        tags=list(parent.tags) if parent.tags else None,
        parent_resume_id=parent.id,
        resume_settings=dict(parent.resume_settings or {}),
    )
    db.add(fork)
    await db.commit()
    await db.refresh(fork)

    # Submit combined optimize+compile job for the fork
    from ..workers.orchestrator import submit_optimize_and_compile
    from .job_routes import _write_initial_redis_state

    job_id = str(uuid4())
    try:
        await _write_initial_redis_state(job_id, "combined", user_id, 120)
        submit_optimize_and_compile(
            latex_content=fork.latex_content,
            job_description=body.job_description,
            job_id=job_id,
            user_id=user_id,
            optimization_level="aggressive",
            custom_instructions=(
                "Tailor this resume for the specific role. "
                "Maximize keyword alignment with the job description. "
                "Keep all factual information accurate."
            ),
            resume_id=str(fork.id),
        )
    except Exception:
        await db.delete(fork)
        await db.commit()
        raise

    return QuickTailorResponse(fork_id=str(fork.id), job_id=job_id)


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


class ScoreHistoryPoint(BaseModel):
    timestamp: datetime
    ats_score: float
    label: Optional[str] = None


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


@router.get("/{resume_id}/score-history", response_model=List[ScoreHistoryPoint])
async def get_score_history(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return ATS score history for a resume, sorted oldest-first. Only entries with a score."""
    try:
        result = await db.execute(
            select(Optimization)
            .where(
                Optimization.resume_id == resume_id,
                Optimization.user_id == user_id,
                Optimization.ats_score.is_not(None),
            )
            .order_by(Optimization.created_at.asc())
        )
        rows = result.scalars().all()
    except Exception as exc:
        logger.warning(f"DB error fetching score history for resume {resume_id}: {exc}")
        return []
    return [
        {
            "timestamp": r.created_at,
            "ats_score": float(r.ats_score),
            "label": r.checkpoint_label,
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
    resume.updated_at = datetime.now(timezone.utc)
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


# ── Share links ───────────────────────────────────────────────────────────

class ShareLinkRequest(BaseModel):
    anonymous: bool = False


class ShareLinkResponse(BaseModel):
    share_token: str
    share_url: str
    created_at: datetime
    anonymous: bool = False


@router.post("/{resume_id}/share", response_model=ShareLinkResponse)
async def create_share_link(
    resume_id: str,
    body: ShareLinkRequest = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Generate (or return existing) share token for a resume."""
    anonymous = body.anonymous if body else False
    resume = await _verify_resume_ownership(db, resume_id, user_id)

    # Update anonymous flag in metadata regardless of whether token exists
    current_meta: dict = dict(resume.resume_settings or {})
    current_anonymous = current_meta.get("share_anonymous", False)
    if anonymous != current_anonymous:
        current_meta["share_anonymous"] = anonymous
        resume.resume_settings = current_meta

    if not resume.share_token:
        from pathlib import Path

        from ..database.models import Compilation

        # Try to upload the latest PDF to MinIO for persistent serving
        comp_result = await db.execute(
            select(Compilation)
            .where(
                Compilation.resume_id == resume_id,
                Compilation.status == "completed",
            )
            .order_by(Compilation.created_at.desc())
            .limit(1)
        )
        compilation = comp_result.scalar_one_or_none()

        if compilation and not compilation.pdf_path:
            temp_pdf = Path(settings.TEMP_DIR) / compilation.job_id / "resume.pdf"
            if temp_pdf.exists():
                try:
                    from ..services.storage_service import upload_bytes
                    share_key = f"shares/{resume_id}/resume.pdf"
                    upload_bytes(share_key, temp_pdf.read_bytes(), "application/pdf")
                    compilation.pdf_path = share_key
                    logger.info(f"Uploaded PDF to MinIO for resume {resume_id} at {share_key}")
                except Exception as exc:
                    logger.warning(f"Could not upload PDF to MinIO for share link: {exc}")

        resume.share_token = secrets.token_urlsafe(24)
        resume.share_token_created_at = datetime.now(timezone.utc)

    # If anonymous mode is newly enabled, submit a compile job for redacted LaTeX
    if anonymous and not current_meta.get("share_anonymous_job_id"):
        try:
            from ..services.latex_pii_redactor import redact
            from ..workers.latex_worker import submit_latex_compilation
            anon_job_id = str(uuid4())
            redacted_latex = redact(resume.latex_content)
            submit_latex_compilation(
                latex_content=redacted_latex,
                job_id=anon_job_id,
                user_id=user_id,
                resume_id=resume_id,
                metadata={"anonymous_share": True, "resume_id": resume_id},
            )
            current_meta["share_anonymous_job_id"] = anon_job_id
            resume.resume_settings = current_meta
            logger.info(f"Submitted anonymous compile job {anon_job_id} for resume {resume_id}")
        except Exception as exc:
            logger.error(f"Could not submit anonymous compile job for resume {resume_id}: {exc}")
            current_meta["share_anonymous_pending"] = True
            resume.resume_settings = current_meta

    await db.commit()
    await db.refresh(resume)

    return ShareLinkResponse(
        share_token=resume.share_token,
        share_url=f"{settings.FRONTEND_URL}/r/{resume.share_token}",
        created_at=resume.share_token_created_at,
        anonymous=anonymous,
    )


@router.delete("/{resume_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share_link(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Revoke a share token — the public link immediately stops working."""
    resume = await _verify_resume_ownership(db, resume_id, user_id)
    resume.share_token = None
    resume.share_token_created_at = None
    await db.commit()
    return None


# ── Bulk / Batch Export (Feature 49) ─────────────────────────────────────────

def _sanitize_filename(title: str) -> str:
    """Convert a resume title to a safe filename (no path traversal)."""
    safe = re.sub(r'[^\w\s-]', '', title).strip()
    safe = re.sub(r'[\s-]+', '_', safe)
    return safe or "resume"


@router.get("/export/bulk")
async def bulk_export(
    format: str = Query("tex", pattern="^(tex|pdf|docx)$"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Download all non-archived resumes as a ZIP archive.
    format=tex  → one .tex file per resume
    format=pdf  → one .pdf per resume (skips resumes with no compiled PDF)
    format=docx → one .docx per resume (rule-based LaTeX→DOCX conversion)
    """
    from pathlib import Path

    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.updated_at.desc())
    )
    resumes = result.scalars().all()

    if not resumes:
        # Return empty ZIP rather than 404
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED):
            pass
        buf.seek(0)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="latexy-resumes-{today}.zip"'},
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: dict[str, int] = {}

        for resume in resumes:
            base = _sanitize_filename(resume.title)
            # Deduplicate filenames
            if base in seen_names:
                seen_names[base] += 1
                filename_base = f"{base}_{seen_names[base]}"
            else:
                seen_names[base] = 0
                filename_base = base

            if format == "tex":
                zf.writestr(f"{filename_base}.tex", resume.latex_content or "")

            elif format == "pdf":
                from ..database.models import Compilation
                comp_result = await db.execute(
                    select(Compilation)
                    .where(
                        Compilation.resume_id == resume.id,
                        Compilation.status == "completed",
                    )
                    .order_by(Compilation.created_at.desc())
                    .limit(1)
                )
                compilation = comp_result.scalar_one_or_none()
                if not compilation:
                    continue  # skip — no compiled PDF

                pdf_bytes: Optional[bytes] = None
                if compilation.pdf_path:
                    try:
                        from ..services.storage_service import download_bytes
                        pdf_bytes = download_bytes(compilation.pdf_path)
                    except Exception as exc:
                        logger.warning(f"Could not fetch PDF from MinIO for {resume.id}: {exc}")
                if pdf_bytes is None:
                    temp_pdf = Path(settings.TEMP_DIR) / compilation.job_id / "resume.pdf"
                    if temp_pdf.exists():
                        pdf_bytes = temp_pdf.read_bytes()
                if pdf_bytes:
                    zf.writestr(f"{filename_base}.pdf", pdf_bytes)

            elif format == "docx":
                try:
                    from ..services.document_export_service import DocumentExportService
                    svc = DocumentExportService()
                    docx_bytes = svc.to_docx(resume.latex_content or "")
                    zf.writestr(f"{filename_base}.docx", docx_bytes)
                except Exception as exc:
                    logger.warning(f"DOCX export failed for {resume.id}: {exc}")

    buf.seek(0)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="latexy-resumes-{today}.zip"'},
    )


# ── Feature 40 — Collaborator management ─────────────────────────────────────

_VALID_ROLES = {"editor", "commenter", "viewer"}


class CollaboratorInviteRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(default="editor")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class CollaboratorRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class CollaboratorResponse(BaseModel):
    id: str
    resume_id: str
    user_id: str
    user_name: Optional[str]
    user_email: Optional[str]
    role: str
    invited_by: Optional[str]
    joined_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.post(
    "/{resume_id}/collaborators",
    response_model=CollaboratorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_collaborator(
    resume_id: str,
    body: CollaboratorInviteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Invite a user by email to collaborate on a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    # Look up invitee by email
    result = await db.execute(
        select(User).where(User.email == body.email.lower().strip())
    )
    invitee = result.scalar_one_or_none()
    if invitee is None:
        raise HTTPException(status_code=404, detail="User with that email not found")

    if invitee.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot invite yourself")

    # Check for existing row
    existing_result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == invitee.id,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User is already a collaborator")

    collab = ResumeCollaborator(
        resume_id=resume_id,
        user_id=invitee.id,
        role=body.role,
        invited_by=user_id,
    )
    db.add(collab)
    await db.commit()
    await db.refresh(collab)

    return CollaboratorResponse(
        id=collab.id,
        resume_id=collab.resume_id,
        user_id=collab.user_id,
        user_name=invitee.name,
        user_email=invitee.email,
        role=collab.role,
        invited_by=collab.invited_by,
        joined_at=collab.joined_at,
        created_at=collab.created_at,
    )


@router.get("/{resume_id}/collaborators", response_model=List[CollaboratorResponse])
async def list_collaborators(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """List all collaborators for a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    result = await db.execute(
        select(ResumeCollaborator, User)
        .join(User, User.id == ResumeCollaborator.user_id)
        .where(ResumeCollaborator.resume_id == resume_id)
        .order_by(ResumeCollaborator.created_at)
    )
    rows = result.all()

    return [
        CollaboratorResponse(
            id=collab.id,
            resume_id=collab.resume_id,
            user_id=collab.user_id,
            user_name=user.name,
            user_email=user.email,
            role=collab.role,
            invited_by=collab.invited_by,
            joined_at=collab.joined_at,
            created_at=collab.created_at,
        )
        for collab, user in rows
    ]


@router.patch(
    "/{resume_id}/collaborators/{collab_user_id}",
    response_model=CollaboratorResponse,
)
async def update_collaborator_role(
    resume_id: str,
    collab_user_id: str,
    body: CollaboratorRoleUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Change a collaborator's role (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    from ..database.models import User

    result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == collab_user_id,
        )
    )
    collab = result.scalar_one_or_none()
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    collab.role = body.role
    await db.commit()
    await db.refresh(collab)

    user_result = await db.execute(select(User).where(User.id == collab_user_id))
    user = user_result.scalar_one_or_none()

    return CollaboratorResponse(
        id=collab.id,
        resume_id=collab.resume_id,
        user_id=collab.user_id,
        user_name=user.name if user else None,
        user_email=user.email if user else None,
        role=collab.role,
        invited_by=collab.invited_by,
        joined_at=collab.joined_at,
        created_at=collab.created_at,
    )


@router.delete(
    "/{resume_id}/collaborators/{collab_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_collaborator(
    resume_id: str,
    collab_user_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Remove a collaborator from a resume (owner only)."""
    await _verify_resume_ownership(db, resume_id, user_id)

    result = await db.execute(
        select(ResumeCollaborator).where(
            ResumeCollaborator.resume_id == resume_id,
            ResumeCollaborator.user_id == collab_user_id,
        )
    )
    collab = result.scalar_one_or_none()
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    await db.delete(collab)
    await db.commit()
    return None


# ── Reference Page Generator (Feature 70) ───────────────────────────────────



def _get_jinja_env() -> _JinjaEnv:
    """Return a Jinja2 env with LaTeX-friendly delimiters (<< >>, <% %>)."""
    templates_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "templates")
    return _JinjaEnv(
        loader=_JinjaFSL(templates_dir),
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        keep_trailing_newline=True,
        autoescape=False,
    )


def _extract_documentclass(latex: str) -> str:
    m = re.search(r'\\documentclass(?:\[[^\]]*\])?\{[^}]+\}', latex)
    return m.group(0) if m else r'\documentclass{article}'


# Packages already injected by references_page.tex.j2 — skip to avoid option clashes.
_TEMPLATE_PACKAGES: set[str] = {"geometry", "hyperref", "parskip"}


def _extract_extra_preamble(latex: str) -> str:
    """Extract style macros from preamble to style-match the reference page."""
    lines_list = latex.splitlines()
    preamble_lines: list[str] = []
    in_preamble = False
    for line in lines_list:
        stripped = line.strip()
        if re.match(r'\\documentclass', stripped):
            in_preamble = True
            continue
        if stripped == r'\begin{document}':
            break
        if in_preamble and (
            stripped.startswith(r'\usepackage')
            or stripped.startswith(r'\definecolor')
            or stripped.startswith(r'\colorlet')
            or stripped.startswith(r'\setmainfont')
            or stripped.startswith(r'\newcommand')
            or stripped.startswith(r'\renewcommand')
        ):
            if 'draftwatermark' in stripped:
                continue
            # Skip packages the template already provides to avoid option clashes
            pkg_m = re.match(r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}', stripped)
            if pkg_m:
                pkgs = {p.strip() for p in pkg_m.group(1).split(',')}
                if pkgs & _TEMPLATE_PACKAGES:
                    continue
            preamble_lines.append(line)
    return '\n'.join(preamble_lines)


def _escape_latex(text: str) -> str:
    """Escape LaTeX special characters to prevent compilation errors/injection."""
    if not text:
        return text
    # Backslash must be replaced first
    replacements = [
        ('\\', r'\textbackslash{}'),
        ('&', r'\&'),
        ('%', r'\%'),
        ('$', r'\$'),
        ('#', r'\#'),
        ('_', r'\_'),
        ('{', r'\{'),
        ('}', r'\}'),
        ('~', r'\textasciitilde{}'),
        ('^', r'\textasciicircum{}'),
    ]
    for char, escaped in replacements:
        text = text.replace(char, escaped)
    return text


class ReferenceContact(BaseModel):
    name: str = Field(..., max_length=100)
    title: str = Field(..., max_length=200)
    company: str = Field(..., max_length=200)
    email: Optional[str] = None
    phone: Optional[str] = None
    relationship: str = Field(..., max_length=100)


class GenerateReferencesRequest(BaseModel):
    references: List[ReferenceContact] = Field(..., min_length=1, max_length=5)


class GenerateReferencesResponse(BaseModel):
    latex_content: str


@router.post("/{resume_id}/generate-references", response_model=GenerateReferencesResponse)
async def generate_references(
    resume_id: str,
    request: GenerateReferencesRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> GenerateReferencesResponse:
    """
    Generate a matching-style LaTeX reference page from up to 5 contact entries.
    Extracts \\documentclass and preamble macros from the source resume.
    """
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    source_latex: str = resume.latex_content or ""
    documentclass = _extract_documentclass(source_latex)
    extra_preamble = _extract_extra_preamble(source_latex)

    try:
        env = _get_jinja_env()
        template = env.get_template("references_page.tex.j2")
        # Escape all user-supplied fields before rendering to prevent LaTeX
        # compilation errors or injection via special characters (%, &, _, etc.).
        safe_refs = [
            {
                "name": _escape_latex(ref.name),
                "title": _escape_latex(ref.title),
                "company": _escape_latex(ref.company),
                "relationship": _escape_latex(ref.relationship),
                # Email used raw in mailto: URL; display copy is escaped
                "email": ref.email or "",
                "email_display": _escape_latex(ref.email or ""),
                "phone": _escape_latex(ref.phone or "") if ref.phone else "",
            }
            for ref in request.references
        ]
        latex_content = template.render(
            documentclass=documentclass,
            extra_preamble=extra_preamble,
            references=safe_refs,
        )
    except Exception as exc:
        logger.error(f"Reference page render error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to render reference page template")

    return GenerateReferencesResponse(latex_content=latex_content)

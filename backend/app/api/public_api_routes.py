"""Stable public API v1 routes for third-party integrations."""

from __future__ import annotations

import json
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import DeveloperAPIKey, User
from ..middleware.auth_middleware import get_developer_api_key_required
from ..services.ats_scoring_service import ats_scoring_service
from ..services.developer_key_service import developer_key_service
from ..utils.file_utils import get_job_files, validate_job_id
from ..workers.latex_worker import submit_latex_compilation
from ..workers.llm_worker import submit_resume_optimization
from .job_routes import _write_initial_redis_state

router = APIRouter(prefix="/api/v1", tags=["public-api"])


class V1CompileRequest(BaseModel):
    latex_content: str = Field(..., min_length=1, max_length=500_000)
    compiler: str = Field(default="pdflatex")


class V1OptimizeRequest(BaseModel):
    latex_content: str = Field(..., min_length=1, max_length=500_000)
    job_description: str = Field(..., min_length=1, max_length=20_000)
    optimization_level: str = Field(default="balanced")


class V1ATSRequest(BaseModel):
    latex_content: str = Field(..., min_length=1, max_length=500_000)
    job_description: Optional[str] = Field(default=None, max_length=20_000)
    industry: Optional[str] = None


class V1QueuedResponse(BaseModel):
    job_id: str
    status: str
    poll_url: str
    estimated_seconds: int


class V1ATSResponse(BaseModel):
    score: float
    category_scores: Dict[str, float]
    recommendations: list[str]
    warnings: list[str]
    strengths: list[str]
    industry_key: Optional[str] = None
    industry_label: Optional[str] = None


class V1JobResponse(BaseModel):
    job_id: str
    status: str
    stage: Optional[str] = None
    poll_url: str
    result: Optional[Dict] = None
    error: Optional[str] = None
    pdf_url: Optional[str] = None


async def _get_plan_id(db: AsyncSession, user_id: str) -> str:
    result = await db.execute(select(User.subscription_plan).where(User.id == user_id))
    return result.scalar_one_or_none() or "free"


async def _authorize(
    scope: str,
    api_key: DeveloperAPIKey,
    db: AsyncSession,
) -> str:
    scopes = set(api_key.scopes or [])
    if scope not in scopes:
        raise HTTPException(status_code=403, detail=f"API key lacks '{scope}' scope")

    plan_id = await _get_plan_id(db, api_key.user_id)
    meter = await developer_key_service.consume_rate_limit(api_key.user_id, plan_id)
    if not meter["allowed"]:
        raise HTTPException(
            status_code=429,
            detail=f"Developer API daily limit exceeded ({meter['limit']} requests/day)",
        )

    await developer_key_service.touch_usage(api_key, db)
    return plan_id


async def _assert_job_owner(job_id: str, api_key: DeveloperAPIKey):
    r = await get_redis_client()
    raw = await r.get(f"latexy:job:{job_id}:meta")
    if not raw:
        raise HTTPException(status_code=404, detail="Job not found")
    meta = json.loads(raw)
    if meta.get("user_id") != api_key.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return meta


@router.post("/compile", response_model=V1QueuedResponse)
async def compile_v1(
    body: V1CompileRequest,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
    db: AsyncSession = Depends(get_db),
):
    plan_id = await _authorize("compile", api_key, db)

    compiler = body.compiler or settings.DEFAULT_LATEX_COMPILER
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        raise HTTPException(status_code=400, detail="Unsupported compiler")

    job_id = str(uuid.uuid4())
    estimated_seconds = 20 if plan_id in {"pro", "byok", "team", "student", "pro_annual", "byok_annual"} else 30
    await _write_initial_redis_state(job_id, "latex_compilation", api_key.user_id, estimated_seconds)
    submit_latex_compilation(
        latex_content=body.latex_content,
        job_id=job_id,
        user_id=api_key.user_id,
        user_plan=plan_id,
        metadata={"submitted_via": "developer_api", "developer_key_id": api_key.id},
        compiler=compiler,
    )
    return V1QueuedResponse(
        job_id=job_id,
        status="queued",
        poll_url=f"/api/v1/jobs/{job_id}",
        estimated_seconds=estimated_seconds,
    )


@router.post("/optimize", response_model=V1QueuedResponse)
async def optimize_v1(
    body: V1OptimizeRequest,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
    db: AsyncSession = Depends(get_db),
):
    plan_id = await _authorize("optimize", api_key, db)

    job_id = str(uuid.uuid4())
    estimated_seconds = 60
    await _write_initial_redis_state(job_id, "llm_optimization", api_key.user_id, estimated_seconds)
    submit_resume_optimization(
        latex_content=body.latex_content,
        job_description=body.job_description,
        job_id=job_id,
        user_id=api_key.user_id,
        user_plan=plan_id,
        optimization_level=body.optimization_level,
        metadata={"submitted_via": "developer_api", "developer_key_id": api_key.id},
    )
    return V1QueuedResponse(
        job_id=job_id,
        status="queued",
        poll_url=f"/api/v1/jobs/{job_id}",
        estimated_seconds=estimated_seconds,
    )


@router.post("/ats/score", response_model=V1ATSResponse)
async def ats_score_v1(
    body: V1ATSRequest,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
    db: AsyncSession = Depends(get_db),
):
    await _authorize("ats", api_key, db)
    result = await ats_scoring_service.score_resume(
        latex_content=body.latex_content,
        job_description=body.job_description,
        industry=body.industry,
    )
    return V1ATSResponse(
        score=result.overall_score,
        category_scores=result.category_scores,
        recommendations=result.recommendations,
        warnings=result.warnings,
        strengths=result.strengths,
        industry_key=result.industry_key,
        industry_label=result.industry_label,
    )


@router.get("/jobs/{job_id}", response_model=V1JobResponse)
async def get_job_v1(
    job_id: str,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
):
    validate_job_id(job_id)
    await _assert_job_owner(job_id, api_key)
    r = await get_redis_client()

    state_raw = await r.get(f"latexy:job:{job_id}:state")
    if not state_raw:
        raise HTTPException(status_code=404, detail="Job not found")

    state = json.loads(state_raw)
    result_raw = await r.get(f"latexy:job:{job_id}:result")
    result = json.loads(result_raw) if result_raw else None
    pdf_job_id = result.get("pdf_job_id") if result else None
    pdf_url = f"/api/v1/jobs/{job_id}/pdf" if pdf_job_id and result and result.get("success") else None

    return V1JobResponse(
        job_id=job_id,
        status=state.get("status", "queued"),
        stage=state.get("stage"),
        poll_url=f"/api/v1/jobs/{job_id}",
        result=result if result and result.get("success") else None,
        error=None if not result or result.get("success") else result.get("error"),
        pdf_url=pdf_url,
    )


@router.get("/jobs/{job_id}/pdf")
async def download_job_pdf_v1(
    job_id: str,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
):
    validate_job_id(job_id)
    await _assert_job_owner(job_id, api_key)
    job_dir, pdf_file, _ = get_job_files(job_id)
    del job_dir
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        path=pdf_file,
        media_type="application/pdf",
        filename=f"latexy-{job_id[:8]}.pdf",
    )

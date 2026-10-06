"""Stable public API v1 routes for third-party integrations."""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import DeveloperAPIKey, User
from ..middleware.auth_middleware import get_developer_api_key_required
from ..services.ats_scoring_service import ats_scoring_service
from ..services.developer_key_service import developer_key_service
from ..services.entitlement_service import QuotaTicket, entitlement_service
from ..utils.bounded_io import MAX_COMPILED_PDF_BYTES, BoundedReadError, decode_base64_bounded
from ..utils.file_utils import get_job_files, validate_job_id
from ..workers.latex_worker import submit_latex_compilation
from ..workers.llm_worker import submit_resume_optimization
from .job_routes import (
    _mark_dispatch_accepted,
    _mark_dispatch_started,
    _new_finalization_row,
    _write_initial_redis_state,
)

router = APIRouter(prefix="/api/v1", tags=["public-api"])
logger = get_logger(__name__)


async def _commit_db_changes(db: AsyncSession) -> None:
    """Commit an async session, tolerating sync session adapters.

    Production dependencies provide ``AsyncSession.commit``.  The small
    adapter also keeps the route usable with synchronous session wrappers used
    by operator tooling, without branching on a test-double type.
    """
    result = db.commit()
    if inspect.isawaitable(result):
        await result


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


# The developer API spends exactly the same resources as the first-party routes,
# so it must spend the same plan allowance. The daily developer meter below is an
# anti-burst limiter layered on top of that allowance, never a substitute for it —
# free users can self-issue keys, so treating it as the only limit would put the
# paywall one `POST /developer/keys` away from irrelevant.
_SCOPE_QUOTA_DIMENSIONS = {
    "compile": "compilations",
    "optimize": "optimizations",
}


async def _authorize(
    scope: str,
    api_key: DeveloperAPIKey,
    db: AsyncSession,
    *,
    job_id: Optional[str] = None,
) -> tuple[str, Optional[QuotaTicket]]:
    """Authorise a developer-API call and spend its plan allowance.

    Returns the caller's plan and the quota ticket, so the caller can hand the
    unit back if the dispatch it was charged for never happens. A scope with no
    quota dimension (``ats``) yields a ``None`` ticket.
    """
    scopes = set(api_key.scopes or [])
    if scope not in scopes:
        raise HTTPException(status_code=403, detail=f"API key lacks '{scope}' scope")

    plan_id = await _get_plan_id(db, api_key.user_id)
    meter = await developer_key_service.consume_rate_limit(api_key.user_id, plan_id)
    if not meter["allowed"]:
        if meter.get("unavailable"):
            raise HTTPException(
                status_code=503,
                detail="Rate limiter temporarily unavailable, please retry shortly",
            )
        raise HTTPException(
            status_code=429,
            detail=f"Developer API daily limit exceeded ({meter['limit']} requests/day)",
        )

    dimension = _SCOPE_QUOTA_DIMENSIONS.get(scope)
    ticket = (
        await entitlement_service.enforce_quota(
            dimension, user_id=api_key.user_id, plan=plan_id, job_id=job_id
        )
        if dimension
        else None
    )

    await developer_key_service.touch_usage(api_key, db)
    return plan_id, ticket


async def _assert_job_owner(job_id: str, api_key: DeveloperAPIKey, db: AsyncSession):
    """Check Redis ownership, falling back only to an owned terminal DB row."""
    try:
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:meta")
    except Exception as exc:
        logger.warning("Public job ownership lookup unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Job status temporarily unavailable") from exc
    if raw:
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Malformed public job metadata (%s)", type(exc).__name__)
            meta = None
        if isinstance(meta, dict):
            if meta.get("user_id") != api_key.user_id:
                raise HTTPException(status_code=404, detail="Job not found")
            return meta

    from ..services.job_result_recovery import recover_terminal_job

    if await recover_terminal_job(db, job_id=job_id, user_id=api_key.user_id):
        return {"job_id": job_id, "user_id": api_key.user_id, "recovered": True}
    raise HTTPException(status_code=404, detail="Job not found")


@router.post("/compile", response_model=V1QueuedResponse)
async def compile_v1(
    body: V1CompileRequest,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
    db: AsyncSession = Depends(get_db),
):
    # Validated before _authorize charges the allowance: a rejected compiler must
    # not cost the caller a compilation.
    compiler = body.compiler or settings.DEFAULT_LATEX_COMPILER
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        raise HTTPException(status_code=400, detail="Unsupported compiler")

    job_id = str(uuid.uuid4())
    finalization_record = _new_finalization_row(job_id, "latex_compilation", api_key.user_id, {})
    db.add(finalization_record)
    await _commit_db_changes(db)
    try:
        plan_id, quota_ticket = await _authorize("compile", api_key, db, job_id=job_id)
    except Exception:
        await db.delete(finalization_record)
        await _commit_db_changes(db)
        raise

    try:
        dispatch_attempted = False
        estimated_seconds = 20 if plan_id in {"pro", "byok", "team", "student", "pro_annual", "byok_annual"} else 30
        await _write_initial_redis_state(job_id, "latex_compilation", api_key.user_id, estimated_seconds)
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True
        submit_latex_compilation(
            latex_content=body.latex_content,
            job_id=job_id,
            user_id=api_key.user_id,
            user_plan=plan_id,
            metadata={"submitted_via": "developer_api", "developer_key_id": api_key.id},
            compiler=compiler,
            quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
        )
        await _mark_dispatch_accepted(job_id)
    except BoundedReadError:
        raise HTTPException(status_code=413, detail="Compiled PDF is too large")
    except Exception:
        if dispatch_attempted:
            # The broker may have accepted work even when its client raised.
            # Preserve the lifecycle and let the bounded cleanup fence it.
            return V1QueuedResponse(
                job_id=job_id,
                status="queued",
                poll_url=f"/api/v1/jobs/{job_id}",
                estimated_seconds=estimated_seconds,
            )
        # The job never reached the dispatch intent — give the plan allowance back.
        if quota_ticket is not None:
            await entitlement_service.refund_quota(quota_ticket)
        await db.delete(finalization_record)
        await _commit_db_changes(db)
        raise

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
    job_id = str(uuid.uuid4())
    finalization_record = _new_finalization_row(job_id, "llm_optimization", api_key.user_id, {})
    db.add(finalization_record)
    await _commit_db_changes(db)
    try:
        plan_id, quota_ticket = await _authorize("optimize", api_key, db, job_id=job_id)
    except Exception:
        await db.delete(finalization_record)
        await _commit_db_changes(db)
        raise

    try:
        dispatch_attempted = False
        estimated_seconds = 60
        await _write_initial_redis_state(job_id, "llm_optimization", api_key.user_id, estimated_seconds)
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True
        submit_resume_optimization(
            latex_content=body.latex_content,
            job_description=body.job_description,
            job_id=job_id,
            user_id=api_key.user_id,
            user_plan=plan_id,
            optimization_level=body.optimization_level,
            metadata={"submitted_via": "developer_api", "developer_key_id": api_key.id},
            quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
        )
        await _mark_dispatch_accepted(job_id)
    except Exception:
        if dispatch_attempted:
            return V1QueuedResponse(
                job_id=job_id,
                status="queued",
                poll_url=f"/api/v1/jobs/{job_id}",
                estimated_seconds=estimated_seconds,
            )
        # The job never reached the dispatch intent — give the plan allowance back.
        if quota_ticket is not None:
            await entitlement_service.refund_quota(quota_ticket)
        await db.delete(finalization_record)
        await _commit_db_changes(db)
        raise

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
    # ATS scoring is deterministic and spends no LLM budget, so it has no quota
    # dimension — the developer daily meter inside _authorize is the only limit.
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
    db: AsyncSession = Depends(get_db),
):
    validate_job_id(job_id)
    await _assert_job_owner(job_id, api_key, db)
    try:
        r = await get_redis_client()
    except Exception as exc:
        logger.warning("Public job result lookup unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Job status temporarily unavailable") from exc

    try:
        state_raw = await r.get(f"latexy:job:{job_id}:state")
        result_raw = await r.get(f"latexy:job:{job_id}:result")
    except Exception as exc:
        logger.warning("Public job result read unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Job status temporarily unavailable") from exc
    try:
        state = json.loads(state_raw) if state_raw else None
    except (TypeError, ValueError, json.JSONDecodeError):
        state = None
    try:
        result = json.loads(result_raw) if result_raw else None
    except (TypeError, ValueError, json.JSONDecodeError):
        result = None
    if not isinstance(state, dict):
        state = None
    if not isinstance(result, dict):
        result = None

    from ..services.job_result_recovery import recover_terminal_job

    # Result publication precedes its terminal event/state. A worker can die
    # in that interval while both Redis keys still exist; waiting for eviction
    # would keep a durably finished job looking queued/processing for hours.
    recovery = await recover_terminal_job(db, job_id=job_id, user_id=api_key.user_id)
    if recovery:
        state = {"status": recovery["state"]}
        result = recovery["payload"]
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")

    pdf_available = False
    if recovery is not None:
        # Durable recovery is authoritative. An immutable pointer remains
        # usable after cache eviction; Redis-only jobs still need a live PDF.
        pdf_available = recovery["state"] == "completed" and bool(recovery.get("pdf_path"))
    if not pdf_available and result and result.get("success"):
        pdf_job_id = result.get("pdf_job_id")
        if isinstance(pdf_job_id, str) and pdf_job_id == job_id:
            try:
                pdf_available = bool(await r.exists(f"latexy:job:{pdf_job_id}:pdf"))
            except Exception as exc:
                logger.warning("Public PDF availability lookup unavailable (%s)", type(exc).__name__)
                raise HTTPException(status_code=503, detail="Job status temporarily unavailable") from exc
    pdf_url = f"/api/v1/jobs/{job_id}/pdf" if pdf_available and result and result.get("success") else None

    return V1JobResponse(
        job_id=job_id,
        status=state.get("status", "queued"),
        stage=state.get("stage"),
        poll_url=f"/api/v1/jobs/{job_id}",
        result=result if result and result.get("success") else None,
        error=(
            None if not result or result.get("success")
            else recovery["error"] if recovery else "Job failed"
        ),
        pdf_url=pdf_url,
    )


@router.get("/jobs/{job_id}/pdf")
async def download_job_pdf_v1(
    job_id: str,
    api_key: DeveloperAPIKey = Depends(get_developer_api_key_required),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import Response as _Response

    if "export" not in set(api_key.scopes or []):
        raise HTTPException(status_code=403, detail="API key lacks 'export' scope")

    validate_job_id(job_id)
    await _assert_job_owner(job_id, api_key, db)

    from ..services.job_result_recovery import recover_terminal_job

    recovery = await recover_terminal_job(db, job_id=job_id, user_id=api_key.user_id)
    if recovery is not None:
        if recovery["state"] != "completed":
            raise HTTPException(status_code=404, detail="PDF not found")

    # Primary: Redis cache (works in serverless / multi-container envs).
    try:
        r = await get_redis_client()
        pdf_b64 = await r.get(f"latexy:job:{job_id}:pdf")
        if pdf_b64:
            try:
                content = decode_base64_bounded(pdf_b64, MAX_COMPILED_PDF_BYTES)
            except BoundedReadError as exc:
                raise HTTPException(status_code=413, detail="Compiled PDF is too large") from exc
            return _Response(
                content=content,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="latexy-{job_id[:8]}.pdf"'},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Public PDF Redis lookup unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="PDF temporarily unavailable") from exc

    # A durable completion can outlive both Redis result and PDF cache.  Read
    # only the immutable, user-owned object pointer recorded by the arbiter.
    if recovery and recovery.get("pdf_path"):
        try:
            from ..services.storage_service import StorageObjectTooLarge, download_bytes

            content = download_bytes(recovery["pdf_path"], MAX_COMPILED_PDF_BYTES)
            if content is not None:
                return _Response(
                    content=content,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="latexy-{job_id[:8]}.pdf"'},
                )
        except StorageObjectTooLarge as exc:
            raise HTTPException(status_code=413, detail="Compiled PDF is too large") from exc
        except Exception as exc:
            logger.warning("Durable public PDF lookup failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail="PDF temporarily unavailable") from exc
        raise HTTPException(status_code=404, detail="PDF not found")

    # A terminal completed row without a durable pointer may still have a
    # currently-live Redis PDF (handled above), but must not fall back to an
    # unrelated local file after that cache expires.
    if recovery is not None:
        raise HTTPException(status_code=404, detail="PDF not found")

    # Fallback: local filesystem.
    job_dir, pdf_file, _ = get_job_files(job_id)
    del job_dir
    if not pdf_file.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    if pdf_file.stat().st_size > MAX_COMPILED_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Compiled PDF is too large")
    return FileResponse(
        path=pdf_file,
        media_type="application/pdf",
        filename=f"latexy-{job_id[:8]}.pdf",
    )

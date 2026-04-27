"""
Job management API routes — event-driven rebuild.

Key changes from previous version:
- ConnectionManager class removed (replaced by EventBusManager + ws_routes.py)
- WebSocket endpoint removed (replaced by /ws/jobs in ws_routes.py)
- Job submission now generates job_id upfront and writes initial Redis state
- GET /jobs/{job_id}/state reads from new latexy:job:{job_id}:state key
- GET /jobs/{job_id}/result reads from new latexy:job:{job_id}:result key
- cancel_job uses Redis cancel flag instead of in-process ConnectionManager
- ats_scoring job type wired to ats_worker
- combined job type wired to orchestrator
"""

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import get_redis_client, redis_manager
from ..database.connection import get_db
from ..database.models import Compilation, Resume, User
from ..middleware.auth_middleware import get_current_user_optional, get_current_user_required
from ..services.optimization_personas import VALID_PERSONA_KEYS
from ..workers.ats_worker import submit_ats_scoring
from ..workers.cleanup_worker import submit_expired_jobs_cleanup, submit_temp_files_cleanup
from ..workers.latex_worker import submit_latex_compilation
from ..workers.llm_worker import submit_resume_optimization
from ..workers.orchestrator import submit_optimize_and_compile

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_JOB_TTL = 86400   # 24 hours
_BATCH_TTL = 86400  # 24 hours


# ------------------------------------------------------------------ #
#  Pydantic models                                                     #
# ------------------------------------------------------------------ #

_WATERMARK_RE = re.compile(r"^[A-Za-z0-9 \-\.]+$")
_WATERMARK_MAX_LEN = 30


class WatermarkCompileRequest(BaseModel):
    latex_content: str
    watermark: str
    user_plan: str = "free"
    device_fingerprint: Optional[str] = None
    compiler: Optional[str] = None


class JobSubmissionRequest(BaseModel):
    job_type: str  # "latex_compilation" | "llm_optimization" | "combined" | "ats_scoring"
    latex_content: Optional[str] = None
    job_description: Optional[str] = None
    optimization_level: str = "balanced"
    user_plan: str = "free"
    device_fingerprint: Optional[str] = None
    industry: Optional[str] = None
    target_sections: Optional[List[str]] = None
    custom_instructions: Optional[str] = None
    metadata: Optional[Dict] = None
    model: Optional[str] = None
    compiler: Optional[str] = None  # "pdflatex" | "xelatex" | "lualatex"
    persona: Optional[str] = None


class JobSubmissionResponse(BaseModel):
    success: bool
    job_id: str
    message: str
    estimated_time: Optional[int] = None


class JobStateResponse(BaseModel):
    status: str
    stage: str
    percent: int
    last_updated: float


class JobResultResponse(BaseModel):
    success: bool
    job_id: str
    result: Optional[Dict] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    jobs: List[Dict]
    total_count: int


class BatchJobItem(BaseModel):
    company_name: str = Field(..., max_length=200)
    role_title: str = Field(..., max_length=200)
    job_description: str = Field(..., max_length=20_000)
    job_url: Optional[str] = Field(None, max_length=500)


class BatchTailorRequest(BaseModel):
    resume_id: str
    jobs: List[BatchJobItem] = Field(..., min_length=1, max_length=10)


class BatchTailorResponse(BaseModel):
    batch_id: str
    job_ids: List[str]


class BatchJobStatus(BaseModel):
    job_id: str
    company_name: str
    role_title: str
    status: str
    variant_resume_id: Optional[str] = None


class BatchStatusResponse(BaseModel):
    batch_id: str
    status: str
    jobs: List[BatchJobStatus]


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

async def _write_initial_redis_state(
    job_id: str,
    job_type: str,
    user_id: Optional[str],
    estimated_seconds: int,
) -> None:
    """
    Write the initial job.queued state snapshot + event to Redis.
    This runs in the FastAPI process (async Redis client).
    """
    r = await get_redis_client()

    # State snapshot
    state = {
        "status": "queued",
        "stage": "",
        "percent": 0,
        "last_updated": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:state", _JOB_TTL, json.dumps(state))

    # Job metadata
    meta = {
        "job_id": job_id,
        "user_id": user_id,
        "job_type": job_type,
        "submitted_at": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:meta", _JOB_TTL, json.dumps(meta))

    # job.queued event — persisted to stream + published to Pub/Sub
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

    # Include stream_id so the frontend can track the Redis Stream entry position
    # for accurate XREAD replay on reconnect.
    ws_message = json.dumps({"type": "event", "event": event, "stream_id": entry_id})
    await r.publish(f"latexy:events:{job_id}", ws_message)


# ------------------------------------------------------------------ #
#  Job submission                                                      #
# ------------------------------------------------------------------ #

@router.post("/submit", response_model=JobSubmissionResponse)
async def submit_job(
    request: JobSubmissionRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Submit a new job to the async queue."""
    try:
        ip_address = http_request.client.host if http_request.client else None
        job_id = str(uuid.uuid4())

        estimated_times = {
            "latex_compilation": 30,
            "llm_optimization": 60,
            "combined": 90,
            "ats_scoring": 20,
            "document_conversion": 45,
            "cover_letter_generation": 60,
        }
        estimated_time = estimated_times.get(request.job_type, 60)
        if request.user_plan in ("pro", "byok"):
            estimated_time = int(estimated_time * 0.7)

        # Sanitise caller-supplied metadata: cap at 10 keys, 256 chars per value.
        safe_meta: Dict[str, Any] = {}
        for k, v in (request.metadata or {}).items():
            if len(safe_meta) >= 10:
                break
            safe_meta[str(k)[:64]] = str(v)[:256] if not isinstance(v, (int, float, bool)) else v

        extra_meta = {
            "ip_address": ip_address,
            "submitted_via": "api",
            **safe_meta,
        }

        # Resolve compiler and compile settings: explicit request field > resume metadata > default
        compiler = settings.DEFAULT_LATEX_COMPILER
        compile_settings: Optional[Dict] = None
        if request.compiler:
            if request.compiler not in settings.ALLOWED_LATEX_COMPILERS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported compiler '{request.compiler}'. Allowed: {settings.ALLOWED_LATEX_COMPILERS}",
                )
            compiler = request.compiler
        if safe_meta.get("resume_id") and user_id:
            # Look up resume's stored compiler preference and compile settings
            from sqlalchemy import select as sa_select
            try:
                resume_result = await db.execute(
                    sa_select(Resume.resume_settings).where(
                        Resume.id == safe_meta["resume_id"],
                        Resume.user_id == user_id,
                    )
                )
                resume_meta = resume_result.scalar_one_or_none()
                if isinstance(resume_meta, dict):
                    if not request.compiler:
                        stored_compiler = resume_meta.get("compiler", "")
                        if stored_compiler in settings.ALLOWED_LATEX_COMPILERS:
                            compiler = stored_compiler
                    # Collect compile settings for the worker
                    compile_settings = {
                        k: resume_meta[k]
                        for k in ("main_file", "extra_packages", "latexmk_flags", "texlive_version")
                        if k in resume_meta and resume_meta[k] is not None
                    } or None
            except Exception as exc:
                logger.debug(f"Could not fetch resume compile settings: {exc}")

        if request.job_type == "latex_compilation":
            if not request.latex_content:
                raise HTTPException(
                    status_code=400,
                    detail="latex_content is required for latex_compilation jobs",
                )
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            submit_latex_compilation(
                latex_content=request.latex_content,
                job_id=job_id,
                user_id=user_id,
                user_plan=request.user_plan,
                device_fingerprint=request.device_fingerprint,
                metadata=extra_meta,
                compiler=compiler,
                compile_settings=compile_settings,
            )

        elif request.job_type == "llm_optimization":
            if not request.latex_content:
                raise HTTPException(
                    status_code=400,
                    detail="latex_content is required for llm_optimization jobs",
                )
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            submit_resume_optimization(
                latex_content=request.latex_content,
                job_description=request.job_description,
                job_id=job_id,
                user_id=user_id,
                user_plan=request.user_plan,
                optimization_level=request.optimization_level,
                model=request.model,
                metadata=extra_meta,
            )

        elif request.job_type == "combined":
            if not request.latex_content:
                raise HTTPException(
                    status_code=400,
                    detail="latex_content is required for combined jobs",
                )
            if request.persona and request.persona not in VALID_PERSONA_KEYS:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid persona '{request.persona}'. Valid values: {sorted(VALID_PERSONA_KEYS)}",
                )
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            submit_optimize_and_compile(
                latex_content=request.latex_content,
                job_description=request.job_description,
                job_id=job_id,
                user_id=user_id,
                user_plan=request.user_plan,
                optimization_level=request.optimization_level,
                device_fingerprint=request.device_fingerprint,
                target_sections=request.target_sections,
                custom_instructions=request.custom_instructions,
                model=request.model,
                metadata=extra_meta,
                compiler=compiler,
                persona=request.persona,
            )

        elif request.job_type == "ats_scoring":
            if not request.latex_content:
                raise HTTPException(
                    status_code=400,
                    detail="latex_content is required for ats_scoring jobs",
                )
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            submit_ats_scoring(
                latex_content=request.latex_content,
                job_id=job_id,
                job_description=request.job_description,
                industry=request.industry,
                user_id=user_id,
                user_plan=request.user_plan,
                device_fingerprint=request.device_fingerprint,
                metadata=extra_meta,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported job_type: {request.job_type!r}",
            )

        # Save Compilation record for analytics (non-blocking)
        if user_id and request.job_type in ("latex_compilation", "combined"):
            try:
                resume_id = safe_meta.get("resume_id")
                compilation = Compilation(
                    user_id=user_id,
                    job_id=job_id,
                    status="processing",
                    resume_id=resume_id if resume_id else None,
                    device_fingerprint=request.device_fingerprint,
                )
                db.add(compilation)
                await db.commit()
            except Exception as e:
                logger.warning(f"Failed to create compilation record: {e}")
                await db.rollback()

        return JobSubmissionResponse(
            success=True,
            job_id=job_id,
            message=f"Job queued: {request.job_type}",
            estimated_time=estimated_time,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error submitting job: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Watermarked compile                                                 #
# ------------------------------------------------------------------ #

@router.post("/compile-watermarked", response_model=JobSubmissionResponse)
async def compile_watermarked(
    request: WatermarkCompileRequest,
    http_request: Request,
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """
    Compile LaTeX with a watermark overlay.

    The resulting PDF is a one-off temporary file — it is NOT stored as
    the canonical PDF for the resume and does NOT trigger an auto-save
    checkpoint.  Download via GET /download/{job_id} once the job
    completes.
    """
    # Validate watermark text
    watermark = request.watermark.strip()
    if not watermark or not _WATERMARK_RE.match(watermark) or len(watermark) > _WATERMARK_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Watermark must be 1–{_WATERMARK_MAX_LEN} characters "
                "containing only letters, digits, spaces, hyphens, and dots."
            ),
        )

    if not request.latex_content or not request.latex_content.strip():
        raise HTTPException(status_code=422, detail="latex_content is required")

    compiler = settings.DEFAULT_LATEX_COMPILER
    if request.compiler:
        if request.compiler not in settings.ALLOWED_LATEX_COMPILERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported compiler '{request.compiler}'. Allowed: {settings.ALLOWED_LATEX_COMPILERS}",
            )
        compiler = request.compiler

    try:
        job_id = str(uuid.uuid4())
        ip_address = http_request.client.host if http_request.client else None
        estimated_time = 30 if request.user_plan in ("pro", "byok") else 45

        await _write_initial_redis_state(job_id, "latex_compilation", user_id, estimated_time)

        submit_latex_compilation(
            latex_content=request.latex_content,
            job_id=job_id,
            user_id=user_id,
            user_plan=request.user_plan,
            device_fingerprint=request.device_fingerprint,
            metadata={"ip_address": ip_address, "submitted_via": "watermark"},
            compiler=compiler,
            watermark=watermark,
        )

        return JobSubmissionResponse(
            success=True,
            job_id=job_id,
            message=f"Watermarked compile queued ({watermark!r})",
            estimated_time=estimated_time,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error submitting watermarked compile: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Batch tailor (Feature 75)                                           #
# ------------------------------------------------------------------ #

@router.post("/batch", response_model=BatchTailorResponse, status_code=201)
async def create_batch_tailor(
    body: BatchTailorRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """
    Fork a resume once per job description and submit a combined optimize+compile
    job for each fork.  Returns immediately; clients poll /jobs/batch/{batch_id}.
    """
    from sqlalchemy import select as sa_select

    # Verify resume ownership and fetch caller's subscription plan in one pass
    result = await db.execute(
        sa_select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id)
    )
    parent = result.scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=403, detail="Resume not found or access denied")

    user_result = await db.execute(sa_select(User.subscription_plan).where(User.id == user_id))
    user_plan: str = user_result.scalar_one_or_none() or "free"

    # Phase 1 — create all fork rows and commit before touching Celery/Redis.
    # This ensures no orphaned DB rows if a later Celery/Redis call fails.
    forks: List[tuple] = []  # (fork, item)
    try:
        for item in body.jobs:
            fork = Resume(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=f"{parent.title} — {item.company_name}",
                latex_content=parent.latex_content,
                is_template=False,
                tags=list(parent.tags) if parent.tags else None,
                parent_resume_id=parent.id,
                resume_settings=dict(parent.resume_settings or {}),
            )
            db.add(fork)
            await db.flush()  # get fork.id before commit
            forks.append((fork, item))

        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error(f"Batch tailor DB phase failed: {exc}")
        raise HTTPException(status_code=500, detail="Failed to create batch tailor jobs")

    # Phase 2 — submit Celery jobs (outside DB transaction, forks already committed).
    batch_id = str(uuid.uuid4())
    job_entries: List[Dict] = []
    job_ids: List[str] = []
    estimated_time = 84 if user_plan in ("pro", "byok") else 120  # mirrors submit_job logic

    for fork, item in forks:
        job_id = str(uuid.uuid4())
        await _write_initial_redis_state(job_id, "combined", user_id, estimated_time)
        submit_optimize_and_compile(
            latex_content=fork.latex_content,
            job_description=item.job_description,
            job_id=job_id,
            user_id=user_id,
            user_plan=user_plan,
            optimization_level="aggressive",
            custom_instructions=(
                f"Tailor this resume for the {item.role_title} role at {item.company_name}. "
                "Maximise keyword alignment with the job description. "
                "Keep all factual information accurate."
            ),
            resume_id=str(fork.id),
        )
        job_ids.append(job_id)
        job_entries.append(
            {
                "job_id": job_id,
                "company_name": item.company_name,
                "role_title": item.role_title,
                "variant_resume_id": str(fork.id),
                "job_url": item.job_url,
            }
        )

    # Persist batch metadata in Redis
    r = await get_redis_client()
    batch_meta = {
        "batch_id": batch_id,
        "user_id": user_id,
        "created_at": time.time(),
        "jobs": job_entries,
    }
    await r.setex(f"latexy:batch:{batch_id}", _BATCH_TTL, json.dumps(batch_meta))

    return BatchTailorResponse(batch_id=batch_id, job_ids=job_ids)


@router.get("/batch/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: str,
    user_id: str = Depends(get_current_user_required),
):
    """Return per-job status for a batch and an aggregated batch-level status."""
    r = await get_redis_client()
    raw = await r.get(f"latexy:batch:{batch_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Batch not found")

    meta = json.loads(raw)
    if meta.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    statuses: List[BatchJobStatus] = []
    for entry in meta["jobs"]:
        job_state_raw = await r.get(f"latexy:job:{entry['job_id']}:state")
        if job_state_raw:
            job_state = json.loads(job_state_raw)
            job_status = job_state.get("status", "queued")
        else:
            job_status = "queued"

        statuses.append(
            BatchJobStatus(
                job_id=entry["job_id"],
                company_name=entry["company_name"],
                role_title=entry["role_title"],
                status=job_status,
                variant_resume_id=entry.get("variant_resume_id"),
            )
        )

    # Aggregate batch status.
    # Per-job values: queued | processing | running | completed | failed | cancelled
    all_statuses = {s.status for s in statuses}
    terminal = {"completed", "failed", "cancelled"}
    active = {"processing", "running"}
    if all_statuses <= {"completed"}:
        agg = "completed"
    elif all_statuses <= {"failed", "cancelled"}:
        agg = "failed"
    elif all_statuses <= terminal and "completed" in all_statuses:
        agg = "partial"
    elif all_statuses & active:
        agg = "running"
    else:
        agg = "pending"

    return BatchStatusResponse(batch_id=batch_id, status=agg, jobs=statuses)


# ------------------------------------------------------------------ #
#  Job state & result                                                  #
# ------------------------------------------------------------------ #

@router.get("/{job_id}/state", response_model=JobStateResponse)
async def get_job_state(job_id: str):
    """Get current job state snapshot (for REST polling fallback)."""
    try:
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:state")
        if not raw:
            raise HTTPException(status_code=404, detail="Job not found")
        return json.loads(raw)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error getting state for job {job_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch the final job result (available after job.completed event)."""
    try:
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:result")
        if not raw:
            raise HTTPException(
                status_code=404,
                detail="Job result not available yet or job not found",
            )
        result_data = json.loads(raw)

        # Update Compilation record with final status (non-blocking)
        try:
            from sqlalchemy import update
            final_status = "completed" if result_data.get("success") else "failed"
            compilation_time = result_data.get("compilation_time")
            pdf_size = result_data.get("pdf_size")
            error_msg = result_data.get("error")
            await db.execute(
                update(Compilation)
                .where(Compilation.job_id == job_id)
                .values(
                    status=final_status,
                    compilation_time=compilation_time,
                    pdf_size=pdf_size,
                    error_message=error_msg[:500] if error_msg else None,
                )
            )
            await db.commit()
        except Exception as e:
            logger.debug(f"Compilation record update skipped: {e}")
            await db.rollback()

        return JobResultResponse(
            success=result_data.get("success", False),
            job_id=job_id,
            result=result_data if result_data.get("success") else None,
            error=result_data.get("error") if not result_data.get("success") else None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error getting result for job {job_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Job cancellation                                                    #
# ------------------------------------------------------------------ #

@router.delete("/{job_id}")
async def cancel_job(job_id: str):
    """
    Request cancellation of a running job.

    Sets latexy:job:{job_id}:cancel flag in Redis.  Celery workers poll
    is_cancelled() between stages and stop gracefully.
    """
    try:
        r = await get_redis_client()
        await r.setex(f"latexy:job:{job_id}:cancel", 3600, "1")

        # Publish provisional cancellation event so WebSocket clients
        # get immediate feedback before the worker processes it.
        cancel_event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": time.time(),
            "sequence": 0,
            "type": "job.cancelled",
        }
        await r.publish(
            f"latexy:events:{job_id}",
            json.dumps({"type": "event", "event": cancel_event}),
        )

        return {"success": True, "message": "Cancellation requested"}

    except Exception as exc:
        logger.error(f"Error cancelling job {job_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Job listing                                                         #
# ------------------------------------------------------------------ #

@router.get("/", response_model=JobListResponse)
async def list_jobs(
    user_id: Optional[str] = Depends(get_current_user_optional),
    limit: int = 50,
):
    """
    List recent jobs for the authenticated user (reads from user ZSET).
    Returns an empty list for unauthenticated users.
    """
    if not user_id:
        return JobListResponse(jobs=[], total_count=0)

    try:
        r = await get_redis_client()
        zset_key = f"latexy:user:{user_id}:jobs"
        # Get job IDs ordered by recency (highest score = newest)
        job_ids = await r.zrevrange(zset_key, 0, limit - 1)

        jobs: List[Dict] = []
        for jid in job_ids:
            raw = await r.get(f"latexy:job:{jid}:state")
            if raw:
                state = json.loads(raw)
                state["job_id"] = jid
                jobs.append(state)

        return JobListResponse(jobs=jobs, total_count=len(jobs))

    except Exception as exc:
        logger.error(f"Error listing jobs for user {user_id}: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  System health & cleanup                                             #
# ------------------------------------------------------------------ #

@router.get("/health")
async def jobs_health():
    """Get job system health: queue depths and basic Redis status."""
    try:
        if not redis_manager.redis_client:
            await redis_manager.init_redis()
        redis_health = await redis_manager.health_check()
        return {
            "status": "healthy" if all(redis_health.values()) else "degraded",
            "redis": redis_health,
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.error(f"Health check error: {exc}")
        return {"status": "unhealthy", "error": str(exc), "timestamp": time.time()}


@router.post("/system/cleanup")
async def trigger_cleanup(
    cleanup_type: str = "temp_files",
    max_age_hours: int = 24,
):
    """Trigger a background cleanup task."""
    try:
        if cleanup_type == "temp_files":
            job_id = submit_temp_files_cleanup(max_age_hours=max_age_hours)
        elif cleanup_type == "expired_jobs":
            job_id = submit_expired_jobs_cleanup(max_age_hours=max_age_hours)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported cleanup_type: {cleanup_type!r}",
            )
        return {"success": True, "message": f"Cleanup submitted: {cleanup_type}", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error triggering cleanup: {exc}")
        raise HTTPException(status_code=500, detail="Internal server error")

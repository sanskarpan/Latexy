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
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..core.redis import get_redis_client, redis_manager
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..workers.ats_worker import submit_ats_scoring
from ..workers.cleanup_worker import submit_expired_jobs_cleanup, submit_temp_files_cleanup
from ..workers.latex_worker import submit_latex_compilation
from ..workers.llm_worker import submit_resume_optimization
from ..workers.orchestrator import submit_optimize_and_compile

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_JOB_TTL = 86400  # 24 hours


# ------------------------------------------------------------------ #
#  Pydantic models                                                     #
# ------------------------------------------------------------------ #

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
async def get_job_result(job_id: str):
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

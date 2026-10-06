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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import resolve_plan_family, settings
from ..core.logging import get_logger
from ..core.observability import record_job_submitted
from ..core.redis import get_redis_cache_client, get_redis_client, redis_manager
from ..database.connection import get_db
from ..database.models import Compilation, JobFinalization, Resume, User
from ..middleware.auth_middleware import (
    get_current_user_optional,
    get_current_user_required,
    require_admin,
)
from ..middleware.entitlements import require_feature
from ..services.api_key_service import api_key_service
from ..services.cover_letter_signature_service import (
    InvalidSignatureImage,
    validate_embedded_signature,
)
from ..services.entitlement_service import QuotaTicket, entitlement_service
from ..services.optimization_personas import VALID_PERSONA_KEYS
from ..services.trial_service import trial_service
from ..utils.file_utils import validate_job_id
from ..workers.ats_worker import submit_ats_scoring
from ..workers.cleanup_worker import submit_expired_jobs_cleanup, submit_temp_files_cleanup
from ..workers.finalization_arbiter import FinalizationOutcome, bounded_result_payload
from ..workers.finalization_arbiter import request_cancel as request_cancel_finalization
from ..workers.job_lifecycle import (
    begin_dispatch_async,
    lifecycle_key,
    mark_dispatch_accepted_async,
    request_cancel_async,
)
from ..workers.latex_worker import submit_latex_compilation
from ..workers.llm_worker import submit_resume_optimization
from ..workers.orchestrator import submit_optimize_and_compile
from .job_metadata import parse_ownership_metadata

logger = get_logger(__name__)

# Anonymous, resource-consuming job types that count against the device trial.
_TRIAL_JOB_TYPES = {"latex_compilation", "combined", "llm_optimization"}

# Authenticated counterpart of _TRIAL_JOB_TYPES: which plan allowance a job type
# spends (the reset window per dimension lives in config.PLAN_QUOTAS). Anonymous
# callers are metered by the device trial instead.
_JOB_QUOTA_DIMENSIONS = {
    "latex_compilation": "compilations",
    "auto_fit": "compilations",
    "llm_optimization": "optimizations",
    # A combined run is one user-facing AI action (it also compiles, but we do
    # not double-charge) so it spends a single optimization.
    "combined": "optimizations",
}

_FINALIZATION_JOB_TYPES = frozenset(_JOB_QUOTA_DIMENSIONS)
_LIFECYCLE_JOB_TYPES = _FINALIZATION_JOB_TYPES | {"ats_scoring"}
_FINALIZATION_TTL = timedelta(days=40)


def _uuid_or_none(value: Any) -> Optional[str]:
    """Return only UUID-shaped metadata for FK-backed recovery fields."""
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (TypeError, ValueError, AttributeError):
        return None


def _new_finalization_row(
    job_id: str,
    job_type: str,
    user_id: Optional[str],
    metadata: Dict[str, Any],
    *,
    compilation_id: Optional[str] = None,
    cover_letter_id: Optional[str] = None,
    cover_letter_apply_requested: bool = False,
) -> JobFinalization:
    """Create the pending DB arbiter row before quota consumption/dispatch."""
    resume_id = _uuid_or_none(metadata.get("resume_id"))
    return JobFinalization(
        id=str(uuid.uuid4()),
        job_id=job_id,
        user_id=user_id,
        job_type=job_type,
        compilation_id=compilation_id,
        resume_id=resume_id,
        owner_token=None,
        owner_epoch=0,
        state="pending",
        # Auto-fit's existing auto-save checkpoint is a separate operation;
        # callers must opt into arbiter resume application only when they can
        # provide an expected source hash and the full typed payload.
        resume_apply_requested=False,
        cover_letter_id=cover_letter_id,
        cover_letter_apply_requested=cover_letter_apply_requested,
        lease_expires_at=None,
        expires_at=datetime.now(timezone.utc) + _FINALIZATION_TTL,
    )


async def _delete_quota_refund_receipt(job_id: str) -> None:
    try:
        redis = await get_redis_cache_client()
        await redis.delete(f"latexy:quota-refund-pending:{job_id}")
    except Exception:
        logger.warning("Failed to remove quota refund receipt for job %s", job_id, exc_info=True)


async def _terminalize_undispatched_batch_job(
    db: AsyncSession,
    *,
    job_id: str,
    reason: str = "dispatch_failed",
) -> bool:
    """Commit a proven never-dispatched batch intent before refunding it.

    This path deliberately has no worker owner: ``job_id`` was persisted but
    its broker dispatch call was never attempted.  Locking the durable intent
    and recording a bounded terminal payload first prevents a refund from
    leaving a pending row that recovery could later mistake for live work.
    The ambiguous entry (whose broker call was attempted) is never passed here.
    """
    row = await db.scalar(
        select(JobFinalization)
        .where(JobFinalization.job_id == job_id)
        .with_for_update()
    )
    if row is None:
        return False
    if row.state in {"completed", "failed", "cancelled", "fenced"}:
        return row.state in {"failed", "cancelled", "fenced"}
    row.state = "failed"
    row.terminal_result = "failed"
    row.failure_code = reason[:64]
    row.result_payload = bounded_result_payload(
        job_id,
        {"success": False, "job_id": job_id, "error_code": reason},
    )
    row.decided_at = func.clock_timestamp()
    await db.commit()
    return True


async def _consume_job_quota(
    job_type: str,
    user_id: Optional[str],
    plan: str,
    *,
    job_id: Optional[str] = None,
) -> Optional[QuotaTicket]:
    """Spend one unit of the caller's plan allowance for a paid job type.

    Raises 402 when the allowance is used up. Returns the ticket so the caller
    can refund it if the enqueue itself fails, or None when nothing was charged.
    """
    dimension = _JOB_QUOTA_DIMENSIONS.get(job_type)
    if user_id is None or dimension is None:
        return None
    return await entitlement_service.enforce_quota(
        dimension, user_id=user_id, plan=plan, job_id=job_id
    )


_TRIAL_ERRORS = {
    "trial_limit_exceeded": "Free trial limit reached. Please sign up to continue.",
    "blocked": "Device blocked due to abuse. Please contact support.",
    "daily_limit_exceeded": "Daily request limit exceeded. Please try again tomorrow.",
}


async def _enforce_anonymous_trial(
    db: AsyncSession,
    http_request: Request,
    job_type: str,
    device_fingerprint: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Charge an anonymous, resource-consuming job against the device trial.

    This is the single source of truth for anonymous metering: every route that
    can start a compile or an LLM run without a session must go through it, or
    the 3-use limit is bypassable by picking a different endpoint.
    """
    if job_type not in _TRIAL_JOB_TYPES:
        return
    if not device_fingerprint:
        raise HTTPException(
            status_code=400,
            detail="device_fingerprint is required for anonymous jobs.",
        )
    usage = await trial_service.check_and_track_usage(
        db=db,
        device_fingerprint=device_fingerprint,
        action="optimize" if job_type in {"combined", "llm_optimization"} else "compile",
        ip_address=ip_address,
        user_agent=http_request.headers.get("user-agent"),
        resource_type="resume",
    )
    if usage.get("success"):
        return
    errors = {
        **_TRIAL_ERRORS,
        "cooldown": f"Please wait {int(usage.get('waitTime') or 0)} seconds before trying again.",
    }
    raise HTTPException(
        status_code=429,
        detail=errors.get(usage.get("error", ""), "Trial limit reached."),
    )


async def _resolve_user_plan(db: AsyncSession, user_id: Optional[str]) -> str:
    """Server-derived subscription plan. NEVER trust a client-supplied plan — it
    governs paid queue priority and compile timeout. Anonymous callers are 'free';
    authenticated callers get their real users.subscription_plan."""
    if not user_id:
        return "free"
    from sqlalchemy import select as sa_select

    try:
        row = await db.execute(sa_select(User.subscription_plan).where(User.id == user_id))
        return row.scalar_one_or_none() or "free"
    except Exception:
        return "free"


router = APIRouter(prefix="/jobs", tags=["jobs"])

_JOB_TTL = 86400  # 24 hours
_BATCH_TTL = 86400  # 24 hours
_DISPATCH_MARKER_SUFFIX = ":dispatch-started"
_DISPATCH_MARKER_TTL = 40 * 86400


# ------------------------------------------------------------------ #
#  Pydantic models                                                     #
# ------------------------------------------------------------------ #

_WATERMARK_RE = re.compile(r"^[A-Za-z0-9 \-\.]+$")
_WATERMARK_MAX_LEN = 30


class WatermarkCompileRequest(BaseModel):
    latex_content: str = Field(..., min_length=1, max_length=1_000_000)
    watermark: str = Field(..., min_length=1, max_length=_WATERMARK_MAX_LEN)
    user_plan: str = Field("free", max_length=50)
    device_fingerprint: Optional[str] = Field(None, min_length=1, max_length=255)
    compiler: Optional[str] = Field(None, max_length=20)


class JobSubmissionRequest(BaseModel):
    job_type: str = Field(..., min_length=1, max_length=50)
    latex_content: Optional[str] = Field(None, max_length=1_000_000)
    job_description: Optional[str] = Field(None, max_length=20_000)
    optimization_level: Literal["conservative", "balanced", "aggressive"] = "balanced"
    user_plan: str = Field("free", max_length=50)
    device_fingerprint: Optional[str] = Field(None, min_length=1, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    target_sections: Optional[List[str]] = Field(None, max_length=20)
    custom_instructions: Optional[str] = Field(None, max_length=10_000)
    metadata: Optional[Dict] = Field(None, max_length=20)
    model: Optional[Literal["gpt-4o-mini", "gpt-4o"]] = None
    compiler: Optional[str] = Field(None, max_length=20)
    persona: Optional[str] = Field(None, max_length=100)
    # Guided-intake direction (input-driven optimization, PRD 2026-08-02): the
    # user's explicit answers, threaded into the LLM prompt so the output honours
    # their intent over generic ATS heuristics.
    seniority: Optional[str] = Field(None, max_length=100)
    tone: Optional[str] = Field(None, max_length=100)
    emphasize: Optional[List[str]] = Field(None, max_length=20)
    downplay: Optional[List[str]] = Field(None, max_length=20)
    auto_fit_intensity: Optional[int] = Field(None, ge=0, le=100)

    @field_validator("target_sections", "emphasize", "downplay")
    @classmethod
    def validate_short_text_lists(cls, values: Optional[List[str]]) -> Optional[List[str]]:
        if values is not None and any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("List items must contain 1 to 200 characters")
        return values


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


def _job_result_response_from_recovery(job_id: str, recovered: Dict[str, Any]) -> JobResultResponse:
    """Translate durable recovery while preserving typed delivery errors."""
    result_data = dict(recovered.get("payload") or {})
    recovered_success = recovered.get("state") == "completed" and result_data.get("success") is True
    delivery_error = recovered.get("output_unavailable") is True
    result_data["success"] = recovered_success
    result_data["job_id"] = job_id
    return JobResultResponse(
        success=recovered_success,
        job_id=job_id,
        result=result_data if recovered_success or delivery_error else None,
        error=recovered.get("error"),
    )


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

    @field_validator("resume_id")
    @classmethod
    def validate_resume_id(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("resume_id must be a valid UUID")
        return value


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
    await r.set(f"latexy:job:{job_id}:state", json.dumps(state), ex=_JOB_TTL)

    # Job metadata
    meta = {
        "job_id": job_id,
        "user_id": user_id,
        "job_type": job_type,
        "submitted_at": time.time(),
    }
    await r.set(f"latexy:job:{job_id}:meta", json.dumps(meta), ex=_JOB_TTL)

    # Index the job under the owning user so GET /jobs/ can list it.
    # (Owner-less / anonymous jobs are intentionally not indexed.)
    if user_id:
        user_zset = f"latexy:user:{user_id}:jobs"
        await r.zadd(user_zset, {job_id: time.time()})
        await r.expire(user_zset, _JOB_TTL)

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


async def _delete_initial_redis_state(job_id: str, user_id: Optional[str]) -> None:
    """Best-effort cleanup when a job fails before broker dispatch."""
    try:
        r = await get_redis_client()
        await r.delete(
            f"latexy:job:{job_id}:state",
            f"latexy:job:{job_id}:meta",
            f"latexy:job:{job_id}:seq",
            f"latexy:stream:{job_id}",
            f"latexy:job:{job_id}{_DISPATCH_MARKER_SUFFIX}",
        )
        if user_id:
            await r.zrem(f"latexy:user:{user_id}:jobs", job_id)
    except Exception:
        logger.warning("Failed to clean undispatched job state %s", job_id, exc_info=True)


async def _mark_dispatch_started(job_id: str) -> None:
    """Record that broker/Modal submission is about to be attempted.

    This marker is deliberately written immediately before the external
    dispatch call.  Recovery may refund a queued receipt only when the marker
    is absent, which proves this process died before it attempted submission;
    an accepted-but-not-started worker remains protected from an unsafe refund.
    """
    redis = await get_redis_client()
    # This lifecycle record is the authoritative dispatch fence.  It lives in
    # the same queue Redis as worker events so cleanup and worker entry can
    # resolve their race with one atomic Lua operation.
    if not await begin_dispatch_async(redis, job_id):
        raise RuntimeError(f"Job lifecycle already exists for {job_id}")
    try:
        await redis.set(
            f"latexy:job:{job_id}{_DISPATCH_MARKER_SUFFIX}",
            "1",
            # Keep dispatch evidence at least as long as a quota receipt. Job
            # state/result keys expire after 24h, but a late receipt recovery must
            # never mistake that expiry for proof that an accepted task vanished.
            ex=_DISPATCH_MARKER_TTL,
        )
    except Exception:
        # Lifecycle creation succeeded but the marker did not. No broker call
        # has started yet, so remove the intent and let the caller refund.
        await redis.delete(lifecycle_key(job_id))
        raise


async def _mark_dispatch_accepted(job_id: str) -> bool:
    """Record broker return without treating it as worker ownership."""
    redis = await get_redis_client()
    accepted = await mark_dispatch_accepted_async(redis, job_id)
    if not accepted:
        # A false result means the lifecycle was already terminal/fenced or
        # disappeared.  The caller must enter its ambiguous-dispatch recovery
        # path; it must never claim a successful submission after this point.
        raise RuntimeError(f"Could not acknowledge dispatch for {job_id}")
    return True


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
    # Set once a plan allowance has been charged, so an enqueue failure below can
    # hand the unit back instead of silently billing the user for nothing.
    quota_ticket: Optional[QuotaTicket] = None
    compilation_record: Optional[Compilation] = None
    finalization_record: Optional[JobFinalization] = None
    job_id: Optional[str] = None
    dispatched = False
    dispatch_attempted = False
    try:
        ip_address = http_request.client.host if http_request.client else None
        job_id = str(uuid.uuid4())

        # Plan is server-derived (never trust request.user_plan — it governs paid
        # queue priority + compile timeout).
        resolved_plan = await _resolve_user_plan(db, user_id)
        user_api_key: Optional[str] = None
        if user_id and request.job_type in {"llm_optimization", "combined"}:
            user_api_key = await api_key_service.get_user_provider(db, user_id, "openai")

        # Client model selection is a paid OpenAI feature. Never forward an
        # arbitrary model name to the platform key, and do not send OpenAI model
        # names to an OpenAI-compatible non-OpenAI platform endpoint (for example
        # Gemini); that endpoint must use the operator-configured OPENAI_MODEL.
        paid_model_selection = resolve_plan_family(resolved_plan) in {
            "pro",
            "byok",
            "team",
        }
        safe_model = (
            request.model
            if paid_model_selection and (user_api_key is not None or not settings.OPENAI_BASE_URL)
            else None
        )

        estimated_times = {
            "latex_compilation": 30,
            "auto_fit": 60,
            "llm_optimization": 60,
            "combined": 90,
            "ats_scoring": 20,
            "document_conversion": 45,
            "cover_letter_generation": 60,
        }
        estimated_time = estimated_times.get(request.job_type, 60)
        if resolve_plan_family(resolved_plan) in {"pro", "byok", "team"}:
            estimated_time = int(estimated_time * 0.7)

        # Sanitise caller-supplied metadata: cap at 10 keys, 256 chars per value.
        # Nulls are dropped rather than stringified — str(None) is the truthy
        # 4-char "None", which downstream consumers then treat as a real value
        # (a {"resume_id": null} payload used to reach the Compilation insert as
        # the literal 'None' and fail it with a UUID DataError, silently leaving
        # the row uncreated and therefore breaking share links).
        safe_meta: Dict[str, Any] = {}
        for k, v in (request.metadata or {}).items():
            if len(safe_meta) >= 10:
                break
            if v is None:
                continue
            safe_meta[str(k)[:64]] = str(v)[:256] if not isinstance(v, (int, float, bool)) else v

        extra_meta = {
            "ip_address": ip_address,
            "submitted_via": "api",
            **safe_meta,
        }

        if request.job_type == "auto_fit":
            if not user_id:
                raise HTTPException(status_code=401, detail="Authentication required")
            resume_id = safe_meta.get("resume_id")
            try:
                uuid.UUID(str(resume_id))
            except (TypeError, ValueError, AttributeError):
                raise HTTPException(
                    status_code=422,
                    detail="A valid metadata.resume_id is required for auto-fit",
                ) from None
            from sqlalchemy import select as sa_select

            resume_result = await db.execute(sa_select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id))
            auto_fit_resume = resume_result.scalar_one_or_none()
            if auto_fit_resume is None:
                raise HTTPException(status_code=404, detail="Resume not found")
            if auto_fit_resume.document_type not in (None, "resume"):
                raise HTTPException(
                    status_code=422,
                    detail="Auto-fit is only available for resumes",
                )
            extra_meta["skip_auto_save"] = True
        elif request.auto_fit_intensity is not None:
            raise HTTPException(
                status_code=422,
                detail="auto_fit_intensity is only valid for auto_fit jobs",
            )

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
                        for k in (
                            "main_file",
                            "extra_packages",
                            "latexmk_flags",
                            "texlive_version",
                            "bibtex",
                            "halt_on_error",
                            "draft_mode",
                        )
                        if k in resume_meta and resume_meta[k] is not None
                    } or None
            except Exception:
                logger.debug("Could not fetch resume compile settings", exc_info=True)

        # Validate every condition that can reject the request before charging an
        # anonymous device trial. A missing document, unsupported persona, or bad
        # compiler must not consume one of three uses or start its cooldown.
        if request.job_type in {
            "latex_compilation",
            "llm_optimization",
            "combined",
            "ats_scoring",
            "auto_fit",
        } and (not request.latex_content or not request.latex_content.strip()):
            raise HTTPException(
                status_code=422,
                detail=f"latex_content is required for {request.job_type} jobs",
            )
        if request.latex_content:
            try:
                validate_embedded_signature(request.latex_content)
            except InvalidSignatureImage as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
        if request.job_type == "combined" and request.persona and request.persona not in VALID_PERSONA_KEYS:
            raise HTTPException(
                status_code=422,
                detail=(f"Invalid persona '{request.persona}'. Valid values: {sorted(VALID_PERSONA_KEYS)}"),
            )

        # Server-side trial enforcement for anonymous resource-consuming jobs is
        # the final gate before dispatch. Authenticated users use plan quotas.
        if user_id is None:
            await _enforce_anonymous_trial(
                db,
                http_request,
                request.job_type,
                request.device_fingerprint,
                ip_address,
            )

        # The worker can start as soon as dispatch returns (and Modal executes
        # inline).  Create the durable Compilation row before dispatch so a
        # fast worker cannot reconcile an absent row and then leave a newly
        # inserted row stuck at ``processing`` forever.
        if user_id and request.job_type in ("latex_compilation", "auto_fit", "combined"):
            compilation_record = Compilation(
                user_id=user_id,
                job_id=job_id,
                status="processing",
                resume_id=safe_meta.get("resume_id") or None,
                device_fingerprint=request.device_fingerprint,
            )
            db.add(compilation_record)
            await db.flush()
            if request.job_type in _LIFECYCLE_JOB_TYPES:
                finalization_record = _new_finalization_row(
                    job_id,
                    request.job_type,
                    user_id,
                    safe_meta,
                    compilation_id=compilation_record.id,
                )
                db.add(finalization_record)
            await db.commit()
            # Commit the durable placeholder before quota consumption.  If the
            # process dies after this point, orphan recovery can terminalize a
            # no-receipt row; if consumption succeeds, its receipt is atomic in
            # the cache DB and recovery can refund it.
            quota_ticket = await _consume_job_quota(
                request.job_type, user_id, resolved_plan, job_id=job_id
            )

        # LLM jobs have no Compilation placeholder, but still need a durable
        # arbiter row before consuming the quota receipt.  This closes the
        # process-crash window between consumption and broker dispatch.
        if (
            request.job_type in _LIFECYCLE_JOB_TYPES
            and finalization_record is None
        ):
            finalization_record = _new_finalization_row(
                job_id,
                request.job_type,
                user_id,
                safe_meta,
            )
            db.add(finalization_record)
            await db.commit()

        if request.job_type in {"latex_compilation", "auto_fit"}:
            if compilation_record is None:
                quota_ticket = await _consume_job_quota(request.job_type, user_id, resolved_plan)
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            await _mark_dispatch_started(job_id)
            dispatch_attempted = True
            submit_latex_compilation(
                latex_content=request.latex_content,
                job_id=job_id,
                user_id=user_id,
                user_plan=resolved_plan,
                device_fingerprint=request.device_fingerprint,
                metadata=extra_meta,
                compiler=compiler,
                compile_settings=compile_settings,
                quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
                auto_fit=request.job_type == "auto_fit",
                auto_fit_intensity=request.auto_fit_intensity,
            )

        elif request.job_type == "llm_optimization":
            quota_ticket = await _consume_job_quota(
                request.job_type, user_id, resolved_plan, job_id=job_id
            )
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            await _mark_dispatch_started(job_id)
            dispatch_attempted = True
            submit_resume_optimization(
                latex_content=request.latex_content,
                job_description=request.job_description,
                job_id=job_id,
                user_id=user_id,
                user_plan=resolved_plan,
                optimization_level=request.optimization_level,
                user_api_key=user_api_key,
                model=safe_model,
                metadata=extra_meta,
                quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
            )

        elif request.job_type == "combined":
            if compilation_record is None:
                quota_ticket = await _consume_job_quota(request.job_type, user_id, resolved_plan)
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            await _mark_dispatch_started(job_id)
            dispatch_attempted = True
            submit_optimize_and_compile(
                latex_content=request.latex_content,
                job_description=request.job_description,
                job_id=job_id,
                user_id=user_id,
                user_plan=resolved_plan,
                optimization_level=request.optimization_level,
                device_fingerprint=request.device_fingerprint,
                target_sections=request.target_sections,
                custom_instructions=request.custom_instructions,
                user_api_key=user_api_key,
                model=safe_model,
                metadata=extra_meta,
                compiler=compiler,
                persona=request.persona,
                industry=request.industry,
                seniority=request.seniority,
                tone=request.tone,
                emphasize=request.emphasize,
                downplay=request.downplay,
                compile_settings=compile_settings,
                quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
            )

        elif request.job_type == "ats_scoring":
            await _write_initial_redis_state(job_id, request.job_type, user_id, estimated_time)
            await _mark_dispatch_started(job_id)
            dispatch_attempted = True
            submit_ats_scoring(
                latex_content=request.latex_content,
                job_id=job_id,
                job_description=request.job_description,
                industry=request.industry,
                user_id=user_id,
                user_plan=resolved_plan,
                device_fingerprint=request.device_fingerprint,
                metadata=extra_meta,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported job_type: {request.job_type!r}",
            )

        await _mark_dispatch_accepted(job_id)
        dispatched = True

        record_job_submitted(request.job_type, authenticated=user_id is not None)

        return JobSubmissionResponse(
            success=True,
            job_id=job_id,
            message=f"Job queued: {request.job_type}",
            estimated_time=estimated_time,
        )

    except HTTPException:
        if quota_ticket is not None and not dispatched and not dispatch_attempted:
            await entitlement_service.refund_quota(quota_ticket)
        if compilation_record is not None and not dispatched and not dispatch_attempted:
            try:
                await db.execute(
                    delete(Compilation).where(
                        Compilation.job_id == job_id,
                        Compilation.status == "processing",
                    )
                )
                if finalization_record is not None and job_id is not None:
                    await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        elif finalization_record is not None and not dispatched and not dispatch_attempted:
            try:
                await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        raise
    except Exception:
        if dispatched and job_id is not None:
            # The broker accepted the task. Do not erase its state, refund a
            # charge for work that is running, or make the caller retry into a
            # duplicate merely because post-dispatch bookkeeping failed.
            logger.error("Post-dispatch bookkeeping failed for job %s", job_id, exc_info=True)
            return JobSubmissionResponse(
                success=True,
                job_id=job_id,
                message=f"Job queued: {request.job_type}",
                estimated_time=estimated_time,
            )
        # The job never made it onto the queue — give the plan allowance back.
        if dispatch_attempted:
            # The broker may have accepted work even when its client raised or
            # the response was lost. Preserve the lifecycle/receipt and let
            # cleanup fence an unclaimed job; never refund an ambiguous call.
            logger.error("Ambiguous dispatch for job %s; preserving lifecycle", job_id, exc_info=True)
            return JobSubmissionResponse(
                success=True,
                job_id=job_id,
                message=f"Job queued: {request.job_type}",
                estimated_time=estimated_time,
            )
        if quota_ticket is not None:
            await entitlement_service.refund_quota(quota_ticket)
        if compilation_record is not None:
            try:
                # Only remove a pre-dispatch placeholder.  A worker that
                # already reached a terminal state owns that history row.
                await db.execute(
                    delete(Compilation).where(
                        Compilation.job_id == job_id,
                        Compilation.status == "processing",
                    )
                )
                if finalization_record is not None and job_id is not None:
                    await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        elif finalization_record is not None and job_id is not None:
            try:
                await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        if job_id is not None:
            await _delete_initial_redis_state(job_id, user_id)
        logger.error("Error submitting job", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Watermarked compile                                                 #
# ------------------------------------------------------------------ #


@router.post("/compile-watermarked", response_model=JobSubmissionResponse)
async def compile_watermarked(
    request: WatermarkCompileRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """
    Compile LaTeX with a watermark overlay.

    The resulting PDF is a one-off temporary file — it is NOT stored as
    the canonical PDF for the resume and does NOT trigger an auto-save
    checkpoint.  Download via GET /download/{job_id} once the job
    completes.

    Metered exactly like /jobs/submit's latex_compilation: authenticated callers
    spend a ``compilations`` unit, anonymous callers must pass the device trial.
    It runs the same pdflatex, so leaving it unmetered would make the whole
    compile allowance one endpoint away from being bypassed.
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

    quota_ticket: Optional[QuotaTicket] = None
    finalization_record: Optional[JobFinalization] = None
    job_id: Optional[str] = None
    dispatched = False
    dispatch_attempted = False
    try:
        job_id = str(uuid.uuid4())
        ip_address = http_request.client.host if http_request.client else None
        resolved_plan = await _resolve_user_plan(db, user_id)
        estimated_time = 30 if resolve_plan_family(resolved_plan) in {"pro", "byok", "team"} else 45

        if user_id is None:
            await _enforce_anonymous_trial(
                db, http_request, "latex_compilation", request.device_fingerprint, ip_address
            )

        finalization_record = _new_finalization_row(
            job_id,
            "latex_compilation",
            user_id,
            {},
        )
        db.add(finalization_record)
        await db.commit()
        quota_ticket = await _consume_job_quota(
            "latex_compilation", user_id, resolved_plan, job_id=job_id
        )
        await _write_initial_redis_state(job_id, "latex_compilation", user_id, estimated_time)
        await _mark_dispatch_started(job_id)
        dispatch_attempted = True

        submit_latex_compilation(
            latex_content=request.latex_content,
            job_id=job_id,
            user_id=user_id,
            user_plan=resolved_plan,
            device_fingerprint=request.device_fingerprint,
            metadata={"ip_address": ip_address, "submitted_via": "watermark"},
            compiler=compiler,
            watermark=watermark,
            quota_refund=quota_ticket.refund_payload() if quota_ticket else None,
        )
        await _mark_dispatch_accepted(job_id)
        dispatched = True

        return JobSubmissionResponse(
            success=True,
            job_id=job_id,
            message=f"Watermarked compile queued ({watermark!r})",
            estimated_time=estimated_time,
        )

    except HTTPException:
        if not dispatch_attempted and finalization_record is not None and job_id is not None:
            try:
                await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        raise
    except Exception as exc:
        if dispatched and job_id is not None:
            logger.error(
                "Post-dispatch bookkeeping failed for watermarked job %s",
                job_id,
                extra={"error_type": type(exc).__name__},
            )
            return JobSubmissionResponse(
                success=True,
                job_id=job_id,
                message=f"Watermarked compile queued ({watermark!r})",
                estimated_time=estimated_time,
            )
        if dispatch_attempted:
            logger.error("Ambiguous watermarked dispatch for job %s; preserving lifecycle", job_id, exc_info=True)
            return JobSubmissionResponse(
                success=True,
                job_id=job_id,
                message=f"Watermarked compile queued ({watermark!r})",
                estimated_time=estimated_time,
            )
        # The compile never made it onto the queue — give the allowance back.
        if quota_ticket is not None:
            await entitlement_service.refund_quota(quota_ticket)
        if finalization_record is not None and job_id is not None:
            try:
                await db.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
                await db.commit()
            except Exception:
                await db.rollback()
        if job_id is not None:
            await _delete_initial_redis_state(job_id, user_id)
        logger.error("Error submitting watermarked compile", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Batch tailor (Feature 75)                                           #
# ------------------------------------------------------------------ #


@router.post(
    "/batch",
    response_model=BatchTailorResponse,
    status_code=201,
    dependencies=[Depends(require_feature("batch_tailor"))],
)
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
    result = await db.execute(sa_select(Resume).where(Resume.id == body.resume_id, Resume.user_id == user_id))
    parent = result.scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=403, detail="Resume not found or access denied")

    user_result = await db.execute(sa_select(User.subscription_plan).where(User.id == user_id))
    user_plan: str = user_result.scalar_one_or_none() or "free"

    # One LLM run per job description. Keep one job-scoped ticket per item so
    # each worker carries an independent receipt and a failed/cancelled item can
    # refund exactly one unit. Durable finalization rows are committed before
    # this loop, so a process crash cannot consume a ticket with no recovery
    # identity.
    quota_tickets: Dict[str, QuotaTicket] = {}

    # Pre-assign job IDs before consuming so every quota receipt has a durable
    # recovery identity even if the process dies during DB/fork creation.
    planned_job_ids = [str(uuid.uuid4()) for _ in body.jobs]
    # Phase 1 — create all fork and finalization rows and commit before quota,
    # Celery, or Redis. This makes each charge recoverable by job_id.
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

        for planned_job_id, (fork, _item) in zip(planned_job_ids, forks):
            db.add(
                _new_finalization_row(
                    planned_job_id,
                    "combined",
                    user_id,
                    {"resume_id": str(fork.id)},
                )
            )

        await db.commit()
    except Exception as exc:
        await db.rollback()
        for ticket in quota_tickets.values():
            await entitlement_service.refund_quota(ticket)
        logger.error("Batch tailor DB phase failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Failed to create batch tailor jobs")

    try:
        for job_id in planned_job_ids:
            quota_tickets[job_id] = await entitlement_service.enforce_quota(
                "optimizations", user_id=user_id, plan=user_plan, job_id=job_id
            )
    except Exception as exc:
        for ticket in quota_tickets.values():
            await entitlement_service.refund_quota(ticket)
        try:
            from sqlalchemy import delete as sa_delete

            await db.execute(sa_delete(JobFinalization).where(JobFinalization.job_id.in_(planned_job_ids)))
            await db.execute(sa_delete(Resume).where(Resume.id.in_([str(fork.id) for fork, _ in forks])))
            await db.commit()
        except Exception:
            await db.rollback()
        logger.error("Batch quota phase failed", extra={"error_type": type(exc).__name__})
        raise

    # Phase 2 — pre-assign job IDs and persist batch metadata BEFORE submitting any
    # Celery jobs. If a later submit raises mid-loop, the batch record already lists all
    # planned job_ids so the user can still track/cancel via GET /jobs/batch/{batch_id}
    # instead of ending up with untracked, uncancellable running jobs.
    batch_id = str(uuid.uuid4())
    estimated_time = (
        84 if resolve_plan_family(user_plan) in {"pro", "byok", "team"} else 120
    )  # mirrors submit_job logic

    job_plan: List[tuple] = []  # (job_id, fork, item)
    job_entries: List[Dict] = []
    job_ids: List[str] = []
    for planned_job_id, (fork, item) in zip(planned_job_ids, forks):
        job_id = planned_job_id
        job_plan.append((job_id, fork, item))
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

    # A Redis blip or broker error here means the remaining LLM runs never
    # started, so their share of the up-front charge has to go back before the
    # 500 surfaces. Only the undispatched ones: jobs already handed to the broker
    # are running and will be billed, and refunding those too would hand back
    # optimizations the user is actually consuming.
    dispatched = 0
    pending_state_job_id: Optional[str] = None
    pending_dispatch_attempted = False
    r = None
    try:
        r = await get_redis_client()
        batch_meta = {
            "batch_id": batch_id,
            "user_id": user_id,
            "created_at": time.time(),
            "jobs": job_entries,
        }
        await r.set(f"latexy:batch:{batch_id}", json.dumps(batch_meta), ex=_BATCH_TTL)

        for job_id, fork, item in job_plan:
            pending_state_job_id = job_id
            await _write_initial_redis_state(job_id, "combined", user_id, estimated_time)
            await _mark_dispatch_started(job_id)
            pending_dispatch_attempted = True
            fork_settings = dict(fork.resume_settings or {})
            compile_settings = {
                key: fork_settings[key]
                for key in (
                    "main_file",
                    "extra_packages",
                    "latexmk_flags",
                    "texlive_version",
                    "bibtex",
                    "halt_on_error",
                    "draft_mode",
                )
                if key in fork_settings and fork_settings[key] is not None
            } or None
            stored_compiler = fork_settings.get("compiler")
            compiler = (
                stored_compiler
                if stored_compiler in settings.ALLOWED_LATEX_COMPILERS
                else settings.DEFAULT_LATEX_COMPILER
            )
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
                compiler=compiler,
                compile_settings=compile_settings,
                metadata={
                    "persist_optimized_resume": True,
                    "expected_latex_content": fork.latex_content,
                },
                quota_refund=quota_tickets[job_id].refund_payload(),
            )
            await _mark_dispatch_accepted(job_id)
            dispatched += 1
            pending_state_job_id = None
            pending_dispatch_attempted = False
    except Exception as exc:
        # Do not erase a lifecycle after the dispatch intent was recorded: the
        # broker may have accepted work even if the client raised. Cleanup will
        # fence an unclaimed job after its deadline.
        if pending_state_job_id is not None and not pending_dispatch_attempted:
            await _delete_initial_redis_state(pending_state_job_id, user_id)
        refunded_unstarted = 0
        for entry in job_entries[dispatched:]:
            if pending_dispatch_attempted and entry["job_id"] == pending_state_job_id:
                entry["status"] = "queued"
                continue
            ticket = quota_tickets[entry["job_id"]]
            try:
                terminalized = await _terminalize_undispatched_batch_job(
                    db,
                    job_id=entry["job_id"],
                )
            except Exception as terminal_exc:
                terminalized = False
                await db.rollback()
                logger.error(
                    "Could not terminalize undispatched batch job %s before refund",
                    entry["job_id"],
                    extra={"error_type": type(terminal_exc).__name__},
                )
            if terminalized:
                await entitlement_service.refund_quota(ticket)
                refunded_unstarted += 1
                entry["status"] = "failed"
            else:
                # Keep the receipt and durable intent for recovery when the
                # terminal write itself was unavailable; refunding here would
                # make a pending job indistinguishable from a safe orphan.
                entry["status"] = "queued"
        # Once any task has reached the broker, returning an error invites the
        # caller to retry work that is already running. Keep the accepted batch
        # trackable instead and explicitly mark every undispatched entry failed.
        if dispatched > 0 or pending_dispatch_attempted:
            for entry in job_entries[dispatched:]:
                if entry.get("status") not in {"queued", "failed"}:
                    entry["status"] = "failed"
            if r is not None:
                try:
                    batch_meta["jobs"] = job_entries
                    batch_meta["dispatch_error"] = "Some jobs could not be queued"
                    await r.set(f"latexy:batch:{batch_id}", json.dumps(batch_meta), ex=_BATCH_TTL)
                except Exception as persist_exc:
                    logger.error(
                        "Could not persist partial batch status %s",
                        batch_id,
                        extra={"error_type": type(persist_exc).__name__},
                    )
            logger.error(
                "Batch tailor partially queued %s/%s jobs; refunded %s",
                dispatched,
                len(body.jobs),
                refunded_unstarted,
                extra={"error_type": type(exc).__name__},
            )
            return BatchTailorResponse(batch_id=batch_id, job_ids=job_ids)

        # Nothing was accepted. Remove the batch record and the committed fork
        # rows so a failed request cannot leave empty variants in the account.
        if r is not None:
            try:
                await r.delete(f"latexy:batch:{batch_id}")
            except Exception as cleanup_exc:
                logger.warning(
                    "Could not delete failed batch record %s",
                    batch_id,
                    extra={"error_type": type(cleanup_exc).__name__},
                )
        try:
            from sqlalchemy import delete as sa_delete

            variant_ids = [entry["variant_resume_id"] for entry in job_entries]
            await db.execute(sa_delete(Resume).where(Resume.id.in_(variant_ids)))
            await db.commit()
        except Exception as cleanup_exc:
            await db.rollback()
            logger.error(
                "Could not delete variants for failed batch %s",
                batch_id,
                extra={"error_type": type(cleanup_exc).__name__},
            )
        logger.error(
            "Batch tailor enqueue phase failed after %s/%s dispatched, refunded %s",
            dispatched,
            len(body.jobs),
            refunded_unstarted,
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail="Failed to queue batch tailor jobs")

    return BatchTailorResponse(batch_id=batch_id, job_ids=job_ids)


@router.get("/batch/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Return per-job status for a batch and an aggregated batch-level status."""
    r = await get_redis_client()
    raw = await r.get(f"latexy:batch:{batch_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Batch not found")

    meta = parse_ownership_metadata(raw, batch_id, id_field="batch_id")
    if meta.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    statuses: List[BatchJobStatus] = []
    for entry in meta["jobs"]:
        job_state_raw = await r.get(f"latexy:job:{entry['job_id']}:state")
        if job_state_raw:
            job_state = json.loads(job_state_raw)
            job_status = job_state.get("status", "queued")
        else:
            job_status = entry.get("status", "queued")

        # Redis state can be queued/processing (or expired) after the worker
        # has already committed a terminal arbiter decision.  Recover only
        # the exact authenticated owner and preserve the durable state; never
        # turn missing cache data into a new queued job.
        if job_status in {"queued", "processing", "running"}:
            from ..services.job_result_recovery import recover_terminal_job

            recovered = await recover_terminal_job(
                db,
                job_id=entry["job_id"],
                user_id=user_id,
                expected_type="combined",
            )
            if recovered is not None and recovered.get("state") in {
                "completed",
                "failed",
                "cancelled",
                "fenced",
            }:
                job_status = recovered["state"]
                if job_status == "fenced":
                    job_status = "failed"

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
async def get_job_state(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Get current job state snapshot (for REST polling fallback)."""
    validate_job_id(job_id)
    try:
        r = await get_redis_client()

        # Ownership check — fetch meta first
        meta_raw = await r.get(f"latexy:job:{job_id}:meta")
        if not meta_raw:
            if not user_id:
                raise HTTPException(status_code=404, detail="Job not found")
            from ..services.job_result_recovery import recover_terminal_job

            if await recover_terminal_job(db, job_id=job_id, user_id=user_id) is None:
                raise HTTPException(status_code=404, detail="Job not found")
        if meta_raw:
            meta = parse_ownership_metadata(meta_raw, job_id)
            job_owner = meta.get("user_id")
            if job_owner is not None and job_owner != user_id:
                raise HTTPException(status_code=403, detail="Access denied")

        raw = await r.get(f"latexy:job:{job_id}:state")
        if not raw:
            if not user_id:
                raise HTTPException(status_code=404, detail="Job not found")
            from ..services.job_result_recovery import recover_terminal_job

            recovered = await recover_terminal_job(db, job_id=job_id, user_id=user_id)
            if recovered is None:
                raise HTTPException(status_code=404, detail="Job not found")
            terminal_state = recovered["state"]
            return JobStateResponse(
                status=terminal_state,
                stage="recovered",
                percent=100 if terminal_state == "completed" else 0,
                last_updated=time.time(),
            )
        snapshot = json.loads(raw)
        # A worker may durably commit the DB terminal decision after publishing
        # its result but before refreshing this cached state.  Prefer that
        # owner-authorized decision while Redis still says queued/processing so
        # polling cannot remain stuck until the 24-hour state TTL.
        if user_id and snapshot.get("status") not in {"completed", "failed", "cancelled"}:
            from ..services.job_result_recovery import recover_terminal_job

            recovered = await recover_terminal_job(db, job_id=job_id, user_id=user_id)
            if recovered is not None and recovered.get("state") in {"completed", "failed", "cancelled", "fenced"}:
                terminal_state = recovered["state"]
                return JobStateResponse(
                    status="failed" if terminal_state == "fenced" else terminal_state,
                    stage="recovered",
                    percent=100 if terminal_state == "completed" else 0,
                    last_updated=time.time(),
                )
        return snapshot
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting state for job %s", job_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Fetch the final job result (available after job.completed event)."""
    validate_job_id(job_id)
    try:
        r = await get_redis_client()

        # Ownership check via meta. Meta and result share the same TTL, so a
        # missing meta means the job is gone — deny rather than serve the result
        # without an ownership check (closes a TTL-window IDOR).
        meta_raw = await r.get(f"latexy:job:{job_id}:meta")
        if not meta_raw:
            if not user_id:
                raise HTTPException(status_code=404, detail="Job not found")
            from ..services.job_result_recovery import recover_terminal_job

            if await recover_terminal_job(db, job_id=job_id, user_id=user_id) is None:
                raise HTTPException(status_code=404, detail="Job not found")
        if meta_raw:
            meta = parse_ownership_metadata(meta_raw, job_id)
            job_owner = meta.get("user_id")
            if job_owner is not None and job_owner != user_id:
                raise HTTPException(status_code=403, detail="Access denied")

        # The durable arbiter is authoritative once it has a terminal
        # decision. Consult it even when Redis still contains an older success
        # or processing snapshot, so a canonical failed/cancelled decision is
        # never concealed by stale transport data.
        recovered = None
        if user_id:
            from ..services.job_result_recovery import recover_terminal_job

            recovered = await recover_terminal_job(db, job_id=job_id, user_id=user_id)
        if recovered is not None:
            return _job_result_response_from_recovery(job_id, recovered)

        raw = await r.get(f"latexy:job:{job_id}:result")
        if not raw:
            if not user_id:
                raise HTTPException(status_code=404, detail="Job result not available yet or job not found")
            from ..services.job_result_recovery import recover_terminal_job

            recovered = await recover_terminal_job(db, job_id=job_id, user_id=user_id)
            if recovered is None:
                raise HTTPException(status_code=404, detail="Job result not available yet or job not found")
            return _job_result_response_from_recovery(job_id, recovered)
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
        logger.error("Error getting result for job %s", job_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Redis Stream replay                                                 #
# ------------------------------------------------------------------ #


@router.get("/{job_id}/stream")
async def get_job_stream(
    job_id: str,
    from_id: str = "0",
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """
    Replay all Redis Stream events for a job (HTTP fallback for WebSocket reconnects).

    Returns the ordered list of events stored in latexy:stream:{job_id}.
    Clients that missed events while disconnected can catch up by hitting this
    endpoint and then re-subscribing to the WebSocket.

    Query param:
      from_id — Stream entry ID to start from (default "0" = beginning).
                Pass the last seen stream_id to get only new events.
    """
    validate_job_id(job_id)
    try:
        r = await get_redis_client()

        meta_raw = await r.get(f"latexy:job:{job_id}:meta")
        if not meta_raw:
            raise HTTPException(status_code=404, detail="Job not found")
        meta = parse_ownership_metadata(meta_raw, job_id)
        job_owner = meta.get("user_id")
        if job_owner is not None and job_owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        stream_key = f"latexy:stream:{job_id}"
        # XRANGE min is inclusive. When the caller passes a last-seen stream_id we must
        # use Redis exclusive-interval syntax ("(<id>") so that entry is not re-delivered
        # on each catch-up poll. from_id="0" means "from the beginning" (inclusive).
        range_min = from_id if from_id in ("0", "-") else f"({from_id}"
        # xrange returns [(entry_id, {field: value}), ...]
        entries = await r.xrange(stream_key, min=range_min, max="+")
        events = []
        for entry_id, fields in entries:
            raw_payload = fields.get("payload") or fields.get(b"payload")
            if raw_payload:
                try:
                    evt = json.loads(raw_payload)
                    evt["_stream_id"] = entry_id if isinstance(entry_id, str) else entry_id.decode()
                    events.append(evt)
                except Exception:
                    pass

        return {"job_id": job_id, "events": events, "count": len(events)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error reading stream for job %s", job_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Job cancellation                                                    #
# ------------------------------------------------------------------ #


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """
    Request cancellation of a running job.

    Sets latexy:job:{job_id}:cancel flag in Redis.  Celery workers poll
    is_cancelled() between stages and stop gracefully.
    """
    try:
        r = await get_redis_client()

        # Every submitted job, including anonymous trial jobs, has metadata.
        # Without it we cannot prove that this caller may mutate the job.
        meta_raw = await r.get(f"latexy:job:{job_id}:meta")
        if not meta_raw:
            raise HTTPException(status_code=404, detail="Job not found")
        meta = parse_ownership_metadata(meta_raw, job_id)
        job_owner = meta.get("user_id")
        if job_owner is not None and job_owner != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Linearize cancellation in PostgreSQL before exposing a Redis cancel
        # flag.  A worker that races this lock can no longer commit success and
        # then be refunded by cleanup.  If the arbiter is unavailable, fail
        # closed and leave the accepted job running with its receipt intact.
        try:
            db_cancel = await request_cancel_finalization(session=db, job_id=job_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Durable cancellation failed for %s",
                job_id,
                extra={"error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=503, detail="Cancellation temporarily unavailable") from None
        if db_cancel in {
            FinalizationOutcome.ALREADY_COMPLETED,
            FinalizationOutcome.FAILED,
            FinalizationOutcome.FENCED,
        }:
            terminal_message = (
                "Job already completed"
                if db_cancel is FinalizationOutcome.ALREADY_COMPLETED
                else "Job already reached a terminal state"
            )
            return {"success": True, "message": terminal_message}

        await r.set(f"latexy:job:{job_id}:cancel", "1", ex=3600)
        # Queue-side lifecycle fencing makes cancellation atomic with worker
        # admission. A running owner gets a cancellation request and retains
        # the receipt until it publishes its terminal result; queued work is
        # fenced immediately and cleanup can refund it safely.
        await request_cancel_async(r, job_id)

        # A queued/unmetered worker may never start after the durable
        # cancellation decision.  Materialize the terminal Redis snapshots
        # now so polling/recovery does not leave the job at ``queued`` forever.
        cancel_result = {"success": False, "job_id": job_id, "cancelled": True}
        await r.set(
            f"latexy:job:{job_id}:state",
            json.dumps({"status": "cancelled", "stage": "cancelled", "percent": 100, "last_updated": time.time()}),
            ex=_JOB_TTL,
        )
        await r.set(f"latexy:job:{job_id}:result", json.dumps(cancel_result), ex=_JOB_TTL)

        # Publish provisional cancellation event so WebSocket clients
        # get immediate feedback before the worker processes it.
        # Write to the Redis Stream (for replay) AND publish to Pub/Sub (for live delivery).
        event_id = str(uuid.uuid4())
        seq_key = f"latexy:job:{job_id}:seq"
        seq = await r.incr(seq_key)
        await r.expire(seq_key, _JOB_TTL)

        cancel_event = {
            "event_id": event_id,
            "job_id": job_id,
            "timestamp": time.time(),
            "sequence": seq,
            "type": "job.cancelled",
        }
        payload_json = json.dumps(cancel_event)

        stream_key = f"latexy:stream:{job_id}"
        entry_id = await r.xadd(
            stream_key,
            {
                "payload": payload_json,
                "type": "job.cancelled",
                "sequence": str(seq),
                "event_id": event_id,
            },
            maxlen=10000,
            approximate=True,
        )
        await r.expire(stream_key, _JOB_TTL)

        ws_message = json.dumps({"type": "event", "event": cancel_event, "stream_id": entry_id})
        await r.publish(f"latexy:events:{job_id}", ws_message)

        return {"success": True, "message": "Cancellation requested"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error cancelling job %s", job_id, extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")


# ------------------------------------------------------------------ #
#  Job listing                                                         #
# ------------------------------------------------------------------ #


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    user_id: Optional[str] = Depends(get_current_user_optional),
    limit: int = Query(50, ge=1, le=200),
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
            if isinstance(jid, bytes):
                jid = jid.decode("utf-8")
            meta_raw = await r.get(f"latexy:job:{jid}:meta")
            if not meta_raw:
                continue
            try:
                meta = parse_ownership_metadata(meta_raw, jid)
            except HTTPException:
                # The user index is advisory, not an ownership capability.
                continue
            if meta["user_id"] != user_id:
                continue
            raw = await r.get(f"latexy:job:{jid}:state")
            if raw:
                state = json.loads(raw)
                state["job_id"] = jid
                # Merge job_type/submitted_at from meta so the list UI isn't blank.
                state["job_type"] = meta.get("job_type")
                state["created_at"] = meta.get("submitted_at")
                jobs.append(state)

        return JobListResponse(jobs=jobs, total_count=len(jobs))

    except Exception as exc:
        logger.error("Error listing jobs for user %s", user_id, extra={"error_type": type(exc).__name__})
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
        logger.error("Job health check failed (%s)", type(exc).__name__)
        return {
            "status": "unhealthy",
            "error": "Job infrastructure is unavailable",
            "timestamp": time.time(),
        }


@router.post("/system/cleanup")
async def trigger_cleanup(
    cleanup_type: str = "temp_files",
    max_age_hours: int = 24,
    _admin: str = Depends(require_admin),
):
    """Trigger a background cleanup task (admin only)."""
    try:
        # Clamp to a sane minimum so a caller cannot purge in-flight jobs/temp files
        # with max_age_hours=0.
        max_age_hours = max(int(max_age_hours), 1)
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
        logger.error("Error triggering cleanup", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=500, detail="Internal server error")

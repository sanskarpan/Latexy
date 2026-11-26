"""Admin stuck-job diagnosis and audited retry/cancel/fence remediation.

The diagnosis surface is read-only and built from durable job state: the
``job_finalizations`` lease/finalization arbiter and the ``compilations``
status row. Redis remains the worker admission layer, but it is deliberately
not read here so an unavailable queue cannot blank the operator view. The
mutation paths reuse the same finalization primitives as workers, cancellation
and cleanup; nothing retries or cancels automatically.

Every effective action writes exactly one append-only admin audit row with the
bounded before/after states. Repeating an already-applied action is a no-op
that returns the prior result and never writes a second row.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.log_sanitize import sanitize_for_log
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database import models
from ..database.models import AdminAuditLog
from .admin_audit_service import AdminActor, record_admin_audit

logger = get_logger(__name__)

DEFAULT_MIN_AGE_MINUTES = 15
MAX_MIN_AGE_MINUTES = 7 * 24 * 60
MAX_ITEMS = 200
MAX_SCAN_ITEMS = 800

ACTIVE_COMPILATION_STATUSES = ("queued", "pending", "processing", "running", "retrying")
ACTIVE_FINALIZATION_STATES = ("pending", "committing")
TERMINAL_FINALIZATION_STATES = frozenset({"completed", "failed", "cancelled", "fenced"})
RETRYABLE_JOB_TYPES = frozenset({"latex_compilation", "auto_fit"})

_JOB_TTL = 86400
_DISPATCH_MARKER_TTL = 40 * 86400
_DISPATCH_MARKER_SUFFIX = ":dispatch-started"

_QUEUE_BY_JOB_TYPE = {
    "latex_compilation": "latex",
    "auto_fit": "latex",
    "llm_optimization": "llm",
    "combined": "combined",
    "ats_scoring": "ats",
    "cover_letter_generation": "llm",
    "document_conversion": "llm",
    "github_import": "llm",
}

_STAGE_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:- ")


class StuckJobConflict(Exception):
    """A remediation cannot be applied to the current job state."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    normalized = _as_utc(value)
    if normalized is None:
        return None
    return max(0, int((now - normalized).total_seconds()))


def _human_age(seconds: int | None) -> str:
    if seconds is None:
        return "an unknown period"
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours // 24} day{'s' if hours // 24 != 1 else ''}"


def _stage(value: Any) -> str | None:
    """Keep only a short opaque stage/status token; never a message or error."""
    if not isinstance(value, str):
        return None
    cleaned = "".join(char for char in value if char in _STAGE_ALLOWED).strip()[:64]
    return cleaned or None


_WORKER_PREFIXES = (
    "latex-",
    "llm-",
    "ats-",
    "combined-",
    "orchestrator-",
    "cover-letter-",
    "converter-",
    "github-import-",
    "deep-ats-",
    "cleanup-",
    "job-cleanup-",
    "worker-",
)


def _worker_label(owner_token: Any) -> str | None:
    """Expose a bounded worker name, never a capability token or lease secret.

    Real worker capabilities are ``<task-worker-id>:<random suffix>``. An
    arbitrary single-segment value is not a worker name and must be reduced to
    a stable fingerprint instead of being echoed back.
    """
    if not isinstance(owner_token, str) or not owner_token:
        return None
    candidate = owner_token.split(":", 1)[0] if ":" in owner_token else owner_token
    cleaned = "".join(char for char in candidate if char in _STAGE_ALLOWED).strip()[:80]
    if not cleaned:
        return None
    if ":" in owner_token or cleaned.startswith(_WORKER_PREFIXES):
        return cleaned
    fingerprint = hashlib.sha256(owner_token.encode("utf-8")).hexdigest()[:12]
    return f"worker-{fingerprint}"


def _queue_for(job_type: str | None, *, has_compilation: bool) -> str:
    if job_type and job_type in _QUEUE_BY_JOB_TYPE:
        return _QUEUE_BY_JOB_TYPE[job_type]
    return "latex" if has_compilation else "unknown"


def _owner_user_id(finalization: models.JobFinalization | None, compilation: models.Compilation | None) -> str | None:
    for row in (finalization, compilation):
        value = getattr(row, "user_id", None) if row is not None else None
        if value:
            return str(value)
    return None


def _resume_id(finalization: models.JobFinalization | None, compilation: models.Compilation | None) -> str | None:
    for row in (finalization, compilation):
        value = getattr(row, "resume_id", None) if row is not None else None
        if value:
            return str(value)
    return None


def _job_type(finalization: models.JobFinalization | None, compilation: models.Compilation | None) -> str | None:
    value = getattr(finalization, "job_type", None) if finalization is not None else None
    if value:
        return str(value)
    return "latex_compilation" if compilation is not None else None


def _retry_supported(
    *,
    job_type: str | None,
    owner_user_id: str | None,
    resume_id: str | None,
) -> bool:
    """Only compilation families have durable enough input to be re-dispatched.

    Other families persist output but intentionally never persist prompts or
    job descriptions, so an admin retry cannot reproduce them faithfully. A
    compilation job only needs its saved résumé source, even when its
    ``compilations`` status row was never created.
    """
    return bool(job_type in RETRYABLE_JOB_TYPES and owner_user_id and resume_id)


def _reason_for(
    *,
    finalization: models.JobFinalization | None,
    compilation: models.Compilation | None,
    now: datetime,
) -> tuple[str, str]:
    if finalization is None:
        age = _human_age(_age_seconds(getattr(compilation, "created_at", None), now))
        return (
            "missing_finalization",
            f"No durable finalization row exists for this {age}-old job; worker ownership cannot be verified.",
        )
    if finalization.state in TERMINAL_FINALIZATION_STATES:
        return (
            "stale_compilation_after_terminal",
            f"Job finalization is {finalization.state} but the compilation row never reached a terminal state.",
        )
    lease = _as_utc(finalization.lease_expires_at)
    age = _human_age(_age_seconds(finalization.created_at, now))
    if finalization.cancel_requested:
        return (
            "cancel_requested_not_terminal",
            f"Cancellation was requested {age} ago but finalization is still {finalization.state}.",
        )
    if finalization.state == "committing":
        if lease is None:
            return ("committing_without_lease", f"Finalization has been committing for {age} without a worker lease.")
        return ("committing_lease_expired", f"Finalization has been committing for {age} and its worker lease expired.")
    if not finalization.owner_token:
        return ("queued_unclaimed", f"No worker has claimed this job for {age}.")
    if lease is None:
        return (
            "processing_without_heartbeat",
            f"Worker {_worker_label(finalization.owner_token) or 'unknown'} has no durable heartbeat for {age}.",
        )
    return (
        "processing_lease_expired",
        f"Worker {_worker_label(finalization.owner_token) or 'unknown'} stopped renewing its lease for {age}.",
    )


def _state_snapshot(
    finalization: models.JobFinalization | None,
    compilation: models.Compilation | None,
    *,
    retry_job_id: str | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "state": (
            finalization.state
            if finalization is not None
            else (compilation.status if compilation is not None else None)
        ),
        "finalization_state": finalization.state if finalization is not None else None,
        "compilation_status": compilation.status if compilation is not None else None,
        "cancel_requested": bool(finalization.cancel_requested) if finalization is not None else None,
        "worker": _worker_label(finalization.owner_token) if finalization is not None else None,
        "worker_epoch": int(finalization.owner_epoch) if finalization is not None else None,
        "lease_expires_at": _iso(finalization.lease_expires_at) if finalization is not None else None,
    }
    if retry_job_id is not None:
        snapshot["retry_job_id"] = retry_job_id
    return snapshot


def _serialize_job(
    *,
    job_id: str,
    finalization: models.JobFinalization | None,
    compilation: models.Compilation | None,
    now: datetime,
) -> dict[str, Any] | None:
    created_at = None
    if finalization is not None:
        created_at = finalization.created_at
    if created_at is None and compilation is not None:
        created_at = compilation.created_at
    age = _age_seconds(created_at, now)
    if age is None:
        return None

    job_type = _job_type(finalization, compilation)
    owner_id = _owner_user_id(finalization, compilation)
    resume = _resume_id(finalization, compilation)
    finished = finalization is not None and finalization.state in TERMINAL_FINALIZATION_STATES
    retry_supported = _retry_supported(
        job_type=job_type,
        owner_user_id=owner_id,
        resume_id=resume,
    )
    reason_code, reason = _reason_for(finalization=finalization, compilation=compilation, now=now)
    lease = _as_utc(finalization.lease_expires_at) if finalization is not None else None
    lease_active = bool(lease is not None and lease > now)
    lease_state = (
        "none" if finalization is None else "missing" if lease is None else "active" if lease_active else "expired"
    )
    heartbeat_at = finalization.updated_at if finalization is not None else None
    if heartbeat_at is None:
        heartbeat_at = created_at

    status = (
        compilation.status
        if compilation is not None
        else (finalization.state if finalization is not None else "unknown")
    )
    return {
        "job_id": job_id,
        "job_type": job_type or "unknown",
        "owner": owner_id,
        "owner_user_id": owner_id,
        "owner_kind": "user" if owner_id else "anonymous",
        "resume_id": resume,
        "queue": _queue_for(job_type, has_compilation=compilation is not None),
        "status": status,
        "stage": _stage(finalization.state if finalization is not None else status),
        "finalization_state": finalization.state if finalization is not None else None,
        "compilation_status": compilation.status if compilation is not None else None,
        "created_at": _iso(created_at),
        "updated_at": _iso(heartbeat_at),
        "age": _human_age(age),
        "age_seconds": age,
        "heartbeat_age_seconds": _age_seconds(heartbeat_at, now),
        "lease_expires_at": _iso(lease),
        "lease_expired": (lease is not None and lease <= now) if finalization is not None else None,
        "lease_active": lease_active,
        "lease_state": lease_state,
        "worker": _worker_label(finalization.owner_token) if finalization is not None else None,
        "worker_epoch": int(finalization.owner_epoch) if finalization is not None else None,
        "cancel_requested": bool(finalization.cancel_requested) if finalization is not None else False,
        "reason_code": reason_code,
        "reason": reason,
        "terminal": finished,
        "retry_supported": retry_supported,
        "recommended_actions": []
        if finished
        else (["retry", "cancel", "fence"] if retry_supported else ["cancel", "fence"]),
        "source": (
            "finalization+compilation"
            if finalization is not None and compilation is not None
            else "finalization"
            if finalization is not None
            else "compilation"
        ),
    }


def _is_stuck(
    *,
    finalization: models.JobFinalization | None,
    compilation: models.Compilation | None,
    cutoff: datetime,
    now: datetime,
) -> bool:
    if compilation is not None and compilation.status in {"completed", "failed", "cancelled"}:
        # The user-visible compilation is already terminal; a stale arbiter
        # row must not turn it back into an actionable "stuck" job.
        return False
    if finalization is not None and finalization.state in ACTIVE_FINALIZATION_STATES:
        lease = _as_utc(finalization.lease_expires_at)
        if lease is not None and lease > now:
            return False
        created = _as_utc(finalization.created_at)
        return bool(created is not None and created <= cutoff)
    if compilation is not None and compilation.status in ACTIVE_COMPILATION_STATUSES:
        if finalization is not None:
            lease = _as_utc(finalization.lease_expires_at)
            if finalization.state in ACTIVE_FINALIZATION_STATES and lease is not None and lease > now:
                return False
        created = _as_utc(compilation.created_at)
        return bool(created is not None and created <= cutoff)
    return False


async def list_stuck_jobs(
    db: AsyncSession,
    *,
    min_age_minutes: int = DEFAULT_MIN_AGE_MINUTES,
    limit: int = 50,
    status_filter: str | None = None,
    job_id_filter: str | None = None,
) -> dict[str, Any]:
    """Return bounded per-job stuck diagnosis; never document content or PII."""
    bounded_minutes = max(1, min(int(min_age_minutes), MAX_MIN_AGE_MINUTES))
    bounded_limit = max(1, min(int(limit), MAX_ITEMS))
    scan_limit = min(MAX_SCAN_ITEMS, bounded_limit * 4)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=bounded_minutes)
    bounded_job_id = str(job_id_filter)[:255] if job_id_filter else None

    finalization_query = select(models.JobFinalization).where(
        models.JobFinalization.state.in_(ACTIVE_FINALIZATION_STATES),
        models.JobFinalization.created_at <= cutoff,
    )
    compilation_query = select(models.Compilation).where(
        models.Compilation.status.in_(ACTIVE_COMPILATION_STATUSES),
        models.Compilation.created_at <= cutoff,
    )
    if bounded_job_id:
        finalization_query = finalization_query.where(models.JobFinalization.job_id == bounded_job_id)
        compilation_query = compilation_query.where(models.Compilation.job_id == bounded_job_id)
    active_finalizations = list(
        (await db.execute(finalization_query.order_by(models.JobFinalization.created_at.asc()).limit(scan_limit)))
        .scalars()
        .all()
    )
    active_compilations = list(
        (await db.execute(compilation_query.order_by(models.Compilation.created_at.asc()).limit(scan_limit)))
        .scalars()
        .all()
    )

    job_ids = {row.job_id for row in active_finalizations} | {row.job_id for row in active_compilations}
    if not job_ids:
        return _list_payload(now, bounded_minutes, [], total=0, truncated=False)

    bounded_job_ids = list(job_ids)[: MAX_SCAN_ITEMS * 2]
    final_rows = (
        (await db.execute(select(models.JobFinalization).where(models.JobFinalization.job_id.in_(bounded_job_ids))))
        .scalars()
        .all()
    )
    compilation_rows = (
        (await db.execute(select(models.Compilation).where(models.Compilation.job_id.in_(bounded_job_ids))))
        .scalars()
        .all()
    )
    final_by_job = {row.job_id: row for row in final_rows}
    compilation_by_job = {row.job_id: row for row in compilation_rows}

    items: list[dict[str, Any]] = []
    for job_id in sorted(job_ids):
        finalization = final_by_job.get(job_id)
        compilation = compilation_by_job.get(job_id)
        if not _is_stuck(
            finalization=finalization,
            compilation=compilation,
            cutoff=cutoff,
            now=now,
        ):
            continue
        item = _serialize_job(
            job_id=job_id,
            finalization=finalization,
            compilation=compilation,
            now=now,
        )
        if item is not None:
            items.append(item)

    if status_filter:
        wanted = status_filter.strip().lower()
        if wanted in {"queued", "pending"}:
            items = [item for item in items if item["status"] in {"queued", "pending"}]
        elif wanted in {"processing", "running"}:
            items = [item for item in items if item["status"] in {"processing", "running"}]
        elif wanted != "all":
            items = [item for item in items if item["status"] == wanted or item["reason_code"] == wanted]

    items.sort(key=lambda item: (-int(item["age_seconds"] or 0), item["job_id"]))
    total = len(items)
    page = items[:bounded_limit]
    return _list_payload(
        now,
        bounded_minutes,
        page,
        total=total,
        truncated=total > len(page),
    )


def _list_payload(
    now: datetime,
    min_age_minutes: int,
    items: list[dict[str, Any]],
    *,
    total: int,
    truncated: bool,
) -> dict[str, Any]:
    queued = sum(1 for item in items if item["status"] in {"queued", "pending"})
    processing = sum(1 for item in items if item["status"] in {"processing", "running", "committing"})
    stale = max(0, total - queued - processing)
    oldest = max((int(item["age_seconds"] or 0) for item in items), default=0)
    return {
        "generated_at": now.isoformat(),
        "min_age_minutes": min_age_minutes,
        "stale_after_seconds": min_age_minutes * 60,
        "total": total,
        "truncated": truncated,
        "summary": {
            "total": total,
            "queued": queued,
            "processing": processing,
            "stale": stale,
            "oldest_age_seconds": oldest,
            "retry_supported": sum(1 for item in items if item["retry_supported"]),
        },
        "items": items,
    }


async def _advisory_lock(db: AsyncSession, job_id: str) -> None:
    """Serialize concurrent admin actions for the same job across processes."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:job_key)::bigint)"),
        {"job_key": job_id},
    )


async def _load_job(db: AsyncSession, job_id: str) -> tuple[models.JobFinalization | None, models.Compilation | None]:
    finalization = await db.scalar(
        select(models.JobFinalization).where(models.JobFinalization.job_id == job_id).with_for_update()
    )
    compilation = await db.scalar(
        select(models.Compilation).where(models.Compilation.job_id == job_id).with_for_update()
    )
    return finalization, compilation


async def _find_audit(
    db: AsyncSession,
    *,
    job_id: str,
    actions: Iterable[str],
    idempotency_key: str | None,
) -> AdminAuditLog | None:
    stmt = select(AdminAuditLog).where(
        AdminAuditLog.target_type == "job",
        AdminAuditLog.target_id == job_id,
        AdminAuditLog.action.in_(tuple(actions)),
    )
    if idempotency_key:
        stmt = stmt.where(AdminAuditLog.event_metadata["idempotency_key"].astext == idempotency_key)
    return await db.scalar(stmt.order_by(AdminAuditLog.created_at.desc()).limit(1))


def _audit_response(row: AdminAuditLog, *, action: str, job_id: str) -> dict[str, Any]:
    metadata = row.event_metadata if isinstance(row.event_metadata, dict) else {}
    return {
        "success": True,
        "action": action,
        "job_id": job_id,
        "changed": False,
        "idempotent": True,
        "before": row.before_state,
        "after": row.after_state,
        "reason": row.reason,
        "audit_id": str(row.id),
        "new_job_id": metadata.get("new_job_id"),
        "dispatch_status": metadata.get("dispatch_status"),
    }


def _clean_reason(reason: str | None) -> str:
    cleaned = " ".join((reason or "").split())[:1000]
    if not cleaned:
        raise ValueError("A reason is required for a job action")
    return cleaned


async def _record_action(
    db: AsyncSession,
    *,
    actor: AdminActor,
    request: Any,
    job_id: str,
    action: str,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Any:
    return await record_admin_audit(
        db,
        actor=actor,
        action=f"job.{action}",
        target_type="job",
        target_id=job_id,
        reason=reason,
        before=before,
        after=after,
        metadata=metadata or {},
        request=request,
    )


async def _mark_redis_cancelled(job_id: str) -> bool:
    """Best-effort queue signal after the durable cancellation decision."""
    try:
        from ..workers.job_lifecycle import request_cancel_async

        redis = await get_redis_client()
        await redis.set(f"latexy:job:{job_id}:cancel", "1", ex=3600)
        await request_cancel_async(redis, job_id)
        await redis.set(
            f"latexy:job:{job_id}:state",
            json.dumps(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "percent": 100,
                    "last_updated": time.time(),
                }
            ),
            ex=_JOB_TTL,
        )
        await redis.set(
            f"latexy:job:{job_id}:result",
            json.dumps({"success": False, "job_id": job_id, "cancelled": True}),
            ex=_JOB_TTL,
        )
        event = {
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "timestamp": time.time(),
            "sequence": await redis.incr(f"latexy:job:{job_id}:seq"),
            "type": "job.cancelled",
        }
        await redis.expire(f"latexy:job:{job_id}:seq", _JOB_TTL)
        payload = json.dumps(event)
        entry_id = await redis.xadd(
            f"latexy:stream:{job_id}",
            {
                "payload": payload,
                "type": "job.cancelled",
                "sequence": str(event["sequence"]),
                "event_id": event["event_id"],
            },
            maxlen=10000,
            approximate=True,
        )
        await redis.expire(f"latexy:stream:{job_id}", _JOB_TTL)
        await redis.publish(
            f"latexy:events:{job_id}",
            json.dumps({"type": "event", "event": event, "stream_id": entry_id}),
        )
        return True
    except Exception:
        logger.warning("Admin cancel queue signal failed for %s", sanitize_for_log(job_id))
        return False


async def _mark_redis_fenced(job_id: str) -> bool:
    """Best-effort queue fence after the durable finalization fence."""
    try:
        from ..workers.job_lifecycle import fence_job_async

        redis = await get_redis_client()
        fenced = await fence_job_async(redis, job_id, "admin_fence")
        if not fenced:
            # A live Redis lease still owns presentation. The durable DB fence
            # already prevents any terminal commit; do not overwrite live state.
            return False
        await redis.set(
            f"latexy:job:{job_id}:state",
            json.dumps(
                {
                    "status": "failed",
                    "stage": "admin_fence",
                    "percent": 100,
                    "last_updated": time.time(),
                }
            ),
            ex=_JOB_TTL,
        )
        await redis.set(
            f"latexy:job:{job_id}:result",
            json.dumps(
                {
                    "success": False,
                    "job_id": job_id,
                    "error": "Job was fenced by an administrator.",
                    "error_code": "admin_fence",
                }
            ),
            ex=_JOB_TTL,
        )
        return bool(fenced)
    except Exception:
        logger.warning("Admin fence queue signal failed for %s", sanitize_for_log(job_id))
        return False


async def cancel_stuck_job(
    db: AsyncSession,
    *,
    job_id: str,
    actor: AdminActor,
    reason: str,
    request: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Durably cancel a stuck job through the existing finalization arbiter."""
    cleaned_reason = _clean_reason(reason)
    await _advisory_lock(db, job_id)

    prior = await _find_audit(db, job_id=job_id, actions=("job.cancel",), idempotency_key=idempotency_key)
    if prior is not None:
        prior_response = _audit_response(prior, action="cancel", job_id=job_id)
        await db.rollback()
        return prior_response

    finalization, compilation = await _load_job(db, job_id)
    if finalization is None and compilation is None:
        await db.rollback()
        raise StuckJobConflict("Job not found", status_code=404)
    if finalization is not None and finalization.state in {"completed", "failed", "fenced"}:
        terminal_state = finalization.state
        await db.rollback()
        raise StuckJobConflict(f"Job is already {terminal_state} and cannot be cancelled")

    before = _state_snapshot(finalization, compilation)
    from ..workers.finalization_arbiter import FinalizationOutcome, request_cancel

    outcome = await request_cancel(db, job_id=job_id, reason_code="admin_cancel")
    if outcome is FinalizationOutcome.ALREADY_COMPLETED:
        await db.rollback()
        raise StuckJobConflict("Job is already completed and cannot be cancelled")
    if outcome is FinalizationOutcome.FAILED:
        await db.rollback()
        raise StuckJobConflict("Job is already terminal and cannot be cancelled")

    finalization, compilation = await _load_job(db, job_id)
    after = _state_snapshot(finalization, compilation)
    if after == before and finalization is not None and finalization.state == "cancelled":
        # A previous user cancellation already terminated every durable row.
        await db.rollback()
        return {
            "success": True,
            "action": "cancel",
            "job_id": job_id,
            "changed": False,
            "idempotent": True,
            "before": before,
            "after": after,
            "reason": cleaned_reason,
            "audit_id": None,
            "new_job_id": None,
            "dispatch_status": None,
        }

    metadata: dict[str, Any] = {"job_type": _job_type(finalization, compilation)}
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    row = await _record_action(
        db,
        actor=actor,
        request=request,
        job_id=job_id,
        action="cancel",
        reason=cleaned_reason,
        before=before,
        after=after,
        metadata=metadata,
    )
    await db.commit()
    queue_signal = await _mark_redis_cancelled(job_id)
    return {
        "success": True,
        "action": "cancel",
        "job_id": job_id,
        "changed": True,
        "idempotent": False,
        "before": before,
        "after": after,
        "reason": cleaned_reason,
        "audit_id": str(row.id),
        "new_job_id": None,
        "dispatch_status": "cancelled" if queue_signal else "durable_only",
    }


async def fence_stuck_job(
    db: AsyncSession,
    *,
    job_id: str,
    actor: AdminActor,
    reason: str,
    request: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Durably fence a stale worker and leave a non-revivable tombstone."""
    cleaned_reason = _clean_reason(reason)
    await _advisory_lock(db, job_id)

    prior = await _find_audit(db, job_id=job_id, actions=("job.fence",), idempotency_key=idempotency_key)
    if prior is not None:
        prior_response = _audit_response(prior, action="fence", job_id=job_id)
        await db.rollback()
        return prior_response

    finalization, compilation = await _load_job(db, job_id)
    if finalization is None and compilation is None:
        await db.rollback()
        raise StuckJobConflict("Job not found", status_code=404)
    if finalization is not None and finalization.state in {"completed", "failed", "cancelled"}:
        terminal_state = finalization.state
        await db.rollback()
        raise StuckJobConflict(f"Job is already {terminal_state} and cannot be fenced")
    if compilation is not None and compilation.status in {"completed", "failed", "cancelled"}:
        terminal_state = compilation.status
        await db.rollback()
        raise StuckJobConflict(f"Job is already {terminal_state} and cannot be fenced")

    before = _state_snapshot(finalization, compilation)
    from ..workers.finalization_arbiter import (
        FinalizationOutcome,
        bounded_result_payload,
        fence_finalization,
    )

    outcome = await fence_finalization(db, job_id=job_id, reason_code="admin_fence")
    if outcome is FinalizationOutcome.BUSY:
        await db.rollback()
        raise StuckJobConflict("Job still has a live worker lease; wait for it to expire before fencing")
    if outcome is FinalizationOutcome.ALREADY_COMPLETED:
        await db.rollback()
        raise StuckJobConflict("Job is already completed and cannot be fenced")
    if outcome in {FinalizationOutcome.FAILED, FinalizationOutcome.CANCELLED}:
        await db.rollback()
        raise StuckJobConflict("Job is already terminal and cannot be fenced")

    finalization, compilation = await _load_job(db, job_id)
    if compilation is not None and compilation.status not in {"completed", "failed", "cancelled"}:
        compilation.status = "failed"
        compilation.error_message = "admin_fence"
    if finalization is not None and (
        not isinstance(finalization.result_payload, dict) or not finalization.result_payload.get("error_code")
    ):
        finalization.result_payload = bounded_result_payload(
            job_id,
            {"success": False, "job_id": job_id, "error_code": "admin_fence"},
        )
    after = _state_snapshot(finalization, compilation)
    if after == before:
        await db.rollback()
        return {
            "success": True,
            "action": "fence",
            "job_id": job_id,
            "changed": False,
            "idempotent": True,
            "before": before,
            "after": after,
            "reason": cleaned_reason,
            "audit_id": None,
            "new_job_id": None,
            "dispatch_status": None,
        }

    metadata: dict[str, Any] = {"job_type": _job_type(finalization, compilation)}
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    row = await _record_action(
        db,
        actor=actor,
        request=request,
        job_id=job_id,
        action="fence",
        reason=cleaned_reason,
        before=before,
        after=after,
        metadata=metadata,
    )
    await db.commit()
    queue_signal = await _mark_redis_fenced(job_id)
    return {
        "success": True,
        "action": "fence",
        "job_id": job_id,
        "changed": True,
        "idempotent": False,
        "before": before,
        "after": after,
        "reason": cleaned_reason,
        "audit_id": str(row.id),
        "new_job_id": None,
        "dispatch_status": "fenced" if queue_signal else "durable_only",
    }


async def _dispatch_compile_retry(
    *,
    job_id: str,
    source_job_id: str,
    latex_content: str,
    user_id: str,
    user_plan: str,
    resume_id: str,
    device_fingerprint: str | None,
    compiler: str | None,
    job_type: str,
) -> str:
    """Initialize and dispatch the retry replacement through existing primitives."""
    from ..core.modal_dispatch import submit_async
    from ..services.job_admission_state import initialize_job_state
    from ..workers.job_lifecycle import begin_dispatch_async, mark_dispatch_accepted_async
    from ..workers.latex_worker import submit_latex_compilation

    redis = await get_redis_client()
    await initialize_job_state(
        redis,
        job_id=job_id,
        job_type=job_type,
        user_id=user_id,
        estimated_seconds=30,
        ttl=_JOB_TTL,
    )
    if not await begin_dispatch_async(redis, job_id):
        raise RuntimeError("Retry lifecycle already exists")
    try:
        await redis.set(f"latexy:job:{job_id}{_DISPATCH_MARKER_SUFFIX}", "1", ex=_DISPATCH_MARKER_TTL)
    except Exception:
        await redis.delete(f"latexy:job:{job_id}:lifecycle")
        raise
    try:
        retry_metadata: dict[str, Any] = {
            "submitted_via": "admin_retry",
            "retry_of": source_job_id,
        }
        if job_type == "auto_fit":
            # Never let an operator retry silently overwrite the saved resume;
            # the original auto-fit opt-in is not persisted with the job.
            retry_metadata["skip_auto_save"] = True
        await submit_async(
            submit_latex_compilation,
            latex_content=latex_content,
            job_id=job_id,
            user_id=user_id,
            user_plan=user_plan,
            device_fingerprint=device_fingerprint,
            metadata=retry_metadata,
            resume_id=resume_id,
            compiler=compiler,
            quota_refund=None,
            auto_fit=job_type == "auto_fit",
        )
    except Exception:
        # The broker call is ambiguous. Keep the lifecycle for cleanup recovery;
        # never refund or erase an attempt that may have been accepted.
        logger.warning("Admin retry dispatch was ambiguous for %s", job_id)
        return "ambiguous"
    if not await mark_dispatch_accepted_async(redis, job_id):
        logger.warning("Admin retry dispatch acknowledgement failed for %s", job_id)
        return "ambiguous"
    return "dispatched"


async def _fail_retry_rows(db: AsyncSession, *, job_id: str) -> None:
    """Mark a replacement failed when its local queue admission never started."""
    from ..workers.finalization_arbiter import bounded_result_payload

    finalization = await db.scalar(
        select(models.JobFinalization).where(models.JobFinalization.job_id == job_id).with_for_update()
    )
    compilation = await db.scalar(
        select(models.Compilation).where(models.Compilation.job_id == job_id).with_for_update()
    )
    if finalization is not None and finalization.state == "pending":
        finalization.state = "failed"
        finalization.terminal_result = "failed"
        finalization.failure_code = "retry_dispatch_failed"
        finalization.result_payload = bounded_result_payload(
            job_id,
            {"success": False, "job_id": job_id, "error_code": "retry_dispatch_failed"},
        )
    if compilation is not None and compilation.status not in {"completed", "failed", "cancelled"}:
        compilation.status = "failed"
        compilation.error_message = "retry_dispatch_failed"
    await db.commit()


async def retry_stuck_job(
    db: AsyncSession,
    *,
    job_id: str,
    actor: AdminActor,
    reason: str,
    request: Any = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Fence the stuck original and create one linked replacement job."""
    cleaned_reason = _clean_reason(reason)
    await _advisory_lock(db, job_id)

    prior = await _find_audit(
        db,
        job_id=job_id,
        actions=("job.retry", "job.requeue"),
        idempotency_key=idempotency_key,
    )
    if prior is None and idempotency_key:
        # A retry is single-use per job: a different client key must still
        # return the one existing replacement instead of creating a second.
        prior = await _find_audit(
            db,
            job_id=job_id,
            actions=("job.retry", "job.requeue"),
            idempotency_key=None,
        )
    if prior is not None:
        prior_response = _audit_response(prior, action="retry", job_id=job_id)
        await db.rollback()
        return prior_response

    finalization, compilation = await _load_job(db, job_id)
    if finalization is None and compilation is None:
        await db.rollback()
        raise StuckJobConflict("Job not found", status_code=404)
    if finalization is not None and finalization.state in TERMINAL_FINALIZATION_STATES:
        terminal_state = finalization.state
        await db.rollback()
        raise StuckJobConflict(f"Job is already {terminal_state}; completed and terminal jobs are never retried")
    if compilation is not None and compilation.status in {"completed", "failed", "cancelled"}:
        terminal_state = compilation.status
        await db.rollback()
        raise StuckJobConflict(
            f"Job compilation is already {terminal_state}; completed and terminal jobs are never retried"
        )

    job_type = _job_type(finalization, compilation)
    owner_id = _owner_user_id(finalization, compilation)
    resume_id = _resume_id(finalization, compilation)
    if not _retry_supported(
        job_type=job_type,
        owner_user_id=owner_id,
        resume_id=resume_id,
    ):
        await db.rollback()
        raise StuckJobConflict(
            "This job family does not persist enough input to be re-dispatched safely; cancel or fence it instead",
            status_code=422,
        )

    from ..core.config import settings
    from ..workers.finalization_arbiter import (
        FinalizationOutcome,
        bounded_result_payload,
        fence_finalization,
    )

    resume = await db.scalar(
        select(models.Resume).where(
            models.Resume.id == resume_id,
            models.Resume.user_id == owner_id,
        )
    )
    if resume is None or not (resume.latex_content or "").strip():
        await db.rollback()
        raise StuckJobConflict(
            "The retry source resume is missing or empty; cancel or fence the job instead",
            status_code=422,
        )

    before = _state_snapshot(finalization, compilation)
    outcome = await fence_finalization(db, job_id=job_id, reason_code="admin_retry")
    if outcome is FinalizationOutcome.BUSY:
        await db.rollback()
        raise StuckJobConflict("Job still has a live worker lease; wait for it to expire before retrying")
    if outcome is FinalizationOutcome.ALREADY_COMPLETED:
        await db.rollback()
        raise StuckJobConflict("Job completed before the retry; terminal jobs are never retried")
    if outcome in {FinalizationOutcome.FAILED, FinalizationOutcome.CANCELLED}:
        await db.rollback()
        raise StuckJobConflict("Job is already terminal and is never retried")

    finalization, compilation = await _load_job(db, job_id)
    if compilation is not None and compilation.status not in {"completed", "failed", "cancelled"}:
        compilation.status = "failed"
        compilation.error_message = "admin_retry"
    if finalization is not None and (
        not isinstance(finalization.result_payload, dict) or not finalization.result_payload.get("error_code")
    ):
        finalization.result_payload = bounded_result_payload(
            job_id,
            {"success": False, "job_id": job_id, "error_code": "admin_retry"},
        )

    new_job_id = str(uuid.uuid4())
    plan = (await db.scalar(select(models.User.subscription_plan).where(models.User.id == owner_id))) or "free"
    compiler = compilation.compiler if compilation is not None else None
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        compiler = settings.DEFAULT_LATEX_COMPILER
    device_fingerprint = compilation.device_fingerprint if compilation is not None else None

    new_compilation = models.Compilation(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        resume_id=resume.id,
        job_id=new_job_id,
        status="processing",
        device_fingerprint=device_fingerprint,
        plan_family=compilation.plan_family if compilation is not None else None,
        compiler=compiler,
        template_id=compilation.template_id if compilation is not None else None,
        section_count=compilation.section_count if compilation is not None else None,
    )
    db.add(new_compilation)
    new_finalization = models.JobFinalization(
        id=str(uuid.uuid4()),
        job_id=new_job_id,
        user_id=owner_id,
        job_type=job_type,
        compilation_id=new_compilation.id,
        resume_id=resume.id,
        owner_token=None,
        owner_epoch=0,
        state="pending",
        lease_expires_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=40),
    )
    db.add(new_finalization)

    after = _state_snapshot(finalization, compilation, retry_job_id=new_job_id)
    metadata: dict[str, Any] = {
        "job_type": job_type,
        "queue": _queue_for(job_type, has_compilation=True),
        "new_job_id": new_job_id,
        "retry_of": job_id,
    }
    if idempotency_key:
        metadata["idempotency_key"] = idempotency_key
    row = await _record_action(
        db,
        actor=actor,
        request=request,
        job_id=job_id,
        action="retry",
        reason=cleaned_reason,
        before=before,
        after=after,
        metadata=metadata,
    )
    await db.commit()

    try:
        dispatch_status = await _dispatch_compile_retry(
            job_id=new_job_id,
            source_job_id=job_id,
            latex_content=resume.latex_content,
            user_id=owner_id,
            user_plan=plan,
            resume_id=str(resume.id),
            device_fingerprint=device_fingerprint,
            compiler=compiler,
            job_type=str(job_type),
        )
    except Exception:
        logger.warning("Admin retry queue admission failed for %s", new_job_id)
        dispatch_status = "not_dispatched"
        try:
            await _fail_retry_rows(db, job_id=new_job_id)
        except Exception:
            await db.rollback()
            logger.warning("Admin retry failure reconciliation failed for %s", new_job_id)

    return {
        "success": True,
        "action": "retry",
        "job_id": job_id,
        "changed": True,
        "idempotent": False,
        "before": before,
        "after": after,
        "reason": cleaned_reason,
        "audit_id": str(row.id),
        "new_job_id": new_job_id,
        "dispatch_status": dispatch_status,
    }

"""
Cleanup worker for Phase 8 - File and job cleanup tasks.

State updates (set_job_status / set_job_progress / set_job_result) have been
migrated from asyncio.run(job_status_manager.*()) to the synchronous
publish_event() / publish_job_result() helpers in event_publisher.

The cleanup tasks create synthetic job_ids (cleanup_{task_id},
job_cleanup_{task_id}, health_check_{task_id}) purely for internal progress
tracking.  These ids are NOT user-facing WebSocket channels, so the events
published here will not be consumed by any frontend client.

Read operations also use the synchronous Redis helpers so Celery prefork
workers never reuse async Redis clients across closed event loops.
"""

import asyncio
import json
import math
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import get_sync_redis_cache_client, redis_manager
from ..workers.event_publisher import get_worker_redis, publish_event, publish_job_result
from ..workers.finalization_arbiter import (
    FinalizationOutcome,
    FinalizationState,
    fence_finalization,
    recover_finalization,
)
from ..workers.job_lifecycle import (
    DISPATCH_DEADLINE_SECONDS,
    fence_expired_dispatch_without_lifecycle,
    fence_job,
    fence_orphan_without_lifecycle,
    lifecycle_status,
    recover_completed_lifecycle,
)

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.cleanup_worker.cleanup_temp_files_task")
def cleanup_temp_files_task(
    self,
    max_age_hours: int = 24,
    target_directory: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Clean up temporary files older than specified age.

    Args:
        max_age_hours: Maximum age of files to keep (in hours)
        target_directory: Specific directory to clean (defaults to TEMP_DIR)
        metadata: Additional metadata

    Returns:
        Dict containing cleanup result
    """
    task_id = self.request.id
    job_id = f"cleanup_{task_id}"

    logger.info(f"Starting temp files cleanup task {task_id} for job {job_id}")

    try:
        # Set initial status
        publish_event(job_id, "job.started", {
            "worker_id": f"cleanup-{task_id}",
            "stage": "temp_file_cleanup",
            "task_id": task_id,
            "max_age_hours": max_age_hours,
            "target_directory": target_directory,
            "started_at": time.time(),
        })

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "temp_file_cleanup",
            "message": "Scanning for temporary files",
        })

        # Determine target directory
        cleanup_dir = Path(target_directory) if target_directory else settings.TEMP_DIR

        if not cleanup_dir.exists():
            logger.warning(f"Cleanup directory does not exist: {cleanup_dir}")
            result_data = {
                "success": True,
                "task_id": task_id,
                "job_id": job_id,
                "message": "Cleanup directory does not exist",
                "files_deleted": 0,
                "directories_deleted": 0,
                "space_freed": 0,
                "space_freed_mb": 0.0,
                "max_age_hours": max_age_hours,
                "target_directory": str(cleanup_dir),
                "errors": [],
                "error_count": 0,
                "completed_at": time.time()
            }

            # The result is the terminal authority. Publish it before the
            # completion event so clients never observe completion and then
            # wait for (or miss) the result write.
            publish_job_result(job_id, result_data)
            publish_event(job_id, "job.completed", {
                "ats_score": 0.0,
                "ats_details": {},
                "changes_made": [],
                "compilation_time": 0.0,
                "optimization_time": 0.0,
                "tokens_used": 0,
            })
            return result_data

        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cutoff_timestamp = cutoff_time.timestamp()

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 30,
            "stage": "temp_file_cleanup",
            "message": f"Cleaning files older than {max_age_hours} hours",
        })

        # Scan and clean files
        files_deleted = 0
        directories_deleted = 0
        space_freed = 0
        errors = []

        try:
            # Walk through directory tree
            for item in cleanup_dir.rglob("*"):
                try:
                    # Check if item is old enough to delete
                    if item.stat().st_mtime < cutoff_timestamp:
                        if item.is_file():
                            file_size = item.stat().st_size
                            item.unlink()
                            files_deleted += 1
                            space_freed += file_size
                            logger.debug(f"Deleted file: {item}")
                        elif item.is_dir() and not any(item.iterdir()):
                            # Delete empty directories
                            item.rmdir()
                            directories_deleted += 1
                            logger.debug(f"Deleted empty directory: {item}")
                except Exception as e:
                    logger.error(
                        "Cleanup item deletion failed",
                        extra={"error_type": type(e).__name__},
                    )
                    errors.append("Cleanup item deletion failed")

        except Exception as e:
            logger.error("Error during cleanup scan", extra={"error_type": type(e).__name__})
            errors.append("Cleanup scan failed")

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 80,
            "stage": "temp_file_cleanup",
            "message": f"Cleanup completed: {files_deleted} files deleted",
        })

        # Clean up empty parent directories
        try:
            for item in cleanup_dir.rglob("*"):
                if item.is_dir() and not any(item.iterdir()) and item != cleanup_dir:
                    try:
                        item.rmdir()
                        directories_deleted += 1
                        logger.debug(f"Deleted empty directory: {item}")
                    except Exception as e:
                        logger.debug(
                            "Could not delete cleanup directory",
                            extra={"error_type": type(e).__name__},
                        )
        except Exception as e:
            logger.error("Error cleaning empty directories", extra={"error_type": type(e).__name__})

        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Cleanup completed: {files_deleted} files, {directories_deleted} directories deleted",
            "files_deleted": files_deleted,
            "directories_deleted": directories_deleted,
            "space_freed": space_freed,
            "space_freed_mb": round(space_freed / (1024 * 1024), 2),
            "max_age_hours": max_age_hours,
            "target_directory": str(cleanup_dir),
            "errors": errors,
            "error_count": len(errors),
            "completed_at": time.time()
        }

        # Set final status and result
        publish_job_result(job_id, result_data)
        publish_event(job_id, "job.completed", {
            "ats_score": 0.0,
            "ats_details": {},
            "changes_made": [],
            "compilation_time": 0.0,
            "optimization_time": 0.0,
            "tokens_used": 0,
        })

        logger.info(f"Temp files cleanup task {task_id} completed: {files_deleted} files, {space_freed} bytes freed")
        return result_data

    except Exception as e:
        logger.error(
            "Temp files cleanup task %s failed for job %s",
            task_id,
            job_id,
            extra={"error_type": type(e).__name__},
            exc_info=True,
        )

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": "Cleanup task failed",
            "error": "Cleanup task failed",
            "files_deleted": 0,
            "directories_deleted": 0,
            "space_freed": 0,
            "completed_at": time.time()
        }

        try:
            publish_event(job_id, "job.failed", {
                "stage": "temp_file_cleanup",
                "error_code": "internal",
                "error_message": "Cleanup task failed",
                "retryable": False,
            })
            publish_job_result(job_id, error_data)
        except Exception:
            pass  # best-effort; don't mask the original error

        return error_data


_COMPILATION_PREFIX = "compilations/"
# Only owner-scoped finalization objects are safe for this orphan pass. Older
# or ad-hoc objects under the prefix may have a different ownership contract;
# retaining them is safer than treating a naming convention as proof of
# orphanhood.
_OWNER_SCOPED_COMPILATION_KEY_RE = re.compile(
    r"^compilations/[A-Za-z0-9_-]{1,255}/finalization-[0-9a-f]{32}\.pdf$"
)
# Objects younger than this are never touched, so a compile that is still
# mid-flight (or whose row is committed a moment later) can't be pruned.
_ORPHAN_GRACE_SECONDS = 3600
_ORPHANED_COMPILATION_TIMEOUT_SECONDS = 15 * 60
_DISPATCH_MARKER_SUFFIX = ":dispatch-started"
_RECEIPT_SCAN_TTL = 40 * 86400
_FINALIZATION_DB_UNAVAILABLE = "__db_unavailable__"
_FINALIZATION_EXPIRED = "__expired__"


class _RecoveryTTL(int):
    """Whole-second TTL carrying the DB-read monotonic timestamp."""

    def __new__(cls, seconds: int, read_monotonic: float):
        value = int.__new__(cls, seconds)
        value.read_monotonic = read_monotonic
        return value


def _redis_server_time(redis_client) -> Optional[float]:
    """Return Redis wall-clock time, or ``None`` when the clock is unavailable.

    Cleanup makes refund/fencing decisions from these ages.  Falling back to a
    process clock on a Redis outage is unsafe: a host clock skew can make live
    work appear expired.  Callers therefore fail closed when this returns
    ``None``.
    """
    try:
        seconds, micros = redis_client.time()
        seconds = float(seconds)
        micros = float(micros)
        if not (math.isfinite(seconds) and math.isfinite(micros)):
            return None
        return seconds + micros / 1_000_000
    except Exception:
        # A failed clock read must not make cleanup more aggressive.
        return None


def _load_pending_quota_receipt(cache_client, job_id: str) -> Optional[Dict[str, Any]]:
    """Read and validate the durable receipt without mutating it."""
    raw = cache_client.get(f"latexy:quota-refund-pending:{job_id}")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not raw:
        return None
    try:
        receipt = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Invalid quota receipt for job %s; retaining evidence", job_id)
        return None
    return receipt if isinstance(receipt, dict) else None


def _pending_receipt_age_seconds(cache_client, receipt: Optional[Dict[str, Any]]) -> Optional[float]:
    """Return age only for receipts stamped from Redis' server clock."""
    if not isinstance(receipt, dict) or receipt.get("created_at_clock") != "redis":
        return None
    created_at = receipt.get("created_at")
    if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
        return None
    now = _redis_server_time(cache_client)
    if now is None:
        return None
    age = now - float(created_at)
    return age if math.isfinite(age) else None


def _refund_pending_quota_receipt(
    cache_client,
    job_id: str,
    receipt: Optional[Dict[str, Any]] = None,
) -> bool:
    """Refund one pending receipt, accepting an existing marker as success."""
    from .quota_refund import refund_quota_once

    receipt = receipt or _load_pending_quota_receipt(cache_client, job_id)
    if not receipt:
        return False
    dimension = receipt.get("dimension")
    if dimension not in {"compilations", "optimizations", "ai_assists"}:
        logger.warning("Unsupported quota receipt dimension for job %s", job_id)
        return False
    if refund_quota_once(job_id, receipt, expected_dimension=dimension):
        return True
    # A worker may have completed the atomic refund and died before deleting
    # the receipt.  The marker is durable proof that retrying is unnecessary.
    return bool(cache_client.exists(f"latexy:quota-refund:{dimension}:{job_id}"))


def _terminalize_timeout(job_id: str, *, reason: str = "timeout") -> None:
    """Persist a timeout result and reconcile any durable compile row."""
    result = {
        "success": False,
        "job_id": job_id,
        "error": "Job timed out — worker may have crashed",
        "error_code": reason,
    }
    # fence_job() must have won before this helper is called.  No newer worker
    # can claim a failed lifecycle, so remove artifacts left by the fenced
    # worker while keeping ordinary worker exception cleanup non-destructive.
    try:
        get_worker_redis().delete(
            f"latexy:job:{job_id}:pdf",
            f"latexy:job:{job_id}:synctex",
            f"latexy:job:{job_id}:log",
        )
    except Exception as exc:
        logger.warning(
            "Could not remove timed-out artifacts for %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )
    publish_job_result(job_id, result, force=True)
    publish_event(job_id, "job.failed", {
        "stage": reason,
        "error_code": reason,
        "error_message": result["error"],
        "retryable": False,
    })
    try:
        from .latex_worker import reconcile_compilation_record

        reconcile_compilation_record(job_id, success=False, error_message=reason)
    except Exception as exc:
        logger.warning(
            "Could not reconcile timed-out compilation %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )


def _fence_database_before_timeout(job_id: str, reason: str) -> str:
    """Linearize cleanup timeout against durable output ownership.

    ``fenced`` means the DB arbiter accepted (or already recorded) a terminal
    non-success outcome; ``blocked`` means a live/completed owner won or the
    DB could not be trusted; ``legacy`` means there is no arbiter row. The
    caller may use Redis-only fencing only for the explicit legacy case.
    """

    async def _fence() -> str:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..utils.db_url import normalize_database_url

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                outcome = await fence_finalization(session, job_id=job_id, reason_code=reason)
                row = await recover_finalization(session, job_id=job_id)
                if row is None:
                    return "legacy"
                if outcome in {FinalizationOutcome.BUSY, FinalizationOutcome.ALREADY_COMPLETED}:
                    await session.rollback()
                    return "blocked"
                if outcome in {
                    FinalizationOutcome.FENCED,
                    FinalizationOutcome.FAILED,
                    FinalizationOutcome.CANCELLED,
                }:
                    if (
                        not isinstance(row.result_payload, dict)
                        or not row.result_payload.get("error_code")
                    ):
                        from .finalization_arbiter import bounded_result_payload

                        fallback = dict(row.result_payload) if isinstance(row.result_payload, dict) else {}
                        fallback.update({"success": False, "job_id": job_id, "error_code": reason})
                        if row.state == FinalizationState.CANCELLED.value:
                            fallback["cancelled"] = True
                        row.result_payload = bounded_result_payload(job_id, fallback)
                    await session.commit()
                    return "fenced"
                await session.rollback()
                return "blocked"
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_fence())
    except Exception as exc:
        logger.warning(
            "Could not fence durable finalization before timeout for %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )
        return "blocked"


def _scan_pending_receipt_job_ids(cache_client, count: int = 500) -> list[str]:
    """Find receipts that have no corresponding DB placeholder."""
    try:
        # Keep the Redis SCAN cursor between cleanup passes. A fresh scan with
        # an early break can otherwise revisit the same first 500 live keys
        # forever and starve receipts later in the keyspace.
        cursor_key = "latexy:quota-refund-pending:scan-cursor"
        raw_cursor = cache_client.get(cursor_key)
        cursor = int(raw_cursor or 0)
        cursor, keys = cache_client.scan(cursor, match="latexy:quota-refund-pending:*", count=count)
        if cursor:
            cache_client.set(cursor_key, cursor, ex=_RECEIPT_SCAN_TTL)
        else:
            cache_client.delete(cursor_key)
    except Exception:
        # Older Redis test doubles/clients may expose only scan_iter. This
        # fallback remains bounded, while production clients use the cursor.
        try:
            keys = cache_client.scan_iter(match="latexy:quota-refund-pending:*", count=count)
        except Exception:
            logger.warning("Could not scan pending quota receipts", exc_info=True)
            return []
    prefix = "latexy:quota-refund-pending:"
    job_ids: list[str] = []
    for key in keys:
        if len(job_ids) >= count:
            break
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(key, str) and key.startswith(prefix) and not key.endswith(":scan-cursor"):
            job_ids.append(key[len(prefix):])
    return job_ids


def _reconcile_receipts_without_compilation_rows(redis_client, cache_client) -> int:
    """Refund receipts for jobs that died before a Compilation row existed.

    A receipt with no job state and no dispatch marker is unambiguously a
    pre-dispatch crash.  Terminal failed/cancelled states are also safe to
    refund.  Receipts for queued/processing jobs with a dispatch marker remain
    untouched because work may still be live or waiting in the broker.
    """
    repaired = 0
    for job_id in _scan_pending_receipt_job_ids(cache_client):
        state_key = f"latexy:job:{job_id}:state"
        result_key = f"latexy:job:{job_id}:result"
        marker_key = f"latexy:job:{job_id}{_DISPATCH_MARKER_SUFFIX}"
        try:
            receipt = _load_pending_quota_receipt(cache_client, job_id)
            receipt_age = _pending_receipt_age_seconds(cache_client, receipt)
            # A DB-committed success is authoritative even if Redis result
            # publication or receipt deletion crashed.  Clear only this
            # success evidence; failed DB rows still require the Redis fence
            # below before a refund can be considered safe.
            durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
            if durable_state == _FINALIZATION_DB_UNAVAILABLE:
                # A DB outage is not evidence of a legacy/no-row job. Leave
                # the receipt and all terminal state untouched for recovery.
                continue
            if durable_state == _FINALIZATION_EXPIRED:
                # Expired durable history cannot authorize replay or a legacy
                # refund. Retain the receipt until its own bounded TTL ends.
                continue
            if durable_state == FinalizationState.COMPLETED.value:
                if not _replay_durable_completion(redis_client, job_id, durable_payload, durable_ttl):
                    # Keep the receipt as recovery evidence until both the
                    # canonical result and its completion event are restored.
                    continue
                cache_client.set(f"latexy:quota-terminal:{job_id}", "success", ex=_RECEIPT_SCAN_TTL)
                cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                continue
            if durable_state in {
                FinalizationState.FAILED.value,
                FinalizationState.CANCELLED.value,
                FinalizationState.FENCED.value,
            }:
                terminal_status = (
                    "cancelled"
                    if durable_state == FinalizationState.CANCELLED.value
                    else "failed"
                )
                if not _replay_durable_terminal(
                    redis_client,
                    job_id,
                    durable_payload,
                    terminal_status=terminal_status,
                    ttl=durable_ttl,
                ):
                    continue
                if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                    cache_client.set(
                        f"latexy:quota-terminal:{job_id}", terminal_status, ex=_RECEIPT_SCAN_TTL
                    )
                    cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                    repaired += 1
                continue
            terminal_outcome = cache_client.get(f"latexy:quota-terminal:{job_id}")
            if isinstance(terminal_outcome, bytes):
                terminal_outcome = terminal_outcome.decode("utf-8")
            if terminal_outcome == "success":
                cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                continue
            has_state = bool(redis_client.exists(state_key))
            has_result = bool(redis_client.exists(result_key))
            dispatched = bool(redis_client.exists(marker_key))
            database_fenced = False
            raw_state = redis_client.get(state_key) if has_state else None
            state = json.loads(raw_state) if raw_state else {}
            status = state.get("status")
            raw_result = redis_client.get(result_key) if has_result else None
            result = json.loads(raw_result) if raw_result else {}
            success = result.get("success") is True
            lifecycle = lifecycle_status(redis_client, job_id)
            if lifecycle == "completed":
                # Some workers persist a job-type-specific result key rather
                # than the canonical job result. The lifecycle terminal
                # outcome is authoritative and must clear the receipt.
                if durable_state is not None:
                    # A durable pending/committing row is not success evidence
                    # before its dispatch/lease deadline. Once that deadline
                    # passes, fence in the DB first and replay the resulting
                    # canonical terminal outcome instead of accepting stale
                    # Redis success state.
                    if receipt_age is None or receipt_age < DISPATCH_DEADLINE_SECONDS:
                        continue
                    db_fence = _fence_database_before_timeout(job_id, "dispatch_timeout")
                    if db_fence != "fenced":
                        continue
                    durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
                    if durable_state not in {
                        FinalizationState.FAILED.value,
                        FinalizationState.CANCELLED.value,
                        FinalizationState.FENCED.value,
                    } or not _replay_durable_terminal(
                        redis_client,
                        job_id,
                        durable_payload,
                        terminal_status=(
                            "cancelled"
                            if durable_state == FinalizationState.CANCELLED.value
                            else "failed"
                        ),
                        ttl=durable_ttl,
                    ):
                        continue
                    if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                        cache_client.set(
                            f"latexy:quota-terminal:{job_id}", "failed", ex=_RECEIPT_SCAN_TTL
                        )
                        cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                    continue
                if durable_payload and not _replay_durable_completion(
                    redis_client, job_id, durable_payload, durable_ttl
                ):
                    continue
                cache_client.set(f"latexy:quota-terminal:{job_id}", "success", ex=_RECEIPT_SCAN_TTL)
                cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                continue
            if lifecycle is not None:
                # Redis state/result snapshots are advisory and may be a stale
                # failure event from an expired owner.  Only an atomic
                # lifecycle terminal outcome authorizes refund for lifecycle-
                # tracked jobs; otherwise fence first after the deadline.
                terminal_failure = lifecycle in {"failed", "cancelled"}
            else:
                terminal_failure = status in {"failed", "cancelled"} or (
                    has_result and result.get("success") is False
                )
            # Metadata alone is also safe: _write_initial_redis_state writes
            # state first, and the dispatch marker is written only immediately
            # before the broker call.
            pre_dispatch = not dispatched and not has_state and not has_result
            if success and durable_state is None:
                # A successful worker should normally delete this itself, but
                # cleanup is safe to perform after observing the terminal result.
                cache_client.set(f"latexy:quota-terminal:{job_id}", "success", ex=_RECEIPT_SCAN_TTL)
                cache_client.delete(f"latexy:quota-refund-pending:{job_id}")
                continue
            created_at = receipt_created_at = None
            if receipt:
                receipt_created_at = receipt.get("created_at")
                # Only receipts stamped by the producer's Redis TIME clock can
                # be aged against this cache's Redis TIME. Legacy receipts
                # without provenance remain bounded evidence rather than being
                # expired using an unproven host-clock origin.
                if receipt_age is not None:
                    created_at = receipt_age
            # A process can be between the atomic quota consume and its first
            # Redis state write.  Require the receipt's conservative orphan
            # grace before refunding that no-state case; old receipts without a
            # timestamp are retained for manual/legacy recovery.
            aged_pre_dispatch = bool(
                pre_dispatch and created_at is not None and created_at >= _ORPHANED_COMPILATION_TIMEOUT_SECONDS
            )
            if lifecycle is None and aged_pre_dispatch:
                db_fence = _fence_database_before_timeout(job_id, "dispatch_timeout")
                if db_fence not in {"legacy", "fenced"}:
                    continue
                if db_fence == "fenced":
                    durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
                    if durable_state not in {
                        FinalizationState.FAILED.value,
                        FinalizationState.CANCELLED.value,
                        FinalizationState.FENCED.value,
                    } or not _replay_durable_terminal(
                        redis_client,
                        job_id,
                        durable_payload,
                        terminal_status=(
                            "cancelled"
                            if durable_state == FinalizationState.CANCELLED.value
                            else "failed"
                        ),
                        ttl=durable_ttl,
                    ):
                        continue
                    if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                        repaired += 1
                    continue
                database_fenced = db_fence == "fenced"
                if fence_orphan_without_lifecycle(redis_client, job_id):
                    lifecycle = "failed"
                    terminal_failure = True
                else:
                    continue
            if terminal_failure:
                # A Redis failure snapshot is advisory. For lifecycle-backed
                # jobs, first linearize the durable arbiter decision; only a
                # committed failed/cancelled/fenced row authorizes refund.
                if lifecycle is not None and not database_fenced and durable_state not in {
                    FinalizationState.FAILED.value,
                    FinalizationState.CANCELLED.value,
                    FinalizationState.FENCED.value,
                }:
                    db_fence = _fence_database_before_timeout(job_id, "terminal_failure")
                    if db_fence not in {"legacy", "fenced"}:
                        continue
                    if db_fence == "fenced":
                        durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
                        if durable_state not in {
                            FinalizationState.FAILED.value,
                            FinalizationState.CANCELLED.value,
                            FinalizationState.FENCED.value,
                        } or not _replay_durable_terminal(
                            redis_client,
                            job_id,
                            durable_payload,
                            terminal_status=(
                                "cancelled"
                                if durable_state == FinalizationState.CANCELLED.value
                                else "failed"
                            ),
                            ttl=durable_ttl,
                        ):
                            continue
                if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                    repaired += 1
                continue
            # Dispatching/queued work with no worker owner can be fenced after
            # a bounded deadline. This covers a crash after the marker but
            # before the broker call, while a live worker's lease blocks the
            # fence and therefore blocks a refund.
            dispatch_expired = bool(
                lifecycle in {"dispatching", "queued"}
                and receipt_created_at is not None
                and created_at is not None
                and created_at >= DISPATCH_DEADLINE_SECONDS
            )
            marker_expired_without_lifecycle = bool(
                dispatched
                and lifecycle is None
                and receipt_created_at is not None
                and created_at is not None
                and created_at >= DISPATCH_DEADLINE_SECONDS
            )
            if marker_expired_without_lifecycle:
                # The marker proves that a broker call was attempted, but a
                # missing lifecycle means no guarded worker can own it.  Create
                # an atomic tombstone before refunding so a delayed delivery
                # is rejected at worker admission rather than running free.
                db_fence = _fence_database_before_timeout(job_id, "dispatch_timeout")
                if db_fence not in {"legacy", "fenced"}:
                    continue
                if db_fence == "fenced":
                    durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
                    if durable_state not in {
                        FinalizationState.FAILED.value,
                        FinalizationState.CANCELLED.value,
                        FinalizationState.FENCED.value,
                    } or not _replay_durable_terminal(
                        redis_client,
                        job_id,
                        durable_payload,
                        terminal_status=(
                            "cancelled"
                            if durable_state == FinalizationState.CANCELLED.value
                            else "failed"
                        ),
                        ttl=durable_ttl,
                    ):
                        continue
                    if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                        repaired += 1
                    continue
                if not fence_expired_dispatch_without_lifecycle(redis_client, job_id):
                    continue
                _terminalize_timeout(job_id, reason="dispatch_timeout")
                if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                    repaired += 1
                continue
            if aged_pre_dispatch or dispatch_expired:
                db_fence = _fence_database_before_timeout(job_id, "dispatch_timeout")
                if db_fence not in {"legacy", "fenced"}:
                    continue
                if db_fence == "fenced":
                    durable_state, durable_payload, durable_ttl = _read_finalization_outcome(job_id)
                    if durable_state not in {
                        FinalizationState.FAILED.value,
                        FinalizationState.CANCELLED.value,
                        FinalizationState.FENCED.value,
                    } or not _replay_durable_terminal(
                        redis_client,
                        job_id,
                        durable_payload,
                        terminal_status=(
                            "cancelled"
                            if durable_state == FinalizationState.CANCELLED.value
                            else "failed"
                        ),
                        ttl=durable_ttl,
                    ):
                        continue
                    if _refund_pending_quota_receipt(cache_client, job_id, receipt):
                        repaired += 1
                    continue
                if not fence_job(redis_client, job_id, "dispatch_timeout"):
                    continue
                _terminalize_timeout(job_id, reason="dispatch_timeout")
                refunded = _refund_pending_quota_receipt(cache_client, job_id, receipt)
                if refunded:
                    repaired += 1
        except Exception:
            logger.warning("Could not reconcile quota receipt for job %s", job_id, exc_info=True)
    return repaired


def _read_finalization_outcome(
    job_id: str,
) -> tuple[Optional[str], Optional[dict[str, Any]], Optional[int]]:
    """Read one durable arbiter outcome/payload with a worker-owned DB loop."""

    async def _read() -> tuple[Optional[str], Optional[dict[str, Any]], Optional[int]]:
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..database.models import JobFinalization
        from ..utils.db_url import normalize_database_url, resolve_database_url

        db_url = resolve_database_url()
        if not db_url:
            return _FINALIZATION_DB_UNAVAILABLE, None, None
        engine = create_async_engine(normalize_database_url(db_url), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                # Read the retention state and remaining TTL from the same DB
                # clock statement.  A local worker clock must never extend a
                # recovery payload beyond its server-side expiry deadline.
                remaining_ttl = func.extract(
                    "epoch", JobFinalization.expires_at - func.clock_timestamp()
                ).label("remaining_ttl")
                result = await session.execute(
                    select(JobFinalization, remaining_ttl)
                    .where(
                        JobFinalization.job_id == job_id
                    )
                )
                record = result.one_or_none()
                read_monotonic = time.monotonic()
                if record is None:
                    return None, None, None
                row, remaining = record
                try:
                    remaining_seconds = float(remaining)
                except (TypeError, ValueError):
                    return _FINALIZATION_DB_UNAVAILABLE, None, None
                if not math.isfinite(remaining_seconds):
                    return _FINALIZATION_DB_UNAVAILABLE, None, None
                if remaining_seconds < 1:
                    return _FINALIZATION_EXPIRED, None, None
                remaining_ttl = math.floor(remaining_seconds)
                return (
                    row.state,
                    row.result_payload if isinstance(row.result_payload, dict) else None,
                    _RecoveryTTL(remaining_ttl, read_monotonic),
                )
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_read())
    except Exception as exc:
        logger.warning(
            "Could not read durable finalization outcome for %s",
            job_id,
            extra={"error_type": type(exc).__name__},
        )
        return _FINALIZATION_DB_UNAVAILABLE, None, None


def _read_finalization_state(job_id: str) -> Optional[str]:
    state, _payload, _ttl = _read_finalization_outcome(job_id)
    return state


def _normalize_recovery_ttl(ttl: Optional[float]) -> Optional[int]:
    """Return a finite, conservative whole-second recovery TTL."""
    if isinstance(ttl, bool) or ttl is None:
        return None
    try:
        seconds = float(ttl)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(ttl, _RecoveryTTL):
        seconds -= max(0.0, time.monotonic() - ttl.read_monotonic)
    if not math.isfinite(seconds):
        return None
    whole_seconds = math.floor(seconds)
    return whole_seconds if whole_seconds >= 1 else None


def _replay_durable_completion(
    redis_client,
    job_id: str,
    payload: Optional[dict[str, Any]],
    ttl: Optional[int],
) -> bool:
    """Restore canonical Redis result/event from a committed DB completion."""
    if not isinstance(payload, dict):
        return False
    from .event_publisher import publish_job_result

    result = dict(payload)
    result["job_id"] = job_id
    result["success"] = True
    recovery_ttl = ttl
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        return False
    from .job_lifecycle import lifecycle_key

    if not recover_completed_lifecycle(redis_client, job_id):
        return False

    # recover_completed_lifecycle uses a conservative default TTL. Tighten it
    # to the DB row's remaining retention so replay cannot resurrect history.
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        # The DB retention deadline elapsed while Redis recovery ran. Remove
        # the provisional default-TTL lifecycle rather than resurrecting it.
        redis_client.delete(lifecycle_key(job_id))
        return False
    if not redis_client.expire(lifecycle_key(job_id), ttl):
        return False
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        return False
    if not publish_job_result(job_id, result, ttl=ttl, force=True):
        return False
    event_payload = {
        "stage": "recovered",
        "percent": 100,
        "ats_score": result.get("ats_score"),
        "ats_details": result.get("ats_details") or {},
        "changes_made": result.get("changes_made") or [],
        "compilation_time": result.get("compilation_time") or 0.0,
        "optimization_time": result.get("optimization_time") or 0.0,
        "tokens_used": result.get("tokens_used") or 0,
    }
    # Only compilation results have a PDF job identifier.  Supplying the
    # parent job ID for custom/GitHub/ATS completions misrepresents an
    # unavailable artifact to clients.
    if result.get("pdf_job_id"):
        event_payload["pdf_job_id"] = result["pdf_job_id"]
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        return False
    event_id = publish_event(job_id, "job.completed", event_payload, ttl=ttl)
    return bool(event_id)


def _recover_durable_terminal_lifecycle(
    redis_client,
    job_id: str,
    terminal_status: str,
    ttl: int,
) -> bool:
    """Replace a live Redis snapshot with a DB-authoritative terminal state."""
    ttl = _normalize_recovery_ttl(ttl)
    if terminal_status not in {"failed", "cancelled"} or ttl is None:
        return False
    script = """
    local status = redis.call('HGET', KEYS[1], 'status')
    local clock = redis.call('TIME')
    local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
    redis.call('HSET', KEYS[1], 'status', ARGV[1],
      'terminal_result', ARGV[1], 'terminal_owner', 'recovery',
      'fenced_at', now, 'recovered_at', now, 'updated_at', now)
    redis.call('HDEL', KEYS[1], 'owner', 'lease_until', 'cancel_requested', 'reason')
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 1
    """
    from .job_lifecycle import lifecycle_key

    result = redis_client.eval(script, 1, lifecycle_key(job_id), terminal_status, ttl)
    return result is True or result == 1 or result == "1" or result == b"1"


def _replay_durable_terminal(
    redis_client,
    job_id: str,
    payload: Optional[dict[str, Any]],
    *,
    terminal_status: str,
    ttl: Optional[int],
) -> bool:
    """Replay a canonical DB failure/cancellation before refunding its receipt."""
    recovery_ttl = ttl
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if not isinstance(payload, dict) or ttl is None:
        return False
    if not _recover_durable_terminal_lifecycle(
        redis_client,
        job_id,
        terminal_status,
        _normalize_recovery_ttl(recovery_ttl),
    ):
        return False
    from .event_publisher import publish_job_result

    result = dict(payload)
    result["job_id"] = job_id
    result["success"] = False
    if terminal_status == "cancelled":
        result["cancelled"] = True
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        return False
    if not publish_job_result(job_id, result, ttl=ttl, force=True):
        return False
    event_payload = {
        "stage": "recovered",
        "error_code": result.get("error_code") or result.get("failure_code") or "job_failed",
        "error_message": result.get("error") or result.get("error_message") or "Job failed",
        "retryable": False,
    }
    ttl = _normalize_recovery_ttl(recovery_ttl)
    if ttl is None:
        return False
    return bool(publish_event(job_id, f"job.{terminal_status}", event_payload, ttl=ttl))


def _purge_expired_finalization_rows(limit: int = 500) -> int:
    """Garbage-collect bounded recovery payloads after their retention TTL."""

    async def _purge() -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from ..core.config import settings
        from ..utils.db_url import normalize_database_url
        from .finalization_arbiter import purge_expired_finalizations

        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                deleted = await purge_expired_finalizations(session, limit=limit)
                await session.commit()
                return deleted
        finally:
            await engine.dispose()

    try:
        return int(asyncio.run(_purge()))
    except Exception as exc:
        logger.warning(
            "Could not purge expired finalization rows",
            extra={"error_type": type(exc).__name__},
        )
        return 0


async def _reconcile_orphaned_compilations(
    redis_client,
    *,
    stale_after_seconds: int = _ORPHANED_COMPILATION_TIMEOUT_SECONDS,
    batch_size: int = 100,
    session_factory=None,
    cache_client=None,
) -> int:
    """Terminalize DB rows committed before a process died during dispatch.

    ``/jobs/submit`` creates the Compilation row before publishing work so a
    fast worker can reconcile it.  The complementary crash window is a process
    dying after that commit but before Redis metadata/broker dispatch.  Such a
    row has no job state to be found by the normal Redis cleanup scan.  After a
    conservative age threshold, mark only rows with no state, metadata, or
    result as failed; a live Redis job remains owned by its worker timeout path.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..database.models import Compilation
    from ..utils.db_url import resolve_database_url
    engine = None
    if session_factory is None:
        db_url = resolve_database_url()
        if not db_url:
            return 0
        engine = create_async_engine(db_url, echo=False)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    repaired = 0
    try:
        if cache_client is None:
            cache_client = get_sync_redis_cache_client()
        async with session_factory() as session:
            result = await session.execute(
                select(Compilation).where(
                    Compilation.status == "processing",
                    Compilation.created_at < cutoff,
                )
                .order_by(Compilation.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            for compilation in result.scalars().all():
                job_id = str(compilation.job_id)
                state_key = f"latexy:job:{job_id}:state"
                marker_key = f"latexy:job:{job_id}{_DISPATCH_MARKER_SUFFIX}"
                raw_state = redis_client.get(state_key)
                if not isinstance(raw_state, (str, bytes)):
                    raw_state = None
                try:
                    state = json.loads(raw_state) if raw_state else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    state = {}
                # A queued snapshot without the pre-dispatch marker proves the
                # process died before it attempted broker/Modal submission.
                # A marker means dispatch was attempted, so recovery must not
                # refund potentially live work merely because its DB row is old.
                if raw_state and state.get("status") != "queued":
                    continue
                if redis_client.exists(marker_key):
                    continue
                lifecycle = lifecycle_status(redis_client, job_id)
                if lifecycle is None:
                    # The process may have died after committing the durable
                    # placeholder but before quota/lifecycle initialization.
                    # Create a failed tombstone atomically before closing the
                    # row/refunding; a late begin_dispatch then loses the same
                    # Redis race rather than running after compensation.
                    if (
                        not raw_state
                        and not redis_client.exists(marker_key)
                    ):
                        arbiter_outcome = await fence_finalization(
                            session, job_id=job_id, reason_code="dispatch_timeout"
                        )
                        # A previous pass may have committed the DB fence but
                        # crashed before Redis/refund. Treat that durable
                        # tombstone as retryable evidence, not as a fresh
                        # ambiguous outcome.
                        if arbiter_outcome is FinalizationOutcome.FAILED:
                            durable = await recover_finalization(session, job_id=job_id)
                            arbiter_outcome = (
                                FinalizationOutcome.FENCED
                                if durable and durable.state == FinalizationState.FENCED.value
                                else arbiter_outcome
                            )
                        if arbiter_outcome != FinalizationOutcome.FENCED:
                            continue
                        await session.commit()
                        if not fence_orphan_without_lifecycle(redis_client, job_id) and lifecycle_status(
                            redis_client, job_id
                        ) != "failed":
                            continue
                        await session.refresh(compilation)
                        compilation.status = "failed"
                        compilation.error_message = "Job dispatch did not start; please retry."
                        await session.commit()
                        repaired += 1
                    continue
                if lifecycle not in {"dispatching", "queued"}:
                    # Missing or already-running lifecycle evidence is not
                    # proof that this DB row is safe to refund.
                    continue
                arbiter_outcome = await fence_finalization(
                    session, job_id=job_id, reason_code="dispatch_timeout"
                )
                if arbiter_outcome is FinalizationOutcome.FAILED:
                    durable = await recover_finalization(session, job_id=job_id)
                    arbiter_outcome = (
                        FinalizationOutcome.FENCED
                        if durable and durable.state == FinalizationState.FENCED.value
                        else arbiter_outcome
                    )
                if arbiter_outcome != FinalizationOutcome.FENCED:
                    continue
                await session.commit()
                if not fence_job(redis_client, job_id, "dispatch_timeout") and lifecycle_status(
                    redis_client, job_id
                ) != "failed":
                    continue
                quota_refund = _load_pending_quota_receipt(cache_client, job_id)
                if cache_client.exists(f"latexy:quota-refund-pending:{job_id}") and not quota_refund:
                    logger.warning("Deferred orphaned job %s because its quota receipt is invalid", job_id)
                    continue
                if quota_refund and not _refund_pending_quota_receipt(cache_client, job_id, quota_refund):
                    logger.warning("Deferred orphaned job %s until quota refund succeeds", job_id)
                    continue
                await session.refresh(compilation)
                compilation.status = "failed"
                compilation.error_message = "Job dispatch did not complete; please retry."
                await session.commit()
                repaired += 1
        return repaired
    except Exception:
        logger.warning("Could not reconcile orphaned compilation rows", exc_info=True)
        return 0
    finally:
        if engine is not None:
            await engine.dispose()


async def _select_committed_compilation_paths(pdf_paths: list[str]) -> Optional[set[str]]:
    """
    Return the exact PDF pointers committed in the owning database.

    Returns None when the answer cannot be TRUSTED, so callers skip pruning
    rather than deleting objects they could not verify. A row for the job is
    not enough: an interrupted upload can leave a second owner-scoped object
    beside the committed winner, so pruning must compare immutable pointers.
    Untrusted means either the DB is unreachable/unconfigured, or it holds no
    Compilation or JobFinalization rows at all — which is indistinguishable
    from having connected to the wrong database, and "delete everything under
    compilations/" is not a recoverable mistake.

    The DSN comes from the shared resolver so this reads the SAME database
    latex_worker._update_compilation_record writes the owning rows to.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..database.models import Compilation, JobFinalization
    from ..utils.db_url import database_identity, resolve_database_url
    from .storage_guard import read_compilation_database

    db_url = resolve_database_url()
    if not db_url:
        logger.warning("DATABASE_URL not set — skipping MinIO orphan prune")
        return None

    # Positive confirmation that this is the database the uploader indexed the
    # objects in — a mismatch means every object would look like an orphan.
    identity = database_identity(db_url)
    stamped = read_compilation_database()
    if stamped != identity:
        logger.warning(
            "MinIO orphan prune skipped — compilations were indexed in %s but this "
            "worker resolved %s",
            stamped or "an unknown database",
            identity,
        )
        return None

    engine = create_async_engine(db_url, echo=False)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        committed: set[str] = set()
        async with session_factory() as session:
            for i in range(0, len(pdf_paths), 500):
                chunk = pdf_paths[i:i + 500]
                compilation_rows = await session.execute(
                    select(Compilation.pdf_path).where(Compilation.pdf_path.in_(chunk))
                )
                finalization_rows = await session.execute(
                    select(JobFinalization.pdf_path).where(JobFinalization.pdf_path.in_(chunk))
                )
                committed.update(
                    path for path in compilation_rows.scalars().all() if isinstance(path, str)
                )
                committed.update(
                    path for path in finalization_rows.scalars().all() if isinstance(path, str)
                )

            if not committed:
                # Nothing matched. Before treating every object as an orphan,
                # confirm this database is the one that records durable jobs.
                any_compilation = await session.execute(select(Compilation.job_id).limit(1))
                any_finalization = await session.execute(select(JobFinalization.job_id).limit(1))
                if (
                    any_compilation.scalar_one_or_none() is None
                    and any_finalization.scalar_one_or_none() is None
                ):
                    logger.warning(
                        "MinIO orphan prune skipped — %s has no durable job rows, "
                        "refusing to treat %d candidate PDF paths as orphans",
                        identity,
                        len(pdf_paths),
                    )
                    return None
        logger.info(
            "MinIO orphan prune verified %d/%d candidate PDF pointers against %s",
            len(committed),
            len(pdf_paths),
            identity,
        )
        return committed
    except Exception as exc:
        logger.warning(
            "Could not verify compilation PDF paths for MinIO prune",
            extra={"error_type": type(exc).__name__},
        )
        return None
    finally:
        await engine.dispose()


def _prune_orphaned_compilation_objects() -> Dict[str, int]:
    """
    Delete aged, owner-scoped finalization objects with no committed PDF path.

    Compile paths without an owning row (anonymous /jobs/submit,
    /jobs/compile-watermarked, the anonymous-share redaction compile) used to
    upload unconditionally, and account deletion / resume deletion can also
    remove rows, so the prefix could grow without bound. Legacy/unrelated keys
    are retained because this pass has no immutable ownership proof for them.
    Objects still pointed at by a row are kept regardless of age because share
    links serve them indefinitely.
    """
    import asyncio

    from ..services import storage_service

    stats = {"scanned": 0, "deleted": 0}
    try:
        objects = storage_service.list_objects(_COMPILATION_PREFIX, max_keys=5000)
    except Exception as exc:
        logger.warning(
            "MinIO prune skipped — could not list compilation objects",
            extra={"error_type": type(exc).__name__},
        )
        return stats

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_ORPHAN_GRACE_SECONDS)
    candidates: list[str] = []
    for obj in objects:
        stats["scanned"] += 1
        key = obj.get("key") if isinstance(obj, dict) else None
        if not isinstance(key, str) or not _OWNER_SCOPED_COMPILATION_KEY_RE.fullmatch(key):
            # Preserve legacy and unrelated objects under the broad prefix;
            # this pass only has an explicit immutable ownership contract for
            # finalization-{sha256}.pdf keys.
            continue
        last_modified = obj.get("last_modified")
        if (
            not isinstance(last_modified, datetime)
            or last_modified.tzinfo is None
            or last_modified > cutoff
        ):
            # Missing timestamps cannot establish the grace period. A recent
            # upload must never be deleted merely because metadata is absent.
            continue
        candidates.append(key)

    if not candidates:
        return stats

    committed_paths = asyncio.run(_select_committed_compilation_paths(candidates))
    if committed_paths is None:
        return stats

    for key in candidates:
        if key in committed_paths:
            continue
        try:
            if storage_service.delete_object(key):
                stats["deleted"] += 1
        except Exception as exc:
            logger.warning(
                "Failed to delete orphaned compilation object",
                extra={"error_type": type(exc).__name__},
            )
    if stats["deleted"]:
        logger.info(
            f"Pruned {stats['deleted']} orphaned objects under {_COMPILATION_PREFIX}"
        )
    return stats



def _scan_job_state_keys(r, count: int = 500) -> list:
    """List job-state keys without blocking Redis.

    KEYS is O(N) over the whole keyspace and blocks the server for its entire
    duration — every other client waits, including the API's job-state reads,
    quota checks and rate limiters. On a production keyspace that is long enough
    for user-facing requests to time out.

    These tasks only ever run on a schedule, so paying a few extra round-trips
    for SCAN's incremental cursor costs nothing and keeps Redis responsive.
    """
    keys = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor=cursor, match="latexy:job:*:state", count=count)
        keys.extend(batch)
        if cursor == 0:
            return keys


_ACTIVE_JOB_STATES = frozenset({"queued", "pending", "processing", "running", "retrying"})
_SYNTHETIC_JOB_PREFIXES = ("health_check_", "cleanup_", "job_cleanup_")


def _count_active_job_states(r, batch_size: int = 500) -> int:
    """Count non-terminal user jobs without mistaking retained history for work."""
    keys = _scan_job_state_keys(r, count=batch_size)
    active = 0
    for offset in range(0, len(keys), batch_size):
        batch = keys[offset:offset + batch_size]
        for key, raw_state in zip(batch, r.mget(batch)):
            job_id = key[len("latexy:job:"):-len(":state")]
            if job_id.startswith(_SYNTHETIC_JOB_PREFIXES) or not raw_state:
                continue
            try:
                status = json.loads(raw_state).get("status")
            except (TypeError, ValueError, json.JSONDecodeError):
                # A malformed retained snapshot is not evidence of active work.
                continue
            if status in _ACTIVE_JOB_STATES:
                active += 1
    return active


@celery_app.task(bind=True, name="app.workers.cleanup_worker.cleanup_expired_jobs_task")
def cleanup_expired_jobs_task(
    self,
    max_age_hours: int = 24,
    batch_size: int = 100,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Clean up expired job data from Redis.

    Args:
        max_age_hours: Maximum age of job data to keep (in hours)
        batch_size: Number of jobs to process in each batch
        metadata: Additional metadata

    Returns:
        Dict containing cleanup result
    """
    task_id = self.request.id
    job_id = f"job_cleanup_{task_id}"

    logger.info(f"Starting expired jobs cleanup task {task_id} for job {job_id}")

    try:
        # Set initial status
        publish_event(job_id, "job.started", {
            "worker_id": f"job-cleanup-{task_id}",
            "stage": "expired_job_cleanup",
            "task_id": task_id,
            "max_age_hours": max_age_hours,
            "batch_size": batch_size,
            "started_at": time.time(),
        })

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "expired_job_cleanup",
            "message": "Scanning for expired jobs",
        })

        # Prune aged owner-scoped MinIO objects with no durable PDF pointer.
        minio_prune = _prune_orphaned_compilation_objects()
        finalization_rows_purged = _purge_expired_finalization_rows()

        r = get_worker_redis()
        quota_cache = get_sync_redis_cache_client()

        # Receipt keys are the recovery source for LLM and other jobs that do
        # not have a Compilation row.  Only pre-dispatch/terminal failures are
        # refunded; marked queued/processing jobs are left alone.
        receipt_recoveries = _reconcile_receipts_without_compilation_rows(r, quota_cache)

        # Repair the DB-only crash window from submission: a process can die
        # after committing a Compilation placeholder but before writing Redis
        # metadata or publishing to the broker. Redis scanning cannot discover
        # those rows, so reconcile them independently after a grace period.
        orphaned_compilations = asyncio.run(_reconcile_orphaned_compilations(r))

        # Scan for all job state keys using the canonical latexy:job:*:state pattern.
        # get_active_jobs_sync() uses an old job_status: prefix that does not match
        # the keys written by publish_event / _update_state_snapshot.
        state_keys = _scan_job_state_keys(r)
        # Derive job IDs by stripping the trailing ":state" suffix.
        active_jobs = [k[len("latexy:job:"):-len(":state")] for k in state_keys]

        if not active_jobs:
            logger.info("No active jobs found for cleanup")
            result_data = {
                "success": True,
                "task_id": task_id,
                "job_id": job_id,
                "message": "No active jobs found for cleanup",
                "minio_objects_scanned": minio_prune["scanned"],
                "minio_objects_pruned": minio_prune["deleted"],
                "jobs_cleaned": 0,
                "total_jobs_scanned": 0,
                "jobs_timed_out": 0,
                "orphaned_compilations": orphaned_compilations,
                "quota_receipts_recovered": receipt_recoveries,
                "finalization_rows_purged": finalization_rows_purged,
                "max_age_hours": max_age_hours,
                "batch_size": batch_size,
                "errors": [],
                "error_count": 0,
                "completed_at": time.time()
            }

            publish_event(job_id, "job.completed", {
                "pdf_job_id": job_id,
                "ats_score": 0.0,
                "ats_details": {},
                "changes_made": [],
                "compilation_time": 0.0,
                "optimization_time": 0.0,
                "tokens_used": 0,
            })
            publish_job_result(job_id, result_data)
            return result_data

        # Redis owns the timestamps written by the event Lua script. Use its
        # clock for retention comparisons too; a skewed cleanup host must not
        # delete live terminal snapshots (or preserve expired ones).
        retention_now = _redis_server_time(r)
        cutoff_time = (
            retention_now - (max_age_hours * 3600)
            if retention_now is not None
            else None
        )
        # Threshold for detecting stuck "processing" jobs (10 minutes)
        processing_timeout = 10 * 60

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 30,
            "stage": "expired_job_cleanup",
            "message": f"Processing {len(active_jobs)} jobs",
        })

        jobs_cleaned = 0
        jobs_scanned = 0
        jobs_timed_out = 0
        errors = []

        # Process jobs in batches
        for i in range(0, len(active_jobs), batch_size):
            batch = active_jobs[i:i + batch_size]

            for job_id_to_check in batch:
                try:
                    jobs_scanned += 1

                    # Read state from the canonical latexy:job:{id}:state key
                    raw_state = r.get(f"latexy:job:{job_id_to_check}:state")
                    if not raw_state:
                        continue

                    state_data = json.loads(raw_state)
                    last_updated = state_data.get("last_updated", 0)
                    job_status_value = state_data.get("status", "unknown")

                    # Detect stuck "processing" jobs older than 10 minutes and
                    # transition them to "failed" so the frontend gets a clear signal.
                    # Internal probes (health_check_*, cleanup_*) publish job
                    # lifecycle events under synthetic ids. They are not user
                    # work, and treating them as stuck filled the logs with
                    # "marking failed" for jobs nobody submitted.
                    if job_id_to_check.startswith(_SYNTHETIC_JOB_PREFIXES):
                        continue

                    # Durable terminal rows are authoritative even when the
                    # Redis lifecycle still says running/processing. Repair
                    # the transport for unmetered jobs too; do not replace a
                    # canonical failure/cancellation with a timeout result.
                    durable_state, durable_payload, durable_ttl = _read_finalization_outcome(
                        job_id_to_check
                    )
                    if durable_state in {
                        FinalizationState.COMPLETED.value,
                        FinalizationState.FAILED.value,
                        FinalizationState.CANCELLED.value,
                        FinalizationState.FENCED.value,
                    }:
                        if durable_ttl is None:
                            continue
                        if durable_state == FinalizationState.COMPLETED.value:
                            replayed = _replay_durable_completion(
                                r, job_id_to_check, durable_payload, durable_ttl
                            )
                        else:
                            replayed = _replay_durable_terminal(
                                r,
                                job_id_to_check,
                                durable_payload,
                                terminal_status=(
                                    "cancelled"
                                    if durable_state == FinalizationState.CANCELLED.value
                                    else "failed"
                                ),
                                ttl=durable_ttl,
                            )
                        if replayed:
                            _refund_pending_quota_receipt(quota_cache, job_id_to_check)
                        continue
                    if durable_state in {_FINALIZATION_DB_UNAVAILABLE, _FINALIZATION_EXPIRED}:
                        # DB outage cannot authorize a transport mutation.
                        # Expired history cannot authorize replay/refund, but
                        # ordinary Redis lifecycle cleanup may still proceed.
                        if durable_state == _FINALIZATION_DB_UNAVAILABLE:
                            continue

                    dispatch_marker = r.exists(
                        f"latexy:job:{job_id_to_check}{_DISPATCH_MARKER_SUFFIX}"
                    )

                    # A queued snapshot without a dispatch marker means the
                    # submitting process died before it attempted the broker.
                    # Refund its receipt and terminalize it after a grace
                    # period; marked queued work may still be live in Celery or
                    # Modal and is intentionally left untouched.
                    if job_status_value == "queued" and not dispatch_marker:
                        redis_now = _redis_server_time(r)
                        queued_since = last_updated or redis_now
                        if redis_now is not None and queued_since is not None and redis_now - queued_since > processing_timeout:
                            db_fence = _fence_database_before_timeout(job_id_to_check, "dispatch_timeout")
                            if db_fence not in {"legacy", "fenced"}:
                                continue
                            if db_fence == "fenced":
                                durable_state, durable_payload, durable_ttl = _read_finalization_outcome(
                                    job_id_to_check
                                )
                                replayed = durable_state in {
                                    FinalizationState.FAILED.value,
                                    FinalizationState.CANCELLED.value,
                                    FinalizationState.FENCED.value,
                                } and _replay_durable_terminal(
                                    r,
                                    job_id_to_check,
                                    durable_payload,
                                    terminal_status=(
                                        "cancelled"
                                        if durable_state == FinalizationState.CANCELLED.value
                                        else "failed"
                                    ),
                                    ttl=durable_ttl,
                                )
                                if replayed:
                                    _refund_pending_quota_receipt(quota_cache, job_id_to_check)
                                    jobs_timed_out += 1
                                continue
                            if not fence_job(r, job_id_to_check, "dispatch_timeout"):
                                continue
                            _terminalize_timeout(job_id_to_check, reason="dispatch_timeout")
                            _refund_pending_quota_receipt(quota_cache, job_id_to_check)
                            jobs_timed_out += 1
                            continue

                    if job_status_value == "processing":
                        # A terminal result can be written before its final state
                        # event. Never overwrite that accepted result with timeout.
                        result_key = f"latexy:job:{job_id_to_check}:result"
                        if r.exists(result_key) and lifecycle_status(r, job_id_to_check) not in {"failed", "cancelled"}:
                            # A worker can die after atomically publishing the
                            # success result but before reconciling its DB row.
                            # The result is the durable terminal evidence; close
                            # the placeholder instead of timing it out.
                            try:
                                raw_result = r.get(result_key)
                                parsed_result = json.loads(raw_result) if raw_result else {}
                                if parsed_result.get("success") is True and durable_state is None:
                                    from .latex_worker import reconcile_compilation_record

                                    reconcile_compilation_record(
                                        job_id_to_check,
                                        success=True,
                                        compilation_time=parsed_result.get("compilation_time"),
                                    )
                            except Exception as exc:
                                logger.warning(
                                    "Could not reconcile completed result %s",
                                    job_id_to_check,
                                    extra={"error_type": type(exc).__name__},
                                )
                                if durable_state is None:
                                    continue
                            if durable_state is None:
                                continue

                        # Measure active work from its most recent heartbeat, not
                        # from submission time: queue wait is not processing time.
                        redis_now = _redis_server_time(r)
                        processing_since = last_updated or redis_now
                        if redis_now is not None and processing_since is not None and redis_now - processing_since > processing_timeout:
                            db_fence = _fence_database_before_timeout(job_id_to_check, "timeout")
                            if db_fence not in {"legacy", "fenced"}:
                                continue
                            if db_fence == "fenced":
                                durable_state, durable_payload, durable_ttl = _read_finalization_outcome(
                                    job_id_to_check
                                )
                                replayed = durable_state in {
                                    FinalizationState.FAILED.value,
                                    FinalizationState.CANCELLED.value,
                                    FinalizationState.FENCED.value,
                                } and _replay_durable_terminal(
                                    r,
                                    job_id_to_check,
                                    durable_payload,
                                    terminal_status=(
                                        "cancelled"
                                        if durable_state == FinalizationState.CANCELLED.value
                                        else "failed"
                                    ),
                                    ttl=durable_ttl,
                                )
                                if replayed:
                                    _refund_pending_quota_receipt(quota_cache, job_id_to_check)
                                    jobs_timed_out += 1
                                continue
                            if not fence_job(r, job_id_to_check, "timeout"):
                                continue
                            logger.warning(
                                f"Job {job_id_to_check} stuck in 'processing' for "
                                f"{(redis_now - processing_since):.0f}s — marking failed"
                            )
                            try:
                                celery_app.control.revoke(
                                    job_id_to_check,
                                    terminate=True,
                                    signal="SIGTERM",
                                )
                            except Exception as revoke_exc:
                                logger.warning(
                                    "Failed to revoke timed-out job %s (%s)",
                                    job_id_to_check,
                                    type(revoke_exc).__name__,
                                )
                            _terminalize_timeout(job_id_to_check)
                            _refund_pending_quota_receipt(quota_cache, job_id_to_check)
                            jobs_timed_out += 1

                    # Check if job is expired (terminal state, last updated before cutoff)
                    if (
                        cutoff_time is not None
                        and last_updated < cutoff_time
                        and job_status_value in ["completed", "failed", "cancelled"]
                    ):
                        r.delete(
                            f"latexy:job:{job_id_to_check}:state",
                            f"latexy:job:{job_id_to_check}:result",
                            f"latexy:job:{job_id_to_check}:meta",
                            f"latexy:job:{job_id_to_check}:seq",
                            f"latexy:stream:{job_id_to_check}",
                        )
                        jobs_cleaned += 1
                        logger.debug(f"Cleaned expired job: {job_id_to_check}")

                except Exception as e:
                    logger.error(
                        "Error processing expired job %s",
                        job_id_to_check,
                        extra={"error_type": type(e).__name__},
                    )
                    # Keep the affected job identifiable for operators while
                    # avoiding raw Redis/backend exception text in the result.
                    errors.append(f"Expired job processing failed: {job_id_to_check}")

            # Update progress
            progress = 30 + int((i / len(active_jobs)) * 60)
            publish_event(job_id, "job.progress", {
                "percent": progress,
                "stage": "expired_job_cleanup",
                "message": f"Processed {min(i + batch_size, len(active_jobs))}/{len(active_jobs)} jobs",
            })

        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Job cleanup completed: {jobs_cleaned} jobs cleaned, {jobs_timed_out} timed out",
            "minio_objects_scanned": minio_prune["scanned"],
            "minio_objects_pruned": minio_prune["deleted"],
            "jobs_cleaned": jobs_cleaned,
            "jobs_timed_out": jobs_timed_out,
            "orphaned_compilations": orphaned_compilations,
            "quota_receipts_recovered": receipt_recoveries,
            "finalization_rows_purged": finalization_rows_purged,
            "total_jobs_scanned": jobs_scanned,
            "max_age_hours": max_age_hours,
            "batch_size": batch_size,
            "errors": errors,
            "error_count": len(errors),
            "completed_at": time.time()
        }

        # Set final status and result
        publish_job_result(job_id, result_data)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": 0.0,
            "ats_details": {},
            "changes_made": [],
            "compilation_time": 0.0,
            "optimization_time": 0.0,
            "tokens_used": 0,
        })

        # Final progress update
        publish_event(job_id, "job.progress", {
            "percent": 100,
            "stage": "expired_job_cleanup",
            "message": "Job cleanup task completed",
        })

        logger.info(
            f"Expired jobs cleanup task {task_id} completed: "
            f"{jobs_cleaned}/{jobs_scanned} jobs cleaned, {jobs_timed_out} timed out"
        )
        return result_data

    except Exception as e:
        logger.error(
            "Expired jobs cleanup task %s failed for job %s",
            task_id,
            job_id,
            extra={"error_type": type(e).__name__},
        )

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": "Expired jobs cleanup failed",
            "error": "Expired jobs cleanup failed",
            "jobs_cleaned": 0,
            "total_jobs_scanned": 0,
            "completed_at": time.time()
        }

        # Set error status
        publish_event(job_id, "job.failed", {
            "stage": "expired_job_cleanup",
            "error_code": "internal",
            "error_message": "Expired jobs cleanup failed",
            "retryable": False,
        })
        publish_job_result(job_id, error_data)

        # Re-raise via Celery retry so the task is marked FAILED rather than
        # silently swallowing the exception and returning a success-shaped dict.
        raise self.retry(exc=e, countdown=60)


@celery_app.task(bind=True, name="app.workers.cleanup_worker.health_check_task")
def health_check_task(
    self,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Perform system health check.

    Args:
        metadata: Additional metadata

    Returns:
        Dict containing health check result
    """
    task_id = self.request.id
    job_id = f"health_check_{task_id}"

    logger.info(f"Starting health check task {task_id} for job {job_id}")

    try:
        # Set initial status
        publish_event(job_id, "job.started", {
            "worker_id": f"health-check-{task_id}",
            "stage": "health_check",
            "task_id": task_id,
            "started_at": time.time(),
        })

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 20,
            "stage": "health_check",
            "message": "Checking Redis connections",
        })

        redis_health = redis_manager.health_check_sync()

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 50,
            "stage": "health_check",
            "message": "Checking disk space",
        })

        # Check disk space
        temp_dir = settings.TEMP_DIR
        disk_usage = shutil.disk_usage(temp_dir)
        disk_free_gb = disk_usage.free / (1024 ** 3)
        disk_total_gb = disk_usage.total / (1024 ** 3)
        disk_used_percent = ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100

        # Update progress
        publish_event(job_id, "job.progress", {
            "percent": 80,
            "stage": "health_check",
            "message": "Checking active jobs",
        })

        _r = get_worker_redis()
        active_jobs_count = _count_active_job_states(_r)

        # Determine overall health
        health_issues = []

        if not all(redis_health.values()):
            health_issues.append("Redis connection issues")

        if disk_free_gb < 1.0:  # Less than 1GB free
            health_issues.append(f"Low disk space: {disk_free_gb:.2f}GB free")

        if active_jobs_count > 1000:  # Too many active jobs
            health_issues.append(f"High job count: {active_jobs_count} active jobs")

        overall_health = "healthy" if not health_issues else "degraded"

        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Health check completed: {overall_health}",
            "overall_health": overall_health,
            "health_issues": health_issues,
            "redis_health": redis_health,
            "disk_usage": {
                "free_gb": round(disk_free_gb, 2),
                "total_gb": round(disk_total_gb, 2),
                "used_percent": round(disk_used_percent, 2)
            },
            "active_jobs_count": active_jobs_count,
            "temp_directory": str(temp_dir),
            "completed_at": time.time()
        }

        # Set final status and result
        publish_job_result(job_id, result_data)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": 0.0,
            "ats_details": {},
            "changes_made": [],
            "compilation_time": 0.0,
            "optimization_time": 0.0,
            "tokens_used": 0,
        })

        # Final progress update
        publish_event(job_id, "job.progress", {
            "percent": 100,
            "stage": "health_check",
            "message": "Health check completed",
        })

        logger.info(f"Health check task {task_id} completed: {overall_health}")
        return result_data

    except Exception as e:
        logger.error(
            "Health check task %s failed for job %s",
            task_id,
            job_id,
            extra={"error_type": type(e).__name__},
        )

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": "Health check failed",
            "error": "Health check failed",
            "overall_health": "unhealthy",
            "completed_at": time.time()
        }

        # Set error status
        publish_event(job_id, "job.failed", {
            "stage": "health_check",
            "error_code": "internal",
            "error_message": "Health check failed",
            "retryable": False,
        })
        publish_job_result(job_id, error_data)

        # Re-raise via Celery retry so the task is marked FAILED rather than
        # silently swallowing the exception and returning a success-shaped dict.
        raise self.retry(exc=e, countdown=60)


# Utility functions to submit cleanup jobs
def submit_temp_files_cleanup(
    max_age_hours: int = 24,
    target_directory: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit temp files cleanup job to queue.

    Returns:
        job_id: Job ID for tracking
    """
    import os
    if os.environ.get("DEPLOY_TARGET") == "modal":
        import uuid

        from ..core.modal_dispatch import spawn
        job_id = f"cleanup_{uuid.uuid4()}"
        spawn("run_cleanup_task", {
            "task_type": "temp_files",
            "max_age_hours": max_age_hours,
            "target_directory": target_directory,
            "metadata": metadata,
        })
        logger.info(f"Modal spawn: temp files cleanup {job_id}")
        return job_id

    task = cleanup_temp_files_task.apply_async(
        args=[max_age_hours],
        kwargs={
            "target_directory": target_directory,
            "metadata": metadata
        },
        queue="cleanup"
    )

    job_id = f"cleanup_{task.id}"
    logger.info(f"Submitted temp files cleanup job {job_id} with task {task.id}")
    return job_id


def submit_expired_jobs_cleanup(
    max_age_hours: int = 24,
    batch_size: int = 100,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit expired jobs cleanup job to queue.

    Returns:
        job_id: Job ID for tracking
    """
    import os
    if os.environ.get("DEPLOY_TARGET") == "modal":
        import uuid

        from ..core.modal_dispatch import spawn
        job_id = f"job_cleanup_{uuid.uuid4()}"
        spawn("run_cleanup_task", {
            "task_type": "expired_jobs",
            "max_age_hours": max_age_hours,
            "batch_size": batch_size,
            "metadata": metadata,
        })
        logger.info(f"Modal spawn: expired jobs cleanup {job_id}")
        return job_id

    task = cleanup_expired_jobs_task.apply_async(
        args=[max_age_hours],
        kwargs={
            "batch_size": batch_size,
            "metadata": metadata
        },
        queue="cleanup"
    )

    job_id = f"job_cleanup_{task.id}"
    logger.info(f"Submitted expired jobs cleanup job {job_id} with task {task.id}")
    return job_id


# Scheduled task aliases for Celery Beat
cleanup_expired_jobs = cleanup_expired_jobs_task
cleanup_temp_files = cleanup_temp_files_task
health_check = health_check_task

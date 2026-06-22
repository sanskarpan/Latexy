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

import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import redis_manager
from ..workers.event_publisher import get_worker_redis, publish_event, publish_job_result

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
                    error_msg = f"Error deleting {item}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

        except Exception as e:
            logger.error(f"Error during cleanup scan: {e}")
            errors.append(f"Scan error: {e}")

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
                        logger.debug(f"Could not delete directory {item}: {e}")
        except Exception as e:
            logger.error(f"Error cleaning empty directories: {e}")

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
            "stage": "temp_file_cleanup",
            "message": "Cleanup task completed",
        })

        logger.info(f"Temp files cleanup task {task_id} completed: {files_deleted} files, {space_freed} bytes freed")
        return result_data

    except Exception as e:
        logger.error(f"Temp files cleanup task {task_id} failed for job {job_id}: {e}", exc_info=True)

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Cleanup error: {str(e)}",
            "error": str(e),
            "files_deleted": 0,
            "directories_deleted": 0,
            "space_freed": 0,
            "completed_at": time.time()
        }

        try:
            publish_event(job_id, "job.failed", {
                "stage": "temp_file_cleanup",
                "error_code": "internal",
                "error_message": str(e),
                "retryable": False,
            })
            publish_job_result(job_id, error_data)
        except Exception:
            pass  # best-effort; don't mask the original error

        return error_data


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

        # Scan for all job state keys using the canonical latexy:job:*:state pattern.
        # get_active_jobs_sync() uses an old job_status: prefix that does not match
        # the keys written by publish_event / _update_state_snapshot.
        r = get_worker_redis()
        state_keys = r.keys("latexy:job:*:state")
        # Derive job IDs by stripping the trailing ":state" suffix.
        active_jobs = [k[len("latexy:job:"):-len(":state")] for k in state_keys]

        if not active_jobs:
            logger.info("No active jobs found for cleanup")
            result_data = {
                "success": True,
                "task_id": task_id,
                "job_id": job_id,
                "message": "No active jobs found for cleanup",
                "jobs_cleaned": 0,
                "total_jobs_scanned": 0,
                "jobs_timed_out": 0,
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

        # Calculate cutoff time for expired jobs
        cutoff_time = time.time() - (max_age_hours * 3600)
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
                    if job_status_value == "processing":
                        raw_meta = r.get(f"latexy:job:{job_id_to_check}:meta")
                        if raw_meta:
                            meta_data = json.loads(raw_meta)
                            submitted_at = meta_data.get("submitted_at", time.time())
                        else:
                            submitted_at = last_updated or time.time()
                        if time.time() - submitted_at > processing_timeout:
                            logger.warning(
                                f"Job {job_id_to_check} stuck in 'processing' for "
                                f"{(time.time() - submitted_at):.0f}s — marking failed"
                            )
                            publish_event(job_id_to_check, "job.failed", {
                                "stage": "timeout",
                                "error_code": "timeout",
                                "error_message": "Job timed out — worker may have crashed",
                                "retryable": False,
                            })
                            jobs_timed_out += 1

                    # Check if job is expired (terminal state, last updated before cutoff)
                    if last_updated < cutoff_time and job_status_value in ["completed", "failed", "cancelled"]:
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
                    error_msg = f"Error processing job {job_id_to_check}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

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
            "jobs_cleaned": jobs_cleaned,
            "jobs_timed_out": jobs_timed_out,
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
        logger.error(f"Expired jobs cleanup task {task_id} failed for job {job_id}: {e}")

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Job cleanup error: {str(e)}",
            "error": str(e),
            "jobs_cleaned": 0,
            "total_jobs_scanned": 0,
            "completed_at": time.time()
        }

        # Set error status
        publish_event(job_id, "job.failed", {
            "stage": "expired_job_cleanup",
            "error_code": "internal",
            "error_message": str(e),
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
        active_jobs_count = len(_r.keys("latexy:job:*:state"))

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
        logger.error(f"Health check task {task_id} failed for job {job_id}: {e}")

        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Health check error: {str(e)}",
            "error": str(e),
            "overall_health": "unhealthy",
            "completed_at": time.time()
        }

        # Set error status
        publish_event(job_id, "job.failed", {
            "stage": "health_check",
            "error_code": "internal",
            "error_message": str(e),
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

"""
Celery application configuration for Phase 8.
"""

from __future__ import annotations

from time import perf_counter

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_postrun, task_prerun, worker_process_init

from ..core.config import settings
from ..core.logging import get_logger
from ..core.observability import record_celery_task, reset_context, set_task_context
from ..core.tracing import instrument_celery, setup_telemetry

setup_telemetry("worker")
instrument_celery()
logger = get_logger(__name__)
_task_start_times: dict[str, float] = {}

# Create Celery instance
celery_app = Celery(
    "latexy",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.latex_worker",
        "app.workers.llm_worker",
        "app.workers.email_worker",
        "app.workers.cleanup_worker",
        "app.workers.ats_worker",
        "app.workers.orchestrator",
        "app.workers.auto_save_worker",
        "app.workers.cover_letter_worker",
        "app.workers.interview_prep_worker",
        "app.workers.converter_worker",
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    timezone=settings.CELERY_TIMEZONE,
    enable_utc=settings.CELERY_ENABLE_UTC,

    # Task routing
    task_routes={
        "app.workers.latex_worker.*": {"queue": "latex"},
        "app.workers.llm_worker.*": {"queue": "llm"},
        "app.workers.email_worker.*": {"queue": "email"},
        "app.workers.cleanup_worker.*": {"queue": "cleanup"},
        "app.workers.ats_worker.*": {"queue": "ats"},
        "app.workers.orchestrator.*": {"queue": "combined"},
        "app.workers.auto_save_worker.*": {"queue": "cleanup"},
        "app.workers.cover_letter_worker.*": {"queue": "llm"},
        "app.workers.interview_prep_worker.*": {"queue": "llm"},
        "app.workers.converter_worker.*": {"queue": "llm"},
    },

    # Task configuration
    task_always_eager=False,
    task_eager_propagates=True,
    task_ignore_result=False,
    task_store_eager_result=True,

    # Result backend configuration
    result_expires=settings.JOB_RESULT_TTL,
    result_persistent=True,

    # Worker configuration
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,

    # Retry configuration
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=settings.JOB_RETRY_DELAY,
    task_max_retries=settings.JOB_RETRY_ATTEMPTS,

    # Beat configuration (for scheduled tasks)
    beat_schedule={
        "cleanup-expired-jobs": {
            "task": "app.workers.cleanup_worker.cleanup_expired_jobs_task",
            "schedule": 3600.0,  # Run every hour
        },
        "cleanup-temp-files": {
            "task": "app.workers.cleanup_worker.cleanup_temp_files_task",
            "schedule": 1800.0,  # Run every 30 minutes
        },
        "health-check": {
            "task": "app.workers.cleanup_worker.health_check_task",
            "schedule": 300.0,  # Run every 5 minutes
        },
        # Feature 19 — weekly digest every Monday at 09:00 UTC
        "weekly-digest-monday-9am": {
            "task": "app.workers.email_worker.send_weekly_digest_to_all",
            "schedule": crontab(hour=9, minute=0, day_of_week="monday"),
        },
    },
    beat_schedule_filename="celerybeat-schedule",

    # Priority queues — Redis requires these transport options to honour the
    # `priority` kwarg passed to .apply_async().  Without this config the
    # broker processes tasks FIFO regardless of the priority value.
    broker_transport_options={
        "priority_steps": list(range(10)),   # 0 (highest) … 9 (lowest)
        "sep": ":",
        "queue_order_strategy": "priority",
    },
    task_queue_max_priority=9,

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,

    # Security
    worker_hijack_root_logger=False,
    worker_log_color=False,
)

# Task priority levels
TASK_PRIORITY_HIGH = 9
TASK_PRIORITY_NORMAL = 5
TASK_PRIORITY_LOW = 1

# Queue configurations
QUEUE_CONFIGS = {
    "latex": {
        "routing_key": "latex",
        "priority": TASK_PRIORITY_NORMAL,
        "max_retries": 3,
    },
    "llm": {
        "routing_key": "llm",
        "priority": TASK_PRIORITY_NORMAL,
        "max_retries": 2,
    },
    "email": {
        "routing_key": "email",
        "priority": TASK_PRIORITY_LOW,
        "max_retries": 5,
    },
    "cleanup": {
        "routing_key": "cleanup",
        "priority": TASK_PRIORITY_LOW,
        "max_retries": 1,
    },
    "ats": {
        "routing_key": "ats",
        "priority": TASK_PRIORITY_NORMAL,
        "max_retries": 2,
    },
}


def get_task_priority(user_plan: str = "free") -> int:
    """Get task priority based on user plan.

    When the task_priority feature flag is disabled, everyone gets high priority.
    """
    try:
        from ..services.feature_flag_service import feature_flag_service
        if not feature_flag_service.sync_get_flag("task_priority"):
            return TASK_PRIORITY_HIGH
    except Exception:
        pass
    priority_mapping = {
        "free": TASK_PRIORITY_LOW,
        "basic": TASK_PRIORITY_NORMAL,
        "pro": TASK_PRIORITY_HIGH,
        "byok": TASK_PRIORITY_HIGH,
        "team": TASK_PRIORITY_HIGH,
    }
    return priority_mapping.get(user_plan, TASK_PRIORITY_NORMAL)


# Celery signals for monitoring
@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery setup."""
    logger.info(f"Request: {self.request!r}")
    return "Celery is working!"


# ------------------------------------------------------------------ #
#  Worker process initialisation signal                               #
# ------------------------------------------------------------------ #


@worker_process_init.connect
def init_worker_process(sender=None, **kwargs):
    """
    Called once per Celery worker OS process on startup.
    Initialises both the synchronous Redis client (for event_publisher)
    and the async Redis clients (for cleanup/health tasks that use asyncio.run()).
    """
    try:
        from ..workers.event_publisher import initialize_worker_redis
        initialize_worker_redis(
            redis_url=settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
        )
        logger.info("Worker process: event publisher Redis initialised")
    except Exception as exc:
        logger.error(f"Worker process: failed to initialise Redis: {exc}")
        raise

    # Also init async Redis so tasks using asyncio.run(redis_manager.*()) work
    try:
        import asyncio  # noqa: I001

        from ..core.redis import redis_manager
        asyncio.run(redis_manager.init_redis())
        logger.info("Worker process: async Redis initialised")
    except Exception as exc:
        logger.warning(f"Worker process: async Redis init failed (non-critical): {exc}")


def _extract_job_id(args, kwargs) -> str | None:
    candidates = [kwargs]
    candidates.extend(item for item in args if isinstance(item, dict))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("job_id", "resume_id", "compilation_id"):
            value = candidate.get(key)
            if value:
                return str(value)
    return None


def _extract_queue_name(task) -> str:
    delivery_info = getattr(task.request, "delivery_info", {}) or {}
    return delivery_info.get("routing_key") or delivery_info.get("exchange") or "default"


@task_prerun.connect
def on_task_prerun(task_id=None, task=None, args=None, kwargs=None, **_unused):
    """Attach correlation context and start timing for Celery tasks."""
    if task is None or task_id is None:
        return

    queue_name = _extract_queue_name(task)
    job_id = _extract_job_id(args or (), kwargs or {})
    context_tokens = set_task_context(
        task_id=str(task_id),
        task_name=task.name,
        queue_name=queue_name,
        job_id=job_id,
    )
    setattr(task.request, "_latexy_context_tokens", context_tokens)
    _task_start_times[str(task_id)] = perf_counter()
    logger.info(
        "celery_task_started",
        extra={"queue": queue_name, "job_id": job_id},
    )


@task_postrun.connect
def on_task_postrun(task_id=None, task=None, args=None, kwargs=None, state=None, **_unused):
    """Record task completion metrics and clear context.

    JOB-01: When a task ends in FAILURE or REVOKED we write a terminal
    "failed" state snapshot to Redis so the job never stays stuck in
    "processing" state (e.g. after a worker OOM-kill or SIGKILL).
    """
    if task is None or task_id is None:
        return

    queue_name = _extract_queue_name(task)
    duration = perf_counter() - _task_start_times.pop(str(task_id), perf_counter())
    status = (state or "unknown").lower()
    record_celery_task(task_name=task.name, queue_name=queue_name, status=status, duration_seconds=duration)
    logger.info(
        "celery_task_finished",
        extra={
            "queue": queue_name,
            "status_code": status,
            "latency_seconds": round(duration, 6),
        },
    )
    context_tokens = getattr(task.request, "_latexy_context_tokens", None)
    if context_tokens:
        reset_context(context_tokens)

    # JOB-01: Ensure abnormally terminated jobs are marked failed in Redis
    # so consumers never see a perpetual "processing" state.
    if state in ("FAILURE", "REVOKED"):
        job_id = _extract_job_id(args or (), kwargs or {})
        if job_id:
            try:
                from ..workers.event_publisher import get_worker_redis, publish_event

                r = get_worker_redis()
                # Only write the failed state if the result key is absent —
                # a properly handled task will have already published its own
                # terminal event, so we must not overwrite it.
                result_key = f"latexy:job:{job_id}:result"
                if not r.exists(result_key):
                    reason = "Task was revoked" if state == "REVOKED" else "Task ended abnormally"
                    publish_event(
                        job_id=job_id,
                        event_type="job.failed",
                        payload_extra={
                            "stage": "worker",
                            "percent": 0,
                            "error": reason,
                            "task_id": str(task_id),
                            "task_name": task.name,
                        },
                    )
                    logger.warning(
                        "celery_task_stuck_job_recovered",
                        extra={"job_id": job_id, "task_state": state},
                    )
            except Exception as exc:
                # Best-effort — never crash the signal handler
                logger.error(f"JOB-01 recovery failed for job {job_id}: {exc}")


@task_failure.connect
def on_task_failure(
    task_id=None,
    exception=None,
    traceback=None,
    einfo=None,
    sender=None,
    args=None,
    kwargs=None,
    **_unused,
):
    """Emit structured failure logs for failed Celery tasks.

    CW-002 (dead-letter queue): When a task has exhausted all retries we
    publish a "job.failed" event and write the task details to a per-task
    Redis dead-letter list (latexy:dlq:{task_name}) for post-mortem
    inspection.

    CW-008 (poison messages): TypeError / ValueError on task entry almost
    always means a malformed payload was enqueued.  We log these at ERROR
    with a distinct marker so they can be filtered and the offending
    message identified without reprocessing the whole queue.
    """
    task = sender
    if task is None or task_id is None:
        return

    queue_name = _extract_queue_name(task)

    # CW-008: Detect likely poison/malformed messages early so they can be
    # triaged separately from genuine runtime errors.  TypeError and
    # ValueError at the start of a task execution almost always indicate
    # that the enqueued payload does not match the task signature (e.g. a
    # missing required argument, wrong type, or JSON that failed to
    # deserialise into the expected structure).
    if isinstance(exception, (TypeError, ValueError)):
        logger.error(
            "celery_task_poison_message_detected",
            extra={
                "queue": queue_name,
                "task_name": task.name,
                "task_id": str(task_id),
                "exception_type": type(exception).__name__,
                "exception": str(exception),
                # args/kwargs may contain the raw payload — log for triage
                "task_args": repr(args),
                "task_kwargs": repr(kwargs),
            },
            exc_info=(type(exception), exception, traceback) if exception and traceback else None,
        )
    else:
        logger.error(
            "celery_task_failed",
            extra={
                "queue": queue_name,
                "status_code": "failed",
                "latency_seconds": None,
            },
            exc_info=(type(exception), exception, traceback) if exception and traceback else None,
        )

    # CW-002: Dead-letter queue — fires only when retries are exhausted.
    # task.max_retries may be None (no limit) in which we skip DLQ logic.
    max_retries = getattr(task, "max_retries", None)
    current_retries = getattr(task.request, "retries", 0)
    retries_exhausted = (
        max_retries is not None and current_retries >= max_retries
    )
    if retries_exhausted:
        job_id = _extract_job_id(args or (), kwargs or {})
        error_str = str(exception) if exception else "unknown error"

        # 1. Publish a terminal job.failed event so the frontend unblocks.
        if job_id:
            try:
                from ..workers.event_publisher import get_worker_redis, publish_event

                r = get_worker_redis()
                result_key = f"latexy:job:{job_id}:result"
                if not r.exists(result_key):
                    publish_event(
                        job_id=job_id,
                        event_type="job.failed",
                        payload_extra={
                            "stage": "worker",
                            "percent": 0,
                            "error": f"Task failed after {current_retries} retries: {error_str}",
                            "task_id": str(task_id),
                            "task_name": task.name,
                        },
                    )
            except Exception as pub_exc:
                logger.error(f"CW-002: failed to publish job.failed for {job_id}: {pub_exc}")

        # 2. Write to the dead-letter list for debugging.
        try:
            import json as _json

            from ..workers.event_publisher import get_worker_redis

            r = get_worker_redis()
            dlq_key = f"latexy:dlq:{task.name}"
            dlq_entry = _json.dumps(
                {
                    "task_id": str(task_id),
                    "task_name": task.name,
                    "job_id": job_id,
                    "retries": current_retries,
                    "max_retries": max_retries,
                    "error": error_str,
                    "exception_type": type(exception).__name__ if exception else None,
                    "args": repr(args),
                    "kwargs": repr(kwargs),
                    "timestamp": __import__("time").time(),
                }
            )
            # Keep the most recent 500 dead-letter entries per task type
            r.lpush(dlq_key, dlq_entry)
            r.ltrim(dlq_key, 0, 499)
            r.expire(dlq_key, 7 * 86400)  # 7-day retention
            logger.error(
                "celery_task_dead_lettered",
                extra={
                    "dlq_key": dlq_key,
                    "job_id": job_id,
                    "retries": current_retries,
                    "error": error_str,
                },
            )
        except Exception as dlq_exc:
            logger.error(f"CW-002: failed to write DLQ entry for {task.name}/{task_id}: {dlq_exc}")


# Import tasks to register them
try:
    from ..workers import (  # noqa: F401
        ats_worker,
        auto_save_worker,
        cleanup_worker,
        converter_worker,
        cover_letter_worker,
        email_worker,
        interview_prep_worker,
        latex_worker,
        llm_worker,
        orchestrator,
    )
    logger.info("Celery workers imported successfully")
except ImportError as e:
    logger.error(f"Failed to import required workers: {e}")
    raise

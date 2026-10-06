"""
Celery application configuration for Phase 8.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from time import perf_counter

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    task_failure,
    task_postrun,
    task_prerun,
    worker_process_init,
    worker_process_shutdown,
)

from ..core.config import settings
from ..core.logging import get_logger
from ..core.observability import (
    record_celery_task,
    reset_context,
    set_queue_depth,
    set_task_context,
)
from ..core.tracing import instrument_celery, setup_telemetry

setup_telemetry("worker")
instrument_celery()
logger = get_logger(__name__)
_task_start_times: dict[str, float] = {}


def _safe_celery_identifier(value) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    if not all(char.isalnum() or char in ".-_" for char in value):
        return None
    return value


class _CeleryTracePrivacyFilter(logging.Filter):
    """Prevent Celery's built-in tracer from logging caller-controlled data.

    Celery 5.6's ``build_tracer`` logs ``saferepr(result)`` as well as
    ``safe_repr(args/kwargs)`` on the success path, and formats exception and
    traceback text on failure.  These values are useful to Celery itself (the
    original return value is still stored in the backend), but must never be
    emitted to a worker log.  This filter runs on Celery's trace/request/
    strategy loggers and strips both interpolated arguments and the
    ``extra['data']`` context before records propagate to application handlers.
    It deliberately preserves only the event class, not arbitrary task names
    or IDs supplied by a caller.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name not in {"celery.app.trace", "celery.worker.request", "celery.worker.strategy"}:
            return True

        data = getattr(record, "data", None)
        if isinstance(data, dict):
            if "return_value" in data:
                state = "success"
            elif "traceback" in data or "exc" in data:
                state = "failure"
            elif "description" in data:
                state = "retry_or_internal"
            else:
                state = "task"
            record.msg = "celery_task_trace"
            record.args = ()
            safe_data = {"event": "celery_task_trace", "state": state}
            for field in ("id", "name"):
                safe_value = _safe_celery_identifier(data.get(field))
                if safe_value is not None:
                    safe_data[field] = safe_value
            runtime = data.get("runtime")
            if isinstance(runtime, (int, float)) and not isinstance(runtime, bool) and runtime == runtime:
                safe_data["runtime"] = runtime
            record.data = safe_data
        else:
            # Internal Celery diagnostics can interpolate exception objects
            # directly (for example process-cleanup failures).  Keep the
            # diagnostic marker but discard every caller-controlled argument.
            record.msg = "celery_task_trace_internal"
            record.args = ()
            if hasattr(record, "data"):
                record.data = {"event": "celery_task_trace_internal"}

        # A traceback's locals and exception text can contain prompts, source,
        # provider credentials, or generated document text.
        record.exc_info = None
        record.exc_text = None
        # ``logging.Formatter`` renders stack_info independently of exc_info;
        # leaving it populated would still expose caller-controlled source
        # snippets when Celery (or an application handler) requests stacks.
        record.stack_info = None
        return True


def _install_celery_trace_privacy_filter() -> None:
    """Install the tracer redaction once in each worker process/import."""
    from celery.app import trace as celery_trace

    for target in (
        celery_trace.logger,
        logging.getLogger("celery.worker.request"),
        logging.getLogger("celery.worker.strategy"),
    ):
        if not any(isinstance(item, _CeleryTracePrivacyFilter) for item in target.filters):
            target.addFilter(_CeleryTracePrivacyFilter())


_install_celery_trace_privacy_filter()


_CELERY_REDACTED_REPR = "<redacted>"


def _install_celery_event_privacy_guards() -> None:
    """Redact Celery protocol/event metadata without changing task payloads.

    Celery's producer puts ``argsrepr``/``kwargsrepr`` in protocol headers and
    task-sent events, while the worker's Request object reuses those values in
    task-received events.  Worker success/failure events also include the real
    return value or exception.  Patch only those metadata paths; the protocol
    body and backend result remain untouched, so task execution, callbacks, and
    result retrieval retain their original values.
    """
    from celery import signals as celery_signals
    from celery.app.amqp import AMQP
    from celery.worker.request import Request

    if not getattr(AMQP.as_task_v2, "_latexy_privacy_guard", False):
        original_as_task_v2 = AMQP.as_task_v2

        def safe_as_task_v2(self, *args, **kwargs):
            message = original_as_task_v2(self, *args, **kwargs)
            headers = dict(message.headers)
            headers["argsrepr"] = _CELERY_REDACTED_REPR
            headers["kwargsrepr"] = _CELERY_REDACTED_REPR
            sent_event = dict(message.sent_event) if message.sent_event else None
            if sent_event is not None:
                sent_event["args"] = _CELERY_REDACTED_REPR
                sent_event["kwargs"] = _CELERY_REDACTED_REPR
            return message._replace(headers=headers, sent_event=sent_event)

        safe_as_task_v2._latexy_privacy_guard = True
        AMQP.as_task_v2 = safe_as_task_v2

    if not getattr(Request.__init__, "_latexy_privacy_guard", False):
        original_request_init = Request.__init__

        def safe_request_init(self, *args, **kwargs):
            original_request_init(self, *args, **kwargs)
            self._argsrepr = _CELERY_REDACTED_REPR
            self._kwargsrepr = _CELERY_REDACTED_REPR

        safe_request_init._latexy_privacy_guard = True
        Request.__init__ = safe_request_init

    if not getattr(Request.send_event, "_latexy_privacy_guard", False):
        original_send_event = Request.send_event

        def safe_request_send_event(self, event_type, **fields):
            for field in ("args", "kwargs", "result", "exception", "traceback"):
                if field in fields:
                    fields[field] = _CELERY_REDACTED_REPR
            return original_send_event(self, event_type, **fields)

        safe_request_send_event._latexy_privacy_guard = True
        Request.send_event = safe_request_send_event

    # Celery's deprecated ``task_sent`` signal still receives the raw body
    # even when protocol headers/events are redacted. Preserve the signal and
    # sender identity, but expose only structural placeholders to receivers.
    task_sent_send = celery_signals.task_sent.send
    if not getattr(task_sent_send, "_latexy_privacy_guard", False):
        def safe_task_sent_send(*args, **kwargs):
            for field in ("args", "kwargs"):
                if field in kwargs:
                    kwargs[field] = _CELERY_REDACTED_REPR
            return task_sent_send(*args, **kwargs)

        safe_task_sent_send._latexy_privacy_guard = True
        celery_signals.task_sent.send = safe_task_sent_send


_install_celery_event_privacy_guards()

# On Modal, worker tasks execute in-process (`.apply()`) and results are never
# read from the Celery backend, so we disable eager-result storage there.
_IS_MODAL = (settings.DEPLOY_TARGET or "").lower() == "modal"
# ``task_ignore_result`` controls persistence, but Celery's eager ``Task.apply``
# still touches ``task.backend`` while tracing. Passing a configured rediss URL
# here therefore initializes RedisBackend even though Modal never reads it (and
# can abort every wrapper before the task body runs). Explicitly select Celery's
# DisabledBackend on Modal so an environment-level result URL cannot override it.
_RESULT_BACKEND = "disabled://" if _IS_MODAL else settings.CELERY_RESULT_BACKEND
if _IS_MODAL:
    # Celery itself re-reads this environment variable and gives it precedence
    # over both constructor and runtime config. Override it process-locally;
    # Settings has already loaded, and Modal has no result consumer.
    os.environ["CELERY_RESULT_BACKEND"] = "disabled://"

# Create Celery instance
celery_app = Celery(
    "latexy",
    broker=settings.CELERY_BROKER_URL,
    backend=_RESULT_BACKEND,
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
        "app.workers.github_import_worker",
        "app.workers.tracker_notification_worker",
    ],
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
        "app.workers.github_import_worker.*": {"queue": "llm"},
        "app.workers.tracker_notification_worker.*": {"queue": "email"},
    },
    # Task configuration
    task_always_eager=False,
    task_eager_propagates=True,
    # On Modal, tasks run in-process via `.apply()` and job state/results are
    # published to Redis directly by the event_publisher — we never read the
    # Celery result backend. Storing eager results there makes Celery connect to
    # CELERY_RESULT_BACKEND (localhost by default on Modal), which raises
    # ConnectionError on every task and *fails* cold-start compiles. Disable
    # result storage on Modal to avoid the wasted round-trip and the failures.
    task_ignore_result=_IS_MODAL,
    task_store_eager_result=not _IS_MODAL,
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
        "comment-mention-delivery-recovery": {
            "task": "app.workers.email_worker.send_pending_comment_mention_emails",
            "schedule": 60.0,
        },
        "document-email-delivery-recovery": {
            "task": "app.workers.email_worker.send_pending_document_email_deliveries",
            "schedule": 60.0,
        },
        "tracker-notifications": {
            "task": "app.workers.tracker_notification_worker.send_tracker_notifications",
            "schedule": 300.0,
        },
        # Observability — sample pending Celery queue depths every 20s.
        # Routed to the cleanup queue since a worker always consumes it.
        "sample-queue-depths": {
            "task": "app.core.celery_app.sample_queue_depths",
            "schedule": 20.0,
            "options": {"queue": "cleanup"},
        },
    },
    beat_schedule_filename="celerybeat-schedule",
    # Priority queues — Redis requires these transport options to honour the
    # `priority` kwarg passed to .apply_async().  Without this config the
    # broker processes tasks FIFO regardless of the priority value.
    broker_transport_options={
        "priority_steps": list(range(10)),  # 0 (highest) … 9 (lowest)
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
#  Queue-depth sampler (observability)                                #
# ------------------------------------------------------------------ #

# Celery's Redis broker stores each queue as a Redis list keyed by the queue
# name, so LLEN <queue> yields the number of pending (not-yet-delivered)
# messages. These are the queues this deployment actually uses.
_SAMPLED_QUEUES = ("latex", "llm", "combined", "ats", "cleanup", "email")

_broker_redis_client = None


def _get_broker_redis():
    """Lazily build (and reuse) a sync Redis client pointed at the broker."""
    global _broker_redis_client
    if _broker_redis_client is None:
        import redis  # local import — only needed by the sampler

        _broker_redis_client = redis.from_url(
            settings.CELERY_BROKER_URL,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=10,
            retry_on_timeout=True,
        )
    return _broker_redis_client


def _close_broker_redis() -> None:
    """Close and forget the queue-depth sampler client for this process."""
    global _broker_redis_client
    client = _broker_redis_client
    _broker_redis_client = None
    if client is not None:
        client.close()


@celery_app.task(name="app.core.celery_app.sample_queue_depths")
def sample_queue_depths():
    """Sample pending depth of each Celery queue and export it as a gauge.

    Runs periodically via the beat schedule. Defensive: a Redis hiccup on any
    single queue is logged and skipped rather than crashing the beat/worker.
    """
    sampled: dict[str, int] = {}
    try:
        r = _get_broker_redis()
    except Exception as exc:  # noqa: BLE001 — never crash the scheduler
        logger.warning("queue-depth sampler: broker Redis unavailable", extra={"error_type": type(exc).__name__})
        return sampled

    for queue in _SAMPLED_QUEUES:
        try:
            depth = int(r.llen(queue))
            set_queue_depth(queue, depth)
            sampled[queue] = depth
        except Exception as exc:  # noqa: BLE001 — per-queue best effort
            logger.warning("queue-depth sampler: LLEN failed", extra={"error_type": type(exc).__name__})
    return sampled


# ------------------------------------------------------------------ #
#  Worker process initialisation signal                               #
# ------------------------------------------------------------------ #


def _install_darwin_fork_safe_resolver() -> None:
    """
    Pin DNS resolution to IPv4 inside prefork children on macOS.

    macOS resolves AF_UNSPEC lookups through Network.framework's NAT64
    synthesis pass (getaddrinfo -> _gai_nat64_second_pass ->
    nw_path_evaluator_evaluate -> os_log_type_enabled). That path is not
    fork-safe: a prefork child inherits CoreFoundation/Network state from a
    multi-threaded parent and segfaults the first time it resolves an
    *external* hostname. The OS annotates the crash report itself with
    "*** multi-threaded process forked ***" and "crashed on child side of fork
    pre-exec".

    Only tasks that reach an external API trip it — the LLM/embedding calls to
    api.openai.com — which is why compile-only tasks (Redis/Postgres/MinIO are
    all localhost) survive while orchestrator and embed tasks die. Once a child
    dies billiard forks a replacement from the same parent, so the pool
    crash-loops and jobs never reach a terminal state: /download/{job_id} 404s
    and /jobs/{id}/state polls forever.

    Forcing family=AF_INET skips the NAT64 pass and is the only variant that
    survives a poisoned fork — AF_INET6 and AF_UNSPEC both still crash. Every
    endpoint the worker talks to is reachable over IPv4.

    No-op off Darwin, so Linux/Docker — where fork is safe and IPv6 may be
    required — keeps stock dual-stack resolution.
    """
    if sys.platform != "darwin" or getattr(socket, "_latexy_ipv4_only", False):
        return

    _stock_getaddrinfo = socket.getaddrinfo

    def _ipv4_only_getaddrinfo(host, port, family=socket.AF_UNSPEC, *args, **kwargs):
        if family == socket.AF_UNSPEC:
            family = socket.AF_INET
        return _stock_getaddrinfo(host, port, family, *args, **kwargs)

    # asyncio (and therefore asyncpg) resolves via socket.getaddrinfo in an
    # executor and looks the attribute up per call, so patching the module
    # covers sync and async callers alike.
    socket.getaddrinfo = _ipv4_only_getaddrinfo
    socket._latexy_stock_getaddrinfo = _stock_getaddrinfo
    socket._latexy_ipv4_only = True


@worker_process_init.connect
def init_worker_process(sender=None, **kwargs):
    """
    Called once per Celery worker OS process on startup.
    Initialises the synchronous Redis client used by event_publisher.

    Async Redis clients deliberately do not live in Celery worker globals:
    creating them with ``asyncio.run()`` binds their sockets to a loop that is
    closed as soon as this signal returns. Worker paths use the synchronous
    publisher/health clients or create and dispose task-local async resources.
    """
    # Must run before anything in this process resolves a hostname.
    _install_darwin_fork_safe_resolver()

    try:
        from ..core.redis import redis_manager
        from ..workers.event_publisher import initialize_worker_redis

        initialize_worker_redis(
            redis_url=settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
        )
        redis_manager.init_sync_redis()
        logger.info("Worker process: Redis clients initialised")
    except Exception as exc:
        logger.error("Worker process: failed to initialise Redis", extra={"error_type": type(exc).__name__})
        raise


@worker_process_shutdown.connect
def close_worker_process(sender=None, **kwargs):
    """Release worker-owned Redis pools before the child process exits."""
    from ..core.redis import redis_manager
    from ..workers.event_publisher import close_worker_redis

    cleanups = (
        ("event publisher", close_worker_redis),
        ("queue sampler", _close_broker_redis),
        ("core Redis", redis_manager.close_sync_redis),
    )
    for owner, cleanup in cleanups:
        try:
            cleanup()
        except Exception as exc:
            logger.warning("Worker process: failed to close %s client", owner, extra={"error_type": type(exc).__name__})


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


def _safe_payload_repr(value, max_len: int = 256) -> str:
    """Describe payload structure without retaining any caller-supplied text.

    Truncation is not redaction: even a short prefix can contain an entire API
    key. Do not inspect values, arbitrary dictionary keys, or their repr.
    """
    if isinstance(value, dict):
        known_fields = (
            "job_id", "resume_id", "compilation_id", "user_id", "latex_content",
            "job_description", "api_key", "quota_refund", "content", "prompt",
        )
        fields = [field for field in known_fields if field in value]
        return f"<mapping: {len(value)} fields; known fields: {','.join(fields)}>"[:max_len]
    if isinstance(value, (tuple, list)):
        return f"<sequence: {len(value)} items>"[:max_len]
    return "<absent>" if value is None else "<redacted payload>"


def _recover_failed_job(job_id: str, task_id: str, task_name: str, reason: str) -> bool:
    """Commit a fenced result before notifying clients of a task failure.

    A signal cannot take ownership from a different/expired worker. Rejected
    writes are left to orphan recovery; no signal performs an unfenced refund.
    """
    from ..workers.event_publisher import publish_event, publish_job_result

    accepted = publish_job_result(job_id, {
        "success": False,
        "error": reason,
        "error_type": "worker_failure",
    })
    if accepted:
        publish_event(
            job_id=job_id,
            event_type="job.failed",
            payload_extra={
                "stage": "worker", "percent": 0, "error": reason,
                "task_id": task_id, "task_name": task_name,
            },
        )
    return accepted


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
    """Always release this invocation's ownership, including signal failures."""
    job_id = _extract_job_id(args or (), kwargs or {})
    try:
        _record_task_postrun(task_id, task, args, kwargs, state)
    finally:
        if job_id:
            from ..workers.job_lifecycle import clear_current_owner, stop_lease_heartbeat

            try:
                stop_lease_heartbeat(job_id)
            finally:
                clear_current_owner(job_id)


def _record_task_postrun(task_id=None, task=None, args=None, kwargs=None, state=None):
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
                from ..workers.event_publisher import get_worker_redis

                r = get_worker_redis()
                # Only write the failed state if the result key is absent —
                # a properly handled task will have already published its own
                # terminal event, so we must not overwrite it.
                result_key = f"latexy:job:{job_id}:result"
                if not r.exists(result_key):
                    reason = "Task was revoked" if state == "REVOKED" else "Task ended abnormally"
                    if _recover_failed_job(job_id, str(task_id), task.name, reason):
                        logger.warning(
                            "celery_task_stuck_job_recovered",
                            extra={"job_id": job_id, "task_state": state},
                        )
            except Exception as exc:
                # Best-effort — never crash the signal handler
                logger.error("JOB-01 recovery failed for job %s", job_id, extra={"error_type": type(exc).__name__})


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
                # Retain structural diagnostics, never values or exception text.
                "task_args": _safe_payload_repr(args),
                "task_kwargs": _safe_payload_repr(kwargs),
            },
        )
    else:
        logger.error(
            "celery_task_failed",
            extra={
                "queue": queue_name,
                "status_code": "failed",
                "latency_seconds": None,
                "exception_type": type(exception).__name__ if exception else None,
            },
        )

    # CW-002: Dead-letter queue — fires only when retries are exhausted.
    # task.max_retries may be None (no limit) in which we skip DLQ logic.
    max_retries = getattr(task, "max_retries", None)
    current_retries = getattr(task.request, "retries", 0)
    retries_exhausted = max_retries is not None and current_retries >= max_retries
    if retries_exhausted:
        job_id = _extract_job_id(args or (), kwargs or {})
        error_str = "Task failed after exhausting retries. Please try again."

        # 1. Publish a terminal job.failed event so the frontend unblocks.
        if job_id:
            try:
                from ..workers.event_publisher import get_worker_redis

                r = get_worker_redis()
                result_key = f"latexy:job:{job_id}:result"
                if not r.exists(result_key):
                    _recover_failed_job(job_id, str(task_id), task.name, error_str)
            except Exception as pub_exc:
                logger.error("CW-002: failed to publish task failure", extra={"error_type": type(pub_exc).__name__})

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
                    # Structural diagnostics only: entries persist for 7 days.
                    "args": _safe_payload_repr(args),
                    "kwargs": _safe_payload_repr(kwargs),
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
            logger.error("CW-002: failed to write DLQ entry", extra={"error_type": type(dlq_exc).__name__})


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
    logger.error("Failed to import required workers", extra={"error_type": type(e).__name__})
    raise

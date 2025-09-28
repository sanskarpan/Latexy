"""
Celery application configuration for Phase 8.
"""

from celery import Celery
from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# Create Celery instance
celery_app = Celery(
    "latexy",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.latex_worker",
        "app.workers.llm_worker", 
        "app.workers.email_worker",
        "app.workers.cleanup_worker"
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
            "task": "app.workers.cleanup_worker.cleanup_expired_jobs",
            "schedule": 3600.0,  # Run every hour
        },
        "cleanup-temp-files": {
            "task": "app.workers.cleanup_worker.cleanup_temp_files",
            "schedule": 1800.0,  # Run every 30 minutes
        },
        "health-check": {
            "task": "app.workers.cleanup_worker.health_check",
            "schedule": 300.0,  # Run every 5 minutes
        },
    },
    beat_schedule_filename="celerybeat-schedule",
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
    
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
}


def get_task_priority(user_plan: str = "free") -> int:
    """Get task priority based on user plan."""
    priority_mapping = {
        "free": TASK_PRIORITY_LOW,
        "basic": TASK_PRIORITY_NORMAL,
        "pro": TASK_PRIORITY_HIGH,
        "byok": TASK_PRIORITY_HIGH,
    }
    return priority_mapping.get(user_plan, TASK_PRIORITY_NORMAL)


# Celery signals for monitoring
@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery setup."""
    logger.info(f"Request: {self.request!r}")
    return "Celery is working!"


# Import tasks to register them
try:
    from ..workers import latex_worker, llm_worker, email_worker, cleanup_worker
    logger.info("Celery workers imported successfully")
except ImportError as e:
    logger.warning(f"Could not import some workers: {e}")

"""
Workers package for Phase 8 - Async job processing.
"""

from .ats_worker import (
    analyze_job_description_ats_task,
    deep_analyze_ats_task,
    embed_resume_task,
    score_resume_ats_task,
)
from .cleanup_worker import cleanup_expired_jobs_task, cleanup_temp_files_task
from .email_worker import send_completion_email_task, send_notification_email_task
from .latex_worker import compile_latex_task
from .llm_worker import optimize_resume_task

__all__ = [
    "compile_latex_task",
    "optimize_resume_task",
    "send_notification_email_task",
    "send_completion_email_task",
    "cleanup_temp_files_task",
    "cleanup_expired_jobs_task",
    "score_resume_ats_task",
    "analyze_job_description_ats_task",
    "deep_analyze_ats_task",
    "embed_resume_task",
]

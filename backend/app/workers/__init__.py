"""
Workers package for Phase 8 - Async job processing.
"""

from .latex_worker import compile_latex_task, compile_latex_with_optimization_task
from .llm_worker import optimize_resume_task, analyze_job_description_task
from .email_worker import send_notification_email_task, send_completion_email_task
from .cleanup_worker import cleanup_temp_files_task, cleanup_expired_jobs_task
from .ats_worker import score_resume_ats_task, analyze_job_description_ats_task

__all__ = [
    "compile_latex_task",
    "compile_latex_with_optimization_task", 
    "optimize_resume_task",
    "analyze_job_description_task",
    "send_notification_email_task",
    "send_completion_email_task",
    "cleanup_temp_files_task",
    "cleanup_expired_jobs_task",
    "score_resume_ats_task",
    "analyze_job_description_ats_task",
]

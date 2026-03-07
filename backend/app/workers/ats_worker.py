"""
ATS Scoring worker — event-driven rebuild.

Replaces asyncio.run(job_status_manager.*) calls with publish_event().
The ATS scoring service call itself uses asyncio.run() because
ats_scoring_service.score_resume() is async but contains only pure
Python CPU work (no Redis, no network I/O), making it safe to call
from a sync Celery worker.
"""

import asyncio
import re
import time
import uuid
from typing import Dict, Any, Optional

from ..core.celery_app import celery_app, get_task_priority
from ..core.logging import get_logger
from ..services.ats_scoring_service import ats_scoring_service
from ..workers.event_publisher import publish_event, publish_job_result, is_cancelled

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.ats_worker.score_resume_ats_task",
    max_retries=2,
    default_retry_delay=60,
)
def score_resume_ats_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Score resume for ATS compatibility, publishing progress events.

    Publishes:
      job.started    — when worker picks up the task
      job.progress   — intermediate milestones
      job.completed  — with ATS score and details
      job.failed     — on any error
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"ats-{task_id}"
    logger.info(f"ATS task {task_id} starting for job {job_id}")

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "ats_scoring",
    })

    try:
        if not latex_content or not latex_content.strip():
            error_msg = "LaTeX content is required for ATS scoring"
            publish_event(job_id, "job.failed", {
                "stage": "ats_scoring",
                "error_code": "latex_error",
                "error_message": error_msg,
                "retryable": False,
            })
            return {"success": False, "job_id": job_id, "error": error_msg}

        publish_event(job_id, "job.progress", {
            "percent": 20,
            "stage": "ats_scoring",
            "message": "Analyzing resume content",
        })

        # score_resume is async but pure-Python — safe to call once with asyncio.run()
        start_time = time.time()
        scoring_result = asyncio.run(
            ats_scoring_service.score_resume(
                latex_content=latex_content,
                job_description=job_description,
                industry=industry,
            )
        )
        scoring_time = time.time() - start_time

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "ats_scoring",
            "message": f"Scoring complete: {scoring_result.overall_score:.1f}/100",
        })

        ats_details = {
            "category_scores": scoring_result.category_scores,
            "recommendations": scoring_result.recommendations,
            "strengths": scoring_result.strengths,
            "warnings": scoring_result.warnings,
        }

        result = {
            "success": True,
            "job_id": job_id,
            "ats_score": scoring_result.overall_score,
            "ats_details": ats_details,
            "scoring_time": scoring_time,
            "detailed_analysis": scoring_result.detailed_analysis,
            "user_id": user_id,
            "device_fingerprint": device_fingerprint,
            "industry": industry,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": scoring_result.overall_score,
            "ats_details": ats_details,
            "changes_made": [],
            "compilation_time": 0.0,
            "optimization_time": 0.0,
            "tokens_used": 0,
        })
        logger.info(
            f"ATS task {task_id} succeeded for job {job_id}: "
            f"{scoring_result.overall_score:.1f}/100"
        )
        return result

    except Exception as exc:
        logger.error(f"ATS task {task_id} raised: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "ats_scoring",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=60, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


@celery_app.task(
    bind=True,
    name="app.workers.ats_worker.analyze_job_description_ats_task",
    max_retries=2,
    default_retry_delay=30,
)
def analyze_job_description_ats_task(
    self,
    job_description: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Extract keywords and requirements from a job description."""
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"ats-jd-{task_id}"
    logger.info(f"ATS JD analysis task {task_id} starting for job {job_id}")

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "ats_scoring",
    })

    try:
        if not job_description or not job_description.strip():
            error_msg = "Job description is required for analysis"
            publish_event(job_id, "job.failed", {
                "stage": "ats_scoring",
                "error_code": "latex_error",
                "error_message": error_msg,
                "retryable": False,
            })
            return {"success": False, "job_id": job_id, "error": error_msg}

        publish_event(job_id, "job.progress", {
            "percent": 20,
            "stage": "ats_scoring",
            "message": "Analyzing job description",
        })

        start_time = time.time()
        keywords = ats_scoring_service._extract_keywords_from_job_description(  # noqa: SLF001
            job_description
        )

        words = job_description.split()
        sentences = job_description.split(".")

        requirement_patterns = [
            r"required?:?\s*([^.]+)",
            r"must have:?\s*([^.]+)",
            r"essential:?\s*([^.]+)",
            r"minimum:?\s*([^.]+)",
        ]
        requirements: list[str] = []
        for pattern in requirement_patterns:
            requirements.extend(re.findall(pattern, job_description, re.IGNORECASE))

        preferred_patterns = [
            r"preferred?:?\s*([^.]+)",
            r"nice to have:?\s*([^.]+)",
            r"bonus:?\s*([^.]+)",
            r"plus:?\s*([^.]+)",
        ]
        preferred: list[str] = []
        for pattern in preferred_patterns:
            preferred.extend(re.findall(pattern, job_description, re.IGNORECASE))

        industry_indicators = {
            "technology": ["software", "programming", "development", "tech", "IT"],
            "finance": ["financial", "banking", "investment", "accounting"],
            "healthcare": ["medical", "healthcare", "clinical", "patient"],
            "marketing": ["marketing", "advertising", "brand", "campaign"],
            "sales": ["sales", "revenue", "client", "customer"],
        }
        detected_industry = "general"
        for ind, indicators in industry_indicators.items():
            if any(i.lower() in job_description.lower() for i in indicators):
                detected_industry = ind
                break

        analysis_time = time.time() - start_time

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "ats_scoring",
            "message": "Analysis complete",
        })

        result = {
            "success": True,
            "job_id": job_id,
            "keywords": keywords[:15],
            "requirements": requirements[:10],
            "preferred_qualifications": preferred[:10],
            "detected_industry": detected_industry,
            "analysis_metrics": {
                "word_count": len(words),
                "sentence_count": len(sentences),
                "keyword_count": len(keywords),
            },
            "analysis_time": analysis_time,
            "user_id": user_id,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": 0.0,
            "ats_details": {"detected_industry": detected_industry},
            "changes_made": [],
            "compilation_time": 0.0,
            "optimization_time": 0.0,
            "tokens_used": 0,
        })
        return result

    except Exception as exc:
        logger.error(f"ATS JD analysis task {task_id} raised: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "ats_scoring",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ------------------------------------------------------------------ #
#  Submission helpers                                                  #
# ------------------------------------------------------------------ #

def submit_ats_scoring(
    latex_content: str,
    job_id: str,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue score_resume_ats_task on the ats queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    score_resume_ats_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_id": job_id,
            "job_description": job_description,
            "industry": industry,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
        },
        priority=priority,
        queue="ats",
    )
    logger.info(f"Submitted ATS scoring for job {job_id}")
    return job_id


def submit_job_description_analysis(
    job_description: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue analyze_job_description_ats_task on the ats queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    analyze_job_description_ats_task.apply_async(
        args=[job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "metadata": metadata,
        },
        priority=priority,
        queue="ats",
    )
    logger.info(f"Submitted JD analysis for job {job_id}")
    return job_id

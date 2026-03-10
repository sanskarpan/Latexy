"""
LaTeX compilation worker — event-driven rebuild.

Streams pdflatex log lines via publish_event() instead of collecting
them all at once.  Uses subprocess.Popen for line-by-line stdout
streaming.  Zero asyncio — all Redis I/O goes through event_publisher.
"""

import uuid
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.latex_service import latex_service
from ..workers.event_publisher import publish_event, publish_job_result

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.latex_worker.compile_latex_task",
    max_retries=3,
    default_retry_delay=60,
)
def compile_latex_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Compile LaTeX content to PDF, streaming each pdflatex log line as
    a log.line event.  Publishes job.completed on success or job.failed
    on error.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"latex-{task_id}"
    logger.info(f"LaTeX task {task_id} starting for job {job_id}")

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "latex_compilation",
    })

    try:
        # ── Validation ──────────────────────────────────────────────
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "latex_compilation",
            "message": "Validating LaTeX content",
        })

        if not latex_service.validate_latex_content(latex_content):
            error_msg = (
                r"Invalid LaTeX: missing \documentclass, "
                r"\begin{document}, or \end{document}"
            )
            publish_event(job_id, "job.failed", {
                "stage": "latex_compilation",
                "error_code": "latex_error",
                "error_message": error_msg,
                "retryable": False,
            })
            return {"success": False, "job_id": job_id, "error": error_msg}

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "latex_compilation",
            "message": "Starting pdflatex compilation",
        })

        # ── Compile via shared helper ────────────────────────────────
        from ..services.latex_service import run_latex_subprocess
        ok, compilation_time, error_msg = run_latex_subprocess(
            job_id=job_id,
            latex_content=latex_content,
            timeout=float(settings.COMPILE_TIMEOUT),
        )

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "latex_compilation",
            "message": "Finalizing PDF",
        })

        # ── Success / failure ────────────────────────────────────────
        job_dir = settings.TEMP_DIR / job_id
        pdf_file = job_dir / "resume.pdf"

        if ok and pdf_file.exists():
            pdf_size = pdf_file.stat().st_size
            result = {
                "success": True,
                "job_id": job_id,
                "pdf_job_id": job_id,
                "compilation_time": compilation_time,
                "pdf_size": pdf_size,
            }
            publish_job_result(job_id, result)
            publish_event(job_id, "job.completed", {
                "pdf_job_id": job_id,
                "ats_score": 0.0,
                "ats_details": {},
                "changes_made": [],
                "compilation_time": compilation_time,
                "optimization_time": 0.0,
                "tokens_used": 0,
            })
            logger.info(
                f"LaTeX task {task_id} succeeded for job {job_id} ({pdf_size} bytes)"
            )
            return result

        publish_event(job_id, "job.failed", {
            "stage": "latex_compilation",
            "error_code": "latex_error",
            "error_message": error_msg,
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": error_msg}

    except Exception as exc:
        logger.error(f"LaTeX task {task_id} raised: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "latex_compilation",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=60, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_latex_compilation(
    latex_content: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue compile_latex_task on the latex queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    compile_latex_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
        },
        priority=priority,
        queue="latex",
    )
    logger.info(f"Submitted LaTeX compilation for job {job_id}")
    return job_id

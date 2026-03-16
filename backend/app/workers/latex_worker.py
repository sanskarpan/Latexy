"""
LaTeX compilation worker — event-driven rebuild.

Streams pdflatex log lines via publish_event() instead of collecting
them all at once.  Uses subprocess.Popen for line-by-line stdout
streaming.  Zero asyncio — all Redis I/O goes through event_publisher.
"""

import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.latex_service import latex_service
from ..workers.event_publisher import is_cancelled, publish_event, publish_job_result

logger = get_logger(__name__)

PAGE_COUNT_RE = re.compile(r"Output written on .*?\((\d+) page", re.IGNORECASE)


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
    resume_id: Optional[str] = None,
    compiler: str = "pdflatex",
) -> Dict[str, Any]:
    """
    Compile LaTeX content to PDF, streaming each pdflatex log line as
    a log.line event.  Publishes job.completed on success or job.failed
    on error.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    # Validate and sanitise compiler choice
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        logger.warning(f"Invalid compiler '{compiler}', falling back to pdflatex")
        compiler = settings.DEFAULT_LATEX_COMPILER

    task_id = self.request.id
    worker_id = f"latex-{task_id}"
    logger.info(f"LaTeX task {task_id} starting for job {job_id} (compiler={compiler})")

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

        # ── Setup ────────────────────────────────────────────────────
        job_dir = Path(settings.TEMP_DIR) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        tex_file = job_dir / "resume.tex"
        tex_file.write_text(latex_content, encoding="utf-8")

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "latex_compilation",
            "message": f"Starting {compiler} compilation",
        })

        # ── Compile ──────────────────────────────────────────────────
        cmd = [
            compiler,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-synctex=1",
            "-output-directory", str(job_dir),
            str(tex_file),
        ]

        try:
            timeout = float(settings.COMPILE_TIMEOUT)
        except (TypeError, ValueError, AttributeError):
            timeout = 120.0

        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(job_dir),
        )

        # ── Stream log lines ─────────────────────────────────────────
        page_count: Optional[int] = None
        for line in proc.stdout:
            stripped = line.rstrip()
            if not stripped:
                continue

            # Extract page count from pdflatex summary line
            m = PAGE_COUNT_RE.search(stripped)
            if m:
                page_count = int(m.group(1))

            is_error_line = (
                "error" in stripped.lower()
                or stripped.startswith("!")
                or "fatal" in stripped.lower()
            )
            publish_event(job_id, "log.line", {
                "line": stripped,
                "source": "pdflatex",
                "is_error": is_error_line,
            })

            # ── Cancellation check ───────────────────────────────────
            if is_cancelled(job_id):
                proc.kill()
                publish_event(job_id, "job.cancelled", {})
                return {"success": False, "job_id": job_id, "cancelled": True}

            # ── Timeout check ────────────────────────────────────────
            if time.time() - start_time > timeout:
                proc.kill()
                publish_event(job_id, "job.failed", {
                    "stage": "latex_compilation",
                    "error_code": "timeout",
                    "error_message": f"LaTeX compilation timed out after {timeout}s",
                    "retryable": False,
                })
                return {"success": False, "job_id": job_id, "error": "timeout"}

        proc.wait()
        compilation_time = time.time() - start_time

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "latex_compilation",
            "message": "Finalizing PDF",
        })

        # ── Success / failure ────────────────────────────────────────
        pdf_file = job_dir / "resume.pdf"

        if proc.returncode == 0 and pdf_file.exists():
            pdf_size = pdf_file.stat().st_size
            result = {
                "success": True,
                "job_id": job_id,
                "pdf_job_id": job_id,
                "compilation_time": compilation_time,
                "pdf_size": pdf_size,
                "page_count": page_count,
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
                "page_count": page_count,
                "compiler": compiler,
            })
            logger.info(
                f"LaTeX task {task_id} succeeded for job {job_id} ({pdf_size} bytes)"
            )

            # Auto-save checkpoint if resume_id is known
            _resume_id = resume_id or (metadata or {}).get("resume_id")
            if _resume_id and user_id:
                try:
                    from .auto_save_worker import record_auto_save_checkpoint
                    record_auto_save_checkpoint.apply_async(
                        args=[_resume_id, user_id, latex_content],
                        queue="cleanup",
                    )
                except Exception as auto_exc:
                    logger.warning(f"Failed to enqueue auto-save for resume {_resume_id}: {auto_exc}")

            return result

        error_msg = f"{compiler} exited with code {proc.returncode}"
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
    resume_id: Optional[str] = None,
    compiler: str = "pdflatex",
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
            "resume_id": resume_id,
            "compiler": compiler,
        },
        priority=priority,
        queue="latex",
    )
    logger.info(f"Submitted LaTeX compilation for job {job_id} (compiler={compiler})")
    return job_id

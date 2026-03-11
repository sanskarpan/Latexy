"""
Document conversion worker — converts parsed resume content to LaTeX using LLM.

Receives pre-extracted structured data (ParsedResume.to_dict()) so the
expensive I/O (file reading, parsing) happens synchronously in the API layer,
while only the LLM call runs async in the worker.
"""
import time
import uuid
from typing import Any, Dict, Optional

import openai

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.document_converter_service import document_converter_service
from ..workers.event_publisher import publish_event, publish_job_result

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.converter_worker.convert_document_task",
    max_retries=2,
    default_retry_delay=30,
    time_limit=120,
    soft_time_limit=100,
)
def convert_document_task(
    self,
    extracted_data: Dict,
    source_format: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_api_key: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Convert parsed resume data to LaTeX using LLM (gpt-4o-mini).

    Publishes:
      job.started    — when worker picks up the task
      job.progress   — at 15%, 40%, 90%
      job.completed  — when conversion is done (includes latex_content)
      job.failed     — on any error
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"converter-{task_id}"
    logger.info(f"Converter task {task_id} starting for job {job_id}, format={source_format}")

    api_key = user_api_key or settings.OPENAI_API_KEY

    if not api_key:
        publish_event(job_id, "job.failed", {
            "stage": "document_conversion",
            "error_code": "no_api_key",
            "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "No OpenAI API key configured"}

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "document_conversion",
    })

    try:
        publish_event(job_id, "job.progress", {
            "percent": 15,
            "stage": "document_conversion",
            "message": "Analyzing document structure",
        })

        messages = document_converter_service.build_conversion_prompt(extracted_data, source_format)

        publish_event(job_id, "job.progress", {
            "percent": 40,
            "stage": "document_conversion",
            "message": f"Generating LaTeX from {source_format.upper()} content",
        })

        start_time = time.time()
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=4096,
        )

        raw_latex = response.choices[0].message.content or ""
        latex_content = document_converter_service.clean_latex_output(raw_latex)
        conversion_time = time.time() - start_time
        tokens_used = response.usage.total_tokens if response.usage else 0

        is_valid, validation_error = document_converter_service.validate_latex_output(latex_content)
        if not is_valid:
            logger.warning(f"LLM returned invalid LaTeX for job {job_id}: {validation_error}")
            retryable = self.request.retries < self.max_retries
            publish_event(job_id, "job.failed", {
                "stage": "document_conversion",
                "error_code": "invalid_latex",
                "error_message": f"Generated LaTeX is invalid: {validation_error}",
                "retryable": retryable,
            })
            if retryable:
                raise self.retry(countdown=15)
            return {"success": False, "job_id": job_id, "error": validation_error}

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "document_conversion",
            "message": "Finalizing LaTeX output",
        })

        result = {
            "success": True,
            "job_id": job_id,
            "latex_content": latex_content,
            "source_format": source_format,
            "conversion_time": conversion_time,
            "tokens_used": tokens_used,
        }
        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "latex_content": latex_content,
            "source_format": source_format,
            "conversion_time": conversion_time,
            "tokens_used": tokens_used,
        })
        logger.info(
            f"Converter task {task_id} succeeded for job {job_id} "
            f"({tokens_used} tokens, {conversion_time:.1f}s)"
        )
        return result

    except openai.OpenAIError as exc:
        logger.error(f"OpenAI error in converter task {task_id}: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "document_conversion",
            "error_code": "llm_error",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}

    except Exception as exc:
        logger.error(f"Converter task {task_id} raised: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "document_conversion",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ─── Submission helper ────────────────────────────────────────────────────────

def submit_document_conversion(
    extracted_data: Dict,
    source_format: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_api_key: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue convert_document_task on the llm queue."""
    if priority is None:
        priority = get_task_priority("free")

    convert_document_task.apply_async(
        kwargs={
            "extracted_data": extracted_data,
            "source_format": source_format,
            "job_id": job_id,
            "user_id": user_id,
            "user_api_key": user_api_key,
            "metadata": metadata,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted document conversion for job {job_id} (format={source_format})")
    return job_id

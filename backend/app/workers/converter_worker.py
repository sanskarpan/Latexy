"""
Document conversion worker — converts parsed resume content to LaTeX using LLM.

Receives pre-extracted structured data (ParsedResume.to_dict()) so the
expensive I/O (file reading, parsing) happens synchronously in the API layer,
while only the LLM call runs async in the worker.
"""
import os
import time
import uuid
from typing import Any, Dict, Optional

import openai

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.document_converter_service import document_converter_service
from ..workers.event_publisher import (
    get_worker_redis,
    is_cancelled,
    publish_event,
    publish_job_result,
)
from ..workers.job_lifecycle import admit_worker, clear_current_owner, stop_lease_heartbeat
from ..workers.quota_refund import clear_quota_refund_receipt, refund_quota_once

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
    source_hint: Optional[str] = None,
    source_platform: Optional[str] = None,
    metadata: Optional[Dict] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
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

    lifecycle_owner = f"{worker_id}:{uuid.uuid4()}"
    owner_admitted = False
    if not admit_worker(get_worker_redis(), job_id, lifecycle_owner, quota_refund, user_id):
        # Do not refund a duplicate delivery while the admitted owner may
        # still be running; cleanup or that owner owns reconciliation.
        return {
            "success": False,
            "job_id": job_id,
            "error": "Job ownership unavailable",
        }
    owner_admitted = True

    def _release_owner() -> None:
        if owner_admitted:
            stop_lease_heartbeat(job_id)
            clear_current_owner(job_id)

    def _refund() -> None:
        if quota_refund:
            refund_quota_once(job_id, quota_refund, expected_dimension="ai_assists")

    def _terminal(
        result: Dict[str, Any],
        event_type: str,
        event_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            stored = publish_job_result(job_id, result)
        except Exception:
            _release_owner()
            raise
        if not stored:
            _release_owner()
            return result
        try:
            entry_id = publish_event(job_id, event_type, event_payload)
            if result.get("success") is True:
                if entry_id and quota_refund:
                    clear_quota_refund_receipt(job_id)
            else:
                # The accepted failed/cancelled result is the immutable
                # terminal decision. A missing/rejected event does not make it
                # safe to defer or skip the refund; a rejected result does.
                _refund()
        finally:
            _release_owner()
        return result

    api_key = user_api_key or settings.OPENAI_API_KEY

    if not api_key:
        return _terminal(
            {"success": False, "job_id": job_id, "error": "No OpenAI API key configured"},
            "job.failed",
            {
                "stage": "document_conversion",
                "error_code": "no_api_key",
                "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
                "retryable": False,
            },
        )

    try:
        publish_event(job_id, "job.started", {
            "worker_id": worker_id,
            "stage": "document_conversion",
        })
        publish_event(job_id, "job.progress", {
            "percent": 15,
            "stage": "document_conversion",
            "message": "Analyzing document structure",
        })

        messages = document_converter_service.build_conversion_prompt(
            extracted_data, source_format, source_hint=source_hint,
            source_platform=source_platform,
        )

        publish_event(job_id, "job.progress", {
            "percent": 40,
            "stage": "document_conversion",
            "message": f"Generating LaTeX from {source_format.upper()} content",
        })

        start_time = time.time()
        client = openai.OpenAI(api_key=api_key, timeout=60.0)
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
            if retryable:
                try:
                    publish_event(job_id, "job.retrying", {
                        "stage": "document_conversion",
                        "worker_id": worker_id,
                        "attempt": self.request.retries + 2,
                        "error_message": "Document conversion is retrying",
                    })
                finally:
                    _release_owner()
                raise self.retry(countdown=15)
            return _terminal(
                {"success": False, "job_id": job_id, "error": validation_error},
                "job.failed",
                {
                    "stage": "document_conversion",
                    "error_code": "invalid_latex",
                    "error_message": f"Generated LaTeX is invalid: {validation_error}",
                    "retryable": False,
                },
            )

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
        if is_cancelled(job_id):
            return _terminal(
                {"success": False, "job_id": job_id, "cancelled": True},
                "job.cancelled",
                {"stage": "document_conversion"},
            )
        if not publish_job_result(job_id, result):
            _release_owner()
            return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
        # Do NOT re-emit latex_content here — it's already persisted via publish_job_result.
        # The client fetches it from /jobs/{job_id}/result after seeing job.completed.
        entry_id = publish_event(job_id, "job.completed", {
            "source_format": source_format,
            "conversion_time": conversion_time,
            "tokens_used": tokens_used,
        })
        if quota_refund and not entry_id:
            _release_owner()
            return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
        if quota_refund:
            clear_quota_refund_receipt(job_id)
        _release_owner()
        logger.info(
            f"Converter task {task_id} succeeded for job {job_id} "
            f"({tokens_used} tokens, {conversion_time:.1f}s)"
        )
        return result

    except openai.OpenAIError as exc:
        logger.error("OpenAI error in converter task %s", task_id, extra={"error_type": type(exc).__name__})
        retryable = self.request.retries < self.max_retries
        if retryable:
            try:
                publish_event(job_id, "job.retrying", {
                    "stage": "document_conversion",
                    "worker_id": worker_id,
                    "attempt": self.request.retries + 2,
                    "error_message": "Document conversion is retrying",
                })
            finally:
                _release_owner()
            raise self.retry(countdown=30, exc=exc)
        return _terminal(
            {"success": False, "job_id": job_id, "error": "Conversion failed"},
            "job.failed",
            {
                "stage": "document_conversion",
                "error_code": "llm_error",
                "error_message": "Document conversion provider request failed",
                "retryable": False,
            },
        )

    except Exception as exc:
        # Re-raise Celery's own Retry sentinel so it isn't swallowed as an "internal" failure
        from celery.exceptions import Retry
        if isinstance(exc, Retry):
            _release_owner()
            raise
        logger.error("Converter task %s raised", task_id, extra={"error_type": type(exc).__name__})
        retryable = self.request.retries < self.max_retries
        if retryable:
            try:
                publish_event(job_id, "job.retrying", {
                    "stage": "document_conversion",
                    "worker_id": worker_id,
                    "attempt": self.request.retries + 2,
                    "error_message": "Document conversion is retrying",
                })
            finally:
                _release_owner()
            raise self.retry(countdown=30, exc=exc)
        return _terminal(
            {"success": False, "job_id": job_id, "error": "Conversion failed"},
            "job.failed",
            {
                "stage": "document_conversion",
                "error_code": "internal",
                "error_message": "Document conversion failed",
                "retryable": False,
            },
        )

    except BaseException:
        # Celery/provider cancellation may bypass ``Exception`` handlers.
        _release_owner()
        raise


# ─── Submission helper ────────────────────────────────────────────────────────

def submit_document_conversion(
    extracted_data: Dict,
    source_format: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_api_key: Optional[str] = None,
    source_hint: Optional[str] = None,
    source_platform: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
) -> str:
    """Enqueue convert_document_task on the llm queue."""
    if priority is None:
        priority = get_task_priority("free")

    # See submit_cover_letter_generation: no Celery consumer exists on Modal.
    # #951 added a quota charge to this path, so a silent drop here bills the
    # user for a conversion that never happens.
    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn
        spawn("run_document_conversion_task", {
            "extracted_data": extracted_data,
            "source_format": source_format,
            "job_id": job_id,
            "user_id": user_id,
            "user_api_key": user_api_key,
            "source_hint": source_hint,
            "source_platform": source_platform,
            "metadata": metadata,
            "quota_refund": quota_refund,
        })
        logger.info(f"Dispatched document conversion to Modal for job {job_id}")
        return job_id

    convert_document_task.apply_async(
        kwargs={
            "extracted_data": extracted_data,
            "source_format": source_format,
            "job_id": job_id,
            "user_id": user_id,
            "user_api_key": user_api_key,
            "source_hint": source_hint,
            "source_platform": source_platform,
            "metadata": metadata,
            "quota_refund": quota_refund,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted document conversion for job {job_id} (format={source_format})")
    return job_id

"""
LLM optimization worker — event-driven rebuild with OpenAI token streaming.

Uses the synchronous openai.OpenAI client (not AsyncOpenAI) with
stream=True so each token is published immediately as an llm.token
event.  Zero asyncio — all Redis I/O goes through event_publisher.
"""

import json
import re
import time
import uuid
from typing import Dict, Any, Optional

import openai

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.llm_service import llm_service
from ..workers.event_publisher import publish_event, publish_job_result, is_cancelled

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.llm_worker.optimize_resume_task",
    max_retries=2,
    default_retry_delay=120,
)
def optimize_resume_task(
    self,
    latex_content: str,
    job_description: Optional[str] = None,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Optimize a LaTeX resume using OpenAI with live token streaming.

    Publishes:
      job.started    — when worker picks up the task
      job.progress   — preparation steps
      llm.token      — every streamed token delta
      llm.complete   — full assembled content + total token count
      job.completed  — when optimization is done
      job.failed     — on any error
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"llm-{task_id}"
    logger.info(f"LLM task {task_id} starting for job {job_id}")

    api_key = user_api_key or settings.OPENAI_API_KEY

    # Validate API key BEFORE publishing job.started to avoid a confusing
    # started → immediately-failed event sequence on the frontend.
    if not api_key:
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "llm_error",
            "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
            "retryable": False,
        })
        return {
            "success": False,
            "job_id": job_id,
            "error": "No OpenAI API key configured",
        }

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "llm_optimization",
    })

    try:
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "llm_optimization",
            "message": "Building optimization prompt",
        })

        # Build prompt via llm_service helper (pure Python, no I/O)
        keywords = llm_service.extract_keywords_from_job_description(job_description)
        prompt = llm_service._create_optimization_prompt(  # noqa: SLF001
            latex_content, job_description, keywords, optimization_level
        )

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "llm_optimization",
            "message": "Streaming LLM response",
        })

        client = openai.OpenAI(api_key=api_key)
        start_time = time.time()
        accumulated = ""
        token_count = 0

        stream = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert resume optimizer specializing in ATS-friendly "
                        "LaTeX resumes. You help job seekers optimize their resumes for "
                        "specific job descriptions while maintaining professional formatting."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=settings.OPENAI_MAX_TOKENS,
            temperature=settings.OPENAI_TEMPERATURE,
            stream=True,
            stream_options={"include_usage": True},
        )

        tokens_total = 0
        for chunk in stream:
            # Final chunk may carry usage info when stream_options include_usage=True
            if hasattr(chunk, "usage") and chunk.usage is not None:
                tokens_total = chunk.usage.total_tokens
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta.content
            if delta:
                accumulated += delta
                token_count += 1
                publish_event(job_id, "llm.token", {"token": delta})

                # Check cancellation every 20 tokens to avoid hammering Redis
                if token_count % 20 == 0 and is_cancelled(job_id):
                    publish_event(job_id, "job.cancelled", {})
                    return {"success": False, "job_id": job_id, "cancelled": True}

        optimization_time = time.time() - start_time

        # Fall back to tiktoken estimate if API didn't return usage
        if tokens_total == 0:
            tokens_total = llm_service.count_tokens(accumulated)

        # ── Parse accumulated JSON FIRST ─────────────────────────────
        # Must parse before publishing llm.complete so full_content
        # contains the actual LaTeX (not the raw JSON wrapper string).
        optimized_latex = latex_content  # safe fallback
        changes_made: list[Dict] = []

        try:
            parsed = json.loads(accumulated)
            optimized_latex = parsed.get("optimized_latex", latex_content)
            raw_changes = parsed.get("changes", [])
            changes_made = [
                {
                    "section": c.get("section", ""),
                    "change_type": c.get("change_type", "modified"),
                    "reason": c.get("reason", ""),
                }
                for c in raw_changes
                if isinstance(c, dict)
            ]
        except Exception as parse_err:
            logger.warning(f"[{job_id}] Could not parse LLM JSON: {parse_err}")
            # Attempt regex extraction of the LaTeX block as fallback
            match = re.search(
                r'"optimized_latex"\s*:\s*"(.*?)"(?=\s*[,}])',
                accumulated,
                re.DOTALL,
            )
            if match:
                optimized_latex = (
                    match.group(1)
                    .replace("\\n", "\n")
                    .replace('\\"', '"')
                )

        # Publish llm.complete with parsed LaTeX (not the raw JSON string)
        publish_event(job_id, "llm.complete", {
            "full_content": optimized_latex,
            "tokens_total": tokens_total,
        })

        result = {
            "success": True,
            "job_id": job_id,
            "optimized_latex": optimized_latex,
            "changes_made": changes_made,
            "optimization_time": optimization_time,
            "tokens_used": tokens_total,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": 0.0,
            "ats_details": {},
            "changes_made": changes_made,
            "compilation_time": 0.0,
            "optimization_time": optimization_time,
            "tokens_used": tokens_total,
        })
        logger.info(
            f"LLM task {task_id} succeeded for job {job_id} ({tokens_total} tokens)"
        )
        return result

    except Exception as exc:
        logger.error(f"LLM task {task_id} raised: {exc}")
        is_rate_limit = "rate limit" in str(exc).lower()
        retryable = self.request.retries < self.max_retries and not is_rate_limit
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "llm_error",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=120, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_resume_optimization(
    latex_content: str,
    job_description: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue optimize_resume_task on the llm queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    optimize_resume_task.apply_async(
        args=[latex_content, job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "optimization_level": optimization_level,
            "user_api_key": user_api_key,
            "metadata": metadata,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted LLM optimization for job {job_id}")
    return job_id

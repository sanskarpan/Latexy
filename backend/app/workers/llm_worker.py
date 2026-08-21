"""
LLM optimization worker — event-driven rebuild with OpenAI token streaming.

Uses the synchronous openai.OpenAI client (not AsyncOpenAI) with
stream=True so each token is published immediately as an llm.token
event.  Zero asyncio — all Redis I/O goes through event_publisher.
"""

import time
import uuid
from typing import Any, Dict, Optional

import openai
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..core.observability import record_llm_call
from ..core.tracing import traced
from ..services.llm_service import llm_service, parse_delimited_optimization
from ..workers.event_publisher import is_cancelled, publish_event, publish_job_result

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.llm_worker.optimize_resume_task",
    max_retries=2,
    default_retry_delay=120,
    time_limit=180,
    soft_time_limit=150,
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
    model: Optional[str] = None,
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

    # Provider TYPE + model for metrics/spans. This worker talks to the OpenAI
    # streaming client directly (BYOK provider routing lives elsewhere).
    provider = "openai"
    model_name = model or settings.OPENAI_MODEL

    prompt_build_seconds: float | None = None
    provider_call_seconds: float | None = None
    total_start = time.perf_counter()

    start_time = time.time()
    try:
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "llm_optimization",
            "message": "Building optimization prompt",
        })

        # Build prompt via llm_service helper (pure Python, no I/O)
        prompt_build_start = time.perf_counter()
        with traced("llm.prompt_build", provider=provider, model=model_name):
            keywords = llm_service.extract_keywords_from_job_description(job_description)
            prompt = llm_service._create_optimization_prompt(  # noqa: SLF001
                latex_content, job_description, keywords, optimization_level
            )
        prompt_build_seconds = time.perf_counter() - prompt_build_start

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "llm_optimization",
            "message": "Streaming LLM response",
        })

        accumulated = ""
        token_count = 0
        prompt_tokens = 0
        completion_tokens = 0
        tokens_total = 0

        provider_call_start = time.perf_counter()
        start_time = time.time()

        # Route the platform key through an OpenAI-compatible base URL when
        # configured (e.g. Gemini); BYOK keys keep native OpenAI unchanged.
        _use_platform_base = bool(settings.OPENAI_BASE_URL) and api_key == settings.OPENAI_API_KEY
        if _use_platform_base:
            client = openai.OpenAI(api_key=api_key, base_url=settings.OPENAI_BASE_URL)
            model_name = settings.OPENAI_MODEL
        else:
            client = openai.OpenAI(api_key=api_key)

        # Gemini's OpenAI-compat models "think" by default, consuming the token
        # budget before ever emitting the closing <<<END_LATEX>>> delimiter —
        # confirmed live in production, a real call spent 4,146 tokens and
        # produced zero visible output. reasoning_effort="none" reduces this
        # but does NOT eliminate it (confirmed empirically: it still happens
        # some fraction of the time, non-deterministically) — so on top of
        # disabling it, retry once on a genuinely empty/undelimited response
        # before giving up. Silently returning the unmodified resume as a
        # "success" (the previous behavior) is worse than a clear failure the
        # user can retry.
        MAX_ATTEMPTS = 2
        optimized_latex = latex_content
        changes_made: list[Dict] = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            accumulated = ""
            token_count = 0
            with traced("llm.provider_call", provider=provider, model=model_name, attempt=attempt):
                create_kwargs: Dict[str, Any] = dict(
                    model=model_name,
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
                if _use_platform_base:
                    create_kwargs["extra_body"] = {"reasoning_effort": "none"}

                stream = client.chat.completions.create(**create_kwargs)

                for chunk in stream:
                    # Final chunk may carry usage info when stream_options include_usage=True
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        tokens_total += chunk.usage.total_tokens
                        prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                        completion_tokens += getattr(chunk.usage, "completion_tokens", 0) or 0
                        continue

                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta.content
                    if delta:
                        accumulated += delta
                        token_count += 1
                        # Only stream tokens to the client on the attempt that
                        # actually pans out is unknowable in advance, so the
                        # first attempt's tokens are shown live as normal; a
                        # retry (rare) republishes from scratch below.
                        publish_event(job_id, "llm.token", {"token": delta})

                        # Check cancellation every 20 tokens to avoid hammering Redis
                        if token_count % 20 == 0 and is_cancelled(job_id):
                            publish_event(job_id, "job.cancelled", {})
                            return {"success": False, "job_id": job_id, "cancelled": True}

            optimized_latex, raw_changes = parse_delimited_optimization(accumulated, latex_content)
            changes_made = [
                {
                    "section": c.get("section", ""),
                    "change_type": c.get("change_type", "modified"),
                    "reason": c.get("reason", ""),
                }
                for c in raw_changes
            ]

            if "<<<LATEX>>>" in accumulated:
                break  # got real delimited output — done

            logger.warning(
                f"[{job_id}] attempt {attempt}/{MAX_ATTEMPTS}: LLM output missing "
                f"<<<LATEX>>> markers ({len(accumulated)} chars, {token_count} tokens accumulated)"
            )
            if attempt < MAX_ATTEMPTS:
                publish_event(job_id, "job.progress", {
                    "percent": 10,
                    "stage": "llm_optimization",
                    "message": "Retrying — first attempt produced no usable output",
                })

        provider_call_seconds = time.perf_counter() - provider_call_start
        optimization_time = time.time() - start_time

        # Fall back to tiktoken estimate if API didn't return usage
        if tokens_total == 0:
            tokens_total = llm_service.count_tokens(accumulated)

        if "<<<LATEX>>>" not in accumulated:
            # Exhausted every retry with no usable output — this is a real
            # failure, not a resume that "didn't need changes". Say so.
            logger.error(f"[{job_id}] LLM optimization failed after {MAX_ATTEMPTS} attempts — no delimited output")
            publish_event(job_id, "job.failed", {
                "stage": "llm_optimization",
                "error_code": "llm_error",
                "error_message": "The AI didn't return a usable result after retrying. Please try again.",
                "retryable": True,
            })
            record_llm_call(
                provider, model_name, "error",
                total_seconds=time.perf_counter() - total_start,
                prompt_build_seconds=prompt_build_seconds,
                provider_call_seconds=provider_call_seconds,
            )
            return {
                "success": False,
                "job_id": job_id,
                "error": "LLM returned no usable output after retrying",
            }

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

        record_llm_call(
            provider,
            model_name,
            "success",
            total_seconds=time.perf_counter() - total_start,
            prompt_build_seconds=prompt_build_seconds,
            provider_call_seconds=provider_call_seconds,
            prompt_tokens=prompt_tokens or None,
            completion_tokens=completion_tokens or None,
            total_tokens=tokens_total or None,
        )

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "percent": 100,
            "pdf_job_id": job_id,
            # This is a pure LLM rewrite — no ATS scoring stage runs here, so
            # send None (not a fake 0.0) to avoid a misleading 0/100 "Poor"
            # verdict on the client.
            "ats_score": None,
            "ats_details": None,
            "changes_made": changes_made,
            "compilation_time": 0.0,
            "optimization_time": optimization_time,
            "tokens_used": tokens_total,
        })
        logger.info(
            f"LLM task {task_id} succeeded for job {job_id} ({tokens_total} tokens)"
        )
        return result

    except SoftTimeLimitExceeded:
        elapsed = time.time() - start_time
        record_llm_call(provider, model_name, "error", total_seconds=time.perf_counter() - total_start)
        logger.error(f"LLM task {task_id} exceeded soft time limit for job {job_id}", exc_info=True)
        logger.warning(
            "llm_timeout",
            extra={"job_id": job_id, "duration_ms": elapsed * 1000},
            exc_info=True,
        )
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

    except Exception as exc:
        record_llm_call(provider, model_name, "error", total_seconds=time.perf_counter() - total_start)
        logger.error(f"LLM task {task_id} raised: {exc}", exc_info=True)
        is_rate_limit = "rate limit" in str(exc).lower()
        has_retries_left = self.request.retries < self.max_retries
        retryable = has_retries_left
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "llm_error",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if has_retries_left:
            if is_rate_limit:
                # Exponential backoff: 30s, 60s, 120s — avoids hammering the API.
                backoff = 30 * (2 ** self.request.retries)
                raise self.retry(exc=exc, countdown=backoff)
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
    model: Optional[str] = None,
) -> str:
    """Enqueue optimize_resume_task on the llm queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    import os
    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn
        spawn("run_llm_task", {
            "latex_content": latex_content,
            "job_description": job_description,
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "optimization_level": optimization_level,
            "user_api_key": user_api_key,
            "metadata": metadata,
            "model": model,
        })
        logger.info(f"Modal spawn: LLM optimization for job {job_id}")
        return job_id

    optimize_resume_task.apply_async(
        args=[latex_content, job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "optimization_level": optimization_level,
            "user_api_key": user_api_key,
            "metadata": metadata,
            "model": model,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted LLM optimization for job {job_id}")
    return job_id

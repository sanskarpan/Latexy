"""
Cover letter generation worker — streams LaTeX cover letter via OpenAI.

Mirrors llm_worker.py patterns: synchronous OpenAI client with stream=True,
publishes llm.token events for each delta. Runs on the 'llm' queue.
"""

import re
import time
import uuid
from typing import Any, Dict, Optional

import openai
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..workers.event_publisher import is_cancelled, publish_event, publish_job_result

logger = get_logger(__name__)

# Delimiter used to extract LaTeX from LLM output
_LATEX_RE = re.compile(r"<<<LATEX>>>(.*?)<<<END_LATEX>>>", re.DOTALL)


def _build_cover_letter_prompt(
    resume_latex: str,
    job_description: str,
    company_name: Optional[str],
    role_title: Optional[str],
    tone: str,
    length_preference: str,
) -> tuple[str, str]:
    """Build system and user prompts for cover letter generation.

    Returns (system_prompt, user_prompt).
    """
    tone_desc = {
        "formal": "professional and formal",
        "conversational": "warm, approachable, and conversational",
        "enthusiastic": "energetic, passionate, and enthusiastic",
    }.get(tone, "professional and formal")

    length_desc = {
        "3_paragraphs": "3 focused paragraphs",
        "4_paragraphs": "4 paragraphs with more detail",
        "detailed": "5+ paragraphs, comprehensive and detailed",
    }.get(length_preference, "3 focused paragraphs")

    system_prompt = (
        "You are an expert career coach and professional writer. "
        "Generate a cover letter in LaTeX format.\n\n"
        "REQUIREMENTS:\n"
        "- Use the SAME \\documentclass and font packages from the resume preamble "
        "to ensure visual consistency. If the resume uses a custom class, fall back "
        "to \\documentclass[11pt]{article} with matching fonts.\n"
        f"- Tone: {tone_desc}\n"
        f"- Length: {length_desc}\n"
        "- Structure: opening paragraph (interest + hook), body paragraphs "
        "(match skills to job requirements), closing (call to action + next steps)\n"
        "- Include: date, company address block if company name is given, "
        "salutation (use \"Hiring Manager\" if name unknown), signature block\n"
        "- Do NOT include: generic filler phrases like \"I am writing to express "
        "interest\", overused clichés, or vague statements\n"
        "- Use specific achievements and skills from the resume to demonstrate fit\n"
        "- The LaTeX must compile with pdflatex without errors\n"
        "- Output the COMPLETE LaTeX document wrapped in <<<LATEX>>> and "
        "<<<END_LATEX>>> delimiters. No explanations outside the delimiters."
    )

    company_line = f"Company: {company_name}\n" if company_name else ""
    role_line = f"Role: {role_title}\n" if role_title else ""

    user_prompt = (
        f"Generate a cover letter based on the following:\n\n"
        f"--- RESUME (LaTeX) ---\n{resume_latex}\n--- END RESUME ---\n\n"
        f"--- JOB DESCRIPTION ---\n{job_description}\n--- END JOB DESCRIPTION ---\n\n"
        f"{company_line}{role_line}"
        f"Tone: {tone}\n"
        f"Length: {length_preference}\n\n"
        "Wrap the complete LaTeX document in <<<LATEX>>> ... <<<END_LATEX>>> delimiters."
    )

    return system_prompt, user_prompt


@celery_app.task(
    bind=True,
    name="app.workers.cover_letter_worker.generate_cover_letter_task",
    max_retries=2,
    default_retry_delay=120,
    time_limit=180,
    soft_time_limit=150,
    queue="llm",
)
def generate_cover_letter_task(
    self,
    resume_latex: str,
    job_description: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    cover_letter_id: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    tone: str = "formal",
    length_preference: str = "3_paragraphs",
    user_api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a cover letter using OpenAI with live token streaming.

    Publishes:
      job.started    — when worker picks up the task
      job.progress   — preparation steps
      llm.token      — every streamed token delta
      llm.complete   — full assembled LaTeX content
      job.completed  — when generation is done
      job.failed     — on any error
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"cover-letter-{task_id}"
    logger.info(f"Cover letter task {task_id} starting for job {job_id}")

    api_key = user_api_key or settings.OPENAI_API_KEY

    if not api_key:
        publish_event(job_id, "job.failed", {
            "stage": "cover_letter_generation",
            "error_code": "llm_error",
            "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "No OpenAI API key configured"}

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "cover_letter_generation",
    })

    try:
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "cover_letter_generation",
            "message": "Building cover letter prompt",
        })

        system_prompt, user_prompt = _build_cover_letter_prompt(
            resume_latex, job_description, company_name, role_title,
            tone, length_preference,
        )

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "cover_letter_generation",
            "message": "Streaming LLM response",
        })

        client = openai.OpenAI(api_key=api_key)
        start_time = time.time()
        accumulated = ""
        token_count = 0

        stream = client.chat.completions.create(
            model=model or settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=settings.OPENAI_MAX_TOKENS,
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True},
        )

        tokens_total = 0
        for chunk in stream:
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

                if token_count % 20 == 0 and is_cancelled(job_id):
                    publish_event(job_id, "job.cancelled", {})
                    return {"success": False, "job_id": job_id, "cancelled": True}

        generation_time = time.time() - start_time

        # Extract LaTeX from delimiters
        cover_letter_latex = accumulated
        match = _LATEX_RE.search(accumulated)
        if match:
            cover_letter_latex = match.group(1).strip()

        # Publish llm.complete with the extracted LaTeX
        publish_event(job_id, "llm.complete", {
            "full_content": cover_letter_latex,
            "tokens_total": tokens_total,
        })

        # Save cover letter content to DB
        if cover_letter_id:
            _save_cover_letter_content(cover_letter_id, cover_letter_latex)

        result = {
            "success": True,
            "job_id": job_id,
            "cover_letter_latex": cover_letter_latex,
            "cover_letter_id": cover_letter_id,
            "generation_time": generation_time,
            "tokens_used": tokens_total,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": None,
            "optimization_time": generation_time,
            "tokens_used": tokens_total,
        })
        logger.info(
            f"Cover letter task {task_id} succeeded for job {job_id} "
            f"({tokens_total} tokens, {generation_time:.1f}s)"
        )
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Cover letter task {task_id} exceeded soft time limit for job {job_id}")
        publish_event(job_id, "job.failed", {
            "stage": "cover_letter_generation",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

    except Exception as exc:
        logger.error(f"Cover letter task {task_id} raised: {exc}")
        is_rate_limit = "rate limit" in str(exc).lower()
        has_retries_left = self.request.retries < self.max_retries
        retryable = has_retries_left
        publish_event(job_id, "job.failed", {
            "stage": "cover_letter_generation",
            "error_code": "llm_error",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if has_retries_left:
            if is_rate_limit:
                backoff = 30 * (2 ** self.request.retries)
                raise self.retry(exc=exc, countdown=backoff)
            raise self.retry(countdown=120, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


def _save_cover_letter_content(cover_letter_id: str, latex_content: str) -> None:
    """Save generated LaTeX content to cover_letters table (sync DB call from worker)."""
    import asyncio

    asyncio.run(_async_save_cover_letter(cover_letter_id, latex_content))


async def _async_save_cover_letter(cover_letter_id: str, latex_content: str) -> None:
    """Async helper to update cover letter record with generated content."""
    import os

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..database.models import CoverLetter
    from ..utils.db_url import normalize_database_url

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("DATABASE_URL not set — cannot save cover letter content")
        return

    db_url = normalize_database_url(raw_url)
    engine = create_async_engine(db_url, echo=False)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await session.execute(
                update(CoverLetter)
                .where(CoverLetter.id == cover_letter_id)
                .values(latex_content=latex_content)
            )
            await session.commit()
    finally:
        await engine.dispose()


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_cover_letter_generation(
    resume_latex: str,
    job_description: str,
    job_id: str,
    user_id: Optional[str] = None,
    cover_letter_id: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    tone: str = "formal",
    length_preference: str = "3_paragraphs",
    user_api_key: Optional[str] = None,
    user_plan: str = "free",
    model: Optional[str] = None,
) -> str:
    """Enqueue generate_cover_letter_task on the llm queue."""
    priority = get_task_priority(user_plan)

    generate_cover_letter_task.apply_async(
        args=[resume_latex, job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "cover_letter_id": cover_letter_id,
            "company_name": company_name,
            "role_title": role_title,
            "tone": tone,
            "length_preference": length_preference,
            "user_api_key": user_api_key,
            "model": model,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted cover letter generation for job {job_id}")
    return job_id

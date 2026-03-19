"""
Interview prep generation worker — generates role-specific interview questions via OpenAI.

Uses non-streaming JSON call (gpt-4o-mini with response_format=json_object).
Questions are saved to the interview_prep table. Runs on the 'llm' queue.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

import openai
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..workers.event_publisher import is_cancelled, publish_event, publish_job_result

logger = get_logger(__name__)

_SYSTEM_PROMPT = """You are a senior hiring manager and interview coach. Generate realistic interview questions for the role based on the candidate's resume and job description.

Generate EXACTLY:
- 5 behavioral questions (STAR format — past situations demonstrating skills)
- 5 technical/role-specific questions (skills, tools, domain knowledge from the JD)
- 3 motivational questions (why this role, why this company, career goals)
- 2 difficult/awkward questions (employment gaps, weaknesses, salary expectations, failure stories)

For each question output a JSON object with these fields:
- "category": one of "behavioral", "technical", "motivational", "difficult"
- "question": the interview question text
- "what_interviewer_assesses": 1-2 sentences on what the interviewer is evaluating
- "star_hint": for behavioral questions only — a STAR hint like "Situation: describe a time when... | Task: what were you responsible for... | Action: what did you do... | Result: what was the outcome...". For non-behavioral questions use null.

Output a single JSON object: {"questions": [<15 question objects>]}

IMPORTANT: Output only valid JSON, no markdown, no explanations."""


def _build_user_prompt(
    resume_latex: str,
    job_description: Optional[str],
    company_name: Optional[str],
    role_title: Optional[str],
) -> str:
    company_line = f"Company: {company_name}\n" if company_name else ""
    role_line = f"Role: {role_title}\n" if role_title else ""
    jd_section = f"--- JOB DESCRIPTION ---\n{job_description}\n--- END JD ---\n\n" if job_description else "No job description provided. Generate questions based on the resume content.\n\n"

    return (
        f"--- RESUME (LaTeX) ---\n{resume_latex}\n--- END RESUME ---\n\n"
        f"{jd_section}"
        f"{company_line}{role_line}"
        "Generate 15 interview questions as specified."
    )


@celery_app.task(
    bind=True,
    name="app.workers.interview_prep_worker.generate_interview_prep_task",
    max_retries=2,
    default_retry_delay=60,
    time_limit=120,
    soft_time_limit=100,
    queue="llm",
)
def generate_interview_prep_task(
    self,
    resume_latex: str,
    prep_id: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    resume_id: Optional[str] = None,
    job_description: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    user_api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate interview questions using OpenAI JSON mode.

    Publishes:
      job.started    — when worker picks up the task
      job.progress   — preparation steps
      job.completed  — when generation is done
      job.failed     — on any error
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    logger.info(f"Interview prep task {task_id} starting for job {job_id}, prep {prep_id}")

    api_key = user_api_key or settings.OPENAI_API_KEY
    if not api_key:
        publish_event(job_id, "job.failed", {
            "stage": "interview_prep_generation",
            "error_code": "llm_error",
            "error_message": "No OpenAI API key configured.",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "No OpenAI API key configured"}

    publish_event(job_id, "job.started", {
        "worker_id": f"interview-prep-{task_id}",
        "stage": "interview_prep_generation",
    })

    try:
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "interview_prep_generation",
            "message": "Building interview question prompt",
        })

        user_prompt = _build_user_prompt(resume_latex, job_description, company_name, role_title)

        publish_event(job_id, "job.progress", {
            "percent": 15,
            "stage": "interview_prep_generation",
            "message": "Generating questions with AI",
        })

        client = openai.OpenAI(api_key=api_key)
        start_time = time.time()

        if is_cancelled(job_id):
            publish_event(job_id, "job.cancelled", {})
            return {"success": False, "job_id": job_id, "cancelled": True}

        response = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=3000,
            temperature=0.7,
            response_format={"type": "json_object"},
        )

        generation_time = time.time() - start_time
        tokens_used = response.usage.total_tokens if response.usage else 0

        raw_content = response.choices[0].message.content or ""

        try:
            parsed = json.loads(raw_content)
            questions: List[Dict] = parsed.get("questions", [])
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse questions JSON for prep {prep_id}: {e}")
            questions = []

        publish_event(job_id, "job.progress", {
            "percent": 80,
            "stage": "interview_prep_generation",
            "message": f"Saving {len(questions)} questions",
        })

        # Save questions to DB
        _save_questions(prep_id, questions)

        result = {
            "success": True,
            "job_id": job_id,
            "prep_id": prep_id,
            "questions_count": len(questions),
            "generation_time": generation_time,
            "tokens_used": tokens_used,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "questions_count": len(questions),
            "generation_time": generation_time,
            "tokens_used": tokens_used,
        })
        logger.info(
            f"Interview prep task {task_id} succeeded for prep {prep_id} "
            f"({len(questions)} questions, {tokens_used} tokens, {generation_time:.1f}s)"
        )
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Interview prep task {task_id} exceeded soft time limit")
        publish_event(job_id, "job.failed", {
            "stage": "interview_prep_generation",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

    except Exception as exc:
        logger.error(f"Interview prep task {task_id} raised: {exc}")
        has_retries_left = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "interview_prep_generation",
            "error_code": "llm_error",
            "error_message": str(exc),
            "retryable": has_retries_left,
        })
        if has_retries_left:
            raise self.retry(countdown=60, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


def _save_questions(prep_id: str, questions: List[Dict]) -> None:
    """Save generated questions to interview_prep table (sync DB call from worker)."""
    import asyncio
    asyncio.run(_async_save_questions(prep_id, questions))


async def _async_save_questions(prep_id: str, questions: List[Dict]) -> None:
    """Async helper to update interview_prep record with generated questions."""
    import json as _json
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..utils.db_url import normalize_database_url

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("DATABASE_URL not set — cannot save interview questions")
        return

    db_url = normalize_database_url(raw_url)
    engine = create_async_engine(db_url, echo=False)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await session.execute(
                text(
                    "UPDATE interview_prep SET questions = :questions, updated_at = NOW() WHERE id = :id"
                ),
                {"questions": _json.dumps(questions), "id": prep_id},
            )
            await session.commit()
    finally:
        await engine.dispose()


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_interview_prep_generation(
    resume_latex: str,
    prep_id: str,
    job_id: str,
    user_id: Optional[str] = None,
    resume_id: Optional[str] = None,
    job_description: Optional[str] = None,
    company_name: Optional[str] = None,
    role_title: Optional[str] = None,
    user_api_key: Optional[str] = None,
    user_plan: str = "free",
    model: Optional[str] = None,
) -> str:
    """Enqueue generate_interview_prep_task on the llm queue."""
    priority = get_task_priority(user_plan)

    generate_interview_prep_task.apply_async(
        args=[resume_latex, prep_id],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "resume_id": resume_id,
            "job_description": job_description,
            "company_name": company_name,
            "role_title": role_title,
            "user_api_key": user_api_key,
            "model": model,
        },
        priority=priority,
        queue="llm",
    )
    logger.info(f"Submitted interview prep generation for job {job_id}, prep {prep_id}")
    return job_id

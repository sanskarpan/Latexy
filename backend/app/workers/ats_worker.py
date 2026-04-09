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
from typing import Any, Dict, Optional

from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.ats_scoring_service import ats_scoring_service
from ..services.industry_ats_profiles import detect_industry
from ..workers.event_publisher import publish_event, publish_job_result

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.ats_worker.score_resume_ats_task",
    max_retries=2,
    default_retry_delay=60,
    time_limit=60,
    soft_time_limit=50,
)
def score_resume_ats_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    industry_profile_key: Optional[str] = None,  # None = auto-detect; explicit key = override
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

        # Resolve industry profile: explicit key is used as-is; None triggers auto-detection
        if industry_profile_key is not None:
            effective_profile_key = industry_profile_key
        elif job_description:
            effective_profile_key = detect_industry(job_description)
        else:
            effective_profile_key = "generic"

        # score_resume is async but pure-Python — safe to call once with asyncio.run()
        start_time = time.time()
        scoring_result = asyncio.run(
            ats_scoring_service.score_resume(
                latex_content=latex_content,
                job_description=job_description,
                industry=industry,
                industry_profile_key=effective_profile_key,
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
            "industry_label": scoring_result.industry_label,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": scoring_result.overall_score,
            "ats_details": {
                **ats_details,
                "industry_label": scoring_result.industry_label,
            },
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

    except SoftTimeLimitExceeded:
        logger.error(f"ATS task {task_id} exceeded soft time limit for job {job_id}")
        publish_event(job_id, "job.failed", {
            "stage": "ats_scoring",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

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
    industry_profile_key: Optional[str] = None,
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
            "industry_profile_key": industry_profile_key,
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


# ------------------------------------------------------------------ #
#  Layer 2 — Deep LLM Analysis Task                                  #
# ------------------------------------------------------------------ #

_DEEP_ANALYSIS_PROMPT = """You are an expert ATS (Applicant Tracking System) resume analyst.
Analyze the following resume text and return a detailed JSON analysis.

Resume text:
{resume_text}

{jd_section}

Return ONLY valid JSON (no markdown) with this exact structure:
{{
  "overall_score": <integer 0-100>,
  "overall_feedback": "<2-3 sentence overall assessment>",
  "sections": [
    {{
      "name": "<section name>",
      "score": <integer 0-100>,
      "strengths": ["<strength 1>", "<strength 2>"],
      "improvements": ["<improvement 1>", "<improvement 2>"],
      "rewrite_suggestion": "<optional one-sentence rewrite tip>"
    }}
  ],
  "ats_compatibility": {{
    "score": <integer 0-100>,
    "issues": ["<issue 1>", "<issue 2>"],
    "keyword_gaps": ["<missing keyword 1>", "<missing keyword 2>"]
  }},
  "job_match": null
}}

Be specific, actionable, and honest. Score strictly (90+ = excellent, 70-89 = good, 50-69 = needs work, <50 = poor)."""

_DEEP_ANALYSIS_PROMPT_WITH_JD = """You are an expert ATS resume analyst.
Analyze the following resume against the provided job description.

Resume text:
{resume_text}

Job Description:
{job_description}

Return ONLY valid JSON (no markdown) with this exact structure:
{{
  "overall_score": <integer 0-100>,
  "overall_feedback": "<2-3 sentence overall assessment>",
  "sections": [
    {{
      "name": "<section name>",
      "score": <integer 0-100>,
      "strengths": ["<strength 1>"],
      "improvements": ["<improvement 1>"],
      "rewrite_suggestion": "<optional rewrite tip>"
    }}
  ],
  "ats_compatibility": {{
    "score": <integer 0-100>,
    "issues": ["<ats issue>"],
    "keyword_gaps": ["<missing keyword>"]
  }},
  "job_match": {{
    "score": <integer 0-100>,
    "matched_requirements": ["<matched req>"],
    "missing_requirements": ["<missing req>"],
    "recommendation": "<one sentence on fit>"
  }}
}}"""


async def _async_deep_analyze(
    task,
    latex_content: str,
    job_id: str,
    job_description: Optional[str],
    api_key: Optional[str],
) -> bool:
    """Async implementation of deep analysis task."""
    import time

    from openai import AsyncOpenAI

    start_time = time.time()

    publish_event(job_id, "job.started", {
        "worker_id": f"deep-ats-{job_id[:8]}",
        "stage": "deep_analysis",
    })

    # Extract text
    resume_text = ats_scoring_service._extract_text_from_latex(latex_content)  # noqa: SLF001
    if not resume_text.strip():
        publish_event(job_id, "job.failed", {
            "stage": "deep_analysis",
            "error_code": "latex_error",
            "error_message": "Could not extract text from LaTeX content",
            "retryable": False,
        })
        return False

    publish_event(job_id, "job.progress", {
        "percent": 20,
        "stage": "deep_analysis",
        "message": "Analysing resume with AI...",
    })

    # Build prompt
    if job_description:
        prompt = _DEEP_ANALYSIS_PROMPT_WITH_JD.format(
            resume_text=resume_text[:8000],
            job_description=job_description[:3000],
        )
    else:
        jd_section = ""
        prompt = _DEEP_ANALYSIS_PROMPT.format(
            resume_text=resume_text[:8000],
            jd_section=jd_section,
        )

    # Call OpenAI
    resolved_key = api_key or settings.OPENAI_API_KEY
    if not resolved_key:
        publish_event(job_id, "job.failed", {
            "stage": "deep_analysis",
            "error_code": "config_error",
            "error_message": "No OpenAI API key configured",
            "retryable": False,
        })
        return False

    client = AsyncOpenAI(api_key=resolved_key)

    publish_event(job_id, "job.progress", {
        "percent": 40,
        "stage": "deep_analysis",
        "message": "Calling LLM for section-by-section analysis...",
    })

    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are an expert resume analyst. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
        temperature=0.3,
    )

    publish_event(job_id, "job.progress", {
        "percent": 80,
        "stage": "deep_analysis",
        "message": "Parsing analysis results...",
    })

    tokens_used = response.usage.total_tokens if response.usage else 0
    analysis_time = time.time() - start_time

    # Parse response
    try:
        import json as _json
        result = _json.loads(response.choices[0].message.content)
    except Exception:
        result = {
            "overall_score": 0,
            "overall_feedback": "Analysis parsing failed. Please retry.",
            "sections": [],
            "ats_compatibility": {"score": 0, "issues": [], "keyword_gaps": []},
            "job_match": None,
        }

    # Compute multi-dimensional scores (rule-based, fast)
    multi_dim_scores: dict = {}
    try:
        scoring_result = await ats_scoring_service.score_resume(
            latex_content=latex_content,
            job_description=job_description,
        )
        multi_dim_scores = scoring_result.multi_dim_scores or {}
    except Exception as _e:
        logger.warning(f"Multi-dim scoring failed for job {job_id}: {_e}")

    # Publish deep_complete event
    publish_event(job_id, "ats.deep_complete", {
        "overall_score": result.get("overall_score", 0),
        "overall_feedback": result.get("overall_feedback", ""),
        "sections": result.get("sections", []),
        "ats_compatibility": result.get("ats_compatibility", {}),
        "job_match": result.get("job_match"),
        "tokens_used": tokens_used,
        "analysis_time": analysis_time,
        "multi_dim_scores": multi_dim_scores,
    })

    publish_job_result(job_id, {
        "success": True,
        "job_id": job_id,
        "deep_analysis": result,
        "tokens_used": tokens_used,
        "analysis_time": analysis_time,
    })

    publish_event(job_id, "job.completed", {
        "pdf_job_id": job_id,
        "ats_score": float(result.get("overall_score", 0)),
        "ats_details": {
            "category_scores": {},
            "recommendations": [],
            "strengths": [],
            "warnings": [],
        },
        "changes_made": [],
        "compilation_time": 0.0,
        "optimization_time": analysis_time,
        "tokens_used": tokens_used,
    })

    logger.info(f"Deep analysis complete for job {job_id}: {result.get('overall_score')}/100")
    return True


@celery_app.task(
    bind=True,
    name="app.workers.ats_worker.deep_analyze_ats_task",
    queue="ats",
    max_retries=1,
    default_retry_delay=30,
    time_limit=120,
    soft_time_limit=100,
)
def deep_analyze_ats_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    job_description: Optional[str] = None,
    api_key: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Deep LLM-powered ATS analysis task.
    Uses gpt-4o-mini with JSON mode for structured section-by-section feedback.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    logger.info(f"Deep ATS analysis starting for job {job_id}")

    try:
        success = asyncio.run(_async_deep_analyze(self, latex_content, job_id, job_description, api_key))
        return {"success": bool(success), "job_id": job_id}
    except SoftTimeLimitExceeded:
        logger.error(f"Deep ATS analysis exceeded soft time limit for job {job_id}")
        publish_event(job_id, "job.failed", {
            "stage": "deep_analysis",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

    except Exception as exc:
        logger.error(f"Deep ATS analysis failed for job {job_id}: {exc}")
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "deep_analysis",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=30, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ------------------------------------------------------------------ #
#  Layer 3 — Background Resume Embedding Task                        #
# ------------------------------------------------------------------ #

async def _async_embed_resume(resume_id: str, latex_content: str) -> None:
    """Async implementation: extract text -> embed -> store in DB."""
    from ..database.connection import get_async_db_session
    from ..services.embedding_service import embedding_service

    async with get_async_db_session() as db:
        await embedding_service.embed_resume(resume_id, latex_content, db)


@celery_app.task(
    bind=True,
    name="app.workers.ats_worker.embed_resume_task",
    queue="ats",
    max_retries=2,
    default_retry_delay=60,
    priority=1,
)
def embed_resume_task(
    self,
    resume_id: str,
    latex_content: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fire-and-forget task to compute and store the embedding for a resume.
    Priority=1 (low) so it doesn't compete with interactive tasks.
    """
    if not settings.OPENAI_API_KEY:
        return {"skipped": True, "reason": "no_api_key"}

    try:
        asyncio.run(_async_embed_resume(resume_id, latex_content))
        return {"success": True, "resume_id": resume_id}
    except Exception as exc:
        logger.error(f"embed_resume_task failed for {resume_id}: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=exc)
        return {"success": False, "resume_id": resume_id, "error": str(exc)}

"""
Orchestrator — combined LLM → LaTeX → ATS pipeline in a single Celery task.

This is the main task for the 'combined' job type (optimize + compile + score).

Stage progression:
  job.started           → stage=llm_optimization
  llm.token (×N)        → live token stream to frontend Monaco editor
  llm.complete          → full assembled LaTeX + token count
  job.progress 40%      → stage=latex_compilation
  log.line (×N)         → pdflatex stdout lines
  job.progress 80%      → stage=ats_scoring
  job.completed 100%    → ats_score, pdf_job_id, changes_made, times

All Redis I/O via event_publisher (sync redis.Redis — no asyncio).
"""

import asyncio
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from subprocess import PIPE, STDOUT
from typing import Any, Dict, List, Optional

import openai

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.ats_scoring_service import ats_scoring_service
from ..services.latex_service import latex_service
from ..services.llm_service import llm_service
from ..workers.event_publisher import (
    is_cancelled,
    publish_event,
    publish_job_result,
)

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.orchestrator.optimize_and_compile_task",
    max_retries=1,
    default_retry_delay=60,
)
def optimize_and_compile_task(
    self,
    latex_content: str,
    job_description: Optional[str] = None,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: LLM optimize → pdflatex compile → ATS score.

    The job_id is used as the PDF storage path so GET /download/{job_id}
    serves the compiled PDF directly.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    task_id = self.request.id
    worker_id = f"orchestrator-{task_id}"
    logger.info(f"Orchestrator task {task_id} starting for job {job_id}")

    api_key = user_api_key or settings.OPENAI_API_KEY

    # Validate API key BEFORE publishing job.started so the client never sees
    # a confusing started → immediately-failed sequence.
    if not api_key:
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "llm_error",
            "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "No OpenAI API key"}

    publish_event(job_id, "job.started", {
        "worker_id": worker_id,
        "stage": "llm_optimization",
    })

    try:
        # ================================================================ #
        # Stage 1 — LLM optimization with token streaming (0% → 40%)      #
        # ================================================================ #
        optimized_latex, changes_made, tokens_used, optimization_time = _run_llm_stage(
            job_id=job_id,
            latex_content=latex_content,
            job_description=job_description,
            optimization_level=optimization_level,
            api_key=api_key,
        )

        if is_cancelled(job_id):
            publish_event(job_id, "job.cancelled", {})
            return {"success": False, "job_id": job_id, "cancelled": True}

        # ================================================================ #
        # Stage 2 — LaTeX compilation with log streaming (40% → 80%)      #
        # ================================================================ #
        publish_event(job_id, "job.progress", {
            "percent": 40,
            "stage": "latex_compilation",
            "message": "Starting LaTeX compilation",
        })

        compilation_ok, compilation_time = _run_latex_stage(
            job_id=job_id,
            latex_content=optimized_latex,
        )

        if is_cancelled(job_id):
            publish_event(job_id, "job.cancelled", {})
            return {"success": False, "job_id": job_id, "cancelled": True}

        if not compilation_ok:
            # job.failed already published inside _run_latex_stage
            return {"success": False, "job_id": job_id, "error": "LaTeX compilation failed"}

        # ================================================================ #
        # Stage 3 — ATS scoring (80% → 100%)                              #
        # ================================================================ #
        publish_event(job_id, "job.progress", {
            "percent": 80,
            "stage": "ats_scoring",
            "message": "Scoring ATS compatibility",
        })

        ats_score, ats_details = _run_ats_stage(
            job_id=job_id,
            latex_content=optimized_latex,
            job_description=job_description,
        )

        # ================================================================ #
        # Completion                                                        #
        # ================================================================ #
        result = {
            "success": True,
            "job_id": job_id,
            "pdf_job_id": job_id,
            "ats_score": ats_score,
            "ats_details": ats_details,
            "changes_made": changes_made,
            "compilation_time": compilation_time,
            "optimization_time": optimization_time,
            "tokens_used": tokens_used,
            "optimized_latex": optimized_latex,
        }

        publish_job_result(job_id, result)
        publish_event(job_id, "job.completed", {
            "pdf_job_id": job_id,
            "ats_score": ats_score,
            "ats_details": ats_details,
            "changes_made": changes_made,
            "compilation_time": compilation_time,
            "optimization_time": optimization_time,
            "tokens_used": tokens_used,
        })
        logger.info(
            f"Orchestrator task {task_id} succeeded for job {job_id} "
            f"(ATS {ats_score:.1f}, {tokens_used} tokens, {compilation_time:.1f}s)"
        )
        return result

    except Exception as exc:
        logger.error(f"Orchestrator task {task_id} raised: {exc}")
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": self.request.retries < self.max_retries,
        })
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=60, exc=exc)
        return {"success": False, "job_id": job_id, "error": str(exc)}


# ------------------------------------------------------------------ #
#  Internal stage helpers                                              #
# ------------------------------------------------------------------ #

def _run_llm_stage(
    job_id: str,
    latex_content: str,
    job_description: Optional[str],
    optimization_level: str,
    api_key: str,
) -> tuple[str, List[Dict], int, float]:
    """
    Stream OpenAI tokens, publish llm.token per delta, return
    (optimized_latex, changes_made, tokens_total, optimization_time).
    """
    publish_event(job_id, "job.progress", {
        "percent": 5,
        "stage": "llm_optimization",
        "message": "Building optimization prompt",
    })

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
    tokens_total = 0

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
                raise RuntimeError("Job cancelled during LLM streaming")

    optimization_time = time.time() - start_time
    if tokens_total == 0:
        tokens_total = llm_service.count_tokens(accumulated)

    # Parse JSON response FIRST before publishing llm.complete,
    # so full_content contains the actual LaTeX (not the raw JSON wrapper string).
    optimized_latex = latex_content
    changes_made: List[Dict] = []
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

    # Publish with parsed LaTeX so the frontend Monaco editor receives
    # actual LaTeX content, not the raw JSON wrapper from the LLM response.
    publish_event(job_id, "llm.complete", {
        "full_content": optimized_latex,
        "tokens_total": tokens_total,
    })

    return optimized_latex, changes_made, tokens_total, optimization_time


def _run_latex_stage(
    job_id: str,
    latex_content: str,
) -> tuple[bool, float]:
    """
    Write LaTeX, run pdflatex via Docker with line-by-line log streaming.
    Returns (success, compilation_time).
    """
    job_dir = settings.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    tex_file = job_dir / "resume.tex"
    pdf_file = job_dir / "resume.pdf"
    tex_file.write_text(latex_content, encoding="utf-8")

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{job_dir}:/workspace",
        "-w", "/workspace",
        settings.LATEX_DOCKER_IMAGE,
        "pdflatex",
        "-interaction=nonstopmode",
        "-synctex=1",
        "-output-directory", "/workspace",
        "-jobname", "resume",
        "resume.tex",
    ]

    start_time = time.time()
    proc = subprocess.Popen(
        docker_cmd,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    for raw_line in proc.stdout:  # type: ignore[union-attr]
        line = raw_line.rstrip("\n")
        if not line:
            continue
        line_lower = line.lower()
        is_error = any(
            kw in line_lower for kw in ("error", "fatal", "undefined control")
        )
        publish_event(job_id, "log.line", {
            "source": "pdflatex",
            "line": line,
            "is_error": is_error,
        })
        if is_cancelled(job_id):
            proc.kill()
            proc.wait()
            raise RuntimeError("Job cancelled during LaTeX compilation")

    proc.wait()
    compilation_time = time.time() - start_time

    if proc.returncode == 0 and pdf_file.exists():
        return True, compilation_time

    error_msg = (
        f"pdflatex exited with code {proc.returncode}. "
        "See log.line events for details."
    )
    publish_event(job_id, "job.failed", {
        "stage": "latex_compilation",
        "error_code": "latex_error",
        "error_message": error_msg,
        "retryable": False,
    })
    return False, compilation_time


def _run_ats_stage(
    job_id: str,
    latex_content: str,
    job_description: Optional[str],
) -> tuple[float, Dict]:
    """
    Run ATS scoring (pure-Python async) and return (score, details).
    asyncio.run() is safe here because ats_scoring_service has no
    Redis or cross-process async calls inside it.
    """
    try:
        scoring_result = asyncio.run(
            ats_scoring_service.score_resume(
                latex_content=latex_content,
                job_description=job_description,
            )
        )
        ats_details = {
            "category_scores": scoring_result.category_scores,
            "recommendations": scoring_result.recommendations,
            "strengths": scoring_result.strengths,
            "warnings": scoring_result.warnings,
        }
        return scoring_result.overall_score, ats_details
    except Exception as exc:
        logger.warning(f"[{job_id}] ATS scoring failed (non-fatal): {exc}")
        return 0.0, {}


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_optimize_and_compile(
    latex_content: str,
    job_description: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    user_api_key: Optional[str] = None,
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
) -> str:
    """Enqueue optimize_and_compile_task on the combined queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    optimize_and_compile_task.apply_async(
        args=[latex_content, job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "optimization_level": optimization_level,
            "user_api_key": user_api_key,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
        },
        priority=priority,
        queue="combined",
    )
    logger.info(f"Submitted optimize-and-compile for job {job_id}")
    return job_id

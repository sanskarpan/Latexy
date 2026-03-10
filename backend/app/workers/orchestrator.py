"""
Orchestrator — combined LLM → LaTeX → ATS pipeline in a single Celery task.

This is the main task for the 'combined' job type (optimize + compile + score).

Stage progression:
  job.started           → stage=llm_optimization
  llm.token (×N)        → live LaTeX token stream to frontend Monaco editor
  llm.complete          → full assembled LaTeX + token count
  job.progress 40%      → stage=latex_compilation
  log.line (×N)         → pdflatex stdout lines
  job.progress 80%      → stage=ats_scoring
  job.completed 100%    → ats_score, pdf_job_id, changes_made, times

Fix notes:
- Delimiter streaming: LLM output wrapped in <<<LATEX>>>...<<<END_LATEX>>> markers;
  only LaTeX tokens published via llm.token (JSON scaffold never reaches editor).
- Docker fallback: shutil.which("docker") → local pdflatex when Docker unavailable.
- Compile failure preserves LLM work: job.failed includes optimized_latex + changes_made.
- Section-specific optimization: target_sections + custom_instructions pass-through.

All Redis I/O via event_publisher (sync redis.Redis — no asyncio).
"""

import asyncio
import json
import re
import shutil
import subprocess
import time
import uuid
from subprocess import PIPE, STDOUT
from typing import Any, Dict, List, Optional

import openai
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..services.ats_scoring_service import ats_scoring_service
from ..services.llm_service import llm_service
from ..workers.event_publisher import (
    is_cancelled,
    publish_event,
    publish_job_result,
)

logger = get_logger(__name__)

# Delimiter markers for structured LLM output (Fix 2)
_LS = "<<<LATEX>>>"
_LE = "<<<END_LATEX>>>"
_CS = "<<<CHANGES>>>"
_CE = "<<<END_CHANGES>>>"
_BEFORE, _IN_LATEX, _AFTER_LATEX, _IN_CHANGES = 0, 1, 2, 3


@celery_app.task(
    bind=True,
    name="app.workers.orchestrator.optimize_and_compile_task",
    max_retries=1,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=270,
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
    target_sections: Optional[List[str]] = None,
    custom_instructions: Optional[str] = None,
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
            target_sections=target_sections,
            custom_instructions=custom_instructions,
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

        compilation_ok, compilation_time, compile_error = _run_latex_stage(
            job_id=job_id,
            latex_content=optimized_latex,
        )

        if is_cancelled(job_id):
            publish_event(job_id, "job.cancelled", {})
            return {"success": False, "job_id": job_id, "cancelled": True}

        if not compilation_ok:
            # Fix 3: include optimized_latex and changes_made in failure event
            # so the frontend can offer an "Apply anyway" option.
            publish_event(job_id, "job.failed", {
                "stage": "latex_compilation",
                "error_code": "latex_error",
                "error_message": compile_error,
                "retryable": False,
                "optimized_latex": optimized_latex,
                "changes_made": changes_made,
            })
            return {
                "success": False,
                "job_id": job_id,
                "error": "LaTeX compilation failed",
                "optimized_latex": optimized_latex,
            }

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

    except SoftTimeLimitExceeded:
        logger.error(f"Orchestrator task {task_id} exceeded soft time limit for job {job_id}")
        publish_event(job_id, "job.failed", {
            "stage": "llm_optimization",
            "error_code": "timeout",
            "error_message": "Task exceeded time limit",
            "retryable": False,
        })
        return {"success": False, "job_id": job_id, "error": "Task exceeded time limit"}

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
    target_sections: Optional[List[str]] = None,
    custom_instructions: Optional[str] = None,
) -> tuple[str, List[Dict], int, float]:
    """
    Stream OpenAI tokens through a delimiter state machine.

    Only LaTeX tokens inside <<<LATEX>>>...<<<END_LATEX>>> are published
    via llm.token events — the JSON scaffold never reaches the Monaco editor.

    Returns (optimized_latex, changes_made, tokens_total, optimization_time).
    """
    publish_event(job_id, "job.progress", {
        "percent": 5,
        "stage": "llm_optimization",
        "message": "Building optimization prompt",
    })

    keywords = llm_service.extract_keywords_from_job_description(job_description)
    prompt = llm_service._create_optimization_prompt(  # noqa: SLF001
        latex_content, job_description, keywords, optimization_level,
        target_sections=target_sections,
        custom_instructions=custom_instructions,
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

    # ── Delimiter state machine ──────────────────────────────────────
    # States: BEFORE → IN_LATEX → AFTER_LATEX → IN_CHANGES
    # Only tokens inside <<<LATEX>>>...<<<END_LATEX>>> are published.
    llm_state = _BEFORE
    latex_parts: List[str] = []
    changes_parts: List[str] = []
    buf = ""  # rolling buffer for delimiter detection

    for chunk in stream:
        if hasattr(chunk, "usage") and chunk.usage is not None:
            tokens_total = chunk.usage.total_tokens
            continue
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if not delta:
            continue

        accumulated += delta
        token_count += 1
        buf += delta

        if token_count % 20 == 0 and is_cancelled(job_id):
            raise RuntimeError("Job cancelled during LLM streaming")

        # Process state transitions; loop allows multiple per chunk
        # (e.g. chunk contains both <<<END_LATEX>>> and <<<CHANGES>>>)
        for _ in range(4):
            if llm_state == _BEFORE:
                if _LS in buf:
                    buf = buf.split(_LS, 1)[1]
                    llm_state = _IN_LATEX
                    continue  # re-process buf with IN_LATEX state
                else:
                    if len(buf) >= len(_LS):
                        buf = buf[-len(_LS):]  # keep potential partial match
                break

            elif llm_state == _IN_LATEX:
                if _LE in buf:
                    before, _, buf = buf.partition(_LE)
                    if before:
                        latex_parts.append(before)
                        publish_event(job_id, "llm.token", {"token": before})
                    llm_state = _AFTER_LATEX
                    continue  # re-process buf with AFTER_LATEX state
                else:
                    # Flush safe portion (hold back enough to detect end delimiter)
                    safe_len = len(buf) - len(_LE) + 1
                    if safe_len > 0:
                        safe = buf[:safe_len]
                        latex_parts.append(safe)
                        publish_event(job_id, "llm.token", {"token": safe})
                        buf = buf[safe_len:]
                break

            elif llm_state == _AFTER_LATEX:
                if _CS in buf:
                    buf = buf.split(_CS, 1)[1]
                    llm_state = _IN_CHANGES
                    continue  # re-process buf with IN_CHANGES state
                else:
                    if len(buf) >= len(_CS):
                        buf = buf[-len(_CS):]
                break

            elif llm_state == _IN_CHANGES:
                if _CE in buf:
                    before, _, _ = buf.partition(_CE)
                    changes_parts.append(before)
                    buf = ""
                else:
                    # Hold back potential delimiter chars (same pattern as IN_LATEX)
                    safe_len = len(buf) - len(_CE) + 1
                    if safe_len > 0:
                        changes_parts.append(buf[:safe_len])
                        buf = buf[safe_len:]
                break

    optimization_time = time.time() - start_time
    if tokens_total == 0:
        tokens_total = llm_service.count_tokens(accumulated)

    # ── Build result from delimiter-parsed parts ─────────────────────
    optimized_latex = "".join(latex_parts).strip()
    changes_raw = "".join(changes_parts).strip()

    # Fallback: if LLM ignored delimiter format, try JSON parse
    if not optimized_latex:
        logger.warning(f"[{job_id}] Delimiter format not found; falling back to JSON parse")
        try:
            parsed = json.loads(accumulated)
            optimized_latex = parsed.get("optimized_latex", latex_content)
            raw_changes = parsed.get("changes", [])
        except Exception:
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
            else:
                optimized_latex = latex_content
            raw_changes = []
    else:
        try:
            raw_changes = json.loads(changes_raw) if changes_raw else []
        except Exception:
            raw_changes = []

    changes_made = [
        {
            "section": c.get("section", ""),
            "change_type": c.get("change_type", "modified"),
            "reason": c.get("reason", ""),
        }
        for c in raw_changes
        if isinstance(c, dict)
    ]

    # Publish with the fully-parsed LaTeX so the editor reflects final content
    publish_event(job_id, "llm.complete", {
        "full_content": optimized_latex,
        "tokens_total": tokens_total,
    })

    return optimized_latex, changes_made, tokens_total, optimization_time


def _run_latex_stage(
    job_id: str,
    latex_content: str,
) -> tuple[bool, float, str]:
    """
    Write LaTeX, run pdflatex (Docker if available, else local texlive)
    with line-by-line log streaming.

    Returns (success, compilation_time, error_message).
    Does NOT publish job.failed — caller is responsible so it can
    include optimized_latex in the failure payload.

    # TODO(refactor): LaTeX compilation logic is also present in latex_worker.py.
    # Extract to a shared helper function in app/services/latex_service.py.
    """
    job_dir = settings.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    tex_file = job_dir / "resume.tex"
    pdf_file = job_dir / "resume.pdf"
    tex_file.write_text(latex_content, encoding="utf-8")

    # Fix 1: Docker if available, else local pdflatex (matches latex_worker.py)
    _use_docker = shutil.which("docker") is not None
    if _use_docker:
        compile_cmd = [
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
        compile_cwd = None
    else:
        # Inside the backend container, pdflatex is installed via texlive
        compile_cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-synctex=1",
            "-output-directory", str(job_dir),
            "-jobname", "resume",
            "resume.tex",
        ]
        compile_cwd = str(job_dir)

    start_time = time.time()
    proc = subprocess.Popen(
        compile_cmd,
        stdout=PIPE,
        stderr=STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=compile_cwd,
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
        return True, compilation_time, ""

    error_msg = (
        f"pdflatex exited with code {proc.returncode}. "
        "See log.line events for details."
    )
    return False, compilation_time, error_msg


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
    target_sections: Optional[List[str]] = None,
    custom_instructions: Optional[str] = None,
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
            "target_sections": target_sections,
            "custom_instructions": custom_instructions,
            "metadata": metadata,
        },
        priority=priority,
        queue="combined",
    )
    logger.info(f"Submitted optimize-and-compile for job {job_id}")
    return job_id

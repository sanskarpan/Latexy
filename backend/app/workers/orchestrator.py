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
- Docker fallback: sandboxed Docker engine, else the opt-in local engine (see
  latex_service.assert_local_engine_allowed).
- Compile failure preserves LLM work: job.failed includes optimized_latex + changes_made.
- Section-specific optimization: target_sections + custom_instructions pass-through.

All Redis I/O via event_publisher (sync redis.Redis — no asyncio).
"""

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import openai
from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import get_compile_timeout, resolve_plan_family, settings
from ..core.logging import get_logger
from ..core.observability import record_compile
from ..core.tracing import traced
from ..services.ats_scoring_service import ats_scoring_service
from ..services.cover_letter_signature_service import materialize_embedded_signature
from ..services.latex_service import (
    ENGINE_READ_ESCAPE_ERROR,
    LATEX_SANDBOX_FLAGS,
    RECORDER_SUFFIX,
    assert_local_engine_allowed,
    cleanup_docker_container,
    docker_container_name,
    docker_engine_available,
    docker_sandbox_args,
    engine_env,
    find_engine_read_escape,
    find_recorder_read_escape,
    latex_service,
)
from ..services.llm_service import llm_service
from ..services.optimization_personas import PERSONAS
from ..utils.bounded_io import (
    MAX_COMPILED_PDF_BYTES,
    BoundedReadError,
    BoundedTranscript,
    iter_bounded_lines,
)
from ..utils.process_watchdog import ProcessWatchdog
from ..workers.event_publisher import (
    get_worker_redis,
    is_cancelled,
    publish_event,
    publish_job_result,
)
from ..workers.job_lifecycle import admit_worker, begin_finalizing, current_owner_epoch, lifecycle_key
from ..workers.latex_worker import (
    _ALLOWED_EXTRA_FLAGS,
    _MAIN_FILE_RE,
    CompilationPersistenceOutcome,
    _inject_draft_graphics,
    _inject_packages,
    cache_compile_log,
    cache_compile_output,
    commit_latex_finalization,
    compute_queue_wait_seconds,
    consume_cold_start_seconds,
    is_beamer_document,
    reconcile_compilation_record,
    write_reference_library,
)
from ..workers.quota_refund import clear_quota_refund_receipt, refund_quota_once

logger = get_logger(__name__)


def _refund_combined_quota_once(job_id: str, quota_refund: Optional[Dict[str, Any]]) -> bool:
    return refund_quota_once(
        job_id,
        quota_refund,
        expected_dimension="optimizations",
    )


def _publish_combined_terminal(
    job_id: str,
    result: Dict[str, Any],
    event_payload: Dict[str, Any],
    quota_refund: Optional[Dict[str, Any]],
    *,
    event_type: str = "job.failed",
) -> bool:
    """Commit the fenced outcome before notifying or refunding quota."""
    accepted = publish_job_result(job_id, result)
    if accepted:
        # Keep the event terminal type aligned with the canonical result even
        # when a caller omitted the optional override. A cancelled result must
        # never be surfaced as a failure (or refunded through the wrong event
        # replay path).
        effective_event_type = "job.cancelled" if result.get("cancelled") is True else event_type
        publish_event(job_id, effective_event_type, event_payload)
        _refund_combined_quota_once(job_id, quota_refund)
    return accepted

# Delimiter markers for structured LLM output (Fix 2)
_LS = "<<<LATEX>>>"
_PAGE_COUNT_RE = re.compile(r"Output written on .*?\((\d+) page", re.IGNORECASE)
_LE = "<<<END_LATEX>>>"
_CS = "<<<CHANGES>>>"
_CE = "<<<END_CHANGES>>>"
_BEFORE, _IN_LATEX, _AFTER_LATEX, _IN_CHANGES = 0, 1, 2, 3


class LLMStreamCancelled(RuntimeError):
    """Control-flow signal for a user cancellation observed mid-stream."""


@celery_app.task(
    bind=True,
    name="app.workers.orchestrator.optimize_and_compile_task",
    max_retries=1,
    default_retry_delay=60,
    time_limit=600,  # 10 min hard kill — covers Pro/BYOK (240s compile + ~120s LLM + buffer)
    soft_time_limit=570,
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
    model: Optional[str] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: str = "pdflatex",
    timeout_seconds: Optional[int] = None,
    persona: Optional[str] = None,
    industry: Optional[str] = None,
    seniority: Optional[str] = None,
    tone: Optional[str] = None,
    emphasize: Optional[List[str]] = None,
    downplay: Optional[List[str]] = None,
    compile_settings: Optional[Dict] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: LLM optimize → pdflatex compile → ATS score.

    The job_id is used as the PDF storage path so GET /download/{job_id}
    serves the compiled PDF directly.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    # Timing instrumentation (#1281) — same phases latex_worker.compile_latex_task
    # reports, plus the LLM/ATS stages that are unique to this combined pipeline.
    _task_monotonic_start = time.monotonic()
    _cold_start_seconds = consume_cold_start_seconds()
    _queue_wait_seconds = compute_queue_wait_seconds(job_id)

    task_id = self.request.id
    worker_id = f"orchestrator-{task_id}"
    logger.info(
        f"Orchestrator task {task_id} starting for job {job_id}",
        extra={
            "job_id": job_id,
            "task_id": task_id,
            "queue_wait_seconds": _queue_wait_seconds,
            "cold_start_seconds": _cold_start_seconds,
        },
    )

    lifecycle_owner = f"{worker_id}:{uuid.uuid4()}"
    queue_redis = get_worker_redis()
    if not admit_worker(queue_redis, job_id, lifecycle_owner, quota_refund, user_id):
        return {
            "success": False,
            "job_id": job_id,
            "error": "Job ownership unavailable",
        }
    lifecycle_owned = bool(queue_redis.exists(lifecycle_key(job_id)))
    # Capture once at admission; a later Redis read could observe a replacement
    # owner's epoch and incorrectly authorize this stale delivery.
    lifecycle_epoch = current_owner_epoch(job_id) if lifecycle_owned else None
    if lifecycle_owned and lifecycle_epoch is None:
        return {"success": False, "job_id": job_id, "error": "Job ownership unavailable"}

    def _log_task_timing(
        outcome: str,
        optimization_seconds: Optional[float] = None,
        compile_subprocess_seconds: Optional[float] = None,
        ats_scoring_seconds: Optional[float] = None,
        reporting_start: Optional[float] = None,
    ) -> None:
        """One structured, grep-able line per task completion (#1281).

        Splits the combined LLM -> LaTeX -> ATS pipeline into its phases so a
        latency regression shows up as a specific field instead of one opaque
        total.
        """
        reporting_seconds = time.monotonic() - reporting_start if reporting_start is not None else None
        logger.info(
            "orchestrator_task_timing",
            extra={
                "job_id": job_id,
                "task_id": task_id,
                "compiler": compiler,
                "outcome": outcome,
                "queue_wait_seconds": _queue_wait_seconds,
                "cold_start_seconds": _cold_start_seconds,
                "optimization_seconds": optimization_seconds,
                "compile_subprocess_seconds": compile_subprocess_seconds,
                "ats_scoring_seconds": ats_scoring_seconds,
                "reporting_seconds": reporting_seconds,
                "total_task_seconds": time.monotonic() - _task_monotonic_start,
            },
        )

    api_key = user_api_key or settings.OPENAI_API_KEY

    # Resolve per-plan compile timeout
    compile_timeout = timeout_seconds or get_compile_timeout(user_plan)

    # Validate API key BEFORE publishing job.started so the client never sees
    # a confusing started → immediately-failed sequence.
    if not api_key:
        result = {"success": False, "job_id": job_id, "error": "No OpenAI API key"}
        _publish_combined_terminal(
            job_id,
            result,
            {
                "stage": "llm_optimization",
                "error_code": "llm_error",
                "error_message": "No OpenAI API key configured. Add one via BYOK settings.",
                "retryable": False,
            },
            quota_refund,
        )
        reconcile_compilation_record(
            job_id,
            success=False,
            error_message="No OpenAI API key configured",
            lifecycle_owner=lifecycle_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        return result

    if self.request.retries == 0:
        publish_event(
            job_id,
            "job.started",
            {
                "worker_id": worker_id,
                "stage": "llm_optimization",
            },
        )
    else:
        publish_event(
            job_id,
            "job.retrying",
            {
                "worker_id": worker_id,
                "stage": "llm_optimization",
                "attempt": self.request.retries + 1,
            },
        )

    current_stage = "llm_optimization"
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
            model=model,
            persona=persona,
            industry=industry,
            seniority=seniority,
            tone=tone,
            emphasize=emphasize,
            downplay=downplay,
        )

        if is_cancelled(job_id):
            result = {"success": False, "job_id": job_id, "cancelled": True}
            _publish_combined_terminal(job_id, result, {}, quota_refund, event_type="job.cancelled")
            # Same terminal-state obligation as the failure paths: DELETE /jobs/{id}
            # must not leave the row wedged at "processing".
            reconcile_compilation_record(
                job_id,
                success=False,
                status="cancelled",
                error_message="cancelled",
                lifecycle_owner=lifecycle_owner,
                lifecycle_epoch=lifecycle_epoch,
                terminal_result=result,
            )
            return result

        current_stage = "latex_compilation"
        # ================================================================ #
        # Stage 2 — LaTeX compilation with log streaming (40% → 80%)      #
        # ================================================================ #
        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 40,
                "stage": "latex_compilation",
                "message": "Starting LaTeX compilation",
            },
        )

        compilation_ok, compilation_time, compile_error, page_count, pdf_bytes = _run_latex_stage(
            job_id=job_id,
            latex_content=optimized_latex,
            compiler=compiler,
            timeout_seconds=compile_timeout,
            bibtex=(compile_settings or {}).get("bibtex"),
            halt_on_error=(compile_settings or {}).get("halt_on_error") is not False,
            draft_mode=(compile_settings or {}).get("draft_mode") is True,
            main_file=(compile_settings or {}).get("main_file"),
            extra_packages=(compile_settings or {}).get("extra_packages"),
            latexmk_flags=(compile_settings or {}).get("latexmk_flags"),
        )

        if is_cancelled(job_id):
            result = {"success": False, "job_id": job_id, "cancelled": True}
            _publish_combined_terminal(job_id, result, {}, quota_refund, event_type="job.cancelled")
            reconcile_compilation_record(
                job_id,
                success=False,
                status="cancelled",
                compilation_time=compilation_time,
                error_message="cancelled",
                lifecycle_owner=lifecycle_owner,
                lifecycle_epoch=lifecycle_epoch,
                terminal_result=result,
            )
            return result

        if not compilation_ok:
            # Differentiate timeout errors from regular LaTeX errors
            is_timeout = "timed out" in compile_error or compile_error == "compile_timeout"
            error_code = "compile_timeout" if is_timeout else "latex_error"
            result = {
                "success": False,
                "job_id": job_id,
                "error": "LaTeX compilation failed",
                "optimized_latex": optimized_latex,
            }
            _publish_combined_terminal(job_id, result, {
                    "stage": "latex_compilation",
                    "error_code": error_code,
                    "error_message": compile_error,
                    **({"timeout_seconds": int(compile_timeout)} if is_timeout else {}),
                    **(
                        {
                            "upgrade_message": "Upgrade to Pro for a 4-minute compile timeout",
                            "user_plan": user_plan,
                        }
                        if is_timeout and resolve_plan_family(user_plan) in {"free", "basic"}
                        else {}
                    ),
                    "retryable": False,
                    "optimized_latex": optimized_latex,
                    "changes_made": changes_made,
                }, quota_refund)
            reconcile_compilation_record(
                job_id,
                success=False,
                compilation_time=compilation_time,
                error_message=compile_error,
                lifecycle_owner=lifecycle_owner,
                lifecycle_epoch=lifecycle_epoch,
                terminal_result=result,
            )
            _log_task_timing(
                error_code,
                optimization_seconds=optimization_time,
                compile_subprocess_seconds=compilation_time,
            )
            return result

        # Keep combined compilation's presentation metadata in parity with the
        # direct LaTeX worker.  Detection must use the shared comment-aware
        # helper so a commented-out documentclass cannot be reported as Beamer.
        is_beamer = is_beamer_document(optimized_latex)
        slide_count = page_count if is_beamer else None

        # ================================================================ #
        current_stage = "ats_scoring"
        # Stage 3 — ATS scoring (80% → 100%)                              #
        # ================================================================ #
        publish_event(
            job_id,
            "job.progress",
            {
                "percent": 80,
                "stage": "ats_scoring",
                "message": "Scoring ATS compatibility",
            },
        )

        _ats_start = time.monotonic()
        ats_score, ats_details = _run_ats_stage(
            job_id=job_id,
            latex_content=optimized_latex,
            job_description=job_description,
        )
        _ats_scoring_seconds = time.monotonic() - _ats_start
        _reporting_start = time.monotonic()

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
            "page_count": page_count,
            "slide_count": slide_count,
            "is_beamer": is_beamer,
            "pdf_size": len(pdf_bytes) if pdf_bytes else None,
        }

        _resume_id = resume_id or (metadata or {}).get("resume_id")
        generated_resume_content = None
        expected_resume_sha256 = None
        if (metadata or {}).get("persist_optimized_resume") and _resume_id and user_id:
            expected_latex_content = (metadata or {}).get("expected_latex_content")
            generated_resume_content = optimized_latex
            if isinstance(expected_latex_content, str):
                expected_resume_sha256 = hashlib.sha256(
                    expected_latex_content.encode("utf-8")
                ).hexdigest()

        replayed = False
        if lifecycle_owned:
            if not begin_finalizing(queue_redis, job_id, lifecycle_owner, lifecycle_epoch):
                return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
            finalization = commit_latex_finalization(
                job_id,
                lifecycle_owner,
                lifecycle_epoch,
                result,
                pdf_bytes,
                compilation_time,
                resume_id=_resume_id if generated_resume_content is not None else None,
                resume_user_id=user_id if generated_resume_content is not None else None,
                resume_content=generated_resume_content,
                expected_resume_sha256=expected_resume_sha256,
            )
            if not finalization:
                failure_result = finalization.canonical_result or {
                    **result,
                    "success": False,
                    "error": "Job finalization unavailable",
                }
                _publish_combined_terminal(
                    job_id,
                    failure_result,
                    {
                        "stage": "finalization",
                        "error_code": failure_result.get("error", "finalization_failed"),
                        "error_message": failure_result.get("error", "Job finalization unavailable"),
                        "retryable": False,
                    },
                    quota_refund,
                )
                return failure_result
            replayed = finalization.replayed
            result = finalization.canonical_result or result
        else:
            # Ownerless legacy jobs keep the historical generated-resume CAS
            # contract. Lifecycle-owned jobs pass this content to the typed
            # commit above, so they never mutate Resume in a separate commit.
            if (metadata or {}).get("persist_optimized_resume") and _resume_id and user_id:
                from .auto_save_worker import ResumePersistenceConflict, persist_resume_content

                expected_latex_content = (metadata or {}).get("expected_latex_content")
                persisted = False
                persistence_code = "resume_persistence_conflict"
                persistence_error = "Tailored output could not be applied without its dispatch snapshot"
                if isinstance(expected_latex_content, str):
                    try:
                        persisted = persist_resume_content(
                            _resume_id,
                            user_id,
                            optimized_latex,
                            expected_latex_content=expected_latex_content,
                        )
                        persistence_code = "resume_persistence_failed"
                        persistence_error = "Tailored resume could not be saved"
                    except ResumePersistenceConflict:
                        persistence_error = (
                            "Tailored output was not applied because the resume changed while it was running"
                        )
                if not persisted:
                    failure_result = {**result, "success": False, "error": persistence_error}
                    _publish_combined_terminal(
                        job_id,
                        failure_result,
                        {
                            "stage": "resume_persistence",
                            "error_code": persistence_code,
                            "error_message": persistence_error,
                            "retryable": False,
                            "optimized_latex": optimized_latex,
                            "changes_made": changes_made,
                        },
                        quota_refund,
                    )
                    reconcile_compilation_record(
                        job_id,
                        success=False,
                        compilation_time=compilation_time,
                        error_message=persistence_error,
                        lifecycle_owner=lifecycle_owner,
                        lifecycle_epoch=lifecycle_epoch,
                        terminal_result=failure_result,
                    )
                    _log_task_timing(
                        "resume_persistence_failed",
                        optimization_seconds=optimization_time,
                        compile_subprocess_seconds=compilation_time,
                        ats_scoring_seconds=_ats_scoring_seconds,
                        reporting_start=_reporting_start,
                    )
                    return failure_result
            persistence_outcome = reconcile_compilation_record(
                job_id,
                success=True,
                compilation_time=compilation_time,
                pdf_bytes=pdf_bytes,
                lifecycle_owner=lifecycle_owner if lifecycle_owned else None,
                lifecycle_epoch=lifecycle_epoch if lifecycle_owned else None,
            )
            if persistence_outcome == CompilationPersistenceOutcome.STORAGE_FAILURE:
                return {"success": False, "job_id": job_id, "error": "Compiled PDF could not be durably stored"}
        if not publish_job_result(job_id, result):
            return {"success": False, "job_id": job_id, "error": "Job ownership expired"}
        completion_event = publish_event(
            job_id,
            "job.completed",
            {
                "percent": 100,
                "pdf_job_id": job_id,
                "ats_score": result.get("ats_score", ats_score),
                "ats_details": result.get("ats_details", ats_details),
                "changes_made": result.get("changes_made", changes_made),
                "compilation_time": result.get("compilation_time", compilation_time),
                "optimization_time": result.get("optimization_time", optimization_time),
                "tokens_used": result.get("tokens_used", tokens_used),
                "page_count": result.get("page_count", page_count),
                "slide_count": result.get("slide_count", slide_count),
                "is_beamer": result.get("is_beamer", is_beamer),
                "compiler": result.get("compiler", compiler),
            },
        )
        logger.info(
            f"Orchestrator task {task_id} succeeded for job {job_id} "
            f"(ATS {result.get('ats_score', ats_score):.1f}, {result.get('tokens_used', tokens_used)} tokens, {result.get('compilation_time', compilation_time):.1f}s)"
        )
        if quota_refund and completion_event:
            clear_quota_refund_receipt(job_id)
        _log_task_timing(
            "success",
            optimization_seconds=optimization_time,
            compile_subprocess_seconds=compilation_time,
            ats_scoring_seconds=_ats_scoring_seconds,
            reporting_start=_reporting_start,
        )

        # Auto-save checkpoint if resume_id is known
        if not replayed and _resume_id and user_id:
            from .auto_save_worker import submit_auto_save_checkpoint

            submit_auto_save_checkpoint(_resume_id, user_id, optimized_latex)

        # Email notification (Feature 19) — fire-and-forget, non-critical
        # Guard on _resume_id to avoid broken workspace links in the email
        if not replayed and user_id and _resume_id:
            from .email_worker import submit_job_completion_email

            submit_job_completion_email(
                user_id,
                "llm_optimization",
                job_id,
                result_summary={"ats_score": result.get("ats_score", ats_score), "resume_id": _resume_id},
            )

        return result

    except LLMStreamCancelled:
        # Cancellation is terminal user intent, not a transient provider error.
        # Retrying here would issue a second billed LLM request and eventually
        # misreport the cancelled job as an internal failure.
        result = {"success": False, "job_id": job_id, "cancelled": True}
        _publish_combined_terminal(job_id, result, {}, quota_refund, event_type="job.cancelled")
        reconcile_compilation_record(
            job_id,
            success=False,
            status="cancelled",
            error_message="cancelled",
            lifecycle_owner=lifecycle_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("cancelled")
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Orchestrator task {task_id} exceeded soft time limit for job {job_id}", exc_info=True)
        upgrade_msg = (
            "Upgrade to Pro for a 4-minute compile timeout"
            if resolve_plan_family(user_plan) in {"free", "basic"}
            else None
        )
        result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
        _publish_combined_terminal(job_id, result, {
                "stage": current_stage,
                "error_code": "compile_timeout",
                "error_message": f"Task exceeded time limit ({user_plan} plan)",
                "upgrade_message": upgrade_msg,
                "user_plan": user_plan,
                "timeout_seconds": int(compile_timeout),
                "retryable": False,
            }, quota_refund)
        reconcile_compilation_record(
            job_id,
            success=False,
            error_message="compile_timeout",
            lifecycle_owner=lifecycle_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("soft_time_limit_exceeded")
        return result

    except Exception as exc:
        logger.error("Orchestrator task %s raised", task_id, extra={"error_type": type(exc).__name__})
        if self.request.retries < self.max_retries:
            # A retry is scheduled — emit a transient 'retrying' event instead of a
            # terminal job.failed so the client doesn't surface a spurious failure for a
            # job that may still succeed on retry.
            publish_event(
                job_id,
                "job.retrying",
                {
                    "stage": current_stage,
                    "worker_id": worker_id,
                    "attempt": self.request.retries + 2,
                    "error_message": "Compilation task is retrying",
                },
            )
            _log_task_timing("retrying")
            raise self.retry(countdown=min(60 * (2**self.request.retries), 600), exc=exc)
        result = {"success": False, "job_id": job_id, "error": "Compilation task failed"}
        _publish_combined_terminal(job_id, result, {
                "stage": current_stage,
                "error_code": "internal",
                "error_message": "Compilation task failed",
                "retryable": False,
            }, quota_refund)
        reconcile_compilation_record(
            job_id,
            success=False,
            error_message="Compilation task failed",
            lifecycle_owner=lifecycle_owner,
            lifecycle_epoch=lifecycle_epoch,
            terminal_result=result,
        )
        _log_task_timing("exception")
        return result


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
    model: Optional[str] = None,
    persona: Optional[str] = None,
    industry: Optional[str] = None,
    seniority: Optional[str] = None,
    tone: Optional[str] = None,
    emphasize: Optional[List[str]] = None,
    downplay: Optional[List[str]] = None,
) -> tuple[str, List[Dict], int, float]:
    """
    Stream OpenAI tokens through a delimiter state machine.

    Only LaTeX tokens inside <<<LATEX>>>...<<<END_LATEX>>> are published
    via llm.token events — the JSON scaffold never reaches the Monaco editor.

    Returns (optimized_latex, changes_made, tokens_total, optimization_time).
    """
    publish_event(
        job_id,
        "job.progress",
        {
            "percent": 5,
            "stage": "llm_optimization",
            "message": "Building optimization prompt",
        },
    )

    keywords = llm_service.extract_keywords_from_job_description(job_description)
    prompt = llm_service._create_optimization_prompt(  # noqa: SLF001
        latex_content,
        job_description,
        keywords,
        optimization_level,
        target_sections=target_sections,
        custom_instructions=custom_instructions,
        industry=industry,
        seniority=seniority,
        tone=tone,
        emphasize=emphasize,
        downplay=downplay,
    )

    publish_event(
        job_id,
        "job.progress",
        {
            "percent": 10,
            "stage": "llm_optimization",
            "message": "Streaming LLM response",
        },
    )

    # Route the PLATFORM key through an OpenAI-compatible base URL when configured
    # (e.g. Gemini). BYOK keys always use native OpenAI and never inherit the
    # platform model override.
    _use_platform_base = bool(settings.OPENAI_BASE_URL) and api_key == settings.OPENAI_API_KEY
    if _use_platform_base:
        client = openai.OpenAI(api_key=api_key, base_url=settings.OPENAI_BASE_URL)
        effective_model = model or settings.OPENAI_MODEL
    else:
        client = openai.OpenAI(api_key=api_key)
        effective_model = model or ("gpt-4o-mini" if settings.OPENAI_BASE_URL else settings.OPENAI_MODEL)
    start_time = time.time()
    accumulated = ""
    token_count = 0
    tokens_total = 0
    finish_reason: Optional[str] = None

    base_system = (
        "You are an expert resume optimizer specializing in ATS-friendly "
        "LaTeX resumes. You help job seekers optimize their resumes for "
        "specific job descriptions while maintaining professional formatting."
    )
    persona_config = PERSONAS.get(persona or "")
    system_content = f"{base_system} {persona_config['prompt_addon']}" if persona_config else base_system

    create_kwargs = dict(
        model=effective_model,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ],
        max_tokens=settings.OPENAI_MAX_TOKENS,
        temperature=settings.OPENAI_TEMPERATURE,
        stream=True,
        stream_options={"include_usage": True},
    )
    # Gemini's OpenAI-compat models "think" by default, consuming the token
    # budget before emitting the closing <<<END_LATEX>>> delimiter and breaking
    # the parser. Disable it on the platform-base (Gemini) path only.
    if _use_platform_base:
        create_kwargs["extra_body"] = {"reasoning_effort": "none"}
    stream = client.chat.completions.create(**create_kwargs)

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
        choice = chunk.choices[0]
        reason = getattr(choice, "finish_reason", None)
        if isinstance(reason, str):
            finish_reason = reason
        delta = choice.delta.content
        if not delta:
            continue

        accumulated += delta
        token_count += 1
        buf += delta

        if token_count % 20 == 0 and is_cancelled(job_id):
            raise LLMStreamCancelled("Job cancelled during LLM streaming")

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
                        buf = buf[-len(_LS) :]  # keep potential partial match
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
                        buf = buf[-len(_CS) :]
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

    # Never publish or compile a response the provider explicitly says was cut
    # off by the output-token limit. It can contain a deceptively valid prefix
    # (or even the closing LaTeX delimiter while truncating the change payload),
    # but it is not the complete response the user paid for.
    if finish_reason == "length":
        raise RuntimeError("AI output reached the configured token limit before completion.")

    # A provider can end a syntactically complete response without emitting the
    # requested closing delimiter (or can omit only the changes delimiter). The
    # streaming state machine intentionally holds back delimiter-length tails,
    # so failing to flush here silently truncates valid LaTeX such as
    # ``\\end{document}``. Preserve the residual content; the shared LaTeX
    # validator still rejects an actually incomplete/unsafe document before it
    # reaches the compiler.
    if buf and llm_state == _IN_LATEX:
        latex_parts.append(buf)
        publish_event(job_id, "llm.token", {"token": buf})
        buf = ""
    elif buf and llm_state == _IN_CHANGES:
        changes_parts.append(buf)
        buf = ""

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
                optimized_latex = match.group(1).replace("\\n", "\n").replace('\\"', '"')
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
    publish_event(
        job_id,
        "llm.complete",
        {
            "full_content": optimized_latex,
            "tokens_total": tokens_total,
        },
    )

    return optimized_latex, changes_made, tokens_total, optimization_time


def _run_latex_stage(
    job_id: str,
    latex_content: str,
    compiler: str = "pdflatex",
    timeout_seconds: Optional[int] = None,
    bibtex: object = None,
    halt_on_error: bool = True,
    draft_mode: bool = False,
    main_file: Optional[str] = None,
    extra_packages: Optional[List[str]] = None,
    latexmk_flags: Optional[List[str]] = None,
) -> tuple[bool, float, str, Optional[int], Optional[bytes]]:
    """
    Write LaTeX, run the requested compiler (sandboxed Docker engine if available,
    else the opt-in local engine) with line-by-line log streaming.

    The LLM-produced LaTeX goes through the same latex_service.validate_latex_content
    gate as the direct compile path — the combined path used to skip it entirely, so a
    prompt-injected \\input{/etc/passwd} would have been compiled and its contents
    streamed back over the job's log.line events.

    Returns (success, compilation_time, error_message, page_count, pdf_bytes).
    The log and (on success) the PDF + SyncTeX data are cached in Redis before
    job_dir is removed, so GET /download/{job_id}, /logs/{job_id} and
    /download/{job_id}/synctex keep working — same artifacts as latex_worker.
    Does NOT publish job.failed — caller is responsible so it can
    include optimized_latex in the failure payload.
    """
    # Validate compiler
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        compiler = settings.DEFAULT_LATEX_COMPILER
    # Even worker payloads must respect the same filename/flag/package boundary
    # as the direct compile path. Keep artifact names stable independently of
    # the user's input filename.
    main_file = main_file if isinstance(main_file, str) and _MAIN_FILE_RE.fullmatch(main_file) else "resume.tex"
    custom_flags = [flag for flag in (latexmk_flags or []) if isinstance(flag, str) and flag in _ALLOWED_EXTRA_FLAGS]
    if isinstance(extra_packages, list):
        latex_content = _inject_packages(latex_content, extra_packages)
    if draft_mode:
        latex_content = _inject_draft_graphics(latex_content)

    # Shared content gate (same call the latex_compilation path makes)
    if not latex_service.validate_latex_content(latex_content):
        error_msg = (
            r"Invalid LaTeX: missing \documentclass, \begin{document}, "
            r"\end{document}, or disallowed file/shell primitives"
        )
        # This gate runs BEFORE the compiler ever starts, so there is no
        # pdflatex stdout to stream — without this, the Live Logs panel stays
        # completely empty on failure (the caller publishes job.failed from
        # the returned error_msg alone). Publish it as a log line too, so it
        # shows up the same way a real compiler failure's output would.
        publish_event(
            job_id,
            "log.line",
            {
                "line": f"! {error_msg}",
                "source": compiler,
                "is_error": True,
            },
        )
        return False, 0.0, error_msg, None, None

    job_dir = Path(settings.TEMP_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        tex_file = job_dir / main_file
        tex_file.write_text(latex_content, encoding="utf-8")
        materialize_embedded_signature(latex_content, job_dir)
        write_reference_library(job_dir, bibtex)
        error_mode_flags = ["-interaction=nonstopmode"]
        if halt_on_error:
            error_mode_flags.append("-halt-on-error")

        use_docker = docker_engine_available()
        container_name = docker_container_name(job_id, "orchestrator") if use_docker else None
        if use_docker:
            cmd = [
                "docker",
                "run",
                "--rm",
                "--name",
                container_name,
                *docker_sandbox_args(),
                "-v",
                f"{job_dir}:/workdir",
                "-w",
                "/workdir",
                settings.LATEX_DOCKER_IMAGE,
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-synctex=1",
                "-jobname",
                "resume",
                *custom_flags,
                main_file,
            ]
            cwd = None
            workspace = "/workdir"
        else:
            assert_local_engine_allowed(job_id)
            # Relative paths + cwd=job_dir: the sandbox sets openin_any/openout_any=p
            # (paranoid), under which kpathsea refuses ABSOLUTE read/write paths, so
            # an absolute /tmp/.../resume.tex fails with "Not reading … (openin_any=p)".
            cmd = [
                compiler,
                *LATEX_SANDBOX_FLAGS,
                *error_mode_flags,
                "-synctex=1",
                "-jobname",
                "resume",
                "-output-directory",
                ".",
                *custom_flags,
                main_file,
            ]
            cwd = str(job_dir)
            workspace = str(job_dir)

        timeout = float(timeout_seconds) if timeout_seconds else float(settings.COMPILE_TIMEOUT)
        _perf_start = time.perf_counter()
        with traced("latex.compile", compiler=compiler, docker=(cmd[0] == "docker")):
            start_time = time.time()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                env=engine_env(),
            )

            page_count: Optional[int] = None
            transcript = BoundedTranscript()
            watchdog = ProcessWatchdog(
                proc,
                timeout=timeout,
                is_cancelled=lambda: is_cancelled(job_id),
            ).start()
            try:
                for stripped in iter_bounded_lines(proc.stdout):
                    if stripped:
                        # Read confinement (see latex_service.find_engine_read_escape):
                        # kill before the line is streamed, because what follows it is
                        # the contents of whatever file was opened. \openin reads are
                        # invisible here — the recorder check after the run covers those.
                        escaped = find_engine_read_escape(stripped, workspace)
                        if escaped:
                            proc.kill()
                            cleanup_docker_container(container_name)
                            proc.wait()
                            logger.warning(f"[{job_id}] engine read outside the job directory: {escaped}")
                            return (
                                False,
                                time.time() - start_time,
                                ENGINE_READ_ESCAPE_ERROR,
                                None,
                                None,
                            )

                        bounded_line = transcript.append(stripped)

                        # Extract page count from pdflatex summary line
                        m = _PAGE_COUNT_RE.search(stripped)
                        if m:
                            page_count = int(m.group(1))

                        is_error = "error" in stripped.lower() or stripped.startswith("!")
                        if "fatal" in stripped.lower():
                            is_error = True
                        publish_event(
                            job_id,
                            "log.line",
                            {
                                "line": bounded_line,
                                "source": compiler,
                                "is_error": is_error,
                            },
                        )

                    if is_cancelled(job_id):
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        return False, time.time() - start_time, "cancelled", None, None

                    if time.time() - start_time > timeout:
                        proc.kill()
                        cleanup_docker_container(container_name)
                        proc.wait()
                        record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                        return (
                            False,
                            time.time() - start_time,
                            f"Compilation timed out after {int(timeout)}s",
                            None,
                            None,
                        )
            except SoftTimeLimitExceeded:
                # Kill the subprocess before the exception propagates to the task handler
                try:
                    proc.kill()
                    cleanup_docker_container(container_name)
                    proc.wait()
                except Exception:
                    pass
                raise
            except BaseException:
                # Any parser/publisher/read failure must not strand a named
                # daemon container.  The cleanup helper validates the exact name.
                try:
                    proc.kill()
                except (ProcessLookupError, AttributeError):
                    pass
                try:
                    proc.wait()
                except (ProcessLookupError, AttributeError):
                    pass
                cleanup_docker_container(container_name)
                raise
            finally:
                watchdog_reason = watchdog.stop()

            if watchdog_reason == "cancelled":
                cleanup_docker_container(container_name)
                proc.wait()
                return False, time.time() - start_time, "cancelled", None, None
            if watchdog_reason == "timeout":
                cleanup_docker_container(container_name)
                proc.wait()
                record_compile("error", duration_seconds=time.perf_counter() - _perf_start)
                return (
                    False,
                    time.time() - start_time,
                    f"Compilation timed out after {int(timeout)}s",
                    None,
                    None,
                )

            proc.wait()
            compilation_time = time.time() - start_time
        _compile_duration = time.perf_counter() - _perf_start

        # Post-run read confinement: the -recorder .fls file lists every file the
        # engine opened, including the \openin reads the transcript never mentions.
        # Checked before the log is cached and before the PDF is published.
        recorder_escape = find_recorder_read_escape(
            job_dir / f"resume{RECORDER_SUFFIX}",
            workspace,
            require_recorder=proc.returncode == 0,
        )
        if recorder_escape:
            logger.warning(f"[{job_id}] engine read outside the job directory: {recorder_escape}")
            return False, compilation_time, ENGINE_READ_ESCAPE_ERROR, None, None

        cache_compile_log(job_id, transcript.text())

        pdf_file = job_dir / "resume.pdf"
        if proc.returncode == 0 and pdf_file.exists():
            try:
                _pdf_bytes = pdf_file.stat().st_size
            except OSError:
                _pdf_bytes = None
            if _pdf_bytes is not None and _pdf_bytes > MAX_COMPILED_PDF_BYTES:
                return (
                    False,
                    compilation_time,
                    f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit",
                    None,
                    None,
                )
            record_compile(
                "success",
                duration_seconds=_compile_duration,
                pdf_bytes=_pdf_bytes,
                pages=page_count,
            )
            # cache_compile_output caches the PDF (latexy:job:{id}:pdf) + SyncTeX
            # in Redis before job_dir is rmtree'd, so GET /download/{job_id}
            # works from the API container (Modal has no shared worker/API FS).
            # This supersedes the earlier inline PDF-only cache (same key).
            try:
                cached_pdf = cache_compile_output(job_id, job_dir)
            except BoundedReadError:
                return (
                    False,
                    compilation_time,
                    f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit",
                    None,
                    None,
                )
            return True, compilation_time, "", page_count, cached_pdf

        record_compile("error", duration_seconds=_compile_duration)
        return False, compilation_time, f"{compiler} exited with code {proc.returncode}", None, None
    finally:
        # ``--rm`` handles an exited container.  Force-remove only when the
        # client process was interrupted before it reported an exit, avoiding a
        # redundant Docker CLI call on successful/nonzero completion.
        process_obj = locals().get("proc")
        if locals().get("container_name") and (
            process_obj is None or getattr(process_obj, "returncode", None) is None
        ):
            cleanup_docker_container(locals().get("container_name"))
        shutil.rmtree(job_dir, ignore_errors=True)


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
        logger.warning("ATS scoring failed (non-fatal) for job %s", job_id, extra={"error_type": type(exc).__name__})
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
    model: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: str = "pdflatex",
    timeout_seconds: Optional[int] = None,
    persona: Optional[str] = None,
    industry: Optional[str] = None,
    seniority: Optional[str] = None,
    tone: Optional[str] = None,
    emphasize: Optional[List[str]] = None,
    downplay: Optional[List[str]] = None,
    compile_settings: Optional[Dict] = None,
    quota_refund: Optional[Dict[str, Any]] = None,
) -> str:
    """Enqueue optimize_and_compile_task on the combined queue."""
    if priority is None:
        priority = get_task_priority(user_plan)

    compile_timeout = timeout_seconds or get_compile_timeout(user_plan)
    # Task time_limit covers both LLM stage (~120s) + compile stage + buffer
    task_time_limit = compile_timeout + 180

    import os

    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn

        spawn(
            "run_orchestrator_task",
            {
                "latex_content": latex_content,
                "job_description": job_description,
                "job_id": job_id,
                "user_id": user_id,
                "user_plan": user_plan,
                "optimization_level": optimization_level,
                "user_api_key": user_api_key,
                "device_fingerprint": device_fingerprint,
                "target_sections": target_sections,
                "custom_instructions": custom_instructions,
                "model": model,
                "metadata": metadata,
                "resume_id": resume_id,
                "compiler": compiler,
                "timeout_seconds": compile_timeout,
                "persona": persona,
                "industry": industry,
                "seniority": seniority,
                "tone": tone,
                "emphasize": emphasize,
                "downplay": downplay,
                "compile_settings": compile_settings,
                "quota_refund": quota_refund,
            },
        )
        logger.info(f"Modal spawn: orchestrator for job {job_id} (compiler={compiler})")
        return job_id

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
            "model": model,
            "metadata": metadata,
            "resume_id": resume_id,
            "compiler": compiler,
            "timeout_seconds": compile_timeout,
            "persona": persona,
            "industry": industry,
            "seniority": seniority,
            "tone": tone,
            "emphasize": emphasize,
            "downplay": downplay,
            "compile_settings": compile_settings,
            "quota_refund": quota_refund,
        },
        priority=priority,
        queue="combined",
        task_id=job_id,
        time_limit=task_time_limit,
        soft_time_limit=task_time_limit - 30,
    )
    logger.info(
        f"Submitted optimize-and-compile for job {job_id} (compiler={compiler}, compile_timeout={compile_timeout}s)"
    )
    return job_id

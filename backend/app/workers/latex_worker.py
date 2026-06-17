"""
LaTeX compilation worker — event-driven rebuild.

Streams pdflatex log lines via publish_event() instead of collecting
them all at once.  Uses subprocess.Popen for line-by-line stdout
streaming.  Zero asyncio — all Redis I/O goes through event_publisher.
"""

import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app, get_task_priority
from ..core.config import get_compile_timeout, resolve_plan_family, settings
from ..core.logging import get_logger
from ..services.latex_service import latex_service
from ..workers.event_publisher import is_cancelled, publish_event, publish_job_result

logger = get_logger(__name__)

PAGE_COUNT_RE = re.compile(r"Output written on .*?\((\d+) page", re.IGNORECASE)
BEAMER_RE = re.compile(r"\\documentclass\s*(?:\[.*?\])?\s*\{beamer\}", re.DOTALL)

# Flags allowed to be appended from compile_settings (must match resume_routes whitelist)
# NOTE: --shell-escape is intentionally excluded — it enables arbitrary code execution
_ALLOWED_EXTRA_FLAGS = {
    "--file-line-error",
}
# Note: --synctex=1, --interaction=nonstopmode, --halt-on-error are already hardcoded

_MAIN_FILE_RE = re.compile(r"^[a-zA-Z0-9_-]+\.tex$")
_HOST_PDFTOTEXT_CANDIDATES = (
    "/opt/homebrew/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "/usr/bin/pdftotext",
)

# Watermark validation
_WATERMARK_RE = re.compile(r"^[A-Za-z0-9 \-\.]+$")
_WATERMARK_MAX_LEN = 30

_PDFTOTEXT_FALLBACK_PATHS = (
    "/opt/homebrew/bin/pdftotext",
    "/usr/local/bin/pdftotext",
    "/usr/bin/pdftotext",
)


def _inject_watermark(latex_content: str, watermark_text: str) -> str:
    """Inject draftwatermark directives immediately before \\begin{document}."""
    marker = r"\begin{document}"
    pos = latex_content.find(marker)
    if pos == -1:
        return latex_content  # Validation should have caught this; leave unchanged
    watermark_block = (
        "\\usepackage{draftwatermark}\n"
        f"\\SetWatermarkText{{{watermark_text}}}\n"
        "\\SetWatermarkScale{1.2}\n"
        "\\SetWatermarkColor[gray]{0.94}\n"
    )
    return latex_content[:pos] + watermark_block + latex_content[pos:]


def _inject_packages(latex_content: str, packages: list) -> str:
    """Prepend \\usepackage{pkg} directives after \\documentclass line for any missing package."""
    docclass_match = re.search(r"\\documentclass[^\n]*\n", latex_content)
    if not docclass_match:
        return latex_content  # Can't find safe insertion point
    insert_pos = docclass_match.end()
    lines_to_insert = [
        f"\\usepackage{{{pkg}}}"
        for pkg in packages
        if f"\\usepackage{{{pkg}}}" not in latex_content
    ]
    if not lines_to_insert:
        return latex_content
    return latex_content[:insert_pos] + "\n".join(lines_to_insert) + "\n" + latex_content[insert_pos:]


def _resolve_pdftotext_binary() -> Optional[str]:
    """Find a usable host pdftotext binary for ATS text extraction."""
    binary = shutil.which("pdftotext")
    if binary:
        return binary
    for candidate in _PDFTOTEXT_FALLBACK_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def _extract_pdf_text(pdf_file: Path, job_id: str) -> Optional[str]:
    """Extract text from the compiled PDF with host pdftotext, then pdfminer fallback."""
    pdftotext_bin = _resolve_pdftotext_binary()
    if pdftotext_bin:
        for attempt in range(1, 4):
            try:
                pt_result = subprocess.run(
                    [pdftotext_bin, "-layout", str(pdf_file), "-"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if pt_result.returncode == 0 and pt_result.stdout.strip():
                    return pt_result.stdout
                logger.warning(
                    "pdftotext returned empty output for job %s on attempt %s",
                    job_id,
                    attempt,
                )
            except Exception as exc:
                logger.warning(
                    "pdftotext failed for job %s on attempt %s: %s",
                    job_id,
                    attempt,
                    exc,
                )
            if attempt < 3:
                time.sleep(0.5)
    else:
        logger.warning("pdftotext binary not found for job %s; falling back to pdfminer", job_id)

    try:
        from pdfminer.high_level import extract_text

        extracted_text = extract_text(str(pdf_file))
        return extracted_text if extracted_text and extracted_text.strip() else None
    except Exception as exc:
        logger.warning("pdfminer extraction failed for job %s: %s", job_id, exc)
        return None


@celery_app.task(
    bind=True,
    name="app.workers.latex_worker.compile_latex_task",
    max_retries=3,
    default_retry_delay=60,
)
def compile_latex_task(
    self,
    latex_content: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    compile_settings: Optional[Dict] = None,
    watermark: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compile LaTeX content to PDF, streaming each pdflatex log line as
    a log.line event.  Publishes job.completed on success or job.failed
    on error.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())

    # Resolve and validate compiler — None means "use configured default"
    compiler = compiler or settings.DEFAULT_LATEX_COMPILER
    if compiler not in settings.ALLOWED_LATEX_COMPILERS:
        logger.warning(f"Invalid compiler '{compiler}', falling back to {settings.DEFAULT_LATEX_COMPILER}")
        compiler = settings.DEFAULT_LATEX_COMPILER

    # Resolve per-plan compile timeout
    timeout = float(timeout_seconds) if timeout_seconds else float(get_compile_timeout(user_plan))

    task_id = self.request.id
    worker_id = f"latex-{task_id}"
    logger.info(f"LaTeX task {task_id} starting for job {job_id} (compiler={compiler})")

    if self.request.retries == 0:
        publish_event(job_id, "job.started", {
            "worker_id": worker_id,
            "stage": "latex_compilation",
        })
    else:
        publish_event(job_id, "job.retrying", {
            "worker_id": worker_id,
            "stage": "latex_compilation",
            "attempt": self.request.retries + 1,
        })

    job_dir: Optional[Path] = None
    try:
        # ── Validation ──────────────────────────────────────────────
        publish_event(job_id, "job.progress", {
            "percent": 5,
            "stage": "latex_compilation",
            "message": "Validating LaTeX content",
        })

        if not latex_service.validate_latex_content(latex_content):
            error_msg = (
                r"Invalid LaTeX: missing \documentclass, "
                r"\begin{document}, or \end{document}"
            )
            publish_event(job_id, "job.failed", {
                "stage": "latex_compilation",
                "error_code": "latex_error",
                "error_message": error_msg,
                "retryable": False,
            })
            result = {"success": False, "job_id": job_id, "error": error_msg}
            publish_job_result(job_id, result)
            return result

        # ── Apply compile settings ───────────────────────────────────
        _cs = compile_settings or {}

        # Inject extra packages if any
        extra_packages = _cs.get("extra_packages") or []
        if extra_packages and isinstance(extra_packages, list):
            latex_content = _inject_packages(latex_content, extra_packages)

        # Inject watermark if requested
        if watermark:
            if not _WATERMARK_RE.match(watermark) or len(watermark) > _WATERMARK_MAX_LEN:
                error_msg = "Invalid watermark text"
                publish_event(job_id, "job.failed", {
                    "stage": "latex_compilation",
                    "error_code": "invalid_watermark",
                    "error_message": error_msg,
                    "retryable": False,
                })
                result = {"success": False, "job_id": job_id, "error": error_msg}
                publish_job_result(job_id, result)
                return result
            latex_content = _inject_watermark(latex_content, watermark)

        # Determine main .tex filename (validated regex, default resume.tex)
        main_file = str(_cs.get("main_file") or "resume.tex")
        if not _MAIN_FILE_RE.match(main_file):
            main_file = "resume.tex"

        # Extra flags — only from the safe subset (skip flags already hardcoded)
        custom_flags = [
            f for f in (_cs.get("latexmk_flags") or [])
            if f in _ALLOWED_EXTRA_FLAGS
        ]

        # ── Setup ────────────────────────────────────────────────────
        job_dir = Path(settings.TEMP_DIR) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        # job_dir is now set; finally block will clean it up
        tex_file = job_dir / main_file
        tex_file.write_text(latex_content, encoding="utf-8")

        publish_event(job_id, "job.progress", {
            "percent": 10,
            "stage": "latex_compilation",
            "message": f"Starting {compiler} compilation",
        })

        # ── Compile ──────────────────────────────────────────────────
        _use_docker = shutil.which("docker") is not None
        if _use_docker:
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{job_dir}:/workspace",
                "-w", "/workspace",
                settings.LATEX_DOCKER_IMAGE,
                compiler,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-synctex=1",
                "-output-directory", "/workspace",
                "-jobname", "resume",
                *custom_flags,
                main_file,
            ]
            compile_cwd = None
        else:
            cmd = [
                compiler,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-synctex=1",
                "-jobname", "resume",
                "-output-directory", str(job_dir),
                *custom_flags,
                str(tex_file),
            ]
            compile_cwd = str(job_dir)

        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=compile_cwd,
        )

        # ── Detect Beamer presentation ───────────────────────────────
        is_beamer = bool(BEAMER_RE.search(latex_content))

        # ── Stream log lines ─────────────────────────────────────────
        page_count: Optional[int] = None
        first_latex_error: Optional[str] = None  # first "! ..." line from pdflatex
        all_output_lines: list = []  # accumulated for stderr tail on failure
        for line in proc.stdout:
            stripped = line.rstrip()
            if not stripped:
                continue

            all_output_lines.append(stripped)

            # Extract page count from pdflatex summary line
            m = PAGE_COUNT_RE.search(stripped)
            if m:
                page_count = int(m.group(1))

            # Capture the first "! <error type>" line for persistent storage
            if first_latex_error is None and stripped.startswith("!"):
                first_latex_error = stripped[:250]

            is_error_line = (
                "error" in stripped.lower()
                or stripped.startswith("!")
                or "fatal" in stripped.lower()
            )
            publish_event(job_id, "log.line", {
                "line": stripped,
                "source": compiler,
                "is_error": is_error_line,
            })

            # ── Cancellation check ───────────────────────────────────
            if is_cancelled(job_id):
                proc.kill()
                publish_event(job_id, "job.cancelled", {})
                result = {"success": False, "job_id": job_id, "cancelled": True}
                publish_job_result(job_id, result)
                return result

            # ── Timeout check ────────────────────────────────────────
            if time.time() - start_time > timeout:
                proc.kill()
                upgrade_msg = (
                    "Upgrade to Pro for a 4-minute compile timeout"
                    if resolve_plan_family(user_plan) in {"free", "basic"} else None
                )
                publish_event(job_id, "job.failed", {
                    "stage": "latex_compilation",
                    "error_code": "compile_timeout",
                    "error_message": f"Compilation timed out after {int(timeout)}s ({user_plan} plan limit)",
                    "upgrade_message": upgrade_msg,
                    "user_plan": user_plan,
                    "retryable": False,
                })
                result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
                publish_job_result(job_id, result)
                return result

        proc.wait()
        compilation_time = time.time() - start_time

        publish_event(job_id, "job.progress", {
            "percent": 90,
            "stage": "latex_compilation",
            "message": "Finalizing PDF",
        })

        # ── Success / failure ────────────────────────────────────────
        pdf_file = job_dir / "resume.pdf"

        if proc.returncode == 0 and pdf_file.exists():
            pdf_size = pdf_file.stat().st_size

            # ── PDF text extraction for ATS pre-flight ───────────────
            extracted_text = _extract_pdf_text(pdf_file, job_id)

            # For Beamer, slide_count == page_count (one PDF page per slide)
            slide_count = page_count if is_beamer else None

            result = {
                "success": True,
                "job_id": job_id,
                "pdf_job_id": job_id,
                "compilation_time": compilation_time,
                "pdf_size": pdf_size,
                "page_count": page_count,
                "slide_count": slide_count,
                "is_beamer": is_beamer,
                "extracted_text": extracted_text,
            }
            publish_job_result(job_id, result)

            # Publish extracted text as a dedicated event before job.completed
            if extracted_text is not None:
                publish_event(job_id, "job.pdf_extracted", {
                    "text": extracted_text,
                    "page_count": page_count or 1,
                })

            publish_event(job_id, "job.completed", {
                "pdf_job_id": job_id,
                "ats_score": 0.0,
                "ats_details": {},
                "changes_made": [],
                "compilation_time": compilation_time,
                "optimization_time": 0.0,
                "tokens_used": 0,
                "page_count": page_count,
                "slide_count": slide_count,
                "is_beamer": is_beamer,
                "compiler": compiler,
            })
            logger.info(
                f"LaTeX task {task_id} succeeded for job {job_id} ({pdf_size} bytes)"
            )

            # Auto-save checkpoint if resume_id is known (skip for watermarked compiles)
            _resume_id = resume_id or (metadata or {}).get("resume_id")
            if _resume_id and user_id and not watermark:
                try:
                    from .auto_save_worker import record_auto_save_checkpoint
                    record_auto_save_checkpoint.apply_async(
                        args=[_resume_id, user_id, latex_content],
                        queue="cleanup",
                    )
                except Exception as auto_exc:
                    logger.warning(f"Failed to enqueue auto-save for resume {_resume_id}: {auto_exc}")

            return result

        error_msg = f"{compiler} exited with code {proc.returncode}"
        stderr = "\n".join(all_output_lines)
        logger.error(
            "latex_compile_failed",
            extra={
                "job_id": job_id,
                "returncode": proc.returncode,
                "stderr_tail": stderr[-500:] if stderr else "",
            },
        )
        publish_event(job_id, "job.failed", {
            "stage": "latex_compilation",
            "error_code": "latex_error",
            "error_message": error_msg,
            "retryable": False,
        })
        result: Dict[str, Any] = {"success": False, "job_id": job_id, "error": error_msg}
        if first_latex_error:
            result["latex_error_line"] = first_latex_error
        publish_job_result(job_id, result)
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"LaTeX task {task_id} hit soft time limit for job {job_id}", exc_info=True)
        # Kill the subprocess if it was started before the limit fired
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        upgrade_msg = (
            "Upgrade to Pro for a 4-minute compile timeout"
            if resolve_plan_family(user_plan) in {"free", "basic"} else None
        )
        publish_event(job_id, "job.failed", {
            "stage": "latex_compilation",
            "error_code": "compile_timeout",
            "error_message": f"Compilation timed out after {int(timeout)}s ({user_plan} plan limit)",
            "upgrade_message": upgrade_msg,
            "user_plan": user_plan,
            "retryable": False,
        })
        result = {"success": False, "job_id": job_id, "error": "compile_timeout"}
        publish_job_result(job_id, result)
        return result

    except Exception as exc:
        logger.error(f"LaTeX task {task_id} raised: {exc}", exc_info=True)
        retryable = self.request.retries < self.max_retries
        publish_event(job_id, "job.failed", {
            "stage": "latex_compilation",
            "error_code": "internal",
            "error_message": str(exc),
            "retryable": retryable,
        })
        if retryable:
            raise self.retry(countdown=min(60 * (2 ** self.request.retries), 600), exc=exc)
        result = {"success": False, "job_id": job_id, "error": str(exc)}
        publish_job_result(job_id, result)
        return result
    finally:
        if job_dir is not None and job_dir.exists():
            try:
                shutil.rmtree(job_dir)
            except Exception as cleanup_exc:
                logger.warning("Failed to remove job_dir %s: %s", job_dir, cleanup_exc)


# ------------------------------------------------------------------ #
#  Submission helper                                                   #
# ------------------------------------------------------------------ #

def submit_latex_compilation(
    latex_content: str,
    job_id: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None,
    resume_id: Optional[str] = None,
    compiler: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    compile_settings: Optional[Dict] = None,
    watermark: Optional[str] = None,
) -> str:
    """Enqueue compile_latex_task on the latex queue (Celery) or Modal."""
    import os
    if priority is None:
        priority = get_task_priority(user_plan)
    compiler = compiler or settings.DEFAULT_LATEX_COMPILER
    timeout = timeout_seconds or get_compile_timeout(user_plan)

    if os.environ.get("DEPLOY_TARGET") == "modal":
        from ..core.modal_dispatch import spawn
        spawn("run_latex_task", {
            "latex_content": latex_content,
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
            "resume_id": resume_id,
            "compiler": compiler,
            "timeout_seconds": timeout,
            "compile_settings": compile_settings,
            "watermark": watermark,
        })
        logger.info(f"Modal spawn: LaTeX compilation for job {job_id} (compiler={compiler})")
        return job_id

    compile_latex_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata,
            "resume_id": resume_id,
            "compiler": compiler,
            "timeout_seconds": timeout,
            "compile_settings": compile_settings,
            "watermark": watermark,
        },
        priority=priority,
        queue="latex",
        time_limit=timeout + 30,
        soft_time_limit=timeout + 15,
    )
    logger.info(f"Submitted LaTeX compilation for job {job_id} (compiler={compiler}, timeout={timeout}s)")
    return job_id

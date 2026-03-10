"""
LaTeX compilation service.
"""

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from ..core.config import settings
from ..core.logging import get_logger
from ..models.schemas import CompilationResponse

logger = get_logger(__name__)


class LaTeXService:
    """Service for LaTeX compilation operations."""

    def __init__(self):
        """Initialize the LaTeX service."""
        # Ensure temp directory exists
        settings.TEMP_DIR.mkdir(exist_ok=True)

    def validate_latex_content(self, content: str) -> bool:
        """Basic validation of LaTeX content."""
        if not content.strip():
            return False

        # Check for basic LaTeX structure
        has_document_class = "\\documentclass" in content
        has_begin_document = "\\begin{document}" in content
        has_end_document = "\\end{document}" in content

        return has_document_class and has_begin_document and has_end_document

    def check_latex_installation(self) -> bool:
        """Check if Docker and LaTeX Docker image are available."""
        try:
            # Check if Docker is available
            docker_result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if docker_result.returncode != 0:
                return False

            # Check if LaTeX Docker image is available
            image_result = subprocess.run(
                ["docker", "image", "inspect", settings.LATEX_DOCKER_IMAGE],
                capture_output=True,
                text=True,
                timeout=5
            )
            return image_result.returncode == 0
        except Exception:
            return False

    async def compile_latex(self, latex_content: str, job_id: Optional[str] = None) -> CompilationResponse:
        """Compile LaTeX content to PDF using Docker with LaTeX."""
        if job_id is None:
            job_id = str(uuid.uuid4())

        start_time = time.time()

        # Create job-specific directory
        job_dir = settings.TEMP_DIR / job_id
        job_dir.mkdir(exist_ok=True)

        tex_file = job_dir / "resume.tex"
        pdf_file = job_dir / "resume.pdf"
        log_file = job_dir / "resume.log"

        try:
            # Write LaTeX content to file
            tex_file.write_text(latex_content, encoding='utf-8')
            logger.info(f"Created LaTeX file for job {job_id}")

            # Docker command to compile LaTeX
            docker_cmd = [
                "docker", "run", "--rm",
                "-v", f"{job_dir}:/workspace",
                "-w", "/workspace",
                settings.LATEX_DOCKER_IMAGE,
                "pdflatex",
                "-interaction=nonstopmode",
                "-output-directory", "/workspace",
                "-jobname", "resume",
                "resume.tex"
            ]

            logger.info(f"Starting LaTeX compilation for job {job_id} using Docker")

            # Run compilation with timeout
            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=settings.COMPILE_TIMEOUT
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise HTTPException(
                    status_code=408,
                    detail=f"LaTeX compilation timed out after {settings.COMPILE_TIMEOUT} seconds"
                )

            compilation_time = time.time() - start_time

            # Read log output
            log_output = ""
            if log_file.exists():
                log_output = log_file.read_text(encoding='utf-8', errors='ignore')
            else:
                # If no log file, use stdout/stderr
                log_output = stdout.decode('utf-8', errors='ignore')
                if stderr:
                    log_output += "\n" + stderr.decode('utf-8', errors='ignore')

            # Check if compilation was successful
            if process.returncode == 0 and pdf_file.exists():
                pdf_size = pdf_file.stat().st_size
                logger.info(f"Compilation successful for job {job_id}. PDF size: {pdf_size} bytes")

                return CompilationResponse(
                    success=True,
                    job_id=job_id,
                    message="LaTeX compiled successfully",
                    compilation_time=compilation_time,
                    pdf_size=pdf_size,
                    log_output=log_output
                )
            else:
                error_msg = f"LaTeX compilation failed. Return code: {process.returncode}"
                if stderr:
                    error_msg += f"\nStderr: {stderr.decode('utf-8', errors='ignore')}"

                logger.error(f"Compilation failed for job {job_id}: {error_msg}")

                return CompilationResponse(
                    success=False,
                    job_id=job_id,
                    message="LaTeX compilation failed",
                    compilation_time=compilation_time,
                    log_output=log_output
                )

        except Exception as e:
            logger.error(f"Error during compilation for job {job_id}: {e}")
            return CompilationResponse(
                success=False,
                job_id=job_id,
                message=f"Compilation error: {str(e)}"
            )

    def cleanup_temp_files(self, job_dir: Path) -> None:
        """Clean up temporary files after compilation."""
        try:
            if job_dir.exists():
                shutil.rmtree(job_dir)
                logger.info(f"Cleaned up temporary directory: {job_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up {job_dir}: {e}")

    async def cleanup_temp_files_delayed(self, job_dir: Path, delay: int = 5):
        """Clean up temporary files after a delay."""
        await asyncio.sleep(delay)
        self.cleanup_temp_files(job_dir)


# Global service instance
latex_service = LaTeXService()


def run_latex_subprocess(
    job_id: str,
    latex_content: str,
    timeout: Optional[float] = None,
) -> tuple[bool, float, str]:
    """
    Shared synchronous LaTeX compilation helper used by both
    ``latex_worker.py`` and ``orchestrator.py``.

    Writes *latex_content* to ``{TEMP_DIR}/{job_id}/resume.tex``,
    runs pdflatex (Docker if available, else local texlive),
    streams every log line via ``publish_event``, honours
    cancellation flags and an optional *timeout*, then returns
    ``(success, compilation_time, error_message)``.

    Callers are responsible for publishing ``job.failed`` so they
    can include any extra payload (e.g. ``optimized_latex``).
    """
    # Lazy import to avoid circular imports (workers → services → workers)
    from ..workers.event_publisher import is_cancelled, publish_event  # noqa: PLC0415

    job_dir = settings.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    tex_file = job_dir / "resume.tex"
    pdf_file = job_dir / "resume.pdf"
    tex_file.write_text(latex_content, encoding="utf-8")

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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
        is_error = any(kw in line_lower for kw in ("error", "fatal", "undefined control"))
        publish_event(job_id, "log.line", {
            "source": "pdflatex",
            "line": line,
            "is_error": is_error,
        })

        if timeout is not None and time.time() - start_time > timeout:
            proc.kill()
            proc.wait()
            return False, time.time() - start_time, f"pdflatex timed out after {timeout:.0f}s"

        if is_cancelled(job_id):
            proc.kill()
            proc.wait()
            raise RuntimeError("Job cancelled during LaTeX compilation")

    proc.wait()
    compilation_time = time.time() - start_time

    if proc.returncode == 0 and pdf_file.exists():
        return True, compilation_time, ""

    return False, compilation_time, (
        f"pdflatex exited with code {proc.returncode}. "
        "See log.line events for details."
    )

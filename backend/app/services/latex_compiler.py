"""
LaTeX Compilation Service
Handles LaTeX to PDF compilation with proper error handling and Docker support.
"""

import asyncio
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..core.config import settings
from ..utils.bounded_io import MAX_COMPILED_PDF_BYTES, capture_process_output_bounded
from .latex_service import (
    ENGINE_READ_ESCAPE_ERROR,
    LATEX_SANDBOX_FLAGS,
    assert_local_engine_allowed,
    cleanup_docker_container_async,
    docker_container_name,
    docker_sandbox_args,
    engine_env,
    find_engine_read_escape,
    find_recorder_read_escape,
)

logger = logging.getLogger(__name__)

class LaTeXCompiler:
    """Service for compiling LaTeX documents to PDF."""

    def __init__(self, temp_dir: str = "/tmp/latex_compile", docker_image: Optional[str] = None):
        self.temp_dir = Path(temp_dir)
        self.docker_image = docker_image or settings.LATEX_DOCKER_IMAGE
        self.use_docker = self._check_docker_available()
        self.latex_command = self._get_latex_command()

        # Ensure temp directory exists
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "LaTeX compiler initialized (mode=%s)",
            self.capability_summary(),
        )

    def _check_docker_available(self) -> bool:
        """Check that the daemon is reachable and the configured image exists."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.docker_image],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_latex_command(self) -> Optional[str]:
        """Get the appropriate LaTeX command based on availability."""
        # Try different LaTeX commands in order of preference
        commands = ["pdflatex", "xelatex", "lualatex"]

        for cmd in commands:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    return cmd
            except Exception:
                continue

        return None

    async def compile_latex(
        self,
        latex_content: str,
        job_id: str,
        timeout: int = 30
    ) -> Dict[str, any]:
        """
        Compile LaTeX content to PDF.

        Returns:
            Dict with keys: success, pdf_path, error_message, compilation_time
        """
        start_time = asyncio.get_event_loop().time()
        work_dir = None

        try:
            # Create temporary working directory
            work_dir = self._work_dir(job_id)
            work_dir.mkdir(parents=True, exist_ok=True)

            # Write LaTeX content to file
            tex_file = work_dir / "document.tex"
            tex_file.write_text(latex_content, encoding='utf-8')

            # Compile based on availability
            if self.use_docker:
                success, error_msg = await self._compile_with_docker(work_dir, timeout)
            else:
                success, error_msg = await self._compile_local(work_dir, timeout)

            compilation_time = asyncio.get_event_loop().time() - start_time

            if success:
                pdf_file = work_dir / "document.pdf"
                if pdf_file.exists():
                    pdf_size = pdf_file.stat().st_size
                    if pdf_size > MAX_COMPILED_PDF_BYTES:
                        return {
                            "success": False,
                            "pdf_path": None,
                            "pdf_size": pdf_size,
                            "error_message": f"Compiled PDF exceeds the {MAX_COMPILED_PDF_BYTES} byte limit",
                            "compilation_time": compilation_time,
                        }
                    return {
                        "success": True,
                        "pdf_path": str(pdf_file),
                        "pdf_size": pdf_size,
                        "error_message": None,
                        "compilation_time": compilation_time
                    }
                else:
                    return {
                        "success": False,
                        "pdf_path": None,
                        "pdf_size": None,
                        "error_message": "PDF file not generated",
                        "compilation_time": compilation_time
                    }
            else:
                return {
                    "success": False,
                    "pdf_path": None,
                    "pdf_size": None,
                    "error_message": error_msg,
                    "compilation_time": compilation_time
                }

        except asyncio.TimeoutError:
            compilation_time = asyncio.get_event_loop().time() - start_time
            return {
                "success": False,
                "pdf_path": None,
                "pdf_size": None,
                "error_message": f"Compilation timeout after {timeout} seconds",
                "compilation_time": compilation_time
            }
        except Exception as e:
            compilation_time = asyncio.get_event_loop().time() - start_time
            logger.error("Compilation error", extra={"error_type": type(e).__name__})
            return {
                "success": False,
                "pdf_path": None,
                "pdf_size": None,
                "error_message": "Compilation failed unexpectedly",
                "compilation_time": compilation_time
            }
        finally:
            # Cleanup is handled separately by cleanup worker
            pass

    async def _compile_local(self, work_dir: Path, timeout: int) -> Tuple[bool, Optional[str]]:
        """Compile LaTeX locally using system LaTeX installation."""
        try:
            assert_local_engine_allowed(work_dir.name)
            # Run pdflatex command
            process = await asyncio.create_subprocess_exec(
                self.latex_command or "pdflatex",
                *LATEX_SANDBOX_FLAGS,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory", str(work_dir),
                "document.tex",
                cwd=str(work_dir),
                env=engine_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                capture = capture_process_output_bounded(process)
                try:
                    output = await asyncio.wait_for(capture, timeout=timeout)
                except BaseException:
                    capture.close()
                    raise

                if self._read_escape(output, work_dir, str(work_dir), process.returncode == 0):
                    return False, ENGINE_READ_ESCAPE_ERROR
                if process.returncode == 0:
                    return True, None
                else:
                    return False, self._parse_latex_error(output)

            except asyncio.TimeoutError:
                await self._kill_and_wait(process)
                return False, f"Compilation timeout after {timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_and_wait(process)
                raise
            except Exception:
                await self._kill_and_wait(process)
                raise

        except Exception as e:
            logger.error("Local compilation error", extra={"error_type": type(e).__name__})
            return False, "Local compilation failed unexpectedly"

    async def _compile_with_docker(self, work_dir: Path, timeout: int) -> Tuple[bool, Optional[str]]:
        """Compile LaTeX using Docker container."""
        container_name = docker_container_name(work_dir.name, "legacy")
        try:
            # Run Docker command
            docker_cmd = [
                "docker", "run", "--rm", "--name", container_name,
                *docker_sandbox_args(),
                "-v", f"{work_dir}:/work",
                "-w", "/work",
                self.docker_image,
                "pdflatex",
                *LATEX_SANDBOX_FLAGS,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "document.tex"
            ]

            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                env=engine_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                capture = capture_process_output_bounded(process)
                try:
                    output = await asyncio.wait_for(capture, timeout=timeout)
                except BaseException:
                    capture.close()
                    raise

                if self._read_escape(output, work_dir, "/work", process.returncode == 0):
                    await cleanup_docker_container_async(container_name)
                    return False, ENGINE_READ_ESCAPE_ERROR
                if process.returncode == 0:
                    await cleanup_docker_container_async(container_name)
                    return True, None
                else:
                    await cleanup_docker_container_async(container_name)
                    return False, self._parse_latex_error(output)

            except asyncio.TimeoutError:
                await self._kill_and_wait(process)
                await cleanup_docker_container_async(container_name)
                return False, f"Compilation timeout after {timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_and_wait(process)
                await cleanup_docker_container_async(container_name)
                raise
            except Exception:
                await self._kill_and_wait(process)
                await cleanup_docker_container_async(container_name)
                raise

        except Exception as e:
            await cleanup_docker_container_async(container_name)
            logger.error("Docker compilation error", extra={"error_type": type(e).__name__})
            return False, "Container compilation failed unexpectedly"

    @staticmethod
    async def _kill_and_wait(process: asyncio.subprocess.Process) -> None:
        """Terminate a child and reap its subprocess transport."""
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()

    def _parse_latex_error(self, error_output: str) -> str:
        """Parse LaTeX error output to extract meaningful error message."""
        # Look for common LaTeX error patterns
        error_patterns = [
            ("! Undefined control sequence", "Undefined command"),
            ("! Missing $ inserted", "Missing math mode delimiter"),
            ("! LaTeX Error:", "LaTeX error"),
            ("! Emergency stop", "Critical compilation error"),
        ]

        for pattern, message in error_patterns:
            if pattern in error_output:
                # Extract the line with the error
                lines = error_output.split('\n')
                for i, line in enumerate(lines):
                    if pattern in line:
                        context = '\n'.join(lines[max(0, i-2):min(len(lines), i+3)])
                        return f"{message}\n\n{context}"

        # Return first few lines if no specific error found
        lines = error_output.split('\n')
        return '\n'.join(lines[:10])

    async def cleanup_job_files(self, job_id: str):
        """Clean up temporary files for a job."""
        try:
            work_dir = self._work_dir(job_id)
            if work_dir.exists():
                shutil.rmtree(work_dir)
                logger.info(f"Cleaned up files for job {job_id}")
        except Exception as e:
            logger.error("Error cleaning up job %s", job_id, extra={"error_type": type(e).__name__})

    def _work_dir(self, job_id: str) -> Path:
        """Reject traversal and existing symlinks outside this compiler's root."""
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", job_id):
            raise ValueError("Invalid compilation job identifier")
        root = self.temp_dir.resolve()
        work_dir = root / job_id
        if work_dir.resolve().parent != root:
            raise ValueError("Compilation workspace is outside the configured root")
        return work_dir

    @staticmethod
    def _read_escape(output: str, work_dir: Path, workspace: str, success: bool) -> bool:
        """Never publish output/log context from an out-of-workspace read."""
        if any(find_engine_read_escape(line, workspace) for line in output.splitlines()):
            return True
        return bool(find_recorder_read_escape(
            work_dir / "document.fls", workspace, require_recorder=success,
        ))

    def is_available(self) -> bool:
        """Probe current capability instead of returning import-time state."""
        self.use_docker = self._check_docker_available()
        if self.use_docker:
            return True
        self.latex_command = self._get_latex_command()
        return self.latex_command is not None

    def capability_summary(self) -> str:
        """Return a short human-readable description of compilation capability."""
        if self.use_docker:
            return f"docker:{self.docker_image}"
        if self.latex_command:
            return f"local:{self.latex_command}"
        return "unavailable"

# Global instance
latex_compiler = LaTeXCompiler()

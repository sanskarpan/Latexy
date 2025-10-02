"""
LaTeX Compilation Service
Handles LaTeX to PDF compilation with proper error handling and Docker support.
"""

import asyncio
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

class LaTeXCompiler:
    """Service for compiling LaTeX documents to PDF."""
    
    def __init__(self, temp_dir: str = "/tmp/latex_compile", docker_image: str = "texlive/texlive:latest"):
        self.temp_dir = Path(temp_dir)
        self.docker_image = docker_image
        self.use_docker = self._check_docker_available()
        self.latex_command = self._get_latex_command()
        
        # Ensure temp directory exists
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"LaTeX compiler initialized (Docker: {self.use_docker})")
    
    def _check_docker_available(self) -> bool:
        """Check if Docker is available on the system."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _get_latex_command(self) -> str:
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
                    logger.info(f"Found LaTeX command: {cmd}")
                    return cmd
            except Exception:
                continue
        
        logger.warning("No LaTeX command found on system")
        return "pdflatex"  # Default fallback
    
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
            work_dir = self.temp_dir / job_id
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
            logger.error(f"Compilation error: {e}")
            return {
                "success": False,
                "pdf_path": None,
                "pdf_size": None,
                "error_message": str(e),
                "compilation_time": compilation_time
            }
        finally:
            # Cleanup is handled separately by cleanup worker
            pass
    
    async def _compile_local(self, work_dir: Path, timeout: int) -> Tuple[bool, Optional[str]]:
        """Compile LaTeX locally using system LaTeX installation."""
        try:
            # Run pdflatex command
            process = await asyncio.create_subprocess_exec(
                self.latex_command,
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-output-directory", str(work_dir),
                "document.tex",
                cwd=str(work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                if process.returncode == 0:
                    return True, None
                else:
                    error_msg = stderr.decode('utf-8', errors='ignore')
                    return False, self._parse_latex_error(error_msg)
                    
            except asyncio.TimeoutError:
                process.kill()
                return False, f"Compilation timeout after {timeout} seconds"
                
        except Exception as e:
            logger.error(f"Local compilation error: {e}")
            return False, str(e)
    
    async def _compile_with_docker(self, work_dir: Path, timeout: int) -> Tuple[bool, Optional[str]]:
        """Compile LaTeX using Docker container."""
        try:
            # Run Docker command
            docker_cmd = [
                "docker", "run", "--rm",
                "-v", f"{work_dir}:/work",
                "-w", "/work",
                self.docker_image,
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "document.tex"
            ]
            
            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                if process.returncode == 0:
                    return True, None
                else:
                    error_msg = stderr.decode('utf-8', errors='ignore')
                    return False, self._parse_latex_error(error_msg)
                    
            except asyncio.TimeoutError:
                process.kill()
                return False, f"Compilation timeout after {timeout} seconds"
                
        except Exception as e:
            logger.error(f"Docker compilation error: {e}")
            return False, str(e)
    
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
            work_dir = self.temp_dir / job_id
            if work_dir.exists():
                shutil.rmtree(work_dir)
                logger.info(f"Cleaned up files for job {job_id}")
        except Exception as e:
            logger.error(f"Error cleaning up job {job_id}: {e}")
    
    def is_available(self) -> bool:
        """Check if LaTeX compilation is available."""
        if self.use_docker:
            return True
        else:
            # Check if local LaTeX is available
            try:
                result = subprocess.run(
                    [self.latex_command, "--version"],
                    capture_output=True,
                    timeout=5
                )
                return result.returncode == 0
            except Exception:
                return False

# Global instance
latex_compiler = LaTeXCompiler()


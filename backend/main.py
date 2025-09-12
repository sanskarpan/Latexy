# =====================================================
# FILE: main.py - FastAPI Application Entry Point
# =====================================================

import logging
import os
import tempfile
import subprocess
import asyncio
from pathlib import Path
from typing import Optional
import uuid
import shutil

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(name)s"}',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Latexy-Backend",
    description="LaTeX resume compilation and optimization service",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
COMPILE_TIMEOUT = 30  # seconds
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
TEMP_DIR = Path("/tmp/latex_compile")
TEMP_DIR.mkdir(exist_ok=True)

# Data models
class CompilationResponse(BaseModel):
    success: bool
    job_id: str
    message: str
    compilation_time: Optional[float] = None
    pdf_size: Optional[int] = None
    log_output: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    latex_available: bool

# Utility functions
def cleanup_temp_files(job_dir: Path) -> None:
    """Clean up temporary files after compilation."""
    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
            logger.info(f"Cleaned up temporary directory: {job_dir}")
    except Exception as e:
        logger.error(f"Error cleaning up {job_dir}: {e}")

def validate_latex_content(content: str) -> bool:
    """Basic validation of LaTeX content."""
    if not content.strip():
        return False
    
    # Check for basic LaTeX structure
    has_document_class = "\\documentclass" in content
    has_begin_document = "\\begin{document}" in content
    has_end_document = "\\end{document}" in content
    
    return has_document_class and has_begin_document and has_end_document

async def compile_latex(latex_content: str, job_id: str) -> CompilationResponse:
    """Compile LaTeX content to PDF using pdflatex."""
    import time
    start_time = time.time()
    
    # Create job-specific directory
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    
    tex_file = job_dir / "resume.tex"
    pdf_file = job_dir / "resume.pdf"
    log_file = job_dir / "resume.log"
    
    try:
        # Write LaTeX content to file
        tex_file.write_text(latex_content, encoding='utf-8')
        logger.info(f"Created LaTeX file for job {job_id}")
        
        # Compile using pdflatex
        cmd = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-output-directory", str(job_dir),
            "-jobname", "resume",
            str(tex_file)
        ]
        
        logger.info(f"Starting LaTeX compilation for job {job_id}")
        
        # Run compilation with timeout
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=job_dir
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), 
                timeout=COMPILE_TIMEOUT
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise HTTPException(
                status_code=408, 
                detail=f"LaTeX compilation timed out after {COMPILE_TIMEOUT} seconds"
            )
        
        compilation_time = time.time() - start_time
        
        # Read log output
        log_output = ""
        if log_file.exists():
            log_output = log_file.read_text(encoding='utf-8', errors='ignore')
        
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
    finally:
        # Note: We keep temp files for PDF download, cleanup happens in download endpoint
        pass

def check_latex_installation() -> bool:
    """Check if LaTeX is properly installed."""
    try:
        result = subprocess.run(
            ["pdflatex", "--version"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False

# API Endpoints

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    latex_available = check_latex_installation()
    
    return HealthResponse(
        status="healthy" if latex_available else "degraded",
        version="1.0.0",
        latex_available=latex_available
    )

@app.post("/compile", response_model=CompilationResponse)
async def compile_latex_endpoint(
    latex_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """Compile LaTeX content to PDF."""
    
    # Generate unique job ID
    job_id = str(uuid.uuid4())
    
    try:
        # Get LaTeX content from either form data or file upload
        if file:
            if file.size and file.size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413, 
                    detail=f"File too large. Maximum size: {MAX_FILE_SIZE} bytes"
                )
            
            if not file.filename or not file.filename.endswith('.tex'):
                raise HTTPException(
                    status_code=400, 
                    detail="File must be a .tex file"
                )
            
            content = await file.read()
            latex_content = content.decode('utf-8')
            
        elif latex_content:
            pass  # Use provided content
        else:
            raise HTTPException(
                status_code=400, 
                detail="Either latex_content or file must be provided"
            )
        
        # Validate LaTeX content
        if not validate_latex_content(latex_content):
            raise HTTPException(
                status_code=400, 
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Compile LaTeX
        result = await compile_latex(latex_content, job_id)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/download/{job_id}")
async def download_pdf(job_id: str):
    """Download compiled PDF."""
    
    # Validate job_id format (basic UUID check)
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    
    job_dir = TEMP_DIR / job_id
    pdf_file = job_dir / "resume.pdf"
    
    if not pdf_file.exists():
        raise HTTPException(
            status_code=404, 
            detail="PDF not found. Job may have failed or files may have been cleaned up."
        )
    
    try:
        # Return PDF file
        response = FileResponse(
            path=pdf_file,
            media_type='application/pdf',
            filename=f"resume_{job_id[:8]}.pdf"
        )
        
        # Schedule cleanup after response
        asyncio.create_task(cleanup_temp_files_delayed(job_dir))
        
        return response
        
    except Exception as e:
        logger.error(f"Error serving PDF for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error serving PDF file")

async def cleanup_temp_files_delayed(job_dir: Path, delay: int = 5):
    """Clean up temporary files after a delay."""
    await asyncio.sleep(delay)
    cleanup_temp_files(job_dir)

@app.get("/logs/{job_id}")
async def get_compilation_logs(job_id: str):
    """Get compilation logs for debugging."""
    
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    
    job_dir = TEMP_DIR / job_id
    log_file = job_dir / "resume.log"
    
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        log_content = log_file.read_text(encoding='utf-8', errors='ignore')
        return {"job_id": job_id, "logs": log_content}
    except Exception as e:
        logger.error(f"Error reading logs for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading log file")

# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize service on startup."""
    logger.info("Latexy Backend starting up...")
    
    # Check LaTeX installation
    if not check_latex_installation():
        logger.warning("LaTeX installation not found or not working properly")
    else:
        logger.info("LaTeX installation verified successfully")
    
    # Ensure temp directory exists
    TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Temporary directory ready: {TEMP_DIR}")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Latexy Backend shutting down...")
    # Note: In production, you might want to cleanup all temp files here

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )
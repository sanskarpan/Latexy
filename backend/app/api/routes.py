"""
API routes for the application.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..models.schemas import CompilationResponse, HealthResponse, LogsResponse
from ..models.llm_schemas import OptimizationRequest, OptimizationResponse
from ..services.latex_service import latex_service
from ..services.llm_service import llm_service
from ..utils.file_utils import validate_file_upload, validate_job_id, get_job_files

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    latex_available = latex_service.check_latex_installation()
    llm_available = llm_service.is_available()
    
    # Consider service healthy if LaTeX is available (LLM is optional)
    status = "healthy" if latex_available else "degraded"
    
    return HealthResponse(
        status=status,
        version=settings.APP_VERSION,
        latex_available=latex_available
    )


@router.post("/compile", response_model=CompilationResponse)
async def compile_latex_endpoint(
    latex_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """Compile LaTeX content to PDF."""
    
    try:
        # Get LaTeX content from either form data or file upload
        if file:
            validate_file_upload(file)
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
        if not latex_service.validate_latex_content(latex_content):
            raise HTTPException(
                status_code=400, 
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Compile LaTeX
        result = await latex_service.compile_latex(latex_content)
        
        # Schedule cleanup after retention period only if compilation was successful
        if result.success:
            job_dir = settings.TEMP_DIR / result.job_id
            asyncio.create_task(latex_service.cleanup_temp_files_delayed(job_dir, settings.PDF_RETENTION_TIME))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/download/{job_id}")
async def download_pdf(job_id: str):
    """Download compiled PDF."""
    
    validate_job_id(job_id)
    
    job_dir, pdf_file, _ = get_job_files(job_id)
    
    if not pdf_file.exists():
        raise HTTPException(
            status_code=404, 
            detail="PDF not found. Job may have failed or files may have been cleaned up."
        )
    
    try:
        # Return PDF file
        return FileResponse(
            path=pdf_file,
            media_type='application/pdf',
            filename=f"resume_{job_id[:8]}.pdf"
        )
        
    except Exception as e:
        logger.error(f"Error serving PDF for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error serving PDF file")


@router.get("/logs/{job_id}", response_model=LogsResponse)
async def get_compilation_logs(job_id: str):
    """Get compilation logs for debugging."""
    
    validate_job_id(job_id)
    
    _, _, log_file = get_job_files(job_id)
    
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        log_content = log_file.read_text(encoding='utf-8', errors='ignore')
        return LogsResponse(job_id=job_id, logs=log_content)
    except Exception as e:
        logger.error(f"Error reading logs for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading log file")


@router.post("/optimize", response_model=OptimizationResponse)
async def optimize_resume(request: OptimizationRequest):
    """Optimize resume using LLM for better ATS compatibility."""
    
    if not llm_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="LLM service is not available. Please configure OpenAI API key."
        )
    
    try:
        # Validate LaTeX content
        if not latex_service.validate_latex_content(request.latex_content):
            raise HTTPException(
                status_code=400,
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Validate job description
        if not request.job_description.strip():
            raise HTTPException(
                status_code=400,
                detail="Job description cannot be empty"
            )
        
        # Perform optimization
        result = await llm_service.optimize_resume(request)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in optimize endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/optimize-and-compile", response_model=dict)
async def optimize_and_compile_resume(request: OptimizationRequest):
    """Optimize resume and compile to PDF in one step."""
    
    try:
        # First optimize the resume
        optimization_result = await optimize_resume(request)
        
        if not optimization_result.success:
            return {
                "optimization": optimization_result,
                "compilation": None,
                "success": False
            }
        
        # Then compile the optimized LaTeX
        compilation_result = await latex_service.compile_latex(optimization_result.optimized_latex)
        
        # Schedule cleanup after retention period only if compilation was successful
        if compilation_result.success:
            job_dir = settings.TEMP_DIR / compilation_result.job_id
            asyncio.create_task(latex_service.cleanup_temp_files_delayed(job_dir, settings.PDF_RETENTION_TIME))
        
        return {
            "optimization": optimization_result,
            "compilation": compilation_result,
            "success": optimization_result.success and compilation_result.success
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in optimize-and-compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


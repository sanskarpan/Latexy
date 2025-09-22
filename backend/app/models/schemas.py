"""
Pydantic models for request/response schemas.
"""

from typing import Optional
from pydantic import BaseModel


class CompilationResponse(BaseModel):
    """Response model for LaTeX compilation."""
    success: bool
    job_id: str
    message: str
    compilation_time: Optional[float] = None
    pdf_size: Optional[int] = None
    log_output: Optional[str] = None


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    version: str
    latex_available: bool


class CompilationRequest(BaseModel):
    """Request model for LaTeX compilation."""
    latex_content: str


class LogsResponse(BaseModel):
    """Response model for compilation logs."""
    job_id: str
    logs: str

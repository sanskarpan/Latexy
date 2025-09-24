"""
Pydantic models for LLM-related operations.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class OptimizationRequest(BaseModel):
    """Request model for resume optimization."""
    latex_content: str = Field(..., description="Original LaTeX resume content")
    job_description: str = Field(..., description="Target job description")
    optimization_level: str = Field(
        default="balanced", 
        description="Optimization level: conservative, balanced, or aggressive"
    )


class KeywordMatch(BaseModel):
    """Model for keyword matching results."""
    keyword: str
    relevance_score: float = Field(..., ge=0, le=1)
    found_in_resume: bool
    suggested_context: Optional[str] = None


class OptimizationChange(BaseModel):
    """Model for tracking changes made during optimization."""
    section: str
    change_type: str  # "added", "modified", "removed"
    original_text: Optional[str] = None
    new_text: Optional[str] = None
    reason: str


class ATSScore(BaseModel):
    """Model for ATS compatibility scoring."""
    overall_score: float = Field(..., ge=0, le=100)
    keyword_score: float = Field(..., ge=0, le=100)
    format_score: float = Field(..., ge=0, le=100)
    content_score: float = Field(..., ge=0, le=100)
    recommendations: List[str] = Field(default_factory=list)


class OptimizationResponse(BaseModel):
    """Response model for resume optimization."""
    success: bool
    optimized_latex: Optional[str] = None
    original_latex: str
    job_description: str
    
    # Analysis results
    keywords_found: List[KeywordMatch] = Field(default_factory=list)
    changes_made: List[OptimizationChange] = Field(default_factory=list)
    ats_score: Optional[ATSScore] = None
    
    # Metadata
    optimization_time: Optional[float] = None
    tokens_used: Optional[int] = None
    model_used: Optional[str] = None
    
    # Error handling
    error_message: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class LLMUsage(BaseModel):
    """Model for tracking LLM usage statistics."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    cost_estimate: Optional[float] = None

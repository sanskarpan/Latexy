"""
AI tool routes — error explanation and other AI-powered utilities.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.error_explainer_service import error_explainer_service

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-tools"])


# ── Request / Response schemas ──────────────────────────────────────────────


class ExplainErrorRequest(BaseModel):
    error_message: str = Field(..., min_length=1, max_length=2000)
    surrounding_latex: str = Field(default="", max_length=5000)
    error_line: int = Field(default=0, ge=0)


class ExplainErrorResponse(BaseModel):
    success: bool
    explanation: str
    suggested_fix: str
    corrected_code: Optional[str] = None
    source: str  # "pattern" | "llm" | "error"
    cached: bool
    processing_time: float


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/explain-error", response_model=ExplainErrorResponse)
async def explain_latex_error(
    request: ExplainErrorRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Explain a LaTeX compilation error using pattern matching or LLM."""
    try:
        # Resolve API key: BYOK first, then system default
        api_key: str | None = None
        if user_id:
            try:
                from ..services.api_key_service import api_key_service

                api_key = await api_key_service.get_user_provider(
                    db, user_id, "openai"
                )
            except Exception:
                pass

        if not api_key and settings.OPENAI_API_KEY:
            api_key = settings.OPENAI_API_KEY

        result = await error_explainer_service.explain(
            error_message=request.error_message,
            surrounding_latex=request.surrounding_latex,
            error_line=request.error_line,
            api_key=api_key,
        )

        return ExplainErrorResponse(
            success=True,
            explanation=result["explanation"],
            suggested_fix=result["suggested_fix"],
            corrected_code=result.get("corrected_code"),
            source=result.get("source", "pattern"),
            cached=result.get("cached", False),
            processing_time=result.get("processing_time", 0),
        )

    except Exception as e:
        logger.error(f"Error in explain-error endpoint: {e}")
        # Still return a pattern-based result on failure
        pattern = error_explainer_service.explain_from_patterns(
            request.error_message
        )
        return ExplainErrorResponse(
            success=False,
            explanation=pattern.explanation,
            suggested_fix=pattern.suggested_fix,
            corrected_code=pattern.corrected_code,
            source="error",
            cached=False,
            processing_time=0,
        )

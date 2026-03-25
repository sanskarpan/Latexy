"""
AI tool routes — error explanation and other AI-powered utilities.
"""

import hashlib
import json
import time
from typing import List, Optional

import openai
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager
from ..database.connection import get_db
from ..middleware.auth_middleware import get_current_user_optional
from ..services.error_explainer_service import error_explainer_service

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-tools"])


# ── Request / Response schemas ──────────────────────────────────────────────


class GenerateBulletsRequest(BaseModel):
    job_title: str = Field(..., max_length=200)
    responsibility: str = Field(..., max_length=500)
    context: Optional[str] = Field(None, max_length=1000)
    tone: str = Field(default="technical")  # technical | leadership | analytical | creative
    count: int = Field(default=5, ge=1, le=10)


class GenerateBulletsResponse(BaseModel):
    bullets: List[str]
    cached: bool


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

_BULLET_SYSTEM_PROMPT = """\
You are a professional resume writer. Generate {count} strong resume bullet points.
Each bullet must:
- Start with a strong action verb (past tense for past roles)
- Include quantified impact where plausible (numbers, percentages, scale)
- Be 80-150 characters (fits on ~1 line in a resume)
- Match the {tone} tone: technical=precise/technical, leadership=impact/ownership, \
analytical=data/metrics, creative=innovative/design
- Be LaTeX-compatible (escape special chars: &, %, $, #, _, {{, }})
Return JSON: {{ "bullets": ["Led cross-functional team...", "Engineered scalable..."] }}
Only JSON, no markdown."""


def _bullet_cache_key(job_title: str, responsibility: str, tone: str, count: int) -> str:
    raw = f"{job_title}|{responsibility}|{tone}|{count}"
    return "ai:bullets:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@router.post("/generate-bullets", response_model=GenerateBulletsResponse)
async def generate_bullets(
    request: GenerateBulletsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Generate strong resume bullet points using AI. Auth optional."""
    cache_key = _bullet_cache_key(
        request.job_title, request.responsibility, request.tone, request.count
    )

    # Check cache
    try:
        cached = await cache_manager.get(cache_key)
        if cached and isinstance(cached, dict):
            return GenerateBulletsResponse(bullets=cached["bullets"], cached=True)
    except Exception:
        pass

    # Resolve API key
    api_key: Optional[str] = None
    if user_id:
        try:
            from ..services.api_key_service import api_key_service
            api_key = await api_key_service.get_user_provider(db, user_id, "openai")
        except Exception:
            pass
    if not api_key and settings.OPENAI_API_KEY:
        api_key = settings.OPENAI_API_KEY

    if not api_key:
        logger.warning("generate-bullets: no API key available")
        return GenerateBulletsResponse(bullets=[], cached=False)

    system_prompt = _BULLET_SYSTEM_PROMPT.format(count=request.count, tone=request.tone)
    user_parts = [
        f"Job title: {request.job_title}",
        f"Responsibility/task: {request.responsibility}",
    ]
    if request.context:
        user_parts.append(f"Resume context:\n{request.context}")
    user_prompt = "\n".join(user_parts)

    try:
        start = time.monotonic()
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=800,
            temperature=0.8,
            response_format={"type": "json_object"},
        )
        elapsed = time.monotonic() - start
        logger.info(f"generate-bullets LLM call: {elapsed:.2f}s")

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        bullets: List[str] = parsed.get("bullets", [])
        if not isinstance(bullets, list):
            bullets = []

        # Cache for 24h
        try:
            await cache_manager.set(cache_key, {"bullets": bullets}, ttl=86400)
        except Exception:
            pass

        return GenerateBulletsResponse(bullets=bullets, cached=False)

    except Exception as exc:
        logger.error(f"generate-bullets error: {exc}")
        return GenerateBulletsResponse(bullets=[], cached=False)


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

"""
AI tool routes — error explanation and other AI-powered utilities.
"""

import hashlib
import json
import time
from typing import Dict, List, Literal, Optional

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
    tone: Literal["technical", "leadership", "analytical", "creative"] = "technical"
    count: int = Field(default=5, ge=1, le=10)


class GenerateBulletsResponse(BaseModel):
    bullets: List[str]
    cached: bool


class SummaryVariant(BaseModel):
    emphasis: str  # "technical" | "leadership" | "unique"
    title: str
    text: str


class GenerateSummaryRequest(BaseModel):
    resume_latex: str = Field(..., max_length=50_000)
    target_role: Optional[str] = Field(None, max_length=200)
    job_description: Optional[str] = Field(None, max_length=5000)
    count: int = Field(default=3, ge=1, le=5)


class GenerateSummaryResponse(BaseModel):
    summaries: List[SummaryVariant]
    cached: bool


RewriteAction = Literal["improve", "shorten", "quantify", "power_verbs", "change_tone", "expand"]


class RewriteRequest(BaseModel):
    selected_text: str = Field(..., min_length=5, max_length=2000)
    action: RewriteAction
    context: Optional[str] = Field(None, max_length=1000)
    tone: Optional[str] = Field(None, max_length=50)


class RewriteResponse(BaseModel):
    rewritten: str
    action: str
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


def _bullet_cache_key(
    job_title: str,
    responsibility: str,
    tone: str,
    count: int,
    context: Optional[str] = None,
) -> str:
    raw = f"{job_title}|{responsibility}|{tone}|{count}|{(context or '').strip()}"
    return "ai:bullets:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@router.post("/generate-bullets", response_model=GenerateBulletsResponse)
async def generate_bullets(
    request: GenerateBulletsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Generate strong resume bullet points using AI. Auth optional."""
    cache_key = _bullet_cache_key(
        request.job_title,
        request.responsibility,
        request.tone,
        request.count,
        request.context,
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


_SUMMARY_SYSTEM_PROMPT = """\
You are an expert resume writer. Generate {count} professional summary alternatives for this resume.
Each summary: 2-3 sentences, punchy, tailored to the role (if provided).
Variant 1 (technical): Lead with technical skills and technical achievements
Variant 2 (leadership): Lead with impact, leadership, and results
Variant 3 (unique): Lead with most distinctive/unusual differentiators
Each summary: NO filler phrases ("passionate about", "results-driven", "team player")
Each summary: Start with a strong descriptor of the candidate, not "I" or "My"
Target role: {target_role}
Output JSON: {{ "summaries": [{{"emphasis": "technical", "title": "Technical Skills Focus", "text": "..."}}, ...] }}
Only JSON, no markdown."""


def _summary_cache_key(
    resume_latex: str,
    target_role: Optional[str],
    job_description: Optional[str],
    count: int,
) -> str:
    raw = f"{resume_latex[:500]}|{(target_role or '').strip()}|{(job_description or '')[:200].strip()}|{count}"
    return "ai:summary:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@router.post("/generate-summary", response_model=GenerateSummaryResponse)
async def generate_summary(
    request: GenerateSummaryRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Generate professional summary alternatives using AI. Auth optional."""
    cache_key = _summary_cache_key(
        request.resume_latex,
        request.target_role,
        request.job_description,
        request.count,
    )

    try:
        cached = await cache_manager.get(cache_key)
        if cached and isinstance(cached, dict):
            summaries = [SummaryVariant(**s) for s in cached.get("summaries", [])]
            return GenerateSummaryResponse(summaries=summaries, cached=True)
    except Exception:
        pass

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
        logger.warning("generate-summary: no API key available")
        return GenerateSummaryResponse(summaries=[], cached=False)

    system_prompt = _SUMMARY_SYSTEM_PROMPT.format(
        count=request.count,
        target_role=request.target_role or "general",
    )
    user_parts = [f"Resume LaTeX:\n{request.resume_latex[:8000]}"]
    if request.job_description:
        user_parts.append(f"\nJob description:\n{request.job_description[:2000]}")
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
            max_tokens=1000,
            temperature=0.75,
            response_format={"type": "json_object"},
        )
        elapsed = time.monotonic() - start
        logger.info(f"generate-summary LLM call: {elapsed:.2f}s")

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        raw_summaries = parsed.get("summaries", [])
        summaries: List[SummaryVariant] = []
        for s in raw_summaries:
            if isinstance(s, dict) and "emphasis" in s and "title" in s and "text" in s:
                summaries.append(SummaryVariant(**s))

        try:
            await cache_manager.set(
                cache_key,
                {"summaries": [s.model_dump() for s in summaries]},
                ttl=1800,
            )
        except Exception:
            pass

        return GenerateSummaryResponse(summaries=summaries, cached=False)

    except Exception as exc:
        logger.error(f"generate-summary error: {exc}")
        return GenerateSummaryResponse(summaries=[], cached=False)


class ProofreadRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)


@router.post("/proofread")
async def proofread_resume(request: ProofreadRequest):
    """Proofread resume for writing quality issues. Rule-based, no LLM required."""
    from ..services.proofreader_service import proofread_latex
    return proofread_latex(request.latex_content)


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


# ── Writing assistant ────────────────────────────────────────────────────────

_REWRITE_PROMPTS: Dict[str, str] = {
    "improve": (
        "Rewrite for stronger impact and clarity. Keep length similar. "
        "Return ONLY the rewritten LaTeX text — no explanation, no preamble."
    ),
    "shorten": (
        "Condense to roughly 50% fewer words while preserving the core meaning. "
        "Eliminate filler words. "
        "Return ONLY the shortened LaTeX text."
    ),
    "quantify": (
        "Where plausible, add specific metrics, numbers, or percentages to demonstrate scale or impact. "
        "Keep all LaTeX commands valid. "
        "Return ONLY the revised LaTeX text."
    ),
    "power_verbs": (
        "Replace weak verbs such as 'responsible for', 'helped with', 'worked on', "
        "'assisted', 'participated in' with strong action verbs "
        "(e.g. Led, Engineered, Delivered, Architected, Spearheaded). "
        "Leave the rest of the text unchanged. "
        "Return ONLY the revised LaTeX text."
    ),
    "change_tone": (
        "Rewrite in a {tone} tone while keeping all factual content identical. "
        "Return ONLY the rewritten LaTeX text."
    ),
    "expand": (
        "Elaborate with additional detail and supporting context. "
        "Limit the increase to roughly 50% more words. Keep LaTeX commands valid. "
        "Return ONLY the expanded LaTeX text."
    ),
}


def _rewrite_cache_key(action: str, selected_text: str, tone: Optional[str], context: Optional[str] = None) -> str:
    raw = f"{action}|{selected_text}|{tone or ''}|{(context or '').strip()}"
    return "ai:rewrite:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_text(
    request: RewriteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Rewrite selected LaTeX text using AI. Auth optional."""
    cache_key = _rewrite_cache_key(request.action, request.selected_text, request.tone, request.context)

    # Check cache
    try:
        cached = await cache_manager.get(cache_key)
        if cached and isinstance(cached, dict):
            return RewriteResponse(
                rewritten=cached["rewritten"], action=request.action, cached=True
            )
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
        logger.warning("rewrite: no API key available")
        return RewriteResponse(rewritten=request.selected_text, action=request.action, cached=False)

    system_prompt = _REWRITE_PROMPTS[request.action].format(tone=request.tone or "formal")
    user_parts = [f"Text to rewrite:\n{request.selected_text}"]
    if request.context:
        user_parts.append(f"\nContext (for reference only):\n{request.context}")
    user_prompt = "\n".join(user_parts)

    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1000,
            temperature=0.7,
        )

        rewritten = (response.choices[0].message.content or "").strip()
        if not rewritten:
            return RewriteResponse(rewritten=request.selected_text, action=request.action, cached=False)

        try:
            await cache_manager.set(cache_key, {"rewritten": rewritten}, ttl=3600)
        except Exception:
            pass

        return RewriteResponse(rewritten=rewritten, action=request.action, cached=False)

    except Exception as exc:
        logger.error(f"rewrite error: {exc}")
        return RewriteResponse(rewritten=request.selected_text, action=request.action, cached=False)

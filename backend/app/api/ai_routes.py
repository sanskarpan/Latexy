"""
AI tool routes — error explanation and other AI-powered utilities.
"""

import hashlib
import json
import re as _re
import time
from calendar import month_abbr as _month_abbr
from calendar import month_name as _month_name
from typing import Dict, List, Literal, Optional
from uuid import uuid4

import httpx
import openai
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import cache_manager
from ..database.connection import get_db
from ..database.models import Resume
from ..middleware.auth_middleware import get_current_user_optional, get_current_user_required
from ..services.error_explainer_service import error_explainer_service
from ..services.latex_text_extractor import extract_prose, offset_to_latex_position
from ..services.proofreader_service import ProofreadResponse, proofread_latex

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


@router.post("/proofread", response_model=ProofreadResponse)
async def proofread_resume(request: ProofreadRequest) -> ProofreadResponse:
    """Proofread resume for writing quality issues. Rule-based, no LLM required."""
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


# ── Spell Check (Feature 35) ─────────────────────────────────────────────────


class SpellCheckRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)
    language: str = Field(default="en-US", max_length=10)

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        import re as _re
        if not _re.match(r'^[a-z]{2,3}(-[A-Z]{2,3})?$', v):
            raise ValueError("language must be like 'en-US' or 'de'")
        return v


class SpellCheckIssue(BaseModel):
    line: int
    column_start: int
    column_end: int
    severity: Literal["spelling", "grammar", "style"]
    message: str
    replacements: List[str] = Field(default_factory=list)
    rule_id: str


class SpellCheckResponse(BaseModel):
    issues: List[SpellCheckIssue]
    cached: bool


def _lt_category_to_severity(category_id: str) -> Literal["spelling", "grammar", "style"]:
    cat = category_id.upper()
    if cat in ("TYPOS", "MISSPELLING"):
        return "spelling"
    if cat == "STYLE":
        return "style"
    return "grammar"


@router.post("/spell-check", response_model=SpellCheckResponse)
async def spell_check(
    request: SpellCheckRequest,
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Check spelling and grammar via LanguageTool. Auth optional."""
    cache_key = "ai:spell:" + hashlib.sha256(
        f"{request.latex_content}|{request.language}".encode()
    ).hexdigest()[:24]

    # Cache hit
    try:
        cached = await cache_manager.get(cache_key)
        if cached and isinstance(cached, dict):
            issues = [SpellCheckIssue(**i) for i in cached.get("issues", [])]
            return SpellCheckResponse(issues=issues, cached=True)
    except Exception:
        pass

    # Extract prose with position tracking
    segments = extract_prose(request.latex_content)
    if not segments:
        return SpellCheckResponse(issues=[], cached=False)

    # Build prose string (respect SPELL_CHECK_MAX_CHARS)
    prose_parts: List[str] = []
    total_chars = 0
    for seg in segments:
        if total_chars + len(seg.text) > settings.SPELL_CHECK_MAX_CHARS:
            break
        prose_parts.append(seg.text)
        total_chars += len(seg.text) + 1  # +1 for space

    prose_text = " ".join(prose_parts)
    if not prose_text.strip():
        return SpellCheckResponse(issues=[], cached=False)

    # Determine LT URL (prefer local/self-hosted)
    lt_url = settings.LANGUAGETOOL_LOCAL_URL or settings.LANGUAGETOOL_URL

    # Call LanguageTool
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                lt_url,
                data={"text": prose_text, "language": request.language, "enabledOnly": "false"},
                timeout=8.0,
            )
        if resp.status_code != 200:
            logger.warning(f"LanguageTool returned {resp.status_code}")
            return SpellCheckResponse(issues=[], cached=False)
        lt_data = resp.json()
    except Exception as exc:
        logger.warning(f"LanguageTool error: {exc}")
        return SpellCheckResponse(issues=[], cached=False)

    # Map LT matches → SpellCheckIssue with original LaTeX positions
    issues: List[SpellCheckIssue] = []
    for match in lt_data.get("matches", []):
        lt_offset = match.get("offset", 0)
        lt_length = match.get("length", 1)
        start_line, start_col, end_line, end_col = offset_to_latex_position(
            lt_offset, lt_length, segments
        )

        rule = match.get("rule", {})
        category_id = rule.get("category", {}).get("id", "GRAMMAR")
        severity = _lt_category_to_severity(category_id)

        replacements = [r["value"] for r in match.get("replacements", [])[:5]]
        rule_id = rule.get("id", "UNKNOWN")

        issues.append(SpellCheckIssue(
            line=start_line,
            column_start=start_col,
            column_end=end_col,
            severity=severity,
            message=match.get("message", ""),
            replacements=replacements,
            rule_id=rule_id,
        ))

    # Cache result
    try:
        await cache_manager.set(
            cache_key,
            {"issues": [i.model_dump() for i in issues]},
            ttl=3600,
        )
    except Exception:
        pass

    return SpellCheckResponse(issues=issues, cached=False)


# ── Date Standardizer (Feature 57) ──────────────────────────────────────────

# Full month names → 0-padded month numbers
_MONTH_NUM: dict[str, str] = {
    name.lower(): f"{i:02d}" for i, name in enumerate(_month_name) if name
}
_MONTH_NUM.update(
    {abbr.lower(): f"{i:02d}" for i, abbr in enumerate(_month_abbr) if abbr}
)

# 0-padded month → canonical names
_NUM_TO_ABBR: dict[str, str] = {
    f"{i:02d}": abbr for i, abbr in enumerate(_month_abbr) if abbr
}
_NUM_TO_FULL: dict[str, str] = {
    f"{i:02d}": name for i, name in enumerate(_month_name) if name
}


def _parse_month_year(text: str) -> tuple[str, str] | None:
    """
    Parse a date string and return (zero_padded_month, 4_digit_year) or None.
    Handles: "January 2020", "Jan 2020", "01/2020", "2020-01".
    """
    text = text.strip()
    # "January 2020", "Jan 2020", or "Jan. 2020" (dotted abbreviation)
    m = _re.match(r'^([A-Za-z]+)\.?\s+(\d{4})$', text)
    if m:
        month_key = m.group(1).lower()
        if month_key in _MONTH_NUM:
            return _MONTH_NUM[month_key], m.group(2)
    # "01/2020" or "1/2020"
    m = _re.match(r'^(\d{1,2})/(\d{4})$', text)
    if m:
        month_i = int(m.group(1))
        if not 1 <= month_i <= 12:
            return None
        return f"{month_i:02d}", m.group(2)
    # "2020-01"
    m = _re.match(r'^(\d{4})-(\d{2})$', text)
    if m:
        month_i = int(m.group(2))
        if not 1 <= month_i <= 12:
            return None
        return f"{month_i:02d}", m.group(1)
    # "2020/01" (year-first slash)
    m = _re.match(r'^(\d{4})/(\d{2})$', text)
    if m:
        month_i = int(m.group(2))
        if not 1 <= month_i <= 12:
            return None
        return f"{month_i:02d}", m.group(1)
    return None


def _format_month_year(month: str, year: str, target_format: str) -> str:
    """Convert (month, year) to target_format string."""
    if target_format == "MMM YYYY":
        return f"{_NUM_TO_ABBR.get(month, month)} {year}"
    if target_format == "MMMM YYYY":
        return f"{_NUM_TO_FULL.get(month, month)} {year}"
    if target_format == "YYYY-MM":
        return f"{year}-{month}"
    if target_format == "MM/YYYY":
        return f"{month}/{year}"
    return f"{month}/{year}"


# Combined pattern: month-name YYYY | MM/YYYY | YYYY-MM | YYYY/MM
_DATE_RE = _re.compile(
    r'(?<!\d)'
    r'((?:January|February|March|April|May|June|July|August|September|October|November|December'
    r'|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    r'(?:\.)?'
    r'\s+\d{4}'
    r'|\d{1,2}/\d{4}'
    r'|\d{4}-\d{2}'
    r'|\d{4}/\d{2})',
    _re.IGNORECASE,
)


class StandardizeDatesRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)
    target_format: str = Field(..., pattern=r'^(MMM YYYY|MMMM YYYY|YYYY-MM|MM/YYYY)$')


class DateOccurrence(BaseModel):
    line: int
    original: str
    standardized: str


class StandardizeDatesResponse(BaseModel):
    occurrences: List[DateOccurrence]
    standardized_latex: str


@router.post("/standardize-dates", response_model=StandardizeDatesResponse)
async def standardize_dates(request: StandardizeDatesRequest):
    """
    Detect all date occurrences in LaTeX and normalize to the requested format.
    Pure regex — no LLM required. Auth optional.
    """
    occurrences: List[DateOccurrence] = []

    def _replace(m: _re.Match) -> str:
        original = m.group(0)
        parsed = _parse_month_year(original)
        if parsed is None:
            return original
        month, year = parsed
        standardized = _format_month_year(month, year, request.target_format)
        if standardized != original:
            # Record occurrence with 1-based line number
            char_pos = m.start()
            line_num = request.latex_content.count('\n', 0, char_pos) + 1
            occurrences.append(DateOccurrence(
                line=line_num,
                original=original,
                standardized=standardized,
            ))
        return standardized

    standardized_latex = _DATE_RE.sub(_replace, request.latex_content)

    # Deduplicate occurrences keeping first seen per (line, original) pair
    seen: set[tuple[int, str]] = set()
    unique: List[DateOccurrence] = []
    for occ in occurrences:
        key = (occ.line, occ.original)
        if key not in seen:
            seen.add(key)
            unique.append(occ)

    return StandardizeDatesResponse(
        occurrences=unique,
        standardized_latex=standardized_latex,
    )


# ── Salary Estimator (Feature 45) ───────────────────────────────────────────


class SalaryEstimateRequest(BaseModel):
    resume_latex: str = Field(..., max_length=50_000)
    target_role: str = Field(..., max_length=200)
    location: str = Field(..., max_length=200)


class SalaryEstimateResponse(BaseModel):
    currency: str
    low: int
    median: int
    high: int
    percentile: int
    key_skills: List[str]
    disclaimer: str
    cached: bool


_SALARY_SYSTEM_PROMPT = """\
You are a compensation research specialist with deep knowledge of market salary data.
Based on the provided resume, estimate the expected salary range for the given role and location.
Consider: years of experience, skills demonstrated, education, company types worked at, and current market rates.
Percentile is where this candidate falls vs all candidates for the same role in that location (0-100).
Infer the currency from the location (USD for US, GBP for UK, EUR for European cities, INR for India, etc.).
Output ONLY valid JSON in this exact format:
{{
  "currency": "USD",
  "low": 120000,
  "median": 145000,
  "high": 180000,
  "percentile": 72,
  "key_skills": ["Python", "Machine Learning", "AWS"],
  "disclaimer": "Estimates are based on publicly available market data and may vary."
}}
No markdown, no explanation — only the JSON object."""


def _salary_cache_key(resume_latex: str, target_role: str, location: str) -> str:
    resume_digest = hashlib.sha256(resume_latex.encode()).hexdigest()
    raw = f"{resume_digest}|{target_role.strip().lower()}|{location.strip().lower()}"
    return "ai:salary:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


@router.post("/salary-estimate", response_model=SalaryEstimateResponse)
async def salary_estimate(
    request: SalaryEstimateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Estimate salary range for the candidate based on their resume, role, and location. Auth optional."""
    cache_key = _salary_cache_key(request.resume_latex, request.target_role, request.location)

    # Check cache
    try:
        cached_val = await cache_manager.get(cache_key)
        if cached_val and isinstance(cached_val, dict):
            return SalaryEstimateResponse(**cached_val, cached=True)
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
        logger.warning("salary-estimate: no API key available")
        return SalaryEstimateResponse(
            currency="USD", low=0, median=0, high=0, percentile=0,
            key_skills=[], disclaimer="No API key configured.", cached=False,
        )

    user_prompt = (
        f"Target role: {request.target_role}\n"
        f"Location: {request.location}\n\n"
        f"Resume (LaTeX):\n{request.resume_latex[:8000]}"
    )

    try:
        start = time.monotonic()
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SALARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        elapsed = time.monotonic() - start
        logger.info(f"salary-estimate LLM call: {elapsed:.2f}s")

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

        raw_skills = parsed.get("key_skills", [])
        key_skills = (
            [str(s).strip() for s in raw_skills if str(s).strip()]
            if isinstance(raw_skills, list)
            else []
        )

        result = SalaryEstimateResponse(
            currency=str(parsed.get("currency", "USD")),
            low=int(parsed.get("low", 0)),
            median=int(parsed.get("median", 0)),
            high=int(parsed.get("high", 0)),
            percentile=max(0, min(100, int(parsed.get("percentile", 50)))),
            key_skills=key_skills,
            disclaimer=str(parsed.get("disclaimer", "Market estimates may vary.")),
            cached=False,
        )

        # Validate low <= median <= high
        if not (result.low <= result.median <= result.high):
            vals = sorted([result.low, result.median, result.high])
            result = result.model_copy(update={"low": vals[0], "median": vals[1], "high": vals[2]})

        # Cache for 24h
        try:
            cache_data = result.model_dump()
            cache_data.pop("cached", None)
            await cache_manager.set(cache_key, cache_data, ttl=86400)
        except Exception:
            pass

        return result

    except Exception as exc:
        logger.error(f"salary-estimate error: {exc}")
        return SalaryEstimateResponse(
            currency="USD", low=0, median=0, high=0, percentile=0,
            key_skills=[], disclaimer="Unable to estimate salary at this time.", cached=False,
        )


# ── Resume Age Analysis (Feature 55) ────────────────────────────────────────

import datetime as _dt

_PRESTIGIOUS_KEYWORDS = {
    "harvard", "mit", "stanford", "yale", "princeton", "columbia",
    "university of chicago", "upenn", "penn", "dartmouth", "cornell",
    "brown", "duke", "northwestern", "vanderbilt", "johns hopkins",
    "caltech", "rice", "notre dame", "emory", "georgetown",
    "carnegie mellon", "carnegie-mellon", "uc berkeley", "berkeley",
    "university of michigan", "virginia", "usc", "nyu",
    "tufts", "purdue", "georgia tech", "georgia institute",
    "ucla", "uchicago", "oxford", "cambridge", "lse",
    "london school of economics", "imperial college", "eth zurich",
    "hec paris", "insead", "iit", "indian institute of technology",
    "google", "apple", "microsoft", "amazon", "meta", "facebook",
    "netflix", "alphabet", "openai", "deepmind", "anthropic",
    "goldman sachs", "goldman", "mckinsey", "bain",
    "boston consulting", "bcg", "blackstone", "jp morgan", "jpmorgan",
    "morgan stanley", "jane street", "two sigma", "citadel", "bridgewater",
}


def _check_prestigious(name: str) -> bool:
    low = name.lower()
    return any(kw in low for kw in _PRESTIGIOUS_KEYWORDS)


# Year range: "2015 – 2020", "2015 - Present", "2015–2020", solo year
_YEAR_RANGE_RE = _re.compile(
    r'\b((19|20)\d{2})\s*(?:[–—\-]+\s*(?:((?:19|20)\d{2})|([Pp]resent|[Cc]urrent|[Nn]ow|[Tt]oday)))?'
)

_ENTITY_RE = _re.compile(r'\\(?:textbf|textit|textsc|textmd)\{([^}]{2,80})\}')
_PLAIN_CAP_RE = _re.compile(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,5})\b')


def _extract_entity(text: str) -> str:
    m = _ENTITY_RE.search(text)
    if m:
        val = m.group(1).strip()
        if len(val) > 2 and not val.startswith('\\'):
            return val
    m = _PLAIN_CAP_RE.search(text)
    if m:
        return m.group(1).strip()
    return ""


class AgeEntry(BaseModel):
    line: int
    company_or_institution: str
    start_year: int
    end_year: Optional[int]  # None = "Present"
    years_ago: int
    is_old: bool
    is_prestigious: bool
    recommendation: str


class AgeAnalysisResponse(BaseModel):
    entries: List[AgeEntry]
    has_old_entries: bool


class AgeAnalysisRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)


@router.post("/age-analysis", response_model=AgeAnalysisResponse)
async def age_analysis(request: AgeAnalysisRequest) -> AgeAnalysisResponse:
    """
    Detect year-range entries in LaTeX resume and flag those older than 10 years.
    Prestigious institutions are exempt. Pure regex — no LLM required.
    """
    current_year = _dt.date.today().year
    lines = request.latex_content.splitlines()
    entries: List[AgeEntry] = []
    seen: set[tuple[int, int]] = set()

    for line_idx, line_text in enumerate(lines):
        for m in _YEAR_RANGE_RE.finditer(line_text):
            start_year = int(m.group(1))
            if not (1950 <= start_year <= current_year):
                continue

            end_group_year = m.group(3)
            end_group_present = m.group(4)
            if end_group_year:
                end_year: Optional[int] = int(end_group_year)
            elif end_group_present:
                end_year = None  # Present / ongoing
            else:
                end_year = None

            key = (line_idx, start_year)
            if key in seen:
                continue
            seen.add(key)

            years_ago = current_year - start_year
            # Use the most-recent year for the staleness check so that a
            # still-active role (end_year=None → ongoing) is never flagged old.
            recency_year = end_year if end_year is not None else current_year
            entity = ""
            for ctx_offset in range(3):
                ctx_idx = line_idx - ctx_offset
                if ctx_idx < 0:
                    break
                entity = _extract_entity(lines[ctx_idx])
                if entity:
                    break
            if not entity:
                entity = "Experience entry"

            prestigious = _check_prestigious(entity)
            is_old = (current_year - recency_year) > 10 and not prestigious

            if is_old:
                recommendation = (
                    "Consider condensing this entry to 1-2 bullet points "
                    "or removing if not directly relevant to your target role."
                )
            elif years_ago > 10 and prestigious:
                recommendation = (
                    "Prestigious institution — keeping this entry is recommended "
                    "even though it is older than 10 years."
                )
            else:
                recommendation = "This entry is recent — no action needed."

            entries.append(AgeEntry(
                line=line_idx + 1,
                company_or_institution=entity,
                start_year=start_year,
                end_year=end_year,
                years_ago=years_ago,
                is_old=is_old,
                is_prestigious=prestigious,
                recommendation=recommendation,
            ))

    entries.sort(key=lambda e: e.start_year, reverse=True)
    return AgeAnalysisResponse(
        entries=entries,
        has_old_entries=any(e.is_old for e in entries),
    )


# ── Contact Info Formatter (Feature 64) ─────────────────────────────────────

try:
    import phonenumbers as _phonenumbers
    from phonenumbers import PhoneNumberFormat as _PhoneNumberFormat
    _PHONENUMBERS_AVAILABLE = True
except ImportError:
    _PHONENUMBERS_AVAILABLE = False

_LINKEDIN_RE = _re.compile(
    r'(?:https?://)?(?:www\.)?linkedin\.com/in/([A-Za-z0-9_%-]+)/?',
    _re.IGNORECASE,
)
_GITHUB_RE = _re.compile(
    r'(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_-]+)(/[^\s\\}]*)?',
    _re.IGNORECASE,
)
_EMAIL_CONTACT_RE = _re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
)
_PHONE_DETECT_RE = _re.compile(
    r'\+?\d[\d\s\-().]{7,17}\d'
)


def _normalize_phone(raw: str) -> Optional[str]:
    if not _PHONENUMBERS_AVAILABLE:
        return None
    for region in (None, "US"):
        try:
            parsed = _phonenumbers.parse(raw, region)
            if _phonenumbers.is_valid_number(parsed):
                return _phonenumbers.format_number(parsed, _PhoneNumberFormat.INTERNATIONAL)
        except Exception:
            pass
    return None


class ContactFormatRequest(BaseModel):
    latex_content: str = Field(..., max_length=200_000)


class ContactChange(BaseModel):
    line: int
    original: str
    normalized: str
    type: str  # "phone" | "linkedin" | "github" | "email"


class ContactFormatResponse(BaseModel):
    changes: List[ContactChange]
    formatted_latex: str


@router.post("/format-contacts", response_model=ContactFormatResponse)
async def format_contacts(request: ContactFormatRequest) -> ContactFormatResponse:
    """
    Detect and normalize phone numbers, LinkedIn/GitHub URLs, and emails in LaTeX.
    Pure regex + phonenumbers library. No LLM required.
    """
    content = request.latex_content

    def _line_num(pos: int) -> int:
        return content.count('\n', 0, pos) + 1

    # Collect replacements as (start, end, original, normalized, type)
    reps: list[tuple[int, int, str, str, str]] = []

    for m in _LINKEDIN_RE.finditer(content):
        username = m.group(1).rstrip('/')
        normalized = f"linkedin.com/in/{username}"
        if m.group(0) != normalized:
            reps.append((m.start(), m.end(), m.group(0), normalized, "linkedin"))

    for m in _GITHUB_RE.finditer(content):
        if 'linkedin' in m.group(0).lower():
            continue
        username = m.group(1)
        suffix = (m.group(2) or "").rstrip("/")
        normalized = f"github.com/{username}{suffix}"
        if m.group(0) != normalized:
            reps.append((m.start(), m.end(), m.group(0), normalized, "github"))

    for m in _EMAIL_CONTACT_RE.finditer(content):
        normalized = m.group(0).lower()
        if normalized != m.group(0):
            reps.append((m.start(), m.end(), m.group(0), normalized, "email"))

    for m in _PHONE_DETECT_RE.finditer(content):
        raw = m.group(0).strip()
        normalized = _normalize_phone(raw)
        if normalized and normalized != raw:
            reps.append((m.start(), m.end(), raw, normalized, "phone"))

    # Deduplicate, preferring earlier match
    seen_starts: set[int] = set()
    unique_reps: list[tuple[int, int, str, str, str]] = []
    for rep in sorted(reps, key=lambda r: r[0]):
        if rep[0] not in seen_starts:
            seen_starts.add(rep[0])
            unique_reps.append(rep)

    # Apply in reverse order so positions remain valid
    result = content
    changes: List[ContactChange] = []
    for start, end, original, normalized, ctype in reversed(unique_reps):
        result = result[:start] + normalized + result[end:]
        changes.insert(0, ContactChange(
            line=_line_num(start),
            original=original,
            normalized=normalized,
            type=ctype,
        ))

    return ContactFormatResponse(changes=changes, formatted_latex=result)


# ── Multilingual Resume Translation (Feature 44) ─────────────────────────────


class TranslateRequest(BaseModel):
    resume_id: str
    target_language: str = Field(..., min_length=1, max_length=50)   # e.g. "French"
    language_code: str = Field(..., min_length=1, max_length=10)     # e.g. "fr"


class TranslateResponse(BaseModel):
    success: bool
    variant_resume_id: str
    cached: bool


def _translate_cache_key(latex_content: str, target_language: str) -> str:
    # Hash entire content to avoid collision from shared preambles
    content_hash = hashlib.sha256(latex_content.encode()).hexdigest()[:16]
    lang_hash = hashlib.sha256(target_language.lower().strip().encode()).hexdigest()[:8]
    return f"ai:translate:{content_hash}{lang_hash}"


_TRANSLATE_SYSTEM_PROMPT = """\
Translate this LaTeX resume to {target_language}.
STRICT RULES:
1. Translate ONLY prose text content.
2. Never modify LaTeX commands, environments, or special characters.
3. Never modify: \\section{{}}, \\textbf{{}}, \\begin{{...}}, \\end{{...}}, dates, numbers, proper nouns, URLs.
4. Translate: bullet text after \\item, section header labels, prose descriptions.
5. Return ONLY the translated LaTeX source — no explanation or markdown fences.\
"""


@router.post("/translate", response_model=TranslateResponse)
async def translate_resume(
    request: TranslateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Translate a resume to a target language, creating a variant fork. Auth required."""
    # Fetch resume with ownership check
    result = await db.execute(
        select(Resume).where(Resume.id == request.resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Cache check
    cache_key = _translate_cache_key(resume.latex_content, request.target_language)
    was_cached = False
    translated_latex: Optional[str] = None

    try:
        cached_value = await cache_manager.get(cache_key)
        if cached_value and isinstance(cached_value, str):
            translated_latex = cached_value
            was_cached = True
    except Exception:
        pass

    if translated_latex is None:
        # Resolve API key: BYOK first, then system default
        api_key: Optional[str] = None
        try:
            from ..services.api_key_service import api_key_service
            api_key = await api_key_service.get_user_provider(db, user_id, "openai")
        except Exception:
            pass
        if not api_key and settings.OPENAI_API_KEY:
            api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise HTTPException(status_code=503, detail="No OpenAI API key configured")

        system_prompt = _TRANSLATE_SYSTEM_PROMPT.format(target_language=request.target_language)

        try:
            llm_client = openai.AsyncOpenAI(api_key=api_key)
            response = await llm_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": resume.latex_content},
                ],
                max_tokens=8000,
                temperature=0.3,
            )
            translated_latex = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error(f"translate LLM call failed: {exc}")
            raise HTTPException(status_code=502, detail="Translation service error. Please try again.")

        if not translated_latex:
            raise HTTPException(status_code=502, detail="Translation returned empty result. Please try again.")

        # Cache as string TTL=3600
        try:
            await cache_manager.set(cache_key, translated_latex, ttl=3600)
        except Exception:
            pass
        was_cached = False

    # Create variant fork
    variant = Resume(
        id=str(uuid4()),
        user_id=user_id,
        title=f"{resume.title} — [{request.language_code.upper()}]",
        latex_content=translated_latex,
        is_template=False,
        tags=list(resume.tags) if resume.tags else None,
        parent_resume_id=resume.id,
    )
    db.add(variant)
    await db.commit()
    await db.refresh(variant)

    return TranslateResponse(
        success=True,
        variant_resume_id=str(variant.id),
        cached=was_cached,
    )

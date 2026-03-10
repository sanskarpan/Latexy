"""
ATS Scoring API routes for Phase 9.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import DeepAnalysisTrial, Resume
from ..middleware.auth_middleware import get_current_user_optional, get_current_user_required
from ..services.api_key_service import api_key_service
from ..services.ats_scoring_service import ats_scoring_service
from ..workers.ats_worker import deep_analyze_ats_task, submit_ats_scoring, submit_job_description_analysis

logger = get_logger(__name__)

router = APIRouter(prefix="/ats", tags=["ats-scoring"])


# Pydantic models for ATS scoring
class ATSScoreRequest(BaseModel):
    latex_content: str = Field(..., description="LaTeX resume content")
    job_description: Optional[str] = Field(None, description="Job description for keyword matching")
    industry: Optional[str] = Field(None, description="Industry for specialized scoring")
    user_plan: str = Field("free", description="User subscription plan")
    device_fingerprint: Optional[str] = Field(None, description="Device fingerprint for anonymous users")
    async_processing: bool = Field(True, description="Whether to process asynchronously")
    metadata: Optional[Dict] = Field(None, description="Additional metadata")


class ATSScoreResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    ats_score: Optional[float] = None
    category_scores: Optional[Dict[str, float]] = None
    recommendations: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    strengths: Optional[List[str]] = None
    detailed_analysis: Optional[Dict[str, Any]] = None
    processing_time: Optional[float] = None
    message: str
    timestamp: Optional[str] = None


class JobDescriptionAnalysisRequest(BaseModel):
    job_description: str = Field(..., description="Job description to analyze")
    user_plan: str = Field("free", description="User subscription plan")
    async_processing: bool = Field(True, description="Whether to process asynchronously")
    metadata: Optional[Dict] = Field(None, description="Additional metadata")


class JobDescriptionAnalysisResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    keywords: Optional[List[str]] = None
    requirements: Optional[List[str]] = None
    preferred_qualifications: Optional[List[str]] = None
    detected_industry: Optional[str] = None
    analysis_metrics: Optional[Dict[str, Any]] = None
    optimization_tips: Optional[List[str]] = None
    processing_time: Optional[float] = None
    message: str


class ATSRecommendationsRequest(BaseModel):
    ats_score: float = Field(..., description="Current ATS score")
    category_scores: Dict[str, float] = Field(..., description="Category scores")
    industry: Optional[str] = Field(None, description="Industry context")


class ATSRecommendationsResponse(BaseModel):
    success: bool
    priority_improvements: List[Dict[str, Any]]
    quick_wins: List[str]
    long_term_improvements: List[str]
    industry_specific_tips: List[str]
    estimated_score_improvement: float
    message: str


# ATS Scoring endpoints
@router.post("/score", response_model=ATSScoreResponse)
async def score_resume_ats(
    request: ATSScoreRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional)
):
    """Score a resume for ATS compatibility."""
    try:
        # Extract user information
        ip_address = http_request.client.host if http_request.client else None

        # Validate input
        if not request.latex_content.strip():
            raise HTTPException(status_code=400, detail="LaTeX content is required")

        # Add IP address to metadata
        metadata = request.metadata or {}
        metadata.update({
            "ip_address": ip_address,
            "submitted_via": "api",
            "endpoint": "ats_score"
        })

        if request.async_processing:
            # Generate job_id here (submission helper requires it as positional arg)
            job_id = str(uuid.uuid4())
            submit_ats_scoring(
                latex_content=request.latex_content,
                job_id=job_id,
                job_description=request.job_description,
                industry=request.industry,
                user_id=user_id,
                user_plan=request.user_plan,
                device_fingerprint=request.device_fingerprint,
                metadata=metadata,
            )

            return ATSScoreResponse(
                success=True,
                job_id=job_id,
                message="ATS scoring job submitted successfully. Use the job ID to check status and results."
            )
        else:
            # Process synchronously (for testing or immediate results)
            start_time = asyncio.get_event_loop().time()

            result = await ats_scoring_service.score_resume(
                latex_content=request.latex_content,
                job_description=request.job_description,
                industry=request.industry
            )

            processing_time = asyncio.get_event_loop().time() - start_time

            return ATSScoreResponse(
                success=True,
                ats_score=result.overall_score,
                category_scores=result.category_scores,
                recommendations=result.recommendations,
                warnings=result.warnings,
                strengths=result.strengths,
                detailed_analysis=result.detailed_analysis,
                processing_time=processing_time,
                message=f"ATS scoring completed: {result.overall_score:.1f}/100",
                timestamp=result.timestamp
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in ATS scoring endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/analyze-job-description", response_model=JobDescriptionAnalysisResponse)
async def analyze_job_description_ats(
    request: JobDescriptionAnalysisRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional)
):
    """Analyze job description for ATS optimization insights."""
    try:
        # Extract user information
        ip_address = http_request.client.host if http_request.client else None

        # Validate input
        if not request.job_description.strip():
            raise HTTPException(status_code=400, detail="Job description is required")

        # Add IP address to metadata
        metadata = request.metadata or {}
        metadata.update({
            "ip_address": ip_address,
            "submitted_via": "api",
            "endpoint": "analyze_job_description"
        })

        if request.async_processing:
            # Generate job_id here (submission helper requires it as positional arg)
            job_id = str(uuid.uuid4())
            submit_job_description_analysis(
                job_description=request.job_description,
                job_id=job_id,
                user_id=user_id,
                user_plan=request.user_plan,
                metadata=metadata,
            )

            return JobDescriptionAnalysisResponse(
                success=True,
                job_id=job_id,
                message="Job description analysis submitted successfully. Use the job ID to check status and results."
            )
        else:
            # Process synchronously
            start_time = asyncio.get_event_loop().time()

            # Extract keywords from job description
            keywords = ats_scoring_service._extract_keywords_from_job_description(request.job_description)

            # Basic analysis (simplified for sync processing)
            words = request.job_description.split()
            sentences = request.job_description.split('.')

            processing_time = asyncio.get_event_loop().time() - start_time

            return JobDescriptionAnalysisResponse(
                success=True,
                keywords=keywords[:15],
                requirements=["Analysis requires async processing for detailed results"],
                preferred_qualifications=[],
                detected_industry="general",
                analysis_metrics={
                    "word_count": len(words),
                    "sentence_count": len(sentences),
                    "keyword_count": len(keywords)
                },
                optimization_tips=[
                    "Include identified keywords naturally in your resume",
                    "Use similar language and terminology as the job posting",
                    "Address key requirements explicitly"
                ],
                processing_time=processing_time,
                message="Basic job description analysis completed. Use async processing for detailed analysis."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in job description analysis endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/recommendations", response_model=ATSRecommendationsResponse)
async def get_ats_recommendations(request: ATSRecommendationsRequest):
    """Get personalized ATS improvement recommendations."""
    try:
        # Analyze current scores and generate recommendations
        priority_improvements = []
        quick_wins = []
        long_term_improvements = []
        industry_specific_tips = []

        # Prioritize improvements based on category scores
        for category, score in request.category_scores.items():
            if score < 50:
                priority_improvements.append({
                    "category": category,
                    "current_score": score,
                    "priority": "high",
                    "potential_improvement": 100 - score,
                    "recommended_actions": _get_category_recommendations(category, score)
                })
            elif score < 70:
                priority_improvements.append({
                    "category": category,
                    "current_score": score,
                    "priority": "medium",
                    "potential_improvement": 100 - score,
                    "recommended_actions": _get_category_recommendations(category, score)
                })

        # Generate quick wins (easy improvements)
        if request.category_scores.get("formatting", 100) < 80:
            quick_wins.extend([
                "Remove complex tables and graphics",
                "Use standard fonts (Arial, Helvetica, Calibri)",
                "Ensure consistent formatting throughout"
            ])

        if request.category_scores.get("keywords", 100) < 70:
            quick_wins.extend([
                "Include more action verbs (achieved, managed, developed)",
                "Add quantifiable achievements with numbers",
                "Include relevant technical skills"
            ])

        # Generate long-term improvements
        if request.category_scores.get("content", 100) < 60:
            long_term_improvements.extend([
                "Restructure experience section for better impact",
                "Develop stronger achievement statements",
                "Align content more closely with target roles"
            ])

        if request.category_scores.get("structure", 100) < 70:
            long_term_improvements.extend([
                "Reorganize resume sections for better flow",
                "Add missing sections (summary, skills)",
                "Improve section headers and organization"
            ])

        # Industry-specific tips
        if request.industry:
            industry_tips = {
                "technology": [
                    "Highlight programming languages and frameworks",
                    "Include GitHub or portfolio links",
                    "Mention agile/scrum experience",
                    "Quantify technical achievements"
                ],
                "finance": [
                    "Include financial modeling experience",
                    "Mention regulatory compliance knowledge",
                    "Highlight analytical and quantitative skills",
                    "Include relevant certifications (CFA, FRM)"
                ],
                "marketing": [
                    "Highlight campaign performance metrics",
                    "Include digital marketing tools experience",
                    "Mention brand management achievements",
                    "Show ROI and conversion improvements"
                ],
                "healthcare": [
                    "Include patient care experience",
                    "Mention clinical skills and certifications",
                    "Highlight compliance and safety knowledge",
                    "Include continuing education"
                ]
            }
            industry_specific_tips = industry_tips.get(request.industry, [])

        # Estimate potential score improvement
        current_score = request.ats_score
        max_improvement = min(30, 100 - current_score)  # Cap at 30 points improvement
        estimated_improvement = max_improvement * 0.7  # Conservative estimate

        return ATSRecommendationsResponse(
            success=True,
            priority_improvements=priority_improvements,
            quick_wins=quick_wins[:5],  # Top 5 quick wins
            long_term_improvements=long_term_improvements[:5],  # Top 5 long-term
            industry_specific_tips=industry_specific_tips[:5],  # Top 5 industry tips
            estimated_score_improvement=estimated_improvement,
            message=f"Generated {len(priority_improvements)} priority improvements and {len(quick_wins)} quick wins"
        )

    except Exception as e:
        logger.error(f"Error generating ATS recommendations: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/industry-keywords/{industry}")
async def get_industry_keywords(industry: str):
    """Get relevant keywords for a specific industry."""
    try:
        # Get industry keywords from the scoring service
        industry_keywords = ats_scoring_service.industry_keywords.get(industry.lower(), [])

        if not industry_keywords:
            raise HTTPException(status_code=404, detail=f"Industry '{industry}' not found")

        return {
            "success": True,
            "industry": industry,
            "keywords": industry_keywords,
            "count": len(industry_keywords),
            "message": f"Retrieved {len(industry_keywords)} keywords for {industry} industry"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting industry keywords: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/supported-industries")
async def get_supported_industries():
    """Get list of supported industries for ATS scoring."""
    try:
        industries = list(ats_scoring_service.industry_keywords.keys())

        return {
            "success": True,
            "industries": industries,
            "count": len(industries),
            "message": f"Retrieved {len(industries)} supported industries"
        }

    except Exception as e:
        logger.error(f"Error getting supported industries: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


_JOB_TTL = 86400


class DeepAnalyzeRequest(BaseModel):
    latex_content: str = Field(..., min_length=1)
    job_description: Optional[str] = None
    device_fingerprint: Optional[str] = None  # required if unauthenticated


class DeepAnalyzeResponse(BaseModel):
    success: bool
    job_id: Optional[str] = None
    uses_remaining: Optional[int] = None  # None = unlimited (auth user)
    message: str


class SemanticMatchRequest(BaseModel):
    job_description: str = Field(..., min_length=50)
    resume_ids: Optional[List[str]] = None  # omit = all user's resumes (max 20)


class SemanticMatchResultItem(BaseModel):
    resume_id: str
    resume_title: str
    similarity_score: Optional[float]
    matched_keywords: List[str]
    missing_keywords: List[str]
    semantic_gaps: Dict[str, Any]
    note: Optional[str] = None


class SemanticMatchResponse(BaseModel):
    success: bool
    results: List[SemanticMatchResultItem]
    message: str


async def _write_deep_analysis_redis_state(
    job_id: str,
    user_id: Optional[str],
) -> None:
    """Write initial queued state for a deep analysis job."""
    r = await get_redis_client()
    state = {
        "status": "queued",
        "stage": "",
        "percent": 0,
        "last_updated": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:state", _JOB_TTL, json.dumps(state))
    meta = {
        "job_id": job_id,
        "user_id": user_id,
        "job_type": "ats_deep",
        "submitted_at": time.time(),
    }
    await r.setex(f"latexy:job:{job_id}:meta", _JOB_TTL, json.dumps(meta))

    event_id = str(uuid.uuid4())
    seq_key = f"latexy:job:{job_id}:seq"
    seq = await r.incr(seq_key)
    await r.expire(seq_key, _JOB_TTL)
    event = {
        "event_id": event_id,
        "job_id": job_id,
        "timestamp": time.time(),
        "sequence": seq,
        "type": "job.queued",
        "job_type": "ats_deep",
        "user_id": user_id,
        "estimated_seconds": 15,
    }
    payload_json = json.dumps(event)
    stream_key = f"latexy:stream:{job_id}"
    await r.xadd(stream_key, {"payload": payload_json, "type": "job.queued",
                               "sequence": str(seq), "event_id": event_id},
                 maxlen=10000, approximate=True)
    await r.expire(stream_key, _JOB_TTL)
    await r.publish(f"latexy:events:{job_id}", json.dumps({"type": "event", "event": event}))


@router.post("/deep-analyze", response_model=DeepAnalyzeResponse)
async def deep_analyze_resume(
    request: DeepAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Submit a deep LLM-powered section analysis job (gpt-4o-mini JSON mode)."""
    if not request.latex_content.strip():
        raise HTTPException(status_code=400, detail="LaTeX content is required")
    if len(request.latex_content.strip()) < 50:
        raise HTTPException(status_code=422, detail="LaTeX content too short (minimum 50 characters)")

    uses_remaining: Optional[int] = None

    if user_id is None:
        # Anonymous — enforce 2-use trial via device_fingerprint
        if not request.device_fingerprint:
            raise HTTPException(
                status_code=401,
                detail="device_fingerprint is required for anonymous deep analysis"
            )
        # Load or create trial record atomically with row lock
        from sqlalchemy.exc import IntegrityError
        result = await db.execute(
            select(DeepAnalysisTrial)
            .where(DeepAnalysisTrial.device_fingerprint == request.device_fingerprint)
            .with_for_update()
        )
        trial = result.scalar_one_or_none()
        if trial is None:
            try:
                trial = DeepAnalysisTrial(
                    device_fingerprint=request.device_fingerprint,
                    usage_count=0,
                )
                db.add(trial)
                await db.flush()
            except IntegrityError:
                # Concurrent request created the row — reload with lock
                await db.rollback()
                result = await db.execute(
                    select(DeepAnalysisTrial)
                    .where(DeepAnalysisTrial.device_fingerprint == request.device_fingerprint)
                    .with_for_update()
                )
                trial = result.scalar_one()

        if trial.usage_count >= settings.DEEP_ANALYSIS_TRIAL_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"Trial limit reached ({settings.DEEP_ANALYSIS_TRIAL_LIMIT} free deep analyses). Sign in for unlimited access."
            )
        uses_remaining = settings.DEEP_ANALYSIS_TRIAL_LIMIT - trial.usage_count - 1

    # Look up BYOK OpenAI key if user is authenticated
    api_key: Optional[str] = None
    if user_id:
        try:
            api_key = await api_key_service.get_user_provider(db, user_id, "openai")
        except Exception:
            pass  # Fall back to platform key

    # Increment trial counter BEFORE dispatching to avoid counting bypasses on commit failure
    if user_id is None:
        trial.usage_count += 1
        trial.last_used = datetime.now(timezone.utc)
        await db.commit()

    job_id = str(uuid.uuid4())
    try:
        await _write_deep_analysis_redis_state(job_id, user_id)
    except Exception as e:
        logger.warning(f"Redis state write failed for job {job_id}: {e} — proceeding without state")

    deep_analyze_ats_task.apply_async(
        kwargs={
            "latex_content": request.latex_content,
            "job_id": job_id,
            "job_description": request.job_description,
            "api_key": api_key,
            "metadata": {"user_id": user_id},
        },
        queue="ats",
    )

    return DeepAnalyzeResponse(
        success=True,
        job_id=job_id,
        uses_remaining=uses_remaining,
        message="Deep analysis job submitted. Subscribe to WebSocket for live results.",
    )


@router.post("/semantic-match", response_model=SemanticMatchResponse)
async def semantic_match_resumes(
    request: SemanticMatchRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
):
    """Rank user resumes by semantic similarity to a job description."""
    try:
        from ..services.embedding_service import embedding_service
    except ImportError:
        raise HTTPException(status_code=503, detail="Embedding service not available")

    # Fetch resumes (filtered by IDs if provided)
    q = select(Resume).where(Resume.user_id == user_id).limit(20)
    if request.resume_ids:
        q = select(Resume).where(
            Resume.user_id == user_id,
            Resume.id.in_(request.resume_ids[:20])
        ).limit(20)
    result = await db.execute(q)
    resumes = result.scalars().all()

    if not resumes:
        return SemanticMatchResponse(success=True, results=[], message="No resumes found")

    # Embed JD once
    try:
        jd_emb = await embedding_service.embed_job_description(request.job_description)
    except Exception as e:
        logger.error(f"JD embedding failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to embed job description")

    jd_text = request.job_description
    match_results: List[SemanticMatchResultItem] = []

    for resume in resumes:
        resume_emb = resume.content_embedding
        if not resume_emb:
            # Skip resumes without embeddings — embed_resume_task will compute them
            match_results.append(SemanticMatchResultItem(
                resume_id=str(resume.id),
                resume_title=resume.title or "Untitled",
                similarity_score=None,
                matched_keywords=[],
                missing_keywords=[],
                semantic_gaps={},
                note="Embedding not yet computed. Please try again in a moment.",
            ))
            # Fire background embed task so it's ready next time
            if settings.OPENAI_API_KEY:
                try:
                    from ..workers.ats_worker import embed_resume_task
                    embed_resume_task.apply_async(
                        kwargs={"resume_id": str(resume.id), "latex_content": resume.latex_content or ""},
                        queue="ats", priority=1,
                    )
                except Exception:
                    pass
            continue

        resume_text = ats_scoring_service._extract_text_from_latex(resume.latex_content)
        match = await embedding_service.semantic_keyword_match(
            resume_emb, jd_emb, jd_text, resume_text
        )
        match_results.append(SemanticMatchResultItem(
            resume_id=str(resume.id),
            resume_title=resume.title,
            similarity_score=match["similarity_score"],
            matched_keywords=match["matched_keywords"],
            missing_keywords=match["missing_keywords"],
            semantic_gaps=match["semantic_gaps"],
        ))

    match_results.sort(key=lambda x: x.similarity_score if x.similarity_score is not None else -1, reverse=True)

    return SemanticMatchResponse(
        success=True,
        results=match_results[:10],
        message=f"Ranked {len(match_results)} resumes by JD similarity",
    )


# Helper functions
def _get_category_recommendations(category: str, score: float) -> List[str]:
    """Get specific recommendations for a category based on score."""
    recommendations = {
        "formatting": [
            "Use standard fonts like Arial or Calibri",
            "Remove tables, graphics, and complex formatting",
            "Ensure consistent spacing and alignment",
            "Use simple bullet points instead of complex lists"
        ],
        "structure": [
            "Add missing required sections (contact, experience, education)",
            "Include recommended sections (summary, skills)",
            "Organize content in logical order",
            "Use clear section headers"
        ],
        "content": [
            "Include more action verbs and strong language",
            "Add quantifiable achievements with specific numbers",
            "Align content with job requirements",
            "Remove irrelevant or outdated information"
        ],
        "keywords": [
            "Include more relevant industry keywords",
            "Add technical skills and competencies",
            "Use job description terminology",
            "Balance keyword density naturally"
        ],
        "readability": [
            "Use shorter, more concise sentences",
            "Remove passive voice constructions",
            "Eliminate filler words and redundancy",
            "Maintain professional tone throughout"
        ]
    }

    return recommendations.get(category, ["Improve overall quality and relevance"])

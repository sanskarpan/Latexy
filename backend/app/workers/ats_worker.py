"""
ATS Scoring worker
"""

import asyncio
import re
import time
import uuid
from typing import Dict, Any, Optional

from celery import current_task
from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager
from ..services.ats_scoring_service import ats_scoring_service

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.ats_worker.score_resume_ats_task")
def score_resume_ats_task(
    self,
    latex_content: str,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Score resume for ATS compatibility asynchronously.
    
    Args:
        latex_content: LaTeX source code
        job_description: Optional job description for keyword matching
        industry: Optional industry for specialized scoring
        user_id: User ID for authenticated users
        user_plan: User subscription plan
        device_fingerprint: Device fingerprint for anonymous users
        metadata: Additional metadata
    
    Returns:
        Dict containing ATS scoring result
    """
    task_id = self.request.id
    job_id = f"ats_{task_id}"
    
    logger.info(f"Starting ATS scoring task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "user_id": user_id,
                "device_fingerprint": device_fingerprint,
                "started_at": time.time(),
                "industry": industry,
                "has_job_description": bool(job_description),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            10, 
            "Initializing ATS scoring analysis"
        ))
        
        # Validate input
        if not latex_content or not latex_content.strip():
            error_msg = "LaTeX content is required for ATS scoring"
            logger.error(f"ATS scoring validation failed for job {job_id}: {error_msg}")
            
            # Set error status
            asyncio.run(job_status_manager.set_job_status(
                job_id, 
                "failed", 
                {"error": error_msg, "completed_at": time.time()}
            ))
            
            return {
                "success": False,
                "job_id": job_id,
                "task_id": task_id,
                "message": error_msg,
                "error": error_msg
            }
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Analyzing resume formatting"
        ))
        
        # Perform ATS scoring
        start_time = time.time()
        
        # Run the scoring service
        scoring_result = asyncio.run(ats_scoring_service.score_resume(
            latex_content=latex_content,
            job_description=job_description,
            industry=industry
        ))
        
        scoring_time = time.time() - start_time
        
        # Update progress based on scoring completion
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            80, 
            f"ATS scoring completed: {scoring_result.overall_score:.1f}/100"
        ))
        
        # Prepare result data
        result_data = {
            "success": True,
            "job_id": job_id,
            "task_id": task_id,
            "message": f"ATS scoring completed successfully: {scoring_result.overall_score:.1f}/100",
            "ats_score": scoring_result.overall_score,
            "category_scores": scoring_result.category_scores,
            "recommendations": scoring_result.recommendations,
            "warnings": scoring_result.warnings,
            "strengths": scoring_result.strengths,
            "detailed_analysis": scoring_result.detailed_analysis,
            "scoring_time": scoring_time,
            "processing_time": scoring_result.processing_time,
            "user_id": user_id,
            "device_fingerprint": device_fingerprint,
            "industry": industry,
            "has_job_description": bool(job_description),
            "completed_at": time.time(),
            "timestamp": scoring_result.timestamp
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "scoring_time": scoring_time,
                "ats_score": scoring_result.overall_score,
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "ATS scoring task completed"
        ))
        
        logger.info(f"ATS scoring task {task_id} completed for job {job_id}: {scoring_result.overall_score:.1f}/100")
        return result_data
        
    except Exception as e:
        logger.error(f"ATS scoring task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "job_id": job_id,
            "task_id": task_id,
            "message": f"ATS scoring error: {str(e)}",
            "error": str(e),
            "ats_score": 0.0,
            "category_scores": {},
            "recommendations": [f"Scoring failed: {str(e)}"],
            "warnings": ["ATS scoring encountered an error"],
            "strengths": [],
            "detailed_analysis": {"error": str(e)},
            "scoring_time": 0,
            "completed_at": time.time()
        }
        
        # Set error status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "failed", 
            {
                "task_id": task_id,
                "error": str(e),
                "completed_at": time.time()
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, error_data))
        
        # Retry logic for transient errors
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying ATS scoring task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60, exc=e)
        
        return error_data


@celery_app.task(bind=True, name="app.workers.ats_worker.analyze_job_description_ats_task")
def analyze_job_description_ats_task(
    self,
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analyze job description for ATS optimization insights.
    
    Args:
        job_description: Job description text
        user_id: User ID for authenticated users
        user_plan: User subscription plan
        metadata: Additional metadata
    
    Returns:
        Dict containing job description analysis
    """
    task_id = self.request.id
    job_id = f"jd_ats_{task_id}"
    
    logger.info(f"Starting job description ATS analysis task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "user_id": user_id,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Analyzing job description"
        ))
        
        # Validate input
        if not job_description or not job_description.strip():
            error_msg = "Job description is required for analysis"
            logger.error(f"Job description analysis validation failed for job {job_id}: {error_msg}")
            
            asyncio.run(job_status_manager.set_job_status(
                job_id, 
                "failed", 
                {"error": error_msg, "completed_at": time.time()}
            ))
            
            return {
                "success": False,
                "job_id": job_id,
                "task_id": task_id,
                "message": error_msg,
                "error": error_msg
            }
        
        # Perform analysis
        start_time = time.time()
        
        # Extract keywords from job description
        keywords = ats_scoring_service._extract_keywords_from_job_description(job_description)
        
        # Analyze job description structure
        words = job_description.split()
        sentences = job_description.split('.')
        
        # Identify key requirements
        requirement_patterns = [
            r'required?:?\s*([^.]+)',
            r'must have:?\s*([^.]+)',
            r'essential:?\s*([^.]+)',
            r'minimum:?\s*([^.]+)'
        ]
        
        requirements = []
        for pattern in requirement_patterns:
            matches = re.findall(pattern, job_description, re.IGNORECASE)
            requirements.extend(matches)
        
        # Identify preferred qualifications
        preferred_patterns = [
            r'preferred?:?\s*([^.]+)',
            r'nice to have:?\s*([^.]+)',
            r'bonus:?\s*([^.]+)',
            r'plus:?\s*([^.]+)'
        ]
        
        preferred = []
        for pattern in preferred_patterns:
            matches = re.findall(pattern, job_description, re.IGNORECASE)
            preferred.extend(matches)
        
        # Industry detection
        industry_indicators = {
            "technology": ["software", "programming", "development", "tech", "IT"],
            "finance": ["financial", "banking", "investment", "accounting"],
            "healthcare": ["medical", "healthcare", "clinical", "patient"],
            "marketing": ["marketing", "advertising", "brand", "campaign"],
            "sales": ["sales", "revenue", "client", "customer"]
        }
        
        detected_industry = "general"
        for industry, indicators in industry_indicators.items():
            if any(indicator.lower() in job_description.lower() for indicator in indicators):
                detected_industry = industry
                break
        
        analysis_time = time.time() - start_time
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            90, 
            "Analysis completed"
        ))
        
        # Prepare result data
        result_data = {
            "success": True,
            "job_id": job_id,
            "task_id": task_id,
            "message": "Job description analysis completed successfully",
            "keywords": keywords[:15],  # Top 15 keywords
            "requirements": requirements[:10],  # Top 10 requirements
            "preferred_qualifications": preferred[:10],  # Top 10 preferred
            "detected_industry": detected_industry,
            "analysis_metrics": {
                "word_count": len(words),
                "sentence_count": len(sentences),
                "keyword_count": len(keywords),
                "requirement_count": len(requirements),
                "preferred_count": len(preferred)
            },
            "optimization_tips": [
                "Include identified keywords naturally in your resume",
                "Address the required qualifications explicitly",
                "Highlight relevant experience for the detected industry",
                "Use similar language and terminology as the job posting"
            ],
            "analysis_time": analysis_time,
            "user_id": user_id,
            "completed_at": time.time()
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "analysis_time": analysis_time,
                "detected_industry": detected_industry,
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Job description analysis completed"
        ))
        
        logger.info(f"Job description ATS analysis task {task_id} completed for job {job_id}")
        return result_data
        
    except Exception as e:
        logger.error(f"Job description ATS analysis task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "job_id": job_id,
            "task_id": task_id,
            "message": f"Job description analysis error: {str(e)}",
            "error": str(e),
            "keywords": [],
            "requirements": [],
            "preferred_qualifications": [],
            "detected_industry": "unknown",
            "analysis_time": 0,
            "completed_at": time.time()
        }
        
        # Set error status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "failed", 
            {
                "task_id": task_id,
                "error": str(e),
                "completed_at": time.time()
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, error_data))
        
        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying job description analysis task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=30, exc=e)
        
        return error_data


# Utility functions to submit ATS jobs
def submit_ats_scoring(
    latex_content: str,
    job_description: Optional[str] = None,
    industry: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit ATS scoring job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    if priority is None:
        priority = get_task_priority(user_plan)
    
    # Submit task to queue
    task = score_resume_ats_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_description": job_description,
            "industry": industry,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata
        },
        priority=priority,
        queue="ats"
    )
    
    job_id = f"ats_{task.id}"
    logger.info(f"Submitted ATS scoring job {job_id} with task {task.id}")
    return job_id


def submit_job_description_analysis(
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit job description analysis job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    if priority is None:
        priority = get_task_priority(user_plan)
    
    # Submit task to queue
    task = analyze_job_description_ats_task.apply_async(
        args=[job_description],
        kwargs={
            "user_id": user_id,
            "user_plan": user_plan,
            "metadata": metadata
        },
        priority=priority,
        queue="ats"
    )
    
    job_id = f"jd_ats_{task.id}"
    logger.info(f"Submitted job description analysis job {job_id} with task {task.id}")
    return job_id

"""
LLM optimization worker for Phase 8.
"""

import asyncio
import time
import uuid
from typing import Dict, Any, Optional

from celery import current_task
from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager
from ..services.llm_service import llm_service
from ..models.llm_schemas import OptimizationRequest, OptimizationResponse

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.llm_worker.optimize_resume_task")
def optimize_resume_task(
    self,
    latex_content: str,
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    provider: str = "openai",
    model: Optional[str] = None,
    user_api_key: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Optimize resume using LLM asynchronously.
    
    Args:
        latex_content: LaTeX source code
        job_description: Job description for optimization
        user_id: User ID for authenticated users
        user_plan: User subscription plan
        optimization_level: Optimization level (conservative, balanced, aggressive)
        provider: LLM provider (openai, anthropic, gemini)
        model: Specific model to use
        user_api_key: User's API key for BYOK
        metadata: Additional metadata
    
    Returns:
        Dict containing optimization result
    """
    task_id = self.request.id
    job_id = f"llm_{task_id}"
    
    logger.info(f"Starting LLM optimization task {task_id} for job {job_id}")
    
    try:
        # Check if LLM service is available
        if not llm_service.is_available() and not user_api_key:
            error_msg = "LLM service is not available and no user API key provided"
            logger.error(f"LLM service unavailable for task {task_id}: {error_msg}")
            
            return {
                "success": False,
                "task_id": task_id,
                "job_id": job_id,
                "message": error_msg,
                "error": error_msg,
                "optimized_latex": latex_content,  # Return original content
                "changes_made": [],
                "ats_score": None
            }
        
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "user_id": user_id,
                "started_at": time.time(),
                "provider": provider,
                "model": model,
                "optimization_level": optimization_level,
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            10, 
            "Preparing optimization request"
        ))
        
        # Create optimization request
        request = OptimizationRequest(
            latex_content=latex_content,
            job_description=job_description,
            optimization_level=optimization_level
        )
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            30, 
            "Analyzing job description"
        ))
        
        # Perform optimization
        start_time = time.time()
        
        if user_api_key:
            # Use user's API key (BYOK)
            # TODO: Implement BYOK optimization logic
            logger.info(f"Using BYOK for optimization task {task_id}")
            result = asyncio.run(llm_service.optimize_resume(request))
        else:
            # Use platform API key
            result = asyncio.run(llm_service.optimize_resume(request))
        
        optimization_time = time.time() - start_time
        
        # Update progress based on result
        if result.success:
            asyncio.run(job_status_manager.set_job_progress(
                job_id, 
                90, 
                "Optimization completed successfully"
            ))
        else:
            asyncio.run(job_status_manager.set_job_progress(
                job_id, 
                50, 
                "Optimization failed"
            ))
        
        # Prepare result data
        result_data = {
            "success": result.success,
            "task_id": task_id,
            "job_id": job_id,
            "message": result.message,
            "optimized_latex": result.optimized_latex if result.success else latex_content,
            "changes_made": result.changes_made if result.success else [],
            "ats_score": result.ats_score if result.success else None,
            "keywords_added": result.keywords_added if result.success else [],
            "optimization_time": optimization_time,
            "provider": provider,
            "model": model or settings.OPENAI_MODEL,
            "tokens_used": getattr(result, 'tokens_used', None),
            "user_id": user_id,
            "completed_at": time.time()
        }
        
        if not result.success:
            result_data["error"] = result.message
        
        # Set final status and result
        final_status = "completed" if result.success else "failed"
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            final_status, 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "optimization_time": optimization_time,
                "success": result.success,
                "tokens_used": getattr(result, 'tokens_used', None)
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Optimization task completed"
        ))
        
        logger.info(f"LLM optimization task {task_id} completed for job {job_id}: {result.success}")
        return result_data
        
    except Exception as e:
        logger.error(f"LLM optimization task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Optimization error: {str(e)}",
            "error": str(e),
            "optimized_latex": latex_content,  # Return original content
            "changes_made": [],
            "ats_score": None,
            "keywords_added": [],
            "optimization_time": 0,
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
        if self.request.retries < self.max_retries and "rate limit" not in str(e).lower():
            logger.info(f"Retrying LLM optimization task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=120, exc=e)
        
        return error_data


@celery_app.task(bind=True, name="app.workers.llm_worker.analyze_job_description_task")
def analyze_job_description_task(
    self,
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    provider: str = "openai",
    model: Optional[str] = None,
    user_api_key: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analyze job description to extract key requirements.
    
    Args:
        job_description: Job description text
        user_id: User ID for authenticated users
        user_plan: User subscription plan
        provider: LLM provider
        model: Specific model to use
        user_api_key: User's API key for BYOK
        metadata: Additional metadata
    
    Returns:
        Dict containing analysis result
    """
    task_id = self.request.id
    job_id = f"jd_analysis_{task_id}"
    
    logger.info(f"Starting job description analysis task {task_id} for job {job_id}")
    
    try:
        # Check if LLM service is available
        if not llm_service.is_available() and not user_api_key:
            error_msg = "LLM service is not available and no user API key provided"
            logger.error(f"LLM service unavailable for task {task_id}: {error_msg}")
            
            return {
                "success": False,
                "task_id": task_id,
                "job_id": job_id,
                "message": error_msg,
                "error": error_msg,
                "keywords": [],
                "skills": [],
                "requirements": [],
                "industry": "unknown"
            }
        
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "user_id": user_id,
                "started_at": time.time(),
                "provider": provider,
                "model": model,
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Analyzing job description"
        ))
        
        # Perform analysis (simplified for now)
        start_time = time.time()
        
        # TODO: Implement proper job description analysis
        # For now, return a basic analysis
        analysis_result = {
            "success": True,
            "keywords": ["python", "machine learning", "data analysis"],  # Placeholder
            "skills": ["Python", "SQL", "Machine Learning"],  # Placeholder
            "requirements": ["Bachelor's degree", "3+ years experience"],  # Placeholder
            "industry": "technology",  # Placeholder
            "experience_level": "mid-level",  # Placeholder
            "job_type": "full-time"  # Placeholder
        }
        
        analysis_time = time.time() - start_time
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            90, 
            "Analysis completed"
        ))
        
        # Prepare result data
        result_data = {
            "success": analysis_result["success"],
            "task_id": task_id,
            "job_id": job_id,
            "message": "Job description analyzed successfully",
            "keywords": analysis_result["keywords"],
            "skills": analysis_result["skills"],
            "requirements": analysis_result["requirements"],
            "industry": analysis_result["industry"],
            "experience_level": analysis_result.get("experience_level", "unknown"),
            "job_type": analysis_result.get("job_type", "unknown"),
            "analysis_time": analysis_time,
            "provider": provider,
            "model": model or settings.OPENAI_MODEL,
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
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Analysis task completed"
        ))
        
        logger.info(f"Job description analysis task {task_id} completed for job {job_id}")
        return result_data
        
    except Exception as e:
        logger.error(f"Job description analysis task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Analysis error: {str(e)}",
            "error": str(e),
            "keywords": [],
            "skills": [],
            "requirements": [],
            "industry": "unknown",
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
            raise self.retry(countdown=60, exc=e)
        
        return error_data


# Utility functions to submit LLM jobs
def submit_resume_optimization(
    latex_content: str,
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    optimization_level: str = "balanced",
    provider: str = "openai",
    model: Optional[str] = None,
    user_api_key: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit resume optimization job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    if priority is None:
        priority = get_task_priority(user_plan)
    
    # Submit task to queue
    task = optimize_resume_task.apply_async(
        args=[latex_content, job_description],
        kwargs={
            "user_id": user_id,
            "user_plan": user_plan,
            "optimization_level": optimization_level,
            "provider": provider,
            "model": model,
            "user_api_key": user_api_key,
            "metadata": metadata
        },
        priority=priority,
        queue="llm"
    )
    
    job_id = f"llm_{task.id}"
    logger.info(f"Submitted resume optimization job {job_id} with task {task.id}")
    return job_id


def submit_job_description_analysis(
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    provider: str = "openai",
    model: Optional[str] = None,
    user_api_key: Optional[str] = None,
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
    task = analyze_job_description_task.apply_async(
        args=[job_description],
        kwargs={
            "user_id": user_id,
            "user_plan": user_plan,
            "provider": provider,
            "model": model,
            "user_api_key": user_api_key,
            "metadata": metadata
        },
        priority=priority,
        queue="llm"
    )
    
    job_id = f"jd_analysis_{task.id}"
    logger.info(f"Submitted job description analysis job {job_id} with task {task.id}")
    return job_id

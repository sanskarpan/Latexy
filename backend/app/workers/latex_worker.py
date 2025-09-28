"""
LaTeX compilation worker for Phase 8.
"""

import asyncio
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from celery import current_task
from ..core.celery_app import celery_app, get_task_priority
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager
from ..services.latex_service import latex_service
from ..models.schemas import CompilationResponse

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.latex_worker.compile_latex_task")
def compile_latex_task(
    self, 
    latex_content: str, 
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Compile LaTeX content to PDF asynchronously.
    
    Args:
        latex_content: LaTeX source code
        job_id: Optional job ID (will generate if not provided)
        user_id: User ID for authenticated users
        user_plan: User subscription plan for priority
        device_fingerprint: Device fingerprint for anonymous users
        metadata: Additional metadata
    
    Returns:
        Dict containing compilation result
    """
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    task_id = self.request.id
    logger.info(f"Starting LaTeX compilation task {task_id} for job {job_id}")
    
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
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            10, 
            "Validating LaTeX content"
        ))
        
        # Validate LaTeX content
        if not latex_service.validate_latex_content(latex_content):
            error_msg = "Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            logger.error(f"LaTeX validation failed for job {job_id}: {error_msg}")
            
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
            30, 
            "Starting LaTeX compilation"
        ))
        
        # Perform compilation
        start_time = time.time()
        result = asyncio.run(latex_service.compile_latex(latex_content, job_id))
        compilation_time = time.time() - start_time
        
        # Update progress
        if result.success:
            asyncio.run(job_status_manager.set_job_progress(
                job_id, 
                90, 
                "Compilation successful, finalizing"
            ))
        else:
            asyncio.run(job_status_manager.set_job_progress(
                job_id, 
                50, 
                "Compilation failed"
            ))
        
        # Prepare result data
        result_data = {
            "success": result.success,
            "job_id": job_id,
            "task_id": task_id,
            "message": result.message,
            "compilation_time": compilation_time,
            "pdf_size": result.pdf_size if result.success else None,
            "log_output": result.log_output,
            "user_id": user_id,
            "device_fingerprint": device_fingerprint,
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
                "compilation_time": compilation_time,
                "success": result.success
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Task completed"
        ))
        
        logger.info(f"LaTeX compilation task {task_id} completed for job {job_id}: {result.success}")
        return result_data
        
    except Exception as e:
        logger.error(f"LaTeX compilation task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "job_id": job_id,
            "task_id": task_id,
            "message": f"Compilation error: {str(e)}",
            "error": str(e),
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
            logger.info(f"Retrying LaTeX compilation task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60, exc=e)
        
        return error_data


@celery_app.task(bind=True, name="app.workers.latex_worker.compile_latex_with_optimization_task")
def compile_latex_with_optimization_task(
    self,
    latex_content: str,
    job_description: str,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    optimization_level: str = "balanced",
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Optimize and compile LaTeX content in one task.
    
    Args:
        latex_content: LaTeX source code
        job_description: Job description for optimization
        job_id: Optional job ID
        user_id: User ID for authenticated users
        user_plan: User subscription plan
        device_fingerprint: Device fingerprint for anonymous users
        optimization_level: Optimization level (conservative, balanced, aggressive)
        metadata: Additional metadata
    
    Returns:
        Dict containing optimization and compilation results
    """
    if job_id is None:
        job_id = str(uuid.uuid4())
    
    task_id = self.request.id
    logger.info(f"Starting optimization + compilation task {task_id} for job {job_id}")
    
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
                "stage": "optimization",
                "metadata": metadata or {}
            }
        ))
        
        # Step 1: Optimize resume
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Optimizing resume with AI"
        ))
        
        # Import and use LLM worker
        from .llm_worker import optimize_resume_task
        
        optimization_result = optimize_resume_task.apply(
            args=[latex_content, job_description],
            kwargs={
                "user_id": user_id,
                "user_plan": user_plan,
                "optimization_level": optimization_level
            }
        ).get()
        
        if not optimization_result.get("success", False):
            error_msg = f"Optimization failed: {optimization_result.get('error', 'Unknown error')}"
            logger.error(f"Optimization failed for job {job_id}: {error_msg}")
            
            asyncio.run(job_status_manager.set_job_status(
                job_id, 
                "failed", 
                {"error": error_msg, "stage": "optimization", "completed_at": time.time()}
            ))
            
            return {
                "success": False,
                "job_id": job_id,
                "task_id": task_id,
                "message": error_msg,
                "error": error_msg,
                "optimization": optimization_result,
                "compilation": None
            }
        
        # Step 2: Compile optimized LaTeX
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            60, 
            "Compiling optimized LaTeX"
        ))
        
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "stage": "compilation",
                "optimization_completed": True
            }
        ))
        
        optimized_latex = optimization_result.get("optimized_latex", latex_content)
        compilation_result = compile_latex_task.apply(
            args=[optimized_latex],
            kwargs={
                "job_id": f"{job_id}_compiled",
                "user_id": user_id,
                "user_plan": user_plan,
                "device_fingerprint": device_fingerprint,
                "metadata": {"optimized": True, "original_job_id": job_id}
            }
        ).get()
        
        # Combine results
        combined_result = {
            "success": optimization_result.get("success", False) and compilation_result.get("success", False),
            "job_id": job_id,
            "task_id": task_id,
            "optimization": optimization_result,
            "compilation": compilation_result,
            "message": "Optimization and compilation completed",
            "completed_at": time.time()
        }
        
        if not combined_result["success"]:
            combined_result["error"] = "Either optimization or compilation failed"
            combined_result["message"] = "Optimization and compilation failed"
        
        # Set final status
        final_status = "completed" if combined_result["success"] else "failed"
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            final_status, 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "success": combined_result["success"],
                "stage": "completed"
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, combined_result))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Optimization and compilation completed"
        ))
        
        logger.info(f"Optimization + compilation task {task_id} completed for job {job_id}: {combined_result['success']}")
        return combined_result
        
    except Exception as e:
        logger.error(f"Optimization + compilation task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "job_id": job_id,
            "task_id": task_id,
            "message": f"Task error: {str(e)}",
            "error": str(e),
            "optimization": None,
            "compilation": None,
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
            logger.info(f"Retrying optimization + compilation task {task_id} (attempt {self.request.retries + 1})")
            raise self.retry(countdown=120, exc=e)
        
        return error_data


# Utility function to submit LaTeX compilation job
def submit_latex_compilation(
    latex_content: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit LaTeX compilation job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    job_id = str(uuid.uuid4())
    
    if priority is None:
        priority = get_task_priority(user_plan)
    
    # Submit task to queue
    task = compile_latex_task.apply_async(
        args=[latex_content],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "metadata": metadata
        },
        priority=priority,
        queue="latex"
    )
    
    logger.info(f"Submitted LaTeX compilation job {job_id} with task {task.id}")
    return job_id


def submit_optimization_and_compilation(
    latex_content: str,
    job_description: str,
    user_id: Optional[str] = None,
    user_plan: str = "free",
    device_fingerprint: Optional[str] = None,
    optimization_level: str = "balanced",
    priority: Optional[int] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit optimization + compilation job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    job_id = str(uuid.uuid4())
    
    if priority is None:
        priority = get_task_priority(user_plan)
    
    # Submit task to queue
    task = compile_latex_with_optimization_task.apply_async(
        args=[latex_content, job_description],
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "user_plan": user_plan,
            "device_fingerprint": device_fingerprint,
            "optimization_level": optimization_level,
            "metadata": metadata
        },
        priority=priority,
        queue="latex"
    )
    
    logger.info(f"Submitted optimization + compilation job {job_id} with task {task.id}")
    return job_id

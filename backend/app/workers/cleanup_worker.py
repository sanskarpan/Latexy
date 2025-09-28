"""
Cleanup worker for Phase 8 - File and job cleanup tasks.
"""

import asyncio
import time
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from celery import current_task
from ..core.celery_app import celery_app
from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager, redis_manager

logger = get_logger(__name__)


@celery_app.task(bind=True, name="app.workers.cleanup_worker.cleanup_temp_files_task")
def cleanup_temp_files_task(
    self,
    max_age_hours: int = 24,
    target_directory: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Clean up temporary files older than specified age.
    
    Args:
        max_age_hours: Maximum age of files to keep (in hours)
        target_directory: Specific directory to clean (defaults to TEMP_DIR)
        metadata: Additional metadata
    
    Returns:
        Dict containing cleanup result
    """
    task_id = self.request.id
    job_id = f"cleanup_{task_id}"
    
    logger.info(f"Starting temp files cleanup task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "max_age_hours": max_age_hours,
                "target_directory": target_directory,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            10, 
            "Scanning for temporary files"
        ))
        
        # Determine target directory
        cleanup_dir = Path(target_directory) if target_directory else settings.TEMP_DIR
        
        if not cleanup_dir.exists():
            logger.warning(f"Cleanup directory does not exist: {cleanup_dir}")
            result_data = {
                "success": True,
                "task_id": task_id,
                "job_id": job_id,
                "message": "Cleanup directory does not exist",
                "files_deleted": 0,
                "directories_deleted": 0,
                "space_freed": 0,
                "completed_at": time.time()
            }
            
            asyncio.run(job_status_manager.set_job_status(job_id, "completed", {"success": True}))
            asyncio.run(job_status_manager.set_job_result(job_id, result_data))
            return result_data
        
        # Calculate cutoff time
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        cutoff_timestamp = cutoff_time.timestamp()
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            30, 
            f"Cleaning files older than {max_age_hours} hours"
        ))
        
        # Scan and clean files
        files_deleted = 0
        directories_deleted = 0
        space_freed = 0
        errors = []
        
        try:
            # Walk through directory tree
            for item in cleanup_dir.rglob("*"):
                try:
                    # Check if item is old enough to delete
                    if item.stat().st_mtime < cutoff_timestamp:
                        if item.is_file():
                            file_size = item.stat().st_size
                            item.unlink()
                            files_deleted += 1
                            space_freed += file_size
                            logger.debug(f"Deleted file: {item}")
                        elif item.is_dir() and not any(item.iterdir()):
                            # Delete empty directories
                            item.rmdir()
                            directories_deleted += 1
                            logger.debug(f"Deleted empty directory: {item}")
                except Exception as e:
                    error_msg = f"Error deleting {item}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        except Exception as e:
            logger.error(f"Error during cleanup scan: {e}")
            errors.append(f"Scan error: {e}")
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            80, 
            f"Cleanup completed: {files_deleted} files deleted"
        ))
        
        # Clean up empty parent directories
        try:
            for item in cleanup_dir.rglob("*"):
                if item.is_dir() and not any(item.iterdir()) and item != cleanup_dir:
                    try:
                        item.rmdir()
                        directories_deleted += 1
                        logger.debug(f"Deleted empty directory: {item}")
                    except Exception as e:
                        logger.debug(f"Could not delete directory {item}: {e}")
        except Exception as e:
            logger.error(f"Error cleaning empty directories: {e}")
        
        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Cleanup completed: {files_deleted} files, {directories_deleted} directories deleted",
            "files_deleted": files_deleted,
            "directories_deleted": directories_deleted,
            "space_freed": space_freed,
            "space_freed_mb": round(space_freed / (1024 * 1024), 2),
            "max_age_hours": max_age_hours,
            "target_directory": str(cleanup_dir),
            "errors": errors,
            "error_count": len(errors),
            "completed_at": time.time()
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "files_deleted": files_deleted,
                "directories_deleted": directories_deleted,
                "space_freed": space_freed,
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Cleanup task completed"
        ))
        
        logger.info(f"Temp files cleanup task {task_id} completed: {files_deleted} files, {space_freed} bytes freed")
        return result_data
        
    except Exception as e:
        logger.error(f"Temp files cleanup task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Cleanup error: {str(e)}",
            "error": str(e),
            "files_deleted": 0,
            "directories_deleted": 0,
            "space_freed": 0,
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
        
        return error_data


@celery_app.task(bind=True, name="app.workers.cleanup_worker.cleanup_expired_jobs_task")
def cleanup_expired_jobs_task(
    self,
    max_age_hours: int = 24,
    batch_size: int = 100,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Clean up expired job data from Redis.
    
    Args:
        max_age_hours: Maximum age of job data to keep (in hours)
        batch_size: Number of jobs to process in each batch
        metadata: Additional metadata
    
    Returns:
        Dict containing cleanup result
    """
    task_id = self.request.id
    job_id = f"job_cleanup_{task_id}"
    
    logger.info(f"Starting expired jobs cleanup task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "max_age_hours": max_age_hours,
                "batch_size": batch_size,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            10, 
            "Scanning for expired jobs"
        ))
        
        # Get all active job IDs
        active_jobs = asyncio.run(job_status_manager.get_active_jobs())
        
        if not active_jobs:
            logger.info("No active jobs found for cleanup")
            result_data = {
                "success": True,
                "task_id": task_id,
                "job_id": job_id,
                "message": "No active jobs found for cleanup",
                "jobs_cleaned": 0,
                "total_jobs_scanned": 0,
                "completed_at": time.time()
            }
            
            asyncio.run(job_status_manager.set_job_status(job_id, "completed", {"success": True}))
            asyncio.run(job_status_manager.set_job_result(job_id, result_data))
            return result_data
        
        # Calculate cutoff time
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            30, 
            f"Processing {len(active_jobs)} jobs"
        ))
        
        jobs_cleaned = 0
        jobs_scanned = 0
        errors = []
        
        # Process jobs in batches
        for i in range(0, len(active_jobs), batch_size):
            batch = active_jobs[i:i + batch_size]
            
            for job_id_to_check in batch:
                try:
                    jobs_scanned += 1
                    
                    # Get job status
                    status_data = asyncio.run(job_status_manager.get_job_status(job_id_to_check))
                    
                    if status_data:
                        updated_at = status_data.get("updated_at", 0)
                        job_status = status_data.get("status", "unknown")
                        
                        # Check if job is expired
                        if updated_at < cutoff_time and job_status in ["completed", "failed", "cancelled"]:
                            # Delete job data
                            asyncio.run(job_status_manager.delete_job_data(job_id_to_check))
                            jobs_cleaned += 1
                            logger.debug(f"Cleaned expired job: {job_id_to_check}")
                    
                except Exception as e:
                    error_msg = f"Error processing job {job_id_to_check}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            # Update progress
            progress = 30 + int((i / len(active_jobs)) * 60)
            asyncio.run(job_status_manager.set_job_progress(
                job_id, 
                progress, 
                f"Processed {min(i + batch_size, len(active_jobs))}/{len(active_jobs)} jobs"
            ))
        
        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Job cleanup completed: {jobs_cleaned} jobs cleaned",
            "jobs_cleaned": jobs_cleaned,
            "total_jobs_scanned": jobs_scanned,
            "max_age_hours": max_age_hours,
            "batch_size": batch_size,
            "errors": errors,
            "error_count": len(errors),
            "completed_at": time.time()
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "jobs_cleaned": jobs_cleaned,
                "total_jobs_scanned": jobs_scanned,
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Job cleanup task completed"
        ))
        
        logger.info(f"Expired jobs cleanup task {task_id} completed: {jobs_cleaned}/{jobs_scanned} jobs cleaned")
        return result_data
        
    except Exception as e:
        logger.error(f"Expired jobs cleanup task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Job cleanup error: {str(e)}",
            "error": str(e),
            "jobs_cleaned": 0,
            "total_jobs_scanned": 0,
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
        
        return error_data


@celery_app.task(bind=True, name="app.workers.cleanup_worker.health_check_task")
def health_check_task(
    self,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Perform system health check.
    
    Args:
        metadata: Additional metadata
    
    Returns:
        Dict containing health check result
    """
    task_id = self.request.id
    job_id = f"health_check_{task_id}"
    
    logger.info(f"Starting health check task {task_id} for job {job_id}")
    
    try:
        # Set initial status
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "processing", 
            {
                "task_id": task_id,
                "started_at": time.time(),
                "metadata": metadata or {}
            }
        ))
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            20, 
            "Checking Redis connections"
        ))
        
        # Check Redis health
        redis_health = asyncio.run(redis_manager.health_check())
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            50, 
            "Checking disk space"
        ))
        
        # Check disk space
        temp_dir = settings.TEMP_DIR
        disk_usage = shutil.disk_usage(temp_dir)
        disk_free_gb = disk_usage.free / (1024 ** 3)
        disk_total_gb = disk_usage.total / (1024 ** 3)
        disk_used_percent = ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100
        
        # Update progress
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            80, 
            "Checking active jobs"
        ))
        
        # Check active jobs count
        active_jobs = asyncio.run(job_status_manager.get_active_jobs())
        active_jobs_count = len(active_jobs)
        
        # Determine overall health
        health_issues = []
        
        if not all(redis_health.values()):
            health_issues.append("Redis connection issues")
        
        if disk_free_gb < 1.0:  # Less than 1GB free
            health_issues.append(f"Low disk space: {disk_free_gb:.2f}GB free")
        
        if active_jobs_count > 1000:  # Too many active jobs
            health_issues.append(f"High job count: {active_jobs_count} active jobs")
        
        overall_health = "healthy" if not health_issues else "degraded"
        
        # Prepare result data
        result_data = {
            "success": True,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Health check completed: {overall_health}",
            "overall_health": overall_health,
            "health_issues": health_issues,
            "redis_health": redis_health,
            "disk_usage": {
                "free_gb": round(disk_free_gb, 2),
                "total_gb": round(disk_total_gb, 2),
                "used_percent": round(disk_used_percent, 2)
            },
            "active_jobs_count": active_jobs_count,
            "temp_directory": str(temp_dir),
            "completed_at": time.time()
        }
        
        # Set final status and result
        asyncio.run(job_status_manager.set_job_status(
            job_id, 
            "completed", 
            {
                "task_id": task_id,
                "completed_at": time.time(),
                "overall_health": overall_health,
                "health_issues_count": len(health_issues),
                "success": True
            }
        ))
        
        asyncio.run(job_status_manager.set_job_result(job_id, result_data))
        
        # Final progress update
        asyncio.run(job_status_manager.set_job_progress(
            job_id, 
            100, 
            "Health check completed"
        ))
        
        logger.info(f"Health check task {task_id} completed: {overall_health}")
        return result_data
        
    except Exception as e:
        logger.error(f"Health check task {task_id} failed for job {job_id}: {e}")
        
        error_data = {
            "success": False,
            "task_id": task_id,
            "job_id": job_id,
            "message": f"Health check error: {str(e)}",
            "error": str(e),
            "overall_health": "unhealthy",
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
        
        return error_data


# Utility functions to submit cleanup jobs
def submit_temp_files_cleanup(
    max_age_hours: int = 24,
    target_directory: Optional[str] = None,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit temp files cleanup job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    # Submit task to queue
    task = cleanup_temp_files_task.apply_async(
        args=[max_age_hours],
        kwargs={
            "target_directory": target_directory,
            "metadata": metadata
        },
        queue="cleanup"
    )
    
    job_id = f"cleanup_{task.id}"
    logger.info(f"Submitted temp files cleanup job {job_id} with task {task.id}")
    return job_id


def submit_expired_jobs_cleanup(
    max_age_hours: int = 24,
    batch_size: int = 100,
    metadata: Optional[Dict] = None
) -> str:
    """
    Submit expired jobs cleanup job to queue.
    
    Returns:
        job_id: Job ID for tracking
    """
    # Submit task to queue
    task = cleanup_expired_jobs_task.apply_async(
        args=[max_age_hours],
        kwargs={
            "batch_size": batch_size,
            "metadata": metadata
        },
        queue="cleanup"
    )
    
    job_id = f"job_cleanup_{task.id}"
    logger.info(f"Submitted expired jobs cleanup job {job_id} with task {task.id}")
    return job_id


# Scheduled task aliases for Celery Beat
cleanup_expired_jobs = cleanup_expired_jobs_task
cleanup_temp_files = cleanup_temp_files_task
health_check = health_check_task

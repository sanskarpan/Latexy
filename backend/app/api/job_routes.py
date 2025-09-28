"""
Job management API routes for Phase 8.
"""

import asyncio
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..core.redis import job_status_manager, redis_manager
from ..database.connection import get_db
from ..workers.latex_worker import submit_latex_compilation, submit_optimization_and_compilation
from ..workers.llm_worker import submit_resume_optimization, submit_job_description_analysis
from ..workers.email_worker import submit_notification_email, submit_completion_email
from ..workers.cleanup_worker import submit_temp_files_cleanup, submit_expired_jobs_cleanup

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Pydantic models for job management
class JobSubmissionRequest(BaseModel):
    job_type: str  # "latex_compilation", "llm_optimization", "combined"
    latex_content: Optional[str] = None
    job_description: Optional[str] = None
    optimization_level: str = "balanced"
    user_plan: str = "free"
    device_fingerprint: Optional[str] = None
    metadata: Optional[Dict] = None


class JobSubmissionResponse(BaseModel):
    success: bool
    job_id: str
    message: str
    estimated_time: Optional[int] = None  # seconds
    queue_position: Optional[int] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # "pending", "processing", "completed", "failed", "cancelled"
    progress: Optional[int] = None  # 0-100
    message: Optional[str] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    estimated_completion: Optional[float] = None
    metadata: Optional[Dict] = None


class JobResultResponse(BaseModel):
    job_id: str
    success: bool
    result: Optional[Dict] = None
    error: Optional[str] = None
    completed_at: Optional[float] = None


class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]
    total_count: int
    active_count: int
    completed_count: int
    failed_count: int


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.job_subscriptions: Dict[str, List[str]] = {}  # job_id -> [connection_ids]
    
    async def connect(self, websocket: WebSocket, connection_id: str):
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        logger.info(f"WebSocket connection established: {connection_id}")
    
    def disconnect(self, connection_id: str):
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        
        # Remove from job subscriptions
        for job_id, connections in self.job_subscriptions.items():
            if connection_id in connections:
                connections.remove(connection_id)
        
        logger.info(f"WebSocket connection closed: {connection_id}")
    
    def subscribe_to_job(self, connection_id: str, job_id: str):
        if job_id not in self.job_subscriptions:
            self.job_subscriptions[job_id] = []
        
        if connection_id not in self.job_subscriptions[job_id]:
            self.job_subscriptions[job_id].append(connection_id)
        
        logger.debug(f"Connection {connection_id} subscribed to job {job_id}")
    
    async def send_job_update(self, job_id: str, update_data: Dict):
        if job_id in self.job_subscriptions:
            disconnected_connections = []
            
            for connection_id in self.job_subscriptions[job_id]:
                if connection_id in self.active_connections:
                    try:
                        websocket = self.active_connections[connection_id]
                        await websocket.send_json({
                            "type": "job_update",
                            "job_id": job_id,
                            "data": update_data
                        })
                    except Exception as e:
                        logger.error(f"Error sending update to connection {connection_id}: {e}")
                        disconnected_connections.append(connection_id)
                else:
                    disconnected_connections.append(connection_id)
            
            # Clean up disconnected connections
            for connection_id in disconnected_connections:
                if connection_id in self.job_subscriptions[job_id]:
                    self.job_subscriptions[job_id].remove(connection_id)
    
    async def broadcast(self, message: Dict):
        disconnected_connections = []
        
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to connection {connection_id}: {e}")
                disconnected_connections.append(connection_id)
        
        # Clean up disconnected connections
        for connection_id in disconnected_connections:
            self.disconnect(connection_id)


# Global connection manager
manager = ConnectionManager()


# Job submission endpoints
@router.post("/submit", response_model=JobSubmissionResponse)
async def submit_job(
    request: JobSubmissionRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Submit a new job to the queue."""
    try:
        # Extract user information (in production, this would come from authentication)
        user_id = None  # TODO: Extract from JWT token
        ip_address = http_request.client.host if http_request.client else None
        
        # Validate request based on job type
        if request.job_type == "latex_compilation":
            if not request.latex_content:
                raise HTTPException(status_code=400, detail="LaTeX content is required for compilation jobs")
            
            job_id = submit_latex_compilation(
                latex_content=request.latex_content,
                user_id=user_id,
                user_plan=request.user_plan,
                device_fingerprint=request.device_fingerprint,
                metadata={
                    "ip_address": ip_address,
                    "submitted_via": "api",
                    **(request.metadata or {})
                }
            )
            
        elif request.job_type == "llm_optimization":
            if not request.latex_content or not request.job_description:
                raise HTTPException(
                    status_code=400, 
                    detail="LaTeX content and job description are required for optimization jobs"
                )
            
            job_id = submit_resume_optimization(
                latex_content=request.latex_content,
                job_description=request.job_description,
                user_id=user_id,
                user_plan=request.user_plan,
                optimization_level=request.optimization_level,
                metadata={
                    "ip_address": ip_address,
                    "submitted_via": "api",
                    **(request.metadata or {})
                }
            )
            
        elif request.job_type == "combined":
            if not request.latex_content or not request.job_description:
                raise HTTPException(
                    status_code=400, 
                    detail="LaTeX content and job description are required for combined jobs"
                )
            
            job_id = submit_optimization_and_compilation(
                latex_content=request.latex_content,
                job_description=request.job_description,
                user_id=user_id,
                user_plan=request.user_plan,
                device_fingerprint=request.device_fingerprint,
                optimization_level=request.optimization_level,
                metadata={
                    "ip_address": ip_address,
                    "submitted_via": "api",
                    **(request.metadata or {})
                }
            )
            
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported job type: {request.job_type}")
        
        # Estimate completion time based on job type and user plan
        estimated_times = {
            "latex_compilation": 30,  # 30 seconds
            "llm_optimization": 60,   # 1 minute
            "combined": 90            # 1.5 minutes
        }
        
        estimated_time = estimated_times.get(request.job_type, 60)
        if request.user_plan in ["pro", "byok"]:
            estimated_time = int(estimated_time * 0.7)  # 30% faster for premium users
        
        return JobSubmissionResponse(
            success=True,
            job_id=job_id,
            message=f"Job submitted successfully: {request.job_type}",
            estimated_time=estimated_time,
            queue_position=None  # TODO: Implement queue position tracking
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting job: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Job status and result endpoints
@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get job status."""
    try:
        status_data = await job_status_manager.get_job_status(job_id)
        progress_data = await job_status_manager.get_job_progress(job_id)
        
        if not status_data:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobStatusResponse(
            job_id=job_id,
            status=status_data.get("status", "unknown"),
            progress=progress_data.get("progress") if progress_data else None,
            message=progress_data.get("message") if progress_data else status_data.get("message"),
            created_at=status_data.get("started_at"),
            updated_at=status_data.get("updated_at"),
            metadata=status_data.get("metadata")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status for {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str):
    """Get job result."""
    try:
        result_data = await job_status_manager.get_job_result(job_id)
        
        if not result_data:
            raise HTTPException(status_code=404, detail="Job result not found")
        
        return JobResultResponse(
            job_id=job_id,
            success=result_data.get("success", False),
            result=result_data if result_data.get("success") else None,
            error=result_data.get("error") if not result_data.get("success") else None,
            completed_at=result_data.get("completed_at")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job result for {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a job."""
    try:
        # TODO: Implement job cancellation logic
        # For now, just mark as cancelled in Redis
        await job_status_manager.set_job_status(
            job_id, 
            "cancelled", 
            {"cancelled_at": asyncio.get_event_loop().time()}
        )
        
        # Notify WebSocket subscribers
        await manager.send_job_update(job_id, {
            "status": "cancelled",
            "message": "Job cancelled by user"
        })
        
        return {"success": True, "message": "Job cancelled successfully"}
        
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """List jobs with optional filtering."""
    try:
        # Get all active job IDs
        active_jobs = await job_status_manager.get_active_jobs()
        
        jobs = []
        total_count = len(active_jobs)
        status_counts = {"active": 0, "completed": 0, "failed": 0}
        
        # Apply pagination
        paginated_jobs = active_jobs[offset:offset + limit]
        
        for job_id in paginated_jobs:
            try:
                status_data = await job_status_manager.get_job_status(job_id)
                progress_data = await job_status_manager.get_job_progress(job_id)
                
                if status_data:
                    job_status = status_data.get("status", "unknown")
                    
                    # Apply status filter
                    if status and job_status != status:
                        continue
                    
                    # Count statuses
                    if job_status in ["pending", "processing"]:
                        status_counts["active"] += 1
                    elif job_status == "completed":
                        status_counts["completed"] += 1
                    elif job_status == "failed":
                        status_counts["failed"] += 1
                    
                    jobs.append(JobStatusResponse(
                        job_id=job_id,
                        status=job_status,
                        progress=progress_data.get("progress") if progress_data else None,
                        message=progress_data.get("message") if progress_data else status_data.get("message"),
                        created_at=status_data.get("started_at"),
                        updated_at=status_data.get("updated_at"),
                        metadata=status_data.get("metadata")
                    ))
                    
            except Exception as e:
                logger.error(f"Error processing job {job_id}: {e}")
                continue
        
        return JobListResponse(
            jobs=jobs,
            total_count=total_count,
            active_count=status_counts["active"],
            completed_count=status_counts["completed"],
            failed_count=status_counts["failed"]
        )
        
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# WebSocket endpoint for real-time updates
@router.websocket("/ws/{connection_id}")
async def websocket_endpoint(websocket: WebSocket, connection_id: str):
    """WebSocket endpoint for real-time job updates."""
    await manager.connect(websocket, connection_id)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            
            if data.get("type") == "subscribe":
                job_id = data.get("job_id")
                if job_id:
                    manager.subscribe_to_job(connection_id, job_id)
                    await websocket.send_json({
                        "type": "subscription_confirmed",
                        "job_id": job_id
                    })
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"WebSocket error for connection {connection_id}: {e}")
        manager.disconnect(connection_id)


# System health and monitoring endpoints
@router.get("/system/health")
async def system_health():
    """Get system health status."""
    try:
        # Initialize Redis if not already done
        if not redis_manager.redis_client:
            await redis_manager.init_redis()
        
        # Check Redis health
        redis_health = await redis_manager.health_check()
        
        # Get active jobs count (with fallback)
        try:
            active_jobs = await job_status_manager.get_active_jobs()
            active_jobs_count = len(active_jobs)
        except Exception:
            active_jobs_count = 0
        
        # Determine overall health
        overall_health = "healthy" if all(redis_health.values()) else "degraded"
        
        return {
            "status": overall_health,
            "redis_health": redis_health,
            "active_jobs_count": active_jobs_count,
            "websocket_connections": len(manager.active_connections),
            "job_subscriptions": len(manager.job_subscriptions),
            "timestamp": asyncio.get_event_loop().time()
        }
        
    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "redis_available": False,
            "timestamp": asyncio.get_event_loop().time()
        }


@router.post("/system/cleanup")
async def trigger_cleanup(
    cleanup_type: str = "temp_files",
    max_age_hours: int = 24
):
    """Trigger system cleanup tasks."""
    try:
        if cleanup_type == "temp_files":
            job_id = submit_temp_files_cleanup(max_age_hours=max_age_hours)
        elif cleanup_type == "expired_jobs":
            job_id = submit_expired_jobs_cleanup(max_age_hours=max_age_hours)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported cleanup type: {cleanup_type}")
        
        return {
            "success": True,
            "message": f"Cleanup task submitted: {cleanup_type}",
            "job_id": job_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering cleanup: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

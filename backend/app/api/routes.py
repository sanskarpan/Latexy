"""
API routes for the application.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..models.schemas import CompilationResponse, HealthResponse, LogsResponse
from ..models.llm_schemas import OptimizationRequest, OptimizationResponse
from ..services.latex_compiler import latex_compiler
from ..services.latex_service import latex_service
from ..services.llm_service import llm_service
from ..services.trial_service import trial_service
from ..services.payment_service import payment_service
from ..utils.file_utils import validate_file_upload, validate_job_id, get_job_files

logger = get_logger(__name__)

router = APIRouter()

# Include job management routes
from .job_routes import router as job_router
router.include_router(job_router)

# Include ATS scoring routes
from .ats_routes import router as ats_router
router.include_router(ats_router)

# Include BYOK routes
from .byok_routes import router as byok_router
router.include_router(byok_router)

# Include Analytics routes
from .analytics_routes import router as analytics_router
router.include_router(analytics_router)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    latex_available = latex_compiler.is_available()
    llm_available = llm_service.is_available()
    
    # Consider service healthy if LaTeX is available (LLM is optional)
    status = "healthy" if latex_available else "degraded"
    
    return HealthResponse(
        status=status,
        version=settings.APP_VERSION,
        latex_available=latex_available
    )


@router.post("/compile", response_model=CompilationResponse)
async def compile_latex_endpoint(
    latex_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """Compile LaTeX content to PDF."""
    
    try:
        # Get LaTeX content from either form data or file upload
        if file:
            validate_file_upload(file)
            content = await file.read()
            latex_content = content.decode('utf-8')
            
        elif latex_content:
            pass  # Use provided content
        else:
            raise HTTPException(
                status_code=400, 
                detail="Either latex_content or file must be provided"
            )
        
        # Validate LaTeX content
        if not latex_service.validate_latex_content(latex_content):
            raise HTTPException(
                status_code=400, 
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Compile LaTeX
        result = await latex_service.compile_latex(latex_content)
        
        # Schedule cleanup after retention period only if compilation was successful
        if result.success:
            job_dir = settings.TEMP_DIR / result.job_id
            asyncio.create_task(latex_service.cleanup_temp_files_delayed(job_dir, settings.PDF_RETENTION_TIME))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/download/{job_id}")
async def download_pdf(job_id: str):
    """Download compiled PDF."""
    
    validate_job_id(job_id)
    
    job_dir, pdf_file, _ = get_job_files(job_id)
    
    if not pdf_file.exists():
        raise HTTPException(
            status_code=404, 
            detail="PDF not found. Job may have failed or files may have been cleaned up."
        )
    
    try:
        # Return PDF file
        return FileResponse(
            path=pdf_file,
            media_type='application/pdf',
            filename=f"resume_{job_id[:8]}.pdf"
        )
        
    except Exception as e:
        logger.error(f"Error serving PDF for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error serving PDF file")


@router.get("/logs/{job_id}", response_model=LogsResponse)
async def get_compilation_logs(job_id: str):
    """Get compilation logs for debugging."""
    
    validate_job_id(job_id)
    
    _, _, log_file = get_job_files(job_id)
    
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        log_content = log_file.read_text(encoding='utf-8', errors='ignore')
        return LogsResponse(job_id=job_id, logs=log_content)
    except Exception as e:
        logger.error(f"Error reading logs for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading log file")


@router.post("/optimize", response_model=OptimizationResponse)
async def optimize_resume(request: OptimizationRequest):
    """Optimize resume using LLM for better ATS compatibility."""
    
    if not llm_service.is_available():
        raise HTTPException(
            status_code=503,
            detail="LLM service is not available. Please configure OpenAI API key."
        )
    
    try:
        # Validate LaTeX content
        if not latex_service.validate_latex_content(request.latex_content):
            raise HTTPException(
                status_code=400,
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Validate job description
        if not request.job_description.strip():
            raise HTTPException(
                status_code=400,
                detail="Job description cannot be empty"
            )
        
        # Perform optimization
        result = await llm_service.optimize_resume(request)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in optimize endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/optimize-and-compile", response_model=dict)
async def optimize_and_compile_resume(request: OptimizationRequest):
    """Optimize resume and compile to PDF in one step."""
    
    try:
        # First optimize the resume
        optimization_result = await optimize_resume(request)
        
        if not optimization_result.success:
            return {
                "optimization": optimization_result,
                "compilation": None,
                "success": False
            }
        
        # Then compile the optimized LaTeX
        compilation_result = await latex_service.compile_latex(optimization_result.optimized_latex)
        
        # Schedule cleanup after retention period only if compilation was successful
        if compilation_result.success:
            job_dir = settings.TEMP_DIR / compilation_result.job_id
            asyncio.create_task(latex_service.cleanup_temp_files_delayed(job_dir, settings.PDF_RETENTION_TIME))
        
        return {
            "optimization": optimization_result,
            "compilation": compilation_result,
            "success": optimization_result.success and compilation_result.success
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in optimize-and-compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Trial System Endpoints

class TrialStatusResponse(BaseModel):
    usageCount: int
    remainingUses: int
    blocked: bool
    lastUsed: Optional[str]
    canUse: bool

class TrackUsageRequest(BaseModel):
    deviceFingerprint: str
    sessionId: Optional[str] = None
    action: str
    resourceType: Optional[str] = None
    userAgent: Optional[str] = None
    metadata: Optional[dict] = None

class TrackUsageResponse(BaseModel):
    success: bool
    usageCount: Optional[int] = None
    remainingUses: Optional[int] = None
    blocked: Optional[bool] = None
    error: Optional[str] = None
    waitTime: Optional[float] = None


@router.get("/public/trial-status", response_model=TrialStatusResponse)
async def get_trial_status(
    fingerprint: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get trial status for a device fingerprint."""
    try:
        ip_address = request.client.host if request.client else None
        status = await trial_service.get_trial_status(db, fingerprint, ip_address)
        
        return TrialStatusResponse(
            usageCount=status["usageCount"],
            remainingUses=status["remainingUses"],
            blocked=status["blocked"],
            lastUsed=status["lastUsed"],
            canUse=status["canUse"]
        )
    except Exception as e:
        logger.error(f"Error getting trial status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/public/track-usage", response_model=TrackUsageResponse)
async def track_usage(
    request_data: TrackUsageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Track usage for anonymous users."""
    try:
        ip_address = request.client.host if request.client else None
        
        result = await trial_service.track_usage(
            db=db,
            device_fingerprint=request_data.deviceFingerprint,
            action=request_data.action,
            ip_address=ip_address,
            user_agent=request_data.userAgent,
            session_id=request_data.sessionId,
            resource_type=request_data.resourceType,
            metadata=request_data.metadata
        )
        
        return TrackUsageResponse(
            success=result["success"],
            usageCount=result.get("usageCount"),
            remainingUses=result.get("remainingUses"),
            blocked=result.get("blocked"),
            error=result.get("error"),
            waitTime=result.get("waitTime")
        )
    except Exception as e:
        logger.error(f"Error tracking usage: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/public/compile", response_model=CompilationResponse)
async def compile_latex_anonymous(
    latex_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    device_fingerprint: str = Form(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Compile LaTeX content for anonymous users with trial limits."""
    
    try:
        ip_address = request.client.host if request.client else None
        
        # Check trial limits first
        rate_check = await trial_service.check_rate_limits(db, device_fingerprint, ip_address)
        if not rate_check["allowed"]:
            error_messages = {
                "trial_limit_exceeded": "Free trial limit exceeded. Please sign up to continue.",
                "cooldown": f"Please wait {int(rate_check.get('waitTime', 0))} seconds before trying again.",
                "blocked": "Device blocked due to abuse. Please contact support.",
                "daily_limit_exceeded": "Daily request limit exceeded. Please try again tomorrow."
            }
            raise HTTPException(
                status_code=429, 
                detail=error_messages.get(rate_check["reason"], "Rate limit exceeded")
            )
        
        # Get LaTeX content from either form data or file upload
        if file:
            validate_file_upload(file)
            content = await file.read()
            latex_content = content.decode('utf-8')
            
        elif latex_content:
            pass  # Use provided content
        else:
            raise HTTPException(
                status_code=400, 
                detail="Either latex_content or file must be provided"
            )
        
        # Validate LaTeX content
        if not latex_service.validate_latex_content(latex_content):
            raise HTTPException(
                status_code=400, 
                detail="Invalid LaTeX content. Must contain \\documentclass, \\begin{document}, and \\end{document}"
            )
        
        # Track usage
        await trial_service.track_usage(
            db=db,
            device_fingerprint=device_fingerprint,
            action="compile",
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent") if request else None,
            resource_type="resume"
        )
        
        # Compile LaTeX
        result = await latex_service.compile_latex(latex_content)
        
        # Schedule cleanup after retention period only if compilation was successful
        if result.success:
            job_dir = settings.TEMP_DIR / result.job_id
            asyncio.create_task(latex_service.cleanup_temp_files_delayed(job_dir, settings.PDF_RETENTION_TIME))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in anonymous compile endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Payment & Subscription Endpoints

class SubscriptionPlanResponse(BaseModel):
    plans: dict

class CreateSubscriptionRequest(BaseModel):
    planId: str
    customerEmail: str
    customerName: str

class CreateSubscriptionResponse(BaseModel):
    success: bool
    subscriptionId: Optional[str] = None
    shortUrl: Optional[str] = None
    customerId: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None

class UserSubscriptionResponse(BaseModel):
    userId: str
    planId: str
    planName: str
    status: str
    features: dict
    subscriptionId: Optional[str] = None
    currentPeriodEnd: Optional[str] = None

class CancelSubscriptionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


@router.get("/subscription/plans", response_model=SubscriptionPlanResponse)
async def get_subscription_plans():
    """Get available subscription plans."""
    try:
        plans = await payment_service.get_subscription_plans()
        return SubscriptionPlanResponse(plans=plans)
    except Exception as e:
        logger.error(f"Error getting subscription plans: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/subscription/create", response_model=CreateSubscriptionResponse)
async def create_subscription(
    request_data: CreateSubscriptionRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a new subscription."""
    try:
        if not payment_service.is_available():
            raise HTTPException(
                status_code=503,
                detail="Payment service is not available"
            )

        # For demo purposes, we'll use a dummy user ID
        # In production, this would come from authentication
        user_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"  # This should come from JWT token

        result = await payment_service.create_subscription(
            db=db,
            user_id=user_id,
            plan_id=request_data.planId,
            customer_email=request_data.customerEmail,
            customer_name=request_data.customerName
        )

        return CreateSubscriptionResponse(
            success=result["success"],
            subscriptionId=result.get("subscription_id"),
            shortUrl=result.get("short_url"),
            customerId=result.get("customer_id"),
            error=result.get("error"),
            message=result.get("message")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/subscription/current", response_model=UserSubscriptionResponse)
async def get_current_subscription(
    db: AsyncSession = Depends(get_db)
):
    """Get current user's subscription."""
    try:
        # For demo purposes, we'll use a dummy user ID
        # In production, this would come from authentication
        user_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"  # This should come from JWT token

        subscription = await payment_service.get_user_subscription(db, user_id)
        
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")

        return UserSubscriptionResponse(
            userId=subscription["user_id"],
            planId=subscription["plan_id"],
            planName=subscription["plan_name"],
            status=subscription["status"],
            features=subscription["features"],
            subscriptionId=subscription["subscription_id"],
            currentPeriodEnd=subscription["current_period_end"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/subscription/cancel", response_model=CancelSubscriptionResponse)
async def cancel_subscription(
    db: AsyncSession = Depends(get_db)
):
    """Cancel current user's subscription."""
    try:
        # For demo purposes, we'll use a dummy user ID
        # In production, this would come from authentication
        user_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"  # This should come from JWT token

        result = await payment_service.cancel_subscription(db, user_id)

        return CancelSubscriptionResponse(
            success=result["success"],
            message=result.get("message"),
            error=result.get("error")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/billing/webhook")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Razorpay webhook events."""
    try:
        payload = await request.body()
        signature = request.headers.get("X-Razorpay-Signature", "")

        result = await payment_service.handle_webhook(db, payload, signature)

        if result["success"]:
            return {"status": "ok"}
        else:
            logger.error(f"Webhook processing failed: {result.get('error')}")
            raise HTTPException(status_code=400, detail="Webhook processing failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


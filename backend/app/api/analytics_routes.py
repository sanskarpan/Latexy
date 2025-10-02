"""
Analytics API routes for tracking and retrieving usage data.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database.connection import get_db
from app.services.analytics_service import analytics_service
from app.middleware.auth_middleware import get_user_id_required, get_user_id_optional, require_admin
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Pydantic models for request/response
class EventTrackingRequest(BaseModel):
    event_type: str = Field(..., description="Type of event to track")
    user_id: Optional[UUID] = Field(None, description="User ID (if authenticated)")
    device_fingerprint: Optional[str] = Field(None, description="Device fingerprint for anonymous users")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional event metadata")

class UserAnalyticsResponse(BaseModel):
    user_id: str
    period_days: int
    total_compilations: int
    successful_compilations: int
    success_rate: float
    total_optimizations: int
    avg_compilation_time: float
    feature_usage: Dict[str, int]
    daily_activity: Dict[str, int]
    most_active_day: Optional[str]

class SystemAnalyticsResponse(BaseModel):
    period_days: int
    total_users: int
    new_users: int
    total_compilations: int
    successful_compilations: int
    success_rate: float
    total_optimizations: int
    active_subscriptions: int
    total_revenue_inr: float
    trial_users: int
    conversion_rate: float
    real_time_metrics: Dict[str, Any]

class ConversionFunnelResponse(BaseModel):
    period_days: int
    funnel_steps: Dict[str, int]
    conversion_rates: Dict[str, float]

@router.post("/track", status_code=status.HTTP_201_CREATED)
async def track_event(
    request: EventTrackingRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Track a user event for analytics."""
    try:
        # Get IP address and user agent from request
        ip_address = http_request.client.host if http_request.client else None
        user_agent = http_request.headers.get("user-agent")
        
        success = await analytics_service.track_event(
            db=db,
            event_type=request.event_type,
            user_id=request.user_id,
            device_fingerprint=request.device_fingerprint,
            metadata=request.metadata,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if success:
            return {"message": "Event tracked successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to track event"
            )
            
    except Exception as e:
        logger.error(f"Error tracking event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/user/{user_id}", response_model=UserAnalyticsResponse)
async def get_user_analytics(
    user_id: UUID,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get analytics data for a specific user."""
    try:
        # TODO: Add authentication check to ensure user can only access their own data
        # or is an admin
        
        analytics_data = await analytics_service.get_user_analytics(
            db=db,
            user_id=user_id,
            days=days
        )
        
        if not analytics_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User analytics not found"
            )
        
        return UserAnalyticsResponse(**analytics_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/system", response_model=SystemAnalyticsResponse)
async def get_system_analytics(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """Get system-wide analytics. Requires admin access."""
    try:
        # TODO: Add admin authentication check
        
        analytics_data = await analytics_service.get_system_analytics(
            db=db,
            days=days
        )
        
        return SystemAnalyticsResponse(**analytics_data)
        
    except Exception as e:
        logger.error(f"Error getting system analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/conversion-funnel", response_model=ConversionFunnelResponse)
async def get_conversion_funnel(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get conversion funnel analytics. Requires admin access."""
    try:
        # TODO: Add admin authentication check
        
        funnel_data = await analytics_service.get_conversion_funnel(
            db=db,
            days=days
        )
        
        return ConversionFunnelResponse(**funnel_data)
        
    except Exception as e:
        logger.error(f"Error getting conversion funnel: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/compilation")
async def track_compilation(
    compilation_id: str,
    status: str,
    user_id: Optional[UUID] = None,
    device_fingerprint: Optional[str] = None,
    compilation_time: Optional[float] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Track compilation-specific events."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        
        await analytics_service.track_compilation_event(
            db=db,
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            compilation_id=compilation_id,
            status=status,
            compilation_time=compilation_time,
            ip_address=ip_address
        )
        
        return {"message": "Compilation event tracked successfully"}
        
    except Exception as e:
        logger.error(f"Error tracking compilation event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/optimization")
async def track_optimization(
    optimization_id: str,
    provider: str,
    model: str,
    user_id: Optional[UUID] = None,
    tokens_used: Optional[int] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Track optimization-specific events."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        
        await analytics_service.track_optimization_event(
            db=db,
            user_id=user_id,
            optimization_id=optimization_id,
            provider=provider,
            model=model,
            tokens_used=tokens_used,
            ip_address=ip_address
        )
        
        return {"message": "Optimization event tracked successfully"}
        
    except Exception as e:
        logger.error(f"Error tracking optimization event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/page-view")
async def track_page_view(
    page: str,
    user_id: Optional[UUID] = None,
    device_fingerprint: Optional[str] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Track page view events."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        user_agent = http_request.headers.get("user-agent") if http_request else None
        
        await analytics_service.track_user_journey_event(
            db=db,
            event_type="page_view",
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            page=page,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return {"message": "Page view tracked successfully"}
        
    except Exception as e:
        logger.error(f"Error tracking page view: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/feature-usage")
async def track_feature_usage(
    feature: str,
    user_id: Optional[UUID] = None,
    device_fingerprint: Optional[str] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Track feature usage events."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        user_agent = http_request.headers.get("user-agent") if http_request else None
        
        await analytics_service.track_user_journey_event(
            db=db,
            event_type="feature_usage",
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            feature=feature,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return {"message": "Feature usage tracked successfully"}
        
    except Exception as e:
        logger.error(f"Error tracking feature usage: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/dashboard")
async def get_analytics_dashboard(
    days: int = 7,
    db: AsyncSession = Depends(get_db)
):
    """Get comprehensive analytics dashboard data."""
    try:
        # TODO: Add admin authentication check
        
        # Get all analytics data
        system_analytics = await analytics_service.get_system_analytics(db, days)
        conversion_funnel = await analytics_service.get_conversion_funnel(db, days)
        
        return {
            "system_analytics": system_analytics,
            "conversion_funnel": conversion_funnel,
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting analytics dashboard: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


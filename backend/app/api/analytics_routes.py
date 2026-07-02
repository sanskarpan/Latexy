"""
Analytics API routes for tracking and retrieving usage data.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..middleware.auth_middleware import (
    get_current_user_optional,
    get_current_user_required,
    require_admin,
)
from ..services.analytics_service import analytics_service

logger = get_logger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])

# Limits for untrusted, client-supplied event metadata (SEC/DoS guard).
_MAX_METADATA_BYTES = 4096
_MAX_METADATA_DEPTH = 5


def _payload_depth(obj: Any, depth: int = 1) -> int:
    """Return the maximum nesting depth of a JSON-like structure."""
    if isinstance(obj, dict):
        if not obj:
            return depth
        return max(_payload_depth(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return depth
        return max(_payload_depth(v, depth + 1) for v in obj)
    return depth


# Pydantic models for request/response
class EventTrackingRequest(BaseModel):
    event_type: str = Field(..., description="Type of event to track")
    device_fingerprint: Optional[str] = Field(None, description="Device fingerprint for anonymous users")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional event metadata")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Reject oversized / deeply-nested metadata to prevent storage DoS."""
        if value is None:
            return value
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError):
            raise ValueError("metadata must be JSON-serializable")
        if len(serialized.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise ValueError(f"metadata exceeds maximum allowed size of {_MAX_METADATA_BYTES} bytes")
        if _payload_depth(value) > _MAX_METADATA_DEPTH:
            raise ValueError(f"metadata nesting exceeds maximum depth of {_MAX_METADATA_DEPTH}")
        return value

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

class UserAnalyticsTimeseriesPoint(BaseModel):
    date: str
    events: int
    compile_events: int
    optimize_events: int
    feature_events: int

class CompilationTimeseriesPoint(BaseModel):
    date: str
    total: int
    completed: int
    failed: int
    cancelled: int
    avg_latency: float

class OptimizationTimeseriesPoint(BaseModel):
    date: str
    total: int
    avg_tokens: float
    avg_ats_score: float

class FeatureSeriesPoint(BaseModel):
    feature: str
    count: int
    last_used_at: Optional[str]

class UserAnalyticsTimeseriesResponse(BaseModel):
    user_id: str
    period_days: int
    activity_series: List[UserAnalyticsTimeseriesPoint]
    compilation_series: List[CompilationTimeseriesPoint]
    optimization_series: List[OptimizationTimeseriesPoint]
    feature_series: List[FeatureSeriesPoint]
    status_distribution: Dict[str, int]

@router.post("/track", status_code=status.HTTP_201_CREATED)
async def track_event(
    request: EventTrackingRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Track a user event for analytics.

    The attributed user is derived from the authenticated session; any
    client-supplied user_id is ignored to prevent analytics spoofing.
    """
    try:
        # Get IP address and user agent from request
        ip_address = http_request.client.host if http_request.client else None
        user_agent = http_request.headers.get("user-agent")

        success = await analytics_service.track_event(
            db=db,
            event_type=request.event_type,
            user_id=user_id,
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

@router.get("/me", response_model=UserAnalyticsResponse)
async def get_my_analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get analytics data for the current authenticated user."""
    try:
        # user_id is an opaque auth id (UUID(as_uuid=False) column) — pass as-is.
        analytics_data = await analytics_service.get_user_analytics(
            db=db,
            user_id=user_id,
            days=days
        )

        if not analytics_data:
            return {
                "user_id": user_id,
                "period_days": days,
                "total_compilations": 0,
                "successful_compilations": 0,
                "success_rate": 0,
                "total_optimizations": 0,
                "avg_compilation_time": 0,
                "feature_usage": {},
                "daily_activity": {},
                "most_active_day": None
            }

        return UserAnalyticsResponse(**analytics_data)

    except Exception as e:
        logger.error(f"Error getting user analytics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/me/timeseries", response_model=UserAnalyticsTimeseriesResponse)
async def get_my_analytics_timeseries(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required)
):
    """Get richer timeseries analytics for the current authenticated user."""
    try:
        timeseries = await analytics_service.get_user_analytics_timeseries(
            db=db,
            user_id=user_id,
            days=days
        )

        if not timeseries:
            return {
                "user_id": user_id,
                "period_days": days,
                "activity_series": [],
                "compilation_series": [],
                "optimization_series": [],
                "feature_series": [],
                "status_distribution": {
                    "completed": 0,
                    "processing": 0,
                    "queued": 0,
                    "failed": 0,
                    "cancelled": 0,
                },
            }

        return UserAnalyticsTimeseriesResponse(**timeseries)
    except Exception as e:
        logger.error(f"Error getting user analytics timeseries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/user/{user_id}", response_model=UserAnalyticsResponse)
async def get_user_analytics(
    user_id: UUID,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: str = Depends(require_admin)
):
    """Get analytics data for a specific user."""
    try:
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
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: str = Depends(require_admin)
):
    """Get system-wide analytics. Requires admin access."""
    try:
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
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: str = Depends(require_admin)
):
    """Get conversion funnel analytics. Requires admin access."""
    try:
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

@router.post("/track/compilation", status_code=status.HTTP_201_CREATED)
async def track_compilation(
    compilation_id: str,
    compilation_status: str = Query(..., alias="status"),
    device_fingerprint: Optional[str] = None,
    compilation_time: Optional[float] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Track compilation-specific events. Attribution comes from the session."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None

        tracked = await analytics_service.track_compilation_event(
            db=db,
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            compilation_id=compilation_id,
            status=compilation_status,
            compilation_time=compilation_time,
            ip_address=ip_address
        )

        if not tracked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to track compilation event"
            )

        return {"message": "Compilation event tracked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking compilation event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/optimization", status_code=status.HTTP_201_CREATED)
async def track_optimization(
    optimization_id: str,
    provider: str,
    model: str,
    tokens_used: Optional[int] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Track optimization-specific events. Attribution comes from the session."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None

        tracked = await analytics_service.track_optimization_event(
            db=db,
            user_id=user_id,
            optimization_id=optimization_id,
            provider=provider,
            model=model,
            tokens_used=tokens_used,
            ip_address=ip_address
        )

        if not tracked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to track optimization event"
            )

        return {"message": "Optimization event tracked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking optimization event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/page-view", status_code=status.HTTP_201_CREATED)
async def track_page_view(
    page: str,
    device_fingerprint: Optional[str] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Track page view events. Attribution comes from the session."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        user_agent = http_request.headers.get("user-agent") if http_request else None

        tracked = await analytics_service.track_user_journey_event(
            db=db,
            event_type="page_view",
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            page=page,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if not tracked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to track page view"
            )

        return {"message": "Page view tracked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking page view: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.post("/track/feature-usage", status_code=status.HTTP_201_CREATED)
async def track_feature_usage(
    feature: str,
    device_fingerprint: Optional[str] = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_optional),
):
    """Track feature usage events. Attribution comes from the session."""
    try:
        ip_address = http_request.client.host if http_request and http_request.client else None
        user_agent = http_request.headers.get("user-agent") if http_request else None

        tracked = await analytics_service.track_user_journey_event(
            db=db,
            event_type="feature_usage",
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            feature=feature,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if not tracked:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to track feature usage"
            )

        return {"message": "Feature usage tracked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracking feature usage: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/dashboard")
async def get_analytics_dashboard(
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin_user: str = Depends(require_admin)
):
    """Get comprehensive analytics dashboard data."""
    try:
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

"""
Analytics Service for tracking user behavior and system metrics.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import UUID
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.database.models import (
    User, DeviceTrial, Resume, Compilation, Optimization, 
    UsageAnalytics, Subscription, Payment
)
from app.database.connection import get_db
from app.core.redis import redis_manager

logger = logging.getLogger(__name__)

class AnalyticsService:
    """Service for collecting and analyzing usage data."""
    
    def __init__(self):
        self.redis_key_prefix = "analytics:"
        
    async def track_event(
        self,
        db: AsyncSession,
        event_type: str,
        user_id: Optional[UUID] = None,
        device_fingerprint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Track a user event for analytics."""
        try:
            analytics_record = UsageAnalytics(
                user_id=user_id,
                device_fingerprint=device_fingerprint,
                action=event_type,
                resource_type=metadata.get('resource_type') if metadata else None,
                event_metadata=metadata or {},
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.add(analytics_record)
            await db.commit()
            
            # Also cache in Redis for real-time analytics
            await self._cache_event(event_type, user_id, device_fingerprint, metadata)
            
            logger.info(f"Tracked event: {event_type} for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error tracking event {event_type}: {e}")
            await db.rollback()
            return False
    
    async def _cache_event(
        self,
        event_type: str,
        user_id: Optional[UUID],
        device_fingerprint: Optional[str],
        metadata: Optional[Dict[str, Any]]
    ):
        """Cache event in Redis for real-time analytics."""
        try:
            if not redis_manager.redis_client:
                return
                
            # Daily event counter
            today = datetime.now().strftime("%Y-%m-%d")
            daily_key = f"{self.redis_key_prefix}daily:{today}:{event_type}"
            await redis_manager.redis_client.incr(daily_key)
            await redis_manager.redis_client.expire(daily_key, 86400 * 7)  # 7 days
            
            # Hourly event counter
            hour = datetime.now().strftime("%Y-%m-%d:%H")
            hourly_key = f"{self.redis_key_prefix}hourly:{hour}:{event_type}"
            await redis_manager.redis_client.incr(hourly_key)
            await redis_manager.redis_client.expire(hourly_key, 86400)  # 24 hours
            
            # User-specific events (if user is logged in)
            if user_id:
                user_key = f"{self.redis_key_prefix}user:{user_id}:{event_type}"
                await redis_manager.redis_client.incr(user_key)
                await redis_manager.redis_client.expire(user_key, 86400 * 30)  # 30 days
                
        except Exception as e:
            logger.error(f"Error caching event: {e}")
    
    async def get_user_analytics(
        self,
        db: AsyncSession,
        user_id: UUID,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get analytics data for a specific user."""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Get user's compilations
            compilations_query = select(Compilation).where(
                and_(
                    Compilation.user_id == user_id,
                    Compilation.created_at >= start_date
                )
            )
            compilations_result = await db.execute(compilations_query)
            compilations = compilations_result.scalars().all()
            
            # Get user's optimizations
            optimizations_query = select(Optimization).where(
                and_(
                    Optimization.user_id == user_id,
                    Optimization.created_at >= start_date
                )
            )
            optimizations_result = await db.execute(optimizations_query)
            optimizations = optimizations_result.scalars().all()
            
            # Get user's analytics events
            analytics_query = select(UsageAnalytics).where(
                and_(
                    UsageAnalytics.user_id == user_id,
                    UsageAnalytics.created_at >= start_date
                )
            )
            analytics_result = await db.execute(analytics_query)
            analytics_events = analytics_result.scalars().all()
            
            # Calculate metrics
            total_compilations = len(compilations)
            successful_compilations = len([c for c in compilations if c.status == 'completed'])
            total_optimizations = len(optimizations)
            
            # Average compilation time
            compilation_times = [c.compilation_time for c in compilations if c.compilation_time]
            avg_compilation_time = sum(compilation_times) / len(compilation_times) if compilation_times else 0
            
            # Most used features
            feature_usage = {}
            for event in analytics_events:
                action = event.action
                feature_usage[action] = feature_usage.get(action, 0) + 1
            
            # Daily activity
            daily_activity = {}
            for event in analytics_events:
                day = event.created_at.strftime("%Y-%m-%d")
                daily_activity[day] = daily_activity.get(day, 0) + 1
            
            return {
                "user_id": str(user_id),
                "period_days": days,
                "total_compilations": total_compilations,
                "successful_compilations": successful_compilations,
                "success_rate": (successful_compilations / total_compilations * 100) if total_compilations > 0 else 0,
                "total_optimizations": total_optimizations,
                "avg_compilation_time": round(avg_compilation_time, 2),
                "feature_usage": feature_usage,
                "daily_activity": daily_activity,
                "most_active_day": max(daily_activity, key=daily_activity.get) if daily_activity else None
            }
            
        except Exception as e:
            logger.error(f"Error getting user analytics: {e}")
            return {}
    
    async def get_system_analytics(
        self,
        db: AsyncSession,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get system-wide analytics."""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Total users
            users_query = select(func.count(User.id))
            users_result = await db.execute(users_query)
            total_users = users_result.scalar()
            
            # New users in period
            new_users_query = select(func.count(User.id)).where(
                User.created_at >= start_date
            )
            new_users_result = await db.execute(new_users_query)
            new_users = new_users_result.scalar()
            
            # Total compilations
            compilations_query = select(func.count(Compilation.id)).where(
                Compilation.created_at >= start_date
            )
            compilations_result = await db.execute(compilations_query)
            total_compilations = compilations_result.scalar()
            
            # Successful compilations
            successful_query = select(func.count(Compilation.id)).where(
                and_(
                    Compilation.created_at >= start_date,
                    Compilation.status == 'completed'
                )
            )
            successful_result = await db.execute(successful_query)
            successful_compilations = successful_result.scalar()
            
            # Total optimizations
            optimizations_query = select(func.count(Optimization.id)).where(
                Optimization.created_at >= start_date
            )
            optimizations_result = await db.execute(optimizations_query)
            total_optimizations = optimizations_result.scalar()
            
            # Active subscriptions
            active_subs_query = select(func.count(Subscription.id)).where(
                Subscription.status == 'active'
            )
            active_subs_result = await db.execute(active_subs_query)
            active_subscriptions = active_subs_result.scalar()
            
            # Revenue (last 30 days)
            revenue_start = datetime.now() - timedelta(days=30)
            revenue_query = select(func.sum(Payment.amount)).where(
                and_(
                    Payment.created_at >= revenue_start,
                    Payment.status == 'captured'
                )
            )
            revenue_result = await db.execute(revenue_query)
            total_revenue = revenue_result.scalar() or 0
            
            # Trial conversions
            trial_users_query = select(func.count(DeviceTrial.id)).where(
                DeviceTrial.created_at >= start_date
            )
            trial_users_result = await db.execute(trial_users_query)
            trial_users = trial_users_result.scalar()
            
            # Get real-time metrics from Redis
            real_time_metrics = await self._get_real_time_metrics()
            
            return {
                "period_days": days,
                "total_users": total_users,
                "new_users": new_users,
                "total_compilations": total_compilations,
                "successful_compilations": successful_compilations,
                "success_rate": (successful_compilations / total_compilations * 100) if total_compilations > 0 else 0,
                "total_optimizations": total_optimizations,
                "active_subscriptions": active_subscriptions,
                "total_revenue_inr": total_revenue / 100,  # Convert from paise to rupees
                "trial_users": trial_users,
                "conversion_rate": (new_users / trial_users * 100) if trial_users > 0 else 0,
                "real_time_metrics": real_time_metrics
            }
            
        except Exception as e:
            logger.error(f"Error getting system analytics: {e}")
            return {}
    
    async def _get_real_time_metrics(self) -> Dict[str, Any]:
        """Get real-time metrics from Redis."""
        try:
            if not redis_manager.redis_client:
                return {}
                
            today = datetime.now().strftime("%Y-%m-%d")
            hour = datetime.now().strftime("%Y-%m-%d:%H")
            
            # Get today's events
            daily_keys = [
                f"{self.redis_key_prefix}daily:{today}:compile",
                f"{self.redis_key_prefix}daily:{today}:optimize",
                f"{self.redis_key_prefix}daily:{today}:register",
                f"{self.redis_key_prefix}daily:{today}:login"
            ]
            
            daily_values = []
            for key in daily_keys:
                value = await redis_manager.redis_client.get(key)
                daily_values.append(int(value) if value else 0)
            
            # Get this hour's events
            hourly_keys = [
                f"{self.redis_key_prefix}hourly:{hour}:compile",
                f"{self.redis_key_prefix}hourly:{hour}:optimize",
                f"{self.redis_key_prefix}hourly:{hour}:register",
                f"{self.redis_key_prefix}hourly:{hour}:login"
            ]
            
            hourly_values = []
            for key in hourly_keys:
                value = await redis_manager.redis_client.get(key)
                hourly_values.append(int(value) if value else 0)
            
            return {
                "today": {
                    "compilations": daily_values[0],
                    "optimizations": daily_values[1],
                    "registrations": daily_values[2],
                    "logins": daily_values[3]
                },
                "this_hour": {
                    "compilations": hourly_values[0],
                    "optimizations": hourly_values[1],
                    "registrations": hourly_values[2],
                    "logins": hourly_values[3]
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting real-time metrics: {e}")
            return {}
    
    async def get_conversion_funnel(
        self,
        db: AsyncSession,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get conversion funnel analytics."""
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Landing page visits (from analytics events)
            landing_visits_query = select(func.count(UsageAnalytics.id)).where(
                and_(
                    UsageAnalytics.action == 'page_view',
                    UsageAnalytics.metadata['page'].astext == 'landing',
                    UsageAnalytics.created_at >= start_date
                )
            )
            landing_visits_result = await db.execute(landing_visits_query)
            landing_visits = landing_visits_result.scalar() or 0
            
            # Trial starts
            trial_starts_query = select(func.count(DeviceTrial.id)).where(
                DeviceTrial.created_at >= start_date
            )
            trial_starts_result = await db.execute(trial_starts_query)
            trial_starts = trial_starts_result.scalar() or 0
            
            # Registrations
            registrations_query = select(func.count(User.id)).where(
                User.created_at >= start_date
            )
            registrations_result = await db.execute(registrations_query)
            registrations = registrations_result.scalar() or 0
            
            # Subscriptions
            subscriptions_query = select(func.count(Subscription.id)).where(
                and_(
                    Subscription.created_at >= start_date,
                    Subscription.status == 'active'
                )
            )
            subscriptions_result = await db.execute(subscriptions_query)
            subscriptions = subscriptions_result.scalar() or 0
            
            # Calculate conversion rates
            trial_conversion = (trial_starts / landing_visits * 100) if landing_visits > 0 else 0
            registration_conversion = (registrations / trial_starts * 100) if trial_starts > 0 else 0
            subscription_conversion = (subscriptions / registrations * 100) if registrations > 0 else 0
            overall_conversion = (subscriptions / landing_visits * 100) if landing_visits > 0 else 0
            
            return {
                "period_days": days,
                "funnel_steps": {
                    "landing_visits": landing_visits,
                    "trial_starts": trial_starts,
                    "registrations": registrations,
                    "subscriptions": subscriptions
                },
                "conversion_rates": {
                    "landing_to_trial": round(trial_conversion, 2),
                    "trial_to_registration": round(registration_conversion, 2),
                    "registration_to_subscription": round(subscription_conversion, 2),
                    "overall_conversion": round(overall_conversion, 2)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting conversion funnel: {e}")
            return {}
    
    async def track_compilation_event(
        self,
        db: AsyncSession,
        user_id: Optional[UUID],
        device_fingerprint: Optional[str],
        compilation_id: str,
        status: str,
        compilation_time: Optional[float] = None,
        ip_address: Optional[str] = None
    ):
        """Track compilation-specific events."""
        metadata = {
            "compilation_id": compilation_id,
            "status": status,
            "compilation_time": compilation_time
        }
        
        await self.track_event(
            db=db,
            event_type="compile",
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            metadata=metadata,
            ip_address=ip_address
        )
    
    async def track_optimization_event(
        self,
        db: AsyncSession,
        user_id: Optional[UUID],
        optimization_id: str,
        provider: str,
        model: str,
        tokens_used: Optional[int] = None,
        ip_address: Optional[str] = None
    ):
        """Track optimization-specific events."""
        metadata = {
            "optimization_id": optimization_id,
            "provider": provider,
            "model": model,
            "tokens_used": tokens_used
        }
        
        await self.track_event(
            db=db,
            event_type="optimize",
            user_id=user_id,
            metadata=metadata,
            ip_address=ip_address
        )
    
    async def track_user_journey_event(
        self,
        db: AsyncSession,
        event_type: str,
        user_id: Optional[UUID] = None,
        device_fingerprint: Optional[str] = None,
        page: Optional[str] = None,
        feature: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """Track user journey events (page views, feature usage, etc.)."""
        metadata = {}
        if page:
            metadata["page"] = page
        if feature:
            metadata["feature"] = feature
            
        await self.track_event(
            db=db,
            event_type=event_type,
            user_id=user_id,
            device_fingerprint=device_fingerprint,
            metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent
        )

# Global analytics service instance
analytics_service = AnalyticsService()


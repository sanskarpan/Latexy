"""
Analytics Service for tracking user behavior and system metrics.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ..database.models import (
    User, DeviceTrial, Resume, Compilation, Optimization,
    UsageAnalytics, Subscription, Payment
)
from ..database.connection import get_db
from ..core.redis import redis_manager

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

    async def get_user_analytics_timeseries(
        self,
        db: AsyncSession,
        user_id: UUID,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get richer per-day analytics for a specific user."""
        try:
            period_days = max(1, min(days, 365))
            today = datetime.now(timezone.utc).date()
            start_day = today - timedelta(days=period_days - 1)
            start_date = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)

            compilations_query = select(Compilation).where(
                and_(
                    Compilation.user_id == user_id,
                    Compilation.created_at >= start_date
                )
            )
            compilations = (await db.execute(compilations_query)).scalars().all()

            optimizations_query = select(Optimization).where(
                and_(
                    Optimization.user_id == user_id,
                    Optimization.created_at >= start_date
                )
            )
            optimizations = (await db.execute(optimizations_query)).scalars().all()

            events_query = select(UsageAnalytics).where(
                and_(
                    UsageAnalytics.user_id == user_id,
                    UsageAnalytics.created_at >= start_date
                )
            )
            events = (await db.execute(events_query)).scalars().all()

            days_list = [
                (start_day + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(period_days)
            ]

            activity_map: Dict[str, Dict[str, int]] = {
                day: {
                    "events": 0,
                    "compile_events": 0,
                    "optimize_events": 0,
                    "feature_events": 0,
                }
                for day in days_list
            }
            compilation_map: Dict[str, Dict[str, Any]] = {
                day: {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "latency_sum": 0.0,
                    "latency_count": 0,
                }
                for day in days_list
            }
            optimization_map: Dict[str, Dict[str, Any]] = {
                day: {
                    "total": 0,
                    "tokens_sum": 0,
                    "tokens_count": 0,
                    "ats_sum": 0.0,
                    "ats_count": 0,
                }
                for day in days_list
            }
            feature_totals: Dict[str, int] = {}
            feature_last_used: Dict[str, datetime] = {}

            for event in events:
                day = event.created_at.strftime("%Y-%m-%d")
                if day not in activity_map:
                    continue
                activity_map[day]["events"] += 1

                action = event.action or ""
                if action in {"compile", "latex_compilation"}:
                    activity_map[day]["compile_events"] += 1
                if action in {"optimize", "combined", "llm_optimization"}:
                    activity_map[day]["optimize_events"] += 1

                feature_key = None
                metadata = event.event_metadata or {}
                if isinstance(metadata, dict) and metadata.get("feature"):
                    feature_key = str(metadata["feature"])
                elif action:
                    feature_key = action

                if feature_key:
                    activity_map[day]["feature_events"] += 1
                    feature_totals[feature_key] = feature_totals.get(feature_key, 0) + 1
                    previous = feature_last_used.get(feature_key)
                    if previous is None or event.created_at > previous:
                        feature_last_used[feature_key] = event.created_at

            for item in compilations:
                day = item.created_at.strftime("%Y-%m-%d")
                if day not in compilation_map:
                    continue
                entry = compilation_map[day]
                entry["total"] += 1
                status = (item.status or "").lower()
                if status == "completed":
                    entry["completed"] += 1
                elif status == "failed":
                    entry["failed"] += 1
                elif status == "cancelled":
                    entry["cancelled"] += 1

                if item.compilation_time is not None:
                    entry["latency_sum"] += float(item.compilation_time)
                    entry["latency_count"] += 1

            for item in optimizations:
                day = item.created_at.strftime("%Y-%m-%d")
                if day not in optimization_map:
                    continue
                entry = optimization_map[day]
                entry["total"] += 1

                if item.tokens_used is not None:
                    entry["tokens_sum"] += int(item.tokens_used)
                    entry["tokens_count"] += 1

                ats_score_value = None
                if isinstance(item.ats_score, dict):
                    if isinstance(item.ats_score.get("overall_score"), (int, float)):
                        ats_score_value = float(item.ats_score["overall_score"])
                    elif isinstance(item.ats_score.get("overall"), (int, float)):
                        ats_score_value = float(item.ats_score["overall"])
                elif isinstance(item.ats_score, (int, float)):
                    ats_score_value = float(item.ats_score)

                if ats_score_value is not None:
                    entry["ats_sum"] += ats_score_value
                    entry["ats_count"] += 1

            activity_series = [
                {
                    "date": day,
                    "events": activity_map[day]["events"],
                    "compile_events": activity_map[day]["compile_events"],
                    "optimize_events": activity_map[day]["optimize_events"],
                    "feature_events": activity_map[day]["feature_events"],
                }
                for day in days_list
            ]
            compilation_series = [
                {
                    "date": day,
                    "total": compilation_map[day]["total"],
                    "completed": compilation_map[day]["completed"],
                    "failed": compilation_map[day]["failed"],
                    "cancelled": compilation_map[day]["cancelled"],
                    "avg_latency": round(
                        compilation_map[day]["latency_sum"] / compilation_map[day]["latency_count"],
                        2
                    ) if compilation_map[day]["latency_count"] > 0 else 0,
                }
                for day in days_list
            ]
            optimization_series = [
                {
                    "date": day,
                    "total": optimization_map[day]["total"],
                    "avg_tokens": round(
                        optimization_map[day]["tokens_sum"] / optimization_map[day]["tokens_count"],
                        2
                    ) if optimization_map[day]["tokens_count"] > 0 else 0,
                    "avg_ats_score": round(
                        optimization_map[day]["ats_sum"] / optimization_map[day]["ats_count"],
                        2
                    ) if optimization_map[day]["ats_count"] > 0 else 0,
                }
                for day in days_list
            ]
            feature_series = sorted(
                [
                    {
                        "feature": feature,
                        "count": count,
                        "last_used_at": feature_last_used[feature].isoformat() if feature in feature_last_used else None,
                    }
                    for feature, count in feature_totals.items()
                ],
                key=lambda item: item["count"],
                reverse=True,
            )

            status_distribution = {
                "completed": sum(1 for c in compilations if (c.status or "").lower() == "completed"),
                "processing": sum(1 for c in compilations if (c.status or "").lower() == "processing"),
                "queued": sum(1 for c in compilations if (c.status or "").lower() == "queued"),
                "failed": sum(1 for c in compilations if (c.status or "").lower() == "failed"),
                "cancelled": sum(1 for c in compilations if (c.status or "").lower() == "cancelled"),
            }

            return {
                "user_id": str(user_id),
                "period_days": period_days,
                "activity_series": activity_series,
                "compilation_series": compilation_series,
                "optimization_series": optimization_series,
                "feature_series": feature_series,
                "status_distribution": status_distribution,
            }

        except Exception as e:
            logger.error(f"Error getting user analytics timeseries: {e}")
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
            events_query = select(UsageAnalytics).where(
                and_(
                    UsageAnalytics.action == 'page_view',
                    UsageAnalytics.created_at >= start_date
                )
            )
            page_view_events = (await db.execute(events_query)).scalars().all()
            landing_visits = 0
            for event in page_view_events:
                metadata = event.event_metadata or {}
                if isinstance(metadata, dict) and metadata.get("page") == "landing":
                    landing_visits += 1
            
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

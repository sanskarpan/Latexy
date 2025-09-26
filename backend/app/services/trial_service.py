"""Trial system service for freemium model."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..database.models import DeviceTrial, UsageAnalytics
from ..core.logging import get_logger

logger = get_logger(__name__)

TRIAL_LIMIT = 3
COOLDOWN_PERIOD = 300  # 5 minutes in seconds
MAX_DAILY_REQUESTS = 10

class TrialService:
    """Service for managing device trials and usage tracking."""

    async def get_trial_status(
        self, 
        db: AsyncSession, 
        device_fingerprint: str,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get trial status for a device."""
        try:
            # Get or create device trial record
            stmt = select(DeviceTrial).where(DeviceTrial.device_fingerprint == device_fingerprint)
            result = await db.execute(stmt)
            trial = result.scalar_one_or_none()

            if not trial:
                # Create new trial record
                trial = DeviceTrial(
                    device_fingerprint=device_fingerprint,
                    ip_address=ip_address,
                    usage_count=0,
                    blocked=False
                )
                db.add(trial)
                await db.commit()
                await db.refresh(trial)

            return {
                "usageCount": trial.usage_count,
                "remainingUses": max(0, TRIAL_LIMIT - trial.usage_count),
                "blocked": trial.blocked,
                "lastUsed": trial.last_used.isoformat() if trial.last_used else None,
                "canUse": not trial.blocked and trial.usage_count < TRIAL_LIMIT
            }

        except Exception as e:
            logger.error(f"Error getting trial status: {e}")
            return {
                "usageCount": 0,
                "remainingUses": TRIAL_LIMIT,
                "blocked": False,
                "lastUsed": None,
                "canUse": True
            }

    async def check_rate_limits(
        self,
        db: AsyncSession,
        device_fingerprint: str,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Check if device/IP is within rate limits."""
        try:
            now = datetime.utcnow()
            
            # Check device-based rate limiting
            stmt = select(DeviceTrial).where(DeviceTrial.device_fingerprint == device_fingerprint)
            result = await db.execute(stmt)
            trial = result.scalar_one_or_none()

            if trial:
                # Check cooldown period
                if trial.last_used:
                    time_since_last = (now - trial.last_used).total_seconds()
                    if time_since_last < COOLDOWN_PERIOD:
                        return {
                            "allowed": False,
                            "reason": "cooldown",
                            "waitTime": COOLDOWN_PERIOD - time_since_last
                        }

                # Check if blocked
                if trial.blocked:
                    return {
                        "allowed": False,
                        "reason": "blocked",
                        "waitTime": None
                    }

                # Check trial limit
                if trial.usage_count >= TRIAL_LIMIT:
                    return {
                        "allowed": False,
                        "reason": "trial_limit_exceeded",
                        "waitTime": None
                    }

            # Check IP-based daily limits if IP is provided
            if ip_address:
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                stmt = select(UsageAnalytics).where(
                    UsageAnalytics.ip_address == ip_address,
                    UsageAnalytics.created_at >= today_start
                )
                result = await db.execute(stmt)
                daily_usage = len(result.scalars().all())

                if daily_usage >= MAX_DAILY_REQUESTS:
                    return {
                        "allowed": False,
                        "reason": "daily_limit_exceeded",
                        "waitTime": None
                    }

            return {
                "allowed": True,
                "reason": None,
                "waitTime": None
            }

        except Exception as e:
            logger.error(f"Error checking rate limits: {e}")
            # Allow on error to avoid blocking legitimate users
            return {
                "allowed": True,
                "reason": None,
                "waitTime": None
            }

    async def track_usage(
        self,
        db: AsyncSession,
        device_fingerprint: str,
        action: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Track device usage and update trial status."""
        try:
            now = datetime.utcnow()

            # Check rate limits first
            rate_check = await self.check_rate_limits(db, device_fingerprint, ip_address)
            if not rate_check["allowed"]:
                return {
                    "success": False,
                    "error": rate_check["reason"],
                    "waitTime": rate_check.get("waitTime")
                }

            # Get or create device trial record
            stmt = select(DeviceTrial).where(DeviceTrial.device_fingerprint == device_fingerprint)
            result = await db.execute(stmt)
            trial = result.scalar_one_or_none()

            if not trial:
                trial = DeviceTrial(
                    device_fingerprint=device_fingerprint,
                    ip_address=ip_address,
                    session_id=session_id,
                    usage_count=0,
                    blocked=False
                )
                db.add(trial)

            # Update trial usage
            trial.usage_count += 1
            trial.last_used = now
            trial.session_id = session_id or trial.session_id
            trial.ip_address = ip_address or trial.ip_address

            # Block if limit exceeded
            if trial.usage_count >= TRIAL_LIMIT:
                trial.blocked = True

            # Create usage analytics record
            analytics = UsageAnalytics(
                device_fingerprint=device_fingerprint,
                action=action,
                resource_type=resource_type,
                event_metadata=metadata,
                ip_address=ip_address,
                user_agent=user_agent
            )
            db.add(analytics)

            await db.commit()

            return {
                "success": True,
                "usageCount": trial.usage_count,
                "remainingUses": max(0, TRIAL_LIMIT - trial.usage_count),
                "blocked": trial.blocked
            }

        except Exception as e:
            logger.error(f"Error tracking usage: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": "tracking_failed"
            }

    async def reset_trial(
        self,
        db: AsyncSession,
        device_fingerprint: str
    ) -> bool:
        """Reset trial for a device (admin function)."""
        try:
            stmt = update(DeviceTrial).where(
                DeviceTrial.device_fingerprint == device_fingerprint
            ).values(
                usage_count=0,
                blocked=False,
                last_used=datetime.utcnow()
            )
            await db.execute(stmt)
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error resetting trial: {e}")
            await db.rollback()
            return False

    async def block_device(
        self,
        db: AsyncSession,
        device_fingerprint: str,
        reason: str = "abuse_detected"
    ) -> bool:
        """Block a device from using trials."""
        try:
            stmt = update(DeviceTrial).where(
                DeviceTrial.device_fingerprint == device_fingerprint
            ).values(
                blocked=True
            )
            await db.execute(stmt)
            await db.commit()
            
            logger.info(f"Blocked device {device_fingerprint[:8]}... for {reason}")
            return True
        except Exception as e:
            logger.error(f"Error blocking device: {e}")
            await db.rollback()
            return False

# Global service instance
trial_service = TrialService()

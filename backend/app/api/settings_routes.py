"""
Settings routes — Feature 19: notification preferences.

GET  /settings/notifications  — return current prefs
PUT  /settings/notifications  — update prefs
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import User
from ..middleware.auth_middleware import get_current_user_required

logger = get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class NotificationPrefs(BaseModel):
    job_completed: bool = True
    weekly_digest: bool = False


@router.get("/notifications", response_model=NotificationPrefs)
async def get_notification_prefs(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> NotificationPrefs:
    """Return the authenticated user's email notification preferences."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    prefs = user.email_notifications or {}
    return NotificationPrefs(
        job_completed=prefs.get("job_completed", True),
        weekly_digest=prefs.get("weekly_digest", False),
    )


@router.put("/notifications", response_model=NotificationPrefs)
async def update_notification_prefs(
    body: NotificationPrefs,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> NotificationPrefs:
    """Update the authenticated user's email notification preferences."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.email_notifications = {
        "job_completed": body.job_completed,
        "weekly_digest": body.weekly_digest,
    }
    await db.commit()
    logger.info(f"SETTINGS: updated notification prefs for user {user_id}: {user.email_notifications}")
    return body

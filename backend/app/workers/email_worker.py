"""
Email notification worker — Feature 19.

Tasks:
  send_job_completion_email  — triggered after successful optimization/compile
  send_weekly_digest         — per-user weekly summary (called by beat fan-out)
  send_weekly_digest_to_all  — Celery Beat entry point; fans out to per-user tasks

All email sends are guarded by EMAIL_ENABLED in config — disabled by default
until the operator sets it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app

logger = logging.getLogger(__name__)


# ── send_job_completion_email ─────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_job_completion_email",
    queue="email",
    max_retries=2,
    default_retry_delay=30,
    ignore_result=True,
    soft_time_limit=30,
    time_limit=60,
)
def send_job_completion_email(
    user_id: str,
    job_type: str,
    job_id: str,
    result_summary: Optional[Dict[str, Any]] = None,
) -> None:
    """Send a job-completion email to the user if they have opted in."""
    asyncio.run(_async_send_job_completion(user_id, job_type, job_id, result_summary or {}))


async def _async_send_job_completion(
    user_id: str,
    job_type: str,
    job_id: str,
    result_summary: Dict[str, Any],
) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import User
    from ..services.email_service import email_service, render_job_completed_email
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("EMAIL: DATABASE_URL not set, skipping completion email")
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"EMAIL: user {user_id} not found")
            return

        prefs: Dict = user.email_notifications or {}
        if not prefs.get("job_completed", True):
            logger.debug(f"EMAIL: user {user_id} has job_completed notifications disabled")
            return

        user_name = user.name or user.email.split("@")[0]
        ats_score = result_summary.get("ats_score")
        resume_url = f"{settings.FRONTEND_URL}/workspace/{result_summary.get('resume_id', '')}/edit"

        html, text = render_job_completed_email(user_name, job_type, ats_score, resume_url)
        job_label = "optimization" if job_type == "llm_optimization" else "compilation"
        await email_service.send_email(
            to=user.email,
            subject=f"Your resume {job_label} is complete",
            html_body=html,
            text_body=text,
        )
    except Exception as exc:
        logger.error(f"EMAIL: completion email failed for user {user_id}: {exc}")
    finally:
        await engine.dispose()


# ── send_weekly_digest ────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_weekly_digest",
    queue="email",
    max_retries=1,
    ignore_result=True,
    soft_time_limit=60,
    time_limit=120,
)
def send_weekly_digest(user_id: str) -> None:
    """Send weekly activity digest to a single user."""
    asyncio.run(_async_send_weekly_digest(user_id))


async def _async_send_weekly_digest(user_id: str) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import Compilation, Resume, User
    from ..services.email_service import email_service, render_weekly_digest_email
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    try:
        async with session_factory() as session:
            user_result = await session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                return

            prefs: Dict = user.email_notifications or {}
            if not prefs.get("weekly_digest", False):
                return

            # Resume count this week
            resume_result = await session.execute(
                select(func.count()).select_from(Resume).where(
                    Resume.user_id == user_id,
                    Resume.created_at >= since,
                )
            )
            resume_count: int = resume_result.scalar_one() or 0

            # Compilation count + avg ATS score this week
            compile_result = await session.execute(
                select(func.count(), func.avg(Compilation.ats_score)).where(
                    Compilation.user_id == user_id,
                    Compilation.created_at >= since,
                )
            )
            row = compile_result.one()
            compilation_count: int = row[0] or 0
            avg_ats: Optional[float] = float(row[1]) if row[1] else None

            # Stale resumes: not updated in 90+ days, not archived
            stale_result = await session.execute(
                select(Resume.id, Resume.title, Resume.updated_at).where(
                    Resume.user_id == user_id,
                    Resume.updated_at <= stale_cutoff,
                    Resume.archived_at.is_(None),
                )
            )
            now = datetime.now(timezone.utc)
            stale_resumes = [
                {
                    "id": str(row.id),
                    "title": row.title or "Untitled",
                    "days_since_updated": (now - row.updated_at.replace(tzinfo=timezone.utc)).days,
                }
                for row in stale_result.all()
            ]

        user_name = user.name or user.email.split("@")[0]
        html, text = render_weekly_digest_email(
            user_name, resume_count, compilation_count, avg_ats, stale_resumes or None
        )
        await email_service.send_email(
            to=user.email,
            subject="Your weekly Latexy summary",
            html_body=html,
            text_body=text,
        )
    except Exception as exc:
        logger.error(f"EMAIL: weekly digest failed for user {user_id}: {exc}")
    finally:
        await engine.dispose()


# ── send_weekly_digest_to_all ─────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_weekly_digest_to_all",
    queue="email",
    ignore_result=True,
)
def send_weekly_digest_to_all() -> None:
    """Celery Beat entry point — fans out per-user weekly digest tasks."""
    asyncio.run(_async_fan_out_weekly_digest())


async def _async_fan_out_weekly_digest() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import User
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(User.id).where(
                    User.email_notifications["weekly_digest"].astext == "true"
                )
            )
            user_ids = [row[0] for row in result.all()]

        logger.info(f"EMAIL: fanning out weekly digest to {len(user_ids)} users")
        for uid in user_ids:
            send_weekly_digest.apply_async(args=[uid], queue="email", countdown=1)
    except Exception as exc:
        logger.error(f"EMAIL: fan-out weekly digest failed: {exc}")
    finally:
        await engine.dispose()

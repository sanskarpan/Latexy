"""
Email notification worker — Feature 19.

Tasks:
  send_job_completion_email  — triggered after successful optimization/compile
  send_job_failure_email     — triggered once for a terminal job.failed event
  send_share_viewed_email    — triggered after a debounced public share view
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
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
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
        sent = await email_service.send_email(
            to=user.email,
            subject=f"Your resume {job_label} is complete",
            html_body=html,
            text_body=text,
        )
        if not sent:
            raise RuntimeError("email provider did not accept completion email")
    except Exception as exc:
        logger.error(f"EMAIL: completion email failed for user {user_id}: {exc}", exc_info=True)
        raise
    finally:
        await engine.dispose()


# ── send_job_failure_email ────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_job_failure_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
    max_retries=2,
    default_retry_delay=30,
    ignore_result=True,
    soft_time_limit=30,
    time_limit=60,
)
def send_job_failure_email(user_id: str, job_type: str, job_id: str) -> None:
    """Send a terminal job-failure email when the user has opted in."""
    asyncio.run(_async_send_job_failure(user_id, job_type, job_id))


async def _async_send_job_failure(user_id: str, job_type: str, job_id: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import User
    from ..services.email_service import email_service, render_job_failed_email
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("EMAIL: DATABASE_URL not set, skipping failure email")
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            logger.warning("EMAIL: user %s not found for failed job %s", user_id, job_id)
            return

        prefs: Dict = user.email_notifications or {}
        if not prefs.get("job_failed", True):
            return

        user_name = user.name or user.email.split("@")[0]
        workspace_url = f"{settings.FRONTEND_URL}/workspace"
        html, text = render_job_failed_email(user_name, job_type, workspace_url)
        sent = await email_service.send_email(
            to=user.email,
            subject="A Latexy job could not finish",
            html_body=html,
            text_body=text,
        )
        if not sent:
            raise RuntimeError("email provider did not accept failure email")
    except Exception as exc:
        logger.error(
            "EMAIL: failure email failed for user %s, job %s: %s",
            user_id,
            job_id,
            exc,
            exc_info=True,
        )
        raise
    finally:
        await engine.dispose()


# ── send_share_viewed_email ───────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_share_viewed_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
    max_retries=2,
    default_retry_delay=30,
    ignore_result=True,
    soft_time_limit=30,
    time_limit=60,
)
def send_share_viewed_email(
    user_id: str,
    resume_id: str,
    resume_title: str,
    country_code: Optional[str] = None,
    referrer: Optional[str] = None,
) -> None:
    """Send an email for a newly persisted, debounced public share view."""
    asyncio.run(
        _async_send_share_viewed(
            user_id,
            resume_id,
            resume_title,
            country_code,
            referrer,
        )
    )


async def _async_send_share_viewed(
    user_id: str,
    resume_id: str,
    resume_title: str,
    country_code: Optional[str],
    referrer: Optional[str],
) -> None:
    from urllib.parse import quote

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import User
    from ..services.email_service import email_service, render_share_viewed_email
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("EMAIL: DATABASE_URL not set, skipping share-view email")
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            logger.warning("EMAIL: user %s not found for resume %s", user_id, resume_id)
            return

        prefs: Dict = user.email_notifications or {}
        if not prefs.get("share_viewed", False):
            return

        user_name = user.name or user.email.split("@")[0]
        resume_url = (
            f"{settings.FRONTEND_URL}/workspace/{quote(str(resume_id), safe='')}/edit"
        )
        html, text = render_share_viewed_email(
            user_name,
            resume_title,
            resume_url,
            country_code,
            referrer,
        )
        sent = await email_service.send_email(
            to=user.email,
            subject="Your shared resume was viewed",
            html_body=html,
            text_body=text,
        )
        if not sent:
            raise RuntimeError("email provider did not accept share-view email")
    except Exception as exc:
        logger.error(
            "EMAIL: share-view email failed for user %s, resume %s: %s",
            user_id,
            resume_id,
            exc,
            exc_info=True,
        )
        raise
    finally:
        await engine.dispose()


# ── send_weekly_digest ────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_weekly_digest",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
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
    from ..database.models import Compilation, Optimization, Resume, User
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

            # Compilation count this week
            compile_result = await session.execute(
                select(func.count()).select_from(Compilation).where(
                    Compilation.user_id == user_id,
                    Compilation.created_at >= since,
                )
            )
            compilation_count: int = compile_result.scalar_one() or 0

            # ATS scores belong to optimization history, not compilations.
            ats_result = await session.execute(
                select(func.avg(Optimization.ats_score)).where(
                    Optimization.user_id == user_id,
                    Optimization.created_at >= since,
                    Optimization.ats_score.is_not(None),
                )
            )
            avg_ats_value = ats_result.scalar_one_or_none()
            avg_ats: Optional[float] = (
                float(avg_ats_value) if avg_ats_value is not None else None
            )

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
        sent = await email_service.send_email(
            to=user.email,
            subject="Your weekly Latexy summary",
            html_body=html,
            text_body=text,
        )
        if not sent:
            raise RuntimeError("email provider did not accept weekly digest")
    except Exception as exc:
        logger.error(f"EMAIL: weekly digest failed for user {user_id}: {exc}", exc_info=True)
        raise
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
            if os.environ.get("DEPLOY_TARGET") == "modal":
                from ..core.modal_dispatch import spawn

                spawn("run_weekly_digest_task", {"user_id": str(uid)})
                continue
            send_weekly_digest.apply_async(args=[uid], queue="email", countdown=1)
    except Exception as exc:
        logger.error(f"EMAIL: fan-out weekly digest failed: {exc}", exc_info=True)
    finally:
        await engine.dispose()


def submit_job_completion_email(
    user_id: str, job_type: str, job_id: str, result_summary: Optional[Dict[str, Any]] = None
) -> None:
    """Queue a completion email, routing to Modal in production.

    Same shape as submit_auto_save_checkpoint: no Celery consumer exists on
    Modal, so the unconditional apply_async() dropped the notification silently.
    Non-fatal by design — the job itself has already succeeded.
    """
    try:
        if os.environ.get("DEPLOY_TARGET") == "modal":
            from ..core.modal_dispatch import spawn
            spawn("run_email_task", {
                "user_id": user_id,
                "job_type": job_type,
                "job_id": job_id,
                "result_summary": result_summary or {},
            })
            return
        send_job_completion_email.apply_async(
            args=[user_id, job_type, job_id],
            kwargs={"result_summary": result_summary or {}},
            queue="email",
            countdown=3,
        )
    except Exception as exc:
        logger.debug("Failed to enqueue completion email: %s", exc)


def submit_job_failure_email(user_id: str, job_type: str, job_id: str) -> bool:
    """Queue one terminal failure email through the active deployment runtime."""
    try:
        payload = {"user_id": user_id, "job_type": job_type, "job_id": job_id}
        if os.environ.get("DEPLOY_TARGET") == "modal":
            from ..core.modal_dispatch import spawn
            spawn("run_job_failure_email_task", payload)
        else:
            send_job_failure_email.apply_async(kwargs=payload, queue="email", countdown=1)
        return True
    except Exception as exc:
        logger.debug("Failed to enqueue job-failure email: %s", exc)
        return False


def submit_share_viewed_email(
    user_id: str,
    resume_id: str,
    resume_title: str,
    country_code: Optional[str] = None,
    referrer: Optional[str] = None,
) -> bool:
    """Queue a debounced share-view email through the active deployment runtime."""
    try:
        payload = {
            "user_id": user_id,
            "resume_id": resume_id,
            "resume_title": resume_title,
            "country_code": country_code,
            "referrer": referrer,
        }
        if os.environ.get("DEPLOY_TARGET") == "modal":
            from ..core.modal_dispatch import spawn
            spawn("run_share_viewed_email_task", payload)
        else:
            send_share_viewed_email.apply_async(kwargs=payload, queue="email", countdown=1)
        return True
    except Exception as exc:
        logger.debug("Failed to enqueue share-view email: %s", exc)
        return False

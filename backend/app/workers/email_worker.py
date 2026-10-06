"""
Email notification worker — Feature 19.

Tasks:
  send_comment_mention_email — one durable collaborator mention notification
  send_pending_comment_mention_emails — recovery sweep for missed queue sends
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from ..core.celery_app import celery_app

logger = logging.getLogger(__name__)

COMMENT_MENTION_CLAIM_TTL = timedelta(minutes=5)
COMMENT_MENTION_MAX_AGE = timedelta(days=7)


# ── send_document_email_delivery (B50d) ─────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_document_email_delivery",
    queue="email",
    ignore_result=True,
    soft_time_limit=45,
    time_limit=60,
)
def send_document_email_delivery(delivery_id: str) -> None:
    """Retry one durable compiled-document delivery after a process restart."""
    asyncio.run(_async_send_document_email_delivery(delivery_id))


async def _async_send_document_email_delivery(delivery_id: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import User
    from ..services.document_delivery_service import (
        claim_delivery,
        mark_accepted,
        mark_failed,
        mark_permanent_failure,
    )
    from ..services.email_service import EmailAttachment, email_service, render_document_delivery_email
    from ..utils.db_url import normalize_database_url

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url or not settings.EMAIL_ENABLED:
        return
    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            delivery = await claim_delivery(session, delivery_id)
            if delivery is None:
                return
            claim_token = delivery.claim_token
            user_result = await session.execute(select(User).where(User.id == delivery.user_id))
            user = user_result.scalar_one_or_none()
            if user is None or not user.email_verified or user.email.strip().lower() != delivery.recipient_email:
                await mark_permanent_failure(
                    session, delivery, "recipient_unverified", claim_token=claim_token
                )
                return
            # Importing this helper keeps all storage/path validation in one
            # place. It only reads the row scoped to this user and resume.
            from ..api.document_delivery_routes import _owned_compiled_pdf

            # The FK is SET NULL when a compilation is deleted. Never fall
            # back to the resume's latest compilation here: that would attach
            # different document bytes to this delivery's idempotency key.
            if not delivery.compilation_id:
                await mark_permanent_failure(
                    session, delivery, "compiled_artifact_unavailable", claim_token=claim_token
                )
                return
            try:
                resume, _compilation, pdf_bytes = await _owned_compiled_pdf(
                    str(delivery.resume_id),
                    str(delivery.user_id),
                    session,
                    compilation_id=str(delivery.compilation_id),
                )
            except Exception:
                await mark_permanent_failure(
                    session, delivery, "compiled_artifact_unavailable", claim_token=claim_token
                )
                return
            html_body, text_body = render_document_delivery_email(user.name or "there", resume.title)
            sent = await email_service.send_email(
                to=delivery.recipient_email,
                subject="Your compiled resume from Latexy",
                html_body=html_body,
                text_body=text_body,
                idempotency_key=delivery.idempotency_key,
                attachments=(EmailAttachment("resume.pdf", pdf_bytes, "application/pdf"),),
            )
            if sent:
                await mark_accepted(session, delivery, claim_token=claim_token)
            else:
                await mark_failed(session, delivery, "provider_rejected", claim_token=claim_token)
    finally:
        await engine.dispose()


@celery_app.task(
    name="app.workers.email_worker.send_pending_document_email_deliveries",
    queue="email",
    ignore_result=True,
)
def send_pending_document_email_deliveries() -> int:
    """Beat sweep that requeues rows left pending by a crash or provider outage."""
    from sqlalchemy import and_, or_, select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import DocumentEmailDelivery
    from ..services.document_delivery_service import CLAIM_TTL, MAX_ATTEMPTS
    from ..utils.db_url import normalize_database_url

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url or not settings.EMAIL_ENABLED:
        return 0

    async def _sweep() -> list[str]:
        engine = create_async_engine(normalize_database_url(raw_url), echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                now = datetime.now(timezone.utc)
                # A crash after the final claim must not strand the row in
                # ``processing`` forever. Lower-attempt stale claims remain
                # retryable and are selected below.
                await session.execute(
                    update(DocumentEmailDelivery)
                    .where(
                        DocumentEmailDelivery.status == "processing",
                        DocumentEmailDelivery.attempts >= MAX_ATTEMPTS,
                        DocumentEmailDelivery.claimed_at <= now - CLAIM_TTL,
                    )
                    .values(
                        status="failed",
                        claimed_at=None,
                        claim_token=None,
                        last_error="worker_lost",
                    )
                )
                await session.commit()
                result = await session.execute(
                    select(DocumentEmailDelivery.id)
                    .where(
                        DocumentEmailDelivery.attempts < MAX_ATTEMPTS,
                        DocumentEmailDelivery.next_attempt_at <= now,
                        or_(
                            DocumentEmailDelivery.status.in_(("pending", "failed")),
                            and_(
                                DocumentEmailDelivery.status == "processing",
                                DocumentEmailDelivery.claimed_at <= now - CLAIM_TTL,
                            ),
                        ),
                    )
                    .order_by(DocumentEmailDelivery.created_at)
                    .limit(50)
                )
                return [str(row[0]) for row in result.all()]
        finally:
            await engine.dispose()

    ids = asyncio.run(_sweep())
    for item_id in ids:
        if os.environ.get("DEPLOY_TARGET") == "modal":
            from ..core.modal_dispatch import spawn

            spawn("run_document_email_delivery_task", {"delivery_id": item_id})
        else:
            send_document_email_delivery.apply_async(args=[item_id], queue="email")
    return len(ids)


# ── send_comment_mention_email ──────────────────────────────────────────────

@celery_app.task(
    name="app.workers.email_worker.send_comment_mention_email",
    queue="email",
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_jitter=True,
    max_retries=4,
    default_retry_delay=30,
    ignore_result=True,
    soft_time_limit=30,
    time_limit=60,
)
def send_comment_mention_email(mention_id: str) -> None:
    """Deliver one mention using a short claim and a stable provider key."""
    asyncio.run(_async_send_comment_mention(mention_id))


def submit_comment_mention_email(mention_id: str) -> None:
    """Queue through Celery locally or Modal when no Celery consumer exists."""
    try:
        if os.environ.get("DEPLOY_TARGET") == "modal":
            from ..core.modal_dispatch import spawn

            spawn("run_comment_mention_task", {"mention_id": mention_id})
            return
        send_comment_mention_email.apply_async(args=[mention_id], queue="email", countdown=1)
    except Exception as exc:  # pragma: no cover - broker/runtime outage
        logger.warning("Could not queue comment mention email (%s)", type(exc).__name__)


async def _async_send_comment_mention(mention_id: str) -> None:
    from sqlalchemy import or_, select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import aliased

    from ..core.config import settings
    from ..database.models import (
        Resume,
        ResumeCollaborator,
        ResumeComment,
        ResumeCommentMention,
        TenantMember,
        User,
        Workspace,
        WorkspaceMember,
        WorkspaceResume,
    )
    RecipientUser = aliased(User)
    from ..services.email_service import email_service, render_comment_mention_email
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("EMAIL: DATABASE_URL not set, skipping comment mention")
        return

    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = str(uuid4())
    current = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            claim = await session.execute(
                update(ResumeCommentMention)
                .where(
                    ResumeCommentMention.id == mention_id,
                    ResumeCommentMention.delivery_sent_at.is_(None),
                    or_(
                        ResumeCommentMention.delivery_claimed_at.is_(None),
                        ResumeCommentMention.delivery_claimed_at <= current - COMMENT_MENTION_CLAIM_TTL,
                    ),
                )
                .values(
                    delivery_claimed_at=current,
                    delivery_claim_token=token,
                    delivery_attempts=ResumeCommentMention.delivery_attempts + 1,
                    delivery_last_error=None,
                )
            )
            if getattr(claim, "rowcount", 0) != 1:
                await session.rollback()
                return
            await session.commit()

            result = await session.execute(
                select(ResumeCommentMention, ResumeComment, Resume, RecipientUser)
                .join(ResumeComment, ResumeComment.id == ResumeCommentMention.comment_id)
                .join(Resume, Resume.id == ResumeCommentMention.resume_id)
                .join(RecipientUser, RecipientUser.id == ResumeCommentMention.mentioned_user_id)
                .where(
                    ResumeCommentMention.id == mention_id,
                    ResumeComment.resume_id == ResumeCommentMention.resume_id,
                )
            )
            row = result.first()
            if row is None:
                await session.rollback()
                return
            mention, comment, resume, recipient = row
            if mention.created_at < current - COMMENT_MENTION_MAX_AGE:
                await _finalize_comment_mention(
                    session, mention_id, token, sent=True, error="expired"
                )
                return
            if comment.workspace_id:
                access = await session.execute(
                    select(WorkspaceMember.user_id)
                    .join(
                        WorkspaceResume,
                        (WorkspaceResume.workspace_id == WorkspaceMember.workspace_id)
                        & (WorkspaceResume.resume_id == resume.id),
                    )
                    .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                    .outerjoin(
                        TenantMember,
                        (TenantMember.tenant_id == Workspace.tenant_id)
                        & (TenantMember.user_id == recipient.id),
                    )
                    .where(
                        WorkspaceMember.workspace_id == comment.workspace_id,
                        WorkspaceMember.user_id == recipient.id,
                        or_(
                            Workspace.tenant_id.is_(None),
                            WorkspaceMember.role.in_({"owner", "editor"}),
                            TenantMember.role.in_({"admin", "owner"}),
                            Resume.user_id == recipient.id,
                        ),
                    )
                )
            else:
                access = await session.execute(
                    select(Resume.id)
                    .outerjoin(
                        ResumeCollaborator,
                        (ResumeCollaborator.resume_id == resume.id)
                        & (ResumeCollaborator.user_id == recipient.id),
                    )
                    .where(
                        Resume.id == resume.id,
                        or_(
                            Resume.user_id == recipient.id,
                            ResumeCollaborator.user_id == recipient.id,
                        ),
                    )
                )
            if access.scalar_one_or_none() is None:
                await _finalize_comment_mention(
                    session, mention_id, token, sent=True, error="access_revoked"
                )
                return
            prefs = recipient.email_notifications or {}
            if recipient.id == comment.author_id or not recipient.email_verified or not prefs.get("comment_mentions", True):
                await _finalize_comment_mention(
                    session,
                    mention_id,
                    token,
                    sent=True,
                    error=("self_mention" if recipient.id == comment.author_id
                           else "recipient_unverified" if not recipient.email_verified
                           else "notifications_disabled"),
                )
                return

            # Re-check ownership, terminal state, and access after the claim
            # transaction, immediately before provider I/O. A comment edit/
            # delete or access revocation can race after this check; the stable
            # key makes that unavoidable tiny window safe at idempotent providers.
            owned_query = (
                select(
                    ResumeCommentMention.id,
                    RecipientUser.email,
                    RecipientUser.email_verified,
                    RecipientUser.email_notifications,
                )
                .join(ResumeComment, ResumeComment.id == ResumeCommentMention.comment_id)
                .join(RecipientUser, RecipientUser.id == ResumeCommentMention.mentioned_user_id)
                .where(
                    ResumeCommentMention.id == mention_id,
                    ResumeCommentMention.delivery_claim_token == token,
                    ResumeCommentMention.delivery_sent_at.is_(None),
                    ResumeComment.id == comment.id,
                )
            )
            if comment.workspace_id:
                owned_query = owned_query.join(
                    WorkspaceMember,
                    (WorkspaceMember.workspace_id == comment.workspace_id)
                    & (WorkspaceMember.user_id == recipient.id),
                ).join(
                    WorkspaceResume,
                    (WorkspaceResume.workspace_id == comment.workspace_id)
                    & (WorkspaceResume.resume_id == comment.resume_id),
                ).join(Resume, Resume.id == comment.resume_id).join(
                    Workspace, Workspace.id == WorkspaceMember.workspace_id,
                ).outerjoin(
                    TenantMember,
                    (TenantMember.tenant_id == Workspace.tenant_id)
                    & (TenantMember.user_id == recipient.id),
                ).where(
                    or_(
                        Workspace.tenant_id.is_(None),
                        WorkspaceMember.role.in_({"owner", "editor"}),
                        TenantMember.role.in_({"admin", "owner"}),
                        Resume.user_id == recipient.id,
                    )
                )
            else:
                owned_query = owned_query.join(Resume, Resume.id == comment.resume_id).outerjoin(
                    ResumeCollaborator,
                    (ResumeCollaborator.resume_id == comment.resume_id)
                    & (ResumeCollaborator.user_id == recipient.id),
                ).where(
                    or_(
                        Resume.user_id == recipient.id,
                        ResumeCollaborator.user_id == recipient.id,
                    )
                )
            owned = await session.execute(owned_query)
            owned_row = owned.first()
            if owned_row is None:
                await _finalize_comment_mention(
                    session, mention_id, token, sent=True, error="access_revoked"
                )
                return
            live_email, live_verified, live_prefs = owned_row[1:]
            if not live_verified or not (live_prefs or {}).get("comment_mentions", True):
                await _finalize_comment_mention(
                    session,
                    mention_id,
                    token,
                    sent=True,
                    error=("recipient_unverified" if not live_verified else "notifications_disabled"),
                )
                return
            # Rollback closes the read transaction and expires ORM state on
            # some SQLAlchemy versions. Snapshot only the primitives needed for
            # rendering before ending it; never lazy-load recipient/comment
            # data while the worker is outside an async session transaction.
            recipient_email = live_email
            comment_id = comment.id
            comment_workspace_id = comment.workspace_id
            resume_id = resume.id
            await session.rollback()

            html, text = render_comment_mention_email(
                (
                    f"{settings.FRONTEND_URL}/workspaces/{comment_workspace_id}/recruiter"
                    f"?resume_id={resume_id}&comment_id={comment_id}"
                    if comment_workspace_id
                    else f"{settings.FRONTEND_URL}/workspace/{resume_id}/edit?comment_id={comment_id}"
                ),
            )
            try:
                sent = await email_service.send_email(
                    to=recipient_email,
                    subject="You were mentioned in a resume comment",
                    html_body=html,
                    text_body=text,
                    idempotency_key=f"latexy-comment-mention:{mention_id}",
                )
            except Exception:
                await _finalize_comment_mention(
                    session, mention_id, token, sent=False, error="send_failed"
                )
                raise
            if not sent:
                await _finalize_comment_mention(session, mention_id, token, sent=False, error="send_failed")
                raise RuntimeError("email provider did not accept comment mention")
            await _finalize_comment_mention(session, mention_id, token, sent=True)
    finally:
        await engine.dispose()


async def _finalize_comment_mention(
    session: Any,
    mention_id: str,
    token: str,
    *,
    sent: bool,
    error: Optional[str] = None,
) -> bool:
    """Finalize only if this worker still owns the claim."""
    from sqlalchemy import update

    from ..database.models import ResumeCommentMention

    values: dict[str, Any] = {
        "delivery_claimed_at": None,
        "delivery_claim_token": None,
        "delivery_last_error": error,
    }
    if sent:
        values["delivery_sent_at"] = datetime.now(timezone.utc)
    result = await session.execute(
        update(ResumeCommentMention)
        .where(
            ResumeCommentMention.id == mention_id,
            ResumeCommentMention.delivery_claim_token == token,
        )
        .values(**values)
    )
    if getattr(result, "rowcount", 0) != 1:
        await session.rollback()
        return False
    await session.commit()
    return True


@celery_app.task(
    name="app.workers.email_worker.send_pending_comment_mention_emails",
    queue="email",
    ignore_result=True,
)
def send_pending_comment_mention_emails() -> None:
    """Recovery sweep for commits whose broker enqueue raced an outage."""
    asyncio.run(_async_fan_out_comment_mentions())


async def _async_fan_out_comment_mentions() -> None:
    from sqlalchemy import or_, select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..core.config import settings
    from ..database.models import ResumeCommentMention
    from ..utils.db_url import normalize_database_url

    if not settings.EMAIL_ENABLED:
        return
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        return
    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            now = datetime.now(timezone.utc)
            # Do not create a notification storm after a long email outage;
            # old pending mentions are terminally suppressed before recovery
            # queues the bounded fresh window.
            await session.execute(
                update(ResumeCommentMention)
                .where(
                    ResumeCommentMention.delivery_sent_at.is_(None),
                    ResumeCommentMention.created_at < now - COMMENT_MENTION_MAX_AGE,
                )
                .values(
                    delivery_sent_at=now,
                    delivery_claimed_at=None,
                    delivery_claim_token=None,
                    delivery_last_error="expired",
                )
            )
            await session.commit()
            result = await session.execute(
                select(ResumeCommentMention.id)
                .where(
                    ResumeCommentMention.delivery_sent_at.is_(None),
                    or_(
                        ResumeCommentMention.delivery_claimed_at.is_(None),
                        ResumeCommentMention.delivery_claimed_at <= now - COMMENT_MENTION_CLAIM_TTL,
                    ),
                )
                .order_by(ResumeCommentMention.created_at)
                .limit(100)
            )
            mention_ids = [str(row[0]) for row in result.all()]
        for mention_id in mention_ids:
            try:
                if os.environ.get("DEPLOY_TARGET") == "modal":
                    from ..core.modal_dispatch import spawn

                    spawn("run_comment_mention_task", {"mention_id": mention_id})
                else:
                    send_comment_mention_email.apply_async(args=[mention_id], queue="email", countdown=1)
            except Exception as exc:  # pragma: no cover - broker outage is environment-specific
                logger.warning("Could not queue pending comment mention (%s)", type(exc).__name__)
    finally:
        await engine.dispose()


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
        logger.error("EMAIL: completion email failed for user %s (%s)", user_id, type(exc).__name__)
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
        logger.error("EMAIL: weekly digest failed for user %s (%s)", user_id, type(exc).__name__)
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
        logger.error("EMAIL: fan-out weekly digest failed (%s)", type(exc).__name__)
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
        logger.debug("Failed to enqueue completion email", extra={"error_type": type(exc).__name__})


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
        logger.debug("Failed to enqueue job-failure email", extra={"error_type": type(exc).__name__})
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
        logger.debug("Failed to enqueue share-view email", extra={"error_type": type(exc).__name__})
        return False

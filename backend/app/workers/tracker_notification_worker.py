"""Deliver explicit application reminders and saved-search review nudges."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..core.celery_app import celery_app
from ..core.config import settings
from ..database.models import ApplicationReminder, JobAlert, JobApplication, User
from ..services.email_service import email_service
from ..utils.db_url import normalize_database_url

logger = logging.getLogger(__name__)
SendEmail = Callable[..., Awaitable[bool]]

# A provider call can outlive a worker process. Claims older than this are
# eligible for another worker; the provider idempotency key makes that retry
# safe for providers that support it.
CLAIM_TTL = timedelta(minutes=5)


def _reminder_bodies(user: User, application: JobApplication, reminder: ApplicationReminder) -> tuple[str, str]:
    name = escape(user.name or user.email.split("@")[0])
    company = escape(application.company_name)
    role = escape(application.role_title)
    note = f"<p><strong>Note:</strong> {escape(reminder.note)}</p>" if reminder.note else ""
    tracker_url = f"{settings.FRONTEND_URL}/tracker"
    html = (
        f"<h2>Application follow-up reminder</h2><p>Hi {name},</p>"
        f"<p>You asked to be reminded about your {role} application at {company}.</p>"
        f'{note}<p><a href="{tracker_url}">Open application tracker</a></p>'
    )
    text = (
        "Application follow-up reminder\n\n"
        f"You asked to be reminded about your {application.role_title} application at "
        f"{application.company_name}."
    )
    if reminder.note:
        text += f"\n\nNote: {reminder.note}"
    return html, f"{text}\n\nOpen application tracker: {tracker_url}"


def _alert_bodies(user: User, alert: JobAlert) -> tuple[str, str]:
    name = escape(user.name or user.email.split("@")[0])
    query = escape(alert.query)
    source_url = escape(alert.source_url, quote=True)
    html = (
        f"<h2>Review your saved job search</h2><p>Hi {name},</p>"
        f"<p>This is your {escape(alert.frequency)} reminder to review the search "
        f"you saved for <strong>{query}</strong>.</p>"
        f'<p><a href="{source_url}">Open the source search</a></p>'
        "<p>Latexy does not scrape this source or claim that new jobs were found.</p>"
    )
    text = (
        f"Review your saved job search\n\nThis is your {alert.frequency} reminder to review "
        f"the search you saved for {alert.query}.\n\nOpen the source: {alert.source_url}\n\n"
        "Latexy does not scrape this source or claim that new jobs were found."
    )
    return html, text


async def _send(
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
    idempotency_key: str | None = None,
) -> bool:
    return await email_service.send_email(
        to=recipient,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        idempotency_key=idempotency_key,
    )


def _supports_idempotency_key(sender: SendEmail) -> bool:
    """Keep compatibility with older test/custom senders using four args."""
    try:
        parameters = list(inspect.signature(sender).parameters.values())
    except (TypeError, ValueError):
        return True
    return any(
        parameter.name == "idempotency_key"
        or parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters
    ) or len(parameters) >= 5


async def _invoke_sender(
    sender: SendEmail,
    recipient: str,
    subject: str,
    html_body: str,
    text_body: str,
    idempotency_key: str,
) -> bool:
    if _supports_idempotency_key(sender):
        return await sender(
            recipient,
            subject,
            html_body,
            text_body,
            idempotency_key=idempotency_key,
        )
    return await sender(recipient, subject, html_body, text_body)


async def _claim_row(session: AsyncSession, row: Any, current: datetime) -> str | None:
    """Atomically claim one row immediately before external I/O."""
    model = type(row)
    claim_token = str(uuid4())
    availability = or_(
        model.delivery_claimed_at.is_(None),
        model.delivery_claimed_at <= current - CLAIM_TTL,
    )
    terminal = model.sent_at.is_(None) if model is ApplicationReminder else model.active.is_(True)
    try:
        result = await session.execute(
            update(model)
            .where(model.id == row.id, terminal, availability)
            .values(
                delivery_claimed_at=current,
                delivery_claim_token=claim_token,
                delivery_attempts=func.coalesce(model.delivery_attempts, 0) + 1,
                delivery_last_error=None,
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if rowcount == 0:
            await session.rollback()
            return None
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Tracker notification claim transaction failed")
        return None
    row.delivery_claimed_at = current
    row.delivery_claim_token = claim_token
    row.delivery_attempts = (row.delivery_attempts or 0) + 1
    row.delivery_last_error = None
    return claim_token


async def _claim_is_current(session: AsyncSession, row: Any, current: datetime) -> bool:
    """Re-check ownership after claim and immediately before provider I/O."""
    model = type(row)
    conditions = [model.id == row.id, model.delivery_claim_token == row.delivery_claim_token]
    if model is ApplicationReminder:
        conditions.extend((model.sent_at.is_(None), model.remind_at <= current))
    else:
        conditions.append(model.active.is_(True))
    try:
        result = await session.execute(select(model.id).where(*conditions))
        owned = result.scalar_one_or_none() is not None
    except Exception:
        owned = False
    # The check itself opens a read transaction; close it before the network
    # call. An update can still race after this check and before send.
    await session.rollback()
    return owned


async def _persist_delivery_state(
    session: AsyncSession,
    row: Any,
    *,
    sent_at: datetime | None = None,
    last_notified_at: datetime | None = None,
    error: str | None = None,
) -> bool:
    """Commit one row and isolate failures from all other notifications."""
    claim_token = row.delivery_claim_token
    if not claim_token:
        return False
    model = type(row)
    values: dict[str, Any] = {
        "delivery_claimed_at": None,
        "delivery_claim_token": None,
        "delivery_last_error": error,
    }
    if sent_at is not None:
        values["sent_at"] = sent_at
    if last_notified_at is not None:
        values["last_notified_at"] = last_notified_at
    try:
        result = await session.execute(
            update(model)
            .where(model.id == row.id, model.delivery_claim_token == claim_token)
            .values(**values)
        )
        rowcount = getattr(result, "rowcount", None)
        if rowcount == 0:
            await session.rollback()
            return False
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Tracker notification state transaction failed")
        return False
    for field, value in values.items():
        setattr(row, field, value)
    return True


def _reminder_idempotency_key(reminder: ApplicationReminder) -> str:
    return f"latexy-tracker-reminder:{reminder.id}"


def _alert_idempotency_key(alert: JobAlert) -> str:
    # A recurring alert gets one key per interval. Retries of the same cycle
    # therefore deduplicate, while the next successful cycle gets a new key.
    anchor = alert.last_notified_at or alert.created_at
    anchor_value = anchor.isoformat() if anchor else "initial"
    return f"latexy-tracker-alert:{alert.id}:{anchor_value}"


async def deliver_tracker_notifications(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    send_email: SendEmail = _send,
    limit: int = 100,
) -> dict[str, int]:
    """Deliver due tracker notifications with durable, short-lived claims."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    claim_cutoff = current - CLAIM_TTL
    counts = {"reminders": 0, "alerts": 0, "failed": 0}

    reminder_rows = (
        await session.execute(
            select(ApplicationReminder, JobApplication, User)
            .join(
                JobApplication,
                and_(
                    JobApplication.id == ApplicationReminder.application_id,
                    JobApplication.user_id == ApplicationReminder.user_id,
                ),
            )
            .join(User, User.id == ApplicationReminder.user_id)
            .where(
                ApplicationReminder.sent_at.is_(None),
                ApplicationReminder.remind_at <= current,
                or_(
                    ApplicationReminder.delivery_claimed_at.is_(None),
                    ApplicationReminder.delivery_claimed_at <= claim_cutoff,
                ),
            )
            .order_by(ApplicationReminder.remind_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=ApplicationReminder)
        )
    ).all()
    for reminder, application, user in reminder_rows:
        if await _claim_row(session, reminder, current) is None:
            continue
        prefs = user.email_notifications or {}
        if not prefs.get("tracker_updates", True):
            await _persist_delivery_state(session, reminder, sent_at=current)
            continue
        if not await _claim_is_current(session, reminder, current):
            continue
        html, text = _reminder_bodies(user, application, reminder)
        try:
            delivered = await _invoke_sender(
                send_email,
                user.email,
                "Application follow-up reminder",
                html,
                text,
                _reminder_idempotency_key(reminder),
            )
        except Exception:
            delivered = False
        if delivered:
            if await _persist_delivery_state(session, reminder, sent_at=current):
                counts["reminders"] += 1
            else:
                counts["failed"] += 1
        else:
            await _persist_delivery_state(session, reminder, error="send_failed")
            counts["failed"] += 1

    daily_cutoff = current - timedelta(days=1)
    weekly_cutoff = current - timedelta(days=7)
    alert_rows = (
        await session.execute(
            select(JobAlert, User)
            .join(User, User.id == JobAlert.user_id)
            .where(
                JobAlert.active.is_(True),
                or_(
                    and_(
                        JobAlert.frequency == "daily",
                        or_(
                            JobAlert.last_notified_at <= daily_cutoff,
                            and_(
                                JobAlert.last_notified_at.is_(None),
                                JobAlert.created_at <= daily_cutoff,
                            ),
                        ),
                    ),
                    and_(
                        JobAlert.frequency == "weekly",
                        or_(
                            JobAlert.last_notified_at <= weekly_cutoff,
                            and_(
                                JobAlert.last_notified_at.is_(None),
                                JobAlert.created_at <= weekly_cutoff,
                            ),
                        ),
                    ),
                ),
                or_(
                    JobAlert.delivery_claimed_at.is_(None),
                    JobAlert.delivery_claimed_at <= claim_cutoff,
                ),
            )
            .order_by(JobAlert.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=JobAlert)
        )
    ).all()
    for alert, user in alert_rows:
        if await _claim_row(session, alert, current) is None:
            continue
        prefs = user.email_notifications or {}
        if not prefs.get("tracker_updates", True):
            await _persist_delivery_state(session, alert, last_notified_at=current)
            continue
        if not await _claim_is_current(session, alert, current):
            continue
        html, text = _alert_bodies(user, alert)
        try:
            delivered = await _invoke_sender(
                send_email,
                user.email,
                "Review your saved job search",
                html,
                text,
                _alert_idempotency_key(alert),
            )
        except Exception:
            delivered = False
        if delivered:
            if await _persist_delivery_state(session, alert, last_notified_at=current):
                counts["alerts"] += 1
            else:
                counts["failed"] += 1
        else:
            await _persist_delivery_state(session, alert, error="send_failed")
            counts["failed"] += 1
    return counts


@celery_app.task(
    name="app.workers.tracker_notification_worker.send_tracker_notifications",
    queue="email",
    ignore_result=True,
    soft_time_limit=120,
    time_limit=180,
)
def send_tracker_notifications() -> None:
    asyncio.run(_run_scheduled_delivery())


async def _run_scheduled_delivery() -> None:
    if not settings.EMAIL_ENABLED:
        return
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.warning("TRACKER_EMAIL: DATABASE_URL is not set")
        return
    engine = create_async_engine(normalize_database_url(raw_url), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            counts = await deliver_tracker_notifications(session)
        logger.info(
            "TRACKER_EMAIL: delivered %d reminders and %d alerts; %d failed",
            counts["reminders"],
            counts["alerts"],
            counts["failed"],
        )
    finally:
        await engine.dispose()

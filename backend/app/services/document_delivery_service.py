"""Durable state transitions for compiled-document email delivery (B50d)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import DocumentEmailDelivery

CLAIM_TTL = timedelta(minutes=5)
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=30))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


def provider_name() -> str:
    from ..core.config import settings

    return str(settings.EMAIL_PROVIDER or "unknown")[:32]


async def get_or_create_delivery(
    db: AsyncSession,
    *,
    user_id: str,
    resume_id: str,
    compilation_id: str,
    recipient_email: str,
) -> DocumentEmailDelivery:
    """Create one row per compilation, reusing accepted rows idempotently."""
    # Include a one-way recipient version in the key.  A user may change their
    # verified address between attempts; reusing the old row would otherwise
    # send a fresh request to the previous mailbox.
    recipient_digest = hashlib.sha256(recipient_email.strip().lower().encode("utf-8")).hexdigest()[:32]
    key = f"document-email:{user_id}:{resume_id}:{compilation_id}:{recipient_digest}"
    result = await db.execute(
        select(DocumentEmailDelivery).where(DocumentEmailDelivery.idempotency_key == key)
    )
    delivery = result.scalar_one_or_none()
    if delivery is not None:
        return delivery
    delivery = DocumentEmailDelivery(
        id=str(uuid4()),
        user_id=user_id,
        resume_id=resume_id,
        compilation_id=compilation_id,
        recipient_email=recipient_email,
        idempotency_key=key,
        provider=provider_name(),
        status="pending",
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(delivery)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent click may win the unique idempotency key. Roll back
        # only the failed INSERT, then return the winner.
        await db.rollback()
        result = await db.execute(
            select(DocumentEmailDelivery).where(DocumentEmailDelivery.idempotency_key == key)
        )
        delivery = result.scalar_one()
    return delivery


async def claim_delivery(db: AsyncSession, delivery_id: str) -> Optional[DocumentEmailDelivery]:
    """Atomically claim a pending/retryable row for provider I/O."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(DocumentEmailDelivery)
        .where(
            DocumentEmailDelivery.id == delivery_id,
            DocumentEmailDelivery.attempts < MAX_ATTEMPTS,
            DocumentEmailDelivery.next_attempt_at <= now,
            or_(
                and_(
                    DocumentEmailDelivery.status.in_(("pending", "failed")),
                    or_(
                        DocumentEmailDelivery.claimed_at.is_(None),
                        DocumentEmailDelivery.claimed_at <= now - CLAIM_TTL,
                    ),
                ),
                and_(
                    DocumentEmailDelivery.status == "processing",
                    DocumentEmailDelivery.claimed_at <= now - CLAIM_TTL,
                ),
            ),
        )
        .values(
            status="processing",
            provider=provider_name(),
            claimed_at=now,
            claim_token=str(uuid4()),
            attempts=DocumentEmailDelivery.attempts + 1,
            last_error=None,
        )
        .returning(DocumentEmailDelivery.id)
    )
    claimed_id = result.scalar_one_or_none()
    await db.commit()
    if claimed_id is None:
        return None
    result = await db.execute(select(DocumentEmailDelivery).where(DocumentEmailDelivery.id == claimed_id))
    return result.scalar_one_or_none()


async def make_retryable(db: AsyncSession, delivery: DocumentEmailDelivery) -> None:
    """Allow an explicit user retry without waiting for the backoff window."""
    if delivery.status == "accepted":
        return
    delivery.status = "pending"
    delivery.next_attempt_at = datetime.now(timezone.utc)
    delivery.claimed_at = None
    delivery.claim_token = None
    await db.commit()


async def mark_accepted(
    db: AsyncSession,
    delivery: DocumentEmailDelivery,
    *,
    claim_token: str | None = None,
) -> bool:
    if claim_token is not None:
        result = await db.execute(
            update(DocumentEmailDelivery)
            .where(
                DocumentEmailDelivery.id == delivery.id,
                DocumentEmailDelivery.claim_token == claim_token,
                DocumentEmailDelivery.status == "processing",
            )
            .values(
                status="accepted",
                accepted_at=datetime.now(timezone.utc),
                claimed_at=None,
                claim_token=None,
                last_error=None,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            await db.rollback()
            return False
        await db.commit()
        return True
    delivery.status = "accepted"
    delivery.accepted_at = datetime.now(timezone.utc)
    delivery.claimed_at = None
    delivery.claim_token = None
    delivery.last_error = None
    await db.commit()
    return True


async def mark_failed(
    db: AsyncSession,
    delivery: DocumentEmailDelivery,
    error: str,
    *,
    claim_token: str | None = None,
) -> bool:
    attempt_index = max(1, int(delivery.attempts)) - 1
    delay = RETRY_DELAYS[min(attempt_index, len(RETRY_DELAYS) - 1)]
    next_status = "failed" if delivery.attempts >= MAX_ATTEMPTS else "pending"
    next_attempt_at = datetime.now(timezone.utc) + delay
    if claim_token is not None:
        result = await db.execute(
            update(DocumentEmailDelivery)
            .where(
                DocumentEmailDelivery.id == delivery.id,
                DocumentEmailDelivery.claim_token == claim_token,
                DocumentEmailDelivery.status == "processing",
            )
            .values(
                status=next_status,
                next_attempt_at=next_attempt_at,
                claimed_at=None,
                claim_token=None,
                last_error=error[:100],
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            await db.rollback()
            return False
        await db.commit()
        return True
    delivery.status = next_status
    delivery.next_attempt_at = next_attempt_at
    delivery.claimed_at = None
    delivery.claim_token = None
    delivery.last_error = error[:100]
    await db.commit()
    return True


async def mark_permanent_failure(
    db: AsyncSession,
    delivery: DocumentEmailDelivery,
    error: str,
    *,
    claim_token: str | None = None,
) -> bool:
    if claim_token is not None:
        result = await db.execute(
            update(DocumentEmailDelivery)
            .where(
                DocumentEmailDelivery.id == delivery.id,
                DocumentEmailDelivery.claim_token == claim_token,
                DocumentEmailDelivery.status == "processing",
            )
            .values(
                status="failed",
                attempts=MAX_ATTEMPTS,
                claimed_at=None,
                claim_token=None,
                last_error=error[:100],
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            await db.rollback()
            return False
        await db.commit()
        return True
    delivery.status = "failed"
    delivery.attempts = max(int(delivery.attempts), MAX_ATTEMPTS)
    delivery.claimed_at = None
    delivery.claim_token = None
    delivery.last_error = error[:100]
    await db.commit()
    return True


def public_status(delivery: DocumentEmailDelivery) -> dict[str, object]:
    """Expose state without recipient addresses, provider IDs, or error text."""
    return {
        "id": str(delivery.id),
        "status": delivery.status,
        "attempts": int(delivery.attempts),
        "retryable": delivery.status in {"pending", "failed"} and delivery.attempts < MAX_ATTEMPTS,
        "accepted_at": delivery.accepted_at.isoformat() if delivery.accepted_at else None,
    }

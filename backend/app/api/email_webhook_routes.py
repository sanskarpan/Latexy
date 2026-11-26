"""Signed Resend delivery/bounce/complaint webhook ingestion.

Resend retries a webhook when the endpoint answers 5xx. Invalid signatures,
malformed payloads and unknown event types deliberately answer 2xx/4xx so they
cannot create an infinite retry loop. Only a transient persistence failure is
reported as retryable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.connection import get_db
from ..services.email_health_service import EmailWebhookError, ingest_resend_event

logger = get_logger(__name__)

router = APIRouter(tags=["webhooks", "email"])


@router.post("/webhooks/resend")
@router.post("/email/webhooks/resend")
async def resend_email_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Verify and persist one Resend email event using the raw request body."""
    try:
        payload = await request.body()
        result = await ingest_resend_event(db, payload, dict(request.headers))
    except EmailWebhookError as exc:
        if str(exc) == "webhook_verification_unconfigured":
            # Fail closed. An unconfigured endpoint must never accept unsigned
            # delivery data; operators see the 503 and configure the secret.
            logger.error("Resend webhook secret is not configured")
            raise HTTPException(status_code=503, detail="Webhook verification is not configured")
        logger.warning("Resend webhook rejected", extra={"reason": str(exc)})
        raise HTTPException(status_code=400, detail="Invalid webhook") from None
    except Exception as exc:
        # A database outage is transient: let Resend retry the same signed event.
        logger.error("Resend webhook processing failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Webhook processing unavailable") from exc

    return {
        "status": result.get("status", "processed"),
        "event_type": result.get("event_type"),
    }

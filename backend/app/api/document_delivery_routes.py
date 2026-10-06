"""Authenticated delivery of a user's own compiled PDF (B50d).

This endpoint intentionally sends only to the authenticated account's verified
email address. It does not accept arbitrary recipients, filesystem paths, or
sender identity. The request attempts delivery synchronously and persists a
bounded retry record for worker/Modal recovery after provider or process failure.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import Compilation, DocumentEmailDelivery, Resume, User
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..middleware.rate_limiting import client_ip_id
from ..services.document_delivery_service import (
    MAX_ATTEMPTS,
    claim_delivery,
    get_or_create_delivery,
    make_retryable,
    mark_accepted,
    mark_failed,
    public_status,
)
from ..services.email_service import (
    MAX_EMAIL_ATTACHMENT_BYTES,
    EmailAttachment,
    email_service,
    render_document_delivery_email,
)
from ..utils.bounded_io import read_file_bounded
from ..utils.file_utils import get_job_files
from ..utils.uuid_guard import ensure_uuid

logger = get_logger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

_EMAIL_RE = re.compile(r"^[^@\s\x00-\x1f\x7f]+@[^@\s\x00-\x1f\x7f]+\.[^@\s\x00-\x1f\x7f]+$")
_MAX_PDF_BYTES = MAX_EMAIL_ATTACHMENT_BYTES
_DELIVERY_LIMIT = 3
_DELIVERY_WINDOW_SECONDS = 3600
_IP_DELIVERY_LIMIT = 30
_LUA_INCR_EXPIRE_PAIR = """
local user_count = redis.call('INCR', KEYS[1])
if user_count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
if user_count > tonumber(ARGV[2]) then
  return {user_count, 0}
end
local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[1])
end
return {user_count, ip_count}
"""


class EmailDocumentRequest(BaseModel):
    """Empty request: recipient and sender are always server-derived."""

    model_config = ConfigDict(extra="forbid")


class EmailDocumentResponse(BaseModel):
    status: Literal["accepted"]
    recipient: Literal["verified_account_email"]
    retry_behavior: Literal["provider_idempotent", "smtp_best_effort"]


def _rate_limit_digest(value: str) -> str:
    """Keep credential/network identifiers out of Redis key text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def _check_delivery_rate_limit(request: Request, user_id: str) -> None:
    """Apply atomic per-account and secondary spoof-resistant IP mail limits."""
    user_key = f"cache:ratelimit:document-email:user:{_rate_limit_digest(user_id)}"
    ip_key = f"cache:ratelimit:document-email:ip:{_rate_limit_digest(client_ip_id(request))}"
    try:
        from ..core.redis import get_redis_cache_client

        redis = await get_redis_cache_client()
        counts = await redis.eval(
            _LUA_INCR_EXPIRE_PAIR,
            2,
            user_key,
            ip_key,
            _DELIVERY_WINDOW_SECONDS,
            _DELIVERY_LIMIT,
        )
        user_count, ip_count = (int(value) for value in counts)
    except Exception as exc:  # pragma: no cover - cache outage
        logger.warning("Document email rate-limit check failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable") from exc
    if user_count > _DELIVERY_LIMIT or ip_count > _IP_DELIVERY_LIMIT:
        raise HTTPException(status_code=429, detail="Too many document emails; please try again later")


def _safe_verified_email(user: User) -> str:
    address = (user.email or "").strip().lower()
    if not user.email_verified or not _EMAIL_RE.fullmatch(address):
        raise HTTPException(status_code=422, detail="A verified email address is required")
    return address


def _safe_temp_pdf(compilation: Compilation) -> Optional[Path]:
    """Return only a generated job PDF beneath the configured temp directory."""
    try:
        _, candidate, _ = get_job_files(str(compilation.job_id))
    except HTTPException:
        return None
    return candidate


async def _owned_compiled_pdf(
    resume_id: str,
    user_id: str,
    db: AsyncSession,
    *,
    compilation_id: str | None = None,
    max_bytes: int = MAX_EMAIL_ATTACHMENT_BYTES,
    too_large_detail: str = "Compiled PDF is too large to email",
) -> tuple[Resume, Compilation, bytes]:
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")

    compilation_query = select(Compilation).where(
        Compilation.resume_id == resume_id,
        Compilation.user_id == user_id,
        Compilation.status == "completed",
    )
    if compilation_id is not None:
        compilation_query = compilation_query.where(Compilation.id == compilation_id)
    else:
        compilation_query = compilation_query.order_by(Compilation.created_at.desc()).limit(1)
    result = await db.execute(compilation_query)
    compilation = result.scalar_one_or_none()
    if compilation is None:
        raise HTTPException(status_code=422, detail="No completed PDF is available")
    if compilation.pdf_size is not None and compilation.pdf_size > max_bytes:
        raise HTTPException(status_code=413, detail=too_large_detail)

    pdf_bytes: Optional[bytes] = None
    if compilation.pdf_path:
        try:
            from ..services.storage_service import download_bytes

            pdf_bytes = await run_in_threadpool(
                download_bytes, compilation.pdf_path, max_bytes
            )
        except Exception as exc:  # pragma: no cover - provider-specific storage failure
            logger.warning("Compiled PDF storage lookup failed (%s)", type(exc).__name__)

    if not pdf_bytes:
        temp_pdf = _safe_temp_pdf(compilation)
        if temp_pdf and temp_pdf.is_file():
            try:
                if temp_pdf.stat().st_size <= max_bytes:
                    pdf_bytes = await run_in_threadpool(read_file_bounded, temp_pdf, max_bytes)
            except OSError:
                pdf_bytes = None

    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="Compiled PDF is unavailable; please recompile")
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=too_large_detail)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Compiled artifact is not a PDF")
    return resume, compilation, pdf_bytes


@router.post(
    "/{resume_id}/email",
    response_model=EmailDocumentResponse,
    dependencies=[Depends(require_feature("exports"))],
)
async def email_compiled_document(
    request: Request,
    resume_id: str,
    body: EmailDocumentRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> EmailDocumentResponse:
    """Email the latest completed, owned PDF to the user's verified address."""
    del body  # Deliberately empty; prevents recipient/sender injection.
    await _check_delivery_rate_limit(request, user_id)
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    recipient = _safe_verified_email(user)
    resume, compilation, pdf_bytes = await _owned_compiled_pdf(resume_id, user_id, db)
    delivery = await get_or_create_delivery(
        db,
        user_id=user_id,
        resume_id=str(resume.id),
        compilation_id=str(compilation.id),
        recipient_email=recipient,
    )
    if delivery.status == "accepted":
        return EmailDocumentResponse(
            status="accepted",
            recipient="verified_account_email",
            retry_behavior=(
                "provider_idempotent" if delivery.provider == "resend" else "smtp_best_effort"
            ),
        )
    if delivery.status == "failed":
        if delivery.attempts >= MAX_ATTEMPTS:
            raise HTTPException(status_code=503, detail="Email delivery exhausted retries; please try again later")
        await make_retryable(db, delivery)
    delivery = await claim_delivery(db, str(delivery.id))
    if delivery is None:
        raise HTTPException(status_code=409, detail="This document email is already being processed")
    html_body, text_body = render_document_delivery_email(user.name or "there", resume.title)

    # One deterministic key makes repeated clicks for the same compilation
    # dedupe with Resend. Generic SMTP cannot promise deduplication, so that
    # behavior is returned explicitly to the UI.
    claim_token = delivery.claim_token
    sent = await email_service.send_email(
        to=delivery.recipient_email,
        subject="Your compiled resume from Latexy",
        html_body=html_body,
        text_body=text_body,
        idempotency_key=delivery.idempotency_key,
        attachments=(EmailAttachment("resume.pdf", pdf_bytes, "application/pdf"),),
    )
    if not sent:
        await mark_failed(db, delivery, "provider_rejected", claim_token=claim_token)
        raise HTTPException(status_code=503, detail="Email provider did not accept the document; please retry")
    await mark_accepted(db, delivery, claim_token=claim_token)

    retry_behavior: Literal["provider_idempotent", "smtp_best_effort"] = (
        "provider_idempotent" if settings.EMAIL_PROVIDER == "resend" else "smtp_best_effort"
    )
    return EmailDocumentResponse(
        status="accepted",
        recipient="verified_account_email",
        retry_behavior=retry_behavior,
    )


@router.get(
    "/{resume_id}/email/status",
    dependencies=[Depends(require_feature("exports"))],
)
async def email_compiled_document_status(
    resume_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> dict[str, object]:
    """Return durable provider-acceptance state for the latest email request."""
    ensure_uuid(resume_id, "Resume not found")
    result = await db.execute(
        select(DocumentEmailDelivery)
        .where(DocumentEmailDelivery.resume_id == resume_id, DocumentEmailDelivery.user_id == user_id)
        .order_by(DocumentEmailDelivery.created_at.desc())
        .limit(1)
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise HTTPException(status_code=404, detail="No document email has been requested")
    return public_status(delivery)


@router.post(
    "/{resume_id}/email/retry",
    response_model=EmailDocumentResponse,
    dependencies=[Depends(require_feature("exports"))],
)
async def retry_email_compiled_document(
    request: Request,
    resume_id: str,
    body: EmailDocumentRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_required),
) -> EmailDocumentResponse:
    """Explicitly retry the latest failed delivery using the same idempotency key."""
    return await email_compiled_document(request, resume_id, body, db, user_id)

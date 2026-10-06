"""Authenticated, review-only parsing of one user-forwarded status email."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ..middleware.entitlements import require_feature
from ..services.email_status_parser_service import (
    MAX_RAW_EMAIL_BYTES,
    EmailStatusParseError,
    EmailStatusParseResult,
    parse_forwarded_application_email,
)

router = APIRouter(prefix="/tracker/email-status", tags=["tracker"])


class EmailStatusParseRequest(BaseModel):
    """Exactly one raw RFC 5322 message; no mailbox identifiers or options."""

    model_config = ConfigDict(extra="forbid")

    # The encoded-byte limit is enforced in the handler.  A character-count
    # validator would reject/accept a different set of Unicode payloads.
    raw_email: str = Field(...)


class StatusEvidenceResponse(BaseModel):
    signal: str
    source: str


class EmailStatusParseResponse(BaseModel):
    """Only bounded, canonical review data leaves this endpoint."""

    status: str | None
    company: str | None
    role: str | None
    confidence: float
    company_confidence: float
    role_confidence: float
    evidence: list[StatusEvidenceResponse]
    requires_review: bool


def _response(result: EmailStatusParseResult) -> EmailStatusParseResponse:
    return EmailStatusParseResponse(
        status=result.status,
        company=result.company,
        role=result.role,
        confidence=result.confidence,
        company_confidence=result.company_confidence,
        role_confidence=result.role_confidence,
        evidence=[StatusEvidenceResponse(signal=item.signal, source=item.source) for item in result.evidence],
        requires_review=True,
    )


@router.post("/parse", response_model=EmailStatusParseResponse)
async def parse_email_status(
    body: EmailStatusParseRequest,
    _user_id: str = Depends(require_feature("application_tracker")),
) -> EmailStatusParseResponse:
    """Parse one forwarded message without mailbox access or tracker writes."""

    try:
        encoded_size = len(body.raw_email.encode("utf-8", "strict"))
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid forwarded email") from exc
    if encoded_size > MAX_RAW_EMAIL_BYTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid forwarded email")
    try:
        result = parse_forwarded_application_email(body.raw_email)
    except EmailStatusParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid forwarded email") from exc
    return _response(result)


__all__ = [
    "EmailStatusParseRequest",
    "EmailStatusParseResponse",
    "StatusEvidenceResponse",
    "parse_email_status",
    "router",
]

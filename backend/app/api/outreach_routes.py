"""Editable outreach/referral draft generation for tracker applications.

Only user-owned tracker data is used.  This endpoint does not discover
recruiters, scrape external sites, send messages, or save generated content.
"""

from __future__ import annotations

import asyncio

import openai
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.connection import get_db
from ..database.models import JobApplication, TrackerContact
from ..middleware.auth_middleware import get_current_user_required
from ..middleware.entitlements import require_feature
from ..services.outreach_service import (
    OutreachDraftContent,
    build_outreach_messages,
    parse_outreach_response,
    stage_label,
)
from ..utils.uuid_guard import ensure_uuid
from .ai_routes import _charge_ai_assist, _meter_identity, _resolve_ai_api_key

logger = get_logger(__name__)

router = APIRouter(prefix="/outreach", tags=["outreach"])


class OutreachDraftRequest(BaseModel):
    """Inputs for one transient draft; no message body is persisted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    application_id: str
    contact_id: str | None = None
    channel: str = Field("email", pattern=r"^(email|linkedin)$")
    purpose: str = Field(
        "referral_request",
        pattern=r"^(referral_request|follow_up|thank_you|networking)$",
    )
    additional_context: str | None = Field(None, max_length=2_000)


class OutreachDraftResponse(BaseModel):
    """An editable/copyable draft and the source scope used to create it."""

    application_id: str
    contact_id: str | None
    recipient_name: str | None
    recipient_role: str | None
    company_name: str
    role_title: str
    stage: str
    channel: str
    purpose: str
    subject: str
    body: str
    placeholders: list[str]
    editable: bool = True
    sent: bool = False


def _application_facts(application: JobApplication) -> dict[str, str | None]:
    """Select only tracker fields relevant to an outreach draft."""

    return {
        "company_name": application.company_name,
        "role_title": application.role_title,
        "status": application.status,
        # These are user-entered tracker facts.  The prompt treats them as data.
        "job_description": (application.job_description_text or "")[:12_000] or None,
        "notes": (application.notes or "")[:3_000] or None,
    }


def _contact_facts(contact: TrackerContact | None) -> dict[str, str | None] | None:
    if contact is None:
        return None
    # Do not pass contact email/phone to the provider: neither is needed to
    # write a draft, and keeping it out of the provider payload reduces PII.
    return {"name": contact.name, "role_title": contact.role_title}


@router.post(
    "/drafts",
    response_model=OutreachDraftResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_feature("application_tracker"))],
)
async def generate_outreach_draft(
    body: OutreachDraftRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """Generate one stage-aware, editable outreach draft from owned data."""

    ensure_uuid(body.application_id, "Application not found")
    application = (
        await db.execute(
            select(JobApplication).where(
                JobApplication.id == body.application_id,
                JobApplication.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    contact = None
    if body.contact_id:
        ensure_uuid(body.contact_id, "Contact not found")
        contact = (
            await db.execute(
                select(TrackerContact).where(
                    TrackerContact.id == body.contact_id,
                    TrackerContact.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if contact is None:
            raise HTTPException(status_code=404, detail="Contact not found")

    resolved = await _resolve_ai_api_key(db, user_id, _meter_identity(http_request, user_id))
    if not resolved:
        raise HTTPException(
            status_code=503,
            detail="Outreach drafting is temporarily unavailable. Configure an OpenAI key and retry.",
        )

    quota_ticket = await _charge_ai_assist(db, user_id, resolved)
    stage = stage_label(application.status)
    system_prompt, user_prompt = build_outreach_messages(
        application_facts=_application_facts(application),
        contact_facts=_contact_facts(contact),
        stage=stage,
        channel=body.channel,
        purpose=body.purpose,
        additional_context=body.additional_context,
    )

    try:
        client = openai.AsyncOpenAI(api_key=resolved.key)
        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1_200,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content or ""
        draft: OutreachDraftContent = parse_outreach_response(raw_content)
        return OutreachDraftResponse(
            application_id=application.id,
            contact_id=contact.id if contact else None,
            recipient_name=contact.name if contact else None,
            recipient_role=contact.role_title if contact else None,
            company_name=application.company_name,
            role_title=application.role_title,
            stage=stage,
            channel=body.channel,
            purpose=body.purpose,
            subject=draft.subject,
            body=draft.body,
            placeholders=draft.placeholders,
        )
    except HTTPException:
        raise
    except asyncio.CancelledError:
        # Client disconnects and worker shutdowns must not permanently consume
        # an assist that never produced a response. Shield the compensating
        # write from the cancellation already in flight, then preserve the
        # cancellation so request shutdown semantics remain intact.
        if quota_ticket is not None:
            try:
                await asyncio.shield(_refund_quota(quota_ticket))
            except Exception as refund_exc:
                logger.error(
                    "Outreach draft cancellation refund failed (exception_type=%s)",
                    type(refund_exc).__name__,
                )
        raise
    except Exception as exc:
        if quota_ticket is not None:
            await _refund_quota(quota_ticket)
        # Never log provider exceptions verbatim: SDK errors can include
        # request payloads, which may contain user-entered tracker notes.
        logger.warning(
            "Outreach draft provider response rejected (exception_type=%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="AI provider did not return a valid outreach draft. Please retry.",
        ) from exc


async def _refund_quota(ticket: object) -> None:
    """Refund a charged assist without coupling tests to entitlement internals."""

    from ..services.entitlement_service import entitlement_service

    await entitlement_service.refund_quota(ticket)

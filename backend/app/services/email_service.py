"""
Email service for Feature 19 — Email Notifications.

Supports Resend (via httpx) and SMTP. All sends are guarded by the
EMAIL_ENABLED master toggle — when False, every call is a no-op.
"""

from __future__ import annotations

import asyncio
import base64
import smtplib
import ssl
from dataclasses import dataclass
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Optional, Sequence
from urllib.parse import quote

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

MAX_EMAIL_ATTACHMENT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class EmailAttachment:
    """A bounded, already-authorized attachment for a transactional email."""

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


class EmailService:
    """Send transactional emails via Resend or SMTP."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        attachments: Optional[Sequence[EmailAttachment]] = None,
    ) -> bool:
        """Send an email. Returns True if sent, False if skipped or failed."""
        if not settings.EMAIL_ENABLED:
            logger.debug("Email disabled — skipping send")
            return False

        safe_attachments = tuple(attachments or ())
        try:
            self._validate_attachments(safe_attachments)
        except (TypeError, ValueError):
            logger.warning("Email attachment validation failed")
            return False

        try:
            if settings.EMAIL_PROVIDER == "resend":
                return await self._send_via_resend(
                    to, subject, html_body, text_body, idempotency_key, safe_attachments
                )
            elif settings.EMAIL_PROVIDER == "smtp":
                # Resend's SMTP gateway honors the idempotency header; other
                # SMTP relays may ignore it. A timeout after DATA can therefore
                # result in one duplicate on a later retry with non-Resend SMTP.
                if idempotency_key:
                    logger.debug("SMTP transport idempotency depends on relay support")
                smtp_args = (to, subject, html_body, text_body)
                if idempotency_key:
                    if safe_attachments:
                        return await asyncio.to_thread(
                            self._send_via_smtp,
                            *smtp_args,
                            idempotency_key,
                            safe_attachments,
                        )
                    return await asyncio.to_thread(self._send_via_smtp, *smtp_args, idempotency_key)
                if safe_attachments:
                    return await asyncio.to_thread(
                        self._send_via_smtp, *smtp_args, None, safe_attachments
                    )
                return await asyncio.to_thread(self._send_via_smtp, *smtp_args)
            else:
                logger.warning(f"Unknown EMAIL_PROVIDER: {settings.EMAIL_PROVIDER!r}")
                return False
        except Exception as exc:
            # Provider/network errors and recipient/subject values may contain
            # credentials or personal data. Keep operational logs metadata-only.
            logger.error("Email send failed (%s)", type(exc).__name__)
            return False

    async def _send_via_resend(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
        idempotency_key: Optional[str] = None,
        attachments: Sequence[EmailAttachment] = (),
    ) -> bool:
        if not settings.RESEND_API_KEY:
            logger.warning("RESEND_API_KEY not set — cannot send email")
            return False

        import httpx

        payload: dict = {
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
            "to": [to],
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            payload["text"] = text_body
        if attachments:
            payload["attachments"] = [
                {
                    "filename": attachment.filename,
                    "content": base64.b64encode(attachment.content).decode("ascii"),
                }
                for attachment in attachments
            ]

        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {"Authorization": f"Bearer {settings.RESEND_API_KEY}"}
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            resp = await client.post(
                "https://api.resend.com/emails",
                headers=headers,
                json=payload,
            )
            if resp.status_code in (200, 201):
                logger.info("Email sent via Resend")
                return True
            else:
                logger.error("Resend returned HTTP %s", resp.status_code)
                return False

    def _send_via_smtp(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
        idempotency_key: Optional[str] = None,
        attachments: Sequence[EmailAttachment] = (),
    ) -> bool:
        if not settings.SMTP_HOST:
            logger.warning("SMTP_HOST not set — cannot send email")
            return False

        msg = MIMEMultipart("mixed" if attachments else "alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to
        if idempotency_key:
            # Resend's SMTP gateway honors this header. Other SMTP relays may
            # ignore it, so SMTP delivery remains best-effort on retry.
            msg["Resend-Idempotency-Key"] = idempotency_key

        body = MIMEMultipart("alternative") if attachments else msg
        if text_body:
            body.attach(MIMEText(text_body, "plain"))
        body.attach(MIMEText(html_body, "html"))
        if attachments:
            msg.attach(body)
            for attachment in attachments:
                major, _, minor = attachment.content_type.partition("/")
                part = MIMEBase(major or "application", minor or "octet-stream")
                part.set_payload(attachment.content)
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", "attachment", filename=attachment.filename
                )
                msg.attach(part)

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            # smtplib reports per-recipient refusal as a return dictionary
            # rather than raising.  With one recipient, any refused address
            # means the provider did not accept this delivery and must remain
            # retryable in the durable delivery state machine.
            refused = server.sendmail(settings.EMAIL_FROM, to, msg.as_string())
            if isinstance(refused, dict) and refused:
                logger.warning("SMTP provider refused recipient(s)")
                return False

        logger.info("Email sent via SMTP")
        return True

    @staticmethod
    def _validate_attachments(attachments: Sequence[EmailAttachment]) -> None:
        if len(attachments) > 3:
            raise ValueError("too many email attachments")
        for attachment in attachments:
            if not isinstance(attachment, EmailAttachment):
                raise TypeError("invalid email attachment")
            if (
                not attachment.filename
                or len(attachment.filename) > 255
                or any(char in attachment.filename for char in ("/", "\\", "\r", "\n"))
            ):
                raise ValueError("invalid attachment filename")
            if not isinstance(attachment.content, bytes):
                raise TypeError("attachment content must be bytes")
            if len(attachment.content) > MAX_EMAIL_ATTACHMENT_BYTES:
                raise ValueError("attachment too large")
            major, separator, minor = attachment.content_type.partition("/")
            if not separator or not major or not minor or any(
                char in attachment.content_type for char in ("\r", "\n", ";")
            ):
                raise ValueError("invalid attachment content type")


# ── HTML templates ────────────────────────────────────────────────────────────

def render_job_completed_email(
    user_name: str,
    job_type: str,
    ats_score: Optional[float],
    resume_url: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body) for a job-completed notification."""
    safe_user_name = escape(user_name)
    job_label = "optimization" if job_type == "llm_optimization" else "compilation"
    score_line = f"ATS score: <strong>{ats_score:.0f}/100</strong>" if ats_score else ""
    score_text = f"ATS score: {ats_score:.0f}/100" if ats_score else ""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">Your resume {job_label} is complete 🎉</h2>
    <p>Hi {safe_user_name},</p>
    <p>Your resume {job_label} finished successfully. {score_line}</p>
    <p style="margin-top:24px">
      <a href="{resume_url}" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">
        View your resume
      </a>
    </p>
    <p style="color:#71717a;font-size:12px;margin-top:28px">
      You're receiving this because you have job completion emails enabled.<br>
      <a href="{settings.FRONTEND_URL}/settings" style="color:#a78bfa">Manage preferences</a>
    </p>
  </div>
</body>
</html>"""

    text = (
        f"Your resume {job_label} is complete!\n\n"
        f"Hi {user_name},\n\n"
        f"Your resume {job_label} finished successfully. {score_text}\n\n"
        f"View your resume: {resume_url}\n\n"
        f"Manage notification preferences: {settings.FRONTEND_URL}/settings"
    )
    return html, text


def render_job_failed_email(
    user_name: str,
    job_type: str,
    workspace_url: str,
) -> tuple[str, str]:
    """Return a generic failure notice without exposing worker error details."""
    safe_user_name = escape(user_name)
    job_label = {
        "llm_optimization": "resume optimization",
        "latex_compilation": "resume compilation",
        "compilation": "resume compilation",
        "ats_deep": "ATS analysis",
        "cover_letter": "cover letter generation",
        "interview_prep": "interview preparation",
        "document_conversion": "document conversion",
    }.get(job_type, "resume job")

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#f87171;margin-top:0">Your {job_label} did not finish</h2>
    <p>Hi {safe_user_name},</p>
    <p>Latexy could not finish your {job_label}. Open your workspace to review the job and try again.</p>
    <p style="margin-top:24px">
      <a href="{workspace_url}" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">
        Open your workspace
      </a>
    </p>
    <p style="color:#71717a;font-size:12px;margin-top:28px">
      No resume content or internal error details are included in this email.<br>
      <a href="{settings.FRONTEND_URL}/settings" style="color:#a78bfa">Manage preferences</a>
    </p>
  </div>
</body>
</html>"""

    text = (
        f"Your {job_label} did not finish\n\n"
        f"Hi {user_name},\n\n"
        f"Latexy could not finish your {job_label}. "
        "Open your workspace to review the job and try again.\n\n"
        f"Open your workspace: {workspace_url}\n\n"
        "No resume content or internal error details are included in this email.\n"
        f"Manage notification preferences: {settings.FRONTEND_URL}/settings"
    )
    return html, text


def render_share_viewed_email(
    user_name: str,
    resume_title: str,
    resume_url: str,
    country_code: Optional[str] = None,
    referrer: Optional[str] = None,
) -> tuple[str, str]:
    """Return a privacy-minimized notification for a newly recorded share view."""
    safe_user_name = escape(user_name)
    safe_title = escape(resume_title or "Untitled resume")
    detail_parts = []
    if country_code:
        detail_parts.append(f"country: {escape(country_code)}")
    if referrer:
        detail_parts.append(f"referrer: {escape(referrer)}")
    detail_html = (
        f"<p style=\"color:#a1a1aa;font-size:13px\">View details: {', '.join(detail_parts)}</p>"
        if detail_parts else ""
    )
    detail_text = f"\nView details: {', '.join(detail_parts)}" if detail_parts else ""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">Your shared resume was viewed</h2>
    <p>Hi {safe_user_name},</p>
    <p>A new visitor viewed <strong>{safe_title}</strong>.</p>
    {detail_html}
    <p style="margin-top:24px">
      <a href="{resume_url}" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">
        Open your resume
      </a>
    </p>
    <p style="color:#71717a;font-size:12px;margin-top:28px">
      Repeat views from the same browser are debounced.<br>
      <a href="{settings.FRONTEND_URL}/settings" style="color:#a78bfa">Manage preferences</a>
    </p>
  </div>
</body>
</html>"""

    text = (
        "Your shared resume was viewed\n\n"
        f"Hi {user_name},\n\n"
        f"A new visitor viewed {resume_title or 'Untitled resume'}.{detail_text}\n\n"
        f"Open your resume: {resume_url}\n\n"
        f"Manage notification preferences: {settings.FRONTEND_URL}/settings"
    )
    return html, text


def render_document_delivery_email(user_name: str, resume_title: str) -> tuple[str, str]:
    """Return a minimal message for a user-requested compiled PDF delivery."""
    safe_user_name = escape(user_name or "there")
    safe_title = escape(resume_title or "your resume")
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">Your compiled resume is attached</h2>
    <p>Hi {safe_user_name},</p>
    <p>The compiled PDF for <strong>{safe_title}</strong> is attached to this email.</p>
    <p style="color:#71717a;font-size:12px;margin-top:28px">
      This message was sent because you requested the document from Latexy.<br>
      Manage notification preferences at <a href="{settings.FRONTEND_URL}/settings" style="color:#a78bfa">Latexy settings</a>.
    </p>
  </div>
</body>
</html>"""
    text = (
        "Your compiled resume is attached\n\n"
        f"Hi {user_name or 'there'},\n\n"
        f"The compiled PDF for {resume_title or 'your resume'} is attached to this email.\n\n"
        "This message was sent because you requested the document from Latexy.\n"
        f"Manage notification preferences: {settings.FRONTEND_URL}/settings"
    )
    return html, text


def render_comment_mention_email(
    resume_url: str,
) -> tuple[str, str]:
    """Render a privacy-conscious notification for a resolved @mention.

    The comment body is intentionally omitted. Access can be revoked between
    the final ACL check and provider I/O, so email must not disclose private
    comment text in that unavoidable TOCTOU window.
    """
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">You were mentioned in a resume comment</h2>
    <p>A collaborator mentioned you in a Latexy resume comment.</p>
    <p><a href="{escape(resume_url, quote=True)}" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">Open comment</a></p>
    <p style="color:#71717a;font-size:12px;margin-top:28px"><a href="{escape(settings.FRONTEND_URL, quote=True)}/settings" style="color:#a78bfa">Manage notification preferences</a></p>
  </div>
</body></html>"""
    text = (
        "You were mentioned in a resume comment\n\n"
        "A collaborator mentioned you in a Latexy resume comment.\n\n"
        f"Open comment: {resume_url}\n\n"
        f"Manage notification preferences: {settings.FRONTEND_URL}/settings"
    )
    return html, text


def render_weekly_digest_email(
    user_name: str,
    resume_count: int,
    compilation_count: int,
    avg_ats_score: Optional[float],
    stale_resumes: Optional[list] = None,
) -> tuple[str, str]:
    """Returns (html_body, text_body) for a weekly digest email.

    Args:
        user_name: Display name for the recipient.
        resume_count: New resumes created this week.
        compilation_count: Compilations run this week.
        avg_ats_score: Average ATS score for the week, or None.
        stale_resumes: List of dicts with ``id``, ``title``, ``days_since_updated``
                       for resumes not updated in 90+ days (very_stale).
    """
    safe_user_name = escape(user_name)
    score_line = f"<li>Average ATS score: <strong>{avg_ats_score:.0f}/100</strong></li>" if avg_ats_score else ""
    score_text = f"Average ATS score: {avg_ats_score:.0f}/100\n" if avg_ats_score else ""

    # ── Stale resumes section ─────────────────────────────────────────────────
    stale_html = ""
    stale_text = ""
    if stale_resumes:
        rows = "\n".join(
            f'      <li style="margin-bottom:8px">'
            f'<strong>{escape(r["title"])}</strong> '
            f'<span style="color:#71717a">({r["days_since_updated"]} days without update)</span> — '
            f'<a href="{settings.FRONTEND_URL}/workspace/{quote(str(r["id"]), safe="")}/edit" '
            f'style="color:#fb923c;text-decoration:none">Update now →</a>'
            f"</li>"
            for r in stale_resumes
        )
        stale_html = f"""
    <div style="margin-top:24px;border:1px solid #3f3f46;border-radius:8px;padding:16px;background:#1c1c1f">
      <h3 style="color:#fb923c;margin-top:0;font-size:14px">⚠ Resumes that need your attention</h3>
      <p style="font-size:13px;color:#a1a1aa;margin-top:0">
        These resumes haven't been updated in 90+ days. Recruiters notice freshness!
      </p>
      <ul style="line-height:1.8;font-size:13px;padding-left:16px">
{rows}
      </ul>
    </div>"""

        stale_lines = "\n".join(
            f"  • {r['title']} ({r['days_since_updated']} days) — "
            f"{settings.FRONTEND_URL}/workspace/{r['id']}/edit"
            for r in stale_resumes
        )
        stale_text = (
            "\n\n⚠ Resumes that need your attention (90+ days without update):\n"
            + stale_lines
        )

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">Your weekly Latexy summary</h2>
    <p>Hi {safe_user_name}, here's what you achieved this week:</p>
    <ul style="line-height:1.8">
      <li>Resumes: <strong>{resume_count}</strong></li>
      <li>Compilations: <strong>{compilation_count}</strong></li>
      {score_line}
    </ul>{stale_html}
    <p style="margin-top:24px">
      <a href="{settings.FRONTEND_URL}/workspace" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:600">
        Open Latexy
      </a>
    </p>
    <p style="color:#71717a;font-size:12px;margin-top:28px">
      <a href="{settings.FRONTEND_URL}/settings" style="color:#a78bfa">Unsubscribe from weekly digest</a>
    </p>
  </div>
</body>
</html>"""

    text = (
        f"Your weekly Latexy summary\n\n"
        f"Hi {user_name}, here's what you achieved this week:\n"
        f"Resumes: {resume_count}\n"
        f"Compilations: {compilation_count}\n"
        f"{score_text}"
        f"{stale_text}\n\n"
        f"Open Latexy: {settings.FRONTEND_URL}/workspace\n\n"
        f"Unsubscribe: {settings.FRONTEND_URL}/settings"
    )
    return html, text


# Singleton
email_service = EmailService()

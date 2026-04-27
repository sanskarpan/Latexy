"""
Email service for Feature 19 — Email Notifications.

Supports Resend (via httpx) and SMTP. All sends are guarded by the
EMAIL_ENABLED master toggle — when False, every call is a no-op.
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Optional
from urllib.parse import quote

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """Send transactional emails via Resend or SMTP."""

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
    ) -> bool:
        """Send an email. Returns True if sent, False if skipped or failed."""
        if not settings.EMAIL_ENABLED:
            logger.debug(f"Email disabled — skipping: {subject!r} → {to}")
            return False

        try:
            if settings.EMAIL_PROVIDER == "resend":
                return await self._send_via_resend(to, subject, html_body, text_body)
            elif settings.EMAIL_PROVIDER == "smtp":
                return self._send_via_smtp(to, subject, html_body, text_body)
            else:
                logger.warning(f"Unknown EMAIL_PROVIDER: {settings.EMAIL_PROVIDER!r}")
                return False
        except Exception as exc:
            logger.error(f"Email send failed to {to}: {exc}")
            return False

    async def _send_via_resend(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
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

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
            if resp.status_code in (200, 201):
                logger.info(f"Email sent via Resend: {subject!r} → {to}")
                return True
            else:
                logger.error(f"Resend returned {resp.status_code}: {resp.text[:200]}")
                return False

    def _send_via_smtp(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: Optional[str],
    ) -> bool:
        if not settings.SMTP_HOST:
            logger.warning("SMTP_HOST not set — cannot send email")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to

        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAIL_FROM, to, msg.as_string())

        logger.info(f"Email sent via SMTP: {subject!r} → {to}")
        return True


# ── HTML templates ────────────────────────────────────────────────────────────

def render_job_completed_email(
    user_name: str,
    job_type: str,
    ats_score: Optional[float],
    resume_url: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body) for a job-completed notification."""
    job_label = "optimization" if job_type == "llm_optimization" else "compilation"
    score_line = f"ATS score: <strong>{ats_score:.0f}/100</strong>" if ats_score else ""
    score_text = f"ATS score: {ats_score:.0f}/100" if ats_score else ""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0d0d0d;color:#e4e4e7;padding:32px;max-width:520px;margin:auto">
  <div style="background:#18181b;border:1px solid #27272a;border-radius:12px;padding:28px">
    <h2 style="color:#a78bfa;margin-top:0">Your resume {job_label} is complete 🎉</h2>
    <p>Hi {user_name},</p>
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
    <p>Hi {user_name}, here's what you achieved this week:</p>
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

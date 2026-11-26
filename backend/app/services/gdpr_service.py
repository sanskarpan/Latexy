"""GDPR data-subject workflow: signed exports, erasure and legal review.

Security model
--------------
* Export creation and download both require the caller's authenticated session;
  a signed token is a *second* factor that is only issued to the authenticated
  owner. A leaked token alone cannot download a bundle.
* Export tokens are HMAC-signed, bound to the request id and user id, expire
  after ``GDPR_EXPORT_TTL_MINUTES`` and are stored only as SHA-256 hashes.
* The downloaded bundle is itself signed (HMAC-SHA256 over canonical JSON), so
  the recipient can verify that the bytes were produced by this service.
* Erasure requires a fresh session (re-authentication), a typed confirmation,
  a verified email, an admin legal-review approval and no active legal hold.
* Financial, tax, fraud-investigation and append-only audit rows are retained;
  the job reports them explicitly instead of pretending deletion succeeded.
* No document content, token, password hash or provider credential is written
  to logs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.models import (
    GdprLegalHold,
    GdprRequest,
    GdprRequestEvent,
    User,
)
from ..middleware.auth_middleware import extract_session_token
from . import admin_approval_service
from .admin_audit_service import AdminActor, record_admin_audit
from .admin_user_service import mask_email

logger = get_logger(__name__)

EXPORT = "export"
DELETION = "deletion"
DELETION_CONFIRMATION = "DELETE MY ACCOUNT"

ACTIVE_DELETION_STATUSES = (
    "legal_review",
    "approved",
    "processing",
    "blocked",
    "failed",
)

#: Public, explicit retention exceptions. The erasure job never touches these
#: tables and lists each one in ``table_results`` with status ``retained``.
RETENTION_EXCEPTIONS: List[Dict[str, Any]] = [
    {
        "category": "invoices_and_payments",
        "tables": [
            "payments",
            "subscriptions",
            "payment_refunds",
            "admin_refund_requests",
            "billing_webhook_events",
        ],
        "reason": (
            "Tax, accounting and chargeback law requires retaining financial "
            "records. The rows stay linked to the anonymized account row; they "
            "contain no name, email, token or card data."
        ),
        "legal_basis": "legal_obligation",
    },
    {
        "category": "fraud_and_billing_integrity",
        "tables": ["quota_ledger_accounts", "quota_ledger_reservations"],
        "reason": (
            "Immutable quota and billing reconciliation evidence is kept to "
            "prevent abuse and resolve billing disputes. It stores only an "
            "opaque account id, dimension, period and counters."
        ),
        "legal_basis": "legitimate_interest_fraud_prevention",
    },
    {
        "category": "security_audit",
        "tables": [
            "admin_audit_log",
            "admin_approvals",
            "gdpr_requests",
            "gdpr_request_events",
            "gdpr_legal_holds",
        ],
        "reason": (
            "Append-only operator audit, approval and data-subject request history "
            "is required to demonstrate lawful processing and is never deleted."
        ),
        "legal_basis": "legal_obligation_accountability",
    },
    {
        "category": "legal_hold",
        "tables": ["*"],
        "reason": (
            "An active legal hold blocks the erasure job entirely until "
            "counsel releases it. No table is modified while a hold is active."
        ),
        "legal_basis": "legal_claim",
    },
    {
        "category": "referral_credit_ledger",
        "tables": ["referral_rewards"],
        "reason": (
            "Issued referral credits are financial ledger entries and are retained with the anonymized account link."
        ),
        "legal_basis": "legal_obligation",
    },
]

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
    "encrypted",
    "private_key",
    "refresh",
)

_MAX_EXPORT_ROWS = 1000
_MAX_RECENT_USAGE_ROWS = 200


class GdprError(Exception):
    """User-safe workflow error mapped to an HTTP response by the routers."""

    status_code = 400
    code = "gdpr_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class GdprNotFound(GdprError):
    status_code = 404
    code = "not_found"


class GdprForbidden(GdprError):
    status_code = 403
    code = "forbidden"


class GdprConflict(GdprError):
    status_code = 409
    code = "conflict"


class GdprExpired(GdprError):
    status_code = 410
    code = "export_expired"


class GdprUnprocessable(GdprError):
    status_code = 422
    code = "unprocessable"


class GdprLegalHoldBlocked(GdprError):
    status_code = 409
    code = "legal_hold"

    def __init__(self, request_payload: Mapping[str, Any]):
        super().__init__("An active legal hold blocks this deletion")
        self.request_payload = dict(request_payload)


@dataclass(frozen=True)
class DeletionStep:
    """One per-table erasure action with a human-readable report label."""

    key: str
    table: str
    action: str
    sql: str
    description: str


@dataclass(frozen=True)
class RetentionStep:
    table: str
    reason: str
    category: str


# Order matters: leaf rows first, then resume/application parents, credentials,
# and finally the users row. Every statement is scoped to the subject only.
DELETION_STEPS: tuple[DeletionStep, ...] = (
    DeletionStep(
        "document_email_deliveries",
        "document_email_deliveries",
        "delete",
        "DELETE FROM document_email_deliveries WHERE user_id = CAST(:uid AS uuid)",
        "Queued and delivered document email records",
    ),
    DeletionStep(
        "resume_pdf_imports",
        "resume_pdf_imports",
        "delete",
        "DELETE FROM resume_pdf_imports WHERE user_id = CAST(:uid AS uuid)",
        "Private original PDF imports",
    ),
    DeletionStep(
        "resume_comment_mentions",
        "resume_comment_mentions",
        "delete",
        "DELETE FROM resume_comment_mentions WHERE mentioned_user_id = CAST(:uid AS uuid)",
        "Collaborator mentions",
    ),
    DeletionStep(
        "resume_comments",
        "resume_comments",
        "delete",
        "DELETE FROM resume_comments WHERE author_id = CAST(:uid AS uuid)",
        "Authored resume comments",
    ),
    DeletionStep(
        "resume_review_comments",
        "resume_review_comments",
        "delete",
        "DELETE FROM resume_review_comments WHERE resume_id IN "
        "(SELECT id FROM resumes WHERE user_id = CAST(:uid AS uuid))",
        "Anonymous review comments on owned resumes",
    ),
    DeletionStep(
        "resume_collaborators",
        "resume_collaborators",
        "delete",
        "DELETE FROM resume_collaborators WHERE user_id = CAST(:uid AS uuid)",
        "Collaborator memberships",
    ),
    DeletionStep(
        "resume_collaborators_invited_by",
        "resume_collaborators",
        "update",
        "UPDATE resume_collaborators SET invited_by = NULL WHERE invited_by = CAST(:uid AS uuid)",
        "Collaborator invitation attribution",
    ),
    DeletionStep(
        "resume_element_versions",
        "resume_element_versions",
        "delete",
        "DELETE FROM resume_element_versions WHERE user_id = CAST(:uid AS uuid)",
        "Element version history",
    ),
    DeletionStep(
        "resume_suggestion_decisions",
        "resume_suggestion_decisions",
        "delete",
        "DELETE FROM resume_suggestion_decisions WHERE decided_by_user_id = CAST(:uid AS uuid)",
        "Suggestion decision attribution",
    ),
    DeletionStep(
        "recruiter_notes",
        "recruiter_notes",
        "delete",
        "DELETE FROM recruiter_notes WHERE author_id = CAST(:uid AS uuid)",
        "Authored recruiter notes",
    ),
    DeletionStep(
        "snippet_installs",
        "snippet_installs",
        "delete",
        "DELETE FROM snippet_installs WHERE user_id = CAST(:uid AS uuid)",
        "Snippet install records",
    ),
    DeletionStep(
        "snippet_upvotes",
        "snippet_upvotes",
        "delete",
        "DELETE FROM snippet_upvotes WHERE user_id = CAST(:uid AS uuid)",
        "Snippet votes",
    ),
    DeletionStep(
        "snippets",
        "snippets",
        "delete",
        "DELETE FROM snippets WHERE author_id = CAST(:uid AS uuid)",
        "Authored marketplace snippets and dependent install/vote rows",
    ),
    DeletionStep(
        "bullet_variant_sets",
        "bullet_variant_sets",
        "delete",
        "DELETE FROM bullet_variant_sets WHERE user_id = CAST(:uid AS uuid)",
        "Saved bullet variants",
    ),
    DeletionStep(
        "career_analyses",
        "career_analyses",
        "delete",
        "DELETE FROM career_analyses WHERE user_id = CAST(:uid AS uuid)",
        "Career analyses",
    ),
    DeletionStep(
        "interview_prep",
        "interview_prep",
        "delete",
        "DELETE FROM interview_prep WHERE user_id = CAST(:uid AS uuid)",
        "Interview preparation",
    ),
    DeletionStep(
        "job_applications",
        "job_applications",
        "delete",
        "DELETE FROM job_applications WHERE user_id = CAST(:uid AS uuid)",
        "Job applications",
    ),
    DeletionStep(
        "application_reminders",
        "application_reminders",
        "delete",
        "DELETE FROM application_reminders WHERE user_id = CAST(:uid AS uuid)",
        "Application reminders",
    ),
    DeletionStep(
        "application_interviews",
        "application_interviews",
        "delete",
        "DELETE FROM application_interviews WHERE user_id = CAST(:uid AS uuid)",
        "Application interviews",
    ),
    DeletionStep(
        "application_submissions",
        "application_submissions",
        "delete",
        "DELETE FROM application_submissions WHERE user_id = CAST(:uid AS uuid)",
        "Application submission records",
    ),
    DeletionStep(
        "saved_jobs",
        "saved_jobs",
        "delete",
        "DELETE FROM saved_jobs WHERE user_id = CAST(:uid AS uuid)",
        "Saved jobs",
    ),
    DeletionStep(
        "job_alerts",
        "job_alerts",
        "delete",
        "DELETE FROM job_alerts WHERE user_id = CAST(:uid AS uuid)",
        "Job alerts",
    ),
    DeletionStep(
        "tracker_contacts",
        "tracker_contacts",
        "delete",
        "DELETE FROM tracker_contacts WHERE user_id = CAST(:uid AS uuid)",
        "Tracker contacts",
    ),
    DeletionStep(
        "tracker_companies",
        "tracker_companies",
        "delete",
        "DELETE FROM tracker_companies WHERE user_id = CAST(:uid AS uuid)",
        "Tracker companies",
    ),
    DeletionStep(
        "cover_letters",
        "cover_letters",
        "delete",
        "DELETE FROM cover_letters WHERE user_id = CAST(:uid AS uuid)",
        "Cover letters",
    ),
    DeletionStep(
        "optimizations",
        "optimizations",
        "delete",
        "DELETE FROM optimizations WHERE user_id = CAST(:uid AS uuid)",
        "Optimization history",
    ),
    DeletionStep(
        "compilations",
        "compilations",
        "delete",
        "DELETE FROM compilations WHERE user_id = CAST(:uid AS uuid)",
        "Compilation history and stored PDF paths",
    ),
    DeletionStep(
        "job_finalizations",
        "job_finalizations",
        "delete",
        "DELETE FROM job_finalizations WHERE user_id = CAST(:uid AS uuid)",
        "Recoverable job payloads",
    ),
    DeletionStep(
        "resume_job_matches",
        "resume_job_matches",
        "delete",
        "DELETE FROM resume_job_matches WHERE user_id = CAST(:uid AS uuid)",
        "Resume/job matches",
    ),
    DeletionStep(
        "resume_requirement_contexts",
        "resume_requirement_contexts",
        "delete",
        "DELETE FROM resume_requirement_contexts WHERE user_id = CAST(:uid AS uuid)",
        "Job requirement contexts",
    ),
    DeletionStep(
        "resume_optimization_runs",
        "resume_optimization_runs",
        "delete",
        "DELETE FROM resume_optimization_runs WHERE user_id = CAST(:uid AS uuid)",
        "Optimization snapshots",
    ),
    DeletionStep(
        "resumes",
        "resumes",
        "delete",
        "DELETE FROM resumes WHERE user_id = CAST(:uid AS uuid)",
        "Resume source, structured content and cascaded child rows",
    ),
    DeletionStep(
        "user_api_keys",
        "user_api_keys",
        "delete",
        "DELETE FROM user_api_keys WHERE user_id = CAST(:uid AS uuid)",
        "BYOK encrypted provider keys",
    ),
    DeletionStep(
        "developer_api_keys",
        "developer_api_keys",
        "delete",
        "DELETE FROM developer_api_keys WHERE user_id = CAST(:uid AS uuid)",
        "Developer API keys",
    ),
    DeletionStep(
        "user_macros",
        "user_macros",
        "delete",
        "DELETE FROM user_macros WHERE user_id = CAST(:uid AS uuid)",
        "Keyboard macro scripts",
    ),
    DeletionStep(
        "workspace_resumes_shared_by",
        "workspace_resumes",
        "update",
        "UPDATE workspace_resumes SET shared_by = NULL WHERE shared_by = CAST(:uid AS uuid)",
        "Workspace share attribution",
    ),
    DeletionStep(
        "workspace_members",
        "workspace_members",
        "delete",
        "DELETE FROM workspace_members WHERE user_id = CAST(:uid AS uuid)",
        "Workspace memberships",
    ),
    DeletionStep(
        "workspace_members_invited_by",
        "workspace_members",
        "update",
        "UPDATE workspace_members SET invited_by = NULL WHERE invited_by = CAST(:uid AS uuid)",
        "Workspace invitation attribution",
    ),
    DeletionStep(
        "workspaces",
        "workspaces",
        "delete",
        "DELETE FROM workspaces WHERE owner_id = CAST(:uid AS uuid)",
        "Owned workspaces",
    ),
    DeletionStep(
        "team_seats_owned",
        "team_seats",
        "delete",
        "DELETE FROM team_seats WHERE owner_user_id = CAST(:uid AS uuid)",
        "Owned team seats",
    ),
    DeletionStep(
        "team_seats_member",
        "team_seats",
        "delete",
        "DELETE FROM team_seats WHERE member_user_id = CAST(:uid AS uuid)",
        "Team seat memberships",
    ),
    DeletionStep(
        "tenant_members",
        "tenant_members",
        "delete",
        "DELETE FROM tenant_members WHERE user_id = CAST(:uid AS uuid)",
        "Tenant memberships",
    ),
    DeletionStep(
        "tenants",
        "tenants",
        "delete",
        "DELETE FROM tenants WHERE owner_id = CAST(:uid AS uuid)",
        "Owned tenants",
    ),
    DeletionStep(
        "referral_attributions",
        "referral_attributions",
        "delete",
        "DELETE FROM referral_attributions WHERE referred_user_id = CAST(:uid AS uuid)",
        "Referral attribution for the subject",
    ),
    DeletionStep(
        "referral_identities",
        "referral_identities",
        "delete",
        "DELETE FROM referral_identities WHERE user_id = CAST(:uid AS uuid)",
        "Referral codes and digests",
    ),
    DeletionStep(
        "coupon_redemptions",
        "coupon_redemptions",
        "update",
        "UPDATE coupon_redemptions SET user_id = NULL WHERE user_id = CAST(:uid AS uuid)",
        "Coupon redemption attribution (promotion ledger retained)",
    ),
    DeletionStep(
        "signup_funnel_events",
        "signup_funnel_events",
        "delete",
        "DELETE FROM signup_funnel_events WHERE user_id = CAST(:uid AS uuid)",
        "Signup milestone links",
    ),
    DeletionStep(
        "usage_analytics",
        "usage_analytics",
        "delete",
        "DELETE FROM usage_analytics WHERE user_id = CAST(:uid AS uuid)",
        "Usage analytics with IP and user-agent",
    ),
    DeletionStep(
        "auth_sessions",
        "session",
        "delete",
        'DELETE FROM session WHERE "userId" = :uid',
        "Better Auth sessions",
    ),
    DeletionStep(
        "auth_accounts",
        "account",
        "delete",
        'DELETE FROM account WHERE "userId" = :uid',
        "Better Auth linked accounts and password hashes",
    ),
    DeletionStep(
        "auth_two_factor",
        "twoFactor",
        "delete",
        'DELETE FROM "twoFactor" WHERE "userId" = :uid',
        "Two-factor secret and backup codes",
    ),
    DeletionStep(
        "auth_passkeys",
        "passkey",
        "delete",
        'DELETE FROM passkey WHERE "userId" = :uid',
        "WebAuthn passkey registrations",
    ),
    DeletionStep(
        "auth_verification",
        "verification",
        "delete",
        "DELETE FROM verification WHERE identifier = (SELECT email FROM users WHERE id = CAST(:uid AS uuid))",
        "Password-reset and email-verification tokens keyed by the account email",
    ),
    DeletionStep(
        "user_profile",
        "users",
        "anonymize",
        """
        UPDATE users SET
            email = :deleted_email,
            name = NULL,
            avatar_url = NULL,
            subscription_id = NULL,
            email_verified = false,
            github_access_token = NULL,
            github_username = NULL,
            dropbox_access_token = NULL,
            dropbox_refresh_token = NULL,
            dropbox_account_id = NULL,
            user_metadata = NULL,
            public_username = NULL,
            portfolio_enabled = false,
            portfolio_custom_domain = NULL,
            portfolio_tagline = NULL,
            default_tenant_id = NULL,
            email_notifications = NULL,
            two_factor_enabled = false,
            updated_at = now()
        WHERE id = CAST(:uid AS uuid)
        """,
        "Profile, OAuth tokens, metadata and portfolio identity",
    ),
)

RETENTION_STEPS: tuple[RetentionStep, ...] = (
    RetentionStep("payments", "Invoices and payment history retained by tax law", "invoices_and_payments"),
    RetentionStep("subscriptions", "Billing relationship evidence retained by tax law", "invoices_and_payments"),
    RetentionStep("payment_refunds", "Refund ledger retained by tax law", "invoices_and_payments"),
    RetentionStep("admin_refund_requests", "Refund approvals retained for financial audit", "invoices_and_payments"),
    RetentionStep("admin_approvals", "Two-person approvals retained for security audit", "security_audit"),
    RetentionStep(
        "billing_webhook_events",
        "Signed provider event evidence retained for fraud/chargeback review",
        "invoices_and_payments",
    ),
    RetentionStep("quota_ledger_accounts", "Billing/quota integrity ledger", "fraud_and_billing_integrity"),
    RetentionStep(
        "quota_ledger_reservations", "Immutable usage reconciliation evidence", "fraud_and_billing_integrity"
    ),
    RetentionStep("referral_rewards", "Issued referral credit ledger", "referral_credit_ledger"),
    RetentionStep("admin_audit_log", "Append-only operator audit required for accountability", "security_audit"),
    RetentionStep("gdpr_requests", "Data-subject request history", "security_audit"),
    RetentionStep("gdpr_request_events", "Append-only GDPR transition history", "security_audit"),
    RetentionStep("gdpr_legal_holds", "Legal hold evidence", "security_audit"),
)


# --------------------------------------------------------------------------- #
#  Small helpers                                                               #
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _retention_exceptions() -> List[Dict[str, Any]]:
    # Return a copy so callers cannot mutate the module-level policy.
    return json.loads(json.dumps(RETENTION_EXCEPTIONS))


def public_policy() -> Dict[str, Any]:
    """Policy metadata shown in the settings and admin surfaces."""
    return {
        "deletion_confirmation": DELETION_CONFIRMATION,
        "export_ttl_minutes": settings.GDPR_EXPORT_TTL_MINUTES,
        "reauth_max_age_minutes": settings.GDPR_REAUTH_MAX_AGE_MINUTES,
        "retention_exceptions": _retention_exceptions(),
        "export_scope": {
            "included": [
                "profile",
                "resume_metadata_and_latex_source",
                "cover_letters",
                "job_applications",
                "payments_and_subscription_summary",
                "usage_summary",
                "credential_metadata_without_secret_values",
            ],
            "excluded": [
                "passwords_and_password_hashes",
                "OAuth access and refresh tokens",
                "BYOK encrypted keys and developer key hashes",
                "other users' data",
                "binary PDF import content (metadata and checksum only)",
            ],
        },
    }


def _export_signing_key() -> bytes:
    configured = (getattr(settings, "GDPR_EXPORT_SIGNING_KEY", "") or "").strip()
    if configured:
        return configured.encode("utf-8")
    base = (settings.BETTER_AUTH_SECRET or settings.JWT_SECRET_KEY or "").strip()
    if not base:
        raise GdprError(
            "Export signing is not configured",
            code="signing_key_missing",
            status_code=503,
        )
    return hashlib.sha256(b"latexy.gdpr.export.v1:" + base.encode("utf-8")).digest()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def issue_export_token(
    *,
    request_id: str,
    user_id: str,
    expires_at: datetime,
) -> str:
    """Create an HMAC-signed, request-bound download token."""
    payload = {
        "v": 1,
        "rid": str(request_id),
        "uid": str(user_id),
        "exp": int(expires_at.timestamp()),
        "nonce": uuid.uuid4().hex,
    }
    body = _b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_export_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}"


def validate_export_token(
    token: str,
    *,
    request_id: str,
    user_id: str,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Validate signature, expiry and request/user binding.

    Raises ``GdprForbidden`` for a tampered token and ``GdprExpired`` after the
    token lifetime. Callers must still compare the token hash against the
    stored hash; this function cannot do that by itself.
    """
    if not token or token.count(".") != 1:
        raise GdprForbidden("Invalid export token", code="invalid_export_token")
    body, signature = token.split(".", 1)
    try:
        expected = hmac.new(_export_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
        provided = _b64url_decode(signature)
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        json.JSONDecodeError,
        binascii.Error,
        hmac.HMACError,
    ):
        raise GdprForbidden("Invalid export token", code="invalid_export_token") from None
    if not hmac.compare_digest(expected, provided):
        raise GdprForbidden("Invalid export token", code="invalid_export_token")
    if payload.get("v") != 1:
        raise GdprForbidden("Invalid export token", code="invalid_export_token")
    if str(payload.get("rid")) != str(request_id) or str(payload.get("uid")) != str(user_id):
        raise GdprForbidden("Export token does not match this request", code="invalid_export_token")
    if expires_at <= (now or _now()):
        raise GdprExpired("This export download link has expired")
    return payload


def hash_export_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical_export_bytes(data: Mapping[str, Any]) -> bytes:
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def sign_export_data(data: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(sha256_hex, hmac_hex)`` for the canonical bundle data."""
    canonical = canonical_export_bytes(data)
    digest = hashlib.sha256(canonical).hexdigest()
    signature = hmac.new(
        _export_signing_key(),
        b"latexy.gdpr.bundle.v1\0" + canonical,
        hashlib.sha256,
    ).hexdigest()
    return digest, signature


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        # Binary payloads are never exported; report their absence explicitly.
        return None
    return str(value)


def _scrub_sensitive(value: Any) -> Any:
    """Remove credential-shaped keys from exported metadata payloads."""
    if isinstance(value, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            lowered = text_key.casefold()
            if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
                continue
            cleaned[text_key] = _scrub_sensitive(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_sensitive(item) for item in value]
    return value


def _safe_failure_code(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate:
        return str(sqlstate)[:64]
    return type(exc).__name__[:64]


async def _fetch_rows(db: AsyncSession, sql: str, params: Mapping[str, Any] | None = None) -> List[Dict[str, Any]]:
    result = await db.execute(text(sql), dict(params or {}))
    return [dict(row) for row in result.mappings()]


async def _append_event(
    db: AsyncSession,
    request_row: GdprRequest,
    *,
    event: str,
    actor_type: str,
    actor_user_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    reason: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    db.add(
        GdprRequestEvent(
            id=str(uuid.uuid4()),
            request_id=request_row.id,
            event=event[:64],
            actor_type=actor_type,
            actor_user_id=(actor_user_id or "")[:36] or None,
            from_status=from_status,
            to_status=to_status,
            reason=(reason or "")[:1000] or None,
            event_metadata=dict(metadata or {}),
        )
    )


async def _require_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise GdprNotFound("Account not found")
    return user


async def _session_created_at(db: AsyncSession, request: Request | None, user_id: str) -> datetime | None:
    if request is None:
        return None
    token = extract_session_token(request)
    if not token:
        return None
    result = await db.execute(
        text('SELECT "createdAt" FROM session WHERE token = :token AND "userId" = :uid AND "expiresAt" > now()'),
        {"token": token, "uid": str(user_id)},
    )
    return _as_aware(result.scalar_one_or_none())


def _user_request_payload(row: GdprRequest) -> Dict[str, Any]:
    now = _now()
    effective_status = row.status
    if (
        row.request_type == EXPORT
        and row.status == "ready"
        and _as_aware(row.export_expires_at) is not None
        and _as_aware(row.export_expires_at) <= now
    ):
        effective_status = "expired"
    results = row.table_results or []
    failed_tables = [item.get("table") for item in results if item.get("status") == "failed"]
    return {
        "id": str(row.id),
        "request_type": row.request_type,
        "status": effective_status,
        "legal_review_status": row.legal_review_status,
        "identity_verified": row.identity_verified_at is not None,
        "reauthenticated_at": _iso(row.reauthenticated_at),
        "confirmed_at": _iso(row.confirmed_at),
        "legal_reviewed_at": _iso(row.legal_reviewed_at),
        "review_note": row.legal_review_note,
        "legal_hold_blocked": row.legal_hold_blocked,
        "export_expires_at": _iso(row.export_expires_at),
        "export_downloaded_at": _iso(row.export_downloaded_at),
        "export_available": (
            row.request_type == EXPORT and effective_status == "ready" and row.export_expires_at is not None
        ),
        "failure_code": row.failure_code,
        "failure_detail": row.failure_detail,
        "attempts": row.attempts,
        "failed_tables": failed_tables,
        "table_results": results,
        "retention_exceptions": row.retention_exceptions or _retention_exceptions(),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "finished_at": _iso(row.finished_at),
        "can_cancel": row.request_type == DELETION and row.status in {"legal_review", "blocked", "failed"},
    }


def _admin_request_payload(
    row: GdprRequest,
    *,
    user_email: str | None,
    legal_hold_active: bool,
) -> Dict[str, Any]:
    payload = _user_request_payload(row)
    payload.update(
        {
            "user_id": str(row.user_id) if row.user_id else None,
            "user_email_masked": mask_email(user_email),
            "legal_reviewed_by": row.legal_reviewed_by,
            "legal_hold_active": legal_hold_active,
            "retention_exceptions": row.retention_exceptions or _retention_exceptions(),
        }
    )
    return payload


async def _active_holds_for(db: AsyncSession, user_ids: Iterable[str]) -> set[str]:
    ids = [str(value) for value in user_ids if value]
    if not ids:
        return set()
    result = await db.execute(
        select(GdprLegalHold.user_id).where(
            GdprLegalHold.active.is_(True),
            GdprLegalHold.user_id.in_(ids),
        )
    )
    return {str(value) for value in result.scalars().all()}


# --------------------------------------------------------------------------- #
#  Export workflow                                                             #
# --------------------------------------------------------------------------- #


async def _build_export_bundle(db: AsyncSession, user: User, request_row: GdprRequest) -> Dict[str, Any]:
    uid = str(user.id)
    profile = {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "subscription_plan": user.subscription_plan,
        "subscription_status": user.subscription_status,
        "email_verified": bool(user.email_verified),
        "auth_provider": user.auth_provider,
        "trial_used": bool(user.trial_used),
        "public_username": user.public_username,
        "portfolio_enabled": bool(user.portfolio_enabled),
        "portfolio_theme": user.portfolio_theme,
        "portfolio_tagline": user.portfolio_tagline,
        "metadata": _scrub_sensitive(user.user_metadata or {}),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "integrations": {
            "github_connected": bool(user.github_access_token or user.github_username),
            "dropbox_connected": bool(user.dropbox_access_token or user.dropbox_account_id),
        },
    }

    resumes = await _fetch_rows(
        db,
        """
        SELECT id, title, is_template, tags, created_at, updated_at,
               parent_resume_id, metadata, document_type, structured_content,
               structured_version, selected_template_id, content_source,
               builder_status, portfolio_visible, variant_visibility,
               content_revision, archived_at, github_sync_enabled,
               github_repo_name, github_last_sync_at, dropbox_sync_enabled,
               dropbox_folder_path, dropbox_last_sync_at, latex_content
        FROM resumes
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )
    for resume in resumes:
        for key in ("metadata", "structured_content"):
            resume[key] = _scrub_sensitive(resume.get(key))

    resume_files = await _fetch_rows(
        db,
        """
        SELECT id, resume_id, filename, source_sha256, size_bytes,
               extraction_status, adaptation_sha256, expires_at, created_at
        FROM resume_pdf_imports
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )
    for item in resume_files:
        item["content_included"] = False
        item["policy_note"] = (
            "Original binary PDF is excluded from the JSON bundle. It is deleted "
            "with the account and its checksum is shown for verification."
        )

    cover_letters = await _fetch_rows(
        db,
        """
        SELECT id, resume_id, company_name, role_title, tone, length_preference,
               latex_content, created_at, updated_at
        FROM cover_letters
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )

    applications = await _fetch_rows(
        db,
        """
        SELECT id, company_name, role_title, status, resume_id,
               ats_score_at_submission, job_description_text, job_url,
               notes, applied_at, updated_at, created_at
        FROM job_applications
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )

    payments = await _fetch_rows(
        db,
        """
        SELECT id, amount, currency, status, payment_method, provider,
               provider_payment_id, provider_event_at, created_at
        FROM payments
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )

    subscriptions = await _fetch_rows(
        db,
        """
        SELECT id, provider, plan_id, status, current_period_start,
               current_period_end, cancelled_at, created_at, updated_at
        FROM subscriptions
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_EXPORT_ROWS},
    )

    usage_summary = await _fetch_rows(
        db,
        """
        SELECT action, COUNT(*) AS event_count, MAX(created_at) AS last_seen_at
        FROM usage_analytics
        WHERE user_id = CAST(:uid AS uuid)
        GROUP BY action
        ORDER BY event_count DESC
        """,
        {"uid": uid},
    )
    recent_usage = await _fetch_rows(
        db,
        """
        SELECT action, resource_type, created_at
        FROM usage_analytics
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"uid": uid, "limit": _MAX_RECENT_USAGE_ROWS},
    )

    byok_keys = await _fetch_rows(
        db,
        """
        SELECT id, provider, key_name, is_active, last_validated, created_at
        FROM user_api_keys
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        """,
        {"uid": uid},
    )
    developer_keys = await _fetch_rows(
        db,
        """
        SELECT id, key_prefix, name, scopes, is_active, request_count,
               last_used_at, created_at
        FROM developer_api_keys
        WHERE user_id = CAST(:uid AS uuid)
        ORDER BY created_at
        """,
        {"uid": uid},
    )

    return {
        "schema_version": 1,
        "request_id": str(request_row.id),
        "generated_at": _now(),
        "subject_user_id": uid,
        "profile": profile,
        "resumes": resumes,
        "resume_files": resume_files,
        "cover_letters": cover_letters,
        "job_applications": applications,
        "payments": payments,
        "subscriptions": subscriptions,
        "usage": {
            "summary": usage_summary,
            "recent": recent_usage,
            "note": (
                "IP address, user-agent and raw event metadata are excluded from "
                "this export to avoid leaking third-party or credential data."
            ),
        },
        "credentials": {
            "byok_keys": byok_keys,
            "developer_keys": developer_keys,
            "note": "Secret values, hashes and encrypted material are never exported.",
        },
        "retention_exceptions": _retention_exceptions(),
        "export_scope": public_policy()["export_scope"],
    }


def _export_creation_payload(request_row: GdprRequest, token: str, *, reissued: bool) -> Dict[str, Any]:
    return {
        "request": _user_request_payload(request_row),
        "download_token": token,
        "download_path": f"/account/gdpr/exports/{request_row.id}/download",
        "download_token_header": "X-GDPR-Export-Token",
        "expires_at": _iso(request_row.export_expires_at),
        "reissued": reissued,
    }


async def request_export(db: AsyncSession, *, user_id: str, request: Request | None = None) -> Dict[str, Any]:
    user = await _require_user(db, user_id)
    if not user.email_verified:
        raise GdprForbidden(
            "Verify your email address before requesting a data export",
            code="identity_verification_required",
        )
    now = _now()
    ttl = int(settings.GDPR_EXPORT_TTL_MINUTES)
    existing = (
        await db.execute(
            select(GdprRequest)
            .where(
                GdprRequest.user_id == str(user_id),
                GdprRequest.request_type == EXPORT,
                GdprRequest.status == "ready",
                GdprRequest.export_expires_at > now,
            )
            .order_by(GdprRequest.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing is not None:
        expires_at = now + _minutes(ttl)
        token = issue_export_token(
            request_id=str(existing.id),
            user_id=str(user_id),
            expires_at=expires_at,
        )
        existing.export_token_hash = hash_export_token(token)
        existing.export_issued_at = now
        existing.export_expires_at = expires_at
        existing.identity_verified_at = existing.identity_verified_at or now
        await _append_event(
            db,
            existing,
            event="export.link_reissued",
            actor_type="user",
            actor_user_id=str(user_id),
            from_status=existing.status,
            to_status=existing.status,
            metadata={"ttl_minutes": ttl},
        )
        await db.commit()
        await db.refresh(existing)
        logger.info("GDPR export link reissued request_id=%s", str(existing.id))
        return _export_creation_payload(existing, token, reissued=True)

    row = GdprRequest(
        id=str(uuid.uuid4()),
        user_id=str(user_id),
        request_type=EXPORT,
        status="ready",
        legal_review_status="not_required",
        identity_verified_at=now,
        export_issued_at=now,
        export_expires_at=now + _minutes(ttl),
        retention_exceptions=_retention_exceptions(),
    )
    db.add(row)
    await db.flush()
    token = issue_export_token(
        request_id=str(row.id),
        user_id=str(user_id),
        expires_at=row.export_expires_at,
    )
    row.export_token_hash = hash_export_token(token)
    await _append_event(
        db,
        row,
        event="export.ready",
        actor_type="user",
        actor_user_id=str(user_id),
        to_status="ready",
        metadata={"ttl_minutes": ttl},
    )
    await db.commit()
    await db.refresh(row)
    logger.info("GDPR export prepared request_id=%s", str(row.id))
    return _export_creation_payload(row, token, reissued=False)


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


async def download_export(
    db: AsyncSession,
    *,
    user_id: str,
    request_id: str,
    token: str,
) -> tuple[str, bytes]:
    row = (
        await db.execute(
            select(GdprRequest)
            .where(
                GdprRequest.id == str(request_id),
                GdprRequest.user_id == str(user_id),
                GdprRequest.request_type == EXPORT,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("Export request not found")
    now = _now()
    expires_at = _as_aware(row.export_expires_at)
    if row.status not in {"ready", "processing"} or expires_at is None or expires_at <= now:
        if row.status == "ready":
            row.status = "expired"
            await _append_event(
                db,
                row,
                event="export.expired",
                actor_type="system",
                from_status="ready",
                to_status="expired",
            )
            await db.commit()
        raise GdprExpired("This export download link has expired")
    if not row.export_token_hash or not hmac.compare_digest(row.export_token_hash, hash_export_token(token)):
        raise GdprForbidden("Invalid export token", code="invalid_export_token")
    validate_export_token(
        token,
        request_id=str(row.id),
        user_id=str(user_id),
        now=now,
    )
    user = await _require_user(db, user_id)
    if not user.email or user.email.endswith("@privacy.invalid"):
        raise GdprNotFound("Account not found")
    data = await _build_export_bundle(db, user, row)
    digest, signature = sign_export_data(data)
    envelope = {
        "manifest": {
            "schema_version": 1,
            "request_id": str(row.id),
            "subject_user_id": str(user_id),
            "generated_at": _now(),
            "expires_at": expires_at,
            "data_sha256": digest,
            "signature": signature,
            "signature_algorithm": "HMAC-SHA256",
            "signed_payload": "manifest + data canonical JSON (RFC 8785-style sorted keys)",
        },
        "data": data,
    }
    raw = json.dumps(
        envelope,
        ensure_ascii=False,
        default=_json_default,
        separators=(",", ":"),
    ).encode("utf-8")
    row.export_downloaded_at = row.export_downloaded_at or now
    row.export_sha256 = hashlib.sha256(raw).hexdigest()
    row.export_size_bytes = len(raw)
    await _append_event(
        db,
        row,
        event="export.downloaded",
        actor_type="user",
        actor_user_id=str(user_id),
        from_status=row.status,
        to_status=row.status,
        metadata={"size_bytes": len(raw), "data_sha256": digest},
    )
    await db.commit()
    logger.info(
        "GDPR export downloaded request_id=%s size_bytes=%s",
        str(row.id),
        len(raw),
    )
    return f"latexy-gdpr-export-{row.id}.json", raw


# --------------------------------------------------------------------------- #
#  Deletion workflow                                                           #
# --------------------------------------------------------------------------- #


async def request_deletion(
    db: AsyncSession,
    *,
    user_id: str,
    confirmation: str,
    reason: str | None = None,
    request: Request | None = None,
) -> Dict[str, Any]:
    user = await _require_user(db, user_id)
    if not user.email_verified:
        raise GdprForbidden(
            "Verify your email address before requesting account deletion",
            code="identity_verification_required",
        )
    if (confirmation or "").strip().upper() != DELETION_CONFIRMATION:
        raise GdprUnprocessable(
            f'Type "{DELETION_CONFIRMATION}" exactly to confirm deletion',
            code="confirmation_mismatch",
        )
    session_created_at = await _session_created_at(db, request, user_id)
    now = _now()
    max_age = _minutes(int(settings.GDPR_REAUTH_MAX_AGE_MINUTES))
    if session_created_at is None or session_created_at < now - max_age:
        raise GdprForbidden(
            "Sign in again before requesting account deletion",
            code="reauth_required",
        )

    existing = (
        await db.execute(
            select(GdprRequest)
            .where(
                GdprRequest.user_id == str(user_id),
                GdprRequest.request_type == DELETION,
                GdprRequest.status.in_(ACTIVE_DELETION_STATUSES),
            )
            .order_by(GdprRequest.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "request": _user_request_payload(existing),
            "created": False,
            "retention_exceptions": existing.retention_exceptions or _retention_exceptions(),
        }

    row = GdprRequest(
        id=str(uuid.uuid4()),
        user_id=str(user_id),
        request_type=DELETION,
        status="legal_review",
        legal_review_status="pending",
        identity_verified_at=now,
        reauthenticated_at=session_created_at,
        confirmed_at=now,
        retention_exceptions=_retention_exceptions(),
    )
    db.add(row)
    await db.flush()
    await admin_approval_service.create_request(
        db,
        request_type="account_deletion",
        payload={"gdpr_request_id": row.id, "user_id": str(user_id)},
        reason=(reason or "").strip()[:1000] or "User requested account deletion",
        requested_by=str(user_id),
        resource_type="gdpr_request",
        resource_id=row.id,
        expires_in=admin_approval_service.MAX_TTL,
        request=request,
        commit=False,
    )
    await _append_event(
        db,
        row,
        event="deletion.requested",
        actor_type="user",
        actor_user_id=str(user_id),
        to_status="legal_review",
        reason=(reason or "")[:1000] or None,
        metadata={"retention_exceptions": [item["category"] for item in RETENTION_EXCEPTIONS]},
    )
    await db.commit()
    await db.refresh(row)
    logger.info("GDPR deletion requested request_id=%s", str(row.id))
    return {
        "request": _user_request_payload(row),
        "created": True,
        "retention_exceptions": row.retention_exceptions or _retention_exceptions(),
    }


async def _user_request(db: AsyncSession, *, user_id: str, request_id: str) -> GdprRequest:
    row = (
        await db.execute(
            select(GdprRequest).where(
                GdprRequest.id == str(request_id),
                GdprRequest.user_id == str(user_id),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("Request not found")
    return row


async def list_user_requests(db: AsyncSession, *, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(GdprRequest)
                .where(GdprRequest.user_id == str(user_id))
                .order_by(GdprRequest.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        )
        .scalars()
        .all()
    )
    return [_user_request_payload(row) for row in rows]


async def get_user_request(db: AsyncSession, *, user_id: str, request_id: str) -> Dict[str, Any]:
    row = await _user_request(db, user_id=user_id, request_id=request_id)
    payload = _user_request_payload(row)
    hold = await _active_holds_for(db, [str(user_id)])
    payload["legal_hold_active"] = str(user_id) in hold
    return payload


async def cancel_deletion(db: AsyncSession, *, user_id: str, request_id: str) -> Dict[str, Any]:
    row = (
        await db.execute(
            select(GdprRequest)
            .where(
                GdprRequest.id == str(request_id),
                GdprRequest.user_id == str(user_id),
                GdprRequest.request_type == DELETION,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("Deletion request not found")
    if row.status not in {"legal_review", "blocked", "failed"}:
        raise GdprConflict(
            "This deletion request can no longer be cancelled",
            code="not_cancellable",
        )
    previous = row.status
    row.status = "cancelled"
    row.finished_at = _now()
    await _append_event(
        db,
        row,
        event="deletion.cancelled",
        actor_type="user",
        actor_user_id=str(user_id),
        from_status=previous,
        to_status="cancelled",
    )
    await db.commit()
    await db.refresh(row)
    return _user_request_payload(row)


# --------------------------------------------------------------------------- #
#  Admin review, execution and legal holds                                     #
# --------------------------------------------------------------------------- #


async def list_admin_requests(
    db: AsyncSession,
    *,
    status: str | None = None,
    request_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    conditions = []
    if status:
        conditions.append(GdprRequest.status == status)
    if request_type:
        conditions.append(GdprRequest.request_type == request_type)
    base = select(GdprRequest, User.email).outerjoin(User, GdprRequest.user_id == User.id)
    count_stmt = select(func.count()).select_from(GdprRequest)
    if conditions:
        base = base.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    total = int((await db.execute(count_stmt)).scalar_one())
    bounded_limit = max(1, min(int(limit), 200))
    rows = (
        await db.execute(
            base.order_by(GdprRequest.created_at.desc(), GdprRequest.id.desc())
            .offset(max(0, int(offset)))
            .limit(bounded_limit)
        )
    ).all()
    hold_map = await _active_holds_for(db, [str(row[0].user_id) for row in rows if row[0].user_id])
    items = [
        _admin_request_payload(
            request_row,
            user_email=email,
            legal_hold_active=str(request_row.user_id) in hold_map if request_row.user_id else False,
        )
        for request_row, email in rows
    ]
    return {
        "items": items,
        "total": total,
        "limit": bounded_limit,
        "offset": max(0, int(offset)),
    }


async def review_request(
    db: AsyncSession,
    *,
    request_id: str,
    decision: str,
    note: str,
    actor: AdminActor,
    request: Request | None = None,
) -> Dict[str, Any]:
    if decision not in {"approved", "rejected"}:
        raise GdprUnprocessable("Decision must be approved or rejected")
    row = (
        await db.execute(select(GdprRequest).where(GdprRequest.id == str(request_id)).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("GDPR request not found")
    if row.request_type != DELETION:
        raise GdprUnprocessable("Export requests do not require legal review")
    if row.status != "legal_review" or row.legal_review_status != "pending":
        raise GdprConflict(
            "This request is not awaiting legal review",
            code="not_pending_review",
        )
    if row.user_id and str(row.user_id) == str(actor.user_id):
        raise GdprForbidden(
            "You cannot review your own deletion request",
            code="self_review_forbidden",
        )
    await admin_approval_service.sync_decision(
        db,
        request_type="account_deletion",
        resource_id=str(row.id),
        decision="approve" if decision == "approved" else "reject",
        note=note,
        actor=actor,
        request=request,
    )
    previous = row.status
    row.status = "approved" if decision == "approved" else "rejected"
    row.legal_review_status = decision
    row.legal_reviewed_by = str(actor.user_id)[:36]
    row.legal_reviewed_at = _now()
    row.legal_review_note = (note or "").strip()[:2000] or None
    if decision == "rejected":
        row.finished_at = _now()
    user = await db.get(User, str(row.user_id)) if row.user_id else None
    user_email = user.email if user else None
    await _append_event(
        db,
        row,
        event=f"deletion.legal_{decision}",
        actor_type="admin",
        actor_user_id=str(actor.user_id),
        from_status=previous,
        to_status=row.status,
        reason=row.legal_review_note,
        metadata={"legal_review_status": decision},
    )
    await record_admin_audit(
        db,
        actor=actor,
        action=f"gdpr.deletion.{decision}",
        target_type="gdpr_request",
        target_id=str(row.id),
        reason=row.legal_review_note,
        before={"status": previous, "legal_review_status": "pending"},
        after={"status": row.status, "legal_review_status": decision},
        metadata={
            "gdpr_request_id": str(row.id),
            "target_user_id": str(row.user_id) if row.user_id else None,
            "request_type": DELETION,
            "decision": decision,
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    logger.info(
        "GDPR deletion %s request_id=%s actor=%s",
        decision,
        str(row.id),
        str(actor.user_id)[:36],
    )
    hold_map = await _active_holds_for(db, [str(row.user_id)] if row.user_id else [])
    return _admin_request_payload(
        row,
        user_email=user_email,
        legal_hold_active=str(row.user_id) in hold_map if row.user_id else False,
    )


async def _run_deletion_step(db: AsyncSession, step: DeletionStep, user_id: str) -> int:
    params: Dict[str, Any] = {"uid": str(user_id)}
    if step.key == "user_profile":
        params["deleted_email"] = (
            "deleted+" + hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:20] + "@privacy.invalid"
        )
    result = await db.execute(text(step.sql), params)
    return max(0, int(result.rowcount or 0))


async def execute_deletion(
    db: AsyncSession,
    *,
    request_id: str,
    actor: AdminActor,
    note: str | None = None,
    request: Request | None = None,
) -> Dict[str, Any]:
    row = (
        await db.execute(select(GdprRequest).where(GdprRequest.id == str(request_id)).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("GDPR request not found")
    if row.request_type != DELETION:
        raise GdprUnprocessable("Only deletion requests can be executed")
    if row.status == "completed":
        # Idempotent replay: return the stored per-table report without
        # touching any data or incrementing attempts.
        return _admin_request_payload(
            row,
            user_email=None,
            legal_hold_active=False,
        )
    if row.legal_review_status != "approved":
        raise GdprConflict(
            "Legal review approval is required before execution",
            code="legal_review_required",
        )
    if row.status not in {"approved", "failed", "blocked", "processing"}:
        raise GdprConflict("This request cannot be executed", code="not_executable")
    now = _now()
    if row.status == "processing":
        updated = _as_aware(row.updated_at) or now
        if updated > now - _minutes(10):
            raise GdprConflict(
                "This deletion job is already running",
                code="already_running",
            )
    if not row.user_id:
        raise GdprConflict("Account is no longer linked to this request", code="missing_subject")
    await admin_approval_service.require_approved_for_resource(
        db,
        request_type="account_deletion",
        resource_id=str(row.id),
        payload={"gdpr_request_id": str(row.id), "user_id": str(row.user_id)},
        actor=actor,
        request=request,
    )

    holds = await _active_holds_for(db, [str(row.user_id)])
    if str(row.user_id) in holds:
        previous = row.status
        row.status = "blocked"
        row.legal_hold_blocked = True
        row.failure_code = "legal_hold"
        row.failure_detail = "An active legal hold blocks this deletion"
        row.finished_at = None
        await _append_event(
            db,
            row,
            event="deletion.blocked_by_legal_hold",
            actor_type="admin",
            actor_user_id=str(actor.user_id),
            from_status=previous,
            to_status="blocked",
        )
        await record_admin_audit(
            db,
            actor=actor,
            action="gdpr.deletion.blocked",
            target_type="gdpr_request",
            target_id=str(row.id),
            reason="Active legal hold",
            before={"status": previous},
            after={"status": "blocked", "failure_code": "legal_hold"},
            metadata={
                "gdpr_request_id": str(row.id),
                "target_user_id": str(row.user_id),
                "request_type": DELETION,
            },
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        logger.warning("GDPR deletion blocked by legal hold request_id=%s", str(row.id))
        raise GdprLegalHoldBlocked(_admin_request_payload(row, user_email=None, legal_hold_active=True))

    previous = row.status
    row.status = "processing"
    row.legal_hold_blocked = False
    row.failure_code = None
    row.failure_detail = None
    if note:
        row.legal_review_note = (note or "").strip()[:2000] or row.legal_review_note
    row.attempts = int(row.attempts or 0) + 1
    await _append_event(
        db,
        row,
        event="deletion.started",
        actor_type="admin",
        actor_user_id=str(actor.user_id),
        from_status=previous,
        to_status="processing",
        reason=(note or "")[:1000] or None,
        metadata={"attempt": row.attempts},
    )
    await db.commit()
    logger.info(
        "GDPR deletion started request_id=%s attempt=%s",
        str(row.id),
        row.attempts,
    )

    results: List[Dict[str, Any]] = []
    for step in DELETION_STEPS:
        try:
            async with db.begin_nested():
                affected = await _run_deletion_step(db, step, str(row.user_id))
            results.append(
                {
                    "table": step.table,
                    "step": step.key,
                    "action": step.action,
                    "status": "completed",
                    "rows_affected": affected,
                    "description": step.description,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report per-table failure
            results.append(
                {
                    "table": step.table,
                    "step": step.key,
                    "action": step.action,
                    "status": "failed",
                    "rows_affected": 0,
                    "error_code": _safe_failure_code(exc),
                    "description": step.description,
                }
            )
            logger.error(
                "GDPR deletion step failed request_id=%s table=%s error_type=%s",
                str(row.id),
                step.table,
                type(exc).__name__,
            )

    for retained in RETENTION_STEPS:
        results.append(
            {
                "table": retained.table,
                "step": f"retain_{retained.table}",
                "action": "retain",
                "status": "retained",
                "rows_affected": 0,
                "reason": retained.reason,
                "category": retained.category,
            }
        )

    failed = [item for item in results if item["status"] == "failed"]
    row.table_results = results
    row.legal_hold_blocked = False
    if failed:
        row.status = "failed"
        row.failure_code = "partial_failure"
        row.failure_detail = (
            f"{len(failed)} table(s) could not be cleared; retry this job to complete the remaining steps"
        )
        row.finished_at = None
        await _append_event(
            db,
            row,
            event="deletion.failed",
            actor_type="system",
            from_status="processing",
            to_status="failed",
            metadata={
                "failed_tables": [item["table"] for item in failed],
                "attempt": row.attempts,
            },
        )
        await record_admin_audit(
            db,
            actor=actor,
            action="gdpr.deletion.failed",
            target_type="gdpr_request",
            target_id=str(row.id),
            reason=row.failure_detail,
            before={"status": "processing"},
            after={"status": "failed", "failed_tables": [item["table"] for item in failed]},
            metadata={
                "gdpr_request_id": str(row.id),
                "target_user_id": str(row.user_id),
                "request_type": DELETION,
                "attempt": row.attempts,
            },
            request=request,
        )
        await admin_approval_service.sync_execution(
            db,
            request_type="account_deletion",
            resource_id=str(row.id),
            actor=actor,
            failed=True,
            note=note,
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        logger.warning(
            "GDPR deletion partially failed request_id=%s failed_tables=%s",
            str(row.id),
            len(failed),
        )
    else:
        row.status = "completed"
        row.failure_code = None
        row.failure_detail = None
        row.finished_at = _now()
        await _append_event(
            db,
            row,
            event="deletion.completed",
            actor_type="system",
            from_status="processing",
            to_status="completed",
            metadata={
                "tables_completed": len([item for item in results if item["status"] == "completed"]),
                "tables_retained": len([item for item in results if item["status"] == "retained"]),
                "attempt": row.attempts,
            },
        )
        await record_admin_audit(
            db,
            actor=actor,
            action="gdpr.deletion.completed",
            target_type="gdpr_request",
            target_id=str(row.id),
            reason=(note or "")[:1000] or None,
            before={"status": "processing"},
            after={"status": "completed"},
            metadata={
                "gdpr_request_id": str(row.id),
                "target_user_id": str(row.user_id),
                "request_type": DELETION,
                "attempt": row.attempts,
            },
            request=request,
        )
        await admin_approval_service.sync_execution(
            db,
            request_type="account_deletion",
            resource_id=str(row.id),
            actor=actor,
            result={"status": "completed", "attempt": row.attempts},
            note=note,
            request=request,
        )
        await db.commit()
        await db.refresh(row)
        logger.info("GDPR deletion completed request_id=%s", str(row.id))

    return _admin_request_payload(row, user_email=None, legal_hold_active=False)


async def place_legal_hold(
    db: AsyncSession,
    *,
    user_id: str,
    reason: str,
    actor: AdminActor,
    request: Request | None = None,
) -> Dict[str, Any]:
    user = await db.get(User, str(user_id))
    if user is None:
        raise GdprNotFound("Account not found")
    if user.email.endswith("@privacy.invalid"):
        raise GdprConflict("Account is already anonymized", code="already_anonymized")
    existing = (
        await db.execute(
            select(GdprLegalHold).where(
                GdprLegalHold.user_id == str(user_id),
                GdprLegalHold.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise GdprConflict("An active legal hold already exists", code="hold_exists")
    row = GdprLegalHold(
        id=str(uuid.uuid4()),
        user_id=str(user_id),
        active=True,
        reason=(reason or "").strip()[:2000],
        placed_by=str(actor.user_id)[:36],
        placed_email=actor.email,
    )
    db.add(row)
    await record_admin_audit(
        db,
        actor=actor,
        action="gdpr.legal_hold.placed",
        target_type="gdpr_legal_hold",
        target_id=str(row.id),
        reason=row.reason,
        after={"active": True, "user_id": str(user_id)},
        metadata={
            "gdpr_legal_hold_id": str(row.id),
            "target_user_id": str(user_id),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    logger.warning(
        "GDPR legal hold placed hold_id=%s target_user_id=%s actor=%s",
        str(row.id),
        str(user_id),
        str(actor.user_id)[:36],
    )
    return _legal_hold_payload(row, user_email=user.email)


async def release_legal_hold(
    db: AsyncSession,
    *,
    hold_id: str,
    reason: str,
    actor: AdminActor,
    request: Request | None = None,
) -> Dict[str, Any]:
    row = (
        await db.execute(
            select(GdprLegalHold)
            .where(GdprLegalHold.id == str(hold_id), GdprLegalHold.active.is_(True))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise GdprNotFound("Active legal hold not found")
    row.active = False
    row.released_by = str(actor.user_id)[:36]
    row.released_email = actor.email
    row.released_at = _now()
    row.release_reason = (reason or "").strip()[:2000]
    await record_admin_audit(
        db,
        actor=actor,
        action="gdpr.legal_hold.released",
        target_type="gdpr_legal_hold",
        target_id=str(row.id),
        reason=row.release_reason,
        before={"active": True},
        after={"active": False},
        metadata={
            "gdpr_legal_hold_id": str(row.id),
            "target_user_id": str(row.user_id),
        },
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    user = await db.get(User, str(row.user_id))
    logger.info(
        "GDPR legal hold released hold_id=%s target_user_id=%s",
        str(row.id),
        str(row.user_id),
    )
    return _legal_hold_payload(row, user_email=user.email if user else None)


def _legal_hold_payload(row: GdprLegalHold, *, user_email: str | None) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "user_email_masked": mask_email(user_email),
        "active": bool(row.active),
        "reason": row.reason,
        "placed_by": row.placed_by,
        "placed_at": _iso(row.placed_at),
        "released_by": row.released_by,
        "released_at": _iso(row.released_at),
        "release_reason": row.release_reason,
    }


async def list_legal_holds(db: AsyncSession, *, active_only: bool = True, limit: int = 100) -> List[Dict[str, Any]]:
    stmt = select(GdprLegalHold, User.email).outerjoin(User, GdprLegalHold.user_id == User.id)
    if active_only:
        stmt = stmt.where(GdprLegalHold.active.is_(True))
    rows = (await db.execute(stmt.order_by(GdprLegalHold.placed_at.desc()).limit(max(1, min(limit, 200))))).all()
    return [_legal_hold_payload(row, user_email=email) for row, email in rows]

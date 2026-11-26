"""Admin-only CSV/PDF exports, signed downloads and scheduled digests.

The export surface is deliberately aggregate-only. It never reads resume or
document content, prompts, PDFs, emails, tokens, raw IP addresses or provider
payloads. The audit report reads the append-only operator audit log but omits
actor emails, IP addresses, reasons, before/after state and metadata.

No migration is required for this feature:

* Export history is event-sourced in ``admin_audit_log`` (one append-only row
  per generated export and per signed download).
* Scheduled-digest configuration is the latest
  ``admin.export.digest_configured`` audit event for an admin. Run outcomes are
  ``admin.export.digest_sent`` / ``admin.export.digest_failed`` events.

Every file embeds a schema version, generation time, range and normalized
filters. CSV is generated lazily in bounded batches; large exports are handed
to the caller as a short-lived HMAC-signed URL bound to the requesting admin.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, AsyncIterator, Mapping, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import PLAN_FAMILY_ALIASES, resolve_plan_family, settings
from ..core.redis import get_redis_client
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit
from .email_service import email_service

AdminAuditLog = models.AdminAuditLog
Compilation = models.Compilation
Optimization = models.Optimization
Payment = models.Payment
Resume = models.Resume
Subscription = models.Subscription
User = models.User

REPORT_SCHEMA_VERSION = "1"
MIN_GROUP_USERS = 5
MAX_RANGE_DAYS = 365
MAX_CSV_ROWS = 10_000
MAX_PDF_ROWS = 2_000
SYNC_ROW_THRESHOLD = 2_000
AUDIT_BATCH_SIZE = 250
MAX_DIGEST_RECIPIENTS = 10
DIGEST_PREVIEW_ROWS = 12

REPORTS: dict[str, dict[str, Any]] = {
    "overview": {
        "label": "Platform overview",
        "description": "Aggregate users, resumes, compilations and optimizations.",
        "filters": ("plan", "compiler"),
        "formats": ("csv", "pdf"),
        "aliases": ("analytics",),
    },
    "billing": {
        "label": "Billing summary",
        "description": "Aggregate subscription and payment counts by plan/status.",
        "filters": ("plan", "status"),
        "formats": ("csv", "pdf"),
    },
    "users": {
        "label": "User cohorts",
        "description": "Aggregate user counts by role, plan and subscription status.",
        "filters": ("role", "plan", "status"),
        "formats": ("csv", "pdf"),
    },
    "audit": {
        "label": "Admin audit",
        "description": "Operator audit actions without actor email, IP or payloads.",
        "filters": ("action", "target_type"),
        "formats": ("csv", "pdf"),
    },
}

# The analytics report is the platform overview; accept the older public name
# so API clients written against issue #2180 keep working.
REPORT_ALIASES = {"analytics": "overview"}

EXPORT_ACTIONS = ("admin.export.generated", "admin.export.downloaded")
DIGEST_CONFIG_ACTION = "admin.export.digest_configured"
DIGEST_SENT_ACTION = "admin.export.digest_sent"
DIGEST_FAILED_ACTION = "admin.export.digest_failed"
DIGEST_DRY_RUN_ACTION = "admin.export.digest_dry_run"

DIGEST_FREQUENCIES = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
DIGEST_REPORTS = ("overview", "billing", "users")
DIGEST_FORMATS = ("summary", "csv")

FILTER_KEYS: dict[str, tuple[str, ...]] = {report: tuple(spec["filters"]) for report, spec in REPORTS.items()}

_ACTION_RE = r"^[a-z][a-z0-9_.-]{2,119}$"
_TARGET_TYPE_RE = r"^[a-z][a-z0-9_.-]{1,49}$"


class AdminExportError(RuntimeError):
    """Base error with a safe HTTP status and caller-visible detail."""

    status_code = 400
    code = "admin_export_error"

    def __init__(self, message: str, *, code: str | None = None):
        self.detail = message
        self.code = code or self.code
        super().__init__(message)


class AdminExportValidationError(AdminExportError):
    status_code = 422
    code = "invalid_export"


class AdminExportForbidden(AdminExportError):
    status_code = 403
    code = "export_forbidden"


class AdminExportRateLimited(AdminExportError):
    status_code = 429
    code = "export_rate_limited"

    def __init__(self, message: str = "Too many export requests; retry shortly"):
        self.retry_after = 60
        super().__init__(message)


class AdminExportSigningUnavailable(AdminExportError):
    status_code = 503
    code = "export_signing_unavailable"


@dataclass(frozen=True)
class ExportSpec:
    """A validated, bounded export request."""

    report: str
    format: str
    days: int
    start_date: date
    end_date: date
    filters: dict[str, str]

    @property
    def row_cap(self) -> int:
        return MAX_PDF_ROWS if self.format == "pdf" else MAX_CSV_ROWS

    @property
    def start_at(self) -> datetime:
        return datetime.combine(self.start_date, time.min, tzinfo=timezone.utc)

    @property
    def end_at(self) -> datetime:
        return datetime.combine(self.end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)

    def filter_json(self) -> str:
        return json.dumps(self.filters, sort_keys=True, separators=(",", ":"))

    def range_payload(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
        }


@dataclass
class PreparedReport:
    """Bounded report data plus its metadata contract."""

    spec: ExportSpec
    headers: tuple[str, ...]
    generated_at: datetime
    row_count: int
    rows: list[list[Any]]
    suppressed: bool
    truncated: bool
    notes: list[str]
    operator_audit: bool = False

    def metadata_rows(self) -> list[list[Any]]:
        return [
            ["#meta", "schema_version", REPORT_SCHEMA_VERSION],
            ["#meta", "generated_at", self.generated_at.isoformat()],
            ["#meta", "report", self.spec.report],
            ["#meta", "format", self.spec.format],
            ["#meta", "range_start", self.spec.start_date.isoformat()],
            ["#meta", "range_end", self.spec.end_date.isoformat()],
            ["#meta", "days", str(self.spec.days)],
            ["#meta", "filters", self.spec.filter_json()],
            ["#meta", "row_cap", str(self.spec.row_cap)],
            ["#meta", "row_count", str(self.row_count)],
            ["#meta", "minimum_users", str(MIN_GROUP_USERS)],
            ["#meta", "suppressed", "true" if self.suppressed else "false"],
            ["#meta", "truncated", "true" if self.truncated else "false"],
            ["#meta", "operator_audit", "true" if self.operator_audit else "false"],
        ]


@dataclass
class DigestConfig:
    enabled: bool
    frequency: str
    recipient_user_ids: tuple[str, ...]
    report: str
    format: str
    days: int
    start_date: date | None
    end_date: date | None
    filters: dict[str, str]
    configured_at: datetime | None = None
    updated: bool = False

    def public_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "frequency": self.frequency,
            "recipient_user_ids": list(self.recipient_user_ids),
            "recipient_count": len(self.recipient_user_ids),
            "report": self.report,
            "format": self.format,
            "days": self.days,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "filters": dict(self.filters),
            "configured_at": self.configured_at.isoformat() if self.configured_at else None,
            "updated": self.updated,
            "schema_version": REPORT_SCHEMA_VERSION,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _today() -> date:
    return _now().date()


def _normalize_plan(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    if not cleaned:
        return None
    return resolve_plan_family(cleaned) if cleaned in PLAN_FAMILY_ALIASES else cleaned


def _normalize_text(value: str | None, *, max_length: int) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise AdminExportValidationError(f"Filter value exceeds {max_length} characters")
    return cleaned.lower()


def normalize_filters(report: str, filters: Mapping[str, Any] | None) -> dict[str, str]:
    """Apply the per-report filter allowlist and bounded normalization."""
    report = REPORT_ALIASES.get(str(report).strip().lower(), str(report).strip().lower())
    if report not in REPORTS:
        raise AdminExportValidationError("Unknown export report")
    allowed = FILTER_KEYS[report]
    raw = filters or {}
    if not isinstance(raw, Mapping):
        raise AdminExportValidationError("filters must be an object")
    unknown = {str(key) for key in raw if str(key) not in allowed and raw.get(key) not in (None, "")}
    if unknown:
        raise AdminExportValidationError(f"Unsupported filter(s): {', '.join(sorted(unknown))}")
    normalized: dict[str, str] = {}
    for key in allowed:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise AdminExportValidationError(f"Filter '{key}' must be a string")
        if key == "plan":
            cleaned = _normalize_plan(value)
        elif key == "role":
            cleaned = _normalize_text(value, max_length=20)
        elif key in {"action", "target_type"}:
            cleaned = _normalize_text(value, max_length=120 if key == "action" else 50)
        else:
            cleaned = _normalize_text(value, max_length=50)
        if cleaned:
            normalized[key] = cleaned
    if "action" in normalized and normalized["action"] and not _matches(normalized["action"], _ACTION_RE):
        raise AdminExportValidationError("action filter is not a valid audit action")
    if (
        "target_type" in normalized
        and normalized["target_type"]
        and not _matches(normalized["target_type"], _TARGET_TYPE_RE)
    ):
        raise AdminExportValidationError("target_type filter is not a valid audit target type")
    return normalized


def _matches(value: str, pattern: str) -> bool:
    import re

    return re.fullmatch(pattern, value) is not None


def _resolve_window(
    days: int | None,
    start_date: date | str | None,
    end_date: date | str | None,
    *,
    today: date | None = None,
) -> tuple[int, date, date]:
    current = today or _today()
    if (start_date is None) != (end_date is None):
        raise AdminExportValidationError("start_date and end_date must be provided together")
    if start_date is not None and end_date is not None:
        try:
            start_day = (
                start_date.date()
                if isinstance(start_date, datetime)
                else start_date
                if isinstance(start_date, date)
                else date.fromisoformat(str(start_date))
            )
            end_day = (
                end_date.date()
                if isinstance(end_date, datetime)
                else end_date
                if isinstance(end_date, date)
                else date.fromisoformat(str(end_date))
            )
        except (TypeError, ValueError) as exc:
            raise AdminExportValidationError("Invalid date range") from exc
        if end_day < start_day:
            raise AdminExportValidationError("end_date must be on or after start_date")
        if end_day > current:
            raise AdminExportValidationError("end_date cannot be in the future")
        span = (end_day - start_day).days + 1
        if span > MAX_RANGE_DAYS:
            raise AdminExportValidationError(f"Date range cannot exceed {MAX_RANGE_DAYS} days")
        return span, start_day, end_day
    try:
        requested = int(days if days is not None else 30)
    except (TypeError, ValueError) as exc:
        raise AdminExportValidationError("days must be an integer") from exc
    if requested < 1 or requested > MAX_RANGE_DAYS:
        raise AdminExportValidationError(f"days must be between 1 and {MAX_RANGE_DAYS}")
    end_day = current
    start_day = end_day - timedelta(days=requested - 1)
    return requested, start_day, end_day


def normalize_spec(
    *,
    report: str,
    export_format: str = "csv",
    days: int | None = 30,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    filters: Mapping[str, Any] | None = None,
) -> ExportSpec:
    """Validate report, format, range and filters in one place."""
    canonical_report = REPORT_ALIASES.get(str(report).strip().lower(), str(report).strip().lower())
    if canonical_report not in REPORTS:
        raise AdminExportValidationError("Unknown export report")
    fmt = (export_format or "csv").strip().lower()
    if fmt not in REPORTS[canonical_report]["formats"]:
        raise AdminExportValidationError("Unsupported export format for this report")
    span, start_day, end_day = _resolve_window(days, start_date, end_date)
    normalized = normalize_filters(canonical_report, filters)
    return ExportSpec(
        report=canonical_report,
        format=fmt,
        days=span,
        start_date=start_day,
        end_date=end_day,
        filters=normalized,
    )


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str:
    return _as_utc(value).isoformat() if value else ""


def _csv_headers(report: str) -> tuple[str, ...]:
    base = ("window_start", "window_end", "generated_at", "schema_version")
    if report == "overview":
        return ("section", "metric", "value", "unit", "distinct_users") + base
    if report == "billing":
        return ("section", "plan", "status", "currency", "records", "amount_minor", "distinct_users") + base
    if report == "users":
        return ("role", "plan", "subscription_status", "users", "verified_users") + base
    return ("created_at", "action", "target_type", "actor_ref") + base


def _overview_notes() -> list[str]:
    return [
        "Counts are aggregate only; rows with fewer than 5 distinct users are hidden.",
        "No resume/document content, prompts, emails, tokens or per-user rows are read.",
        "Plan filters apply where the dimension exists; compiler filters apply to compilations only.",
    ]


def _billing_notes() -> list[str]:
    return [
        "Subscription and payment rows are grouped and suppressed below 5 distinct users.",
        "Amounts are provider minor units and are never attributed to an individual.",
        "No provider payloads, payment identifiers, emails or invoice documents are read.",
    ]


def _users_notes() -> list[str]:
    return [
        "Only role/plan/status cohort counts are returned.",
        "No names, emails, account identifiers or per-user histories are read.",
        "Cohorts below 5 distinct users are hidden.",
    ]


def _audit_notes() -> list[str]:
    return [
        "Operator audit rows are listed without actor email, IP address, reason, before/after state or metadata.",
        "actor_ref is a one-way short hash used only to distinguish operators within the file.",
        "No end-user document or activity history is included.",
    ]


def _metric_scope(
    model: Any,
    spec: ExportSpec,
    *,
    user_column: Any | None = None,
) -> Any:
    """Build a count/count-distinct select, optionally joined to the owner plan."""
    owner_column = user_column if user_column is not None else model.user_id
    stmt = select(func.count(), func.count(func.distinct(owner_column)))
    extra: list[Any] = []
    if "plan" in spec.filters:
        stmt = stmt.join(User, User.id == model.user_id)
        extra.append(User.subscription_plan == spec.filters["plan"])
    return stmt.where(
        model.created_at >= spec.start_at,
        model.created_at < spec.end_at,
        *extra,
    )


async def _run_metric(db: AsyncSession, stmt: Any) -> tuple[int, int]:
    row = (await db.execute(stmt)).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _metric(
    db: AsyncSession,
    model: Any,
    *,
    start_at: datetime,
    end_at: datetime,
    conditions: Sequence[Any] = (),
    user_column: Any | None = None,
) -> tuple[int, int]:
    owner_column = user_column if user_column is not None else model.user_id
    stmt = select(
        func.count(),
        func.count(func.distinct(owner_column)),
    ).where(model.created_at >= start_at, model.created_at < end_at, *conditions)
    row = (await db.execute(stmt)).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _build_overview(db: AsyncSession, spec: ExportSpec, generated_at: datetime) -> PreparedReport:
    conditions: list[Any] = []
    user_conditions: list[Any] = []
    if "plan" in spec.filters:
        conditions.append(Compilation.plan_family == spec.filters["plan"])
        user_conditions.append(User.subscription_plan == spec.filters["plan"])
    if "compiler" in spec.filters:
        conditions.append(Compilation.compiler == spec.filters["compiler"])

    metrics = [
        (
            "users",
            "new_users",
            await _metric(
                db,
                User,
                start_at=spec.start_at,
                end_at=spec.end_at,
                conditions=user_conditions,
                user_column=User.id,
            ),
        ),
        ("resumes", "resumes_created", await _run_metric(db, _metric_scope(Resume, spec))),
        (
            "compilations",
            "total",
            await _metric(db, Compilation, start_at=spec.start_at, end_at=spec.end_at, conditions=conditions),
        ),
        (
            "compilations",
            "completed",
            await _metric(
                db,
                Compilation,
                start_at=spec.start_at,
                end_at=spec.end_at,
                conditions=[*conditions, Compilation.status == "completed"],
            ),
        ),
        (
            "compilations",
            "failed",
            await _metric(
                db,
                Compilation,
                start_at=spec.start_at,
                end_at=spec.end_at,
                conditions=[*conditions, Compilation.status == "failed"],
            ),
        ),
        ("optimizations", "total", await _run_metric(db, _metric_scope(Optimization, spec))),
    ]

    headers = _csv_headers("overview")
    rows: list[list[Any]] = []
    hidden = 0
    for section, metric_name, (count, users) in metrics:
        if users < MIN_GROUP_USERS:
            hidden += 1
            continue
        rows.append(
            [
                section,
                metric_name,
                count,
                "events" if metric_name != "new_users" else "users",
                users,
                spec.start_date.isoformat(),
                spec.end_date.isoformat(),
                generated_at.isoformat(),
                REPORT_SCHEMA_VERSION,
            ]
        )
    suppressed = bool(metrics) and not rows
    return PreparedReport(
        spec=spec,
        headers=headers,
        generated_at=generated_at,
        row_count=len(rows),
        rows=rows,
        suppressed=suppressed,
        truncated=False,
        notes=_overview_notes() + ([f"{hidden} metrics hidden under the five-user rule."] if hidden else []),
    )


async def _build_billing(db: AsyncSession, spec: ExportSpec, generated_at: datetime) -> PreparedReport:
    subscription_conditions: list[Any] = []
    if "plan" in spec.filters:
        subscription_conditions.append(Subscription.plan_id == spec.filters["plan"])
    if "status" in spec.filters:
        subscription_conditions.append(Subscription.status == spec.filters["status"])

    subscription_rows = (
        await db.execute(
            select(
                Subscription.plan_id,
                Subscription.status,
                func.count(),
                func.count(func.distinct(Subscription.user_id)),
            )
            .where(
                Subscription.created_at >= spec.start_at,
                Subscription.created_at < spec.end_at,
                *subscription_conditions,
            )
            .group_by(Subscription.plan_id, Subscription.status)
            .order_by(Subscription.plan_id, Subscription.status)
        )
    ).all()

    payment_conditions: list[Any] = []
    if "status" in spec.filters:
        payment_conditions.append(Payment.status == spec.filters["status"])
    payment_stmt = (
        select(
            Subscription.plan_id,
            Payment.status,
            Payment.currency,
            func.count(),
            func.coalesce(func.sum(Payment.amount), 0),
            func.count(func.distinct(Payment.user_id)),
        )
        .outerjoin(Subscription, Subscription.id == Payment.subscription_id)
        .where(Payment.created_at >= spec.start_at, Payment.created_at < spec.end_at, *payment_conditions)
    )
    if "plan" in spec.filters:
        payment_stmt = payment_stmt.where(Subscription.plan_id == spec.filters["plan"])
    payment_rows = (
        await db.execute(
            payment_stmt.group_by(Subscription.plan_id, Payment.status, Payment.currency).order_by(
                Subscription.plan_id, Payment.status, Payment.currency
            )
        )
    ).all()

    headers = _csv_headers("billing")
    rows: list[list[Any]] = []
    hidden = 0
    for plan_id, status, count, users in subscription_rows:
        if int(users or 0) < MIN_GROUP_USERS:
            hidden += 1
            continue
        rows.append(
            [
                "subscriptions",
                plan_id or "",
                status or "",
                "",
                int(count or 0),
                "",
                int(users or 0),
                spec.start_date.isoformat(),
                spec.end_date.isoformat(),
                generated_at.isoformat(),
                REPORT_SCHEMA_VERSION,
            ]
        )
    for plan_id, status, currency, count, amount, users in payment_rows:
        if int(users or 0) < MIN_GROUP_USERS:
            hidden += 1
            continue
        rows.append(
            [
                "payments",
                plan_id or "",
                status or "",
                currency or "",
                int(count or 0),
                int(amount or 0),
                int(users or 0),
                spec.start_date.isoformat(),
                spec.end_date.isoformat(),
                generated_at.isoformat(),
                REPORT_SCHEMA_VERSION,
            ]
        )
    suppressed = not rows
    return PreparedReport(
        spec=spec,
        headers=headers,
        generated_at=generated_at,
        row_count=len(rows),
        rows=rows,
        suppressed=suppressed,
        truncated=False,
        notes=_billing_notes() + ([f"{hidden} cohorts hidden under the five-user rule."] if hidden else []),
    )


async def _build_users(db: AsyncSession, spec: ExportSpec, generated_at: datetime) -> PreparedReport:
    conditions: list[Any] = []
    if "role" in spec.filters:
        conditions.append(User.role == spec.filters["role"])
    if "plan" in spec.filters:
        conditions.append(User.subscription_plan == spec.filters["plan"])
    if "status" in spec.filters:
        conditions.append(User.subscription_status == spec.filters["status"])

    group_rows = (
        await db.execute(
            select(
                User.role,
                User.subscription_plan,
                User.subscription_status,
                func.count(),
                func.count().filter(User.email_verified.is_(True)),
            )
            .where(*conditions)
            .group_by(User.role, User.subscription_plan, User.subscription_status)
            .order_by(User.role, User.subscription_plan, User.subscription_status)
        )
    ).all()

    headers = _csv_headers("users")
    rows: list[list[Any]] = []
    hidden = 0
    for role, plan, status, count, verified in group_rows:
        if int(count or 0) < MIN_GROUP_USERS:
            hidden += 1
            continue
        rows.append(
            [
                role or "",
                plan or "",
                status or "",
                int(count or 0),
                int(verified or 0),
                spec.start_date.isoformat(),
                spec.end_date.isoformat(),
                generated_at.isoformat(),
                REPORT_SCHEMA_VERSION,
            ]
        )
    suppressed = not rows
    return PreparedReport(
        spec=spec,
        headers=headers,
        generated_at=generated_at,
        row_count=len(rows),
        rows=rows,
        suppressed=suppressed,
        truncated=False,
        notes=_users_notes() + ([f"{hidden} cohorts hidden under the five-user rule."] if hidden else []),
    )


def _actor_ref(actor_user_id: str | None) -> str:
    if not actor_user_id:
        return "system"
    return hashlib.sha256(b"latexy.admin.export.actor.v1:" + str(actor_user_id).encode("utf-8")).hexdigest()[:12]


def _audit_conditions(spec: ExportSpec) -> list[Any]:
    conditions: list[Any] = [
        AdminAuditLog.created_at >= spec.start_at,
        AdminAuditLog.created_at < spec.end_at,
    ]
    if "action" in spec.filters:
        conditions.append(AdminAuditLog.action == spec.filters["action"])
    if "target_type" in spec.filters:
        conditions.append(AdminAuditLog.target_type == spec.filters["target_type"])
    return conditions


async def _count_audit_rows(db: AsyncSession, spec: ExportSpec) -> int:
    stmt = select(func.count()).select_from(AdminAuditLog).where(*_audit_conditions(spec))
    return int((await db.execute(stmt)).scalar_one() or 0)


def _audit_row_values(row: Any, spec: ExportSpec, generated_at: datetime) -> list[Any]:
    return [
        _iso(row.created_at),
        row.action,
        row.target_type,
        _actor_ref(row.actor_user_id),
        spec.start_date.isoformat(),
        spec.end_date.isoformat(),
        generated_at.isoformat(),
        REPORT_SCHEMA_VERSION,
    ]


async def _iter_audit_rows(db: AsyncSession, spec: ExportSpec, generated_at: datetime) -> AsyncIterator[list[Any]]:
    """Stream audit rows in keyset batches, never materializing the full set."""
    emitted = 0
    cursor_at: datetime | None = None
    cursor_id: str | None = None
    while emitted < spec.row_cap:
        conditions = _audit_conditions(spec)
        if cursor_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    AdminAuditLog.created_at < cursor_at,
                    and_(AdminAuditLog.created_at == cursor_at, AdminAuditLog.id < cursor_id),
                )
            )
        batch = (
            await db.execute(
                select(
                    AdminAuditLog.created_at,
                    AdminAuditLog.action,
                    AdminAuditLog.target_type,
                    AdminAuditLog.actor_user_id,
                    AdminAuditLog.id,
                )
                .where(*conditions)
                .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                .limit(min(AUDIT_BATCH_SIZE, spec.row_cap - emitted))
            )
        ).all()
        if not batch:
            break
        for row in batch:
            yield _audit_row_values(row, spec, generated_at)
            emitted += 1
            if emitted >= spec.row_cap:
                break
        cursor_at = _as_utc(batch[-1].created_at)
        cursor_id = str(batch[-1].id)


async def prepare_report(db: AsyncSession, spec: ExportSpec, *, generated_at: datetime | None = None) -> PreparedReport:
    """Build a bounded report; row-level reports keep a lazy iterator."""
    generated_at = generated_at or _now()
    if spec.report == "overview":
        return await _build_overview(db, spec, generated_at)
    if spec.report == "billing":
        return await _build_billing(db, spec, generated_at)
    if spec.report == "users":
        return await _build_users(db, spec, generated_at)

    total = await _count_audit_rows(db, spec)
    capped = min(total, spec.row_cap)
    return PreparedReport(
        spec=spec,
        headers=_csv_headers("audit"),
        generated_at=generated_at,
        row_count=capped,
        rows=[],
        suppressed=False,
        truncated=total > spec.row_cap,
        notes=_audit_notes(),
        operator_audit=True,
    )


def iter_prepared_rows(db: AsyncSession, prepared: PreparedReport) -> AsyncIterator[list[Any]]:
    """Yield rows for a prepared report, lazily for row-level audit data."""
    if prepared.operator_audit:
        return _iter_audit_rows(db, prepared.spec, prepared.generated_at)
    return _iter_static_rows(prepared.rows)


async def _iter_static_rows(rows: Sequence[Sequence[Any]]) -> AsyncIterator[list[Any]]:
    for row in rows:
        yield list(row)


async def load_report_rows(
    db: AsyncSession, spec: ExportSpec, *, limit: int, generated_at: datetime | None = None
) -> PreparedReport:
    """Load at most ``limit`` rows, used by PDF and digest previews."""
    prepared = await prepare_report(db, spec, generated_at=generated_at)
    if not prepared.operator_audit:
        if len(prepared.rows) > limit:
            prepared.truncated = True
        prepared.rows = prepared.rows[:limit]
        prepared.row_count = len(prepared.rows)
        return prepared
    original_total = prepared.row_count
    prepared.rows = []
    async for row in _iter_audit_rows(db, spec, prepared.generated_at):
        if len(prepared.rows) >= limit:
            prepared.truncated = True
            break
        prepared.rows.append(row)
    prepared.row_count = len(prepared.rows)
    prepared.truncated = original_total > limit or prepared.truncated
    return prepared


# ---------------------------------------------------------------------------
# CSV / PDF rendering
# ---------------------------------------------------------------------------


def safe_csv_cell(value: Any) -> Any:
    """Neutralise spreadsheet formulas in every string cell."""
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n\ufeff")
    if candidate[:1] in {"=", "+", "-", "@"} or value[:1] in {"\t", "\r"}:
        return f"'{value}"
    return value


def _csv_line(values: Sequence[Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([safe_csv_cell(value) for value in values])
    return buffer.getvalue()


async def iter_report_csv(db: AsyncSession, prepared: PreparedReport) -> AsyncIterator[str]:
    """Yield a CSV stream with metadata rows and constant-memory row batches."""
    for row in prepared.metadata_rows():
        yield _csv_line(row)
    yield _csv_line(prepared.headers)
    async for row in iter_prepared_rows(db, prepared):
        yield _csv_line(row)


def report_metadata_payload(prepared: PreparedReport) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": prepared.generated_at.isoformat(),
        "report": prepared.spec.report,
        "format": prepared.spec.format,
        "range": {
            "start_date": prepared.spec.start_date.isoformat(),
            "end_date": prepared.spec.end_date.isoformat(),
            "days": prepared.spec.days,
        },
        "filters": dict(prepared.spec.filters),
        "row_cap": prepared.spec.row_cap,
        "row_count": prepared.row_count,
        "minimum_users": MIN_GROUP_USERS,
        "suppressed": prepared.suppressed,
        "truncated": prepared.truncated,
        "notes": list(prepared.notes),
    }


# ---------------------------------------------------------------------------
# Minimal PDF writer (no external dependency, bounded ASCII text)
# ---------------------------------------------------------------------------


def _pdf_text(value: Any) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return "".join(char if 32 <= ord(char) <= 126 else "?" for char in text)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_pdf_line(value: Any, width: int = 92) -> list[str]:
    text = _pdf_text(value)
    if not text:
        return [""]
    return [text[index : index + width] for index in range(0, len(text), width)]


def render_report_pdf(prepared: PreparedReport) -> bytes:
    """Render a small, dependency-free PDF with filter summary and generation time."""
    lines: list[str] = [
        "Latexy admin export",
        f"Schema version: {REPORT_SCHEMA_VERSION}",
        f"Generated at: {prepared.generated_at.isoformat()}",
        f"Report: {prepared.spec.report}",
        f"Range: {prepared.spec.start_date.isoformat()} to {prepared.spec.end_date.isoformat()} ({prepared.spec.days} days)",
        f"Filters: {prepared.spec.filter_json()}",
        f"Rows: {prepared.row_count} / cap {prepared.spec.row_cap}",
        f"Suppressed: {'yes' if prepared.suppressed else 'no'}    Truncated: {'yes' if prepared.truncated else 'no'}",
        "",
        " | ".join(str(header) for header in prepared.headers),
    ]
    for note in prepared.notes:
        lines.extend(_wrap_pdf_line(f"Note: {note}"))
    lines.append("")
    for row in prepared.rows:
        lines.extend(_wrap_pdf_line(" | ".join(_pdf_text(value) for value in row)))

    lines_per_page = 54
    pages = [lines[index : index + lines_per_page] for index in range(0, len(lines), lines_per_page)] or [[""]]
    object_count = 3 + len(pages) * 2
    objects: list[bytes] = [b"", b"", b""]

    page_ids: list[int] = []
    for index, page_lines in enumerate(pages):
        content_id = 4 + index * 2
        page_id = 5 + index * 2
        page_ids.append(page_id)
        content_commands = ["BT", "/F1 9 Tf", "50 760 Td", "12 TL"]
        for line in page_lines:
            content_commands.append(f"({_pdf_escape(line)}) Tj")
            content_commands.append("T*")
        content_commands.append("ET")
        stream = "\n".join(content_commands).encode("ascii", "replace")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>"
    ).encode("ascii")
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {object_count + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (f"trailer\n<< /Size {object_count + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n").encode("ascii")
    )
    return bytes(output)


# ---------------------------------------------------------------------------
# Signed, actor-bound download tokens
# ---------------------------------------------------------------------------


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def _signing_key() -> bytes:
    configured = (getattr(settings, "ADMIN_EXPORT_SIGNING_KEY", "") or "").strip()
    if configured:
        return configured.encode("utf-8")
    gdpr = (getattr(settings, "GDPR_EXPORT_SIGNING_KEY", "") or "").strip()
    if gdpr:
        return hashlib.sha256(b"latexy.admin.export.v1:" + gdpr.encode("utf-8")).digest()
    base = (settings.BETTER_AUTH_SECRET or settings.JWT_SECRET_KEY or "").strip()
    if not base:
        raise AdminExportSigningUnavailable("Export signing is not configured")
    return hashlib.sha256(b"latexy.admin.export.v1:" + base.encode("utf-8")).digest()


def export_ttl_minutes() -> int:
    return max(1, min(int(getattr(settings, "ADMIN_EXPORT_TTL_MINUTES", 10) or 10), 15))


def issue_export_token(
    spec: ExportSpec,
    *,
    actor_user_id: str,
    export_id: str | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime, str]:
    """Issue an HMAC-signed token bound to one admin, report and range."""
    issued_at = now or _now()
    expires_at = issued_at + timedelta(minutes=export_ttl_minutes())
    export_id = export_id or str(uuid.uuid4())
    payload = {
        "v": 1,
        "eid": export_id,
        "uid": str(actor_user_id),
        "rep": spec.report,
        "fmt": spec.format,
        "days": spec.days,
        "start": spec.start_date.isoformat(),
        "end": spec.end_date.isoformat(),
        "filters": dict(spec.filters),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "nonce": uuid.uuid4().hex,
    }
    body = _b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}", expires_at, export_id


def validate_export_token(
    token: str,
    *,
    actor_user_id: str,
    now: datetime | None = None,
) -> tuple[ExportSpec, str]:
    """Validate signature, expiry, object scope and admin-actor binding."""
    if not token or token.count(".") != 1:
        raise AdminExportForbidden("Invalid or expired export download")
    body, signature = token.split(".", 1)
    try:
        expected = hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
        provided = _b64url_decode(signature)
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError, binascii.Error):
        raise AdminExportForbidden("Invalid or expired export download") from None
    if not hmac.compare_digest(expected, provided):
        raise AdminExportForbidden("Invalid or expired export download")
    if payload.get("v") != 1:
        raise AdminExportForbidden("Invalid or expired export download")
    if str(payload.get("uid")) != str(actor_user_id):
        raise AdminExportForbidden("This export download belongs to another admin")
    if expires_at <= (now or _now()):
        raise AdminExportForbidden("This export download has expired")
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise AdminExportForbidden("Invalid or expired export download")
    try:
        spec = normalize_spec(
            report=str(payload.get("rep")),
            export_format=str(payload.get("fmt")),
            days=int(payload.get("days")),
            start_date=date.fromisoformat(str(payload.get("start"))),
            end_date=date.fromisoformat(str(payload.get("end"))),
            filters=filters,
        )
    except (AdminExportValidationError, TypeError, ValueError):
        raise AdminExportForbidden("Invalid or expired export download") from None
    return spec, str(payload.get("eid"))


# ---------------------------------------------------------------------------
# Request throttling
# ---------------------------------------------------------------------------


async def allow_export_request(actor_user_id: str, *, window_seconds: int = 60, limit: int = 10) -> bool:
    """Bounded per-admin limiter; fails open only on Redis outages."""
    try:
        redis = await get_redis_client()
    except Exception:
        return True
    key = f"ratelimit:admin:exports:{str(actor_user_id)[:64]}"
    try:
        count = await redis.eval(
            """
            local n = redis.call('INCR', KEYS[1])
            if n == 1 then
              redis.call('EXPIRE', KEYS[1], ARGV[1])
            end
            return n
            """,
            1,
            key,
            window_seconds,
        )
        return int(count) <= limit
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Export history and audit
# ---------------------------------------------------------------------------


async def record_export_event(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    export_id: str,
    spec: ExportSpec,
    row_count: int,
    metadata: Mapping[str, Any] | None = None,
    request: Any = None,
) -> None:
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="admin_export",
        target_id=export_id,
        metadata={
            "report": spec.report,
            "format": spec.format,
            "range": spec.range_payload(),
            "filters": dict(spec.filters),
            "row_count": int(row_count),
            "row_cap": spec.row_cap,
            "schema_version": REPORT_SCHEMA_VERSION,
            **dict(metadata or {}),
        },
        request=request,
        commit=True,
    )


async def list_export_history(db: AsyncSession, *, actor_user_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Read the current admin's export audit events; no other actor data."""
    rows = (
        await db.execute(
            select(
                AdminAuditLog.id,
                AdminAuditLog.target_id,
                AdminAuditLog.action,
                AdminAuditLog.created_at,
                AdminAuditLog.event_metadata,
            )
            .where(
                AdminAuditLog.actor_user_id == actor_user_id,
                AdminAuditLog.target_type == "admin_export",
                AdminAuditLog.action.in_(EXPORT_ACTIONS),
            )
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .limit(max(1, min(int(limit), 100)))
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "export_id": row.target_id,
            "event": "downloaded" if row.action.endswith("downloaded") else "generated",
            "created_at": _iso(row.created_at),
            "metadata": row.event_metadata or {},
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Scheduled digest configuration and delivery
# ---------------------------------------------------------------------------


def _digest_row_state(row: Any) -> dict[str, Any]:
    state = getattr(row, "after_state", None)
    if isinstance(state, dict):
        return state
    if isinstance(row, Mapping):
        candidate = row.get("after_state")
        return candidate if isinstance(candidate, dict) else {}
    return {}


def _config_from_state(state: Mapping[str, Any], *, configured_at: datetime | None = None) -> DigestConfig:
    recipients = state.get("recipient_user_ids") or []
    filters = state.get("filters") if isinstance(state.get("filters"), dict) else {}
    return DigestConfig(
        enabled=bool(state.get("enabled")),
        frequency=str(state.get("frequency") or "weekly"),
        recipient_user_ids=tuple(str(item) for item in recipients if item),
        report=str(state.get("report") or "overview"),
        format=str(state.get("format") or "summary"),
        days=int(state.get("days") or 30),
        start_date=date.fromisoformat(str(state["start_date"])) if state.get("start_date") else None,
        end_date=date.fromisoformat(str(state["end_date"])) if state.get("end_date") else None,
        filters={str(key): str(value) for key, value in filters.items()},
        configured_at=configured_at,
    )


async def load_digest_config(db: AsyncSession, actor: AdminActor) -> DigestConfig:
    row = (
        await db.execute(
            select(AdminAuditLog.after_state, AdminAuditLog.created_at)
            .where(
                AdminAuditLog.target_type == "admin_digest",
                AdminAuditLog.target_id == actor.user_id,
                AdminAuditLog.action == DIGEST_CONFIG_ACTION,
            )
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return DigestConfig(
            enabled=False,
            frequency="weekly",
            recipient_user_ids=(actor.user_id,),
            report="overview",
            format="summary",
            days=30,
            start_date=None,
            end_date=None,
            filters={},
        )
    return _config_from_state(_digest_row_state(row), configured_at=_as_utc(row.created_at))


async def list_admin_recipients(db: AsyncSession, *, current_actor_user_id: str) -> list[dict[str, Any]]:
    """List verified administrator ids without exposing emails or names."""
    configured = settings.admin_email_set()
    rows = (
        await db.execute(
            select(User.id, User.email, User.role)
            .where(User.email_verified.is_(True), User.role.in_(["admin", "user", "support"]))
            .order_by(User.id)
            .limit(200)
        )
    ).all()
    result: list[dict[str, Any]] = []
    for user_id, email, role in rows:
        if role != "admin" and (not email or str(email).lower() not in configured):
            continue
        result.append(
            {
                "user_id": str(user_id),
                "role": "admin",
                "is_self": str(user_id) == str(current_actor_user_id),
            }
        )
    return result


async def digest_last_run(db: AsyncSession, actor_user_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(AdminAuditLog.action, AdminAuditLog.event_metadata, AdminAuditLog.created_at)
            .where(
                AdminAuditLog.target_type == "admin_digest",
                AdminAuditLog.target_id == actor_user_id,
                AdminAuditLog.action.in_([DIGEST_SENT_ACTION, DIGEST_FAILED_ACTION]),
            )
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    payload = dict(row.event_metadata or {})
    payload.setdefault("status", "sent" if row.action == DIGEST_SENT_ACTION else "failed")
    payload["finished_at"] = _iso(row.created_at)
    return payload


async def _approved_admin_ids(db: AsyncSession, ids: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return approved/verified admin ids and rejected ids, de-duplicated."""
    canonical: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        try:
            value = str(uuid.UUID(str(raw)))
        except (TypeError, ValueError, AttributeError):
            continue
        if value not in seen:
            seen.add(value)
            canonical.append(value)
    if not canonical:
        return [], []
    rows = (
        await db.execute(select(User.id, User.email, User.role, User.email_verified).where(User.id.in_(canonical)))
    ).all()
    configured_admins = settings.admin_email_set()
    approved: list[str] = []
    rejected: list[str] = []
    for user_id, email, role, verified in rows:
        normalized_id = str(user_id)
        is_admin = role == "admin" or (bool(email) and str(email).lower() in configured_admins and bool(verified))
        if is_admin and bool(verified):
            approved.append(normalized_id)
        else:
            rejected.append(normalized_id)
    rejected.extend(value for value in canonical if value not in {str(row[0]) for row in rows})
    return approved, rejected


async def save_digest_config(
    db: AsyncSession,
    *,
    actor: AdminActor,
    config: DigestConfig,
    reason: str,
    request: Any = None,
) -> DigestConfig:
    """Upsert-by-event: the latest config event is the current state."""
    if config.frequency not in DIGEST_FREQUENCIES:
        raise AdminExportValidationError("frequency must be daily, weekly or monthly")
    if config.report not in DIGEST_REPORTS:
        raise AdminExportValidationError("Unsupported digest report")
    if config.format not in DIGEST_FORMATS:
        raise AdminExportValidationError("Unsupported digest format")
    if not config.recipient_user_ids:
        raise AdminExportValidationError("At least one approved admin recipient is required")
    if len(config.recipient_user_ids) > MAX_DIGEST_RECIPIENTS:
        raise AdminExportValidationError(f"At most {MAX_DIGEST_RECIPIENTS} recipients are allowed")
    approved, rejected = await _approved_admin_ids(db, config.recipient_user_ids)
    if rejected or len(approved) != len(set(config.recipient_user_ids)):
        raise AdminExportValidationError("Digest recipients must be verified administrators")
    spec = normalize_spec(
        report=config.report,
        export_format="csv" if config.format == "csv" else "pdf",
        days=config.days,
        start_date=config.start_date,
        end_date=config.end_date,
        filters=config.filters,
    )
    current = await load_digest_config(db, actor)
    current_payload = current.public_payload()
    candidate_payload = DigestConfig(
        enabled=config.enabled,
        frequency=config.frequency,
        recipient_user_ids=tuple(approved),
        report=config.report,
        format=config.format,
        days=spec.days,
        start_date=config.start_date,
        end_date=config.end_date,
        filters=spec.filters,
    ).public_payload()
    comparable_keys = (
        "enabled",
        "frequency",
        "recipient_user_ids",
        "report",
        "format",
        "days",
        "start_date",
        "end_date",
        "filters",
    )
    if all(current_payload.get(key) == candidate_payload.get(key) for key in comparable_keys):
        current.updated = False
        return current

    after = {
        "enabled": config.enabled,
        "frequency": config.frequency,
        "recipient_user_ids": approved,
        "report": config.report,
        "format": config.format,
        "days": spec.days,
        "start_date": config.start_date.isoformat() if config.start_date else None,
        "end_date": config.end_date.isoformat() if config.end_date else None,
        "filters": spec.filters,
        "schema_version": REPORT_SCHEMA_VERSION,
    }
    await record_admin_audit(
        db,
        actor=actor,
        action=DIGEST_CONFIG_ACTION,
        target_type="admin_digest",
        target_id=actor.user_id,
        reason=reason,
        after=after,
        metadata={
            "enabled": config.enabled,
            "frequency": config.frequency,
            "recipient_count": len(approved),
            "report": config.report,
            "format": config.format,
            "row_cap": spec.row_cap,
            "schema_version": REPORT_SCHEMA_VERSION,
        },
        request=request,
        commit=True,
    )
    saved = _config_from_state(after)
    saved.updated = True
    saved.configured_at = _now()
    return saved


def _digest_period_key(frequency: str, now: datetime) -> str:
    if frequency == "daily":
        return now.strftime("%Y-%m-%d")
    if frequency == "monthly":
        return now.strftime("%Y-%m")
    iso_year, iso_week, _ = now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


async def _last_digest_run_at(db: AsyncSession, actor_user_id: str) -> datetime | None:
    row = (
        await db.execute(
            select(AdminAuditLog.created_at)
            .where(
                AdminAuditLog.target_type == "admin_digest",
                AdminAuditLog.target_id == actor_user_id,
                AdminAuditLog.action.in_([DIGEST_SENT_ACTION, DIGEST_FAILED_ACTION]),
            )
            .order_by(AdminAuditLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _as_utc(row) if row else None


async def due_digest_configs(db: AsyncSession, *, now: datetime | None = None) -> list[tuple[str, DigestConfig, Any]]:
    """Return enabled digest configs whose next scheduled run is due."""
    current = now or _now()
    rows = (
        await db.execute(
            select(
                AdminAuditLog.target_id,
                AdminAuditLog.after_state,
                AdminAuditLog.created_at,
            )
            .where(
                AdminAuditLog.target_type == "admin_digest",
                AdminAuditLog.action == DIGEST_CONFIG_ACTION,
            )
            .order_by(
                AdminAuditLog.target_id,
                AdminAuditLog.created_at.desc(),
                AdminAuditLog.id.desc(),
            )
            .distinct(AdminAuditLog.target_id)
        )
    ).all()
    due: list[tuple[str, DigestConfig, Any]] = []
    for row in rows:
        config = _config_from_state(_digest_row_state(row), configured_at=_as_utc(row.created_at))
        if not config.enabled:
            continue
        interval = DIGEST_FREQUENCIES.get(config.frequency)
        if interval is None:
            continue
        last_run = await _last_digest_run_at(db, str(row.target_id))
        anchor = last_run or _as_utc(row.created_at)
        if current >= anchor + interval:
            due.append((str(row.target_id), config, row))
    return due


async def build_digest_payload(
    db: AsyncSession,
    *,
    actor: AdminActor,
    config: DigestConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the aggregate-only digest payload; never includes emails or content."""
    generated_at = now or _now()
    spec = normalize_spec(
        report=config.report,
        export_format="csv" if config.format == "csv" else "pdf",
        days=config.days,
        start_date=config.start_date,
        end_date=config.end_date,
        filters=config.filters,
    )
    preview = await load_report_rows(db, spec, limit=DIGEST_PREVIEW_ROWS, generated_at=generated_at)
    metadata = report_metadata_payload(preview)
    approved, rejected = await _approved_admin_ids(db, config.recipient_user_ids)
    subject = f"Latexy admin digest: {REPORTS[config.report]['label']}"
    lines = [
        f"Latexy admin digest — {REPORTS[config.report]['label']}",
        f"Range: {spec.start_date.isoformat()} to {spec.end_date.isoformat()} ({spec.days} days)",
        f"Filters: {spec.filter_json()}",
        f"Generated at: {generated_at.isoformat()}",
        f"Schema version: {REPORT_SCHEMA_VERSION}",
        f"Rows: {preview.row_count} (cap {spec.row_cap})",
        f"Suppressed: {'yes' if preview.suppressed else 'no'}",
        "",
        " | ".join(preview.headers),
    ]
    for row in preview.rows[:DIGEST_PREVIEW_ROWS]:
        lines.append(" | ".join(_pdf_text(value) for value in row))
    if preview.truncated or preview.row_count > DIGEST_PREVIEW_ROWS:
        lines.append(f"… {max(0, preview.row_count - DIGEST_PREVIEW_ROWS)} more rows available in the admin export.")
    for note in preview.notes:
        lines.append(f"Note: {note}")
    text_body = "\n".join(lines)
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{_html_escape(value)}</td>" for value in row) + "</tr>" for row in preview.rows
    )
    html_body = (
        '<div style="font-family:system-ui,sans-serif;font-size:13px">'
        f"<h2>Latexy admin digest — {_html_escape(REPORTS[config.report]['label'])}</h2>"
        f"<p>Range: {_html_escape(spec.start_date.isoformat())} to {_html_escape(spec.end_date.isoformat())} "
        f"({spec.days} days)<br>Filters: {_html_escape(spec.filter_json())}<br>"
        f"Generated at: {_html_escape(generated_at.isoformat())} · Schema {REPORT_SCHEMA_VERSION}</p>"
        f'<table border="1" cellpadding="4" cellspacing="0"><thead><tr>'
        + "".join(f"<th>{_html_escape(header)}</th>" for header in preview.headers)
        + f"</tr></thead><tbody>{html_rows}</tbody></table>"
        + "".join(f"<p><small>{_html_escape(note)}</small></p>" for note in preview.notes)
        + "</div>"
    )
    return {
        "subject": subject,
        "html_body": html_body,
        "text_body": text_body,
        "report": spec.report,
        "format": config.format,
        "range": spec.range_payload(),
        "filters": dict(spec.filters),
        "generated_at": generated_at.isoformat(),
        "schema_version": REPORT_SCHEMA_VERSION,
        "row_count": preview.row_count,
        "row_cap": spec.row_cap,
        "suppressed": preview.suppressed,
        "truncated": preview.truncated,
        "recipient_user_ids": approved,
        "rejected_recipient_count": len(rejected),
        "metadata": metadata,
    }


def _html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


async def record_digest_event(
    db: AsyncSession,
    *,
    actor: AdminActor,
    action: str,
    metadata: Mapping[str, Any],
    request: Any = None,
) -> None:
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="admin_digest",
        target_id=actor.user_id,
        metadata=dict(metadata),
        request=request,
        commit=True,
    )


async def send_digest(
    db: AsyncSession,
    *,
    actor: AdminActor,
    config: DigestConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Send one digest to approved admin recipients and record the outcome."""
    current = now or _now()
    payload = await build_digest_payload(db, actor=actor, config=config, now=current)
    owner_approved, _owner_rejected = await _approved_admin_ids(db, [actor.user_id])
    if not owner_approved:
        await record_digest_event(
            db,
            actor=actor,
            action=DIGEST_FAILED_ACTION,
            metadata={
                "status": "failed",
                "error_class": "owner_not_admin",
                "report": payload["report"],
                "format": payload["format"],
                "row_count": payload["row_count"],
                "recipient_count": 0,
                "schema_version": REPORT_SCHEMA_VERSION,
            },
        )
        return {"status": "failed", "error_class": "owner_not_admin", "delivered": 0}
    approved = payload["recipient_user_ids"]
    recipient_rows = (
        (
            await db.execute(
                select(User.id, User.email).where(
                    User.id.in_(approved), User.email_verified.is_(True), User.email.is_not(None)
                )
            )
        ).all()
        if approved
        else []
    )
    recipient_emails = [str(row[1]) for row in recipient_rows if row[1]]
    if not recipient_emails:
        await record_digest_event(
            db,
            actor=actor,
            action=DIGEST_FAILED_ACTION,
            metadata={
                "status": "failed",
                "error_class": "no_approved_recipients",
                "report": payload["report"],
                "format": payload["format"],
                "row_count": payload["row_count"],
                "recipient_count": 0,
                "schema_version": REPORT_SCHEMA_VERSION,
            },
        )
        return {"status": "failed", "error_class": "no_approved_recipients", "delivered": 0}

    period_key = _digest_period_key(config.frequency, current)
    delivered = 0
    failed = 0
    for email in recipient_emails:
        # Per-recipient idempotency prevents one admin's delivery from
        # suppressing another recipient's copy.
        recipient_key = hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]
        try:
            accepted = await email_service.send_email(
                to=email,
                subject=payload["subject"],
                html_body=payload["html_body"],
                text_body=payload["text_body"],
                idempotency_key=f"admin-digest:{actor.user_id}:{period_key}:{recipient_key}",
            )
        except Exception:
            accepted = False
        if accepted:
            delivered += 1
        else:
            failed += 1
    status = "sent" if failed == 0 and delivered > 0 else ("partial" if delivered > 0 else "failed")
    action = DIGEST_SENT_ACTION if delivered > 0 else DIGEST_FAILED_ACTION
    await record_digest_event(
        db,
        actor=actor,
        action=action,
        metadata={
            "status": status,
            "report": payload["report"],
            "format": payload["format"],
            "range": payload["range"],
            "filters": payload["filters"],
            "row_count": payload["row_count"],
            "row_cap": payload["row_cap"],
            "recipient_count": len(recipient_emails),
            "delivered_count": delivered,
            "failed_count": failed,
            "frequency": config.frequency,
            "period_key": period_key,
            "schema_version": REPORT_SCHEMA_VERSION,
        },
    )
    return {
        "status": status,
        "delivered": delivered,
        "failed": failed,
        "recipient_count": len(recipient_emails),
    }


async def dispatch_due_admin_digests(db: AsyncSession, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Scheduler entry point; failure of one digest does not abort the rest."""
    results: list[dict[str, Any]] = []
    for owner_id, config, _row in await due_digest_configs(db, now=now):
        actor = AdminActor(user_id=owner_id, email=None, role="admin")
        try:
            result = await send_digest(db, actor=actor, config=config, now=now)
        except Exception as exc:  # noqa: BLE001 - isolated per-config failure visibility
            try:
                await record_digest_event(
                    db,
                    actor=actor,
                    action=DIGEST_FAILED_ACTION,
                    metadata={
                        "status": "failed",
                        "error_class": type(exc).__name__,
                        "schema_version": REPORT_SCHEMA_VERSION,
                    },
                )
            except Exception:
                pass
            result = {"status": "failed", "error_class": type(exc).__name__, "delivered": 0}
        results.append({"owner_user_id": owner_id, **result})
    return results


__all__ = [
    "AdminExportError",
    "AdminExportForbidden",
    "AdminExportRateLimited",
    "AdminExportSigningUnavailable",
    "AdminExportValidationError",
    "DigestConfig",
    "ExportSpec",
    "PreparedReport",
    "REPORTS",
    "REPORT_SCHEMA_VERSION",
    "MAX_CSV_ROWS",
    "MAX_PDF_ROWS",
    "SYNC_ROW_THRESHOLD",
    "MIN_GROUP_USERS",
    "allow_export_request",
    "build_digest_payload",
    "digest_last_run",
    "dispatch_due_admin_digests",
    "due_digest_configs",
    "export_ttl_minutes",
    "issue_export_token",
    "iter_prepared_rows",
    "iter_report_csv",
    "list_admin_recipients",
    "list_export_history",
    "load_digest_config",
    "load_report_rows",
    "normalize_spec",
    "prepare_report",
    "record_digest_event",
    "record_export_event",
    "render_report_pdf",
    "report_metadata_payload",
    "safe_csv_cell",
    "save_digest_config",
    "send_digest",
    "validate_export_token",
]

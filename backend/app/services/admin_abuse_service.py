"""Human-reviewed abuse-signal queue.

Existing persisted abuse primitives (device trials, hashed-IP clusters, payment
failures, referral reversals/rejections, coupon release churn and usage
velocity) are materialised by an explicit admin scan into one review item per
``signal_type + opaque subject + ISO week``. The queue is advisory: scanning
never blocks, resets, refunds, downgrades or otherwise punishes anyone.

Privacy boundary
----------------
* ``subject_key`` is computed inside PostgreSQL with ``md5(...)`` for device,
  IP and account signals. Raw fingerprints, IPs, user ids and emails never
  enter this process, an audit row or an HTTP response.
* Evidence contains only bounded numeric aggregates, booleans and allowlisted
  labels. Referral reasons are normalised through a fixed allowlist so a
  legacy free-form value cannot echo a token or address.
* Enforcement is restricted to ``device`` subjects. IP clusters, account
  signals and reason groups can only be acknowledged or dismissed.

Enforcement boundary
--------------------
Acknowledge and dismiss require a reason and ``confirm=true`` by one admin.
Block, unblock and whitelist additionally require an approved
``abuse_review_action`` from the shared two-person approval service. The
approval is bound to the queue item, subject hash and action, so it cannot be
replayed for a different subject or reused after the item advanced.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import String, case, cast, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import models
from . import admin_approval_service
from .admin_approval_service import ApprovalError, ApprovalReplay, approval_summary
from .admin_audit_service import AdminActor, record_admin_audit
from .trial_service import TRIAL_LIMIT

MIN_COHORT_SIZE = 5
WINDOWS = (7, 30, 90)
DEFAULT_WINDOW_DAYS = 30
MAX_ITEMS_PER_SIGNAL = 200
MAX_REFERRAL_ROWS = 20_000
MAX_REASON = 1000
MAX_NOTE = 1000

SIGNAL_TYPES: tuple[str, ...] = (
    "blocked_device",
    "trial_limit_reached",
    "repeat_ip_cluster",
    "trial_velocity",
    "payment_failure",
    "referral_rejection",
    "coupon_reuse",
    "rate_limit_pressure",
)
SUBJECT_TYPES: tuple[str, ...] = ("device", "ip", "account", "reason", "coupon")
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")
STATUSES: tuple[str, ...] = ("open", "approved", "dismissed", "actioned")
DECISIONS: tuple[str, ...] = ("approve", "dismiss", "action")
ENFORCEMENT_ACTIONS: tuple[str, ...] = ("block", "unblock", "whitelist")

REPEAT_IP_DEVICE_THRESHOLD = 5
TRIAL_VELOCITY_DEVICE_THRESHOLD = 5
TRIAL_VELOCITY_HOURS = 24
PAYMENT_FAILURE_THRESHOLD = 3
REFERRAL_REASON_THRESHOLD = 5
COUPON_RELEASE_THRESHOLD = 3
RATE_LIMIT_EVENT_THRESHOLD = 50
RATE_LIMIT_HOURS = 24

SIGNAL_DEFINITIONS: dict[str, tuple[str, str]] = {
    "blocked_device": ("Blocked device", "device"),
    "trial_limit_reached": ("Trial limit reached", "device"),
    "repeat_ip_cluster": ("Repeat hashed-IP cluster", "ip"),
    "trial_velocity": ("Trial velocity cluster", "ip"),
    "payment_failure": ("Repeated payment failures", "account"),
    "referral_rejection": ("Referral rejection reason", "reason"),
    "coupon_reuse": ("Repeated coupon release churn", "account"),
    "rate_limit_pressure": ("Usage velocity pressure", "ip"),
}

_EVIDENCE_LINKS: dict[str, list[dict[str, str]]] = {
    "blocked_device": [
        {
            "kind": "trial_health",
            "label": "Trial health & abuse signals",
            "href": "/admin?tab=growth",
        }
    ],
    "trial_limit_reached": [
        {
            "kind": "trial_health",
            "label": "Trial health & abuse signals",
            "href": "/admin?tab=growth",
        }
    ],
    "repeat_ip_cluster": [
        {
            "kind": "trial_health",
            "label": "Trial health & abuse signals",
            "href": "/admin?tab=growth",
        }
    ],
    "trial_velocity": [
        {
            "kind": "trial_health",
            "label": "Trial health & abuse signals",
            "href": "/admin?tab=growth",
        }
    ],
    "payment_failure": [
        {"kind": "billing", "label": "Revenue & payments", "href": "/admin?tab=billing"}
    ],
    "referral_rejection": [
        {
            "kind": "referrals",
            "label": "Referral analytics",
            "href": "/admin?tab=growth",
        }
    ],
    "coupon_reuse": [
        {
            "kind": "coupons",
            "label": "Coupon performance",
            "href": "/admin?tab=billing",
        }
    ],
    "rate_limit_pressure": [
        {
            "kind": "operations",
            "label": "Operations health",
            "href": "/admin?tab=operations",
        }
    ],
}

_REFERRAL_REASON_LABELS: dict[str, str] = {
    "already_referred": "Account already attributed",
    "ineligible_referrer": "Referrer ineligible",
    "invalid_code": "Invalid or unknown referral code",
    "outside_attribution_window": "Outside the attribution window",
    "payment_before_attribution": "Payment predates attribution",
    "payment_refunded": "Payment refunded",
    "plan_not_qualifying": "Plan not eligible",
    "prior_payment_before_attribution": "Prior payment predates attribution",
    "referrer_limit_reached": "Referrer attribution limit reached",
    "self_referral": "Self-referral rejected",
    "subscription_missing": "Paid subscription missing",
    "reward_unavailable": "Reward unavailable for the referrer plan",
    "reversed": "Qualified referral reversed",
    "other": "Other recorded reason",
}
_REFERRAL_REASON_ALIASES: dict[str, str] = {
    "account_too_old": "outside_attribution_window",
    "already_claimed": "already_referred",
    "attribution_window_expired": "outside_attribution_window",
    "duplicate": "already_referred",
    "ineligible": "ineligible_referrer",
    "limit_reached": "referrer_limit_reached",
    "no_subscription": "subscription_missing",
    "outside_window": "outside_attribution_window",
    "payment_reversed": "payment_refunded",
    "plan_not_eligible": "plan_not_qualifying",
    "refunded": "payment_refunded",
    "referral_limit": "referrer_limit_reached",
    "reward_not_available": "reward_unavailable",
    "self_referral_rejected": "self_referral",
}


class AbuseReviewError(Exception):
    status_code = 409
    code = "abuse_review_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class AbuseReviewNotFound(AbuseReviewError):
    status_code = 404
    code = "abuse_review_not_found"


class AbuseReviewValidationError(AbuseReviewError):
    status_code = 422
    code = "abuse_review_invalid"


class AbuseReviewConflict(AbuseReviewError):
    status_code = 409
    code = "abuse_review_conflict"


class AbuseReviewForbidden(AbuseReviewError):
    status_code = 409
    code = "abuse_review_forbidden"


@dataclass(frozen=True)
class SignalCandidate:
    signal_type: str
    subject_type: str
    subject_key: str
    severity: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    evidence: dict[str, Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clean_reason(value: str | None) -> str:
    cleaned = " ".join((value or "").split())[:MAX_REASON]
    if len(cleaned) < 3:
        raise AbuseReviewValidationError(
            "A reason of at least 3 characters is required"
        )
    return cleaned


def _clean_note(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())[:MAX_NOTE]
    return cleaned or None


def _require_confirm(value: bool) -> None:
    if value is not True:
        raise AbuseReviewValidationError("confirm=true is required for this action")


def _window_days(value: int | None) -> int:
    if value is None:
        return DEFAULT_WINDOW_DAYS
    if value not in WINDOWS:
        raise AbuseReviewValidationError(
            f"window_days must be one of {', '.join(str(item) for item in WINDOWS)}"
        )
    return int(value)


def _week_bucket(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _dedupe_key(signal_type: str, subject_key: str, bucket: str) -> str:
    return f"{signal_type}:{subject_key}:{bucket}"


def _hash_text(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _safe_referral_reason(value: str | None) -> tuple[str, str]:
    key = (value or "").strip().lower()
    key = _REFERRAL_REASON_ALIASES.get(key, key)
    if key not in _REFERRAL_REASON_LABELS or key == "other":
        return "other", _REFERRAL_REASON_LABELS["other"]
    return key, _REFERRAL_REASON_LABELS[key]


def _severity_for_count(count: int, *, medium: int, high: int) -> str:
    if count >= high:
        return "high"
    if count >= medium:
        return "medium"
    return "low"


def _publishable_count(value: int) -> int | None:
    """Queue-item counts are operational, but tiny value groups stay hidden."""
    if value == 0 or value >= MIN_COHORT_SIZE:
        return value
    return None


def signal_summary(row: models.AbuseReviewItem) -> dict[str, Any]:
    subject_key = str(row.subject_key or "")
    is_open = row.status in {"open", "approved"}
    return {
        "id": row.id,
        "signal_type": row.signal_type,
        "signal_label": SIGNAL_DEFINITIONS.get(row.signal_type, ("Unknown", ""))[0],
        "subject_type": row.subject_type,
        "subject_key": subject_key,
        "subject_ref": subject_key[:12] if subject_key else "",
        "severity": row.severity,
        "status": row.status,
        "occurrence_count": int(row.occurrence_count or 0),
        "window_days": int(row.window_days or 0),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "evidence": row.evidence if isinstance(row.evidence, Mapping) else {},
        "evidence_links": list(row.evidence_links or []),
        "assigned_to": row.assigned_to,
        "assigned_by": row.assigned_by,
        "assigned_at": row.assigned_at.isoformat() if row.assigned_at else None,
        "decision": row.decision,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_reason": row.decision_reason,
        "enforcement_action": row.enforcement_action,
        "approval_id": row.approval_id,
        "execution_count": int(row.execution_count or 0),
        "last_executed_at": (
            row.last_executed_at.isoformat() if row.last_executed_at else None
        ),
        "can_acknowledge": row.status == "open",
        "can_dismiss": row.status in {"open", "approved"},
        "can_enforce": row.subject_type == "device"
        and is_open
        and row.signal_type in {"blocked_device", "trial_limit_reached"},
        "enforcement_actions": (
            list(ENFORCEMENT_ACTIONS)
            if row.subject_type == "device"
            and row.signal_type in {"blocked_device", "trial_limit_reached"}
            else []
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _summary_payload(
    db: AsyncSession,
    *,
    total: int,
    items: list[dict[str, Any]],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(models.AbuseReviewItem.status, func.count()).group_by(
                models.AbuseReviewItem.status
            )
        )
    ).all()
    severity_rows = (
        await db.execute(
            select(models.AbuseReviewItem.severity, func.count())
            .where(models.AbuseReviewItem.status.in_(("open", "approved")))
            .group_by(models.AbuseReviewItem.severity)
        )
    ).all()
    counts = {status: 0 for status in STATUSES}
    counts.update({str(status): int(count) for status, count in status_rows})
    severity_counts = {severity: 0 for severity in SEVERITIES}
    severity_counts.update(
        {str(severity): int(count) for severity, count in severity_rows}
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "counts": counts,
        "by_severity": severity_counts,
        "open_total": counts.get("open", 0) + counts.get("approved", 0),
        "aggregation_unit": "review_item",
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "enforcement": {
            "automatic": False,
            "sensitive_actions": list(ENFORCEMENT_ACTIONS),
            "two_person_required": True,
            "device_only": True,
        },
        "notes": [
            "Subject keys are MD5 hashes computed inside PostgreSQL. Raw device "
            "fingerprints, IP addresses, account ids and emails are never returned.",
            "Scanning is an explicit, audited admin action. It never blocks, "
            "resets, refunds or downgrades an account.",
            "Block, unblock and whitelist require a second admin through the "
            "two-person approval queue and apply only to device-scoped signals. "
            "Unblock clears the block flag; whitelist also exempts the device from "
            "automatic trial blocking and the usage ceiling.",
            "Shared office, campus and carrier NAT addresses can create false "
            "positives; review the evidence before enforcing.",
            "The five-subject floor gates multi-account clusters and reason groups. "
            "Single-subject device/account items are operational review records, "
            "visible only to admins and never joined to a user history.",
        ],
    }


async def list_queue(
    db: AsyncSession,
    *,
    status: str | None = "open",
    severity: str | None = None,
    signal_type: str | None = None,
    assigned_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    if status is not None and status not in STATUSES:
        raise AbuseReviewValidationError("Unknown abuse-review status")
    if severity is not None and severity not in SEVERITIES:
        raise AbuseReviewValidationError("Unknown abuse-review severity")
    if signal_type is not None and signal_type not in SIGNAL_TYPES:
        raise AbuseReviewValidationError("Unknown abuse-review signal type")
    if assigned_to is not None and assigned_to not in {"unassigned", "me"}:
        try:
            assigned_to = str(uuid.UUID(str(assigned_to)))
        except (ValueError, TypeError, AttributeError):
            raise AbuseReviewValidationError(
                "assigned_to must be a UUID, 'me' or 'unassigned'"
            ) from None
    if limit < 1 or limit > 200:
        raise AbuseReviewValidationError("limit must be between 1 and 200")
    if offset < 0:
        raise AbuseReviewValidationError("offset cannot be negative")

    stmt = select(models.AbuseReviewItem)
    count_stmt = select(func.count()).select_from(models.AbuseReviewItem)
    if status:
        stmt = stmt.where(models.AbuseReviewItem.status == status)
        count_stmt = count_stmt.where(models.AbuseReviewItem.status == status)
    if severity:
        stmt = stmt.where(models.AbuseReviewItem.severity == severity)
        count_stmt = count_stmt.where(models.AbuseReviewItem.severity == severity)
    if signal_type:
        stmt = stmt.where(models.AbuseReviewItem.signal_type == signal_type)
        count_stmt = count_stmt.where(models.AbuseReviewItem.signal_type == signal_type)
    if assigned_to == "unassigned":
        stmt = stmt.where(models.AbuseReviewItem.assigned_to.is_(None))
        count_stmt = count_stmt.where(models.AbuseReviewItem.assigned_to.is_(None))
    elif assigned_to and assigned_to != "me":
        stmt = stmt.where(models.AbuseReviewItem.assigned_to == assigned_to)
        count_stmt = count_stmt.where(models.AbuseReviewItem.assigned_to == assigned_to)

    severity_rank = case(
        (models.AbuseReviewItem.severity == "critical", 0),
        (models.AbuseReviewItem.severity == "high", 1),
        (models.AbuseReviewItem.severity == "medium", 2),
        (models.AbuseReviewItem.severity == "low", 3),
        else_=4,
    )
    rows = (
        await db.execute(
            stmt.order_by(
                severity_rank,
                models.AbuseReviewItem.last_seen_at.desc(),
                models.AbuseReviewItem.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    total = int((await db.execute(count_stmt)).scalar_one())
    return await _summary_payload(
        db,
        total=total,
        items=[signal_summary(row) for row in rows],
        limit=limit,
        offset=offset,
    )


async def get_item(db: AsyncSession, item_id: str) -> models.AbuseReviewItem | None:
    try:
        canonical = str(uuid.UUID(str(item_id)))
    except (ValueError, TypeError, AttributeError):
        return None
    return await db.scalar(
        select(models.AbuseReviewItem).where(models.AbuseReviewItem.id == canonical)
    )


async def _require_item(
    db: AsyncSession, item_id: str, *, for_update: bool = False
) -> models.AbuseReviewItem:
    try:
        canonical = str(uuid.UUID(str(item_id)))
    except (ValueError, TypeError, AttributeError):
        raise AbuseReviewNotFound("Abuse-review item not found") from None
    stmt = select(models.AbuseReviewItem).where(
        models.AbuseReviewItem.id == canonical
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise AbuseReviewNotFound("Abuse-review item not found")
    return row


# ── Signal collection ────────────────────────────────────────────────────────


def _device_subject_expr():
    return func.md5(cast(models.DeviceTrial.device_fingerprint, String))


def _ip_subject_expr(column):
    return func.md5(func.host(column))


def _as_utc(value: datetime | None) -> datetime:
    aware = _as_aware(value)
    return aware if aware is not None else _now()


def _candidate(
    *,
    signal_type: str,
    subject_key: str,
    severity: str,
    occurrences: int,
    first_seen: datetime,
    last_seen: datetime,
    evidence: Mapping[str, Any],
) -> SignalCandidate:
    subject_type = SIGNAL_DEFINITIONS[signal_type][1]
    return SignalCandidate(
        signal_type=signal_type,
        subject_type=subject_type,
        subject_key=str(subject_key)[:64],
        severity=severity,
        occurrence_count=max(1, int(occurrences)),
        first_seen_at=_as_utc(first_seen),
        last_seen_at=_as_utc(last_seen),
        evidence=dict(evidence),
    )


async def _collect_blocked_devices(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    subject = _device_subject_expr()
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                models.DeviceTrial.usage_count.label("usage_count"),
                models.DeviceTrial.whitelisted.label("whitelisted"),
                models.DeviceTrial.created_at.label("created_at"),
                func.coalesce(
                    models.DeviceTrial.last_used, models.DeviceTrial.created_at
                ).label("seen_at"),
            )
            .where(
                models.DeviceTrial.blocked.is_(True),
                func.coalesce(
                    models.DeviceTrial.last_used, models.DeviceTrial.created_at
                )
                >= cutoff,
            )
            .order_by(models.DeviceTrial.last_used.desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="blocked_device",
            subject_key=row.subject_key,
            severity="high",
            occurrences=1,
            first_seen=row.created_at,
            last_seen=row.seen_at,
            evidence={
                "blocked": True,
                "usage_count": int(row.usage_count or 0),
                "whitelisted": bool(row.whitelisted),
                "trial_limit": TRIAL_LIMIT,
            },
        )
        for row in rows
    ]


async def _collect_trial_limit_devices(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    subject = _device_subject_expr()
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                models.DeviceTrial.usage_count.label("usage_count"),
                models.DeviceTrial.created_at.label("created_at"),
                func.coalesce(
                    models.DeviceTrial.last_used, models.DeviceTrial.created_at
                ).label("seen_at"),
            )
            .where(
                models.DeviceTrial.blocked.is_(False),
                models.DeviceTrial.whitelisted.is_(False),
                models.DeviceTrial.usage_count >= TRIAL_LIMIT,
                models.DeviceTrial.created_at >= cutoff,
            )
            .order_by(models.DeviceTrial.last_used.desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="trial_limit_reached",
            subject_key=row.subject_key,
            severity="medium",
            occurrences=1,
            first_seen=row.created_at,
            last_seen=row.seen_at,
            evidence={
                "usage_count": int(row.usage_count or 0),
                "trial_limit": TRIAL_LIMIT,
                "blocked": False,
            },
        )
        for row in rows
    ]


async def _collect_repeat_ip_clusters(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    subject = _ip_subject_expr(models.DeviceTrial.ip_address)
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                func.count(func.distinct(models.DeviceTrial.device_fingerprint)).label(
                    "devices"
                ),
                func.count().label("trials"),
                func.sum(
                    case((models.DeviceTrial.blocked.is_(True), 1), else_=0)
                ).label("blocked"),
                func.sum(models.DeviceTrial.usage_count).label("usage"),
                func.min(models.DeviceTrial.created_at).label("first_seen"),
                func.max(
                    func.coalesce(
                        models.DeviceTrial.last_used, models.DeviceTrial.created_at
                    )
                ).label("last_seen"),
            )
            .where(
                models.DeviceTrial.ip_address.is_not(None),
                models.DeviceTrial.created_at >= cutoff,
            )
            .group_by(subject)
            .having(
                func.count(func.distinct(models.DeviceTrial.device_fingerprint))
                >= REPEAT_IP_DEVICE_THRESHOLD
            )
            .order_by(func.count().desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="repeat_ip_cluster",
            subject_key=row.subject_key,
            severity="high" if int(row.devices) >= 10 else "medium",
            occurrences=int(row.trials),
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            evidence={
                "devices": int(row.devices),
                "trials": int(row.trials),
                "blocked_devices": int(row.blocked or 0),
                "usage_total": int(row.usage or 0),
                "cluster_threshold": REPEAT_IP_DEVICE_THRESHOLD,
                "shared_network_possible": True,
            },
        )
        for row in rows
    ]


async def _collect_trial_velocity(
    db: AsyncSession, *, now: datetime
) -> list[SignalCandidate]:
    start = now - timedelta(hours=TRIAL_VELOCITY_HOURS)
    subject = _ip_subject_expr(models.DeviceTrial.ip_address)
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                func.count(func.distinct(models.DeviceTrial.device_fingerprint)).label(
                    "devices"
                ),
                func.count().label("trials"),
                func.sum(
                    case(
                        (models.DeviceTrial.usage_count >= TRIAL_LIMIT, 1),
                        else_=0,
                    )
                ).label("exhausted"),
                func.min(models.DeviceTrial.created_at).label("first_seen"),
                func.max(
                    func.coalesce(
                        models.DeviceTrial.last_used, models.DeviceTrial.created_at
                    )
                ).label("last_seen"),
            )
            .where(
                models.DeviceTrial.ip_address.is_not(None),
                models.DeviceTrial.created_at >= start,
            )
            .group_by(subject)
            .having(
                func.count(func.distinct(models.DeviceTrial.device_fingerprint))
                >= TRIAL_VELOCITY_DEVICE_THRESHOLD
            )
            .order_by(func.count().desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="trial_velocity",
            subject_key=row.subject_key,
            severity="high" if int(row.devices) >= 10 else "medium",
            occurrences=int(row.trials),
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            evidence={
                "devices": int(row.devices),
                "trials": int(row.trials),
                "exhausted_devices": int(row.exhausted or 0),
                "window_hours": TRIAL_VELOCITY_HOURS,
                "cluster_threshold": TRIAL_VELOCITY_DEVICE_THRESHOLD,
                "shared_network_possible": True,
            },
        )
        for row in rows
    ]


async def _collect_payment_failures(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    subject = func.md5(cast(models.Payment.user_id, String))
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                func.count().label("failures"),
                func.min(models.Payment.created_at).label("first_seen"),
                func.max(models.Payment.created_at).label("last_seen"),
            )
            .where(
                models.Payment.status == "failed",
                models.Payment.created_at >= cutoff,
            )
            .group_by(subject)
            .having(func.count() >= PAYMENT_FAILURE_THRESHOLD)
            .order_by(func.count().desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="payment_failure",
            subject_key=row.subject_key,
            severity="high" if int(row.failures) >= 5 else "medium",
            occurrences=int(row.failures),
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            evidence={
                "failed_payments": int(row.failures),
                "threshold": PAYMENT_FAILURE_THRESHOLD,
                "provider_payload_excluded": True,
            },
        )
        for row in rows
    ]


async def _collect_referral_rejections(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    rows = (
        await db.execute(
            select(
                models.ReferralAttribution.rejection_reason.label("reason"),
                models.ReferralAttribution.status.label("status"),
                models.ReferralAttribution.captured_at.label("captured_at"),
                models.ReferralAttribution.reversed_at.label("reversed_at"),
            )
            .where(
                or_(
                    models.ReferralAttribution.rejection_reason.is_not(None),
                    models.ReferralAttribution.status == "reversed",
                ),
                models.ReferralAttribution.captured_at >= cutoff,
            )
            .order_by(models.ReferralAttribution.captured_at.desc())
            .limit(MAX_REFERRAL_ROWS)
        )
    ).all()
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "reversed": 0, "first_seen": None, "last_seen": None}
    )
    for row in rows:
        raw_reason = row.reason
        if raw_reason is None and row.status == "reversed":
            raw_reason = "reversed"
        reason_key, _label = _safe_referral_reason(raw_reason)
        entry = grouped[reason_key]
        entry["count"] += 1
        if row.status == "reversed":
            entry["reversed"] += 1
        captured = _as_aware(row.captured_at)
        reversed_at = _as_aware(row.reversed_at)
        candidates = [value for value in (captured, reversed_at) if value is not None]
        for value in candidates:
            if entry["first_seen"] is None or value < entry["first_seen"]:
                entry["first_seen"] = value
            if entry["last_seen"] is None or value > entry["last_seen"]:
                entry["last_seen"] = value

    result: list[SignalCandidate] = []
    for reason_key, entry in grouped.items():
        if int(entry["count"]) < REFERRAL_REASON_THRESHOLD:
            continue
        label = _REFERRAL_REASON_LABELS[reason_key]
        first_seen = entry["first_seen"] or cutoff
        last_seen = entry["last_seen"] or first_seen
        result.append(
            _candidate(
                signal_type="referral_rejection",
                subject_key=_hash_text(f"referral_reason:{reason_key}"),
                severity=_severity_for_count(
                    int(entry["count"]), medium=REFERRAL_REASON_THRESHOLD, high=20
                ),
                occurrences=int(entry["count"]),
                first_seen=first_seen,
                last_seen=last_seen,
                evidence={
                    "reason": reason_key,
                    "reason_label": label,
                    "rejections": int(entry["count"]),
                    "reversed": int(entry["reversed"]),
                    "cohort_threshold": REFERRAL_REASON_THRESHOLD,
                },
            )
        )
    result.sort(key=lambda item: (-item.occurrence_count, item.subject_key))
    return result[:MAX_ITEMS_PER_SIGNAL]


async def _collect_coupon_reuse(
    db: AsyncSession, *, cutoff: datetime
) -> list[SignalCandidate]:
    subject = func.md5(cast(models.CouponRedemption.user_id, String))
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                func.count().label("releases"),
                func.count(func.distinct(models.CouponRedemption.coupon_id)).label(
                    "coupons"
                ),
                func.min(models.CouponRedemption.redeemed_at).label("first_seen"),
                func.max(models.CouponRedemption.redeemed_at).label("last_seen"),
            )
            .where(
                models.CouponRedemption.user_id.is_not(None),
                models.CouponRedemption.status == "released",
                models.CouponRedemption.redeemed_at >= cutoff,
            )
            .group_by(subject)
            .having(func.count() >= COUPON_RELEASE_THRESHOLD)
            .order_by(func.count().desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="coupon_reuse",
            subject_key=row.subject_key,
            severity="high" if int(row.releases) >= 8 else "medium",
            occurrences=int(row.releases),
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            evidence={
                "released_reservations": int(row.releases),
                "distinct_coupons": int(row.coupons or 0),
                "threshold": COUPON_RELEASE_THRESHOLD,
            },
        )
        for row in rows
    ]


async def _collect_rate_limit_pressure(
    db: AsyncSession, *, now: datetime
) -> list[SignalCandidate]:
    start = now - timedelta(hours=RATE_LIMIT_HOURS)
    subject = _ip_subject_expr(models.UsageAnalytics.ip_address)
    rows = (
        await db.execute(
            select(
                subject.label("subject_key"),
                func.count().label("events"),
                func.count(
                    func.distinct(models.UsageAnalytics.device_fingerprint)
                ).label("devices"),
                func.min(models.UsageAnalytics.created_at).label("first_seen"),
                func.max(models.UsageAnalytics.created_at).label("last_seen"),
            )
            .where(
                models.UsageAnalytics.ip_address.is_not(None),
                models.UsageAnalytics.created_at >= start,
            )
            .group_by(subject)
            .having(func.count() >= RATE_LIMIT_EVENT_THRESHOLD)
            .order_by(func.count().desc())
            .limit(MAX_ITEMS_PER_SIGNAL)
        )
    ).all()
    return [
        _candidate(
            signal_type="rate_limit_pressure",
            subject_key=row.subject_key,
            severity="medium" if int(row.events) >= RATE_LIMIT_EVENT_THRESHOLD * 4 else "low",
            occurrences=int(row.events),
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            evidence={
                "usage_events": int(row.events),
                "distinct_devices": int(row.devices or 0),
                "window_hours": RATE_LIMIT_HOURS,
                "threshold": RATE_LIMIT_EVENT_THRESHOLD,
                "shared_network_possible": True,
            },
        )
        for row in rows
    ]


async def collect_signals(
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> tuple[list[SignalCandidate], dict[str, bool]]:
    days = _window_days(window_days)
    generated_at = now or _now()
    cutoff = generated_at - timedelta(days=days)
    collected: list[SignalCandidate] = []
    truncated: dict[str, bool] = {}
    collectors: tuple[tuple[str, Any], ...] = (
        ("blocked_device", lambda: _collect_blocked_devices(db, cutoff=cutoff)),
        (
            "trial_limit_reached",
            lambda: _collect_trial_limit_devices(db, cutoff=cutoff),
        ),
        (
            "repeat_ip_cluster",
            lambda: _collect_repeat_ip_clusters(db, cutoff=cutoff),
        ),
        ("trial_velocity", lambda: _collect_trial_velocity(db, now=generated_at)),
        (
            "payment_failure",
            lambda: _collect_payment_failures(db, cutoff=cutoff),
        ),
        (
            "referral_rejection",
            lambda: _collect_referral_rejections(db, cutoff=cutoff),
        ),
        ("coupon_reuse", lambda: _collect_coupon_reuse(db, cutoff=cutoff)),
        (
            "rate_limit_pressure",
            lambda: _collect_rate_limit_pressure(db, now=generated_at),
        ),
    )
    for signal_type, collector in collectors:
        candidates = await collector()
        truncated[signal_type] = len(candidates) >= MAX_ITEMS_PER_SIGNAL
        collected.extend(candidates)
    return collected, truncated


async def scan_signals(
    db: AsyncSession,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    reason: str | None,
    confirm: bool,
    actor: AdminActor,
    request=None,
) -> dict[str, Any]:
    _require_confirm(confirm)
    cleaned_reason = _clean_reason(reason)
    days = _window_days(window_days)
    generated_at = _now()
    bucket = _week_bucket(generated_at)
    candidates, truncated = await collect_signals(
        db, window_days=days, now=generated_at
    )

    created = 0
    updated = 0
    for candidate in candidates:
        dedupe = _dedupe_key(candidate.signal_type, candidate.subject_key, bucket)
        stmt = pg_insert(models.AbuseReviewItem).values(
            id=str(uuid.uuid4()),
            signal_type=candidate.signal_type,
            subject_type=candidate.subject_type,
            subject_key=candidate.subject_key,
            severity=candidate.severity,
            status="open",
            dedupe_key=dedupe,
            occurrence_count=candidate.occurrence_count,
            window_days=days,
            first_seen_at=candidate.first_seen_at,
            last_seen_at=candidate.last_seen_at,
            evidence=candidate.evidence,
            evidence_links=_EVIDENCE_LINKS.get(candidate.signal_type, []),
            created_at=generated_at,
            updated_at=generated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[models.AbuseReviewItem.dedupe_key],
            set_={
                "occurrence_count": func.greatest(
                    models.AbuseReviewItem.occurrence_count,
                    stmt.excluded.occurrence_count,
                ),
                "last_seen_at": func.greatest(
                    models.AbuseReviewItem.last_seen_at, stmt.excluded.last_seen_at
                ),
                "severity": stmt.excluded.severity,
                "evidence": stmt.excluded.evidence,
                "evidence_links": stmt.excluded.evidence_links,
                "window_days": func.greatest(
                    models.AbuseReviewItem.window_days, stmt.excluded.window_days
                ),
                "updated_at": generated_at,
            },
        ).returning(
            models.AbuseReviewItem.id,
            literal_column("(xmax = 0)").label("inserted"),
        )
        row = (await db.execute(stmt)).one()
        if bool(row.inserted):
            created += 1
        else:
            updated += 1

    audit = await record_admin_audit(
        db,
        actor=actor,
        action="admin.abuse.scan",
        target_type="abuse_review_queue",
        target_id="scan",
        reason=cleaned_reason,
        after={
            "created": created,
            "updated": updated,
            "candidates": len(candidates),
            "window_days": days,
            "bucket": bucket,
        },
        metadata={
            "window_days": days,
            "bucket": bucket,
            "created": created,
            "updated": updated,
            "truncated": truncated,
        },
        request=request,
    )
    await db.commit()
    summary = await list_queue(db, status=None, limit=1, offset=0)
    return {
        "created": created,
        "updated": updated,
        "candidates": len(candidates),
        "window_days": days,
        "bucket": bucket,
        "generated_at": generated_at.isoformat(),
        "truncated": truncated,
        "audit_id": audit.id,
        "summary": {
            "total": summary["total"],
            "counts": summary["counts"],
            "by_severity": summary["by_severity"],
        },
    }


# ── Assignment and decisions ────────────────────────────────────────────────


async def assign_item(
    db: AsyncSession,
    *,
    item_id: str,
    assignee_id: str | None,
    reason: str | None,
    confirm: bool,
    actor: AdminActor,
    request=None,
) -> dict[str, Any]:
    _require_confirm(confirm)
    cleaned_reason = _clean_reason(reason)
    item = await _require_item(db, item_id, for_update=True)
    if item.status not in {"open", "approved"}:
        raise AbuseReviewConflict("Only an open or acknowledged item can be assigned")

    canonical_assignee: str | None = None
    if assignee_id is not None:
        try:
            canonical_assignee = str(uuid.UUID(str(assignee_id)))
        except (ValueError, TypeError, AttributeError):
            raise AbuseReviewValidationError("assignee_id must be a UUID") from None
        assignee = await db.scalar(
            select(models.User).where(models.User.id == canonical_assignee)
        )
        if assignee is None or assignee.role != "admin":
            raise AbuseReviewValidationError("assignee_id must identify an admin")

    before = {"assigned_to": item.assigned_to}
    item.assigned_to = canonical_assignee
    item.assigned_by = actor.user_id if canonical_assignee else None
    item.assigned_at = _now() if canonical_assignee else None
    item.updated_at = _now()
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.abuse.assign",
        target_type="abuse_review_item",
        target_id=item.id,
        reason=cleaned_reason,
        before=before,
        after={"assigned_to": item.assigned_to},
        metadata={
            "signal_type": item.signal_type,
            "subject_type": item.subject_type,
            "subject_ref": item.subject_key[:12],
        },
        request=request,
    )
    await db.commit()
    await db.refresh(item)
    return signal_summary(item)


async def _record_decision_audit(
    db: AsyncSession,
    *,
    item: models.AbuseReviewItem,
    action: str,
    reason: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    actor: AdminActor,
    request=None,
    approval_id: str | None = None,
) -> None:
    await record_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="abuse_review_item",
        target_id=item.id,
        reason=reason,
        before=dict(before),
        after=dict(after),
        metadata={
            "signal_type": item.signal_type,
            "subject_type": item.subject_type,
            "subject_ref": item.subject_key[:12],
            "approval_id": approval_id,
        },
        request=request,
    )


async def _apply_device_enforcement(
    db: AsyncSession, *, subject_key: str, action: str
) -> int:
    if action == "block":
        values = {"blocked": True, "whitelisted": False}
    elif action == "unblock":
        values = {"blocked": False, "whitelisted": False}
    elif action == "whitelist":
        values = {"blocked": False, "whitelisted": True}
    else:
        raise AbuseReviewValidationError("Unknown enforcement action")
    result = await db.execute(
        update(models.DeviceTrial)
        .where(_device_subject_expr() == subject_key)
        .values(**values)
    )
    return int(result.rowcount or 0)


def abuse_action_payload(item: models.AbuseReviewItem, action: str) -> dict[str, str]:
    if item.subject_type != "device":
        raise AbuseReviewValidationError(
            "Only device-scoped signals can use block, unblock or whitelist"
        )
    if action not in ENFORCEMENT_ACTIONS:
        raise AbuseReviewValidationError("Unknown enforcement action")
    return {
        "queue_item_id": item.id,
        "subject_key": item.subject_key,
        "action": action,
    }


async def _execute_approved_action(
    db: AsyncSession,
    *,
    approval,
    actor: AdminActor,
    note: str | None = None,
    request=None,
) -> dict[str, Any]:
    payload = admin_approval_service.normalize_payload(
        "abuse_review_action", approval.payload
    )
    item = await _require_item(
        db, str(payload["queue_item_id"]), for_update=True
    )
    if item.subject_type != "device" or item.signal_type not in {
        "blocked_device",
        "trial_limit_reached",
    }:
        raise AbuseReviewConflict(
            "Only device trial signals can use an enforcement action"
        )
    if item.subject_key != payload["subject_key"]:
        raise AbuseReviewConflict("The queue item subject changed after approval")
    if item.status == "actioned":
        if item.approval_id == approval.id:
            return signal_summary(item)
        raise AbuseReviewConflict("This queue item was already actioned")
    if item.status not in {"open", "approved"}:
        raise AbuseReviewConflict(
            f"A {item.status} queue item cannot be enforced"
        )

    await admin_approval_service.require_approved(
        db,
        approval_id=approval.id,
        request_type="abuse_review_action",
        payload=payload,
        actor=actor,
        resource_type="abuse_review_item",
        resource_id=item.id,
        request=request,
    )
    await admin_approval_service.begin_execution(
        db, approval, actor=actor, note=note, request=request
    )
    matched = await _apply_device_enforcement(
        db, subject_key=item.subject_key, action=payload["action"]
    )
    if matched == 0:
        await admin_approval_service.fail_execution(
            db,
            approval,
            actor=actor,
            error_code="abuse_subject_not_found",
            note="The device row no longer exists",
            request=request,
        )
        await db.commit()
        raise AbuseReviewConflict(
            "The device row no longer exists; no enforcement was applied"
        )

    now = _now()
    before = {
        "status": item.status,
        "enforcement_action": item.enforcement_action,
    }
    item.status = "actioned"
    item.decision = "action"
    item.decided_by = actor.user_id[:36]
    item.decided_at = now
    item.decision_reason = approval.reason
    item.enforcement_action = payload["action"]
    item.approval_id = approval.id
    item.execution_count = int(item.execution_count or 0) + 1
    item.last_executed_at = now
    item.updated_at = now
    after = {
        "status": "actioned",
        "enforcement_action": payload["action"],
        "devices_updated": matched,
    }
    await _record_decision_audit(
        db,
        item=item,
        action="admin.abuse.action.executed",
        reason=approval.reason,
        before=before,
        after=after,
        actor=actor,
        request=request,
        approval_id=approval.id,
    )
    await admin_approval_service.complete_execution(
        db,
        approval,
        actor=actor,
        result={
            "queue_item_id": item.id,
            "action": payload["action"],
            "devices_updated": matched,
        },
        note=note,
        request=request,
    )
    await db.commit()
    await db.refresh(item)
    return signal_summary(item)


async def decide(
    db: AsyncSession,
    *,
    item_id: str,
    decision: str,
    action: str | None,
    reason: str | None,
    confirm: bool,
    actor: AdminActor,
    approval_id: str | None = None,
    note: str | None = None,
    request=None,
) -> dict[str, Any]:
    _require_confirm(confirm)
    if decision not in DECISIONS:
        raise AbuseReviewValidationError("decision must be approve, dismiss or action")
    cleaned_reason = _clean_reason(reason)

    if decision == "action":
        if not action or action not in ENFORCEMENT_ACTIONS:
            raise AbuseReviewValidationError(
                "action must be block, unblock or whitelist"
            )
        if approval_id:
            approval = await admin_approval_service.get_request(db, approval_id)
            if approval is None:
                raise AbuseReviewNotFound("Approval request not found")
            if approval.request_type != "abuse_review_action":
                raise AbuseReviewConflict("This approval is not an abuse action")
            try:
                approved_payload = admin_approval_service.normalize_payload(
                    "abuse_review_action", approval.payload
                )
            except ApprovalError:
                raise AbuseReviewConflict(
                    "This approval payload is not a valid abuse action"
                ) from None
            try:
                canonical_item_id = str(uuid.UUID(str(item_id)))
            except (ValueError, TypeError, AttributeError):
                raise AbuseReviewNotFound("Abuse-review item not found") from None
            if (
                approved_payload["queue_item_id"] != canonical_item_id
                or approved_payload["action"] != action
            ):
                raise AbuseReviewConflict(
                    "The approval does not match this queue item and action"
                )
            # Idempotent repeat: the approval has already been consumed by
            # this exact queue item.
            current = await get_item(db, item_id)
            if (
                current is not None
                and current.status == "actioned"
                and current.approval_id == approval.id
                and current.enforcement_action == action
            ):
                return {
                    "item": signal_summary(current),
                    "approval_required": False,
                    "approval": approval_summary(approval),
                    "idempotent": True,
                }
            summary = await _execute_approved_action(
                db,
                approval=approval,
                actor=actor,
                note=note or cleaned_reason,
                request=request,
            )
            refreshed = await admin_approval_service.get_request(db, approval.id)
            return {
                "item": summary,
                "approval_required": False,
                "approval": approval_summary(refreshed or approval),
                "idempotent": False,
            }

        item = await _require_item(db, item_id, for_update=True)
        if item.status == "actioned":
            if item.enforcement_action == action:
                return {
                    "item": signal_summary(item),
                    "approval_required": False,
                    "approval": None,
                    "idempotent": True,
                }
            raise AbuseReviewConflict("This queue item was already actioned")
        if item.status not in {"open", "approved"}:
            raise AbuseReviewConflict(
                f"A {item.status} queue item cannot be actioned"
            )
        payload = abuse_action_payload(item, action)
        approval = await admin_approval_service.create_request(
            db,
            request_type="abuse_review_action",
            payload=payload,
            reason=cleaned_reason,
            actor=actor,
            resource_type="abuse_review_item",
            resource_id=item.id,
            request=request,
            commit=False,
        )
        await _record_decision_audit(
            db,
            item=item,
            action="admin.abuse.action.requested",
            reason=cleaned_reason,
            before={"status": item.status},
            after={"status": item.status, "requested_action": action},
            actor=actor,
            request=request,
            approval_id=approval.id,
        )
        await db.commit()
        await db.refresh(item)
        return {
            "item": signal_summary(item),
            "approval_required": True,
            "approval": approval_summary(approval),
            "idempotent": False,
        }

    item = await _require_item(db, item_id, for_update=True)
    target_status = "approved" if decision == "approve" else "dismissed"
    if item.status == target_status and item.decision == decision:
        return {
            "item": signal_summary(item),
            "approval_required": False,
            "approval": None,
            "idempotent": True,
        }
    if item.status == "actioned":
        raise AbuseReviewConflict("An actioned queue item cannot be changed")
    if decision == "approve" and item.status != "open":
        raise AbuseReviewConflict("Only an open item can be acknowledged")
    if decision == "dismiss" and item.status not in {"open", "approved"}:
        raise AbuseReviewConflict("Only an open or acknowledged item can be dismissed")

    now = _now()
    before = {"status": item.status, "decision": item.decision}
    item.status = target_status
    item.decision = decision
    item.decided_by = actor.user_id[:36]
    item.decided_at = now
    item.decision_reason = cleaned_reason
    item.updated_at = now
    await _record_decision_audit(
        db,
        item=item,
        action="admin.abuse.decision",
        reason=cleaned_reason,
        before=before,
        after={
            "status": target_status,
            "decision": decision,
            "decision_note": _clean_note(note),
        },
        actor=actor,
        request=request,
    )
    await db.commit()
    await db.refresh(item)
    return {
        "item": signal_summary(item),
        "approval_required": False,
        "approval": None,
        "idempotent": False,
    }


async def execute_approved_action(
    db: AsyncSession,
    *,
    approval_id: str,
    actor: AdminActor,
    note: str | None = None,
    request=None,
) -> dict[str, Any]:
    """Executor used by the shared approval queue for ``abuse_review_action``."""
    approval = await admin_approval_service.get_request(db, approval_id)
    if approval is None:
        raise AbuseReviewNotFound("Approval request not found")
    if approval.request_type != "abuse_review_action":
        raise AbuseReviewConflict("This approval is not an abuse action")
    if approval.status == "executed":
        raise ApprovalReplay("This approval was already executed")
    return await _execute_approved_action(
        db, approval=approval, actor=actor, note=note, request=request
    )


async def action_preview(
    db: AsyncSession, *, item_id: str, action: str
) -> dict[str, Any]:
    """Return the exact approval payload without mutating anything."""
    if action not in ENFORCEMENT_ACTIONS:
        raise AbuseReviewValidationError("Unknown enforcement action")
    item = await _require_item(db, item_id)
    payload = abuse_action_payload(item, action)
    return {
        "request_type": "abuse_review_action",
        "payload": payload,
        "payload_hash": admin_approval_service.payload_hash(
            "abuse_review_action", payload
        ),
        "resource_type": "abuse_review_item",
        "resource_id": item.id,
    }

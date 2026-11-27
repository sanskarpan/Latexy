"""Admin-only versioned data-retention policies, previews and bounded purges.

Five classes are managed independently: render PDF artifacts, durable job
finalizations, analytics rows, the append-only admin audit log and expired GDPR
export links. A run never issues an unbounded ``DELETE``/``UPDATE``: it resolves
at most ``limit`` primary keys, refuses active work and legal holds, and writes
one append-only audit row together with a persisted run record.

Retention is a lower bound, not an automatic deletion order. Policy updates
require a reason, an optimistic version and explicit confirmation; a purge
requires a separate reason and confirmation. The audit class is intentionally
immutable at the storage layer and therefore previewable but not purgeable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import Request
from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database.models import (
    AdminAuditLog,
    GdprLegalHold,
    GdprRequest,
    GdprRequestEvent,
    JobFinalization,
    RenderArtifactManifest,
    RetentionPolicy,
    RetentionPolicyRevision,
    RetentionRun,
    UsageAnalytics,
)
from .admin_audit_service import AdminActor, record_admin_audit

logger = get_logger(__name__)

MIN_GROUP_USERS = 5
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
BOUNDARY_WINDOW_HOURS = 24

TERMINAL_FINALIZATION_STATES = ("completed", "failed", "cancelled", "fenced")

PurgeMode = Literal["delete", "scrub", "immutable"]


@dataclass(frozen=True)
class DataClassSpec:
    key: str
    label: str
    description: str
    purge_mode: PurgeMode
    floor_hours: int


DATA_CLASSES: dict[str, DataClassSpec] = {
    "pdfs": DataClassSpec(
        key="pdfs",
        label="PDF artifacts",
        description=(
            "Expired render-artifact manifests. Objects become reference-free and are "
            "collected by the existing reference-aware storage sweep; active jobs and "
            "legal holds are never touched."
        ),
        purge_mode="delete",
        floor_hours=max(
            1, math.ceil(max(1, settings.PDF_RETENTION_TIME or 0) / 3600)
        ),
    ),
    "job_finalizations": DataClassSpec(
        key="job_finalizations",
        label="Job finalizations",
        description=(
            "Terminal durable job recovery rows past their expiry. Non-terminal jobs and "
            "rows with a live artifact reference are refused."
        ),
        purge_mode="delete",
        floor_hours=1,
    ),
    "analytics": DataClassSpec(
        key="analytics",
        label="Analytics events",
        description=(
            "Bounded usage-analytics rows older than the window. Rows owned by an account "
            "under an active legal hold are retained."
        ),
        purge_mode="delete",
        floor_hours=24,
    ),
    "audit": DataClassSpec(
        key="audit",
        label="Admin audit log",
        description=(
            "Append-only operator records. The window is reported for retention review, "
            "but rows cannot be deleted through this surface."
        ),
        purge_mode="immutable",
        floor_hours=24,
    ),
    "exports": DataClassSpec(
        key="exports",
        label="GDPR export links",
        description=(
            "Expired export token hashes are scrubbed from request rows while the request "
            "evidence and append-only event history remain intact."
        ),
        purge_mode="scrub",
        floor_hours=max(
            1, math.ceil(max(1, settings.GDPR_EXPORT_TTL_MINUTES or 0) / 60)
        ),
    ),
}

DATA_CLASS_ORDER = tuple(DATA_CLASSES)


class RetentionError(RuntimeError):
    code = "retention_error"
    status_code = 409

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class RetentionNotFound(RetentionError):
    code = "retention_class_not_found"
    status_code = 404


class RetentionConflict(RetentionError):
    code = "retention_run_in_progress"
    status_code = 409


class RetentionVersionConflict(RetentionError):
    code = "retention_policy_version_conflict"
    status_code = 409


class RetentionRefused(RetentionError):
    code = "retention_purge_refused"
    status_code = 409


class RetentionConfirmationRequired(RetentionError):
    code = "retention_confirmation_required"
    status_code = 422


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _spec(data_class: str) -> DataClassSpec:
    try:
        return DATA_CLASSES[data_class]
    except KeyError as exc:
        raise RetentionNotFound("Unknown retention data class") from exc


def effective_hours(spec: DataClassSpec, configured_hours: int) -> int:
    """Apply the class safety floor; a lower stored value is surfaced, not hidden."""
    return max(int(configured_hours), int(spec.floor_hours))


def retention_cutoff(now: datetime, effective: int) -> datetime:
    return now - timedelta(hours=max(1, int(effective)))


def is_eligible(age_seconds: float, retention_seconds: float) -> bool:
    """Rows exactly on the boundary are eligible (age >= retention)."""
    return float(age_seconds) >= float(retention_seconds)


def _age_seconds(value: datetime | None, now: datetime) -> float | None:
    normalized = _utc(value)
    return max(0.0, (now - normalized).total_seconds()) if normalized else None


def _held_users():
    return select(GdprLegalHold.user_id).where(GdprLegalHold.active.is_(True))


def _not_held(column):
    return (column.is_(None)) | (~column.in_(_held_users()))


def _policy_payload(policy: RetentionPolicy, spec: DataClassSpec) -> dict[str, Any]:
    configured = int(policy.configured_hours)
    effective = effective_hours(spec, configured)
    exceptions: list[str] = []
    if configured < spec.floor_hours:
        exceptions.append("configured_below_safety_floor")
    if effective > configured:
        exceptions.append("effective_floor_applied")
    if spec.purge_mode == "immutable":
        exceptions.append("append_only_immutable")
    if not policy.enabled:
        exceptions.append("schedule_disabled")
    return {
        "data_class": policy.data_class,
        "label": spec.label,
        "description": spec.description,
        "configured_hours": configured,
        "effective_hours": effective,
        "floor_hours": spec.floor_hours,
        "schedule_hours": int(policy.schedule_hours),
        "enabled": bool(policy.enabled),
        "version": int(policy.version),
        "purge_mode": spec.purge_mode,
        "purge_supported": spec.purge_mode != "immutable",
        "policy_updated_at": _iso(policy.updated_at),
        "exceptions": exceptions,
    }


def _run_payload(run: RetentionRun, *, replayed: bool = False) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "data_class": run.data_class,
        "mode": run.mode,
        "status": run.status,
        "dry_run": run.mode == "dry_run",
        "retention_hours": int(run.retention_hours),
        "effective_hours": int(run.effective_hours),
        "cutoff_at": _iso(run.cutoff_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "counts": {
            "scanned": int(run.scanned),
            "eligible": int(run.eligible),
            "protected_active_jobs": int(run.protected_active_jobs),
            "protected_legal_hold": int(run.protected_legal_hold),
            "protected_immutable": int(run.protected_immutable),
            "recent": int(run.recent),
        },
        "affected": int(run.affected),
        "would_affect": int(run.detail.get("would_affect", 0)) if isinstance(run.detail, dict) else 0,
        "limit": int(run.batch_limit),
        "has_more": bool(run.has_more),
        "detail": run.detail if isinstance(run.detail, dict) else {},
        "replayed": replayed,
    }


async def _scalar_count(db: AsyncSession, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(await db.scalar(statement) or 0)


def _pdf_active_condition():
    return exists(
        select(JobFinalization.id).where(
            JobFinalization.job_id == RenderArtifactManifest.job_id,
            JobFinalization.state.notin_(TERMINAL_FINALIZATION_STATES),
        )
    )


def _pdf_hold_condition():
    return exists(
        select(JobFinalization.id)
        .join(GdprLegalHold, GdprLegalHold.user_id == JobFinalization.user_id)
        .where(
            JobFinalization.job_id == RenderArtifactManifest.job_id,
            GdprLegalHold.active.is_(True),
        )
    )


def _pdf_eligible_conditions(cutoff: datetime):
    return (
        RenderArtifactManifest.expires_at <= cutoff,
        ~_pdf_active_condition(),
        ~_pdf_hold_condition(),
    )


def _finalization_live_reference_condition(now: datetime):
    return exists(
        select(RenderArtifactManifest.artifact_id).where(
            RenderArtifactManifest.job_id == JobFinalization.job_id,
            RenderArtifactManifest.expires_at > now,
        )
    )


def _finalization_hold_condition():
    return exists(
        select(GdprLegalHold.id).where(
            GdprLegalHold.user_id == JobFinalization.user_id,
            GdprLegalHold.active.is_(True),
        )
    )


def _finalization_eligible_conditions(cutoff: datetime, now: datetime):
    return (
        JobFinalization.state.in_(TERMINAL_FINALIZATION_STATES),
        JobFinalization.expires_at <= cutoff,
        ~_finalization_live_reference_condition(now),
        ~_finalization_hold_condition(),
    )


async def _boundary_counts_async(
    db: AsyncSession,
    *,
    model,
    age_column,
    cutoff: datetime,
    base_conditions: tuple[Any, ...],
) -> dict[str, int]:
    window = timedelta(hours=BOUNDARY_WINDOW_HOURS)
    inside = await _scalar_count(
        db,
        model,
        *base_conditions,
        age_column > cutoff,
        age_column <= cutoff + window,
    )
    outside = await _scalar_count(
        db,
        model,
        *base_conditions,
        age_column > cutoff - window,
        age_column <= cutoff,
    )
    return {"inside_24h": inside, "outside_24h": outside}


async def _counts_for(
    db: AsyncSession, spec: DataClassSpec, *, cutoff: datetime, now: datetime
) -> dict[str, int]:
    if spec.key == "pdfs":
        base = (RenderArtifactManifest.expires_at <= cutoff,)
        scanned = await _scalar_count(db, RenderArtifactManifest, *base)
        active = await _scalar_count(
            db, RenderArtifactManifest, *base, _pdf_active_condition()
        )
        held = await _scalar_count(
            db,
            RenderArtifactManifest,
            *base,
            ~_pdf_active_condition(),
            _pdf_hold_condition(),
        )
        eligible = await _scalar_count(db, RenderArtifactManifest, *base, ~_pdf_active_condition(), ~_pdf_hold_condition())
        total = await _scalar_count(db, RenderArtifactManifest)
        boundary = await _boundary_counts_async(
            db,
            model=RenderArtifactManifest,
            age_column=RenderArtifactManifest.expires_at,
            cutoff=cutoff,
            base_conditions=(),
        )
        return {
            "total": total,
            "older_than_policy": scanned,
            "eligible": eligible,
            "protected_active_jobs": active,
            "protected_legal_hold": held,
            "protected_immutable": 0,
            "already_scrubbed": 0,
            "recent": max(0, total - scanned),
            **boundary,
        }

    if spec.key == "job_finalizations":
        base = (
            JobFinalization.state.in_(TERMINAL_FINALIZATION_STATES),
            JobFinalization.expires_at <= cutoff,
        )
        scanned = await _scalar_count(db, JobFinalization, *base)
        live = await _scalar_count(
            db,
            JobFinalization,
            *base,
            _finalization_live_reference_condition(now),
        )
        held = await _scalar_count(
            db,
            JobFinalization,
            *base,
            ~_finalization_live_reference_condition(now),
            _finalization_hold_condition(),
        )
        eligible = await _scalar_count(
            db,
            JobFinalization,
            *base,
            ~_finalization_live_reference_condition(now),
            ~_finalization_hold_condition(),
        )
        active_rows = await _scalar_count(
            db,
            JobFinalization,
            JobFinalization.state.notin_(TERMINAL_FINALIZATION_STATES),
        )
        total = await _scalar_count(db, JobFinalization)
        boundary = await _boundary_counts_async(
            db,
            model=JobFinalization,
            age_column=JobFinalization.expires_at,
            cutoff=cutoff,
            base_conditions=(JobFinalization.state.in_(TERMINAL_FINALIZATION_STATES),),
        )
        return {
            "total": total,
            "older_than_policy": scanned,
            "eligible": eligible,
            "protected_active_jobs": active_rows + live,
            "protected_legal_hold": held,
            "protected_immutable": 0,
            "already_scrubbed": 0,
            "recent": max(0, total - scanned),
            **boundary,
        }

    if spec.key == "analytics":
        base = (UsageAnalytics.created_at <= cutoff,)
        scanned = await _scalar_count(db, UsageAnalytics, *base)
        held = await _scalar_count(
            db,
            UsageAnalytics,
            *base,
            UsageAnalytics.user_id.in_(_held_users()),
        )
        eligible = await _scalar_count(
            db,
            UsageAnalytics,
            *base,
            _not_held(UsageAnalytics.user_id),
        )
        total = await _scalar_count(db, UsageAnalytics)
        boundary = await _boundary_counts_async(
            db,
            model=UsageAnalytics,
            age_column=UsageAnalytics.created_at,
            cutoff=cutoff,
            base_conditions=(),
        )
        return {
            "total": total,
            "older_than_policy": scanned,
            "eligible": eligible,
            "protected_active_jobs": 0,
            "protected_legal_hold": held,
            "protected_immutable": 0,
            "already_scrubbed": 0,
            "recent": max(0, total - scanned),
            **boundary,
        }

    if spec.key == "audit":
        base = (AdminAuditLog.created_at <= cutoff,)
        scanned = await _scalar_count(db, AdminAuditLog, *base)
        total = await _scalar_count(db, AdminAuditLog)
        boundary = await _boundary_counts_async(
            db,
            model=AdminAuditLog,
            age_column=AdminAuditLog.created_at,
            cutoff=cutoff,
            base_conditions=(),
        )
        return {
            "total": total,
            "older_than_policy": scanned,
            "eligible": 0,
            "protected_active_jobs": 0,
            "protected_legal_hold": 0,
            "protected_immutable": scanned,
            "already_scrubbed": 0,
            "recent": max(0, total - scanned),
            **boundary,
        }

    # exports
    export_rows = (GdprRequest.request_type == "export",)
    base = (
        *export_rows,
        GdprRequest.export_expires_at.isnot(None),
        GdprRequest.export_expires_at <= cutoff,
    )
    scanned = await _scalar_count(db, GdprRequest, *base)
    held = await _scalar_count(
        db,
        GdprRequest,
        *base,
        GdprRequest.user_id.in_(_held_users()),
    )
    scrubbed = await _scalar_count(
        db,
        GdprRequest,
        *base,
        GdprRequest.export_token_hash.is_(None),
    )
    eligible = await _scalar_count(
        db,
        GdprRequest,
        *base,
        GdprRequest.export_token_hash.isnot(None),
        _not_held(GdprRequest.user_id),
    )
    total = await _scalar_count(db, GdprRequest, *export_rows)
    boundary = await _boundary_counts_async(
        db,
        model=GdprRequest,
        age_column=GdprRequest.export_expires_at,
        cutoff=cutoff,
        base_conditions=(GdprRequest.export_expires_at.isnot(None),),
    )
    return {
        "total": total,
        "older_than_policy": scanned,
        "eligible": eligible,
        "protected_active_jobs": 0,
        "protected_legal_hold": held,
        "protected_immutable": 0,
        "already_scrubbed": scrubbed,
        "recent": max(0, total - scanned),
        **boundary,
    }


async def _recent_runs(db: AsyncSession) -> dict[str, RetentionRun]:
    rows = (
        await db.execute(
            select(RetentionRun)
            .order_by(RetentionRun.started_at.desc())
            .limit(50)
        )
    ).scalars().all()
    latest: dict[str, RetentionRun] = {}
    for row in rows:
        latest.setdefault(row.data_class, row)
    return latest


def _next_run_at(
    policy: RetentionPolicy, last_run: RetentionRun | None
) -> datetime | None:
    if not policy.enabled:
        return None
    anchor = _utc(policy.updated_at) or _now()
    last_started = _utc(last_run.started_at) if last_run else None
    if last_started and last_started > anchor:
        anchor = last_started
    return anchor + timedelta(hours=int(policy.schedule_hours))


async def get_overview(db: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate configured/effective posture for every managed data class."""
    observed = now or _now()
    policies = {
        row.data_class: row
        for row in (
            await db.execute(
                select(RetentionPolicy).order_by(RetentionPolicy.data_class)
            )
        ).scalars().all()
    }
    latest = await _recent_runs(db)
    classes: list[dict[str, Any]] = []
    for key in DATA_CLASS_ORDER:
        spec = DATA_CLASSES[key]
        policy = policies.get(key)
        if policy is None:
            continue
        effective = effective_hours(spec, policy.configured_hours)
        cutoff = retention_cutoff(observed, effective)
        counts = await _counts_for(db, spec, cutoff=cutoff, now=observed)
        last_run = latest.get(key)
        payload = _policy_payload(policy, spec)
        next_run = _next_run_at(policy, last_run)
        payload.update(
            {
                "counts": counts,
                "boundary": {
                    "cutoff_at": _iso(cutoff),
                    "boundary_age_hours": effective,
                    "inside_24h": counts["inside_24h"],
                    "outside_24h": counts["outside_24h"],
                },
                "next_run_at": _iso(next_run),
                "schedule_due": bool(next_run is not None and next_run <= observed),
                "last_run": _run_payload(last_run) if last_run else None,
            }
        )
        classes.append(payload)
    return {
        "generated_at": _iso(observed),
        "aggregate_only": True,
        "per_user_breakdown": False,
        "minimum_cohort_size": MIN_GROUP_USERS,
        "boundary_window_hours": BOUNDARY_WINDOW_HOURS,
        "classes": classes,
    }


async def _acquire_run_lock(db: AsyncSession, data_class: str) -> bool:
    """Transaction-scoped guard shared by previews and purges for one class."""
    result = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
        {"key": f"retention:{data_class}"},
    )
    return bool(result)


async def _promote_existing_run(
    db: AsyncSession, data_class: str, idempotency_key: str | None
) -> RetentionRun | None:
    if not idempotency_key:
        return None
    return (
        await db.execute(
            select(RetentionRun)
            .where(
                RetentionRun.data_class == data_class,
                RetentionRun.idempotency_key == idempotency_key,
            )
            .order_by(RetentionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _purge_pdfs(db: AsyncSession, cutoff: datetime, limit: int) -> int:
    ids = list(
        (
            await db.scalars(
                select(RenderArtifactManifest.artifact_id)
                .where(*_pdf_eligible_conditions(cutoff))
                .order_by(RenderArtifactManifest.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not ids:
        return 0
    result = await db.execute(
        delete(RenderArtifactManifest).where(RenderArtifactManifest.artifact_id.in_(ids))
    )
    return int(result.rowcount or 0)


async def _purge_finalizations(
    db: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = list(
        (
            await db.scalars(
                select(JobFinalization.id)
                .where(*_finalization_eligible_conditions(cutoff, now))
                .order_by(JobFinalization.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not ids:
        return 0
    result = await db.execute(delete(JobFinalization).where(JobFinalization.id.in_(ids)))
    return int(result.rowcount or 0)


async def _purge_analytics(db: AsyncSession, cutoff: datetime, limit: int) -> int:
    ids = list(
        (
            await db.scalars(
                select(UsageAnalytics.id)
                .where(
                    UsageAnalytics.created_at <= cutoff,
                    _not_held(UsageAnalytics.user_id),
                )
                .order_by(UsageAnalytics.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not ids:
        return 0
    result = await db.execute(delete(UsageAnalytics).where(UsageAnalytics.id.in_(ids)))
    return int(result.rowcount or 0)


async def _scrub_exports(db: AsyncSession, cutoff: datetime, limit: int) -> int:
    rows = (
        await db.scalars(
            select(GdprRequest)
            .where(
                GdprRequest.request_type == "export",
                GdprRequest.export_expires_at.isnot(None),
                GdprRequest.export_expires_at <= cutoff,
                GdprRequest.export_token_hash.isnot(None),
                _not_held(GdprRequest.user_id),
            )
            .order_by(GdprRequest.export_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if not rows:
        return 0
    for row in rows:
        row.export_token_hash = None
        db.add(
            GdprRequestEvent(
                id=str(uuid4()),
                request_id=row.id,
                event="export.expired_scrubbed",
                actor_type="system",
                actor_user_id=None,
                from_status=row.status,
                to_status=row.status,
                reason="Expired export token scrubbed by retention policy",
                event_metadata={"data_class": "exports"},
            )
        )
    return len(rows)


async def _mutate(
    db: AsyncSession,
    spec: DataClassSpec,
    *,
    cutoff: datetime,
    now: datetime,
    limit: int,
) -> int:
    if spec.key == "pdfs":
        return await _purge_pdfs(db, cutoff, limit)
    if spec.key == "job_finalizations":
        return await _purge_finalizations(db, cutoff, now, limit)
    if spec.key == "analytics":
        return await _purge_analytics(db, cutoff, limit)
    if spec.key == "exports":
        return await _scrub_exports(db, cutoff, limit)
    raise RetentionRefused("This data class is immutable", code="retention_class_immutable")


async def update_policy(
    db: AsyncSession,
    *,
    data_class: str,
    retention_hours: int,
    schedule_hours: int,
    enabled: bool,
    expected_version: int,
    reason: str,
    confirm: bool,
    actor: AdminActor,
    request: Request | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    spec = _spec(data_class)
    if confirm is not True:
        raise RetentionConfirmationRequired("Policy changes require confirmation")
    observed = now or _now()
    policy = (
        await db.execute(
            select(RetentionPolicy)
            .where(RetentionPolicy.data_class == data_class)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if policy is None:
        raise RetentionNotFound("Unknown retention data class")
    if int(policy.version) != int(expected_version):
        raise RetentionVersionConflict(
            "The retention policy changed; refresh before saving", code="retention_policy_version_conflict"
        )
    before = _policy_payload(policy, spec)
    new_version = int(policy.version) + 1
    policy.configured_hours = int(retention_hours)
    policy.schedule_hours = int(schedule_hours)
    policy.enabled = bool(enabled)
    policy.version = new_version
    policy.updated_by = str(actor.user_id)[:36]
    policy.updated_at = observed
    policy.change_reason = reason.strip()[:2000]
    db.add(
        RetentionPolicyRevision(
            data_class=data_class,
            version=new_version,
            snapshot={
                "data_class": data_class,
                "configured_hours": int(retention_hours),
                "schedule_hours": int(schedule_hours),
                "enabled": bool(enabled),
                "version": new_version,
            },
            changed_by=str(actor.user_id)[:36],
            reason=reason.strip()[:2000],
        )
    )
    after = _policy_payload(policy, spec)
    await record_admin_audit(
        db,
        actor=actor,
        action="retention.policy.updated",
        target_type="retention_policy",
        target_id=data_class,
        reason=reason,
        before=before,
        after=after,
        metadata={"version": new_version},
        request=request,
        commit=False,
    )
    await db.commit()
    return after


async def execute_run(
    db: AsyncSession,
    *,
    data_class: str,
    dry_run: bool,
    reason: str,
    confirm: bool,
    limit: int,
    idempotency_key: str | None,
    actor: AdminActor,
    request: Request | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview or apply one bounded class run; never a broad table wipe."""
    spec = _spec(data_class)
    if not dry_run and confirm is not True:
        raise RetentionConfirmationRequired("Purges require explicit confirmation")
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise RetentionError("limit must be between 1 and 1000", code="invalid_retention_limit")
    observed = now or _now()
    if not await _acquire_run_lock(db, data_class):
        raise RetentionConflict("Another retention run is active for this data class")

    existing = await _promote_existing_run(db, data_class, idempotency_key)
    if existing is not None:
        if existing.status == "running":
            raise RetentionConflict("Another retention run is active for this data class")
        return _run_payload(existing, replayed=True)

    policy = (
        await db.execute(
            select(RetentionPolicy)
            .where(RetentionPolicy.data_class == data_class)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if policy is None:
        raise RetentionNotFound("Unknown retention data class")
    effective = effective_hours(spec, policy.configured_hours)
    cutoff = retention_cutoff(observed, effective)
    counts = await _counts_for(db, spec, cutoff=cutoff, now=observed)
    if spec.purge_mode == "immutable" and not dry_run:
        refused = RetentionRun(
            id=str(uuid4()),
            data_class=data_class,
            mode="purge",
            status="refused",
            retention_hours=int(policy.configured_hours),
            effective_hours=effective,
            cutoff_at=cutoff,
            scanned=counts["older_than_policy"],
            eligible=0,
            protected_active_jobs=counts["protected_active_jobs"],
            protected_legal_hold=counts["protected_legal_hold"],
            protected_immutable=counts["protected_immutable"],
            recent=counts["recent"],
            affected=0,
            batch_limit=int(limit),
            has_more=False,
            started_by=str(actor.user_id)[:36],
            reason=reason.strip()[:2000],
            idempotency_key=idempotency_key,
            started_at=observed,
            finished_at=_now(),
            detail={
                "code": "retention_class_immutable",
                "would_affect": 0,
                "boundary": {
                    "cutoff_at": _iso(cutoff),
                    "inside_24h": counts["inside_24h"],
                    "outside_24h": counts["outside_24h"],
                },
            },
        )
        db.add(refused)
        await record_admin_audit(
            db,
            actor=actor,
            action="retention.purge.refused",
            target_type="retention_policy",
            target_id=data_class,
            reason=reason,
            before=None,
            after={
                "data_class": data_class,
                "code": "retention_class_immutable",
                "eligible": 0,
                "older_than_policy": counts["older_than_policy"],
            },
            metadata={"run_id": str(refused.id), "limit": int(limit)},
            request=request,
            commit=False,
        )
        await db.commit()
        raise RetentionRefused(
            "The admin audit log is append-only and cannot be purged",
            code="retention_class_immutable",
        )
    run = RetentionRun(
        id=str(uuid4()),
        data_class=data_class,
        mode="dry_run" if dry_run else "purge",
        status="running",
        retention_hours=int(policy.configured_hours),
        effective_hours=effective,
        cutoff_at=cutoff,
        scanned=counts["older_than_policy"],
        eligible=counts["eligible"],
        protected_active_jobs=counts["protected_active_jobs"],
        protected_legal_hold=counts["protected_legal_hold"],
        protected_immutable=counts["protected_immutable"],
        recent=counts["recent"],
        affected=0,
        batch_limit=int(limit),
        has_more=counts["eligible"] > int(limit),
        started_by=str(actor.user_id)[:36],
        reason=reason.strip()[:2000],
        idempotency_key=idempotency_key,
        started_at=observed,
        detail={
            "boundary": {
                "cutoff_at": _iso(cutoff),
                "inside_24h": counts["inside_24h"],
                "outside_24h": counts["outside_24h"],
            },
            "already_scrubbed": counts["already_scrubbed"],
        },
    )
    db.add(run)
    await db.flush()

    try:
        if dry_run:
            run.detail = {**run.detail, "would_affect": min(counts["eligible"], int(limit))}
        else:
            affected = await _mutate(db, spec, cutoff=cutoff, now=observed, limit=int(limit))
            run.affected = affected
            run.detail = {**run.detail, "would_affect": affected}
        run.status = "completed"
        run.finished_at = _now()
    except Exception:
        logger.error(
            "Retention run failed",
            extra={
                "data_class": str(data_class).encode("unicode_escape").decode("ascii", "ignore")[:32],
                "dry_run": dry_run,
            },
        )
        raise

    await record_admin_audit(
        db,
        actor=actor,
        action="retention.dry_run" if dry_run else "retention.purge",
        target_type="retention_policy",
        target_id=data_class,
        reason=reason,
        before=None,
        after={
            "data_class": data_class,
            "mode": run.mode,
            "effective_hours": effective,
            "cutoff_at": _iso(cutoff),
            "eligible": run.eligible,
            "affected": run.affected,
            "has_more": run.has_more,
        },
        metadata={
            "run_id": str(run.id),
            "limit": int(limit),
            "protected_active_jobs": run.protected_active_jobs,
            "protected_legal_hold": run.protected_legal_hold,
            "protected_immutable": run.protected_immutable,
            "idempotency_key_present": bool(idempotency_key),
        },
        request=request,
        commit=False,
    )
    await db.commit()
    return _run_payload(run)

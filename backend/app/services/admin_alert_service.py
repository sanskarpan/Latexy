"""Durable admin alerts with evaluation, acknowledgement and snoozing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.logging import get_logger
from ..database import models
from .admin_audit_service import AdminActor, record_admin_audit

logger = get_logger(__name__)

ACTIVE_STATES = ("open", "acknowledged", "snoozed")
RUNBOOK_URL = "https://github.com/sanskarpan/Latexy/blob/main/docs/ADMIN_CONTROL_ROOM.md"
FAILURE_GRACE = timedelta(minutes=5)


def _alert_row(row: models.AdminAlert) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "severity": row.severity,
        "owner": row.owner,
        "title": row.title,
        "dedupe_key": row.dedupe_key,
        "payload": row.payload or {},
        "runbook_url": row.runbook_url,
        "state": row.state,
        "occurrence_count": row.occurrence_count,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "acknowledgement_note": row.acknowledgement_note,
        "snoozed_by": row.snoozed_by,
        "snoozed_at": row.snoozed_at.isoformat() if row.snoozed_at else None,
        "snooze_until": row.snooze_until.isoformat() if row.snooze_until else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolution": row.resolution,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _signal(
    *,
    kind: str,
    severity: str,
    owner: str,
    title: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "owner": owner,
        "title": title,
        "dedupe_key": dedupe_key,
        "payload": payload,
        "runbook_url": RUNBOOK_URL,
    }


async def _failure_signal(
    db: AsyncSession,
    *,
    model,
    status_condition,
    kind: str,
    severity: str,
    owner: str,
    title: str,
    dedupe_key: str,
    timestamp_column,
    now: datetime,
) -> dict[str, Any] | None:
    count, oldest = (
        await db.execute(
            select(func.count(model.id), func.min(timestamp_column)).where(status_condition)
        )
    ).one()
    count = int(count or 0)
    if count == 0 or oldest is None:
        return None
    age = int((now - oldest).total_seconds())
    if age < int(FAILURE_GRACE.total_seconds()):
        return None
    return _signal(
        kind=kind,
        severity=severity,
        owner=owner,
        title=title,
        dedupe_key=dedupe_key,
        payload={"count": count, "oldest_age_seconds": age},
    )


async def collect_signals(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """Return current alertable conditions; no PII or provider errors."""
    signals: list[dict[str, Any]] = []

    webhook = await _failure_signal(
        db,
        model=models.BillingWebhookEvent,
        status_condition=(
            (models.BillingWebhookEvent.status == "failed")
            & models.BillingWebhookEvent.acknowledged_at.is_(None)
        ),
        kind="billing.webhook_failures",
        severity="critical",
        owner="Billing",
        title="Unacknowledged billing webhook failures",
        dedupe_key="billing.webhook_failures",
        timestamp_column=models.BillingWebhookEvent.received_at,
        now=now,
    )
    if webhook:
        signals.append(webhook)

    failed_payments = await _failure_signal(
        db,
        model=models.Payment,
        status_condition=(models.Payment.status == "failed"),
        kind="billing.failed_payments",
        severity="critical",
        owner="Billing",
        title="Failed payments need reconciliation",
        dedupe_key="billing.failed_payments",
        timestamp_column=models.Payment.created_at,
        now=now,
    )
    if failed_payments:
        signals.append(failed_payments)

    past_due = int(
        (
            await db.execute(
                select(func.count(models.Subscription.id)).where(
                    models.Subscription.status.in_(("past_due", "on_hold"))
                )
            )
        ).scalar()
        or 0
    )
    if past_due:
        signals.append(
            _signal(
                kind="billing.past_due",
                severity="high",
                owner="Billing",
                title="Past-due or on-hold subscriptions",
                dedupe_key="billing.past_due",
                payload={"count": past_due},
            )
        )

    cutoff = now - timedelta(minutes=15)
    stuck_compilations = int(
        (
            await db.execute(
                select(func.count(models.Compilation.id)).where(
                    models.Compilation.status.in_(("queued", "pending", "processing", "running")),
                    models.Compilation.created_at < cutoff,
                )
            )
        ).scalar()
        or 0
    )
    stale_finalizations = int(
        (
            await db.execute(
                select(func.count(models.JobFinalization.id)).where(
                    models.JobFinalization.state.in_(("pending", "committing")),
                    models.JobFinalization.created_at < cutoff,
                )
            )
        ).scalar()
        or 0
    )
    stuck = stuck_compilations + stale_finalizations
    if stuck:
        signals.append(
            _signal(
                kind="jobs.stuck",
                severity="high",
                owner="Platform",
                title="Jobs stuck beyond 15 minutes",
                dedupe_key="jobs.stuck",
                payload={"count": stuck},
            )
        )

    # Monthly spend cap only. Per-user outliers stay in the Growth tab and are
    # never copied into alert payloads because they identify an account.
    cap_signal: dict[str, Any] | None = None
    try:
        if float(settings.ADMIN_AI_MONTHLY_SPEND_CAP_USD or 0) > 0:
            from .admin_growth_service import admin_growth_service

            # A failed spend query must not poison the shared transaction and
            # suppress the remaining alert rules.
            async with db.begin_nested():
                cost = await admin_growth_service.ai_cost(db, days=30)
                cap_alert = next(
                    (alert for alert in cost.get("alerts", []) if alert.get("code") == "ai_monthly_cap"),
                    None,
                )
            if cap_alert:
                month_key = now.strftime("%Y-%m")
                cap_signal = _signal(
                    kind="spend.monthly_cap",
                    severity="critical" if cap_alert.get("severity") == "critical" else "medium",
                    owner="Growth",
                    title="Estimated AI spend reached the monthly cap",
                    dedupe_key=f"spend.monthly_cap:{month_key}",
                    payload={
                        "value_usd": cap_alert.get("value"),
                        "threshold_usd": cap_alert.get("threshold"),
                        "month": month_key,
                    },
                )
    except Exception as exc:
        logger.warning("Admin alert spend evaluation failed (%s)", type(exc).__name__)
    if cap_signal:
        signals.append(cap_signal)

    unverified_domains = int(
        (
            await db.execute(
                select(func.count(models.Tenant.id)).where(
                    models.Tenant.custom_domain.is_not(None),
                    models.Tenant.domain_verified_at.is_(None),
                )
            )
        ).scalar()
        or 0
    )
    if unverified_domains:
        signals.append(
            _signal(
                kind="domains.unverified",
                severity="low",
                owner="Growth",
                title="Unverified custom domains",
                dedupe_key="domains.unverified",
                payload={
                    "count": unverified_domains,
                    "expiry_metadata_configured": False,
                },
            )
        )

    return signals


async def evaluate_alerts(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Upsert current signals, reopen expired snoozes and auto-resolve clears."""
    now = now or datetime.now(timezone.utc)
    # Serialize overlapping five-minute evaluations so the SELECT-then-INSERT
    # dedupe path cannot race the partial unique index.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('latexy_admin_alerts'))"))
    signals = await collect_signals(db, now)
    seen: set[str] = set()
    opened = 0
    updated = 0

    for signal in signals:
        seen.add(signal["dedupe_key"])
        existing = (
            await db.execute(
                select(models.AdminAlert).where(
                    models.AdminAlert.dedupe_key == signal["dedupe_key"],
                    models.AdminAlert.state.in_(ACTIVE_STATES),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                models.AdminAlert(
                    **signal,
                    state="open",
                    occurrence_count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            opened += 1
            continue

        existing.severity = signal["severity"]
        existing.owner = signal["owner"]
        existing.title = signal["title"]
        existing.payload = signal["payload"]
        existing.runbook_url = signal["runbook_url"]
        existing.last_seen_at = now
        existing.occurrence_count = int(existing.occurrence_count or 0) + 1
        if existing.state == "snoozed" and existing.snooze_until and existing.snooze_until <= now:
            existing.state = "open"
            existing.snoozed_by = None
            existing.snoozed_at = None
            existing.snooze_until = None
        updated += 1

    resolved = 0
    stale = (
        await db.execute(
            select(models.AdminAlert).where(models.AdminAlert.state.in_(ACTIVE_STATES))
        )
    ).scalars().all()
    for row in stale:
        if row.dedupe_key in seen:
            continue
        if row.state == "snoozed" and row.snooze_until and row.snooze_until > now:
            # A flapping condition must not bypass an operator's snooze.
            continue
        row.state = "resolved"
        row.resolved_at = now
        row.resolution = "auto_clear"
        resolved += 1

    await db.flush()
    return {"opened": opened, "updated": updated, "resolved": resolved}


async def list_alerts(
    db: AsyncSession,
    *,
    state: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = []
    if state == "active":
        filters.append(models.AdminAlert.state.in_(ACTIVE_STATES))
    elif state:
        filters.append(models.AdminAlert.state == state)
    if severity:
        filters.append(models.AdminAlert.severity == severity)
    total = int(
        (
            await db.execute(
                select(func.count(models.AdminAlert.id)).where(*filters)
            )
        ).scalar()
        or 0
    )
    severity_order = case(
        (models.AdminAlert.severity == "critical", 0),
        (models.AdminAlert.severity == "high", 1),
        (models.AdminAlert.severity == "medium", 2),
        (models.AdminAlert.severity == "low", 3),
        else_=4,
    )
    rows = (
        await db.execute(
            select(models.AdminAlert)
            .where(*filters)
            .order_by(severity_order, models.AdminAlert.last_seen_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [_alert_row(row) for row in rows], total


async def get_alert(db: AsyncSession, alert_id: str) -> models.AdminAlert:
    row = await db.scalar(
        select(models.AdminAlert).where(models.AdminAlert.id == alert_id).with_for_update()
    )
    if row is None:
        raise KeyError("Alert not found")
    return row


async def acknowledge_alert(
    db: AsyncSession,
    *,
    alert_id: str,
    actor: AdminActor,
    reason: str,
    request: Any = None,
) -> dict[str, Any]:
    row = await get_alert(db, alert_id)
    if row.state == "resolved":
        raise ValueError("Resolved alerts cannot be acknowledged")
    before = {"state": row.state}
    now = datetime.now(timezone.utc)
    row.state = "acknowledged"
    row.acknowledged_by = actor.user_id[:36]
    row.acknowledged_at = now
    row.acknowledgement_note = reason[:1000]
    row.snoozed_by = None
    row.snoozed_at = None
    row.snooze_until = None
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.alert.acknowledge",
        target_type="admin_alert",
        target_id=alert_id,
        reason=reason,
        before=before,
        after={"state": "acknowledged"},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _alert_row(row)


async def snooze_alert(
    db: AsyncSession,
    *,
    alert_id: str,
    actor: AdminActor,
    reason: str,
    minutes: int,
    request: Any = None,
) -> dict[str, Any]:
    if minutes < 5 or minutes > 24 * 60:
        raise ValueError("Snooze must be between 5 and 1440 minutes")
    row = await get_alert(db, alert_id)
    if row.state == "resolved":
        raise ValueError("Resolved alerts cannot be snoozed")
    before = {"state": row.state, "snooze_until": row.snooze_until.isoformat() if row.snooze_until else None}
    now = datetime.now(timezone.utc)
    row.state = "snoozed"
    row.snoozed_by = actor.user_id[:36]
    row.snoozed_at = now
    row.snooze_until = now + timedelta(minutes=minutes)
    await record_admin_audit(
        db,
        actor=actor,
        action="admin.alert.snooze",
        target_type="admin_alert",
        target_id=alert_id,
        reason=reason,
        before=before,
        after={"state": "snoozed", "snooze_until": row.snooze_until.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _alert_row(row)

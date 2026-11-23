"""Admin operations: needs-attention queue and aggregated dependency health.

The payloads here are operational metadata only. They never include customer
identifiers, document content, credentials, connection strings or raw provider
errors. Every probe is independently bounded so one failed dependency cannot
blank the rest of the response.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..core.redis import redis_manager
from ..database import models

logger = get_logger(__name__)

ACTIVE_JOB_STATUSES = ("queued", "pending", "processing", "running")
PAST_DUE_STATUSES = ("past_due", "on_hold")
STUCK_AFTER = timedelta(minutes=15)
HEALTH_CACHE_SECONDS = 45

_health_cache: tuple[float, dict[str, Any]] | None = None


def reset_admin_operations_cache() -> None:
    """Test/operator seam: discard the in-process health snapshot."""
    global _health_cache
    _health_cache = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def _section(
    status: str,
    observed_at: str,
    detail: str | None = None,
    **metrics: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "observed_at": observed_at}
    if detail:
        payload["detail"] = detail
    payload.update(metrics)
    return payload


def _worst(statuses: list[str]) -> str:
    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def _capacity_status(status: str) -> str:
    if status in {"critical", "exhausted", "misconfigured", "unavailable"}:
        return "unhealthy"
    if status in {"unconfigured", "warning", "unknown"}:
        return "degraded"
    return "healthy"


async def _safe_rollback(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


def _attention_item(
    *,
    key: str,
    title: str,
    severity: str,
    owner: str,
    count: int,
    oldest_at: datetime | None,
    href: str,
    detail: str,
    source_status: str = "ok",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "severity": severity,
        "owner": owner,
        "count": count,
        "oldest_at": _iso(oldest_at),
        "href": href,
        "detail": detail,
        "source_status": source_status,
    }


async def _count_and_oldest(db: AsyncSession, statement) -> tuple[int, datetime | None]:
    row = (await db.execute(statement)).one()
    return int(row[0] or 0), row[1]


async def get_attention(db: AsyncSession) -> dict[str, Any]:
    """Aggregate actionable billing and job failures for the Overview panel."""
    now = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    # Failed provider webhooks stay visible until an operator acknowledges or
    # genuinely reconciles them. Acknowledgement never changes provider state.
    try:
        count, oldest = await _count_and_oldest(
            db,
            select(
                func.count(models.BillingWebhookEvent.id),
                func.min(models.BillingWebhookEvent.received_at),
            ).where(
                models.BillingWebhookEvent.status == "failed",
                models.BillingWebhookEvent.acknowledged_at.is_(None),
            ),
        )
        sources.append({"key": "billing.webhooks", "status": "ok", "count": count})
        if count:
            items.append(
                _attention_item(
                    key="billing.webhooks",
                    title="Unacknowledged billing webhook failures",
                    severity="critical",
                    owner="Billing",
                    count=count,
                    oldest_at=oldest,
                    href="/admin?tab=billing#admin-billing-webhooks",
                    detail="Review the provider event and reconcile or acknowledge it with a reason.",
                )
            )
    except Exception:
        await _safe_rollback(db)
        sources.append(
            {
                "key": "billing.webhooks",
                "status": "unavailable",
                "detail": "Webhook failures could not be checked",
            }
        )

    try:
        count, oldest = await _count_and_oldest(
            db,
            select(
                func.count(models.Subscription.id),
                func.min(models.Subscription.updated_at),
            ).where(models.Subscription.status.in_(PAST_DUE_STATUSES)),
        )
        sources.append({"key": "billing.subscriptions", "status": "ok", "count": count})
        if count:
            items.append(
                _attention_item(
                    key="billing.subscriptions",
                    title="Past-due or on-hold subscriptions",
                    severity="high",
                    owner="Billing",
                    count=count,
                    oldest_at=oldest,
                    href="/admin?tab=billing",
                    detail="Check provider retry state and whether the account needs support.",
                )
            )
    except Exception:
        await _safe_rollback(db)
        sources.append(
            {
                "key": "billing.subscriptions",
                "status": "unavailable",
                "detail": "Past-due subscriptions could not be checked",
            }
        )

    try:
        count, oldest = await _count_and_oldest(
            db,
            select(
                func.count(models.Payment.id),
                func.min(models.Payment.created_at),
            ).where(models.Payment.status == "failed"),
        )
        sources.append({"key": "billing.payments", "status": "ok", "count": count})
        if count:
            items.append(
                _attention_item(
                    key="billing.payments",
                    title="Failed payments",
                    severity="critical",
                    owner="Billing",
                    count=count,
                    oldest_at=oldest,
                    href="/admin?tab=billing",
                    detail="Failed payments stay visible until the provider outcome is reconciled.",
                )
            )
    except Exception:
        await _safe_rollback(db)
        sources.append(
            {
                "key": "billing.payments",
                "status": "unavailable",
                "detail": "Failed payments could not be checked",
            }
        )

    # Redis is the admission layer; the durable finalization row is the
    # cross-store arbiter. Count both, but never mutate either from this view.
    cutoff = now - STUCK_AFTER
    stuck_parts: list[tuple[int, datetime | None]] = []
    partial_jobs = False
    try:
        stuck_parts.append(
            await _count_and_oldest(
                db,
                select(
                    func.count(models.Compilation.id),
                    func.min(models.Compilation.created_at),
                ).where(
                    models.Compilation.status.in_(ACTIVE_JOB_STATUSES),
                    models.Compilation.created_at < cutoff,
                ),
            )
        )
    except Exception:
        await _safe_rollback(db)
        partial_jobs = True
    try:
        stuck_parts.append(
            await _count_and_oldest(
                db,
                select(
                    func.count(models.JobFinalization.id),
                    func.min(models.JobFinalization.created_at),
                ).where(
                    models.JobFinalization.state.in_(("pending", "committing")),
                    models.JobFinalization.created_at < cutoff,
                ),
            )
        )
    except Exception:
        await _safe_rollback(db)
        partial_jobs = True

    stuck_count = sum(part[0] for part in stuck_parts)
    stuck_oldest_values = [part[1] for part in stuck_parts if part[1] is not None]
    stuck_oldest = min(stuck_oldest_values) if stuck_oldest_values else None
    jobs_status = "unavailable" if partial_jobs and not stuck_parts else ("partial" if partial_jobs else "ok")
    sources.append({"key": "jobs.stuck", "status": jobs_status, "count": stuck_count})
    if stuck_count:
        items.append(
            _attention_item(
                key="jobs.stuck",
                title="Jobs stuck beyond 15 minutes",
                severity="high",
                owner="Platform",
                count=stuck_count,
                oldest_at=stuck_oldest,
                href="/admin#admin-job-queue",
                detail="Inspect the queue before retrying or cancelling; no action runs automatically.",
                source_status=jobs_status,
            )
        )

    # Custom-domain expiry/certificate metadata is not stored yet. Be explicit
    # instead of implying the domain source is healthy or empty.
    try:
        count = int(
            (
                await db.execute(
                    select(func.count(models.Tenant.id)).where(
                        models.Tenant.custom_domain.is_not(None),
                        models.Tenant.domain_verified_at.is_(None),
                    )
                )
            ).scalar_one()
            or 0
        )
        sources.append(
            {
                "key": "domains.custom",
                "status": "partial",
                "count": count,
                "detail": "Certificate/DNS expiry metadata is not configured; only unverified custom domains are reported.",
            }
        )
        if count:
            items.append(
                _attention_item(
                    key="domains.custom",
                    title="Unverified custom domains",
                    severity="low",
                    owner="Growth",
                    count=count,
                    oldest_at=None,
                    href="/admin?tab=customers",
                    detail="Domain expiry is unavailable until certificate/DNS metadata is connected.",
                    source_status="partial",
                )
            )
    except Exception:
        await _safe_rollback(db)
        sources.append(
            {
                "key": "domains.custom",
                "status": "unavailable",
                "detail": "Custom-domain state could not be checked",
            }
        )

    items.sort(key=lambda item: (item["severity"] != "critical", item["severity"] != "high", item["title"]))
    unavailable = any(source["status"] == "unavailable" for source in sources)
    return {
        "generated_at": now.isoformat(),
        "overall": "attention" if items or unavailable else "clear",
        "partial": unavailable,
        "items": items,
        "sources": sources,
    }


async def _probe_database(db: AsyncSession) -> tuple[str, str | None]:
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=5)
        return "healthy", None
    except Exception:
        await _safe_rollback(db)
        return "unhealthy", "Database probe failed"


async def _probe_redis() -> tuple[str, str | None]:
    try:
        client = redis_manager.redis_client
        if client is None:
            return "unhealthy", "Redis is not configured"
        await asyncio.wait_for(client.ping(), timeout=5)
        return "healthy", None
    except Exception:
        return "unhealthy", "Redis probe failed"


async def _probe_redis_cache() -> tuple[str, str | None]:
    try:
        client = redis_manager.redis_cache_client
        if client is None:
            return "unhealthy", "Cache Redis is not configured"
        await asyncio.wait_for(client.ping(), timeout=5)
        return "healthy", None
    except Exception:
        return "unhealthy", "Cache Redis probe failed"


async def _probe_storage() -> tuple[str, str | None]:
    try:
        from . import storage_service

        ok, _detail = await asyncio.wait_for(
            asyncio.to_thread(storage_service.probe), timeout=8
        )
        return ("healthy", None) if ok else ("unhealthy", "Object storage probe failed")
    except Exception:
        return "unhealthy", "Object storage probe failed"


async def _probe_capacity() -> tuple[str, str | None, dict[str, Any]]:
    try:
        from .redis_capacity_service import redis_capacity_service

        snapshot = await asyncio.wait_for(redis_capacity_service.snapshot(), timeout=6)
        status = _capacity_status(snapshot.status)
        metrics = {
            "provider": snapshot.provider,
            "configured": snapshot.configured,
            "utilization_ratio": snapshot.utilization_ratio,
        }
        detail = "Capacity probe is unconfigured" if snapshot.status == "unconfigured" else None
        return status, detail, metrics
    except Exception:
        return "unhealthy", "Redis capacity probe failed", {}


async def _billing_metrics(db: AsyncSession, now: datetime) -> dict[str, Any]:
    failed_webhooks = int(
        (
            await db.execute(
                select(func.count(models.BillingWebhookEvent.id)).where(
                    models.BillingWebhookEvent.status == "failed",
                    models.BillingWebhookEvent.acknowledged_at.is_(None),
                )
            )
        ).scalar_one()
        or 0
    )
    failed_payments = int(
        (
            await db.execute(
                select(func.count(models.Payment.id)).where(models.Payment.status == "failed")
            )
        ).scalar_one()
        or 0
    )
    past_due = int(
        (
            await db.execute(
                select(func.count(models.Subscription.id)).where(
                    models.Subscription.status.in_(PAST_DUE_STATUSES)
                )
            )
        ).scalar_one()
        or 0
    )
    return {
        "failed_webhooks": failed_webhooks,
        "failed_payments": failed_payments,
        "past_due_subscriptions": past_due,
        "observed_at": now.isoformat(),
    }


async def _job_metrics(db: AsyncSession, now: datetime) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(models.Compilation.status, func.count(models.Compilation.id))
            .where(models.Compilation.created_at >= now - timedelta(hours=24))
            .group_by(models.Compilation.status)
        )
    ).all()
    counts = {str(status or "unknown"): int(count or 0) for status, count in status_rows}
    cutoff = now - STUCK_AFTER
    stuck_compilations = int(
        (
            await db.execute(
                select(func.count(models.Compilation.id)).where(
                    models.Compilation.status.in_(ACTIVE_JOB_STATUSES),
                    models.Compilation.created_at < cutoff,
                )
            )
        ).scalar_one()
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
        ).scalar_one()
        or 0
    )
    oldest = (
        await db.execute(
            select(func.min(models.Compilation.created_at)).where(
                models.Compilation.status.in_(ACTIVE_JOB_STATUSES)
            )
        )
    ).scalar_one()
    return {
        "queued": counts.get("queued", 0) + counts.get("pending", 0),
        "processing": counts.get("processing", 0) + counts.get("running", 0),
        "stuck": stuck_compilations + stale_finalizations,
        "oldest_active_age_seconds": _age_seconds(oldest, now),
    }


async def _compilation_metrics(db: AsyncSession, now: datetime) -> dict[str, Any]:
    since = now - timedelta(hours=24)
    status_rows = (
        await db.execute(
            select(models.Compilation.status, func.count(models.Compilation.id))
            .where(models.Compilation.created_at >= since)
            .group_by(models.Compilation.status)
        )
    ).all()
    counts = {str(status or "unknown"): int(count or 0) for status, count in status_rows}
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    total = sum(counts.values())
    durations = (
        await db.execute(
            select(models.Compilation.compilation_time)
            .where(
                models.Compilation.created_at >= since,
                models.Compilation.status == "completed",
                models.Compilation.compilation_time.is_not(None),
            )
            .order_by(models.Compilation.created_at.desc())
            .limit(500)
        )
    ).scalars().all()
    values = sorted(float(value) for value in durations if value is not None and float(value) >= 0)
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))] if values else None
    return {
        "completed_24h": completed,
        "failed_24h": failed,
        "failure_rate": round((failed / total) * 100, 1) if total else 0.0,
        "p95_seconds": round(p95, 2) if p95 is not None else None,
        "sample_size": total,
    }


async def get_health(db: AsyncSession, *, use_cache: bool = True) -> dict[str, Any]:
    """Compose dependency, queue, billing and compile health for admins."""
    global _health_cache
    now_mono = time.monotonic()
    if use_cache and _health_cache is not None and now_mono < _health_cache[0]:
        return _health_cache[1]

    now = datetime.now(timezone.utc)
    observed = now.isoformat()
    sections: dict[str, dict[str, Any]] = {}

    for key, probe in (
        ("database", lambda: _probe_database(db)),
        ("redis", _probe_redis),
        ("redis_cache", _probe_redis_cache),
        ("storage", _probe_storage),
    ):
        try:
            status, detail = await probe()
        except Exception:
            status, detail = "unhealthy", f"{key} probe failed"
        sections[key] = _section(status, observed, detail)

    try:
        capacity_status, capacity_detail, capacity_metrics = await _probe_capacity()
    except Exception:
        capacity_status, capacity_detail, capacity_metrics = (
            "unhealthy",
            "Redis capacity probe failed",
            {},
        )
    sections["capacity"] = _section(
        capacity_status, observed, capacity_detail, **capacity_metrics
    )

    try:
        billing = await _billing_metrics(db, now)
        billing_observed = billing.pop("observed_at")
        billing_status = (
            "degraded"
            if any(billing[key] for key in ("failed_webhooks", "failed_payments", "past_due_subscriptions"))
            else "healthy"
        )
        sections["billing"] = _section(billing_status, billing_observed, **billing)
    except Exception:
        await _safe_rollback(db)
        sections["billing"] = _section("unhealthy", observed, "Billing counters could not be checked")

    try:
        jobs = await _job_metrics(db, now)
        stuck = jobs["stuck"]
        jobs_status = "unhealthy" if stuck >= 5 else ("degraded" if stuck else "healthy")
        sections["job_queue"] = _section(jobs_status, observed, **jobs)
    except Exception:
        await _safe_rollback(db)
        sections["job_queue"] = _section("unhealthy", observed, "Job queue metrics could not be checked")

    try:
        compilations = await _compilation_metrics(db, now)
        failure_rate = compilations["failure_rate"]
        p95 = compilations["p95_seconds"]
        if failure_rate >= 50 or (p95 is not None and p95 >= 60):
            compile_status = "unhealthy"
        elif failure_rate >= 25 or (p95 is not None and p95 >= 30):
            compile_status = "degraded"
        else:
            compile_status = "healthy"
        sections["compilations"] = _section(compile_status, observed, **compilations)
    except Exception:
        await _safe_rollback(db)
        sections["compilations"] = _section("unhealthy", observed, "Compile metrics could not be checked")

    payload = {
        "generated_at": observed,
        "status": _worst([section["status"] for section in sections.values()]),
        "sections": sections,
    }
    _health_cache = (now_mono + HEALTH_CACHE_SECONDS, payload)
    return payload

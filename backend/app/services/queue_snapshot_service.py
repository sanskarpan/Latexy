"""Durable Celery queue snapshots and the admin-facing metrics derived from them.

The Celery Beat sampler (:func:`app.core.celery_app.sample_queue_depths`) writes
one row per queue per tick. This module owns the durable read/write path, the
bounded retention window, and the pure helpers used to derive oldest-message age
and enqueue/completion throughput. Every value here is aggregate operational
metadata — never job payloads, task bodies or Redis credentials.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database import models

logger = get_logger(__name__)

# Bounded retention: the sampler prunes rows older than this window so the table
# cannot grow without bound even if the beat schedule or sampler is left running.
RETENTION_HOURS = 24
# Bounded throughput series returned to the admin UI (one point per tick).
SERIES_LIMIT = 180

# Stale/backlogged thresholds shared by the admin endpoint and the alert rule.
BACKLOG_DEPTH_THRESHOLD = 100
STALE_AGE_THRESHOLD_SECONDS = 600  # 10 minutes


def compute_oldest_age(
    stored: dict[str, Any] | None,
    current_id: str | None,
    now: float,
) -> tuple[dict[str, Any] | None, int | None]:
    """Track the age of the queue's oldest pending message.

    ``stored`` is the previous ``{"id", "first_seen"}`` marker for this queue
    (or ``None``). ``current_id`` is the message id at the tail of the queue
    (or ``None`` when the queue is empty). Returns ``(new_stored, age_seconds)``.

    The age is the wall-clock time since this process first observed the current
    oldest message sitting at the tail, which tracks the true enqueue age within
    one sampling interval while the queue stays FIFO.
    """
    if current_id is None:
        return None, None
    if not isinstance(stored, dict) or stored.get("id") != current_id:
        new_stored = {"id": current_id, "first_seen": now}
        return new_stored, 0
    try:
        first_seen = float(stored.get("first_seen", now))
    except (TypeError, ValueError):
        first_seen = now
    return {"id": current_id, "first_seen": first_seen}, max(0, int(now - first_seen))


def rate_per_minute(
    prev_total: int,
    curr_total: int,
    prev_ts: datetime,
    curr_ts: datetime,
) -> float | None:
    """Per-minute throughput between two consecutive cumulative totals."""
    dt = (curr_ts - prev_ts).total_seconds()
    if dt <= 0:
        return None
    delta = max(0, int(curr_total) - int(prev_total))
    return round(delta * 60.0 / dt, 2)


def _normalize_ts(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def compute_series_rates(
    rows: list[models.CeleryQueueSnapshot],
) -> list[dict[str, Any]]:
    """Return a bounded ascending series of enqueue/completion rates per tick."""
    series: list[dict[str, Any]] = []
    for prev, curr in zip(rows, rows[1:]):
        prev_ts = _normalize_ts(prev.sampled_at)
        curr_ts = _normalize_ts(curr.sampled_at)
        series.append(
            {
                "sampled_at": curr_ts.isoformat(),
                "depth": curr.depth,
                "oldest_age_seconds": curr.oldest_age_seconds,
                "enqueue_rate_per_minute": rate_per_minute(
                    prev.enqueued_total, curr.enqueued_total, prev_ts, curr_ts
                ),
                "completion_rate_per_minute": rate_per_minute(
                    prev.completed_total, curr.completed_total, prev_ts, curr_ts
                ),
            }
        )
    return series


def queue_status(depth: int, oldest_age_seconds: int | None) -> str:
    """Classify a queue as healthy, backlogged or stale from its latest sample."""
    if depth >= BACKLOG_DEPTH_THRESHOLD:
        return "backlogged"
    if oldest_age_seconds is not None and oldest_age_seconds >= STALE_AGE_THRESHOLD_SECONDS:
        return "stale"
    return "healthy"


async def persist_snapshots(
    db: AsyncSession,
    rows: list[dict[str, Any]],
) -> int:
    """Insert sampled queue snapshots; returns the number of rows written."""
    for row in rows:
        db.add(models.CeleryQueueSnapshot(**row))
    await db.commit()
    return len(rows)


async def purge_snapshots(db: AsyncSession, *, older_than_hours: int = RETENTION_HOURS) -> int:
    """Delete snapshots older than the retention window; returns rows removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    result = await db.execute(
        delete(models.CeleryQueueSnapshot).where(
            models.CeleryQueueSnapshot.sampled_at < cutoff
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def latest_snapshot_map(db: AsyncSession) -> dict[str, models.CeleryQueueSnapshot]:
    """Latest snapshot per queue (keyed by queue name)."""
    latest_ts = (
        select(
            models.CeleryQueueSnapshot.queue,
            func.max(models.CeleryQueueSnapshot.sampled_at).label("max_ts"),
        )
        .group_by(models.CeleryQueueSnapshot.queue)
        .subquery()
    )
    rows = (
        await db.execute(
            select(models.CeleryQueueSnapshot).join(
                latest_ts,
                (models.CeleryQueueSnapshot.queue == latest_ts.c.queue)
                & (models.CeleryQueueSnapshot.sampled_at == latest_ts.c.max_ts),
            )
        )
    ).scalars().all()
    return {row.queue: row for row in rows}


async def latest_depths(db: AsyncSession) -> dict[str, int]:
    """Latest sampled depth per queue (used by /jobs/health)."""
    return {queue: row.depth for queue, row in (await latest_snapshot_map(db)).items()}


async def _recent_series(
    db: AsyncSession, queue: str, limit: int
) -> list[models.CeleryQueueSnapshot]:
    rows = (
        await db.execute(
            select(models.CeleryQueueSnapshot)
            .where(models.CeleryQueueSnapshot.queue == queue)
            .order_by(models.CeleryQueueSnapshot.sampled_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


async def get_queue_metrics(db: AsyncSession) -> dict[str, Any]:
    """Compose the admin queues payload: latest depth/age plus a throughput series."""
    latest_map = await latest_snapshot_map(db)
    queues: list[dict[str, Any]] = []
    throughput: dict[str, list[dict[str, Any]]] = {}

    for queue in sorted(latest_map):
        latest = latest_map[queue]
        # Re-fetch the last two samples so the latest enqueue/completion rates
        # are derived from real consecutive totals rather than a single point.
        recent = await _recent_series(db, queue, SERIES_LIMIT)
        series = compute_series_rates(recent)
        throughput[queue] = series[-SERIES_LIMIT:]

        latest_rate = series[-1] if series else None
        queues.append(
            {
                "queue": queue,
                "depth": latest.depth,
                "oldest_age_seconds": latest.oldest_age_seconds,
                "enqueue_rate_per_minute": (
                    latest_rate["enqueue_rate_per_minute"] if latest_rate else None
                ),
                "completion_rate_per_minute": (
                    latest_rate["completion_rate_per_minute"] if latest_rate else None
                ),
                "sampled_at": _normalize_ts(latest.sampled_at).isoformat(),
                "status": queue_status(latest.depth, latest.oldest_age_seconds),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queues": queues,
        "throughput": throughput,
    }

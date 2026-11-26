"""Admin-only render artifact lifecycle visibility and guarded cleanup.

The report is aggregate-only: it never reads object bytes and never returns
user ids, emails, document text or provider payloads. Object keys are opaque
content-addressed paths; only their size and age cross the API boundary.

Cleanup is deliberately stricter than the scheduled retention sweep. A
candidate is deleted only when every one of these holds under the same
per-object advisory lock used by manifest registration:

* the storage bucket is bound to this database;
* the object is older than the orphan grace period;
* no render manifest references it (even an expired or unaccepted one);
* no compilation row references it (accepted or not);
* no account owning a reference is under an active GDPR legal hold.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.logging import get_logger
from ..database.models import (
    Compilation,
    GdprLegalHold,
    JobFinalization,
    RenderArtifactManifest,
    UsageAnalytics,
)
from . import storage_service
from .render_engine import retention

logger = get_logger(__name__)

PREFIX = retention.PREFIX
DATABASE_MARKER = retention.DATABASE_MARKER
ORPHAN_GRACE_SECONDS = retention.ORPHAN_GRACE_SECONDS
SWEEP_TELEMETRY_ACTION = retention.SWEEP_TELEMETRY_ACTION
MANUAL_CLEANUP_TELEMETRY_ACTION = retention.MANUAL_CLEANUP_TELEMETRY_ACTION
REPORT_MAX_PAGES = 5
REPORT_PAGE_SIZE = 512
ORPHAN_KEY_SAMPLE = 50
MIN_COHORT_SIZE = 5

MANIFEST_STATES = ("active", "expiring_24h", "expiring_7d", "expired")
MANIFEST_AGE_BUCKETS = ("under_1d", "1_to_7d", "7_to_30d", "over_30d")
OBJECT_STATES = (
    "referenced",
    "unaccepted_reference",
    "legal_hold",
    "recent",
    "orphan_candidate",
    "database_marker",
)


class ArtifactCleanupRefused(RuntimeError):
    """A safety guard rejected the cleanup before any object was touched."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    normalized = _utc(value)
    return normalized.isoformat() if normalized else None


def _empty_bucket() -> dict[str, Any]:
    return {"count": 0, "bytes": 0}


def _add(bucket: dict[str, Any], *, size: int) -> None:
    bucket["count"] += 1
    bucket["bytes"] += size


def _presence(count: int, byte_count: int) -> dict[str, int]:
    return {"count": int(count or 0), "bytes": int(byte_count or 0)}


def _manifest_state_expression(now: datetime):
    expires_at = RenderArtifactManifest.expires_at
    return case(
        (expires_at <= now, "expired"),
        (expires_at <= now + timedelta(hours=24), "expiring_24h"),
        (expires_at <= now + timedelta(days=7), "expiring_7d"),
        else_="active",
    )


def _manifest_age_expression(now: datetime):
    created_at = RenderArtifactManifest.created_at
    return case(
        (created_at >= now - timedelta(days=1), "under_1d"),
        (created_at >= now - timedelta(days=7), "1_to_7d"),
        (created_at >= now - timedelta(days=30), "7_to_30d"),
        else_="over_30d",
    )


def _object_age_bucket(age_seconds: int) -> str:
    if age_seconds < 3600:
        return "under_1h"
    if age_seconds < 86400:
        return "1h_to_1d"
    if age_seconds < 7 * 86400:
        return "1d_to_7d"
    return "over_7d"


def _window_sums(now: datetime):
    size = retention.manifest_size_expression()
    created_at = RenderArtifactManifest.created_at

    def _sum(condition):
        return func.coalesce(func.sum(case((condition, size), else_=0)), 0)

    def _count(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    return (
        _sum(created_at >= now - timedelta(hours=24)).label("bytes_24h"),
        _count(created_at >= now - timedelta(hours=24)).label("count_24h"),
        _sum(created_at >= now - timedelta(days=7)).label("bytes_7d"),
        _count(created_at >= now - timedelta(days=7)).label("count_7d"),
        _sum(created_at >= now - timedelta(days=30)).label("bytes_30d"),
        _count(created_at >= now - timedelta(days=30)).label("count_30d"),
    )


async def _manifest_report(db: AsyncSession, now: datetime) -> dict[str, Any]:
    size = retention.manifest_size_expression()
    total_count, total_bytes = (
        await db.execute(
            select(
                func.count(RenderArtifactManifest.artifact_id),
                func.coalesce(func.sum(size), 0),
            )
        )
    ).one()

    state_expr = _manifest_state_expression(now)
    state_rows = (
        await db.execute(
            select(state_expr, func.count(RenderArtifactManifest.artifact_id), func.coalesce(func.sum(size), 0))
            .group_by(state_expr)
        )
    ).all()
    states = {key: _empty_bucket() for key in MANIFEST_STATES}
    for state, count, byte_count in state_rows:
        bucket = states.setdefault(str(state), _empty_bucket())
        bucket["count"] = int(count or 0)
        bucket["bytes"] = int(byte_count or 0)

    age_expr = _manifest_age_expression(now)
    age_rows = (
        await db.execute(
            select(age_expr, func.count(RenderArtifactManifest.artifact_id), func.coalesce(func.sum(size), 0))
            .group_by(age_expr)
        )
    ).all()
    ages = {key: _empty_bucket() for key in MANIFEST_AGE_BUCKETS}
    for bucket_key, count, byte_count in age_rows:
        bucket = ages.setdefault(str(bucket_key), _empty_bucket())
        bucket["count"] = int(count or 0)
        bucket["bytes"] = int(byte_count or 0)

    live_finalizations = int(
        (
            await db.execute(
                select(func.count(RenderArtifactManifest.artifact_id))
                .select_from(RenderArtifactManifest)
                .join(JobFinalization, JobFinalization.job_id == RenderArtifactManifest.job_id)
                .where(
                    RenderArtifactManifest.expires_at > now,
                    JobFinalization.expires_at > now,
                    JobFinalization.cancel_requested.is_(False),
                    JobFinalization.state.in_(("pending", "committing", "completed")),
                )
            )
        ).scalar_one()
        or 0
    )
    accepted_paths = int(
        (
            await db.execute(
                select(func.count(func.distinct(Compilation.pdf_path))).where(
                    Compilation.pdf_path.startswith(PREFIX, autoescape=True),
                    Compilation.artifact_accepted.is_(True),
                )
            )
        ).scalar_one()
        or 0
    )
    unaccepted_paths = int(
        (
            await db.execute(
                select(func.count(func.distinct(Compilation.pdf_path))).where(
                    Compilation.pdf_path.startswith(PREFIX, autoescape=True),
                    Compilation.artifact_accepted.is_(False),
                )
            )
        ).scalar_one()
        or 0
    )
    held_manifests = int(
        (
            await db.execute(
                select(func.count(RenderArtifactManifest.artifact_id))
                .select_from(RenderArtifactManifest)
                .join(JobFinalization, JobFinalization.job_id == RenderArtifactManifest.job_id)
                .join(GdprLegalHold, GdprLegalHold.user_id == JobFinalization.user_id)
                .where(GdprLegalHold.active.is_(True))
            )
        ).scalar_one()
        or 0
    )
    held_compilations = int(
        (
            await db.execute(
                select(func.count(func.distinct(Compilation.pdf_path)))
                .select_from(Compilation)
                .join(GdprLegalHold, GdprLegalHold.user_id == Compilation.user_id)
                .where(
                    Compilation.pdf_path.startswith(PREFIX, autoescape=True),
                    GdprLegalHold.active.is_(True),
                )
            )
        ).scalar_one()
        or 0
    )

    oldest = (await db.execute(select(func.min(RenderArtifactManifest.created_at)))).scalar_one()
    newest = (await db.execute(select(func.max(RenderArtifactManifest.created_at)))).scalar_one()
    windows = (await db.execute(select(*_window_sums(now)))).one()

    return {
        "total": _presence(total_count, total_bytes),
        "states": states,
        "age_buckets": ages,
        "references": {
            "live_finalizations": live_finalizations,
            "accepted_canonical_paths": accepted_paths,
            "unaccepted_canonical_paths": unaccepted_paths,
            "legal_hold_manifests": held_manifests,
            "legal_hold_compilations": held_compilations,
        },
        "oldest_created_at": _iso(oldest),
        "newest_created_at": _iso(newest),
        "growth": {
            "basis": "registered_manifest_bytes",
            "added_24h": {"count": int(windows.count_24h or 0), "bytes": int(windows.bytes_24h or 0)},
            "added_7d": {"count": int(windows.count_7d or 0), "bytes": int(windows.bytes_7d or 0)},
            "added_30d": {"count": int(windows.count_30d or 0), "bytes": int(windows.bytes_30d or 0)},
        },
    }


async def _classified_page(
    db: AsyncSession, objects: list[dict[str, Any]], *, now: datetime
) -> dict[str, Any]:
    """Classify one storage page without reading any object contents."""
    keys = [str(item.get("key")) for item in objects if item.get("key")]
    key_set = set(keys)
    manifest_refs: set[str] = set()
    accepted_refs: set[str] = set()
    unaccepted_refs: set[str] = set()
    held_refs: set[str] = set()

    if keys:
        manifest_rows = (
            await db.execute(
                select(
                    RenderArtifactManifest.manifest_key,
                    RenderArtifactManifest.pdf_key,
                    RenderArtifactManifest.synctex_key,
                    RenderArtifactManifest.geometry_key,
                    RenderArtifactManifest.job_id,
                ).where(
                    or_(
                        RenderArtifactManifest.manifest_key.in_(keys),
                        RenderArtifactManifest.pdf_key.in_(keys),
                        RenderArtifactManifest.synctex_key.in_(keys),
                        RenderArtifactManifest.geometry_key.in_(keys),
                    )
                )
            )
        ).all()
        job_ids = {str(row.job_id) for row in manifest_rows}
        for row in manifest_rows:
            for column in (row.manifest_key, row.pdf_key, row.synctex_key, row.geometry_key):
                if column in key_set:
                    manifest_refs.add(column)
        if job_ids:
            held_jobs = set(
                (
                    await db.execute(
                        select(JobFinalization.job_id)
                        .join(GdprLegalHold, GdprLegalHold.user_id == JobFinalization.user_id)
                        .where(JobFinalization.job_id.in_(job_ids), GdprLegalHold.active.is_(True))
                    )
                ).scalars().all()
            )
            held_refs |= {
                column
                for row in manifest_rows
                if str(row.job_id) in held_jobs
                for column in (row.manifest_key, row.pdf_key, row.synctex_key, row.geometry_key)
                if column in key_set
            }

        compilation_rows = (
            await db.execute(
                select(Compilation.pdf_path, Compilation.user_id, Compilation.artifact_accepted).where(
                    Compilation.pdf_path.in_(keys)
                )
            )
        ).all()
        compilation_user_ids = {str(row.user_id) for row in compilation_rows if row.user_id}
        held_users = set()
        if compilation_user_ids:
            held_users = set(
                (
                    await db.execute(
                        select(GdprLegalHold.user_id).where(
                            GdprLegalHold.user_id.in_(compilation_user_ids),
                            GdprLegalHold.active.is_(True),
                        )
                    )
                ).scalars().all()
            )
        for row in compilation_rows:
            path = row.pdf_path
            if not path or path not in key_set:
                continue
            if row.artifact_accepted:
                accepted_refs.add(path)
            else:
                unaccepted_refs.add(path)
            if row.user_id and str(row.user_id) in held_users:
                held_refs.add(path)

    counts = {key: {"count": 0, "bytes": 0} for key in OBJECT_STATES}
    age_buckets: dict[str, dict[str, int]] = {}
    candidates: list[dict[str, Any]] = []
    refusals = {"referenced": 0, "unaccepted_reference": 0, "legal_hold": 0, "recent": 0, "database_marker": 0}
    cutoff = now - timedelta(seconds=ORPHAN_GRACE_SECONDS)

    for item in objects:
        key = item.get("key")
        if not key:
            continue
        key = str(key)
        size = int(item.get("size") or 0)
        modified = _utc(item.get("last_modified"))
        age_seconds = max(0, int((now - modified).total_seconds())) if modified else None
        if key == DATABASE_MARKER:
            state = "database_marker"
        elif key in held_refs:
            state = "legal_hold"
        elif key in unaccepted_refs:
            state = "unaccepted_reference"
        elif key in manifest_refs or key in accepted_refs:
            state = "referenced"
        elif modified is None or modified > cutoff:
            state = "recent"
        else:
            state = "orphan_candidate"

        _add(counts[state], size=size)
        bucket_key = _object_age_bucket(age_seconds if age_seconds is not None else 0)
        bucket = age_buckets.setdefault(bucket_key, {"count": 0, "bytes": 0})
        _add(bucket, size=size)
        if state in refusals:
            refusals[state] += 1
        if state == "orphan_candidate":
            candidates.append(
                {
                    "key": key,
                    "bytes": size,
                    "last_modified": _iso(modified),
                    "age_seconds": age_seconds,
                }
            )

    return {
        "counts": counts,
        "age_buckets": age_buckets,
        "candidates": candidates,
        "refusals": refusals,
    }


async def _database_bound() -> bool:
    try:
        return bool(
            await asyncio.wait_for(
                asyncio.to_thread(retention.storage_database_bound), timeout=3
            )
        )
    except Exception:
        return False


def _empty_storage(reason: str) -> dict[str, Any]:
    return {
        "status": "refused",
        "prefix": PREFIX,
        "complete": False,
        "pages_scanned": 0,
        "next_cursor": None,
        "scanned": {"count": 0, "bytes": 0},
        "states": {key: {"count": 0, "bytes": 0} for key in OBJECT_STATES},
        "age_buckets": {},
        "orphan_candidates": {"count": 0, "bytes": 0, "keys": []},
        "detail": reason,
    }


async def _storage_report(db: AsyncSession, now: datetime) -> dict[str, Any]:
    if not await _database_bound():
        return _empty_storage("Storage/database binding unavailable; orphan status is withheld.")

    scanned_count = 0
    scanned_bytes = 0
    pages = 0
    cursor: str | None = None
    complete = False
    totals = {key: {"count": 0, "bytes": 0} for key in OBJECT_STATES}
    ages: dict[str, dict[str, int]] = {}
    candidates: list[dict[str, Any]] = []
    try:
        while pages < REPORT_MAX_PAGES:
            objects, next_cursor = await asyncio.wait_for(
                asyncio.to_thread(
                    storage_service.list_object_page,
                    PREFIX,
                    cursor=cursor,
                    limit=REPORT_PAGE_SIZE,
                ),
                timeout=10,
            )
            pages += 1
            if not objects:
                complete = True
                break
            page = await _classified_page(db, objects, now=now)
            for key, bucket in page["counts"].items():
                totals[key]["count"] += bucket["count"]
                totals[key]["bytes"] += bucket["bytes"]
            for key, bucket in page["age_buckets"].items():
                target = ages.setdefault(key, {"count": 0, "bytes": 0})
                target["count"] += bucket["count"]
                target["bytes"] += bucket["bytes"]
            for item in objects:
                scanned_count += 1
                scanned_bytes += int(item.get("size") or 0)
            if len(candidates) < ORPHAN_KEY_SAMPLE:
                candidates.extend(page["candidates"][: ORPHAN_KEY_SAMPLE - len(candidates)])
            if not next_cursor:
                complete = True
                break
            cursor = next_cursor
    except Exception as exc:
        logger.warning(
            "Artifact lifecycle storage scan unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return _empty_storage("Object storage listing failed; orphan status is withheld.")

    orphan = totals["orphan_candidate"]
    return {
        "status": "ok",
        "prefix": PREFIX,
        "complete": complete,
        "pages_scanned": pages,
        "next_cursor": cursor if not complete else None,
        "scanned": {"count": scanned_count, "bytes": scanned_bytes},
        "states": totals,
        "age_buckets": ages,
        "orphan_candidates": {
            "count": orphan["count"],
            "bytes": orphan["bytes"],
            "keys": candidates,
        },
    }


def _safe_metadata(row: UsageAnalytics) -> dict[str, Any]:
    metadata = row.event_metadata if isinstance(row.event_metadata, dict) else {}
    allowed = {
        "scanned": int,
        "deleted": int,
        "protected": int,
        "failed": int,
        "not_found": int,
        "manifest_count": int,
        "manifest_bytes": int,
        "candidate_count": int,
        "candidate_bytes": int,
        "deleted_bytes": int,
        "duration_ms": int,
        "next_cursor_present": bool,
        "dry_run": bool,
        "skipped": str,
        "refused": int,
    }
    result: dict[str, Any] = {}
    for key, caster in allowed.items():
        value = metadata.get(key)
        if value is None:
            continue
        try:
            result[key] = caster(value)
        except (TypeError, ValueError):
            continue
    failed_keys = metadata.get("failed_keys")
    if isinstance(failed_keys, list):
        result["failed_keys"] = [str(item)[:500] for item in failed_keys[:20]]
    result["at"] = _iso(row.created_at)
    return result


async def _telemetry_rows(
    db: AsyncSession, action: str, *, limit: int = 20
) -> list[UsageAnalytics]:
    return list(
        (
            await db.execute(
                select(UsageAnalytics)
                .where(
                    UsageAnalytics.action == action,
                    UsageAnalytics.resource_type == "render_artifact_gc",
                    UsageAnalytics.user_id.is_(None),
                    UsageAnalytics.device_fingerprint.is_(None),
                )
                .order_by(UsageAnalytics.created_at.desc(), UsageAnalytics.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


def _failed_deletion_summary(sweeps: list[UsageAnalytics], manual: list[UsageAnalytics], now: datetime) -> dict[str, Any]:
    failed_events: list[dict[str, Any]] = []
    failed_keys: list[str] = []
    failed_total = 0
    for row in [*sweeps, *manual]:
        payload = _safe_metadata(row)
        count = int(payload.get("failed") or 0)
        if count <= 0:
            continue
        failed_total += count
        for key in payload.get("failed_keys", []):
            if key not in failed_keys and len(failed_keys) < ORPHAN_KEY_SAMPLE:
                failed_keys.append(key)
        failed_events.append(
            {
                "at": payload.get("at"),
                "failed": count,
                "action": row.action,
            }
        )
    recent: list[dict[str, Any]] = []
    for event in failed_events:
        if not event.get("at"):
            continue
        try:
            observed = datetime.fromisoformat(str(event["at"]))
        except ValueError:
            continue
        if observed >= now - timedelta(days=7):
            recent.append(event)
    return {
        "last_20_sweeps_failed": failed_total,
        "failed_last_7d": sum(int(event["failed"]) for event in recent),
        "failed_keys": failed_keys,
        "events": failed_events[:10],
    }


async def get_lifecycle_report(db: AsyncSession) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    manifests = await _manifest_report(db, now)
    storage = await _storage_report(db, now)
    sweeps = await _telemetry_rows(db, SWEEP_TELEMETRY_ACTION)
    manual = await _telemetry_rows(db, MANUAL_CLEANUP_TELEMETRY_ACTION)
    last_sweep = _safe_metadata(sweeps[0]) if sweeps else None
    last_manual = _safe_metadata(manual[0]) if manual else None
    growth = manifests.pop("growth")
    last_sweep_bytes = last_sweep.get("manifest_bytes") if last_sweep else None
    if last_sweep_bytes is not None:
        growth["last_sweep_manifest_bytes"] = last_sweep_bytes
        growth["change_since_last_sweep_bytes"] = manifests["total"]["bytes"] - int(last_sweep_bytes)
    else:
        growth["last_sweep_manifest_bytes"] = None
        growth["change_since_last_sweep_bytes"] = None
    growth["last_sweep_at"] = last_sweep.get("at") if last_sweep else None

    return {
        "generated_at": now.isoformat(),
        "aggregate_only": True,
        "minimum_cohort_size": MIN_COHORT_SIZE,
        "suppression": {
            "applied": False,
            "suppressed_groups": 0,
            "aggregate_only": True,
            "minimum_cohort_size": MIN_COHORT_SIZE,
            "detail": "Artifact lifecycle data is reported only as aggregate counts and bytes; "
            "no user, device, document or per-customer cohort is exposed.",
        },
        "grace_seconds": ORPHAN_GRACE_SECONDS,
        "manifests": manifests,
        "storage": storage,
        "growth": growth,
        "last_sweep": last_sweep,
        "last_manual_cleanup": last_manual,
        "failed_deletions": _failed_deletion_summary(sweeps, manual, now),
        "safety": {
            "protects_referenced": True,
            "protects_unaccepted": True,
            "protects_legal_hold": True,
            "reads_object_contents": False,
            "scheduled_sweep_telemetry": True,
        },
    }


async def _key_protection(db: AsyncSession, key: str) -> str | None:
    """Return a refusal reason for ``key`` under the caller's object lock."""
    manifest = (
        await db.execute(
            select(RenderArtifactManifest.artifact_id, RenderArtifactManifest.job_id)
            .where(
                or_(
                    RenderArtifactManifest.manifest_key == key,
                    RenderArtifactManifest.pdf_key == key,
                    RenderArtifactManifest.synctex_key == key,
                    RenderArtifactManifest.geometry_key == key,
                )
            )
            .limit(1)
        )
    ).one_or_none()
    if manifest is not None:
        held = await db.scalar(
            select(GdprLegalHold.id)
            .select_from(JobFinalization)
            .join(GdprLegalHold, GdprLegalHold.user_id == JobFinalization.user_id)
            .where(
                JobFinalization.job_id == manifest.job_id,
                GdprLegalHold.active.is_(True),
            )
            .limit(1)
        )
        return "legal_hold" if held else "referenced"

    compilation = (
        await db.execute(
            select(Compilation.artifact_accepted, Compilation.user_id)
            .where(Compilation.pdf_path == key)
            .limit(1)
        )
    ).one_or_none()
    if compilation is not None:
        if compilation.user_id:
            held = await db.scalar(
                select(GdprLegalHold.id)
                .where(
                    GdprLegalHold.user_id == compilation.user_id,
                    GdprLegalHold.active.is_(True),
                )
                .limit(1)
            )
            if held:
                return "legal_hold"
        return "referenced" if compilation.artifact_accepted else "unaccepted_reference"
    return None


def _cleanup_summary() -> dict[str, Any]:
    return {
        "candidates": {"count": 0, "bytes": 0},
        "deleted": {"count": 0, "bytes": 0},
        "failed": {"count": 0, "bytes": 0, "keys": []},
        "protected": {key: {"count": 0, "bytes": 0} for key in OBJECT_STATES if key != "orphan_candidate"},
    }


async def run_cleanup(
    db: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    dry_run: bool,
    min_age_hours: int,
) -> dict[str, Any]:
    """Scan and (when not a dry run) delete one bounded page of orphans."""
    now = datetime.now(timezone.utc)
    if not await _database_bound():
        raise ArtifactCleanupRefused(
            "storage_database_binding_unavailable",
            "Cleanup refused: the storage bucket is not bound to this database.",
            status_code=409,
        )
    try:
        objects, next_cursor = await asyncio.wait_for(
            asyncio.to_thread(
                storage_service.list_object_page, PREFIX, cursor=cursor, limit=limit
            ),
            timeout=10,
        )
    except Exception as exc:
        logger.warning(
            "Artifact cleanup listing failed",
            extra={"error_type": type(exc).__name__},
        )
        raise ArtifactCleanupRefused(
            "storage_listing_unavailable",
            "Cleanup refused: object storage listing is unavailable.",
            status_code=503,
        ) from exc

    page = await _classified_page(db, objects, now=now)
    result = _cleanup_summary()
    result.update(
        {
            "dry_run": dry_run,
            "generated_at": now.isoformat(),
            "scanned": {"count": len(objects), "bytes": sum(int(item.get("size") or 0) for item in objects)},
            "next_cursor": next_cursor,
            "grace_seconds": ORPHAN_GRACE_SECONDS,
            "min_age_hours": max(1, min_age_hours),
            "safety": {
                "protects_referenced": True,
                "protects_unaccepted": True,
                "protects_legal_hold": True,
                "reads_object_contents": False,
                "database_bound": True,
            },
        }
    )
    for state, bucket in page["counts"].items():
        if state in result["protected"]:
            result["protected"][state] = dict(bucket)

    candidates = [
        item
        for item in page["candidates"]
        if item.get("age_seconds") is None or item["age_seconds"] >= max(1, min_age_hours) * 3600
    ]
    result["candidates"] = {
        "count": len(candidates),
        "bytes": sum(int(item["bytes"]) for item in candidates),
        "keys": candidates if dry_run else candidates[:ORPHAN_KEY_SAMPLE],
    }
    if dry_run:
        result["would_delete"] = {
            "count": len(candidates),
            "bytes": sum(int(item["bytes"]) for item in candidates),
        }
        return result

    started = time.monotonic()
    await db.execute(text("SET LOCAL lock_timeout = '5s'"))
    for item in candidates:
        key = item["key"]
        size = int(item["bytes"])
        await retention.lock_object(db, key)
        reason = await _key_protection(db, key)
        if reason is not None:
            bucket = result["protected"].setdefault(reason, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += size
            continue
        try:
            removed = storage_service.delete_object(key)
        except Exception:
            removed = False
        if removed:
            result["deleted"]["count"] += 1
            result["deleted"]["bytes"] += size
        else:
            result["failed"]["count"] += 1
            result["failed"]["bytes"] += size
            if len(result["failed"]["keys"]) < ORPHAN_KEY_SAMPLE:
                result["failed"]["keys"].append(key)

    result["would_delete"] = {
        "count": result["deleted"]["count"],
        "bytes": result["deleted"]["bytes"],
    }
    result["duration_ms"] = max(0, int((time.monotonic() - started) * 1000))
    db.add(
        UsageAnalytics(
            id=str(uuid4()),
            action=MANUAL_CLEANUP_TELEMETRY_ACTION,
            resource_type="render_artifact_gc",
            event_metadata={
                "scanned": result["scanned"]["count"],
                "deleted": result["deleted"]["count"],
                "deleted_bytes": result["deleted"]["bytes"],
                "failed": result["failed"]["count"],
                "failed_keys": result["failed"]["keys"],
                "protected": sum(bucket["count"] for bucket in result["protected"].values()),
                "candidate_count": result["candidates"]["count"],
                "candidate_bytes": result["candidates"]["bytes"],
                "next_cursor_present": bool(next_cursor),
                "duration_ms": result["duration_ms"],
                "dry_run": False,
            },
        )
    )
    return result

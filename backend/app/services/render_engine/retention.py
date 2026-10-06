"""Durable reference-aware artifact retention with bounded S3 sweep work."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ...core.config import settings
from ...database.models import Compilation, JobFinalization, RenderArtifactManifest
from ...utils.db_url import database_identity, normalize_database_url
from .. import storage_service
from .artifacts import RenderManifest, canonical_json, manifest_key, sha256

PREFIX = "render-artifacts/v1/"
ORPHAN_GRACE_SECONDS = 3600
DATABASE_MARKER = PREFIX + "database-binding.json"


def _binding() -> bytes:
    return canonical_json({"schema_version": 1,
        "database_sha256": sha256(database_identity(normalize_database_url(settings.DATABASE_URL)))})


def ensure_storage_database() -> None:
    # An immutable bucket/database binding prevents an accidentally pointed
    # cleanup worker from declaring another database's PDFs to be orphans.
    storage_service.upload_immutable_bytes(DATABASE_MARKER, _binding(), "application/json")


def storage_database_bound() -> bool:
    try:
        return storage_service.download_bytes(DATABASE_MARKER, max_bytes=1024) == _binding()
    except Exception:
        return False


def _factory():
    engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _lock(session: Any, key: str) -> None:
    value = int(sha256(key)[:16], 16)
    if value >= 2 ** 63:
        value -= 2 ** 64
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": value})


async def register_manifest(manifest: RenderManifest, factory=None) -> bool:
    engine = None
    if factory is None:
        engine, factory = _factory()
    try:
        async with factory() as session:
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            authority = await session.scalar(select(JobFinalization).where(
                JobFinalization.job_id == manifest.job_id).with_for_update())
            now = await session.scalar(select(func.clock_timestamp()))
            if (not authority or authority.cancel_requested or authority.state not in {"pending", "committing"}
                    or authority.owner_epoch != manifest.owner_epoch
                    or sha256(authority.owner_token or "") != manifest.owner_token_sha256
                    or not authority.lease_expires_at or authority.lease_expires_at <= now
                    or authority.expires_at <= now
                    or manifest.owner_scope_kind != ("user" if authority.user_id else "device")
                    or (authority.user_id and manifest.owner_scope_sha256 != sha256(f"user:{authority.user_id}"))):
                return False
            key = manifest_key(manifest.owner_scope_sha256, manifest.artifact_id)
            references = [manifest.pdf, manifest.synctex, manifest.geometry]
            for object_key in sorted([key] + [ref.key for ref in references if ref]):
                await _lock(session, object_key)
            # GC may have removed an old unreferenced binary after cache lookup
            # but before registration. Holding the same per-object advisory lock
            # ensures that this check and reference commit precede deletion.
            for ref in references:
                if ref and storage_service.head_size(ref.key) != ref.size:
                    return False
            if storage_service.head_size(key) != len(canonical_json(manifest.model_dump())):
                return False
            ensure_storage_database()
            values = {"artifact_id": manifest.artifact_id, "job_id": manifest.job_id,
                "owner_epoch": manifest.owner_epoch, "owner_token_sha256": manifest.owner_token_sha256,
                "owner_scope_kind": manifest.owner_scope_kind, "manifest_key": key,
                "pdf_key": manifest.pdf.key, "synctex_key": manifest.synctex.key if manifest.synctex else None,
                "geometry_key": manifest.geometry.key if manifest.geometry else None,
                "payload": manifest.model_dump(), "created_at": datetime.fromtimestamp(manifest.created_at, timezone.utc),
                "expires_at": min(authority.expires_at, datetime.fromtimestamp(manifest.expires_at, timezone.utc))}
            await session.execute(insert(RenderArtifactManifest).values(**values).on_conflict_do_nothing(index_elements=["artifact_id"]))
            await session.commit()
            return True
    finally:
        if engine:
            await engine.dispose()


async def sweep_artifacts(*, cursor: str | None = None, limit: int = 512, factory=None) -> dict[str, Any]:
    """Delete only old objects with no live admitted manifest references.

    A sweep reads one page and at most512 rows/objects. Callers retain the opaque
    S3 cursor across runs, so large buckets are inspected without an unbounded
    catalog or interpreting missing references from a partial prefix listing.
    """
    engine = None
    if factory is None:
        engine, factory = _factory()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ORPHAN_GRACE_SECONDS)
    scanned = deleted = protected = 0
    deadline = time.monotonic() + 20
    last_key = None
    try:
        if not storage_database_bound():
            return {"scanned": 0, "deleted": 0, "protected": 0, "next_cursor": cursor,
                    "skipped": "storage_database_binding_unavailable"}
        objects, next_cursor = storage_service.list_object_page(PREFIX, cursor=cursor, limit=min(512, max(1, limit)))
        for item in objects:
            if time.monotonic() >= deadline:
                next_cursor = "after:" + last_key if last_key else cursor
                break
            scanned += 1
            last_key = item["key"]
            if not item.get("last_modified") or item["last_modified"] > cutoff:
                protected += 1
                continue
            key = item["key"]
            if key == DATABASE_MARKER:
                protected += 1
                continue
            async with factory() as session:
                await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                await _lock(session, key)
                references = await session.execute(select(RenderArtifactManifest.owner_token_sha256,
                    JobFinalization.owner_token, JobFinalization.state, JobFinalization.lease_expires_at).join(
                    JobFinalization, JobFinalization.job_id == RenderArtifactManifest.job_id).where(
                    or_(RenderArtifactManifest.manifest_key == key, RenderArtifactManifest.pdf_key == key,
                        RenderArtifactManifest.synctex_key == key, RenderArtifactManifest.geometry_key == key),
                    RenderArtifactManifest.expires_at > now,
                    JobFinalization.expires_at > now,
                    JobFinalization.cancel_requested.is_(False),
                    or_(JobFinalization.user_id.is_not(None), RenderArtifactManifest.owner_scope_kind == "device"),
                    RenderArtifactManifest.owner_epoch == JobFinalization.owner_epoch,
                    JobFinalization.state.in_(["pending", "committing", "completed"])).limit(513))
                candidates = references.all()
                live = len(candidates) >= 513 or any(token_hash == sha256(owner or "")
                    and (state == "completed" or (lease and lease > now))
                    for token_hash, owner, state, lease in candidates)
                # Saved resume/history/share pointers outlive job TTL. Keep
                # authenticated completed outputs, but never promote an
                # unaccepted semantic candidate or orphaned deleted account.
                canonical = await session.scalar(select(Compilation.id).where(
                    Compilation.pdf_path == key, Compilation.status == "completed",
                    Compilation.artifact_accepted.is_(True),
                    or_(Compilation.user_id.is_not(None), Compilation.resume_id.is_not(None)),
                ).limit(1))
                live = live or canonical is not None
                if live:
                    protected += 1
                else:
                    # Keep the advisory lock until deletion completes; a fresh
                    # registration waits, then validates existence before ready.
                    if storage_service.delete_object(key):
                        deleted += 1
                await session.commit()
        async with factory() as session:
            expired = select(RenderArtifactManifest.artifact_id).where(RenderArtifactManifest.expires_at <= now).limit(512)
            await session.execute(delete(RenderArtifactManifest).where(RenderArtifactManifest.artifact_id.in_(expired)))
            await session.commit()
        return {"scanned": scanned, "deleted": deleted, "protected": protected, "next_cursor": next_cursor}
    finally:
        if engine:
            await engine.dispose()

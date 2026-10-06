"""Authorized early previews and terminal exports of immutable render artifacts."""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.redis import get_redis_client
from ..database.connection import get_db
from ..database.models import Compilation, JobFinalization
from ..middleware.auth_middleware import get_current_user_optional
from ..services import storage_service
from ..services.render_engine.artifacts import (
    HASH_PATTERN,
    MAX_GEOMETRY_BYTES,
    MAX_MANIFEST_BYTES,
    RenderManifest,
    download_object,
    manifest_key,
    parse_manifest,
    sha256,
)
from ..services.resume_engine.acceptance import is_candidate_export_accepted
from ..utils.bounded_io import MAX_COMPILED_PDF_BYTES, MAX_SYNCTEX_COMPRESSED_BYTES, MAX_SYNCTEX_DECOMPRESSED_BYTES

router = APIRouter()
PDF_JOB_TYPES = {"latex_compilation", "auto_fit", "combined"}

# A single Redis read verifies the current capability, cancellation, lease and
# manifest pointer together. Completed DB records can survive cache expiry.
_READ_FENCE = """
if redis.call('EXISTS', KEYS[3]) == 1 then return 0 end
if redis.call('EXISTS', KEYS[1]) == 0 then return tonumber(ARGV[4]) end
if redis.call('HGET', KEYS[1], 'cancel_requested') == '1' then return 0 end
local status = redis.call('HGET', KEYS[1], 'status')
if status ~= 'running' and status ~= 'finalizing' and status ~= 'completed' then return 0 end
local owner = redis.call('HGET', KEYS[1], 'owner')
if status == 'completed' then
  if ARGV[4] ~= '1' then return 0 end
  -- Terminal publication removes the Redis owner. The refreshed durable row
  -- already verified its token hash; a retained conflicting token still fails.
  if owner and owner ~= ARGV[1] then return 0 end
elseif owner ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'epoch') ~= ARGV[2] then return 0 end
if ARGV[4] ~= '1' then
  local t = redis.call('TIME')
  if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= tonumber(t[1]) + tonumber(t[2])/1000000 then return 0 end
end
local raw = redis.call('GET', KEYS[2])
if not raw then return tonumber(ARGV[4]) end
local ok, value = pcall(cjson.decode, raw)
if not ok or value['artifact_id'] ~= ARGV[3] then return 0 end
return 1
"""


def _not_found() -> HTTPException:
    return HTTPException(404, "Render artifact is unavailable")


async def _durable_fence(db: AsyncSession, redis: Any, manifest: RenderManifest,
                         user_id: str | None, *, export: bool) -> JobFinalization:
    result = await db.execute(
        select(JobFinalization, (JobFinalization.lease_expires_at > func.clock_timestamp()).label("lease_live"),
               func.extract("epoch", func.clock_timestamp()).label("db_now"))
        .where(JobFinalization.job_id == manifest.job_id, JobFinalization.expires_at > func.clock_timestamp())
        .execution_options(populate_existing=True)
    )
    pair = result.first()
    if pair is None:
        raise _not_found()
    row, lease_live, db_now = pair
    if (row.user_id != user_id or row.job_type not in PDF_JOB_TYPES or row.cancel_requested
            or row.state not in {"pending", "committing", "completed"}
            or row.owner_epoch != manifest.owner_epoch or not row.owner_token
            or sha256(row.owner_token) != manifest.owner_token_sha256
            or manifest.expires_at <= db_now):
        raise _not_found()
    completed = row.state == "completed"
    if not completed and (export or not lease_live):
        raise HTTPException(409, "This PDF is a preview; export is available after completion")
    if completed:
        artifact = (row.result_payload or {}).get("artifact")
        if (not isinstance(artifact, dict) or artifact.get("artifact_id") != manifest.artifact_id
                or row.pdf_path != manifest.pdf.key or row.pdf_size != manifest.pdf.size
                or row.pdf_sha256 != manifest.pdf.sha256):
            raise _not_found()
        if user_id:
            compilation = (await db.execute(select(Compilation).where(
                Compilation.id == row.compilation_id, Compilation.job_id == row.job_id,
                Compilation.user_id == user_id, Compilation.status == "completed",
                Compilation.resume_id.is_not_distinct_from(row.resume_id),
                Compilation.pdf_path == row.pdf_path, Compilation.pdf_size == row.pdf_size,
            ).execution_options(populate_existing=True))).scalar_one_or_none()
            if compilation is None:
                raise _not_found()
            if export and compilation.artifact_accepted is not True:
                raise HTTPException(409, "Accept the reviewed changes before exporting this candidate")
        if export and manifest.branch == "candidate" and (not user_id or not await is_candidate_export_accepted(
            db, manifest.job_id, user_id, manifest.source_sha256,
        )):
            raise HTTPException(409, "Accept the reviewed changes before exporting this candidate")
    allowed = await redis.eval(
        _READ_FENCE, 3, f"latexy:job:{manifest.job_id}:lifecycle",
        f"latexy:job:{manifest.job_id}:artifact", f"latexy:job:{manifest.job_id}:cancel",
        row.owner_token, str(row.owner_epoch), manifest.artifact_id, "1" if completed else "0",
    )
    if allowed != 1:
        raise _not_found()
    return row


async def load_manifest(db: AsyncSession, redis: Any, job_id: str, user_id: str | None,
                        fingerprint: str | None, artifact_id: str | None = None) -> RenderManifest:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", job_id) or (artifact_id and not re.fullmatch(HASH_PATTERN, artifact_id)):
        raise _not_found()
    if not user_id:
        # Legacy anonymous job-ID capabilities never authorize this new API.
        raw_meta = await redis.get(f"latexy:job:{job_id}:meta")
        try:
            meta = json.loads(raw_meta) if raw_meta else None
            if (not isinstance(meta, dict) or "user_id" not in meta or meta["user_id"] is not None
                    or not fingerprint or len(fingerprint) > 512):
                raise _not_found()
        except (ValueError, TypeError):
            raise _not_found() from None
    scope = sha256(f"user:{user_id}" if user_id else f"device:{fingerprint}")
    raw = await redis.get(f"latexy:job:{job_id}:artifact")
    if raw is None:
        # Only completed authenticated jobs recover an expired compact pointer.
        if not user_id:
            raise _not_found()
        row = (await db.execute(select(JobFinalization).where(
            JobFinalization.job_id == job_id, JobFinalization.user_id == user_id,
            JobFinalization.state == "completed", JobFinalization.cancel_requested.is_(False),
            JobFinalization.expires_at > func.clock_timestamp(),
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        public = (row.result_payload or {}).get("artifact") if row else None
        recovered_id = public.get("artifact_id") if isinstance(public, dict) else None
        if not isinstance(recovered_id, str) or not re.fullmatch(HASH_PATTERN, recovered_id):
            raise _not_found()
        raw = await asyncio.to_thread(storage_service.download_bytes,
                                      manifest_key(scope, recovered_id), max_bytes=MAX_MANIFEST_BYTES)
        if raw is None:
            raise _not_found()
    try:
        manifest = parse_manifest(raw)
    except (TypeError, ValueError):
        raise _not_found() from None
    if (manifest.job_id != job_id or manifest.owner_scope_sha256 != scope
            or manifest.owner_scope_kind != ("user" if user_id else "device")
            or artifact_id and manifest.artifact_id != artifact_id):
        raise _not_found()
    return manifest


async def serve_artifact(db: AsyncSession, job_id: str, user_id: str | None,
                         fingerprint: str | None, *, artifact_id: str | None = None,
                         kind: str = "pdf", export: bool = False) -> Response:
    redis = await get_redis_client()
    manifest = await load_manifest(db, redis, job_id, user_id, fingerprint, artifact_id)
    await _durable_fence(db, redis, manifest, user_id, export=export)
    reference = getattr(manifest, kind)
    if reference is None:
        raise _not_found()
    limit = {"pdf": MAX_COMPILED_PDF_BYTES, "synctex": MAX_SYNCTEX_COMPRESSED_BYTES,
             "geometry": MAX_GEOMETRY_BYTES}[kind]
    try:
        data = await asyncio.to_thread(download_object, reference, limit)
        if kind == "pdf" and not data.startswith(b"%PDF-"):
            raise ValueError("invalid PDF")
        if kind == "synctex":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as source:
                data = source.read(MAX_SYNCTEX_DECOMPRESSED_BYTES + 1)
            if len(data) > MAX_SYNCTEX_DECOMPRESSED_BYTES:
                raise ValueError("SyncTeX exceeds limit")
        if kind == "geometry":
            value = json.loads(data)
            if (not isinstance(value, dict) or value.get("pdf_sha256") != manifest.pdf.sha256
                    or value.get("source_sha256") != manifest.source_sha256):
                raise ValueError("geometry identity mismatch")
            data = json.dumps({**value, "artifact_id": manifest.artifact_id}, separators=(",", ":")).encode()
    except (ValueError, OSError, EOFError, storage_service.StorageObjectTooLarge):
        raise _not_found() from None
    # Recheck DB cancellation/replacement and the atomic Redis capability after
    # storage I/O. A stale read cannot return bytes after losing its lease.
    await _durable_fence(db, redis, manifest, user_id, export=export)
    media = {"pdf": "application/pdf", "synctex": "text/plain", "geometry": "application/json"}[kind]
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if kind == "pdf":
        disposition = "attachment" if export else "inline"
        headers["Content-Disposition"] = f'{disposition}; filename="resume_{job_id[:8]}.pdf"'
    return Response(content=data, media_type=media, headers=headers)


@router.get("/download/{job_id}/preview/{artifact_id}")
async def preview_pdf(job_id: str, artifact_id: str, user_id: str | None = Depends(get_current_user_optional),
                      db: AsyncSession = Depends(get_db), fingerprint: str | None = Header(None, alias="X-Device-Fingerprint")):
    return await serve_artifact(db, job_id, user_id, fingerprint, artifact_id=artifact_id)


@router.get("/download/{job_id}/preview/{artifact_id}/geometry")
async def preview_geometry(job_id: str, artifact_id: str, user_id: str | None = Depends(get_current_user_optional),
                           db: AsyncSession = Depends(get_db), fingerprint: str | None = Header(None, alias="X-Device-Fingerprint")):
    return await serve_artifact(db, job_id, user_id, fingerprint, artifact_id=artifact_id, kind="geometry")


@router.get("/download/{job_id}/preview/{artifact_id}/synctex")
async def preview_synctex(job_id: str, artifact_id: str, user_id: str | None = Depends(get_current_user_optional),
                          db: AsyncSession = Depends(get_db), fingerprint: str | None = Header(None, alias="X-Device-Fingerprint")):
    return await serve_artifact(db, job_id, user_id, fingerprint, artifact_id=artifact_id, kind="synctex")

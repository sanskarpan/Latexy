"""Immutable, tenant-scoped render binaries and revision-bound preview manifests.

Redis holds bounded manifests, never PDF/SyncTeX bytes for admitted renders.
S3 stores content-addressed immutable bytes. Publication retains the existing
owner/epoch/cancellation Lua fence; this is preview readiness, not final success.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from billiard.exceptions import SoftTimeLimitExceeded
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ...core.engine_observability import engine_span
from ...utils.bounded_io import (
    MAX_COMPILED_PDF_BYTES,
    MAX_SYNCTEX_COMPRESSED_BYTES,
    MAX_SYNCTEX_DECOMPRESSED_BYTES,
    BoundedReadError,
    read_file_bounded,
    read_gzip_file_bounded,
)
from .. import storage_service

MANIFEST_TTL = 40 * 86400
MAX_MANIFEST_BYTES = 32 * 1024
MAX_GEOMETRY_BYTES = 2 * 1024 * 1024
RENDERER_EPOCH = os.environ.get("LATEXY_COMPILE_CACHE_EPOCH", "v2-manifest")
HASH_PATTERN = r"^[a-f0-9]{64}$"


def sha256(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(max_length=500)
    sha256: str = Field(pattern=HASH_PATTERN)
    size: StrictInt = Field(ge=1, le=MAX_COMPILED_PDF_BYTES)
    media_type: str = Field(max_length=80)


class RenderManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    artifact_id: str = Field(pattern=HASH_PATTERN)
    job_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")
    owner_scope_sha256: str = Field(pattern=HASH_PATTERN)
    owner_token_sha256: str = Field(pattern=HASH_PATTERN)
    owner_epoch: StrictInt = Field(ge=1)
    owner_scope_kind: Literal["user", "device"]
    created_at: StrictInt = Field(ge=1)
    expires_at: StrictInt = Field(ge=1)
    source_sha256: str = Field(pattern=HASH_PATTERN)
    render_source_sha256: str = Field(pattern=HASH_PATTERN)
    settings_sha256: str = Field(pattern=HASH_PATTERN)
    engine_fingerprint: str = Field(max_length=500)
    renderer_epoch: str = Field(max_length=100)
    compiler: Literal["pdflatex", "xelatex", "lualatex"]
    document_id: str | None = Field(default=None, max_length=255)
    content_revision: StrictInt | None = Field(default=None, ge=0)
    branch: Literal["draft", "candidate"]
    page_count: StrictInt | None = Field(default=None, ge=1, le=1000)
    pdf: ObjectRef
    synctex: ObjectRef | None = None
    geometry: ObjectRef | None = None

    def public(self) -> dict[str, Any]:
        prefix = f"/download/{self.job_id}/preview/{self.artifact_id}"
        return {
            "artifact_id": self.artifact_id, "job_id": self.job_id,
            "source_sha256": self.source_sha256,
            "render_source_sha256": self.render_source_sha256,
            "content_revision": self.content_revision, "document_id": self.document_id,
            "branch": self.branch, "owner_epoch": self.owner_epoch,
            "run_id": self.job_id if self.branch == "candidate" else None,
            "compiler": self.compiler, "settings_sha256": self.settings_sha256,
            "pdf_sha256": self.pdf.sha256, "pdf_size": self.pdf.size,
            "page_count": self.page_count, "preview_url": prefix,
            "geometry_url": f"{prefix}/geometry" if self.geometry else None,
        }


def manifest_key(owner_scope_hash: str, artifact_id: str) -> str:
    if not re.fullmatch(HASH_PATTERN, owner_scope_hash) or not re.fullmatch(HASH_PATTERN, artifact_id):
        raise ValueError("invalid artifact identity")
    return f"render-artifacts/v1/{owner_scope_hash}/manifests/{artifact_id}.json"


def binary_key(owner_scope_hash: str, digest: str, kind: str) -> str:
    if not re.fullmatch(HASH_PATTERN, owner_scope_hash) or not re.fullmatch(HASH_PATTERN, digest):
        raise ValueError("invalid artifact identity")
    suffix = {"pdf": ".pdf", "synctex": ".synctex.gz", "geometry": ".json"}[kind]
    return f"render-artifacts/v1/{owner_scope_hash}/{kind}/{digest}{suffix}"


def parse_manifest(raw: str | bytes | dict) -> RenderManifest:
    if isinstance(raw, (str, bytes)):
        if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > MAX_MANIFEST_BYTES:
            raise ValueError("render manifest exceeds limit")
        raw = json.loads(raw)
    manifest = RenderManifest.model_validate(raw)
    ttl = MANIFEST_TTL if manifest.owner_scope_kind == "user" else 86400
    if not 0 < manifest.expires_at - manifest.created_at <= ttl:
        raise ValueError("invalid render retention interval")
    expected = sha256(canonical_json({key: value for key, value in manifest.model_dump().items() if key != "artifact_id"}))
    if manifest.artifact_id != expected:
        raise ValueError("render manifest identity mismatch")
    for kind in ("pdf", "synctex", "geometry"):
        reference = getattr(manifest, kind)
        cap = {"pdf": MAX_COMPILED_PDF_BYTES, "synctex": MAX_SYNCTEX_COMPRESSED_BYTES,
               "geometry": MAX_GEOMETRY_BYTES}[kind]
        media = {"pdf": "application/pdf", "synctex": "application/gzip", "geometry": "application/json"}[kind]
        if reference and (reference.size > cap or reference.media_type != media):
            raise ValueError("invalid render object bounds or type")
        if reference and reference.key != binary_key(manifest.owner_scope_sha256, reference.sha256, kind):
            raise ValueError("invalid render object reference")
    return manifest


def get_job_manifest(redis_client: Any, job_id: str) -> RenderManifest | None:
    raw = redis_client.get(f"latexy:job:{job_id}:artifact")
    if not raw:
        return None
    manifest = parse_manifest(raw)
    if manifest.job_id != job_id:
        raise ValueError("render job identity mismatch")
    return manifest


def download_object(reference: ObjectRef, max_bytes: int) -> bytes:
    with engine_span("artifact_download"):
        data = storage_service.download_bytes(reference.key, max_bytes=max_bytes)
    if not isinstance(data, bytes) or len(data) != reference.size or sha256(data) != reference.sha256:
        raise ValueError("render object integrity mismatch")
    return data


def _put(scope: str, kind: str, data: bytes, media_type: str) -> ObjectRef:
    digest = sha256(data)
    key = binary_key(scope, digest, kind)
    storage_service.upload_immutable_bytes(key, data, media_type)
    return ObjectRef(key=key, sha256=digest, size=len(data), media_type=media_type)


def bind_manifest(
    redis_client: Any, job_id: str, request: dict[str, Any], pdf: ObjectRef,
    synctex: ObjectRef | None = None, geometry: ObjectRef | None = None,
    page_count: int | None = None,
) -> RenderManifest | None:
    from ...workers.event_publisher import publish_event
    from ...workers.job_lifecycle import current_owner, current_owner_epoch, write_owned_artifacts

    owner = current_owner(job_id)
    epoch = current_owner_epoch(job_id)
    if not owner or epoch is None or not request.get("owner_scope"):
        return None
    scope_hash = sha256(request["owner_scope"])
    if pdf.key != binary_key(scope_hash, pdf.sha256, "pdf"):
        raise ValueError("render cache tenant mismatch")
    revision = request.get("content_revision")
    if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 0):
        raise ValueError("invalid content revision")
    fields = {
        "schema_version": 1, "job_id": job_id,
        "owner_scope_kind": "user" if request["owner_scope"].startswith("user:") else "device",
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + (MANIFEST_TTL if request["owner_scope"].startswith("user:") else 86400),
        "owner_scope_sha256": scope_hash, "owner_token_sha256": sha256(owner), "owner_epoch": epoch,
        "source_sha256": sha256(request["source"]),
        "render_source_sha256": sha256(request["render_source"]),
        "settings_sha256": sha256(canonical_json(request["settings"])),
        "engine_fingerprint": request["engine_fingerprint"], "renderer_epoch": RENDERER_EPOCH,
        "compiler": request["compiler"], "document_id": request.get("document_id"),
        "content_revision": revision, "branch": request.get("branch", "draft"),
        "page_count": page_count, "pdf": pdf.model_dump(),
        "synctex": synctex.model_dump() if synctex else None,
        "geometry": geometry.model_dump() if geometry else None,
    }
    fields["artifact_id"] = sha256(canonical_json(fields))
    manifest = parse_manifest(fields)
    encoded = canonical_json(manifest.model_dump())
    # A missing/expired/replaced/cancelled capability may upload unreachable
    # content-addressed objects, but cannot expose a preview or overwrite a job.
    if not write_owned_artifacts(redis_client, job_id, {}, MANIFEST_TTL):
        return None
    with engine_span("artifact_storage"):
        storage_service.upload_immutable_bytes(manifest_key(scope_hash, manifest.artifact_id), encoded, "application/json")
    from .retention import register_manifest

    with engine_span("artifact_storage"):
        registered = asyncio.run(register_manifest(manifest))
    if not registered:
        return None
    entries = {f"latexy:job:{job_id}:artifact": encoded.decode("utf-8")}
    cache_key = request.get("cache_key")
    if isinstance(cache_key, str) and re.fullmatch(r"latexy:compile-cache:[a-f0-9]{64}", cache_key):
        entries[cache_key] = encoded.decode("utf-8")
    if not write_owned_artifacts(redis_client, job_id, entries, MANIFEST_TTL):
        return None
    publish_event(job_id, "artifact.ready", manifest.public())
    return manifest


def persist_render(
    redis_client: Any, job_id: str, job_dir: Path, request: dict[str, Any], pdf_bytes: bytes,
    page_count: int | None = None,
) -> RenderManifest | None:
    from ...workers.job_lifecycle import current_owner, current_owner_epoch, write_owned_artifacts

    if not current_owner(job_id) or current_owner_epoch(job_id) is None or not request.get("owner_scope"):
        return None
    if not pdf_bytes.startswith(b"%PDF-") or len(pdf_bytes) > MAX_COMPILED_PDF_BYTES:
        raise BoundedReadError("invalid compiled PDF")
    if not write_owned_artifacts(redis_client, job_id, {}, MANIFEST_TTL):
        return None
    scope = sha256(request["owner_scope"])
    with engine_span("artifact_storage"):
        pdf = _put(scope, "pdf", pdf_bytes, "application/pdf")
        synctex = None
        compressed = job_dir / "resume.synctex.gz"
        plain = job_dir / "resume.synctex"
        if compressed.exists():
            # Enforce decompression limits before publishing even compressed bytes.
            read_gzip_file_bounded(compressed, max_compressed_bytes=MAX_SYNCTEX_COMPRESSED_BYTES, max_decompressed_bytes=MAX_SYNCTEX_DECOMPRESSED_BYTES)
            synctex = _put(scope, "synctex", read_file_bounded(compressed, MAX_SYNCTEX_COMPRESSED_BYTES), "application/gzip")
        elif plain.exists():
            data = read_file_bounded(plain, MAX_SYNCTEX_DECOMPRESSED_BYTES)
            compressed_data = gzip.compress(data, mtime=0)
            if len(compressed_data) > MAX_SYNCTEX_COMPRESSED_BYTES:
                raise BoundedReadError("SyncTeX compressed artifact exceeds limit")
            synctex = _put(scope, "synctex", compressed_data, "application/gzip")
    geometry = None
    document = request.get("source_document")
    if (isinstance(document, dict) and document.get("source_sha256") == sha256(request["source"])
            and document.get("document_id") == request.get("document_id")
            and document.get("content_revision") == request.get("content_revision")):
        try:
            from .geometry import extract_geometry

            projected = extract_geometry(job_dir / "resume.pdf", document, pdf_sha256=pdf.sha256, branch=request.get("branch", "draft"))
            if projected is not None:
                data = canonical_json(projected)
                if len(data) <= MAX_GEOMETRY_BYTES:
                    with engine_span("artifact_storage"):
                        geometry = _put(scope, "geometry", data, "application/json")
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            # Unsupported/ambiguous mapping is read-only; it never replaces the
            # exact PDF with a guessed overlay or fails an otherwise safe render.
            geometry = None
    return bind_manifest(redis_client, job_id, request, pdf, synctex, geometry, page_count=page_count)


def restore_render(redis_client: Any, job_id: str, request: dict[str, Any], raw: str | bytes) -> tuple[RenderManifest, bytes] | None:
    """Reuse checked bytes, bind a fresh capability, and discard stale geometry."""
    old = parse_manifest(raw)
    if (old.owner_scope_sha256 != sha256(request["owner_scope"])
            or old.render_source_sha256 != sha256(request["render_source"])
            or old.settings_sha256 != sha256(canonical_json(request["settings"]))
            or old.compiler != request["compiler"]
            or old.engine_fingerprint != request["engine_fingerprint"]
            or old.renderer_epoch != RENDERER_EPOCH):
        return None
    data = download_object(old.pdf, MAX_COMPILED_PDF_BYTES)
    if not data.startswith(b"%PDF-"):
        raise ValueError("invalid cached PDF")
    geometry = None
    # Geometry identifies semantic nodes from a particular document revision;
    # matching PDF bytes alone does not authorize reusing those node IDs.
    if (old.source_sha256 == sha256(request["source"])
            and old.document_id == request.get("document_id")
            and old.content_revision == request.get("content_revision")
            and old.branch == request.get("branch", "draft")):
        geometry = old.geometry
    document = request.get("source_document")
    if (geometry is None and isinstance(document, dict)
            and document.get("source_sha256") == sha256(request["source"])
            and document.get("document_id") == request.get("document_id")
            and document.get("content_revision") == request.get("content_revision")):
        try:
            from .geometry import extract_geometry

            with tempfile.TemporaryDirectory(prefix="latexy-cache-geometry-") as directory:
                pdf_file = Path(directory) / "resume.pdf"
                pdf_file.write_bytes(data)
                projected = extract_geometry(pdf_file, document, pdf_sha256=old.pdf.sha256,
                    branch=request.get("branch", "draft"))
                if projected is not None:
                    encoded = canonical_json(projected)
                    if len(encoded) <= MAX_GEOMETRY_BYTES:
                        geometry = _put(old.owner_scope_sha256, "geometry", encoded, "application/json")
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            geometry = None
    new = bind_manifest(redis_client, job_id, request, old.pdf, old.synctex, geometry, old.page_count)
    return (new, data) if new else None


async def get_public_job_artifact(redis_client: Any, job_id: str) -> dict[str, Any] | None:
    raw = await redis_client.get(f"latexy:job:{job_id}:artifact")
    if not raw:
        return None
    try:
        manifest = parse_manifest(raw)
        if manifest.expires_at <= int(time.time()):
            return None
        lifecycle = await redis_client.hgetall(f"latexy:job:{job_id}:lifecycle")
        values = {(key.decode() if isinstance(key, bytes) else key): (value.decode() if isinstance(value, bytes) else value) for key, value in lifecycle.items()}
        if manifest.job_id != job_id or values.get("cancel_requested") == "1" or values.get("status") not in {"running", "finalizing", "completed"}:
            return None
        if values.get("epoch") != str(manifest.owner_epoch):
            return None
        return manifest.public()
    except (ValueError, TypeError):
        return None

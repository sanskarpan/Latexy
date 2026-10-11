"""Real DB/Redis preview fences, expiry recovery and cancellation during storage."""
import asyncio
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import update

from app.api import render_artifact_routes as api
from app.database.models import Compilation, JobFinalization, User
from app.services.render_engine.artifacts import (
    ObjectRef,
    binary_key,
    canonical_json,
    manifest_key,
    parse_manifest,
    sha256,
)

PDF = b"%PDF-1.7\nimmutable authorized fixture\n"


@pytest.fixture
async def render_access(db_session, monkeypatch):
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    job_id, user_id, compilation_id = (str(uuid4()) for _ in range(3))
    owner = "owner-" + str(uuid4())
    scope = sha256("user:" + user_id)
    reference = ObjectRef(key=binary_key(scope, sha256(PDF), "pdf"), sha256=sha256(PDF), size=len(PDF), media_type="application/pdf")
    fields = dict(schema_version=1, job_id=job_id, owner_scope_sha256=scope,
                  owner_scope_kind="user", created_at=int(time.time()), expires_at=int(time.time()) + 86400,
                  owner_token_sha256=sha256(owner), owner_epoch=1, source_sha256=sha256("source"),
                  render_source_sha256=sha256("source"), settings_sha256=sha256(canonical_json({})),
                  engine_fingerprint="fixture", renderer_epoch="fixture", compiler="pdflatex",
                  document_id=None, content_revision=None, branch="draft", page_count=1,
                  pdf=reference.model_dump(), synctex=None, geometry=None)
    fields["artifact_id"] = sha256(canonical_json(fields))
    manifest = parse_manifest(fields)
    db_session.add(User(id=user_id, email="test_render_" + user_id + "@example.test", name="Fixture"))
    await db_session.flush()
    db_session.add(Compilation(id=compilation_id, user_id=user_id, job_id=job_id, status="processing"))
    await db_session.flush()
    row = JobFinalization(id=str(uuid4()), job_id=job_id, user_id=user_id,
                          job_type="latex_compilation", compilation_id=compilation_id,
                          owner_token=owner, owner_epoch=1, state="pending", cancel_requested=False,
                          expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                          lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    db_session.add(row)
    await db_session.commit()
    await redis.hset(f"latexy:job:{job_id}:lifecycle", mapping={
        "status": "running", "owner": owner, "epoch": 1,
        "cancel_requested": 0, "lease_until": time.time() + 600,
    })
    await redis.set(f"latexy:job:{job_id}:artifact", canonical_json(fields))
    objects = {reference.key: PDF, manifest_key(scope, manifest.artifact_id): canonical_json(fields)}

    async def get_redis():
        return redis

    monkeypatch.setattr(api, "get_redis_client", get_redis)
    monkeypatch.setattr(api.storage_service, "download_bytes", lambda key, max_bytes: objects[key])
    yield db_session, redis, manifest, row, objects
    await redis.delete(f"latexy:job:{job_id}:lifecycle", f"latexy:job:{job_id}:artifact", f"latexy:job:{job_id}:meta")
    await redis.aclose()


async def completed(fixture):
    db, redis, manifest, row, _ = fixture
    await db.execute(update(Compilation).where(Compilation.id == row.compilation_id).values(
        status="completed", pdf_path=manifest.pdf.key, pdf_size=manifest.pdf.size,
    ))
    await db.execute(update(JobFinalization).where(JobFinalization.id == row.id).values(
        state="completed", result_payload={"artifact": manifest.public()},
        pdf_path=manifest.pdf.key, pdf_size=manifest.pdf.size, pdf_sha256=manifest.pdf.sha256,
    ))
    await db.commit()
    await redis.hset(f"latexy:job:{row.job_id}:lifecycle", mapping={"status": "completed"})
    await redis.hdel(f"latexy:job:{row.job_id}:lifecycle", "owner", "lease_until")


async def test_completed_publication_without_redis_owner_allows_verified_pdf(render_access):
    db, redis, manifest, row, _ = render_access
    await completed(render_access)
    response = await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)
    assert response.body == PDF
    # A retained conflicting capability, epoch or pointer is never ignored.
    lifecycle = f"latexy:job:{row.job_id}:lifecycle"
    await redis.hset(lifecycle, mapping={"owner": "conflicting-owner"})
    with pytest.raises(HTTPException):
        await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)
    await redis.hdel(lifecycle, "owner")
    await redis.hset(lifecycle, mapping={"epoch": 2})
    with pytest.raises(HTTPException):
        await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)
    await redis.hset(lifecycle, mapping={"epoch": 1})
    await redis.set(f"latexy:job:{row.job_id}:artifact", "{\"artifact_id\":\"replaced\"}")
    with pytest.raises(HTTPException):
        await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)


async def test_preview_ready_does_not_authorize_export(render_access):
    db, _, manifest, row, _ = render_access
    response = await api.serve_artifact(db, row.job_id, row.user_id, None, artifact_id=manifest.artifact_id)
    assert response.body == PDF
    assert response.headers["content-disposition"].startswith("inline")
    with pytest.raises(HTTPException) as error:
        await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)
    assert error.value.status_code == 409


async def test_scope_and_manifest_id_cannot_be_substituted(render_access):
    db, _, manifest, row, _ = render_access
    for user, identity in ((str(uuid4()), manifest.artifact_id), (row.user_id, "0" * 64), (None, manifest.artifact_id)):
        with pytest.raises(HTTPException) as error:
            await api.serve_artifact(db, row.job_id, user, "unrelated-device", artifact_id=identity)
        assert error.value.status_code == 404


async def test_completed_manifest_recovers_after_redis_expiry(render_access):
    db, redis, manifest, row, _ = render_access
    await completed(render_access)
    await redis.delete(f"latexy:job:{row.job_id}:artifact", f"latexy:job:{row.job_id}:lifecycle")
    response = await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)
    assert response.body == PDF
    assert response.headers["content-disposition"].startswith("attachment")
    await db.execute(update(JobFinalization).where(JobFinalization.id == row.id).values(
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    await db.commit()
    with pytest.raises(HTTPException):
        await api.serve_artifact(db, row.job_id, row.user_id, None, export=True)


@pytest.mark.parametrize("replacement", [False, True])
async def test_storage_io_cannot_cross_cancellation_or_owner_replacement(render_access, monkeypatch, replacement):
    db, redis, _, row, _ = render_access
    entered, release = threading.Event(), threading.Event()

    def blocked_download(key, max_bytes):
        entered.set()
        assert release.wait(5)
        return PDF

    monkeypatch.setattr(api.storage_service, "download_bytes", blocked_download)
    request = asyncio.create_task(api.serve_artifact(db, row.job_id, row.user_id, None))
    assert await asyncio.to_thread(entered.wait, 5)
    if replacement:
        await redis.hset(f"latexy:job:{row.job_id}:lifecycle", mapping={"owner": "new-owner", "epoch": 2})
    else:
        await db.execute(update(JobFinalization).where(JobFinalization.id == row.id).values(cancel_requested=True))
        await db.commit()
    release.set()
    with pytest.raises(HTTPException) as error:
        await request
    assert error.value.status_code == 404


async def test_corrupt_binary_is_never_returned(render_access):
    db, _, manifest, row, objects = render_access
    objects[manifest.pdf.key] = PDF + b"tampered"
    with pytest.raises(HTTPException) as error:
        await api.serve_artifact(db, row.job_id, row.user_id, None)
    assert error.value.status_code == 404


async def test_guest_job_requires_exact_device_scope(render_access):
    db, redis, manifest, row, _ = render_access
    fields = manifest.model_dump()
    fields["owner_scope_sha256"] = sha256("device:fixture-device")
    fields["owner_scope_kind"] = "device"
    fields["pdf"]["key"] = binary_key(fields["owner_scope_sha256"], manifest.pdf.sha256, "pdf")
    fields["artifact_id"] = sha256(canonical_json({key: value for key, value in fields.items() if key != "artifact_id"}))
    await redis.set(f"latexy:job:{row.job_id}:artifact", canonical_json(fields))
    await redis.set(f"latexy:job:{row.job_id}:meta", json.dumps({"job_id": row.job_id, "user_id": None}))
    await db.execute(update(JobFinalization).where(JobFinalization.id == row.id).values(user_id=None))
    await db.commit()
    loaded = await api.load_manifest(db, redis, row.job_id, None, "fixture-device")
    assert loaded.owner_scope_sha256 == fields["owner_scope_sha256"]
    for device in (None, "wrong-device"):
        with pytest.raises(HTTPException):
            await api.load_manifest(db, redis, row.job_id, None, device)

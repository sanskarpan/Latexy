"""Opt-in real TeX + Redis Lua + PostgreSQL + isolated S3 integration."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database.models import Compilation, JobFinalization, Resume, User
from app.services import storage_service
from app.services.render_engine.artifacts import get_job_manifest, sha256
from app.workers import event_publisher, job_lifecycle, latex_worker, orchestrator

pytestmark = pytest.mark.skipif(os.environ.get("RUN_RENDER_STORAGE_INTEGRATION") != "1", reason="requires isolated real S3 fixture")
SOURCE = r"\documentclass{article}\begin{document}Hello World\end{document}"


def test_real_conditional_immutable_writes():
    key = "test-conditional/" + uuid4().hex
    storage_service.upload_immutable_bytes(key, b"immutable", "application/octet-stream")
    storage_service.upload_immutable_bytes(key, b"immutable", "application/octet-stream")
    with pytest.raises(ValueError):
        storage_service.upload_immutable_bytes(key, b"different", "application/octet-stream")
    assert storage_service.download_bytes(key, max_bytes=100) == b"immutable"
    storage_service.delete_object(key)


async def test_real_admitted_render_cache_preview_export_sync_geometry(db_session_factory, monkeypatch):
    from app.api.render_artifact_routes import serve_artifact

    user_id, resume_id = str(uuid4()), str(uuid4())
    jobs = ["test_s3_render_" + uuid4().hex for _ in range(3)]
    redis = event_publisher.get_worker_redis()
    source_document = {"document_id": resume_id, "content_revision": 1, "source_sha256": sha256(SOURCE),
        "nodes": [{"node_id": "hello", "node_revision": sha256("Hello World"), "kind": "summary",
                   "text": "Hello World", "editable": True,
                   "source_span": {"start": SOURCE.index("Hello World"), "end": SOURCE.index("Hello World") + 11}}]}
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=jobs[0] + "@example.com"))
        await session.flush()
        session.add(Resume(id=resume_id, user_id=user_id, title="test resume", latex_content=SOURCE))
        await session.flush()
        for index, job in enumerate(jobs):
            session.add(Compilation(id=str(uuid4()), job_id=job, user_id=user_id, resume_id=resume_id, status="processing"))
            session.add(JobFinalization(id=str(uuid4()), job_id=job, user_id=user_id, resume_id=resume_id,
                job_type="combined" if index == 2 else "latex_compilation", owner_epoch=0, state="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
        await session.commit()
    results = []
    real_popen = latex_worker.subprocess.Popen
    try:
        for index, job in enumerate(jobs):
            redis.set(f"latexy:job:{job}:meta", json.dumps({"user_id": user_id, "job_type": "combined" if index == 2 else "latex_compilation"}))
            assert job_lifecycle.begin_dispatch(redis, job)
            assert job_lifecycle.mark_dispatch_accepted(redis, job)
            kwargs = {"latex_content": SOURCE, "job_id": job, "user_id": user_id, "resume_id": resume_id,
                "compiler": "pdflatex", "timeout_seconds": 15, "metadata": {"skip_auto_save": True},
                "render_request": {"source_document": source_document, "document_id": resume_id, "content_revision": 1}}
            if index:
                def forbidden(command, *args, **kwargs):
                    if command[0] in {"pdfinfo", "pdftotext"}:
                        return real_popen(command, *args, **kwargs)
                    raise AssertionError("exact render must not spawn TeX")
                monkeypatch.setattr(latex_worker.subprocess, "Popen", forbidden)
            if index == 2:
                def combined_render():
                    owner = "combined-test-owner"
                    assert job_lifecycle.admit_worker(redis, job, owner, None, user_id)
                    try:
                        ok, seconds, error, pages, pdf = orchestrator._run_latex_stage(
                            job, SOURCE, compiler="pdflatex", timeout_seconds=15,
                            owner_scope=f"user:{user_id}", render_request={**kwargs["render_request"], "branch": "candidate"})
                        assert ok, error
                        artifact = get_job_manifest(redis, job).public()
                        payload = {"success": True, "job_id": job, "compilation_time": seconds,
                                   "page_count": pages, "artifact": artifact}
                        epoch = job_lifecycle.current_owner_epoch(job)
                        assert job_lifecycle.begin_finalizing(redis, job, owner, epoch)
                        assert latex_worker.commit_latex_finalization(job, owner, epoch, payload, pdf, seconds)
                        assert event_publisher.publish_job_result(job, payload)
                        event_publisher.publish_event(job, "job.completed", {"success": True})
                        return payload
                    finally:
                        job_lifecycle.stop_lease_heartbeat(job)
                        job_lifecycle.clear_current_owner(job)
                result = await asyncio.to_thread(combined_render)
            else:
                result = await asyncio.to_thread(lambda: latex_worker.compile_latex_task.apply(kwargs=kwargs, throw=True).get())
            assert result["success"], result
            results.append(result)
            assert redis.get(f"latexy:job:{job}:pdf") is None
            assert redis.get(f"latexy:job:{job}:synctex") is None
            manifest = get_job_manifest(redis, job)
            assert manifest is not None
            assert manifest.source_sha256 == sha256(SOURCE)
            events = [json.loads(fields.get("payload", fields.get(b"payload"))) for _, fields in redis.xrange(f"latexy:stream:{job}")]
            types = [event["type"] for event in events]
            assert types.index("artifact.ready") < types.index("job.completed")
            async with db_session_factory() as session:
                row = await session.scalar(select(Compilation).where(Compilation.job_id == job))
                assert row.status == "completed"
                assert row.pdf_path == manifest.pdf.key
                assert row.artifact_accepted is (index != 2)
                preview = await serve_artifact(session, job, user_id, None, artifact_id=manifest.artifact_id)
                assert preview.body.startswith(b"%PDF-")
                if index == 2:
                    from fastapi import HTTPException
                    with pytest.raises(HTTPException) as rejected:
                        await serve_artifact(session, job, user_id, None, export=True)
                    assert rejected.value.status_code == 409
                else:
                    exported = await serve_artifact(session, job, user_id, None, export=True)
                    assert exported.body == preview.body
                synctex = await serve_artifact(session, job, user_id, None, artifact_id=manifest.artifact_id, kind="synctex")
                assert b"SyncTeX Version:" in synctex.body
                geometry = await serve_artifact(session, job, user_id, None, artifact_id=manifest.artifact_id, kind="geometry")
                value = json.loads(geometry.body)
                assert value["artifact_id"] == manifest.artifact_id
                assert value["boxes"][0]["node_id"] == "hello"
                assert value["pdf_sha256"] == manifest.pdf.sha256
        assert results[1]["compilation_time"] == 0.0
        assert results[0]["artifact"]["pdf_sha256"] == results[1]["artifact"]["pdf_sha256"]
        assert results[0]["artifact"]["artifact_id"] != results[1]["artifact"]["artifact_id"]
    finally:
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(jobs)))
            await session.execute(delete(Compilation).where(Compilation.job_id.in_(jobs)))
            await session.execute(delete(Resume).where(Resume.id == resume_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def test_real_guest_completed_artifact_binding_and_exact_cache(db_session_factory, monkeypatch):
    from fastapi import HTTPException

    from app.api.render_artifact_routes import serve_artifact

    fingerprint = "guest_" + uuid4().hex
    jobs = ["test_s3_guest_" + uuid4().hex for _ in range(2)]
    redis = event_publisher.get_worker_redis()
    real_popen = latex_worker.subprocess.Popen
    document = {"document_id": "guest", "content_revision": 1, "source_sha256": sha256(SOURCE),
        "nodes": [{"node_id": "hello", "node_revision": sha256("Hello World"), "kind": "summary",
            "text": "Hello World", "editable": True,
            "source_span": {"start": SOURCE.index("Hello World"), "end": SOURCE.index("Hello World") + 11}}]}
    async with db_session_factory() as session:
        for job in jobs:
            session.add(JobFinalization(id=str(uuid4()), job_id=job, user_id=None,
                job_type="latex_compilation", owner_epoch=0, state="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24)))
        await session.commit()
    results = []
    try:
        for index, job in enumerate(jobs):
            redis.set(f"latexy:job:{job}:meta", json.dumps({"user_id": None, "job_type": "latex_compilation", "device_fingerprint": fingerprint}))
            assert job_lifecycle.begin_dispatch(redis, job)
            assert job_lifecycle.mark_dispatch_accepted(redis, job)
            if index:
                def forbidden(command, *args, **kwargs):
                    if command[0] in {"pdfinfo", "pdftotext"}:
                        return real_popen(command, *args, **kwargs)
                    raise AssertionError("guest exact cache must not spawn TeX")
                monkeypatch.setattr(latex_worker.subprocess, "Popen", forbidden)
            kwargs = {"latex_content": SOURCE, "job_id": job, "device_fingerprint": fingerprint,
                "compiler": "pdflatex", "timeout_seconds": 15, "watermark": "Latexy",
                "render_request": {"source_document": document, "document_id": "guest", "content_revision": 1}}
            result = await asyncio.to_thread(lambda: latex_worker.compile_latex_task.apply(kwargs=kwargs, throw=True).get())
            assert result["success"], result
            results.append(result)
            manifest = get_job_manifest(redis, job)
            assert manifest.owner_scope_kind == "device"
            assert manifest.expires_at - manifest.created_at <= 86400
            async with db_session_factory() as session:
                final = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job))
                assert final.state == "completed"
                assert (final.pdf_path, final.pdf_size, final.pdf_sha256) == (manifest.pdf.key, manifest.pdf.size, manifest.pdf.sha256)
                assert await session.scalar(select(Compilation.id).where(Compilation.job_id == job)) is None
                for kind in ("pdf", "synctex", "geometry"):
                    response = await serve_artifact(session, job, None, fingerprint, artifact_id=manifest.artifact_id, kind=kind)
                    assert response.body
                exported = await serve_artifact(session, job, None, fingerprint, export=True)
                assert exported.body.startswith(b"%PDF-")
                with pytest.raises(HTTPException) as wrong:
                    await serve_artifact(session, job, None, "wrong-fingerprint", export=True)
                assert wrong.value.status_code == 404
            assert redis.get(f"latexy:job:{job}:pdf") is None
        assert results[1]["compilation_time"] == 0
        assert results[0]["artifact"]["pdf_sha256"] == results[1]["artifact"]["pdf_sha256"]
    finally:
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(jobs)))
            await session.commit()

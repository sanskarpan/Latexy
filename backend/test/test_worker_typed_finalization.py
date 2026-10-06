"""Worker boundary tests for the typed PDF/Compilation/Resume commit."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database.models import Compilation, JobFinalization, Resume, User
from app.services.storage_service import compilation_pdf_key
from app.workers.finalization_arbiter import FinalizationState
from app.workers.latex_worker import commit_latex_finalization


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


async def _seed(session_factory, *, with_compilation: bool, with_resume: bool):
    user_id = str(uuid4())
    resume_id = str(uuid4()) if with_resume else None
    job_id = f"test_worker_typed_{uuid4().hex}"
    owner = f"worker:{uuid4()}"
    async with session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com", name="test"))
        if with_resume:
            session.add(
                Resume(
                    id=resume_id,
                    user_id=user_id,
                    title="Test resume",
                    latex_content="original",
                )
            )
        if with_compilation:
            session.add(
                Compilation(
                    id=str(uuid4()),
                    user_id=user_id,
                    resume_id=resume_id,
                    job_id=job_id,
                    status="processing",
                )
            )
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                owner_token=owner,
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
                resume_id=resume_id,
                resume_apply_requested=bool(with_resume),
            )
        )
        await session.commit()
    return job_id, owner, user_id, resume_id


async def _cleanup(session_factory, job_id: str, user_id: str) -> None:
    async with session_factory() as session:
        await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await session.execute(delete(Compilation).where(Compilation.job_id == job_id))
        await session.execute(delete(Resume).where(Resume.user_id == user_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
async def test_anonymous_lifecycle_commit_keeps_pdf_redis_only(db_session_factory, monkeypatch):
    job_id, owner, user_id, _ = await _seed(
        db_session_factory, with_compilation=False, with_resume=False
    )
    uploaded = []

    def upload(*args, **kwargs):
        uploaded.append(args)
        return "should-not-upload", hashlib.sha256(b"pdf").hexdigest()

    monkeypatch.setattr("app.services.storage_service.upload_compilation_pdf", upload)
    outcome = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner,
        1,
        {"success": True, "job_id": job_id},
        b"pdf",
        0.2,
    )
    assert outcome
    assert uploaded == []
    async with db_session_factory() as session:
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert row.state == FinalizationState.COMPLETED.value
        assert row.pdf_path is None
        assert row.pdf_sha256 is None
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_worker_commit_stores_pdf_and_resume_together(db_session_factory, monkeypatch):
    job_id, owner, user_id, resume_id = await _seed(
        db_session_factory, with_compilation=True, with_resume=True
    )
    pdf = b"pdf-bytes"
    monkeypatch.setattr(
        "app.services.storage_service.upload_compilation_pdf",
        lambda job, token, data: (compilation_pdf_key(job, token), hashlib.sha256(data).hexdigest()),
    )
    outcome = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner,
        1,
        {"success": True, "job_id": job_id, "optimized_latex": "generated"},
        pdf,
        1.5,
        resume_id=resume_id,
        resume_user_id=user_id,
        resume_content="generated",
        expected_resume_sha256=hashlib.sha256(b"original").hexdigest(),
    )
    assert outcome
    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        resume = await session.scalar(select(Resume).where(Resume.id == resume_id))
        arbiter = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "completed"
        assert compilation.pdf_path == compilation_pdf_key(job_id, owner)
        assert compilation.pdf_size == len(pdf)
        assert resume.latex_content == "generated"
        assert arbiter.state == FinalizationState.COMPLETED.value
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_resume_cas_conflict_does_not_complete_compilation(db_session_factory, monkeypatch):
    job_id, owner, user_id, resume_id = await _seed(
        db_session_factory, with_compilation=True, with_resume=True
    )
    async with db_session_factory() as session:
        resume = await session.scalar(select(Resume).where(Resume.id == resume_id))
        resume.latex_content = "edited while running"
        await session.commit()
    monkeypatch.setattr(
        "app.services.storage_service.upload_compilation_pdf",
        lambda job, token, data: (compilation_pdf_key(job, token), hashlib.sha256(data).hexdigest()),
    )
    outcome = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner,
        1,
        {"success": True, "job_id": job_id},
        b"pdf",
        1.0,
        resume_id=resume_id,
        resume_user_id=user_id,
        resume_content="generated",
        expected_resume_sha256=hashlib.sha256(b"original").hexdigest(),
    )
    assert not outcome
    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        resume = await session.scalar(select(Resume).where(Resume.id == resume_id))
        arbiter = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "failed"
        assert compilation.error_message == "resume_conflict"
        assert compilation.pdf_path is None
        assert resume.latex_content == "edited while running"
        assert arbiter.state == FinalizationState.FAILED.value
        assert arbiter.result_payload["success"] is False
        assert outcome.canonical_result == arbiter.result_payload
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_completed_arbiter_replays_original_payload_for_new_owner(db_session_factory):
    job_id, owner, user_id, _ = await _seed(
        db_session_factory, with_compilation=False, with_resume=False
    )
    first = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner,
        1,
        {"success": True, "job_id": job_id, "optimized_latex": "canonical"},
        b"pdf-a",
        0.1,
    )
    second = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        "replacement-owner",
        2,
        {"success": True, "job_id": job_id, "optimized_latex": "stale-attempt"},
        b"pdf-b",
        0.2,
    )
    assert first and second
    assert second.canonical_result["optimized_latex"] == "canonical"
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_storage_failure_is_durable_failure_without_compilation_completion(
    db_session_factory, monkeypatch
):
    job_id, owner, user_id, _ = await _seed(
        db_session_factory, with_compilation=True, with_resume=False
    )
    markers = []
    monkeypatch.setattr(
        "app.services.storage_service.upload_compilation_pdf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )
    monkeypatch.setattr(
        "app.workers.storage_guard.record_compilation_database",
        lambda identity: markers.append(identity),
    )
    outcome = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner,
        1,
        {"success": True, "job_id": job_id},
        b"pdf",
        1.0,
    )
    assert not outcome
    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        arbiter = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "failed"
        assert compilation.error_message == "Compiled PDF could not be durably stored"
        assert compilation.pdf_path is None
        assert arbiter.state == FinalizationState.FAILED.value
        assert arbiter.result_payload["success"] is False
        assert outcome.canonical_result == arbiter.result_payload
    assert markers == []
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_cancel_can_commit_while_storage_upload_is_blocked(db_session_factory, monkeypatch):
    job_id, owner, user_id, _ = await _seed(
        db_session_factory, with_compilation=True, with_resume=False
    )
    upload_started = Event()
    release_upload = Event()

    def blocked_upload(job, token, data):
        upload_started.set()
        # This runs in the worker thread; the event loop remains free to issue
        # the cancellation transaction against the same job.
        while not release_upload.is_set():
            import time

            time.sleep(0.01)
        return compilation_pdf_key(job, token), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr("app.services.storage_service.upload_compilation_pdf", blocked_upload)
    task = asyncio.create_task(
        asyncio.to_thread(
            commit_latex_finalization,
            job_id,
            owner,
            1,
            {"success": True, "job_id": job_id},
            b"pdf",
            1.0,
        )
    )
    while not upload_started.is_set():
        await asyncio.sleep(0.01)
    async with db_session_factory() as session:
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        row.state = FinalizationState.CANCELLED.value
        row.cancel_requested = True
        await session.commit()
    release_upload.set()
    outcome = await task
    assert not outcome
    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "processing"
        assert row.state == FinalizationState.CANCELLED.value
    await _cleanup(db_session_factory, job_id, user_id)


@pytest.mark.asyncio
async def test_losing_storage_failure_replays_replacement_success(
    db_session_factory, monkeypatch
):
    """A replacement owner completing during upload must outrank A's failure."""
    job_id, owner_a, user_id, _ = await _seed(
        db_session_factory, with_compilation=True, with_resume=False
    )
    owner_b = f"worker:{uuid4()}"
    upload_started = Event()
    release_upload = Event()

    def upload(job, token, data):
        if token == owner_a:
            upload_started.set()
            while not release_upload.is_set():
                import time

                time.sleep(0.01)
            raise RuntimeError("owner A lost storage race")
        return compilation_pdf_key(job, token), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr("app.services.storage_service.upload_compilation_pdf", upload)
    task_a = asyncio.create_task(
        asyncio.to_thread(
            commit_latex_finalization,
            job_id,
            owner_a,
            1,
            {"success": True, "job_id": job_id},
            b"pdf-a",
            1.0,
        )
    )
    while not upload_started.is_set():
        await asyncio.sleep(0.01)

    async with db_session_factory() as session:
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        row.owner_token = owner_b
        row.owner_epoch = 2
        row.lease_expires_at = _future()
        await session.commit()

    outcome_b = await asyncio.to_thread(
        commit_latex_finalization,
        job_id,
        owner_b,
        2,
        {"success": True, "job_id": job_id, "optimized_latex": "winner"},
        b"pdf-b",
        1.1,
    )
    release_upload.set()
    outcome_a = await task_a

    assert outcome_b
    assert outcome_a
    assert outcome_a.replayed is True
    assert outcome_a.canonical_result == outcome_b.canonical_result
    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "completed"
        assert row.state == FinalizationState.COMPLETED.value
    await _cleanup(db_session_factory, job_id, user_id)

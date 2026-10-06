"""A Celery soft timeout during PDF upload remains a compile timeout."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import delete, select

from app.database.models import Compilation, JobFinalization
from app.workers.finalization_arbiter import FinalizationState
from app.workers.latex_worker import commit_latex_finalization


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


@pytest.mark.asyncio
async def test_upload_soft_timeout_is_not_persisted_as_storage_failure(db_session_factory, monkeypatch):
    job_id = f"test_soft_timeout_storage_{uuid4().hex}"
    owner = f"worker:{uuid4()}"
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status="processing"))
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                owner_token=owner,
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    def timeout_upload(*args, **kwargs):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr("app.services.storage_service.upload_compilation_pdf", timeout_upload)
    with pytest.raises(SoftTimeLimitExceeded):
        await asyncio.to_thread(
            commit_latex_finalization,
            job_id,
            owner,
            1,
            {"success": True, "job_id": job_id},
            b"pdf",
            1.0,
        )

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        finalization = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "processing"
        assert compilation.pdf_path is None
        assert finalization.state == FinalizationState.PENDING.value

    async with db_session_factory() as session:
        await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await session.execute(delete(Compilation).where(Compilation.job_id == job_id))
        await session.commit()

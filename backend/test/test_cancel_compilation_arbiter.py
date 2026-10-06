"""Real-DB cancellation/Compilation linearization regressions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database.models import Compilation, JobFinalization
from app.workers.finalization_arbiter import FinalizationOutcome, FinalizationState, request_cancel


def _job_id() -> str:
    return f"test_cancel_compilation_{uuid4().hex}"


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


async def _cleanup(session_factory, job_id: str) -> None:
    async with session_factory() as session:
        await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        await session.execute(delete(Compilation).where(Compilation.job_id == job_id))
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "processing"])
async def test_cancel_queued_or_running_compilation_transitions_both_rows_atomically(db_session_factory, status):
    job_id = _job_id()
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status=status))
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                state=FinalizationState.PENDING.value,
                owner_token="owner-a",
                owner_epoch=1,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.CANCELLED
        await session.commit()

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        finalization = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "cancelled"
        assert compilation.error_message == "cancelled"
        assert finalization.state == FinalizationState.CANCELLED.value
        assert finalization.result_payload["cancelled"] is True
    await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_repeated_cancel_is_idempotent_and_preserves_cancelled_compilation(db_session_factory):
    job_id = _job_id()
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status="processing"))
        await session.commit()

    async with db_session_factory() as session:
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.CANCELLED
        await session.commit()
    async with db_session_factory() as session:
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.CANCELLED
        await session.commit()

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "cancelled"
        assert row.state == FinalizationState.CANCELLED.value
        assert row.result_payload["cancelled"] is True
    await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_cancel_never_overwrites_completed_compilation_winner(db_session_factory):
    job_id = _job_id()
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status="completed"))
        await session.commit()

    async with db_session_factory() as session:
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.ALREADY_COMPLETED
        await session.commit()

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        finalization = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "completed"
        assert finalization is None
    await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_cancel_preserves_failed_compilation_winner(db_session_factory):
    job_id = _job_id()
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status="failed"))
        await session.commit()

    async with db_session_factory() as session:
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.FAILED
        await session.commit()

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        finalization = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "failed"
        assert finalization is None
    await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_cancel_identity_mismatch_fails_closed_without_terminal_write(db_session_factory):
    job_id = _job_id()
    other_job_id = _job_id()
    other_compilation_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(Compilation(id=str(uuid4()), job_id=job_id, status="processing"))
        session.add(Compilation(id=other_compilation_id, job_id=other_job_id, status="processing"))
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                compilation_id=other_compilation_id,
                state=FinalizationState.PENDING.value,
                owner_token="owner-a",
                owner_epoch=1,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        with pytest.raises(RuntimeError, match="identity_mismatch"):
            await request_cancel(session, job_id=job_id)
        await session.rollback()

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        finalization = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        assert compilation.status == "processing"
        assert finalization.state == FinalizationState.PENDING.value
    await _cleanup(db_session_factory, job_id)
    await _cleanup(db_session_factory, other_job_id)

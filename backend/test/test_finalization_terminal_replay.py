"""Terminal finalization replay must not perform implicit I/O after rollback."""

import asyncio

import pytest
from sqlalchemy import select

from app.database.models import JobFinalization
from app.workers.latex_worker import commit_latex_finalization

from .test_worker_typed_finalization import _cleanup, _seed


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["cancelled", "failed", "fenced"])
async def test_existing_terminal_result_survives_rollback(db_session_factory, monkeypatch, state):
    job_id, owner, user_id, _ = await _seed(
        db_session_factory, with_compilation=True, with_resume=False,
    )
    canonical = {"success": False, "job_id": job_id, "failure_code": "prior_terminal"}

    def unexpected_upload(*_args, **_kwargs):
        raise AssertionError("A terminal job must not upload another artifact")

    monkeypatch.setattr("app.services.storage_service.upload_compilation_pdf", unexpected_upload)
    try:
        async with db_session_factory() as session:
            row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
            row.state = state
            row.result_payload = canonical
            await session.commit()
        outcome = await asyncio.to_thread(
            commit_latex_finalization, job_id, owner, 1,
            {"success": True, "job_id": job_id}, b"pdf", 0.2,
        )
        assert not outcome
        assert outcome.canonical_result == canonical
        assert outcome.terminal_status == ("cancelled" if state == "cancelled" else "failed")
    finally:
        await _cleanup(db_session_factory, job_id, user_id)

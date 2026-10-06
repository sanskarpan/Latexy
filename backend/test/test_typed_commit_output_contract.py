"""Red regressions for typed output validation at the durable commit boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.database.models import CoverLetter, JobFinalization, Resume, User
from app.workers.finalization_arbiter import (
    FinalizationOutcome,
    FinalizationState,
    commit_success,
)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


def _job_id(prefix: str = "test_typed_commit") -> str:
    return f"{prefix}_{uuid4().hex}"


async def _cleanup(session_factory, job_id: str, *, user_id: str | None = None) -> None:
    async with session_factory() as session:
        await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
        if user_id is not None:
            await session.execute(delete(CoverLetter).where(CoverLetter.user_id == user_id))
            await session.execute(delete(Resume).where(Resume.user_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_payload",
    [
        {"success": True},
        {
            "success": True,
            "deep_analysis": {
                "overall_score": 90,
                "overall_feedback": "Valid outer fields but missing compatibility DTO",
                "sections": [],
            },
        },
    ],
)
async def test_deep_typed_commit_rejects_missing_or_malformed_output_before_completion(
    db_session_factory, result_payload: dict
):
    job_id = _job_id("test_deep_commit_contract")
    async with db_session_factory() as session:
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                job_type="ats_deep_analysis",
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    try:
        async with db_session_factory() as session:
            outcome = await commit_success(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                result_payload=result_payload,
            )
            await session.commit()
            row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
            assert outcome is FinalizationOutcome.FAILED
            assert row is not None
            assert row.state == FinalizationState.FAILED.value
            assert row.result_payload["success"] is False
            assert row.result_payload["error_code"]
            assert row.compilation_id is None
            assert row.resume_applied is False
            assert row.cover_letter_applied is False
    finally:
        await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_valid_deep_typed_commit_remains_compatible(db_session_factory):
    job_id = _job_id("test_deep_commit_valid")
    valid_analysis = {
        "overall_score": 90,
        "overall_feedback": "Strong match",
        "sections": [],
        "ats_compatibility": {"score": 90, "issues": [], "keyword_gaps": []},
        "job_match": None,
    }
    async with db_session_factory() as session:
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                job_type="ats_deep_analysis",
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()
    try:
        async with db_session_factory() as session:
            outcome = await commit_success(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                result_payload={"success": True, "deep_analysis": valid_analysis},
            )
            await session.commit()
            row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
            assert outcome is FinalizationOutcome.ACCEPTED
            assert row is not None
            assert row.state == FinalizationState.COMPLETED.value
            assert row.result_payload["deep_analysis"]["overall_score"] == 90
    finally:
        await _cleanup(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_cover_letter_typed_commit_rejects_missing_payload_before_cover_mutation(db_session_factory):
    job_id = _job_id("test_cover_commit_contract")
    user_id = str(uuid4())
    resume_id = str(uuid4())
    cover_letter_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(Resume(id=resume_id, user_id=user_id, title="Test", latex_content="source"))
        session.add(
            CoverLetter(
                id=cover_letter_id,
                user_id=user_id,
                resume_id=resume_id,
                latex_content="original",
            )
        )
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type="cover_letter_generation",
                cover_letter_id=cover_letter_id,
                cover_letter_apply_requested=True,
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    try:
        async with db_session_factory() as session:
            outcome = await commit_success(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                result_payload={"success": True},
                cover_letter_id=cover_letter_id,
                cover_letter_user_id=user_id,
                cover_letter_content=r"\\documentclass{letter}",
            )
            await session.commit()
            cover = await session.get(CoverLetter, cover_letter_id)
            row = await session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
            assert outcome is FinalizationOutcome.FAILED
            assert cover is not None
            assert cover.latex_content == "original"
            assert row is not None
            assert row.state == FinalizationState.FAILED.value
            assert row.cover_letter_applied is False
            assert row.result_payload["success"] is False
    finally:
        await _cleanup(db_session_factory, job_id, user_id=user_id)

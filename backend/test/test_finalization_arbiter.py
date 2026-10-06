"""Database contract tests for the durable finalization arbiter."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from app.database.models import Compilation, CoverLetter, JobFinalization, Resume, User
from app.services.storage_service import compilation_pdf_key
from app.workers.finalization_arbiter import (
    MAX_RESULT_BYTES,
    FinalizationOutcome,
    FinalizationState,
    bounded_result_payload,
    commit_failure,
    commit_success,
    ensure_finalization,
    fence_finalization,
    purge_expired_finalizations,
    recover_finalization,
    request_cancel,
)


def _job_id() -> str:
    return f"test_arbiter_{uuid4().hex}"


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=10)


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=10)


async def _seed_row(session_factory, *, job_id: str, owner: str = "owner-a", epoch: int = 1, lease=None):
    async with session_factory() as session:
        row = JobFinalization(
            id=str(uuid4()),
            job_id=job_id,
            owner_token=owner,
            owner_epoch=epoch,
            state=FinalizationState.PENDING.value,
            lease_expires_at=lease or _future(),
            expires_at=_future(),
        )
        session.add(row)
        await session.commit()
    return row


async def _delete_rows(session_factory, *job_ids: str, user_ids: tuple[str, ...] = ()) -> None:
    async with session_factory() as session:
        await session.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(job_ids)))
        if user_ids:
            await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def test_result_payload_is_bounded_and_excludes_task_inputs_and_raw_errors():
    payload = bounded_result_payload(
        "job-1",
        {
            "success": True,
            "optimized_latex": "x" * (MAX_RESULT_BYTES * 2),
            "api_key": "must-not-persist",
            "task_args": {"latex_content": "must-not-persist"},
            "error": "provider internals must-not-persist",
            "ats_details": {"category_scores": 80, "provider_error": "must-not-persist"},
            "cover_letter_latex": r"\documentclass{letter}",
            "cover_letter_id": "cover-1",
            "generation_time": 1.25,
            "tokens_total": 42,
            "latex_content": r"\documentclass{article}",
            "source_format": "docx",
            "file_name": "resume.docx",
            "projects": [{"name": "public-project", "summary": "generated"}],
            "deep_analysis": {
                "overall_score": 91,
                "overall_feedback": "Strong match",
                "sections": [{
                    "name": "Experience",
                    "score": 80,
                    "strengths": ["Clear ownership"],
                    "improvements": ["Add dates"],
                    "rewrite_suggestion": "Add month and year to each role.",
                }],
                "ats_compatibility": {
                    "score": 88,
                    "issues": ["Missing dates"],
                    "keyword_gaps": ["Kubernetes"],
                },
                "job_match": {
                    "score": 84,
                    "matched_requirements": ["Python"],
                    "missing_requirements": ["Kubernetes"],
                    "recommendation": "Add a deployment example.",
                },
                "multi_dim_scores": {"grammar": 92},
                "industry_key": "tech_saas",
                "industry_label": "Technology / SaaS",
                "tokens_used": 12,
                "analysis_time": 1.5,
            },
            "artifacts": {"pdf": "latexy:job:job-1:pdf", "log": "latexy:job:job-1:log"},
            "changes_made": [{"section": "Summary", "reason": "tighten"}],
        },
    )

    assert payload["job_id"] == "job-1"
    assert "optimized_latex" not in payload
    assert "api_key" not in payload
    assert "task_args" not in payload
    assert "error" not in payload
    assert payload["ats_details"] == {"category_scores": 80}
    assert payload["cover_letter_latex"].startswith(r"\documentclass")
    assert payload["cover_letter_id"] == "cover-1"
    assert payload["tokens_total"] == 42
    assert payload["projects"][0]["name"] == "public-project"
    assert payload["deep_analysis"]["overall_score"] == 91
    assert payload["deep_analysis"]["sections"][0]["improvements"] == ["Add dates"]
    assert payload["deep_analysis"]["ats_compatibility"]["keyword_gaps"] == ["Kubernetes"]
    assert payload["deep_analysis"]["job_match"]["recommendation"] == "Add a deployment example."
    assert payload["deep_analysis"]["multi_dim_scores"] == {"grammar": 92}
    assert payload["deep_analysis"]["industry_key"] == "tech_saas"
    assert payload["deep_analysis"]["tokens_used"] == 12
    assert payload["deep_analysis"]["analysis_time"] == 1.5
    assert payload["artifacts"]["pdf"].startswith("latexy:job:")


def test_result_payload_preserves_legacy_deep_section_guidance_aliases():
    payload = bounded_result_payload(
        "job-legacy-deep",
        {
            "success": True,
            "deep_analysis": {
                "overall_score": 80,
                "overall_feedback": "Needs a little more detail.",
                "sections": [{
                    "section_name": "Experience",
                    "score": 80,
                    "strengths": [],
                    "improvements": [],
                    "issues": ["Missing dates"],
                    "suggestions": ["Add dates"],
                }],
                "ats_compatibility": {"score": 80, "issues": [], "keyword_gaps": []},
            },
        },
    )

    section = payload["deep_analysis"]["sections"][0]
    assert section["name"] == section["section_name"] == "Experience"
    assert section["strengths"] == []
    assert section["issues"] == ["Missing dates"]
    assert section["suggestions"] == ["Add dates"]


def test_oversized_generated_text_is_omitted_without_invalid_truncation():
    payload = bounded_result_payload("job-2", {"success": True, "latex_content": "x" * (MAX_RESULT_BYTES * 2)})
    assert "latex_content" not in payload
    assert payload["recovery_complete"] is False
    assert payload["omitted_output_fields"] == ["latex_content"]


def test_compilation_pdf_key_is_owner_scoped_and_safe():
    first = compilation_pdf_key("job-1", "worker-a:epoch-1")
    second = compilation_pdf_key("job-1", "worker-b:epoch-2")

    assert first.startswith("compilations/job-1/finalization-")
    assert first.endswith(".pdf")
    assert first != second
    assert ":" not in first


@pytest.mark.asyncio
async def test_fence_and_failure_capabilities_do_not_override_an_active_owner(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, lease=_future())
    async with db_session_factory() as session:
        assert await fence_finalization(session, job_id=job_id) is FinalizationOutcome.BUSY
        assert (
            await commit_failure(
                session,
                job_id=job_id,
                owner_token="wrong-owner",
                owner_epoch=99,
                failure_code="cleanup",
                allow_fenced=True,
            )
            is FinalizationOutcome.BUSY
        )
        await session.rollback()
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_fence_new_and_existing_tombstone_is_idempotently_fenced(db_session_factory):
    job_id = _job_id()
    async with db_session_factory() as session:
        first = await fence_finalization(session, job_id=job_id, reason_code="dispatch_timeout")
        await session.commit()
    assert first is FinalizationOutcome.FENCED

    async with db_session_factory() as session:
        second = await fence_finalization(session, job_id=job_id, reason_code="retry")
        await session.commit()
        row = await recover_finalization(session, job_id=job_id)
    assert second is FinalizationOutcome.FENCED
    assert row.state == FinalizationState.FENCED.value
    assert row.failure_code == "dispatch_timeout"
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_allow_fenced_commits_failure_only_after_durable_fence(db_session_factory):
    job_id = _job_id()
    async with db_session_factory() as session:
        assert await fence_finalization(session, job_id=job_id) is FinalizationOutcome.FENCED
        await session.commit()

    async with db_session_factory() as session:
        outcome = await commit_failure(
            session,
            job_id=job_id,
            owner_token="stale-worker",
            owner_epoch=99,
            failure_code="worker_failed_after_fence",
            allow_fenced=True,
        )
        await session.commit()
        row = await recover_finalization(session, job_id=job_id)
    assert outcome is FinalizationOutcome.ACCEPTED
    assert row.state == FinalizationState.FAILED.value
    assert row.failure_code == "worker_failed_after_fence"

    async with db_session_factory() as session:
        repeated = await commit_failure(
            session,
            job_id=job_id,
            owner_token="stale-worker",
            owner_epoch=99,
            failure_code="different",
            allow_fenced=True,
        )
        await session.rollback()
    assert repeated is FinalizationOutcome.FAILED
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_stale_owner_cannot_fence_a_live_replacement(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, owner="replacement", epoch=2, lease=_future())
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="old-owner",
            owner_epoch=1,
            result_payload={"success": True},
        )
        await session.rollback()
    assert outcome is FinalizationOutcome.BUSY
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_clock_timestamp_rejects_expired_lease_after_long_transaction_start(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, lease=datetime.now(timezone.utc) + timedelta(seconds=1))
    async with db_session_factory() as session:
        await session.begin()
        await session.execute(text("SELECT 1"))
        await asyncio.sleep(1.25)
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True},
        )
        await session.rollback()
    assert outcome is FinalizationOutcome.FENCED
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_cancel_waits_for_success_row_lock_and_cannot_refund_completed_job(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id)
    locked = asyncio.Event()
    release = asyncio.Event()

    async def successful_worker():
        async with db_session_factory() as session:
            await session.begin()
            await session.scalar(
                select(JobFinalization)
                .where(JobFinalization.job_id == job_id)
                .with_for_update()
            )
            locked.set()
            await release.wait()
            outcome = await commit_success(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                result_payload={"success": True, "optimized_latex": "generated"},
            )
            await session.commit()
            return outcome

    async def cancellation():
        await locked.wait()
        async with db_session_factory() as session:
            outcome_task = asyncio.create_task(request_cancel(session, job_id=job_id))
            # Give asyncpg time to issue the blocked SELECT ... FOR UPDATE;
            # the holder then commits the success while cancellation waits.
            await asyncio.sleep(0.05)
            release.set()
            outcome = await outcome_task
            await session.commit()
            return outcome

    worker_outcome, cancel_outcome = await asyncio.gather(successful_worker(), cancellation())
    assert worker_outcome is FinalizationOutcome.ACCEPTED
    assert cancel_outcome is FinalizationOutcome.ALREADY_COMPLETED
    async with db_session_factory() as session:
        row = await recover_finalization(session, job_id=job_id)
        assert row.state == FinalizationState.COMPLETED.value
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_expired_fence_wins_against_blocked_worker_and_is_not_revived(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, lease=_past())
    locked = asyncio.Event()
    commit_started = asyncio.Event()

    async def stale_worker():
        await locked.wait()
        async with db_session_factory() as session:
            commit_started.set()
            outcome = await commit_success(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                result_payload={"success": True},
            )
            await session.commit()
            return outcome

    async with db_session_factory() as fence_session:
        await fence_session.begin()
        await fence_session.scalar(
            select(JobFinalization).where(JobFinalization.job_id == job_id).with_for_update()
        )
        locked.set()
        worker_task = asyncio.create_task(stale_worker())
        await commit_started.wait()
        fence_outcome = await fence_finalization(fence_session, job_id=job_id)
        await fence_session.commit()
    assert fence_outcome is FinalizationOutcome.FENCED
    assert await worker_task is FinalizationOutcome.FENCED

    async with db_session_factory() as session:
        row = await ensure_finalization(
            session,
            job_id=job_id,
            owner_token="replacement",
            owner_epoch=2,
            lease_expires_at=_future(),
        )
        await session.commit()
        assert row.state == FinalizationState.FENCED.value
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_active_owner_blocks_lower_epoch_and_expired_db_lease_allows_replacement(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, owner="owner-a", epoch=3, lease=_future())
    async with db_session_factory() as session:
        row = await ensure_finalization(
            session,
            job_id=job_id,
            owner_token="owner-b",
            owner_epoch=4,
            lease_expires_at=_future(),
        )
        await session.commit()
        assert row.owner_token == "owner-a"
        assert row.owner_epoch == 3

    async with db_session_factory() as session:
        await session.execute(
            JobFinalization.__table__.update()
            .where(JobFinalization.job_id == job_id)
            .values(lease_expires_at=_past())
        )
        await session.commit()
        row = await ensure_finalization(
            session,
            job_id=job_id,
            owner_token="owner-b",
            owner_epoch=4,
            lease_expires_at=_future(),
        )
        await session.commit()
        assert row.owner_token == "owner-b"
        assert row.owner_epoch == 4
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_db_committed_success_is_immutable_and_recoverable_after_redis_loss(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id)
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True, "optimized_latex": "durable"},
        )
        await session.commit()
        assert outcome is FinalizationOutcome.ACCEPTED

    async with db_session_factory() as session:
        row = await recover_finalization(session, job_id=job_id)
        assert row.state == FinalizationState.COMPLETED.value
        assert row.result_payload["optimized_latex"] == "durable"
        assert await request_cancel(session, job_id=job_id) is FinalizationOutcome.ALREADY_COMPLETED
        assert await fence_finalization(session, job_id=job_id) is FinalizationOutcome.ALREADY_COMPLETED
        assert (
            await commit_failure(
                session,
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                failure_code="late_failure",
                allow_fenced=True,
            )
            is FinalizationOutcome.ALREADY_COMPLETED
        )
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_missing_pdf_fails_before_resume_or_compilation_mutation(db_session_factory):
    job_id = _job_id()
    user_id = str(uuid4())
    resume_id = str(uuid4())
    source = r"\\documentclass{article}"
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(Resume(id=resume_id, user_id=user_id, title="Test", latex_content=source))
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
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
                resume_id=resume_id,
                user_id=user_id,
                resume_apply_requested=True,
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True},
            resume_content=source + "\n%generated",
            resume_id=resume_id,
            resume_user_id=user_id,
            expected_resume_sha256=sha256(source.encode()).hexdigest(),
            require_pdf=True,
        )
        await session.commit()
        assert outcome is FinalizationOutcome.FENCED

    async with db_session_factory() as session:
        resume = await session.get(Resume, resume_id)
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        assert resume.latex_content == source
        assert compilation.status == "processing"
    await _delete_rows(db_session_factory, job_id, user_ids=(user_id,))


@pytest.mark.asyncio
async def test_compilation_pdf_must_match_exact_owner_tokenized_path(db_session_factory):
    job_id = _job_id()
    user_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            Compilation(
                id=str(uuid4()),
                user_id=user_id,
                job_id=job_id,
                status="processing",
            )
        )
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True},
            pdf_path=f"compilations/{job_id}/finalization-{'0' * 32}.pdf",
            pdf_sha256="0" * 64,
            pdf_size=10,
        )
        await session.commit()
    assert outcome is FinalizationOutcome.FENCED
    await _delete_rows(db_session_factory, job_id, user_ids=(user_id,))


@pytest.mark.asyncio
async def test_missing_resume_fails_atomically_without_completing_compilation(db_session_factory):
    job_id = _job_id()
    user_id = str(uuid4())
    resume_id = str(uuid4())
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(
            Compilation(
                id=str(uuid4()),
                user_id=user_id,
                job_id=job_id,
                status="processing",
            )
        )
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
                # Keep the arbiter row FK-valid while the supplied resume_id
                # below deliberately names a missing resume.
                resume_id=None,
                user_id=user_id,
                resume_apply_requested=True,
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True},
            resume_content="generated",
            resume_id=resume_id,
            resume_user_id=user_id,
            expected_resume_sha256=sha256(b"source").hexdigest(),
            pdf_path=compilation_pdf_key(job_id, "owner-a"),
            pdf_sha256="0" * 64,
            pdf_size=10,
        )
        await session.commit()
        assert outcome is FinalizationOutcome.FAILED

    async with db_session_factory() as session:
        compilation = await session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        row = await recover_finalization(session, job_id=job_id)
        assert compilation.status == "failed"
        assert row.state == FinalizationState.FAILED.value
    await _delete_rows(db_session_factory, job_id, user_ids=(user_id,))


@pytest.mark.asyncio
async def test_cover_letter_content_is_applied_in_arbiter_transaction(db_session_factory):
    job_id = _job_id()
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
                latex_content=None,
            )
        )
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
                user_id=user_id,
                cover_letter_id=cover_letter_id,
                cover_letter_apply_requested=True,
            )
        )
        await session.commit()

    generated = r"\\documentclass{letter}"
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True, "cover_letter_latex": generated},
            cover_letter_content=generated,
            cover_letter_id=cover_letter_id,
            cover_letter_user_id=user_id,
        )
        await session.commit()
        assert outcome is FinalizationOutcome.ACCEPTED

    async with db_session_factory() as session:
        cover_letter = await session.get(CoverLetter, cover_letter_id)
        row = await recover_finalization(session, job_id=job_id)
        assert cover_letter.latex_content == generated
        assert row.cover_letter_applied is True
    await _delete_rows(db_session_factory, job_id, user_ids=(user_id,))


@pytest.mark.asyncio
async def test_success_without_compilation_row_is_durable(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id)
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True, "pdf_job_id": job_id},
        )
        await session.commit()
        assert outcome is FinalizationOutcome.ACCEPTED
    async with db_session_factory() as session:
        row = await recover_finalization(session, job_id=job_id)
        assert row.state == FinalizationState.COMPLETED.value
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_oversized_promised_source_fails_terminally_instead_of_completed_empty_recovery(
    db_session_factory,
):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id)
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={"success": True, "latex_content": "x" * (MAX_RESULT_BYTES * 2)},
        )
        await session.commit()
        assert outcome is FinalizationOutcome.FAILED
    async with db_session_factory() as session:
        row = await recover_finalization(session, job_id=job_id)
        assert row.state == FinalizationState.FAILED.value
        assert row.failure_code == "generated_output_too_large"
    await _delete_rows(db_session_factory, job_id)


@pytest.mark.asyncio
async def test_aggregate_payload_overflow_fails_before_resume_mutation(db_session_factory):
    """A hard payload cap must not leave generated DB output half-applied."""
    job_id = _job_id()
    user_id = str(uuid4())
    resume_id = str(uuid4())
    source = "source"
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(Resume(id=resume_id, user_id=user_id, title="Test", latex_content=source))
        await session.flush()
        session.add(
            JobFinalization(
                id=str(uuid4()),
                job_id=job_id,
                user_id=user_id,
                resume_id=resume_id,
                resume_apply_requested=True,
                owner_token="owner-a",
                owner_epoch=1,
                state=FinalizationState.PENDING.value,
                lease_expires_at=_future(),
                expires_at=_future(),
            )
        )
        await session.commit()

    # Each source is individually within MAX_LATEX_BYTES, but together they
    # exceed MAX_RESULT_BYTES and force deterministic payload omission.
    generated = "x" * 300_000
    async with db_session_factory() as session:
        outcome = await commit_success(
            session,
            job_id=job_id,
            owner_token="owner-a",
            owner_epoch=1,
            result_payload={
                "success": True,
                "optimized_latex": generated,
                "cover_letter_latex": generated,
            },
            resume_content="generated",
            resume_id=resume_id,
            resume_user_id=user_id,
            expected_resume_sha256=sha256(source.encode()).hexdigest(),
        )
        await session.commit()
        assert outcome is FinalizationOutcome.FAILED

    async with db_session_factory() as session:
        resume = await session.get(Resume, resume_id)
        row = await recover_finalization(session, job_id=job_id)
        assert resume.latex_content == source
        assert row.state == FinalizationState.FAILED.value
        assert row.failure_code == "recovery_output_too_large"
    await _delete_rows(db_session_factory, job_id, user_ids=(user_id,))


@pytest.mark.asyncio
async def test_expired_recovery_payloads_have_explicit_retention_gc(db_session_factory):
    job_id = _job_id()
    await _seed_row(db_session_factory, job_id=job_id, lease=_past())
    async with db_session_factory() as session:
        await session.execute(
            JobFinalization.__table__.update()
            .where(JobFinalization.job_id == job_id)
            .values(expires_at=_past())
        )
        deleted = await purge_expired_finalizations(session)
        await session.commit()
    # A shared local test database may contain another expired recovery row
    # from an interrupted run; the contract is that this row is reclaimed,
    # not that the batch contains exactly one item.
    assert deleted >= 1
    async with db_session_factory() as session:
        assert await recover_finalization(session, job_id=job_id) is None

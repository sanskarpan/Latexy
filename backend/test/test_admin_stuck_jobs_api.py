"""Admin stuck-job diagnosis and audited remediation actions (#2112)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminAuditLog, Compilation, JobFinalization, Resume
from app.services import admin_stuck_jobs_service

REASON = "Operator confirmed the worker stopped heartbeating"


async def _create_user(db: AsyncSession, *, role: str = "user") -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_stuck_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, true, 'free', 'active', false)"
        ),
        {"id": user_id, "email": email, "name": "Stuck Job User", "role": role},
    )
    await db.commit()
    return user_id, email


async def _session_headers(db: AsyncSession, user_id: str) -> dict[str, str]:
    token = f"test_sess_stuck_{uuid.uuid4().hex}"
    await db.execute(
        text('INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession, *, role: str = "admin") -> dict[str, str]:
    admin_id, _ = await _create_user(db, role=role)
    return await _session_headers(db, admin_id)


async def _resume(db: AsyncSession, *, user_id: str, latex: str = "\\documentclass{article}") -> str:
    resume = Resume(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title="Retry source",
        latex_content=latex,
    )
    db.add(resume)
    await db.commit()
    return str(resume.id)


async def _seed_job(
    db: AsyncSession,
    *,
    job_id: str,
    compilation_status: str = "processing",
    finalization_state: str = "pending",
    age_minutes: int = 40,
    lease_minutes: int | None = None,
    owner_token: str | None = None,
    job_type: str = "latex_compilation",
    user_id: str | None = None,
    resume_id: str | None = None,
    error_message: str | None = None,
    with_compilation: bool = True,
    with_finalization: bool = True,
) -> None:
    now = datetime.now(timezone.utc)
    created = now - timedelta(minutes=age_minutes)
    compilation_id = None
    if with_compilation:
        compilation = Compilation(
            id=str(uuid.uuid4()),
            job_id=job_id,
            user_id=user_id,
            resume_id=resume_id,
            status=compilation_status,
            error_message=error_message,
            created_at=created,
        )
        db.add(compilation)
        compilation_id = compilation.id
    if with_finalization:
        db.add(
            JobFinalization(
                id=str(uuid.uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type=job_type,
                compilation_id=compilation_id,
                resume_id=resume_id,
                owner_token=owner_token,
                owner_epoch=1 if owner_token else 0,
                state=finalization_state,
                lease_expires_at=(now + timedelta(minutes=lease_minutes) if lease_minutes is not None else None),
                expires_at=now + timedelta(days=40),
                created_at=created,
                updated_at=created,
            )
        )
    await db.commit()


async def _audit_rows(db: AsyncSession, job_id: str) -> list[AdminAuditLog]:
    db.expire_all()
    return list(
        (
            await db.execute(
                select(AdminAuditLog)
                .where(
                    AdminAuditLog.target_type == "job",
                    AdminAuditLog.target_id == job_id,
                )
                .order_by(AdminAuditLog.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def _cleanup(db: AsyncSession, *job_ids: str) -> None:
    if job_ids:
        await db.execute(delete(Compilation).where(Compilation.job_id.in_(job_ids)))
        await db.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(job_ids)))
        await db.commit()


def _job_id() -> str:
    return f"test_stuck_{uuid.uuid4().hex}"


async def test_stuck_jobs_are_admin_only(client: AsyncClient, db_session: AsyncSession):
    anonymous = await client.get("/admin/operations/stuck-jobs")
    assert anonymous.status_code == 401

    support_headers = await _admin_headers(db_session, role="support")
    forbidden = await client.get("/admin/operations/stuck-jobs", headers=support_headers)
    assert forbidden.status_code == 403


async def test_diagnosis_detects_stale_and_skips_live_lease_and_terminal(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(db_session)
    user_id, email = await _create_user(db_session)
    resume_id = await _resume(db_session, user_id=user_id)

    stale_id = _job_id()
    live_id = _job_id()
    terminal_id = _job_id()
    recent_id = _job_id()
    await _seed_job(
        db_session,
        job_id=stale_id,
        user_id=user_id,
        resume_id=resume_id,
        error_message="secret worker diagnostic payload",
    )
    await _seed_job(
        db_session,
        job_id=live_id,
        user_id=user_id,
        owner_token="latex-worker-1:opaque-token",
        lease_minutes=10,
    )
    await _seed_job(
        db_session,
        job_id=terminal_id,
        user_id=user_id,
        finalization_state="completed",
    )
    await _seed_job(db_session, job_id=recent_id, user_id=user_id, age_minutes=1)

    try:
        responses: dict[str, dict] = {}
        for job_id in (stale_id, live_id, terminal_id, recent_id):
            response = await client.get(
                "/admin/operations/stuck-jobs",
                params={"min_age_minutes": 15, "limit": 50, "job_id": job_id},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            responses[job_id] = body

        assert responses[stale_id]["items"]
        assert responses[live_id]["items"] == []
        assert responses[recent_id]["items"] == []
        assert responses[terminal_id]["items"]
        terminal = responses[terminal_id]["items"][0]
        assert terminal["terminal"] is True
        assert terminal["recommended_actions"] == []
        assert terminal["reason_code"] == "stale_compilation_after_terminal"

        stale = responses[stale_id]["items"][0]
        assert stale["queue"] == "latex"
        assert stale["age_seconds"] >= 15 * 60
        assert stale["reason_code"] == "queued_unclaimed"
        assert stale["retry_supported"] is True
        assert {"retry", "cancel", "fence"} <= set(stale["recommended_actions"])
        assert "worker" in stale and "lease_expires_at" in stale

        serialized = responses[stale_id]["items"][0]
        for secret in (email, "Stuck Job User", "secret worker diagnostic payload"):
            assert secret not in str(serialized)
    finally:
        await _cleanup(db_session, stale_id, live_id, terminal_id, recent_id)


async def test_cancel_requires_reason_confirmation_and_writes_one_audit_row(
    client: AsyncClient, db_session: AsyncSession
):
    headers = await _admin_headers(db_session)
    job_id = _job_id()
    await _seed_job(db_session, job_id=job_id)
    path = f"/admin/operations/stuck-jobs/{job_id}/cancel"

    try:
        assert (await client.post(path, json={"confirm": True}, headers=headers)).status_code == 422
        assert (await client.post(path, json={"reason": "  ", "confirm": True}, headers=headers)).status_code == 422
        assert (await client.post(path, json={"reason": REASON}, headers=headers)).status_code == 422
        assert (await client.post(path, json={"reason": REASON, "confirm": False}, headers=headers)).status_code == 422

        first = await client.post(
            path,
            json={"reason": f"  {REASON}  ", "confirm": True, "idempotency_key": "cancel-once"},
            headers=headers,
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["changed"] is True
        assert body["action"] == "cancel"
        assert body["after"]["finalization_state"] == "cancelled"
        assert body["after"]["compilation_status"] == "cancelled"

        db_session.expire_all()
        finalization = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        compilation = await db_session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        assert finalization.state == "cancelled"
        assert finalization.cancel_requested is True
        assert compilation.status == "cancelled"

        rows = await _audit_rows(db_session, job_id)
        assert len(rows) == 1
        assert rows[0].action == "job.cancel"
        assert rows[0].reason == REASON
        assert rows[0].before_state["finalization_state"] == "pending"
        assert rows[0].after_state["finalization_state"] == "cancelled"

        second = await client.post(
            path,
            json={"reason": REASON, "confirm": True, "idempotency_key": "cancel-once"},
            headers=headers,
        )
        assert second.status_code == 200
        assert second.json()["changed"] is False
        assert second.json()["idempotent"] is True
        assert len(await _audit_rows(db_session, job_id)) == 1
    finally:
        await _cleanup(db_session, job_id)


async def test_fence_transitions_expired_lease_and_is_idempotent(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(db_session)
    job_id = _job_id()
    await _seed_job(
        db_session,
        job_id=job_id,
        owner_token="latex-worker-9:opaque-token",
        lease_minutes=-5,
    )
    path = f"/admin/operations/stuck-jobs/{job_id}/fence"

    try:
        response = await client.post(path, json={"reason": REASON, "confirm": True}, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["after"]["finalization_state"] == "fenced"
        assert body["after"]["compilation_status"] == "failed"

        db_session.expire_all()
        finalization = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        compilation = await db_session.scalar(select(Compilation).where(Compilation.job_id == job_id))
        assert finalization.state == "fenced"
        assert finalization.failure_code == "admin_fence"
        assert compilation.status == "failed"

        rows = await _audit_rows(db_session, job_id)
        assert len(rows) == 1
        assert rows[0].action == "job.fence"

        repeated = await client.post(path, json={"reason": REASON, "confirm": True}, headers=headers)
        assert repeated.status_code == 200
        assert repeated.json()["changed"] is False
        assert len(await _audit_rows(db_session, job_id)) == 1
    finally:
        await _cleanup(db_session, job_id)


async def test_fence_rejects_live_and_terminal_jobs(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(db_session)
    live_id = _job_id()
    completed_id = _job_id()
    await _seed_job(
        db_session,
        job_id=live_id,
        owner_token="latex-worker-live:opaque-token",
        lease_minutes=10,
    )
    await _seed_job(
        db_session,
        job_id=completed_id,
        compilation_status="completed",
        finalization_state="completed",
    )

    try:
        live = await client.post(
            f"/admin/operations/stuck-jobs/{live_id}/fence",
            json={"reason": REASON, "confirm": True},
            headers=headers,
        )
        assert live.status_code == 409
        assert "live worker lease" in live.text

        completed = await client.post(
            f"/admin/operations/stuck-jobs/{completed_id}/fence",
            json={"reason": REASON, "confirm": True},
            headers=headers,
        )
        assert completed.status_code == 409
        assert await _audit_rows(db_session, live_id) == []
        assert await _audit_rows(db_session, completed_id) == []
    finally:
        await _cleanup(db_session, live_id, completed_id)


async def test_retry_fences_original_and_creates_one_linked_replacement(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    headers = await _admin_headers(db_session)
    owner_id, _ = await _create_user(db_session)
    resume_id = await _resume(db_session, user_id=owner_id, latex="\\section{Secret Source}")
    job_id = _job_id()
    await _seed_job(
        db_session,
        job_id=job_id,
        user_id=owner_id,
        resume_id=resume_id,
        owner_token="latex-worker-2:opaque-token",
        lease_minutes=-5,
    )
    dispatch = AsyncMock(return_value="dispatched")
    monkeypatch.setattr(admin_stuck_jobs_service, "_dispatch_compile_retry", dispatch)
    path = f"/admin/operations/stuck-jobs/{job_id}/retry"

    try:
        response = await client.post(
            path,
            json={"reason": REASON, "confirm": True, "idempotency_key": "retry-once"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        new_job_id = body["new_job_id"]
        assert new_job_id and new_job_id != job_id
        assert body["after"]["retry_job_id"] == new_job_id
        assert body["dispatch_status"] == "dispatched"
        assert dispatch.await_count == 1

        db_session.expire_all()
        source = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
        replacement = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == new_job_id))
        replacement_compilation = await db_session.scalar(select(Compilation).where(Compilation.job_id == new_job_id))
        assert source.state == "fenced"
        assert source.failure_code == "admin_retry"
        assert replacement.state == "pending"
        assert str(replacement.compilation_id) == str(replacement_compilation.id)
        assert str(replacement.resume_id) == resume_id
        assert replacement_compilation.status == "processing"
        assert str(replacement_compilation.resume_id) == resume_id

        rows = await _audit_rows(db_session, job_id)
        assert len(rows) == 1
        assert rows[0].action == "job.retry"
        assert rows[0].after_state["retry_job_id"] == new_job_id
        assert rows[0].event_metadata["new_job_id"] == new_job_id
        assert "Secret Source" not in str(rows[0].before_state) + str(rows[0].after_state)

        repeated = await client.post(
            path,
            json={"reason": REASON, "confirm": True, "idempotency_key": "retry-second-client"},
            headers=headers,
        )
        assert repeated.status_code == 200
        assert repeated.json()["new_job_id"] == new_job_id
        assert repeated.json()["changed"] is False
        assert dispatch.await_count == 1
        assert len(await _audit_rows(db_session, job_id)) == 1
    finally:
        await db_session.execute(delete(Compilation).where(Compilation.job_id.like("test_stuck_%")))
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id.like("test_stuck_%")))
        await db_session.commit()


async def test_retry_can_rebuild_a_missing_compilation_row_from_saved_resume(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    headers = await _admin_headers(db_session)
    owner_id, _ = await _create_user(db_session)
    resume_id = await _resume(db_session, user_id=owner_id)
    job_id = _job_id()
    await _seed_job(
        db_session,
        job_id=job_id,
        with_compilation=False,
        user_id=owner_id,
        resume_id=resume_id,
        job_type="latex_compilation",
    )
    monkeypatch.setattr(admin_stuck_jobs_service, "_dispatch_compile_retry", AsyncMock(return_value="dispatched"))
    try:
        response = await client.post(
            f"/admin/operations/stuck-jobs/{job_id}/retry",
            json={"reason": REASON, "confirm": True},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        new_job_id = response.json()["new_job_id"]
        replacement_compilation = await db_session.scalar(select(Compilation).where(Compilation.job_id == new_job_id))
        assert replacement_compilation is not None
        assert str(replacement_compilation.resume_id) == resume_id
        assert replacement_compilation.status == "processing"
    finally:
        await _cleanup(db_session, job_id)
        await db_session.execute(delete(Compilation).where(Compilation.job_id.like("test_stuck_%")))
        await db_session.execute(delete(JobFinalization).where(JobFinalization.job_id.like("test_stuck_%")))
        await db_session.commit()


async def test_retry_rejects_terminal_and_fenced_jobs(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    headers = await _admin_headers(db_session)
    monkeypatch.setattr(admin_stuck_jobs_service, "_dispatch_compile_retry", AsyncMock(return_value="dispatched"))
    terminal_id = _job_id()
    fenced_id = _job_id()
    await _seed_job(
        db_session,
        job_id=terminal_id,
        compilation_status="completed",
        finalization_state="completed",
    )
    await _seed_job(
        db_session,
        job_id=fenced_id,
        finalization_state="fenced",
    )

    try:
        for job_id in (terminal_id, fenced_id):
            response = await client.post(
                f"/admin/operations/stuck-jobs/{job_id}/retry",
                json={"reason": REASON, "confirm": True},
                headers=headers,
            )
            assert response.status_code == 409
            assert "never retried" in response.text
            assert await _audit_rows(db_session, job_id) == []
    finally:
        await _cleanup(db_session, terminal_id, fenced_id)


async def test_retry_unsupported_family_is_rejected_without_audit(client: AsyncClient, db_session: AsyncSession):
    headers = await _admin_headers(db_session)
    job_id = _job_id()
    await _seed_job(
        db_session,
        job_id=job_id,
        with_compilation=False,
        job_type="llm_optimization",
    )
    try:
        response = await client.post(
            f"/admin/operations/stuck-jobs/{job_id}/retry",
            json={"reason": REASON, "confirm": True},
            headers=headers,
        )
        assert response.status_code == 422
        assert "does not persist enough input" in response.text
        assert await _audit_rows(db_session, job_id) == []
    finally:
        await _cleanup(db_session, job_id)

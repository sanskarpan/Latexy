"""Admin retention policy versioning, previews and guarded purges (#2139)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdminAuditLog,
    GdprLegalHold,
    GdprRequest,
    GdprRequestEvent,
    JobFinalization,
    RenderArtifactManifest,
    RetentionPolicyRevision,
    RetentionRun,
    UsageAnalytics,
)
from app.services import admin_retention_service
from test.test_admin_operations_api import _create_user, _headers

PREFIX = "test_retention_"
MARKER = f"{PREFIX}{uuid.uuid4().hex[:10]}"


def _hours_ago(hours: float, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(hours=hours)


async def _seed_analytics(
    db: AsyncSession,
    *,
    action: str,
    created_at: datetime,
    user_id: str | None = None,
) -> str:
    row = UsageAnalytics(
        id=str(uuid.uuid4()),
        user_id=user_id,
        action=action,
        resource_type="retention_test",
        created_at=created_at,
    )
    db.add(row)
    await db.commit()
    return row.id


async def _seed_finalization(
    db: AsyncSession,
    *,
    job_id: str,
    state: str,
    expires_at: datetime,
    user_id: str | None = None,
) -> str:
    row = JobFinalization(
        id=str(uuid.uuid4()),
        job_id=job_id,
        user_id=user_id,
        owner_token="owner",
        owner_epoch=1,
        state=state,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    return row.id


async def _seed_manifest(
    db: AsyncSession,
    *,
    job_id: str,
    expires_at: datetime,
    created_at: datetime | None = None,
) -> str:
    artifact_id = uuid.uuid4().hex * 2
    db.add(
        RenderArtifactManifest(
            artifact_id=artifact_id[:64],
            job_id=job_id,
            owner_epoch=1,
            owner_token_sha256="c" * 64,
            owner_scope_kind="user",
            manifest_key=f"{PREFIX}manifests/{artifact_id}.json",
            pdf_key=f"{PREFIX}pdf/{artifact_id}.pdf",
            payload={"pdf": {"key": f"{PREFIX}pdf/{artifact_id}.pdf", "size": 10}},
            created_at=created_at or expires_at - timedelta(days=1),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return artifact_id[:64]


async def _seed_hold(db: AsyncSession, user_id: str) -> None:
    db.add(
        GdprLegalHold(
            id=str(uuid.uuid4()),
            user_id=user_id,
            reason="Litigation hold for retention test",
            placed_by="test-admin",
            placed_email="admin@example.com",
            active=True,
        )
    )
    await db.commit()


async def _seed_export(
    db: AsyncSession,
    *,
    user_id: str | None,
    expired_hours_ago: float,
    token_hash: str | None = "d" * 64,
) -> str:
    row = GdprRequest(
        id=str(uuid.uuid4()),
        user_id=user_id,
        request_type="export",
        status="ready",
        export_token_hash=token_hash,
        export_issued_at=datetime.now(timezone.utc) - timedelta(hours=expired_hours_ago + 1),
        export_expires_at=_hours_ago(expired_hours_ago),
    )
    db.add(row)
    await db.commit()
    return str(row.id)


@pytest.fixture(autouse=True)
async def reset_retention_state(db_session: AsyncSession):
    await db_session.execute(text("DELETE FROM retention_runs"))
    await db_session.execute(
        text("DELETE FROM usage_analytics WHERE action LIKE :marker"),
        {"marker": f"{PREFIX}%"},
    )
    await db_session.execute(
        text("DELETE FROM render_artifact_manifests WHERE job_id LIKE :marker"),
        {"marker": f"{PREFIX}%"},
    )
    await db_session.execute(
        text("DELETE FROM job_finalizations WHERE job_id LIKE :marker"),
        {"marker": f"{PREFIX}%"},
    )
    await db_session.execute(
        text(
            "UPDATE retention_policies SET configured_hours = CASE data_class "
            "WHEN 'pdfs' THEN 24 WHEN 'job_finalizations' THEN 24 "
            "WHEN 'analytics' THEN 24 WHEN 'audit' THEN 61320 ELSE 720 END, "
            "schedule_hours = 24, enabled = true"
        )
    )
    await db_session.commit()
    yield


def _run_url(data_class: str, action: str) -> str:
    return f"/admin/operations/retention/{data_class}/{action}"


async def test_retention_surface_is_admin_only(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _headers(db_session, "admin")
    user = await _headers(db_session, "user")
    support = await _headers(db_session, "support")

    assert (await client.get("/admin/operations/retention")).status_code == 401
    assert (await client.get("/admin/operations/retention", headers=user)).status_code == 403
    assert (await client.get("/admin/operations/retention", headers=support)).status_code == 403
    assert (await client.get("/admin/operations/retention", headers=admin)).status_code == 200

    payload = {"reason": "Retention review", "confirm": True}
    assert (await client.post(_run_url("analytics", "purge"), json=payload)).status_code == 401
    denied = await client.post(_run_url("analytics", "purge"), headers=user, json=payload)
    assert denied.status_code == 403


async def test_overview_reports_classes_counts_and_schedule(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    response = await client.get("/admin/operations/retention", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["minimum_cohort_size"] == 5
    assert [item["data_class"] for item in body["classes"]] == list(
        admin_retention_service.DATA_CLASS_ORDER
    )
    classes = {item["data_class"]: item for item in body["classes"]}
    assert classes["audit"]["purge_mode"] == "immutable"
    assert classes["audit"]["purge_supported"] is False
    assert classes["pdfs"]["purge_mode"] == "delete"
    assert classes["exports"]["purge_mode"] == "scrub"
    for item in body["classes"]:
        assert "configured_hours" in item and "effective_hours" in item
        assert "next_run_at" in item
        assert item["boundary"]["cutoff_at"]
        assert item["counts"]["eligible"] >= 0
        assert "protected_active_jobs" in item["counts"]
        assert "protected_legal_hold" in item["counts"]


def test_boundary_age_is_inclusive() -> None:
    assert admin_retention_service.is_eligible(86399, 86400) is False
    assert admin_retention_service.is_eligible(86400, 86400) is True
    assert admin_retention_service.is_eligible(86401, 86400) is True


async def test_dry_run_uses_boundary_and_deletes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    inside = await _seed_analytics(
        db_session, action=f"{MARKER}_inside", created_at=now - timedelta(hours=23, minutes=59)
    )
    exact = await _seed_analytics(
        db_session, action=f"{MARKER}_exact", created_at=now - timedelta(hours=24)
    )
    outside = await _seed_analytics(
        db_session, action=f"{MARKER}_outside", created_at=now - timedelta(hours=25)
    )

    policy = await admin_retention_service.get_overview(db_session)
    analytics_policy = next(item for item in policy["classes"] if item["data_class"] == "analytics")
    result = await admin_retention_service.execute_run(
        db_session,
        data_class="analytics",
        dry_run=True,
        reason="Boundary preview",
        confirm=False,
        limit=100,
        idempotency_key=None,
        actor=admin_retention_service.AdminActor(
            user_id=uuid.uuid4().hex, email="admin@example.com", role="admin"
        ),
        now=now,
    )
    assert result["dry_run"] is True
    assert result["affected"] == 0
    assert result["counts"]["eligible"] >= 2
    assert result["would_affect"] >= 2
    assert result["effective_hours"] == analytics_policy["effective_hours"]

    rows = (
        await db_session.execute(
            select(UsageAnalytics.id).where(
                UsageAnalytics.id.in_([inside, exact, outside])
            )
        )
    ).scalars().all()
    assert len(rows) == 3


async def test_purge_analytics_is_bounded_and_keeps_legal_hold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    held_user, _ = await _create_user(db_session)
    await _seed_hold(db_session, held_user)
    old_ids = [
        await _seed_analytics(
            db_session, action=f"{MARKER}_old_{index}", created_at=_hours_ago(24 * 400)
        )
        for index in range(3)
    ]
    held_id = await _seed_analytics(
        db_session,
        action=f"{MARKER}_held",
        created_at=_hours_ago(24 * 400),
        user_id=held_user,
    )
    recent_id = await _seed_analytics(
        db_session, action=f"{MARKER}_recent", created_at=_hours_ago(1)
    )

    preview = await client.post(
        _run_url("analytics", "dry-run"),
        headers=admin,
        json={"reason": "Retention review preview", "limit": 2},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected"] == 0
    assert preview.json()["counts"]["eligible"] >= 2
    still_there = (
        await db_session.execute(
            select(UsageAnalytics.id).where(
                UsageAnalytics.id.in_([*old_ids, held_id, recent_id])
            )
        )
    ).scalars().all()
    assert len(still_there) == 5

    response = await client.post(
        _run_url("analytics", "purge"),
        headers=admin,
        json={"reason": "Retention review", "confirm": True, "limit": 2},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "purge"
    assert result["affected"] == 2
    assert result["has_more"] is True
    assert result["counts"]["protected_legal_hold"] >= 1

    remaining = set(
        (
            await db_session.execute(
                select(UsageAnalytics.id).where(
                    UsageAnalytics.id.in_([*old_ids, held_id, recent_id])
                )
            )
        ).scalars().all()
    )
    assert len(remaining) == 3
    assert held_id in remaining
    assert recent_id in remaining
    assert len(set(old_ids) & remaining) == 1

    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "retention.purge")
        )
    ).scalars().all()
    assert any(row.target_id == "analytics" and "Retention review" in (row.reason or "") for row in audit)

    overview = (
        await client.get("/admin/operations/retention", headers=admin)
    ).json()
    assert overview["aggregate_only"] is True
    analytics = next(item for item in overview["classes"] if item["data_class"] == "analytics")
    assert analytics["last_run"]["mode"] == "purge"
    assert analytics["last_run"]["affected"] == 2
    assert analytics["next_run_at"] is not None


async def test_active_jobs_and_legal_holds_block_pdf_and_finalization_purge(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    held_user, _ = await _create_user(db_session)
    await _seed_hold(db_session, held_user)
    old = datetime.now(timezone.utc) - timedelta(days=3)

    eligible_job = f"{PREFIX}pdf_eligible"
    await _seed_finalization(db_session, job_id=eligible_job, state="completed", expires_at=old)
    await _seed_manifest(db_session, job_id=eligible_job, expires_at=old)

    active_job = f"{PREFIX}pdf_active"
    await _seed_finalization(db_session, job_id=active_job, state="pending", expires_at=old)
    await _seed_manifest(db_session, job_id=active_job, expires_at=old)

    held_job = f"{PREFIX}pdf_held"
    await _seed_finalization(
        db_session, job_id=held_job, state="completed", expires_at=old, user_id=held_user
    )
    await _seed_manifest(db_session, job_id=held_job, expires_at=old)

    pdfs = await client.post(
        _run_url("pdfs", "purge"),
        headers=admin,
        json={"reason": "PDF retention review", "confirm": True, "limit": 100},
    )
    assert pdfs.status_code == 200, pdfs.text
    pdf_body = pdfs.json()
    assert pdf_body["affected"] >= 1
    assert pdf_body["counts"]["protected_active_jobs"] >= 1
    assert pdf_body["counts"]["protected_legal_hold"] >= 1

    manifestations = set(
        (
            await db_session.execute(
                select(RenderArtifactManifest.job_id).where(
                    RenderArtifactManifest.job_id.in_([eligible_job, active_job, held_job])
                )
            )
        ).scalars().all()
    )
    assert eligible_job not in manifestations
    assert active_job in manifestations
    assert held_job in manifestations

    finalizations = await client.post(
        _run_url("job_finalizations", "purge"),
        headers=admin,
        json={"reason": "Finalization retention review", "confirm": True, "limit": 100},
    )
    assert finalizations.status_code == 200, finalizations.text
    final_body = finalizations.json()
    assert final_body["counts"]["protected_active_jobs"] >= 1
    assert final_body["counts"]["protected_legal_hold"] >= 1

    states = {
        row.job_id: row.state
        for row in (
            await db_session.execute(
                select(JobFinalization).where(
                    JobFinalization.job_id.in_([eligible_job, active_job, held_job])
                )
            )
        ).scalars().all()
    }
    assert eligible_job not in states
    assert states.get(active_job) == "pending"
    assert states.get(held_job) == "completed"


async def test_exports_are_scrubbed_not_deleted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    held_user, _ = await _create_user(db_session)
    await _seed_hold(db_session, held_user)
    expired_id = await _seed_export(db_session, user_id=None, expired_hours_ago=24 * 40)
    held_id = await _seed_export(db_session, user_id=held_user, expired_hours_ago=24 * 40)
    recent_id = await _seed_export(db_session, user_id=None, expired_hours_ago=1)

    response = await client.post(
        _run_url("exports", "purge"),
        headers=admin,
        json={"reason": "Expired export link cleanup", "confirm": True, "limit": 100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["affected"] >= 1

    rows = {
        str(row.id): row
        for row in (
            await db_session.execute(
                select(GdprRequest).where(GdprRequest.id.in_([expired_id, held_id, recent_id]))
            )
        ).scalars().all()
    }
    assert set(rows) == {expired_id, held_id, recent_id}
    assert rows[expired_id].export_token_hash is None
    assert rows[held_id].export_token_hash is not None
    assert rows[recent_id].export_token_hash is not None
    events = (
        await db_session.execute(
            select(GdprRequestEvent).where(GdprRequestEvent.request_id == expired_id)
        )
    ).scalars().all()
    assert any(event.event == "export.expired_scrubbed" for event in events)


async def test_audit_is_previewable_but_refuses_purge(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    response = await client.post(
        _run_url("audit", "purge"),
        headers=admin,
        json={"reason": "Audit retention review", "confirm": True},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "retention_class_immutable"

    refused = (
        await db_session.execute(
            select(RetentionRun).where(
                RetentionRun.data_class == "audit", RetentionRun.status == "refused"
            )
        )
    ).scalars().all()
    assert refused
    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "retention.purge.refused",
                AdminAuditLog.target_id == "audit",
            )
        )
    ).scalars().all()
    assert audit


async def test_policy_change_requires_confirmation_and_is_versioned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    overview = (
        await client.get("/admin/operations/retention", headers=admin)
    ).json()
    current = next(item for item in overview["classes"] if item["data_class"] == "analytics")

    missing_confirm = await client.patch(
        "/admin/operations/retention/analytics",
        headers=admin,
        json={
            "retention_hours": 48,
            "schedule_hours": 12,
            "enabled": True,
            "expected_version": current["version"],
            "reason": "Policy review",
        },
    )
    assert missing_confirm.status_code == 422

    stale = await client.patch(
        "/admin/operations/retention/analytics",
        headers=admin,
        json={
            "retention_hours": 48,
            "schedule_hours": 12,
            "enabled": True,
            "expected_version": current["version"] + 100,
            "reason": "Policy review",
            "confirm": True,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "retention_policy_version_conflict"

    updated = await client.patch(
        "/admin/operations/retention/analytics",
        headers=admin,
        json={
            "retention_hours": 48,
            "schedule_hours": 12,
            "enabled": True,
            "expected_version": current["version"],
            "reason": "Policy review",
            "confirm": True,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["configured_hours"] == 48
    assert body["schedule_hours"] == 12
    assert body["version"] == current["version"] + 1

    revisions = (
        await db_session.execute(
            select(RetentionPolicyRevision).where(
                RetentionPolicyRevision.data_class == "analytics"
            )
        )
    ).scalars().all()
    assert any(revision.version == body["version"] for revision in revisions)
    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "retention.policy.updated")
        )
    ).scalars().all()
    assert any(row.target_id == "analytics" for row in audit)


async def test_purge_requires_confirmation_and_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    no_confirm = await client.post(
        _run_url("analytics", "purge"),
        headers=admin,
        json={"reason": "Retention review"},
    )
    assert no_confirm.status_code == 422
    no_reason = await client.post(
        _run_url("analytics", "purge"),
        headers=admin,
        json={"confirm": True},
    )
    assert no_reason.status_code == 422


async def test_idempotency_replays_without_second_mutation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _headers(db_session, "admin")
    await _seed_analytics(
        db_session, action=f"{MARKER}_idem", created_at=_hours_ago(48)
    )
    body = {
        "reason": "Idempotent retention purge",
        "confirm": True,
        "limit": 100,
        "idempotency_key": f"retention-{uuid.uuid4().hex}",
    }
    first = await client.post(_run_url("analytics", "purge"), headers=admin, json=body)
    assert first.status_code == 200, first.text
    second = await client.post(_run_url("analytics", "purge"), headers=admin, json=body)
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["id"] == first.json()["id"]


async def test_concurrent_run_is_refused(
    client: AsyncClient, db_session: AsyncSession, db_session_factory
) -> None:
    admin = await _headers(db_session, "admin")
    async with db_session_factory() as blocker:
        acquired = await blocker.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtext('retention:analytics'))")
        )
        assert acquired is True
        response = await client.post(
            _run_url("analytics", "dry-run"),
            headers=admin,
            json={"reason": "Concurrent preview"},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "retention_run_in_progress"
        await blocker.rollback()

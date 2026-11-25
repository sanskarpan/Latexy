"""GDPR export and deletion workflow (#2130).

Covers signed/expired exports, identity verification, least-privilege ownership,
re-authentication, legal review, legal-hold blocking, partial per-table failure,
idempotent retries, append-only history, audit rows and secret exclusion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.services import gdpr_service

CONFIRM = gdpr_service.DELETION_CONFIRMATION


async def _create_user(
    db: AsyncSession,
    *,
    role: str = "user",
    verified: bool = True,
    name: str = "GDPR Fixture User",
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"test_gdpr_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, role, email_verified, "
            "subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, :name, :role, :verified, 'free', 'active', false)"
        ),
        {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "verified": verified,
        },
    )
    await db.commit()
    return user_id, email


async def _session_headers(
    db: AsyncSession,
    user_id: str,
    *,
    created_at: datetime | None = None,
) -> dict[str, str]:
    token = f"test_sess_gdpr_{uuid.uuid4().hex}"
    await db.execute(
        text(
            'INSERT INTO session (id, "userId", "expiresAt", token, "createdAt") '
            "VALUES (:id, :uid, :exp, :tok, :created)"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "tok": token,
            "created": created_at or datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return {"Authorization": f"Bearer {token}"}


async def _admin_headers(db: AsyncSession) -> tuple[dict[str, str], str]:
    user_id, _ = await _create_user(db, role="admin", name="GDPR Admin")
    return await _session_headers(db, user_id), user_id


async def _seed_owned_data(db: AsyncSession, user_id: str) -> str:
    resume = models.Resume(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title="GDPR Export Resume",
        latex_content="\\documentclass{article}\\begin{document}Hello\\end{document}",
        structured_content={"summary": "candidate", "api_token": "resume-secret-token"},
        resume_settings={"font": "serif", "github_token": "resume-github-secret"},
    )
    db.add(resume)
    db.add(
        models.Payment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider="dodo",
            provider_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
            amount=49900,
            currency="INR",
            status="paid",
        )
    )
    db.add(
        models.UsageAnalytics(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action="compile",
            resource_type="resume",
            event_metadata={"token": "usage-secret-token"},
        )
    )
    db.add(
        models.UserAPIKey(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider="openai",
            encrypted_key="encrypted-byok-secret-value",
            key_name="fixture",
        )
    )
    await db.execute(
        text(
            'INSERT INTO passkey (id, "publicKey", "userId", "credentialID", counter, '
            '"deviceType", "backedUp") '
            "VALUES (:id, 'pk-public', :uid, :credential, 0, 'singleDevice', false)"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id, "credential": f"pk_{uuid.uuid4().hex}"},
    )
    await db.execute(
        text(
            'INSERT INTO verification (id, identifier, value, "expiresAt") '
            "SELECT :id, email, 'reset-token', now() + interval '1 hour' "
            "FROM users WHERE id = :uid"
        ),
        {"id": str(uuid.uuid4()), "uid": user_id},
    )
    await db.execute(
        text('INSERT INTO "twoFactor" (id, "userId", secret, "backupCodes") VALUES (:id, :uid, :secret, :backup)'),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            # The schema stores encrypted hex material, not raw TOTP values.
            "secret": "ab" * 32,
            "backup": "cd" * 32,
        },
    )
    await db.execute(
        text("UPDATE users SET github_access_token = :token, user_metadata = CAST(:metadata AS jsonb) WHERE id = :uid"),
        {
            "token": "github-secret-access-token",
            "metadata": '{"zotero_token": "zotero-secret-token", "theme": "dark"}',
            "uid": user_id,
        },
    )
    await db.commit()
    return resume.id


async def _request_deletion(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post(
        "/account/gdpr/deletion",
        json={"confirmation": CONFIRM, "reason": "Please erase my account"},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _approve(client: AsyncClient, admin_headers: dict[str, str], request_id: str) -> dict[str, Any]:
    response = await client.post(
        f"/admin/gdpr/requests/{request_id}/review",
        json={"decision": "approved", "note": "Counsel approved erasure"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _execute(client: AsyncClient, admin_headers: dict[str, str], request_id: str) -> Any:
    return await client.post(
        f"/admin/gdpr/requests/{request_id}/execute",
        headers=admin_headers,
    )


async def test_export_is_signed_time_limited_and_owner_only(client: AsyncClient, db_session: AsyncSession):
    user_id, email = await _create_user(db_session)
    await _seed_owned_data(db_session, user_id)
    headers = await _session_headers(db_session, user_id)

    policy = await client.get("/account/gdpr/policy", headers=headers)
    assert policy.status_code == 200
    categories = {item["category"] for item in policy.json()["retention_exceptions"]}
    assert {"invoices_and_payments", "legal_hold", "security_audit"} <= categories

    created = await client.post("/account/gdpr/exports", headers=headers)
    assert created.status_code == 202, created.text
    body = created.json()
    request_id = body["request"]["id"]
    token = body["download_token"]
    assert body["request"]["status"] == "ready"
    assert body["request"]["identity_verified"] is True
    assert token

    downloaded = await client.get(
        f"/account/gdpr/exports/{request_id}/download",
        headers={**headers, "X-GDPR-Export-Token": token},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["cache-control"] == "no-store"
    envelope = downloaded.json()
    digest, signature = gdpr_service.sign_export_data(envelope["data"])
    assert envelope["manifest"]["data_sha256"] == digest
    assert envelope["manifest"]["signature"] == signature
    assert envelope["data"]["profile"]["email"] == email
    assert envelope["data"]["resumes"][0]["latex_content"].startswith("\\documentclass")
    assert envelope["data"]["payments"][0]["amount"] == 49900
    assert envelope["data"]["usage"]["recent"][0]["action"] == "compile"
    assert envelope["data"]["resume_files"] == []

    rendered = downloaded.text
    for secret in (
        "github-secret-access-token",
        "resume-secret-token",
        "resume-github-secret",
        "usage-secret-token",
        "encrypted-byok-secret-value",
        "zotero-secret-token",
    ):
        assert secret not in rendered
    assert "profile" in rendered and "dark" in rendered

    missing_header = await client.get(
        f"/account/gdpr/exports/{request_id}/download",
        headers=headers,
    )
    assert missing_header.status_code == 400, missing_header.text
    assert missing_header.json()["detail"]["code"] == "missing_export_token"

    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    rejected = await client.get(
        f"/account/gdpr/exports/{request_id}/download",
        headers={**headers, "X-GDPR-Export-Token": tampered},
    )
    assert rejected.status_code == 403, rejected.text

    other_id, _ = await _create_user(db_session)
    other_headers = await _session_headers(db_session, other_id)
    foreign = await client.get(
        f"/account/gdpr/exports/{request_id}/download",
        headers={**other_headers, "X-GDPR-Export-Token": token},
    )
    assert foreign.status_code == 404, foreign.text

    await db_session.execute(
        text("UPDATE gdpr_requests SET export_expires_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": request_id},
    )
    await db_session.commit()
    expired = await client.get(
        f"/account/gdpr/exports/{request_id}/download",
        headers={**headers, "X-GDPR-Export-Token": token},
    )
    assert expired.status_code == 410, expired.text
    assert expired.json()["detail"]["code"] == "export_expired"


async def test_export_requires_verified_email(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _create_user(db_session, verified=False)
    headers = await _session_headers(db_session, user_id)
    response = await client.post("/account/gdpr/exports", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "identity_verification_required"


async def test_deletion_requires_fresh_reauth_and_confirmation(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _create_user(db_session)
    stale = await _session_headers(
        db_session,
        user_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    stale_response = await client.post(
        "/account/gdpr/deletion",
        json={"confirmation": CONFIRM},
        headers=stale,
    )
    assert stale_response.status_code == 403, stale_response.text
    assert stale_response.json()["detail"]["code"] == "reauth_required"

    fresh = await _session_headers(db_session, user_id)
    wrong = await client.post(
        "/account/gdpr/deletion",
        json={"confirmation": "delete"},
        headers=fresh,
    )
    assert wrong.status_code == 422, wrong.text
    assert wrong.json()["detail"]["code"] == "confirmation_mismatch"

    unverified_id, _ = await _create_user(db_session, verified=False)
    unverified = await _session_headers(db_session, unverified_id)
    blocked = await client.post(
        "/account/gdpr/deletion",
        json={"confirmation": CONFIRM},
        headers=unverified,
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "identity_verification_required"

    count = await db_session.scalar(
        text("SELECT count(*) FROM gdpr_requests WHERE user_id IN (CAST(:uid AS uuid), CAST(:uid2 AS uuid))"),
        {"uid": user_id, "uid2": unverified_id},
    )
    assert int(count or 0) == 0


async def test_deletion_review_audit_idempotency_and_retention(client: AsyncClient, db_session: AsyncSession):
    user_id, email = await _create_user(db_session)
    resume_id = await _seed_owned_data(db_session, user_id)
    headers = await _session_headers(db_session, user_id)
    admin_headers, admin_id = await _admin_headers(db_session)

    first = await _request_deletion(client, headers)
    assert first["created"] is True
    request_id = first["request"]["id"]
    assert first["request"]["status"] == "legal_review"
    assert first["request"]["legal_review_status"] == "pending"

    second = await _request_deletion(client, headers)
    assert second["created"] is False
    assert second["request"]["id"] == request_id
    request_count = await db_session.scalar(
        text("SELECT count(*) FROM gdpr_requests WHERE user_id = CAST(:uid AS uuid)"),
        {"uid": user_id},
    )
    assert int(request_count or 0) == 1

    forbidden = await client.get("/admin/gdpr/requests", headers=headers)
    assert forbidden.status_code == 403, forbidden.text

    listing = await client.get("/admin/gdpr/requests", params={"request_type": "deletion"}, headers=admin_headers)
    assert listing.status_code == 200, listing.text
    item = next(row for row in listing.json()["items"] if row["id"] == request_id)
    assert item["user_email_masked"] and item["user_email_masked"] != email
    assert email not in listing.text
    assert "export_token_hash" not in listing.text

    approved = await _approve(client, admin_headers, request_id)
    assert approved["status"] == "approved"

    audit_rows = (
        (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.action == "gdpr.deletion.approved",
                    models.AdminAuditLog.target_id == request_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].actor_user_id == admin_id
    assert audit_rows[0].event_metadata["gdpr_request_id"] == request_id
    assert audit_rows[0].event_metadata["target_user_id"] == user_id

    executed = await _execute(client, admin_headers, request_id)
    assert executed.status_code == 200, executed.text
    completed = executed.json()
    assert completed["status"] == "completed"
    by_table = {row["table"]: row for row in completed["table_results"]}
    assert by_table["resumes"]["status"] == "completed"
    assert by_table["payments"]["status"] == "retained"
    assert by_table["admin_audit_log"]["status"] == "retained"

    assert await db_session.scalar(select(models.Resume.id).where(models.Resume.id == resume_id)) is None
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM payments WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
        == 1
    )
    assert (
        await db_session.scalar(
            text('SELECT count(*) FROM "twoFactor" WHERE "userId" = :uid'),
            {"uid": user_id},
        )
        == 0
    )
    assert (
        await db_session.scalar(
            text('SELECT count(*) FROM passkey WHERE "userId" = :uid'),
            {"uid": user_id},
        )
        == 0
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM verification WHERE identifier = :email"),
            {"email": email},
        )
        == 0
    )
    anonymized = (
        await db_session.execute(
            text("SELECT email, name, github_access_token, user_metadata FROM users WHERE id = :uid"),
            {"uid": user_id},
        )
    ).fetchone()
    assert anonymized is not None
    assert anonymized[0].startswith("deleted+")
    assert anonymized[1] is None
    assert anonymized[2] is None
    assert anonymized[3] is None

    completed_audit = (
        (
            await db_session.execute(
                select(models.AdminAuditLog).where(
                    models.AdminAuditLog.action == "gdpr.deletion.completed",
                    models.AdminAuditLog.target_id == request_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(completed_audit) == 1

    attempts_before = completed["attempts"]
    replay = await _execute(client, admin_headers, request_id)
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "completed"
    assert replay.json()["attempts"] == attempts_before


async def test_admin_cannot_review_own_deletion_request(client: AsyncClient, db_session: AsyncSession):
    admin_headers, _ = await _admin_headers(db_session)
    request_id = (await _request_deletion(client, admin_headers))["request"]["id"]
    self_review = await client.post(
        f"/admin/gdpr/requests/{request_id}/review",
        json={"decision": "approved", "note": "Approving my own erasure"},
        headers=admin_headers,
    )
    assert self_review.status_code == 403, self_review.text
    assert self_review.json()["detail"]["code"] == "self_review_forbidden"


async def test_legal_hold_blocks_deletion_until_released(client: AsyncClient, db_session: AsyncSession):
    user_id, email = await _create_user(db_session)
    resume_id = await _seed_owned_data(db_session, user_id)
    headers = await _session_headers(db_session, user_id)
    admin_headers, _ = await _admin_headers(db_session)

    request_id = (await _request_deletion(client, headers))["request"]["id"]
    await _approve(client, admin_headers, request_id)

    hold = await client.post(
        "/admin/gdpr/legal-holds",
        json={"user_id": user_id, "reason": "Litigation hold from counsel"},
        headers=admin_headers,
    )
    assert hold.status_code == 201, hold.text
    hold_id = hold.json()["id"]

    blocked = await _execute(client, admin_headers, request_id)
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "legal_hold"
    assert detail["request"]["status"] == "blocked"
    assert detail["request"]["legal_hold_active"] is True

    assert await db_session.scalar(select(models.Resume.id).where(models.Resume.id == resume_id)) == resume_id
    current_email = await db_session.scalar(text("SELECT email FROM users WHERE id = :uid"), {"uid": user_id})
    assert current_email == email

    released = await client.post(
        f"/admin/gdpr/legal-holds/{hold_id}/release",
        json={"reason": "Counsel released the hold"},
        headers=admin_headers,
    )
    assert released.status_code == 200, released.text
    assert released.json()["active"] is False

    executed = await _execute(client, admin_headers, request_id)
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    assert await db_session.scalar(select(models.Resume.id).where(models.Resume.id == resume_id)) is None


async def test_partial_failure_is_reported_and_retry_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    user_id, _ = await _create_user(db_session)
    await _seed_owned_data(db_session, user_id)
    headers = await _session_headers(db_session, user_id)
    admin_headers, _ = await _admin_headers(db_session)

    request_id = (await _request_deletion(client, headers))["request"]["id"]
    await _approve(client, admin_headers, request_id)

    real_steps = gdpr_service.DELETION_STEPS
    broken = gdpr_service.DeletionStep(
        key="broken_probe",
        table="gdpr_missing_probe_table",
        action="delete",
        sql="DELETE FROM gdpr_missing_probe_table WHERE user_id = CAST(:uid AS uuid)",
        description="Injected failure for partial-failure coverage",
    )
    monkeypatch.setattr(gdpr_service, "DELETION_STEPS", real_steps + (broken,))

    failed = await _execute(client, admin_headers, request_id)
    assert failed.status_code == 200, failed.text
    body = failed.json()
    assert body["status"] == "failed"
    assert body["failure_code"] == "partial_failure"
    failed_rows = [row for row in body["table_results"] if row["status"] == "failed"]
    assert any(row["table"] == "gdpr_missing_probe_table" for row in failed_rows)
    assert any(row["table"] == "resumes" and row["status"] == "completed" for row in body["table_results"])
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM resumes WHERE user_id = CAST(:uid AS uuid)"),
            {"uid": user_id},
        )
        == 0
    )

    monkeypatch.setattr(gdpr_service, "DELETION_STEPS", real_steps)
    retried = await _execute(client, admin_headers, request_id)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "completed"
    assert retried.json()["attempts"] == 2
    assert all(row["status"] != "failed" for row in retried.json()["table_results"])


async def test_request_events_and_requests_are_append_only(client: AsyncClient, db_session: AsyncSession):
    user_id, _ = await _create_user(db_session)
    headers = await _session_headers(db_session, user_id)
    request_id = (await _request_deletion(client, headers))["request"]["id"]

    event_id = await db_session.scalar(
        text("SELECT id FROM gdpr_request_events WHERE request_id = :rid LIMIT 1"),
        {"rid": request_id},
    )
    assert event_id is not None

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE gdpr_request_events SET event = 'tampered' WHERE id = :id"),
                {"id": event_id},
            )

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM gdpr_requests WHERE id = :id"),
                {"id": request_id},
            )

    row = (
        await db_session.execute(
            text("SELECT status FROM gdpr_requests WHERE id = :id"),
            {"id": request_id},
        )
    ).fetchone()
    assert row is not None
    assert row[0] == "legal_review"
    event = (
        await db_session.execute(
            text("SELECT event FROM gdpr_request_events WHERE id = :id"),
            {"id": event_id},
        )
    ).fetchone()
    assert event is not None
    assert event[0] != "tampered"


def test_migration_is_chained_to_the_0082_head_without_hardcoding_repo_head():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic/versions/0085_gdpr_requests.py"
    spec = importlib.util.spec_from_file_location("gdpr_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "0085_gdpr_requests"
    assert migration.down_revision == "0084_subscription_history"

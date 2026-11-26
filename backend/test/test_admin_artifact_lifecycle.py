"""PDF artifact lifecycle visibility and guarded orphan cleanup (#2118)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AdminAuditLog,
    Compilation,
    GdprLegalHold,
    JobFinalization,
    RenderArtifactManifest,
    UsageAnalytics,
)
from app.services import storage_service
from app.services.render_engine import retention
from test.test_admin_operations_api import _create_user, _headers

ANCIENT = timedelta(days=60)


def _hex64() -> str:
    return (uuid.uuid4().hex + uuid.uuid4().hex)[:64]


def _object(key: str, size: int, *, age: timedelta) -> dict:
    return {
        "key": key,
        "size": size,
        "last_modified": datetime.now(timezone.utc) - age,
    }


async def _seed_manifest(
    db: AsyncSession,
    *,
    key: str,
    size: int,
    created_at: datetime,
    expires_at: datetime,
    user_id: str | None = None,
    owner_kind: str = "device",
) -> str:
    job_id = f"test_artifact_{uuid.uuid4().hex}"
    db.add(
        JobFinalization(
            id=str(uuid.uuid4()),
            job_id=job_id,
            user_id=user_id,
            owner_token="owner",
            owner_epoch=1,
            state="completed",
            expires_at=expires_at,
        )
    )
    await db.flush()
    artifact_id = _hex64()
    db.add(
        RenderArtifactManifest(
            artifact_id=artifact_id,
            job_id=job_id,
            owner_epoch=1,
            owner_token_sha256="b" * 64,
            owner_scope_kind=owner_kind,
            manifest_key=f"{retention.PREFIX}{_hex64()}/manifests/{artifact_id}.json",
            pdf_key=key,
            payload={"pdf": {"key": key, "size": size}, "synctex": None, "geometry": None},
            created_at=created_at,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return job_id


async def _seed_compilation(
    db: AsyncSession,
    *,
    key: str,
    accepted: bool,
    user_id: str | None = None,
) -> None:
    db.add(
        Compilation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            job_id=f"test_artifact_comp_{uuid.uuid4().hex}",
            status="completed",
            pdf_path=key,
            artifact_accepted=accepted,
        )
    )
    await db.commit()


async def _seed_hold(db: AsyncSession, user_id: str) -> None:
    db.add(
        GdprLegalHold(
            id=str(uuid.uuid4()),
            user_id=user_id,
            reason="Litigation hold for lifecycle test",
            placed_by="test-admin",
            placed_email="admin@example.com",
            active=True,
        )
    )
    await db.commit()


def _patch_storage(monkeypatch, objects: list[dict], deleted: list[str]):
    monkeypatch.setattr(retention, "storage_database_bound", lambda: True)
    monkeypatch.setattr(
        storage_service,
        "list_object_page",
        lambda *args, **kwargs: (objects, None),
    )
    monkeypatch.setattr(
        storage_service,
        "delete_object",
        lambda key: deleted.append(key) or True,
    )


async def _report(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get("/admin/operations/artifacts/lifecycle", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_artifact_lifecycle_is_admin_only(client: AsyncClient, db_session: AsyncSession) -> None:
    admin = await _headers(db_session, "admin")
    user = await _headers(db_session, "user")
    support = await _headers(db_session, "support")

    assert (await client.get("/admin/operations/artifacts/lifecycle")).status_code == 401
    assert (
        await client.get("/admin/operations/artifacts/lifecycle", headers=user)
    ).status_code == 403
    assert (
        await client.get("/admin/operations/artifacts/lifecycle", headers=support)
    ).status_code == 403
    assert (
        await client.get("/admin/operations/artifacts/lifecycle", headers=admin)
    ).status_code == 200

    assert (await client.post("/admin/operations/artifacts/cleanup", json={})).status_code == 401
    denied = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=user,
        json={"reason": "test cleanup", "dry_run": True},
    )
    assert denied.status_code == 403


async def test_report_reconciles_manifests_and_storage_without_writes(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin = await _headers(db_session, "admin")
    now = datetime.now(timezone.utc)
    user_id, email = await _create_user(db_session)
    held_user_id, held_email = await _create_user(db_session)
    await _seed_hold(db_session, held_user_id)

    active_key = f"{retention.PREFIX}tenant/pdf/active.pdf"
    accepted_key = f"{retention.PREFIX}tenant/pdf/accepted.pdf"
    unaccepted_key = f"{retention.PREFIX}tenant/pdf/unaccepted.pdf"
    held_key = f"{retention.PREFIX}tenant/pdf/held.pdf"
    expired_key = f"{retention.PREFIX}tenant/pdf/expired.pdf"
    orphan_key = f"{retention.PREFIX}tenant/pdf/orphan.pdf"
    recent_key = f"{retention.PREFIX}tenant/pdf/recent.pdf"

    await _seed_manifest(
        db_session, key=active_key, size=1000, created_at=now - timedelta(hours=2),
        expires_at=now + timedelta(days=1), user_id=user_id, owner_kind="user",
    )
    await _seed_manifest(
        db_session, key=expired_key, size=2000, created_at=now - ANCIENT,
        expires_at=now - timedelta(hours=1),
    )
    await _seed_manifest(
        db_session, key=held_key, size=5000, created_at=now - timedelta(days=2),
        expires_at=now + timedelta(days=2), user_id=held_user_id, owner_kind="user",
    )
    await _seed_compilation(db_session, key=accepted_key, accepted=True)
    await _seed_compilation(db_session, key=unaccepted_key, accepted=False)

    telemetry_bytes = 999
    db_session.add(
        UsageAnalytics(
            id=str(uuid.uuid4()),
            action=retention.SWEEP_TELEMETRY_ACTION,
            resource_type="render_artifact_gc",
            event_metadata={
                "scanned": 77,
                "deleted": 4,
                "protected": 70,
                "failed": 2,
                "failed_keys": [orphan_key],
                "manifest_count": 3,
                "manifest_bytes": telemetry_bytes,
            },
            created_at=now,
        )
    )
    await db_session.commit()

    objects = [
        _object(active_key, 1000, age=timedelta(hours=2)),
        _object(accepted_key, 3000, age=timedelta(days=2)),
        _object(unaccepted_key, 4000, age=timedelta(days=2)),
        _object(held_key, 5000, age=timedelta(days=2)),
        _object(expired_key, 2000, age=ANCIENT),
        _object(orphan_key, 6000, age=timedelta(days=2)),
        _object(recent_key, 700, age=timedelta(minutes=5)),
        _object(retention.DATABASE_MARKER, 10, age=ANCIENT),
    ]
    deleted: list[str] = []
    _patch_storage(monkeypatch, objects, deleted)

    before_analytics = int(
        (await db_session.execute(select(func.count()).select_from(UsageAnalytics))).scalar_one()
    )
    body = await _report(client, admin)
    after_analytics = int(
        (await db_session.execute(select(func.count()).select_from(UsageAnalytics))).scalar_one()
    )
    assert before_analytics == after_analytics, "a read must not write analytics"
    assert deleted == []

    manifests = body["manifests"]
    assert manifests["total"]["count"] == sum(
        bucket["count"] for bucket in manifests["states"].values()
    )
    assert manifests["total"]["bytes"] == sum(
        bucket["bytes"] for bucket in manifests["states"].values()
    )
    assert manifests["states"]["expired"]["count"] >= 1
    assert manifests["references"]["accepted_canonical_paths"] >= 1
    assert manifests["references"]["unaccepted_canonical_paths"] >= 1
    assert manifests["references"]["legal_hold_manifests"] >= 1
    assert manifests["references"]["legal_hold_compilations"] == 0

    storage = body["storage"]
    assert storage["status"] == "ok"
    assert storage["complete"] is True
    assert storage["scanned"] == {"count": 8, "bytes": 21710}
    assert storage["states"]["referenced"] == {"count": 3, "bytes": 6000}
    assert storage["states"]["unaccepted_reference"] == {"count": 1, "bytes": 4000}
    assert storage["states"]["legal_hold"] == {"count": 1, "bytes": 5000}
    assert storage["states"]["recent"] == {"count": 1, "bytes": 700}
    assert storage["states"]["orphan_candidate"] == {"count": 1, "bytes": 6000}
    assert storage["states"]["database_marker"] == {"count": 1, "bytes": 10}
    assert sum(bucket["count"] for bucket in storage["states"].values()) == 8
    assert storage["orphan_candidates"]["count"] == 1
    assert storage["orphan_candidates"]["bytes"] == 6000
    assert storage["orphan_candidates"]["keys"][0]["key"] == orphan_key

    assert body["last_sweep"]["failed"] == 2
    assert body["last_sweep"]["manifest_bytes"] == telemetry_bytes
    assert body["failed_deletions"]["failed_last_7d"] >= 2
    assert orphan_key in body["failed_deletions"]["failed_keys"]
    assert body["growth"]["change_since_last_sweep_bytes"] == (
        manifests["total"]["bytes"] - telemetry_bytes
    )
    assert body["aggregate_only"] is True
    assert body["minimum_cohort_size"] == 5
    assert body["suppression"]["aggregate_only"] is True
    assert body["safety"]["protects_referenced"] is True
    assert body["safety"]["protects_unaccepted"] is True
    assert body["safety"]["protects_legal_hold"] is True
    assert body["safety"]["reads_object_contents"] is False

    serialized = json.dumps(body)
    for forbidden in (email, held_email, "user_id", '"email"', "%PDF", "latex_content"):
        assert forbidden not in serialized


async def test_scheduled_sweep_records_failed_deletions_without_user_attribution(
    db_session_factory, monkeypatch
) -> None:
    orphan = f"{retention.PREFIX}tenant/pdf/sweep-fails.pdf"
    monkeypatch.setattr(retention, "storage_database_bound", lambda: True)
    monkeypatch.setattr(
        retention.storage_service,
        "list_object_page",
        lambda *args, **kwargs: ([_object(orphan, 123, age=timedelta(days=2))], None),
    )

    def _fail(_key: str) -> bool:
        raise RuntimeError("storage provider rejected delete")

    monkeypatch.setattr(retention.storage_service, "delete_object", _fail)

    result = await retention.sweep_artifacts(factory=db_session_factory)
    assert result["failed"] == 1
    assert result["failed_keys"] == [orphan]
    assert result["deleted"] == 0

    async with db_session_factory() as session:
        telemetry = (
            await session.execute(
                select(UsageAnalytics)
                .where(
                    UsageAnalytics.action == retention.SWEEP_TELEMETRY_ACTION,
                    UsageAnalytics.resource_type == "render_artifact_gc",
                )
                .order_by(UsageAnalytics.created_at.desc())
            )
        ).scalars().first()
        assert telemetry is not None
        assert telemetry.user_id is None
        assert telemetry.device_fingerprint is None
        assert telemetry.event_metadata["failed"] == 1
        assert telemetry.event_metadata["failed_keys"] == [orphan]
        assert telemetry.event_metadata["scanned"] == 1


async def test_dry_run_reports_counts_and_bytes_without_deleting(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin = await _headers(db_session, "admin")
    orphan_a = f"{retention.PREFIX}tenant/pdf/dry-a.pdf"
    orphan_b = f"{retention.PREFIX}tenant/pdf/dry-b.pdf"
    referenced = f"{retention.PREFIX}tenant/pdf/dry-referenced.pdf"
    recent = f"{retention.PREFIX}tenant/pdf/dry-recent.pdf"
    await _seed_compilation(db_session, key=referenced, accepted=True)
    deleted: list[str] = []
    _patch_storage(
        monkeypatch,
        [
            _object(orphan_a, 111, age=timedelta(days=2)),
            _object(orphan_b, 222, age=timedelta(days=2)),
            _object(referenced, 333, age=timedelta(days=2)),
            _object(recent, 444, age=timedelta(minutes=5)),
        ],
        deleted,
    )

    response = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"reason": "Dry-run lifecycle check", "dry_run": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert {item["key"] for item in body["candidates"]["keys"]} == {orphan_a, orphan_b}
    assert body["candidates"]["count"] == 2
    assert body["candidates"]["bytes"] == 333
    assert body["would_delete"] == {"count": 2, "bytes": 333}
    assert body["deleted"] == {"count": 0, "bytes": 0}
    assert deleted == []

    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "artifact.cleanup.dry_run")
        )
    ).scalars().all()
    assert any(row.reason == "Dry-run lifecycle check" for row in audit)


async def test_cleanup_deletes_only_strictly_unreferenced_objects(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin_token = await _headers(db_session, "admin")
    now = datetime.now(timezone.utc)
    user_id, _email = await _create_user(db_session)
    held_user_id, _held_email = await _create_user(db_session)
    await _seed_hold(db_session, held_user_id)

    orphan_a = f"{retention.PREFIX}tenant/pdf/delete-a.pdf"
    orphan_b = f"{retention.PREFIX}tenant/pdf/delete-b.pdf"
    active_key = f"{retention.PREFIX}tenant/pdf/protected-active.pdf"
    expired_key = f"{retention.PREFIX}tenant/pdf/protected-expired.pdf"
    unaccepted_key = f"{retention.PREFIX}tenant/pdf/protected-unaccepted.pdf"
    held_key = f"{retention.PREFIX}tenant/pdf/protected-held.pdf"
    recent_key = f"{retention.PREFIX}tenant/pdf/protected-recent.pdf"

    await _seed_manifest(
        db_session, key=active_key, size=10, created_at=now - timedelta(days=2),
        expires_at=now + timedelta(days=2), user_id=user_id, owner_kind="user",
    )
    await _seed_manifest(
        db_session, key=expired_key, size=20, created_at=now - ANCIENT,
        expires_at=now - timedelta(days=30),
    )
    await _seed_manifest(
        db_session, key=held_key, size=30, created_at=now - timedelta(days=2),
        expires_at=now + timedelta(days=2), user_id=held_user_id, owner_kind="user",
    )
    await _seed_compilation(db_session, key=unaccepted_key, accepted=False)

    deleted: list[str] = []
    _patch_storage(
        monkeypatch,
        [
            _object(orphan_a, 100, age=timedelta(days=2)),
            _object(orphan_b, 200, age=timedelta(days=2)),
            _object(active_key, 10, age=timedelta(days=2)),
            _object(expired_key, 20, age=ANCIENT),
            _object(unaccepted_key, 40, age=timedelta(days=2)),
            _object(held_key, 30, age=timedelta(days=2)),
            _object(recent_key, 50, age=timedelta(minutes=5)),
        ],
        deleted,
    )

    response = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin_token,
        json={
            "reason": "Remove verified orphan PDFs",
            "dry_run": False,
            "confirm": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(deleted) == {orphan_a, orphan_b}
    assert body["deleted"] == {"count": 2, "bytes": 300}
    assert body["failed"]["count"] == 0
    assert body["protected"]["referenced"]["count"] == 2
    assert body["protected"]["unaccepted_reference"]["count"] == 1
    assert body["protected"]["legal_hold"]["count"] == 1
    assert body["protected"]["recent"]["count"] == 1

    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "artifact.cleanup.run")
        )
    ).scalars().all()
    assert any(
        row.reason == "Remove verified orphan PDFs" and row.target_type == "render_artifact"
        for row in audit
    )
    telemetry = (
        await db_session.execute(
            select(UsageAnalytics).where(
                UsageAnalytics.action == retention.MANUAL_CLEANUP_TELEMETRY_ACTION,
                UsageAnalytics.resource_type == "render_artifact_gc",
            ).order_by(UsageAnalytics.created_at.desc())
        )
    ).scalars().first()
    assert telemetry is not None
    assert telemetry.user_id is None
    assert telemetry.device_fingerprint is None
    assert telemetry.event_metadata["deleted"] == 2
    assert telemetry.event_metadata["deleted_bytes"] == 300


async def test_failed_deletion_is_visible_and_audited(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin = await _headers(db_session, "admin")
    orphan = f"{retention.PREFIX}tenant/pdf/delete-fails.pdf"
    deleted: list[str] = []
    monkeypatch.setattr(retention, "storage_database_bound", lambda: True)
    monkeypatch.setattr(
        storage_service, "list_object_page", lambda *args, **kwargs: ([_object(orphan, 900, age=timedelta(days=3))], None)
    )

    def _fail(_key: str) -> bool:
        raise RuntimeError("storage provider rejected delete")

    monkeypatch.setattr(storage_service, "delete_object", _fail)

    response = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"reason": "Exercise failed delete path", "dry_run": False, "confirm": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert deleted == []
    assert body["deleted"] == {"count": 0, "bytes": 0}
    assert body["failed"]["count"] == 1
    assert body["failed"]["bytes"] == 900
    assert body["failed"]["keys"] == [orphan]

    audit = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == "artifact.cleanup.run")
        )
    ).scalars().all()
    assert any(row.reason == "Exercise failed delete path" for row in audit)


async def test_wrong_storage_binding_refuses_cleanup_and_withholds_orphans(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin = await _headers(db_session, "admin")
    monkeypatch.setattr(retention, "storage_database_bound", lambda: False)

    def _forbidden(*args, **kwargs):
        raise AssertionError("unbound storage must not be listed for cleanup")

    monkeypatch.setattr(storage_service, "list_object_page", _forbidden)

    response = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"reason": "Unbound cleanup check", "dry_run": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "storage_database_binding_unavailable"

    report = await _report(client, admin)
    assert report["storage"]["status"] == "refused"
    assert report["storage"]["orphan_candidates"] == {"count": 0, "bytes": 0, "keys": []}


async def test_cleanup_requires_reason_and_confirmation(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    admin = await _headers(db_session, "admin")
    _patch_storage(monkeypatch, [], [])

    missing_confirm = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"reason": "Real cleanup", "dry_run": False},
    )
    assert missing_confirm.status_code == 422
    missing_reason = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"dry_run": False, "confirm": True},
    )
    assert missing_reason.status_code == 422
    short_reason = await client.post(
        "/admin/operations/artifacts/cleanup",
        headers=admin,
        json={"reason": "x", "dry_run": True},
    )
    assert short_reason.status_code == 422

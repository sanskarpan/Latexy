"""Reference-aware bounded GC protects shared active manifests and grace uploads."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.database.models import Compilation, JobFinalization, RenderArtifactManifest, User
from app.services.render_engine import retention
from app.services.render_engine.artifacts import sha256


@pytest.mark.parametrize("active", [True, False])
async def test_shared_reference_active_expired_orphan_gc(db_session_factory, monkeypatch, active):
    monkeypatch.setattr(retention, "storage_database_bound", lambda: True)
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=2)
    future, expired = now + timedelta(hours=1), now - timedelta(hours=1)
    shared = retention.PREFIX + "tenant/pdf/shared.pdf"
    orphan = retention.PREFIX + "tenant/pdf/orphan.pdf"
    recent = retention.PREFIX + "tenant/pdf/upload-in-progress.pdf"
    jobs = ["test_gc_" + uuid4().hex for _ in range(2)]
    deleted = []
    monkeypatch.setattr(retention.storage_service, "list_object_page", lambda *args, **kwargs: (
        [{"key": shared, "last_modified": old}, {"key": orphan, "last_modified": old},
         {"key": recent, "last_modified": now}], "opaque-next-page"))
    monkeypatch.setattr(retention.storage_service, "delete_object", lambda key: deleted.append(key) or True)
    async with db_session_factory() as session:
        for index, job_id in enumerate(jobs):
            session.add(JobFinalization(id=str(uuid4()), job_id=job_id, owner_token="owner", owner_epoch=1,
                state="completed", expires_at=future, lease_expires_at=future))
            await session.flush()
            session.add(RenderArtifactManifest(artifact_id=uuid4().hex + uuid4().hex, job_id=job_id,
                owner_epoch=1, owner_token_sha256=sha256("owner"), owner_scope_kind="device",
                manifest_key=retention.PREFIX + job_id + "/manifest.json", pdf_key=shared,
                payload={}, created_at=old, expires_at=future if index == 1 and active else expired))
        await session.commit()
    try:
        result = await retention.sweep_artifacts(factory=db_session_factory, cursor="prior-page")
        assert result["next_cursor"] == "opaque-next-page"
        assert result["scanned"] == 3
        assert orphan in deleted
        assert recent not in deleted
        assert (shared not in deleted) == active
    finally:
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id.in_(jobs)))
            await session.commit()


@pytest.mark.parametrize("accepted,deleted_account", [(True, False), (False, False), (True, True)])
async def test_canonical_pointer_outlives_job_ttl_without_promoting_candidate(db_session_factory, monkeypatch, accepted, deleted_account):
    monkeypatch.setattr(retention, "storage_database_bound", lambda: True)
    key = retention.PREFIX + "tenant/pdf/history.pdf"
    old = datetime.now(timezone.utc) - timedelta(days=60)
    deleted = []
    monkeypatch.setattr(retention.storage_service, "list_object_page", lambda *args, **kwargs: ([{"key": key, "last_modified": old}], None))
    monkeypatch.setattr(retention.storage_service, "delete_object", lambda target: deleted.append(target) or True)
    user_id, job_id = str(uuid4()), "test_gc_history_" + uuid4().hex
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=job_id + "@example.com"))
        await session.flush()
        session.add(Compilation(id=str(uuid4()), job_id=job_id, user_id=None if deleted_account else user_id,
            status="completed", pdf_path=key, artifact_branch="candidate", artifact_accepted=accepted))
        await session.commit()
    try:
        await retention.sweep_artifacts(factory=db_session_factory)
        assert (key not in deleted) == (accepted and not deleted_account)
    finally:
        async with db_session_factory() as session:
            await session.execute(delete(Compilation).where(Compilation.job_id == job_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def test_wrong_storage_database_binding_never_deletes(db_session_factory, monkeypatch):
    monkeypatch.setattr(retention, "storage_database_bound", lambda: False)
    def forbidden(*args, **kwargs):
        raise AssertionError("wrong-database GC must not list objects")
    monkeypatch.setattr(retention.storage_service, "list_object_page", forbidden)
    result = await retention.sweep_artifacts(factory=db_session_factory)
    assert result["deleted"] == 0
    assert result["skipped"] == "storage_database_binding_unavailable"

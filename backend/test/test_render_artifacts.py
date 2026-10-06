"""Manifest tenant/capability/integrity and conservative geometry boundaries."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.render_engine import artifacts, geometry
from app.workers import event_publisher, job_lifecycle


@pytest.fixture
def storage(monkeypatch):
    objects = {}
    monkeypatch.setattr(artifacts.storage_service, "upload_immutable_bytes", lambda key, data, media: objects.setdefault(key, data))
    monkeypatch.setattr(artifacts.storage_service, "download_bytes", lambda key, max_bytes: objects[key])
    monkeypatch.setattr(artifacts.storage_service, "head_size", lambda key: len(objects[key]))
    return objects


@pytest.fixture
def owned(monkeypatch):
    redis = MagicMock()
    events = []
    job_lifecycle.set_current_capability("job", "owner", 3)
    monkeypatch.setattr(job_lifecycle, "write_owned_artifacts", lambda *args: True)
    monkeypatch.setattr(event_publisher, "publish_event", lambda job, event, payload: events.append((event, payload)))
    from app.services.render_engine import retention
    async def registered(_):
        return True
    monkeypatch.setattr(retention, "register_manifest", registered)
    yield redis, events
    job_lifecycle.clear_current_owner("job")


def request(**overrides):
    return {"source": "raw\r\nsource", "render_source": "injected source", "settings": {},
            "owner_scope": "user:one", "compiler": "pdflatex", "engine_fingerprint": "test",
            "document_id": "resume", "content_revision": 2, **overrides}


def manifest(storage, owned):
    redis, _ = owned
    pdf = artifacts._put(artifacts.sha256("user:one"), "pdf", b"%PDF-checked", "application/pdf")
    return artifacts.bind_manifest(redis, "job", request(), pdf, page_count=1)


@pytest.fixture
def checked_manifest(storage, owned):
    return manifest(storage, owned)


def test_manifest_raw_source_identity_and_closed_public_payload(storage, owned):
    value = manifest(storage, owned)
    assert value.source_sha256 == artifacts.sha256("raw\r\nsource")
    assert value.render_source_sha256 != value.source_sha256
    public = owned[1][0][1]
    assert public["artifact_id"] == value.artifact_id
    assert not {"owner_token_sha256", "owner_scope_sha256", "pdf", "key"} & public.keys()
    assert artifacts.parse_manifest(value.model_dump()) == value


def test_manifest_rejects_tampering_and_cross_tenant_reference(storage, owned):
    value = manifest(storage, owned).model_dump()
    value["source_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        artifacts.parse_manifest(value)
    value["artifact_id"] = artifacts.sha256(artifacts.canonical_json({k: v for k, v in value.items() if k != "artifact_id"}))
    value["pdf"]["key"] = artifacts.binary_key("0" * 64, value["pdf"]["sha256"], "pdf")
    value["artifact_id"] = artifacts.sha256(artifacts.canonical_json({k: v for k, v in value.items() if k != "artifact_id"}))
    with pytest.raises(ValueError):
        artifacts.parse_manifest(value)


def test_restore_binds_current_job_and_drops_other_revision_geometry(storage, owned):
    old = manifest(storage, owned)
    pdf = old.pdf
    geo = artifacts._put(old.owner_scope_sha256, "geometry", b"{}", "application/json")
    old = artifacts.bind_manifest(owned[0], "job", request(), pdf, geometry=geo)
    result = artifacts.restore_render(owned[0], "job", request(content_revision=3), artifacts.canonical_json(old.model_dump()))
    assert result[0].content_revision == 3
    assert result[0].geometry is None
    assert result[1] == b"%PDF-checked"
    assert artifacts.restore_render(owned[0], "job", request(owner_scope="user:other"), artifacts.canonical_json(old.model_dump())) is None


def test_cancelled_fence_publishes_no_artifact(storage, owned, monkeypatch):
    monkeypatch.setattr(job_lifecycle, "write_owned_artifacts", lambda *args: False)
    assert manifest(storage, owned) is None
    assert owned[1] == []


def test_corrupt_object_is_rejected(storage, owned):
    value = manifest(storage, owned)
    storage[value.pdf.key] = b"%PDF-corrupt"
    with pytest.raises(ValueError):
        artifacts.download_object(value.pdf, 100)


def test_cache_reprojects_geometry_for_new_accepted_revision(storage, owned, monkeypatch):
    old = manifest(storage, owned)
    document = {"document_id": "resume", "content_revision": 3,
        "source_sha256": old.source_sha256, "nodes": []}
    def extracted(pdf_file, received, **kwargs):
        assert pdf_file.read_bytes() == b"%PDF-checked"
        assert received is document
        return {"source_sha256": old.source_sha256, "pdf_sha256": old.pdf.sha256,
                "document_id": "resume", "content_revision": 3, "branch": "draft", "boxes": []}
    extractor = MagicMock(side_effect=extracted)
    monkeypatch.setattr(geometry, "extract_geometry", extractor)
    new, data = artifacts.restore_render(owned[0], "job", request(content_revision=3, source_document=document),
        artifacts.canonical_json(old.model_dump()))
    assert new.geometry is not None
    assert data == b"%PDF-checked"
    assert json.loads(storage[new.geometry.key])["content_revision"] == 3
    extractor.assert_called_once()


def test_geometry_failure_preserves_good_pdf(storage, owned, tmp_path, monkeypatch):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-checked")
    monkeypatch.setattr(geometry, "extract_geometry", MagicMock(side_effect=ValueError("bad extraction")))
    req = request(source_document={"source_sha256": artifacts.sha256("raw\r\nsource"),
        "document_id": "resume", "content_revision": 2})
    value = artifacts.persist_render(owned[0], "job", tmp_path, req, b"%PDF-checked")
    assert value.geometry is None
    geometry.extract_geometry.assert_called_once()


def bbox(words):
    return ('<html><page width="600" height="800"><block><line>' + ''.join(
        f'<word xMin="{10 + i * 20}" yMin="10" xMax="{25 + i * 20}" yMax="20">{word}</word>'
        for i, word in enumerate(words)) + '</line></block></page></html>').encode()


def doc(text):
    return {"source_sha256": "0" * 64, "document_id": "resume", "content_revision": 2,
            "nodes": [{"node_id": "node", "node_revision": "1" * 64, "kind": "bullet",
                       "text": text, "editable": True, "source_span": {"start": 1, "end": 10}}]}


def test_geometry_maps_only_unique_exact_actual_pdf_words():
    value = geometry.project_boxes(bbox(["Hello", "world"]), doc("Hello world"), pdf_sha256="2" * 64, branch="draft")
    assert value["boxes"][0]["x"] == 10
    assert value["boxes"][0]["width"] == 35
    duplicate = geometry.project_boxes(bbox(["Hello", "world", "Hello", "world"]), doc("Hello world"), pdf_sha256="2" * 64, branch="draft")
    assert duplicate["boxes"] == []
    assert duplicate["omissions"][0]["reason"] == "ambiguous_pdf_text"


def test_all_page_rotations_are_checked(monkeypatch, tmp_path):
    monkeypatch.setattr(geometry.shutil, "which", lambda _: "available")
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        kwargs["stdout"].write(b"Pages: 2\nPage rot: 0\n" if len(calls) == 1 else b"Page 1 rot: 0\nPage 2 rot: 90\n")
        return MagicMock(returncode=0)
    monkeypatch.setattr(geometry.subprocess, "run", run)
    assert geometry.extract_geometry(Path("pdf"), doc("Hello"), pdf_sha256="2" * 64, branch="draft") is None
    assert calls[1][1:5] == ["-f", "1", "-l", "2"]


@pytest.mark.parametrize("tamper", [None, "owner", "epoch", "tenant", "public_artifact"])
async def test_durable_finalization_binds_private_manifest(db_session_factory, checked_manifest, tamper):
    from sqlalchemy import delete

    from app.database.models import Compilation, JobFinalization, User
    from app.workers.finalization_arbiter import FinalizationOutcome, commit_success

    job_id, user_id = "test_manifest_" + uuid4().hex, str(uuid4())
    fields = checked_manifest.model_dump()
    fields["job_id"] = job_id
    fields["owner_scope_sha256"] = artifacts.sha256(f"user:{user_id}" if tamper != "tenant" else "user:wrong")
    fields["pdf"]["key"] = artifacts.binary_key(fields["owner_scope_sha256"], fields["pdf"]["sha256"], "pdf")
    if tamper == "owner":
        fields["owner_token_sha256"] = artifacts.sha256("stale-owner")
    if tamper == "epoch":
        fields["owner_epoch"] = 4
    fields["artifact_id"] = artifacts.sha256(artifacts.canonical_json({k: v for k, v in fields.items() if k != "artifact_id"}))
    value = artifacts.parse_manifest(fields)
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    async with db_session_factory() as session:
        session.add(User(id=user_id, email=f"{job_id}@example.com"))
        await session.flush()
        session.add(Compilation(id=str(uuid4()), job_id=job_id, user_id=user_id, status="processing"))
        await session.flush()
        session.add(JobFinalization(id=str(uuid4()), job_id=job_id, user_id=user_id,
            owner_token="owner", owner_epoch=3, state="pending", lease_expires_at=future, expires_at=future))
        await session.commit()
    try:
        public = value.public()
        if tamper == "public_artifact":
            public["artifact_id"] = "0" * 64
        async with db_session_factory() as session:
            outcome = await commit_success(session, job_id=job_id, owner_token="owner", owner_epoch=3,
                result_payload={"success": True, "artifact": public}, pdf_path=value.pdf.key,
                pdf_sha256=value.pdf.sha256, pdf_size=value.pdf.size, render_manifest=fields)
            assert outcome is (FinalizationOutcome.ACCEPTED if tamper is None else FinalizationOutcome.FENCED)
            await session.rollback()
    finally:
        async with db_session_factory() as session:
            await session.execute(delete(JobFinalization).where(JobFinalization.job_id == job_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()

"""Manifest tenant/capability/integrity and conservative geometry boundaries."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
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


def _expired_manifest_payload(value):
    fields = value.model_dump()
    # A guest object capability expires after one day, even if its Redis cache
    # pointer remains present for the longer cache TTL.
    now = int(artifacts.time.time())
    fields.update(created_at=now - 86401, expires_at=now - 1)
    fields["artifact_id"] = artifacts.sha256(artifacts.canonical_json({
        key: item for key, item in fields.items() if key != "artifact_id"
    }))
    return artifacts.canonical_json(fields)


@pytest.fixture
def guest_cache_manifest(storage, owned):
    guest_request = request(owner_scope="device:guest")
    pdf = artifacts._put(artifacts.sha256(guest_request["owner_scope"]), "pdf", b"%PDF-checked", "application/pdf")
    value = artifacts.bind_manifest(owned[0], "job", guest_request, pdf, page_count=1)
    assert value.owner_scope_kind == "device"
    return value, guest_request


async def test_expired_cache_pointer_cannot_select_cache_only_dispatch(guest_cache_manifest, monkeypatch):
    from app.services.render_engine import admission_cache

    value, guest_request = guest_cache_manifest
    raw = _expired_manifest_payload(value)
    # Exercise the real closed manifest decoder, not a mocked expiry result.
    assert artifacts.parse_manifest(raw).expires_at < int(artifacts.time.time())
    monkeypatch.setattr(admission_cache, "prepare_direct_request", lambda _kwargs: ("cache", guest_request))
    redis = AsyncMock()
    redis.get.return_value = raw
    assert not await admission_cache.has_exact_render_cache(redis, {})


def test_expired_restore_refuses_storage_access_after_retention_cleanup(storage, owned, guest_cache_manifest, monkeypatch):
    value, guest_request = guest_cache_manifest
    raw = _expired_manifest_payload(value)
    storage.clear()  # GC already removed the unreferenced PDF.
    downloader = MagicMock(side_effect=AssertionError("Expired object must not be requested"))
    monkeypatch.setattr(artifacts, "download_object", downloader)
    assert artifacts.restore_render(owned[0], "job", guest_request, raw) is None
    downloader.assert_not_called()


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
    import hashlib

    monkeypatch.setattr(geometry.shutil, "which", lambda _: "available")
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"%PDF-test")
    calls = []
    def capture(args, limit, deadline):
        calls.append(args)
        return b"Pages: 2\nPage 1 rot: 0\nPage 2 rot: 90\n"
    monkeypatch.setattr(geometry, "_capture", capture)
    assert geometry.extract_geometry(pdf, doc("Hello"), pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), branch="draft") is None
    assert len(calls) == 1
    assert calls[0][1:5] == ["-f", "1", "-l", "1000"]


def _blank_geometry_pdf(page_count, rotated_page):
    """Fabricated valid PDF; test actual Poppler page-range clamping."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               ("<< /Type /Pages /Count " + str(page_count) + " /Kids [" +
                " ".join(f"{page + 3} 0 R" for page in range(1, page_count + 1)) + "] >>").encode(),
               b"<< /Length 0 >>\nstream\n\nendstream"]
    for page in range(1, page_count + 1):
        objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 600] /Contents 3 0 R /Rotate " +
                        ("90" if page == rotated_page else "0") + " >>").encode())
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, content in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


@pytest.mark.parametrize("page_count,rotated_page,accepted", [
    (1, None, True), (2, None, True), (2, 2, False), (1000, None, True), (1001, None, False),
])
def test_actual_poppler_geometry_range_and_rotation_guard(tmp_path, monkeypatch, page_count, rotated_page, accepted):
    if not all(geometry.shutil.which(tool) for tool in ("pdfinfo", "pdftotext")):
        pytest.skip("Actual Poppler is required")
    pdf = _blank_geometry_pdf(page_count, rotated_page)
    path = tmp_path / "range.pdf"
    path.write_bytes(pdf)
    calls = []
    original_capture = geometry._capture

    def capture(arguments, limit, deadline):
        calls.append(arguments)
        return original_capture(arguments, limit, deadline)

    monkeypatch.setattr(geometry, "_capture", capture)
    document = {"nodes": [], "source_sha256": "0" * 64}
    result = geometry.extract_geometry(path, document, pdf_sha256=artifacts.sha256(pdf), branch="draft")
    assert (result is not None) is accepted
    assert calls[0][1:5] == ["-f", "1", "-l", "1000"]
    assert len(calls) == (2 if accepted else 1)
    if accepted:
        assert len(result["pages"]) == page_count
        assert all(page["rotation"] == 0 for page in result["pages"])


@pytest.mark.parametrize("script,limit,budget", [
    ("import sys; sys.stdout.buffer.write(b'x'*131072); sys.stdout.flush(); import time; time.sleep(5)", 1024, 2),
    ("import time; time.sleep(5)", 1024, .1),
])
def test_geometry_capture_reaps_overflow_and_silent_timeout(monkeypatch, script, limit, budget):
    import sys
    import time

    real_popen = geometry.subprocess.Popen
    processes = []
    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(geometry.subprocess, "Popen", start)
    with pytest.raises(ValueError):
        geometry._capture([sys.executable, "-c", script], limit, time.monotonic() + budget)
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed


def test_geometry_capture_reaps_process_when_watchdog_start_fails(monkeypatch):
    import sys
    import time

    processes = []
    original = geometry.subprocess.Popen
    def start(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    def failed_start(self):
        raise RuntimeError("synthetic thread startup failure")
    monkeypatch.setattr(geometry.subprocess, "Popen", start)
    monkeypatch.setattr(geometry.ProcessWatchdog, "start", failed_start)
    with pytest.raises(RuntimeError):
        geometry._capture([sys.executable, "-c", "import time; time.sleep(5)"], 1024, time.monotonic() + 2)
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed


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

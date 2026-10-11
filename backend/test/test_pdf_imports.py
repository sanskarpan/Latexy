"""Real original bytes, owned database receipts, and explicit adaptation."""
import asyncio
import hashlib
import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, inspect, select

from app.api.pdf_import_routes import (
    AdaptImport,
    adapt_import,
    discard_import,
    get_import,
    import_pdf,
    original_pdf,
    resume_import,
)
from app.database.models import Resume, ResumePdfImport, ResumeTemplate, User
from app.services.resume_engine.pdf_imports import purge_expired_imports, validate_original_pdf


def actual_pdf():
    content = b"BT /F1 12 Tf 72 720 Td (Jane Example) Tj 0 -18 Td (jane@example.test) Tj 0 -24 Td (EXPERIENCE) Tj 0 -18 Td (Engineer at Acme) Tj 0 -18 Td (Built Python services) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    value, offsets = b"%PDF-1.4\n", [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(value))
        value += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(value)
    value += b"xref\n0 6\n0000000000 65535 f \n"
    value += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return value + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n"


@pytest.fixture
async def import_scope(db_session_factory):
    user_id, other_id, template_id = (str(uuid4()) for _ in range(3))
    async with db_session_factory() as db:
        db.add_all([User(id=user_id, email="pdf_import_scope_" + user_id + "@example.test"),
                    User(id=other_id, email="pdf_import_other_" + other_id + "@example.test")])
        db.add(ResumeTemplate(id=template_id, name="Import test", category="ats_safe", latex_content="source", is_active=True))
        await db.commit()
    yield user_id, other_id, template_id
    async with db_session_factory() as db:
        for identity in (user_id, other_id):
            await db.delete(await db.get(User, identity))
        await db.delete(await db.get(ResumeTemplate, template_id))
        await db.commit()


async def uploaded(db, owner, data=None):
    return await import_pdf(UploadFile(filename="../original.pdf", file=io.BytesIO(data or actual_pdf())), db, owner)


async def test_original_is_exact_private_deferred_and_requires_explicit_template(import_scope, db_session_factory):
    owner, other, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        assert receipt["extraction"]["status"] == "partial"
        assert {field["confidence"] for field in receipt["extraction"]["fields"]} == {"unknown"}
        assert receipt["original"]["filename"] == "original.pdf"
        assert await db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == owner)) == 0
        row = await db.get(ResumePdfImport, receipt["import_id"])
        assert "original_pdf" in inspect(row).unloaded  # not copied through hot metadata queries
        original = await original_pdf(row.id, db, owner)
        assert original.body == actual_pdf() and original.headers["cache-control"] == "private, no-store"
        for operation in (get_import, original_pdf):
            with pytest.raises(HTTPException) as error:
                await operation(row.id, db, other)
            assert error.value.status_code == 404
        response = await adapt_import(row.id, AdaptImport(template_id=template, title="My adapted resume",
            expected_original_sha256=receipt["original"]["sha256"]), db, owner)
        assert response["document"]["source_mode"] == "managed" and "Jane Example" in response["latex_content"]
        assert (await resume_import(response["resume_id"], db, owner))["import_id"] == row.id
        assert (await original_pdf(row.id, db, owner)).body == actual_pdf()
        assert row.expires_at is None


async def test_adaptation_hash_field_revision_and_replay_are_strict(import_scope, db_session_factory):
    owner, _, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        field = next(field for field in receipt["extraction"]["fields"] if field["field_id"] == "basics.name")
        options = {"template_id": template, "title": "Adapted", "expected_original_sha256": receipt["original"]["sha256"],
                   "field_edits": [{"node_id": field["field_id"], "expected_node_revision": field["node_revision"], "text": "Jane Doe"}]}
        for attack in ("original", "field"):
            bad = {**options, "field_edits": [dict(options["field_edits"][0])]}
            if attack == "original":
                bad["expected_original_sha256"] = "0" * 64
            else:
                bad["field_edits"][0]["expected_node_revision"] = "0" * 64
            with pytest.raises(HTTPException) as error:
                await adapt_import(receipt["import_id"], AdaptImport(**bad), db, owner)
            assert error.value.status_code == 409
            await db.rollback()
        response = await adapt_import(receipt["import_id"], AdaptImport(**options), db, owner)
        again = await adapt_import(receipt["import_id"], AdaptImport(**options), db, owner)
        assert response["resume_id"] == again["resume_id"] and "Jane Doe" in response["latex_content"]
        assert await db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == owner)) == 1
        with pytest.raises(HTTPException) as error:
            await adapt_import(receipt["import_id"], AdaptImport(**{**options, "title": "Different intent"}), db, owner)
        assert error.value.status_code == 409


async def test_expiry_preserves_bound_original_and_cascade_deletes_attachment(import_scope, db_session_factory):
    owner, _, template = import_scope
    async with db_session_factory() as db:
        first, expired = await uploaded(db, owner), await uploaded(db, owner)
        response = await adapt_import(first["import_id"], AdaptImport(template_id=template, title="Saved",
            expected_original_sha256=first["original"]["sha256"]), db, owner)
        row = await db.get(ResumePdfImport, expired["import_id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        assert await purge_expired_imports(db) == 1
        await db.commit()
        assert await db.scalar(select(ResumePdfImport.id).where(ResumePdfImport.id == first["import_id"]))
        await db.delete(await db.get(Resume, response["resume_id"]))
        await db.commit()
        assert await db.scalar(select(ResumePdfImport.id).where(ResumePdfImport.user_id == owner)) is None


async def test_discard_removes_staged_bytes_and_never_bound_original(import_scope, db_session_factory):
    owner, _, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        await discard_import(receipt["import_id"], db, owner)
        with pytest.raises(HTTPException) as error:
            await original_pdf(receipt["import_id"], db, owner)
        assert error.value.status_code == 404
        receipt = await uploaded(db, owner)
        await adapt_import(receipt["import_id"], AdaptImport(template_id=template, title="Saved",
            expected_original_sha256=receipt["original"]["sha256"]), db, owner)
        with pytest.raises(HTTPException) as error:
            await discard_import(receipt["import_id"], db, owner)
        assert error.value.status_code == 409


def test_corrupt_pdf_never_reaches_a_preserved_attachment():
    validate_original_pdf(actual_pdf())
    with pytest.raises(ValueError):
        validate_original_pdf(b"%PDF-1.4\nnot a PDF structure")


def test_readable_encrypted_pdf_is_not_an_unencrypted_original(monkeypatch):
    import pdfminer.pdfdocument

    original_document = pdfminer.pdfdocument.PDFDocument

    def encrypted_document(*args, **kwargs):
        document = original_document(*args, **kwargs)
        # Empty-user-password encryption can be opened without a password.
        # Successful parsing alone is not proof that the original is unencrypted.
        document.encryption = ([], {"Filter": "Standard"})
        return document

    monkeypatch.setattr(pdfminer.pdfdocument, "PDFDocument", encrypted_document)
    with pytest.raises(ValueError, match="unencrypted"):
        validate_original_pdf(actual_pdf())


def test_page_limit_stops_validation_at_the_first_unsupported_page(monkeypatch):
    from pdfminer.pdfpage import PDFPage

    visited = []

    def pages(_):
        for index in range(1000):
            visited.append(index)
            yield object()

    monkeypatch.setattr(PDFPage, "create_pages", pages)
    with pytest.raises(ValueError, match="fifty pages"):
        validate_original_pdf(actual_pdf())
    assert len(visited) == 51


def test_oversized_original_is_rejected_before_the_pdf_parser(monkeypatch):
    import pdfminer.pdfdocument

    from app.services.resume_engine.pdf_imports import MAX_ORIGINAL_BYTES

    def forbidden_open(*args, **kwargs):
        pytest.fail("Oversized originals must not enter the PDF parser")

    monkeypatch.setattr(pdfminer.pdfdocument, "PDFDocument", forbidden_open)
    with pytest.raises(ValueError, match="ten MiB"):
        validate_original_pdf(b"%PDF-" + b"x" * MAX_ORIGINAL_BYTES)


async def test_cross_owner_cannot_adapt_discard_or_open_saved_attachment(import_scope, db_session_factory):
    owner, other, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        body = AdaptImport(template_id=template, title="Private original",
                           expected_original_sha256=receipt["original"]["sha256"])
        for operation in (
            lambda: adapt_import(receipt["import_id"], body, db, other),
            lambda: discard_import(receipt["import_id"], db, other),
        ):
            with pytest.raises(HTTPException) as error:
                await operation()
            assert error.value.status_code == 404
        response = await adapt_import(receipt["import_id"], body, db, owner)
        with pytest.raises(HTTPException) as error:
            await resume_import(response["resume_id"], db, other)
        assert error.value.status_code == 404
        assert (await original_pdf(receipt["import_id"], db, owner)).body == actual_pdf()


async def test_tampered_original_is_never_served(import_scope, db_session_factory):
    owner, _, _ = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        row = await db.get(ResumePdfImport, receipt["import_id"])
        row.original_pdf = actual_pdf().replace(b"Jane Example", b"Fake Example")
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await original_pdf(row.id, db, owner)
        assert error.value.status_code == 409


async def test_expired_unbound_original_cannot_be_read_or_adapted(import_scope, db_session_factory):
    owner, _, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
        row = await db.get(ResumePdfImport, receipt["import_id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        for operation in (
            lambda: original_pdf(row.id, db, owner),
            lambda: adapt_import(row.id, AdaptImport(template_id=template, title="Expired",
                expected_original_sha256=receipt["original"]["sha256"]), db, owner),
        ):
            with pytest.raises(HTTPException) as error:
                await operation()
            assert error.value.status_code == 404


async def test_expired_cleanup_backlog_does_not_block_live_owner_admission(import_scope, db_session_factory):
    owner, other, _ = import_scope
    content = actual_pdf()
    now = datetime.now(timezone.utc)
    async with db_session_factory() as db:
        # The bounded global sweep consumes its entire 200-row batch on another
        # account. This owner's ten expired rows must not count as live imports.
        for identity, count, expiry in ((other, 201, now - timedelta(days=2)),
                                        (owner, 10, now - timedelta(hours=1))):
            db.add_all([ResumePdfImport(id=str(uuid4()), user_id=identity, filename="original.pdf",
                source_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), original_pdf=content,
                structured_seed={"basics": {"name": "Expired"}}, extraction_status="partial", expires_at=expiry)
                for _ in range(count)])
        await db.commit()
        receipt = await uploaded(db, owner)
        assert receipt["expires_at"] is not None
        assert (await original_pdf(receipt["import_id"], db, owner)).body == content
        # Prove this passed without deleting an unbounded cleanup backlog.
        assert await db.scalar(select(func.count()).select_from(ResumePdfImport).where(
            ResumePdfImport.user_id == owner, ResumePdfImport.expires_at <= now)) == 10


async def test_live_staged_imports_still_enforce_owner_cap(import_scope, db_session_factory):
    owner, _, _ = import_scope
    content = actual_pdf()
    async with db_session_factory() as db:
        db.add_all([ResumePdfImport(id=str(uuid4()), user_id=owner, filename="original.pdf",
            source_sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), original_pdf=content,
            structured_seed={"basics": {"name": "Pending"}}, extraction_status="partial",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)) for _ in range(10)])
        await db.commit()
        with pytest.raises(HTTPException) as limit:
            await uploaded(db, owner)
        assert limit.value.status_code == 429
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(ResumePdfImport).where(
            ResumePdfImport.user_id == owner)) == 10


async def test_concurrent_identical_adaptation_creates_one_resume(import_scope, db_session_factory):
    owner, _, template = import_scope
    async with db_session_factory() as db:
        receipt = await uploaded(db, owner)
    body = AdaptImport(template_id=template, title="Concurrent adaptation",
                       expected_original_sha256=receipt["original"]["sha256"])
    ready = asyncio.Event()
    loaded = 0
    async def adapt():
        nonlocal loaded
        async with db_session_factory() as db:
            # Load the unbound row into both identity maps before either writer
            # locks it. The second writer must observe the first binding.
            row = await db.get(ResumePdfImport, receipt["import_id"])
            assert row.resume_id is None
            loaded += 1
            if loaded == 2:
                ready.set()
            await ready.wait()
            return await adapt_import(receipt["import_id"], body, db, owner)
    first, second = await asyncio.gather(adapt(), adapt())
    assert first["resume_id"] == second["resume_id"]
    async with db_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == owner)) == 1
        assert (await original_pdf(receipt["import_id"], db, owner)).body == actual_pdf()

"""Actual PostgreSQL metadata CAS and manual source-save identity integration."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.resume_engine_routes import DocumentPatch, patch_document
from app.api.resume_routes import ResumeUpdate, update_resume
from app.core.config import settings
from app.database.models import Resume, User
from app.services.resume_engine.document import digest
from app.services.resume_engine.imported_identity_db import ensure_imported_projection
from app.services.resume_engine.semantic import project_document
from app.utils.db_url import normalize_database_url

from .test_imported_identity import SOURCE, identities


def run(operation):
    async def invoke():
        engine = create_async_engine(normalize_database_url(settings.DATABASE_URL), poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            return await operation(sessions)
        finally:
            await engine.dispose()
    return asyncio.run(invoke())


@pytest.fixture
def imported_row():
    user, resume = str(uuid4()), str(uuid4())
    async def create(sessions):
        async with sessions() as db:
            db.add(User(id=user, email="imported_scope_" + user + "@example.test", name="Imported test"))
            await db.flush()
            db.add(Resume(id=resume, user_id=user, title="Imported test", latex_content=SOURCE))
            await db.commit()
    run(create)
    yield user, resume
    async def remove(sessions):
        async with sessions() as db:
            await db.delete(await db.get(User, user))
            await db.commit()
    run(remove)


def test_two_seed_writers_choose_one_identity_set_without_source_revision_change(imported_row):
    _, resume_id = imported_row
    async def operation(sessions):
        ready = asyncio.Event()
        loaded = 0
        async def seed():
            nonlocal loaded
            async with sessions() as db:
                resume = await db.get(Resume, resume_id)
                loaded += 1
                if loaded == 2:
                    ready.set()
                await ready.wait()
                document = await ensure_imported_projection(db, resume)
                await db.commit()
                return document
        first, second = await asyncio.gather(seed(), seed())
        assert identities(first) == identities(second)
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            assert row.latex_content == SOURCE and row.content_revision == 1
            assert identities(project_document(row)) == identities(first)
            assert row.imported_projection["source_sha256"] == digest(SOURCE)
    run(operation)


def test_manual_source_cas_reorders_and_inserts_preserving_unique_fields(imported_row):
    user, resume_id = imported_row
    async def operation(sessions):
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            before = await ensure_imported_projection(db, row)
            await db.commit()
            changed = SOURCE.replace("\\item Built Python services\n\\item Built SQL services",
                                     "\\item Built Java services\n\\item Built SQL services\n\\item Built Python services")
            response = await update_resume(resume_id, ResumeUpdate(latex_content=changed, expected_latex_content=SOURCE), db, user)
            assert response.latex_content == changed
            row = await db.get(Resume, resume_id)
            after = project_document(row)
            assert row.content_revision == 2 and row.imported_projection["source_sha256"] == digest(changed)
            assert identities(after)["Built Python services"] == identities(before)["Built Python services"]
            assert identities(after)["Built SQL services"] == identities(before)["Built SQL services"]
            assert identities(after)["Built Java services"] not in identities(before).values()
    run(operation)


def test_stale_metadata_seed_refreshes_source_instead_of_overwriting_writer(imported_row):
    _, resume_id = imported_row
    async def operation(sessions):
        async with sessions() as stale, sessions() as writer:
            old = await stale.get(Resume, resume_id)
            latest = await writer.get(Resume, resume_id)
            latest.latex_content = "% concurrent source edit\n" + SOURCE
            await writer.commit()
            chosen = await ensure_imported_projection(stale, old)
            await stale.commit()
            assert chosen["_source"] == latest.latex_content and chosen["content_revision"] == 2
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            assert row.latex_content == latest.latex_content and row.content_revision == 2
            assert row.imported_projection["source_sha256"] == digest(latest.latex_content)
    run(operation)


def test_approved_node_patch_retains_persisted_id_and_rejects_stale_repeat(imported_row):
    from fastapi import HTTPException

    user, resume_id = imported_row
    async def operation(sessions):
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            before = await ensure_imported_projection(db, row)
            await db.commit()
            node = next(node for node in before["nodes"] if node["text"] == "Built Python services")
            body = DocumentPatch(
                expected_content_revision=before["content_revision"],
                expected_source_sha256=before["source_sha256"],
                patches=[{"node_id": node["node_id"], "expected_node_revision": node["node_revision"],
                          "text": "Developed Python services"}],
            )
            response = await patch_document(resume_id, body, db, user)
            after = response["document"]
            edited = next(node for node in after["nodes"] if node["text"] == "Developed Python services")
            assert edited["node_id"] == node["node_id"] and edited["node_revision"] != node["node_revision"]
            assert identities(after)["Built SQL services"] == identities(before)["Built SQL services"]
            assert after["content_revision"] == 2
            assert response["latex_content"] == SOURCE.replace("Built Python services", "Developed Python services")
            with pytest.raises(HTTPException) as stale:
                await patch_document(resume_id, body, db, user)
            assert stale.value.status_code == 409
            await db.rollback()
        async with sessions() as db:
            stored = await db.get(Resume, resume_id)
            assert identities(project_document(stored))["Developed Python services"] == node["node_id"]
            assert stored.content_revision == 2
    run(operation)

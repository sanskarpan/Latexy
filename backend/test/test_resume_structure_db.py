"""Actual managed route source-CAS, persistence and collaborator authorization."""
from test.test_imported_identity_db import run
from test.test_resume_structure import document
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.api.resume_engine_routes import DocumentPatch, patch_document
from app.api.resume_structure_routes import StructureMutation, reorder_document
from app.database.models import Resume, ResumeCollaborator, ResumeTemplate, User
from app.services.resume_engine.semantic import project_document


@pytest.fixture
def managed_rows():
    owner, editor, resume_id, template_id = [str(uuid4()) for _ in range(4)]
    doc = document()
    async def create(sessions):
        async with sessions() as db:
            db.add_all([User(id=identity, email="structure_scope_" + identity + "@example.test", name="Structure test") for identity in (owner, editor)])
            db.add(ResumeTemplate(id=template_id, name="Structure test", category="ats_safe", latex_content=doc["_source"]))
            await db.flush()
            db.add(Resume(id=resume_id, user_id=owner, title="Structure test", latex_content=doc["_source"],
                          structured_content=doc["_structured_content"], content_source="builder", builder_status="active", selected_template_id=template_id))
            await db.flush()
            db.add(ResumeCollaborator(resume_id=resume_id, user_id=editor, role="editor", invited_by=owner))
            await db.commit()
    run(create)
    yield owner, editor, resume_id, template_id
    async def remove(sessions):
        async with sessions() as db:
            for identity in (owner, editor):
                await db.delete(await db.get(User, identity))
            await db.delete(await db.get(ResumeTemplate, template_id))
            await db.commit()
    run(remove)


def mutation(doc):
    return StructureMutation(expected_content_revision=doc["content_revision"], expected_source_sha256=doc["source_sha256"],
                             container_id="section.experience.entries", ordered_ids=["b", "a"])


def test_editor_structure_route_persists_order_ids_revision_and_stale_repeat_rejects(managed_rows):
    owner, editor, resume_id, template_id = managed_rows
    variant_id = str(uuid4())
    async def operation(sessions):
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            before = project_document(row, "ats_safe")
            db.add(Resume(id=variant_id, user_id=owner, title="Linked structure variant", parent_resume_id=resume_id,
                          latex_content=before["_source"], content_source="builder_variant", builder_status="active",
                          selected_template_id=template_id))
            await db.commit()
            response = await reorder_document(resume_id, mutation(before), db, editor)
            assert response["document"]["content_revision"] == 2
            assert response["latex_content"].index("Beta") < response["latex_content"].index("Acme")
            assert {n["node_id"]: n["node_revision"] for n in response["document"]["nodes"]} == {n["node_id"]: n["node_revision"] for n in before["nodes"]}
            with pytest.raises(HTTPException) as stale:
                await reorder_document(resume_id, mutation(before), db, editor)
            assert stale.value.status_code == 409
            await db.rollback()
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            assert [entry["id"] for entry in row.structured_content["experience"]] == ["b", "a"] and row.content_revision == 2
            variant = await db.get(Resume, variant_id)
            assert variant.latex_content.index("Beta") < variant.latex_content.index("Acme") and variant.content_revision == 2
    run(operation)


def test_stale_loaded_resume_cannot_overwrite_newer_heading(managed_rows):
    owner, _, resume_id, _ = managed_rows
    async def operation(sessions):
        async with sessions() as stale, sessions() as writer:
            old = await stale.get(Resume, resume_id)
            before = project_document(old, "ats_safe")
            heading = next(node for node in before["nodes"] if node["node_id"] == "section.experience.heading")
            response = await patch_document(resume_id, DocumentPatch(expected_content_revision=1, expected_source_sha256=before["source_sha256"],
                                            patches=[{"node_id": heading["node_id"], "expected_node_revision": heading["node_revision"], "text": "Work History"}]), writer, owner)
            assert response["document"]["content_revision"] == 2
            with pytest.raises(HTTPException) as conflict:
                await reorder_document(resume_id, mutation(before), stale, owner)
            assert conflict.value.status_code == 409
            await stale.rollback()
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            assert row.structured_content["section_titles"]["experience"] == "Work History"
            assert [entry["id"] for entry in row.structured_content["experience"]] == ["a", "b"] and row.content_revision == 2
    run(operation)


def test_revoked_editor_rechecked_after_stale_preflight(managed_rows):
    _, editor, resume_id, _ = managed_rows
    async def operation(sessions):
        async with sessions() as stale, sessions() as writer:
            row = await stale.get(Resume, resume_id)
            before = project_document(row, "ats_safe")
            await writer.execute(delete(ResumeCollaborator).where(ResumeCollaborator.resume_id == resume_id, ResumeCollaborator.user_id == editor))
            await writer.commit()
            with pytest.raises(HTTPException) as denied:
                await reorder_document(resume_id, mutation(before), stale, editor)
            assert denied.value.status_code in {403, 404}
            await stale.rollback()
        async with sessions() as db:
            row = await db.get(Resume, resume_id)
            assert row.content_revision == 1 and row.latex_content == before["_source"]
    run(operation)

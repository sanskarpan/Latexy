"""Real API/database interleavings between builder and semantic engine saves."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.resume_engine_routes import Decisions, DocumentPatch, decide_run, patch_document
from app.api.resume_structure_routes import StructureMutation, reorder_document
from app.database.models import JobFinalization, Resume, ResumeOptimizationRun, ResumeTemplate
from app.services.resume_engine.context import build_context
from app.services.resume_engine.document import digest
from app.services.resume_engine.semantic import apply_node_edits, project_document
from app.services.resume_engine.stages import stage_fingerprint


async def create_managed(client, headers, db):
    template = ResumeTemplate(
        id=str(uuid4()), name="test_tmpl_builder_engine_" + uuid4().hex, category="ats_safe",
        latex_content=r"\documentclass{article}\begin{document}Template\end{document}",
        document_type="resume", is_active=True,
    )
    db.add(template)
    await db.commit()
    response = await client.post("/resumes/builder/v1", headers=headers, json={
        "title": "test_builder_engine_conflicts", "template_id": template.id,
        "structured_content": {
            "basics": {"name": "Jane"},
            "experience": [
                {"id": "role-a", "company": "Acme", "bullets": ["Built Python services"], "bullet_ids": ["bullet-a"]},
                {"id": "role-b", "company": "Beta", "bullets": ["Managed SQL data"], "bullet_ids": ["bullet-b"]},
            ],
        },
    })
    assert response.status_code == 201, response.text
    return response.json()["resume"]


async def load_saved(db, resume_id):
    resume = await db.get(Resume, resume_id, populate_existing=True)
    assert resume is not None
    return resume


async def get_document(client, headers, resume_id):
    response = await client.get(f"/resumes/{resume_id}/engine/document", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["document"]


def baseline(document):
    return {"expected_content_revision": document["content_revision"],
            "expected_source_sha256": document["source_sha256"]}


async def seed_candidate(db, resume, *, same_text=False):
    document = project_document(resume, "ats_safe")
    context = build_context(document, "Python required")
    node = next(node for node in document["nodes"] if node["kind"] == "bullet")
    fact = next(fact for fact in context["facts"] if fact["node_id"] == node["node_id"])
    patch = {"patch_id": "patch-a", "node_id": node["node_id"], "expected_node_revision": node["node_revision"],
             "text": node["text"] if same_text else "Developed Python services", "evidence_ids": [fact["fact_id"]]}
    source, _ = apply_node_edits(document, [patch], expected_revision=document["content_revision"],
                                 expected_source=document["source_sha256"], ai_only=True)
    result = {"patches": [patch], "candidate_source_sha256": digest(source)}
    result["result_sha256"] = stage_fingerprint(result)
    run_id = str(uuid4())
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    db.add(JobFinalization(
        id=str(uuid4()), job_id=run_id, job_type="combined", user_id=resume.user_id, resume_id=resume.id,
        owner_token="builder-engine-test", owner_epoch=1, state="completed", cancel_requested=False,
        lease_expires_at=expires, expires_at=expires,
    ))
    await db.flush()
    db.add(ResumeOptimizationRun(
        id=run_id, job_id=run_id, resume_id=resume.id, user_id=resume.user_id,
        base_revision=document["content_revision"], source_sha256=document["source_sha256"], context_hash=stage_fingerprint(context),
        effort="quick", provider="openai", model="test-model", credential_scope="test", status="completed",
        snapshot=document, context_payload=context, budget={}, result=result, decisions={}, expires_at=expires,
    ))
    await db.commit()
    return run_id, patch["patch_id"]


async def edit_engine(client, headers, resume_id, document, kind, *, run_id=None, patch_id=None):
    if kind == "field":
        node = next(node for node in document["nodes"] if node["node_id"] == "basics.name")
        return await client.patch(f"/resumes/{resume_id}/engine/document", headers=headers, json={
            **baseline(document), "patches": [{"node_id": node["node_id"],
                "expected_node_revision": node["node_revision"], "text": "Jane Doe"}],
        })
    if kind == "reorder":
        return await client.post(f"/resumes/{resume_id}/engine/structure", headers=headers, json={
            **baseline(document), "container_id": "section.experience.entries", "ordered_ids": ["role-b", "role-a"],
        })
    return await client.post(f"/resumes/{resume_id}/engine/runs/{run_id}/decisions", headers=headers, json={
        **baseline(document), "accept_patch_ids": [patch_id],
    })


@pytest.mark.parametrize("kind", ["field", "reorder", "accept"])
@pytest.mark.parametrize("builder_suffix", ["builder", "builder/v1"])
async def test_engine_mutation_invalidates_open_builder_save_and_updates_linked_variant(
    client, auth_headers, db_session, kind, builder_suffix,
):
    original = await create_managed(client, auth_headers, db_session)
    resume_id = original["id"]
    fork = await client.post(f"/resumes/{resume_id}/fork", headers=auth_headers,
                             json={"title": "test_builder_engine_variant"})
    assert fork.status_code == 201, fork.text
    variant_id = fork.json()["id"]
    cached = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": True}
    saved = await load_saved(db_session, resume_id)
    saved.resume_settings = deepcopy(cached)
    variant = await load_saved(db_session, variant_id)
    variant.resume_settings = deepcopy(cached)
    await db_session.commit()
    run_id, patch_id = await seed_candidate(db_session, saved) if kind == "accept" else (None, None)
    before = await get_document(client, auth_headers, resume_id)
    response = await edit_engine(client, auth_headers, resume_id, before, kind, run_id=run_id, patch_id=patch_id)
    assert response.status_code == 200, response.text
    newer = response.json()
    assert newer["document"]["schema_version"] == 1
    assert newer["document"]["structured_version"] == original["structured_version"] + 1
    assert newer["document"]["content_revision"] == before["content_revision"] + 1
    saved = await load_saved(db_session, resume_id)
    newer_structured = deepcopy(saved.structured_content)
    assert saved.builder_status == "active" and saved.content_source == "builder"
    assert saved.resume_settings == {"compiler": "lualatex"}
    variant = await load_saved(db_session, variant_id)
    assert variant.structured_version == saved.structured_version
    assert variant.latex_content == saved.latex_content
    assert variant.resume_settings == {"compiler": "lualatex"}

    rejected = await client.patch(f"/resumes/{resume_id}/{builder_suffix}", headers=auth_headers, json={
        "expected_structured_version": original["structured_version"], "title": "Stale title",
        "structured_content": original["structured_content"],
    })
    assert rejected.status_code == 409, rejected.text
    saved = await load_saved(db_session, resume_id)
    assert saved.structured_version == original["structured_version"] + 1
    assert saved.content_revision == before["content_revision"] + 1
    assert saved.title == original["title"]
    assert saved.latex_content == newer["latex_content"] and saved.structured_content == newer_structured

    if kind == "accept":
        replay = await edit_engine(client, auth_headers, resume_id, before, kind, run_id=run_id, patch_id=patch_id)
        assert replay.status_code == 200, replay.text
        assert replay.json()["document"] == newer["document"]


@pytest.mark.parametrize("operation", ["get", "same-text", "identity-reorder", "reject", "accept-same-text"])
async def test_engine_noops_do_not_write_resume_or_materialize_default_titles(
    client, auth_headers, db_session, operation,
):
    original = await create_managed(client, auth_headers, db_session)
    resume_id = original["id"]
    saved = await load_saved(db_session, resume_id)
    assert saved.structured_content["section_titles"] == {}
    cached = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": True}
    saved.resume_settings = cached
    await db_session.commit()
    run_id, patch_id = await seed_candidate(db_session, saved, same_text=True) if operation in {
        "reject", "accept-same-text",
    } else (None, None)
    saved = await load_saved(db_session, resume_id)
    original_updated = saved.updated_at
    before = await get_document(client, auth_headers, resume_id)
    writes = []

    def record_resume_update(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE RESUMES "):
            writes.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record_resume_update)
    try:
        if operation == "get":
            response = await client.get(f"/resumes/{resume_id}/engine/document", headers=auth_headers)
        elif operation == "same-text":
            node = next(node for node in before["nodes"] if node["node_id"] == "basics.name")
            response = await client.patch(f"/resumes/{resume_id}/engine/document", headers=auth_headers, json={
                **baseline(before), "patches": [{"node_id": node["node_id"],
                    "expected_node_revision": node["node_revision"], "text": node["text"]}],
            })
        elif operation == "identity-reorder":
            response = await client.post(f"/resumes/{resume_id}/engine/structure", headers=auth_headers, json={
                **baseline(before), "container_id": "section.experience.entries", "ordered_ids": ["role-a", "role-b"],
            })
        else:
            key = "reject_patch_ids" if operation == "reject" else "accept_patch_ids"
            response = await client.post(f"/resumes/{resume_id}/engine/runs/{run_id}/decisions", headers=auth_headers,
                                         json={**baseline(before), key: [patch_id]})
        assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", record_resume_update)
    assert not writes
    saved = await load_saved(db_session, resume_id)
    assert saved.updated_at == original_updated
    assert saved.structured_version == original["structured_version"]
    assert saved.content_revision == before["content_revision"]
    assert saved.structured_content == original["structured_content"]
    assert saved.latex_content == original["latex_content"]
    assert saved.resume_settings == cached


@pytest.mark.parametrize("kind", ["field", "reorder", "accept"])
async def test_title_only_builder_save_refreshes_stale_engine_save_token_but_keeps_source_cas(
    client, auth_headers, db_session, db_session_factory, kind,
):
    original = await create_managed(client, auth_headers, db_session)
    resume_id = original["id"]
    before = await get_document(client, auth_headers, resume_id)
    saved = await load_saved(db_session, resume_id)
    run_id, patch_id = await seed_candidate(db_session, saved) if kind == "accept" else (None, None)
    async with db_session_factory() as stale:
        stale_row = await stale.get(Resume, resume_id)
        assert stale_row.structured_version == 1
        renamed = await client.patch(f"/resumes/{resume_id}/builder/v1", headers=auth_headers, json={
            "expected_structured_version": original["structured_version"], "title": "New title only",
        })
        assert renamed.status_code == 200, renamed.text
        after_title = await get_document(client, auth_headers, resume_id)
        assert after_title["schema_version"] == 1
        assert after_title["structured_version"] == 2
        assert after_title["content_revision"] == before["content_revision"]
        assert after_title["source_sha256"] == before["source_sha256"]
        assert stale_row.structured_version == 1  # a genuinely stale independent identity map
        # Source CAS remains valid, but the lock must refresh the builder token.
        if kind == "field":
            node = next(node for node in before["nodes"] if node["node_id"] == "basics.name")
            changed = await patch_document(resume_id, DocumentPatch(**baseline(before), patches=[{
                "node_id": node["node_id"], "expected_node_revision": node["node_revision"], "text": "Jane Doe",
            }]), stale, stale_row.user_id)
        elif kind == "reorder":
            changed = await reorder_document(resume_id, StructureMutation(**baseline(before),
                container_id="section.experience.entries", ordered_ids=["role-b", "role-a"]), stale, stale_row.user_id)
        else:
            changed = await decide_run(resume_id, run_id, Decisions(**baseline(before), accept_patch_ids=[patch_id]),
                                       stale, stale_row.user_id)
        assert changed["document"]["structured_version"] == 3
        assert changed["document"]["content_revision"] == before["content_revision"] + 1
    saved = await load_saved(db_session, resume_id)
    assert saved.title == "New title only" and saved.builder_status == "active"


async def test_structured_only_reorder_advances_builder_token_and_preserves_source_cache(
    client, auth_headers, db_session,
):
    original = await create_managed(client, auth_headers, db_session)
    resume_id = original["id"]
    saved = await load_saved(db_session, resume_id)
    cached = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": False}
    saved.resume_settings = cached
    await db_session.commit()
    before = await get_document(client, auth_headers, resume_id)
    sections = next(container for container in before["containers"] if container["container_id"] == "sections")
    reordered = list(sections["ordered_child_ids"])
    first, second = reordered.index("awards"), reordered.index("certifications")
    reordered[first], reordered[second] = reordered[second], reordered[first]
    response = await client.post(f"/resumes/{resume_id}/engine/structure", headers=auth_headers, json={
        **baseline(before), "container_id": "sections", "ordered_ids": reordered,
    })
    assert response.status_code == 200, response.text
    saved = await load_saved(db_session, resume_id)
    assert saved.latex_content == original["latex_content"]
    assert saved.structured_content["section_order"] == reordered
    assert saved.structured_version == 2 and saved.content_revision == before["content_revision"] + 1
    assert saved.resume_settings == cached
    rejected = await client.patch(f"/resumes/{resume_id}/builder/v1", headers=auth_headers, json={
        "expected_structured_version": 1, "structured_content": original["structured_content"],
    })
    assert rejected.status_code == 409, rejected.text


@pytest.mark.parametrize("change_source", [False, True])
async def test_imported_engine_edit_uses_source_only_detachment_and_cache_invalidation(
    client, auth_headers, db_session, change_source,
):
    original = await create_managed(client, auth_headers, db_session)
    resume_id = original["id"]
    saved = await load_saved(db_session, resume_id)
    # A legacy source writer can leave builder metadata attached even though
    # the current source no longer matches the renderer. Projection is imported.
    imported_source = "\n".join([
        r"\documentclass{article}", r"\begin{document}", r"\section{Experience}", r"\begin{itemize}",
        r"\item Built Python services", r"\end{itemize}", r"\end{document}",
    ])
    saved.latex_content = imported_source
    cached = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": True}
    saved.resume_settings = cached
    await db_session.commit()
    before = await get_document(client, auth_headers, resume_id)
    assert before["source_mode"] == "imported"
    node = next(node for node in before["nodes"] if node["text"] == "Built Python services")
    response = await client.patch(f"/resumes/{resume_id}/engine/document", headers=auth_headers, json={
        **baseline(before), "patches": [{"node_id": node["node_id"], "expected_node_revision": node["node_revision"],
            "text": "Developed Python services" if change_source else node["text"]}],
    })
    assert response.status_code == 200, response.text
    saved = await load_saved(db_session, resume_id)
    assert saved.structured_version == original["structured_version"]
    assert saved.structured_content == original["structured_content"]
    assert saved.content_revision == before["content_revision"] + int(change_source)
    assert saved.builder_status == ("detached" if change_source else "active")
    assert saved.content_source == ("manual_latex" if change_source else "builder")
    assert saved.resume_settings == ({"compiler": "lualatex"} if change_source else cached)
    current_node = next(current for current in response.json()["document"]["nodes"] if current["node_id"] == node["node_id"])
    assert current_node["node_id"] == node["node_id"]
    assert current_node["text"] == ("Developed Python services" if change_source else node["text"])

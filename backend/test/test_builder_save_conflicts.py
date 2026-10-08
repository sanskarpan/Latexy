"""Exercise builder save preconditions against the real API and test database."""

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.database.models import Resume, ResumeTemplate
from app.main import app


async def _template(db: AsyncSession, category: str = "minimal") -> ResumeTemplate:
    template = ResumeTemplate(
        id=str(uuid4()), name=f"test_builder_conflict_{uuid4().hex}", category=category,
        description="Builder conflict regression fixture", tags=[category],
        latex_content=r"\documentclass{article}\begin{document}Template\end{document}",
        document_type="resume", is_active=True, sort_order=0,
    )
    db.add(template)
    await db.commit()
    return template


async def _create(client: AsyncClient, headers: dict, db: AsyncSession) -> dict:
    template = await _template(db)
    response = await client.post(
        "/resumes/builder", headers=headers,
        json={"title": "test_builder_conflict_resume", "template_id": template.id,
              "structured_content": {"basics": {"name": "Original Candidate"}}},
    )
    assert response.status_code == 201, response.text
    return response.json()["resume"]


async def _saved(db: AsyncSession, resume_id: str) -> Resume:
    resume = await db.get(Resume, resume_id, populate_existing=True)
    assert resume is not None
    return resume


@pytest.mark.asyncio
async def test_builder_rejects_stale_version_without_changing_saved_content(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    endpoint = f"/resumes/{original['id']}/builder"
    accepted = await client.patch(endpoint, headers=auth_headers, json={
        "expected_structured_version": 1, "title": "Newer saved title",
        "structured_content": {"basics": {"name": "Newer Candidate"}},
    })
    assert accepted.status_code == 200, accepted.text
    newer = accepted.json()["resume"]
    rejected = await client.patch(endpoint, headers=auth_headers, json={
        "expected_structured_version": 1, "title": "Stale title",
        "structured_content": {"basics": {"name": "Stale Candidate"}},
    })
    assert rejected.status_code == 409, rejected.text
    saved = await _saved(db_session, original["id"])
    assert saved.structured_version == 2
    assert saved.title == newer["title"]
    assert saved.structured_content == newer["structured_content"]
    assert saved.latex_content == newer["latex_content"]


@pytest.mark.asyncio
async def test_builder_changed_content_invalidates_anonymous_share_cache(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    saved = await _saved(db_session, original["id"])
    saved.resume_settings = {"compiler": "lualatex", "share_anonymous": True,
                             "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": True}
    await db_session.commit()
    response = await client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers, json={
        "expected_structured_version": 1,
        "structured_content": {"basics": {"name": "Updated Candidate"}},
    })
    assert response.status_code == 200, response.text
    saved = await _saved(db_session, original["id"])
    assert saved.resume_settings == {"compiler": "lualatex", "share_anonymous": True}


@pytest.mark.asyncio
async def test_builder_identical_content_preserves_anonymous_share_cache(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    saved = await _saved(db_session, original["id"])
    cached = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": False}
    saved.resume_settings = cached
    await db_session.commit()
    response = await client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers, json={
        "expected_structured_version": 1, "title": "A new title",
    })
    assert response.status_code == 200, response.text
    saved = await _saved(db_session, original["id"])
    assert saved.resume_settings == cached


@pytest.mark.asyncio
async def test_manual_edit_invalidates_both_anonymous_share_cache_fields(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    saved = await _saved(db_session, original["id"])
    saved.resume_settings = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()),
                             "share_anonymous_pending": True}
    await db_session.commit()
    await _detach(client, auth_headers, original, "Manually edited source")
    saved = await _saved(db_session, original["id"])
    assert saved.resume_settings == {"compiler": "lualatex"}


@pytest.mark.asyncio
async def test_master_change_invalidates_linked_variant_anonymous_share_cache(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    forked = await client.post(f"/resumes/{original['id']}/fork", headers=auth_headers,
                               json={"title": "test_builder_conflict_linked"})
    assert forked.status_code == 201, forked.text
    variant = await _saved(db_session, forked.json()["id"])
    variant.resume_settings = {"compiler": "lualatex", "share_anonymous_job_id": str(uuid4()),
                               "share_anonymous_pending": True}
    await db_session.commit()
    response = await client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers, json={
        "expected_structured_version": 1,
        "structured_content": {"basics": {"name": "Updated Candidate"}},
    })
    assert response.status_code == 200, response.text
    variant = await _saved(db_session, variant.id)
    assert variant.resume_settings == {"compiler": "lualatex"}
    assert "Updated Candidate" in variant.latex_content


@pytest.mark.asyncio
async def test_builder_concurrent_saves_accept_only_one_matching_version(
    client, auth_headers, db_session, db_session_factory, monkeypatch,
):
    original = await _create(client, auth_headers, db_session)

    async def independent_request_session():
        async with db_session_factory() as session:
            yield session

    # Two real connections exercise the PostgreSQL row lock. Sharing the
    # default fixture session cannot prove concurrent-save serialization.
    monkeypatch.setitem(app.dependency_overrides, get_db, independent_request_session)
    responses = await asyncio.gather(*[
        client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers, json={
            "expected_structured_version": 1,
            "structured_content": {"basics": {"name": candidate}},
        })
        for candidate in ("Candidate A", "Candidate B")
    ])
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json()["resume"] for response in responses if response.status_code == 200)
    saved = await _saved(db_session, original["id"])
    assert saved.structured_version == 2
    assert saved.structured_content == winner["structured_content"]
    assert saved.latex_content == winner["latex_content"]


@pytest.mark.asyncio
async def test_builder_versions_title_and_template_changes(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    endpoint = f"/resumes/{original['id']}/builder"
    renamed = await client.patch(endpoint, headers=auth_headers, json={
        "expected_structured_version": 1, "title": "Renamed resume",
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["resume"]["structured_version"] == 2
    replacement = await _template(db_session, "executive")
    switched = await client.patch(endpoint, headers=auth_headers, json={
        "expected_structured_version": 2, "template_id": replacement.id,
    })
    assert switched.status_code == 200, switched.text
    saved = await _saved(db_session, original["id"])
    assert saved.structured_version == 3
    assert saved.selected_template_id == replacement.id
    assert saved.title == "Renamed resume"
    assert saved.structured_content == original["structured_content"]


@pytest.mark.asyncio
async def test_builder_other_owner_cannot_save_or_inspect_version(client, auth_headers, auth_headers2, db_session):
    original = await _create(client, auth_headers, db_session)
    rejected = await client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers2, json={
        "expected_structured_version": 99, "title": "Unauthorized overwrite",
    })
    assert rejected.status_code == 404, rejected.text
    saved = await _saved(db_session, original["id"])
    assert saved.title == original["title"]
    assert saved.structured_version == 1


async def _detach(client, headers, original: dict, manual: str) -> None:
    response = await client.put(f"/resumes/{original['id']}", headers=headers, json={
        "latex_content": manual, "expected_latex_content": original["latex_content"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["builder_status"] == "detached"


@pytest.mark.asyncio
async def test_builder_does_not_overwrite_advanced_editor_content(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    manual = r"\documentclass{article}\begin{document}Advanced edit\end{document}"
    await _detach(client, auth_headers, original, manual)
    rejected = await client.patch(f"/resumes/{original['id']}/builder", headers=auth_headers, json={
        "expected_structured_version": 1, "structured_content": {"basics": {"name": "Stale builder"}},
    })
    assert rejected.status_code == 409, rejected.text
    saved = await _saved(db_session, original["id"])
    assert saved.latex_content == manual
    assert saved.builder_status == "detached"
    assert saved.structured_version == 1


@pytest.mark.asyncio
async def test_builder_reattach_requires_current_manual_document_baseline(client, auth_headers, db_session):
    original = await _create(client, auth_headers, db_session)
    manual = r"\documentclass{article}\begin{document}Keep this edit\end{document}"
    await _detach(client, auth_headers, original, manual)
    endpoint = f"/resumes/{original['id']}/builder"
    body = {"expected_structured_version": 1, "force_reattach": True,
            "structured_content": {"basics": {"name": "Reattached Candidate"}}}
    missing = await client.patch(endpoint, headers=auth_headers, json=body)
    assert missing.status_code == 428, missing.text
    stale = await client.patch(endpoint, headers=auth_headers, json={
        **body, "expected_latex_content": original["latex_content"],
    })
    assert stale.status_code == 409, stale.text
    saved = await _saved(db_session, original["id"])
    assert saved.latex_content == manual
    assert saved.builder_status == "detached"
    assert saved.structured_version == 1
    accepted = await client.patch(endpoint, headers=auth_headers, json={**body, "expected_latex_content": manual})
    assert accepted.status_code == 200, accepted.text
    saved = await _saved(db_session, original["id"])
    assert saved.structured_version == 2
    assert saved.builder_status == "active"
    assert saved.content_source == "builder"
    assert "Reattached Candidate" in saved.latex_content

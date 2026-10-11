"""Real-database regressions for non-builder writers and linked-variant races."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.resume_routes import VariantVisibilityUpdate, _sync_linked_variants, update_variant_visibility
from app.database.models import JobFinalization, Optimization, Resume, ResumeTemplate, User
from app.services.resume_source_service import apply_source_change
from app.workers.auto_save_worker import ResumePersistenceConflict, _persist_resume_content, apply_resume_content
from app.workers.finalization_arbiter import FinalizationOutcome, commit_success

WRITERS = ["restore", "suggestion", "generated", "finalization", "github"]


async def _setup(client, headers, db, *, variant=False):
    template = ResumeTemplate(
        id=str(uuid4()), name=f"test_source_mutation_{uuid4().hex}", category="minimal",
        description="Synthetic source mutation fixture", tags=[], document_type="resume",
        latex_content=r"\documentclass{article}\begin{document}Template\end{document}",
        is_active=True, sort_order=0,
    )
    db.add(template)
    await db.commit()
    created = await client.post("/resumes/builder/v1", headers=headers, json={
        "title": "test_builder_source_mutation", "template_id": template.id,
        "structured_content": {"basics": {"name": "Synthetic Candidate", "summary": "Synthetic profile summary"}},
    })
    assert created.status_code == 201, created.text
    parent = created.json()["resume"]
    original = parent
    if variant:
        forked = await client.post(f"/resumes/{parent['id']}/fork", headers=headers,
                                   json={"title": "test_builder_source_variant"})
        assert forked.status_code == 201, forked.text
        original = forked.json()
        assert original["content_source"] == "builder_variant"
    saved = await db.get(Resume, original["id"], populate_existing=True)
    saved.resume_settings = {"compiler": "lualatex", "share_anonymous": True,
                             "share_anonymous_job_id": str(uuid4()), "share_anonymous_pending": True}
    await db.commit()
    return original, parent, saved.resume_settings.copy()


async def _mutate(writer, original, content, client, headers, db, factory, *, token=None):
    if writer == "restore":
        opt = Optimization(
            id=str(uuid4()), user_id=original["user_id"], resume_id=original["id"],
            original_latex=original["latex_content"], optimized_latex=content,
            job_description="", provider="checkpoint", model="synthetic", is_checkpoint=True,
        )
        db.add(opt)
        await db.commit()
        response = await client.post(
            f"/resumes/{original['id']}/restore-optimization/{opt.id}", headers=headers,
        )
    elif writer == "suggestion":
        original_text = r"\begin{document}"
        replacement_text = original_text if content == original["latex_content"] else original_text + "\n% source mutation\n"
        assert original["latex_content"].replace(original_text, replacement_text) == content
        response = await client.post(f"/resumes/{original['id']}/suggestion-decisions", headers=headers, json={
            "suggestion_id": token or f"test-source-{uuid4().hex}", "status": "accepted",
            "expected_content": original["latex_content"], "original_text": original_text,
            "replacement_text": replacement_text,
        })
    elif writer == "github":
        user = await db.get(User, original["user_id"])
        user.github_access_token = "synthetic-encrypted-token"
        user.github_username = "synthetic-user"
        user.user_metadata = {"github_oauth": {"scopes": ["repo"]}}
        saved = await db.get(Resume, original["id"], populate_existing=True)
        saved.github_sync_enabled = True
        saved.github_repo_name = "synthetic-repo"
        await db.commit()
        with (
            patch("app.api.github_routes.encryption_service.decrypt", return_value="synthetic-token"),
            patch("app.api.github_routes.github_sync_service.pull_file", new=AsyncMock(
                return_value={"content": content, "sha": "synthetic-revision"},
            )),
        ):
            response = await client.post(f"/github/resumes/{original['id']}/pull", headers=headers)
    elif writer == "finalization":
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        job_id = f"test_builder_finalization_{uuid4().hex}"
        db.add(JobFinalization(
            id=str(uuid4()), job_id=job_id, owner_token="synthetic-owner", owner_epoch=1,
            state="pending", lease_expires_at=future, expires_at=future,
            resume_id=original["id"], user_id=original["user_id"], resume_apply_requested=True,
        ))
        await db.commit()
        async with factory() as session:
            outcome = await commit_success(
                session, job_id=job_id, owner_token="synthetic-owner", owner_epoch=1,
                result_payload={"success": True, "optimized_latex": content},
                resume_content=content, resume_id=original["id"], resume_user_id=original["user_id"],
                expected_resume_sha256=sha256(original["latex_content"].encode()).hexdigest(),
            )
            assert outcome is FinalizationOutcome.ACCEPTED
            await session.commit()
        return
    else:
        assert await _persist_resume_content(
            original["id"], original["user_id"], content,
            expected_latex_content=original["latex_content"], session_factory=factory,
        ) is True
        return
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("variant", [False, True])
async def test_source_writer_detaches_and_blocks_stale_builder_save(
    client, auth_headers, db_session, db_session_factory, writer, variant,
):
    original, parent, _ = await _setup(client, auth_headers, db_session, variant=variant)
    changed = original["latex_content"].replace(r"\begin{document}", "\\begin{document}\n% source mutation\n")
    await _mutate(writer, original, changed, client, auth_headers, db_session, db_session_factory)
    for suffix in ("builder", "builder/v1"):
        stale = await client.patch(f"/resumes/{original['id']}/{suffix}", headers=auth_headers, json={
            "expected_structured_version": original["structured_version"],
            "structured_content": {"basics": {"name": "Stale Candidate"}},
        })
        assert stale.status_code == 409, stale.text
    saved = await db_session.get(Resume, original["id"], populate_existing=True)
    assert saved.latex_content == changed
    assert saved.builder_status == "detached"
    assert saved.content_source == "manual_latex"
    assert saved.variant_visibility is None
    assert saved.resume_settings == {"compiler": "lualatex", "share_anonymous": True,
                                     **({"github_sync_sha": "synthetic-revision"} if writer == "github" else {})}
    # Detached variants must also stay outside later parent regeneration.
    if variant:
        result = await client.patch(f"/resumes/{parent['id']}/builder/v1", headers=auth_headers, json={
            "expected_structured_version": parent["structured_version"],
            "structured_content": {"basics": {"name": "New Parent Candidate"}},
        })
        assert result.status_code == 200, result.text
        await db_session.refresh(saved)
        assert saved.latex_content == changed


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("variant", [False, True])
async def test_identical_source_keeps_builder_link_and_cached_pdf(
    client, auth_headers, db_session, db_session_factory, writer, variant,
):
    original, _, cached = await _setup(client, auth_headers, db_session, variant=variant)
    saved = await db_session.get(Resume, original["id"])
    old_updated_at = saved.updated_at
    await db_session.commit()
    await _mutate(writer, original, original["latex_content"], client, auth_headers, db_session, db_session_factory)
    await db_session.refresh(saved)
    assert saved.builder_status == "active"
    assert saved.content_source == ("builder_variant" if variant else "builder")
    assert saved.variant_visibility == original["variant_visibility"]
    assert saved.resume_settings == {**cached, **({"github_sync_sha": "synthetic-revision"} if writer == "github" else {})}
    if writer != "github":  # Pulls still record sync metadata/timing, even for unchanged source.
        assert saved.updated_at == old_updated_at


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["suggestion", "generated"])
async def test_source_mutation_replay_does_not_invalidate_a_new_pdf_cache(
    client, auth_headers, db_session, db_session_factory, writer,
):
    original, _, cached = await _setup(client, auth_headers, db_session)
    changed = original["latex_content"].replace(r"\begin{document}", "\\begin{document}\n% source mutation\n")
    token = f"test-source-replay-{uuid4().hex}"
    await _mutate(writer, original, changed, client, auth_headers, db_session, db_session_factory, token=token)
    saved = await db_session.get(Resume, original["id"], populate_existing=True)
    saved.resume_settings = cached
    await db_session.commit()
    await db_session.refresh(saved)
    old_updated_at = saved.updated_at
    await _mutate(writer, original, changed, client, auth_headers, db_session, db_session_factory, token=token)
    await db_session.refresh(saved)
    assert saved.latex_content == changed
    assert saved.resume_settings == cached
    assert saved.updated_at == old_updated_at


async def _wait_for_lock(factory, pid):
    async def wait():
        async with factory() as observer:
            while True:
                waiting = await observer.scalar(text(
                    "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                ), {"pid": pid})
                await observer.rollback()
                if waiting:
                    return
                await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), timeout=5)


@pytest.mark.asyncio
async def test_queued_parent_refresh_skips_a_newly_detached_variant(
    client, auth_headers, db_session, db_session_factory,
):
    variant, parent, _ = await _setup(client, auth_headers, db_session, variant=True)
    changed = variant["latex_content"] + "\n% Keep the external source"
    async with db_session_factory() as source_writer, db_session_factory() as parent_writer:
        # Prime the second identity map before the other transaction detaches.
        cached_variant = await parent_writer.get(Resume, variant["id"])
        assert cached_variant.content_source == "builder_variant"
        parent_row = await parent_writer.scalar(select(Resume).where(Resume.id == parent["id"]).with_for_update())
        variant_row = await source_writer.scalar(select(Resume).where(Resume.id == variant["id"]).with_for_update())
        pid = await parent_writer.scalar(text("SELECT pg_backend_pid()"))
        refresh = asyncio.create_task(_sync_linked_variants(parent_row, parent_writer))
        try:
            await _wait_for_lock(db_session_factory, pid)
            apply_source_change(variant_row, changed)
            await source_writer.commit()
            await refresh
            await parent_writer.commit()
        finally:
            await source_writer.rollback()
            if not refresh.done():
                refresh.cancel()
                await asyncio.gather(refresh, return_exceptions=True)
    saved = await db_session.get(Resume, variant["id"], populate_existing=True)
    assert saved.latex_content == changed
    assert saved.content_source == "manual_latex"
    assert saved.variant_visibility is None


@pytest.mark.asyncio
async def test_generated_writer_reloads_stale_session_before_snapshot_check(
    client, auth_headers, db_session, db_session_factory,
):
    original, _, _ = await _setup(client, auth_headers, db_session)
    async with db_session_factory() as generated, db_session_factory() as source_writer:
        cached = await generated.get(Resume, original["id"])
        updated = await source_writer.scalar(select(Resume).where(Resume.id == original["id"]).with_for_update())
        apply_source_change(updated, original["latex_content"] + "\n% Newer source")
        await source_writer.commit()
        with pytest.raises(ResumePersistenceConflict):
            await apply_resume_content(
                generated, resume_id=original["id"], user_id=original["user_id"],
                latex_content=original["latex_content"],
                expected_latex_sha256=sha256(original["latex_content"].encode()).hexdigest(),
            )
        assert cached.latex_content.endswith("% Newer source")
        await generated.rollback()


@pytest.mark.asyncio
async def test_queued_visibility_save_rechecks_variant_after_source_change(
    client, auth_headers, db_session, db_session_factory,
):
    variant, _, _ = await _setup(client, auth_headers, db_session, variant=True)
    changed = variant["latex_content"] + "\n% New authoritative variant source"
    async with db_session_factory() as source_writer, db_session_factory() as visibility_writer:
        locked = await source_writer.scalar(select(Resume).where(Resume.id == variant["id"]).with_for_update())
        cached = await visibility_writer.get(Resume, variant["id"])
        assert cached.content_source == "builder_variant"
        pid = await visibility_writer.scalar(text("SELECT pg_backend_pid()"))
        updating = asyncio.create_task(update_variant_visibility(
            variant["id"], VariantVisibilityUpdate(visibility={"hidden_sections": ["summary"]}),
            visibility_writer, variant["user_id"],
        ))
        try:
            await _wait_for_lock(db_session_factory, pid)
            apply_source_change(locked, changed)
            await source_writer.commit()
            with pytest.raises(HTTPException) as error:
                await updating
            assert error.value.status_code == 409
            await visibility_writer.rollback()
        finally:
            await source_writer.rollback()
            if not updating.done():
                updating.cancel()
                await asyncio.gather(updating, return_exceptions=True)
    saved = await db_session.get(Resume, variant["id"], populate_existing=True)
    assert saved.latex_content == changed
    assert saved.content_source == "manual_latex"
    assert saved.variant_visibility is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change_source", [False, True])
async def test_visibility_save_invalidates_pdf_only_if_rendered_source_changes(
    client, auth_headers, db_session, change_source,
):
    variant, _, cached = await _setup(client, auth_headers, db_session, variant=True)
    response = await client.patch(f"/resumes/{variant['id']}/variant-visibility", headers=auth_headers,
                                  json={"visibility": {"hidden_sections": ["summary"] if change_source else []}})
    assert response.status_code == 200, response.text
    saved = await db_session.get(Resume, variant["id"], populate_existing=True)
    assert saved.builder_status == "active"
    assert saved.content_source == "builder_variant"
    assert (saved.latex_content != variant["latex_content"]) is change_source
    assert saved.resume_settings == ({"compiler": "lualatex", "share_anonymous": True} if change_source else cached)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["restore", "suggestion"])
async def test_source_route_reloads_its_cached_resume_under_lock(
    client, auth_headers, db_session, db_session_factory, writer,
):
    original, _, _ = await _setup(client, auth_headers, db_session)
    cached = await db_session.get(Resume, original["id"])
    async with db_session_factory() as other_writer:
        saved = await other_writer.scalar(select(Resume).where(Resume.id == original["id"]).with_for_update())
        newer = original["latex_content"] + "\n% Newer source before row lock"
        apply_source_change(saved, newer)
        await other_writer.commit()
    assert cached.latex_content == original["latex_content"]
    if writer == "suggestion":
        response = await client.post(f"/resumes/{original['id']}/suggestion-decisions", headers=auth_headers, json={
            "suggestion_id": f"test-stale-session-{uuid4().hex}", "status": "accepted",
            "expected_content": original["latex_content"], "original_text": r"\begin{document}",
            "replacement_text": "Not applied",
        })
        assert response.status_code == 409, response.text
        expected = newer
    else:
        # The requested checkpoint equals the stale identity-map source, but
        # differs from the committed source. It still needs a real restore.
        await _mutate("restore", original, original["latex_content"], client, auth_headers, db_session, db_session_factory)
        expected = original["latex_content"]
    await db_session.refresh(cached)
    assert cached.latex_content == expected
    assert cached.builder_status == "detached"


@pytest.mark.asyncio
async def test_visibility_save_reloads_parent_after_waiting_for_its_builder_save(
    client, auth_headers, db_session, db_session_factory,
):
    variant, parent, _ = await _setup(client, auth_headers, db_session, variant=True)
    async with db_session_factory() as parent_writer, db_session_factory() as visibility_writer:
        locked_parent = await parent_writer.scalar(select(Resume).where(Resume.id == parent["id"]).with_for_update())
        cached_parent = await visibility_writer.get(Resume, parent["id"])
        assert cached_parent.structured_version == 1
        pid = await visibility_writer.scalar(text("SELECT pg_backend_pid()"))
        updating = asyncio.create_task(update_variant_visibility(
            variant["id"], VariantVisibilityUpdate(visibility={}), visibility_writer, variant["user_id"],
        ))
        try:
            await _wait_for_lock(db_session_factory, pid)
            locked_parent.structured_content = {
                **locked_parent.structured_content,
                "basics": {**locked_parent.structured_content["basics"], "name": "New Parent Name"},
            }
            locked_parent.structured_version = 2
            await parent_writer.commit()
            response = await updating
            assert response.resume.structured_version == 2
            assert "New Parent Name" in response.resume.latex_content
        finally:
            await parent_writer.rollback()
            if not updating.done():
                updating.cancel()
                await asyncio.gather(updating, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("disable_during_fetch", [False, True])
async def test_github_pull_reloads_state_after_remote_fetch(
    client, auth_headers, db_session, db_session_factory, disable_during_fetch,
):
    original, _, _ = await _setup(client, auth_headers, db_session, variant=True)
    user = await db_session.get(User, original["user_id"])
    user.github_access_token = "synthetic-encrypted-token"
    user.github_username = "synthetic-user"
    user.user_metadata = {"github_oauth": {"scopes": ["repo"]}}
    resume = await db_session.get(Resume, original["id"])
    resume.github_sync_enabled = True
    resume.github_repo_name = "synthetic-repo"
    await db_session.commit()
    remote_content = original["latex_content"] + "\n% Remote source"

    async def remote_fetch(**_kwargs):
        async with db_session_factory() as concurrent:
            current = await concurrent.scalar(select(Resume).where(Resume.id == original["id"]).with_for_update())
            current.resume_settings = {**current.resume_settings, "concurrent_metadata": "preserve"}
            if disable_during_fetch:
                current.github_sync_enabled = False
            await concurrent.commit()
        return {"content": remote_content, "sha": "synthetic-sha"}

    with (
        patch("app.api.github_routes.encryption_service.decrypt", return_value="synthetic-token"),
        patch("app.api.github_routes.github_sync_service.pull_file", new=AsyncMock(side_effect=remote_fetch)),
    ):
        response = await client.post(f"/github/resumes/{original['id']}/pull", headers=auth_headers)
    assert response.status_code == (409 if disable_during_fetch else 200), response.text
    await db_session.refresh(resume)
    assert resume.resume_settings["concurrent_metadata"] == "preserve"
    assert resume.latex_content == (original["latex_content"] if disable_during_fetch else remote_content)
    assert resume.content_source == ("builder_variant" if disable_during_fetch else "manual_latex")

"""PostgreSQL regression for F04 collaborator-role rechecks under contention."""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text, update

from app.api.resume_routes import CollaboratorRoleUpdate, update_collaborator_role
from app.database.models import ResumeCollaborator
from app.services.entitlement_service import entitlement_service


async def _user_id(db, headers):
    return await db.scalar(
        text('SELECT "userId" FROM session WHERE token = :token'),
        {"token": headers["Authorization"].removeprefix("Bearer ")},
    )


async def test_viewer_promotion_rechecks_role_after_concurrent_downgrade(
    client, db_session, db_session_factory, auth_headers, auth_headers2
):
    owner_id = await _user_id(db_session, auth_headers)
    collaborator_id = await _user_id(db_session, auth_headers2)
    created = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": "Collaborator role lock", "latex_content": "owned source"},
    )
    assert created.status_code == 201, created.text
    resume_id = created.json()["id"]
    db_session.add(
        ResumeCollaborator(
            resume_id=resume_id,
            user_id=collaborator_id,
            role="editor",
            invited_by=owner_id,
        )
    )
    await db_session.commit()

    await entitlement_service.set_kill_switch("f04", False, db_session)
    try:
        async with db_session_factory() as holder:
            await holder.begin()
            row = await holder.scalar(
                select(ResumeCollaborator)
                .where(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == collaborator_id,
                )
                .with_for_update()
            )
            assert row is not None and row.role == "editor"

            query_started = asyncio.Event()

            def observe_locked_read(_conn, _cursor, statement, _params, _context, _many):
                normalized = statement.lower()
                if "from resume_collaborators" in normalized and "for update" in normalized:
                    query_started.set()

            sync_engine = db_session.get_bind()
            event.listen(sync_engine, "before_cursor_execute", observe_locked_read)
            try:
                async with db_session_factory() as update_session:
                    request = asyncio.create_task(
                        update_collaborator_role(
                            resume_id,
                            collaborator_id,
                            CollaboratorRoleUpdate(role="commenter"),
                            db=update_session,
                            user_id=owner_id,
                        )
                    )
                    await asyncio.wait_for(query_started.wait(), timeout=5)
                    await asyncio.sleep(0.05)
                    assert not request.done(), "the concurrent role read should wait on the row lock"

                    await holder.execute(
                        update(ResumeCollaborator).where(ResumeCollaborator.id == row.id).values(role="viewer")
                    )
                    await holder.commit()

                    with pytest.raises(HTTPException) as denied:
                        await asyncio.wait_for(request, timeout=5)
                assert denied.value.status_code == 403
                assert "f04" in str(denied.value.detail)
            finally:
                event.remove(sync_engine, "before_cursor_execute", observe_locked_read)

        assert (
            await db_session.scalar(
                select(ResumeCollaborator.role).where(
                    ResumeCollaborator.resume_id == resume_id,
                    ResumeCollaborator.user_id == collaborator_id,
                )
            )
            == "viewer"
        )
    finally:
        await entitlement_service.set_kill_switch("f04", True, db_session)

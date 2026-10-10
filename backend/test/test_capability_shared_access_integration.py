"""Real-DB admission/recovery tests; no email, payment or provider calls."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database.models import ResumeCollaborator, Workspace, WorkspaceMember, WorkspaceResume
from app.services.entitlement_service import entitlement_service


async def _user_id(db, headers):
    return await db.scalar(text('SELECT "userId" FROM session WHERE token = :token'), {
        "token": headers["Authorization"].removeprefix("Bearer "),
    })


async def _resume(client, headers, title):
    result = await client.post("/resumes/", headers=headers, json={"title": title, "latex_content": "owned source"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


@pytest.mark.parametrize("disabled_role", ["user", "support"])
async def test_owner_and_collaborator_account_roles_intersect_live_sharing_and_reenable(
    client, db_session, auth_headers, auth_headers2, disabled_role,
):
    owner = await _user_id(db_session, auth_headers)
    actor = await _user_id(db_session, auth_headers2)
    await db_session.execute(text("UPDATE users SET role='support' WHERE id=:id"), {"id": actor})
    resume_id = await _resume(client, auth_headers, "Role-scoped collaboration")
    db_session.add(ResumeCollaborator(resume_id=resume_id, user_id=actor, role="editor", invited_by=owner))
    await db_session.commit()
    try:
        await entitlement_service.set_role_cell(disabled_role, "f04", True, db_session)
        assert (await client.get(f"/resumes/{resume_id}", headers=auth_headers2)).status_code == 200
        await entitlement_service.set_role_cell(disabled_role, "f04", False, db_session)
        denied = await client.get(f"/resumes/{resume_id}", headers=auth_headers2)
        assert denied.status_code == 403, denied.text
        denied_write = await client.put(f"/resumes/{resume_id}", headers=auth_headers2, json={
            "latex_content": "collaborator changed", "expected_latex_content": "owned source",
        })
        assert denied_write.status_code == 403
        own_read = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert own_read.status_code == 200
        assert own_read.json()["latex_content"] == "owned source"
        await entitlement_service.set_role_cell(disabled_role, "f04", True, db_session)
        restored = await client.get(f"/resumes/{resume_id}", headers=auth_headers2)
        assert restored.status_code == 200
        assert restored.json()["access_role"] == "editor"
    finally:
        await entitlement_service.set_role_cell(disabled_role, "f04", True, db_session)


async def test_disabled_workspace_hides_shared_documents_but_retains_own_submission_and_removal(
    client, db_session, auth_headers, auth_headers2,
):
    owner = await _user_id(db_session, auth_headers)
    actor = await _user_id(db_session, auth_headers2)
    theirs = await _resume(client, auth_headers, "Workspace owner's document")
    own = await _resume(client, auth_headers2, "My submitted document")
    workspace_id = str(uuid4())
    db_session.add(Workspace(id=workspace_id, name="Shared test workspace", owner_id=owner))
    await db_session.flush()
    db_session.add_all([
        WorkspaceMember(workspace_id=workspace_id, user_id=owner, role="owner"),
        WorkspaceMember(workspace_id=workspace_id, user_id=actor, role="editor"),
        WorkspaceResume(workspace_id=workspace_id, resume_id=theirs, shared_by=owner),
        WorkspaceResume(workspace_id=workspace_id, resume_id=own, shared_by=actor),
    ])
    await db_session.commit()
    try:
        await entitlement_service.set_kill_switch("f08", True, db_session)
        before = await client.get(f"/workspaces/{workspace_id}/resumes", headers=auth_headers2)
        assert before.status_code == 200, before.text
        assert {item["id"] for item in before.json()} == {own, theirs}
        await entitlement_service.set_kill_switch("f08", False, db_session)
        after = await client.get(f"/workspaces/{workspace_id}/resumes", headers=auth_headers2)
        assert after.status_code == 200, after.text
        assert [item["id"] for item in after.json()] == [own]
        forbidden_pdf = await client.get(f"/workspaces/{workspace_id}/resumes/{theirs}/download", headers=auth_headers2)
        assert forbidden_pdf.status_code == 403
        own_source = await client.get(f"/resumes/{own}", headers=auth_headers2)
        assert own_source.status_code == 200
        removed = await client.delete(f"/workspaces/{workspace_id}/resumes/{own}", headers=auth_headers2)
        assert removed.status_code == 204
    finally:
        await entitlement_service.set_kill_switch("f08", True, db_session)


async def test_public_review_off_blocks_existing_link_but_owner_can_revoke_review(
    client, db_session, auth_headers,
):
    resume_id = await _resume(client, auth_headers, "Review recovery")
    link = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers, json={"review_comments": True})
    assert link.status_code == 200, link.text
    token = link.json()["share_token"]
    try:
        await entitlement_service.set_kill_switch("f03", False, db_session)
        assert (await client.get(f"/share/{token}/review-comments")).status_code == 404
        await entitlement_service.set_kill_switch("f01", False, db_session)
        revoke = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers, json={"review_comments": "false"})
        assert revoke.status_code == 200, revoke.text
        assert revoke.json()["review_comments"] is False
        assert revoke.json()["share_token"] == token
        assert (await client.get(f"/resumes/{resume_id}", headers=auth_headers)).status_code == 200
        assert (await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)).status_code == 204
    finally:
        await entitlement_service.set_kill_switch("f01", True, db_session)
        await entitlement_service.set_kill_switch("f03", True, db_session)

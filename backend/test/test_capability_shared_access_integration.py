"""Real-DB admission/recovery tests; no email, payment or provider calls."""
import base64
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database.models import Compilation, ResumeCollaborator, Workspace, WorkspaceMember, WorkspaceResume
from app.services.entitlement_service import entitlement_service


async def _user_id(db, headers):
    return await db.scalar(text('SELECT "userId" FROM session WHERE token = :token'), {
        "token": headers["Authorization"].removeprefix("Bearer "),
    })


async def _resume(client, headers, title):
    result = await client.post("/resumes/", headers=headers, json={"title": title, "latex_content": "owned source"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


async def _accepted_pdf(db, resume_id, owner, monkeypatch):
    """Use actual PDF bytes and an explicitly accepted row, isolating only storage."""
    pdf = (Path(__file__).parent / "fixtures" / "accepted-sharing.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-")
    key = f"compilations/{uuid4()}/accepted.pdf"
    pdf_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode()

    def presign(requested_key, **_kwargs):
        assert requested_key == key
        return pdf_url

    monkeypatch.setattr("app.services.storage_service.generate_presigned_url", presign)
    db.add(Compilation(
        resume_id=resume_id, user_id=owner, job_id=str(uuid4()), status="completed",
        artifact_accepted=True, artifact_branch="draft", pdf_path=key, pdf_size=len(pdf),
    ))
    await db.commit()
    return pdf_url


async def _assert_public_pdf(client, token, pdf_url, *, review_comments=None):
    response = await client.get(f"/share/{token}")
    assert response.status_code == 200, response.text
    assert response.json()["share_token"] == token
    assert response.json()["pdf_url"] == pdf_url
    assert base64.b64decode(response.json()["pdf_url"].split(",", 1)[1]).startswith(b"%PDF-")
    if review_comments is not None:
        assert response.json()["review_comments"] is review_comments


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
    client, db_session, auth_headers, monkeypatch,
):
    resume_id = await _resume(client, auth_headers, "Review recovery")
    pdf_url = await _accepted_pdf(db_session, resume_id, await _user_id(db_session, auth_headers), monkeypatch)
    link = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers, json={"review_comments": True})
    assert link.status_code == 200, link.text
    token = link.json()["share_token"]
    try:
        await _assert_public_pdf(client, token, pdf_url, review_comments=True)
        assert (await client.get(f"/share/{token}/review-comments")).status_code == 200
        await entitlement_service.set_kill_switch("f03", False, db_session)
        assert (await client.get(f"/share/{token}/review-comments")).status_code == 404
        await _assert_public_pdf(client, token, pdf_url, review_comments=False)
        await entitlement_service.set_kill_switch("f03", True, db_session)
        assert (await client.get(f"/share/{token}/review-comments")).status_code == 200
        await entitlement_service.set_kill_switch("f01", False, db_session)
        assert (await client.get(f"/share/{token}")).status_code == 404
        revoke = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers, json={"review_comments": "false"})
        assert revoke.status_code == 200, revoke.text
        assert revoke.json()["review_comments"] is False
        assert revoke.json()["share_token"] == token
        assert (await client.get(f"/resumes/{resume_id}", headers=auth_headers)).status_code == 200
        assert (await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)).status_code == 204
        await entitlement_service.set_kill_switch("f01", True, db_session)
        assert (await client.get(f"/share/{token}")).status_code == 404
    finally:
        await entitlement_service.set_kill_switch("f01", True, db_session)
        await entitlement_service.set_kill_switch("f03", True, db_session)


async def test_share_child_denials_compose_across_role_plan_sku_and_parent_with_owner_recovery(
    client, db_session, auth_headers, auth_headers2, monkeypatch,
):
    """A child grant cannot outrank any owner-policy axis; private recovery remains available."""
    owner = await _user_id(db_session, auth_headers)
    unrelated_user = await _user_id(db_session, auth_headers2)
    original_plan = await db_session.scalar(
        text("SELECT subscription_plan FROM users WHERE id = :id"), {"id": owner},
    )
    original_subscription_status = await db_session.scalar(
        text("SELECT subscription_status FROM users WHERE id = :id"), {"id": owner},
    )
    original_owner_role = await db_session.scalar(
        text("SELECT role FROM users WHERE id = :id"), {"id": owner},
    )
    original_unrelated_role = await db_session.scalar(
        text("SELECT role FROM users WHERE id = :id"), {"id": unrelated_user},
    )
    original_unrelated_plan = await db_session.scalar(
        text("SELECT subscription_plan FROM users WHERE id = :id"), {"id": unrelated_user},
    )
    original_unrelated_status = await db_session.scalar(
        text("SELECT subscription_status FROM users WHERE id = :id"), {"id": unrelated_user},
    )
    original_policy = await entitlement_service.get_state()
    controlled_keys = ("collaboration", "f01", "f03", "resume_builder", "b01", "c01")
    original_globals = {key: original_policy["kill_switches"][key] for key in controlled_keys}
    original_plans = {
        (plan, key): original_policy["matrix"][plan][key]
        for plan in ("pro", "pro_annual")
        for key in controlled_keys
    }
    original_roles = {key: original_policy["role_matrix"]["user"][key] for key in controlled_keys}
    await db_session.execute(
        text("UPDATE users SET role = 'user', subscription_plan = 'pro_annual', subscription_status = 'active' WHERE id = :id"),
        {"id": owner},
    )
    await db_session.execute(
        text("UPDATE users SET role = 'user', subscription_plan = 'pro_annual', subscription_status = 'active' WHERE id = :id"),
        {"id": unrelated_user},
    )
    await db_session.commit()

    try:
        for key in controlled_keys:
            await entitlement_service.set_kill_switch(key, True, db_session)
            await entitlement_service.set_matrix_cell("pro", key, True, db_session)
            await entitlement_service.set_matrix_cell("pro_annual", key, True, db_session)
            await entitlement_service.set_role_cell("user", key, True, db_session)

        resume_id = await _resume(client, auth_headers, "Synthetic child-control owner")
        pdf_url = await _accepted_pdf(db_session, resume_id, owner, monkeypatch)
        created = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"review_comments": True},
        )
        assert created.status_code == 200, created.text
        share_token = created.json()["share_token"]
        await _assert_public_pdf(client, share_token, pdf_url, review_comments=True)
        effective = await client.get("/config/entitlements?include_quotas=false", headers=auth_headers)
        assert effective.status_code == 200
        assert effective.json()["features"]["f01"] is True
        unrelated_effective = await client.get(
            "/config/entitlements?include_quotas=false", headers=auth_headers2,
        )
        assert unrelated_effective.status_code == 200
        assert unrelated_effective.json()["features"]["f01"] is True
        wrong_owner_share = await client.post(
            f"/resumes/{resume_id}/share", headers=auth_headers2,
        )
        assert wrong_owner_share.status_code == 404
        assert (await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers2)).status_code == 404
        assert (await client.put(f"/resumes/{resume_id}", headers=auth_headers2, json={
            "latex_content": "unrelated write", "expected_latex_content": "owned source",
        })).status_code == 404

        # These are ordinary independent accounts. Product permission does not
        # become document ownership or a collaborator ACL.
        assert await db_session.scalar(
            text("SELECT role FROM users WHERE id = :id"), {"id": owner},
        ) == "user"
        assert await db_session.scalar(
            text("SELECT role FROM users WHERE id = :id"), {"id": unrelated_user},
        ) == "user"
        assert (await client.get(f"/resumes/{resume_id}", headers=auth_headers2)).status_code == 404

        async def share_again():
            return await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)

        # A retained authenticated client request must be rechecked against
        # authoritative account role, plan family and exact SKU state.
        await entitlement_service.set_role_cell("user", "f01", False, db_session)
        assert (await share_again()).status_code == 403
        assert (await client.get(f"/share/{share_token}")).status_code == 404
        await entitlement_service.set_role_cell("user", "f01", True, db_session)
        await _assert_public_pdf(client, share_token, pdf_url)

        await entitlement_service.set_matrix_cell("pro", "f01", False, db_session)
        assert (await share_again()).status_code == 403
        assert (await client.get(f"/share/{share_token}")).status_code == 404
        await entitlement_service.set_matrix_cell("pro", "f01", True, db_session)
        await _assert_public_pdf(client, share_token, pdf_url)

        await entitlement_service.set_matrix_cell("pro_annual", "f01", False, db_session)
        assert (await share_again()).status_code == 403
        assert (await client.get(f"/share/{share_token}")).status_code == 404
        await entitlement_service.set_matrix_cell("pro_annual", "f01", True, db_session)
        await _assert_public_pdf(client, share_token, pdf_url)

        # The F01 child remains explicitly ON while its collaboration parent is
        # OFF. The public serving route and new link admission both fail closed.
        await entitlement_service.set_kill_switch("collaboration", False, db_session)
        state = await entitlement_service.get_state()
        assert state["kill_switches"]["f01"] is True
        assert state["kill_switches"]["collaboration"] is False
        effective = await client.get("/config/entitlements", headers=auth_headers)
        assert effective.status_code == 200
        assert effective.json()["features"]["f01"] is False
        assert (await share_again()).status_code == 403
        parent_blocked_share = await client.post(
            f"/resumes/{resume_id}/share", headers=auth_headers2,
        )
        assert parent_blocked_share.status_code == 403
        assert (await client.get(f"/share/{share_token}")).status_code == 404
        await entitlement_service.set_kill_switch("collaboration", True, db_session)
        await _assert_public_pdf(client, share_token, pdf_url)
        await entitlement_service.set_kill_switch("collaboration", False, db_session)

        # Disabling review and revoking the existing link are owned recovery
        # operations, even while new public sharing is disabled.
        revoke_review = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"review_comments": False},
        )
        assert revoke_review.status_code == 200, revoke_review.text
        assert revoke_review.json()["share_token"] == share_token
        assert revoke_review.json()["review_comments"] is False
        own_source = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert own_source.status_code == 200
        assert own_source.json()["latex_content"] == "owned source"
        assert (await client.get(f"/resumes/{resume_id}", headers=auth_headers2)).status_code == 404
        assert (await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)).status_code == 204

        await entitlement_service.set_kill_switch("collaboration", True, db_session)
        restored = await share_again()
        assert restored.status_code == 200, restored.text
        replacement_token = restored.json()["share_token"]
        assert replacement_token != share_token
        await _assert_public_pdf(client, replacement_token, pdf_url, review_comments=False)
        assert (await client.get(f"/share/{share_token}")).status_code == 404
        assert (await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)).status_code == 204
        assert (await client.get(f"/share/{replacement_token}")).status_code == 404
    finally:
        for key, enabled in original_globals.items():
            await entitlement_service.set_kill_switch(key, enabled, db_session)
        for (plan, key), enabled in original_plans.items():
            await entitlement_service.set_matrix_cell(plan, key, enabled, db_session)
        for key, enabled in original_roles.items():
            await entitlement_service.set_role_cell("user", key, enabled, db_session)
        await db_session.execute(
            text("UPDATE users SET role = :role, subscription_plan = :plan, subscription_status = :status WHERE id = :id"),
            {"role": original_owner_role, "plan": original_plan, "status": original_subscription_status, "id": owner},
        )
        await db_session.execute(
            text("UPDATE users SET role = :role, subscription_plan = :plan, subscription_status = :status WHERE id = :id"),
            {
                "role": original_unrelated_role,
                "plan": original_unrelated_plan,
                "status": original_unrelated_status,
                "id": unrelated_user,
            },
        )
        await db_session.commit()

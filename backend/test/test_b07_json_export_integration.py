"""Real disposable PostgreSQL/API coverage for B07 JSON export controls."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database.models import ResumeTemplate
from app.services.entitlement_service import entitlement_service
from test._entitlement_reset import reset_entitlements_baseline


@pytest.fixture(autouse=True)
async def restore_capability_policy():
    # These are real shared policy rows in the disposable CI database. Keep the
    # test independent of its order and return the full policy plane to baseline.
    await reset_entitlements_baseline()
    yield
    await reset_entitlements_baseline()


async def _user_id(db, headers):
    token = headers["Authorization"].removeprefix("Bearer ")
    return await db.scalar(
        text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
    )


async def test_b07_toggle_denies_all_json_export_routes_and_recovers_with_owner_acl(
    client, db_session, auth_headers, auth_headers2,
):
    owner_id = await _user_id(db_session, auth_headers)
    other_id = await _user_id(db_session, auth_headers2)
    for user_id in (owner_id, other_id):
        await db_session.execute(
            text(
                "UPDATE users SET role = 'user', subscription_plan = 'pro_annual', "
                "subscription_status = 'active' WHERE id = :id"
            ),
            {"id": user_id},
        )
    await db_session.commit()
    for user_id in (owner_id, other_id):
        role = await db_session.scalar(
            text("SELECT role FROM users WHERE id = :id"), {"id": user_id}
        )
        assert role == "user"

    source = r"\documentclass{article}\begin{document}Synthetic B07 owner.\end{document}"
    created = await client.post(
        "/resumes/", headers=auth_headers,
        json={"title": "Synthetic B07 saved resume", "latex_content": source},
    )
    assert created.status_code == 201, created.text
    saved_resume_id = created.json()["id"]

    template_id = str(uuid4())
    db_session.add(ResumeTemplate(
        id=template_id,
        name=f"test_tmpl_b07_{uuid4().hex}",
        description="Synthetic B07 builder fixture",
        category="minimal",
        tags=["minimal"],
        latex_content=r"\documentclass{article}\begin{document}Template.\end{document}",
        is_active=True,
        sort_order=0,
        document_type="resume",
    ))
    await db_session.commit()
    builder_created = await client.post(
        "/resumes/builder/v1",
        headers=auth_headers,
        json={
            "title": "Synthetic B07 builder resume",
            "template_id": template_id,
            "structured_content": {
                "basics": {"name": "Synthetic B07 Candidate", "email": "b07@example.test"}
            },
        },
    )
    assert builder_created.status_code == 201, builder_created.text
    builder_resume = builder_created.json()["resume"]
    builder_resume_id = builder_resume["id"]
    assert builder_resume["content_source"] == "builder"
    assert builder_resume["builder_status"] == "active"
    assert builder_resume["structured_content"]["basics"]["name"] == "Synthetic B07 Candidate"

    enabled = await client.get("/config/entitlements?include_quotas=false", headers=auth_headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["features"]["h01"] is True
    assert enabled.json()["features"]["b07"] is True

    # With B07 enabled, an unrelated ordinary account reaches the resource ACL.
    cross_owner = await client.get(
        f"/export/{saved_resume_id}/json", headers=auth_headers2,
    )
    assert cross_owner.status_code == 403, cross_owner.text
    assert cross_owner.json()["detail"] == "Access denied"
    cross_owner_builder = await client.get(
        f"/export/builder/v1/{builder_resume_id}/json", headers=auth_headers2,
    )
    assert cross_owner_builder.status_code == 403, cross_owner_builder.text
    assert cross_owner_builder.json()["detail"] == "Access denied"

    # B07 remains denied when either the ordinary-user role cell or the
    # concrete annual plan cell is switched off, even with global B07 on.
    await entitlement_service.set_role_cell("user", "b07", False, db_session)
    role_denied = await client.get(
        f"/export/{saved_resume_id}/json", headers=auth_headers,
    )
    assert role_denied.status_code == 403, role_denied.text
    assert "b07" in role_denied.text
    await entitlement_service.set_role_cell("user", "b07", True, db_session)

    await entitlement_service.set_matrix_cell("pro", "b07", True, db_session)
    await entitlement_service.set_matrix_cell("pro_annual", "b07", False, db_session)
    plan_denied = await client.get(
        f"/export/{saved_resume_id}/json", headers=auth_headers,
    )
    assert plan_denied.status_code == 403, plan_denied.text
    assert "b07" in plan_denied.text
    await entitlement_service.set_matrix_cell("pro_annual", "b07", True, db_session)

    # H01 is B07's parent. Turning the parent off must block JSON even while
    # B07's own global, plan and role cells all allow it.
    await entitlement_service.set_kill_switch("h01", False, db_session)
    parent_denied = await client.get(
        f"/export/{saved_resume_id}/json", headers=auth_headers,
    )
    assert parent_denied.status_code == 403, parent_denied.text
    assert "h01" in parent_denied.text
    parent_denied_builder = await client.get(
        f"/export/builder/v1/{builder_resume_id}/json", headers=auth_headers,
    )
    assert parent_denied_builder.status_code == 403, parent_denied_builder.text
    assert "h01" in parent_denied_builder.text
    await entitlement_service.set_kill_switch("h01", True, db_session)

    await entitlement_service.set_kill_switch("b07", False, db_session)
    disabled = await client.get("/config/entitlements?include_quotas=false", headers=auth_headers)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["features"]["h01"] is True
    assert disabled.json()["features"]["b07"] is False

    denied_responses = [
        await client.post(
            "/export/content/json", headers=auth_headers,
            json={"latex_content": source},
        ),
        await client.get(f"/export/{saved_resume_id}/json", headers=auth_headers),
        await client.get(f"/export/builder/v1/{builder_resume_id}/json", headers=auth_headers),
    ]
    for response in denied_responses:
        assert response.status_code == 403, response.text
        assert "feature_disabled" in response.text
        assert "b07" in response.text

    # Export admission being off does not disable the owner's existing source.
    source_recovery = await client.get(f"/resumes/{saved_resume_id}", headers=auth_headers)
    assert source_recovery.status_code == 200, source_recovery.text
    assert source_recovery.json()["latex_content"] == source
    builder_source_recovery = await client.get(
        f"/resumes/{builder_resume_id}/builder/v1", headers=auth_headers,
    )
    assert builder_source_recovery.status_code == 200, builder_source_recovery.text
    assert builder_source_recovery.json()["resume"]["content_source"] == "builder"
    assert (
        builder_source_recovery.json()["resume"]["structured_content"]["basics"]["name"]
        == "Synthetic B07 Candidate"
    )

    await entitlement_service.set_kill_switch("b07", True, db_session)
    recovered = await client.get("/config/entitlements?include_quotas=false", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["features"]["h01"] is True
    assert recovered.json()["features"]["b07"] is True

    allowed_responses = [
        await client.post(
            "/export/content/json", headers=auth_headers,
            json={"latex_content": source},
        ),
        await client.get(f"/export/{saved_resume_id}/json", headers=auth_headers),
        await client.get(f"/export/builder/v1/{builder_resume_id}/json", headers=auth_headers),
    ]
    for response in allowed_responses:
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        assert isinstance(response.json(), dict)
        assert "basics" in response.json()
    assert allowed_responses[2].json()["basics"]["name"] == "Synthetic B07 Candidate"

    # Re-enabling B07 restores export for the owner without changing the ACL.
    still_cross_owner = await client.get(
        f"/export/{saved_resume_id}/json", headers=auth_headers2,
    )
    assert still_cross_owner.status_code == 403, still_cross_owner.text
    assert still_cross_owner.json()["detail"] == "Access denied"
    still_cross_owner_builder = await client.get(
        f"/export/builder/v1/{builder_resume_id}/json", headers=auth_headers2,
    )
    assert still_cross_owner_builder.status_code == 403, still_cross_owner_builder.text
    assert still_cross_owner_builder.json()["detail"] == "Access denied"


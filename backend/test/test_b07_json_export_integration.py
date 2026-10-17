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
                "UPDATE users SET subscription_plan = 'pro_annual', "
                "subscription_status = 'active' WHERE id = :id"
            ),
            {"id": user_id},
        )
    await db_session.commit()

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
    builder_resume_id = builder_created.json()["resume"]["id"]

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

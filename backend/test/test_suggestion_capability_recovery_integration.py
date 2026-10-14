"""PostgreSQL/Redis-backed suggestion recovery with actual account/plan policy.

No LLM, mail, payment, or other external provider is involved.
"""
import pytest
from sqlalchemy import select

from app.database.models import Resume, ResumeSuggestionDecision
from app.services.entitlement_service import entitlement_service
from test._entitlement_reset import reset_entitlements_baseline
from test.test_admin_control_plane_api import _create_session, _create_user

SOURCE = "Before Target After"


def body(content, suggestion_id, status="accepted", original="Target", replacement="Changed"):
    return dict(suggestion_id=suggestion_id, status=status, expected_content=content,
                original_text=original, replacement_text=replacement, prefix="Before ", suffix=" After")


@pytest.fixture(autouse=True)
async def restore_grants():
    yield
    await reset_entitlements_baseline()


async def account(db, role, plan="pro_annual"):
    user_id, _ = await _create_user(db, role=role, plan=plan)
    token = await _create_session(db, user_id)
    return user_id, {"Authorization": f"Bearer {token}"}


async def switch(db, axis, role, key, enabled):
    if axis == "global":
        await entitlement_service.set_kill_switch(key, enabled, db)
    elif axis == "role":
        await entitlement_service.set_role_cell(role, key, enabled, db)
    else:
        await entitlement_service.set_matrix_cell("pro_annual", key, enabled, db)


@pytest.mark.parametrize("role", ["user", "support", "admin"])
@pytest.mark.parametrize("axis", ["global", "role", "sku"])
@pytest.mark.parametrize("key", ["f07", "c01"])
async def test_real_policy_off_preserves_recovery_and_on_restores_acceptance(client, db_session, role, axis, key):
    owner, auth = await account(db_session, role)
    created = await client.post("/resumes/", headers=auth, json={"title": "Recovery policy", "latex_content": SOURCE})
    assert created.status_code == 201, created.text
    resume_id = created.json()["id"]
    path = f"/resumes/{resume_id}/suggestion-decisions"
    accepted = await client.post(path, headers=auth, json=body(SOURCE, "peer:seed"))
    assert accepted.status_code == 200, accepted.text
    current = accepted.json()["latex_content"]
    assert current == "Before Changed After"

    await switch(db_session, axis, role, key, False)
    features = (await client.get("/config/entitlements", headers=auth)).json()["features"]
    assert features[key] is False
    blocked = await client.post(path, headers=auth, json=body(current, "peer:blocked", original="Changed", replacement="Final"))
    assert blocked.status_code == 403 and key in blocked.text
    retry = await client.post(path, headers=auth, json=body(SOURCE, "peer:seed"))
    assert retry.status_code == 403, retry.text

    for status in ["rejected", "conflicted"]:
        recovered = await client.post(path, headers=auth, json=body(current, "peer:" + status, status))
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == status and recovered.json()["latex_content"] == ""
    first_wins = await client.post(path, headers=auth, json=body("stale", "peer:seed", "conflicted"))
    assert first_wins.status_code == 200, first_wins.text
    assert first_wins.json()["status"] == "accepted" and first_wins.json()["replayed"] is True
    recovered = await client.get(path + "/peer:seed", headers=auth)
    assert recovered.status_code == 200 and recovered.json()["latex_content"] == current
    rows = (await db_session.execute(select(ResumeSuggestionDecision).where(ResumeSuggestionDecision.resume_id == resume_id))).scalars().all()
    assert {row.suggestion_id: row.status for row in rows} == {
        "peer:seed": "accepted", "peer:rejected": "rejected", "peer:conflicted": "conflicted",
    }
    resume = (await db_session.execute(select(Resume).where(Resume.id == resume_id).execution_options(populate_existing=True))).scalar_one()
    assert resume.user_id == owner and resume.latex_content == current

    await switch(db_session, axis, role, key, True)
    assert (await client.get("/config/entitlements", headers=auth)).json()["features"][key] is True
    final = await client.post(path, headers=auth, json=body(current, "peer:enabled", original="Changed", replacement="Final"))
    assert final.status_code == 200 and final.json()["latex_content"] == "Before Final After"


async def test_parent_collaboration_off_still_preserves_owned_recovery(client, db_session):
    _, auth = await account(db_session, "user")
    created = await client.post("/resumes/", headers=auth, json={"title": "Parent recovery", "latex_content": SOURCE})
    assert created.status_code == 201, created.text
    path = f"/resumes/{created.json()['id']}/suggestion-decisions"
    await entitlement_service.set_kill_switch("collaboration", False, db_session)
    blocked = await client.post(path, headers=auth, json=body(SOURCE, "peer:blocked"))
    assert blocked.status_code == 403 and "f07" in blocked.text
    rejected = await client.post(path, headers=auth, json=body(SOURCE, "peer:reject", "rejected"))
    assert rejected.status_code == 200, rejected.text
    assert (await client.get(path + "/peer:reject", headers=auth)).status_code == 200

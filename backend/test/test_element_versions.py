"""B52 immutable per-element history contract."""

import asyncio
import base64
import json

import pytest
from httpx import AsyncClient

LATEX = r"""\documentclass{article}\begin{document}\begin{itemize}\item Baseline\end{itemize}\end{document}"""


async def _resume(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/resumes/",
        headers=headers,
        json={"title": "test_element_versions", "latex_content": LATEX},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_element_history_is_immutable_paginated_and_restore_is_a_new_snapshot(
    client: AsyncClient, pro_auth_headers: dict
) -> None:
    resume_id = await _resume(client, pro_auth_headers)
    first = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": r"\item Built the first system.",
            "provenance": {"provider": "manual"},
            "idempotency_key": "test-version-first",
        },
    )
    assert first.status_code == 201, first.text
    first_data = first.json()
    assert first_data["operation"] == "create"
    assert first_data["parent_version_id"] is None
    assert first_data["root_version_id"] == first_data["id"]
    mismatched_replay = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": r"\item Different payload.",
            "idempotency_key": "test-version-first",
        },
    )
    assert mismatched_replay.status_code == 409
    mismatched_metadata = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": first_data["content"],
            "element_type": "paragraph",
            "provenance": {"provider": "different"},
            "idempotency_key": "test-version-first",
        },
    )
    assert mismatched_metadata.status_code == 409

    second = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": r"\item Built the resilient system.",
            "operation": "edit",
            "source": "ai",
            "parent_version_id": first_data["id"],
            "expected_head_version_id": first_data["id"],
        },
    )
    assert second.status_code == 201, second.text
    second_data = second.json()
    assert second_data["parent_version_id"] == first_data["id"]
    assert second_data["root_version_id"] == first_data["id"]

    page = await client.get(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        params={"element_key": "experience:exp-1:bullet:0", "limit": 1},
    )
    assert page.status_code == 200, page.text
    assert [item["id"] for item in page.json()["items"]] == [second_data["id"]]
    assert page.json()["next_cursor"]
    older = await client.get(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        params={
            "element_key": "experience:exp-1:bullet:0",
            "limit": 1,
            "cursor": page.json()["next_cursor"],
        },
    )
    assert [item["id"] for item in older.json()["items"]] == [first_data["id"]]

    restored = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/restore",
        headers=pro_auth_headers,
        json={"expected_head_version_id": second_data["id"], "idempotency_key": "restore-retry"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["operation"] == "restore"
    assert restored.json()["content"] == first_data["content"]
    assert restored.json()["parent_version_id"] == second_data["id"]
    restored_retry = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/restore",
        headers=pro_auth_headers,
        json={"expected_head_version_id": second_data["id"], "idempotency_key": "restore-retry"},
    )
    assert restored_retry.status_code == 200
    restored_retry_again = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/restore",
        headers=pro_auth_headers,
        json={"expected_head_version_id": second_data["id"], "idempotency_key": "restore-retry"},
    )
    assert restored_retry_again.status_code == 200
    assert restored_retry_again.json()["id"] == restored_retry.json()["id"]
    altered_restore_retry = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/restore",
        headers=pro_auth_headers,
        json={"expected_head_version_id": first_data["id"], "idempotency_key": "restore-retry"},
    )
    assert altered_restore_retry.status_code == 409

    forked = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/fork",
        headers=pro_auth_headers,
        json={"expected_head_version_id": restored.json()["id"]},
    )
    assert forked.status_code == 200, forked.text
    assert forked.json()["operation"] == "fork"
    assert forked.json()["root_version_id"] == forked.json()["id"]
    assert forked.json()["parent_version_id"] == first_data["id"]
    fork_retry = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/fork",
        headers=pro_auth_headers,
        json={"expected_head_version_id": restored.json()["id"], "idempotency_key": "fork-retry"},
    )
    assert fork_retry.status_code == 200
    fork_retry_again = await client.post(
        f"/resumes/{resume_id}/element-versions/{first_data['id']}/fork",
        headers=pro_auth_headers,
        json={"expected_head_version_id": restored.json()["id"], "idempotency_key": "fork-retry"},
    )
    assert fork_retry_again.status_code == 200
    assert fork_retry_again.json()["id"] == fork_retry.json()["id"]

    direct_fork = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": "Must use action endpoint.",
            "operation": "fork",
            "source": "fork",
        },
    )
    assert direct_fork.status_code == 422

    stale = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-1:bullet:0",
            "content": r"\item Stale writer.",
            "expected_head_version_id": second_data["id"],
        },
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_element_history_links_only_explicit_user_tracker_evidence_and_is_private(
    client: AsyncClient, pro_auth_headers: dict, auth_headers2: dict
) -> None:
    resume_id = await _resume(client, pro_auth_headers)
    application = await client.post(
        "/tracker/applications",
        headers=pro_auth_headers,
        json={"company_name": "Acme", "role_title": "Engineer", "resume_id": resume_id},
    )
    assert application.status_code == 201, application.text
    application_id = application.json()["id"]
    created = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={
            "element_key": "project:proj-1:bullet:0",
            "content": "Shipped a measurable project.",
            "application_id": application_id,
        },
    )
    assert created.status_code == 201, created.text
    evidence = created.json()["tracker_evidence"]
    assert evidence["source"] == "user_tracker"
    assert "does not establish" in evidence["interpretation"]

    private = await client.get(
        f"/resumes/{resume_id}/element-versions",
        headers=auth_headers2,
        params={"element_key": "project:proj-1:bullet:0"},
    )
    assert private.status_code == 404


@pytest.mark.asyncio
async def test_element_history_rejects_unsafe_values(client: AsyncClient, pro_auth_headers: dict) -> None:
    resume_id = await _resume(client, pro_auth_headers)
    response = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={"element_key": "bad key", "content": "value"},
    )
    assert response.status_code == 422

    naive_cursor = base64.urlsafe_b64encode(
        json.dumps({"created_at": "2026-09-14T00:00:00", "id": resume_id}).encode()
    ).decode().rstrip("=")
    invalid_cursor = await client.get(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        params={"element_key": "safe:key", "cursor": naive_cursor},
    )
    assert invalid_cursor.status_code == 400


@pytest.mark.asyncio
async def test_element_history_enforces_resume_wide_storage_cap(
    client: AsyncClient, pro_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import element_version_routes

    resume_id = await _resume(client, pro_auth_headers)
    monkeypatch.setattr(element_version_routes, "MAX_VERSIONS_PER_RESUME", 1)
    first = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={"element_key": "experience:first", "content": "First."},
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        f"/resumes/{resume_id}/element-versions",
        headers=pro_auth_headers,
        json={"element_key": "experience:second", "content": "Second."},
    )
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_element_history_enforces_create_then_edit_operation_order(
    client: AsyncClient, pro_auth_headers: dict
) -> None:
    resume_id = await _resume(client, pro_auth_headers)
    endpoint = f"/resumes/{resume_id}/element-versions"
    empty_edit = await client.post(
        endpoint,
        headers=pro_auth_headers,
        json={"element_key": "experience:exp-order:bullet:0", "content": "Edit too early.", "operation": "edit"},
    )
    assert empty_edit.status_code == 409
    created = await client.post(
        endpoint,
        headers=pro_auth_headers,
        json={"element_key": "experience:exp-order:bullet:0", "content": "Initial."},
    )
    assert created.status_code == 201
    duplicate_create = await client.post(
        endpoint,
        headers=pro_auth_headers,
        json={
            "element_key": "experience:exp-order:bullet:0",
            "content": "Second.",
            "operation": "create",
            "expected_head_version_id": created.json()["id"],
        },
    )
    assert duplicate_create.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_empty_writes_replay_idempotency_and_serialize_heads(
    client: AsyncClient, pro_auth_headers: dict, db_session_factory
) -> None:
    # The shared client fixture intentionally uses one transaction. Replace
    # that override for this test so each request gets a real DB session and
    # the Resume row lock is exercised across concurrent transactions.
    from app.database.connection import get_db
    from app.main import app

    resume_id = await _resume(client, pro_auth_headers)
    async def isolated_db():
        async with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = isolated_db
    try:
        endpoint = f"/resumes/{resume_id}/element-versions"
        same_request = {
            "element_key": "experience:exp-race:bullet:0",
            "content": "The one idempotent snapshot.",
            "idempotency_key": "test-concurrent-idempotency",
        }
        responses = await asyncio.gather(
            client.post(endpoint, headers=pro_auth_headers, json=same_request),
            client.post(endpoint, headers=pro_auth_headers, json=same_request),
        )
        assert sorted(response.status_code for response in responses) == [201, 201]
        assert responses[0].json()["id"] == responses[1].json()["id"]

        head_id = responses[0].json()["id"]
        raced = await asyncio.gather(
            client.post(
                endpoint,
                headers=pro_auth_headers,
                json={
                    "element_key": "experience:exp-race:bullet:0",
                    "content": "Writer A.",
                    "operation": "edit",
                    "expected_head_version_id": head_id,
                },
            ),
            client.post(
                endpoint,
                headers=pro_auth_headers,
                json={
                    "element_key": "experience:exp-race:bullet:0",
                    "content": "Writer B.",
                    "operation": "edit",
                    "expected_head_version_id": head_id,
                },
            ),
        )
        assert sorted(response.status_code for response in raced) == [201, 409]
    finally:
        app.dependency_overrides.pop(get_db, None)

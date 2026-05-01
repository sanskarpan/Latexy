"""
Tests for Feature 74 — Resume Collaboration Comments.

Covers:
  - Author can add comment (personal and workspace-scoped)
  - Author can edit own comment
  - Non-author cannot edit (403)
  - Author can delete own comment
  - Resume owner can resolve any comment
  - Non-member of workspace gets 403 on workspace-scoped comments
  - List returns correct comments filtered by workspace
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

# ── helpers ───────────────────────────────────────────────────────────────────

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


async def _create_resume(client: AsyncClient, headers: dict, title: str = "My Resume") -> dict:
    resp = await client.post("/resumes/", headers=headers, json={"title": title, "latex_content": _LATEX})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_workspace(client: AsyncClient, headers: dict, name: str = "Comment WS") -> dict:
    resp = await client.post("/workspaces", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _share_resume(client: AsyncClient, headers: dict, workspace_id: str, resume_id: str) -> None:
    resp = await client.post(f"/workspaces/{workspace_id}/resumes/{resume_id}", headers=headers)
    assert resp.status_code == 201, resp.text


async def _add_comment(
    client: AsyncClient,
    headers: dict,
    resume_id: str,
    content: str = "Great section!",
    workspace_id: str | None = None,
    line_number: int | None = None,
) -> dict:
    body: dict = {"content": content}
    if workspace_id:
        body["workspace_id"] = workspace_id
    if line_number is not None:
        body["line_number"] = line_number
    resp = await client.post(
        f"/resumes/{resume_id}/comments",
        headers=headers,
        json=body,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_member(
    db: AsyncSession, client: AsyncClient, owner_headers: dict, workspace_id: str
) -> tuple[str, str]:
    """Insert a user in DB, invite them to workspace, return (user_id, token)."""
    member_id = str(uuid.uuid4())
    member_email = f"member_{uuid.uuid4().hex[:8]}@example.com"
    await db.execute(
        sa_text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
            "VALUES (:id, :email, 'Member', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": member_id, "email": member_email},
    )
    await db.commit()
    resp = await client.post(
        f"/workspaces/{workspace_id}/members/invite",
        headers=owner_headers,
        json={"email": member_email, "role": "editor"},
    )
    assert resp.status_code == 201, resp.text
    # Insert session for this member
    token = f"test_sess_{uuid.uuid4().hex}"
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    await db.execute(
        sa_text(
            'INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :exp, :tok)'
        ),
        {"id": str(uuid.uuid4()), "uid": member_id, "exp": expires_at, "tok": token},
    )
    await db.commit()
    return member_id, token


# ── Add comment ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAddComment:
    async def test_owner_can_add_personal_comment(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume['id']}/comments",
            headers=auth_headers,
            json={"content": "Nice work here"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["content"] == "Nice work here"
        assert data["workspace_id"] is None
        assert data["resolved"] is False

    async def test_comment_with_line_number(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        comment = await _add_comment(client, auth_headers, resume["id"], line_number=42)
        assert comment["line_number"] == 42

    async def test_workspace_member_can_add_comment(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        _, token = await _create_member(db_session, client, auth_headers, ws["id"])
        member_headers = {"Authorization": f"Bearer {token}"}

        resp = await client.post(
            f"/resumes/{resume['id']}/comments",
            headers=member_headers,
            json={"content": "Workspace comment", "workspace_id": ws["id"]},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["workspace_id"] == ws["id"]

    async def test_non_owner_cannot_add_personal_comment(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        """User2 cannot comment on user1's resume without workspace context."""
        resume = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{resume['id']}/comments",
            headers=auth_headers2,
            json={"content": "Unauthorized"},
        )
        assert resp.status_code == 403

    async def test_non_member_cannot_add_workspace_comment(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        resp = await client.post(
            f"/resumes/{resume['id']}/comments",
            headers=auth_headers2,
            json={"content": "Should fail", "workspace_id": ws["id"]},
        )
        assert resp.status_code == 403


# ── Edit comment ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestEditComment:
    async def test_author_can_edit_own_comment(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        comment = await _add_comment(client, auth_headers, resume["id"])

        resp = await client.patch(
            f"/resumes/{resume['id']}/comments/{comment['id']}",
            headers=auth_headers,
            json={"content": "Updated content"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["content"] == "Updated content"

    async def test_non_author_cannot_edit(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict, db_session: AsyncSession
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        # Owner adds a comment
        comment = await _add_comment(
            client, auth_headers, resume["id"], workspace_id=ws["id"]
        )

        # Another non-member tries to edit → 403
        resp = await client.patch(
            f"/resumes/{resume['id']}/comments/{comment['id']}",
            headers=auth_headers2,
            json={"content": "Hijacked"},
        )
        assert resp.status_code == 403


# ── Delete comment ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteComment:
    async def test_author_can_delete_own_comment(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        comment = await _add_comment(client, auth_headers, resume["id"])

        del_resp = await client.delete(
            f"/resumes/{resume['id']}/comments/{comment['id']}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

    async def test_non_author_cannot_delete(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        resume = await _create_resume(client, auth_headers)
        comment = await _add_comment(client, auth_headers, resume["id"])

        resp = await client.delete(
            f"/resumes/{resume['id']}/comments/{comment['id']}",
            headers=auth_headers2,
        )
        assert resp.status_code == 403


# ── Resolve comment ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResolveComment:
    async def test_resume_owner_can_resolve_any_comment(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        # Member leaves a comment
        _, token = await _create_member(db_session, client, auth_headers, ws["id"])
        member_headers = {"Authorization": f"Bearer {token}"}
        comment = await _add_comment(
            client, member_headers, resume["id"], workspace_id=ws["id"]
        )

        # Resume owner resolves it
        resp = await client.patch(
            f"/resumes/{resume['id']}/comments/{comment['id']}/resolve",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolved"] is True

    async def test_resolve_toggles_back_to_unresolved(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        comment = await _add_comment(client, auth_headers, resume["id"])

        # Resolve
        await client.patch(
            f"/resumes/{resume['id']}/comments/{comment['id']}/resolve",
            headers=auth_headers,
        )
        # Resolve again → unresolve
        resp = await client.patch(
            f"/resumes/{resume['id']}/comments/{comment['id']}/resolve",
            headers=auth_headers,
        )
        assert resp.json()["resolved"] is False


# ── List + filter ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListComments:
    async def test_list_personal_comments(self, client: AsyncClient, auth_headers: dict):
        resume = await _create_resume(client, auth_headers)
        await _add_comment(client, auth_headers, resume["id"], content="Personal comment")

        resp = await client.get(f"/resumes/{resume['id']}/comments", headers=auth_headers)
        assert resp.status_code == 200
        assert any(c["content"] == "Personal comment" for c in resp.json())

    async def test_list_filters_by_workspace(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        # Add one personal and one workspace comment
        await _add_comment(client, auth_headers, resume["id"], content="Personal")
        await _add_comment(
            client, auth_headers, resume["id"], content="Workspace", workspace_id=ws["id"]
        )

        # Workspace-filtered list should only return workspace comment
        resp = await client.get(
            f"/resumes/{resume['id']}/comments?workspace_id={ws['id']}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        contents = [c["content"] for c in resp.json()]
        assert "Workspace" in contents
        assert "Personal" not in contents

    async def test_non_member_gets_403_on_workspace_list(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await _share_resume(client, auth_headers, ws["id"], resume["id"])

        resp = await client.get(
            f"/resumes/{resume['id']}/comments?workspace_id={ws['id']}",
            headers=auth_headers2,
        )
        assert resp.status_code == 403

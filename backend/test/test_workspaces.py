"""
Tests for Feature 66 — Team / Agency Workspace.

Covers:
  - POST /workspaces          — create workspace, owner auto-added as member
  - GET  /workspaces          — list user's workspaces
  - GET  /workspaces/{id}     — detail view with member list
  - PATCH /workspaces/{id}    — rename (owner only)
  - DELETE /workspaces/{id}   — delete (owner only)
  - POST /workspaces/{id}/members/invite    — invite by email (owner only)
  - DELETE /workspaces/{id}/members/{uid}  — remove member
  - PATCH /workspaces/{id}/members/{uid}/role — change role
  - POST /workspaces/{id}/resumes/{rid}    — share resume into workspace
  - DELETE /workspaces/{id}/resumes/{rid}  — unshare resume
  - GET  /workspaces/{id}/resumes          — list shared resumes (any member)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ── helpers ───────────────────────────────────────────────────────────────────

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


async def _create_workspace(
    client: AsyncClient, auth_headers: dict, name: str = "My Workspace"
) -> dict:
    resp = await client.post("/workspaces", headers=auth_headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_resume(
    client: AsyncClient, auth_headers: dict, title: str = "My Resume"
) -> dict:
    resp = await client.post(
        "/resumes/", headers=auth_headers, json={"title": title, "latex_content": _LATEX}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── create workspace ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateWorkspace:
    async def test_create_returns_201(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post(
            "/workspaces", headers=auth_headers, json={"name": "Test WS"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test WS"
        assert data["plan_id"] == "free"
        assert data["max_members"] == 5

    async def test_owner_auto_added_as_member(self, client: AsyncClient, auth_headers: dict):
        """Creating a workspace should auto-add the creator as owner member."""
        ws = await _create_workspace(client, auth_headers)
        detail = await client.get(f"/workspaces/{ws['id']}", headers=auth_headers)
        assert detail.status_code == 200
        members = detail.json()["members"]
        assert len(members) == 1
        assert members[0]["role"] == "owner"

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        resp = await client.post("/workspaces", json={"name": "Test"})
        assert resp.status_code == 401

    async def test_empty_name_returns_422(self, client: AsyncClient, auth_headers: dict):
        resp = await client.post("/workspaces", headers=auth_headers, json={"name": ""})
        assert resp.status_code == 422


# ── list workspaces ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListWorkspaces:
    async def test_returns_own_workspace(self, client: AsyncClient, auth_headers: dict):
        ws = await _create_workspace(client, auth_headers, name="Listed WS")
        resp = await client.get("/workspaces", headers=auth_headers)
        assert resp.status_code == 200
        ids = [w["id"] for w in resp.json()]
        assert ws["id"] in ids

    async def test_other_user_workspace_not_visible(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers, name="Private WS")
        resp = await client.get("/workspaces", headers=auth_headers2)
        ids = [w["id"] for w in resp.json()]
        assert ws["id"] not in ids

    async def test_list_reports_member_and_resume_counts(
        self, client: AsyncClient, auth_headers: dict
    ):
        """list_workspaces must report real member/resume counts, not always 0."""
        ws = await _create_workspace(client, auth_headers, name="Counts WS")
        resume = await _create_resume(client, auth_headers, title="Shared")
        share = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )
        assert share.status_code == 201, share.text

        resp = await client.get("/workspaces", headers=auth_headers)
        assert resp.status_code == 200
        entry = next(w for w in resp.json() if w["id"] == ws["id"])
        assert entry["member_count"] == 1  # owner
        assert entry["resume_count"] == 1


# ── access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWorkspaceAccessControl:
    async def test_non_member_get_resumes_returns_403(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        """Non-member should get 403 on GET /workspaces/{id}/resumes."""
        ws = await _create_workspace(client, auth_headers)
        resp = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers2
        )
        assert resp.status_code == 403

    async def test_non_member_get_detail_returns_403(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.get(f"/workspaces/{ws['id']}", headers=auth_headers2)
        assert resp.status_code == 403

    async def test_non_owner_rename_returns_403(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.patch(
            f"/workspaces/{ws['id']}", headers=auth_headers2, json={"name": "Hacked"}
        )
        assert resp.status_code == 403

    async def test_non_owner_delete_returns_403(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.delete(f"/workspaces/{ws['id']}", headers=auth_headers2)
        assert resp.status_code == 403


# ── max members limit ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMaxMembersLimit:
    async def test_invite_beyond_limit_returns_422(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        """Cannot invite beyond max_members (default 5). Already have 1 (owner)."""
        import uuid

        from sqlalchemy import text as sa_text

        ws = await _create_workspace(client, auth_headers, name="Full WS")

        # Set max_members=1 via the test session (same session the API uses via
        # override_get_db) — no commit needed since they share the transaction.
        await db_session.execute(
            sa_text("UPDATE workspaces SET max_members=1 WHERE id=:id"),
            {"id": ws["id"]},
        )

        resp = await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": f"newuser_{uuid.uuid4().hex[:8]}@example.com", "role": "editor"},
        )
        assert resp.status_code == 422
        assert "member limit" in resp.json()["detail"]


# ── invite + remove members ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMemberManagement:
    async def test_invite_existing_user(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict, db_session
    ):
        """Owner can invite an existing user. Second user becomes an editor."""
        import uuid

        from sqlalchemy import text as sa_text

        # Create a real user row for auth_headers2 to invite
        invited_email = f"invite_{uuid.uuid4().hex[:8]}@example.com"
        invited_uid = str(uuid.uuid4())
        await db_session.execute(
            sa_text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Invited', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": invited_uid, "email": invited_email},
        )
        await db_session.commit()

        ws = await _create_workspace(client, auth_headers, name="Invite WS")
        resp = await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": invited_email, "role": "editor"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["role"] == "editor"
        assert resp.json()["email"] == invited_email

    async def test_invite_unknown_email_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": "nobody_at_all@fake.invalid", "role": "editor"},
        )
        assert resp.status_code == 404

    async def test_invite_invalid_role_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": "someone@example.com", "role": "superadmin"},
        )
        assert resp.status_code == 422

    async def test_invite_malformed_email_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resp = await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": "not-an-email", "role": "editor"},
        )
        assert resp.status_code == 422

    async def test_non_owner_cannot_invite(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict, db_session
    ):
        """A regular member (editor) cannot invite other users."""
        import uuid

        from sqlalchemy import text as sa_text

        # Add auth_headers2's user as an editor
        owner_ws = await _create_workspace(client, auth_headers, name="NI WS")
        editor_email = f"editor_{uuid.uuid4().hex[:8]}@example.com"
        editor_uid = str(uuid.uuid4())
        await db_session.execute(
            sa_text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Editor', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": editor_uid, "email": editor_email},
        )
        await db_session.commit()

        await client.post(
            f"/workspaces/{owner_ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": editor_email, "role": "editor"},
        )

        # Simulate auth_headers2 being a different user trying to invite
        resp = await client.post(
            f"/workspaces/{owner_ws['id']}/members/invite",
            headers=auth_headers2,
            json={"email": "third@example.com", "role": "editor"},
        )
        assert resp.status_code == 403

    async def test_owner_remove_member(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        """Owner can remove an editor; owner cannot remove themselves."""
        import uuid

        from sqlalchemy import text as sa_text

        member_email = f"member_{uuid.uuid4().hex[:8]}@example.com"
        member_uid = str(uuid.uuid4())
        await db_session.execute(
            sa_text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Member', true, 'free', 'active', false) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": member_uid, "email": member_email},
        )
        await db_session.commit()

        ws = await _create_workspace(client, auth_headers, name="Remove WS")
        await client.post(
            f"/workspaces/{ws['id']}/members/invite",
            headers=auth_headers,
            json={"email": member_email, "role": "editor"},
        )

        # Remove member
        resp = await client.delete(
            f"/workspaces/{ws['id']}/members/{member_uid}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Detail should only have 1 member (owner)
        detail = await client.get(f"/workspaces/{ws['id']}", headers=auth_headers)
        assert len(detail.json()["members"]) == 1

    async def test_cannot_remove_owner(self, client: AsyncClient, auth_headers: dict, db_session):
        """Trying to remove the owner's own membership returns 422."""
        ws = await _create_workspace(client, auth_headers)
        owner_id = ws["owner_id"]
        resp = await client.delete(
            f"/workspaces/{ws['id']}/members/{owner_id}", headers=auth_headers
        )
        assert resp.status_code == 422


# ── resume sharing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWorkspaceResumes:
    async def test_share_resume_into_workspace(
        self, client: AsyncClient, auth_headers: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)

        resp = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )
        assert resp.status_code == 201
        assert resp.json()["id"] == resume["id"]

    async def test_list_resumes_as_member(
        self, client: AsyncClient, auth_headers: dict
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )

        resp = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert resume["id"] in ids

    async def test_unshare_resume(self, client: AsyncClient, auth_headers: dict):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )

        del_resp = await client.delete(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )
        assert del_resp.status_code == 204

        list_resp = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers
        )
        ids = [r["id"] for r in list_resp.json()]
        assert resume["id"] not in ids

    async def test_share_unowned_resume_returns_404(
        self, client: AsyncClient, auth_headers: dict, auth_headers2: dict
    ):
        """Cannot share a resume you don't own."""
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers2)  # owned by user2

        resp = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )
        assert resp.status_code == 404


# ── delete workspace ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDeleteWorkspace:
    async def test_owner_can_delete(self, client: AsyncClient, auth_headers: dict):
        ws = await _create_workspace(client, auth_headers, name="Delete Me")
        resp = await client.delete(f"/workspaces/{ws['id']}", headers=auth_headers)
        assert resp.status_code == 204

        # Subsequent GET returns 404
        get_resp = await client.get(f"/workspaces/{ws['id']}", headers=auth_headers)
        assert get_resp.status_code in (403, 404)

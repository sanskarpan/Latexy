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

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _user_id_for_headers(db: AsyncSession, headers: dict) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    result = await db.execute(
        text('SELECT "userId" FROM session WHERE token = :token'), {"token": token}
    )
    return str(result.scalar_one())


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


# ── role enforcement for recruiter notes ────────────────────────────────────


@pytest.mark.asyncio
class TestRecruiterNoteRoles:
    @pytest.mark.parametrize(("role", "expected"), [("editor", 201), ("viewer", 403)])
    async def test_member_role_controls_note_creation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
        role: str,
        expected: int,
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        shared = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}", headers=auth_headers
        )
        assert shared.status_code == 201

        member_id = await _user_id_for_headers(db_session, auth_headers2)
        await db_session.execute(
            text(
                "INSERT INTO workspace_members "
                "(workspace_id, user_id, role, joined_at) "
                "VALUES (:workspace_id, :user_id, :role, now())"
            ),
            {"workspace_id": ws["id"], "user_id": member_id, "role": role},
        )
        await db_session.commit()

        response = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}/notes",
            headers=auth_headers2,
            json={"content": "Candidate has strong systems experience."},
        )
        assert response.status_code == expected, response.text

    async def test_demoted_viewer_cannot_modify_existing_own_note(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
    ):
        ws = await _create_workspace(client, auth_headers)
        resume = await _create_resume(client, auth_headers)
        assert (
            await client.post(
                f"/workspaces/{ws['id']}/resumes/{resume['id']}",
                headers=auth_headers,
            )
        ).status_code == 201

        member_id = await _user_id_for_headers(db_session, auth_headers2)
        await db_session.execute(
            text(
                "INSERT INTO workspace_members "
                "(workspace_id, user_id, role, joined_at) "
                "VALUES (:workspace_id, :user_id, 'editor', now())"
            ),
            {"workspace_id": ws["id"], "user_id": member_id},
        )
        await db_session.commit()
        created = await client.post(
            f"/workspaces/{ws['id']}/resumes/{resume['id']}/notes",
            headers=auth_headers2,
            json={"content": "Initial assessment"},
        )
        assert created.status_code == 201

        await db_session.execute(
            text(
                "UPDATE workspace_members SET role = 'viewer' "
                "WHERE workspace_id = :workspace_id AND user_id = :user_id"
            ),
            {"workspace_id": ws["id"], "user_id": member_id},
        )
        await db_session.commit()
        note_url = (
            f"/workspaces/{ws['id']}/resumes/{resume['id']}"
            f"/notes/{created.json()['id']}"
        )
        update = await client.patch(
            note_url,
            headers=auth_headers2,
            json={"content": "Viewer mutation"},
        )
        delete = await client.delete(note_url, headers=auth_headers2)
        assert update.status_code == 403
        assert delete.status_code == 403


@pytest.mark.asyncio
class TestCareerCentreCohortPrivacy:
    async def test_student_submits_own_resume_without_seeing_classmates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        auth_headers2: dict,
    ):
        owner_id = await _user_id_for_headers(db_session, auth_headers)
        student_id = await _user_id_for_headers(db_session, auth_headers2)
        ws = await _create_workspace(client, auth_headers, name='Test Cohort')
        tenant_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO tenants (id, slug, name, owner_id, plan_id, max_members) "
                "VALUES (:id, :slug, 'Test University', :owner, 'university', 200)"
            ),
            {'id': tenant_id, 'slug': f'test-{uuid.uuid4().hex[:10]}', 'owner': owner_id},
        )
        await db_session.execute(
            text("UPDATE workspaces SET tenant_id = :tenant WHERE id = :workspace"),
            {'tenant': tenant_id, 'workspace': ws['id']},
        )
        await db_session.execute(
            text(
                "INSERT INTO workspace_members (workspace_id, user_id, role, joined_at) "
                "VALUES (:workspace, :student, 'viewer', now())"
            ),
            {'workspace': ws['id'], 'student': student_id},
        )
        await db_session.commit()

        owner_resume = await _create_resume(client, auth_headers, title='Admin Resume')
        assert (await client.post(
            f"/workspaces/{ws['id']}/resumes/{owner_resume['id']}", headers=auth_headers
        )).status_code == 201
        student_resume = await _create_resume(client, auth_headers2, title='Student Resume')
        submitted = await client.post(
            f"/workspaces/{ws['id']}/resumes/{student_resume['id']}",
            headers=auth_headers2,
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()['owner_id'] == student_id

        student_list = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers2
        )
        assert student_list.status_code == 200
        assert [item['id'] for item in student_list.json()] == [student_resume['id']]
        assert student_list.json()[0]['opened_at'] is not None
        assert student_list.json()[0]['opened_actor'] == 'candidate'
        assert student_list.json()[0]['opened_source'] == 'candidate_self'

        owner_list = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers
        )
        assert {item['id'] for item in owner_list.json()} == {
            owner_resume['id'], student_resume['id']
        }
        student_owner_view = next(
            item for item in owner_list.json() if item['id'] == student_resume['id']
        )
        assert student_owner_view['opened_actor'] == 'candidate'
        assert student_owner_view['opened_source'] == 'candidate_self'

        hidden_download = await client.get(
            f"/workspaces/{ws['id']}/resumes/{owner_resume['id']}/download",
            headers=auth_headers2,
        )
        assert hidden_download.status_code == 404

        missing_job_id = f'missing-{uuid.uuid4()}'
        await db_session.execute(
            text(
                "INSERT INTO compilations (id, user_id, resume_id, job_id, status) "
                "VALUES (:id, :user, :resume, :job, 'completed')"
            ),
            {
                'id': str(uuid.uuid4()),
                'user': student_id,
                'resume': student_resume['id'],
                'job': missing_job_id,
            },
        )
        await db_session.commit()
        unavailable = await client.get(
            f"/workspaces/{ws['id']}/resumes/{student_resume['id']}/download",
            headers=auth_headers2,
        )
        assert unavailable.status_code == 404
        milestone = await db_session.execute(
            text(
                'SELECT downloaded_at FROM workspace_resumes '
                'WHERE workspace_id = :workspace AND resume_id = :resume'
            ),
            {'workspace': ws['id'], 'resume': student_resume['id']},
        )
        assert milestone.scalar_one() is None

        # The legacy milestone columns are candidate-only. Even when a
        # download milestone exists, both workspace and cohort responses must
        # identify it as candidate self-activity rather than reviewer activity.
        await db_session.execute(
            text(
                'UPDATE workspace_resumes SET downloaded_at = now() '
                'WHERE workspace_id = :workspace AND resume_id = :resume'
            ),
            {'workspace': ws['id'], 'resume': student_resume['id']},
        )
        await db_session.commit()
        owner_with_download = await client.get(
            f"/workspaces/{ws['id']}/resumes", headers=auth_headers
        )
        downloaded_item = next(
            item for item in owner_with_download.json() if item['id'] == student_resume['id']
        )
        assert downloaded_item['downloaded_actor'] == 'candidate'
        assert downloaded_item['downloaded_source'] == 'candidate_self'

        cohort_list = await client.get(
            f"/tenants/{tenant_id}/cohorts/{ws['id']}/submissions",
            headers=auth_headers,
        )
        assert cohort_list.status_code == 200, cohort_list.text
        cohort_item = next(
            item for item in cohort_list.json() if item['resume_id'] == student_resume['id']
        )
        assert cohort_item['opened_actor'] == 'candidate'
        assert cohort_item['opened_source'] == 'candidate_self'
        assert cohort_item['downloaded_actor'] == 'candidate'
        assert cohort_item['downloaded_source'] == 'candidate_self'

        withdrawn = await client.delete(
            f"/workspaces/{ws['id']}/resumes/{student_resume['id']}",
            headers=auth_headers2,
        )
        assert withdrawn.status_code == 204

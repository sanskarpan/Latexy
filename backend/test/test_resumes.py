import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

@pytest.mark.asyncio
class TestResumeCRUD:
    """Test the /resumes/ CRUD endpoints."""

    async def test_create_resume(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can create a resume."""
        resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Test Resume",
                "latex_content": r"\documentclass{article}\begin{document}Hello\end{document}",
                "tags": ["test", "dev"]
            }
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Resume"
        assert "id" in data
        assert data["user_id"] is not None

    async def test_list_resumes(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can list their resumes."""
        # Create one first
        await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "R1", "latex_content": "C1"}
        )
        
        resp = await client.get("/resumes/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(r["title"] == "R1" for r in data)

    async def test_get_resume_by_id(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can fetch a specific resume they own."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Target", "latex_content": "Content"}
        )
        resume_id = create_resp.json()["id"]

        resp = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Target"

    async def test_get_nonexistent_resume(self, client: AsyncClient, auth_headers: dict):
        """Fetching a nonexistent ID returns 404."""
        resp = await client.get(f"/resumes/{uuid.uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_resume(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can update their resume."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Old Title", "latex_content": "Old Content"}
        )
        resume_id = create_resp.json()["id"]

        resp = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={"title": "New Title"}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"
        assert resp.json()["latex_content"] == "Old Content"

    async def test_delete_resume(self, client: AsyncClient, auth_headers: dict):
        """Authenticated user can delete their resume."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "To Delete", "latex_content": "..."}
        )
        resume_id = create_resp.json()["id"]

        resp = await client.delete(f"/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    async def test_unauthorized_access(self, client: AsyncClient):
        """Unauthenticated access to /resumes/ returns 401."""
        resp = await client.get("/resumes/")
        assert resp.status_code == 401

    async def test_cannot_access_others_resume(
        self, client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """A user cannot access a resume belonging to someone else."""
        # Create a resume for "Other User" directly in DB
        other_uid = str(uuid.uuid4())
        resume_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other', true, 'free', 'active', false)"
            ),
            {"id": other_uid, "email": f"other_{other_uid[:8]}@example.com"},
        )
        await db_session.execute(
            text(
                "INSERT INTO resumes (id, user_id, title, latex_content) "
                "VALUES (:id, :uid, 'Secret', 'Top Secret')"
            ),
            {"id": resume_id, "uid": other_uid}
        )
        await db_session.commit()

        # Try to access with 'auth_headers' (different user)
        resp = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert resp.status_code == 404 # We return 404 instead of 403 for privacy usually

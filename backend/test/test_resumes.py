import inspect
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
        assert data["metadata"]["compiler"] == "lualatex"

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
        payload = resp.json()
        data = payload["resumes"] if isinstance(payload, dict) else payload
        assert len(data) >= 1
        assert any(r["title"] == "R1" for r in data)

    async def test_list_resumes_rejects_malformed_parent_id(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A malformed parent filter is rejected before reaching the UUID DB parameter."""
        resp = await client.get(
            "/resumes/?parent_id=not-a-uuid",
            headers=auth_headers,
        )

        assert 400 <= resp.status_code < 500, resp.text

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

    async def test_update_resume_rejects_stale_full_document_save(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Autosave's base snapshot prevents a stale channel from clobbering newer content."""
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "CAS", "latex_content": "Before Target After"},
        )
        resume_id = create_resp.json()["id"]

        accepted = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={
                "latex_content": "Before Changed After",
                "expected_latex_content": "Before Target After",
            },
        )
        assert accepted.status_code == 200, accepted.text

        stale = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={
                "latex_content": "Before Target After (stale autosave)",
                "expected_latex_content": "Before Target After",
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "document_changed"

        current = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert current.status_code == 200
        assert current.json()["latex_content"] == "Before Changed After"

    async def test_update_resume_requires_cas_for_document_writes(
        self, client: AsyncClient, auth_headers: dict
    ):
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "CAS precondition", "latex_content": "Source"},
        )
        resume_id = create_resp.json()["id"]

        missing = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={"latex_content": "New source"},
        )
        assert missing.status_code == 428, missing.text
        assert missing.json()["detail"]["code"] == "precondition_required"

    async def test_update_resume_allows_converged_duplicate_with_stale_token(
        self, client: AsyncClient, auth_headers: dict
    ):
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "CAS converged", "latex_content": "Source"},
        )
        resume_id = create_resp.json()["id"]
        first = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={"latex_content": "Converged", "expected_latex_content": "Source"},
        )
        assert first.status_code == 200, first.text

        # Two Yjs clients can converge on the same source while carrying
        # different old snapshots. The duplicate must be a no-op, not a false
        # conflict that causes an unnecessary reload.
        duplicate = await client.put(
            f"/resumes/{resume_id}",
            headers=auth_headers,
            json={"latex_content": "Converged", "expected_latex_content": "Source"},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["latex_content"] == "Converged"

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

    async def test_create_oversized_title_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Title longer than 255 chars is a clean 422, not a DB 500."""
        resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "x" * 256, "latex_content": "hi"},
        )
        assert resp.status_code == 422

    async def test_create_invalid_document_type_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Unknown document_type is rejected at validation time."""
        resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Doc", "latex_content": "hi", "document_type": "bogus"},
        )
        assert resp.status_code == 422

    async def test_create_oversized_latex_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ):
        """LaTeX content beyond the size cap is rejected."""
        resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={"title": "Big", "latex_content": "a" * 1_000_001},
        )
        assert resp.status_code == 422

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


# ── BUG-01 / BUG-02 (F86): document_type field in schema and list filter ──────


class TestDocumentTypeField:
    """Unit tests for BUG-01 (document_type in ResumeResponse) and BUG-02 (list filter)."""

    def test_resume_response_includes_document_type(self):
        """ResumeResponse schema exposes document_type field (BUG-01 fix)."""
        from app.api.resume_routes import ResumeResponse

        now = datetime.now(timezone.utc)
        r = ResumeResponse(
            id="abc", user_id="u1", title="Test", latex_content=r"\doc",
            document_type="beamer", created_at=now, updated_at=now,
        )
        assert r.document_type == "beamer"

    def test_resume_response_document_type_defaults_to_resume(self):
        """ResumeResponse.document_type defaults to 'resume' when not provided."""
        from app.api.resume_routes import ResumeResponse

        now = datetime.now(timezone.utc)
        r = ResumeResponse(
            id="abc", user_id="u1", title="Test", latex_content=r"\doc",
            created_at=now, updated_at=now,
        )
        assert r.document_type == "resume"

    def test_list_resumes_accepts_document_type_filter(self):
        """list_resumes handler signature includes document_type parameter (BUG-02 fix)."""
        from app.api.resume_routes import list_resumes

        sig = inspect.signature(list_resumes)
        assert "document_type" in sig.parameters


@pytest.mark.asyncio
async def test_list_resumes_honors_advertised_200_row_limit():
    """A valid limit=200 request must not be silently truncated to 100."""
    from app.api.resume_routes import list_resumes

    class _Result:
        def __init__(self, *, count=None, rows=None):
            self._count = count
            self._rows = rows or []

        def scalar(self):
            return self._count

        def all(self):
            return self._rows

    class _DB:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            if len(self.statements) == 1:
                return _Result(count=0)
            return _Result(rows=[])

    db = _DB()
    response = await list_resumes(
        page=1, limit=200, parent_id=None, db=db, user_id=str(uuid.uuid4())
    )

    assert response["limit"] == 200
    assert db.statements[1]._limit_clause.value == 200

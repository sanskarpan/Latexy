"""
Tests for Feature 10: Shareable Resume Links.

Covers:
  - POST /resumes/{id}/share  — generate share token (+ idempotent)
  - DELETE /resumes/{id}/share — revoke share token
  - GET /share/{token}         — public endpoint (no-auth)
  - Auth boundaries + ownership checks
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello\end{document}"


async def _create_resume(
    client: AsyncClient, auth_headers: dict, title: str = "Share Test Resume"
) -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _insert_completed_compilation(
    db: AsyncSession, resume_id: str, pdf_path: str | None = None
) -> str:
    """Insert a completed Compilation record (no user_id — nullable) and return the job_id."""
    job_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO compilations (id, resume_id, job_id, status, pdf_path) "
            "VALUES (:id, :rid, :jid, 'completed', :pdf_path)"
        ),
        {
            "id": str(uuid.uuid4()),
            "rid": resume_id,
            "jid": job_id,
            "pdf_path": pdf_path,
        },
    )
    await db.commit()
    return job_id



# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestShareLinks:

    # ------------------------------------------------------------------
    # POST /resumes/{id}/share
    # ------------------------------------------------------------------

    async def test_create_share_link(self, client: AsyncClient, auth_headers: dict):
        """POST /share creates a share token and returns share_url."""
        resume = await _create_resume(client, auth_headers)

        resp = await client.post(
            f"/resumes/{resume['id']}/share",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "share_token" in data
        assert len(data["share_token"]) > 10
        assert "share_url" in data
        assert data["share_token"] in data["share_url"]
        assert "created_at" in data

    async def test_create_share_link_idempotent(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Calling POST /share twice returns the same token (idempotent)."""
        resume = await _create_resume(client, auth_headers, "Idempotent Test")

        resp1 = await client.post(
            f"/resumes/{resume['id']}/share",
            headers=auth_headers,
        )
        resp2 = await client.post(
            f"/resumes/{resume['id']}/share",
            headers=auth_headers,
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["share_token"] == resp2.json()["share_token"]

    async def test_create_share_requires_auth(self, client: AsyncClient):
        """POST /share without auth returns 401/403."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(f"/resumes/{fake_id}/share")
        assert resp.status_code in (401, 403, 422)

    async def test_cannot_share_nonexistent_resume(
        self, client: AsyncClient, auth_headers: dict
    ):
        """POST /share on a non-existent resume returns 404."""
        resp = await client.post(
            f"/resumes/{uuid.uuid4()}/share",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------
    # DELETE /resumes/{id}/share
    # ------------------------------------------------------------------

    async def test_revoke_share_link(self, client: AsyncClient, auth_headers: dict):
        """DELETE /share revokes the token (returns 204)."""
        resume = await _create_resume(client, auth_headers, "Revoke Test")

        # Create first
        await client.post(f"/resumes/{resume['id']}/share", headers=auth_headers)

        resp = await client.delete(
            f"/resumes/{resume['id']}/share",
            headers=auth_headers,
        )
        assert resp.status_code == 204

    async def test_revoke_clears_token_from_resume_response(
        self, client: AsyncClient, auth_headers: dict
    ):
        """After revoke, GET /resumes/{id} shows share_token=null."""
        resume = await _create_resume(client, auth_headers, "Revoke Token Test")

        await client.post(f"/resumes/{resume['id']}/share", headers=auth_headers)
        await client.delete(f"/resumes/{resume['id']}/share", headers=auth_headers)

        get_resp = await client.get(f"/resumes/{resume['id']}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["share_token"] is None

    # ------------------------------------------------------------------
    # GET /share/{token}
    # ------------------------------------------------------------------

    async def test_get_nonexistent_token_404(self, client: AsyncClient):
        """GET /share/nonexistent returns 404."""
        resp = await client.get("/share/totally_made_up_token_abc123")
        assert resp.status_code == 404
        assert "revoked" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()

    async def test_get_after_revoke_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /share/{token} after revoke returns 404."""
        resume = await _create_resume(client, auth_headers, "Revoke GET Test")

        share_resp = await client.post(
            f"/resumes/{resume['id']}/share", headers=auth_headers
        )
        token = share_resp.json()["share_token"]

        await client.delete(f"/resumes/{resume['id']}/share", headers=auth_headers)

        get_resp = await client.get(f"/share/{token}")
        assert get_resp.status_code == 404

    async def test_get_no_compilation_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /share/{token} with no compiled PDF returns 404 with helpful message."""
        resume = await _create_resume(client, auth_headers, "No Compilation Test")

        share_resp = await client.post(
            f"/resumes/{resume['id']}/share", headers=auth_headers
        )
        token = share_resp.json()["share_token"]

        get_resp = await client.get(f"/share/{token}")
        assert get_resp.status_code == 404
        assert "compiled" in get_resp.json()["detail"].lower()

    async def test_get_with_minio_pdf_returns_200(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        """GET /share/{token} with a compilation that has pdf_path in MinIO → 200."""
        resume = await _create_resume(client, auth_headers, "MinIO PDF Test")
        resume_id = resume["id"]

        # Insert a completed compilation with pdf_path set (simulating MinIO upload)
        fake_pdf_key = f"shares/{resume_id}/resume.pdf"
        await _insert_completed_compilation(
            db_session, resume_id, pdf_path=fake_pdf_key
        )

        # Create share link
        share_resp = await client.post(
            f"/resumes/{resume_id}/share", headers=auth_headers
        )
        token = share_resp.json()["share_token"]

        # Mock generate_presigned_url to avoid real MinIO call
        fake_url = "http://localhost:9000/latexy/shares/test/resume.pdf?sig=xxx"
        with patch(
            "app.services.storage_service.generate_presigned_url",
            return_value=fake_url,
        ):
            get_resp = await client.get(f"/share/{token}")

        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert data["resume_title"] == "MinIO PDF Test"
        assert data["share_token"] == token
        assert data["pdf_url"] == fake_url
        assert "compiled_at" in data

    # ------------------------------------------------------------------
    # ResumeResponse includes share_token / share_url
    # ------------------------------------------------------------------

    async def test_resume_response_includes_share_fields(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /resumes/{id} returns share_token and share_url after link created."""
        resume = await _create_resume(client, auth_headers, "Fields Test")

        # Initially no share
        get1 = await client.get(f"/resumes/{resume['id']}", headers=auth_headers)
        assert get1.json()["share_token"] is None
        assert get1.json()["share_url"] is None

        # Create share
        await client.post(f"/resumes/{resume['id']}/share", headers=auth_headers)

        # Now response includes share fields
        get2 = await client.get(f"/resumes/{resume['id']}", headers=auth_headers)
        data = get2.json()
        assert data["share_token"] is not None
        assert data["share_url"] is not None
        assert data["share_token"] in data["share_url"]
        assert "/r/" in data["share_url"]

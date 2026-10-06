"""
Tests for Feature 10: Shareable Resume Links.

Covers:
  - POST /resumes/{id}/share  — generate share token (+ idempotent)
  - DELETE /resumes/{id}/share — revoke share token
  - GET /share/{token}         — public endpoint (no-auth)
  - Auth boundaries + ownership checks
"""

from __future__ import annotations

import asyncio
import base64
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.main import app

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
        assert data["review_comments"] is False

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
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"review_comments": True},
        )
        token = share_resp.json()["share_token"]
        assert share_resp.json()["review_comments"] is True

        # A legacy client that omits the new field must preserve the enabled
        # capability while changing only the existing share settings.
        preserved = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"anonymous": False},
        )
        assert preserved.status_code == 200
        assert preserved.json()["review_comments"] is True

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
        assert data["review_comments"] is True
        assert "compiled_at" in data
        assert "Hello" in data["accessible_text"]

    async def test_legacy_share_repairs_are_job_scoped_across_compilations(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        tmp_path,
    ):
        """A later legacy compile must not overwrite an earlier share object."""
        resume = await _create_resume(client, auth_headers, "Versioned share repair")
        resume_id = resume["id"]
        first_job = await _insert_completed_compilation(db_session, resume_id)
        first_pdf = tmp_path / "first.pdf"
        first_pdf.write_bytes(b"%PDF-first")

        with (
            patch(
                "app.api.resume_routes.get_job_files",
                return_value=(tmp_path, first_pdf, tmp_path / "first.log"),
            ),
            patch("app.services.storage_service.upload_bytes") as upload,
        ):
            first_share = await client.post(
                f"/resumes/{resume_id}/share", headers=auth_headers
            )
        assert first_share.status_code == 200, first_share.text
        first_key = upload.call_args.args[0]
        assert first_key.startswith(f"compilations/{first_job}/finalization-")
        upload.assert_called_once_with(first_key, b"%PDF-first", "application/pdf")

        # Revoke the capability, add a newer legacy compilation, and repair it
        # through the same endpoint.  Each row must retain its own immutable key.
        await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)
        second_job = await _insert_completed_compilation(db_session, resume_id)
        second_pdf = tmp_path / "second.pdf"
        second_pdf.write_bytes(b"%PDF-second")
        with (
            patch(
                "app.api.resume_routes.get_job_files",
                return_value=(tmp_path, second_pdf, tmp_path / "second.log"),
            ),
            patch("app.services.storage_service.upload_bytes") as upload,
        ):
            second_share = await client.post(
                f"/resumes/{resume_id}/share", headers=auth_headers
            )
        assert second_share.status_code == 200, second_share.text
        second_key = upload.call_args.args[0]
        assert second_key.startswith(f"compilations/{second_job}/finalization-")
        upload.assert_called_once_with(second_key, b"%PDF-second", "application/pdf")
        assert first_key != second_key

        rows = (
            await db_session.execute(
                text("SELECT job_id, pdf_path FROM compilations WHERE job_id IN (:first, :second)"),
                {"first": first_job, "second": second_job},
            )
        ).all()
        paths = {job_id: pdf_path for job_id, pdf_path in rows}
        assert paths == {first_job: first_key, second_job: second_key}

    async def test_existing_pdf_path_is_preserved_when_presign_fails(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        tmp_path,
    ):
        """A presign outage must not replace a stable historical pointer."""
        resume = await _create_resume(client, auth_headers, "Stable share path")
        resume_id = resume["id"]
        stable_path = f"compilations/{uuid.uuid4()}/finalization-{'a' * 32}.pdf"
        job_id = await _insert_completed_compilation(db_session, resume_id, stable_path)
        share = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)
        token = share.json()["share_token"]

        fallback_pdf = tmp_path / "fallback.pdf"
        fallback_pdf.write_bytes(b"%PDF-fallback")
        with (
            patch(
                "app.services.storage_service.generate_presigned_url",
                side_effect=RuntimeError("storage unavailable"),
            ),
            patch(
                "app.api.routes.get_job_files",
                return_value=(tmp_path, fallback_pdf, tmp_path / "fallback.log"),
            ) as get_files,
            patch("app.services.storage_service.upload_bytes") as upload,
        ):
            response = await client.get(f"/share/{token}")

        assert response.status_code == 404
        get_files.assert_not_called()
        upload.assert_not_called()
        row = (
            await db_session.execute(
                text("SELECT pdf_path FROM compilations WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        ).scalar_one()
        assert row == stable_path

    async def test_public_share_repairs_null_path_with_job_scoped_key(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        tmp_path,
    ):
        resume = await _create_resume(client, auth_headers, "Public legacy repair")
        resume_id = resume["id"]
        share = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)
        token = share.json()["share_token"]
        job_id = await _insert_completed_compilation(db_session, resume_id)

        pdf = tmp_path / "public.pdf"
        pdf.write_bytes(b"%PDF-public")
        with (
            patch(
                "app.api.routes.get_job_files",
                return_value=(tmp_path, pdf, tmp_path / "public.log"),
            ),
            patch("app.services.storage_service.upload_bytes") as upload,
            patch(
                "app.services.storage_service.generate_presigned_url",
                return_value="https://storage.example/public.pdf",
            ),
        ):
            response = await client.get(f"/share/{token}")

        assert response.status_code == 200, response.text
        assert response.json()["pdf_url"] == "https://storage.example/public.pdf"
        expected_key = upload.call_args.args[0]
        assert expected_key.startswith(f"compilations/{job_id}/finalization-")
        upload.assert_called_once_with(expected_key, b"%PDF-public", "application/pdf")
        row = (
            await db_session.execute(
                text("SELECT pdf_path FROM compilations WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        ).scalar_one()
        assert row == expected_key

    async def test_public_share_repairs_null_path_from_bounded_redis_pdf(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        tmp_path,
    ):
        """Public sharing must work when the compiler/API lack a shared temp dir."""
        resume = await _create_resume(client, auth_headers, "Redis legacy repair")
        resume_id = resume["id"]
        share = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)
        token = share.json()["share_token"]
        job_id = await _insert_completed_compilation(db_session, resume_id)

        fake_redis = AsyncMock()
        fake_redis.get.return_value = base64.b64encode(b"%PDF-redis")
        with (
            patch(
                "app.api.routes.get_job_files",
                return_value=(tmp_path, tmp_path / "missing.pdf", tmp_path / "missing.log"),
            ),
            patch("app.core.redis.get_redis_client", AsyncMock(return_value=fake_redis)),
            patch("app.services.storage_service.upload_bytes") as upload,
            patch(
                "app.services.storage_service.generate_presigned_url",
                return_value="https://storage.example/redis.pdf",
            ),
        ):
            response = await client.get(f"/share/{token}")

        assert response.status_code == 200, response.text
        assert response.json()["pdf_url"] == "https://storage.example/redis.pdf"
        expected_key = upload.call_args.args[0]
        assert expected_key.startswith(f"compilations/{job_id}/finalization-")
        upload.assert_called_once_with(expected_key, b"%PDF-redis", "application/pdf")

    async def test_concurrent_same_job_repairs_keep_cas_winner_and_delete_loser(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
        db_session_factory,
        tmp_path,
    ):
        """Concurrent repairs upload distinct objects and preserve the CAS winner."""
        resume = await _create_resume(client, auth_headers, "Concurrent legacy repair")
        resume_id = resume["id"]
        share = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)
        token = share.json()["share_token"]
        job_id = await _insert_completed_compilation(db_session, resume_id)
        first_pdf = tmp_path / "concurrent-first.pdf"
        second_pdf = tmp_path / "concurrent-second.pdf"
        first_pdf.write_bytes(b"%PDF-first-concurrent")
        second_pdf.write_bytes(b"%PDF-second-concurrent")

        update_gate = asyncio.Event()
        update_count = 0
        original_execute = AsyncSession.execute

        async def gated_execute(session, statement, *args, **kwargs):
            nonlocal update_count
            if getattr(statement, "is_update", False) and getattr(
                getattr(statement, "table", None), "name", None
            ) == "compilations":
                update_count += 1
                if update_count == 1:
                    await update_gate.wait()
                elif update_count == 2:
                    update_gate.set()
            return await original_execute(session, statement, *args, **kwargs)

        upload_calls: list[tuple[str, bytes, str]] = []

        def capture_upload(key, data, content_type):
            upload_calls.append((key, data, content_type))

        async def route_db_override():
            async with db_session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = route_db_override
        with (
            patch.object(AsyncSession, "execute", new=gated_execute),
            patch(
                "app.api.routes.get_job_files",
                side_effect=[
                    (tmp_path, first_pdf, tmp_path / "first.log"),
                    (tmp_path, second_pdf, tmp_path / "second.log"),
                ],
            ),
            patch("app.services.storage_service.upload_bytes", side_effect=capture_upload),
            patch(
                "app.services.storage_service.generate_presigned_url",
                return_value="https://storage.example/concurrent.pdf",
            ),
            patch("app.services.storage_service.delete_object") as delete_object,
        ):
            try:
                async with (
                    AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client_a,
                    AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client_b,
                ):
                    responses = await asyncio.gather(
                        client_a.get(f"/share/{token}"),
                        client_b.get(f"/share/{token}"),
                    )
            finally:
                app.dependency_overrides.pop(get_db, None)

        assert [response.status_code for response in responses] == [200, 200]
        assert update_count == 2
        assert len(upload_calls) == 2
        keys = [key for key, _, _ in upload_calls]
        assert len(set(keys)) == 2
        assert {data for _, data, _ in upload_calls} == {
            b"%PDF-first-concurrent",
            b"%PDF-second-concurrent",
        }
        winner = (
            await db_session.execute(
                text("SELECT pdf_path FROM compilations WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        ).scalar_one()
        assert winner in keys
        winner_bytes = {key: data for key, data, _ in upload_calls}[winner]
        assert winner_bytes in {b"%PDF-first-concurrent", b"%PDF-second-concurrent"}
        delete_object.assert_called_once_with(keys[0] if keys[1] == winner else keys[1])

    async def test_authenticated_resume_reports_review_access_and_revoke_resets_it(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        resume = await _create_resume(client, auth_headers, "Review capability state")
        resume_id = resume["id"]

        enabled = await client.post(
            f"/resumes/{resume_id}/share",
            headers=auth_headers,
            json={"review_comments": True},
        )
        assert enabled.status_code == 200
        assert enabled.json()["review_comments"] is True

        authenticated = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert authenticated.status_code == 200
        assert authenticated.json()["share_review_comments"] is True

        revoked = await client.delete(f"/resumes/{resume_id}/share", headers=auth_headers)
        assert revoked.status_code == 204
        after_revoke = await client.get(f"/resumes/{resume_id}", headers=auth_headers)
        assert after_revoke.status_code == 200
        assert after_revoke.json()["share_review_comments"] is False

        recreated = await client.post(f"/resumes/{resume_id}/share", headers=auth_headers)
        assert recreated.status_code == 200
        assert recreated.json()["review_comments"] is False

    async def test_anonymous_share_never_falls_back_to_original_pdf(
        self,
        client: AsyncClient,
        auth_headers: dict,
        db_session: AsyncSession,
    ):
        create_resp = await client.post(
            "/resumes/",
            headers=auth_headers,
            json={
                "title": "Jane Doe Private Resume",
                "latex_content": (
                    r"\documentclass{article}\begin{document}"
                    r"jane.private@example.com\end{document}"
                ),
            },
        )
        resume_id = create_resp.json()["id"]
        await _insert_completed_compilation(
            db_session,
            resume_id,
            pdf_path=f"shares/{resume_id}/original.pdf",
        )

        with patch("app.workers.latex_worker.submit_latex_compilation"):
            share_resp = await client.post(
                f"/resumes/{resume_id}/share",
                headers=auth_headers,
                json={"anonymous": True},
            )
        token = share_resp.json()["share_token"]

        with patch("app.services.storage_service.file_exists", return_value=False):
            get_resp = await client.get(f"/share/{token}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["anonymous_processing"] is True
        assert data["pdf_url"] is None
        assert data["resume_title"] == "Anonymous Resume"
        assert data["review_comments"] is False
        assert "jane.private@example.com" not in data["accessible_text"]

    async def test_anonymous_share_promotes_worker_redis_pdf_to_job_scoped_storage(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """The API and compiler have no shared filesystem on Modal."""
        resume = await _create_resume(client, auth_headers, "Redis Handoff")
        with patch("app.workers.latex_worker.submit_latex_compilation"):
            share_resp = await client.post(
                f"/resumes/{resume['id']}/share",
                headers=auth_headers,
                json={"anonymous": True},
            )
        token = share_resp.json()["share_token"]
        stored = (await client.get(
            f"/resumes/{resume['id']}", headers=auth_headers
        )).json()
        job_id = stored["metadata"]["share_anonymous_job_id"]

        fake_redis = AsyncMock()
        fake_redis.get.return_value = base64.b64encode(b"%PDF-1.7 redacted")
        expected_url = "https://storage.example/redacted.pdf"
        with (
            patch("app.services.storage_service.file_exists", return_value=False),
            patch("app.core.redis.get_redis_client", AsyncMock(return_value=fake_redis)),
            patch("app.services.storage_service.upload_bytes") as upload,
            patch(
                "app.services.storage_service.generate_presigned_url",
                return_value=expected_url,
            ),
        ):
            get_resp = await client.get(f"/share/{token}")

        assert get_resp.status_code == 200
        assert get_resp.json()["pdf_url"] == expected_url
        expected_key = f"shares/{resume['id']}/anonymous/{job_id}.pdf"
        upload.assert_called_once_with(
            expected_key, b"%PDF-1.7 redacted", "application/pdf"
        )

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

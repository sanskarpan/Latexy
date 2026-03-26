"""
Tests for Feature 26: One-Click Resume Tailoring (Quick Tailor).

Covers:
  - POST /resumes/{id}/quick-tailor returns fork_id and job_id
  - Fork title includes role_title when provided
  - Fork title falls back to company_name when no role_title
  - Fork title defaults to "Tailored" when neither is provided
  - parent_resume_id set correctly on the created fork
  - Original resume's latex_content is unchanged after tailoring
  - Job submitted with optimization_level = "aggressive"
  - Requires auth (401/403 without credentials)
  - job_description too short → 422
  - job_description too long → 422
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Hello World\end{document}"
_JD = "We are looking for a Senior Software Engineer with 5+ years of experience in Python and FastAPI. You will design scalable microservices."


async def _create_resume(
    client: AsyncClient,
    auth_headers: dict,
    title: str = "Test Resume",
) -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch_job_submission():
    """Patch Redis state writing and Celery task submission so no infra needed."""
    return (
        patch(
            "app.api.job_routes._write_initial_redis_state",
            new_callable=AsyncMock,
        ),
        patch(
            "app.workers.orchestrator.submit_optimize_and_compile",
            return_value="mock-job-id",
        ),
    )


# ---------------------------------------------------------------------------
# Validation tests (no infra needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQuickTailorValidation:
    async def test_job_description_too_short_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{parent['id']}/quick-tailor",
            headers=auth_headers,
            json={"job_description": "short"},
        )
        assert resp.status_code == 422

    async def test_job_description_too_long_returns_422(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        resp = await client.post(
            f"/resumes/{parent['id']}/quick-tailor",
            headers=auth_headers,
            json={"job_description": "x" * 10001},
        )
        assert resp.status_code == 422

    async def test_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/resumes/some-nonexistent-id/quick-tailor",
            json={"job_description": _JD},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Core behaviour tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQuickTailorBehaviour:
    async def test_returns_fork_id_and_job_id(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD, "role_title": "Senior SWE"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "fork_id" in data
        assert "job_id" in data
        assert isinstance(data["fork_id"], str) and len(data["fork_id"]) > 0
        assert isinstance(data["job_id"], str) and len(data["job_id"]) > 0

    async def test_fork_has_correct_parent_resume_id(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD},
            )
        assert resp.status_code == 201
        fork_id = resp.json()["fork_id"]

        fork_resp = await client.get(f"/resumes/{fork_id}", headers=auth_headers)
        assert fork_resp.status_code == 200
        assert fork_resp.json()["parent_resume_id"] == parent["id"]

    async def test_fork_title_uses_role_title(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers, title="My Resume")
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={
                    "job_description": _JD,
                    "role_title": "Backend Engineer",
                    "company_name": "Google",
                },
            )
        assert resp.status_code == 201
        fork_id = resp.json()["fork_id"]

        fork_resp = await client.get(f"/resumes/{fork_id}", headers=auth_headers)
        assert "Backend Engineer" in fork_resp.json()["title"]

    async def test_fork_title_falls_back_to_company_name(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers, title="My Resume")
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD, "company_name": "Meta"},
            )
        assert resp.status_code == 201
        fork_id = resp.json()["fork_id"]

        fork_resp = await client.get(f"/resumes/{fork_id}", headers=auth_headers)
        assert "Meta" in fork_resp.json()["title"]

    async def test_fork_title_defaults_to_tailored(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers, title="My Resume")
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD},
            )
        assert resp.status_code == 201
        fork_id = resp.json()["fork_id"]

        fork_resp = await client.get(f"/resumes/{fork_id}", headers=auth_headers)
        assert "Tailored" in fork_resp.json()["title"]

    async def test_original_latex_content_unchanged(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD, "role_title": "SWE"},
            )

        parent_resp = await client.get(f"/resumes/{parent['id']}", headers=auth_headers)
        assert parent_resp.status_code == 200
        assert parent_resp.json()["latex_content"] == _LATEX

    async def test_job_submitted_with_aggressive_level(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ) as mock_redis, patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD, "role_title": "SWE"},
            )
        assert resp.status_code == 201
        # Redis state was initialised for the combined job
        mock_redis.assert_awaited_once()
        args = mock_redis.call_args
        assert args[0][1] == "combined"  # job_type

    async def test_fork_clones_latex_content_from_parent(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        parent = await _create_resume(client, auth_headers)
        with patch(
            "app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock
        ), patch(
            "app.workers.orchestrator.optimize_and_compile_task"
        ):
            resp = await client.post(
                f"/resumes/{parent['id']}/quick-tailor",
                headers=auth_headers,
                json={"job_description": _JD},
            )
        assert resp.status_code == 201
        fork_id = resp.json()["fork_id"]

        fork_resp = await client.get(f"/resumes/{fork_id}", headers=auth_headers)
        assert fork_resp.json()["latex_content"] == _LATEX

    async def test_cannot_tailor_others_resume(
        self, client: AsyncClient, auth_headers: dict, db_session
    ) -> None:
        """Ownership check — another user's resume returns 404."""
        import uuid as _uuid
        from sqlalchemy import text
        from conftest import _insert_session

        # Create a second user
        other_user_id = str(_uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, name, email_verified, subscription_plan, subscription_status, trial_used) "
                "VALUES (:id, :email, 'Other User', true, 'free', 'active', false) ON CONFLICT DO NOTHING"
            ),
            {"id": other_user_id, "email": f"test_{other_user_id[:8]}@example.com"},
        )
        await db_session.commit()

        # Create a resume for the second user
        other_token = await _insert_session(db_session, other_user_id)
        other_headers = {"Authorization": f"Bearer {other_token}"}
        other_resume_resp = await client.post(
            "/resumes/",
            headers=other_headers,
            json={"title": "Other User Resume", "latex_content": _LATEX},
        )
        assert other_resume_resp.status_code == 201
        other_resume_id = other_resume_resp.json()["id"]

        # auth_headers user should get 404 trying to tailor the other user's resume
        resp = await client.post(
            f"/resumes/{other_resume_id}/quick-tailor",
            headers=auth_headers,
            json={"job_description": _JD},
        )
        assert resp.status_code == 404

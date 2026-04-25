"""
Tests for Feature 75 — Bulk Apply Package.

Covers:
  - Batch of 3 jobs → 3 separate variant resumes created (mock LLM / infra)
  - jobs list with 11 entries → 422
  - Non-owned resume_id → 403
  - GET /jobs/batch/{batch_id} returns correct per-job status
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LATEX = r"\documentclass{article}\begin{document}Alice Lee\end{document}"

_JD = (
    "We are looking for a software engineer with 3+ years of Python experience. "
    "You will build scalable backend services and collaborate with product teams."
)


def _make_job(company: str = "Acme Corp", role: str = "Software Engineer", jd: str = _JD) -> dict:
    return {"company_name": company, "role_title": role, "job_description": jd}


async def _create_resume(client: AsyncClient, auth_headers: dict, title: str = "Test Resume") -> dict:
    resp = await client.post(
        "/resumes/",
        headers=auth_headers,
        json={"title": title, "latex_content": _LATEX},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _patch_infra():
    """Patch Redis writes and Celery submission so no real infra is required."""
    return (
        patch("app.api.job_routes._write_initial_redis_state", new_callable=AsyncMock),
        patch("app.api.job_routes.submit_optimize_and_compile", return_value="mock-job-id"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBatchTailorEndpoint:
    async def test_batch_of_three_creates_three_variants(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A batch of 3 jobs should create 3 forked resume variants."""
        parent = await _create_resume(client, auth_headers)
        parent_id = parent["id"]

        jobs = [
            _make_job("Acme Corp", "Backend Engineer"),
            _make_job("Globex Inc", "Senior Python Dev"),
            _make_job("Initech", "Platform Engineer"),
        ]

        with _patch_infra()[0], _patch_infra()[1]:
            resp = await client.post(
                "/jobs/batch",
                headers=auth_headers,
                json={"resume_id": parent_id, "jobs": jobs},
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "batch_id" in data
        assert len(data["job_ids"]) == 3

        # Verify the parent now has 3 child variants
        variants_resp = await client.get(f"/resumes/{parent_id}/variants", headers=auth_headers)
        assert variants_resp.status_code == 200
        assert len(variants_resp.json()) == 3

    async def test_eleven_jobs_returns_422(self, client: AsyncClient, auth_headers: dict):
        """Submitting 11 job items should fail validation with 422."""
        parent = await _create_resume(client, auth_headers)
        jobs = [_make_job(f"Company {i}", f"Role {i}") for i in range(11)]

        resp = await client.post(
            "/jobs/batch",
            headers=auth_headers,
            json={"resume_id": parent["id"], "jobs": jobs},
        )
        assert resp.status_code == 422

    async def test_non_owned_resume_returns_403(self, client: AsyncClient, auth_headers: dict):
        """Using a resume_id the authenticated user does not own should return 403."""
        with _patch_infra()[0], _patch_infra()[1]:
            resp = await client.post(
                "/jobs/batch",
                headers=auth_headers,
                json={"resume_id": "00000000-0000-0000-0000-000000000000", "jobs": [_make_job()]},
            )
        assert resp.status_code == 403

    async def test_get_batch_status_returns_job_list(
        self, client: AsyncClient, auth_headers: dict
    ):
        """GET /jobs/batch/{batch_id} should return per-job status for an existing batch."""
        parent = await _create_resume(client, auth_headers)
        jobs = [_make_job("Acme", "Engineer"), _make_job("Globex", "Developer")]

        # Patch _write_initial_redis_state to actually write a real queued state
        # (the mock captures the call but we still need Redis state for the GET to read)
        from app.api.job_routes import _write_initial_redis_state

        written_job_ids: list[str] = []

        async def _fake_write(job_id: str, job_type: str, user_id, estimated_seconds: int):
            written_job_ids.append(job_id)
            await _write_initial_redis_state(job_id, job_type, user_id, estimated_seconds)

        with (
            patch("app.api.job_routes._write_initial_redis_state", side_effect=_fake_write),
            patch("app.api.job_routes.submit_optimize_and_compile", return_value="mock"),
        ):
            post_resp = await client.post(
                "/jobs/batch",
                headers=auth_headers,
                json={"resume_id": parent["id"], "jobs": jobs},
            )

        assert post_resp.status_code == 201
        batch_id = post_resp.json()["batch_id"]

        get_resp = await client.get(f"/jobs/batch/{batch_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        status_data = get_resp.json()
        assert status_data["batch_id"] == batch_id
        assert len(status_data["jobs"]) == 2
        _VALID = {"queued", "processing", "running", "completed", "failed", "cancelled"}
        assert all(j["status"] in _VALID for j in status_data["jobs"])
        # Company names round-trip
        company_names = {j["company_name"] for j in status_data["jobs"]}
        assert company_names == {"Acme", "Globex"}

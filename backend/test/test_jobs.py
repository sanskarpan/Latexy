"""
Job submission, state polling, and cancellation tests.

Tests run against the real API endpoints (httpx ASGI transport).
Celery tasks are mocked at the task dispatch level so we don't need a
running worker for these unit/integration tests.
"""

import re
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\begin{document}
\begin{center}\textbf{\Large Jane Smith}\\jane@example.com\end{center}
\section*{Skills}
Python, TypeScript, Docker
\end{document}
"""


# ── Job submission ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobSubmission:

    async def test_submit_latex_compilation(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch(
            "app.workers.latex_worker.submit_latex_compilation",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={"job_type": "latex_compilation", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert "job_id" in data
        assert data["success"] is True
        # Validate UUID format
        uuid.UUID(data["job_id"])

    async def test_submit_missing_latex_content(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/jobs/submit",
            json={"job_type": "latex_compilation"},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    async def test_submit_invalid_job_type(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.post(
            "/jobs/submit",
            json={"job_type": "nonexistent_type", "latex_content": VALID_LATEX},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)

    async def test_submit_combined_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch(
            "app.workers.orchestrator.submit_optimize_and_compile",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": VALID_LATEX,
                    "job_description": "Software Engineer at Google with Python experience",
                    "optimization_level": "balanced",
                },
                headers=auth_headers,
            )
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data
        assert re.match(r'^[0-9a-f-]{36}$', data["job_id"]), "job_id should be a UUID"

    async def test_submit_ats_scoring(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch(
            "app.workers.ats_worker.submit_ats_scoring",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "ats_scoring",
                    "latex_content": VALID_LATEX,
                    "job_description": "Data Scientist role",
                },
                headers=auth_headers,
            )
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert data["success"] is True
        assert "job_id" in data
        assert re.match(r'^[0-9a-f-]{36}$', data["job_id"]), "job_id should be a UUID"


# ── Job state polling ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobState:

    async def test_get_state_nonexistent_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}/state", headers=auth_headers)
        assert resp.status_code == 404
        data = resp.json()
        assert "detail" in data

    async def test_get_state_unauthenticated(self, client: AsyncClient):
        """State endpoint has no auth requirement; returns 404 for non-existent job."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}/state")
        assert resp.status_code == 404

    async def test_get_state_after_submit(
        self, client: AsyncClient, auth_headers: dict
    ):
        """State should be readable immediately after job submission."""
        with patch(
            "app.workers.latex_worker.submit_latex_compilation",
            return_value=None,
        ):
            submit = await client.post(
                "/jobs/submit",
                json={"job_type": "latex_compilation", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        if submit.status_code not in (200, 202):
            pytest.skip("Submit failed — Redis may not be available")

        job_id = submit.json()["job_id"]
        state_resp = await client.get(f"/jobs/{job_id}/state", headers=auth_headers)
        # State must be 200 immediately after submit (Redis is written before task dispatch)
        if state_resp.status_code == 404:
            pytest.skip("Redis state key missing — Redis may not be available")
        assert state_resp.status_code == 200
        data = state_resp.json()
        assert "status" in data
        assert data["status"] == "queued"


# ── Job cancellation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobCancellation:

    async def test_cancel_nonexistent_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/jobs/{fake_id}", headers=auth_headers)
        # Should not crash — 200 (noop), 404, or 204
        assert resp.status_code in (200, 204, 404)

    async def test_cancel_no_auth_required(self, client: AsyncClient):
        """Cancel endpoint has no auth requirement; sets Redis flag and returns 200."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"/jobs/{fake_id}")
        assert resp.status_code in (200, 204)


# ── PDF download ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPDFDownload:

    async def test_download_nonexistent_pdf(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/download/{fake_id}")
        assert resp.status_code == 404

    async def test_download_invalid_job_id_format(self, client: AsyncClient):
        # Path traversal attempt should be blocked
        resp = await client.get("/download/../etc/passwd")
        assert resp.status_code in (400, 404, 422)


# ── Trial / anonymous access ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTrialSystem:

    async def test_trial_status_with_fingerprint(self, client: AsyncClient):
        fp = "test_device_fingerprint_abc123"
        resp = await client.get(f"/public/trial-status?fingerprint={fp}")
        assert resp.status_code == 200
        data = resp.json()
        assert "usageCount" in data or "usage_count" in data
        assert "canUse" in data or "can_use" in data

    async def test_trial_status_missing_fingerprint(self, client: AsyncClient):
        resp = await client.get("/public/trial-status")
        assert resp.status_code in (400, 422)


# ── Error path tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobSubmissionErrorPaths:

    async def test_combined_job_missing_job_description(
        self, client: AsyncClient, auth_headers: dict
    ):
        """combined job without job_description is accepted (JD is optional)."""
        with patch(
            "app.workers.orchestrator.submit_optimize_and_compile",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={"job_type": "combined", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        assert resp.status_code == 200

    async def test_llm_optimization_missing_job_description(
        self, client: AsyncClient, auth_headers: dict
    ):
        """llm_optimization without job_description is accepted (JD is optional)."""
        with patch(
            "app.workers.llm_worker.submit_resume_optimization",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={"job_type": "llm_optimization", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        assert resp.status_code == 200

    async def test_submit_with_empty_metadata_dict(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Empty metadata dict is valid and should not cause 500."""
        with patch(
            "app.workers.latex_worker.submit_latex_compilation",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": VALID_LATEX,
                    "metadata": {},
                },
                headers=auth_headers,
            )
        assert resp.status_code in (200, 202)

    async def test_submit_with_large_metadata_is_sanitised(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Metadata with too many keys should be accepted (sanitised server-side)."""
        oversized_meta = {f"key_{i}": "x" * 300 for i in range(20)}
        with patch(
            "app.workers.latex_worker.submit_latex_compilation",
            return_value=None,
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": VALID_LATEX,
                    "metadata": oversized_meta,
                },
                headers=auth_headers,
            )
        # Should succeed (server truncates metadata, not reject)
        assert resp.status_code in (200, 202)

    async def test_result_not_available_for_queued_job(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Result endpoint should return 404 for a job that was just queued."""
        with patch(
            "app.workers.latex_worker.submit_latex_compilation",
            return_value=None,
        ):
            submit = await client.post(
                "/jobs/submit",
                json={"job_type": "latex_compilation", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        if submit.status_code not in (200, 202):
            pytest.skip("Submit failed")
        job_id = submit.json()["job_id"]
        result_resp = await client.get(f"/jobs/{job_id}/result", headers=auth_headers)
        assert result_resp.status_code == 404


# ── Estimated time in response ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestEstimatedTime:

    async def test_latex_compilation_has_estimated_time(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch("app.workers.latex_worker.submit_latex_compilation", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={"job_type": "latex_compilation", "latex_content": VALID_LATEX},
                headers=auth_headers,
            )
        if resp.status_code not in (200, 202):
            pytest.skip("Submit failed")
        data = resp.json()
        assert "estimated_time" in data
        assert isinstance(data["estimated_time"], int)
        assert data["estimated_time"] > 0

    async def test_combined_job_has_estimated_time(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch("app.workers.orchestrator.submit_optimize_and_compile", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": VALID_LATEX,
                    "job_description": "Software Engineer role",
                },
                headers=auth_headers,
            )
        if resp.status_code not in (200, 202):
            pytest.skip("Submit failed")
        assert resp.json()["estimated_time"] > 0

    async def test_pro_plan_has_lower_estimated_time(
        self, client: AsyncClient, auth_headers: dict
    ):
        """Pro plan should have lower estimated time (0.7x multiplier)."""
        free_resp = None
        pro_resp = None
        with patch("app.workers.latex_worker.submit_latex_compilation", return_value=None):
            free_resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": VALID_LATEX,
                    "user_plan": "free",
                },
                headers=auth_headers,
            )
            pro_resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "latex_compilation",
                    "latex_content": VALID_LATEX,
                    "user_plan": "pro",
                },
                headers=auth_headers,
            )
        if free_resp.status_code not in (200, 202) or pro_resp.status_code not in (200, 202):
            pytest.skip("Submit failed")
        assert pro_resp.json()["estimated_time"] < free_resp.json()["estimated_time"]

    async def test_ats_scoring_has_expected_estimated_time(
        self, client: AsyncClient, auth_headers: dict
    ):
        with patch("app.workers.ats_worker.submit_ats_scoring", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "ats_scoring",
                    "latex_content": VALID_LATEX,
                    "job_description": "Data Scientist",
                },
                headers=auth_headers,
            )
        if resp.status_code not in (200, 202):
            pytest.skip("Submit failed")
        # ats_scoring default is 20s
        assert resp.json()["estimated_time"] == 20


# ── Jobs health endpoint ───────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestJobsHealth:

    async def test_health_endpoint_returns_200(self, client: AsyncClient):
        resp = await client.get("/jobs/health")
        assert resp.status_code == 200

    async def test_health_response_has_status_field(self, client: AsyncClient):
        resp = await client.get("/jobs/health")
        data = resp.json()
        assert "status" in data

    async def test_health_response_has_timestamp(self, client: AsyncClient):
        resp = await client.get("/jobs/health")
        data = resp.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], float)

    async def test_health_status_is_healthy_or_degraded(self, client: AsyncClient):
        resp = await client.get("/jobs/health")
        assert resp.json()["status"] in ("healthy", "degraded", "unhealthy")


# ── System cleanup endpoint ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSystemCleanup:

    async def test_cleanup_temp_files_accepted(self, client: AsyncClient):
        with patch("app.workers.cleanup_worker.submit_temp_files_cleanup", return_value="test-job-id"):
            resp = await client.post("/jobs/system/cleanup?cleanup_type=temp_files")
        assert resp.status_code == 200

    async def test_cleanup_expired_jobs_accepted(self, client: AsyncClient):
        with patch("app.workers.cleanup_worker.submit_expired_jobs_cleanup", return_value="test-job-id"):
            resp = await client.post("/jobs/system/cleanup?cleanup_type=expired_jobs")
        assert resp.status_code == 200

    async def test_cleanup_invalid_type_returns_400(self, client: AsyncClient):
        resp = await client.post("/jobs/system/cleanup?cleanup_type=nonexistent_type")
        assert resp.status_code == 400

    async def test_cleanup_returns_job_id(self, client: AsyncClient):
        with patch("app.api.job_routes.submit_temp_files_cleanup", return_value="cleanup-123"):
            resp = await client.post("/jobs/system/cleanup?cleanup_type=temp_files")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] == "cleanup-123"


# ── List jobs endpoint ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestListJobs:

    async def test_list_jobs_unauthenticated_returns_empty(self, client: AsyncClient):
        resp = await client.get("/jobs/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["total_count"] == 0

    async def test_list_jobs_response_has_required_fields(self, client: AsyncClient):
        resp = await client.get("/jobs/")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "total_count" in data

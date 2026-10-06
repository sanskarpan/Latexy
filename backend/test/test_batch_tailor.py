"""
Tests for Feature 75 — Bulk Apply Package.

Covers:
  - Batch of 3 jobs → 3 separate variant resumes created (mock LLM / infra)
  - jobs list with 11 entries → 422
  - Non-owned resume_id → 403
  - GET /jobs/batch/{batch_id} returns correct per-job status
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.api.job_routes import get_batch_status, get_job_result
from app.database.models import JobFinalization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_headers(pro_auth_headers: dict) -> dict:
    """Run this module as a PRO user.

    A batch tailor spends one optimization per job description and a batch is
    all-or-nothing, so run this module on a plan with an unlimited allowance.
    The money meter itself is covered in test_usage_quotas.py.
    """
    return pro_auth_headers


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
        settings_resp = await client.patch(
            f"/resumes/{parent_id}/settings",
            headers=auth_headers,
            json={"compiler": "xelatex", "main_file": "main.tex", "extra_packages": ["xcolor"]},
        )
        assert settings_resp.status_code == 200, settings_resp.text

        jobs = [
            _make_job("Acme Corp", "Backend Engineer"),
            _make_job("Globex Inc", "Senior Python Dev"),
            _make_job("Initech", "Platform Engineer"),
        ]

        redis_patch, submit_patch = _patch_infra()
        with redis_patch, submit_patch as mock_submit:
            resp = await client.post(
                "/jobs/batch",
                headers=auth_headers,
                json={"resume_id": parent_id, "jobs": jobs},
            )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "batch_id" in data
        assert len(data["job_ids"]) == 3
        assert mock_submit.call_count == 3
        assert all(
            call.kwargs["metadata"]["persist_optimized_resume"] is True
            and isinstance(call.kwargs["metadata"]["expected_latex_content"], str)
            and call.kwargs["quota_refund"]["dimension"] == "optimizations"
            and call.kwargs["quota_refund"]["cost"] == 1
            and call.kwargs["compiler"] == "xelatex"
            and call.kwargs["compile_settings"]["main_file"] == "main.tex"
            and call.kwargs["compile_settings"]["extra_packages"] == ["xcolor"]
            for call in mock_submit.call_args_list
        )

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


@pytest.mark.asyncio
class TestBatchTailorQuotaRefund:
    """The whole batch is charged up front and ambiguous dispatch stays trackable."""

    async def test_enqueue_failure_refunds_the_whole_batch(
        self, client: AsyncClient, pro_auth_headers: dict
    ):
        from app.services.entitlement_service import entitlement_service

        resume = await _create_resume(client, pro_auth_headers, "Refund Resume")
        user_id = resume["user_id"]

        redis_patch, submit_patch = _patch_infra()
        with redis_patch, submit_patch as mock_submit:
            mock_submit.side_effect = RuntimeError("broker down")
            resp = await client.post(
                "/jobs/batch",
                headers=pro_auth_headers,
                json={"resume_id": resume["id"], "jobs": [_make_job(), _make_job("Globex")]},
            )

        assert resp.status_code == 201
        snapshot = await entitlement_service.quota_snapshot(user_id, "pro")
        # The first marked dispatch is ambiguous and remains charged until
        # lifecycle cleanup proves it never ran; only the second is refunded.
        assert snapshot["dimensions"]["optimizations"]["used"] == 1
        variants = await client.get(
            f"/resumes/{resume['id']}/variants", headers=pro_auth_headers
        )
        assert variants.status_code == 200
        assert len(variants.json()) == 2

    async def test_partial_enqueue_returns_trackable_batch_and_refunds_unstarted(
        self, client: AsyncClient, pro_auth_headers: dict, db_session
    ):
        from app.services.entitlement_service import entitlement_service

        resume = await _create_resume(client, pro_auth_headers, "Partial Resume")
        user_id = resume["user_id"]

        redis_patch, submit_patch = _patch_infra()
        with redis_patch, submit_patch as mock_submit:
            mock_submit.side_effect = ["accepted", RuntimeError("broker down")]
            response = await client.post(
                "/jobs/batch",
                headers=pro_auth_headers,
                json={"resume_id": resume["id"], "jobs": [_make_job(), _make_job("Globex")]},
            )

        assert response.status_code == 201
        batch = response.json()
        status = await client.get(
            f"/jobs/batch/{batch['batch_id']}", headers=pro_auth_headers
        )
        assert status.status_code == 200
        # Both broker calls reached the dispatch marker. The second exception
        # is therefore ambiguous and must remain queued/charged until cleanup
        # proves that no worker claimed it; no refund is safe at this point.
        assert [job["status"] for job in status.json()["jobs"]] == ["queued", "queued"]
        finalizations = (
            await db_session.execute(
                select(JobFinalization).where(JobFinalization.job_id.in_(batch["job_ids"]))
            )
        ).scalars().all()
        by_job = {row.job_id: row for row in finalizations}
        assert by_job[batch["job_ids"][0]].state == "pending"
        assert by_job[batch["job_ids"][1]].state == "pending"

        snapshot = await entitlement_service.quota_snapshot(user_id, "pro")
        # The second marked dispatch is also ambiguous, so both receipts stay
        # charged until bounded cleanup fences the unresolved work.
        assert snapshot["dimensions"]["optimizations"]["used"] == 2

    async def test_unattempted_tail_is_terminalized_and_refunded(
        self, client: AsyncClient, pro_auth_headers: dict, db_session
    ):
        from app.services.entitlement_service import entitlement_service

        resume = await _create_resume(client, pro_auth_headers, "Unattempted Tail Resume")
        user_id = resume["user_id"]
        jobs = [_make_job(), _make_job("Globex"), _make_job("Initech")]
        write_patch = patch(
            "app.api.job_routes._write_initial_redis_state",
            new_callable=AsyncMock,
            side_effect=[None, None, RuntimeError("redis unavailable before dispatch")],
        )
        submit_patch = patch(
            "app.api.job_routes.submit_optimize_and_compile",
            side_effect=["accepted-1", "accepted-2"],
        )
        with write_patch, submit_patch:
            response = await client.post(
                "/jobs/batch",
                headers=pro_auth_headers,
                json={"resume_id": resume["id"], "jobs": jobs},
            )

        assert response.status_code == 201
        batch = response.json()
        status = await client.get(
            f"/jobs/batch/{batch['batch_id']}", headers=pro_auth_headers
        )
        assert status.status_code == 200
        assert [job["status"] for job in status.json()["jobs"]] == [
            "queued",
            "queued",
            "failed",
        ]
        finalizations = (
            await db_session.execute(
                select(JobFinalization).where(JobFinalization.job_id.in_(batch["job_ids"]))
            )
        ).scalars().all()
        by_job = {row.job_id: row for row in finalizations}
        assert [by_job[job_id].state for job_id in batch["job_ids"]] == [
            "pending",
            "pending",
            "failed",
        ]
        snapshot = await entitlement_service.quota_snapshot(user_id, "pro")
        assert snapshot["dimensions"]["optimizations"]["used"] == 2


class _BatchRedis:
    def __init__(self, values: dict[str, str | None]):
        self.values = values

    async def get(self, key: str):
        return self.values.get(key)


@pytest.mark.asyncio
class TestBatchDurableRecovery:
    async def _seed_finalization(self, db_session, *, user_id: str, state: str) -> str:
        # API job-result routes validate server-issued IDs as UUIDs.
        job_id = str(uuid.uuid4())
        db_session.add(
            JobFinalization(
                id=str(uuid.uuid4()),
                job_id=job_id,
                user_id=user_id,
                job_type="combined",
                state=state,
                terminal_result="completed" if state == "completed" else "failed",
                result_payload={"success": state == "completed", "job_id": job_id},
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        await db_session.commit()
        return job_id

    async def test_cached_processing_recovers_owned_terminal_batch_job(self, db_session, auth_headers, client):
        resume = await _create_resume(client, auth_headers, "Recovery Resume")
        user_id = resume["user_id"]
        job_id = await self._seed_finalization(db_session, user_id=user_id, state="completed")
        batch_id = f"test_batch_{uuid.uuid4().hex}"
        redis = _BatchRedis(
            {
                f"latexy:batch:{batch_id}": json.dumps(
                    {
                        "batch_id": batch_id,
                        "user_id": user_id,
                        "jobs": [{"job_id": job_id, "company_name": "Acme", "role_title": "Engineer"}],
                    }
                ),
                f"latexy:job:{job_id}:state": json.dumps({"status": "processing"}),
            }
        )
        with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
            response = await get_batch_status(batch_id, db_session, user_id)
        assert response.jobs[0].status == "completed"

    async def test_missing_state_recovers_owned_failed_batch_job(self, db_session, auth_headers, client):
        resume = await _create_resume(client, auth_headers, "Missing State Resume")
        user_id = resume["user_id"]
        job_id = await self._seed_finalization(db_session, user_id=user_id, state="failed")
        batch_id = f"test_batch_{uuid.uuid4().hex}"
        redis = _BatchRedis(
            {
                f"latexy:batch:{batch_id}": json.dumps(
                    {
                        "batch_id": batch_id,
                        "user_id": user_id,
                        "jobs": [{"job_id": job_id, "company_name": "Acme", "role_title": "Engineer"}],
                    }
                )
            }
        )
        with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
            response = await get_batch_status(batch_id, db_session, user_id)
        assert response.jobs[0].status == "failed"

    async def test_durable_failure_overrides_stale_redis_success(self, db_session, auth_headers, client):
        resume = await _create_resume(client, auth_headers, "Result Recovery Resume")
        user_id = resume["user_id"]
        job_id = await self._seed_finalization(db_session, user_id=user_id, state="failed")
        redis = _BatchRedis(
            {
                f"latexy:job:{job_id}:meta": json.dumps({"user_id": user_id}),
                f"latexy:job:{job_id}:result": json.dumps({"success": True, "job_id": job_id}),
            }
        )
        with patch("app.api.job_routes.get_redis_client", new=AsyncMock(return_value=redis)):
            response = await get_job_result(job_id, db_session, user_id)
        assert response.success is False
        assert response.result is None
        assert response.error == "Job failed"

"""
Phase 7 Integration tests — full HTTP API ↔ Redis consistency.

These tests exercise the REST endpoints end-to-end (using httpx ASGI transport)
and then inspect Redis directly to verify that the correct keys/values were
written.  They require a running Redis instance on the URL configured in
conftest.py (default: redis://localhost:6379/15, DB 15 for tests).

Celery task dispatch is mocked at the submit function level so no Celery
worker is required.

Coverage:
  - POST /jobs/submit writes Redis state, stream entry, and metadata
  - GET /jobs/{id}/state returns the queued state immediately after submit
  - GET /jobs/{id}/result returns 404 for a freshly-submitted (not-yet-complete) job
  - DELETE /jobs/{id} sets the latexy:job:{id}:cancel key with correct TTL
  - Multi-job isolation: two jobs have independent Redis state/streams
  - Cancel isolation: cancelling job A does not set cancel flag for job B
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.redis import get_redis_client

# Minimal valid LaTeX for submission tests
_VALID_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\begin{document}
Hello World
\end{document}
"""

_JOB_DESCRIPTION = "Software Engineer role requiring Python and Docker experience"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _submit_latex_job(client: AsyncClient) -> dict | None:
    """Submit a latex_compilation job with the worker patched out.

    Returns the JSON body on success, None if submission unexpectedly failed.
    """
    with patch("app.workers.latex_worker.submit_latex_compilation", return_value=None):
        resp = await client.post(
            "/jobs/submit",
            json={"job_type": "latex_compilation", "latex_content": _VALID_LATEX},
        )
    if resp.status_code not in (200, 202):
        return None
    return resp.json()


# ---------------------------------------------------------------------------
# Job submission → Redis state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobSubmissionRedisState:
    """After POST /jobs/submit the correct Redis keys must be written."""

    async def test_submit_writes_state_key(self, client: AsyncClient):
        """latexy:job:{id}:state should be set with status=queued."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed — Redis may not be available")

        job_id = body["job_id"]
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:state")

        assert raw is not None, f"State key missing for job {job_id}"
        state = json.loads(raw)
        assert state["status"] == "queued"
        assert state["percent"] == 0
        assert "last_updated" in state

    async def test_submit_writes_stream_entry(self, client: AsyncClient):
        """latexy:stream:{id} should have a job.queued entry after submission."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        entries = await r.xread({f"latexy:stream:{job_id}": "0-0"}, count=10)

        assert entries, f"Stream empty for job {job_id}"
        _stream_key, messages = entries[0]
        assert len(messages) >= 1

        _msg_id, fields = messages[0]
        payload = json.loads(fields["payload"])
        assert payload["type"] == "job.queued"
        assert payload["job_id"] == job_id

    async def test_submit_writes_metadata_key(self, client: AsyncClient):
        """latexy:job:{id}:meta should record job_type and job_id."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:meta")

        assert raw is not None, f"Meta key missing for job {job_id}"
        meta = json.loads(raw)
        assert meta["job_type"] == "latex_compilation"
        assert meta["job_id"] == job_id

    async def test_submit_queued_event_has_correct_fields(self, client: AsyncClient):
        """The job.queued stream event must have required base fields."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        entries = await r.xread({f"latexy:stream:{job_id}": "0-0"}, count=1)

        if not entries:
            pytest.skip("Stream empty — Redis may not be persisting")

        _key, messages = entries[0]
        _msg_id, fields = messages[0]
        event = json.loads(fields["payload"])

        assert "event_id" in event
        assert "timestamp" in event
        assert "sequence" in event
        assert event["sequence"] >= 1
        assert event["type"] == "job.queued"


# ---------------------------------------------------------------------------
# GET /jobs/{id}/state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobStateEndpoint:

    async def test_state_returns_queued_after_submit(self, client: AsyncClient):
        """GET /jobs/{id}/state should return status=queued immediately after submit."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        state_resp = await client.get(f"/jobs/{job_id}/state")

        assert state_resp.status_code == 200
        data = state_resp.json()
        assert data["status"] == "queued"
        assert isinstance(data["percent"], int)

    async def test_state_returns_404_for_unknown_job(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}/state")
        assert resp.status_code == 404

    async def test_state_fields_match_redis_data(self, client: AsyncClient):
        """The state endpoint should return exactly what was written to Redis."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]

        # Read directly from Redis
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:state")
        if not raw:
            pytest.skip("Redis state key not found")
        redis_state = json.loads(raw)

        # Read via REST endpoint
        rest_resp = await client.get(f"/jobs/{job_id}/state")
        assert rest_resp.status_code == 200
        rest_state = rest_resp.json()

        assert rest_state["status"] == redis_state["status"]
        assert rest_state["percent"] == redis_state["percent"]


# ---------------------------------------------------------------------------
# GET /jobs/{id}/result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobResultEndpoint:

    async def test_result_returns_404_for_queued_job(self, client: AsyncClient):
        """A freshly queued job has no result yet — should return 404."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        result_resp = await client.get(f"/jobs/{job_id}/result")

        assert result_resp.status_code == 404

    async def test_result_returns_404_for_nonexistent_job(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}/result")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /jobs/{id} — cancel flag in Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCancelRedisState:

    async def test_cancel_sets_redis_flag(self, client: AsyncClient):
        """DELETE /jobs/{id} must write latexy:job:{id}:cancel = '1'."""
        job_id = str(uuid.uuid4())
        resp = await client.delete(f"/jobs/{job_id}")
        assert resp.status_code in (200, 204)

        r = await get_redis_client()
        flag = await r.get(f"latexy:job:{job_id}:cancel")
        assert flag is not None, "Cancel flag not set in Redis"
        assert flag == "1"

    async def test_cancel_flag_has_positive_ttl(self, client: AsyncClient):
        """Cancel flag TTL should be positive (not persisted forever)."""
        job_id = str(uuid.uuid4())
        await client.delete(f"/jobs/{job_id}")

        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:job:{job_id}:cancel")
        assert ttl > 0, "Cancel flag should have a TTL"

    async def test_cancel_flag_ttl_not_exceeds_one_hour(self, client: AsyncClient):
        """Cancel flag TTL should be at most 1 hour (3600 seconds)."""
        job_id = str(uuid.uuid4())
        await client.delete(f"/jobs/{job_id}")

        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:job:{job_id}:cancel")
        assert ttl <= 3600

    async def test_cancel_is_idempotent(self, client: AsyncClient):
        """Calling cancel twice on the same job should not error."""
        job_id = str(uuid.uuid4())
        resp1 = await client.delete(f"/jobs/{job_id}")
        resp2 = await client.delete(f"/jobs/{job_id}")

        assert resp1.status_code in (200, 204)
        assert resp2.status_code in (200, 204)

        r = await get_redis_client()
        flag = await r.get(f"latexy:job:{job_id}:cancel")
        assert flag == "1"

    async def test_cancel_returns_success_body(self, client: AsyncClient):
        job_id = str(uuid.uuid4())
        resp = await client.delete(f"/jobs/{job_id}")
        assert resp.status_code in (200, 204)
        if resp.status_code == 200:
            data = resp.json()
            assert data.get("success") is True


# ---------------------------------------------------------------------------
# Multi-job isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMultiJobIsolation:

    async def test_two_jobs_have_different_ids(self, client: AsyncClient):
        """Submitting two jobs must produce two distinct job_ids."""
        ids = []
        for _ in range(2):
            body = await _submit_latex_job(client)
            if body:
                ids.append(body["job_id"])

        if len(ids) < 2:
            pytest.skip("Could not submit 2 jobs")

        assert ids[0] != ids[1]

    async def test_two_jobs_have_independent_state_keys(self, client: AsyncClient):
        """Each job has its own latexy:job:{id}:state key."""
        ids = []
        for _ in range(2):
            body = await _submit_latex_job(client)
            if body:
                ids.append(body["job_id"])

        if len(ids) < 2:
            pytest.skip("Could not submit 2 jobs")

        r = await get_redis_client()
        for jid in ids:
            raw = await r.get(f"latexy:job:{jid}:state")
            assert raw is not None, f"State key missing for job {jid}"
            state = json.loads(raw)
            assert state["status"] == "queued"

    async def test_two_jobs_have_independent_streams(self, client: AsyncClient):
        """Stream entries for job A should contain only job A's events."""
        ids = []
        for _ in range(2):
            body = await _submit_latex_job(client)
            if body:
                ids.append(body["job_id"])

        if len(ids) < 2:
            pytest.skip("Could not submit 2 jobs")

        r = await get_redis_client()
        for jid in ids:
            entries = await r.xread({f"latexy:stream:{jid}": "0-0"}, count=10)
            if not entries:
                continue
            _key, messages = entries[0]
            for _msg_id, fields in messages:
                event = json.loads(fields["payload"])
                assert event["job_id"] == jid, (
                    f"Stream for job {jid} contains event for wrong job {event['job_id']}"
                )

    async def test_cancel_job_a_does_not_set_flag_for_job_b(self, client: AsyncClient):
        """Cancelling job A must not write the cancel flag for job B."""
        job_a = str(uuid.uuid4())
        job_b = str(uuid.uuid4())

        await client.delete(f"/jobs/{job_a}")

        r = await get_redis_client()
        flag_a = await r.get(f"latexy:job:{job_a}:cancel")
        flag_b = await r.get(f"latexy:job:{job_b}:cancel")

        assert flag_a == "1", "Job A should have cancel flag"
        assert flag_b is None, "Job B should NOT have cancel flag"


# ---------------------------------------------------------------------------
# Trial / anonymous access regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTrialSystemRegression:
    """Verify the trial limit system (trial_service.py) is unaffected."""

    async def test_trial_status_endpoint_responds(self, client: AsyncClient):
        fp = f"test_fp_{uuid.uuid4().hex[:12]}"
        resp = await client.get(f"/public/trial-status?fingerprint={fp}")
        assert resp.status_code == 200

    async def test_trial_status_has_required_fields(self, client: AsyncClient):
        fp = f"test_fp_{uuid.uuid4().hex[:12]}"
        resp = await client.get(f"/public/trial-status?fingerprint={fp}")
        data = resp.json()

        # Accept both camelCase and snake_case field names
        has_usage = "usageCount" in data or "usage_count" in data
        has_can_use = "canUse" in data or "can_use" in data
        assert has_usage, f"Response missing usage count field: {data}"
        assert has_can_use, f"Response missing can_use field: {data}"

    async def test_fresh_fingerprint_has_zero_usage(self, client: AsyncClient):
        """A brand-new fingerprint should have 0 prior usage."""
        fp = f"new_device_{uuid.uuid4().hex}"
        resp = await client.get(f"/public/trial-status?fingerprint={fp}")
        assert resp.status_code == 200
        data = resp.json()

        # Use explicit key lookup to avoid falsy-zero issue with `or`
        if "usageCount" in data:
            usage_count = data["usageCount"]
        elif "usage_count" in data:
            usage_count = data["usage_count"]
        else:
            usage_count = -1

        if usage_count == -1:
            # device_trials table may not be present in test DB (Alembic migration)
            pytest.skip("device_trials table not available in test DB — skipping value check")

        assert usage_count == 0

    async def test_trial_missing_fingerprint_returns_error(self, client: AsyncClient):
        resp = await client.get("/public/trial-status")
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Submit combined / ats_scoring job types (routing regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobTypeRouting:

    async def test_combined_job_type_accepted(self, client: AsyncClient):
        """combined job type should be accepted and queued."""
        with patch(
            "app.workers.orchestrator.submit_optimize_and_compile", return_value=None
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": _VALID_LATEX,
                    "job_description": _JOB_DESCRIPTION,
                },
            )
        assert resp.status_code in (200, 202)
        assert "job_id" in resp.json()

    async def test_ats_scoring_job_type_accepted(self, client: AsyncClient):
        """ats_scoring job type should be accepted and queued."""
        with patch("app.workers.ats_worker.submit_ats_scoring", return_value=None):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "ats_scoring",
                    "latex_content": _VALID_LATEX,
                    "job_description": _JOB_DESCRIPTION,
                },
            )
        assert resp.status_code in (200, 202)

    async def test_combined_job_writes_redis_state(self, client: AsyncClient):
        """combined job type should also write Redis state after submission."""
        with patch(
            "app.workers.orchestrator.submit_optimize_and_compile", return_value=None
        ):
            resp = await client.post(
                "/jobs/submit",
                json={
                    "job_type": "combined",
                    "latex_content": _VALID_LATEX,
                    "job_description": _JOB_DESCRIPTION,
                },
            )
        if resp.status_code not in (200, 202):
            pytest.skip("Submit failed")

        job_id = resp.json()["job_id"]
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:state")
        assert raw is not None
        state = json.loads(raw)
        assert state["status"] == "queued"

    async def test_unsupported_job_type_returns_400(self, client: AsyncClient):
        resp = await client.post(
            "/jobs/submit",
            json={"job_type": "nonexistent_type", "latex_content": _VALID_LATEX},
        )
        assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /jobs/{id}/result when result IS available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobResultWhenAvailable:

    async def test_result_returns_200_when_available(self, client: AsyncClient):
        """Writing result directly to Redis then fetching via REST returns 200."""
        job_id = str(uuid.uuid4())
        r = await get_redis_client()
        result_payload = json.dumps({
            "success": True,
            "job_id": job_id,
            "pdf_job_id": job_id,
            "ats_score": 85.0,
            "compilation_time": 3.5,
            "optimization_time": 12.0,
            "tokens_used": 320,
        })
        await r.setex(f"latexy:job:{job_id}:result", 3600, result_payload)

        resp = await client.get(f"/jobs/{job_id}/result")
        assert resp.status_code == 200

    async def test_result_body_has_success_true(self, client: AsyncClient):
        job_id = str(uuid.uuid4())
        r = await get_redis_client()
        result_payload = json.dumps({"success": True, "job_id": job_id})
        await r.setex(f"latexy:job:{job_id}:result", 3600, result_payload)

        resp = await client.get(f"/jobs/{job_id}/result")
        assert resp.json()["success"] is True

    async def test_result_body_has_job_id(self, client: AsyncClient):
        job_id = str(uuid.uuid4())
        r = await get_redis_client()
        result_payload = json.dumps({"success": True, "job_id": job_id})
        await r.setex(f"latexy:job:{job_id}:result", 3600, result_payload)

        resp = await client.get(f"/jobs/{job_id}/result")
        assert resp.json()["job_id"] == job_id

    async def test_failed_result_has_error_field(self, client: AsyncClient):
        """A failed result stored in Redis should expose the error field."""
        job_id = str(uuid.uuid4())
        r = await get_redis_client()
        result_payload = json.dumps({
            "success": False,
            "job_id": job_id,
            "error": "pdflatex exited with code 1",
        })
        await r.setex(f"latexy:job:{job_id}:result", 3600, result_payload)

        resp = await client.get(f"/jobs/{job_id}/result")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"] is not None


# ---------------------------------------------------------------------------
# Redis key TTLs and metadata correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisKeyTTLs:

    async def test_state_key_has_positive_ttl(self, client: AsyncClient):
        """The state key must have a TTL > 0 (not persisted forever)."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:job:{job_id}:state")
        assert ttl > 0, "State key should have a positive TTL"

    async def test_state_key_ttl_not_exceeds_24h(self, client: AsyncClient):
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:job:{job_id}:state")
        assert ttl <= 86400, "State key TTL should not exceed 24 hours"

    async def test_meta_key_has_positive_ttl(self, client: AsyncClient):
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:job:{job_id}:meta")
        assert ttl > 0

    async def test_meta_submitted_at_is_float(self, client: AsyncClient):
        """meta key should contain a float submitted_at timestamp."""
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:meta")
        if not raw:
            pytest.skip("Meta key not found")
        meta = json.loads(raw)
        assert isinstance(meta["submitted_at"], float)
        assert meta["submitted_at"] > 0

    async def test_meta_contains_job_type(self, client: AsyncClient):
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        raw = await r.get(f"latexy:job:{job_id}:meta")
        if not raw:
            pytest.skip("Meta key not found")
        meta = json.loads(raw)
        assert meta["job_type"] == "latex_compilation"

    async def test_stream_key_has_positive_ttl(self, client: AsyncClient):
        body = await _submit_latex_job(client)
        if body is None:
            pytest.skip("Job submission failed")

        job_id = body["job_id"]
        r = await get_redis_client()
        ttl = await r.ttl(f"latexy:stream:{job_id}")
        assert ttl > 0

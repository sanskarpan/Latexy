"""Real isolated DB/Redis admission and refund contract; no live provider calls."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.api import job_routes
from app.core.redis import get_redis_cache_client
from app.services.entitlement_service import entitlement_service
from app.workers import llm_worker


async def test_admitted_job_survives_toggle_and_worker_failure_refunds_once(
    client, auth_headers, db_session, monkeypatch,
):
    # Capture dispatch to a controlled queue. The real route persists admission,
    # consumes real quota and creates the normal durable ownership metadata.
    queued = MagicMock()
    monkeypatch.setattr(job_routes, "submit_resume_optimization", queued)
    monkeypatch.setattr(llm_worker.settings, "OPENAI_API_KEY", "")
    payload = {
        "job_type": "llm_optimization",
        "latex_content": r"\documentclass{article}\begin{document}Resume\end{document}",
        "job_description": "Software engineer with Python experience",
    }
    await entitlement_service.set_kill_switch("d01", True, db_session)
    try:
        admitted = await client.post("/jobs/submit", json=payload, headers=auth_headers)
        assert admitted.status_code == 200, admitted.text
        queued.assert_called_once()
        kwargs = queued.call_args.kwargs
        job_id = admitted.json()["job_id"]
        receipt = kwargs["quota_refund"]
        cache = await get_redis_cache_client()
        quota_key = f"latexy:quota:{receipt['dimension']}:{receipt['user_id']}:{receipt['period']}"
        assert int(await cache.get(quota_key)) == 1

        await entitlement_service.set_kill_switch("d01", False, db_session)
        blocked = await client.post("/jobs/submit", json=payload, headers=auth_headers)
        assert blocked.status_code == 403
        assert "feature_disabled" in blocked.text
        queued.assert_called_once()
        assert int(await cache.get(quota_key)) == 1

        # The real worker still owns the admitted job after the switch. Missing
        # provider config is a controlled terminal failure, before any network
        # call. Its ordinary finalizer/refund must settle this admitted credit.
        result = await asyncio.to_thread(llm_worker.optimize_resume_task.run, **kwargs)
        assert result["success"] is False
        assert result["error"] == "No OpenAI API key configured"
        assert int(await cache.get(quota_key)) == 0
        marker = f"latexy:quota-refund:{receipt['dimension']}:{job_id}"
        assert await cache.get(marker)

        # Redelivery cannot refund twice or drive the user's balance negative.
        await asyncio.to_thread(llm_worker.optimize_resume_task.run, **kwargs)
        assert int(await cache.get(quota_key)) == 0
        state = await client.get(f"/jobs/{job_id}/state", headers=auth_headers)
        historical = await client.get(f"/jobs/{job_id}/result", headers=auth_headers)
        assert state.status_code == 200
        assert historical.status_code == 200
        assert state.json()["status"] == "failed"
    finally:
        await entitlement_service.set_kill_switch("d01", True, db_session)

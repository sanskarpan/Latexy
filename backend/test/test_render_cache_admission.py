"""Cache-only admission retains normal authorization/quota/durable dispatch."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.api import job_routes
from app.core.redis import get_redis_client
from app.database.models import JobFinalization
from app.services.render_engine import admission_cache

SOURCE = r"\documentclass{article}\begin{document}Resume\end{document}"


@pytest.mark.parametrize("primitive", [r"\today", r"\directlua{tex.print(os.time())}"])
async def test_volatile_source_bypasses_lookup_without_invalid_redis_key(monkeypatch, primitive):
    redis = AsyncMock()
    assert not await admission_cache.has_exact_render_cache(redis, {
        "latex_content": SOURCE.replace("Resume", primitive), "user_id": "fixture",
        "compiler": "pdflatex",
    })
    redis.get.assert_not_awaited()


@pytest.mark.parametrize("hit", [False, True])
async def test_exact_cache_avoids_broker_but_retains_durable_admission(client, db_session, auth_headers, monkeypatch, hit):
    monkeypatch.setattr(admission_cache, "has_exact_render_cache", AsyncMock(return_value=hit))
    broker = MagicMock(return_value="queued")
    cache = MagicMock(return_value={"success": True})
    monkeypatch.setattr(job_routes, "submit_latex_compilation", broker)
    monkeypatch.setattr(admission_cache, "execute_exact_render_cache", cache)
    response = await client.post("/jobs/submit", headers=auth_headers, json={
        "job_type": "latex_compilation", "latex_content": SOURCE,
    })
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    row = (await db_session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))).scalar_one()
    assert row.user_id and row.job_type == "latex_compilation"
    redis = await get_redis_client()
    lifecycle = await redis.hgetall(f"latexy:job:{job_id}:lifecycle")
    assert lifecycle["status"] == "queued" and lifecycle.get("accepted_at")
    assert broker.call_count == (0 if hit else 1)
    assert cache.call_count == (1 if hit else 0)
    kwargs = cache.call_args.args[0] if hit else broker.call_args.kwargs
    assert kwargs["user_id"] == row.user_id
    assert kwargs["quota_refund"] and kwargs["quota_refund"]["user_id"] == row.user_id
    cache_redis = await job_routes.get_redis_cache_client()
    assert await cache_redis.exists(f"latexy:quota-refund-pending:{job_id}")


async def test_lookup_failure_is_not_ambiguous_dispatch(client, db_session, auth_headers, monkeypatch):
    lookup = AsyncMock(side_effect=RuntimeError("lookup unavailable"))
    broker = MagicMock()
    monkeypatch.setattr(admission_cache, "has_exact_render_cache", lookup)
    monkeypatch.setattr(job_routes, "submit_latex_compilation", broker)
    response = await client.post("/jobs/submit", headers=auth_headers, json={
        "job_type": "latex_compilation", "latex_content": SOURCE,
    })
    assert response.status_code == 500
    broker.assert_not_called()
    job_id = lookup.call_args.args[1]["job_id"]
    assert (await db_session.execute(select(JobFinalization).where(JobFinalization.job_id == job_id))).scalar_one_or_none() is None


async def test_accepted_cache_failure_never_falls_back_to_tex(client, auth_headers, monkeypatch):
    broker = MagicMock()
    monkeypatch.setattr(admission_cache, "has_exact_render_cache", AsyncMock(return_value=True))
    monkeypatch.setattr(admission_cache, "execute_exact_render_cache", MagicMock(side_effect=RuntimeError("cache disappeared")))
    monkeypatch.setattr(job_routes, "submit_latex_compilation", broker)
    response = await client.post("/jobs/submit", headers=auth_headers, json={
        "job_type": "latex_compilation", "latex_content": SOURCE,
    })
    assert response.status_code == 200 and response.json()["success"]
    broker.assert_not_called()

"""Authenticated ATS cache-loss recovery contract probes.

These tests deliberately run the route and worker against the isolated test
Postgres/Redis fixtures. Provider calls and broker dispatch are mocked; the
worker's terminal Redis publication is real. They document which ATS jobs have
an authoritative durable result after the 24-hour transport keys disappear.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis_client
from app.database.models import JobFinalization
from app.workers.ats_worker import (
    analyze_job_description_ats_task,
    score_resume_ats_task,
)

LATEX = r"""
\documentclass{article}
\begin{document}
\section*{Experience}
Software engineer with Python and distributed systems experience.
\end{document}
"""

JOB_DESCRIPTION = "Python software engineer with distributed systems and cloud experience."


async def _session_user_id(db_session: AsyncSession, headers: dict) -> str:
    token = headers["Authorization"].removeprefix("Bearer ")
    return str(
        await db_session.scalar(
            text('SELECT "userId" FROM session WHERE token = :token'),
            {"token": token},
        )
    )


async def _drop_transport_keys(job_id: str) -> None:
    redis = await get_redis_client()
    await redis.delete(
        f"latexy:job:{job_id}:state",
        f"latexy:job:{job_id}:meta",
        f"latexy:job:{job_id}:result",
        f"latexy:job:{job_id}:events",
        f"latexy:stream:{job_id}",
        f"latexy:job:{job_id}:seq",
        f"latexy:job:{job_id}:lifecycle",
    )


def _score_result() -> SimpleNamespace:
    return SimpleNamespace(
        overall_score=78.0,
        category_scores={"formatting": 80},
        recommendations=["Quantify impact"],
        strengths=["Clear experience"],
        warnings=[],
        detailed_analysis={"word_count": 20},
        industry_label=None,
        locale_key="global",
        locale_label="Global / role-only",
        score_threshold=80,
        calibration_statement="Document-quality checks",
    )


@pytest.mark.asyncio
async def test_authenticated_ats_score_recovers_after_redis_loss(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    user_id = await _session_user_id(db_session, auth_headers)
    with patch("app.api.ats_routes.submit_ats_scoring", return_value=str(uuid.uuid4())):
        response = await client.post(
            "/ats/score",
            json={"latex_content": LATEX, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    with (
        patch(
            "app.workers.ats_worker.ats_scoring_service.score_resume",
            new_callable=AsyncMock,
            return_value=_score_result(),
        ),
    ):
        task_result = (
            await asyncio.to_thread(
                score_resume_ats_task.apply,
                args=[LATEX],
                kwargs={"job_id": job_id, "user_id": user_id},
            )
        ).result
    assert task_result["success"] is True

    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "completed"

    await _drop_transport_keys(job_id)
    state = await client.get(f"/jobs/{job_id}/state", headers=auth_headers)
    result = await client.get(f"/jobs/{job_id}/result", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["status"] == "completed"
    assert result.status_code == 200
    assert result.json()["success"] is True
    assert result.json()["result"]["ats_score"] == 78.0


@pytest.mark.asyncio
async def test_authenticated_jd_analysis_recovers_after_redis_loss(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    auth_headers2: dict,
):
    with patch(
        "app.api.ats_routes.submit_job_description_analysis",
        return_value=str(uuid.uuid4()),
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # The real worker path publishes to the isolated Redis transport; no LLM
    # or broker call is involved in this rule-based JD analysis.
    task_result = (
        await asyncio.to_thread(
            analyze_job_description_ats_task.apply,
            args=[JOB_DESCRIPTION],
            kwargs={"job_id": job_id, "user_id": await _session_user_id(db_session, auth_headers)},
        )
    ).result
    assert task_result["success"] is True

    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "completed"
    await _drop_transport_keys(job_id)

    state = await client.get(f"/jobs/{job_id}/state", headers=auth_headers)
    result = await client.get(f"/jobs/{job_id}/result", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["status"] == "completed"
    assert result.status_code == 200
    assert result.json()["success"] is True
    assert result.json()["result"]["keywords"]
    assert (await client.get(f"/jobs/{job_id}/result", headers=auth_headers2)).status_code == 404
    assert (await client.get(f"/jobs/{job_id}/result")).status_code == 404


@pytest.mark.asyncio
async def test_ats_score_ambiguous_dispatch_retains_durable_reservation(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    with patch(
        "app.api.ats_routes.submit_ats_scoring",
        side_effect=RuntimeError("broker acknowledgement lost"),
    ):
        response = await client.post(
            "/ats/score",
            json={"latex_content": LATEX, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "pending"


@pytest.mark.asyncio
async def test_jd_analysis_ambiguous_dispatch_retains_durable_reservation(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    with patch(
        "app.api.ats_routes.submit_job_description_analysis",
        side_effect=RuntimeError("broker acknowledgement lost"),
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "pending"


@pytest.mark.asyncio
async def test_jd_worker_suppresses_completed_when_arbiter_rejects(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    with patch(
        "app.api.ats_routes.submit_job_description_analysis",
        return_value=str(uuid.uuid4()),
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    job_id = response.json()["job_id"]
    with patch("app.workers.event_publisher._persist_arbiter_terminal", return_value=False):
        task_result = (
            await asyncio.to_thread(
                analyze_job_description_ats_task.apply,
                args=[JOB_DESCRIPTION],
                kwargs={"job_id": job_id, "user_id": await _session_user_id(db_session, auth_headers)},
            )
        ).result
    assert task_result["success"] is False

    redis = await get_redis_client()
    entries = await redis.xrange(f"latexy:stream:{job_id}")
    event_types = [json.loads(fields["payload"])["type"] for _, fields in entries]
    assert "job.completed" not in event_types
    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "pending"
    await _drop_transport_keys(job_id)


@pytest.mark.asyncio
async def test_jd_failed_result_recovers_after_redis_loss(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    with patch(
        "app.api.ats_routes.submit_job_description_analysis",
        return_value=str(uuid.uuid4()),
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    monkeypatch.setattr(analyze_job_description_ats_task, "max_retries", 0)
    with patch(
        "app.workers.ats_worker.ats_scoring_service._extract_keywords_from_job_description",
        side_effect=RuntimeError("controlled JD failure"),
    ):
        task_result = (
            await asyncio.to_thread(
                analyze_job_description_ats_task.apply,
                args=[JOB_DESCRIPTION],
                kwargs={"job_id": job_id, "user_id": await _session_user_id(db_session, auth_headers)},
            )
        ).result
    assert task_result["success"] is False
    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "failed"

    await _drop_transport_keys(job_id)
    state = await client.get(f"/jobs/{job_id}/state", headers=auth_headers)
    result = await client.get(f"/jobs/{job_id}/result", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["status"] == "failed"
    assert result.status_code == 200
    assert result.json()["success"] is False


@pytest.mark.asyncio
async def test_jd_retrying_releases_lease_for_real_readmission(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    with patch(
        "app.api.ats_routes.submit_job_description_analysis",
        return_value=str(uuid.uuid4()),
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    user_id = await _session_user_id(db_session, auth_headers)

    with (
        patch(
            "app.workers.ats_worker.ats_scoring_service._extract_keywords_from_job_description",
            side_effect=RuntimeError("retryable JD failure"),
        ),
        patch.object(analyze_job_description_ats_task, "retry", side_effect=RuntimeError("retry requested")),
    ):
        with pytest.raises(RuntimeError, match="retry requested"):
            await asyncio.to_thread(
                analyze_job_description_ats_task.run,
                JOB_DESCRIPTION,
                job_id=job_id,
                user_id=user_id,
            )

    redis = await get_redis_client()
    lifecycle = await redis.hgetall(f"latexy:job:{job_id}:lifecycle")
    assert lifecycle.get("status") == "queued"
    assert "owner" not in lifecycle

    second_result = (
        await asyncio.to_thread(
            analyze_job_description_ats_task.apply,
            args=[JOB_DESCRIPTION],
            kwargs={"job_id": job_id, "user_id": user_id},
        )
    ).result
    assert second_result["success"] is True
    row = await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id))
    assert row is not None
    assert row.state == "completed"
    await _drop_transport_keys(job_id)


@pytest.mark.asyncio
async def test_jd_analysis_rolls_back_row_when_redis_admission_fails(
    client: AsyncClient,
    db_session: AsyncSession,
    auth_headers: dict,
):
    job_id = str(uuid.uuid4())
    with (
        patch("app.api.ats_routes.uuid.uuid4", return_value=uuid.UUID(job_id)),
        patch(
            "app.api.ats_routes._write_initial_redis_state",
            new_callable=AsyncMock,
            side_effect=RuntimeError("redis unavailable"),
        ),
        patch("app.api.ats_routes.submit_job_description_analysis") as submit,
    ):
        response = await client.post(
            "/ats/analyze-job-description",
            json={"job_description": JOB_DESCRIPTION, "async_processing": True},
            headers=auth_headers,
        )
    assert response.status_code == 503
    assert await db_session.scalar(select(JobFinalization).where(JobFinalization.job_id == job_id)) is None
    submit.assert_not_called()

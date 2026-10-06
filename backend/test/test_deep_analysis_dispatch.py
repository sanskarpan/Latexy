from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.ats_routes import (
    ATSScoreRequest,
    DeepAnalyzeRequest,
    SemanticMatchRequest,
    deep_analyze_resume,
    score_resume_ats,
)
from app.api.job_routes import (
    JobSubmissionRequest,
    _delete_initial_redis_state,
    submit_job,
)


def test_semantic_match_rejects_malformed_or_oversized_resume_id_lists():
    with pytest.raises(ValidationError):
        SemanticMatchRequest(job_description="x" * 50, resume_ids=["not-a-uuid"])

    with pytest.raises(ValidationError):
        SemanticMatchRequest(
            job_description="x" * 50,
            resume_ids=[f"00000000-0000-0000-0000-{index:012d}" for index in range(21)],
        )


@pytest.mark.asyncio
async def test_undispatched_job_cleanup_removes_every_initial_index():
    redis = AsyncMock()
    with patch("app.api.job_routes.get_redis_client", AsyncMock(return_value=redis)):
        await _delete_initial_redis_state("job-1", "user-1")

    redis.delete.assert_awaited_once_with(
        "latexy:job:job-1:state",
        "latexy:job:job-1:meta",
        "latexy:job:job-1:seq",
        "latexy:stream:job-1",
        "latexy:job:job-1:dispatch-started",
    )
    redis.zrem.assert_awaited_once_with("latexy:user:user-1:jobs", "job-1")


@pytest.mark.asyncio
async def test_redis_state_failure_refunds_and_never_dispatches_worker():
    db = AsyncMock(spec=AsyncSession)
    quota_ticket = MagicMock()
    submit = MagicMock()
    cleanup = AsyncMock()
    request = Request({"type": "http", "method": "POST", "path": "/ats/deep-analyze", "headers": []})

    with (
        patch(
            "app.api.ats_routes.api_key_service.get_user_provider",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.api.job_routes._resolve_user_plan",
            AsyncMock(return_value="pro"),
        ),
        patch(
            "app.api.ats_routes.entitlement_service.enforce_quota",
            AsyncMock(return_value=quota_ticket),
        ),
        patch(
            "app.api.ats_routes.entitlement_service.refund_quota",
            AsyncMock(return_value=None),
        ) as refund,
        patch(
            "app.api.ats_routes._write_deep_analysis_redis_state",
            AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ),
        patch("app.api.ats_routes._delete_initial_redis_state", cleanup),
        patch("app.api.ats_routes.submit_deep_analyze_ats", submit),
    ):
        with pytest.raises(HTTPException) as exc:
            await deep_analyze_resume(
                DeepAnalyzeRequest(latex_content="x" * 100),
                http_request=request,
                db=db,
                user_id="00000000-0000-0000-0000-000000000001",
            )

    assert exc.value.status_code == 503
    refund.assert_awaited_once_with(quota_ticket)
    cleanup.assert_awaited_once()
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_deep_analysis_broker_failure_preserves_ambiguous_dispatch():
    db = AsyncMock(spec=AsyncSession)
    quota_ticket = MagicMock()
    cleanup = AsyncMock()
    request = Request({"type": "http", "method": "POST", "path": "/ats/deep-analyze", "headers": []})

    with (
        patch(
            "app.api.ats_routes.api_key_service.get_user_provider",
            AsyncMock(return_value=None),
        ),
        patch("app.api.job_routes._resolve_user_plan", AsyncMock(return_value="pro")),
        patch(
            "app.api.ats_routes.entitlement_service.enforce_quota",
            AsyncMock(return_value=quota_ticket),
        ),
        patch(
            "app.api.ats_routes.entitlement_service.refund_quota",
            AsyncMock(return_value=None),
        ) as refund,
        patch("app.api.ats_routes._write_deep_analysis_redis_state", AsyncMock()),
        patch("app.api.ats_routes._delete_initial_redis_state", cleanup),
        patch("app.api.ats_routes._mark_dispatch_started", AsyncMock()),
        patch("app.api.ats_routes._mark_dispatch_accepted", AsyncMock()),
        patch(
            "app.api.ats_routes.submit_deep_analyze_ats",
            MagicMock(side_effect=RuntimeError("broker unavailable")),
        ),
    ):
        response = await deep_analyze_resume(
            DeepAnalyzeRequest(latex_content="x" * 100),
            http_request=request,
            db=db,
            user_id="00000000-0000-0000-0000-000000000001",
        )

    assert response.success is True
    assert response.job_id
    cleanup.assert_not_awaited()
    refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_rule_based_ats_state_failure_never_dispatches_invisible_job():
    db = AsyncMock(spec=AsyncSession)
    submit = MagicMock()
    cleanup = AsyncMock()
    request = Request({"type": "http", "method": "POST", "path": "/ats/score", "headers": []})

    with (
        patch("app.api.ats_routes._rate_limit_ok", AsyncMock(return_value=True)),
        patch("app.api.ats_routes._derive_user_plan", AsyncMock(return_value="free")),
        patch(
            "app.api.ats_routes._write_initial_redis_state",
            AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ),
        patch("app.api.ats_routes._delete_initial_redis_state", cleanup),
        patch("app.api.ats_routes.submit_ats_scoring", submit),
    ):
        with pytest.raises(HTTPException) as exc:
            await score_resume_ats(
                ATSScoreRequest(latex_content="x" * 100),
                http_request=request,
                db=db,
                user_id="00000000-0000-0000-0000-000000000001",
            )

    assert exc.value.status_code == 503
    cleanup.assert_awaited_once()
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_post_dispatch_bookkeeping_failure_does_not_create_retry_duplicate():
    db = AsyncMock(spec=AsyncSession)
    cleanup = AsyncMock()
    request = Request({"type": "http", "method": "POST", "path": "/jobs/submit", "headers": []})

    with (
        patch("app.api.job_routes._resolve_user_plan", AsyncMock(return_value="free")),
        patch("app.api.job_routes._write_initial_redis_state", AsyncMock()),
        patch("app.api.job_routes.submit_ats_scoring", MagicMock()),
        patch(
            "app.api.job_routes.record_job_submitted",
            MagicMock(side_effect=RuntimeError("metrics unavailable")),
        ),
        patch("app.api.job_routes._delete_initial_redis_state", cleanup),
    ):
        response = await submit_job(
            JobSubmissionRequest(job_type="ats_scoring", latex_content="x" * 100),
            http_request=request,
            db=db,
            user_id="00000000-0000-0000-0000-000000000001",
        )

    assert response.success is True
    assert response.job_id
    cleanup.assert_not_awaited()

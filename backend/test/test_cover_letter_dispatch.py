from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.cover_letter_routes import (
    GenerateCoverLetterRequest,
    generate_cover_letter,
)


@pytest.mark.asyncio
async def test_quota_rejection_creates_no_cover_letter_row():
    db = AsyncMock()
    db.add = MagicMock()
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = "free"
    db.execute.return_value = plan_result
    resume = SimpleNamespace(latex_content="resume")

    with (
        patch(
            "app.api.cover_letter_routes._verify_resume_ownership",
            AsyncMock(return_value=resume),
        ),
        patch(
            "app.api.cover_letter_routes.api_key_service.get_user_provider",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.api.cover_letter_routes.entitlement_service.enforce_quota",
            AsyncMock(side_effect=HTTPException(status_code=402, detail="Quota exceeded")),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await generate_cover_letter(
                GenerateCoverLetterRequest(
                    resume_id="00000000-0000-0000-0000-000000000001",
                    job_description="A sufficiently detailed job description",
                ),
                db=db,
                user_id="00000000-0000-0000-0000-000000000002",
            )

    assert exc.value.status_code == 402
    # The durable CoverLetter + JobFinalization intent is recorded before
    # quota consumption so a crash after the receipt can be reconciled.  A
    # rejected charge then removes both rows in the route's compensating
    # transaction rather than relying on an in-memory rollback.
    assert db.add.call_count == 2
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_ambiguous_broker_failure_preserves_job_for_recovery():
    db = AsyncMock()
    db.add = MagicMock()
    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = "pro"
    db.execute.return_value = plan_result
    resume = SimpleNamespace(latex_content="resume")
    ticket = MagicMock()
    ticket.refund_payload.return_value = {
        "dimension": "optimizations",
        "user_id": "user-1",
        "period": "202610",
        "cost": 1,
    }
    cleanup = AsyncMock()

    with (
        patch(
            "app.api.cover_letter_routes._verify_resume_ownership",
            AsyncMock(return_value=resume),
        ),
        patch(
            "app.api.cover_letter_routes.api_key_service.get_user_provider",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.api.cover_letter_routes.entitlement_service.enforce_quota",
            AsyncMock(return_value=ticket),
        ) as quota,
        patch(
            "app.api.cover_letter_routes.entitlement_service.refund_quota",
            AsyncMock(),
        ) as refund,
        patch("app.api.cover_letter_routes._write_initial_redis_state", AsyncMock()),
        patch("app.api.cover_letter_routes._mark_dispatch_started", AsyncMock()),
        patch("app.api.cover_letter_routes._mark_dispatch_accepted", AsyncMock()),
        patch(
            "app.api.cover_letter_routes.submit_cover_letter_generation",
            MagicMock(side_effect=RuntimeError("broker unavailable")),
        ) as submit,
        patch("app.api.cover_letter_routes._delete_initial_redis_state", cleanup),
    ):
        response = await generate_cover_letter(
            GenerateCoverLetterRequest(
                resume_id="00000000-0000-0000-0000-000000000001",
                job_description="A sufficiently detailed job description",
            ),
            db=db,
            user_id="00000000-0000-0000-0000-000000000002",
        )

    assert response.success is True
    assert response.job_id
    quota.assert_awaited_once_with(
        "optimizations",
        user_id="00000000-0000-0000-0000-000000000002",
        plan="pro",
        job_id=response.job_id,
    )
    assert submit.call_args.kwargs["quota_refund"] == ticket.refund_payload.return_value
    refund.assert_not_awaited()
    cleanup.assert_not_awaited()
    db.delete.assert_not_awaited()

"""A frozen primary must not look like fresh or refundable Redis quota."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.config import QUOTA_DIMENSIONS
from app.services import entitlement_service as module


@pytest.mark.parametrize("plan", [None, "free", "basic", "pro", "team", "byok"])
@pytest.mark.parametrize("dimension", QUOTA_DIMENSIONS)
async def test_frozen_quota_denies_every_plan_before_identity_policy_or_redis(plan, dimension):
    service = module.EntitlementService()
    with (
        patch.object(module, "_quota_authority_active", new=AsyncMock(return_value=False)),
        patch.object(service, "_effective_plan_for_billing_status", new=AsyncMock()) as identity,
        patch("app.core.redis.get_redis_cache_client", new=AsyncMock()) as redis,
    ):
        ticket = await service.consume_quota(dimension, user_id="synthetic", plan=plan, job_id="uncertain")
    assert not ticket.allowed
    assert ticket.unavailable
    assert ticket.receipt_id == ""
    identity.assert_not_awaited()
    redis.assert_not_awaited()


async def test_frozen_enforcement_is_unavailable_not_exhausted_or_upgrade_prompt():
    with patch.object(module, "_quota_authority_active", new=AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as caught:
            await module.EntitlementService().enforce_quota("compilations", user_id="synthetic", plan="pro")
    assert caught.value.status_code == 503
    assert "quota_unavailable" in str(caught.value.detail)
    assert "quota_exceeded" not in str(caught.value.detail)


@pytest.mark.parametrize("unavailable", [False, True])
async def test_frozen_refund_never_confirms_cleanup_or_writes_a_marker(unavailable):
    ticket = module.QuotaTicket(
        dimension="compilations", user_id="synthetic", period="202610", used=1,
        limit=10, allowed=True, unavailable=unavailable, job_id="uncertain",
    )
    with (
        patch.object(module, "_quota_authority_active", new=AsyncMock(return_value=False)),
        patch("app.core.redis.get_redis_cache_client", new=AsyncMock()) as redis,
    ):
        assert await module.EntitlementService().refund_quota(ticket) is False
    redis.assert_not_awaited()


async def test_frozen_snapshot_reports_unknown_usage_without_reading_empty_backup():
    service = module.EntitlementService()
    policies = {dimension: {"limit": None, "window": "month"} for dimension in QUOTA_DIMENSIONS}
    with (
        patch.object(module, "_quota_authority_active", new=AsyncMock(return_value=False)),
        patch.object(service, "_effective_plan_for_billing_status", new=AsyncMock(return_value="pro")),
        patch("app.services.quota_policy_service.quota_policy_service.resolve", new=AsyncMock(return_value=policies)),
        patch("app.core.redis.get_redis_cache_client", new=AsyncMock()) as redis,
    ):
        snapshot = await service.quota_snapshot("synthetic", "pro")
    assert snapshot["authority_available"] is False
    assert all(value["used"] is None for value in snapshot["dimensions"].values())
    redis.assert_not_awaited()

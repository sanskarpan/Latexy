"""Global billing sales admission regressions with synthetic checkout data."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.redis import get_redis_cache_client
from app.database.models import FeatureFlag, User
from app.services.entitlement_service import entitlement_service
from app.services.feature_flag_service import FeatureFlagService
from app.services.payment_service import payment_service


@pytest.fixture
async def billing_on(db_session):
    flag = await db_session.get(FeatureFlag, "billing")
    existed = flag is not None
    original_value = flag.enabled if flag is not None else None
    if flag is None:
        flag = FeatureFlag(key="billing", enabled=True, label="Billing")
        db_session.add(flag)
    else:
        flag.enabled = True
    await db_session.commit()
    try:
        yield
    finally:
        await db_session.rollback()
        current = await db_session.get(FeatureFlag, "billing")
        if existed and current is not None:
            current.enabled = original_value
        elif current is not None:
            await db_session.delete(current)
        await db_session.commit()


async def _set_billing(db_session, enabled: bool) -> None:
    flag = await db_session.get(FeatureFlag, "billing")
    assert flag is not None
    flag.enabled = enabled
    await db_session.commit()


async def _create_customer(db_session) -> tuple[str, dict[str, str]]:
    user_id = str(uuid4())
    token = f"test_billing_admission_{uuid4().hex}"
    db_session.add(User(
        id=user_id,
        email=f"test_{uuid4().hex}@example.test",
        name="Synthetic billing customer",
        role="user",
        subscription_plan="free",
        subscription_status="inactive",
    ))
    await db_session.commit()
    await db_session.execute(text(
        'INSERT INTO session (id, "userId", "expiresAt", token) VALUES (:id, :uid, :expires, :token)'
    ), {
        "id": str(uuid4()),
        "uid": user_id,
        "expires": datetime.now(timezone.utc) + timedelta(days=1),
        "token": token,
    })
    await db_session.commit()
    return user_id, {"Authorization": f"Bearer {token}"}


async def test_billing_reads_latest_db_value_across_service_instances(db_session, billing_on):
    first_worker = FeatureFlagService()
    second_worker = FeatureFlagService()

    assert await first_worker.get_flag("billing", db_session) is True
    await _set_billing(db_session, False)
    assert await second_worker.get_flag("billing", db_session) is False


async def test_billing_read_failure_fails_closed():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("synthetic database outage")

    assert await FeatureFlagService().get_flag("billing", db) is False
    db.rollback.assert_awaited_once_with()

    db.execute.side_effect = None
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
    assert await FeatureFlagService().get_flag("billing", db) is False

    db.execute.side_effect = RuntimeError("synthetic database outage")
    assert await FeatureFlagService().get_flag("task_priority", db) is True
    assert db.rollback.await_count == 2


async def test_billing_off_blocks_checkout_and_preserves_student_verification(
    client, db_session, billing_on, monkeypatch,
):
    user_id, auth = await _create_customer(db_session)
    checkout = AsyncMock(return_value={"success": True, "short_url": "https://checkout.example.test/synthetic"})
    monkeypatch.setattr(payment_service, "create_subscription", checkout)

    # Warm one worker's previous on-state, then commit the global sales pause.
    assert await FeatureFlagService().get_flag("billing", db_session) is True
    await _set_billing(db_session, False)

    direct = await client.post("/subscription/create", headers=auth, json={
        "planId": "pro", "customerEmail": "ignored@example.test", "customerName": "Ignored",
    })
    assert direct.status_code == 503, direct.text
    checkout.assert_not_awaited()

    redis = await get_redis_cache_client()
    token = f"test_billing_off_student_{uuid4().hex}"
    token_key = f"student_plan_verify:{token}"
    lock_key = f"latexy:student-verify:{hashlib.sha256(token.encode()).hexdigest()}"
    await redis.set(token_key, json.dumps({
        "user_id": user_id,
        "customer_email": "student@example.edu",
        "customer_name": "Synthetic billing customer",
        "student_email": "student@example.edu",
    }), ex=3600)
    try:
        verified = await client.get(f"/subscription/student/verify/{token}")
        assert verified.status_code == 503, verified.text
        checkout.assert_not_awaited()
        assert await redis.get(token_key)
        assert await redis.get(lock_key) is None
    finally:
        await redis.delete(token_key)
        await redis.delete(lock_key)


async def test_billing_on_keeps_valid_checkout_and_student_verification(
    client, db_session, billing_on, monkeypatch,
):
    user_id, auth = await _create_customer(db_session)
    monkeypatch.setattr(
        entitlement_service, "has_feature_for_plan", AsyncMock(return_value=True),
    )
    monkeypatch.setattr(payment_service, "is_available", lambda: True)
    checkout = AsyncMock(return_value={
        "success": True,
        "subscription_id": "sub_synthetic_billing_admission",
        "checkout_session_id": "session_synthetic_billing_admission",
        "short_url": "https://checkout.example.test/synthetic",
    })
    monkeypatch.setattr(payment_service, "create_subscription", checkout)

    direct = await client.post("/subscription/create", headers=auth, json={
        "planId": "pro", "customerEmail": "ignored@example.test", "customerName": "Ignored",
    })
    assert direct.status_code == 200, direct.text
    assert direct.json()["success"] is True
    checkout.assert_awaited_once()

    redis = await get_redis_cache_client()
    token = f"test_billing_on_student_{uuid4().hex}"
    token_key = f"student_plan_verify:{token}"
    lock_key = f"latexy:student-verify:{hashlib.sha256(token.encode()).hexdigest()}"
    await redis.set(token_key, json.dumps({
        "user_id": user_id,
        "customer_email": "student@example.edu",
        "customer_name": "Synthetic billing customer",
        "student_email": "student@example.edu",
    }), ex=3600)
    try:
        verified = await client.get(f"/subscription/student/verify/{token}")
        assert verified.status_code == 200, verified.text
        assert verified.json()["success"] is True
        assert checkout.await_count == 2
        assert await redis.get(token_key) is None
        assert await redis.get(lock_key) is None
    finally:
        await redis.delete(token_key)
        await redis.delete(lock_key)

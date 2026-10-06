"""Focused B59 referral safety tests that do not require a live payment provider."""

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.models import (
    Payment,
    ReferralAttribution,
    ReferralIdentity,
    ReferralReward,
    Subscription,
    User,
)
from app.services.referral_service import ReferralService, normalize_referral_code


def test_referral_codes_are_bounded_and_case_normalized():
    assert normalize_referral_code(" abcd1234efgh5678 ") == "ABCD1234EFGH5678"
    assert normalize_referral_code("short") is None
    assert normalize_referral_code("ABCD-1234EFGH5678") is None
    assert normalize_referral_code("A" * 65) is None
    assert normalize_referral_code("💥" * 16) is None


def test_default_policy_is_honestly_unavailable():
    # Test settings are intentionally not mutated: source defaults are zero days
    # and disabled, so the API must not imply a monetary or time reward.
    policy = ReferralService.policy()
    assert policy["enabled"] is False
    assert policy["reward_days"] == 0
    assert policy["scope"] == "user_referral"


async def _user(db: AsyncSession, *, age_hours: int = 0, plan: str = "free") -> User:
    user = User(
        email=f"test_referral_{uuid4().hex}@example.com",
        name="Referral Test",
        email_verified=True,
        subscription_plan=plan,
        subscription_status="active",
        created_at=datetime.now(timezone.utc) - timedelta(hours=age_hours),
    )
    db.add(user)
    await db.flush()
    return user


def _enable_policy(monkeypatch: pytest.MonkeyPatch, *, days: int = 7) -> None:
    monkeypatch.setattr(settings, "REFERRAL_PROGRAM_ENABLED", True)
    monkeypatch.setattr(settings, "REFERRAL_REWARD_DAYS", days)
    monkeypatch.setattr(settings, "REFERRAL_ATTRIBUTION_WINDOW_HOURS", 24)


@pytest.mark.asyncio
async def test_claim_rejects_old_accounts_and_multi_hop_chains(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_policy(monkeypatch)
    first = await _user(db_session)
    middle = await _user(db_session)
    downstream = await _user(db_session)
    old_account = await _user(db_session, age_hours=25)
    first_code = uuid4().hex.upper()
    middle_code = uuid4().hex.upper()
    first_identity = ReferralIdentity(
        user_id=first.id,
        code=first_code,
        code_digest=hashlib.sha256(first_code.encode("ascii")).hexdigest(),
    )
    middle_identity = ReferralIdentity(
        user_id=middle.id,
        code=middle_code,
        code_digest=hashlib.sha256(middle_code.encode("ascii")).hexdigest(),
    )
    db_session.add_all([first_identity, middle_identity])
    await db_session.flush()
    db_session.add(
        ReferralAttribution(
            referral_identity_id=middle_identity.id,
            referrer_user_id=middle.id,
            referred_user_id=downstream.id,
            status="captured",
        )
    )
    await db_session.commit()

    old_result = await ReferralService.claim(db_session, old_account.id, first_identity.code)
    assert old_result["accepted"] is False
    assert "window" in old_result["message"]

    chain_result = await ReferralService.claim(db_session, middle.id, first_identity.code)
    assert chain_result["accepted"] is False
    assert chain_result["status"] == "rejected"


@pytest.mark.asyncio
async def test_status_reports_only_the_callers_referrals_and_rewards(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_policy(monkeypatch)
    referrer = await _user(db_session, plan="pro")
    referred = await _user(db_session)
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    db_session.add(identity)
    await db_session.flush()
    subscription = Subscription(user_id=referred.id, plan_id="pro", status="active")
    db_session.add(subscription)
    await db_session.flush()
    payment = Payment(
        user_id=referred.id,
        subscription_id=subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
    )
    db_session.add(payment)
    await db_session.flush()
    attribution = ReferralAttribution(
        referral_identity_id=identity.id,
        referrer_user_id=referrer.id,
        referred_user_id=referred.id,
        status="qualified",
        qualifying_payment_id=payment.id,
        qualified_at=datetime.now(timezone.utc),
    )
    db_session.add(attribution)
    await db_session.flush()
    db_session.add(
        ReferralReward(
            attribution_id=attribution.id,
            referrer_user_id=referrer.id,
            qualifying_payment_id=payment.id,
            reward_type="subscription_extension_days",
            reward_value=7,
            status="issued",
            issued_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()
    referrer_id = referrer.id
    referred_id = referred.id

    owner_status = await ReferralService.status(db_session, referrer_id)
    assert owner_status["referral_summary"]["qualified"] == 1
    assert owner_status["reward_summary"]["issued"] == 1
    assert owner_status["reward_summary"]["issued_extension_days"] == 7
    await db_session.rollback()
    referred_status = await ReferralService.status(db_session, referred_id)
    assert referred_status["your_attribution"]["status"] == "qualified"
    assert referred_status["reward_summary"]["issued"] == 0


@pytest.mark.asyncio
async def test_pending_reward_is_issued_when_referrer_later_has_a_paid_term(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_policy(monkeypatch, days=5)
    referrer = await _user(db_session, plan="pro")
    referred = await _user(db_session)
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    db_session.add(identity)
    await db_session.flush()

    earned_subscription = Subscription(user_id=referred.id, plan_id="pro", status="active")
    db_session.add(earned_subscription)
    await db_session.flush()
    earned_payment = Payment(
        user_id=referred.id,
        subscription_id=earned_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
    )
    db_session.add(earned_payment)
    await db_session.flush()
    attribution = ReferralAttribution(
        referral_identity_id=identity.id,
        referrer_user_id=referrer.id,
        referred_user_id=referred.id,
        status="qualified",
        qualifying_payment_id=earned_payment.id,
    )
    db_session.add(attribution)
    await db_session.flush()
    reward = ReferralReward(
        attribution_id=attribution.id,
        referrer_user_id=referrer.id,
        qualifying_payment_id=earned_payment.id,
        reward_type="subscription_extension_days",
        reward_value=5,
        status="pending",
    )
    db_session.add(reward)

    period_end = datetime.now(timezone.utc) + timedelta(days=30)
    paid_subscription = Subscription(
        user_id=referrer.id,
        plan_id="pro",
        status="active",
        current_period_end=period_end,
    )
    db_session.add(paid_subscription)
    await db_session.flush()
    activating_payment = Payment(
        user_id=referrer.id,
        subscription_id=paid_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
    )
    db_session.add(activating_payment)
    await db_session.commit()

    result = await ReferralService.qualify_paid_payment(db_session, activating_payment.id)
    assert result["pending_rewards_issued"] == 1
    await db_session.refresh(reward)
    await db_session.refresh(paid_subscription)
    assert reward.status == "issued"
    assert paid_subscription.current_period_end >= period_end + timedelta(days=5)


@pytest.mark.asyncio
async def test_reward_stays_pending_for_an_unpaid_checkout(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """An ``authenticated`` Razorpay row is only a checkout placeholder."""
    _enable_policy(monkeypatch, days=5)
    referrer = await _user(db_session)
    referred = await _user(db_session)
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    checkout_end = datetime.now(timezone.utc) + timedelta(days=30)
    checkout = Subscription(
        user_id=referrer.id,
        plan_id="pro",
        status="authenticated",
        current_period_end=checkout_end,
    )
    earned_subscription = Subscription(user_id=referred.id, plan_id="pro", status="active")
    db_session.add_all([identity, checkout, earned_subscription])
    await db_session.flush()
    captured_at = datetime.now(timezone.utc)
    payment = Payment(
        user_id=referred.id,
        subscription_id=earned_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
        created_at=captured_at + timedelta(seconds=1),
    )
    db_session.add(payment)
    await db_session.flush()
    attribution = ReferralAttribution(
        referral_identity_id=identity.id,
        referrer_user_id=referrer.id,
        referred_user_id=referred.id,
        status="captured",
        captured_at=captured_at,
    )
    db_session.add(attribution)
    await db_session.commit()

    result = await ReferralService.qualify_paid_payment(db_session, payment.id)
    await db_session.refresh(checkout)
    reward = await db_session.scalar(
        select(ReferralReward).where(ReferralReward.qualifying_payment_id == payment.id)
    )
    assert result["status"] == "pending"
    assert reward is not None and reward.status == "pending"
    assert checkout.current_period_end == checkout_end


@pytest.mark.asyncio
async def test_payment_before_attribution_cannot_qualify_referral(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_policy(monkeypatch)
    referrer = await _user(db_session)
    referred = await _user(db_session)
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    earned_subscription = Subscription(user_id=referred.id, plan_id="pro", status="active")
    db_session.add_all([identity, earned_subscription])
    await db_session.flush()
    payment_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    payment = Payment(
        user_id=referred.id,
        subscription_id=earned_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
        created_at=payment_time,
    )
    db_session.add(payment)
    await db_session.flush()
    attribution = ReferralAttribution(
        referral_identity_id=identity.id,
        referrer_user_id=referrer.id,
        referred_user_id=referred.id,
        status="captured",
        captured_at=payment_time + timedelta(minutes=1),
    )
    db_session.add(attribution)
    renewal = Payment(
        user_id=referred.id,
        subscription_id=earned_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
        created_at=payment_time + timedelta(minutes=2),
    )
    db_session.add(renewal)
    await db_session.commit()

    result = await ReferralService.qualify_paid_payment(db_session, renewal.id)
    await db_session.refresh(attribution)
    assert result == {"status": "ignored", "reason": "prior_payment_before_attribution"}
    assert attribution.status == "captured"


@pytest.mark.asyncio
async def test_payment_subscription_must_belong_to_payer(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_policy(monkeypatch)
    referrer = await _user(db_session)
    referred = await _user(db_session)
    unrelated = await _user(db_session, plan="pro")
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    unrelated_subscription = Subscription(user_id=unrelated.id, plan_id="pro", status="active")
    db_session.add_all([identity, unrelated_subscription])
    await db_session.flush()
    captured_at = datetime.now(timezone.utc)
    payment = Payment(
        user_id=referred.id,
        subscription_id=unrelated_subscription.id,
        razorpay_payment_id=f"pay_{uuid4().hex}",
        amount=100,
        currency="INR",
        status="paid",
        created_at=captured_at + timedelta(seconds=1),
    )
    db_session.add(payment)
    await db_session.flush()
    attribution = ReferralAttribution(
        referral_identity_id=identity.id,
        referrer_user_id=referrer.id,
        referred_user_id=referred.id,
        status="captured",
        captured_at=captured_at,
    )
    db_session.add(attribution)
    await db_session.commit()

    result = await ReferralService.qualify_paid_payment(db_session, payment.id)
    assert result == {"status": "ignored", "reason": "payment_subscription_missing"}


@pytest.mark.asyncio
async def test_reversing_an_earlier_reward_preserves_later_reward(
    db_session: AsyncSession,
):
    """A refund must claw back its own extension, not the latest term."""
    referrer = await _user(db_session, plan="pro")
    referred_one = await _user(db_session)
    referred_two = await _user(db_session)
    referrer_subscription = Subscription(
        user_id=referrer.id,
        plan_id="pro",
        status="active",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(referrer_subscription)
    await db_session.flush()
    base = referrer_subscription.current_period_end
    code = uuid4().hex.upper()
    identity = ReferralIdentity(
        user_id=referrer.id,
        code=code,
        code_digest=hashlib.sha256(code.encode("ascii")).hexdigest(),
    )
    db_session.add(identity)
    await db_session.flush()

    payments = []
    rewards = []
    cursor = base
    for referred in (referred_one, referred_two):
        earned_subscription = Subscription(user_id=referred.id, plan_id="pro", status="active")
        db_session.add(earned_subscription)
        await db_session.flush()
        payment = Payment(
            user_id=referred.id,
            subscription_id=earned_subscription.id,
            razorpay_payment_id=f"pay_{uuid4().hex}",
            amount=100,
            currency="INR",
            status="paid",
        )
        db_session.add(payment)
        await db_session.flush()
        attribution = ReferralAttribution(
            referral_identity_id=identity.id,
            referrer_user_id=referrer.id,
            referred_user_id=referred.id,
            status="qualified",
            qualifying_payment_id=payment.id,
            qualified_at=datetime.now(timezone.utc),
        )
        db_session.add(attribution)
        await db_session.flush()
        after = cursor + timedelta(days=7)
        reward = ReferralReward(
            attribution_id=attribution.id,
            referrer_user_id=referrer.id,
            qualifying_payment_id=payment.id,
            subscription_id=referrer_subscription.id,
            reward_type="subscription_extension_days",
            reward_value=7,
            status="issued",
            period_end_before=cursor,
            period_end_after=after,
            issued_at=datetime.now(timezone.utc),
        )
        db_session.add(reward)
        payments.append(payment)
        rewards.append(reward)
        cursor = after
    referrer_subscription.current_period_end = cursor
    payment_ids = [payment.id for payment in payments]
    await db_session.commit()

    await ReferralService.reverse_paid_payment(db_session, payment_ids[0])
    await db_session.refresh(referrer_subscription)
    await db_session.refresh(rewards[0])
    await db_session.refresh(rewards[1])
    assert referrer_subscription.current_period_end == base + timedelta(days=7)
    assert rewards[0].status == "reversed"
    assert rewards[1].status == "issued"

    await db_session.rollback()
    await ReferralService.reverse_paid_payment(db_session, payment_ids[1])
    await db_session.refresh(referrer_subscription)
    assert referrer_subscription.current_period_end == base

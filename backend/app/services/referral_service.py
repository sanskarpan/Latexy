"""Server-authoritative user referral attribution and reward accounting (B59).

This is a user referral programme, not an affiliate network. Referral links are
random bearer identifiers, attribution is first-touch and one-time, and reward
issuance can only be called after a locally verified paid ``Payment`` row.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import resolve_plan_family, settings
from ..database import models as db_models

ReferralIdentity = db_models.ReferralIdentity
ReferralAttribution = db_models.ReferralAttribution
ReferralReward = db_models.ReferralReward
Payment = db_models.Payment
Subscription = db_models.Subscription
User = db_models.User

_CODE_RE = re.compile(r"^[A-Z0-9]{16,64}$")
_MAX_CODE_BYTES = 128


def normalize_referral_code(raw: str) -> Optional[str]:
    """Normalize a referral token without accepting whitespace or delimiters."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_CODE_BYTES:
        return None
    value = raw.strip().upper()
    return value if _CODE_RE.fullmatch(value) else None


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


class ReferralService:
    """Referral operations shared by HTTP routes and payment webhooks."""

    @staticmethod
    def policy() -> dict[str, Any]:
        days = int(settings.REFERRAL_REWARD_DAYS or 0)
        enabled = bool(settings.REFERRAL_PROGRAM_ENABLED and days > 0)
        return {
            "enabled": enabled,
            "reward_type": "subscription_extension_days",
            "reward_days": days if enabled else 0,
            "qualifying_plan_families": sorted(
                {resolve_plan_family(p) for p in settings.REFERRAL_QUALIFYING_PLAN_FAMILIES}
            ),
            "max_attributions_per_referrer": int(settings.REFERRAL_MAX_ATTRIBUTIONS_PER_REFERRER),
            "attribution_window_hours": int(settings.REFERRAL_ATTRIBUTION_WINDOW_HOURS),
            "scope": "user_referral",
        }

    @classmethod
    async def _ensure_identity(cls, db: AsyncSession, user_id: str) -> ReferralIdentity:
        existing = await db.scalar(select(ReferralIdentity).where(ReferralIdentity.user_id == user_id))
        if existing:
            return existing
        # 128 bits of random entropy; this is intentionally unrelated to user
        # identity and remains bounded for URLs and logs.
        code = secrets.token_hex(16).upper()
        identity = ReferralIdentity(user_id=user_id, code=code, code_digest=_digest(code))
        db.add(identity)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            winner = await db.scalar(select(ReferralIdentity).where(ReferralIdentity.user_id == user_id))
            if winner is None:  # pragma: no cover - defensive transient race
                raise
            return winner
        return identity

    @classmethod
    async def status(cls, db: AsyncSession, user_id: str) -> dict[str, Any]:
        policy = cls.policy()
        if not policy["enabled"]:
            return {
                "available": False,
                "scope": policy["scope"],
                "message": "User referrals are not currently available.",
                "share_code": None,
                "your_attribution": None,
                "referral_summary": {"total": 0, "captured": 0, "qualified": 0, "reversed": 0},
                "reward_summary": {
                    "issued": 0,
                    "pending": 0,
                    "reversed": 0,
                    "issued_extension_days": 0,
                },
                "policy_configured": False,
            }

        identity = await cls._ensure_identity(db, user_id)
        await db.commit()
        own_attribution = await db.scalar(
            select(ReferralAttribution)
            .where(ReferralAttribution.referred_user_id == user_id)
            .order_by(ReferralAttribution.captured_at.desc())
        )
        referral_statuses = list(
            await db.scalars(
                select(ReferralAttribution.status).where(
                    ReferralAttribution.referrer_user_id == user_id
                )
            )
        )
        reward_rows = (
            await db.execute(
                select(ReferralReward.status, ReferralReward.reward_value).where(
                    ReferralReward.referrer_user_id == user_id
                )
            )
        ).all()
        return {
            "available": True,
            "scope": policy["scope"],
            "message": "Share this link with someone you know. A reward is recorded only after their first qualifying paid purchase.",
            "share_code": identity.code,
            "your_attribution": {
                "status": own_attribution.status,
                "captured_at": own_attribution.captured_at.isoformat(),
            }
            if own_attribution
            else None,
            "referral_summary": {
                "total": len(referral_statuses),
                "captured": referral_statuses.count("captured"),
                "qualified": referral_statuses.count("qualified"),
                "reversed": referral_statuses.count("reversed"),
            },
            "reward_summary": {
                "issued": sum(1 for status, _value in reward_rows if status == "issued"),
                "pending": sum(1 for status, _value in reward_rows if status == "pending"),
                "reversed": sum(1 for status, _value in reward_rows if status == "reversed"),
                "issued_extension_days": sum(
                    int(value) for status, value in reward_rows if status == "issued"
                ),
            },
            "policy_configured": True,
        }

    @classmethod
    async def claim(cls, db: AsyncSession, user_id: str, raw_code: str) -> dict[str, Any]:
        policy = cls.policy()
        if not policy["enabled"]:
            return {"accepted": False, "status": "unavailable", "message": "User referrals are not currently available."}
        code = normalize_referral_code(raw_code)
        if code is None:
            return {"accepted": False, "status": "rejected", "message": "That referral link is not valid."}

        existing = await db.scalar(
            select(ReferralAttribution).where(ReferralAttribution.referred_user_id == user_id)
        )
        if existing:
            return {"accepted": existing.status == "captured", "status": existing.status, "message": "Referral attribution is already recorded."}

        referred_created_at = await db.scalar(select(User.created_at).where(User.id == user_id))
        if referred_created_at is None:
            return {"accepted": False, "status": "rejected", "message": "That referral link is not valid."}
        now = datetime.now(timezone.utc)
        if referred_created_at.tzinfo is None:
            referred_created_at = referred_created_at.replace(tzinfo=timezone.utc)
        if now - referred_created_at > timedelta(hours=policy["attribution_window_hours"]):
            return {
                "accepted": False,
                "status": "rejected",
                "message": "This account is outside the referral attribution window.",
            }

        # Lock the referrer's identity while checking the lifetime cap. This
        # serializes concurrent claims for one code so the cap cannot be
        # exceeded by a count-then-insert race.
        identity = await db.scalar(
            select(ReferralIdentity)
            .where(ReferralIdentity.code_digest == _digest(code))
            .with_for_update()
        )
        if identity is None or identity.user_id == user_id:
            return {"accepted": False, "status": "rejected", "message": "That referral link is not valid."}

        # Keep the graph one level deep. A referred user cannot become a
        # referrer, which makes A -> B -> A cycles impossible and avoids
        # ambiguous multi-hop reward chains.
        already_referred = await db.scalar(
            select(ReferralAttribution.id).where(ReferralAttribution.referred_user_id == identity.user_id)
        )
        if already_referred is not None:
            return {"accepted": False, "status": "rejected", "message": "That referral link is not eligible."}
        already_referrer = await db.scalar(
            select(ReferralAttribution.id).where(
                ReferralAttribution.referrer_user_id == user_id,
                ReferralAttribution.status != "reversed",
            )
        )
        if already_referrer is not None:
            return {"accepted": False, "status": "rejected", "message": "That referral link is not eligible."}
        referrer_count = await db.scalar(
            select(func.count(ReferralAttribution.id)).where(
                ReferralAttribution.referrer_user_id == identity.user_id,
                ReferralAttribution.status != "reversed",
            )
        )
        if int(referrer_count or 0) >= policy["max_attributions_per_referrer"]:
            return {"accepted": False, "status": "rejected", "message": "This referral link has reached its account limit."}

        attribution = ReferralAttribution(
            referral_identity_id=identity.id,
            referrer_user_id=identity.user_id,
            referred_user_id=user_id,
            status="captured",
        )
        db.add(attribution)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = await db.scalar(
                select(ReferralAttribution).where(ReferralAttribution.referred_user_id == user_id)
            )
            return {
                "accepted": bool(existing and existing.status == "captured"),
                "status": existing.status if existing else "rejected",
                "message": "Referral attribution is already recorded.",
            }
        return {"accepted": True, "status": "captured", "message": "Referral attribution recorded."}

    @classmethod
    async def qualify_paid_payment(cls, db: AsyncSession, payment_id: str) -> dict[str, Any]:
        """Qualify exactly one first paid event and issue a configured reward.

        Callers must invoke this only after their payment handler has inserted a
        server-verified ``payments.status = paid`` row.  The row lock and unique
        attribution/payment constraints make webhook retries/concurrent workers
        harmless.
        """
        policy = cls.policy()
        async with db.begin():
            payment = await db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
            if payment is None or payment.status != "paid":
                return {"status": "ignored", "reason": "payment_not_qualifying"}
            plan_id = None
            if payment.subscription_id:
                plan_id = await db.scalar(
                    select(Subscription.plan_id).where(
                        Subscription.id == payment.subscription_id,
                        Subscription.user_id == payment.user_id,
                    )
                )
            plan_family = resolve_plan_family(plan_id)
            if not payment.subscription_id or plan_id is None or plan_family == "free":
                return {"status": "ignored", "reason": "payment_subscription_missing"}
            if plan_family not in set(policy["qualifying_plan_families"]):
                return {"status": "ignored", "reason": "plan_not_qualifying"}

            # A payment may unlock rewards this payer earned as a referrer,
            # but only after its own paid subscription binding has been
            # authenticated above. Otherwise a corrupt/mismatched Payment row
            # could issue pending rewards despite being ineligible itself.
            pending_issued = await cls._issue_pending_rewards(
                db,
                referrer_user_id=payment.user_id,
                now=datetime.now(timezone.utc),
            )
            attribution = await db.scalar(
                select(ReferralAttribution)
                .where(ReferralAttribution.referred_user_id == payment.user_id)
                .with_for_update()
            )
            if attribution is None or attribution.status in {"reversed", "qualified"}:
                return {
                    "status": "pending_rewards_issued" if pending_issued else "ignored",
                    "pending_rewards_issued": pending_issued,
                    "reason": "already_processed_or_unattributed",
                }

            # Attribution is first-touch and only earns credit for a purchase
            # made after that touch.  Without this guard, a user could buy a
            # paid plan, then claim a link later in the account-age window,
            # and have the already-completed purchase retroactively qualify.
            payment_created_at = payment.created_at
            captured_at = attribution.captured_at
            if payment_created_at and captured_at:
                if payment_created_at.tzinfo is None:
                    payment_created_at = payment_created_at.replace(tzinfo=timezone.utc)
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
                if payment_created_at < captured_at:
                    return {"status": "ignored", "reason": "payment_before_attribution"}
                prior_paid_payment = await db.scalar(
                    select(Payment.id)
                    .where(
                        Payment.user_id == payment.user_id,
                        Payment.status.in_(["paid", "partially_refunded", "refunded"]),
                        Payment.created_at < captured_at,
                    )
                    .limit(1)
                )
                if prior_paid_payment is not None:
                    return {"status": "ignored", "reason": "prior_payment_before_attribution"}

            now = datetime.now(timezone.utc)
            attribution.status = "qualified"
            attribution.qualifying_payment_id = payment.id
            attribution.qualified_at = now
            reward_status = "unavailable"
            period_before = period_after = None
            if policy["enabled"]:
                reward_status = "pending"
                referrer_sub = await db.scalar(
                    select(Subscription)
                    .where(
                        Subscription.user_id == attribution.referrer_user_id,
                        # ``authenticated`` is an unpaid Razorpay checkout and
                        # its placeholder period is overwritten on activation.
                        # A reward must attach only to a paid term. A scheduled
                        # cancellation remains entitled through period end.
                        Subscription.status.in_(["active", "cancel_scheduled"]),
                    )
                    .order_by(Subscription.updated_at.desc())
                    .with_for_update()
                )
                if referrer_sub:
                    if referrer_sub.current_period_end:
                        period_before = referrer_sub.current_period_end
                        period_after = max(period_before, now) + timedelta(days=policy["reward_days"])
                        referrer_sub.current_period_end = period_after
                        reward_status = "issued"
                    else:
                        # Lifetime ownership has no expiring term to extend;
                        # keeping this as pending would create an unfulfillable
                        # balance because lifetime checkout cannot later acquire
                        # a recurring period on the same account.
                        reward_status = "unavailable"
            db.add(
                ReferralReward(
                    attribution_id=attribution.id,
                    referrer_user_id=attribution.referrer_user_id,
                    qualifying_payment_id=payment.id,
                    reward_type=policy["reward_type"],
                    reward_value=policy["reward_days"],
                    subscription_id=referrer_sub.id if reward_status == "issued" and referrer_sub else None,
                    status=reward_status,
                    period_end_before=period_before,
                    period_end_after=period_after,
                    issued_at=now if reward_status == "issued" else None,
                )
            )
        return {
            "status": "issued" if reward_status == "issued" else reward_status,
            "pending_rewards_issued": pending_issued,
        }

    @classmethod
    async def _issue_pending_rewards(
        cls,
        db: AsyncSession,
        *,
        referrer_user_id: str,
        now: datetime,
    ) -> int:
        """Apply previously earned extensions once the referrer has a paid term.

        The caller owns the surrounding transaction. Ledger values are used as
        recorded, so disabling or changing the current programme policy cannot
        erase an already-earned pending reward.
        """

        subscription = await db.scalar(
            select(Subscription)
            .where(
                Subscription.user_id == referrer_user_id,
                Subscription.status.in_(["active", "cancel_scheduled"]),
                Subscription.current_period_end.is_not(None),
            )
            .order_by(Subscription.updated_at.desc())
            .with_for_update()
        )
        if subscription is None or subscription.current_period_end is None:
            return 0
        rewards = list(
            await db.scalars(
                select(ReferralReward)
                .where(
                    ReferralReward.referrer_user_id == referrer_user_id,
                    ReferralReward.status == "pending",
                )
                .order_by(ReferralReward.created_at.asc())
                .with_for_update()
            )
        )
        cursor = max(subscription.current_period_end, now)
        for reward in rewards:
            reward.period_end_before = cursor
            cursor += timedelta(days=reward.reward_value)
            reward.period_end_after = cursor
            reward.subscription_id = subscription.id
            reward.status = "issued"
            reward.issued_at = now
        if rewards:
            subscription.current_period_end = cursor
        return len(rewards)

    @classmethod
    async def reverse_paid_payment(cls, db: AsyncSession, payment_id: str) -> dict[str, Any]:
        """Reverse attribution/reward state after a provider refund."""
        async with db.begin():
            attribution = await db.scalar(
                select(ReferralAttribution).where(ReferralAttribution.qualifying_payment_id == payment_id).with_for_update()
            )
            if attribution is None:
                return {"status": "ignored"}
            reward = await db.scalar(
                select(ReferralReward).where(ReferralReward.attribution_id == attribution.id).with_for_update()
            )
            if reward:
                if reward.status == "issued":
                    referrer_sub = None
                    if reward.subscription_id:
                        referrer_sub = await db.scalar(
                            select(Subscription)
                            .where(
                                Subscription.id == reward.subscription_id,
                                Subscription.user_id == attribution.referrer_user_id,
                            )
                            .with_for_update()
                        )
                    # Legacy rewards have no subscription link.  Only use an
                    # exact period match in that case; never pick an arbitrary
                    # latest subscription and mutate another billing term.
                    if referrer_sub is None and reward.subscription_id is None and reward.period_end_after:
                        # Rewards written before subscription binding was added
                        # cannot be safely clawed back when multiple terms have
                        # the same end. Only mutate a uniquely identifiable
                        # legacy term; always retain the ledger reversal.
                        legacy_matches = list(
                            await db.scalars(
                                select(Subscription)
                                .where(
                                    Subscription.user_id == attribution.referrer_user_id,
                                    Subscription.current_period_end == reward.period_end_after,
                                )
                                .with_for_update()
                            )
                        )
                        if len(legacy_matches) == 1:
                            referrer_sub = legacy_matches[0]
                    # Subtract only this ledger entry's delta from the exact
                    # term that received it.  A later reward or renewal remains
                    # intact; inclusive comparison also permits reversing two
                    # adjacent rewards in either delivery order.
                    if (
                        referrer_sub
                        and reward.period_end_before
                        and reward.period_end_after
                        and referrer_sub.current_period_end
                        and referrer_sub.current_period_end >= reward.period_end_before
                    ):
                        delta = reward.period_end_after - reward.period_end_before
                        if delta > timedelta(0):
                            referrer_sub.current_period_end -= delta
                reward.status = "reversed"
                reward.reversed_at = datetime.now(timezone.utc)
            attribution.status = "reversed"
            attribution.reversed_at = datetime.now(timezone.utc)
        return {"status": "reversed"}


referral_service = ReferralService()

"""
GROUP G — billing correctness tests.

Covers:
  G1. /subscription/current stays 200 when a user has several subscription rows
  G2. A second live Razorpay subscription can never be created
  G3. cancel_subscription reports failure when Razorpay rejects the cancel
  G4. Webhook replay protection works without a body-level event id
  G5. A coupon discount that cannot reach Razorpay is refused, not consumed
  G6. Team seats are revoked when the owner's team subscription ends
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import razorpay
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.payment_service import PaymentService

_WEBHOOK_SECRET = "test_razorpay_webhook_secret_32chars"

# subscriptions.razorpay_subscription_id is globally unique, so ids must not
# collide with rows left behind by a previous run of this module.
_RUN = uuid.uuid4().hex[:8]


def _rz(name: str) -> str:
    return f"sub_{name}_{_RUN}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _create_user(
    db: AsyncSession,
    plan: str = "free",
    status: str = "active",
    subscription_id: str | None = None,
) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"billing_{user_id.replace('-', '')}@example.com"
    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, subscription_plan, "
            "subscription_status, trial_used, subscription_id) "
            "VALUES (:id, :email, 'Billing Group G', true, :plan, :status, false, :sub_id)"
        ),
        {"id": user_id, "email": email, "plan": plan, "status": status, "sub_id": subscription_id},
    )
    await db.commit()
    return user_id, email


async def _add_subscription(
    db: AsyncSession,
    user_id: str,
    plan_id: str,
    status: str,
    razorpay_subscription_id: str | None = None,
    age_days: int = 0,
    period_end_days: int | None = None,
) -> str:
    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    created_at = now - timedelta(days=age_days)
    period_end = now + timedelta(days=period_end_days) if period_end_days is not None else None
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, razorpay_subscription_id, plan_id, "
            "status, current_period_start, current_period_end, created_at) "
            "VALUES (:id, :uid, :rz, :plan, :status, :start, :pend, :created)"
        ),
        {
            "id": row_id,
            "uid": user_id,
            "rz": razorpay_subscription_id,
            "plan": plan_id,
            "status": status,
            "start": created_at,
            "pend": period_end,
            "created": created_at,
        },
    )
    await db.commit()
    return row_id


async def _add_team_seat(
    db: AsyncSession,
    owner_user_id: str,
    member_user_id: str | None,
    member_email: str,
    status: str = "active",
) -> str:
    seat_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO team_seats (id, owner_user_id, member_email, member_user_id, status) "
            "VALUES (:id, :owner, :email, :member, :status)"
        ),
        {
            "id": seat_id,
            "owner": owner_user_id,
            "email": member_email,
            "member": member_user_id,
            "status": status,
        },
    )
    await db.commit()
    return seat_id


def _make_signature(payload: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class _FakeRedis:
    """Minimal redis stub with real SET NX semantics."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1

    async def get(self, key):
        return self.store.get(key)


@pytest.fixture()
def svc():
    """PaymentService with a mocked Razorpay client that returns real dicts."""
    service = PaymentService.__new__(PaymentService)
    service.client = MagicMock()
    service.client.plan.create.return_value = {"id": "plan_test"}
    service.client.customer.create.return_value = {"id": "cust_test"}
    service.client.subscription.create.return_value = {
        "id": f"sub_new_{uuid.uuid4().hex[:8]}",
        "short_url": "https://rzp.io/i/newlink",
    }
    service.client.subscription.fetch.return_value = {
        "id": "sub_fetched",
        "short_url": "https://rzp.io/i/existing",
        "status": "created",
    }
    service._base_status = {
        "available": True,
        "feature_enabled": True,
        "mode": "enabled",
        "reason": None,
        "message": "Billing is available.",
    }
    return service


# ─────────────────────────────────────────────────────────────────────────────
# G1 — current subscription with several rows
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCurrentSubscriptionSelection:
    async def test_multiple_rows_returns_the_provider_pointed_row(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """Two+ subscription rows must not blow up; the live one is returned."""
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("live_g1")
        )
        await _add_subscription(db_session, user_id, "free", "cancelled", age_days=60)
        await _add_subscription(
            db_session, user_id, "pro", "created", _rz("abandoned_g1"), age_days=2
        )
        await _add_subscription(
            db_session, user_id, "pro", "active", _rz("live_g1"), age_days=1, period_end_days=30
        )

        result = await svc.get_user_subscription(db_session, user_id)

        assert result is not None, "multiple rows must not produce a 404"
        assert result["plan_id"] == "pro"
        assert result["subscription_id"] == _rz("live_g1")
        assert result["current_period_end"] is not None

    async def test_without_provider_pointer_prefers_active_row(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """With no user.subscription_id, the most authoritative status wins."""
        user_id, _ = await _create_user(db_session, plan="pro")
        await _add_subscription(
            db_session, user_id, "pro", "created", _rz("pending_g1b"), age_days=0
        )
        await _add_subscription(
            db_session, user_id, "pro", "active", _rz("active_g1b"), age_days=5, period_end_days=10
        )

        picked = await svc._get_current_subscription(db_session, user_id)

        assert picked is not None
        assert picked.razorpay_subscription_id == _rz("active_g1b")


# ─────────────────────────────────────────────────────────────────────────────
# G2 — no second live subscription
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSingleLiveSubscription:
    async def test_active_subscription_blocks_plan_switch(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, email = await _create_user(
            db_session, plan="basic", subscription_id=_rz("active_g2")
        )
        await _add_subscription(db_session, user_id, "basic", "active", _rz("active_g2"))

        fake_redis = _FakeRedis()
        with patch(
            "app.services.payment_service.get_redis_cache_client",
            new=AsyncMock(return_value=fake_redis),
        ):
            result = await svc.create_subscription(
                db_session, user_id, "pro", email, "Group G", billing_period="monthly"
            )

        assert result["success"] is False
        assert "Cancel it before switching" in result["error"]
        svc.client.subscription.create.assert_not_called()
        # the lock must be released so the user can retry after cancelling
        assert fake_redis.store == {}

    async def test_duplicate_click_reuses_pending_checkout(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, email = await _create_user(
            db_session, plan="free", subscription_id=_rz("dupclick")
        )
        await _add_subscription(db_session, user_id, "pro", "created", _rz("dupclick"))

        with patch(
            "app.services.payment_service.get_redis_cache_client",
            new=AsyncMock(return_value=_FakeRedis()),
        ):
            result = await svc.create_subscription(
                db_session, user_id, "pro", email, "Group G", billing_period="monthly"
            )

        assert result["success"] is True
        assert result["subscription_id"] == _rz("dupclick")
        assert result["short_url"] == "https://rzp.io/i/existing"
        svc.client.subscription.create.assert_not_called()

    async def test_pending_checkout_for_other_plan_is_cancelled_first(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, email = await _create_user(
            db_session, plan="free", subscription_id=_rz("switch")
        )
        await _add_subscription(db_session, user_id, "basic", "created", _rz("switch"))

        with patch(
            "app.services.payment_service.get_redis_cache_client",
            new=AsyncMock(return_value=_FakeRedis()),
        ):
            result = await svc.create_subscription(
                db_session, user_id, "pro", email, "Group G", billing_period="monthly"
            )

        assert result["success"] is True, result
        svc.client.subscription.cancel.assert_called_once_with(
            _rz("switch"), {"cancel_at_cycle_end": 0}
        )
        svc.client.subscription.create.assert_called_once()

        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("switch")},
            )
        ).scalar_one()
        assert status == "cancelled"

    async def test_concurrent_checkout_is_locked_out(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, email = await _create_user(db_session, plan="free")
        fake_redis = _FakeRedis()
        await fake_redis.set(f"latexy:subscription:checkout:{user_id}", "1", nx=True, ex=120)

        with patch(
            "app.services.payment_service.get_redis_cache_client",
            new=AsyncMock(return_value=fake_redis),
        ):
            result = await svc.create_subscription(
                db_session, user_id, "pro", email, "Group G", billing_period="monthly"
            )

        assert result["success"] is False
        assert "already in progress" in result["error"]
        svc.client.subscription.create.assert_not_called()

    async def test_free_downgrade_refused_while_paid_subscription_lives(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """Switching to free must not orphan the paying Razorpay subscription."""
        user_id, email = await _create_user(
            db_session, plan="pro", subscription_id=_rz("active_g2e")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("active_g2e"))

        result = await svc.create_subscription(
            db_session, user_id, "free", email, "Group G", billing_period="monthly"
        )

        assert result["success"] is False
        assert "Cancel your paid subscription" in result["error"]

        row = (
            await db_session.execute(
                text("SELECT subscription_plan, subscription_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
        assert row == ("pro", _rz("active_g2e"))

    async def test_free_downgrade_retires_abandoned_checkout(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """An unpaid 'created' row bills nobody: close it, don't block free."""
        user_id, email = await _create_user(
            db_session, plan="free", status="inactive", subscription_id=_rz("abandoned_g2f")
        )
        await _add_subscription(db_session, user_id, "pro", "created", _rz("abandoned_g2f"))

        result = await svc.create_subscription(
            db_session, user_id, "free", email, "Group G", billing_period="monthly"
        )

        assert result["success"] is True, result
        svc.client.subscription.cancel.assert_called_once_with(
            _rz("abandoned_g2f"), {"cancel_at_cycle_end": 0}
        )

        status = (
            await db_session.execute(
                text("SELECT status FROM subscriptions WHERE razorpay_subscription_id = :rz"),
                {"rz": _rz("abandoned_g2f")},
            )
        ).scalar_one()
        assert status == "cancelled"

        row = (
            await db_session.execute(
                text("SELECT subscription_plan, subscription_id FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
        assert row == ("free", None)


# ─────────────────────────────────────────────────────────────────────────────
# G3 — cancellation honesty
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCancellationHonesty:
    async def test_provider_failure_reports_error_and_keeps_state(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("cancel_fail")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("cancel_fail"))
        svc.client.subscription.cancel.side_effect = RuntimeError("razorpay 502")

        result = await svc.cancel_subscription(db_session, user_id)

        assert result["success"] is False
        assert "could not cancel" in result["error"].lower()

        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions "
                    "WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("cancel_fail")},
            )
        ).scalar_one()
        assert status == "active", "local state must still mirror Razorpay"

        user_status = (
            await db_session.execute(
                text("SELECT subscription_status FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one()
        assert user_status == "active"

    async def test_provider_success_cancels_local_records(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("cancel_ok")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("cancel_ok"))

        result = await svc.cancel_subscription(db_session, user_id)

        assert result["success"] is True
        svc.client.subscription.cancel.assert_called_once_with(
            _rz("cancel_ok"), {"cancel_at_cycle_end": 1}
        )
        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions "
                    "WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("cancel_ok")},
            )
        ).scalar_one()
        assert status == "cancelled"

    async def test_already_cancelled_at_provider_still_clears_local_state(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """A terminal provider state must not deadlock self-serve cancellation."""
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("cancel_moot")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("cancel_moot"))
        svc.client.subscription.cancel.side_effect = razorpay.errors.BadRequestError(
            "The subscription has already been cancelled"
        )
        svc.client.subscription.fetch.return_value = {
            "id": _rz("cancel_moot"),
            "status": "cancelled",
        }

        result = await svc.cancel_subscription(db_session, user_id)

        assert result["success"] is True, result
        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("cancel_moot")},
            )
        ).scalar_one()
        assert status == "cancelled"
        user_status = (
            await db_session.execute(
                text("SELECT subscription_status FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one()
        assert user_status == "cancelled"

    async def test_unknown_subscription_at_provider_still_clears_local_state(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("cancel_404")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("cancel_404"))
        svc.client.subscription.cancel.side_effect = razorpay.errors.BadRequestError(
            "The id provided does not exist"
        )
        svc.client.subscription.fetch.side_effect = razorpay.errors.BadRequestError(
            "The id provided does not exist"
        )

        result = await svc.cancel_subscription(db_session, user_id)

        assert result["success"] is True, result
        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("cancel_404")},
            )
        ).scalar_one()
        assert status == "cancelled"

    async def test_abandoned_checkout_cancel_reaches_provider(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """plan='free' with a live Razorpay id must still be cancelled upstream."""
        user_id, _ = await _create_user(
            db_session,
            plan="free",
            status="created",
            subscription_id=_rz("cancel_abandoned"),
        )
        await _add_subscription(db_session, user_id, "pro", "created", _rz("cancel_abandoned"))

        result = await svc.cancel_subscription(db_session, user_id)

        assert result["success"] is True, result
        svc.client.subscription.cancel.assert_called_once_with(
            _rz("cancel_abandoned"), {"cancel_at_cycle_end": 0}
        )
        status = (
            await db_session.execute(
                text(
                    "SELECT status FROM subscriptions WHERE razorpay_subscription_id = :rz"
                ),
                {"rz": _rz("cancel_abandoned")},
            )
        ).scalar_one()
        assert status == "cancelled"
        subscription_id = (
            await db_session.execute(
                text("SELECT subscription_id FROM users WHERE id = :uid"), {"uid": user_id}
            )
        ).scalar_one()
        assert subscription_id is None, "a dead checkout must not stay pinned to the user"


# ─────────────────────────────────────────────────────────────────────────────
# G4 — webhook replay protection
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestWebhookReplayProtection:
    @staticmethod
    def _razorpay_payload(subscription_id: str) -> bytes:
        """A payload shaped like a real Razorpay delivery — no body-level id."""
        return json.dumps(
            {
                "entity": "event",
                "account_id": "acc_test",
                "event": "subscription.paused",
                "contains": ["subscription"],
                "payload": {"subscription": {"entity": {"id": subscription_id}}},
                "created_at": 1770000000,
            }
        ).encode("utf-8")

    async def test_replayed_body_without_event_id_is_skipped(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("replay_g4")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("replay_g4"))

        payload = self._razorpay_payload(_rz("replay_g4"))
        sig = _make_signature(payload)
        fake_redis = _FakeRedis()

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            first = await svc.handle_webhook(db_session, payload, sig)
            second = await svc.handle_webhook(db_session, payload, sig)

        assert first["success"] is True
        assert first.get("message") == "Subscription paused"
        assert second["success"] is True
        assert second.get("message") == "Event already processed"
        assert len(fake_redis.store) == 1

    async def test_delivery_header_is_used_as_idempotency_key(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("hdr_g4")
        )
        await _add_subscription(db_session, user_id, "pro", "active", _rz("hdr_g4"))

        payload = self._razorpay_payload(_rz("hdr_g4"))
        sig = _make_signature(payload)
        fake_redis = _FakeRedis()
        delivery_id = "evt_header_g4"

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            first = await svc.handle_webhook(db_session, payload, sig, event_id=delivery_id)
            second = await svc.handle_webhook(db_session, payload, sig, event_id=delivery_id)

        assert first["success"] is True
        assert second.get("message") == "Event already processed"
        assert list(fake_redis.store) == [f"latexy:webhook:processed:{delivery_id}"]

    async def test_distinct_events_are_not_deduped(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_a, _ = await _create_user(db_session, plan="pro", subscription_id=_rz("a_g4"))
        await _add_subscription(db_session, user_a, "pro", "active", _rz("a_g4"))
        user_b, _ = await _create_user(db_session, plan="pro", subscription_id=_rz("b_g4"))
        await _add_subscription(db_session, user_b, "pro", "active", _rz("b_g4"))

        fake_redis = _FakeRedis()
        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            for sub_id in (_rz("a_g4"), _rz("b_g4")):
                payload = self._razorpay_payload(sub_id)
                result = await svc.handle_webhook(db_session, payload, _make_signature(payload))
                assert result.get("message") == "Subscription paused", result

        assert len(fake_redis.store) == 2

    async def test_nested_entity_payload_is_unwrapped(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """A real Razorpay body nests the subscription under payload.*.entity."""
        user_id, _ = await _create_user(
            db_session, plan="free", subscription_id=_rz("unwrap_g4")
        )
        await _add_subscription(db_session, user_id, "pro", "created", _rz("unwrap_g4"))

        payload = json.dumps(
            {
                "entity": "event",
                "event": "subscription.activated",
                "payload": {"subscription": {"entity": {"id": _rz("unwrap_g4")}}},
                "created_at": 1770000001,
            }
        ).encode("utf-8")

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=_FakeRedis()),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            result = await svc.handle_webhook(db_session, payload, _make_signature(payload))

        assert result["success"] is True, result
        plan = (
            await db_session.execute(
                text("SELECT subscription_plan FROM users WHERE id = :uid"), {"uid": user_id}
            )
        ).scalar_one()
        assert plan == "pro"

    async def test_empty_and_non_ascii_signatures_are_rejected(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        payload = self._razorpay_payload(_rz("sig_g4"))

        with patch("app.services.payment_service.settings") as mock_settings:
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            assert svc._verify_webhook_signature(payload, "") is False
            assert svc._verify_webhook_signature(payload, "sïgnature") is False
            assert svc._verify_webhook_signature(payload, _make_signature(payload)) is True


# ─────────────────────────────────────────────────────────────────────────────
# G5 — coupons that cannot be applied are refused, not consumed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestCouponSafety:
    async def test_discount_coupon_is_refused_and_not_redeemed(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        user_id, email = await _create_user(db_session, plan="free")
        coupon_id = str(uuid.uuid4())
        code = f"G5{uuid.uuid4().hex[:8].upper()}"
        await db_session.execute(
            text(
                "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, used_count) "
                "VALUES (:id, :code, 20, ARRAY['pro'], 0)"
            ),
            {"id": coupon_id, "code": code},
        )
        await db_session.commit()

        result = await svc.create_subscription(
            db_session,
            user_id,
            "pro",
            email,
            "Group G",
            billing_period="monthly",
            coupon_code=code,
        )

        assert result["success"] is False
        assert "Coupon codes cannot be applied" in result["error"]
        svc.client.subscription.create.assert_not_called()

        used_count = (
            await db_session.execute(
                text("SELECT used_count FROM coupon_codes WHERE id = :id"), {"id": coupon_id}
            )
        ).scalar_one()
        assert used_count == 0, "an unusable coupon must not burn a redemption"

        redemptions = (
            await db_session.execute(
                text("SELECT COUNT(*) FROM coupon_redemptions WHERE coupon_id = :id"),
                {"id": coupon_id},
            )
        ).scalar_one()
        assert redemptions == 0

    async def test_unusable_discount_is_refused_at_validation_time(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """The coupon box must not say "applied" for a checkout that will refuse."""
        user_id, _ = await _create_user(db_session, plan="free")
        code = f"G5{uuid.uuid4().hex[:8].upper()}"
        await db_session.execute(
            text(
                "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, used_count) "
                "VALUES (:id, :code, 20, ARRAY['pro'], 0)"
            ),
            {"id": str(uuid.uuid4()), "code": code},
        )
        await db_session.commit()

        result = await svc.validate_coupon(db_session, code, "pro", user_id=user_id)

        assert result["valid"] is False
        assert "Coupon codes cannot be applied" in result["message"]

    async def test_mapped_offer_makes_the_discount_usable(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        """With RAZORPAY_COUPON_OFFERS configured the discount reaches Razorpay."""
        user_id, email = await _create_user(db_session, plan="free")
        code = f"G5{uuid.uuid4().hex[:8].upper()}"
        await db_session.execute(
            text(
                "INSERT INTO coupon_codes (id, code, discount_percent, applicable_plans, used_count) "
                "VALUES (:id, :code, 20, ARRAY['pro'], 0)"
            ),
            {"id": str(uuid.uuid4()), "code": code},
        )
        await db_session.commit()

        with (
            patch(
                "app.services.payment_service.get_razorpay_offer_id",
                return_value="offer_test123",
            ),
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=_FakeRedis()),
            ),
        ):
            validated = await svc.validate_coupon(db_session, code, "pro", user_id=user_id)
            assert validated["valid"] is True
            assert validated["offer_id"] == "offer_test123"

            result = await svc.create_subscription(
                db_session,
                user_id,
                "pro",
                email,
                "Group G",
                billing_period="monthly",
                coupon_code=code,
            )

        assert result["success"] is True, result
        payload = svc.client.subscription.create.call_args[0][0]
        assert payload["offer_id"] == "offer_test123"


# ─────────────────────────────────────────────────────────────────────────────
# G6 — team seat reconciliation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTeamSeatReconciliation:
    async def test_owner_cancellation_revokes_seats(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        owner_id, _ = await _create_user(
            db_session, plan="team", subscription_id=_rz("team_g6")
        )
        await _add_subscription(db_session, owner_id, "team", "active", _rz("team_g6"))
        member_id, member_email = await _create_user(db_session, plan="team_member")
        await _add_team_seat(db_session, owner_id, member_id, member_email)

        result = await svc.cancel_subscription(db_session, owner_id)

        assert result["success"] is True
        seat_status = (
            await db_session.execute(
                text("SELECT status FROM team_seats WHERE owner_user_id = :uid"),
                {"uid": owner_id},
            )
        ).scalar_one()
        assert seat_status == "removed"

        member = (
            await db_session.execute(
                text(
                    "SELECT subscription_plan, subscription_status FROM users WHERE id = :uid"
                ),
                {"uid": member_id},
            )
        ).fetchone()
        assert member == ("free", "inactive")

    async def test_cancellation_webhook_revokes_seats(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        owner_id, _ = await _create_user(
            db_session, plan="team", subscription_id=_rz("team_hook_g6")
        )
        await _add_subscription(db_session, owner_id, "team", "active", _rz("team_hook_g6"))
        member_id, member_email = await _create_user(db_session, plan="team_member")
        await _add_team_seat(db_session, owner_id, member_id, member_email)

        result = await svc._handle_subscription_cancelled(
            db_session, {"id": _rz("team_hook_g6")}
        )

        assert result["success"] is True
        seat_status = (
            await db_session.execute(
                text("SELECT status FROM team_seats WHERE owner_user_id = :uid"),
                {"uid": owner_id},
            )
        ).scalar_one()
        assert seat_status == "removed"

        member_plan = (
            await db_session.execute(
                text("SELECT subscription_plan FROM users WHERE id = :uid"),
                {"uid": member_id},
            )
        ).scalar_one()
        assert member_plan == "free"

    async def test_halted_subscription_revokes_seats(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        owner_id, _ = await _create_user(
            db_session, plan="team", subscription_id=_rz("team_halt_g6")
        )
        await _add_subscription(db_session, owner_id, "team", "active", _rz("team_halt_g6"))
        member_id, member_email = await _create_user(db_session, plan="team_member")
        await _add_team_seat(db_session, owner_id, member_id, member_email)

        result = await svc._handle_subscription_ended(
            db_session, {"id": _rz("team_halt_g6")}, "halted"
        )

        assert result["success"] is True
        member_plan = (
            await db_session.execute(
                text("SELECT subscription_plan FROM users WHERE id = :uid"),
                {"uid": member_id},
            )
        ).scalar_one()
        assert member_plan == "free"

    async def test_non_team_cancellation_leaves_other_owners_seats_alone(
        self, svc: PaymentService, db_session: AsyncSession
    ):
        owner_id, _ = await _create_user(
            db_session, plan="pro", subscription_id=_rz("pro_g6")
        )
        await _add_subscription(db_session, owner_id, "pro", "active", _rz("pro_g6"))
        member_id, member_email = await _create_user(db_session, plan="team_member")
        await _add_team_seat(db_session, owner_id, member_id, member_email)

        result = await svc.cancel_subscription(db_session, owner_id)

        assert result["success"] is True
        seat_status = (
            await db_session.execute(
                text("SELECT status FROM team_seats WHERE owner_user_id = :uid"),
                {"uid": owner_id},
            )
        ).scalar_one()
        assert seat_status == "active"

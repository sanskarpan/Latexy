"""
GAP-001 — Webhook security tests.

Covers:
  1. Valid Razorpay webhook signature is accepted
  2. Tampered webhook body is rejected (wrong HMAC)
  3. Missing RAZORPAY_WEBHOOK_SECRET causes rejection
  4. Same event_id arriving twice is rejected (replay protection)
  5. subscription.activated event upgrades user plan
  6. subscription.cancelled event downgrades user plan to free
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.payment_service import PaymentService

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_WEBHOOK_SECRET = "test_razorpay_webhook_secret_32chars"


def _make_payload(event_type: str, subscription_id: str, event_id: str | None = None) -> bytes:
    """Build a minimal Razorpay webhook payload."""
    data: dict = {
        "event": event_type,
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                },
                "id": subscription_id,
            }
        },
    }
    if event_id is not None:
        data["id"] = event_id
    return json.dumps(data).encode("utf-8")


def _make_signature(payload: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


async def _create_user_with_subscription(
    db: AsyncSession,
    plan: str = "pro",
    subscription_id: str | None = None,
) -> tuple[str, str]:
    """Insert a user + subscription row; return (user_id, razorpay_sub_id)."""
    user_id = str(uuid.uuid4())
    razorpay_sub_id = subscription_id or f"sub_{uuid.uuid4().hex[:12]}"

    await db.execute(
        text(
            "INSERT INTO users (id, email, name, email_verified, "
            "subscription_plan, subscription_status, trial_used, subscription_id) "
            "VALUES (:id, :email, 'Webhook Test', true, :plan, 'active', false, :sub_id)"
        ),
        {
            "id": user_id,
            "email": f"test_{user_id.replace('-','')}@example.com",
            "plan": plan,
            "sub_id": razorpay_sub_id,
        },
    )
    # Insert a matching Subscription row
    await db.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, razorpay_subscription_id, "
            "plan_id, status, current_period_start) "
            "VALUES (:id, :uid, :rz_id, :plan, 'active', NOW())"
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": user_id,
            "rz_id": razorpay_sub_id,
            "plan": plan,
        },
    )
    await db.commit()
    return user_id, razorpay_sub_id


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — build a PaymentService that reports as "available"
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def svc_available():
    """
    Return a PaymentService where is_available() is True and
    RAZORPAY_WEBHOOK_SECRET is set to the test secret.
    """
    svc = PaymentService.__new__(PaymentService)
    svc.client = MagicMock()  # non-None → is_available() passes client check
    svc._base_status = {
        "available": True,
        "feature_enabled": True,
        "mode": "enabled",
        "reason": None,
        "message": "Billing is available.",
    }
    return svc


# ─────────────────────────────────────────────────────────────────────────────
# Test class
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestWebhookSecurity:
    """Webhook signature verification and replay protection."""

    # ── 1. Valid signature accepted ──────────────────────────────────────────

    async def test_valid_signature_returns_success(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """A correctly-signed payload with a known event type returns success."""
        user_id, razorpay_sub_id = await _create_user_with_subscription(db_session)
        event_id = f"evt_{uuid.uuid4().hex}"
        payload = _make_payload("subscription.paused", razorpay_sub_id, event_id=event_id)
        sig = _make_signature(payload)

        # Patch settings.RAZORPAY_WEBHOOK_SECRET and Redis
        fake_redis = AsyncMock()
        fake_redis.sismember = AsyncMock(return_value=False)
        fake_redis.sadd = AsyncMock()
        fake_redis.expire = AsyncMock()

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch("app.services.payment_service.get_redis_cache_client", new=AsyncMock(return_value=fake_redis)),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET
            mock_settings.ADMIN_EMAIL = ""

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is True

    # ── 2. Tampered body rejected ────────────────────────────────────────────

    async def test_tampered_body_rejected(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """A payload whose body was altered after signing must be rejected."""
        original_payload = _make_payload("subscription.charged", "sub_tampered")
        sig = _make_signature(original_payload)
        # Tamper: change a byte in the payload
        tampered_payload = original_payload[:-1] + b"X"

        with patch("app.services.payment_service.settings") as mock_settings:
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET

            result = await svc_available.handle_webhook(db_session, tampered_payload, sig)

        assert result["success"] is False
        assert "signature" in result.get("error", "").lower()

    # ── 3. Missing webhook secret causes rejection ───────────────────────────

    async def test_missing_webhook_secret_rejected(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """Empty RAZORPAY_WEBHOOK_SECRET must cause every request to be rejected."""
        payload = _make_payload("subscription.charged", "sub_nosecret")
        # Use a valid HMAC — but the secret is missing server-side
        sig = _make_signature(payload, secret="some_secret")

        with patch("app.services.payment_service.settings") as mock_settings:
            mock_settings.RAZORPAY_WEBHOOK_SECRET = ""  # not configured

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is False

    # ── 4. Replay protection — duplicate event_id rejected ───────────────────

    async def test_duplicate_event_id_rejected(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """The same event_id arriving a second time must be silently skipped."""
        event_id = f"evt_replay_{uuid.uuid4().hex}"
        payload = _make_payload("subscription.charged", "sub_replay", event_id=event_id)
        sig = _make_signature(payload)

        # Redis reports this event_id as already processed
        fake_redis = AsyncMock()
        fake_redis.sismember = AsyncMock(return_value=True)  # ← already in set

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is True
        assert result.get("message") == "Event already processed"

    # ── 5. subscription.activated upgrades plan ──────────────────────────────

    async def test_subscription_activated_upgrades_user(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """subscription.activated must set subscription status to active in the DB."""
        user_id, razorpay_sub_id = await _create_user_with_subscription(
            db_session, plan="basic"
        )
        event_id = f"evt_act_{uuid.uuid4().hex}"
        payload = _make_payload("subscription.activated", razorpay_sub_id, event_id=event_id)
        sig = _make_signature(payload)

        fake_redis = AsyncMock()
        fake_redis.sismember = AsyncMock(return_value=False)
        fake_redis.sadd = AsyncMock()
        fake_redis.expire = AsyncMock()

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is True, result

        # Verify the User row was updated
        row = (
            await db_session.execute(
                text("SELECT subscription_status FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "active"

    # ── 6. subscription.cancelled downgrades plan ────────────────────────────

    async def test_subscription_cancelled_downgrades_user(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """subscription.cancelled must set plan=free, status=cancelled in the DB."""
        user_id, razorpay_sub_id = await _create_user_with_subscription(
            db_session, plan="pro"
        )
        event_id = f"evt_can_{uuid.uuid4().hex}"
        payload = _make_payload("subscription.cancelled", razorpay_sub_id, event_id=event_id)
        sig = _make_signature(payload)

        fake_redis = AsyncMock()
        fake_redis.sismember = AsyncMock(return_value=False)
        fake_redis.sadd = AsyncMock()
        fake_redis.expire = AsyncMock()

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is True, result

        # Verify the User row was downgraded
        row = (
            await db_session.execute(
                text(
                    "SELECT subscription_plan, subscription_status FROM users WHERE id = :uid"
                ),
                {"uid": user_id},
            )
        ).fetchone()
        assert row is not None
        plan, status = row
        assert plan == "free"
        assert status == "cancelled"

    # ── Extra: wrong-secret signature produces rejection ─────────────────────

    async def test_wrong_secret_signature_rejected(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """Signature computed with a different secret must be rejected."""
        payload = _make_payload("subscription.charged", "sub_wrong_key")
        wrong_sig = _make_signature(payload, secret="completely_different_secret_value")

        with patch("app.services.payment_service.settings") as mock_settings:
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET  # server uses correct secret

            result = await svc_available.handle_webhook(db_session, payload, wrong_sig)

        assert result["success"] is False

    # ── Extra: first-time event_id is marked as processed in Redis ───────────

    async def test_processed_event_id_written_to_redis(
        self, svc_available: PaymentService, db_session: AsyncSession
    ):
        """After successful handling, the event_id must be persisted in Redis."""
        user_id, razorpay_sub_id = await _create_user_with_subscription(db_session)
        event_id = f"evt_mark_{uuid.uuid4().hex}"
        payload = _make_payload("subscription.paused", razorpay_sub_id, event_id=event_id)
        sig = _make_signature(payload)

        fake_redis = AsyncMock()
        fake_redis.sismember = AsyncMock(return_value=False)
        fake_redis.sadd = AsyncMock()
        fake_redis.expire = AsyncMock()

        with (
            patch("app.services.payment_service.settings") as mock_settings,
            patch(
                "app.services.payment_service.get_redis_cache_client",
                new=AsyncMock(return_value=fake_redis),
            ),
        ):
            mock_settings.RAZORPAY_WEBHOOK_SECRET = _WEBHOOK_SECRET

            result = await svc_available.handle_webhook(db_session, payload, sig)

        assert result["success"] is True
        fake_redis.sadd.assert_awaited_once()
        call_args = fake_redis.sadd.call_args[0]
        assert event_id in call_args

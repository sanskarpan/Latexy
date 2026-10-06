"""Payment service for Razorpay integration and subscription management."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import razorpay as _razorpay_module
except (ImportError, ModuleNotFoundError):
    _razorpay_module = None  # type: ignore[assignment]

from ..core.config import (
    get_plan_config,
    get_razorpay_offer_id,
    get_razorpay_plan_id,
    is_b57_sku_configured,
    resolve_plan_family,
    settings,
)
from ..core.logging import get_logger
from ..core.observability import record_business_event
from ..core.redis import get_redis_cache_client
from ..database import models as db_models
from .email_service import email_service
from .referral_service import referral_service

logger = get_logger(__name__)

Payment = db_models.Payment
Subscription = db_models.Subscription
TeamSeat = db_models.TeamSeat
User = db_models.User
CouponCode = getattr(db_models, "CouponCode", None)
CouponRedemption = getattr(db_models, "CouponRedemption", None)

# Statuses a Razorpay subscription can hold while it is still live, most
# authoritative first. Used both to pick the "current" subscription when a user
# has several rows and to refuse creating a second live subscription.
SCHEDULED_CANCEL_STATUS = "cancel_scheduled"
LIVE_SUBSCRIPTION_STATUSES = (
    SCHEDULED_CANCEL_STATUS,
    "active",
    "authenticated",
    "created",
    "pending",
    "paused",
)

# Live statuses where nothing has been charged yet, so the subscription can be
# abandoned/replaced without a refund.
UNPAID_SUBSCRIPTION_STATUSES = ("created", "authenticated")

# Live statuses that can actually take money from the customer. Only these
# justify refusing a downgrade — an abandoned checkout bills nobody.
BILLING_SUBSCRIPTION_STATUSES = tuple(
    status for status in LIVE_SUBSCRIPTION_STATUSES if status not in UNPAID_SUBSCRIPTION_STATUSES
)

# Provider statuses where the subscription is finished: it cannot charge again
# and there is nothing left to cancel.
TERMINAL_PROVIDER_STATUSES = ("cancelled", "completed", "expired")

WEBHOOK_PROCESSING_TTL_SECONDS = 120
WEBHOOK_DONE_TTL_SECONDS = 86400

# A webhook claim is the random token stored in Redis while the handler runs.
# The final transition must compare that token atomically: a slow handler whose
# lease expires must not mark a newer owner's claim as done (or delete it after
# a failure).  GET-then-SET/DEL would leave exactly that stale-owner race.
_WEBHOOK_PROMOTE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""
_WEBHOOK_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

class PaymentService:
    """Service for handling payments and subscriptions via Razorpay."""

    def __init__(self):
        """Initialize Razorpay client."""
        self.client = None
        self._base_status = self._build_base_status()

        if self._base_status["available"]:
            self.client = _razorpay_module.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            logger.info("Billing enabled with Razorpay")
        else:
            logger.info(self._base_status["message"])

    def _build_base_status(self) -> Dict[str, Any]:
        """Return billing status derived from static application configuration."""
        billing_mode = settings.normalized_billing_mode
        if billing_mode == "disabled":
            return {
                "feature_enabled": False,
                "mode": "disabled",
                "available": False,
                "reason": "billing_disabled",
                "message": "Billing is disabled in this environment.",
            }

        if not settings.billing_credentials_configured():
            return {
                "feature_enabled": True,
                "mode": "unconfigured",
                "available": False,
                "reason": "billing_unconfigured",
                "message": (
                    "Billing is enabled in the product, but Razorpay is not "
                    "fully configured in this environment."
                ),
            }

        if not _razorpay_module:
            return {
                "feature_enabled": True,
                "mode": "unconfigured",
                "available": False,
                "reason": "billing_sdk_unavailable",
                "message": "Billing is unavailable because the Razorpay SDK is not installed.",
            }

        return {
            "feature_enabled": True,
            "mode": "enabled",
            "available": True,
            "reason": None,
            "message": "Billing is available.",
        }

    def get_status(self, feature_enabled: bool = True) -> Dict[str, Any]:
        """Return effective billing status after applying runtime feature flags."""
        if not feature_enabled:
            return {
                "feature_enabled": False,
                "mode": "disabled",
                "available": False,
                "reason": "feature_flag_disabled",
                "message": "Billing is currently disabled.",
            }
        return dict(self._base_status)

    def is_available(self) -> bool:
        """Check if payment service is available."""
        return bool(self._base_status["available"] and self.client is not None)

    async def get_subscription_plans(self) -> Dict[str, Any]:
        """Get only server-configured plans safe to show at checkout.

        B57 prices are not invented in code: operators configure integer INR
        paise and a reviewed Razorpay weekly plan ID. Until then those cards
        are omitted, so an unavailable provider cannot be presented as a free
        or payable plan.
        """
        # The API returns a keyed object for backwards compatibility, while the
        # browser renders values as cards. Include the canonical key in every
        # value so a client cannot accidentally POST an undefined plan ID.
        plans = {
            key: {**dict(value), "id": key}
            for key, value in settings.SUBSCRIPTION_PLANS.items()
        }
        for sku in ("weekly", "lifetime"):
            if not is_b57_sku_configured(sku) or not self.is_available():
                plans.pop(sku, None)
                continue
            config = get_plan_config(sku)
            plans[sku] = {**config, "id": sku}
        return plans

    async def create_razorpay_plan(self, plan_id: str) -> Optional[str]:
        """Create a plan in Razorpay."""
        if not self.client:
            logger.error("Razorpay client not initialized")
            return None

        try:
            plan_config = get_plan_config(plan_id)
            if not plan_config:
                logger.error(f"Plan {plan_id} not found in configuration")
                return None

            # Skip free plan
            if plan_config["price"] == 0:
                return None

            # B57 weekly is deliberately bound to a dashboard-created plan;
            # never manufacture a commercial SKU from application defaults.
            if plan_id == "weekly" and not get_razorpay_plan_id("weekly"):
                return None

            interval = plan_config.get("interval")
            period = {
                "week": "weekly",
                "month": "monthly",
                "year": "yearly",
            }.get(interval)
            if period is None:
                return None

            razorpay_plan = self.client.plan.create({
                "period": period,
                "interval": 1,
                "item": {
                    "name": plan_config["name"],
                    "amount": plan_config["price"],
                    "currency": plan_config["currency"]
                }
            })

            logger.info(f"Created Razorpay plan: {razorpay_plan['id']} for {plan_id}")
            return razorpay_plan["id"]

        except Exception as e:
            logger.error("Error creating Razorpay plan for %s", plan_id, extra={"error_type": type(e).__name__})
            return None

    def _resolve_concrete_plan_id(self, plan_id: str, billing_period: str) -> str:
        normalized = (plan_id or "free").strip().lower()
        period = (billing_period or "monthly").strip().lower()
        if normalized in {"basic", "pro", "byok"} and period == "annual":
            return f"{normalized}_annual"
        return normalized

    def _is_student_email(self, email: str) -> bool:
        normalized = (email or "").strip().lower()
        return any(normalized.endswith(suffix.lower()) for suffix in settings.STUDENT_EMAIL_ALLOWED_SUFFIXES)

    async def _request_student_verification(
        self,
        db: AsyncSession,
        user_id: str,
        customer_email: str,
        customer_name: str,
        student_email: str,
    ) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        redis = await get_redis_cache_client()
        payload = {
            "user_id": user_id,
            "customer_email": customer_email,
            "customer_name": customer_name,
            "student_email": student_email,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis.set(f"student_plan_verify:{token}", json.dumps(payload), ex=24 * 3600)

        verify_url = f"{settings.FRONTEND_URL}/billing?student_verify={token}"
        await email_service.send_email(
            to=student_email,
            subject="Verify your Latexy student plan",
            html_body=(
                f"<p>Verify your student email to activate the discounted Latexy student plan.</p>"
                f"<p><a href=\"{verify_url}\">Verify student email</a></p>"
            ),
            text_body=f"Verify your Latexy student plan: {verify_url}",
        )

        return {
            "success": True,
            "verification_required": True,
            "message": "Verification email sent to your student address.",
            "verification_preview_url": verify_url if not settings.EMAIL_ENABLED else None,
        }

    async def verify_student_subscription(
        self,
        db: AsyncSession,
        token: str,
    ) -> Dict[str, Any]:
        try:
            redis = await get_redis_cache_client()
            token_lock = f"latexy:student-verify:{token}"
            if not await redis.set(token_lock, "1", nx=True, ex=120):
                return {"success": False, "error": "Student verification is already in progress"}
            try:
                # Re-read the one-time token after taking the lock. A second
                # request may have read it just before the first request deleted
                # it, and must not create a second Razorpay subscription.
                raw = await redis.get(f"student_plan_verify:{token}")
                if not raw:
                    return {"success": False, "error": "Student verification link is invalid or expired"}

                payload = json.loads(raw)
                user_id = payload["user_id"]

                if not self.client:
                    # Never grant a paid/Pro-equivalent plan (student resolves to the
                    # Pro family) without a completed payment. When Razorpay is not
                    # configured, fail verification rather than activating the plan.
                    logger.warning(
                        "Student verification attempted while billing is unavailable; "
                        "refusing to grant plan without payment"
                    )
                    return {"success": False, "error": self._base_status["message"]}

                if not await self._acquire_checkout_lock(user_id):
                    return {"success": False, "error": "A checkout is already in progress for this account."}
                try:
                    existing = await self._get_live_provider_subscription(db, user_id)
                    if existing is not None:
                        resolved = await self._resolve_existing_subscription(db, existing, "student")
                        if resolved is not None:
                            return resolved

                    result = await self._create_paid_subscription(
                        db=db,
                        user_id=user_id,
                        concrete_plan_id="student",
                        customer_email=payload["customer_email"],
                        customer_name=payload["customer_name"],
                    )
                finally:
                    await self._release_checkout_lock(user_id)

                if result.get("success"):
                    await redis.delete(f"student_plan_verify:{token}")
                    result.setdefault(
                        "message",
                        "Student email verified. Complete payment to activate your plan.",
                    )
                return result
            finally:
                await redis.delete(token_lock)
        except Exception as exc:
            logger.error("Error verifying student subscription", extra={"error_type": type(exc).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to verify student subscription"}

    async def validate_coupon(
        self,
        db: AsyncSession,
        code: str,
        plan_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate a coupon for the given plan."""
        if CouponCode is None or CouponRedemption is None:
            return {"valid": False, "message": "Coupons are not available in this environment"}

        normalized_code = (code or "").strip().upper()
        if not normalized_code:
            return {"valid": False, "message": "Coupon code is required"}

        result = await db.execute(select(CouponCode).where(CouponCode.code == normalized_code))
        coupon = result.scalar_one_or_none()
        if not coupon:
            return {"valid": False, "message": "Invalid or expired code"}

        now = datetime.now(timezone.utc)
        expires_at = coupon.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at <= now:
            return {"valid": False, "message": "Invalid or expired code"}

        if coupon.max_uses is not None and int(coupon.used_count or 0) >= coupon.max_uses:
            return {"valid": False, "message": "Invalid or expired code"}

        applicable = set(coupon.applicable_plans or [])
        if applicable and plan_id not in applicable and resolve_plan_family(plan_id) not in applicable:
            return {"valid": False, "message": "Code not valid for this plan"}

        already_redeemed = False
        if user_id:
            redemption = await db.execute(
                select(CouponRedemption).where(
                    CouponRedemption.coupon_id == coupon.id,
                    CouponRedemption.user_id == user_id,
                )
            )
            already_redeemed = redemption.scalar_one_or_none() is not None
            if already_redeemed:
                return {"valid": False, "message": "Coupon already used by this account"}

        discount_percent = int(coupon.discount_percent)
        offer_id = get_razorpay_offer_id(normalized_code)
        if discount_percent > 0 and not offer_id:
            # Razorpay discounts subscriptions through an offer_id; without one
            # the discount cannot reach checkout. Refuse here so the UI never
            # shows "Coupon applied" for something the Subscribe button will
            # then reject.
            logger.error(
                f"Coupon {normalized_code} has a {discount_percent}% discount but no "
                "Razorpay offer is mapped in RAZORPAY_COUPON_OFFERS; refusing it"
            )
            return {
                "valid": False,
                "message": "Coupon codes cannot be applied at checkout right now.",
            }

        return {
            "valid": True,
            "code": normalized_code,
            "discount_percent": discount_percent,
            "offer_id": offer_id,
            "message": "Coupon applied",
            "already_redeemed": already_redeemed,
        }

    async def _reserve_coupon(
        self,
        db: AsyncSession,
        code: str,
        plan_id: str,
        user_id: str,
    ) -> tuple[bool, str]:
        """Atomically reserve one coupon use before contacting Razorpay."""
        result = await db.execute(
            select(CouponCode)
            .where(CouponCode.code == code)
            .with_for_update()
        )
        coupon = result.scalar_one_or_none()
        if coupon is None:
            return False, "Invalid or expired code"

        now = datetime.now(timezone.utc)
        expires_at = coupon.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        applicable = set(coupon.applicable_plans or [])
        if expires_at and expires_at <= now:
            return False, "Invalid or expired code"
        if applicable and plan_id not in applicable and resolve_plan_family(plan_id) not in applicable:
            return False, "Code not valid for this plan"
        if coupon.max_uses is not None and int(coupon.used_count or 0) >= coupon.max_uses:
            return False, "Invalid or expired code"

        redemption = await db.execute(
            select(CouponRedemption.id).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.user_id == user_id,
            )
        )
        if redemption.scalar_one_or_none() is not None:
            return False, "Coupon already used by this account"

        coupon.used_count = int(coupon.used_count or 0) + 1
        db.add(CouponRedemption(coupon_id=coupon.id, user_id=user_id))
        await db.flush()
        return True, ""

    async def _get_current_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        razorpay_subscription_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Return the single subscription row that represents the user "now".

        A user legitimately accumulates rows (retried checkout, free -> paid
        upgrade), so this picks one deterministically instead of assuming there
        is at most one: the row Razorpay currently points at, then the most
        authoritative live status, then the newest row.
        """
        status_rank = case(
            {status: rank for rank, status in enumerate(LIVE_SUBSCRIPTION_STATUSES)},
            value=Subscription.status,
            else_=len(LIVE_SUBSCRIPTION_STATUSES),
        )

        stmt = select(Subscription).where(Subscription.user_id == user_id)
        if razorpay_subscription_id:
            # CASE rather than a bare boolean: free rows carry a NULL provider id,
            # and "NULL = 'sub_x' DESC" sorts NULLS FIRST in Postgres.
            stmt = stmt.order_by(
                case(
                    (Subscription.razorpay_subscription_id == razorpay_subscription_id, 0),
                    else_=1,
                ).asc()
            )
        stmt = stmt.order_by(status_rank.asc(), Subscription.created_at.desc()).limit(1)

        result = await db.execute(stmt)
        return result.scalars().first()

    async def _get_live_provider_subscription(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> Optional[Any]:
        """Return the user's live Razorpay-backed subscription, if any.

        Free-plan rows are ignored (they carry no razorpay_subscription_id) —
        only provider-backed subscriptions can double-bill.
        """
        status_rank = case(
            {status: rank for rank, status in enumerate(LIVE_SUBSCRIPTION_STATUSES)},
            value=Subscription.status,
            else_=len(LIVE_SUBSCRIPTION_STATUSES),
        )
        result = await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.razorpay_subscription_id.is_not(None),
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            )
            .order_by(status_rank.asc(), Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _acquire_checkout_lock(self, user_id: str) -> bool:
        """Take a short per-user lock so a double-click cannot create two subs."""
        redis = await get_redis_cache_client()
        return bool(await redis.set(f"latexy:subscription:checkout:{user_id}", "1", nx=True, ex=120))

    async def _release_checkout_lock(self, user_id: str) -> None:
        redis = await get_redis_cache_client()
        await redis.delete(f"latexy:subscription:checkout:{user_id}")

    def _fetch_provider_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a subscription from Razorpay; None when it cannot be read."""
        try:
            return self.client.subscription.fetch(subscription_id)
        except Exception as e:
            logger.error("Error fetching Razorpay subscription %s", subscription_id, extra={"error_type": type(e).__name__})
            return None

    async def _resolve_existing_subscription(
        self,
        db: AsyncSession,
        existing: Any,
        concrete_plan_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Decide what to do about a user's existing live subscription.

        Returns the response to send back to the caller, or None when the
        existing subscription was retired and a new one may be created.
        """
        is_unpaid = existing.status in UNPAID_SUBSCRIPTION_STATUSES

        if existing.plan_id == concrete_plan_id:
            if is_unpaid:
                # Same plan, never paid: this is a double-click or an abandoned
                # checkout. Hand back the original payment link instead of
                # creating a second subscription.
                provider = self._fetch_provider_subscription(existing.razorpay_subscription_id)
                return {
                    "success": True,
                    "subscription_id": existing.razorpay_subscription_id,
                    "short_url": (provider or {}).get("short_url"),
                    "message": "A checkout for this plan is already open.",
                }
            return {
                "success": False,
                "error": "You are already subscribed to this plan.",
            }

        if not is_unpaid:
            # A paying subscription must be cancelled explicitly; switching
            # silently would leave two live subscriptions billing the customer.
            plan_name = (get_plan_config(existing.plan_id) or {}).get("name", existing.plan_id)
            return {
                "success": False,
                "error": (
                    f"You already have an active {plan_name} subscription. "
                    "Cancel it before switching to a different plan."
                ),
            }

        # Unpaid subscription for a different plan: retire it (at the provider
        # and locally) so the user is left with exactly one live subscription.
        if not await self._retire_unpaid_subscription(db, existing, reason=concrete_plan_id):
            return {
                "success": False,
                "error": "Could not close your pending checkout. Please try again in a moment.",
            }
        return None

    async def _retire_unpaid_subscription(
        self,
        db: AsyncSession,
        existing: Any,
        reason: str,
        require_provider_confirmation: bool = True,
    ) -> bool:
        """Cancel an unpaid subscription at Razorpay and locally.

        Returns False when the provider could not be told, so the caller can
        refuse instead of leaving an orphaned live subscription behind.
        """
        settled = False
        if not self.client:
            logger.error(
                "Cannot retire subscription "
                f"{existing.razorpay_subscription_id}: billing client unavailable"
            )
        else:
            try:
                self.client.subscription.cancel(
                    existing.razorpay_subscription_id, {"cancel_at_cycle_end": False}
                )
                settled = True
            except Exception as e:
                logger.error(
                    "Error cancelling pending subscription "
                    f"{existing.razorpay_subscription_id}: {e}"
                )
                settled = self._provider_cancel_is_moot(existing.razorpay_subscription_id)

        if not settled:
            # A 'created' subscription has no authorised mandate, so Razorpay
            # cannot charge it on its own: a caller that only needs the row out
            # of the way (the free downgrade) may proceed. 'authenticated' will
            # be charged at the cycle start and must be confirmed cancelled.
            if require_provider_confirmation or existing.status != "created":
                return False
            logger.warning(
                f"Retiring unconfirmed checkout {existing.razorpay_subscription_id} locally; "
                "the provider could not be reached and it cannot charge on its own"
            )

        await db.execute(
            update(Subscription)
            .where(Subscription.id == existing.id)
            .values(status="cancelled", cancelled_at=datetime.now(timezone.utc))
        )
        await db.commit()
        logger.info(
            f"Retired pending subscription {existing.razorpay_subscription_id} "
            f"before switching to {reason}"
        )
        return True

    def _provider_cancel_is_moot(self, subscription_id: str) -> bool:
        """True when Razorpay rejected a cancel because nothing is left to cancel.

        Razorpay answers BAD_REQUEST_ERROR both for "already cancelled/completed/
        expired" and for ids it does not know, so read the subscription back
        rather than pattern-matching the message. A terminal (or missing)
        subscription cannot charge anyone, and refusing the local cleanup in
        that case would strand the user on a plan they can never leave.
        """
        if not self.client:
            return False

        try:
            provider = self.client.subscription.fetch(subscription_id)
        except Exception as exc:
            not_found = _razorpay_module is not None and isinstance(
                exc, _razorpay_module.errors.BadRequestError
            )
            if not_found:
                logger.warning(
                    f"Razorpay does not know subscription {subscription_id} ({exc}); "
                    "treating it as already cancelled"
                )
                return True
            logger.error("Could not read back Razorpay subscription %s", subscription_id, extra={"error_type": type(exc).__name__})
            return False

        status = str((provider or {}).get("status") or "").lower()
        if status in TERMINAL_PROVIDER_STATUSES:
            logger.warning(
                f"Razorpay subscription {subscription_id} is already '{status}'; "
                "treating the cancel as complete"
            )
            return True
        return False

    async def _revoke_team_seats(self, db: AsyncSession, owner_user_id: str) -> int:
        """Release every seat owned by a user whose team subscription ended.

        Mirrors DELETE /team/seats/{id}: the seat is marked removed and any
        member still riding on the owner's plan drops back to free.
        """
        seat_result = await db.execute(
            select(TeamSeat.id, TeamSeat.member_user_id).where(
                TeamSeat.owner_user_id == owner_user_id,
                TeamSeat.status != "removed",
            )
        )
        seats = seat_result.all()
        if not seats:
            return 0

        member_ids = [member_id for _seat_id, member_id in seats if member_id]
        if member_ids:
            await db.execute(
                update(User)
                .where(User.id.in_(member_ids), User.subscription_plan == "team_member")
                .values(subscription_plan="free", subscription_status="inactive")
            )

        await db.execute(
            update(TeamSeat)
            .where(
                TeamSeat.owner_user_id == owner_user_id,
                TeamSeat.status != "removed",
            )
            .values(status="removed")
        )
        logger.info(f"Revoked {len(seats)} team seat(s) for owner {owner_user_id}")
        return len(seats)

    async def _suspend_team_seats(self, db: AsyncSession, owner_user_id: str) -> int:
        """Temporarily remove entitlements while retaining active memberships."""
        seat_result = await db.execute(
            select(TeamSeat.id, TeamSeat.member_user_id).where(
                TeamSeat.owner_user_id == owner_user_id,
                TeamSeat.status == "active",
            )
        )
        seats = seat_result.all()
        member_ids = [member_id for _seat_id, member_id in seats if member_id]
        if member_ids:
            await db.execute(
                update(User)
                .where(User.id.in_(member_ids), User.subscription_plan == "team_member")
                .values(subscription_plan="free", subscription_status="paused")
            )
        if seats:
            await db.execute(
                update(TeamSeat)
                .where(
                    TeamSeat.owner_user_id == owner_user_id,
                    TeamSeat.status == "active",
                )
                .values(status="suspended")
            )
        return len(seats)

    async def _restore_team_seats(self, db: AsyncSession, owner_user_id: str) -> int:
        """Restore memberships suspended by a temporary billing pause."""
        seat_result = await db.execute(
            select(TeamSeat.id, TeamSeat.member_user_id).where(
                TeamSeat.owner_user_id == owner_user_id,
                TeamSeat.status == "suspended",
            )
        )
        seats = seat_result.all()
        member_ids = [member_id for _seat_id, member_id in seats if member_id]
        if member_ids:
            # Never overwrite a plan the member bought independently while the
            # owner was paused.
            await db.execute(
                update(User)
                .where(User.id.in_(member_ids), User.subscription_plan == "free")
                .values(subscription_plan="team_member", subscription_status="active")
            )
        if seats:
            await db.execute(
                update(TeamSeat)
                .where(
                    TeamSeat.owner_user_id == owner_user_id,
                    TeamSeat.status == "suspended",
                )
                .values(status="active")
            )
        return len(seats)

    async def _create_paid_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        concrete_plan_id: str,
        customer_email: str,
        customer_name: str,
        coupon_code: Optional[str] = None,
        offer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.client:
            return {"success": False, "error": self._base_status["message"]}

        plan_config = get_plan_config(concrete_plan_id)
        razorpay_plan_id = get_razorpay_plan_id(concrete_plan_id) or await self.create_razorpay_plan(concrete_plan_id)
        if not razorpay_plan_id:
            return {"success": False, "error": "Failed to create payment plan"}

        customer = self.client.customer.create({
            "name": customer_name,
            "email": customer_email,
        })

        interval = plan_config.get("interval", "month")
        period_count = {"week": 52, "year": 1}.get(interval, 12)
        current_period_end = datetime.now(timezone.utc) + self._period_delta_for_plan(concrete_plan_id)
        subscription = self.client.subscription.create({
            "plan_id": razorpay_plan_id,
            "customer_id": customer["id"],
            "total_count": period_count,
            "quantity": 1,
            # Razorpay applies a coupon discount through the mapped offer.
            **({"offer_id": offer_id} if offer_id else {}),
            "notes": {
                "user_id": user_id,
                "plan_id": concrete_plan_id,
                **({"coupon_code": coupon_code} if coupon_code else {}),
            },
        })

        db.add(
            Subscription(
                user_id=user_id,
                razorpay_subscription_id=subscription["id"],
                plan_id=concrete_plan_id,
                status="created",
                current_period_start=datetime.now(timezone.utc),
                current_period_end=current_period_end,
            )
        )
        # NOTE: do NOT grant the paid plan here. The Razorpay subscription is still
        # in "created" state (unpaid); User.subscription_plan is what gates paid
        # features, so upgrading it now would grant the plan before any payment.
        # The plan is applied in _handle_subscription_activated after payment.
        await db.execute(
            update(User).where(User.id == user_id).values(
                subscription_status="created",
                subscription_id=subscription["id"],
            )
        )
        await db.commit()

        record_business_event("subscription", "created")

        return {
            "success": True,
            "subscription_id": subscription["id"],
            "short_url": subscription.get("short_url"),
            "customer_id": customer["id"],
        }

    async def _create_lifetime_order(
        self,
        db: AsyncSession,
        user_id: str,
        customer_email: str,
        customer_name: str,
    ) -> Dict[str, Any]:
        """Create or reuse the one-time Razorpay Orders API checkout.

        The local Subscription row is used as the durable order-intent record
        (its provider-id column predates B57 and is nullable); the value is an
        ``order_`` id and is never treated as a recurring subscription. This
        avoids a schema migration while preserving webhook reconciliation and
        payment history on the existing model.
        """
        if not self.client or not is_b57_sku_configured("lifetime"):
            return {"success": False, "error": "Lifetime billing is not configured."}

        recurring = await self._get_live_provider_subscription(db, user_id)
        if recurring and recurring.plan_id != "lifetime" and recurring.status in BILLING_SUBSCRIPTION_STATUSES:
            return {"success": False, "error": "Cancel your recurring subscription before purchasing Lifetime."}

        active = await db.execute(
            select(Subscription.id).where(
                Subscription.user_id == user_id,
                Subscription.plan_id == "lifetime",
                Subscription.status == "active",
            ).limit(1)
        )
        if active.scalar_one_or_none() is not None:
            return {"success": False, "error": "You already own the Lifetime plan."}

        existing = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.plan_id == "lifetime",
                Subscription.status.in_(("created", "pending")),
            ).order_by(Subscription.created_at.desc()).limit(1)
        )
        pending = existing.scalars().first()
        if pending and pending.razorpay_subscription_id:
            order_id = pending.razorpay_subscription_id
            try:
                order = self.client.order.fetch(order_id)
            except Exception as exc:
                logger.warning("Could not verify pending lifetime order %s", order_id, extra={"error_type": type(exc).__name__})
                return {"success": False, "error": "Pending lifetime checkout could not be verified."}
            if (
                int(order.get("amount") or 0) != int(get_plan_config("lifetime")["price"])
                or str(order.get("currency") or "").upper()
                != str(get_plan_config("lifetime")["currency"]).upper()
            ):
                return {"success": False, "error": "Pending lifetime checkout does not match configured price."}
            return self._lifetime_order_response(order, user_id)

        plan = get_plan_config("lifetime")
        try:
            order = self.client.order.create({
                "amount": int(plan["price"]),
                "currency": str(plan["currency"]).upper(),
                "receipt": f"latexy_{secrets.token_urlsafe(12)}",
                "notes": {"user_id": user_id, "plan_id": "lifetime"},
            })
        except Exception as exc:
            logger.error("Error creating lifetime Razorpay order", extra={"error_type": type(exc).__name__})
            return {"success": False, "error": "Failed to create lifetime checkout."}

        order_id = str(order.get("id") or "")
        if not order_id.startswith("order_"):
            return {"success": False, "error": "Payment provider returned an invalid order."}
        if (
            int(order.get("amount") or 0) != int(plan["price"])
            or str(order.get("currency") or "").upper() != str(plan["currency"]).upper()
        ):
            logger.error("Razorpay returned an unexpected lifetime order amount/currency: %s", order_id)
            return {"success": False, "error": "Payment provider order did not match configured price."}

        db.add(Subscription(
            user_id=user_id,
            razorpay_subscription_id=order_id,
            plan_id="lifetime",
            status="created",
            current_period_start=datetime.now(timezone.utc),
            current_period_end=None,
        ))
        await db.execute(update(User).where(User.id == user_id).values(subscription_status="pending"))
        await db.commit()
        response = self._lifetime_order_response(order, user_id)
        return response

    @staticmethod
    def _lifetime_order_response(order: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        return {
            "success": True,
            "order_id": order.get("id"),
            "amount": int(order.get("amount") or 0),
            "currency": str(order.get("currency") or "INR").upper(),
            "key_id": settings.RAZORPAY_KEY_ID,
            "plan_id": "lifetime",
            "user_id": user_id,
            "checkout_type": "one_time",
        }

    async def create_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        plan_id: str,
        customer_email: str,
        customer_name: str,
        billing_period: str = "monthly",
        coupon_code: Optional[str] = None,
        student_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new subscription."""
        try:
            concrete_plan_id = self._resolve_concrete_plan_id(plan_id, billing_period)
            # Do not let get_plan_config's backwards-compatible family fallback
            # turn an arbitrary client string into a free/paid SKU.
            if concrete_plan_id not in settings.SUBSCRIPTION_PLANS:
                return {"success": False, "error": "Invalid plan selected"}
            plan_config = get_plan_config(concrete_plan_id)
            if not plan_config:
                return {
                    "success": False,
                    "error": "Invalid plan selected"
                }

            # Annual SKUs (basic_annual/pro_annual/byok_annual) are only
            # launched once their RAZORPAY_PLAN_*_ANNUAL id is configured in
            # the dashboard. Without that, falling through would spin up an
            # ad-hoc Razorpay plan on every checkout attempt (via the
            # create_razorpay_plan fallback in _create_paid_subscription)
            # instead of billing against a reviewed, pre-configured annual
            # SKU — refuse cleanly instead.
            if concrete_plan_id.endswith("_annual") and not get_razorpay_plan_id(concrete_plan_id):
                return {
                    "success": False,
                    "error": "Annual billing isn't available yet — please choose monthly.",
                }

            if concrete_plan_id in {"weekly", "lifetime"}:
                if not is_b57_sku_configured(concrete_plan_id):
                    return {
                        "success": False,
                        "error": f"{plan_config.get('name', concrete_plan_id)} billing is not configured yet.",
                    }
                if not self.client:
                    return {"success": False, "error": self._base_status["message"]}
                if concrete_plan_id == "weekly" and coupon_code:
                    # Weekly webhook reconciliation verifies the exact
                    # configured charge. Razorpay offers can reduce that
                    # amount, but the resulting amount is not recoverable
                    # from a subscription.charged event; reject the coupon
                    # before creating a checkout that cannot be activated.
                    return {
                        "success": False,
                        "error": "Coupons cannot be applied to the Weekly plan.",
                    }
                if concrete_plan_id == "lifetime":
                    # Razorpay Orders checkout has no subscription offer path;
                    # never accept a coupon and silently charge the full
                    # one-time amount.
                    if coupon_code:
                        return {
                            "success": False,
                            "error": "Coupons cannot be applied to the Lifetime plan.",
                        }
                    if not await self._acquire_checkout_lock(user_id):
                        return {"success": False, "error": "A checkout is already in progress for this account."}
                    try:
                        return await self._create_lifetime_order(
                            db, user_id, customer_email, customer_name
                        )
                    finally:
                        await self._release_checkout_lock(user_id)

            # Handle free plan
            if plan_config["price"] == 0:
                live = await self._get_live_provider_subscription(db, user_id)
                if live is not None and live.status in BILLING_SUBSCRIPTION_STATUSES:
                    # Downgrading here would clear User.subscription_id and orphan
                    # a subscription that keeps charging with no way to cancel it.
                    return {
                        "success": False,
                        "error": (
                            "Cancel your paid subscription before switching to the free plan."
                        ),
                    }
                if live is not None:
                    # Unpaid ('created'/'authenticated') row — an abandoned
                    # checkout that bills nobody. Close it at the provider
                    # instead of blocking the free plan behind it.
                    if not await self._retire_unpaid_subscription(
                        db,
                        live,
                        reason=concrete_plan_id,
                        require_provider_confirmation=False,
                    ):
                        return {
                            "success": False,
                            "error": (
                                "Could not close your pending checkout. "
                                "Please try again in a moment."
                            ),
                        }
                return await self._create_free_subscription(db, user_id, concrete_plan_id)

            if concrete_plan_id == "student":
                if not student_email or not self._is_student_email(student_email):
                    return {
                        "success": False,
                        "error": "Student plan requires a verified .edu or academic email address",
                    }
                # Student checkout is deliberately a two-step flow: the
                # verification email is sent before a provider subscription
                # exists, and the provider is checked again when the token is
                # redeemed.  Keeping this pre-check out of the request phase
                # also lets invalid student addresses return the normal
                # validation response instead of a misleading billing 503.
                return await self._request_student_verification(
                    db=db,
                    user_id=user_id,
                    customer_email=customer_email,
                    customer_name=customer_name,
                    student_email=student_email,
                )

            coupon_result: Optional[Dict[str, Any]] = None
            if coupon_code:
                coupon_result = await self.validate_coupon(db, coupon_code, concrete_plan_id, user_id=user_id)
                if not coupon_result["valid"]:
                    return {"success": False, "error": coupon_result["message"]}

                if int(coupon_result.get("discount_percent") or 0) > 0 and not coupon_result.get(
                    "offer_id"
                ):
                    # Belt and braces: validate_coupon already refuses a discount
                    # with no Razorpay offer behind it. Never charge full price
                    # while burning the user's one-time redemption.
                    logger.error(
                        f"Coupon {coupon_result['code']} has a "
                        f"{coupon_result['discount_percent']}% discount but no Razorpay "
                        "offer is configured; refusing to charge full price"
                    )
                    return {
                        "success": False,
                        "error": "Coupon codes cannot be applied at checkout right now.",
                    }

            if not self.client:
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            # BILLING: serialise checkout per user. Without this, two concurrent
            # clicks both see "no live subscription" and create two subscriptions.
            if not await self._acquire_checkout_lock(user_id):
                return {
                    "success": False,
                    "error": "A checkout is already in progress for this account.",
                }

            try:
                existing = await self._get_live_provider_subscription(db, user_id)
                if existing is not None:
                    resolved = await self._resolve_existing_subscription(
                        db, existing, concrete_plan_id
                    )
                    if resolved is not None:
                        return resolved

                if coupon_result and coupon_result.get("code"):
                    reserved, reservation_error = await self._reserve_coupon(
                        db,
                        coupon_result["code"],
                        concrete_plan_id,
                        user_id,
                    )
                    if not reserved:
                        # Release the coupon row lock before returning. No provider
                        # object has been created at this point.
                        await db.rollback()
                        return {"success": False, "error": reservation_error}

                result = await self._create_paid_subscription(
                    db=db,
                    user_id=user_id,
                    concrete_plan_id=concrete_plan_id,
                    customer_email=customer_email,
                    customer_name=customer_name,
                    coupon_code=(coupon_result or {}).get("code"),
                    offer_id=(coupon_result or {}).get("offer_id"),
                )
                if not result.get("success") and coupon_result:
                    # _create_paid_subscription commits the reservation together
                    # with the local subscription only on success. Undo it when a
                    # provider plan cannot be created.
                    await db.rollback()
            finally:
                await self._release_checkout_lock(user_id)

            if result.get("success") and coupon_result:
                result["coupon"] = coupon_result

            return result

        except Exception as e:
            logger.error("Error creating subscription", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {
                "success": False,
                "error": "Failed to create subscription"
            }

    async def _create_free_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        plan_id: str
    ) -> Dict[str, Any]:
        """Create a free subscription."""
        try:
            # Update user to free plan
            stmt = update(User).where(User.id == user_id).values(
                subscription_plan=plan_id,
                subscription_status="active",
                subscription_id=None,
                trial_used=True
            )
            await db.execute(stmt)
            db.add(
                Subscription(
                    user_id=user_id,
                    plan_id=plan_id,
                    status="active",
                    current_period_start=datetime.now(timezone.utc),
                    current_period_end=None,
                )
            )
            await db.commit()

            return {
                "success": True,
                "subscription_id": None,
                "message": "Free plan activated"
            }

        except Exception as e:
            logger.error("Error creating free subscription", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {
                "success": False,
                "error": "Failed to activate free plan"
            }

    async def handle_webhook(
        self,
        db: AsyncSession,
        payload: bytes,
        signature: str,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle Razorpay webhook events.

        ``event_id`` is the ``x-razorpay-event-id`` delivery header when the
        caller has it; replay protection falls back to the signed body itself.
        """
        try:
            if not self.is_available():
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            # Verify webhook signature
            if not self._verify_webhook_signature(payload, signature):
                logger.warning("Invalid webhook signature")
                return {
                    "success": False,
                    "error": "Invalid signature"
                }

            # Parse webhook data
            event_data = json.loads(payload.decode('utf-8'))
            event_type = event_data.get("event")
            event_payload = event_data.get("payload", {})
            # Razorpay nests the object under payload.subscription.entity.
            entity = self._unwrap_entity(event_payload.get("subscription") or {})

            # PAYMENT-001: idempotency — claim deliveries briefly while they
            # run, then retain a completed marker. A processing claim expires
            # so a worker crash cannot suppress provider retries for 24 hours.
            processed_key = self._webhook_idempotency_key(payload, event_data, event_id)
            redis = await get_redis_cache_client()
            claim_token = secrets.token_urlsafe(32)
            was_new = await redis.set(
                processed_key,
                claim_token,
                nx=True,
                ex=WEBHOOK_PROCESSING_TTL_SECONDS,
            )
            if not was_new:
                state = await redis.get(processed_key)
                if isinstance(state, bytes):
                    state = state.decode("utf-8", errors="replace")
                # ``1`` is retained as a completed marker for deployments that
                # still have keys written by the previous implementation.
                if state in {"done", "1"}:
                    logger.info(f"Duplicate webhook delivery skipped: {processed_key}")
                    return {"success": True, "message": "Event already processed"}
                if state == "processing":
                    return {
                        "success": False,
                        "error": "Webhook delivery is already being processed; retry later",
                    }

                # The short claim may have expired between SET and GET. Try
                # once more so a retry can take ownership immediately.
                claim_token = secrets.token_urlsafe(32)
                was_new = await redis.set(
                    processed_key,
                    claim_token,
                    nx=True,
                    ex=WEBHOOK_PROCESSING_TTL_SECONDS,
                )
                if not was_new:
                    return {
                        "success": False,
                        "error": "Webhook delivery is already being processed; retry later",
                    }

            logger.info(f"Processing webhook event: {event_type}")

            try:
                if event_type == "subscription.activated":
                    result = await self._handle_subscription_activated(db, entity)
                elif event_type == "subscription.charged":
                    result = await self._handle_subscription_charged(db, event_payload)
                elif event_type == "subscription.cancelled":
                    result = await self._handle_subscription_cancelled(db, entity)
                elif event_type == "subscription.paused":
                    result = await self._handle_subscription_paused(db, entity)
                elif event_type in ("subscription.halted", "subscription.completed"):
                    result = await self._handle_subscription_ended(
                        db, entity, event_type.split(".", 1)[1]
                    )
                elif event_type == "subscription.pending":
                    result = await self._handle_subscription_pending(db, entity)
                elif event_type == "payment.captured":
                    result = await self._handle_lifetime_payment_captured(db, event_payload)
                elif event_type == "payment.failed":
                    result = await self._handle_lifetime_payment_failed(db, event_payload)
                elif event_type in ("refund.created", "refund.processed", "payment.refunded"):
                    result = await self._handle_lifetime_refund(db, event_payload)
                else:
                    logger.info(f"Unhandled webhook event: {event_type}")
                    result = {"success": True, "message": "Event ignored"}
            except Exception:
                # Release only our claim. If the lease expired and another
                # worker reclaimed the delivery, deleting by key would erase
                # that worker's claim and allow a third duplicate handler in.
                await redis.eval(
                    _WEBHOOK_RELEASE_SCRIPT,
                    1,
                    processed_key,
                    claim_token,
                )
                raise

            if result.get("success"):
                # Only successful handling gets the long-lived replay marker.
                await redis.eval(
                    _WEBHOOK_PROMOTE_SCRIPT,
                    1,
                    processed_key,
                    claim_token,
                    "done",
                    WEBHOOK_DONE_TTL_SECONDS,
                )
            else:
                # Explicit handler failures are retryable and release the
                # short-lived claim immediately, but never release a newer
                # worker's claim if ours expired during handler execution.
                await redis.eval(
                    _WEBHOOK_RELEASE_SCRIPT,
                    1,
                    processed_key,
                    claim_token,
                )

            return result

        except Exception as e:
            logger.error("Error handling webhook", extra={"error_type": type(e).__name__})
            return {
                "success": False,
                "error": "Webhook processing failed"
            }

    async def _handle_lifetime_payment_captured(
        self, db: AsyncSession, event_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Activate a lifetime entitlement only for an exact paid order.

        Razorpay amounts are minor units (paise); both amount and currency are
        checked against operator config before a plan is granted.
        """
        payment_entity = self._unwrap_entity(event_payload.get("payment") or {})
        order_entity = self._unwrap_entity(event_payload.get("order") or {})
        payment_id = payment_entity.get("id")
        order_id = payment_entity.get("order_id") or order_entity.get("id")
        if not order_id or not payment_id:
            return {"success": False, "error": "Lifetime payment is missing order or payment ID"}

        amount = int(payment_entity.get("amount") or order_entity.get("amount") or 0)
        currency = str(payment_entity.get("currency") or order_entity.get("currency") or "").upper()

        # The provider can commit an order before the local transaction does.
        # Reconcile that crash window from the server-authored provider notes
        # before treating a signed payment as an unknown order.  Roll back the
        # read transaction so the handler's explicit transaction starts cleanly.
        tracked = await db.scalar(
            select(Subscription.id).where(
                Subscription.razorpay_subscription_id == order_id,
                Subscription.plan_id == "lifetime",
            )
        )
        await db.rollback()
        if tracked is None:
            recovered = await self._recover_missing_lifetime_order(
                db, order_id, amount, currency
            )
            if not recovered:
                logger.info("Ignoring payment for unknown/non-Latexy order %s", order_id)
                return {"success": True, "message": "Payment order not tracked"}

        async with db.begin():
            duplicate = await db.execute(
                select(
                    Payment.id,
                    Payment.amount,
                    Payment.currency,
                    Subscription.razorpay_subscription_id,
                ).where(
                    Payment.razorpay_payment_id == payment_id,
                    Payment.subscription_id == Subscription.id,
                )
            )
            existing_payment = duplicate.one_or_none()
            existing_payment_id = existing_payment[0] if existing_payment else None
            if existing_payment is not None:
                if (
                    existing_payment[3] != order_id
                    or int(existing_payment[1]) != amount
                    or str(existing_payment[2]).upper() != currency
                ):
                    return {"success": False, "error": "Lifetime payment does not match recorded order"}
                # The payment transaction and referral qualification are
                # intentionally separate. A transient referral failure must be
                # retried even after the payment row already exists.
                payment_row_id = existing_payment_id
            else:
                payment_row_id = None

            if payment_row_id is None:
                result = await db.execute(
                    select(Subscription.id, Subscription.user_id, Subscription.status).where(
                        Subscription.razorpay_subscription_id == order_id,
                        Subscription.plan_id == "lifetime",
                    )
                )
                row = result.one_or_none()
                if row is None:
                    # payment.captured may also be enabled for unrelated provider
                    # integrations. Ignore orders not created by this service; a
                    # signed provider event must not become an entitlement without
                    # a local order intent.
                    logger.info("Ignoring payment for unknown/non-Latexy order %s", order_id)
                    return {"success": True, "message": "Payment order not tracked"}
                subscription_id, user_id, local_status = row
                expected = get_plan_config("lifetime")
                if amount != int(expected.get("price") or 0) or currency != str(expected.get("currency")).upper():
                    logger.error("Rejecting lifetime payment with unexpected amount/currency for %s", order_id)
                    return {"success": False, "error": "Lifetime payment amount or currency mismatch"}
                payment_row = Payment(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    razorpay_payment_id=payment_id,
                    amount=amount,
                    currency=currency,
                    status="paid",
                    payment_method=payment_entity.get("method"),
                )
                db.add(payment_row)
                await db.flush()
                payment_row_id = payment_row.id
                await db.execute(
                    update(Subscription).where(Subscription.id == subscription_id).values(status="active")
                )
                await db.execute(
                    update(User).where(User.id == user_id).values(
                        subscription_plan="lifetime",
                        subscription_status="active",
                        subscription_id=order_id,
                    )
                )

        record_business_event("payment", "success")
        try:
            await referral_service.qualify_paid_payment(db, payment_row_id)
        except Exception as exc:
            logger.error("Referral qualification failed for payment %s", payment_row_id, extra={"error_type": type(exc).__name__})
            await db.rollback()
            return {"success": False, "error": "Referral qualification could not be completed"}
        if existing_payment_id is not None:
            return {"success": True, "message": "Payment already recorded"}
        return {"success": True, "message": "Lifetime plan activated"}

    async def _handle_lifetime_payment_failed(
        self, db: AsyncSession, event_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        payment_entity = self._unwrap_entity(event_payload.get("payment") or {})
        order_id = payment_entity.get("order_id")
        if not order_id:
            return {"success": True, "message": "Payment failure without a tracked order"}
        async with db.begin():
            result = await db.execute(
                select(Subscription.user_id, Subscription.status).where(
                    Subscription.razorpay_subscription_id == order_id,
                    Subscription.plan_id == "lifetime",
                )
            )
            row = result.one_or_none()
            if row:
                user_id, local_status = row
            else:
                user_id, local_status = None, None

            # A failed payment attempt can arrive after a successful capture
            # for the same order (for example, when multiple checkout attempts
            # race). Never let that stale failure revoke a paid entitlement.
            # Only an order still waiting for its first capture can transition
            # to failed.
            if user_id and local_status in {"created", "pending"}:
                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == order_id,
                        Subscription.plan_id == "lifetime",
                    ).values(status="failed")
                )
                await db.execute(
                    update(User).where(
                        User.id == user_id,
                        User.subscription_id == order_id,
                    ).values(subscription_status="failed", subscription_id=None)
                )
        return {"success": True, "message": "Lifetime payment failed"}

    async def _handle_lifetime_refund(
        self, db: AsyncSession, event_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        refund = self._unwrap_entity(event_payload.get("refund") or {})
        payment_entity = self._unwrap_entity(event_payload.get("payment") or {})
        payment_id = refund.get("payment_id") or payment_entity.get("id")
        if not payment_id:
            return {"success": False, "error": "Refund is missing payment ID"}
        async with db.begin():
            result = await db.execute(
                select(
                    Payment.subscription_id,
                    Payment.user_id,
                    Payment.amount,
                    Payment.currency,
                    Subscription.razorpay_subscription_id,
                ).where(
                    Payment.razorpay_payment_id == payment_id,
                    Payment.subscription_id == Subscription.id,
                )
            )
            row = result.one_or_none()
            if row is None:
                return {"success": True, "message": "Refund payment not tracked"}
            subscription_id, user_id, original_amount, original_currency, provider_order_id = row

            # ``refund.created`` is not a terminal entitlement signal and a
            # processed refund may be partial. Razorpay's payment entity exposes
            # cumulative ``amount_refunded``/``refund_status``; revoke only when
            # those fields (or an exact full processed refund) prove that the
            # entire locally-recorded payment was returned.
            refund_currency = str(
                payment_entity.get("currency") or refund.get("currency") or ""
            ).upper()
            if refund_currency and refund_currency != str(original_currency).upper():
                logger.error("Ignoring refund with unexpected currency for %s", payment_id)
                return {"success": False, "error": "Refund currency mismatch"}

            payment_status = str(payment_entity.get("status") or "").lower()
            provider_refund_status = str(payment_entity.get("refund_status") or "").lower()
            refund_status = str(refund.get("status") or "").lower()
            amount_refunded = payment_entity.get("amount_refunded")
            is_full_refund = payment_status == "refunded" or provider_refund_status == "full"
            if amount_refunded is not None:
                is_full_refund = is_full_refund or int(amount_refunded) >= int(original_amount)
            elif refund_status == "processed" and refund.get("amount") is not None:
                is_full_refund = int(refund.get("amount") or 0) >= int(original_amount)

                # A processed refund entity carries only that refund's amount,
                # not the cumulative total. When it is smaller than the charge,
                # fetch the payment so multiple partial refunds can eventually
                # produce a verified full-refund transition.
                if not is_full_refund and self.client:
                    try:
                        provider_payment = self.client.payment.fetch(payment_id)
                    except Exception as exc:
                        logger.warning(
                            "Could not verify cumulative refund for %s: %s",
                            payment_id,
                            exc,
                        )
                        return {"success": False, "error": "Refund status could not be verified"}
                    provider_currency = str(provider_payment.get("currency") or "").upper()
                    if provider_currency and provider_currency != str(original_currency).upper():
                        return {"success": False, "error": "Refund currency mismatch"}
                    is_full_refund = (
                        str(provider_payment.get("status") or "").lower() == "refunded"
                        or str(provider_payment.get("refund_status") or "").lower() == "full"
                        or int(provider_payment.get("amount_refunded") or 0) >= int(original_amount)
                    )

            if not is_full_refund:
                # Keep a truthful local audit state without revoking access.
                # A later full-refund webhook has its own delivery id and will
                # perform the terminal transition.
                await db.execute(
                    update(Payment)
                    .where(Payment.razorpay_payment_id == payment_id)
                    .values(status="partially_refunded" if refund_status == "processed" else "paid")
                )
                return {"success": True, "message": "Partial or pending refund recorded"}

            await db.execute(
                update(Payment).where(Payment.razorpay_payment_id == payment_id).values(status="refunded")
            )
            if subscription_id:
                await db.execute(
                    update(Subscription).where(
                        Subscription.id == subscription_id,
                    ).values(status="refunded", cancelled_at=datetime.now(timezone.utc))
                )
                plan_result = await db.execute(
                    select(Subscription.plan_id).where(Subscription.id == subscription_id)
                )
                plan_id = plan_result.scalar_one_or_none()
                await db.execute(
                    update(User).where(
                        User.id == user_id,
                        User.subscription_plan == plan_id,
                        # A delayed refund for an old lifetime order must not
                        # revoke a later lifetime purchase on the same account.
                        User.subscription_id == provider_order_id,
                    ).values(subscription_plan="free", subscription_status="refunded", subscription_id=None)
                )
        await referral_service.reverse_paid_payment(db, payment_id)
        return {"success": True, "message": "Entitlement revoked after refund"}

    def _period_delta_for_plan(self, plan_id: Optional[str]) -> timedelta:
        """Return the billing period length derived from the plan's interval."""
        plan_config = get_plan_config(plan_id) or {}
        interval = plan_config.get("interval")
        if interval == "week":
            return timedelta(days=7)
        if interval == "year":
            return timedelta(days=365)
        # Lifetime is intentionally non-expiring. Callers that use this helper
        # for one-time purchases should leave current_period_end NULL.
        return timedelta(days=30)

    def _webhook_idempotency_key(
        self,
        payload: bytes,
        event_data: Dict[str, Any],
        event_id: Optional[str],
    ) -> str:
        """Return the replay-protection key for one webhook delivery.

        Razorpay does not put a delivery id in the webhook body — it ships in
        the ``x-razorpay-event-id`` header. When that header is unavailable we
        key off a digest of the signed body, which is byte-identical across
        Razorpay's retries of an event and different for every distinct event.
        """
        delivery_id = (event_id or event_data.get("id") or "").strip()
        if delivery_id:
            return f"latexy:webhook:processed:{delivery_id}"
        return f"latexy:webhook:processed:sha256:{hashlib.sha256(payload).hexdigest()}"

    def _verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Razorpay webhook signature."""
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            logger.error("Webhook secret not configured")
            return False

        if not signature:
            return False

        try:
            expected_signature = hmac.new(
                settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()

            # Compare as bytes: compare_digest rejects non-ASCII str inputs, and
            # an attacker controls the header value. Encoding keeps the compare
            # constant-time for any header content.
            return hmac.compare_digest(
                signature.strip().encode("utf-8"),
                expected_signature.encode("utf-8"),
            )
        except Exception as e:
            logger.error("Error verifying webhook signature", extra={"error_type": type(e).__name__})
            return False

    async def _handle_subscription_activated(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription activated event."""
        try:
            subscription_id = entity.get("id")
            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            tracked = await db.scalar(
                select(Subscription.id).where(
                    Subscription.razorpay_subscription_id == subscription_id
                )
            )
            await db.rollback()
            if tracked is None and not await self._recover_missing_subscription_intent(
                db, entity
            ):
                logger.warning("Subscription not found: %s", subscription_id)
                return {"success": False, "error": "Subscription not found"}

            # DB-012: wrap update + dependent update in a single explicit transaction
            async with db.begin():
                # Fetch user_id first so we can update User without a second SELECT
                sub_result = await db.execute(
                    select(
                        Subscription.user_id,
                        Subscription.plan_id,
                        Subscription.status,
                    ).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                sub_row = sub_result.one_or_none()
                if sub_row is None:
                    logger.warning(f"Subscription not found: {subscription_id}")
                    return {"success": False, "error": "Subscription not found"}
                user_id_row, plan_id, local_status = sub_row
                if local_status == SCHEDULED_CANCEL_STATUS:
                    logger.info(
                        f"Ignoring stale activation for cancellation-scheduled {subscription_id}"
                    )
                    return {
                        "success": True,
                        "message": "Subscription cancellation remains scheduled",
                    }

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(
                        status="active",
                        current_period_start=datetime.now(timezone.utc),
                        # Derive period length from the plan interval so annual
                        # plans do not get a 30-day period.
                        current_period_end=datetime.now(timezone.utc) + self._period_delta_for_plan(plan_id),
                    )
                )
                # Razorpay's weekly subscription activation is mandate setup;
                # require the first captured charge before granting B57 access.
                if plan_id != "weekly":
                    user_update = await db.execute(
                        update(User).where(
                            User.id == user_id_row,
                            User.subscription_id == subscription_id,
                        ).values(
                            subscription_plan=plan_id,
                            subscription_status="active",
                        )
                    )
                else:
                    user_update = None
                # A late activation for an old subscription must not overwrite
                # the account's newer provider pointer. Team-seat restoration is
                # tied to the same guard for the same reason.
                if user_update is not None and user_update.rowcount and resolve_plan_family(plan_id) == "team":
                    await self._restore_team_seats(db, user_id_row)
            # db.begin() context manager commits on exit

            record_business_event("subscription", "activated")
            logger.info(f"Subscription activated: {subscription_id}")
            return {"success": True, "message": "Subscription activated"}

        except Exception as e:
            logger.error("Error handling subscription activation", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to activate subscription"}

    @staticmethod
    def _unwrap_entity(wrapper: Dict[str, Any]) -> Dict[str, Any]:
        """Return the Razorpay ``entity`` sub-object if present, else the dict.

        Razorpay nests the real object under ``payload.<type>.entity``; some
        callers/tests pass the flattened dict directly.
        """
        inner = wrapper.get("entity")
        return inner if isinstance(inner, dict) else wrapper

    async def _recover_missing_subscription_intent(
        self, db: AsyncSession, entity: Dict[str, Any]
    ) -> bool:
        """Recover a provider subscription whose local insert lost a crash race.

        The provider object and its server-authored notes are required; an
        arbitrary subscription event can never select a user from event data
        alone. This closes the provider-created-before-DB-commit window while
        retaining the existing unknown-subscription rejection behavior.
        """
        subscription_id = entity.get("id")
        if not subscription_id or not self.client:
            return False
        provider = self._fetch_provider_subscription(subscription_id)
        if not provider:
            return False
        if str(provider.get("id") or "") != str(subscription_id):
            logger.warning("Provider subscription lookup returned a mismatched ID for %s", subscription_id)
            return False
        # Only trust notes read back from Razorpay.  The signed event is useful
        # for routing, but its user/plan fields must not become an alternate
        # client-controlled identity source.
        notes = provider.get("notes") or {}
        user_id = notes.get("user_id")
        plan_id = str(notes.get("plan_id") or "").strip().lower()
        if not user_id or plan_id not in settings.SUBSCRIPTION_PLANS or plan_id in {"free", "lifetime"}:
            return False
        configured_provider_plan = get_razorpay_plan_id(plan_id)
        if configured_provider_plan and provider.get("plan_id") and provider.get("plan_id") != configured_provider_plan:
            return False

        try:
            async with db.begin():
                existing = await db.scalar(
                    select(Subscription.id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                if existing:
                    return True
                # Serialize recovery for this account.  Without a user-row lock,
                # two webhook workers could both observe no live subscription
                # and insert competing provider subscriptions before either
                # commit becomes visible.
                user = await db.scalar(
                    select(User).where(User.id == user_id).with_for_update()
                )
                if user is None:
                    return False
                live = await self._get_live_provider_subscription(db, user_id)
                if live is not None and live.razorpay_subscription_id != subscription_id:
                    return False
                now = datetime.now(timezone.utc)
                db.add(
                    Subscription(
                        user_id=user_id,
                        razorpay_subscription_id=subscription_id,
                        plan_id=plan_id,
                        status="created",
                        current_period_start=now,
                        current_period_end=now + self._period_delta_for_plan(plan_id),
                    )
                )
                await db.execute(
                    update(User).where(User.id == user_id).values(
                        subscription_status="created", subscription_id=subscription_id
                    )
                )
            return True
        except Exception:
            await db.rollback()
            raise

    async def _recover_missing_lifetime_order(
        self,
        db: AsyncSession,
        order_id: str,
        amount: int,
        currency: str,
    ) -> bool:
        """Recover a paid Lifetime order created before its local row committed."""
        if not self.client:
            return False
        try:
            order = self.client.order.fetch(order_id)
        except Exception:
            # A provider read failure is retryable; do not classify it as an
            # unknown order and permanently acknowledge the webhook.
            raise
        expected = get_plan_config("lifetime")
        if (
            str(order.get("id") or "") != order_id
            or int(order.get("amount") or 0) != int(expected.get("price") or 0)
            or str(order.get("currency") or "").upper() != str(expected.get("currency") or "").upper()
        ):
            return False
        notes = order.get("notes") or {}
        user_id = notes.get("user_id")
        if notes.get("plan_id") != "lifetime" or not user_id:
            return False
        if amount != int(expected.get("price") or 0) or currency != str(expected.get("currency") or "").upper():
            return False
        async with db.begin():
            # Serialize one-time and recurring recovery for the account so a
            # pair of webhook workers cannot both pass the live-subscription
            # check before inserting their provider-backed rows.
            user = await db.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if user is None:
                return False
            existing = await db.scalar(
                select(Subscription.id).where(
                    Subscription.razorpay_subscription_id == order_id,
                    Subscription.plan_id == "lifetime",
                )
            )
            if existing:
                return True
            live = await self._get_live_provider_subscription(db, user_id)
            if live is not None and live.razorpay_subscription_id != order_id:
                return False
            db.add(
                Subscription(
                    user_id=user_id,
                    razorpay_subscription_id=order_id,
                    plan_id="lifetime",
                    status="created",
                    current_period_start=datetime.now(timezone.utc),
                )
            )
            await db.execute(
                update(User).where(User.id == user_id).values(
                    subscription_status="pending", subscription_id=order_id
                )
            )
        return True

    async def _handle_subscription_charged(
        self,
        db: AsyncSession,
        event_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription charged event (initial charge and renewals)."""
        try:
            sub_entity = self._unwrap_entity(event_payload.get("subscription") or {})
            payment_entity = self._unwrap_entity(event_payload.get("payment") or {})
            subscription_id = sub_entity.get("id")

            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            tracked = await db.scalar(
                select(Subscription.id).where(
                    Subscription.razorpay_subscription_id == subscription_id
                )
            )
            await db.rollback()
            if tracked is None and not await self._recover_missing_subscription_intent(
                db, sub_entity
            ):
                logger.warning("Subscription not found: %s", subscription_id)
                return {"success": False, "error": "Subscription not found"}

            async with db.begin():
                sub_result = await db.execute(
                    select(
                        Subscription.id,
                        Subscription.user_id,
                        Subscription.plan_id,
                        Subscription.status,
                        Subscription.current_period_end,
                    ).where(Subscription.razorpay_subscription_id == subscription_id)
                )
                sub_row = sub_result.one_or_none()
                if sub_row is None:
                    logger.warning(f"Subscription not found for charge: {subscription_id}")
                    return {"success": False, "error": "Subscription not found"}
                local_sub_id, user_id_row, plan_id, local_status, current_period_end = sub_row

                # The payment lives under payload.payment.entity for charged
                # events (NOT subscription.latest_invoice).
                razorpay_payment_id = payment_entity.get("id")
                if not razorpay_payment_id:
                    return {"success": False, "error": "Subscription charge is missing payment ID"}

                if plan_id == "weekly":
                    expected = get_plan_config("weekly")
                    if (
                        int(payment_entity.get("amount") or 0) != int(expected.get("price") or 0)
                        or str(payment_entity.get("currency") or "").upper()
                        != str(expected.get("currency") or "").upper()
                    ):
                        logger.error("Rejecting weekly charge with unexpected amount/currency: %s", subscription_id)
                        return {"success": False, "error": "Weekly payment amount or currency mismatch"}

                # Dedupe on the real Razorpay payment id — retries/races must not
                # create duplicate payment rows.
                existing_payment_id = None
                if razorpay_payment_id:
                    existing = await db.execute(
                        select(Payment.id).where(
                            Payment.razorpay_payment_id == razorpay_payment_id
                        )
                    )
                    existing_payment_id = existing.scalar_one_or_none()

                if existing_payment_id is None:
                    payment_row = Payment(
                        user_id=user_id_row,
                        subscription_id=local_sub_id,
                        razorpay_payment_id=razorpay_payment_id,
                        amount=int(payment_entity.get("amount") or 0),
                        currency=payment_entity.get("currency") or "INR",
                        status="paid",
                        payment_method=payment_entity.get("method"),
                    )
                    db.add(payment_row)
                    await db.flush()
                    payment_row_id = payment_row.id
                else:
                    logger.info(f"Payment already recorded: {razorpay_payment_id}")
                    payment_row_id = existing_payment_id

                if local_status != SCHEDULED_CANCEL_STATUS and existing_payment_id is None:
                    # Advance the billing period and re-affirm active status so
                    # renewals extend the stored period instead of letting it lapse.
                    now = datetime.now(timezone.utc)
                    period_base = current_period_end
                    if period_base is not None and period_base.tzinfo is None:
                        period_base = period_base.replace(tzinfo=timezone.utc)
                    if period_base is None or period_base < now:
                        period_base = now
                    await db.execute(
                        update(Subscription).where(
                            Subscription.razorpay_subscription_id == subscription_id
                        ).values(
                            status="active",
                            current_period_start=now,
                            current_period_end=period_base + self._period_delta_for_plan(plan_id),
                        )
                    )
                    user_update = await db.execute(
                        update(User).where(
                            User.id == user_id_row,
                            User.subscription_id == subscription_id,
                        ).values(
                            subscription_plan=plan_id,
                            subscription_status="active",
                        )
                    )
                    if user_update.rowcount and resolve_plan_family(plan_id) == "team":
                        await self._restore_team_seats(db, user_id_row)

            record_business_event("payment", "success")
            try:
                await referral_service.qualify_paid_payment(db, payment_row_id)
            except Exception as exc:
                logger.error("Referral qualification failed for payment %s", payment_row_id, extra={"error_type": type(exc).__name__})
                await db.rollback()
                return {"success": False, "error": "Referral qualification could not be completed"}
            logger.info(f"Payment recorded for subscription: {subscription_id}")
            return {
                "success": True,
                "message": "Payment already recorded" if existing_payment_id is not None else "Payment recorded",
            }

        except Exception as e:
            logger.error("Error handling subscription charge", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to record payment"}

    async def _handle_subscription_ended(
        self,
        db: AsyncSession,
        entity: Dict[str, Any],
        sub_status: str,
    ) -> Dict[str, Any]:
        """Downgrade a user to free when a subscription halts or completes.

        Razorpay emits subscription.halted after repeated renewal failures and
        subscription.completed once the final cycle is billed; in both cases the
        subscription is no longer paying, so the user must lose paid features.
        """
        try:
            subscription_id = entity.get("id")
            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            async with db.begin():
                sub_result = await db.execute(
                    select(Subscription.user_id, Subscription.plan_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                sub_row = sub_result.first()
                if sub_row is None:
                    logger.warning(
                        f"Subscription not found for {sub_status}: {subscription_id}"
                    )
                    return {"success": False, "error": "Subscription not found"}
                user_id_row, plan_id = sub_row

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(status=sub_status)
                )
                user_update = await db.execute(
                    update(User).where(
                        User.id == user_id_row,
                        User.subscription_id == subscription_id,
                    ).values(
                        subscription_plan="free",
                        subscription_status=sub_status,
                        subscription_id=None,
                    )
                )

                if user_update.rowcount and resolve_plan_family(plan_id) == "team":
                    await self._revoke_team_seats(db, user_id_row)

            logger.info(f"Subscription {sub_status}: {subscription_id}")
            return {"success": True, "message": f"Subscription {sub_status}"}

        except Exception as e:
            logger.error("Error handling subscription %s", sub_status, extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": f"Failed to handle {sub_status}"}

    async def _handle_subscription_pending(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mark a subscription pending (renewal failed, awaiting retry)."""
        try:
            subscription_id = entity.get("id")
            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            async with db.begin():
                sub_result = await db.execute(
                    select(Subscription.user_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                user_id_row = sub_result.scalar_one_or_none()

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(status="pending")
                )

                if user_id_row:
                    await db.execute(
                        update(User).where(
                            User.id == user_id_row,
                            User.subscription_id == subscription_id,
                        ).values(
                            subscription_status="pending"
                        )
                    )

            logger.info(f"Subscription pending: {subscription_id}")
            return {"success": True, "message": "Subscription pending"}

        except Exception as e:
            logger.error("Error handling subscription pending", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to handle pending"}

    async def _handle_subscription_cancelled(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription cancelled event."""
        try:
            subscription_id = entity.get("id")
            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            # DB-012: explicit transaction; resolve user_id before updating to avoid extra SELECT
            async with db.begin():
                sub_result = await db.execute(
                    select(Subscription.user_id, Subscription.plan_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                sub_row = sub_result.first()
                if sub_row is None:
                    logger.warning(f"Subscription not found for cancel: {subscription_id}")
                    return {"success": False, "error": "Subscription not found"}
                user_id_row, plan_id = sub_row

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(
                        status="cancelled",
                        cancelled_at=datetime.now(timezone.utc),
                    )
                )
                user_update = await db.execute(
                    update(User).where(
                        User.id == user_id_row,
                        User.subscription_id == subscription_id,
                    ).values(
                        subscription_plan="free",
                        subscription_status="cancelled",
                        subscription_id=None,
                    )
                )

                # A team owner losing their subscription must lose their seats;
                # otherwise members keep team entitlements forever.
                if user_update.rowcount and resolve_plan_family(plan_id) == "team":
                    await self._revoke_team_seats(db, user_id_row)

            record_business_event("subscription", "cancelled")
            logger.info(f"Subscription cancelled: {subscription_id}")
            return {"success": True, "message": "Subscription cancelled"}

        except Exception as e:
            logger.error("Error handling subscription cancellation", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to cancel subscription"}

    async def _handle_subscription_paused(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription paused event."""
        try:
            subscription_id = entity.get("id")
            if not subscription_id:
                return {"success": False, "error": "No subscription ID"}

            # DB-012: explicit transaction; resolve user_id upfront to avoid extra SELECT
            async with db.begin():
                sub_result = await db.execute(
                    select(Subscription.user_id, Subscription.plan_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                sub_row = sub_result.first()

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(status="paused")
                )

                if sub_row:
                    user_id_row, plan_id = sub_row
                    user_update = await db.execute(
                        update(User).where(
                            User.id == user_id_row,
                            User.subscription_id == subscription_id,
                        ).values(
                            subscription_plan="free",
                            subscription_status="paused",
                        )
                    )
                    if user_update.rowcount and resolve_plan_family(plan_id) == "team":
                        await self._suspend_team_seats(db, user_id_row)

            logger.info(f"Subscription paused: {subscription_id}")
            return {"success": True, "message": "Subscription paused"}

        except Exception as e:
            logger.error("Error handling subscription pause", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to pause subscription"}

    async def get_user_subscription(
        self,
        db: AsyncSession,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get user's current subscription."""
        try:
            # Get user
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()

            if not user:
                return None

            # Get subscription details. A user can hold several rows (retried
            # checkout, free -> paid upgrade), so pick the current one instead
            # of blowing up on more than one match.
            subscription = await self._get_current_subscription(
                db, user_id, razorpay_subscription_id=user.subscription_id
            )

            plan_config = get_plan_config(user.subscription_plan)

            return {
                "user_id": user_id,
                "plan_id": user.subscription_plan,
                "plan_name": plan_config.get("name", "Unknown"),
                "status": user.subscription_status,
                "features": plan_config.get("features", {}),
                "subscription_id": user.subscription_id,
                "current_period_end": subscription.current_period_end.isoformat() if subscription and subscription.current_period_end else None
            }

        except Exception as e:
            logger.error("Error getting user subscription", extra={"error_type": type(e).__name__})
            return None

    async def cancel_subscription(
        self,
        db: AsyncSession,
        user_id: str
    ) -> Dict[str, Any]:
        """Cancel user's subscription."""
        try:
            # Get user's subscription
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()

            if not user or not user.subscription_id:
                return {
                    "success": False,
                    "error": "No active subscription found"
                }

            if user.subscription_plan == "lifetime":
                return {
                    "success": False,
                    "error": "Lifetime purchases do not renew. Contact support for refund requests.",
                }

            # BILLING: whether Razorpay has to be told is decided by the
            # subscription row, not by user.subscription_plan. An abandoned
            # checkout deliberately leaves the plan at 'free' while a live
            # provider subscription exists, and that one must still be cancelled.
            live = await self._get_live_provider_subscription(db, user_id)
            provider_subscription_id = live.razorpay_subscription_id if live is not None else None
            if not provider_subscription_id and str(user.subscription_id or "").startswith("sub_"):
                # Local rows can drift from the provider; a Razorpay id parked on
                # the user is still worth cancelling.
                provider_subscription_id = user.subscription_id

            if live is not None and live.status == SCHEDULED_CANCEL_STATUS:
                return {
                    "success": True,
                    "message": "Cancellation is already scheduled for the end of the billing cycle.",
                }

            if provider_subscription_id and not self.is_available():
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            # An unpaid subscription has no billing cycle to run out, so it is
            # cancelled immediately; a paying one runs to cycle end.
            unpaid_checkout = live is not None and live.status in UNPAID_SUBSCRIPTION_STATUSES
            provider_is_terminal = False

            if provider_subscription_id and self.client:
                cancel_at_cycle_end = not unpaid_checkout
                try:
                    self.client.subscription.cancel(
                        provider_subscription_id, {"cancel_at_cycle_end": cancel_at_cycle_end}
                    )
                except Exception as e:
                    logger.error("Error cancelling Razorpay subscription", extra={"error_type": type(e).__name__})
                    # Razorpay also rejects cancels for subscriptions that are
                    # already cancelled/completed/expired. Those have nothing
                    # left to charge, so refusing the local cleanup there would
                    # lock the user out of cancelling forever. Only a genuinely
                    # transient failure leaves the subscription live.
                    if not self._provider_cancel_is_moot(provider_subscription_id):
                        return {
                            "success": False,
                            "error": (
                                "We could not cancel your subscription with the payment "
                                "provider. Please try again or contact support."
                            ),
                        }
                    provider_is_terminal = True

            cancellation_is_scheduled = bool(
                provider_subscription_id and not unpaid_checkout and not provider_is_terminal
            )

            # A paid end-of-cycle cancellation remains live at Razorpay until
            # the current term ends. Mirror that intermediate state locally so
            # entitlements, team seats, and duplicate-checkout protection remain
            # intact. The terminal webhook performs the eventual downgrade.
            local_status = (
                SCHEDULED_CANCEL_STATUS if cancellation_is_scheduled else "cancelled"
            )
            subscription_values: Dict[str, Any] = {"status": local_status}
            if not cancellation_is_scheduled:
                subscription_values["cancelled_at"] = datetime.now(timezone.utc)
            await db.execute(
                update(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                ).values(**subscription_values)
            )

            user_values: Dict[str, Any] = {"subscription_status": local_status}
            if not cancellation_is_scheduled:
                user_values["subscription_plan"] = "free"
                user_values["subscription_id"] = None
            await db.execute(update(User).where(User.id == user_id).values(**user_values))

            # Team access lasts through a paid cancellation's period end.
            if not cancellation_is_scheduled and resolve_plan_family(user.subscription_plan) == "team":
                await self._revoke_team_seats(db, user_id)

            await db.commit()
            if cancellation_is_scheduled:
                return {
                    "success": True,
                    "message": "Cancellation scheduled for the end of the billing cycle.",
                }
            return {"success": True, "message": "Subscription cancelled"}

        except Exception as e:
            logger.error("Error cancelling subscription", extra={"error_type": type(e).__name__})
            await db.rollback()
            return {
                "success": False,
                "error": "Failed to cancel subscription"
            }

# Global service instance
payment_service = PaymentService()

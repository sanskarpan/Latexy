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
    resolve_plan_family,
    settings,
)
from ..core.logging import get_logger
from ..core.observability import record_business_event
from ..core.redis import get_redis_cache_client
from ..database import models as db_models
from .email_service import email_service

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
LIVE_SUBSCRIPTION_STATUSES = ("active", "authenticated", "created", "pending", "paused")

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
        """Get available subscription plans."""
        return dict(settings.SUBSCRIPTION_PLANS)

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

            razorpay_plan = self.client.plan.create({
                "period": "yearly" if plan_config.get("interval") == "year" else "monthly",
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
            logger.error(f"Error creating Razorpay plan for {plan_id}: {e}")
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
        await redis.setex(f"student_plan_verify:{token}", 24 * 3600, json.dumps(payload))

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

            result = await self._create_paid_subscription(
                db=db,
                user_id=user_id,
                concrete_plan_id="student",
                customer_email=payload["customer_email"],
                customer_name=payload["customer_name"],
            )
            if result.get("success"):
                await redis.delete(f"student_plan_verify:{token}")
            return result
        except Exception as exc:
            logger.error(f"Error verifying student subscription: {exc}")
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
            logger.error(f"Error fetching Razorpay subscription {subscription_id}: {e}")
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
                    existing.razorpay_subscription_id, {"cancel_at_cycle_end": 0}
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
            .values(status="cancelled", cancelled_at=datetime.utcnow())
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
            logger.error(f"Could not read back Razorpay subscription {subscription_id}: {exc}")
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
        current_period_end = datetime.utcnow() + (timedelta(days=365) if interval == "year" else timedelta(days=30))
        subscription = self.client.subscription.create({
            "plan_id": razorpay_plan_id,
            "customer_id": customer["id"],
            "total_count": 1 if interval == "year" else 12,
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
                current_period_start=datetime.utcnow(),
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
            logger.error(f"Error creating subscription: {e}")
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
                    current_period_start=datetime.utcnow(),
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
            logger.error(f"Error creating free subscription: {e}")
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

            # PAYMENT-001: idempotency — atomic set-if-absent per delivery.
            # A single SET key NX EX avoids the check-then-act race of
            # SISMEMBER + SADD (two concurrent deliveries could both pass the
            # SISMEMBER before either SADDs). A per-event key also stops the
            # shared-set TTL from being reset on every delivery.
            processed_key = self._webhook_idempotency_key(payload, event_data, event_id)
            redis = await get_redis_cache_client()
            was_new = await redis.set(processed_key, "1", nx=True, ex=86400)
            if not was_new:
                logger.info(f"Duplicate webhook delivery skipped: {processed_key}")
                return {"success": True, "message": "Event already processed"}

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
                else:
                    logger.info(f"Unhandled webhook event: {event_type}")
                    result = {"success": True, "message": "Event ignored"}
            except Exception:
                # Release the idempotency key so a retry can reprocess this event.
                await redis.delete(processed_key)
                raise

            # If handling failed (transient/retryable), release the idempotency
            # key so Razorpay's retry can reprocess the event.
            if not result.get("success"):
                await redis.delete(processed_key)

            return result

        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return {
                "success": False,
                "error": "Webhook processing failed"
            }

    def _period_delta_for_plan(self, plan_id: Optional[str]) -> timedelta:
        """Return the billing period length derived from the plan's interval."""
        plan_config = get_plan_config(plan_id) or {}
        return timedelta(days=365) if plan_config.get("interval") == "year" else timedelta(days=30)

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
            logger.error(f"Error verifying webhook signature: {e}")
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

            # DB-012: wrap update + dependent update in a single explicit transaction
            async with db.begin():
                # Fetch user_id first so we can update User without a second SELECT
                sub_result = await db.execute(
                    select(Subscription.user_id, Subscription.plan_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                sub_row = sub_result.one_or_none()
                if sub_row is None:
                    logger.warning(f"Subscription not found: {subscription_id}")
                    return {"success": False, "error": "Subscription not found"}
                user_id_row, plan_id = sub_row

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(
                        status="active",
                        current_period_start=datetime.utcnow(),
                        # Derive period length from the plan interval so annual
                        # plans do not get a 30-day period.
                        current_period_end=datetime.utcnow() + self._period_delta_for_plan(plan_id),
                    )
                )
                # Grant the paid plan now that payment is confirmed (post-activation).
                await db.execute(
                    update(User).where(User.id == user_id_row).values(
                        subscription_plan=plan_id,
                        subscription_status="active",
                    )
                )
            # db.begin() context manager commits on exit

            record_business_event("subscription", "activated")
            logger.info(f"Subscription activated: {subscription_id}")
            return {"success": True, "message": "Subscription activated"}

        except Exception as e:
            logger.error(f"Error handling subscription activation: {e}")
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

            async with db.begin():
                sub_result = await db.execute(
                    select(
                        Subscription.id, Subscription.user_id, Subscription.plan_id
                    ).where(Subscription.razorpay_subscription_id == subscription_id)
                )
                sub_row = sub_result.one_or_none()
                if sub_row is None:
                    logger.warning(f"Subscription not found for charge: {subscription_id}")
                    return {"success": False, "error": "Subscription not found"}
                local_sub_id, user_id_row, plan_id = sub_row

                # The payment lives under payload.payment.entity for charged
                # events (NOT subscription.latest_invoice).
                razorpay_payment_id = payment_entity.get("id")

                # Dedupe on the real Razorpay payment id — retries/races must not
                # create duplicate payment rows.
                if razorpay_payment_id:
                    existing = await db.execute(
                        select(Payment.id).where(
                            Payment.razorpay_payment_id == razorpay_payment_id
                        )
                    )
                    if existing.scalar_one_or_none() is not None:
                        logger.info(f"Payment already recorded: {razorpay_payment_id}")
                        return {"success": True, "message": "Payment already recorded"}

                db.add(
                    Payment(
                        user_id=user_id_row,
                        subscription_id=local_sub_id,
                        razorpay_payment_id=razorpay_payment_id,
                        amount=int(payment_entity.get("amount") or 0),
                        currency=payment_entity.get("currency") or "INR",
                        status="paid",
                        payment_method=payment_entity.get("method"),
                    )
                )

                # Advance the billing period and re-affirm active status so
                # renewals extend the stored period instead of letting it lapse.
                now = datetime.utcnow()
                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(
                        status="active",
                        current_period_start=now,
                        current_period_end=now + self._period_delta_for_plan(plan_id),
                    )
                )
                await db.execute(
                    update(User).where(User.id == user_id_row).values(
                        subscription_plan=plan_id,
                        subscription_status="active",
                    )
                )

            record_business_event("payment", "success")
            logger.info(f"Payment recorded for subscription: {subscription_id}")
            return {"success": True, "message": "Payment recorded"}

        except Exception as e:
            logger.error(f"Error handling subscription charge: {e}")
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
                await db.execute(
                    update(User).where(User.id == user_id_row).values(
                        subscription_plan="free",
                        subscription_status=sub_status,
                    )
                )

                if resolve_plan_family(plan_id) == "team":
                    await self._revoke_team_seats(db, user_id_row)

            logger.info(f"Subscription {sub_status}: {subscription_id}")
            return {"success": True, "message": f"Subscription {sub_status}"}

        except Exception as e:
            logger.error(f"Error handling subscription {sub_status}: {e}")
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
                        update(User).where(User.id == user_id_row).values(
                            subscription_status="pending"
                        )
                    )

            logger.info(f"Subscription pending: {subscription_id}")
            return {"success": True, "message": "Subscription pending"}

        except Exception as e:
            logger.error(f"Error handling subscription pending: {e}")
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
                        cancelled_at=datetime.utcnow(),
                    )
                )
                await db.execute(
                    update(User).where(User.id == user_id_row).values(
                        subscription_plan="free",
                        subscription_status="cancelled",
                    )
                )

                # A team owner losing their subscription must lose their seats;
                # otherwise members keep team entitlements forever.
                if resolve_plan_family(plan_id) == "team":
                    await self._revoke_team_seats(db, user_id_row)

            record_business_event("subscription", "cancelled")
            logger.info(f"Subscription cancelled: {subscription_id}")
            return {"success": True, "message": "Subscription cancelled"}

        except Exception as e:
            logger.error(f"Error handling subscription cancellation: {e}")
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
                    select(Subscription.user_id).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                user_id_row = sub_result.scalar_one_or_none()

                await db.execute(
                    update(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    ).values(status="paused")
                )

                if user_id_row:
                    await db.execute(
                        update(User).where(User.id == user_id_row).values(
                            subscription_status="paused"
                        )
                    )

            logger.info(f"Subscription paused: {subscription_id}")
            return {"success": True, "message": "Subscription paused"}

        except Exception as e:
            logger.error(f"Error handling subscription pause: {e}")
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
            logger.error(f"Error getting user subscription: {e}")
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

            if provider_subscription_id and not self.is_available():
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            # An unpaid subscription has no billing cycle to run out, so it is
            # cancelled immediately; a paying one runs to cycle end.
            unpaid_checkout = live is not None and live.status in UNPAID_SUBSCRIPTION_STATUSES

            if provider_subscription_id and self.client:
                cancel_at_cycle_end = 0 if unpaid_checkout else 1
                try:
                    self.client.subscription.cancel(
                        provider_subscription_id, {"cancel_at_cycle_end": cancel_at_cycle_end}
                    )
                except Exception as e:
                    logger.error(f"Error cancelling Razorpay subscription: {e}")
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

            # Update local records for the live subscriptions only; already
            # cancelled/completed history keeps its original status.
            await db.execute(
                update(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                ).values(
                    status="cancelled",
                    cancelled_at=datetime.utcnow()
                )
            )

            user_values: Dict[str, Any] = {"subscription_status": "cancelled"}
            if unpaid_checkout:
                # The checkout died immediately, so nothing points at it any
                # more; a paying subscription keeps its id until the cycle ends.
                user_values["subscription_id"] = None
            await db.execute(update(User).where(User.id == user_id).values(**user_values))

            # Team owners lose their seats with their subscription.
            if resolve_plan_family(user.subscription_plan) == "team":
                await self._revoke_team_seats(db, user_id)

            await db.commit()
            return {"success": True, "message": "Subscription cancelled"}

        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            await db.rollback()
            return {
                "success": False,
                "error": "Failed to cancel subscription"
            }

# Global service instance
payment_service = PaymentService()

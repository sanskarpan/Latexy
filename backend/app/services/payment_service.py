"""Payment service for Razorpay integration and subscription management."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import razorpay as _razorpay_module
except (ImportError, ModuleNotFoundError):
    _razorpay_module = None  # type: ignore[assignment]

from ..core.config import (
    get_plan_config,
    get_razorpay_plan_id,
    resolve_plan_family,
    settings,
)
from ..core.logging import get_logger
from ..core.redis import get_redis_cache_client
from ..database.models import CouponCode, CouponRedemption, Payment, Subscription, User
from .email_service import email_service

logger = get_logger(__name__)

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
                await db.execute(
                    update(User).where(User.id == user_id).values(
                        subscription_plan="student",
                        subscription_status="active",
                    )
                )
                db.add(
                    Subscription(
                        user_id=user_id,
                        plan_id="student",
                        status="active",
                        current_period_start=datetime.utcnow(),
                        current_period_end=datetime.utcnow() + timedelta(days=30),
                    )
                )
                await db.commit()
                await redis.delete(f"student_plan_verify:{token}")
                return {"success": True, "message": "Student plan activated"}

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

        return {
            "valid": True,
            "code": normalized_code,
            "discount_percent": int(coupon.discount_percent),
            "message": "Coupon applied",
            "already_redeemed": already_redeemed,
        }

    async def _create_paid_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        concrete_plan_id: str,
        customer_email: str,
        customer_name: str,
        coupon_code: Optional[str] = None,
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
        await db.execute(
            update(User).where(User.id == user_id).values(
                subscription_plan=concrete_plan_id,
                subscription_status="created",
                subscription_id=subscription["id"],
            )
        )
        await db.commit()

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

            # Handle free plan
            if plan_config["price"] == 0:
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

            if not self.client:
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            result = await self._create_paid_subscription(
                db=db,
                user_id=user_id,
                concrete_plan_id=concrete_plan_id,
                customer_email=customer_email,
                customer_name=customer_name,
                coupon_code=(coupon_result or {}).get("code"),
            )

            if result.get("success") and coupon_result and coupon_result.get("code"):
                coupon_row_result = await db.execute(
                    select(CouponCode).where(CouponCode.code == coupon_result["code"])
                )
                coupon_row = coupon_row_result.scalar_one_or_none()
                if coupon_row and not coupon_result.get("already_redeemed"):
                    coupon_row.used_count = int(coupon_row.used_count or 0) + 1
                    db.add(CouponRedemption(coupon_id=coupon_row.id, user_id=user_id))
                    await db.commit()
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
        signature: str
    ) -> Dict[str, Any]:
        """Handle Razorpay webhook events."""
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
            entity = event_data.get("payload", {}).get("subscription", {})

            logger.info(f"Processing webhook event: {event_type}")

            if event_type == "subscription.activated":
                return await self._handle_subscription_activated(db, entity)
            elif event_type == "subscription.charged":
                return await self._handle_subscription_charged(db, entity)
            elif event_type == "subscription.cancelled":
                return await self._handle_subscription_cancelled(db, entity)
            elif event_type == "subscription.paused":
                return await self._handle_subscription_paused(db, entity)
            else:
                logger.info(f"Unhandled webhook event: {event_type}")
                return {"success": True, "message": "Event ignored"}

        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return {
                "success": False,
                "error": "Webhook processing failed"
            }

    def _verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Razorpay webhook signature."""
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            logger.error("Webhook secret not configured")
            return False

        try:
            expected_signature = hmac.new(
                settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(signature, expected_signature)
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

            # Update subscription status
            stmt = update(Subscription).where(
                Subscription.razorpay_subscription_id == subscription_id
            ).values(
                status="active",
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=30)
            )
            result = await db.execute(stmt)

            if result.rowcount > 0:
                # Update user status
                subscription_result = await db.execute(
                    select(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                subscription = subscription_result.scalar_one_or_none()

                if subscription:
                    await db.execute(
                        update(User).where(User.id == subscription.user_id).values(
                            subscription_status="active"
                        )
                    )

                await db.commit()
                logger.info(f"Subscription activated: {subscription_id}")
                return {"success": True, "message": "Subscription activated"}
            else:
                logger.warning(f"Subscription not found: {subscription_id}")
                return {"success": False, "error": "Subscription not found"}

        except Exception as e:
            logger.error(f"Error handling subscription activation: {e}")
            await db.rollback()
            return {"success": False, "error": "Failed to activate subscription"}

    async def _handle_subscription_charged(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription charged event."""
        try:
            subscription_id = entity.get("id")
            payment_data = entity.get("latest_invoice", {})

            # Create payment record
            payment = Payment(
                subscription_id=subscription_id,
                razorpay_payment_id=payment_data.get("payment_id"),
                amount=payment_data.get("amount", 0),
                currency=payment_data.get("currency", "INR"),
                status="paid",
                payment_method=payment_data.get("method")
            )
            db.add(payment)
            await db.commit()

            logger.info(f"Payment recorded for subscription: {subscription_id}")
            return {"success": True, "message": "Payment recorded"}

        except Exception as e:
            logger.error(f"Error handling subscription charge: {e}")
            await db.rollback()
            return {"success": False, "error": "Failed to record payment"}

    async def _handle_subscription_cancelled(
        self,
        db: AsyncSession,
        entity: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription cancelled event."""
        try:
            subscription_id = entity.get("id")

            # Update subscription status
            stmt = update(Subscription).where(
                Subscription.razorpay_subscription_id == subscription_id
            ).values(
                status="cancelled",
                cancelled_at=datetime.utcnow()
            )
            result = await db.execute(stmt)

            if result.rowcount > 0:
                # Update user status to free
                subscription_result = await db.execute(
                    select(Subscription).where(
                        Subscription.razorpay_subscription_id == subscription_id
                    )
                )
                subscription = subscription_result.scalar_one_or_none()

                if subscription:
                    await db.execute(
                        update(User).where(User.id == subscription.user_id).values(
                            subscription_plan="free",
                            subscription_status="cancelled"
                        )
                    )

                await db.commit()
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

            # Update subscription status
            stmt = update(Subscription).where(
                Subscription.razorpay_subscription_id == subscription_id
            ).values(status="paused")
            await db.execute(stmt)

            # Update user status
            subscription_result = await db.execute(
                select(Subscription).where(
                    Subscription.razorpay_subscription_id == subscription_id
                )
            )
            subscription = subscription_result.scalar_one_or_none()

            if subscription:
                await db.execute(
                    update(User).where(User.id == subscription.user_id).values(
                        subscription_status="paused"
                    )
                )

            await db.commit()
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

            # Get subscription details
            subscription_result = await db.execute(
                select(Subscription).where(Subscription.user_id == user_id)
                .order_by(Subscription.created_at.desc())
            )
            subscription = subscription_result.scalar_one_or_none()

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

            if user.subscription_plan not in {"free", "student", "team_member"} and not self.is_available():
                return {
                    "success": False,
                    "error": self._base_status["message"],
                }

            # Cancel in Razorpay if not free plan
            if user.subscription_plan not in {"free", "student", "team_member"} and self.client and user.subscription_id:
                try:
                    self.client.subscription.cancel(user.subscription_id, {"cancel_at_cycle_end": 1})
                except Exception as e:
                    logger.error(f"Error cancelling Razorpay subscription: {e}")

            # Update local records
            await db.execute(
                update(Subscription).where(
                    Subscription.user_id == user_id
                ).values(
                    status="cancelled",
                    cancelled_at=datetime.utcnow()
                )
            )

            await db.execute(
                update(User).where(User.id == user_id).values(
                    subscription_status="cancelled"
                )
            )

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

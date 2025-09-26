"""Payment service for Razorpay integration and subscription management."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
import razorpay

from ..database.models import User, Subscription, Payment
from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

class PaymentService:
    """Service for handling payments and subscriptions via Razorpay."""

    def __init__(self):
        """Initialize Razorpay client."""
        if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
            self.client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        else:
            self.client = None
            logger.warning("Razorpay credentials not configured")

    def is_available(self) -> bool:
        """Check if payment service is available."""
        return self.client is not None

    async def get_subscription_plans(self) -> Dict[str, Any]:
        """Get available subscription plans."""
        return settings.SUBSCRIPTION_PLANS

    async def create_razorpay_plan(self, plan_id: str) -> Optional[str]:
        """Create a plan in Razorpay."""
        if not self.client:
            logger.error("Razorpay client not initialized")
            return None

        try:
            plan_config = settings.SUBSCRIPTION_PLANS.get(plan_id)
            if not plan_config:
                logger.error(f"Plan {plan_id} not found in configuration")
                return None

            # Skip free plan
            if plan_config["price"] == 0:
                return None

            razorpay_plan = self.client.plan.create({
                "period": plan_config["interval"],
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

    async def create_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        plan_id: str,
        customer_email: str,
        customer_name: str
    ) -> Dict[str, Any]:
        """Create a new subscription."""
        try:
            if not self.client:
                return {
                    "success": False,
                    "error": "Payment service not available"
                }

            # Get plan configuration
            plan_config = settings.SUBSCRIPTION_PLANS.get(plan_id)
            if not plan_config:
                return {
                    "success": False,
                    "error": "Invalid plan selected"
                }

            # Handle free plan
            if plan_config["price"] == 0:
                return await self._create_free_subscription(db, user_id, plan_id)

            # Create Razorpay customer
            customer = self.client.customer.create({
                "name": customer_name,
                "email": customer_email
            })

            # Create Razorpay plan if not exists
            razorpay_plan_id = await self.create_razorpay_plan(plan_id)
            if not razorpay_plan_id:
                return {
                    "success": False,
                    "error": "Failed to create payment plan"
                }

            # Create Razorpay subscription
            subscription = self.client.subscription.create({
                "plan_id": razorpay_plan_id,
                "customer_id": customer["id"],
                "total_count": 12,  # 12 months
                "quantity": 1,
                "notes": {
                    "user_id": user_id,
                    "plan_id": plan_id
                }
            })

            # Store subscription in database
            db_subscription = Subscription(
                user_id=user_id,
                razorpay_subscription_id=subscription["id"],
                plan_id=plan_id,
                status="created",
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + timedelta(days=30)
            )
            db.add(db_subscription)

            # Update user subscription info
            stmt = update(User).where(User.id == user_id).values(
                subscription_plan=plan_id,
                subscription_status="created",
                subscription_id=subscription["id"]
            )
            await db.execute(stmt)
            await db.commit()

            return {
                "success": True,
                "subscription_id": subscription["id"],
                "short_url": subscription.get("short_url"),
                "customer_id": customer["id"]
            }

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
                trial_used=True
            )
            await db.execute(stmt)
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
            logger.warning("Webhook secret not configured")
            return True  # Skip verification if secret not set

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

            plan_config = settings.SUBSCRIPTION_PLANS.get(user.subscription_plan, {})

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

            # Cancel in Razorpay if not free plan
            if user.subscription_plan != "free" and self.client:
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
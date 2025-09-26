"""Payment service for Razorpay integration and subscription management."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import uuid4

import razorpay
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from sqlalchemy.exc import IntegrityError

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

    async def create_razorpay_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
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
                return {"id": f"plan_{plan_id}", "status": "active"}

            razorpay_plan = self.client.plan.create({
                "period": plan_config["interval"],
                "interval": 1,
                "item": {
                    "name": plan_config["name"],
                    "amount": plan_config["price"],
                    "currency": plan_config["currency"],
                    "description": f"Latexy {plan_config['name']} subscription"
                }
            })

            logger.info(f"Created Razorpay plan: {razorpay_plan['id']}")
            return razorpay_plan

        except Exception as e:
            logger.error(f"Error creating Razorpay plan {plan_id}: {e}")
            return None

    async def create_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        plan_id: str,
        customer_details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new subscription for a user."""
        try:
            # Get user
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                return {"success": False, "error": "User not found"}

            # Get plan configuration
            plan_config = settings.SUBSCRIPTION_PLANS.get(plan_id)
            if not plan_config:
                return {"success": False, "error": "Invalid plan"}

            # Check if user already has an active subscription
            stmt = select(Subscription).where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(["active", "created"])
                )
            )
            result = await db.execute(stmt)
            existing_subscription = result.scalar_one_or_none()

            if existing_subscription:
                return {"success": False, "error": "User already has an active subscription"}

            # Handle free plan
            if plan_id == "free":
                subscription = Subscription(
                    user_id=user_id,
                    plan_id=plan_id,
                    status="active",
                    current_period_start=datetime.utcnow(),
                    current_period_end=datetime.utcnow() + timedelta(days=30)
                )
                db.add(subscription)

                # Update user subscription info
                user.subscription_plan = plan_id
                user.subscription_status = "active"
                user.trial_used = True

                await db.commit()
                await db.refresh(subscription)

                return {
                    "success": True,
                    "subscription_id": subscription.id,
                    "status": "active",
                    "plan_id": plan_id
                }

            # Create Razorpay subscription for paid plans
            if not self.client:
                return {"success": False, "error": "Payment service not available"}

            try:
                # Create customer if not exists
                customer_data = {
                    "name": customer_details.get("name", user.name or ""),
                    "email": user.email,
                    "contact": customer_details.get("phone", "")
                }

                razorpay_customer = self.client.customer.create(customer_data)

                # Create subscription
                subscription_data = {
                    "plan_id": f"plan_{plan_id}",
                    "customer_id": razorpay_customer["id"],
                    "total_count": 12,  # 12 months
                    "quantity": 1,
                    "notes": {
                        "user_id": user_id,
                        "plan_id": plan_id
                    }
                }

                razorpay_subscription = self.client.subscription.create(subscription_data)

                # Create subscription record
                subscription = Subscription(
                    user_id=user_id,
                    razorpay_subscription_id=razorpay_subscription["id"],
                    plan_id=plan_id,
                    status="created",
                    current_period_start=datetime.utcnow(),
                    current_period_end=datetime.utcnow() + timedelta(days=30)
                )
                db.add(subscription)

                await db.commit()
                await db.refresh(subscription)

                return {
                    "success": True,
                    "subscription_id": subscription.id,
                    "razorpay_subscription_id": razorpay_subscription["id"],
                    "status": "created",
                    "plan_id": plan_id,
                    "short_url": razorpay_subscription.get("short_url")
                }

            except Exception as e:
                logger.error(f"Error creating Razorpay subscription: {e}")
                await db.rollback()
                return {"success": False, "error": "Failed to create subscription"}

        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

    async def get_user_subscription(
        self,
        db: AsyncSession,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get user's current subscription."""
        try:
            stmt = select(Subscription).where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(["active", "created", "past_due"])
                )
            ).order_by(Subscription.created_at.desc())

            result = await db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                return None

            plan_config = settings.SUBSCRIPTION_PLANS.get(subscription.plan_id, {})

            return {
                "id": subscription.id,
                "plan_id": subscription.plan_id,
                "plan_name": plan_config.get("name", "Unknown"),
                "status": subscription.status,
                "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
                "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
                "features": plan_config.get("features", {}),
                "price": plan_config.get("price", 0),
                "currency": plan_config.get("currency", "INR")
            }

        except Exception as e:
            logger.error(f"Error getting user subscription: {e}")
            return None

    async def cancel_subscription(
        self,
        db: AsyncSession,
        user_id: str,
        subscription_id: str
    ) -> Dict[str, Any]:
        """Cancel a user's subscription."""
        try:
            # Get subscription
            stmt = select(Subscription).where(
                and_(
                    Subscription.id == subscription_id,
                    Subscription.user_id == user_id
                )
            )
            result = await db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                return {"success": False, "error": "Subscription not found"}

            # Cancel in Razorpay if it's a paid subscription
            if subscription.razorpay_subscription_id and self.client:
                try:
                    self.client.subscription.cancel(subscription.razorpay_subscription_id, {
                        "cancel_at_cycle_end": True
                    })
                except Exception as e:
                    logger.error(f"Error cancelling Razorpay subscription: {e}")

            # Update subscription status
            subscription.status = "cancelled"
            subscription.cancelled_at = datetime.utcnow()

            # Update user status
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if user:
                user.subscription_status = "cancelled"

            await db.commit()

            return {"success": True, "message": "Subscription cancelled successfully"}

        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

    async def handle_webhook(
        self,
        db: AsyncSession,
        payload: str,
        signature: str
    ) -> Dict[str, Any]:
        """Handle Razorpay webhook events."""
        try:
            # Verify webhook signature
            if not self._verify_webhook_signature(payload, signature):
                logger.warning("Invalid webhook signature")
                return {"success": False, "error": "Invalid signature"}

            event = json.loads(payload)
            event_type = event.get("event")
            
            logger.info(f"Processing webhook event: {event_type}")

            if event_type == "subscription.activated":
                return await self._handle_subscription_activated(db, event)
            elif event_type == "subscription.charged":
                return await self._handle_subscription_charged(db, event)
            elif event_type == "subscription.cancelled":
                return await self._handle_subscription_cancelled(db, event)
            elif event_type == "subscription.paused":
                return await self._handle_subscription_paused(db, event)
            elif event_type == "payment.failed":
                return await self._handle_payment_failed(db, event)
            else:
                logger.info(f"Unhandled webhook event: {event_type}")
                return {"success": True, "message": "Event ignored"}

        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return {"success": False, "error": "Internal server error"}

    def _verify_webhook_signature(self, payload: str, signature: str) -> bool:
        """Verify Razorpay webhook signature."""
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            logger.warning("Webhook secret not configured")
            return True  # Skip verification if secret not set

        try:
            expected_signature = hmac.new(
                settings.RAZORPAY_WEBHOOK_SECRET.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False

    async def _handle_subscription_activated(
        self,
        db: AsyncSession,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription activated event."""
        try:
            subscription_data = event["payload"]["subscription"]["entity"]
            razorpay_subscription_id = subscription_data["id"]

            # Find subscription
            stmt = select(Subscription).where(
                Subscription.razorpay_subscription_id == razorpay_subscription_id
            )
            result = await db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                logger.warning(f"Subscription not found: {razorpay_subscription_id}")
                return {"success": False, "error": "Subscription not found"}

            # Update subscription status
            subscription.status = "active"
            subscription.current_period_start = datetime.fromtimestamp(
                subscription_data["current_start"]
            )
            subscription.current_period_end = datetime.fromtimestamp(
                subscription_data["current_end"]
            )

            # Update user status
            stmt = select(User).where(User.id == subscription.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if user:
                user.subscription_status = "active"

            await db.commit()

            logger.info(f"Subscription activated: {razorpay_subscription_id}")
            return {"success": True, "message": "Subscription activated"}

        except Exception as e:
            logger.error(f"Error handling subscription activated: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

    async def _handle_subscription_charged(
        self,
        db: AsyncSession,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription charged event."""
        try:
            payment_data = event["payload"]["payment"]["entity"]
            subscription_data = event["payload"]["subscription"]["entity"]

            # Find subscription
            stmt = select(Subscription).where(
                Subscription.razorpay_subscription_id == subscription_data["id"]
            )
            result = await db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                logger.warning(f"Subscription not found: {subscription_data['id']}")
                return {"success": False, "error": "Subscription not found"}

            # Create payment record
            payment = Payment(
                user_id=subscription.user_id,
                subscription_id=subscription.id,
                razorpay_payment_id=payment_data["id"],
                amount=payment_data["amount"],
                currency=payment_data["currency"],
                status="captured",
                payment_method=payment_data.get("method", "unknown")
            )
            db.add(payment)

            await db.commit()

            logger.info(f"Payment recorded: {payment_data['id']}")
            return {"success": True, "message": "Payment recorded"}

        except Exception as e:
            logger.error(f"Error handling subscription charged: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

    async def _handle_subscription_cancelled(
        self,
        db: AsyncSession,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription cancelled event."""
        try:
            subscription_data = event["payload"]["subscription"]["entity"]
            razorpay_subscription_id = subscription_data["id"]

            # Find subscription
            stmt = select(Subscription).where(
                Subscription.razorpay_subscription_id == razorpay_subscription_id
            )
            result = await db.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                logger.warning(f"Subscription not found: {razorpay_subscription_id}")
                return {"success": False, "error": "Subscription not found"}

            # Update subscription status
            subscription.status = "cancelled"
            subscription.cancelled_at = datetime.utcnow()

            # Update user status
            stmt = select(User).where(User.id == subscription.user_id)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()

            if user:
                user.subscription_status = "cancelled"

            await db.commit()

            logger.info(f"Subscription cancelled: {razorpay_subscription_id}")
            return {"success": True, "message": "Subscription cancelled"}

        except Exception as e:
            logger.error(f"Error handling subscription cancelled: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

    async def _handle_subscription_paused(
        self,
        db: AsyncSession,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle subscription paused event."""
        # Similar implementation to cancelled
        return await self._handle_subscription_cancelled(db, event)

    async def _handle_payment_failed(
        self,
        db: AsyncSession,
        event: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle payment failed event."""
        try:
            payment_data = event["payload"]["payment"]["entity"]

            # Create failed payment record
            payment = Payment(
                razorpay_payment_id=payment_data["id"],
                amount=payment_data["amount"],
                currency=payment_data["currency"],
                status="failed",
                payment_method=payment_data.get("method", "unknown")
            )
            db.add(payment)

            await db.commit()

            logger.info(f"Failed payment recorded: {payment_data['id']}")
            return {"success": True, "message": "Failed payment recorded"}

        except Exception as e:
            logger.error(f"Error handling payment failed: {e}")
            await db.rollback()
            return {"success": False, "error": "Internal server error"}

# Global service instance
payment_service = PaymentService()

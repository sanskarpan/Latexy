"""Provider-neutral billing orchestration with Dodo Payments as the adapter."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_dodo_product_id, get_plan_config, is_b57_sku_configured, resolve_plan_family, settings
from ..core.logging import get_logger
from ..core.observability import record_business_event
from ..core.redis import get_redis_cache_client
from ..database import models as db_models
from .dodo_provider import DodoAPIError, DodoProvider
from .email_service import email_service
from .referral_service import referral_service

logger = get_logger(__name__)
Payment, Subscription, User = db_models.Payment, db_models.Subscription, db_models.User
TeamSeat = db_models.TeamSeat
CouponCode, CouponRedemption = db_models.CouponCode, db_models.CouponRedemption
BillingWebhookEvent, PaymentRefund = db_models.BillingWebhookEvent, db_models.PaymentRefund

LIVE_SUBSCRIPTION_STATUSES = ("cancel_scheduled", "active", "past_due", "on_hold", "paused", "created", "pending", "checkout_pending", "checkout_unknown")
PAID_SUBSCRIPTION_STATUSES = ("cancel_scheduled", "active", "past_due", "on_hold", "paused")
LEGACY_BILLING_STATUSES = ("active", "created", "authenticated", "pending", "halted", "paused", "cancel_scheduled")
WEBHOOK_TOLERANCE_SECONDS = 300
RECONCILE_LOCK_TTL_SECONDS = 75
RECONCILE_COOLDOWN_SECONDS = 20
_LOCK_RELEASE_SCRIPT = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"


class PaymentService:
    """Owns Latexy checkout, entitlement and durable webhook state transitions."""

    def __init__(self, provider: DodoProvider | None = None):
        self.provider = provider or DodoProvider()
        self._base_status = self._build_base_status()

    def _build_base_status(self) -> dict[str, Any]:
        if settings.normalized_billing_mode == "disabled":
            return {"feature_enabled": False, "mode": "disabled", "available": False,
                    "reason": "billing_disabled", "message": "Billing is disabled in this environment."}
        if settings.is_production_like() and settings.normalized_dodo_mode != "live":
            return {"feature_enabled": True, "mode": "unconfigured", "available": False,
                    "reason": "production_test_billing_blocked",
                    "message": "Production billing requires explicitly configured Dodo live mode."}
        if not settings.billing_credentials_configured():
            return {"feature_enabled": True, "mode": "unconfigured", "available": False,
                    "reason": "billing_unconfigured", "message": "Dodo billing is not fully configured for this environment."}
        return {"feature_enabled": True, "mode": "enabled", "available": True,
                "reason": None, "message": "Billing is available."}

    def get_status(self, feature_enabled: bool = True) -> dict[str, Any]:
        if not feature_enabled:
            return {"feature_enabled": False, "mode": "disabled", "available": False,
                    "reason": "feature_flag_disabled", "message": "Billing is currently disabled."}
        return dict(self._base_status)

    def is_available(self) -> bool:
        return bool(self._base_status["available"] and self.provider.available)

    def is_service_available(self) -> bool:
        """Existing billing remains manageable when new checkout is disabled."""
        if settings.is_production_like() and settings.normalized_dodo_mode != "live":
            return False
        return self.is_available() or bool(self.provider.available)

    async def get_subscription_plans(self) -> dict[str, Any]:
        plans: dict[str, Any] = {}
        for key, value in settings.SUBSCRIPTION_PLANS.items():
            if key == "free":
                plans[key] = {**dict(value), "id": key}
            elif get_dodo_product_id(key) and self.is_available():
                plan = get_plan_config(key)
                plans[key] = {**plan, "id": key, "provider": "dodo"}
        for sku in ("weekly", "lifetime"):
            if is_b57_sku_configured(sku) and self.is_available():
                plans[sku] = {**get_plan_config(sku), "id": sku, "provider": "dodo"}
        return plans

    def _resolve_concrete_plan_id(self, plan_id: str, billing_period: str) -> str:
        normalized, period = (plan_id or "free").strip().lower(), (billing_period or "monthly").strip().lower()
        if normalized in {"basic", "pro", "byok"} and period in {"annual", "yearly"}:
            return f"{normalized}_annual"
        return normalized

    @staticmethod
    def _is_student_email(email: str) -> bool:
        email = (email or "").strip().lower()
        return any(email.endswith(suffix.lower()) for suffix in settings.STUDENT_EMAIL_ALLOWED_SUFFIXES)

    async def _acquire_checkout_lock(self, user_id: str) -> str | None:
        redis = await get_redis_cache_client()
        token = secrets.token_urlsafe(24)
        return token if await redis.set(f"latexy:billing:checkout:{user_id}", token, nx=True, ex=180) else None

    async def _release_checkout_lock(self, user_id: str, token: str) -> None:
        redis = await get_redis_cache_client()
        await redis.eval(_LOCK_RELEASE_SCRIPT, 1, f"latexy:billing:checkout:{user_id}", token)

    async def _acquire_reconcile_lock(self, user_id: str) -> str | None:
        """Bound provider reads and serialize recovery attempts per account."""
        redis = await get_redis_cache_client()
        token = secrets.token_urlsafe(24)
        return token if await redis.set(
            f"latexy:billing:reconcile:{user_id}", token, nx=True, ex=RECONCILE_LOCK_TTL_SECONDS,
        ) else None

    async def _acquire_reconcile_cooldown(self, user_id: str) -> bool:
        """Rate limit provider reads even after the in-flight lock is released."""
        redis = await get_redis_cache_client()
        return bool(await redis.set(
            f"latexy:billing:reconcile-cooldown:{user_id}", "1", nx=True, ex=RECONCILE_COOLDOWN_SECONDS,
        ))

    async def _release_reconcile_lock(self, user_id: str, token: str) -> None:
        redis = await get_redis_cache_client()
        await redis.eval(_LOCK_RELEASE_SCRIPT, 1, f"latexy:billing:reconcile:{user_id}", token)

    async def _request_student_verification(
        self, db: AsyncSession, user_id: str, customer_email: str, customer_name: str, student_email: str,
    ) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        redis = await get_redis_cache_client()
        payload = {"user_id": user_id, "customer_email": customer_email, "customer_name": customer_name,
                   "student_email": student_email, "requested_at": datetime.now(timezone.utc).isoformat()}
        await redis.set(f"student_plan_verify:{token}", json.dumps(payload), ex=24 * 3600)
        url = f"{settings.FRONTEND_URL}/billing?student_verify={token}"
        await email_service.send_email(
            to=student_email, subject="Verify your Latexy student plan",
            html_body=f"<p>Verify your student email to continue to checkout.</p><p><a href=\"{url}\">Verify student email</a></p>",
            text_body=f"Verify your Latexy student plan: {url}",
        )
        return {"success": True, "verification_required": True, "message": "Verification email sent to your student address.",
                "verification_preview_url": url if not settings.EMAIL_ENABLED else None}

    async def verify_student_subscription(self, db: AsyncSession, token: str) -> dict[str, Any]:
        redis = await get_redis_cache_client()
        lock = f"latexy:student-verify:{hashlib.sha256(token.encode()).hexdigest()}"
        if not await redis.set(lock, "1", nx=True, ex=120):
            return {"success": False, "error": "Student verification is already in progress"}
        try:
            raw = await redis.get(f"student_plan_verify:{token}")
            if not raw:
                return {"success": False, "error": "Student verification link is invalid or expired"}
            data = json.loads(raw)
            if not self.is_available():
                return {"success": False, "error": self._base_status["message"]}
            result = await self.create_subscription(
                db, data["user_id"], "student", data["customer_email"], data["customer_name"],
                student_email=data["student_email"], student_verified=True,
            )
            if result.get("success"):
                await redis.delete(f"student_plan_verify:{token}")
            return result
        except Exception as exc:
            logger.error("Student billing verification failed", extra={"error_type": type(exc).__name__})
            await db.rollback()
            return {"success": False, "error": "Failed to verify student subscription"}
        finally:
            await redis.delete(lock)

    async def validate_coupon(self, db: AsyncSession, code: str, plan_id: str, user_id: str | None = None) -> dict[str, Any]:
        normalized = (code or "").strip().upper()
        if not normalized:
            return {"valid": False, "message": "Coupon code is required"}
        coupon = await db.scalar(select(CouponCode).where(CouponCode.code == normalized))
        if coupon is None:
            return {"valid": False, "message": "Invalid or expired code"}
        now = datetime.now(timezone.utc)
        expiry = coupon.expires_at
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        applicable = set(coupon.applicable_plans or [])
        if (expiry and expiry <= now) or (coupon.max_uses is not None and coupon.used_count >= coupon.max_uses):
            return {"valid": False, "message": "Invalid or expired code"}
        if applicable and plan_id not in applicable and resolve_plan_family(plan_id) not in applicable:
            return {"valid": False, "message": "Code not valid for this plan"}
        if user_id and await db.scalar(select(CouponRedemption.id).where(
            CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user_id,
            CouponRedemption.status.in_(("reserved", "redeemed")),
        )):
            return {"valid": False, "message": "Coupon already used by this account"}
        return {"valid": True, "code": normalized, "discount_percent": int(coupon.discount_percent),
                "message": "Coupon applied"}

    def _provider_coupon_compatibility_error(
        self, provider_discount: Any, *, code: str, discount_percent: int, product_id: str,
    ) -> str | None:
        """Accept only provider discounts matching our perpetual local quote."""
        if not isinstance(provider_discount, dict):
            return "Coupon is not configured for recurring billing"
        provider_code = provider_discount.get("code", provider_discount.get("discount_code"))
        if not isinstance(provider_code, str) or provider_code.strip().upper() != code:
            return "Coupon configuration does not match this code"
        if provider_discount.get("type") != "percentage":
            return "Only percentage coupons are supported"
        amount = provider_discount.get("amount")
        if type(amount) is not int or amount != discount_percent * 100:
            return "Coupon discount does not match the configured offer"
        if provider_discount.get("subscription_cycles") is not None:
            return "Coupon must apply to every subscription payment"
        if provider_discount.get("expires_at") is not None:
            return "Coupons with a provider expiry are not supported"
        starts_at = provider_discount.get("starts_at")
        if starts_at is not None:
            starts = self._parse_time(starts_at)
            if starts is None or starts > datetime.now(timezone.utc):
                return "Coupon is not currently available"
        restricted_to = provider_discount.get("restricted_to", [])
        if (
            not isinstance(restricted_to, list)
            or any(not isinstance(value, str) for value in restricted_to)
            or (restricted_to and product_id not in restricted_to)
        ):
            return "Coupon is not available for this plan"
        currency_options = provider_discount.get("currency_options")
        if currency_options not in (None, [], {}):
            return "Coupon has unsupported currency restrictions"
        if provider_discount.get("customer_eligibility") != "any":
            return "Coupon has unsupported customer eligibility rules"
        # The local ledger cannot prove the provider customer has never used a
        # code on another product/account, so any provider usage cap is unsafe.
        if provider_discount.get("per_customer_usage_limit") is not None:
            return "Coupon has unsupported per-customer usage limits"
        usage_limit = provider_discount.get("usage_limit")
        times_used = provider_discount.get("times_used")
        if usage_limit is not None:
            if type(usage_limit) is not int or usage_limit < 0 or type(times_used) is not int or times_used < 0:
                return "Coupon usage information is unavailable"
            if usage_limit == 0 or times_used >= usage_limit:
                return "Coupon usage limit has been reached"
        elif times_used is not None and (type(times_used) is not int or times_used < 0):
            return "Coupon usage information is invalid"
        if provider_discount.get("preserve_on_plan_change") is not True:
            return "Coupon is not configured to continue after a plan change"
        return None

    async def _reserve_coupon(
        self, db: AsyncSession, code: str, plan_id: str, user_id: str, subscription_id: str,
    ) -> tuple[bool, str]:
        coupon = await db.scalar(select(CouponCode).where(CouponCode.code == code).with_for_update())
        if coupon is None:
            return False, "Invalid or expired code"
        expiry = coupon.expires_at
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        applicable = set(coupon.applicable_plans or [])
        if (expiry and expiry <= datetime.now(timezone.utc)) or (coupon.max_uses is not None and coupon.used_count >= coupon.max_uses):
            return False, "Invalid or expired code"
        if applicable and plan_id not in applicable and resolve_plan_family(plan_id) not in applicable:
            return False, "Code not valid for this plan"
        redemption = await db.scalar(select(CouponRedemption).where(
            CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user_id,
        ).with_for_update())
        if redemption and redemption.status in {"reserved", "redeemed"}:
            return False, "Coupon already used by this account"
        coupon.used_count = int(coupon.used_count or 0) + 1
        if redemption:
            redemption.status = "reserved"
            redemption.subscription_id = subscription_id
            redemption.redeemed_at = None
        else:
            db.add(CouponRedemption(
                coupon_id=coupon.id,
                user_id=user_id,
                subscription_id=subscription_id,
                status="reserved",
                redeemed_at=None,
            ))
        await db.flush()
        return True, ""

    async def _set_coupon_reservation_status(
        self, db: AsyncSession, subscription_id: str, status: str,
    ) -> None:
        """Finalize or release this intent's reservation while serializing count updates."""
        redemption = await db.scalar(select(CouponRedemption).where(
            CouponRedemption.subscription_id == subscription_id,
        ))
        if not redemption or redemption.status != "reserved" or not redemption.coupon_id:
            return
        coupon = await db.scalar(select(CouponCode).where(
            CouponCode.id == redemption.coupon_id,
        ).with_for_update())
        redemption = await db.scalar(select(CouponRedemption).where(
            CouponRedemption.id == redemption.id,
        ).with_for_update())
        if not redemption or redemption.status != "reserved":
            return
        if status == "released":
            if coupon:
                coupon.used_count = max(0, int(coupon.used_count or 0) - 1)
            redemption.status = "released"
            redemption.subscription_id = None
            redemption.redeemed_at = None
        elif status == "redeemed":
            redemption.status = "redeemed"
            redemption.redeemed_at = datetime.now(timezone.utc)

    async def _get_live_subscription(self, db: AsyncSession, user_id: str) -> Subscription | None:
        rank = case({state: i for i, state in enumerate(LIVE_SUBSCRIPTION_STATUSES)}, value=Subscription.status,
                    else_=len(LIVE_SUBSCRIPTION_STATUSES))
        return await db.scalar(select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.provider == "dodo",
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        ).order_by(rank, Subscription.created_at.desc()).limit(1))

    async def _get_legacy_subscription(self, db: AsyncSession, user_id: str) -> Subscription | None:
        """Find an unsettled pre-migration subscription that can still charge."""
        return await db.scalar(select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.provider == "razorpay",
            Subscription.provider_subscription_id.is_not(None),
            Subscription.status.in_(LEGACY_BILLING_STATUSES),
        ).order_by(Subscription.created_at.desc()).limit(1))

    def _period_delta(self, plan_id: str) -> timedelta:
        interval = str(get_plan_config(plan_id).get("interval", "month")).lower()
        return {"week": timedelta(days=7), "year": timedelta(days=365)}.get(interval, timedelta(days=30))

    async def create_subscription(
        self, db: AsyncSession, user_id: str, plan_id: str, customer_email: str, customer_name: str,
        billing_period: str = "monthly", coupon_code: str | None = None, student_email: str | None = None,
        student_verified: bool = False,
    ) -> dict[str, Any]:
        concrete = self._resolve_concrete_plan_id(plan_id, billing_period)
        if concrete not in settings.SUBSCRIPTION_PLANS:
            return {"success": False, "error": "Invalid plan selected"}
        plan = get_plan_config(concrete)
        quoted_tax_inclusive = plan.get("tax_inclusive", True)
        if type(quoted_tax_inclusive) is not bool:
            return {"success": False, "error": "Billing tax settings are not configured correctly"}
        legacy = await self._get_legacy_subscription(db, user_id)
        if legacy:
            return {"success": False,
                    "error": "An existing subscription is still linked to the previous payment provider. Contact support to cancel it before changing plans."}
        if concrete == "free":
            current = await self._get_live_subscription(db, user_id)
            if current and current.status in PAID_SUBSCRIPTION_STATUSES:
                return {"success": False, "error": "Cancel your paid subscription before switching to the free plan."}
            if current and not current.provider_subscription_id:
                # The hosted URL can still accept payment. A local downgrade
                # cannot revoke it, so retain the blocking intent until the
                # provider confirms its outcome through reconciliation/webhook.
                return {"success": False, "error": "This checkout has not activated yet. Wait for it to finish before changing plans."}
            if current and current.provider_subscription_id:
                try:
                    updated = await self.provider.update_subscription(current.provider_subscription_id, {"cancel_at_next_billing_date": False, "status": "cancelled"})
                except DodoAPIError:
                    return {"success": False, "error": "Could not close your pending checkout. Please try again."}
                if updated.get("status") != "cancelled":
                    return {"success": False, "error": "Provider did not confirm checkout cancellation."}
            user = await db.get(User, user_id)
            if user:
                user.subscription_plan, user.subscription_status, user.subscription_id = "free", "inactive", None
            if current:
                current.status = "cancelled"
                await self._set_coupon_reservation_status(db, current.id, "released")
            await db.commit()
            return {"success": True, "message": "Free plan activated"}
        if concrete == "student" and not student_verified:
            if not student_email or not self._is_student_email(student_email):
                return {"success": False, "error": "Student plan requires a verified academic email address"}
            if not self.is_available():
                return {"success": False, "error": self._base_status["message"]}
            return await self._request_student_verification(db, user_id, customer_email, customer_name, student_email)
        if concrete in {"weekly", "lifetime"} and not is_b57_sku_configured(concrete):
            return {"success": False, "error": f"{plan.get('name', concrete)} billing is not configured yet."}
        if not get_dodo_product_id(concrete):
            return {"success": False, "error": f"{plan.get('name', concrete)} billing is not configured yet."}
        if not self.is_available():
            return {"success": False, "error": self._base_status["message"]}

        current = await self._get_live_subscription(db, user_id)
        if current and current.status in PAID_SUBSCRIPTION_STATUSES:
            if current.plan_id == concrete and current.provider_checkout_session_id:
                return {"success": True, "subscription_id": current.provider_subscription_id,
                        "short_url": None, "message": "This subscription is already active."}
            return {"success": False, "error": "Manage or cancel your current paid subscription before starting another."}
        if current and current.status in {"checkout_pending", "checkout_unknown", "created", "pending"}:
            return {"success": False, "error": "A checkout is still pending for this account. Wait for it to finish before starting another."}

        coupon = None
        if coupon_code:
            coupon = await self.validate_coupon(db, coupon_code, concrete, user_id)
            if not coupon["valid"]:
                return {"success": False, "error": coupon["message"]}
        lock_token = await self._acquire_checkout_lock(user_id)
        if not lock_token:
            return {"success": False, "error": "A checkout is already in progress for this account."}
        intent_id = str(uuid4())
        provider_request_started = False
        try:
            # The earlier checks are only a fast path. Another request may have
            # completed its checkout between that read and this Redis lease.
            # Serialize the durable intent creation on the account as well, so
            # a lease expiry cannot allow a second payable checkout.
            owner = await db.scalar(select(User).where(User.id == user_id)
                                    .with_for_update().execution_options(populate_existing=True))
            if owner is None:
                await db.rollback()
                return {"success": False, "error": "Authenticated user not found"}
            if await self._get_legacy_subscription(db, user_id):
                await db.rollback()
                return {"success": False,
                        "error": "An existing subscription is still linked to the previous payment provider. Contact support to cancel it before changing plans."}
            if await self._get_live_subscription(db, user_id):
                await db.rollback()
                return {"success": False, "error": "A checkout or paid subscription is already in progress for this account."}
            if coupon:
                try:
                    provider_discount = await self.provider.get_discount_by_code(coupon["code"])
                except DodoAPIError as exc:
                    logger.warning("Could not verify Dodo coupon configuration", extra={
                        "status": exc.status_code, "code": exc.code,
                    })
                    await db.rollback()
                    return {"success": False, "error": "Coupon could not be verified with the billing provider"}
                compatibility_error = self._provider_coupon_compatibility_error(
                    provider_discount,
                    code=coupon["code"],
                    discount_percent=int(coupon["discount_percent"]),
                    product_id=get_dodo_product_id(concrete),
                )
                if compatibility_error:
                    await db.rollback()
                    return {"success": False, "error": compatibility_error}
            # Persist the local intent before the provider call. A timeout or
            # early webhook can be reconciled using the signed metadata UUID.
            intent = Subscription(
                id=intent_id, user_id=user_id, provider="dodo", plan_id=concrete, status="checkout_pending",
                current_period_start=datetime.now(timezone.utc),
                current_period_end=None,
                provider_product_id=get_dodo_product_id(concrete),
                quoted_amount=int(plan.get("price") or 0),
                quoted_tax_inclusive=quoted_tax_inclusive,
                discount_percent=int((coupon or {}).get("discount_percent") or 0),
            )
            db.add(intent)
            await db.flush()
            if coupon:
                reserved, message = await self._reserve_coupon(
                    db, coupon["code"], concrete, user_id, intent_id,
                )
                if not reserved:
                    await db.rollback()
                    return {"success": False, "error": message}
            await db.execute(update(User).where(User.id == user_id).values(
                subscription_status="checkout_pending", subscription_id=intent_id,
            ))
            await db.commit()

            payload: dict[str, Any] = {
                "product_cart": [{"product_id": get_dodo_product_id(concrete), "quantity": 1}],
                "customer": {"email": customer_email, "name": customer_name or "Latexy customer"},
                # Adaptive pricing otherwise selects currency from the buyer's
                # IP, even when the checkout currency selector is disabled.
                "billing_currency": str(plan.get("currency") or settings.BILLING_CURRENCY).upper(),
                "return_url": f"{settings.FRONTEND_URL}/billing?checkout=return",
                "metadata": {
                    "latexy_intent_id": intent_id,
                    "latexy_user_id": user_id,
                    "latexy_plan_id": concrete,
                    # Keep the pricing basis with the checkout so later catalog
                    # or application config changes cannot reinterpret its quote.
                    "latexy_tax_inclusive": str(quoted_tax_inclusive).lower(),
                },
                # Lock checkout to the currency used by this server quote;
                # hiding the currency selector alone does not disable adaptive
                # pricing based on the customer's IP.
                "feature_flags": {
                    "allow_currency_selection": False,
                    "allow_discount_code": bool(coupon_code),
                },
            }
            if coupon_code:
                payload["discount_codes"] = [coupon["code"]]
            provider_request_started = True
            session = await self.provider.create_checkout_session(payload)
            session_id, checkout_url = session.get("session_id"), session.get("checkout_url")
            if not session_id or not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
                raise DodoAPIError(502, "invalid_checkout_session")
            intent.provider_checkout_session_id = str(session_id)
            await db.execute(update(User).where(
                User.id == user_id, User.subscription_id == intent_id,
                User.subscription_status.in_(("checkout_pending", "checkout_unknown")),
            ).values(
                subscription_status="checkout_pending", subscription_id=intent_id,
            ))
            await db.commit()
            record_business_event("subscription", "checkout_created")
            return {"success": True, "subscription_id": None, "checkout_session_id": str(session_id),
                    "short_url": checkout_url, "checkout_type": "hosted"}
        except DodoAPIError as exc:
            logger.warning("Dodo checkout creation failed", extra={"status": exc.status_code, "code": exc.code})
            await db.rollback()
            row = await db.scalar(select(Subscription).where(Subscription.id == intent_id)
                                  .with_for_update().execution_options(populate_existing=True))
            if row and row.status in {"checkout_pending", "checkout_unknown"}:
                row.status = "checkout_unknown" if exc.code == "provider_unavailable" or exc.code == "invalid_checkout_session" or exc.status_code >= 500 else "failed"
                if row.status == "failed":
                    await self._set_coupon_reservation_status(db, intent_id, "released")
                    user = await db.get(User, user_id)
                    if user and user.subscription_id == intent_id:
                        user.subscription_plan, user.subscription_status, user.subscription_id = "free", "inactive", None
                await db.commit()
            else:
                await db.rollback()
            return {"success": False, "error": "Checkout could not be created. Please try again."}
        except Exception as exc:
            logger.error("Checkout creation failed", extra={"error_type": type(exc).__name__})
            await db.rollback()
            row = await db.scalar(select(Subscription).where(Subscription.id == intent_id)
                                  .with_for_update().execution_options(populate_existing=True))
            if row and row.status in {"checkout_pending", "checkout_unknown"}:
                row.status = "checkout_unknown" if provider_request_started else "failed"
                if row.status == "failed":
                    await self._set_coupon_reservation_status(db, intent_id, "released")
                    user = await db.get(User, user_id)
                    if user and user.subscription_id == intent_id:
                        user.subscription_plan, user.subscription_status, user.subscription_id = "free", "inactive", None
                await db.commit()
            else:
                await db.rollback()
            return {"success": False, "error": "Checkout could not be created. Please try again."}
        finally:
            try:
                await self._release_checkout_lock(user_id, lock_token)
            except Exception as exc:
                logger.warning("Checkout lock release failed", extra={"error_type": type(exc).__name__})

    async def get_user_subscription(self, db: AsyncSession, user_id: str) -> dict[str, Any] | None:
        user = await db.get(User, user_id)
        if not user:
            return None
        sub = await db.scalar(select(Subscription).where(Subscription.user_id == user_id)
                              .order_by(Subscription.created_at.desc()).limit(1))
        plan_id = user.subscription_plan or "free"
        plan = get_plan_config(plan_id)
        return {"user_id": user_id, "plan_id": plan_id, "plan_name": plan.get("name", plan_id.title()),
                "status": user.subscription_status or "inactive", "features": plan.get("features", {}),
                "subscription_id": sub.provider_subscription_id if sub else None,
                "current_period_end": sub.current_period_end.isoformat() if sub and sub.current_period_end else None}

    async def cancel_subscription(self, db: AsyncSession, user_id: str) -> dict[str, Any]:
        user = await db.get(User, user_id)
        if not user:
            return {"success": False, "error": "Subscription not found"}
        sub = await self._get_live_subscription(db, user_id)
        if not sub:
            if await self._get_legacy_subscription(db, user_id):
                return {"success": False,
                        "error": "This subscription is still linked to the previous payment provider. Contact support to cancel it."}
            return {"success": False, "error": "No active subscription found"}
        if not self.is_service_available():
            return {"success": False, "error": self._base_status["message"]}
        if not sub.provider_subscription_id:
            return {"success": False, "error": "This checkout has not activated yet."}
        try:
            updated = await self.provider.update_subscription(sub.provider_subscription_id, {"cancel_at_next_billing_date": True})
        except DodoAPIError as exc:
            logger.warning("Dodo cancellation failed", extra={"status": exc.status_code, "code": exc.code})
            return {"success": False, "error": "Could not cancel subscription. Please try again."}
        if updated.get("cancel_at_next_billing_date") is not True:
            return {"success": False, "error": "Provider did not confirm scheduled cancellation."}
        # A lifecycle webhook can commit while the provider request is in
        # flight. Re-read under the usual intent -> user row-lock order, and
        # never turn cancellation scheduling into a paid-access restoration.
        sub = await db.scalar(select(Subscription).where(Subscription.id == sub.id)
                              .with_for_update().execution_options(populate_existing=True))
        if sub is None:
            await db.rollback()
            return {"success": False, "error": "Subscription not found"}
        if sub.status in {"cancelled", "expired", "failed", "refunded"}:
            await db.rollback()
            return {"success": True, "message": "Subscription has already ended."}
        user = await db.scalar(select(User).where(User.id == user_id)
                               .with_for_update().execution_options(populate_existing=True))
        if sub.status in {"active", "cancel_scheduled"}:
            sub.status = "cancel_scheduled"
        if user and user.subscription_id == sub.id:
            user.subscription_status = sub.status
        await db.commit()
        return {"success": True, "message": "Cancellation scheduled for the end of the billing cycle."}

    @staticmethod
    def _provider_resource(response: Any) -> dict[str, Any] | None:
        if not isinstance(response, dict):
            return None
        nested = response.get("data")
        return nested if isinstance(nested, dict) else response

    @staticmethod
    def _provider_metadata_matches(metadata: Any, intent: Subscription) -> bool:
        if not isinstance(metadata, dict):
            return False
        expected_tax = intent.quoted_tax_inclusive
        return (
            metadata.get("latexy_intent_id") == intent.id
            and metadata.get("latexy_user_id") == intent.user_id
            and metadata.get("latexy_plan_id") == intent.plan_id
            and metadata.get("latexy_tax_inclusive") == str(expected_tax).lower()
        )

    async def reconcile_checkout(self, db: AsyncSession, user_id: str) -> dict[str, Any]:
        """Recover one current, owner-scoped checkout using authenticated provider reads.

        This deliberately accepts no provider identifiers from the caller. The
        checkout session ID comes only from the user's locked local intent.
        """
        if not self.is_service_available():
            return {"success": False, "status": "unavailable", "message": "Billing is unavailable."}
        try:
            lock_token = await self._acquire_reconcile_lock(user_id)
        except Exception as exc:
            logger.error("Dodo checkout recovery lock unavailable", extra={"error_type": type(exc).__name__})
            await db.rollback()
            return {"success": False, "status": "unavailable", "message": "Payment status could not be checked yet."}
        if not lock_token:
            return {"success": False, "status": "pending", "message": "Checkout recovery is already in progress."}
        try:
            # Read the owner pointer first without locking the user row. Payment
            # and subscription webhooks lock the intent before touching users;
            # using the same row-lock order here avoids a user->intent deadlock.
            user = await db.scalar(select(User).where(User.id == user_id).execution_options(populate_existing=True))
            if not user:
                await db.rollback()
                return {"success": False, "status": "closed", "message": "No pending checkout was found."}

            current_id = user.subscription_id
            intent = None
            if current_id:
                intent = await db.scalar(select(Subscription).where(
                    Subscription.id == current_id,
                    Subscription.user_id == user_id,
                    Subscription.provider == "dodo",
                ).with_for_update().execution_options(populate_existing=True))
            if intent is None:
                await db.rollback()
                return {"success": False, "status": "closed", "message": "No pending checkout was found."}
            user = await db.scalar(
                select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
            )
            if user is None or user.subscription_id != intent.id:
                await db.rollback()
                return {"success": False, "status": "closed", "message": "Checkout is no longer current."}
            if intent.status in {"failed", "cancelled", "expired", "refunded"}:
                await db.rollback()
                return {"success": False, "status": "closed", "message": "This checkout is closed."}
            if intent.status in {"active", "cancel_scheduled", "past_due", "on_hold", "paused"}:
                has_paid_ledger = await db.scalar(select(Payment.id).where(
                    Payment.provider == "dodo",
                    Payment.subscription_id == intent.id,
                    Payment.status.in_(("paid", "partially_refunded")),
                ).limit(1))
                entitlement_matches = (
                    user.subscription_id == intent.id
                    and user.subscription_plan == intent.plan_id
                    and user.subscription_status in PAID_SUBSCRIPTION_STATUSES
                )
                if has_paid_ledger and entitlement_matches:
                    response = {
                        "success": True, "status": "reconciled", "subscriptionId": intent.provider_subscription_id,
                        "planId": intent.plan_id,
                        "currentPeriodEnd": intent.current_period_end.isoformat() if intent.current_period_end else None,
                        "message": "Subscription is already active.",
                    }
                    await db.rollback()
                    return response
            elif intent.status not in {"checkout_pending", "checkout_unknown"}:
                await db.rollback()
                return {"success": False, "status": "pending", "message": "Checkout is still being prepared."}
            if not intent.provider_checkout_session_id:
                await db.rollback()
                return {"success": False, "status": "pending", "message": "Checkout is still being prepared."}
            if intent.quoted_tax_inclusive is None or type(intent.quoted_amount) is not int:
                await db.rollback()
                return {"success": False, "status": "unavailable", "message": "Checkout quote could not be verified."}

            owner_email = (user.email or "").strip().casefold()
            checkout_id = intent.provider_checkout_session_id
            expected_product_id = get_dodo_product_id(intent.plan_id)
            if not expected_product_id or expected_product_id != intent.provider_product_id or not owner_email:
                await db.rollback()
                return {"success": False, "status": "unavailable", "message": "Checkout details could not be verified."}

            try:
                cooldown_acquired = await self._acquire_reconcile_cooldown(user_id)
            except Exception as exc:
                await db.rollback()
                logger.error("Dodo checkout recovery cooldown unavailable", extra={"error_type": type(exc).__name__})
                return {"success": False, "status": "unavailable", "message": "Payment status could not be checked yet."}
            if not cooldown_acquired:
                await db.rollback()
                return {"success": False, "status": "pending", "message": "Please wait before checking payment status again."}

            try:
                checkout = self._provider_resource(await self.provider.get_checkout_session(checkout_id))
                if not isinstance(checkout, dict):
                    raise DodoAPIError(502, "invalid_provider_response")
                if str(checkout.get("id") or checkout.get("session_id") or "") != checkout_id:
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Checkout details did not match this account."}
                if str(checkout.get("customer_email") or "").strip().casefold() != owner_email:
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Checkout customer did not match this account."}

                provider_payment_id = str(checkout.get("payment_id") or "")
                checkout_payment_status = str(checkout.get("payment_status") or "").lower()
                if not provider_payment_id:
                    await db.rollback()
                    return {"success": False, "status": "pending", "message": "Payment is not confirmed yet."}
                payment = self._provider_resource(await self.provider.get_payment(provider_payment_id))
                if not isinstance(payment, dict):
                    raise DodoAPIError(502, "invalid_provider_response")
                if (
                    str(payment.get("payment_id") or payment.get("id") or "") != provider_payment_id
                    or str(payment.get("checkout_session_id") or "") != checkout_id
                    or not self._provider_metadata_matches(payment.get("metadata"), intent)
                ):
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Payment details did not match this checkout."}

                payment_status = str(payment.get("status") or "").lower()
                if checkout_payment_status == "failed" and payment_status == "failed":
                    failed_subscription_ids = payment.get("subscription_ids")
                    failed_subscription_id = str(payment.get("subscription_id") or "")
                    if isinstance(failed_subscription_ids, list):
                        if len(failed_subscription_ids) != 1:
                            await db.rollback()
                            return {"success": False, "status": "pending", "message": "Subscription is not confirmed yet."}
                        listed_id = str(failed_subscription_ids[0] or "")
                        if failed_subscription_id and failed_subscription_id != listed_id:
                            await db.rollback()
                            return {"success": False, "status": "unavailable", "message": "Subscription details did not match this checkout."}
                        failed_subscription_id = listed_id
                    if not failed_subscription_id:
                        await db.rollback()
                        return {"success": False, "status": "pending", "message": "Subscription is not confirmed yet."}
                    failed_subscription = self._provider_resource(
                        await self.provider.get_subscription(failed_subscription_id)
                    )
                    if not isinstance(failed_subscription, dict):
                        raise DodoAPIError(502, "invalid_provider_response")
                    failed_customer = failed_subscription.get("customer")
                    failed_customer = failed_customer if isinstance(failed_customer, dict) else {}
                    failed_payment_customer = payment.get("customer")
                    failed_payment_customer = failed_payment_customer if isinstance(failed_payment_customer, dict) else {}
                    failed_customer_id = str(
                        failed_customer.get("customer_id") or failed_subscription.get("customer_id") or ""
                    )
                    failed_customer_email = str(failed_customer.get("email") or "").strip().casefold()
                    if (
                        str(failed_subscription.get("subscription_id") or failed_subscription.get("id") or "")
                        != failed_subscription_id
                        or str(failed_subscription.get("status") or "").lower() != "failed"
                        or str(failed_subscription.get("product_id") or "") != expected_product_id
                        or type(failed_subscription.get("quantity")) is not int
                        or failed_subscription.get("quantity") != 1
                        or failed_customer_id != str(failed_payment_customer.get("customer_id") or "")
                        or str(failed_payment_customer.get("email") or "").strip().casefold() != owner_email
                        or failed_customer_email != owner_email
                        or not self._provider_metadata_matches(failed_subscription.get("metadata"), intent)
                    ):
                        await db.rollback()
                        return {"success": False, "status": "pending", "message": "Checkout is not confirmed as closed."}
                    await db.refresh(intent)
                    await db.refresh(user)
                    if (
                        intent.status not in {"checkout_pending", "checkout_unknown"}
                        or user.subscription_id != intent.id
                        or intent.provider_checkout_session_id != checkout_id
                    ):
                        await db.rollback()
                        return {"success": False, "status": "closed", "message": "Checkout changed while recovery was running."}
                    intent.provider_subscription_id = failed_subscription_id
                    intent.provider_customer_id = failed_customer_id
                    await self._end_subscription(db, intent, "failed")
                    await db.commit()
                    return {"success": False, "status": "closed", "message": "The provider confirmed this checkout failed."}

                if checkout_payment_status != "succeeded" or payment_status != "succeeded":
                    await db.rollback()
                    return {"success": False, "status": "pending", "message": "Payment is not confirmed yet."}

                payment_customer = payment.get("customer")
                payment_customer = payment_customer if isinstance(payment_customer, dict) else {}
                customer_id = str(payment_customer.get("customer_id") or "")
                payment_email = str(payment_customer.get("email") or "").strip().casefold()
                if not customer_id or payment_email != owner_email:
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Payment customer did not match this account."}

                # Dodo may omit product_cart for recurring payments. An explicit
                # cart must still match exactly; when it is null, defer product
                # proof to the independently retrieved subscription below.
                product_cart = payment.get("product_cart")
                if product_cart is not None and (
                    not isinstance(product_cart, list) or len(product_cart) != 1
                    or not isinstance(product_cart[0], dict)
                    or str(product_cart[0].get("product_id") or "") != expected_product_id
                    or type(product_cart[0].get("quantity")) is not int
                    or product_cart[0]["quantity"] != 1
                ):
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Paid product did not match this plan."}

                one_time = intent.plan_id == "lifetime"
                subscription_ids = payment.get("subscription_ids")
                provider_subscription_id = str(payment.get("subscription_id") or "")
                if subscription_ids is not None and not isinstance(subscription_ids, list):
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Subscription details did not match this checkout."}
                provider_subscription: dict[str, Any] = {}
                if one_time:
                    # Lifetime is a one-time product: require direct product
                    # proof, and never invent a recurring subscription or term.
                    if provider_subscription_id or subscription_ids or product_cart is None:
                        await db.rollback()
                        return {"success": False, "status": "unavailable", "message": "Lifetime payment did not match a one-time checkout."}
                else:
                    if isinstance(subscription_ids, list):
                        if len(subscription_ids) != 1:
                            await db.rollback()
                            return {"success": False, "status": "unavailable", "message": "Subscription details did not match this checkout."}
                        listed_id = str(subscription_ids[0] or "")
                        if provider_subscription_id and provider_subscription_id != listed_id:
                            await db.rollback()
                            return {"success": False, "status": "unavailable", "message": "Subscription details did not match this checkout."}
                        provider_subscription_id = listed_id
                    if not provider_subscription_id:
                        await db.rollback()
                        return {"success": False, "status": "pending", "message": "Subscription is not confirmed yet."}

                    provider_subscription = self._provider_resource(
                        await self.provider.get_subscription(provider_subscription_id)
                    )
                    if not isinstance(provider_subscription, dict):
                        raise DodoAPIError(502, "invalid_provider_response")
                    provider_sub_id = str(provider_subscription.get("subscription_id") or provider_subscription.get("id") or "")
                    sub_customer = provider_subscription.get("customer")
                    sub_customer = sub_customer if isinstance(sub_customer, dict) else {}
                    sub_customer_id = str(sub_customer.get("customer_id") or provider_subscription.get("customer_id") or "")
                    sub_email = str(sub_customer.get("email") or "").strip().casefold()
                    if (
                        provider_sub_id != provider_subscription_id
                        or str(provider_subscription.get("status") or "").lower() != "active"
                        or str(provider_subscription.get("product_id") or "") != expected_product_id
                        or type(provider_subscription.get("quantity")) is not int
                        or provider_subscription.get("quantity") != 1
                        or type(provider_subscription.get("tax_inclusive")) is not bool
                        or provider_subscription.get("tax_inclusive") is not intent.quoted_tax_inclusive
                        or sub_customer_id != customer_id
                        or sub_email != owner_email
                        or not self._provider_metadata_matches(provider_subscription.get("metadata"), intent)
                    ):
                        await db.rollback()
                        return {"success": False, "status": "unavailable", "message": "Subscription details did not match this checkout."}

                if product_cart is None:
                    # The validated subscription is authoritative for this
                    # nullable recurring-payment field; the common payment
                    # handler requires a canonical cart for its normal checks.
                    product_cart = [{
                        "product_id": str(provider_subscription["product_id"]),
                        "quantity": provider_subscription["quantity"],
                    }]

                plan = get_plan_config(intent.plan_id)
                expected_currency = str(plan.get("currency") or settings.BILLING_CURRENCY).upper()
                currency = str(payment.get("currency") or "").upper()
                amount, tax = payment.get("total_amount"), payment.get("tax")
                if tax is None:
                    tax = 0
                if (
                    currency != expected_currency
                    or type(amount) is not int or type(tax) is not int
                    or amount <= 0 or tax < 0 or tax > amount
                ):
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Payment amount could not be verified."}
                quoted_amount = amount if intent.quoted_tax_inclusive else amount - tax
                expected_amount = intent.quoted_amount * (100 - int(intent.discount_percent or 0)) // 100
                if quoted_amount != expected_amount:
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Payment amount did not match the checkout quote."}

                period_start = self._parse_time(provider_subscription.get("current_period_start"))
                period_end = self._parse_time(
                    provider_subscription.get("current_period_end")
                    or provider_subscription.get("next_billing_date")
                )
                if not one_time and (period_end is None or period_end <= datetime.now(timezone.utc)):
                    await db.rollback()
                    return {"success": False, "status": "pending", "message": "Current billing period is not confirmed yet."}

                # Recheck local lifecycle and ownership after provider I/O while
                # this intent row is still locked. The common payment handler
                # locks the same row before recording a payment.
                await db.refresh(intent)
                await db.refresh(user)
                if (
                    intent.status not in {"checkout_pending", "checkout_unknown", "active", "cancel_scheduled", "past_due", "on_hold", "paused"}
                    or user.subscription_id != intent.id
                    or intent.provider_checkout_session_id != checkout_id
                ):
                    await db.rollback()
                    return {"success": False, "status": "closed", "message": "Checkout changed while recovery was running."}

                event_data = {
                    "payload_type": "Payment", "payment_id": provider_payment_id, "status": "succeeded",
                    "currency": currency, "total_amount": amount, "tax": tax,
                    "customer": {"customer_id": customer_id, "email": owner_email},
                    "metadata": payment["metadata"], "checkout_session_id": checkout_id,
                    "subscription_id": provider_subscription_id, "product_cart": product_cart,
                    "payment_method": payment.get("payment_method"),
                }
                recovery_time = datetime.now(timezone.utc)
                payment_result = await self._handle_payment_succeeded(
                    db, event_data, {"timestamp": recovery_time.isoformat()}, current_state_verified=True,
                )
                if not payment_result.get("success"):
                    await db.rollback()
                    return {"success": False, "status": "unavailable", "message": "Payment could not be reconciled."}

                # The common handler commits the payment and entitlement. Re-lock
                # before copying provider-authoritative lifecycle dates so a
                # concurrent terminal webhook cannot be overwritten.
                refreshed_intent = await db.scalar(select(Subscription).where(
                    Subscription.id == intent.id, Subscription.user_id == user_id,
                ).with_for_update().execution_options(populate_existing=True))
                refreshed_user = await db.scalar(
                    select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
                )
                if refreshed_intent is None or refreshed_user is None:
                    await db.rollback()
                    return {"success": False, "status": "closed", "message": "Checkout changed during recovery."}
                if refreshed_intent.status in {"cancelled", "expired", "failed", "refunded"}:
                    await db.rollback()
                    return {"success": False, "status": "closed", "message": "Checkout is closed."}
                if refreshed_user.subscription_id != refreshed_intent.id:
                    await db.rollback()
                    return {"success": False, "status": "closed", "message": "Checkout is no longer current."}
                refreshed_intent.provider_subscription_id = provider_subscription_id or None
                refreshed_intent.provider_customer_id = customer_id
                newer_lifecycle_event = bool(
                    refreshed_intent.provider_event_at and refreshed_intent.provider_event_at > recovery_time
                )
                if (
                    not newer_lifecycle_event
                    and refreshed_intent.status in {"active", "cancel_scheduled"}
                ):
                    refreshed_intent.provider_product_id = expected_product_id
                    if period_start:
                        refreshed_intent.current_period_start = period_start
                    refreshed_intent.current_period_end = period_end
                    if (
                        refreshed_intent.status == "cancel_scheduled"
                        or provider_subscription.get("cancel_at_next_billing_date") is True
                    ):
                        refreshed_intent.status = "cancel_scheduled"
                        refreshed_user.subscription_status = "cancel_scheduled"
                    else:
                        refreshed_intent.status = "active"
                        refreshed_user.subscription_status = "active"
                await db.commit()
                return {
                    "success": True, "status": "reconciled", "subscriptionId": provider_subscription_id or None,
                    "planId": refreshed_intent.plan_id,
                    "currentPeriodEnd": refreshed_intent.current_period_end.isoformat()
                    if refreshed_intent.current_period_end else None,
                    "message": "Subscription restored from the provider's current payment state.",
                }
            except DodoAPIError as exc:
                await db.rollback()
                logger.warning("Dodo checkout recovery unavailable", extra={"status": exc.status_code, "code": exc.code})
                return {"success": False, "status": "unavailable", "message": "Payment status could not be checked yet."}
            except Exception as exc:
                await db.rollback()
                logger.error("Dodo checkout recovery failed", extra={"error_type": type(exc).__name__})
                return {"success": False, "status": "unavailable", "message": "Payment status could not be checked yet."}
        finally:
            try:
                await self._release_reconcile_lock(user_id, lock_token)
            except Exception as exc:
                logger.warning("Checkout recovery lock release failed", extra={"error_type": type(exc).__name__})

    @staticmethod
    def _verify_webhook_signature(payload: bytes, headers: dict[str, str], secret: str | None = None) -> bool:
        secret = secret or settings.dodo_webhook_key
        webhook_id = headers.get("webhook-id", "")
        timestamp = headers.get("webhook-timestamp", "")
        signatures = headers.get("webhook-signature", "")
        if not secret or not webhook_id or not timestamp or not signatures:
            return False
        try:
            ts = int(timestamp)
            if abs(time.time() - ts) > WEBHOOK_TOLERANCE_SECONDS:
                return False
            key = secret.removeprefix("whsec_")
            signing_key = base64.b64decode(key + "=" * (-len(key) % 4), validate=True)
            message = webhook_id.encode() + b"." + timestamp.encode() + b"." + payload
            expected = base64.b64encode(hmac.new(signing_key, message, hashlib.sha256).digest()).decode()
            return any(
                hmac.compare_digest(candidate.split(",", 1)[-1], expected)
                for candidate in signatures.split()
                if candidate.startswith("v1,")
            )
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _webhook_snapshot_matches(
        event: BillingWebhookEvent, *, event_type: str, resource_id: str | None,
        event_at: datetime | None, digest: str,
    ) -> bool:
        if event.payload_sha256 == digest:
            return True
        # Dodo signs the latest resource snapshot on each delivery, so mutable
        # payload fields may legitimately change on retry. Only a persisted
        # immutable identity can authorize that change; legacy hash-only rows
        # and malformed events keep the original fail-closed behavior.
        return bool(
            event.event_resource_id and resource_id == event.event_resource_id
            and event.event_type == event_type
            and event_at is not None and event.event_at == event_at
        )

    async def handle_webhook(self, db: AsyncSession, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
        if settings.is_production_like() and settings.normalized_dodo_mode != "live":
            return {"success": False, "retryable": False, "error": "Production Dodo webhooks require live mode"}
        normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
        if not self._verify_webhook_signature(payload, normalized_headers):
            return {"success": False, "retryable": False, "error": "Invalid webhook signature"}
        try:
            envelope = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return {"success": False, "retryable": False, "error": "Invalid webhook JSON"}
        if not isinstance(envelope, dict):
            return {"success": False, "retryable": False, "error": "Invalid webhook envelope"}
        event_id, event_type, data = normalized_headers["webhook-id"], envelope.get("type"), envelope.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            return {"success": False, "retryable": False, "error": "Missing webhook fields"}
        if settings.dodo_business_id and envelope.get("business_id") != settings.dodo_business_id:
            return {"success": False, "retryable": False, "error": "Webhook belongs to a different Dodo business"}
        digest = hashlib.sha256(payload).hexdigest()
        event_at = self._parse_time(envelope.get("timestamp"))
        resource_key = {"Payment": "payment_id", "Subscription": "subscription_id", "Refund": "refund_id"}.get(
            data.get("payload_type") if isinstance(data.get("payload_type"), str) else "",
        )
        resource_id = data.get(resource_key) if resource_key else None
        if not isinstance(resource_id, str) or not resource_id or len(resource_id) > 255:
            resource_id = None
        snapshot = {"event_type": event_type, "resource_id": resource_id, "event_at": event_at, "digest": digest}
        event = await db.scalar(select(BillingWebhookEvent).where(
            BillingWebhookEvent.provider == "dodo", BillingWebhookEvent.event_id == event_id,
        ).with_for_update().execution_options(populate_existing=True))
        if event and not self._webhook_snapshot_matches(event, **snapshot):
            await db.rollback()
            return {"success": False, "retryable": False, "error": "Webhook ID payload mismatch"}
        if event and event.status == "processed":
            await db.rollback()
            return {"success": True, "duplicate": True}
        if event:
            event.attempts += 1
            event.payload_sha256 = digest
            event.status, event.last_error = "processing", None
        else:
            event = BillingWebhookEvent(provider="dodo", event_id=event_id, event_type=event_type,
                                        payload_sha256=digest, event_at=event_at, event_resource_id=resource_id,
                                        status="processing", attempts=1)
            db.add(event)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            event = await db.scalar(select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == "dodo", BillingWebhookEvent.event_id == event_id,
            ))
            if event and event.status == "processed" and self._webhook_snapshot_matches(event, **snapshot):
                return {"success": True, "duplicate": True}
            return {"success": False, "retryable": True, "error": "Webhook is already being processed"}
        try:
            event = await db.scalar(select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == "dodo", BillingWebhookEvent.event_id == event_id,
            ).with_for_update().execution_options(populate_existing=True))
            if event and event.status == "processed":
                await db.rollback()
                return {"success": True, "duplicate": True}
            if event is None or event.payload_sha256 != digest:
                await db.rollback()
                return {"success": False, "retryable": True, "error": "A newer webhook snapshot is being processed"}
            result = await self._process_webhook_event(db, event_type, data, envelope)
            if not result.get("success"):
                raise ValueError(result.get("error", "Webhook could not be reconciled"))
            event = await db.scalar(select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == "dodo", BillingWebhookEvent.event_id == event_id,
            ).with_for_update().execution_options(populate_existing=True))
            if event.payload_sha256 == digest:
                event.status, event.last_error, event.processed_at = "processed", None, datetime.now(timezone.utc)
            await db.commit()
            return {"success": True}
        except Exception as exc:
            await db.rollback()
            event = await db.scalar(select(BillingWebhookEvent).where(
                BillingWebhookEvent.provider == "dodo", BillingWebhookEvent.event_id == event_id,
            ).with_for_update().execution_options(populate_existing=True))
            if event and event.status != "processed" and event.payload_sha256 == digest:
                event.status = "failed"
                event.last_error = type(exc).__name__[:240]
                await db.commit()
            else:
                await db.rollback()
            logger.error("Dodo webhook processing failed", extra={"error_type": type(exc).__name__})
            return {"success": False, "retryable": True, "error": "Webhook processing failed"}

    async def _process_webhook_event(
        self, db: AsyncSession, event_type: str, data: dict[str, Any], envelope: dict[str, Any],
    ) -> dict[str, Any]:
        if data.get("payload_type") not in {"Payment", "Subscription", "Refund"}:
            return {"success": False, "error": "Unsupported webhook payload type"}
        customer = data.get("customer")
        if customer is not None and not isinstance(customer, dict):
            return {"success": False, "error": "Invalid webhook customer"}
        if event_type.startswith("payment."):
            if event_type == "payment.succeeded":
                return await self._handle_payment_succeeded(db, data, envelope)
            if event_type in {"payment.failed", "payment.cancelled"}:
                # A failed/cancelled charge is not proof that its subscription
                # is terminal. Dodo uses subscription.failed for terminal
                # checkout creation failures and subscription lifecycle events
                # for recoverable retries, so retain the intent/reservation.
                return {"success": True}
            return {"success": True}
        if event_type.startswith("subscription."):
            return await self._handle_subscription_event(db, event_type, data, envelope)
        if event_type.startswith("refund."):
            return await self._handle_refund_event(db, event_type, data)
        # Disputes are retained as durable events for admin reconciliation. They
        # do not silently alter access until an explicit dispute policy exists.
        return {"success": True}

    async def _resolve_intent(self, db: AsyncSession, data: dict[str, Any]) -> Subscription | None:
        metadata = data.get("metadata") or {}
        intent_id = metadata.get("latexy_intent_id") if isinstance(metadata, dict) else None
        if intent_id:
            row = await db.get(Subscription, str(intent_id))
            if row and row.provider == "dodo":
                return row
        session_id = data.get("checkout_session_id")
        if session_id:
            return await db.scalar(select(Subscription).where(
                Subscription.provider == "dodo", Subscription.provider_checkout_session_id == str(session_id),
            ))
        provider_sub_id = data.get("subscription_id")
        if provider_sub_id:
            return await db.scalar(select(Subscription).where(
                Subscription.provider == "dodo", Subscription.provider_subscription_id == str(provider_sub_id),
            ))
        return None

    def _resolve_configured_plan_for_product(self, product_id: str) -> str | None:
        candidates = [
            plan_id for plan_id in settings.SUBSCRIPTION_PLANS
            if get_dodo_product_id(plan_id) == product_id
        ]
        candidates.extend(
            plan_id for plan_id in ("weekly", "lifetime")
            if get_dodo_product_id(plan_id) == product_id and plan_id not in candidates
        )
        return candidates[0] if len(candidates) == 1 else None

    async def _handle_payment_succeeded(
        self,
        db: AsyncSession,
        data: dict[str, Any],
        envelope: dict[str, Any],
        *,
        current_state_verified: bool = False,
    ) -> dict[str, Any]:
        if str(data.get("status") or "").lower() != "succeeded":
            return {"success": False, "error": "Payment event is not in succeeded state"}
        intent = await self._resolve_intent(db, data)
        if not intent:
            return {"success": False, "error": "Payment did not match a local checkout intent"}
        intent = await db.scalar(
            select(Subscription).where(Subscription.id == intent.id).with_for_update()
            .execution_options(populate_existing=True)
        )
        if intent is None:
            return {"success": False, "error": "Local checkout intent disappeared"}
        terminal_intent = intent.status in {"cancelled", "expired", "failed", "refunded"}
        # A checkout can remain payable at the provider after the local intent
        # is closed. Verify and ledger a genuine late capture for reconciliation,
        # while keeping the terminal intent and its user's access closed.
        now = self._parse_time(envelope.get("timestamp")) or datetime.now(timezone.utc)
        stale_event = (
            not current_state_verified
            and intent.provider_event_at is not None
            and intent.provider_event_at > now
        )
        plan = get_plan_config(intent.plan_id)
        product_cart = data.get("product_cart")
        if product_cart is None and data.get("subscription_id"):
            # Dodo's recurring payment webhook can omit product_cart. Resolve
            # the subscription with the authenticated API, then apply the same
            # local product, quantity, and ownership checks as checkout.
            try:
                provider_subscription = await self.provider.get_subscription(str(data["subscription_id"]))
            except DodoAPIError:
                logger.warning("Could not reconcile Dodo subscription payment")
                return {"success": False, "error": "Paid subscription could not be verified"}
            if not isinstance(provider_subscription, dict):
                return {"success": False, "error": "Paid subscription could not be verified"}
            if isinstance(provider_subscription.get("data"), dict):
                provider_subscription = provider_subscription["data"]
            provider_sub_id = str(provider_subscription.get("subscription_id") or provider_subscription.get("id") or "")
            provider_product_id = str(provider_subscription.get("product_id") or "")
            provider_quantity = provider_subscription.get("quantity")
            provider_customer = provider_subscription.get("customer") or {}
            provider_customer_id = str(
                (provider_customer.get("customer_id") if isinstance(provider_customer, dict) else None)
                or provider_subscription.get("customer_id")
                or ""
            )
            webhook_customer = data.get("customer") or {}
            webhook_customer_id = str(webhook_customer.get("customer_id") or "") if isinstance(webhook_customer, dict) else ""
            metadata = data.get("metadata") or {}
            if (
                provider_sub_id != str(data.get("subscription_id") or "")
                or provider_product_id != str(intent.provider_product_id or "")
                or type(provider_quantity) is not int
                or provider_quantity != 1
                or not provider_customer_id
                or (intent.provider_customer_id and provider_customer_id != intent.provider_customer_id)
                or (webhook_customer_id and webhook_customer_id != provider_customer_id)
                or (not intent.provider_customer_id and (
                    not isinstance(metadata, dict)
                    or str(metadata.get("latexy_user_id") or "") != intent.user_id
                    or not webhook_customer_id
                ))
            ):
                return {"success": False, "error": "Paid subscription does not match the local checkout"}
            if not terminal_intent and not intent.provider_customer_id:
                intent.provider_customer_id = provider_customer_id
            product_cart = [{"product_id": provider_product_id, "quantity": provider_quantity}]
        if not isinstance(product_cart, list) or len(product_cart) != 1:
            return {"success": False, "error": "Paid product does not match the local plan"}
        product = product_cart[0]
        if (
            not isinstance(product, dict)
            or str(product.get("product_id") or "") != str(intent.provider_product_id or "")
            or type(product.get("quantity")) is not int
            or product.get("quantity") != 1
        ):
            return {"success": False, "error": "Paid product does not match the local plan"}
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            return {"success": False, "error": "Paid metadata does not match the local checkout"}
        if (
            metadata.get("latexy_intent_id") not in {None, intent.id}
            or metadata.get("latexy_user_id") not in {None, intent.user_id}
        ):
            return {"success": False, "error": "Paid ownership does not match the local checkout"}
        webhook_customer = data.get("customer") or {}
        if not isinstance(webhook_customer, dict):
            return {"success": False, "error": "Invalid webhook customer"}
        webhook_customer_id = str(webhook_customer.get("customer_id") or "")
        if intent.provider_customer_id and webhook_customer_id and webhook_customer_id != intent.provider_customer_id:
            return {"success": False, "error": "Payment customer does not match the local intent"}
        if isinstance(metadata, dict) and metadata.get("latexy_plan_id") not in {None, intent.plan_id}:
            return {"success": False, "error": "Paid plan does not match the local checkout"}
        checkout_session_id = str(data.get("checkout_session_id") or "")
        if intent.provider_checkout_session_id and checkout_session_id and checkout_session_id != intent.provider_checkout_session_id:
            return {"success": False, "error": "Payment checkout does not match the local intent"}
        provider_subscription_id = str(data.get("subscription_id") or "")
        if (
            intent.provider_subscription_id
            and provider_subscription_id
            and provider_subscription_id != intent.provider_subscription_id
        ):
            return {"success": False, "error": "Payment subscription does not match the local intent"}
        currency = str(data.get("currency") or "").upper()
        expected_currency = str(plan.get("currency") or settings.BILLING_CURRENCY).upper()
        if currency != expected_currency:
            return {"success": False, "error": "Paid currency does not match the local plan"}
        payment_id = str(data.get("payment_id") or "")
        raw_amount, raw_tax = data.get("total_amount"), data.get("tax")
        if type(raw_amount) is not int or (raw_tax is not None and type(raw_tax) is not int):
            return {"success": False, "error": "Paid event is missing a valid transaction"}
        amount, tax = raw_amount, raw_tax or 0
        if not payment_id or amount <= 0 or tax < 0 or tax > amount:
            return {"success": False, "error": "Paid event is missing a valid transaction"}
        # Dodo reports total_amount including tax and tax separately. For
        # tax-inclusive catalog items the quoted price is the gross amount;
        # for exclusive items it is the pre-tax subtotal. Checkout metadata
        # snapshots that choice for this intent.
        configured_tax_inclusive = plan.get("tax_inclusive", True)
        raw_tax_inclusive = metadata.get("latexy_tax_inclusive")
        if raw_tax_inclusive is None:
            tax_inclusive = (
                intent.quoted_tax_inclusive
                if intent.quoted_tax_inclusive is not None
                else configured_tax_inclusive
            )
        elif raw_tax_inclusive in (True, "true"):
            tax_inclusive = True
        elif raw_tax_inclusive in (False, "false"):
            tax_inclusive = False
        else:
            return {"success": False, "error": "Paid tax settings do not match the local checkout"}
        if type(tax_inclusive) is not bool:
            return {"success": False, "error": "Local tax settings are invalid"}
        if intent.quoted_tax_inclusive is not None and tax_inclusive != intent.quoted_tax_inclusive:
            return {"success": False, "error": "Paid tax settings do not match the local checkout"}
        quoted_amount = amount if tax_inclusive else amount - tax
        quoted = int(intent.quoted_amount or plan.get("price") or 0)
        expected = quoted * (100 - int(intent.discount_percent or 0)) // 100
        if quoted_amount < 1 or quoted_amount != expected:
            logger.error("Rejecting Dodo payment with unexpected subtotal", extra={"plan_id": intent.plan_id})
            return {"success": False, "error": "Paid amount does not match the configured plan price"}
        if intent.quoted_tax_inclusive is None and not terminal_intent:
            intent.quoted_tax_inclusive = tax_inclusive
        if not terminal_intent:
            await self._set_coupon_reservation_status(db, intent.id, "redeemed")
        existing = await db.scalar(select(Payment).where(Payment.provider == "dodo", Payment.provider_payment_id == payment_id))
        if existing:
            if existing.user_id != intent.user_id or existing.subscription_id != intent.id:
                return {"success": False, "error": "Payment identifier is already attached to another checkout"}
            payment = existing
        else:
            payment = Payment(user_id=intent.user_id, subscription_id=intent.id, provider="dodo",
                              provider_payment_id=payment_id, amount=amount, currency=currency,
                              status="paid", payment_method=str(data.get("payment_method") or "") or None,
                              provider_event_at=now)
            db.add(payment)
        if not terminal_intent:
            intent.provider_subscription_id = provider_subscription_id or intent.provider_subscription_id or None
            webhook_customer = data.get("customer") or {}
            webhook_customer_id = webhook_customer.get("customer_id") if isinstance(webhook_customer, dict) else None
            intent.provider_customer_id = str(webhook_customer_id or intent.provider_customer_id or "") or None
        was_duplicate = existing is not None
        if not stale_event and intent.status not in {"cancelled", "expired", "failed", "refunded"}:
            if intent.status != "cancel_scheduled":
                intent.status = "active"
            if intent.provider_event_at is None or now > intent.provider_event_at:
                intent.provider_event_at = now
        # Lifecycle webhooks can arrive before the initial payment event. An
        # older, verified payment still proves paid access when the newer state
        # is active, without rolling back newer pause/termination state or dates.
        can_grant_access = (
            intent.status not in {"cancelled", "expired", "failed", "refunded"}
            and (not stale_event or intent.status in {"active", "cancel_scheduled"})
            and payment.status in {"paid", "partially_refunded"}
        )
        if intent.plan_id != "lifetime":
            if (
                not stale_event
                and not was_duplicate
                and intent.current_period_end is None
                and intent.status not in {"cancelled", "expired", "failed", "refunded"}
            ):
                # subscription.active/renewed carries Dodo's authoritative
                # next_billing_date. Only derive a period when no lifecycle
                # event has supplied one; adding a delta to an existing end
                # double-extends renewals when the renewal event arrives first.
                intent.current_period_start = now
                intent.current_period_end = now + self._period_delta(intent.plan_id)
            user = await db.get(User, intent.user_id)
            if can_grant_access and user and (not user.subscription_id or user.subscription_id == intent.id):
                user.subscription_plan = intent.plan_id
                user.subscription_status = "cancel_scheduled" if intent.status == "cancel_scheduled" else "active"
                user.subscription_id = intent.id
            if can_grant_access and resolve_plan_family(intent.plan_id) == "team":
                await self._restore_team_seats(db, intent.user_id)
        else:
            if not stale_event:
                intent.current_period_end = None
            user = await db.get(User, intent.user_id)
            if can_grant_access and user and (not user.subscription_id or user.subscription_id == intent.id):
                user.subscription_plan, user.subscription_status, user.subscription_id = "lifetime", "active", intent.id
        await db.commit()
        record_business_event("payment", "success")
        if not terminal_intent:
            try:
                await referral_service.qualify_paid_payment(db, payment.id)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.error("Referral qualification failed after payment", extra={"error_type": type(exc).__name__})
                raise
        return {"success": True}

    async def _handle_subscription_event(
        self, db: AsyncSession, event_type: str, data: dict[str, Any], envelope: dict[str, Any],
    ) -> dict[str, Any]:
        intent = await self._resolve_intent(db, data)
        if not intent:
            return {"success": False, "error": "Subscription did not match a local checkout intent"}
        intent = await db.scalar(
            select(Subscription).where(Subscription.id == intent.id).with_for_update()
            .execution_options(populate_existing=True)
        )
        if intent is None:
            return {"success": False, "error": "Subscription did not match a local checkout intent"}
        sub_id = str(data.get("subscription_id") or "")
        if not sub_id or (intent.provider_subscription_id and sub_id != intent.provider_subscription_id):
            return {"success": False, "error": "Subscription identifier does not match the local intent"}
        product_id = str(data.get("product_id") or "")
        plan_change = event_type == "subscription.plan_changed"
        next_plan_id: str | None = None
        if plan_change:
            next_plan_id = self._resolve_configured_plan_for_product(product_id)
            if not next_plan_id:
                return {"success": False, "error": "Changed product does not match a configured plan"}
            next_plan = get_plan_config(next_plan_id)
            currency = str(data.get("currency") or "").upper()
            expected_currency = str(next_plan.get("currency") or settings.BILLING_CURRENCY).upper()
            if currency != expected_currency:
                return {"success": False, "error": "Changed subscription currency does not match the configured plan"}
            next_tax_inclusive = data.get("tax_inclusive")
            if type(next_tax_inclusive) is not bool or (
                intent.quoted_tax_inclusive is not None
                and next_tax_inclusive != intent.quoted_tax_inclusive
            ):
                return {"success": False, "error": "Changed subscription tax settings do not match the local quote"}
            recurring_amount = data.get("recurring_pre_tax_amount")
            if type(recurring_amount) is not int:
                return {"success": False, "error": "Changed subscription is missing its recurring amount"}
            expected_amount = int(next_plan.get("price") or 0) * (100 - int(intent.discount_percent or 0)) // 100
            if expected_amount <= 0 or recurring_amount != expected_amount:
                return {"success": False, "error": "Changed subscription amount does not match the configured plan"}
        elif intent.provider_product_id and product_id != intent.provider_product_id:
            return {"success": False, "error": "Subscription product does not match the local intent"}
        if not product_id:
            return {"success": False, "error": "Subscription event is missing its product"}
        event_at = self._parse_time(envelope.get("timestamp")) or datetime.now(timezone.utc)
        if intent.provider_event_at and intent.provider_event_at > event_at:
            return {"success": True}
        customer = data.get("customer") or {}
        customer_id = str(customer.get("customer_id") or "")
        if intent.provider_customer_id and customer_id and customer_id != intent.provider_customer_id:
            return {"success": False, "error": "Subscription customer does not match the local intent"}
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict) or (
            metadata.get("latexy_intent_id") not in {None, intent.id}
            or metadata.get("latexy_user_id") not in {None, intent.user_id}
        ):
            return {"success": False, "error": "Subscription ownership does not match the local intent"}
        if intent.status in {"cancelled", "expired", "failed", "refunded"}:
            metadata = data.get("metadata") or {}
            if (
                (intent.provider_customer_id and customer_id != intent.provider_customer_id)
                or (
                    not intent.provider_customer_id
                    and (
                        not isinstance(metadata, dict)
                        or metadata.get("latexy_intent_id") != intent.id
                        or metadata.get("latexy_user_id") != intent.user_id
                    )
                )
            ):
                return {"success": False, "error": "Subscription ownership does not match the local intent"}
            await db.rollback()
            return {"success": True}
        intent.provider_subscription_id = sub_id
        intent.provider_customer_id = customer_id or intent.provider_customer_id or None
        if plan_change and next_plan_id:
            old_family = resolve_plan_family(intent.plan_id)
            new_family = resolve_plan_family(next_plan_id)
            intent.plan_id = next_plan_id
            intent.provider_product_id = product_id
            intent.quoted_amount = int(get_plan_config(next_plan_id).get("price") or 0)
            user = await db.get(User, intent.user_id)
            if user and user.subscription_id == intent.id and intent.status in {"active", "cancel_scheduled"}:
                user.subscription_plan = next_plan_id
            if old_family == "team" and new_family != "team":
                await self._revoke_team_seats(db, intent.user_id)
            elif old_family != "team" and new_family == "team":
                await self._restore_team_seats(db, intent.user_id)
        else:
            intent.provider_product_id = product_id
        intent.provider_event_at = event_at
        status = str(data.get("status") or "").lower()
        # Dodo delivers the latest resource snapshot, including on retries of
        # older event types. The payload's status must win over the event name.
        state_event = {
            "active": "subscription.updated", "past_due": "subscription.past_due",
            "on_hold": "subscription.on_hold", "paused": "subscription.paused",
            "cancelled": "subscription.cancelled", "failed": "subscription.failed",
            "expired": "subscription.expired", "pending": "subscription.updated",
        }.get(status, event_type)
        if data.get("next_billing_date"):
            intent.current_period_end = self._parse_time(data["next_billing_date"])
        if state_event in {"subscription.active", "subscription.renewed", "subscription.updated", "subscription.unpaused"}:
            # A subscription lifecycle event alone never grants paid access; a
            # matching, succeeded payment event performs that entitlement change.
            if status in {"paused", "on_hold", "past_due"}:
                intent.status = status
            elif status in {"failed", "cancelled", "expired"}:
                await self._end_subscription(db, intent, "failed" if status == "failed" else status)
            elif status == "active":
                if data.get("cancel_at_next_billing_date") is True:
                    intent.status = "cancel_scheduled"
                elif data.get("cancel_at_next_billing_date") is False or intent.status != "cancel_scheduled":
                    intent.status = "active"
            elif intent.status not in {"active", "cancel_scheduled"}:
                intent.status = "checkout_pending" if status in {"pending", ""} else status
            if status in {"paused", "on_hold", "past_due"}:
                if status == "past_due" and data.get("past_due_ends_at"):
                    intent.current_period_end = self._parse_time(data["past_due_ends_at"])
                user = await db.get(User, intent.user_id)
                if user and user.subscription_id == intent.id:
                    user.subscription_status = status
            elif status == "active":
                user = await db.get(User, intent.user_id)
                if user and user.subscription_id == intent.id and user.subscription_plan == intent.plan_id:
                    # Keep an already-entitled customer in sync, including when
                    # an earlier updated event changed only the local intent.
                    user.subscription_status = intent.status
        elif state_event == "subscription.past_due":
            intent.status = "past_due"
            if data.get("past_due_ends_at"):
                intent.current_period_end = self._parse_time(data["past_due_ends_at"])
            user = await db.get(User, intent.user_id)
            if user and user.subscription_id == intent.id:
                user.subscription_status = "past_due"
        elif state_event == "subscription.on_hold":
            intent.status = "on_hold"
            user = await db.get(User, intent.user_id)
            if user and user.subscription_id == intent.id:
                user.subscription_status = "on_hold"
        elif state_event == "subscription.paused":
            intent.status = "paused"
            user = await db.get(User, intent.user_id)
            if user and user.subscription_id == intent.id:
                user.subscription_status = "paused"
        elif state_event == "subscription.cancelled":
            if data.get("cancel_at_next_billing_date") and intent.current_period_end and intent.current_period_end > event_at:
                intent.status = "cancel_scheduled"
                user = await db.get(User, intent.user_id)
                if user and user.subscription_id == intent.id:
                    user.subscription_status = "cancel_scheduled"
            else:
                await self._end_subscription(db, intent, "cancelled")
        elif state_event in {"subscription.failed", "subscription.expired"}:
            await self._end_subscription(db, intent, "failed" if state_event.endswith("failed") else "expired")
        await db.commit()
        return {"success": True}

    async def _end_subscription(self, db: AsyncSession, intent: Subscription, status: str) -> None:
        intent.status = status
        intent.cancelled_at = datetime.now(timezone.utc)
        await self._set_coupon_reservation_status(db, intent.id, "released")
        user = await db.get(User, intent.user_id)
        if user and user.subscription_id == intent.id:
            user.subscription_plan, user.subscription_status, user.subscription_id = "free", status, None
        if resolve_plan_family(intent.plan_id) == "team":
            await self._revoke_team_seats(db, intent.user_id)

    async def _handle_refund_event(self, db: AsyncSession, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        refund_id, payment_id = str(data.get("refund_id") or ""), str(data.get("payment_id") or "")
        if not refund_id or not payment_id:
            return {"success": False, "error": "Refund event is missing identifiers"}
        payment = await db.scalar(select(Payment).where(
            Payment.provider == "dodo", Payment.provider_payment_id == payment_id,
        ).with_for_update().execution_options(populate_existing=True))
        if not payment:
            return {"success": False, "error": "Refund does not match a local payment"}
        status = str(data.get("status") or ("succeeded" if event_type == "refund.succeeded" else "failed")).lower()
        if status not in {"succeeded", "failed", "pending", "review"}:
            return {"success": False, "error": "Refund has an unsupported status"}
        currency = str(data.get("currency") or payment.currency).upper()
        if currency != str(payment.currency or "").upper():
            return {"success": False, "error": "Refund currency does not match the payment"}
        raw_amount = data.get("amount")
        if raw_amount is not None and type(raw_amount) is not int:
            return {"success": False, "error": "Refund amount is invalid"}
        if status == "succeeded" and (raw_amount is None or raw_amount <= 0 or raw_amount > payment.amount):
            return {"success": False, "error": "Refund amount is invalid"}
        refund = await db.scalar(select(PaymentRefund).where(
            PaymentRefund.provider == "dodo", PaymentRefund.provider_refund_id == refund_id,
        ))
        if refund is not None and refund.payment_id != payment.id:
            return {"success": False, "error": "Refund identifier is already attached to another payment"}
        if refund is not None and refund.status == "succeeded" and status != "succeeded":
            # A later delivery/replay cannot roll a settled refund back to a
            # nonterminal or failed ledger state.
            return {"success": True}
        if refund is not None and refund.status == "succeeded" and status == "succeeded":
            # A provider refund ID is immutable once settled. Treat an exact
            # duplicate as idempotent, but never rewrite its settled amount or
            # re-run payment/referral side effects from a conflicting payload.
            if refund.amount != raw_amount or str(refund.currency or "").upper() != currency:
                return {"success": False, "error": "Settled refund details do not match the existing refund"}
            return {"success": True}
        if status == "succeeded":
            succeeded = await db.scalars(select(PaymentRefund.amount).where(
                PaymentRefund.payment_id == payment.id,
                PaymentRefund.status == "succeeded",
                PaymentRefund.provider_refund_id != refund_id,
            ))
            if sum(int(n or 0) for n in succeeded.all()) + raw_amount > payment.amount:
                return {"success": False, "error": "Refund total exceeds the payment amount"}
        if refund is None:
            refund = PaymentRefund(payment_id=payment.id, provider="dodo", provider_refund_id=refund_id,
                                   amount=raw_amount,
                                   currency=currency,
                                   status=status, reason=str(data.get("reason") or "")[:500] or None)
            db.add(refund)
        else:
            refund.status = status
            if raw_amount is not None:
                refund.amount = raw_amount
        if status == "succeeded":
            succeeded = await db.scalars(select(PaymentRefund.amount).where(
                PaymentRefund.payment_id == payment.id, PaymentRefund.status == "succeeded",
            ))
            total = sum(int(n or 0) for n in succeeded.all())
            previous_payment_status = payment.status
            if total >= payment.amount:
                payment.status = "refunded"
                intent = await db.get(Subscription, payment.subscription_id) if payment.subscription_id else None
                if intent and intent.plan_id == "lifetime":
                    await self._end_subscription(db, intent, "refunded")
                if previous_payment_status != "refunded":
                    await referral_service.reverse_paid_payment(db, payment.id)
            elif total:
                payment.status = "partially_refunded"
        await db.commit()
        return {"success": True}

    async def _revoke_team_seats(self, db: AsyncSession, owner_user_id: str) -> int:
        result = await db.execute(select(TeamSeat.member_user_id).where(
            TeamSeat.owner_user_id == owner_user_id, TeamSeat.status == "active", TeamSeat.member_user_id.is_not(None),
        ))
        member_ids = [r[0] for r in result.all()]
        if not member_ids:
            return 0
        await db.execute(update(TeamSeat).where(
            TeamSeat.owner_user_id == owner_user_id, TeamSeat.status == "active",
        ).values(status="revoked"))
        await db.execute(update(User).where(User.id.in_(member_ids), User.subscription_plan == "team_member")
                         .values(subscription_plan="free", subscription_status="inactive"))
        return len(member_ids)

    async def _restore_team_seats(self, db: AsyncSession, owner_user_id: str) -> int:
        result = await db.execute(select(TeamSeat.member_user_id).where(
            TeamSeat.owner_user_id == owner_user_id, TeamSeat.status == "active", TeamSeat.member_user_id.is_not(None),
        ))
        member_ids = [r[0] for r in result.all()]
        if not member_ids:
            return 0
        await db.execute(update(User).where(User.id.in_(member_ids), User.subscription_plan == "free")
                         .values(subscription_plan="team_member", subscription_status="active"))
        return len(member_ids)


payment_service = PaymentService()

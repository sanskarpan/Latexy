"""
FastAPI application main module.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .api.routes import _check_cors_origins_on_startup, router
from .core.config import settings
from .core.errors import register_exception_handlers
from .core.event_bus import event_bus
from .core.logging import get_logger, setup_logging
from .core.redis import get_redis_client, redis_manager
from .core.tracing import instrument_fastapi, setup_telemetry
from .database.connection import close_db, init_db
from .middleware.limits import BodySizeLimitMiddleware, TimeoutMiddleware
from .middleware.rate_limiting import APIKeyRateLimitMiddleware, RateLimitMiddleware
from .middleware.request_context import RequestContextMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tenant_middleware import TenantMiddleware
from .services.latex_compiler import latex_compiler

# Setup logging
setup_logging()
setup_telemetry("api")
logger = get_logger(__name__)


async def _check_coupon_offer_mappings_on_startup() -> None:
    """Report which active percentage coupons Razorpay can actually apply.

    A percentage discount reaches Razorpay only through an offer ID mapped in
    RAZORPAY_COUPON_OFFERS; validate_coupon refuses any code without one rather
    than charging full price behind an advertised discount. That refusal is
    invisible until a customer hits checkout, so list the state at boot.

    Best-effort: a failure here must never crash startup.
    """
    try:
        from datetime import datetime, timezone

        from sqlalchemy import or_
        from sqlalchemy import select as _select

        from .core.config import get_razorpay_offer_id
        from .database.connection import get_async_db_session
        from .database.models import CouponCode

        now = datetime.now(timezone.utc)
        async with get_async_db_session() as session:
            result = await session.execute(
                _select(CouponCode.code).where(
                    CouponCode.discount_percent > 0,
                    or_(CouponCode.expires_at.is_(None), CouponCode.expires_at > now),
                )
            )
            codes = [row[0] for row in result.all()]

        if not codes:
            return

        mapped = [c for c in codes if get_razorpay_offer_id(c)]
        unmapped = [c for c in codes if c not in mapped]
        logger.info("Coupon offer mapping: %d of %d active percentage coupon(s) redeemable: %s",
                    len(mapped), len(codes), ", ".join(sorted(mapped)) or "none")
        if unmapped:
            logger.warning(
                "Coupon codes with no RAZORPAY_COUPON_OFFERS entry will be refused at "
                "checkout: %s",
                ", ".join(sorted(unmapped)),
            )
    except Exception as e:  # pragma: no cover - diagnostics only
        logger.error(f"Coupon offer mapping check failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Latexy Backend starting up...")

    # Initialize database connection
    try:
        await init_db()
        logger.info("Database connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Reconcile admin roles from ADMIN_EMAIL(S). Any user whose email is in the
    # configured admin set but whose role != 'admin' is promoted. Best-effort:
    # a failure here must never crash startup.
    admin_emails = settings.admin_email_set()
    if admin_emails:
        try:
            from sqlalchemy import text as _text

            from .database.connection import get_async_db_session
            async with get_async_db_session() as session:
                result = await session.execute(
                    _text(
                        "UPDATE users SET role = 'admin' "
                        "WHERE lower(email) = ANY(:emails) AND role != 'admin'"
                    ),
                    {"emails": list(admin_emails)},
                )
                await session.commit()
                logger.info(
                    "Admin role reconcile: promoted %s user(s) from %d configured admin email(s)",
                    result.rowcount if result.rowcount is not None else "?",
                    len(admin_emails),
                )
        except Exception as e:
            logger.error(f"Admin role reconcile failed (non-fatal): {e}")

    # Validate Redis URL before connecting (OBS-004)
    if not settings.REDIS_URL or "localhost" in settings.REDIS_URL.lower():
        if settings.ENVIRONMENT in ("production", "staging"):
            logger.warning("REDIS_URL points to localhost in production environment")

    # Initialize Redis connections
    try:
        await redis_manager.init_redis()
        logger.info("Redis connections initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        # Redis is not critical for basic functionality, so don't raise
        logger.warning("Continuing without Redis - some features may be limited")

    # Initialize EventBusManager (WebSocket → Redis Pub/Sub bridge)
    try:
        async_redis = await get_redis_client()
        await event_bus.init(async_redis)
        logger.info("EventBusManager initialized")
    except Exception as e:
        logger.error(f"Failed to initialize EventBusManager: {e}")
        logger.warning("Real-time WebSocket events will not be available")

    # Check LaTeX installation
    if not latex_compiler.is_available():
        logger.warning(
            "LaTeX compilation is unavailable (mode=%s)",
            latex_compiler.capability_summary(),
        )
    else:
        logger.info(
            "LaTeX compilation available (mode=%s)",
            latex_compiler.capability_summary(),
        )

    # Ensure temp directory exists
    settings.TEMP_DIR.mkdir(exist_ok=True)
    logger.info(f"Temporary directory ready: {settings.TEMP_DIR}")

    # CONFIG-002: Warn if CORS origins include localhost in production
    _check_cors_origins_on_startup()

    # Surface coupons that checkout will refuse before a customer finds them.
    await _check_coupon_offer_mappings_on_startup()

    yield

    # Shutdown
    logger.info("Latexy Backend shutting down...")
    # Collaboration bridges own Redis Pub/Sub connections and must finish
    # their asynchronous unsubscribe/close paths while Redis and the event
    # loop are still available.
    from .services.collab_manager import collab_manager

    await collab_manager.shutdown()
    await close_db()
    await redis_manager.close_redis()


# Interactive API docs are disabled in production-like environments so the
# schema/endpoints are not publicly enumerable; kept enabled in dev.
_docs_enabled = not settings.is_production_like()

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
instrument_fastapi(app)
register_exception_handlers(app)

# Middleware ordering note: add_middleware() PREPENDS, so the LAST middleware
# registered is the OUTERMOST one at request time. CORSMiddleware must therefore
# be registered LAST (see below) so that it wraps every middleware that can
# short-circuit a request (429/413/504) and those error responses still carry
# access-control-* headers — otherwise the browser only sees an opaque
# "Failed to fetch". Do not move the CORS block back up here.
#
# Consequence of CORS being outermost: it answers OPTIONS preflights itself and
# short-circuits them, so preflights never reach rate limiting, tenant
# resolution or request-context. That is deliberate — a preflight touches no DB
# and carries no credentials, and browsers cache it (Access-Control-Max-Age), so
# there is nothing worth metering or tenant-scoping. The trade-off is accepted
# in exchange for real error responses (429/413/504) being readable by the
# browser.

# Compress responses. Registered FIRST, so it is the INNERMOST middleware: it
# only sees bodies produced by the router, which is what we want — short-circuit
# responses from the middlewares below (429/413/504) and the access-control-*
# headers added by CORS above stay uncompressed and untouched.
app.add_middleware(GZipMiddleware, minimum_size=settings.GZIP_MIN_SIZE)

# Baseline security headers on every response (does not affect CORS/JSON).
app.add_middleware(SecurityHeadersMiddleware)

# Reject oversized bodies (413) and time out slow requests (504).
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
app.add_middleware(TimeoutMiddleware, timeout_seconds=settings.REQUEST_TIMEOUT_SECONDS)

if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimitMiddleware,
        calls_per_minute=settings.RATE_LIMIT_CALLS_PER_MINUTE,
        calls_per_hour=settings.RATE_LIMIT_CALLS_PER_HOUR,
    )
    app.add_middleware(APIKeyRateLimitMiddleware)

# Resolve white-label tenant from Host / X-Tenant-Slug (Feature 85)
app.add_middleware(TenantMiddleware)
app.add_middleware(RequestContextMiddleware)

# Configure CORS. Registered LAST so it is the OUTERMOST middleware and every
# short-circuited response above (rate limit 429, body size 413, timeout 504)
# gets access-control-* headers.
# effective_cors_origins() strips localhost/127.0.0.1 in production-like envs so
# credentialed requests are only allowed from real deployed origins (CONFIG-002).
_cors_origins = settings.effective_cors_origins()
# allow_credentials=True must never be paired with a wildcard origin.
_allow_credentials = "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-Device-Fingerprint", "X-Tenant-Slug", "traceparent", "tracestate"],
    # Without expose_headers the browser hides every non-CORS-safelisted response
    # header from JS, so the Retry-After on a 429 would be unreadable and the
    # header-carrying fix above pointless. X-Request-ID (set by
    # RequestContextMiddleware on every response) is exposed so clients can quote
    # it in bug reports.
    expose_headers=["Retry-After", "X-Request-ID"],
)

# Include routes
app.include_router(router)


def main():
    """Application entry point."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )


if __name__ == "__main__":
    main()

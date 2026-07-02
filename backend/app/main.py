"""
FastAPI application main module.
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import _check_cors_origins_on_startup, router
from .core.config import settings
from .core.event_bus import event_bus
from .core.logging import get_logger, setup_logging
from .core.redis import get_redis_client, redis_manager
from .core.tracing import instrument_fastapi, setup_telemetry
from .database.connection import close_db, init_db
from .middleware.rate_limiting import APIKeyRateLimitMiddleware, RateLimitMiddleware
from .middleware.request_context import RequestContextMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tenant_middleware import TenantMiddleware
from .services.latex_compiler import latex_compiler

# Setup logging
setup_logging()
setup_telemetry("api")
logger = get_logger(__name__)


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

    yield

    # Shutdown
    logger.info("Latexy Backend shutting down...")
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

# Configure CORS.
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
)

# Baseline security headers on every response (does not affect CORS/JSON).
app.add_middleware(SecurityHeadersMiddleware)

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
